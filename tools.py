"""Інструменти агента підтримки гравців.

Кожен інструмент має Pydantic-схему входу (закриту: extra="forbid"),
опис для моделі у docstring і повертає JSON-рядок єдиного формату:
    {"status": "ok", "data": ...}  або  {"status": "error", "error": {"type": ..., "message": ...}}
"""

import json
import re
import time
from typing import Literal, Optional

from langchain_core.tools import tool
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from mock_data import (
    CLIENT_CRASHES,
    COMPENSATION_BASE,
    KNOWN_ISSUES,
    LATEST_VERSION,
    MIN_SUPPORTED_VERSION,
    PLAYERS,
    PURCHASES,
    SERVER_STATUS,
)

# Штучна затримка інструментів у секундах — лише для демонстрації тайм-ауту.
SIMULATED_DELAY_S: dict[str, float] = {}


def ok(data) -> str:
    return json.dumps({"status": "ok", "data": data}, ensure_ascii=False)


def error(error_type: str, message: str) -> str:
    return json.dumps(
        {"status": "error", "error": {"type": error_type, "message": message}},
        ensure_ascii=False,
    )


def simulate_delay(tool_name: str) -> None:
    delay = SIMULATED_DELAY_S.get(tool_name, 0.0)
    if delay:
        time.sleep(delay)


