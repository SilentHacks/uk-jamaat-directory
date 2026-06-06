# pytest-xdist Parallelisation Report

## Executive Summary

**pytest-xdist is not recommended for this codebase in its current state.**

The PostGIS integration tests fail under parallel execution because they share a single database, and even the fast unit-test suite runs slower with xdist due to worker startup overhead outweighing the gains.

---

## Tested Configurations

| Configuration | Result | Time | Notes |
|---|---|---|---|
| **Baseline (no xdist)** | 225 passed, 3 errors | ~23.5s | Clean rebuild; occasional errors are pre-existing flaky tests |
| **Non-DB tests, `-n auto`** | 130 passed, 98 skipped | **7.2s** | **Slower** than single-process (~3.5s) |
| **PostGIS tests, `-n 2`** | 10–13 failed, 210 passed | ~17.5s | Shared DB state collisions |
| **PostGIS tests, `-n 2 --dist=loadscope`** | 13 failed, 5 errors | ~20.5s | Same issue; module grouping doesn't help |
| **PostGIS tests, `-n 1`** | 6 failed, 1 error | ~31.8s | xdist changes test ordering, exposing ordering-dependent mutable state |

---

## Root Causes of Failure

### 1. Shared Database State (PostGIS tests)

All workers connect to the **same** `directory_test` database. Our cleanup strategy (`DELETE` per test in topological order) is not process-safe:

- **Worker A** inserts a `Mosque` and commits.
- **Worker B** runs `DELETE FROM mosques` as part of its fixture teardown.
- **Worker A's next assertion** fails because its row vanished.

This is the dominant failure mode.

### 2. Mutable Module-Level Caches (All tests)

Several modules maintain global in-memory state that is not reset between processes:

| Module | State | Reset mechanism |
|---|---|---|
| `ingest.fetch.throttle` | `_domain_last_fetch` dict | `clear_domain_throttle()` (fixture `autouse`) |
| `ingest.fetch.robots` | robots.txt cache | `clear_robots_cache()` (fixture `autouse`) |
| `ingest.discovery.websites.search.cache` | `SearchCache` on disk | None — file-level state |

These are fine in a single process because `autouse` fixtures clear them, but under xdist the fixtures run in *different* processes, so state set by one worker pollutes another.

### 3. Test Ordering Dependencies

Even with `-n 1` (single worker, but xdist's test collector/distributor), the test order changes. This exposes latent ordering bugs where tests depend on module-level state left behind by earlier tests.

---

## Why Non-DB Tests Are Also Slower

The non-DB suite completes in ~3.5s with 130 tests. xdist worker startup/teardown dominates:

```
-n auto:  7.2s  (2× slower)
-n 2:     ~5s   (still slower)
-n 4:     ~6s   (no benefit)
```

The tests are **too fast individually** (many < 0.01s) for process-level parallelism to pay off.

---

## What Would Be Needed to Make xdist Work

| Change | Effort | Benefit |
|---|---|---|
| **Separate DB per worker** (e.g., `directory_test_{gw}`) | Medium | Eliminates shared DB collisions; requires dynamic DB naming in fixtures and bootstrap |
| **Switch to transaction rollback** (savepoint + rollback after each test) | High | Faster than DELETE and naturally isolated per connection; but breaks tests that call `session.commit()` |
| **Replace all module-level mutable caches** with dependency-injected state | High | Removes hidden shared state; significant refactoring |
| **Add `pytest-xdist` to dev dependencies** | Trivial | Only useful after above changes |

### Separate DB per worker — rough sketch

```python
# conftest.py
import os
import getpass

def get_test_database_url() -> str:
    base = os.environ.get("TEST_DATABASE_URL", DEFAULT_TEST_DATABASE_URL)
    worker_id = os.environ.get("PYTEST_XDIST_WORKER", "master")
    if worker_id != "master":
        base = base.replace("directory_test", f"directory_test_{worker_id}")
    return base
```

Then in `postgres_schema_ready`, each worker bootstraps its own database. This is the most viable path, but would add ~5s of schema bootstrap per worker, which for a 20s suite may not be worth it.

---

## Recommendations

1. **Do NOT add pytest-xdist now.** The failure rate is high and the speedup (even if fixed) would be marginal given the current ~22s run time.

2. **If the suite grows to 500+ tests or >60s**, revisit by:
   - Implementing per-worker test databases (see sketch above).
   - Auditing and removing all module-level mutable caches.

3. **Immediate wins already achieved** (in this branch):
   - ~4× speedup from fast `DELETE` cleanup.
   - ~18s saved from configurable ExaClient backoff.
   - ~6s saved from zeroing fetch throttle delays in tests.
   - Cleaned up `RuntimeWarning` and `DeprecationWarning` noise.

---

## Appendix: Raw Commands

```bash
# Baseline
UK_JAMAAT_TEST_POSTGRES=1 make test-postgres          # ~23s

# xdist attempts (all show failures)
UK_JAMAAT_TEST_POSTGRES=1 pytest -n 2 tests/          # 10-13 failures
UK_JAMAAT_TEST_POSTGRES=1 pytest -n 2 --dist=loadscope tests/  # 13 failures
UK_JAMAAT_TEST_POSTGRES=1 pytest -n 1 tests/          # 6 failures (ordering)

# Non-DB tests (slower with xdist)
pytest -n auto tests/                                  # 7.2s vs 3.5s
```

---

*Conclusion: xdist is a future optimisation for when the suite is much larger. The current ~22s PostGIS run is already healthy and does not justify the infrastructure investment required for safe parallelisation.*
