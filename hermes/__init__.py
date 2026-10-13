"""Hermes provider plugin for the resident pi-claude-cli worker."""
from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

from providers import register_provider
from providers.base import ProviderProfile, OMIT_TEMPERATURE

from .client import HermesClaudeClient, to_transcript, validate_request
from .worker_location import default_worker_path, require_worker

PLUGIN_ROOT = Path(__file__).resolve().parent

DEFAULT_WORKER = default_worker_path(PLUGIN_ROOT)
class HermesClaudeProfile(ProviderProfile):
    """Claude Code login/API-key transport owned by this repository."""


    def create_client(self, **client_kwargs: Any) -> HermesClaudeClient:
        command = client_kwargs.get("command") or os.environ.get("PI_CLAUDE_HERMES_NODE") or shutil.which("node") or "node"
        worker = os.environ.get("PI_CLAUDE_HERMES_WORKER")
        supplied_args = client_kwargs.get("args")
        if worker:
            args = (worker,)
        elif isinstance(supplied_args, (tuple, list)):
            args = tuple(str(arg) for arg in supplied_args)
        else:
            args = (str(DEFAULT_WORKER),)
        if args == (str(DEFAULT_WORKER),):
            require_worker(DEFAULT_WORKER)
        return HermesClaudeClient(command=str(command), args=tuple(str(arg) for arg in args), client_kwargs=client_kwargs)


    def build_api_kwargs_extras(self, *, reasoning_config: dict | None = None, **_context: Any) -> tuple[dict, dict]:
        if reasoning_config and reasoning_config.get("enabled", True) and reasoning_config.get("effort") is not None:
            return {}, {"reasoning_effort": reasoning_config["effort"]}
        return {}, {}

    def discover_models(self, **_kwargs: Any) -> list[dict[str, str]]:
        return [{"id": model, "label": model, "note": "Claude model; availability depends on configured Claude driver"} for model in self.fallback_models]

    def fetch_models(self, *, api_key: str | None = None, base_url: str | None = None, timeout: float = 8.0) -> list[str]:
        del api_key, base_url, timeout
        return list(self.fallback_models)

    def get_model_context_length(self, model: str) -> int | None:
        del model
        return 200_000


profile = HermesClaudeProfile(
    name="pi-claude-cli",
    aliases=("claude-bridge",),
    display_name="Claude (pi-claude-cli bridge)",
    description="Claude Code CLI or official Agent SDK through the resident local bridge",
    signup_url="https://claude.ai/",
    auth_type="external_process",
    base_url="process://pi-claude-cli",
    fixed_temperature=OMIT_TEMPERATURE,
    unsupported_response_formats=("json_schema", "json_object"),
    supports_health_check=False,
    native_reasoning_details_type="pi-claude-cli.native_assistant",
    supports_model_listing=True,
    supports_vision=True,
    process_command="node",
    process_args=(str(DEFAULT_WORKER),),
    process_command_env_vars=("PI_CLAUDE_HERMES_NODE",),
    fallback_models=("opus", "sonnet", "haiku"),
    model_aliases={"sonnet": "sonnet", "haiku": "haiku", "opus": "opus"},
    default_aux_model="haiku",
    model_capabilities={
        "sonnet": {"supports_reasoning": True, "supports_vision": True, "supports_tools": True, "context_window": 200000, "model_family": "claude"},
        "haiku": {"supports_reasoning": True, "supports_vision": True, "supports_tools": True, "context_window": 200000, "model_family": "claude"},
        "opus": {"supports_reasoning": True, "supports_vision": True, "supports_tools": True, "context_window": 200000, "model_family": "claude"},
    },
)
register_provider(profile)
