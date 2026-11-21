"""Тест-кейси агента підтримки та демонстрації захисних механізмів.

Відповіді моделі не детерміновані (моделі 5.5 не приймають temperature),
тому перевіряються стабільні речі: які інструменти викликано, категорія,
наступна дія, сума компенсації, чи посилаються докази лише на викликані інструменти.

Запуск:
    python test_runner.py              # 5 тест-кейсів + 3 демо
    python test_runner.py --only TC-001 --skip-demos   # швидкий пробний прогін
"""

import argparse
import json
from collections import Counter
from pathlib import Path

import tools
from agent import SupportAgent, make_model
from logger import TrajectoryLogger

TEST_CASES = [
    {
        "id": "TC-001",
        "complexity": "simple",
        "query": "Привіт! Чи працюють зараз сервери в Європі?",
        "expected": {
            "tools": ["get_server_status"],
            "category": ["server"],
            "next_action": ["none"],
            "resolved": True,
        },
    },
    {
        "id": "TC-002",
        "complexity": "simple",
        "query": "У мене iPhone, версія гри 2.0.4. Вона ще підтримується? Яка зараз остання?",
        "expected": {
            "tools": ["check_client"],
            "category": ["technical"],
            "next_action": ["none"],
            "resolved": True,
        },
    },
    {
        "id": "TC-003",
        "complexity": "medium",
        "query": "Я гравець P-1001. Купив 500 кристалів, транзакція T-1042. Гроші списали, а кристали так і не прийшли.",
        "expected": {
            "tools": ["get_purchase_status"],
            "category": ["purchase"],
            "next_action": ["escalate", "compensation"],
            "resolved": False,
        },
    },
    {
        "id": "TC-004",
        "complexity": "medium",
        "query": "Гра вилітає щоразу, коли відкриваю вікно івенту. Android, версія 2.3.0. Що робити?",
        "expected": {
            "tools": ["check_client", "search_known_issues"],
            "category": ["technical"],
            "next_action": ["none"],
            "resolved": True,
        },
    },
    {
        "id": "TC-005",
        "complexity": "complex",
        "query": (
            "Я P-1001. Через виліт на Android (версія 2.3.0) я пропустив івент «Кузня дракона». "
            "Чи належить мені компенсація і скільки?"
        ),
        "expected": {
            "tools": ["get_player_profile", "calculate_compensation"],
            "category": ["technical"],
            "next_action": ["compensation", "escalate"],
            # 300 кристалів за пропущений івент × (1 + 42/100) = 426 → 430
            "compensation": 430,
        },
    },
]

DEMOS = [
    {
        "id": "DEMO-MAX-STEPS",
        "purpose": "Ліміт кроків: складний кейс TC-005 з max_steps=2.",
        "query": TEST_CASES[4]["query"],
        "agent_kwargs": {"max_steps": 2},
        "delays": {},
        "expected_stop": "max_steps",
    },
    {
        "id": "DEMO-TIMEOUT",
        "purpose": "Тайм-аут: сервер статусів відповідає 8 с, загальний ліміт 5 с.",
        "query": TEST_CASES[0]["query"],
        "agent_kwargs": {"timeout_s": 5},
        "delays": {"get_server_status": 8.0},
        "expected_stop": "timeout",
    },
    {
        "id": "DEMO-LOOP",
        "purpose": "Зациклення: покупка в статусі syncing, гравець просить перевіряти, доки не прийде.",
        "query": (
            "Я P-1002, транзакція T-1099, купив 1200 кристалів. Перевір статус покупки, "
            "і якщо ще не прийшло — перевір ще раз, і ще, доки кристали не прийдуть."
        ),
        "agent_kwargs": {},
        "delays": {},
        "expected_stop": "loop",
    },
]


