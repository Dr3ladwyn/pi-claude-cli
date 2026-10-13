"""Small OpenAI-shaped facade over the local Hermes worker protocol."""
from __future__ import annotations

import asyncio
import copy
import json
import os
import queue
import signal
import subprocess
import threading
import uuid
from types import SimpleNamespace
from typing import Any, Iterator

PROTOCOL_VERSION = 1
NATIVE_REPLAY_TYPE = "pi-claude-cli.native_assistant"


class _AttrDict(dict):
    """Attribute-accessible wire mappings, retaining mapping compatibility."""
    def __getattr__(self, name: str) -> Any:
        try:
            return self[name]
        except KeyError as error:
            raise AttributeError(name) from error


def _wire_value(value: Any) -> Any:
    if isinstance(value, dict):
        return _AttrDict({key: _wire_value(item) for key, item in value.items()})
    if isinstance(value, list):
        return [_wire_value(item) for item in value]
    return value


def _obj(**values: Any) -> SimpleNamespace:
    return SimpleNamespace(**{key: _wire_value(value) for key, value in values.items()})


def _json_args(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        parsed = json.loads(value)
    else:
        parsed = value
    if not isinstance(parsed, dict):
        raise ValueError("tool arguments must be a JSON object")
    return parsed


def validate_request(kwargs: dict[str, Any]) -> None:
    for field in ("temperature", "top_p", "presence_penalty", "frequency_penalty", "seed", "logit_bias", "stop", "logprobs", "top_logprobs"):
        if field in kwargs and kwargs[field] is not None:
            raise ValueError(f"Unsupported request field: {field}")
    response_format = kwargs.get("response_format")
    if response_format not in (None, {"type": "text"}):
        raise ValueError("Unsupported request field: response_format")
    if kwargs.get("n", 1) != 1:
        raise ValueError("Unsupported request field: n")
    if kwargs.get("tool_choice", "auto") not in ("auto", "none"):
        raise ValueError("Unsupported request field: tool_choice")
    if kwargs.get("parallel_tool_calls") not in (None, False):
        raise ValueError("Unsupported request field: parallel_tool_calls")
    max_tokens = kwargs.get("max_tokens", kwargs.get("max_completion_tokens"))
    if max_tokens is not None and (isinstance(max_tokens, bool) or not isinstance(max_tokens, int) or max_tokens <= 0):
        raise ValueError("max_tokens must be a positive integer")

def to_transcript(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    transcript: list[dict[str, Any]] = []
    tool_names: dict[str, str] = {}
    for message in messages:
        role = message.get("role")
        content = message.get("content")
        if role in ("system", "developer"):
            text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
            transcript.append({"role": "developer", "content": [{"type": "text", "text": text}]})
        elif role == "user":
            transcript.append({"role": "user", "content": _user_content(content)})
        elif role == "assistant":
            blocks: list[dict[str, Any]] = []
            details = message.get("reasoning_details") or []
            carriers = [detail for detail in details if isinstance(detail, dict) and detail.get("type") == NATIVE_REPLAY_TYPE]
            visible_calls = [{"type": "tool_call", "id": call["id"], "name": call["function"]["name"], "arguments": _json_args(call["function"].get("arguments", "{}"))} for call in message.get("tool_calls") or []]
            if carriers:
                if len(carriers) != 1 or not isinstance(carriers[0].get("content"), list):
                    raise ValueError("Malformed native assistant replay carrier")
                blocks = copy.deepcopy(carriers[0]["content"])
                if not all(isinstance(block, dict) for block in blocks):
                    raise ValueError("Malformed native assistant replay blocks")
                native_calls = [block for block in blocks if block.get("type") == "tool_call"]
                native_text = "".join(block.get("text", "") for block in blocks if block.get("type") == "text")
                if native_calls != visible_calls or native_text != (content or ""):
                    raise ValueError("Native assistant carrier disagrees with edited visible history")
            else:
                for detail in details:
                    if isinstance(detail, dict) and detail.get("type") == "thinking" and isinstance(detail.get("text"), str) and isinstance(detail.get("signature"), str):
                        blocks.append({"type": "thinking", "thinking": detail["text"], "signature": detail["signature"]})
                if isinstance(content, str) and content:
                    blocks.append({"type": "text", "text": content})
                blocks.extend(visible_calls)
            for block in blocks:
                if block.get("type") == "tool_call":
                    tool_names[block["id"]] = block["name"]
            transcript.append({"role": "assistant", "content": blocks, "stopReason": "toolUse" if message.get("tool_calls") else "stop"})
        elif role == "tool":
            call_id = message.get("tool_call_id")
            if not isinstance(call_id, str) or not call_id:
                raise ValueError("tool result requires tool_call_id")
            result_content = _user_content(content)
            transcript.append({"role": "tool_result", "toolCallId": call_id, "toolName": message.get("name") or tool_names.get(call_id, ""), "content": result_content, "isError": bool(message.get("is_error", False))})
        else:
            raise ValueError(f"Unsupported message role: {role}")
    return transcript


def _user_content(content: Any) -> list[dict[str, Any]]:
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    if not isinstance(content, list):
        raise ValueError("message content must be text or a content-parts list")
    result: list[dict[str, Any]] = []
    for part in content:
        if not isinstance(part, dict):
            raise ValueError("message content part must be an object")
        if part.get("type") == "text":
            result.append({"type": "text", "text": part.get("text", "")})
        elif part.get("type") == "image_url":
            image_url = part.get("image_url", {}).get("url", "")
            if not isinstance(image_url, str) or not image_url.startswith("data:"):
                raise ValueError("Only data URL image content is supported")
            metadata, encoded = image_url[5:].split(",", 1)
            mime = metadata.split(";", 1)[0]
            result.append({"type": "image", "data": encoded, "mimeType": mime})
        else:
            raise ValueError(f"Unsupported content part: {part.get('type')}")
    return result


class _Worker:
    def __init__(self, command: str, args: tuple[str, ...]):
        self._command = command
        self._args = args
        self._lock = threading.RLock()
        self._process: subprocess.Popen[str] | None = None
        self._write_lock = threading.Lock()
        self._pending_cancellations: set[str] = set()
        self._active_request: str | None = None
        self._request_sent = False
        self._ready = False
        self._closed = False
        self._stderr_thread: threading.Thread | None = None

    def _start(self) -> subprocess.Popen[str]:
        if self._closed:
            raise RuntimeError("Claude worker is closed")
        if self._process is not None and self._process.poll() is None:
            return self._process
        if self._process is not None:
            self._process.wait(timeout=3)
            for stream in (self._process.stdin, self._process.stdout, self._process.stderr):
                if stream is not None:
                    stream.close()
            if self._stderr_thread is not None:
                self._stderr_thread.join(timeout=2)
        env = os.environ.copy()
        # Never import credentials from Hermes. Existing PI_CLAUDE_* controls are the only bridge config.
        if env.get("PI_CLAUDE_AUTH", "claude-login") not in ("claude-login", "api-key"):
            raise ValueError("PI_CLAUDE_AUTH must be claude-login or api-key")
        kwargs: dict[str, Any] = {"stdin": subprocess.PIPE, "stdout": subprocess.PIPE, "stderr": subprocess.PIPE, "text": True, "bufsize": 1, "env": env}
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kwargs["start_new_session"] = True
        process = subprocess.Popen([self._command, *self._args], **kwargs)
        self._process = process
        self._ready = False
        self._stderr_thread = threading.Thread(target=self._drain_stderr, args=(process,), daemon=True)
        self._stderr_thread.start()
        hello_id = str(uuid.uuid4())
        process.stdin.write(json.dumps({"version": PROTOCOL_VERSION, "id": hello_id, "type": "hello"}) + "\n")
        process.stdin.flush()
        reply = process.stdout.readline()
        packet = json.loads(reply)
        if packet.get("version") != PROTOCOL_VERSION or packet.get("id") != hello_id or packet.get("type") != "ready":
            self._terminate(process)
            raise RuntimeError("Claude worker handshake failed")
        with self._write_lock:
            self._ready = True
        return process

    @staticmethod
    def _drain_stderr(process: subprocess.Popen[str]) -> None:
        if process.stderr is not None:
            for line in process.stderr:
                # Worker sanitizes before logging; do not copy stderr to Hermes' stdout.
                if len(line) > 1024:
                    continue

    @staticmethod
    def _terminate(process: subprocess.Popen[str]) -> None:
        if process.poll() is not None:
            return
        try:
            if os.name == "nt":
                process.terminate()
            else:
                os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=3)
        except (OSError, subprocess.TimeoutExpired):
            try:
                if os.name == "nt":
                    process.kill()
                else:
                    os.killpg(process.pid, signal.SIGKILL)
            except OSError:
                process.kill()
            process.wait(timeout=3)
    def request(self, payload: dict[str, Any], on_event: Any = None, request_id: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            request_id = request_id or str(uuid.uuid4())
            with self._write_lock:
                self._active_request = request_id
                self._request_sent = False
            try:
                process = self._start()
                request = {"version": PROTOCOL_VERSION, "id": request_id, **payload}
                with self._write_lock:
                    process.stdin.write(json.dumps(request, ensure_ascii=False) + "\n")
                    process.stdin.flush()
                    self._request_sent = True
                    if request_id in self._pending_cancellations:
                        self._pending_cancellations.remove(request_id)
                        self._send_cancel(process, request_id)
                events: list[dict[str, Any]] = []
                while True:
                    line = process.stdout.readline()
                    if not line:
                        code = process.poll()
                        self._ready = False
                        # Retain the owned handle so close/restart can reap it and
                        # release every pipe even when the request hit EOF first.
                        raise RuntimeError(f"Claude worker exited unexpectedly ({code})")
                    packet = json.loads(line)
                    if packet.get("version") != PROTOCOL_VERSION or packet.get("id") != request_id:
                        continue
                    if packet.get("type") == "error":
                        raise RuntimeError(str(packet.get("error", "Claude worker request failed")))
                    if packet.get("type") == "event":
                        event = packet.get("event")
                        if isinstance(event, dict):
                            events.append(event)
                            if on_event is not None:
                                on_event(event)
                    elif packet.get("type") == "result":
                        return events
            finally:
                with self._write_lock:
                    self._pending_cancellations.discard(request_id)
                    self._active_request = None
                    self._request_sent = False

    @staticmethod
    def _send_cancel(process: subprocess.Popen[str], target_id: str) -> None:
        if process.poll() is not None or process.stdin is None:
            return
        packet = {"version": PROTOCOL_VERSION, "id": str(uuid.uuid4()), "type": "cancel", "targetId": target_id}
        try:
            process.stdin.write(json.dumps(packet) + "\n")
            process.stdin.flush()
        except (BrokenPipeError, OSError):
            return

    def cancel(self, target_id: str) -> None:
        with self._write_lock:
            process = self._process
            if target_id == self._active_request and not self._request_sent:
                self._pending_cancellations.add(target_id)
                return
            if process is None or process.poll() is not None or not self._ready:
                self._pending_cancellations.add(target_id)
                return
            self._send_cancel(process, target_id)

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            process = self._process
            self._process = None
            self._ready = False
            if process is None:
                return
            if process.poll() is None:
                try:
                    packet = {"version": PROTOCOL_VERSION, "id": str(uuid.uuid4()), "type": "shutdown"}
                    with self._write_lock:
                        process.stdin.write(json.dumps(packet) + "\n")
                        process.stdin.flush()
                    process.wait(timeout=5)
                except (OSError, subprocess.TimeoutExpired):
                    self._terminate(process)
            for stream in (process.stdin, process.stdout, process.stderr):
                if stream is not None:
                    stream.close()
            if self._stderr_thread is not None:
                self._stderr_thread.join(timeout=2)
class _Completions:
    def __init__(self, client: "HermesClaudeClient"):
        self._client = client

    def create(self, **kwargs: Any) -> Any:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return self._client._stream(kwargs) if kwargs.get("stream", False) else self._client._complete(kwargs)
        return self._client._async_stream(kwargs) if kwargs.get("stream", False) else self._client._acreate(kwargs)

class HermesClaudeClient:
    # Hermes must leave this complete NDJSON transport and its sync/async facade intact.
    HERMES_SKIP_TRANSPORT_WRAP = True
    HERMES_SKIP_ASYNC_WRAP = True

    def __init__(self, *, command: str, args: tuple[str, ...], client_kwargs: dict[str, Any]):
        del client_kwargs
        self._worker = _Worker(command, args)
        self._owner_id = str(uuid.uuid4())
        self._session_id = str(uuid.uuid4())
        self._round = 0
        self._active: str | None = None
        self._lock = threading.Lock()
        self.chat = _obj(completions=_Completions(self))
    def cancel(self) -> None:
        if self._active is not None:
            self._worker.cancel(self._active)

    def close(self) -> None:
        self.cancel()
        self._worker.close()

    async def aclose(self) -> None:
        await asyncio.to_thread(self.close)

    async def __aenter__(self) -> "HermesClaudeClient":
        return self

    async def __aexit__(self, *_args: Any) -> None:
        await self.aclose()

    def _request(self, kwargs: dict[str, Any], on_event: Any = None) -> tuple[list[dict[str, Any]], str, str]:
        validate_request(kwargs)
        with self._lock:
            if self._active is not None:
                raise RuntimeError("Overlapping calls on one Hermes client are unsupported")
            self._round += 1
            request_id = str(uuid.uuid4())
            self._active = request_id
            try:
                messages = kwargs.get("messages")
                if not isinstance(messages, list) or not messages:
                    raise ValueError("messages must be a non-empty list")
                system_parts = [block for message in messages if message.get("role") == "system"
                                for block in _user_content(message.get("content"))]
                if any(block.get("type") != "text" for block in system_parts):
                    raise ValueError("System messages must contain text")
                system_prompt = "\n\n".join(block["text"] for block in system_parts)
                transcript = to_transcript([message for message in messages if message.get("role") != "system"])
                if not transcript:
                    raise ValueError("messages require a non-system turn")
                definitions = []
                if kwargs.get("tool_choice", "auto") != "none":
                    for item in kwargs.get("tools", []):
                        function = item.get("function", {})
                        definitions.append({"name": function.get("name", ""), "description": function.get("description", ""), "owner": "host", "inputSchema": function.get("parameters", {"type": "object"})})
                effort = _effort(kwargs.get("reasoning_effort"))
                max_tokens = kwargs.get("max_tokens", kwargs.get("max_completion_tokens"))
                boundary = max((i for i, message in enumerate(transcript) if message["role"] == "assistant"), default=-1) + 1
                tail = transcript[boundary:]
                current = transcript[-1]
                if current["role"] == "tool_result":
                    results = [message for message in tail if message["role"] == "tool_result"]
                    input_data = {"kind": "tool-results", "results": results}
                else:
                    prompts = [message for message in tail if message["role"] in ("user", "developer")]
                    input_data = {"kind": "prompt", "content": [block for message in prompts for block in message["content"]], "messages": prompts}
                request = {
                    "version": PROTOCOL_VERSION,
                    "id": request_id,
                    "type": "round",
                    "request": {
                        "roundId": f"{self._session_id}:{self._round}",
                        "session": {"sessionId": self._session_id, "branchId": self._owner_id, "historyRevision": "0"},
                        "cwd": os.getcwd(),
                        "model": str(kwargs.get("model", "claude-sonnet-4-5")),
                        "systemPrompt": system_prompt,
                        "tools": definitions,
                        "transcript": transcript,
                        "input": input_data,
                        "settings": {**({"effort": effort} if effort is not None else {}), **({"maxOutputTokens": max_tokens} if max_tokens is not None else {}), "toolResultTimeoutMs": 180000, "claudeTools": [], "userMcpServers": [], "settingSources": []},
                        "auth": {"mode": "api-key"} if os.environ.get("PI_CLAUDE_AUTH") == "api-key" else {"mode": "claude-login"},
                    },
                }
                events = self._worker.request({key: value for key, value in request.items() if key not in ("version", "id")}, on_event, request_id)
                return events, request_id, str(kwargs.get("model", "claude-sonnet-4-5"))
            finally:
                self._active = None

    def _complete(self, kwargs: dict[str, Any]) -> Any:
        events, request_id, model = self._request(kwargs)
        return _response(events, request_id, model)

    def _stream(self, kwargs: dict[str, Any]) -> Iterator[Any]:
        output: queue.Queue[Any] = queue.Queue()
        sentinel = object()
        model = str(kwargs.get("model", "claude-sonnet-4-5"))
        tool_indexes: dict[str, int] = {}

        def receive(event: dict[str, Any]) -> None:
            for chunk in _event_chunks(event, self._active or "", model, tool_indexes):
                output.put(chunk)

        def produce() -> None:
            try:
                self._request(kwargs, receive)
            except BaseException as exc:
                output.put(exc)
            finally:
                output.put(sentinel)

        worker = threading.Thread(target=produce, daemon=True)
        worker.start()
        try:
            while True:
                item = output.get()
                if item is sentinel:
                    break
                if isinstance(item, BaseException):
                    raise item
                yield item
        finally:
            if worker.is_alive():
                self.cancel()
                worker.join(timeout=2)

    async def _acreate(self, kwargs: dict[str, Any]) -> Any:
        return await asyncio.to_thread(self._complete, kwargs)

    async def _async_stream(self, kwargs: dict[str, Any]):
        return self._astream(kwargs)

    async def _astream(self, kwargs: dict[str, Any]):
        stream_queue: queue.Queue[Any] = queue.Queue()
        sentinel = object()

        def produce() -> None:
            try:
                for chunk in self._stream(kwargs):
                    stream_queue.put(chunk)
            except BaseException as exc:
                stream_queue.put(exc)
            finally:
                stream_queue.put(sentinel)

        thread = threading.Thread(target=produce, daemon=True)
        thread.start()
        try:
            while True:
                item = await asyncio.to_thread(stream_queue.get)
                if item is sentinel:
                    break
                if isinstance(item, BaseException):
                    raise item
                yield item
        finally:
            if thread.is_alive():
                self.cancel()



def _effort(value: Any) -> str | None:
    if value is None:
        return None
    if value in ("low", "medium", "high", "xhigh", "max"):
        return value
    raise ValueError("Unsupported reasoning_effort")


def _text_and_tools(events: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]], str, dict[str, Any]]:
    text_parts: list[str] = []
    calls: dict[str, dict[str, Any]] = {}
    finish = "stop"
    usage: dict[str, Any] = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    final_text: str | None = None
    for envelope in events:
        if envelope.get("type") == "round_end":
            reason = envelope.get("reason")
            if reason in ("error", "aborted"):
                error = envelope.get("error") or {}
                raise RuntimeError(str(error.get("message", f"Claude round {reason}")))
            finish = "tool_calls" if reason == "toolUse" else "length" if reason == "length" else "stop"
            final_blocks = envelope.get("content")
            if isinstance(final_blocks, list):
                final_text = "".join(block.get("text", "") for block in final_blocks if isinstance(block, dict) and block.get("type") == "text")
            raw = envelope.get("usage") or {}
            input_tokens = raw.get("inputTokens", 0)
            output_tokens = raw.get("outputTokens", 0)
            usage = {
                "prompt_tokens": input_tokens,
                "completion_tokens": output_tokens,
                "total_tokens": input_tokens + output_tokens,
                "prompt_tokens_details": {"cached_tokens": raw.get("cacheReadTokens", 0), "cache_write_tokens": raw.get("cacheWriteTokens", 0)},
                "completion_tokens_details": {"reasoning_tokens": raw.get("reasoningTokens", 0)},
            }
            continue
        if envelope.get("type") != "driver_event":
            continue
        event = envelope.get("event", {})
        if event.get("type") == "content_delta":
            delta = event.get("delta", {})
            if delta.get("kind") == "text":
                text_parts.append(delta.get("text", ""))
        elif event.get("type") == "host_tool_request":
            call = event.get("call", {})
            call_id = call.get("id")
            if isinstance(call_id, str):
                calls[call_id] = call
    response_text = "".join(text_parts) if final_text is None else final_text
    return response_text, list(calls.values()), finish, usage


