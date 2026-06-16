from __future__ import annotations

import asyncio
import contextlib
import importlib
import json
import os
import re
import signal
from collections.abc import Iterable
from pathlib import Path
from typing import Any, Literal

PromptKey = Literal["user_prompt", "system_prompt"]
CLAUDE_TOOL_FLAGS = {
    "allowed_tools": "--allowedTools",
    "disallowed_tools": "--disallowedTools",
}
CLAUDE_KWARG_ENV_KEYS = {
    "max_thinking_tokens": "MAX_THINKING_TOKENS",
}


def resolve_import_path(import_path: str, **kwargs: Any) -> Any:
    if ":" not in import_path:
        raise ValueError(
            f"Import path must be in format 'module.path:name': {import_path}"
        )

    module_path, attr_name = import_path.split(":", 1)
    module = importlib.import_module(module_path)
    value = getattr(module, attr_name)
    return value(**kwargs) if callable(value) else value


def build_prompt_template(
    prompt_path: str,
    *,
    key: PromptKey,
    **kwargs: Any,
) -> str:
    prompt_bundle = resolve_import_path(prompt_path, key=key, **kwargs)
    if not isinstance(prompt_bundle, dict):
        raise TypeError("Prompt builder must return a mapping.")

    value = prompt_bundle[key]

    if not isinstance(value, str):
        raise TypeError(f"Prompt builder must return a string for {key}.")
    return value


def _get_claude_env(env_config: dict[str, Any], key: str) -> str | None:
    if key in env_config:
        value = env_config[key]
        return None if value is None else str(value)
    return os.environ.get(key)


