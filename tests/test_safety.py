"""Тести захисних механізмів: детектор зациклення і контролер зупинки."""

import time

from safety import LoopDetector, StopController


def test_loop_detected_after_three_identical_calls():
    detector = LoopDetector(repeats=3)
    args = {"player_id": "P-1002", "transaction_id": "T-1099"}
    assert detector.register("get_purchase_status", args) is False
    assert detector.register("get_purchase_status", args) is False
    assert detector.register("get_purchase_status", args) is True


def test_different_args_reset_streak():
    detector = LoopDetector(repeats=3)
    detector.register("get_server_status", {"region": "eu"})
    detector.register("get_server_status", {"region": "eu"})
    detector.register("get_server_status", {"region": "na"})
    assert detector.looping is False


def test_args_order_does_not_matter():
    detector = LoopDetector(repeats=2)
    detector.register("t", {"a": 1, "b": 2})
    assert detector.register("t", {"b": 2, "a": 1}) is True


def test_max_steps_reason():
    controller = StopController(max_steps=2, timeout_s=60)
    controller.start()
    controller.register_step()
    assert controller.stop_reason() is None
    controller.register_step()
    assert controller.stop_reason() == "max_steps"


def test_timeout_reason():
    controller = StopController(max_steps=10, timeout_s=0.05)
    controller.start()
    time.sleep(0.06)
    assert controller.stop_reason() == "timeout"
    assert controller.remaining_s == 0


def test_loop_has_priority_in_message():
    controller = StopController(loop_repeats=2)
    controller.start()
    controller.register_tool_call("get_purchase_status", {"x": 1})
    controller.register_tool_call("get_purchase_status", {"x": 1})
    assert controller.stop_reason() == "loop"
    assert "get_purchase_status" in controller.stop_message("loop")
