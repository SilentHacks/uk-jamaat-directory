"""Pluggable coding-agent CLI backends for the authoring orchestrator.

The orchestrator is agent-agnostic: it builds a prompt, runs one agent
subprocess in the repo root, and reads the JSON result file the agent is
instructed to write. Everything CLI-specific — binary name, argv shape,
model selection, credential environment variables — lives in an
:class:`AgentBackend`.

Adding a backend: subclass :class:`AgentBackend`, fill in the class
attributes, implement :meth:`build_argv` (and :meth:`apply_env` if the CLI
needs credentials), and register it in :data:`AGENT_BACKENDS`. Select it
with the ``AI_AGENT_BACKEND`` setting.
"""

from __future__ import annotations

import shutil
from abc import ABC, abstractmethod
from typing import ClassVar

from uk_jamaat_directory.config import Settings


class AgentNotInstalledError(RuntimeError):
    """Raised when the selected agent's binary is not on ``PATH``."""


class UnknownAgentBackendError(ValueError):
    """Raised when ``ai_agent_backend`` names no registered backend."""


class AgentBackend(ABC):
    """One way of launching a coding agent as a one-shot subprocess."""

    #: registry key, used as the ``ai_agent_backend`` setting value
    name: ClassVar[str]
    #: executable looked up on PATH
    binary: ClassVar[str]
    #: model used when ``ai_agent_model`` is unset
    default_model: ClassVar[str]
    #: when True, the prompt is delivered on the subprocess's stdin instead of
    #: as an argv element, so nothing quotes or escapes the prompt body
    prompt_via_stdin: ClassVar[bool] = False

    def is_available(self) -> bool:
        return shutil.which(self.binary) is not None

    def resolve_binary(self) -> str:
        path = shutil.which(self.binary)
        if not path:
            msg = (
                f"agent binary {self.binary!r} (backend {self.name!r}) not found "
                f"on PATH. Install it or select another AI_AGENT_BACKEND."
            )
            raise AgentNotInstalledError(msg)
        return path

    def resolve_model(self, settings: Settings) -> str:
        return settings.ai_agent_model or self.default_model

    def resolve_agent_name(self, settings: Settings) -> str | None:
        return settings.ai_agent_name

    @abstractmethod
    def build_argv(
        self,
        *,
        bin_path: str,
        model: str,
        prompt: str,
        agent_name: str | None = None,
    ) -> list[str]:
        """Return the full subprocess argv for one non-interactive run."""

    def apply_env(self, env: dict[str, str], settings: Settings) -> None:
        """Inject credentials/routing into the subprocess environment.

        Must use ``setdefault`` so explicitly exported variables win.
        Backends whose CLI handles its own auth need not override this.
        """
        return None

    def describe(self, *, model: str, prompt: str, agent_name: str | None = None) -> str:
        """Loggable command summary that never includes the prompt body."""
        argv = self.build_argv(bin_path=self.binary, model=model, prompt="", agent_name=agent_name)
        rendered = " ".join(part for part in argv if part)
        return f"{rendered} <prompt:{len(prompt)} chars>"


class OpenCodeBackend(AgentBackend):
    """OpenCode CLI: ``opencode -m <model> run --format json`` with the prompt
    piped on stdin.

    OpenCode's ``run`` reads the message from stdin when no positional
    ``message`` is given, so the prompt is passed verbatim — no argv quoting
    or backslash-escaping of nested quotes touches the prompt body.
    """

    name = "opencode"
    binary = "opencode"
    default_model = "opencode-go/deepseek-v4-flash"
    prompt_via_stdin = True

    def build_argv(
        self, *, bin_path: str, model: str, prompt: str, agent_name: str | None = None
    ) -> list[str]:
        argv = [bin_path, "-m", model, "run", "--format", "json"]
        if agent_name:
            argv.extend(["--agent", agent_name])
        return argv

    def apply_env(self, env: dict[str, str], settings: Settings) -> None:
        # OpenCode routes through OpenAI-compatible provider variables.
        if settings.ai_agent_api_key:
            env.setdefault("OPENAI_API_KEY", settings.ai_agent_api_key)
        if settings.ai_agent_base_url:
            env.setdefault("OPENAI_BASE_URL", settings.ai_agent_base_url)


