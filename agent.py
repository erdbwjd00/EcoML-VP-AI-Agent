# -*- coding: utf-8 -*-
"""EcoML-VP AI agent (any OpenAI-compatible LLM server with tool calling)."""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger("ecoml_agent")


# --- Config (all overridable via environment variables) ---

def _env(*names: str, default: str) -> str:
    """Return the first non-empty environment variable among `names`."""
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    return default


# QWEN_* names are kept as legacy fallbacks.
LLM_BASE_URL = _env("LLM_BASE_URL", "QWEN_BASE_URL", default="http://127.0.0.1:8080/v1")
LLM_MODEL = _env("LLM_MODEL", "QWEN_MODEL", default="default")
LLM_API_KEY = _env("LLM_API_KEY", default="local")

# Tools may only touch files under this directory.
# Default: the "input" folder next to this file (the Docker image sets INPUT_DIR=/input).
INPUT_DIR = Path(
    os.environ.get("INPUT_DIR") or str(Path(__file__).resolve().parent / "input")
).resolve()
ECOML_VP_DIR = Path(
    os.environ.get("ECOML_VP_DIR", str(Path(__file__).resolve().parent / "EcoML-VP"))
).resolve()
ECOML_PYTHON = os.environ.get("ECOML_PYTHON", sys.executable)

LOG_PATH = os.environ.get("AGENT_LOG_PATH", "logs/agent.jsonl")
MAX_ITERATIONS = int(os.environ.get("AGENT_MAX_ITERATIONS", "10"))
LLM_TIMEOUT_SEC = float(os.environ.get("LLM_TIMEOUT_SEC", "120"))
LLM_MAX_RETRIES = int(os.environ.get("LLM_MAX_RETRIES", "2"))
# Reasoning models spend tokens on thinking, so keep this generous.
MAX_TOKENS = int(os.environ.get("LLM_MAX_TOKENS", "2048"))
TOOL_TIMEOUT_SEC = int(os.environ.get("TOOL_TIMEOUT_SEC", "600"))
MAX_TOOL_OUTPUT_CHARS = 4000
FASTA_SUFFIXES = {".fasta", ".fa", ".fna"}


# --- JSONL logging (one line per event; aggregate later for success rate / latency) ---

class JsonlLogger:
    def __init__(self, path: str | None):
        self.path = Path(path) if path else None

    def log(self, event: str, **fields: Any) -> None:
        if self.path is None:
            return
        record = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "event": event, **fields}
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        except OSError:
            logger.warning("failed to write JSONL log", exc_info=True)


# --- Tools ---

class ToolError(Exception):
    """Expected tool failure. The message is shown to the LLM as-is."""


