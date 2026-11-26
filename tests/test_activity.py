"""FR-20..FR-25: Cassandra time series (+ MongoDB and Dgraph for stats)."""
from datetime import date

import pytest
from conftest import DEMO_USER

from dishcovery.queries import cassandra_queries as cq
from dishcovery.services import activity, catalog


@pytest.mark.fr("FR-20")
def test_checkin_writes_three_tables(fresh_user, evidence):
    """Input: check-in at rest_0004. Expected: row in visits_by_user, visits_by_user_month and activity_by_user."""
    rest, ts = activity.checkin(fresh_user["_id"], "rest_0004")
    assert activity.passport(fresh_user["_id"], 1)[0].restaurant_id == "rest_0004"
    month_rows = list(cq.execute("q6_month", (fresh_user["_id"], cq.ym(ts))))
    assert any(r.restaurant_id == "rest_0004" for r in month_rows)
    act = activity.recent_activity(fresh_user["_id"], 1)[0]
    assert (act.event_type, act.target_id) == ("checkin", "rest_0004")
    evidence("check-in %s at %s -> 3 tables" % (rest["name"], ts.isoformat()))


@pytest.mark.fr("FR-21")
def test_food_passport_newest_first(evidence):
    """Input: user_0001. Expected: visited places, newest first, with denormalized name and cuisine."""
    rows = activity.passport(DEMO_USER)
    assert rows and all(r.restaurant_name and r.cuisine for r in rows)
    d = [r.visited_at for r in rows]
    assert d == sorted(d, reverse=True)
    evidence("%d visits, latest %s at %s" % (len(rows), rows[0].restaurant_name, rows[0].visited_at))


@pytest.mark.fr("FR-22")
def test_recent_activity_newest_first(evidence):
    """Input: user_0001, limit 20. Expected: <= 20 events in descending time order across month buckets."""
    rows = activity.recent_activity(DEMO_USER, 20)
    assert 0 < len(rows) <= 20
    ts = [r.event_ts for r in rows]
    assert ts == sorted(ts, reverse=True)
    evidence(", ".join("%s:%s" % (r.event_type, r.target_id) for r in rows[:4]))


@pytest.mark.fr("FR-23")
def test_search_history(fresh_user, evidence):
    """Steps: search 'birria' as a logged user. Expected: newest row of searches_by_user is that search."""
    catalog.search(text="birria", user_id=fresh_user["_id"])
    rows = activity.search_history(fresh_user["_id"], 5)
    assert rows[0].query_text == "birria"
    evidence(rows[0].query_text + " @ " + str(rows[0].searched_at))


@pytest.mark.fr("FR-24")
def test_trending_and_view_counter(evidence):
    """Steps: view dish_0001 once, read 7 daily partitions of Tlaquepaque. Expected: today's counter +1, ranking sorted, dish_0001 on top."""
    before = {r.dish_id: r.views for r in cq.execute("q5_views", ("Tlaquepaque", date.today()))}.get("dish_0001", 0)
    catalog.view_dish("dish_0001")
    after = {r.dish_id: r.views for r in cq.execute("q5_views", ("Tlaquepaque", date.today()))}["dish_0001"]
    assert after == before + 1
    ranking, per_day = activity.trending("Tlaquepaque", 7, 5)
    views = [v for _, _, v in ranking]
    assert len(per_day) == 7 and views == sorted(views, reverse=True) and ranking[0][0] == "dish_0001"
    evidence("top: " + ", ".join("%s %d" % (n, v) for _, n, v in ranking[:3]))


@pytest.mark.fr("FR-25")
def test_personal_stats(db, evidence):
    """Input: user_0001. Expected: visits per month (Cassandra), reviews by cuisine (MongoDB $lookup) and rating distribution (Dgraph @groupby) agree with the source data."""
    s = activity.personal_stats(DEMO_USER, months=6)
    assert len(s["visits_per_month"]) == 6 and sum(s["visits_per_month"].values()) > 0
    n_reviews = db.reviews.count_documents({"user_id": DEMO_USER})
    assert sum(r["reviews"] for r in s["reviews_by_cuisine"]) == n_reviews
    assert sum(g["count"] for g in s["rating_distribution"]) == n_reviews
    assert s["graph_cuisines"]
    evidence("visits=%s; ratings=%s" % (s["visits_per_month"], s["rating_distribution"]))
