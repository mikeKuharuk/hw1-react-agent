"""Захисні механізми агента: ліміт кроків, загальний тайм-аут і детекція зациклення."""

import json
import time
from dataclasses import dataclass, field
from typing import Optional

MAX_STEPS = 10
TIMEOUT_S = 120.0
LOOP_REPEATS = 3

STOP_MESSAGES = {
    "max_steps": "Агент досяг ліміту кроків ({max_steps}) і зупинився, не завершивши задачу.",
    "timeout": "Агент перевищив ліміт часу ({timeout_s:.0f} с) і зупинився, не завершивши задачу.",
    "loop": "Виявлено зациклення: {repeats} однакові виклики {tool} поспіль. Агент зупинився.",
}


class LoopDetector:
    """Рахує однакові виклики інструментів поспіль (та сама назва й ті самі аргументи)."""

    def __init__(self, repeats: int = LOOP_REPEATS):
        self.repeats = repeats
        self.last_signature: Optional[str] = None
        self.streak = 0
        self.last_tool: Optional[str] = None

    @staticmethod
    def signature(tool_name: str, args: dict) -> str:
        return tool_name + ":" + json.dumps(args, sort_keys=True, ensure_ascii=False)

    def register(self, tool_name: str, args: dict) -> bool:
        """Додає виклик і повертає True, якщо серія однакових викликів досягла порога."""
        sig = self.signature(tool_name, args)
        self.streak = self.streak + 1 if sig == self.last_signature else 1
        self.last_signature = sig
        self.last_tool = tool_name
        return self.streak >= self.repeats

    @property
    def looping(self) -> bool:
        return self.streak >= self.repeats


@dataclass
class StopController:
    """Один контролер на всі критерії зупинки; перевіряється після кожного кроку."""

    max_steps: int = MAX_STEPS
    timeout_s: float = TIMEOUT_S
    loop_repeats: int = LOOP_REPEATS
    steps: int = 0
    started_at: float = field(default_factory=time.monotonic)
    loop_detector: LoopDetector = field(init=False)

    def __post_init__(self):
        self.loop_detector = LoopDetector(self.loop_repeats)

    def start(self) -> None:
        self.steps = 0
        self.started_at = time.monotonic()
        self.loop_detector = LoopDetector(self.loop_repeats)

    def register_step(self) -> None:
        self.steps += 1

    def register_tool_call(self, tool_name: str, args: dict) -> None:
        self.loop_detector.register(tool_name, args)

    @property
    def elapsed_s(self) -> float:
        return time.monotonic() - self.started_at

    @property
    def remaining_s(self) -> float:
        return max(0.0, self.timeout_s - self.elapsed_s)

    def stop_reason(self) -> Optional[str]:
        """Повертає причину зупинки або None, якщо можна продовжувати."""
        if self.loop_detector.looping:
            return "loop"
        if self.elapsed_s >= self.timeout_s:
            return "timeout"
        if self.steps >= self.max_steps:
            return "max_steps"
        return None

    def stop_message(self, reason: str) -> str:
        return STOP_MESSAGES[reason].format(
            max_steps=self.max_steps,
            timeout_s=self.timeout_s,
            repeats=self.loop_repeats,
            tool=self.loop_detector.last_tool,
        )
