# -*- coding: utf-8 -*-
"""Agent tests using a scripted fake LLM. No LLM server or openai package needed."""

import json
import subprocess
from types import SimpleNamespace as NS

import pytest

import agent


# --- helpers ---

def tool_call(name, args, call_id="call_1"):
    raw = args if isinstance(args, str) else json.dumps(args)
    return NS(id=call_id, function=NS(name=name, arguments=raw))


def reply(content="", tool_calls=None, reasoning=None, finish="stop"):
    msg = NS(content=content, tool_calls=tool_calls, reasoning_content=reasoning)
    return NS(choices=[NS(message=msg, finish_reason=finish)])


class FakeClient:
    """Returns scripted replies in order; repeats the last one when exhausted."""

    def __init__(self, replies):
        self._replies = list(replies)
        self.calls = []
        self.chat = NS(completions=NS(create=self._create))

    def _create(self, **kwargs):
        kwargs["messages"] = list(kwargs["messages"])  # snapshot
        self.calls.append(kwargs)
        if len(self._replies) > 1:
            return self._replies.pop(0)
        return self._replies[0]


class ExplodingClient:
    def __init__(self):
        self.chat = NS(completions=NS(create=self._create))

    def _create(self, **kwargs):
        raise RuntimeError("connection refused")


@pytest.fixture
def env(tmp_path, monkeypatch):
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "a.fasta").write_text(">a\nACGT\n")
    (input_dir / "b.fa").write_text(">b\nACGT\n")
    (input_dir / "notes.txt").write_text("not fasta")

    ecoml_dir = tmp_path / "EcoML-VP"
    ecoml_dir.mkdir()
    (ecoml_dir / "main.py").write_text("print('stub')\n")

    monkeypatch.setattr(agent, "INPUT_DIR", input_dir.resolve())
    monkeypatch.setattr(agent, "ECOML_VP_DIR", ecoml_dir.resolve())
    return NS(input_dir=input_dir.resolve(), tmp_path=tmp_path)


# --- path safety ---

@pytest.mark.parametrize("bad", ["../", "/etc", "/etc/passwd", "../../etc", "a\x00b"])
def test_list_blocks_paths_outside_input(env, bad):
    r = agent.execute_tool("list_fasta_files", {"directory": bad}, agent.TOOLS)
    assert r["ok"] is False


def test_run_blocks_paths_outside_input(env):
    r = agent.execute_tool("run_ecoml_vp", {"fasta_path": "/etc/passwd"}, agent.TOOLS)
    assert r["ok"] is False and "access denied" in r["error"]


def test_symlink_escape_blocked(env):
    outside = env.tmp_path / "secret.fasta"
    outside.write_text(">x\nA\n")
    try:
        (env.input_dir / "link.fasta").symlink_to(outside)
    except OSError:
        pytest.skip("symlinks not supported")
    r = agent.execute_tool("run_ecoml_vp", {"fasta_path": "link.fasta"}, agent.TOOLS)
    assert r["ok"] is False and "access denied" in r["error"]


def test_list_only_returns_fasta(env):
    r = agent.execute_tool("list_fasta_files", {"directory": str(env.input_dir)}, agent.TOOLS)
    assert r["ok"] is True
    assert r["data"]["count"] == 2
    assert all(f.endswith((".fasta", ".fa")) for f in r["data"]["files"])


def test_rejects_non_fasta_extension(env):
    r = agent.execute_tool("run_ecoml_vp", {"fasta_path": "notes.txt"}, agent.TOOLS)
    assert r["ok"] is False and "not a FASTA" in r["error"]


# --- subprocess handling ---

def test_subprocess_uses_list_args_no_shell(env, monkeypatch):
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"], captured["kwargs"] = cmd, kwargs
        return subprocess.CompletedProcess(cmd, 0, stdout="Label_1\n", stderr="")

    monkeypatch.setattr(agent.subprocess, "run", fake_run)
    r = agent.execute_tool("run_ecoml_vp", {"fasta_path": "a.fasta"}, agent.TOOLS)

    assert r["ok"] is True and r["data"]["output"] == "Label_1"
    assert isinstance(captured["cmd"], list)
    assert captured["kwargs"]["shell"] is False
    assert captured["kwargs"]["timeout"] == agent.TOOL_TIMEOUT_SEC
    # relative path was resolved to an absolute one before cwd changes
    assert captured["cmd"][-1] == str(env.input_dir / "a.fasta")