def _get_claude_env_or(env_config: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = _get_claude_env(env_config, key)
        if value:
            return value
    return None


def build_claude_env(
    *,
    model_name: str,
    env_config: dict[str, Any],
    claude_config_dir: Path | str,
) -> dict[str, str]:
    path = _get_claude_env(env_config, "PATH") or os.environ.get("PATH", "")
    local_bin = str(Path.home() / ".local" / "bin")
    env: dict[str, str] = {
        "FORCE_AUTO_BACKGROUND_TASKS": "1",
        "ENABLE_BACKGROUND_TASKS": "1",
        "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
        "IS_SANDBOX": "1",
        "PATH": f"{local_bin}:{path}" if path else local_bin,
    }

    anthropic_base_url = _get_claude_env(env_config, "ANTHROPIC_BASE_URL")
    if anthropic_base_url:
        env["ANTHROPIC_BASE_URL"] = anthropic_base_url

    anthropic_auth_token = _get_claude_env(env_config, "ANTHROPIC_AUTH_TOKEN")
    if anthropic_auth_token:
        env["ANTHROPIC_AUTH_TOKEN"] = anthropic_auth_token

    anthropic_api_key = _get_claude_env_or(
        env_config,
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_AUTH_TOKEN",
    )
    if anthropic_api_key:
        env["ANTHROPIC_API_KEY"] = anthropic_api_key

    if "ANTHROPIC_BASE_URL" in env:
        env["ANTHROPIC_MODEL"] = model_name
    else:
        env["ANTHROPIC_MODEL"] = model_name.split("/")[-1]

    for key, value in env_config.items():
        if value is not None and (key == "ANTHROPIC_MODEL" or "MODEL" not in key):
            env.setdefault(key, str(value))
    env["CLAUDE_CONFIG_DIR"] = str(claude_config_dir)
    return env


def build_claude_agent_env_config(
    *,
    env_config: dict[str, Any] | None = None,
    agent_env: dict[str, Any] | None = None,
    agent_kwargs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    if env_config:
        merged.update(env_config)
    if agent_env:
        merged.update(agent_env)
    if agent_kwargs:
        for kwarg_key, env_key in CLAUDE_KWARG_ENV_KEYS.items():
            if kwarg_key in agent_kwargs:
                merged[env_key] = agent_kwargs[kwarg_key]
    return merged


def _strip_cli_quotes(value: Any) -> str:
    text = str(value)
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {"'", '"'}:
        return text[1:-1]
    return text


def build_claude_tool_args(tool_kwargs: dict[str, Any]) -> list[str]:
    args: list[str] = []
    for key, flag in CLAUDE_TOOL_FLAGS.items():
        if key in tool_kwargs:
            args.extend([flag, _strip_cli_quotes(tool_kwargs[key])])
    return args


async def run_command(
    args: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
    stdin_text: str | None = None,
    log_path: Path,
    timeout_sec: float | None = None,
) -> None:
    merged_env = os.environ.copy()
    if env is not None:
        merged_env.update(env)

    log_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        process = await asyncio.create_subprocess_exec(
            *args,
            cwd=str(cwd),
            env=merged_env,
            stdin=asyncio.subprocess.PIPE if stdin_text is not None else None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            start_new_session=True,
        )
    except OSError as exc:
        log_path.write_text(f"[command failed to start] {exc}\n", encoding="utf-8")
        raise RuntimeError(f"command failed to start: {args[0]}: {exc}") from exc
    input_bytes = stdin_text.encode("utf-8") if stdin_text is not None else None
    try:
        stdout, _ = await asyncio.wait_for(
            process.communicate(input_bytes),
            timeout=timeout_sec,
        )
    except TimeoutError as exc:
        if process.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
        stdout, _ = await process.communicate()
        output = stdout.decode("utf-8", errors="replace")
        marker = f"\n[command timed out after {timeout_sec} seconds]\n"
        log_path.write_text(output + marker, encoding="utf-8")
        raise TimeoutError(f"command timed out after {timeout_sec} seconds") from exc

    output = stdout.decode("utf-8", errors="replace")
    log_path.write_text(output, encoding="utf-8")

    if process.returncode != 0:
        tail = "\n".join(output.splitlines()[-40:])
        raise RuntimeError(
            f"command failed with exit code {process.returncode}: {tail}"
        )


def read_session_id_from_jsonl(session_file: Path) -> str:
    with session_file.open(encoding="utf-8", errors="replace") as file:
        first_line = file.readline().strip()
    if not first_line:
        raise ValueError(f"session file is empty: {session_file}")
    payload = json.loads(first_line)
    # Claude Code session files use top-level "sessionId" field
    return payload["sessionId"]


def find_latest_session_file_by_id(sessions_root: Path, session_id: str) -> Path:
    if not sessions_root.exists():
        raise FileNotFoundError(f"sessions directory not found: {sessions_root}")

    matching_files: list[Path] = []
    for session_file in sessions_root.rglob("*.jsonl"):
        try:
            candidate_session_id = read_session_id_from_jsonl(session_file)
        except (KeyError, ValueError, json.JSONDecodeError):
            continue
        if candidate_session_id == session_id:
            matching_files.append(session_file)

    if not matching_files:
        raise FileNotFoundError(
            f"no session file found for session_id={session_id} under {sessions_root}"
        )

    return max(matching_files, key=lambda path: path.stat().st_mtime_ns)


def read_claude_session_id_from_jsonl(session_file: Path) -> str:
    with session_file.open(encoding="utf-8", errors="replace") as file:
        for line in file:
            stripped = line.strip()
            if not stripped:
                continue
            payload = json.loads(stripped)
            session_id = payload.get("sessionId")
            if isinstance(session_id, str) and session_id:
                return session_id
    return session_file.stem


def find_latest_claude_session_file_by_id(
    sessions_root: Path,
    session_id: str,
) -> Path:
    matching_files: list[Path] = []
    for session_file in sessions_root.rglob("*.jsonl"):
        try:
            candidate_session_id = read_claude_session_id_from_jsonl(session_file)
        except (ValueError, json.JSONDecodeError):
            continue
        if candidate_session_id == session_id:
            matching_files.append(session_file)

    if not matching_files:
        raise FileNotFoundError(
            f"no Claude session file found for session_id={session_id} "
            f"under {sessions_root}"
        )

    return max(matching_files, key=lambda path: path.stat().st_mtime_ns)


def _strip_json_fence(text: str) -> str:
    stripped = text.strip()
    match = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", stripped, re.DOTALL)
    return match.group(1).strip() if match is not None else stripped


def _loads_json_object(text: str) -> dict[str, Any]:
    stripped = _strip_json_fence(text)
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start < 0 or end < start:
            raise
        payload = json.loads(stripped[start : end + 1])
    if not isinstance(payload, dict):
        raise TypeError("Claude output JSON must be an object.")
    return payload


def read_claude_output_payload(output_path: Path) -> dict[str, Any]:
    output = _loads_json_object(output_path.read_text(encoding="utf-8"))
    structured_output = output.get("structured_output")
    if isinstance(structured_output, dict):
        return structured_output
    if isinstance(structured_output, str):
        return _loads_json_object(structured_output)

    result = output.get("result")
    if isinstance(result, str):
        return _loads_json_object(result)
    return output


_DEFAULT_TRACE_PER_MESSAGE_CHARS = 4000
_DEFAULT_TRACE_TOTAL_CHARS = 200_000
_SKIPPED_PAYLOAD_TYPES = frozenset(
    {
        "summary",
        "last-prompt",
        "file-history-snapshot",
        "queue-operation",
    }
)


def _truncate_text(text: str, limit: int) -> str:
    if limit <= 0 or len(text) <= limit:
        return text
    head = text[: max(0, limit - 60)]
    return f"{head}\n... [truncated {len(text) - len(head)} chars]"


def _format_content_block(
    block: Any,
    *,
    per_message_limit: int,
) -> str | None:
    if not isinstance(block, dict):
        return None
    block_type = block.get("type")
    if block_type == "text":
        text = block.get("text")
        if not isinstance(text, str) or not text:
            return None
        return _truncate_text(text, per_message_limit)
    if block_type == "thinking":
        # Skip extended thinking content to keep trace focused on actions.
        return None
    if block_type == "tool_use":
        name = block.get("name") or "unknown_tool"
        tool_input = block.get("input")
        if not isinstance(tool_input, (dict, list)):
            tool_input_repr = repr(tool_input) if tool_input is not None else ""
        else:
            try:
                tool_input_repr = json.dumps(tool_input, ensure_ascii=False)
            except (TypeError, ValueError):
                tool_input_repr = repr(tool_input)
        body = _truncate_text(tool_input_repr, per_message_limit)
        return f"[tool_use:{name}] {body}"
    if block_type == "tool_result":
        tool_use_id = block.get("tool_use_id") or ""
        is_error = bool(block.get("is_error"))
        content = block.get("content")
        if isinstance(content, list):
            rendered_parts: list[str] = []
            for part in content:
                formatted = _format_content_block(
                    part, per_message_limit=per_message_limit
                )
                if formatted:
                    rendered_parts.append(formatted)
            content_repr = "\n".join(rendered_parts)
        elif isinstance(content, str):
            content_repr = content
        else:
            content_repr = repr(content) if content is not None else ""
        if not content_repr:
            content_repr = "(empty result)"
        status = " (error)" if is_error else ""
        body = _truncate_text(content_repr, per_message_limit)
        prefix = f"[tool_result{status}:{tool_use_id}]"
        return f"{prefix}\n{body}"
    if block_type == "image" or block_type == "image_url":
        return "[image omitted]"
    return None


def _format_message(
    payload: dict[str, Any],
    *,
    per_message_limit: int,
) -> str | None:
    message = payload.get("message")
    if not isinstance(message, dict):
        return None
    role = message.get("role") or payload.get("type") or "unknown"
    content = message.get("content")
    if isinstance(content, str):
        rendered = content.strip()
        if not rendered:
            return None
        return f"[{role}]\n{_truncate_text(rendered, per_message_limit)}"
    if isinstance(content, list):
        rendered_parts = [
            formatted
            for block in content
            for formatted in [
                _format_content_block(block, per_message_limit=per_message_limit)
            ]
            if formatted
        ]
        if not rendered_parts:
            return None
        return f"[{role}]\n" + "\n".join(rendered_parts)
    return None


def parse_claude_session_trace(
    session_file: Path,
    *,
    per_message_chars: int = _DEFAULT_TRACE_PER_MESSAGE_CHARS,
    total_chars: int = _DEFAULT_TRACE_TOTAL_CHARS,
) -> str:
    """Render a Claude Code session JSONL into a markdown trace string.

    The output is a chronological transcript with one block per message.
    Each block starts with a role tag (``[user]`` / ``[assistant]``) and
    includes text, tool invocations, and tool results, with per-message
    and total character caps to keep the embedded trace bounded.
    """
    if per_message_chars < 0:
        per_message_chars = 0
    if total_chars < 0:
        total_chars = 0

    blocks: list[str] = []
    total_used = 0
    truncated = False
    with session_file.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                payload = json.loads(stripped)
            except json.JSONDecodeError:
                continue
            if not isinstance(payload, dict):
                continue
            payload_type = payload.get("type")
            if payload_type in _SKIPPED_PAYLOAD_TYPES:
                continue
            if payload.get("isMeta"):
                continue
            if (
                payload_type not in {"user", "assistant", "system", "tool"}
                and "message" not in payload
            ):
                # Skip unknown payload shapes that are not message records.
                continue
            rendered = _format_message(
                payload,
                per_message_limit=per_message_chars,
            )
            if not rendered:
                continue
            projected = len(rendered) + 2  # account for the join separator
            if total_chars and total_used + projected > total_chars:
                truncated = True
                break
            blocks.append(rendered)
            total_used += projected

    if not blocks:
        return "(session trace is empty)"

    trace = "\n\n".join(blocks)
    if truncated:
        trace += (
            f"\n\n... [truncated, session continues for at least {total_used} chars]"
        )
    return trace


def iter_claude_session_messages(session_file: Path) -> Iterable[dict[str, Any]]:
    """Yield raw message payloads from a Claude Code session JSONL file.

    Skips summary/metadata rows and rows that fail to parse. Intended for
    callers that want full-fidelity access to the original payloads
    (for example, the evolve step) without re-implementing the file
    protocol.
    """
    with session_file.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                payload = json.loads(stripped)
            except json.JSONDecodeError:
                continue
            if not isinstance(payload, dict):
                continue
            if payload.get("type") in _SKIPPED_PAYLOAD_TYPES:
                continue
            if payload.get("isMeta"):
                continue
            yield payload