def version_tuple(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


class StrictInput(BaseModel):
    """Базова схема: зайві поля заборонені, пробіли на краях обрізаються."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


# ---------- 1. Профіль гравця ----------

class PlayerProfileInput(StrictInput):
    player_id: str = Field(
        description="ID гравця у форматі P-1234 (літера P, дефіс, 4 цифри).",
        pattern=r"^P-\d{4}$",
    )

    @field_validator("player_id", mode="before")
    @classmethod
    def normalize_player_id(cls, value):
        if isinstance(value, str):
            value = value.strip().upper().replace(" ", "")
            if re.fullmatch(r"P\d{4}", value):
                value = f"P-{value[1:]}"
        return value


@tool(args_schema=PlayerProfileInput)
def get_player_profile(player_id: str) -> str:
    """Повертає профіль гравця: рівень, платформу, версію гри, країну, VIP і статус бану.

    Коли використовувати: гравець назвав свій ID і потрібні його рівень, платформа
    чи версія клієнта (наприклад, для розрахунку компенсації або перевірки бану).
    Коли НЕ використовувати: ID не названо — спершу попроси гравця його вказати.
    Помилки: not_found — гравця з таким ID немає (повторювати виклик немає сенсу).
    """
    simulate_delay("get_player_profile")
    profile = PLAYERS.get(player_id)
    if profile is None:
        return error("not_found", f"Гравця {player_id} не знайдено.")
    return ok(profile)


# ---------- 2. Статус покупки ----------

class PurchaseStatusInput(StrictInput):
    player_id: str = Field(description="ID гравця у форматі P-1234.", pattern=r"^P-\d{4}$")
    transaction_id: str = Field(
        description="Номер транзакції у форматі T-1234 (з чека магазину або історії покупок).",
        pattern=r"^T-\d{4}$",
    )

    @field_validator("player_id", "transaction_id", mode="before")
    @classmethod
    def normalize_ids(cls, value):
        return value.strip().upper().replace(" ", "") if isinstance(value, str) else value


@tool(args_schema=PurchaseStatusInput)
def get_purchase_status(player_id: str, transaction_id: str) -> str:
    """Повертає статус оплати й видачі товару за номером транзакції.

    Коли використовувати: гравець скаржиться, що оплачений товар не прийшов,
    зник або гроші повернули; потрібні і ID гравця, і номер транзакції.
    Коли НЕ використовувати: немає номера транзакції — попроси його в гравця.
    Статуси оплати: completed, refunded, failed, syncing (магазин ще передає дані).
    Помилки: not_found — транзакції немає; forbidden — транзакція іншого гравця.
    """
    simulate_delay("get_purchase_status")
    purchase = PURCHASES.get(transaction_id)
    if purchase is None:
        return error("not_found", f"Транзакцію {transaction_id} не знайдено.")
    if purchase["player_id"] != player_id:
        return error("forbidden", f"Транзакція {transaction_id} не належить гравцю {player_id}.")
    data = dict(purchase)
    if data["payment_status"] == "syncing":
        data["hint"] = "Магазин ще передає дані про оплату. Статус оновиться пізніше."
    return ok(data)


# ---------- 3. Перевірка клієнта ----------

class ClientCheckInput(StrictInput):
    platform: Literal["android", "ios"] = Field(description="Платформа гравця: android або ios.")
    app_version: str = Field(
        description="Точна версія гри у форматі X.Y.Z, наприклад 2.3.0 (видно в налаштуваннях гри).",
        pattern=r"^\d+\.\d+\.\d+$",
    )

    @field_validator("platform", mode="before")
    @classmethod
    def normalize_platform(cls, value):
        if isinstance(value, str):
            value = value.strip().lower()
            aliases = {"iphone": "ios", "ipad": "ios", "apple": "ios", "андроїд": "android", "андроід": "android"}
            value = aliases.get(value, value)
        return value

    @field_validator("app_version", mode="before")
    @classmethod
    def normalize_version(cls, value):
        if isinstance(value, str):
            value = value.strip().lower().lstrip("v")
            if value in {"latest", "остання", "найновіша", "нова"}:
                raise ValueError("потрібна точна версія у форматі X.Y.Z (наприклад, 2.3.0), а не «остання»")
        return value


@tool(args_schema=ClientCheckInput)
def check_client(platform: str, app_version: str) -> str:
    """Перевіряє версію клієнта: чи вона підтримується, яка остання і які відомі краші на ній.

    Коли використовувати: гравець повідомляє про виліт, помилку запуску чи питає про
    оновлення, і відомі його платформа та точна версія гри.
    Коли НЕ використовувати: версію не названо або названо «остання» — попроси точну.
    Обмеження: лише android та ios; версія строго у форматі X.Y.Z.
    """
    simulate_delay("check_client")
    current = version_tuple(app_version)
    data = {
        "platform": platform,
        "app_version": app_version,
        "latest_version": LATEST_VERSION,
        "supported": current >= version_tuple(MIN_SUPPORTED_VERSION),
        "update_available": current < version_tuple(LATEST_VERSION),
        "known_crashes": CLIENT_CRASHES.get((platform, app_version), []),
    }
    return ok(data)


# ---------- 4. Пошук відомих проблем ----------

class KnownIssuesInput(StrictInput):
    query: str = Field(
        description="Опис проблеми своїми словами, 3–200 символів (наприклад, «вилітає при відкритті івенту»).",
        min_length=3,
        max_length=200,
    )
    platform: Optional[Literal["android", "ios"]] = Field(
        default=None, description="Платформа для фільтрації (необов'язково)."
    )
    limit: int = Field(default=3, ge=1, le=5, description="Скільки результатів повернути, від 1 до 5.")


@tool(args_schema=KnownIssuesInput)
def search_known_issues(query: str, platform: Optional[str] = None, limit: int = 3) -> str:
    """Шукає в базі відомих проблем гри збіги з описом проблеми гравця.

    Коли використовувати: щоб знайти відоме рішення, обхідний шлях або політику
    (компенсації, бани, повернення коштів) для описаної проблеми.
    Коли НЕ використовувати: для фактів про конкретного гравця чи покупку —
    для цього є профіль і статус покупки.
    Повертає до `limit` записів, відсортованих за кількістю збігів; порожній список — збігів немає.
    """
    simulate_delay("search_known_issues")
    text = query.lower()
    scored = []
    for issue in KNOWN_ISSUES:
        if platform and platform not in issue["platforms"]:
            continue
        score = sum(1 for tag in issue["tags"] if tag in text)
        if score:
            scored.append((score, issue))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    results = [{key: value for key, value in issue.items() if key != "tags"} for _, issue in scored[:limit]]
    return ok({"query": query, "matches": results})


# ---------- 5. Статус серверів ----------

REGION_ALIASES = {
    "europe": "eu", "європа": "eu", "європі": "eu", "європи": "eu", "eu-west": "eu",
    "usa": "na", "us": "na", "америка": "na", "north america": "na",
    "азія": "asia", "азії": "asia",
    "латинська америка": "latam", "latin america": "latam",
}


class ServerStatusInput(StrictInput):
    region: Literal["eu", "na", "asia", "latam"] = Field(
        description="Регіон серверів: eu (Європа), na (Північна Америка), asia (Азія), latam (Латинська Америка)."
    )

    @field_validator("region", mode="before")
    @classmethod
    def normalize_region(cls, value):
        if isinstance(value, str):
            value = value.strip().lower()
            value = REGION_ALIASES.get(value, value)
        return value


@tool(args_schema=ServerStatusInput)
def get_server_status(region: str) -> str:
    """Повертає поточний стан ігрових серверів регіону: працює, деградація чи обслуговування.

    Коли використовувати: гравець питає, чи працюють сервери, скаржиться на лаги,
    розриви з'єднання або на те, що гра не підключається.
    Коли НЕ використовувати: проблема стосується лише конкретного пристрою чи покупки.
    Статуси: operational, degraded, maintenance.
    """
    simulate_delay("get_server_status")
    return ok(SERVER_STATUS[region])


# ---------- 6. Розрахунок компенсації ----------

class CompensationInput(StrictInput):
    issue_type: Literal["missed_event", "lost_purchase", "crash_progress_loss", "server_outage"] = Field(
        description=(
            "Тип проблеми: missed_event — пропустив івент через збій; lost_purchase — оплачений товар не видано; "
            "crash_progress_loss — втрата прогресу через виліт; server_outage — недоступність серверів."
        )
    )
    player_level: int = Field(ge=1, le=200, description="Рівень гравця з профілю, від 1 до 200.")
    hours_affected: float = Field(
        default=0, ge=0, le=72, description="Скільки годин тривала проблема (обов'язково для server_outage), до 72."
    )

    @model_validator(mode="after")
    def outage_needs_hours(self):
        if self.issue_type == "server_outage" and self.hours_affected <= 0:
            raise ValueError("для server_outage потрібно вказати hours_affected > 0")
        return self


@tool(args_schema=CompensationInput)
def calculate_compensation(issue_type: str, player_level: int, hours_affected: float = 0) -> str:
    """Розраховує розмір компенсації в кристалах за політикою студії. Нічого не нараховує.

    Коли використовувати: проблему гравця підтверджено (відома проблема, краш на його
    версії, збій сервера) і гравець питає про компенсацію; рівень береться з профілю.
    Коли НЕ використовувати: проблему не підтверджено фактами з інших інструментів.
    Формула: база за типом × (1 + рівень / 100); для server_outage база множиться
    на години (не більше 24). Результат округлюється до десятків.
    """
    simulate_delay("calculate_compensation")
    base = COMPENSATION_BASE[issue_type]
    if issue_type == "server_outage":
        base *= min(hours_affected, 24)
    amount = int(round(base * (1 + player_level / 100) / 10) * 10)
    return ok({"issue_type": issue_type, "player_level": player_level, "crystals": amount})


ALL_TOOLS = [
    get_player_profile,
    get_purchase_status,
    check_client,
    search_known_issues,
    get_server_status,
    calculate_compensation,
]
TOOLS_BY_NAME = {t.name: t for t in ALL_TOOLS}
