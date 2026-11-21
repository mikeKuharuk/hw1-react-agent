"""Тести графа на сценарній моделі: цикл agent ⇄ tools, ліміти, помилки інструментів.

Сценарна модель повертає наперед задані відповіді, тому тести детерміновані й не витрачають API.
"""

import itertools
import json

import pytest
from langchain_core.messages import AIMessage, ToolMessage

import tools
from agent import SupportAgent, SupportAnswer
from logger import TrajectoryLogger
from test_runner import evaluate

_ids = itertools.count(1)


def tool_call(name: str, **args) -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": f"call_{next(_ids)}"}])


FINAL_SERVER = {
    "answer": "Сервери в Європі працюють у штатному режимі.",
    "category": "server",
    "resolved": True,
    "next_action": "none",
    "evidence": [{"tool": "get_server_status", "fact": "eu: operational"}],
    "compensation": None,
}


class ScriptedModel:
    """Повертає відповіді по черзі; repeat=True — останню відповідь повторює безкінечно."""

    model = "scripted"

    def __init__(self, responses, final=None, repeat=False):
        self.responses = list(responses)
        self.final = final or FINAL_SERVER
        self.repeat = repeat
        self.calls = 0

    def bind_tools(self, _tools):
        return self

    def invoke(self, _messages):
        self.calls += 1
        if len(self.responses) > 1 or not self.repeat:
            response = self.responses.pop(0)
        else:
            response = self.responses[0]
        return response() if callable(response) else response

    def with_structured_output(self, schema, method=None, include_raw=False):
        final = self.final

        class Structured:
            def invoke(self, _messages):
                return {"raw": AIMessage(content=""), "parsed": schema(**final), "parsing_error": None}

        return Structured()


def make_agent(model, **kwargs) -> SupportAgent:
    return SupportAgent(model, logger=TrajectoryLogger(), **kwargs)


def tool_messages(agent: SupportAgent, query: str):
    """Запускає граф напряму й повертає повідомлення з результатами інструментів."""
    agent.controller.start()
    agent.logger.start_run("direct", query)
    state = agent.graph.invoke({"messages": [("user", query)], "stop_reason": None, "final": None})
    return [m for m in state["messages"] if isinstance(m, ToolMessage)], state


def test_tool_then_final_answer():
    model = ScriptedModel([tool_call("get_server_status", region="eu"), AIMessage(content="Сервери працюють.")])
    agent = make_agent(model)
    result = agent.run("Чи працюють сервери в Європі?", run_id="T1")
    assert result["stop_reason"] == "final_answer"
    assert result["tool_calls"] == ["get_server_status"]
    assert result["steps"] == 2
    assert SupportAnswer(**result["final"]).category == "server"
    nodes = [s["node"] for s in agent.logger.runs[0]["steps"]]
    assert nodes == ["agent", "tools", "agent", "finalize"]


def test_unknown_tool_returns_structured_error():
    model = ScriptedModel([tool_call("refund_money", player_id="P-1001"), AIMessage(content="Не можу.")])
    agent = make_agent(model)
    messages, _ = tool_messages(agent, "Поверни гроші")
    error = json.loads(messages[0].content)
    assert error["error"]["type"] == "unknown_tool"


def test_validation_error_then_fixed_args():
    model = ScriptedModel([
        tool_call("check_client", platform="android", app_version="latest"),
        tool_call("check_client", platform="android", app_version="2.3.0"),
        AIMessage(content="Оновіть гру."),
    ])
    agent = make_agent(model)
    messages, _ = tool_messages(agent, "Вилітає гра")
    first, second = (json.loads(m.content) for m in messages)
    assert first["error"]["type"] == "validation_error"
    assert "X.Y.Z" in first["error"]["message"]
    assert second["status"] == "ok"


def test_max_steps_stops_with_fallback():
    regions = itertools.cycle(["eu", "na", "asia", "latam"])
    model = ScriptedModel([lambda: tool_call("get_server_status", region=next(regions))], repeat=True)
    agent = make_agent(model, max_steps=2)
    result = agent.run("Перевір усі регіони", run_id="T-max")
    assert result["stop_reason"] == "max_steps"
    assert result["steps"] == 2
    assert result["final"]["next_action"] == "escalate"
    assert "ліміту кроків" in result["final"]["answer"]


def test_loop_detected_on_identical_calls():
    model = ScriptedModel(
        [lambda: tool_call("get_purchase_status", player_id="P-1002", transaction_id="T-1099")], repeat=True
    )
    agent = make_agent(model)
    result = agent.run("Перевіряй, доки не прийде", run_id="T-loop")
    assert result["stop_reason"] == "loop"
    assert result["tool_calls"].count("get_purchase_status") == 3


def test_timeout_on_slow_tool():
    tools.SIMULATED_DELAY_S["get_server_status"] = 1.0
    try:
        model = ScriptedModel([tool_call("get_server_status", region="eu"), AIMessage(content="ok")])
        agent = make_agent(model, timeout_s=0.3)
        result = agent.run("Сервери?", run_id="T-timeout")
    finally:
        tools.SIMULATED_DELAY_S.clear()
    assert result["stop_reason"] == "timeout"
    assert result["time_ms"] < 1000


def test_trajectory_saved(tmp_path):
    model = ScriptedModel([tool_call("get_server_status", region="eu"), AIMessage(content="ok")])
    agent = make_agent(model)
    agent.run("Сервери?", run_id="T-log")
    path = agent.logger.save(tmp_path / "trajectory.json")
    data = json.loads(path.read_text(encoding="utf-8"))
    run = data["runs"][0]
    assert run["stop_reason"] == "final_answer"
    assert run["steps"][1]["input"]["tool"] == "get_server_status"


@pytest.mark.parametrize(
    "evidence_tool, expected_status",
    [("get_server_status", "success"), ("get_player_profile", "partial")],
)
def test_evaluate_flags_ungrounded_evidence(evidence_tool, expected_status):
    result = {
        "stop_reason": "final_answer",
        "tool_calls": ["get_server_status"],
        "final": {**FINAL_SERVER, "evidence": [{"tool": evidence_tool, "fact": "…"}]},
    }
    status, checks = evaluate(result, {"tools": ["get_server_status"], "category": ["server"]})
    assert status == expected_status
