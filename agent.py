"""ReAct-агент підтримки гравців на LangGraph.

Граф: START → agent ⇄ tools → finalize → END.
- agent    — модель з прив'язаними інструментами вирішує наступний крок;
- tools    — безпечне виконання інструментів (allowlist, валідація, тайм-аут, лог);
- finalize — структурована відповідь SupportAnswer або запасна відповідь при зупинці за лімітом.
"""

import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from typing import Annotated, Literal, Optional, TypedDict

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field, ValidationError

from logger import TrajectoryLogger
from safety import LOOP_REPEATS, MAX_STEPS, TIMEOUT_S, StopController
from tools import ALL_TOOLS, error

MODEL_NAME = "claude-sonnet-5-5"

ToolName = Literal[
    "get_player_profile",
    "get_purchase_status",
    "check_client",
    "search_known_issues",
    "get_server_status",
    "calculate_compensation",
]


# ---------- Структурована фінальна відповідь ----------

class Evidence(BaseModel):
    tool: ToolName = Field(description="Інструмент, який повернув цей факт.")
    fact: str = Field(description="Коротко сам факт, наприклад «оплата completed, товар не видано».")


class SupportAnswer(BaseModel):
    answer: str = Field(description="Відповідь гравцю українською, 1–4 речення.")
    category: Literal["purchase", "technical", "account", "server", "other"] = Field(
        description="Тип звернення: purchase — покупки; technical — краші й версія клієнта; "
        "account — акаунт і бани; server — стан серверів; other — інше."
    )
    resolved: bool = Field(description="Чи вирішено звернення без участі людини.")
    next_action: Literal["none", "compensation", "escalate", "wait"] = Field(
        description="Наступна дія: none — нічого; compensation — гравцю належить компенсація; "
        "escalate — потрібна людина (білінг, модерація); wait — проблема тимчасова, треба зачекати."
    )
    evidence: list[Evidence] = Field(
        description="Факти з результатів інструментів у цій розмові. Порожній список, якщо інструменти не викликались."
    )
    compensation: Optional[int] = Field(
        default=None,
        description="Сума компенсації в кристалах — лише якщо її повернув calculate_compensation, інакше null.",
    )


SYSTEM_PROMPT = """Ти — агент служби підтримки гравців мобільної гри «Forge & Craft».

Мета: вирішити звернення гравця або чітко сказати, що потрібно далі.

Політики:
- Факти про гравця, покупки, версії, сервери й компенсації бери лише з інструментів. Нічого не вигадуй.
- Якщо бракує ID гравця, номера транзакції чи точної версії гри — попроси їх у гравця, не вгадуй.
- Покупки: перевір статус покупки. Якщо оплата пройшла, а товар не видано, — порадь «Відновити покупки» і запропонуй ескалацію в білінг.
- Статус оплати syncing означає, що магазин ще передає дані; його можна перевірити ще раз.
- Краші: перевір версію клієнта й пошукай відому проблему; порадь рішення з бази відомих проблем.
- Компенсацію рахуй лише після того, як проблему підтвердили інструменти, і з рівнем гравця з профілю.
  Нарахувати компенсацію ти не можеш — лише назвати суму й передати запит оператору.
- Якщо інструмент повернув помилку валідації — виправ аргументи; якщо not_found — повідом гравця.

Критерій завершення: у тебе є факти для відповіді гравцю, або потрібне уточнення від гравця.
Відповідай українською, коротко й по суті."""

FINALIZE_SYSTEM = "Ти перетворюєш протокол звернення до служби підтримки гравців на структуровану відповідь."

FINALIZE_INSTRUCTION = """Сформуй структуровану відповідь за протоколом вище.
- answer — фінальна відповідь гравцю з останньої репліки агента.
- evidence — лише факти, які повернули інструменти в цій розмові, з назвою інструмента.
- compensation — лише якщо calculate_compensation повернув суму, інакше null.
- resolved — чи вирішено звернення без участі людини."""


