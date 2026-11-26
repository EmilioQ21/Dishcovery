"""Shared fixtures + a reporter that writes tests/results/results.md (one row per requirement).

Prerequisite: the 4 databases are running and loaded:
    python -m dishcovery.loading.load_all
Run:
    pytest                    (or: pytest -k FR15 -v)
"""
import json
import time
import uuid
from datetime import datetime
from pathlib import Path

import pytest

import dishcovery.services  # noqa: F401  (registers sync handlers)
from dishcovery.connection import dgraph as dg
from dishcovery.connection.chroma import get_collection
from dishcovery.connection.mongo import get_db

RESULTS_DIR = Path(__file__).resolve().parent / "results"
_results = []

DEMO_USER = "user_0001"
PASSWORD = "dishcovery123"


def pytest_configure(config):
    config.addinivalue_line("markers", "fr(id): functional requirement covered by the test")


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    rep = outcome.get_result()
    if rep.when == "call" or (rep.when == "setup" and rep.outcome != "passed"):
        marker = item.get_closest_marker("fr")
        _results.append({
            "fr": marker.args[0] if marker else "-",
            "test": item.name,
            "acceptance": (item.function.__doc__ or "").strip().split("\n")[0],
            "outcome": {"passed": "PASS", "failed": "FAIL", "skipped": "SKIP"}[rep.outcome],
            "seconds": round(rep.duration, 3),
            "evidence": getattr(item, "evidence", ""),
            "error": str(rep.longrepr).splitlines()[-1][:200] if rep.failed else "",
        })


def pytest_sessionfinish(session, exitstatus):
    if not _results:
        return
    RESULTS_DIR.mkdir(exist_ok=True)
    (RESULTS_DIR / "results.json").write_text(json.dumps(_results, indent=2, ensure_ascii=False), encoding="utf-8")
    passed = sum(r["outcome"] == "PASS" for r in _results)
    lines = ["# Dishcovery acceptance test results", "",
             "Run at %s - %d tests, %d passed, %d failed, %d skipped" % (
                 datetime.now().strftime("%Y-%m-%d %H:%M"), len(_results), passed,
                 sum(r["outcome"] == "FAIL" for r in _results), sum(r["outcome"] == "SKIP" for r in _results)), "",
             "| Req | Test | Acceptance test | Result | Evidence | Time (s) |", "|---|---|---|---|---|---|"]
    for r in sorted(_results, key=lambda r: (r["fr"], r["test"])):
        ev = (r["evidence"] or r["error"]).replace("|", "/").replace("\n", " ")
        lines.append("| %s | %s | %s | **%s** | %s | %s |" % (r["fr"], r["test"], r["acceptance"], r["outcome"], ev, r["seconds"]))
    (RESULTS_DIR / "results.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


# ------------------------------------------------------------------ fixtures
@pytest.fixture
def evidence(request):
    """Call evidence("text") inside a test to store what was observed in the results file."""
    def _set(text):
        request.node.evidence = str(text)[:300]
    return _set


@pytest.fixture(scope="session")
def db():
    return get_db()


@pytest.fixture
def fresh_user():
    """A brand-new user created through the service (all databases) and deleted afterwards."""
    from dishcovery.services import users
    tag = uuid.uuid4().hex[:8]
    u = users.register("test_%s@example.com" % tag, PASSWORD, "Test User %s" % tag, "Zapopan")
    yield u
    try:
        users.delete_account(u["_id"])
    except Exception:  # noqa: BLE001 - already deleted by the test
        pass


@pytest.fixture
def temp_restaurant():
    from dishcovery.services import catalog
    r = catalog.create_restaurant("Test Taqueria %s" % uuid.uuid4().hex[:6], ["mexican", "street food"], 1,
                                  -103.4170, 20.6080, "Tlaquepaque", "Av. Test 1", "ITESO / Periferico Sur",
                                  "Test place for spicy tacos", {"terrace": True})
    yield r
    purge_restaurant(r["_id"])


def purge_restaurant(rid):
    db = get_db()
    dish_ids = [d["_id"] for d in db.dishes.find({"restaurant_id": rid}, {"_id": 1})]
    db.dishes.delete_many({"restaurant_id": rid})
    db.restaurants.delete_one({"_id": rid})
    for did in dish_ids:
        dg.upsert('{ d as var(func: eq(dish_id, "%s")) }' % did, del_nquads="uid(d) * * .")
    dg.upsert('{ r as var(func: eq(restaurant_id, "%s")) }' % rid, del_nquads="uid(r) * * .")
    if dish_ids:
        get_collection("dishes").delete(ids=dish_ids)
    get_collection("restaurants").delete(ids=[rid])


def dgraph_one(dql):
    data, _ = dg.query(dql)
    key = next(iter(data))
    return (data[key] or [None])[0]


def wait(seconds=0.2):
    time.sleep(seconds)