def _truncate(text: str, limit: int = MAX_TOOL_OUTPUT_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n...[truncated {len(text) - limit} chars]"


def resolve_under_input(raw: Any) -> Path:
    """Resolve a user/LLM supplied path and ensure it stays under INPUT_DIR.

    resolve() collapses '../' and follows symlinks *before* the prefix check,
    so neither traversal nor symlink escapes get through.
    """
    if not isinstance(raw, str) or not raw.strip():
        raise ToolError("path must be a non-empty string")
    try:
        p = Path(raw)
        if not p.is_absolute():
            candidate = INPUT_DIR / p
            # Models often prefix the input directory's own name ("input/a.fasta").
            if p.parts and p.parts[0] == INPUT_DIR.name and not candidate.exists():
                candidate = INPUT_DIR.joinpath(*p.parts[1:])
            p = candidate
        p = p.resolve()
    except (ValueError, OSError) as e:
        raise ToolError(f"invalid path: {e}") from e
    if not p.is_relative_to(INPUT_DIR):
        raise ToolError(f"access denied: path must be inside {INPUT_DIR}")
    return p


def list_fasta_files(directory: str = ".") -> dict:
    """List FASTA files in a directory under INPUT_DIR (default: INPUT_DIR itself)."""
    d = resolve_under_input(directory)
    if not d.is_dir():
        raise ToolError(
            f"directory not found: {d}. Relative paths are resolved against the "
            f"input directory {INPUT_DIR}; use '.' for the input directory itself."
        )
    files = sorted(
        str(p) for p in d.iterdir()
        if p.is_file() and p.suffix.lower() in FASTA_SUFFIXES
    )
    return {"directory": str(d), "count": len(files), "files": files}


def run_ecoml_vp(fasta_path: str) -> dict:
    """Run the EcoML-VP pipeline on one FASTA file under INPUT_DIR."""
    path = resolve_under_input(fasta_path)
    if not path.is_file():
        raise ToolError(
            f"FASTA file not found: {path}. Relative paths are resolved against "
            f"the input directory {INPUT_DIR}."
        )
    if path.suffix.lower() not in FASTA_SUFFIXES:
        raise ToolError(f"not a FASTA file (expected {sorted(FASTA_SUFFIXES)}): {path.name}")

    main_py = ECOML_VP_DIR / "main.py"
    if not main_py.is_file():
        raise ToolError("EcoML-VP pipeline is not installed on this server")

    try:
        proc = subprocess.run(
            [ECOML_PYTHON, str(main_py), str(path)],  # list args, never shell=True
            capture_output=True,
            text=True,
            timeout=TOOL_TIMEOUT_SEC,
            cwd=str(ECOML_VP_DIR),
            shell=False,
        )
    except subprocess.TimeoutExpired:
        raise ToolError(f"EcoML-VP timed out after {TOOL_TIMEOUT_SEC}s") from None

    if proc.returncode != 0:
        raise ToolError(
            f"EcoML-VP failed (exit code {proc.returncode}): "
            f"{_truncate((proc.stderr or proc.stdout).strip())}"
        )
    return {"file": path.name, "output": _truncate(proc.stdout.strip())}


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: dict
    func: Callable[..., Any]

    def spec(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    def validate(self, args: dict) -> None:
        props = self.parameters.get("properties", {})
        required = self.parameters.get("required", [])
        missing = [k for k in required if k not in args]
        unknown = [k for k in args if k not in props]
        if missing or unknown:
            raise ToolError(f"invalid arguments: missing={missing}, unknown={unknown}")


TOOLS: dict[str, Tool] = {
    t.name: t
    for t in [
        Tool(
            name="list_fasta_files",
            description=(
                "List FASTA files in a directory. Use this when the user asks to "
                "find or analyze FASTA files in a directory."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "directory": {
                        "type": "string",
                        "description": (
                            "Directory to list. Relative paths are resolved against "
                            "the input directory. Omit or use '.' for the input directory."
                        ),
                    }
                },
                "required": [],
            },
            func=list_fasta_files,
        ),
        Tool(
            name="run_ecoml_vp",
            description=(
                "Run the EcoML-VP pipeline on one E. coli genomic FASTA file. "
                "Use this whenever the user asks to analyze an E. coli FASTA file."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "fasta_path": {
                        "type": "string",
                        "description": "Path to the FASTA file to analyze.",
                    }
                },
                "required": ["fasta_path"],
            },
            func=run_ecoml_vp,
        ),
    ]
}


def execute_tool(name: str, raw_arguments: Any, tools: dict[str, Tool]) -> dict:
    """Run a tool and ALWAYS return {"ok": bool, ...}; never raises."""
    tool = tools.get(name)
    if tool is None:
        return {"ok": False, "error": f"unknown tool '{name}'. Available: {sorted(tools)}"}
    try:
        args = json.loads(raw_arguments) if isinstance(raw_arguments, str) else raw_arguments
        if not isinstance(args, dict):
            raise ToolError("arguments must be a JSON object")
        tool.validate(args)
        return {"ok": True, "data": tool.func(**args)}
    except json.JSONDecodeError as e:
        return {"ok": False, "error": f"arguments are not valid JSON: {e}"}
    except ToolError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:  # tool bug: do not crash the agent loop
        logger.exception("unexpected error in tool %s", name)
        return {"ok": False, "error": f"internal tool error: {type(e).__name__}"}