class ClaudeCodeBackend(AgentBackend):
    """Claude Code headless mode (https://code.claude.com/docs/en/headless).

    ``claude -p <prompt> --model <model> --permission-mode bypassPermissions``
    runs one non-interactive session with all tool-permission prompts
    bypassed, which the orchestrator requires: there is no human attached to
    approve file writes or web fetches, and the authored script is gated
    afterwards by the static validator, smoke test, and semantic checks.
    """

    name = "claude_code"
    binary = "claude"
    default_model = "claude-haiku-4-5-20251001"

    def build_argv(
        self, *, bin_path: str, model: str, prompt: str, agent_name: str | None = None
    ) -> list[str]:
        return [
            bin_path,
            "-p",
            prompt,
            "--model",
            model,
            "--permission-mode",
            "bypassPermissions",
            "--output-format",
            "json",
        ]

    def apply_env(self, env: dict[str, str], settings: Settings) -> None:
        if settings.ai_agent_api_key:
            env.setdefault("ANTHROPIC_API_KEY", settings.ai_agent_api_key)
        if settings.ai_agent_base_url:
            env.setdefault("ANTHROPIC_BASE_URL", settings.ai_agent_base_url)


class PiBackend(AgentBackend):
    """Pi CLI non-interactive mode (https://pi.dev/docs/latest/usage).

    ``pi --model <model> -p <prompt> --mode json`` runs one non-interactive
    session (``-p``/``--print``), emitting all events as JSON lines
    (``--mode json``) for the orchestrator's diagnostics. The model pattern
    supports ``provider/id`` syntax, which also selects the provider.

    Pi resolves credentials from the provider-native environment variables
    (e.g. ``ANTHROPIC_API_KEY``, ``OPENAI_API_KEY``). The configured key is
    injected under both common names so the chosen provider finds it.
    """

    name = "pi"
    binary = "pi"
    default_model = "anthropic/claude-haiku-4-5-20251001"

    def build_argv(
        self, *, bin_path: str, model: str, prompt: str, agent_name: str | None = None
    ) -> list[str]:
        # ``--no-skills``/``--no-context-files`` keep the run focused on the
        # authoring prompt: no ambient AGENTS.md/CLAUDE.md or skill discovery.
        return [
            bin_path,
            "--model",
            model,
            "-p",
            prompt,
            "--mode",
            "json",
            "--no-skills",
            "--no-context-files",
        ]

    def apply_env(self, env: dict[str, str], settings: Settings) -> None:
        if settings.ai_agent_api_key:
            env.setdefault("ANTHROPIC_API_KEY", settings.ai_agent_api_key)
            env.setdefault("OPENAI_API_KEY", settings.ai_agent_api_key)
        if settings.ai_agent_base_url:
            env.setdefault("OPENAI_BASE_URL", settings.ai_agent_base_url)


AGENT_BACKENDS: dict[str, type[AgentBackend]] = {
    OpenCodeBackend.name: OpenCodeBackend,
    ClaudeCodeBackend.name: ClaudeCodeBackend,
    PiBackend.name: PiBackend,
}


def get_agent_backend(settings: Settings) -> AgentBackend:
    """Return the backend selected by ``settings.ai_agent_backend``."""
    name = settings.ai_agent_backend
    backend_cls = AGENT_BACKENDS.get(name)
    if backend_cls is None:
        msg = f"unknown agent backend {name!r}; available: {', '.join(sorted(AGENT_BACKENDS))}"
        raise UnknownAgentBackendError(msg)
    return backend_cls()