class AgentState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    stop_reason: Optional[str]
    final: Optional[dict]


def make_model(model_name: str = MODEL_NAME, max_tokens: int = 4096, request_timeout_s: float = 60):
    """Модель Claude без temperature/top_p: моделі 5.5 відхиляють нестандартні значення."""
    from langchain_anthropic import ChatAnthropic

    return ChatAnthropic(model=model_name, max_tokens=max_tokens, timeout=request_timeout_s, max_retries=2)


def format_validation_error(tool_name: str, exc: ValidationError) -> str:
    """Перетворює помилку Pydantic на зрозуміле повідомлення для моделі."""
    parts = []
    for item in exc.errors():
        field = ".".join(str(loc) for loc in item["loc"]) or "аргументи"
        kind = item["type"]
        ctx = item.get("ctx", {})
        if kind == "missing":
            text = "обов'язкове поле відсутнє"
        elif kind == "extra_forbidden":
            text = "такого параметра немає"
        elif kind == "string_pattern_mismatch":
            text = f"не відповідає формату {ctx.get('pattern')}"
        elif kind == "literal_error":
            text = f"допустимі значення: {ctx.get('expected')}"
        elif kind in {"greater_than_equal", "less_than_equal", "greater_than", "less_than"}:
            text = f"значення поза межами ({item['msg']})"
        elif kind == "value_error":
            text = str(ctx.get("error", item["msg"]))
        else:
            text = item["msg"]
        parts.append(f"{field}: {text}")
    return f"Некоректні аргументи для {tool_name}: " + "; ".join(parts) + ". Виправ аргументи й виклич ще раз."


