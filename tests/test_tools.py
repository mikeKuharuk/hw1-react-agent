"""Юніт-тести інструментів: валідація входів, нормалізація і формат результату."""

import json

import pytest
from pydantic import ValidationError

from tools import (
    ClientCheckInput,
    CompensationInput,
    KnownIssuesInput,
    PlayerProfileInput,
    PurchaseStatusInput,
    ServerStatusInput,
    calculate_compensation,
    check_client,
    get_player_profile,
    get_purchase_status,
    get_server_status,
    search_known_issues,
)


def call(tool, **args) -> dict:
    return json.loads(tool.invoke(args))


# ---------- get_player_profile ----------

def test_profile_ok():
    result = call(get_player_profile, player_id="P-1001")
    assert result["status"] == "ok"
    assert result["data"]["level"] == 42


def test_profile_id_normalized():
    assert PlayerProfileInput(player_id=" p1001 ").player_id == "P-1001"


def test_profile_not_found():
    result = call(get_player_profile, player_id="P-9999")
    assert result["status"] == "error"
    assert result["error"]["type"] == "not_found"


@pytest.mark.parametrize("bad_id", ["1001", "P-12", "player-1001", ""])
def test_profile_bad_id_rejected(bad_id):
    with pytest.raises(ValidationError):
        PlayerProfileInput(player_id=bad_id)


def test_extra_field_forbidden():
    with pytest.raises(ValidationError):
        PlayerProfileInput(player_id="P-1001", lang="uk")


# ---------- get_purchase_status ----------

def test_purchase_delivered_flag():
    result = call(get_purchase_status, player_id="P-1001", transaction_id="T-1042")
    assert result["data"]["payment_status"] == "completed"
    assert result["data"]["delivered"] is False


def test_purchase_of_other_player_forbidden():
    result = call(get_purchase_status, player_id="P-1001", transaction_id="T-1050")
    assert result["error"]["type"] == "forbidden"


def test_purchase_syncing_has_hint():
    result = call(get_purchase_status, player_id="P-1002", transaction_id="T-1099")
    assert result["data"]["payment_status"] == "syncing"
    assert "hint" in result["data"]


def test_purchase_bad_transaction_rejected():
    with pytest.raises(ValidationError):
        PurchaseStatusInput(player_id="P-1001", transaction_id="1042")


# ---------- check_client ----------

def test_client_known_crash():
    result = call(check_client, platform="android", app_version="2.3.0")
    assert result["data"]["update_available"] is True
    assert result["data"]["known_crashes"]


def test_client_unsupported_version():
    result = call(check_client, platform="ios", app_version="2.0.4")
    assert result["data"]["supported"] is False


def test_client_normalization():
    data = ClientCheckInput(platform="iPhone", app_version="v2.3.1")
    assert (data.platform, data.app_version) == ("ios", "2.3.1")


@pytest.mark.parametrize("version", ["latest", "остання", "2.3", "2.x.1"])
def test_client_bad_version_rejected(version):
    with pytest.raises(ValidationError):
        ClientCheckInput(platform="android", app_version=version)


def test_client_bad_platform_rejected():
    with pytest.raises(ValidationError):
        ClientCheckInput(platform="windows", app_version="2.3.1")


# ---------- search_known_issues ----------

def test_known_issues_finds_crash():
    result = call(search_known_issues, query="гра вилітає при відкритті івенту", platform="android")
    ids = [issue["id"] for issue in result["data"]["matches"]]
    assert "KI-01" in ids


def test_known_issues_no_match_is_ok():
    result = call(search_known_issues, query="погода в Києві")
    assert result["status"] == "ok"
    assert result["data"]["matches"] == []


@pytest.mark.parametrize("args", [{"query": "ab"}, {"query": "краш", "limit": 10}])
def test_known_issues_bad_args_rejected(args):
    with pytest.raises(ValidationError):
        KnownIssuesInput(**args)


# ---------- get_server_status ----------

def test_server_status_alias():
    assert ServerStatusInput(region="Європа").region == "eu"
    assert call(get_server_status, region="eu")["data"]["status"] == "operational"


def test_server_status_bad_region_rejected():
    with pytest.raises(ValidationError):
        ServerStatusInput(region="mars")


# ---------- calculate_compensation ----------

def test_compensation_missed_event_level_42():
    result = call(calculate_compensation, issue_type="missed_event", player_level=42)
    assert result["data"]["crystals"] == 430


def test_compensation_outage_needs_hours():
    with pytest.raises(ValidationError):
        CompensationInput(issue_type="server_outage", player_level=10)


def test_compensation_outage_capped_at_24h():
    full = call(calculate_compensation, issue_type="server_outage", player_level=10, hours_affected=24)
    over = call(calculate_compensation, issue_type="server_outage", player_level=10, hours_affected=48)
    assert full["data"]["crystals"] == over["data"]["crystals"]


@pytest.mark.parametrize("level", [0, 201])
def test_compensation_level_bounds(level):
    with pytest.raises(ValidationError):
        CompensationInput(issue_type="missed_event", player_level=level)