# --- Fallback parser: some models (e.g. Qwen3) emit <tool_call> as plain text ---

_TOOL_CALL_RE = re.compile(r"<tool_call>(.*?)</tool_call>", re.DOTALL)
_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)


def parse_text_tool_calls(text: str) -> list[tuple[str, Any]]:
    """Return [(name, arguments)]. Raises ValueError if a block is malformed."""
    calls = []
    for block in _TOOL_CALL_RE.findall(text or ""):
        try:
            data = json.loads(block.strip())
            calls.append((data["name"], data.get("arguments", {})))
        except (json.JSONDecodeError, KeyError, TypeError, AttributeError) as e:
            raise ValueError(f"malformed <tool_call>: {e}") from e
    return calls


# --- Agent ---

def build_system_prompt() -> str:
    return (
        "You are an AI assistant for EcoML-VP.\n"
        "\n"
        "Rules:\n"
        f"- The input directory is {INPUT_DIR}. Relative paths are resolved against it; "
        "use '.' for the input directory itself. Tools cannot access anything outside it.\n"
        "- If the user does not name a directory, use the input directory.\n"
        "- To analyze an E. coli genomic FASTA file you MUST call run_ecoml_vp.\n"
        "- If the user refers to FASTA files in a directory without exact filenames, "
        "call list_fasta_files first. To analyze all files in a directory, list them, "
        "then analyze every file returned. To analyze one file, list the directory and "
        "analyze the first file returned.\n"
        "- Tool results are JSON: {\"ok\": true, \"data\": ...} or "
        "{\"ok\": false, \"error\": ...}.\n"
        "- Base your answer ONLY on tool results. Do not guess filenames, predictions, "
        "or the meaning of output labels. Report labels exactly as returned.\n"
        "- If a tool returns ok=false because a path was not found, retry once with a "
        "corrected path (for example '.'). Otherwise report the error text and continue "
        "with the remaining files. Never repeat a call with identical arguments.\n"
        "- With multiple files, summarize each file and its exact result separately.\n"
        "- Reply in the same language as the user."
    )


@dataclass
class ToolCallRecord:
    name: str
    arguments: str
    ok: bool
    error: str | None
    latency_ms: float


@dataclass
class AgentResult:
    answer: str
    status: str  # ok | max_iterations | llm_error | empty_response | truncated
    iterations: int
    latency_ms: float
    request_id: str
    tool_calls: list[ToolCallRecord] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def make_client(base_url: str = LLM_BASE_URL):
    """Build the OpenAI-compatible client lazily (keeps tests import-free)."""
    from openai import OpenAI

    return OpenAI(
        base_url=base_url,
        api_key=LLM_API_KEY,
        timeout=LLM_TIMEOUT_SEC,
        max_retries=LLM_MAX_RETRIES,
    )