class SupportAgent:
    def __init__(
        self,
        model,
        tools=ALL_TOOLS,
        max_steps: int = MAX_STEPS,
        timeout_s: float = TIMEOUT_S,
        loop_repeats: int = LOOP_REPEATS,
        logger: Optional[TrajectoryLogger] = None,
        structured_method: str = "json_schema",
    ):
        self.model = model
        self.tools = {t.name: t for t in tools}
        self.model_with_tools = model.bind_tools(list(tools))
        # Моделі 5.5 відхиляють примусовий виклик інструмента, тому — нативний structured output.
        self.structured_model = model.with_structured_output(
            SupportAnswer, method=structured_method, include_raw=True
        )
        self.finalize_usage = {"input": 0, "output": 0}
        self.controller = StopController(max_steps=max_steps, timeout_s=timeout_s, loop_repeats=loop_repeats)
        self.logger = logger or TrajectoryLogger()
        self.executor = ThreadPoolExecutor(max_workers=4)
        self.graph = self._build_graph()

    # ---------- Виконання з тайм-аутом ----------

    def _run_with_timeout(self, fn, timeout_s: float):
        if timeout_s <= 0:
            raise FutureTimeout()
        return self.executor.submit(fn).result(timeout=timeout_s)

    # ---------- Вузли графа ----------

    def agent_node(self, state: AgentState) -> dict:
        remaining = self.controller.remaining_s
        started = time.monotonic()
        messages = [SystemMessage(SYSTEM_PROMPT)] + state["messages"]
        try:
            response = self._run_with_timeout(lambda: self.model_with_tools.invoke(messages), remaining)
        except FutureTimeout:
            self.logger.log_step("agent", error=f"Модель не відповіла за {remaining:.1f} с", duration_ms=self._ms(started))
            return {"stop_reason": "timeout"}
        self.controller.register_step()
        self.logger.log_step(
            "agent",
            input_data=self._message_text(state["messages"][-1]),
            output_data=self._message_text(response),
            tool_calls=[{"name": c["name"], "args": c["args"]} for c in response.tool_calls],
            duration_ms=self._ms(started),
        )
        return {"messages": [response]}

    def tools_node(self, state: AgentState) -> dict:
        last = state["messages"][-1]
        results, stop_reason = [], None
        for call in last.tool_calls:
            name, args, call_id = call["name"], call.get("args", {}), call["id"]
            started = time.monotonic()
            if stop_reason:
                content = error("skipped", "Виклик пропущено: агент зупиняється.")
            elif name not in self.tools:
                self.controller.register_tool_call(name, args)
                content = error("unknown_tool", f"Інструмента {name} не існує. Доступні: {', '.join(self.tools)}.")
            else:
                content, stop_reason = self._execute_tool(name, args)
            self.logger.log_step(
                "tools",
                input_data={"tool": name, "args": args},
                output_data=content,
                duration_ms=self._ms(started),
            )
            results.append(ToolMessage(content=content, tool_call_id=call_id, name=name))
            if self.controller.loop_detector.looping:
                stop_reason = stop_reason or "loop"
        return {"messages": results, "stop_reason": stop_reason}

    def _execute_tool(self, name: str, args: dict) -> tuple[str, Optional[str]]:
        tool = self.tools[name]
        try:
            validated = tool.args_schema.model_validate(args)
        except ValidationError as exc:
            self.controller.register_tool_call(name, args)
            return error("validation_error", format_validation_error(name, exc)), None
        clean_args = validated.model_dump()
        self.controller.register_tool_call(name, clean_args)
        remaining = self.controller.remaining_s
        try:
            return self._run_with_timeout(lambda: tool.func(**clean_args), remaining), None
        except FutureTimeout:
            return error("timeout", f"{name} не відповів за {remaining:.1f} с (загальний ліміт часу)."), "timeout"
        except Exception as exc:  # інструмент не повинен валити граф
            return error("execution_error", f"{type(exc).__name__}: {exc}"), None

    def finalize_node(self, state: AgentState) -> dict:
        started = time.monotonic()
        reason = self._stop_reason(state)
        if reason == "final_answer":
            # Протокол передається текстом: запит без блоків tool_use не потребує опису інструментів.
            transcript = self._transcript(state["messages"])
            prompt = [SystemMessage(FINALIZE_SYSTEM), HumanMessage(transcript + "\n\n" + FINALIZE_INSTRUCTION)]
            remaining = self.controller.remaining_s
            try:
                output = self._run_with_timeout(lambda: self.structured_model.invoke(prompt), remaining)
                if output["parsing_error"] is not None:
                    raise output["parsing_error"]
                usage = getattr(output["raw"], "usage_metadata", None) or {}
                self.finalize_usage = {"input": usage.get("input_tokens", 0), "output": usage.get("output_tokens", 0)}
                final = output["parsed"].model_dump()
            except FutureTimeout:
                reason = "timeout"
            except Exception as exc:
                reason = "structured_output_error"
                self.logger.log_step("finalize", error=f"{type(exc).__name__}: {exc}", duration_ms=self._ms(started))
        if reason != "final_answer":
            final = self._fallback_answer(state, reason)
        self.logger.log_step("finalize", input_data={"stop_reason": reason}, output_data=final, duration_ms=self._ms(started))
        return {"final": final, "stop_reason": reason}

    # ---------- Маршрутизація ----------

    def should_continue(self, state: AgentState) -> str:
        if state.get("stop_reason"):
            return "finalize"
        last = state["messages"][-1]
        if not (isinstance(last, AIMessage) and last.tool_calls):
            return "finalize"
        return "finalize" if self.controller.stop_reason() else "tools"

    def after_tools(self, state: AgentState) -> str:
        if state.get("stop_reason") or self.controller.stop_reason():
            return "finalize"
        return "agent"

    def _build_graph(self):
        graph = StateGraph(AgentState)
        graph.add_node("agent", self.agent_node)
        graph.add_node("tools", self.tools_node)
        graph.add_node("finalize", self.finalize_node)
        graph.add_edge(START, "agent")
        graph.add_conditional_edges("agent", self.should_continue, {"tools": "tools", "finalize": "finalize"})
        graph.add_conditional_edges("tools", self.after_tools, {"agent": "agent", "finalize": "finalize"})
        graph.add_edge("finalize", END)
        return graph.compile()

    # ---------- Запуск ----------

    def run(self, query: str, run_id: str = "run") -> dict:
        self.controller.start()
        self.finalize_usage = {"input": 0, "output": 0}
        limits = {
            "max_steps": self.controller.max_steps,
            "timeout_s": self.controller.timeout_s,
            "loop_repeats": self.controller.loop_repeats,
        }
        self.logger.start_run(run_id, query, model=getattr(self.model, "model", type(self.model).__name__), limits=limits)
        state = self.graph.invoke(
            {"messages": [HumanMessage(query)], "stop_reason": None, "final": None},
            config={"recursion_limit": 2 * self.controller.max_steps + 5},
        )
        elapsed_ms = self.controller.elapsed_s * 1000
        tool_calls = [c["name"] for m in state["messages"] if isinstance(m, AIMessage) for c in m.tool_calls]
        result = {
            "run_id": run_id,
            "query": query,
            "final": state["final"],
            "stop_reason": state["stop_reason"],
            "steps": self.controller.steps,
            "tool_calls": tool_calls,
            "time_ms": round(elapsed_ms, 1),
            "tokens": self._token_usage(state["messages"], self.finalize_usage),
        }
        self.logger.end_run(state["stop_reason"], state["final"], elapsed_ms)
        return result

    # ---------- Допоміжне ----------

    def _stop_reason(self, state: AgentState) -> str:
        if state.get("stop_reason"):
            return state["stop_reason"]
        last = state["messages"][-1]
        if isinstance(last, AIMessage) and not last.tool_calls:
            return "final_answer"
        return self.controller.stop_reason() or "final_answer"

    def _fallback_answer(self, state: AgentState, reason: str) -> dict:
        """Запасна відповідь без виклику моделі: причина зупинки + факти, зібрані до зупинки."""
        if reason == "structured_output_error":
            message = "Не вдалося сформувати структуровану відповідь."
        else:
            message = self.controller.stop_message(reason)
        evidence = []
        for msg in state["messages"]:
            if isinstance(msg, ToolMessage) and '"status": "ok"' in msg.content:
                evidence.append({"tool": msg.name, "fact": msg.content[:200]})
        return SupportAnswer(
            answer=message + " Звернення передано оператору підтримки.",
            category="other",
            resolved=False,
            next_action="escalate",
            evidence=evidence,
            compensation=None,
        ).model_dump()

    @staticmethod
    def _token_usage(messages, finalize_usage: dict) -> dict:
        """Токени всіх викликів моделі, включно з фінальним structured output."""
        usage = dict(finalize_usage)
        for m in messages:
            meta = getattr(m, "usage_metadata", None) or {}
            usage["input"] += meta.get("input_tokens", 0)
            usage["output"] += meta.get("output_tokens", 0)
        return usage

    @classmethod
    def _transcript(cls, messages) -> str:
        """Текстовий протокол розмови: репліки гравця й агента, виклики інструментів і їхні результати."""
        lines = ["ПРОТОКОЛ ЗВЕРНЕННЯ"]
        for m in messages:
            if isinstance(m, HumanMessage):
                lines.append(f"Гравець: {cls._message_text(m)}")
            elif isinstance(m, AIMessage):
                text = cls._message_text(m).strip()
                if text:
                    lines.append(f"Агент: {text}")
                for call in m.tool_calls:
                    lines.append(f"Виклик інструмента {call['name']}: {call['args']}")
            elif isinstance(m, ToolMessage):
                lines.append(f"Результат {m.name}: {m.content}")
        return "\n".join(lines)

    @staticmethod
    def _message_text(message) -> str:
        content = getattr(message, "content", message)
        if isinstance(content, list):
            content = " ".join(part.get("text", "") for part in content if isinstance(part, dict))
        return str(content)

    @staticmethod
    def _ms(started: float) -> float:
        return (time.monotonic() - started) * 1000
