"""API contract tests, run against the committed deploy bundle (data/deploy).

The bundle is the exact data the hosted app serves, so these tests check what a
user would actually get back -- not a mock of it.
"""
from __future__ import annotations

import csv
import io

import pytest
from fastapi.testclient import TestClient

from api import db
from api.main import app, readable_value, reason
from src.config import ROOT

DEPLOY = ROOT / "data" / "deploy"
pytestmark = pytest.mark.skipif(not (DEPLOY / "hcp_call_plan.parquet").exists(),
                                reason="deploy bundle not present")


@pytest.fixture(scope="module")
def client():
    mp = pytest.MonkeyPatch()
    mp.setenv("PHARMATARGET_DATA_DIR", str(DEPLOY))
    mp.setattr(db, "_con", None)           # a fresh connection on the bundle
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    db._con = None
    mp.undo()


def _csv(text: str) -> list[dict]:
    return list(csv.DictReader(io.StringIO(text)))


# ------------------------------------------------------------------ health

def test_health_reports_core_views_and_request_id(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok" and body["missing_core_views"] == []
    assert r.headers["x-request-id"]


def test_request_id_is_echoed(client):
    r = client.get("/api/health", headers={"X-Request-ID": "abc123"})
    assert r.headers["x-request-id"] == "abc123"


# ------------------------------------------------------------- targets list

def test_hcps_filters_sort_and_paginate(client):
    r = client.get("/api/hcps", params={"specialty": "Cardiology", "decile_min": 9,
                                        "sort": "opportunity", "page_size": 25})
    body = r.json()
    assert r.status_code == 200 and len(body["rows"]) == 25
    assert all(row["specialty_group"] == "Cardiology" for row in body["rows"])
    assert all(row["opportunity_decile"] >= 9 for row in body["rows"])
    opp = [row["opportunity"] for row in body["rows"]]
    assert opp == sorted(opp, reverse=True)


def test_hcps_rejects_unknown_sort_column(client):
    # The sort key is interpolated into SQL, so it must be allow-listed.
    assert client.get("/api/hcps", params={"sort": "npi; DROP TABLE x"}).status_code == 400


def test_export_matches_the_on_screen_filters(client):
    """The export used to ignore specialty and search, so it downloaded a
    different list from the one on screen."""
    params = {"specialty": "Cardiology", "decile_min": 10, "state": "TX"}
    shown = client.get("/api/hcps", params={**params, "page_size": 500}).json()
    rows = _csv(client.get("/api/hcps/export/csv", params=params).text)
    assert len(rows) == shown["total"]
    assert {r["specialty_group"] for r in rows} == {"Cardiology"}
    assert {r["state"] for r in rows} == {"TX"}


# ---------------------------------------------------------------- call list

def test_calllist_options_cover_every_territory(client):
    body = client.get("/api/calllist", params={"n_reps": 60}).json()
    assert len(body["options"]) == 60
    assert body["rows"] == []


def test_calllist_is_in_priority_order_with_reasons(client):
    body = client.get("/api/calllist", params={"territory": 3}).json()
    rows = body["rows"]
    assert rows and [r["priority"] for r in rows] == list(range(1, len(rows) + 1))
    assert all(r["is_target"] for r in rows)
    opp = [r["opportunity"] for r in rows]
    assert opp == sorted(opp, reverse=True)
    assert sum(r["why"] is not None for r in rows) / len(rows) > 0.9
    assert len(rows) == body["territory"]["n_targets"]


def test_calllist_csv_matches_json(client):
    js = client.get("/api/calllist", params={"territory": 3}).json()["rows"]
    r = client.get("/api/calllist/csv", params={"territory": 3})
    assert r.status_code == 200 and "territory_3" in r.headers["content-disposition"]
    rows = _csv(r.text)
    assert [int(x["npi"]) for x in rows] == [x["npi"] for x in js]


@pytest.mark.parametrize("params,code", [
    ({"territory": 999}, 404),
    ({"territory": 3, "n_reps": 61}, 400),
    ({"territory": -1}, 422),
])
def test_calllist_bad_requests(client, params, code):
    assert client.get("/api/calllist", params=params).status_code == code


# --------------------------------------------------------------- reasons

def test_readable_value_undoes_log1p():
    assert readable_value("log_panel_benes", "6.13") == "458"
    assert readable_value("pct_panel_65", "0.957") == "96%"
    assert readable_value("specialty_group", "Cardiology") == "Cardiology"
    assert readable_value(None, None) == "--"


def test_reason_names_anticoagulant_clinics():
    # Few claims outside the class with a HIGH multiplier is a clinic, not a
    # small prescriber; the sentence must say so rather than read as a bug.
    s = reason("log_non_class_clms", "Total prescribing volume", "4.03", 3.59)
    assert s.startswith("Anticoagulant-focused practice: only 55")
    s = reason("log_non_class_clms", "Total prescribing volume", "9.94", 2.1)
    assert s.startswith("Total prescribing volume: 20,")
    assert reason(None, None, None, None) is None


# ------------------------------------------------------------- errors

def test_unknown_api_route_is_404_json(client):
    r = client.get("/api/hcps/123")        # not a real NPI
    assert r.status_code == 404 and "detail" in r.json()
