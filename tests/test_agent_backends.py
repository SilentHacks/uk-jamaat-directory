from __future__ import annotations

import pytest

from uk_jamaat_directory.config import Settings
from uk_jamaat_directory.ingest.authoring.backends import (
    AGENT_BACKENDS,
    AgentNotInstalledError,
    ClaudeCodeBackend,
    KiroCliBackend,
    OpenCodeBackend,
    PiBackend,
    UnknownAgentBackendError,
    get_agent_backend,
)


def _settings(**overrides) -> Settings:
    return Settings(_env_file=None, **overrides)


def test_default_backend_is_opencode() -> None:
    backend = get_agent_backend(_settings())
    assert isinstance(backend, OpenCodeBackend)


def test_claude_code_backend_selectable() -> None:
    backend = get_agent_backend(_settings(ai_agent_backend="claude_code"))
    assert isinstance(backend, ClaudeCodeBackend)


def test_unknown_backend_raises() -> None:
    with pytest.raises(UnknownAgentBackendError, match="cursor"):
        get_agent_backend(_settings(ai_agent_backend="cursor"))


def test_opencode_passes_prompt_on_stdin_not_argv() -> None:
    # The prompt is piped on stdin, so it must never appear in argv (no
    # quoting/escaping of the prompt body).
    argv = OpenCodeBackend().build_argv(
        bin_path="/usr/bin/opencode", model="opencode-go/deepseek-v4-flash", prompt="PROMPT"
    )
    assert OpenCodeBackend.prompt_via_stdin is True
    assert "PROMPT" not in argv
    assert argv == [
        "/usr/bin/opencode",
        "-m",
        "opencode-go/deepseek-v4-flash",
        "run",
        "--format",
        "json",
    ]


def test_opencode_argv_with_agent_name() -> None:
    argv = OpenCodeBackend().build_argv(
        bin_path="/usr/bin/opencode",
        model="opencode-go/deepseek-v4-flash",
        prompt="PROMPT",
        agent_name="default",
    )
    assert "PROMPT" not in argv
    assert argv == [
        "/usr/bin/opencode",
        "-m",
        "opencode-go/deepseek-v4-flash",
        "run",
        "--format",
        "json",
        "--agent",
        "default",
    ]


def test_claude_code_argv_uses_headless_flags() -> None:
    backend = ClaudeCodeBackend()
    argv = backend.build_argv(
        bin_path="/usr/bin/claude", model="claude-haiku-4-5-20251001", prompt="PROMPT"
    )
    assert argv[:3] == ["/usr/bin/claude", "-p", "PROMPT"]
    assert argv[argv.index("--model") + 1] == "claude-haiku-4-5-20251001"
    assert argv[argv.index("--permission-mode") + 1] == "bypassPermissions"
    assert argv[argv.index("--output-format") + 1] == "json"


def test_pi_argv_disables_skills_and_context_files() -> None:
    argv = PiBackend().build_argv(
        bin_path="/usr/bin/pi", model="anthropic/claude-haiku-4-5-20251001", prompt="PROMPT"
    )
    assert "--no-skills" in argv
    assert "--no-context-files" in argv
    assert argv[:6] == [
        "/usr/bin/pi",
        "--model",
        "anthropic/claude-haiku-4-5-20251001",
        "-p",
        "PROMPT",
        "--mode",
    ]


def test_kiro_cli_argv_uses_headless_flags() -> None:
    argv = KiroCliBackend().build_argv(
        bin_path="/usr/bin/kiro-cli", model="claude-sonnet-4-20250514", prompt="PROMPT"
    )
    assert argv == [
        "/usr/bin/kiro-cli",
        "chat",
        "--no-interactive",
        "--trust-all-tools",
        "PROMPT",
    ]


def test_kiro_cli_argv_with_agent_name() -> None:
    argv = KiroCliBackend().build_argv(
        bin_path="/usr/bin/kiro-cli",
        model="claude-sonnet-4-20250514",
        prompt="PROMPT",
        agent_name="my-agent",
    )
    assert argv == [
        "/usr/bin/kiro-cli",
        "chat",
        "--no-interactive",
        "--trust-all-tools",
        "--agent",
        "my-agent",
        "PROMPT",
    ]


def test_kiro_cli_backend_selectable() -> None:
    backend = get_agent_backend(_settings(ai_agent_backend="kiro-cli"))
    assert isinstance(backend, KiroCliBackend)


def test_only_opencode_uses_stdin() -> None:
    assert OpenCodeBackend.prompt_via_stdin is True
    assert PiBackend.prompt_via_stdin is False
    assert ClaudeCodeBackend.prompt_via_stdin is False
    assert KiroCliBackend.prompt_via_stdin is False


def test_backend_default_models() -> None:
    settings = _settings()
    assert OpenCodeBackend().resolve_model(settings) == "opencode-go/deepseek-v4-flash"
    assert ClaudeCodeBackend().resolve_model(settings) == "claude-haiku-4-5-20251001"
    assert KiroCliBackend().resolve_model(settings) == "claude-sonnet-4-20250514"


def test_explicit_model_overrides_backend_default() -> None:
    settings = _settings(ai_agent_model="claude-sonnet-4-6")
    assert ClaudeCodeBackend().resolve_model(settings) == "claude-sonnet-4-6"


def test_agent_name_resolved_from_settings() -> None:
    settings = _settings(ai_agent_name="default")
    assert OpenCodeBackend().resolve_agent_name(settings) == "default"


def test_agent_name_defaults_to_none() -> None:
    settings = _settings()
    assert OpenCodeBackend().resolve_agent_name(settings) is None


def test_opencode_env_maps_openai_variables() -> None:
    env: dict[str, str] = {}
    OpenCodeBackend().apply_env(env, _settings(ai_agent_api_key="k", ai_agent_base_url="http://b"))
    assert env == {"OPENAI_API_KEY": "k", "OPENAI_BASE_URL": "http://b"}


def test_claude_code_env_maps_anthropic_variables() -> None:
    env: dict[str, str] = {}
    ClaudeCodeBackend().apply_env(
        env, _settings(ai_agent_api_key="k", ai_agent_base_url="http://b")
    )
    assert env == {"ANTHROPIC_API_KEY": "k", "ANTHROPIC_BASE_URL": "http://b"}


def test_apply_env_does_not_override_explicit_exports() -> None:
    env = {"ANTHROPIC_API_KEY": "explicit"}
    ClaudeCodeBackend().apply_env(env, _settings(ai_agent_api_key="from-settings"))
    assert env["ANTHROPIC_API_KEY"] == "explicit"


def test_describe_never_contains_prompt_body() -> None:
    secret_prompt = "VERY-SECRET-PROMPT-BODY"
    for backend_cls in AGENT_BACKENDS.values():
        described = backend_cls().describe(model="m", prompt=secret_prompt)
        assert secret_prompt not in described
        assert f"<prompt:{len(secret_prompt)} chars>" in described


def test_resolve_binary_raises_when_missing(monkeypatch) -> None:
    monkeypatch.setattr("shutil.which", lambda _: None)
    with pytest.raises(AgentNotInstalledError, match="claude"):
        ClaudeCodeBackend().resolve_binary()