def _thinking_details(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for envelope in reversed(events):
        if envelope.get("type") == "round_end" and isinstance(envelope.get("content"), list):
            return [{"type": NATIVE_REPLAY_TYPE, "content": copy.deepcopy(envelope["content"])}]
    return []


def _response(events: list[dict[str, Any]], request_id: str, model: str) -> Any:
    text, calls, finish, usage = _text_and_tools(events)
    for envelope in reversed(events):
        event = envelope.get("event", {}) if envelope.get("type") == "driver_event" else {}
        if event.get("type") == "message_start" and isinstance(event.get("model"), str):
            model = event["model"]
            break
    tool_calls = [_obj(id=call["id"], type="function", function=_obj(name=call["name"], arguments=json.dumps(call["arguments"], ensure_ascii=False, separators=(",", ":")))) for call in calls]
    message = _obj(role="assistant", content=text or None, tool_calls=tool_calls or None, reasoning_details=_thinking_details(events) or None)
    return _obj(id=f"chatcmpl-{request_id}", object="chat.completion", created=0, model=model, choices=[_obj(index=0, message=message, finish_reason=finish)], usage=_obj(**usage))


def _event_chunks(event: dict[str, Any], request_id: str, model: str, tool_indexes: dict[str, int]) -> list[Any]:
    chunk_id = f"chatcmpl-{request_id}"
    if event.get("type") == "driver_event":
        payload = event.get("event", {})
        if payload.get("type") == "content_delta":
            delta = payload.get("delta", {})
            if delta.get("kind") == "text":
                delta_value = {"content": delta.get("text", "")}
            elif delta.get("kind") == "thinking":
                delta_value = {"reasoning_content": delta.get("thinking", "")}
            else:
                return []
            return [_obj(id=chunk_id, object="chat.completion.chunk", created=0, model=model, choices=[_obj(index=0, delta=delta_value, finish_reason=None)])]
        if payload.get("type") == "host_tool_request":
            call = payload.get("call", {})
            call_id = call.get("id")
            if not isinstance(call_id, str):
                return []
            index = tool_indexes.setdefault(call_id, len(tool_indexes))
            call_delta = {"index": index, "id": call_id, "type": "function", "function": {"name": call.get("name"), "arguments": json.dumps(call.get("arguments", {}), separators=(",", ":"))}}
            return [_obj(id=chunk_id, object="chat.completion.chunk", created=0, model=model, choices=[_obj(index=0, delta={"tool_calls": [call_delta]}, finish_reason=None)])]
    if event.get("type") == "round_end":
        _, _, finish, _ = _text_and_tools([event])
        return [_obj(id=chunk_id, object="chat.completion.chunk", created=0, model=model, choices=[_obj(index=0, delta={}, finish_reason=finish)])]
    return []


def _full_chunks(events: list[dict[str, Any]], request_id: str, model: str) -> Iterator[Any]:
    tool_indexes: dict[str, int] = {}
    for event in events:
        yield from _event_chunks(event, request_id, model, tool_indexes)
