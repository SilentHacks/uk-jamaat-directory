# Implementation Plan: Extractor Review Dashboard

This document details the complete design, routing structure, database logic, and frontend layout to implement the manual **Extractor Review Dashboard** under the `/admin` web interface.

---

## 1. Design & Architectural Evaluations

During planning, the following design trade-offs were evaluated:

### Evaluation A: Data Model for Flagging Scrapers
*   **Option 1: Mosque Status flag (`Mosque.status = MosqueStatus.NEEDS_REVIEW`)**
    *   *Pros:* Reuses an existing enum state.
    *   *Cons:* Mosque status affects discovery matching and public directory inclusion. A broken scraper script is an operational crawler concern, not a physical mosque identity concern (e.g. coordinates/duplicate issues).
*   **Option 2: Source Health Status flag (`SourceHealth.freshness_status = FreshnessStatus.NEEDS_REVIEW`)**
    *   *Pros:* Fits under the "health/coverage" domain.
    *   *Cons:* `SourceHealth` is automatically recomputed and overwritten by the daily scheduling/freshness cron jobs. Manual flags would get wiped out.
*   **Option 3: Assignment Metadata JSON (`SourceExtractorAssignment.metadata`)**
    *   *Pros:* The `SourceExtractorAssignment` table contains a standard JSONB `metadata` column. We can store key-value pairs like `{"needs_attention": true, "attention_notes": "Extracts adhan instead of jamaat time", "attention_updated_at": "..."}` without running Alembic schema migrations. It isolates parser errors from physical mosque details and remains persistent.
    *   *Cons:* Requires serializing/deserializing the dictionary (handled cleanly by SQLAlchemy's `JSONB` type).
    *   *Selection:* **Option 3 (Assignment Metadata JSON)**. This is clean, local to the scraper logic, and does not require database migration overhead.

### Evaluation B: Timetable Preview Strategy
*   **Option 1: Execute live HTTP web fetches during page previews**
    *   *Pros:* Inspects the absolute latest code/website status.
    *   *Cons:* Too slow (Playwright calls can take up to 30 seconds), blocks network resources, and risks rate-limiting/throttling.
*   **Option 2: Run dry-run sandboxed extraction against the *last successfully crawled artifact***
    *   *Pros:* Extremely fast (<500ms) since the artifact body is fetched directly from local S3/MinIO storage.
    *   *Cons:* May show timings from the last crawl run instead of the exact live website state.
    *   *Selection:* **Option 2 (Last Crawled Artifact)** as the default for clicking "Preview". We will also provide a secondary **"Recrawl & Test"** button that dispatches a Celery crawler task in the background for live testing.

### Evaluation C: User Interface Layout
*   **Option 1: Embed the listing directly into the existing `/admin/pipeline` page**
    *   *Pros:* Keeps all pipeline data on one page.
    *   *Cons:* The pipeline page is already dense. Loading 450+ assignments with search, filtering, and preview drawers would degrade performance.
*   **Option 2: A dedicated navigation tab at `/admin/extractors`**
    *   *Pros:* Dedicated page allows comprehensive filtering (by run frequency, attention status, sync status), clean search, and scroll-preservation when viewing previews.
    *   *Selection:* **Option 2 (Dedicated Navigation Tab)**.

---

## 2. URL & Route Mappings

We will introduce a new admin router [extractors.py](file:///home/codex-dev/work/uk-jamaat-directory/src/uk_jamaat_directory/ui/admin/extractors.py) containing:

| Method | Route | Description |
| :--- | :--- | :--- |
| `GET` | `/admin/extractors` | Lists assignments, showing Mosque name, Website link, Run Frequency, Attention status. Supports search, status filtering, and pagination. |
| `POST` | `/admin/extractors/{source_id}/preview` | Runs a DB-free sandboxed extraction against the last artifact and renders the HTML timetable snippet. |
| `POST` | `/admin/extractors/{source_id}/attention` | Sets/unsets `needs_attention` and updates `review_notes` in `SourceExtractorAssignment.metadata`. |
| `POST` | `/admin/extractors/{source_id}/recrawl` | Dispatches the Celery crawl worker `process_source_task` to refresh raw source data. |

---

## 3. Database & Helper Logic

### A. Updating the Metadata Flag
```python
async def flag_assignment_for_attention(
    session: AsyncSession,
    source_id: uuid.UUID,
    needs_attention: bool,
    notes: str | None,
) -> None:
    assignment = await session.get(SourceExtractorAssignment, source_id)
    if not assignment:
        raise ValueError("Assignment not found")
        
    meta = dict(assignment.metadata_ or {})
    if needs_attention:
        meta["needs_attention"] = True
        meta["attention_notes"] = notes.strip() if notes else ""
        meta["attention_updated_at"] = datetime.now(UTC).isoformat()
    else:
        meta.pop("needs_attention", None)
        meta.pop("attention_notes", None)
        meta.pop("attention_updated_at", None)
        
    assignment.metadata_ = meta
    await session.flush()
```

### B. Dry-running Sandbox Extraction from an Artifact
Using existing helper logic from [smoke_test.py](file:///home/codex-dev/work/uk-jamaat-directory/src/uk_jamaat_directory/ingest/authoring/smoke_test.py) and [runner.py](file:///home/codex-dev/work/uk-jamaat-directory/src/uk_jamaat_directory/ingest/extract/repo_extractors/runner.py):
```python
async def preview_extracted_timetable(
    session: AsyncSession,
    source: MosqueSource,
    settings: Settings,
) -> ExtractorResult:
    # 1. Fetch the latest successfully retrieved artifact from the database
    stmt = (
        select(SourceArtifact)
        .where(SourceArtifact.source_id == source.id)
        .order_by(SourceArtifact.created_at.desc())
        .limit(1)
    )
    artifact = (await session.execute(stmt)).scalar_one_or_none()
    if not artifact:
        raise ValueError("No stored artifacts found for this source. Please crawl first.")

    # 2. Get artifact bytes from MinIO/S3
    storage = S3Storage(settings)
    body = await storage.get_bytes(artifact.object_key)

    # 3. Retrieve the matching extractor key
    assignment = await session.get(SourceExtractorAssignment, source.id)
    if not assignment:
        raise ValueError("No extractor assigned to this source")

    # 4. Construct Sandbox Payload
    ext_artifact = ExtractorArtifact(
        target_label="timetable",
        target_url=source.source_url,
        content_type=artifact.content_type,
        body=body,
    )
    payload = build_sandbox_payload(
        extractor_key=assignment.extractor_key,
        source_id=str(source.id),
        mosque_name=source.display_name or "Unknown Mosque",
        mosque_id=str(source.mosque_id) if source.mosque_id else None,
        source_url=source.source_url,
        timezone=assignment.run_timezone,
        artifacts={"timetable": ext_artifact},
    )

    # 5. Execute sandbox dry-run
    sandbox = await run_sandbox(assignment.extractor_key, payload, settings=settings)
    if not sandbox.ok or sandbox.result is None:
        raise ValueError(sandbox.error or "Sandbox execution failed")
    
    return sandbox.result
```

---

## 4. UI Elements & Templates

### A. Navigation Link
Modify [admin_base.html](file:///home/codex-dev/work/uk-jamaat-directory/src/uk_jamaat_directory/ui/templates/admin/admin_base.html):
```html
<nav class="admin-nav">
  <a href="/admin">Dashboard</a>
  <a href="/admin/mosques">Mosques</a>
  <a href="/admin/candidates">Schedules</a>
  <a href="/admin/pipeline">Pipeline</a>
  <a href="/admin/extractors">Extractors</a> <!-- Add this line -->
  ...
</nav>
```

### B. List Template (`extractors.html`)
The table layout includes dynamic HTMX selectors. When the user clicks the row action, it expands the collapsible detail drawer inline.

```html
{% extends "admin/admin_base.html" %}
{% block title %}Extractors — Admin{% endblock %}

{% block admin %}
<h1>Extractor Review Dashboard</h1>

<!-- Filters and Search panel -->
<div class="panel">
  <form method="get" action="/admin/extractors" class="filter-form">
    <input type="text" name="q" value="{{ q }}" placeholder="Search mosque or domain..." />
    <select name="status">
      <option value="">All Statuses</option>
      <option value="active" {% if status_filter == 'active' %}selected{% endif %}>Active</option>
      <option value="needs_attention" {% if status_filter == 'needs_attention' %}selected{% endif %}>Needs Attention</option>
      <option value="missing_script" {% if status_filter == 'missing_script' %}selected{% endif %}>Missing Script</option>
    </select>
    <select name="frequency">
      <option value="">All Frequencies</option>
      <option value="daily" {% if freq_filter == 'daily' %}selected{% endif %}>Daily</option>
      <option value="weekly" {% if freq_filter == 'weekly' %}selected{% endif %}>Weekly</option>
      <option value="monthly" {% if freq_filter == 'monthly' %}selected{% endif %}>Monthly</option>
    </select>
    <button type="submit" class="btn">Filter</button>
  </form>
</div>

<!-- Table listing -->
<table class="data">
  <thead>
    <tr>
      <th>Mosque & Website</th>
      <th>Extractor Key</th>
      <th>Frequency</th>
      <th>Status</th>
      <th>Actions</th>
    </tr>
  </thead>
  <tbody>
    {% for row in rows %}
    {% set assignment = row.Assignment %}
    {% set source = row.Source %}
    {% set mosque = row.Mosque %}
    {% set needs_attention = assignment.metadata_.get('needs_attention', False) %}
    <tr id="row-{{ source.id }}">
      <td>
        <strong><a href="/admin/mosques/{{ source.mosque_id }}">{{ mosque.name }}</a></strong>
        <br />
        <a href="{{ source.source_url }}" target="_blank" class="muted small">{{ source.source_url | truncate(50) }}</a>
      </td>
      <td><code>{{ assignment.extractor_key }}</code> <small class="muted">v{{ assignment.extractor_version }}</small></td>
      <td><span class="badge">{{ assignment.run_frequency }}</span></td>
      <td>
        {% if needs_attention %}
          <span class="badge status-duplicate" style="border-color: var(--danger); color: var(--danger)">Attention Needed</span>
        {% else %}
          <span class="badge status-active">{{ assignment.status }}</span>
        {% endif %}
      </td>
      <td>
        <button class="btn small" 
                hx-post="/admin/extractors/{{ source.id }}/preview" 
                hx-target="#detail-{{ source.id }}" 
                hx-swap="innerHTML"
                onclick="document.getElementById('drawer-{{ source.id }}').style.display = 'table-row'">
          Preview
        </button>
      </td>
    </tr>
    <!-- Collapsible drawer for inline previews -->
    <tr id="drawer-{{ source.id }}" class="detail-drawer" style="display:none; background: var(--panel);">
      <td colspan="5">
        <div id="detail-{{ source.id }}" class="detail-container">
          <div class="muted">Loading preview sandbox...</div>
        </div>
      </td>
    </tr>
    {% else %}
    <tr><td colspan="5" class="muted">No extractor assignments matched.</td></tr>
    {% endfor %}
  </tbody>
</table>

<!-- Pagination -->
<div class="pager">
  {% if prev_offset is not none %}<a class="btn" href="/admin/extractors?offset={{ prev_offset }}">← Prev</a>{% endif %}
  {% if next_offset is not none %}<a class="btn" href="/admin/extractors?offset={{ next_offset }}">Next →</a>{% endif %}
</div>
{% endblock %}
```

### C. Collapsible Drawer Preview Template (`extractor_preview.html`)
This is returned dynamically by HTMX to populate the collapsible drawer. It shows the dry-run output and the review notes input panel.

```html
<div style="display: flex; gap: 20px; flex-wrap: wrap;">
  
  <!-- Extracted timings grid -->
  <div style="flex: 2; min-width: 300px;">
    <h4>Extracted Timetable Preview</h4>
    {% if preview.rows %}
      <table class="data small">
        <thead>
          <tr><th>Date</th><th>Prayer</th><th>Start (Adhan)</th><th>Jamaat (Congregation)</th></tr>
        </thead>
        <tbody>
          {% for row in preview.rows %}
            <tr>
              <td>{{ row.date }}</td>
              <td>{{ row.prayer.value }}</td>
              <td>{{ row.start_time or '—' }}</td>
              <td><strong>{{ row.jamaat_time }}</strong></td>
            </tr>
          {% endfor %}
        </tbody>
      </table>
    {% else %}
      <div class="flash err">No rows extracted. Reason: {{ preview.no_schedule_reason or 'None' }}</div>
    {% endif %}
    
    {% if preview.warnings %}
      <div class="legend" style="color: var(--danger)">
        <strong>Warnings:</strong>
        <ul>
          {% for w in preview.warnings %}
            <li>{{ w.message }}</li>
          {% endfor %}
        </ul>
      </div>
    {% endif %}
  </div>

  <!-- Review Panel (Flag Attention) -->
  <div class="panel" style="flex: 1; min-width: 250px; margin: 0; background: var(--panel); border-color: var(--border);">
    <h4>Moderation Flags</h4>
    
    <form hx-post="/admin/extractors/{{ source_id }}/attention" hx-target="#row-{{ source_id }}" hx-swap="outerHTML">
      <input type="hidden" name="csrf_token" value="{{ csrf_token }}" />
      
      <label style="display: block; margin-bottom: 8px;">
        <input type="checkbox" name="needs_attention" value="true" {% if needs_attention %}checked{% endif %} />
        <strong>Requires Attention</strong>
      </label>
      
      <textarea name="notes" placeholder="Why does this need attention? (e.g. missing prayers, incorrect adhan times)" style="width: 100%; height: 80px; margin-bottom: 10px;">{{ notes }}</textarea>
      
      <div style="display: flex; gap: 8px;">
        <button type="submit" class="btn small primary">Save Notes</button>
        <button type="button" class="btn small" onclick="document.getElementById('drawer-{{ source_id }}').style.display='none'">Close</button>
      </div>
    </form>
    
    <hr style="margin: 15px 0; border: 0; border-top: 1px solid var(--border);" />
    
    <!-- Recrawl action -->
    <form hx-post="/admin/extractors/{{ source_id }}/recrawl" hx-swap="none">
      <input type="hidden" name="csrf_token" value="{{ csrf_token }}" />
      <button type="submit" class="btn small danger">Force Recrawl &amp; Process</button>
    </form>
  </div>
  
</div>
```

---

## 5. Verification Checklist

To verify the dashboard behaves as expected once implemented, perform these steps:
1.  Run `make test` to ensure existing regression tests pass.
2.  Launch the development stack with `make dev` and log in to the admin panel using `ADMIN_API_KEY`.
3.  Navigate to the `/admin/extractors` URL, verifying that all assignments and frequencies load correctly.
4.  Type a mosque name in the filter input to test the search query pipeline.
5.  Click the **Preview** button for a source:
    *   Verify the drawer expands and shows the dry-run timetable.
    *   Check that warnings or errors are cleanly displayed.
6.  Toggle the **Requires Attention** checkbox, type a note, and press **Save Notes**:
    *   Verify the table row updates dynamically via HTMX.
    *   Confirm the row badge changes to "Attention Needed" in red.
    *   Refresh the page to ensure the flag persists in the database's `SourceExtractorAssignment.metadata` column.
