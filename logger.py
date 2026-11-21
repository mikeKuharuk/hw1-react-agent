"""Журнал траєкторії агента: кожен крок кожного запуску записується у trajectory.json."""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

MAX_FIELD_CHARS = 500


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def truncate(value: Any, limit: int = MAX_FIELD_CHARS) -> Any:
    """Обрізає довгі рядки, щоб лог не роздувався; вкладені структури обробляє рекурсивно."""
    if isinstance(value, str):
        return value if len(value) <= limit else value[:limit] + f"… [+{len(value) - limit} симв.]"
    if isinstance(value, dict):
        return {key: truncate(item, limit) for key, item in value.items()}
    if isinstance(value, list):
        return [truncate(item, limit) for item in value]
    return value


class TrajectoryLogger:
    def __init__(self):
        self.runs: list[dict] = []
        self.current: Optional[dict] = None

    def start_run(self, run_id: str, query: str, **meta) -> None:
        self.current = {
            "run_id": run_id,
            "query": query,
            "started_at": now_iso(),
            **meta,
            "steps": [],
        }
        self.runs.append(self.current)

    def log_step(
        self,
        node: str,
        input_data: Any = None,
        output_data: Any = None,
        tool_calls: Optional[list] = None,
        duration_ms: Optional[float] = None,
        error: Optional[str] = None,
    ) -> None:
        if self.current is None:
            raise RuntimeError("Спершу викличте start_run().")
        step = {
            "step": len(self.current["steps"]) + 1,
            "node": node,
            "timestamp": now_iso(),
            "input": truncate(input_data),
            "output": truncate(output_data),
            "tool_calls": truncate(tool_calls or []),
            "duration_ms": round(duration_ms, 1) if duration_ms is not None else None,
        }
        if error:
            step["error"] = truncate(error)
        self.current["steps"].append(step)

    def end_run(self, stop_reason: str, final_answer: Any, elapsed_ms: float) -> None:
        if self.current is None:
            return
        self.current["finished_at"] = now_iso()
        self.current["stop_reason"] = stop_reason
        self.current["elapsed_ms"] = round(elapsed_ms, 1)
        self.current["final_answer"] = final_answer
        self.current = None

    def save(self, path: str | Path = "trajectory.json") -> Path:
        path = Path(path)
        path.write_text(json.dumps({"runs": self.runs}, ensure_ascii=False, indent=2), encoding="utf-8")
        return path