def test_subprocess_failure_is_structured_and_truncated(env, monkeypatch):
    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="boom" * 5000)

    monkeypatch.setattr(agent.subprocess, "run", fake_run)
    r = agent.execute_tool("run_ecoml_vp", {"fasta_path": "a.fasta"}, agent.TOOLS)
    assert r["ok"] is False and "boom" in r["error"]
    assert len(r["error"]) < agent.MAX_TOOL_OUTPUT_CHARS + 200


def test_subprocess_timeout(env, monkeypatch):
    def fake_run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, 1)

    monkeypatch.setattr(agent.subprocess, "run", fake_run)
    r = agent.execute_tool("run_ecoml_vp", {"fasta_path": "a.fasta"}, agent.TOOLS)
    assert r["ok"] is False and "timed out" in r["error"]


# --- argument / tool errors ---

def test_invalid_json_arguments(env):
    r = agent.execute_tool("list_fasta_files", "{bad json", agent.TOOLS)
    assert r["ok"] is False and "not valid JSON" in r["error"]


def test_missing_and_unknown_arguments(env):
    assert agent.execute_tool("run_ecoml_vp", {}, agent.TOOLS)["ok"] is False
    r = agent.execute_tool("run_ecoml_vp", {"fasta_path": "a.fasta", "x": 1}, agent.TOOLS)
    assert r["ok"] is False


def test_unknown_tool(env):
    r = agent.execute_tool("rm_rf", {}, agent.TOOLS)
    assert r["ok"] is False and "unknown tool" in r["error"]


# --- agent loop ---

def test_native_tool_call_then_answer(env):
    client = FakeClient([
        reply(tool_calls=[tool_call("list_fasta_files", {"directory": str(env.input_dir)})]),
        reply(content="Found a.fasta and b.fa"),
    ])
    result = agent.run_agent("list files", client=client)

    assert result.status == "ok"
    assert result.answer == "Found a.fasta and b.fa"
    assert [c.name for c in result.tool_calls] == ["list_fasta_files"]
    assert result.tool_calls[0].ok is True
    # tool message goes back to the LLM in OpenAI format
    last = client.calls[1]["messages"][-1]
    assert last["role"] == "tool" and last["tool_call_id"] == "call_1"
    assert json.loads(last["content"])["ok"] is True


def test_tool_error_is_fed_back_to_llm(env):
    client = FakeClient([
        reply(tool_calls=[tool_call("run_ecoml_vp", {"fasta_path": "missing.fasta"})]),
        reply(content="File not found."),
    ])
    result = agent.run_agent("analyze missing.fasta", client=client)

    assert result.status == "ok"
    assert result.tool_calls[0].ok is False
    fed_back = json.loads(client.calls[1]["messages"][-1]["content"])
    assert fed_back["ok"] is False and "not found" in fed_back["error"]


def test_invalid_json_args_do_not_crash_loop(env):
    client = FakeClient([
        reply(tool_calls=[tool_call("list_fasta_files", "{bad")]),
        reply(content="sorry"),
    ])
    result = agent.run_agent("x", client=client)
    assert result.status == "ok" and result.tool_calls[0].ok is False


def test_max_iterations_stops_infinite_loop(env):
    looping = reply(tool_calls=[tool_call("list_fasta_files", {"directory": "."})])
    client = FakeClient([looping])
    result = agent.run_agent("x", client=client, max_iterations=3)

    assert result.status == "max_iterations"
    assert len(client.calls) == 3
    # 1st call executes, repeats are rejected by the duplicate guard
    assert result.tool_calls[0].ok is True
    assert all(not c.ok for c in result.tool_calls[1:])