def evaluate(result: dict, expected: dict) -> tuple[str, dict]:
    """Порівнює результат з очікуваним і повертає статус та деталі перевірок."""
    final = result["final"] or {}
    called = set(result["tool_calls"])
    checks = {"stop_reason": result["stop_reason"] == "final_answer"}
    if "tools" in expected:
        checks["tools"] = set(expected["tools"]).issubset(called)
    if "category" in expected:
        checks["category"] = final.get("category") in expected["category"]
    if "next_action" in expected:
        checks["next_action"] = final.get("next_action") in expected["next_action"]
    if "resolved" in expected:
        checks["resolved"] = final.get("resolved") == expected["resolved"]
    if "compensation" in expected:
        checks["compensation"] = final.get("compensation") == expected["compensation"]
    # Докази мають посилатися лише на інструменти, які справді викликались.
    checks["evidence_grounded"] = all(item.get("tool") in called for item in final.get("evidence", []))
    if not checks["stop_reason"]:
        status = "fail"
    elif all(checks.values()):
        status = "success"
    else:
        status = "partial"
    return status, checks


def run_test_cases(model, logger: TrajectoryLogger, only: list[str] | None = None) -> list[dict]:
    agent = SupportAgent(model, logger=logger)
    results = []
    for case in TEST_CASES:
        if only and case["id"] not in only:
            continue
        result = agent.run(case["query"], run_id=case["id"])
        status, checks = evaluate(result, case["expected"])
        record = {
            "test_id": case["id"],
            "complexity": case["complexity"],
            "query": case["query"],
            "expected": case["expected"],
            "actual": result["final"],
            "status": status,
            "checks": checks,
            "stop_reason": result["stop_reason"],
            "steps": result["steps"],
            "tool_calls": result["tool_calls"],
            "tool_calls_count": dict(Counter(result["tool_calls"])),
            "time_ms": result["time_ms"],
            "tokens": result["tokens"],
        }
        results.append(record)
        print(f"{case['id']} [{case['complexity']}] → {status}: кроків {result['steps']}, "
              f"інструменти {record['tool_calls_count']}, {result['time_ms'] / 1000:.1f} с")
    return results


def run_demos(model, logger: TrajectoryLogger) -> list[dict]:
    results = []
    for demo in DEMOS:
        tools.SIMULATED_DELAY_S.clear()
        tools.SIMULATED_DELAY_S.update(demo["delays"])
        agent = SupportAgent(model, logger=logger, **demo["agent_kwargs"])
        result = agent.run(demo["query"], run_id=demo["id"])
        tools.SIMULATED_DELAY_S.clear()
        record = {
            "demo_id": demo["id"],
            "purpose": demo["purpose"],
            "limits": demo["agent_kwargs"],
            "expected_stop": demo["expected_stop"],
            "actual_stop": result["stop_reason"],
            "triggered": result["stop_reason"] == demo["expected_stop"],
            "steps": result["steps"],
            "tool_calls": result["tool_calls"],
            "time_ms": result["time_ms"],
            "answer": (result["final"] or {}).get("answer"),
        }
        results.append(record)
        print(f"{demo['id']} → зупинка: {result['stop_reason']} (очікувано {demo['expected_stop']}), "
              f"кроків {result['steps']}, {result['time_ms'] / 1000:.1f} с")
    return results


def summarize(results: list[dict]) -> dict:
    statuses = Counter(r["status"] for r in results)
    return {
        "total": len(results),
        "success": statuses.get("success", 0),
        "partial": statuses.get("partial", 0),
        "fail": statuses.get("fail", 0),
        "avg_steps": round(sum(r["steps"] for r in results) / max(len(results), 1), 2),
        "avg_time_ms": round(sum(r["time_ms"] for r in results) / max(len(results), 1), 1),
        "tokens_total": {
            "input": sum(r["tokens"]["input"] for r in results),
            "output": sum(r["tokens"]["output"] for r in results),
        },
    }


def main(model=None, only=None, skip_demos=False, out_dir="."):
    model = model or make_model()
    logger = TrajectoryLogger()
    out = Path(out_dir)
    results = run_test_cases(model, logger, only)
    (out / "test_results.json").write_text(
        json.dumps({"summary": summarize(results), "results": results}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    demos = [] if skip_demos else run_demos(model, logger)
    if demos:
        (out / "demo_results.json").write_text(json.dumps(demos, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.save(out / "trajectory.json")
    return results, demos


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", nargs="*", help="ID тест-кейсів для запуску, наприклад TC-001")
    parser.add_argument("--skip-demos", action="store_true")
    args = parser.parse_args()
    main(only=args.only, skip_demos=args.skip_demos)