def run_agent(
    user_message: str,
    *,
    client: Any,
    tools: dict[str, Tool] | None = None,
    model: str = LLM_MODEL,
    max_iterations: int = MAX_ITERATIONS,
    jsonl: JsonlLogger | None = None,
) -> AgentResult:
    tools = tools if tools is not None else TOOLS
    jsonl = jsonl or JsonlLogger(None)
    specs = [t.spec() for t in tools.values()]
    request_id = uuid.uuid4().hex[:12]
    t_start = time.perf_counter()

    messages: list[dict] = [
        {"role": "system", "content": build_system_prompt()},
        {"role": "user", "content": user_message},
    ]
    records: list[ToolCallRecord] = []
    seen_calls: set[tuple[str, str]] = set()

    jsonl.log("request_start", request_id=request_id, user_message=user_message)

    def finish(answer: str, status: str, iterations: int) -> AgentResult:
        result = AgentResult(
            answer=answer,
            status=status,
            iterations=iterations,
            latency_ms=round((time.perf_counter() - t_start) * 1000, 1),
            request_id=request_id,
            tool_calls=records,
        )
        jsonl.log(
            "request_end",
            request_id=request_id,
            status=status,
            iterations=iterations,
            latency_ms=result.latency_ms,
            n_tool_calls=len(records),
        )
        return result

    def call_tool(name: str, raw_args: Any) -> dict:
        key_args = raw_args if isinstance(raw_args, str) else json.dumps(
            raw_args, sort_keys=True, ensure_ascii=False
        )
        t0 = time.perf_counter()
        if (name, key_args) in seen_calls:  # loop guard
            result = {
                "ok": False,
                "error": "duplicate call: this exact call was already made. "
                         "Use the earlier result or answer the user.",
            }
        else:
            seen_calls.add((name, key_args))
            result = execute_tool(name, raw_args, tools)
        latency_ms = round((time.perf_counter() - t0) * 1000, 1)
        records.append(
            ToolCallRecord(name, key_args, result["ok"], result.get("error"), latency_ms)
        )
        jsonl.log(
            "tool_call",
            request_id=request_id,
            tool=name,
            arguments=key_args,
            ok=result["ok"],
            error=result.get("error"),
            latency_ms=latency_ms,
        )
        return result

    for iteration in range(1, max_iterations + 1):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                tools=specs,
                tool_choice="auto",
                max_tokens=MAX_TOKENS,
                temperature=0,  # reproducible evals
            )
        except Exception as e:  # network/timeouts after client-level retries
            logger.exception("LLM request failed")
            jsonl.log("llm_error", request_id=request_id, error=type(e).__name__)
            return finish(f"LLM request failed: {type(e).__name__}", "llm_error", iteration)

        choice = response.choices[0]
        message = choice.message
        content = message.content or ""
        reasoning = getattr(message, "reasoning_content", None) or ""
        native_calls = getattr(message, "tool_calls", None) or []

        # 1) Native tool calls
        if native_calls:
            messages.append(
                {
                    "role": "assistant",
                    "content": content,
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            },
                        }
                        for tc in native_calls
                    ],
                }
            )
            for tc in native_calls:
                result = call_tool(tc.function.name, tc.function.arguments)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )
            continue

        # 2) <tool_call> emitted as text (content or reasoning)
        try:
            text_calls = parse_text_tool_calls(content) or parse_text_tool_calls(reasoning)
        except ValueError as e:
            messages.append({"role": "assistant", "content": content})
            messages.append(
                {
                    "role": "user",
                    "content": f"Your tool call could not be parsed ({e}). "
                               "Emit valid JSON inside <tool_call></tool_call>, "
                               "or answer without tools.",
                }
            )
            continue

        if text_calls:
            messages.append({"role": "assistant", "content": content})
            responses = []
            for name, args in text_calls:
                result = call_tool(name, args)
                payload = json.dumps({"name": name, **result}, ensure_ascii=False)
                responses.append(f"<tool_response>\n{payload}\n</tool_response>")
            messages.append({"role": "user", "content": "\n".join(responses)})
            continue

        # 3) Final answer
        answer = _THINK_RE.sub("", content).strip()
        if not answer:
            if choice.finish_reason == "length":
                return finish("(response truncated: raise LLM_MAX_TOKENS)", "truncated", iteration)
            return finish("(empty response from model)", "empty_response", iteration)
        return finish(answer, "ok", iteration)

    return finish("(stopped: max iterations reached)", "max_iterations", max_iterations)


# --- Main ---

def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    print("========================================")
    print("       EcoML-VP Local AI Agent")
    print("========================================")
    user_message = input("\nUser: ")

    result = run_agent(
        user_message,
        client=make_client(),
        jsonl=JsonlLogger(LOG_PATH),
    )

    print("\nAgent:")
    print(result.answer)
    print(
        f"\n[status={result.status} iterations={result.iterations} "
        f"tool_calls={len(result.tool_calls)} latency={result.latency_ms}ms]"
    )


if __name__ == "__main__":
    main()