def test_text_tool_call_in_reasoning_fallback(env):
    payload = json.dumps(
        {"name": "list_fasta_files", "arguments": {"directory": str(env.input_dir)}}
    )
    client = FakeClient([
        reply(content="", reasoning=f"I should call <tool_call>{payload}</tool_call>"),
        reply(content="done"),
    ])
    result = agent.run_agent("x", client=client)

    assert result.status == "ok" and result.tool_calls[0].ok is True
    last = client.calls[1]["messages"][-1]
    assert last["role"] == "user" and "<tool_response>" in last["content"]


def test_malformed_text_tool_call_is_reported_back(env):
    client = FakeClient([
        reply(content="", reasoning="<tool_call>{oops</tool_call>"),
        reply(content="ok, answering directly"),
    ])
    result = agent.run_agent("x", client=client)

    assert result.status == "ok" and result.tool_calls == []
    assert "could not be parsed" in client.calls[1]["messages"][-1]["content"]


def test_llm_error_returns_status_not_exception(env):
    result = agent.run_agent("x", client=ExplodingClient())
    assert result.status == "llm_error"


def test_think_block_stripped_from_answer(env):
    client = FakeClient([reply(content="<think>hmm</think>final answer")])
    assert agent.run_agent("x", client=client).answer == "final answer"


def test_truncated_response_status(env):
    client = FakeClient([reply(content="", finish="length")])
    assert agent.run_agent("x", client=client).status == "truncated"


def test_jsonl_log_written(env):
    log_path = env.tmp_path / "logs" / "agent.jsonl"
    client = FakeClient([
        reply(tool_calls=[tool_call("list_fasta_files", {"directory": str(env.input_dir)})]),
        reply(content="done"),
    ])
    agent.run_agent("x", client=client, jsonl=agent.JsonlLogger(str(log_path)))

    events = [json.loads(line) for line in log_path.read_text().splitlines()]
    assert [e["event"] for e in events] == ["request_start", "tool_call", "request_end"]
    assert events[-1]["status"] == "ok" and "latency_ms" in events[-1]
    assert len({e["request_id"] for e in events}) == 1


# --- default directory / relative paths ---

def test_list_defaults_to_input_dir(env):
    r = agent.execute_tool("list_fasta_files", {}, agent.TOOLS)
    assert r["ok"] is True and r["data"]["count"] == 2


def test_relative_paths_resolve_against_input_dir(env):
    r = agent.execute_tool("list_fasta_files", {"directory": "."}, agent.TOOLS)
    assert r["ok"] is True
    r = agent.execute_tool("run_ecoml_vp", {"fasta_path": "missing.fasta"}, agent.TOOLS)
    assert r["ok"] is False and str(env.input_dir) in r["error"]


def test_missing_directory_error_tells_model_how_to_recover(env):
    r = agent.execute_tool("list_fasta_files", {"directory": "no_such_dir/"}, agent.TOOLS)
    assert r["ok"] is False
    assert str(env.input_dir) in r["error"] and "'.'" in r["error"]


def test_system_prompt_states_input_dir(env):
    assert str(env.input_dir) in agent.build_system_prompt()


# --- input-dir name prefix tolerance ---

def test_leading_input_dir_name_is_tolerated(env):
    name = env.input_dir.name  # "input"
    for raw in (f"{name}/a.fasta", f"./{name}/a.fasta"):
        assert agent.resolve_under_input(raw) == env.input_dir / "a.fasta"
    assert agent.resolve_under_input(f"./{name}/") == env.input_dir
    r = agent.execute_tool("list_fasta_files", {"directory": f"./{name}/"}, agent.TOOLS)
    assert r["ok"] is True and r["data"]["count"] == 2


def test_real_subdirectory_with_same_name_wins(env):
    nested = env.input_dir / env.input_dir.name
    nested.mkdir()
    assert agent.resolve_under_input(env.input_dir.name) == nested


def test_name_prefix_cannot_escape_input_dir(env):
    r = agent.execute_tool(
        "list_fasta_files", {"directory": f"{env.input_dir.name}/../../etc"}, agent.TOOLS
    )
    assert r["ok"] is False and "access denied" in r["error"]
