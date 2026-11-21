"""Тестові дані служби підтримки гравців мобільної гри «Forge & Craft».

Дані вигадані й фіксовані, щоб тест-кейси були відтворюваними.
"""

LATEST_VERSION = "2.3.1"
MIN_SUPPORTED_VERSION = "2.1.0"

PLAYERS = {
    "P-1001": {
        "player_id": "P-1001",
        "nickname": "IronSmith",
        "level": 42,
        "platform": "android",
        "app_version": "2.3.0",
        "country": "UA",
        "registered": "2025-03-14",
        "vip": False,
        "banned": False,
    },
    "P-1002": {
        "player_id": "P-1002",
        "nickname": "RuneForger",
        "level": 87,
        "platform": "ios",
        "app_version": "2.3.1",
        "country": "PL",
        "registered": "2024-11-02",
        "vip": True,
        "banned": False,
    },
    "P-1003": {
        "player_id": "P-1003",
        "nickname": "AnvilKing",
        "level": 15,
        "platform": "android",
        "app_version": "2.2.4",
        "country": "DE",
        "registered": "2026-08-20",
        "vip": False,
        "banned": True,
        "ban_reason": "використання стороннього ПЗ (тимчасовий бан до 2026-12-01)",
    },
}

PURCHASES = {
    "T-1042": {
        "transaction_id": "T-1042",
        "player_id": "P-1001",
        "item": "500 кристалів",
        "price_usd": 4.99,
        "store": "Google Play",
        "payment_status": "completed",
        "delivered": False,
        "created_at": "2026-11-20T18:42:00Z",
    },
    "T-1050": {
        "transaction_id": "T-1050",
        "player_id": "P-1002",
        "item": "Набір «Кузня дракона»",
        "price_usd": 9.99,
        "store": "App Store",
        "payment_status": "refunded",
        "delivered": False,
        "created_at": "2026-11-12T09:15:00Z",
    },
    "T-1099": {
        "transaction_id": "T-1099",
        "player_id": "P-1002",
        "item": "1200 кристалів",
        "price_usd": 9.99,
        "store": "App Store",
        "payment_status": "syncing",
        "delivered": False,
        "created_at": "2026-11-21T10:05:00Z",
    },
}

# Відомі краші за платформою та версією клієнта.
CLIENT_CRASHES = {
    ("android", "2.3.0"): [
        "Виліт при відкритті вікна івенту на пристроях з GPU Mali (KI-01)",
    ],
    ("ios", "2.2.4"): [
        "Виліт після сплячого режиму на iOS 18 (KI-05)",
    ],
}

KNOWN_ISSUES = [
    {
        "id": "KI-01",
        "title": "Android 2.3.0: виліт при відкритті івенту",
        "platforms": ["android"],
        "versions": ["2.3.0"],
        "status": "виправлено у 2.3.1",
        "workaround": "Оновити гру до 2.3.1 з Google Play.",
        "tags": ["краш", "крашиться", "вилітає", "виліт", "вилітала", "івент", "event", "crash", "android"],
    },
    {
        "id": "KI-02",
        "title": "Покупка оплачена, але товар не видано",
        "platforms": ["android", "ios"],
        "versions": [],
        "status": "відома проблема, обробляє білінг",
        "workaround": "Перезапустити гру й натиснути «Відновити покупки»; якщо не допомогло — ескалація в білінг з номером транзакції.",
        "tags": ["покупка", "покупку", "купив", "кристали", "кристалів", "не прийшли", "не прийшло", "не видано", "purchase"],
    },
    {
        "id": "KI-03",
        "title": "Втрата прогресу кузні після виліту",
        "platforms": ["android", "ios"],
        "versions": ["2.3.0"],
        "status": "розслідується",
        "workaround": "Прогрес відновлюється з хмари при наступному вході; якщо ні — компенсація.",
        "tags": ["прогрес", "втратив", "зник", "кузня", "кузні", "progress"],
    },
    {
        "id": "KI-04",
        "title": "Пропущений івент через технічну проблему",
        "platforms": ["android", "ios"],
        "versions": [],
        "status": "політика компенсацій",
        "workaround": "Гравцям, які пропустили івент через підтверджений технічний збій, нараховується компенсація кристалами.",
        "tags": ["пропустив", "пропустила", "івент", "event", "компенсація", "компенсацію"],
    },
    {
        "id": "KI-05",
        "title": "iOS 2.2.4: виліт після сплячого режиму",
        "platforms": ["ios"],
        "versions": ["2.2.4"],
        "status": "виправлено у 2.3.0",
        "workaround": "Оновити гру з App Store.",
        "tags": ["ios", "iphone", "сплячий", "вилітає", "краш"],
    },
    {
        "id": "KI-06",
        "title": "Не вдається увійти після бану",
        "platforms": ["android", "ios"],
        "versions": [],
        "status": "політика модерації",
        "workaround": "Під час дії бану вхід неможливий; апеляція — через форму на сайті.",
        "tags": ["бан", "заблоковано", "не можу увійти", "увійти", "акаунт"],
    },
    {
        "id": "KI-07",
        "title": "Затримки в Азії під час технічного обслуговування",
        "platforms": ["android", "ios"],
        "versions": [],
        "status": "планове обслуговування",
        "workaround": "Дочекатися завершення обслуговування (див. статус серверів).",
        "tags": ["лаги", "затримки", "сервер", "сервери", "азія", "asia"],
    },
    {
        "id": "KI-08",
        "title": "Повернення коштів скасовує товар",
        "platforms": ["android", "ios"],
        "versions": [],
        "status": "правило магазину",
        "workaround": "Після повернення коштів товар списується з акаунта автоматично.",
        "tags": ["повернення", "refund", "повернули гроші", "зник набір"],
    },
]

SERVER_STATUS = {
    "eu": {"region": "eu", "status": "operational", "incidents": [], "maintenance": None},
    "na": {"region": "na", "status": "operational", "incidents": [], "maintenance": None},
    "asia": {
        "region": "asia",
        "status": "maintenance",
        "incidents": [],
        "maintenance": {"start": "2026-11-21T02:00:00Z", "end": "2026-11-21T06:00:00Z"},
    },
    "latam": {
        "region": "latam",
        "status": "degraded",
        "incidents": ["Затримки нарахування покупок до 15 хвилин"],
        "maintenance": None,
    },
}

# Базові суми компенсації в кристалах за типом проблеми.
COMPENSATION_BASE = {
    "missed_event": 300,
    "lost_purchase": 100,
    "crash_progress_loss": 200,
    "server_outage": 50,
}
