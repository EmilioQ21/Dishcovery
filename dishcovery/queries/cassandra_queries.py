"""Cassandra access patterns Q1..Q6. Every read uses the full partition key
(no ALLOW FILTERING, no secondary indexes)."""
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache

from cassandra.concurrent import execute_concurrent_with_args
from cassandra.util import uuid_from_time

from dishcovery.connection.cassandra import get_session

MAX_MONTH_BUCKETS = 12   # how far back a "newest first" read walks (one partition per month)
MAX_YEAR_BUCKETS = 3

CQL = {
    # writes
    "ins_activity": "INSERT INTO activity_by_user (user_id, year_month, event_ts, event_id, event_type, target_type, target_id, details) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
    "ins_visit": "INSERT INTO visits_by_user (user_id, year, visited_at, restaurant_id, restaurant_name, cuisine, city) VALUES (?, ?, ?, ?, ?, ?, ?)",
    "ins_visit_month": "INSERT INTO visits_by_user_month (user_id, year_month, visited_at, restaurant_id, cuisine) VALUES (?, ?, ?, ?, ?)",
    "ins_review": "INSERT INTO reviews_by_restaurant (restaurant_id, year_month, created_at, review_id, user_id, user_name, dish_id, dish_name, rating, text) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
    "del_review": "DELETE FROM reviews_by_restaurant WHERE restaurant_id = ? AND year_month = ? AND created_at = ? AND review_id = ?",
    "ins_search": "INSERT INTO searches_by_user (user_id, searched_at, search_id, query_text, filters) VALUES (?, ?, ?, ?, ?)",
    "inc_view": "UPDATE dish_views_by_day SET views = views + ? WHERE city = ? AND day = ? AND dish_id = ?",
    "del_activity_part": "DELETE FROM activity_by_user WHERE user_id = ? AND year_month = ?",
    "del_visit_part": "DELETE FROM visits_by_user WHERE user_id = ? AND year = ?",
    "del_visit_month_part": "DELETE FROM visits_by_user_month WHERE user_id = ? AND year_month = ?",
    "del_search_part": "DELETE FROM searches_by_user WHERE user_id = ?",
    # reads (Q1..Q6)
    "q1_activity": "SELECT * FROM activity_by_user WHERE user_id = ? AND year_month = ? LIMIT ?",
    "q2_passport": "SELECT * FROM visits_by_user WHERE user_id = ? AND year = ? LIMIT ?",
    "q3_reviews": "SELECT * FROM reviews_by_restaurant WHERE restaurant_id = ? AND year_month = ? LIMIT ?",
    "q4_searches": "SELECT * FROM searches_by_user WHERE user_id = ? LIMIT ?",
    "q5_views": "SELECT dish_id, views FROM dish_views_by_day WHERE city = ? AND day = ?",
    "q6_month": "SELECT * FROM visits_by_user_month WHERE user_id = ? AND year_month = ?",
}


@lru_cache(maxsize=None)
def prepared(key):
    return get_session().prepare(CQL[key])


def execute(key, params, trace=False):
    return get_session().execute(prepared(key), params, trace=trace)


def execute_many(key, rows, concurrency=64):
    if rows:
        execute_concurrent_with_args(get_session(), prepared(key), rows, concurrency=concurrency, raise_on_first_error=True)


# ------------------------------------------------------------------ buckets
def utc(dt):
    if isinstance(dt, str):
        dt = datetime.fromisoformat(dt.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def ym(dt):
    return utc(dt).strftime("%Y-%m")


def month_buckets(start=None, n=MAX_MONTH_BUCKETS):
    d = utc(start or datetime.now(timezone.utc)).replace(day=1)
    out = []
    for _ in range(n):
        out.append(d.strftime("%Y-%m"))
        d = (d - timedelta(days=1)).replace(day=1)
    return out


def _walk(key, partition_prefix, buckets, limit):
    rows = []
    for b in buckets:
        rows.extend(execute(key, (*partition_prefix, b, limit - len(rows))))
        if len(rows) >= limit:
            break
    return rows[:limit]


# ------------------------------------------------------------------ writes
def activity_row(user_id, ts, event_type, target_type, target_id, details=None):
    ts = utc(ts)
    return (user_id, ym(ts), ts, uuid_from_time(ts), event_type, target_type, target_id,
            {k: str(v) for k, v in (details or {}).items()})


def log_activity(user_id, event_type, target_type, target_id, details=None, ts=None):
    execute("ins_activity", activity_row(user_id, ts or datetime.now(timezone.utc), event_type, target_type, target_id, details))


def visit_rows(user_id, ts, restaurant):
    ts = utc(ts)
    cuisine = restaurant["cuisine"][0]
    return ((user_id, ts.year, ts, restaurant["_id"], restaurant["name"], cuisine, restaurant["address"]["city"]),
            (user_id, ym(ts), ts, restaurant["_id"], cuisine))


def record_checkin(user_id, restaurant, ts=None):
    """FR-20: one check-in = 3 writes (passport, monthly stats, activity)."""
    ts = utc(ts or datetime.now(timezone.utc))
    v, vm = visit_rows(user_id, ts, restaurant)
    execute("ins_visit", v)
    execute("ins_visit_month", vm)
    log_activity(user_id, "checkin", "restaurant", restaurant["_id"], {"name": restaurant["name"]}, ts)
    return ts


def review_row(review, user_name, dish_name):
    ts = utc(review["created_at"])
    return (review["restaurant_id"], ym(ts), ts, review["_id"], review["user_id"], user_name,
            review.get("dish_id"), dish_name, review["rating"], review["text"])


def upsert_review(review, user_name, dish_name):
    """FR-15/FR-16: the row is keyed by (restaurant_id, month, created_at, review_id), so an edit
    overwrites the same row (Cassandra INSERT = upsert)."""
    execute("ins_review", review_row(review, user_name, dish_name))


def delete_review(review):
    ts = utc(review["created_at"])
    execute("del_review", (review["restaurant_id"], ym(ts), ts, review["_id"]))


def record_search(user_id, query_text, filters=None, ts=None):
    ts = utc(ts or datetime.now(timezone.utc))
    execute("ins_search", (user_id, ts, uuid_from_time(ts), query_text, {k: str(v) for k, v in (filters or {}).items()}))
    return ts


def add_dish_view(city, dish_id, day=None, n=1):
    execute("inc_view", (n, city, day or date.today(), dish_id))


def delete_user_data(user_id):
    """Account deletion (FR-05): drop the user's partitions (partition deletes, no scans)."""
    for b in month_buckets(n=24):
        execute("del_activity_part", (user_id, b))
        execute("del_visit_month_part", (user_id, b))
    year = datetime.now(timezone.utc).year
    for y in range(year - MAX_YEAR_BUCKETS, year + 1):
        execute("del_visit_part", (user_id, y))
    execute("del_search_part", (user_id,))


# ------------------------------------------------------------------ reads
def recent_activity(user_id, limit=20):                       # Q1 FR-22
    return _walk("q1_activity", (user_id,), month_buckets(), limit)


def passport(user_id, limit=50):                              # Q2 FR-21
    year = datetime.now(timezone.utc).year
    return _walk("q2_passport", (user_id,), [year - i for i in range(MAX_YEAR_BUCKETS)], limit)


def restaurant_reviews(restaurant_id, limit=10):              # Q3 FR-17
    return _walk("q3_reviews", (restaurant_id,), month_buckets(), limit)


def search_history(user_id, limit=10):                        # Q4 FR-23
    return list(execute("q4_searches", (user_id, limit)))


def trending(city, days=7, top=10, today=None):              # Q5 FR-24
    today = today or date.today()
    totals = Counter()
    per_day = {}
    for i in range(days):
        day = today - timedelta(days=i)
        rows = list(execute("q5_views", (city, day)))
        per_day[day.isoformat()] = sum(r.views for r in rows)
        for r in rows:
            totals[r.dish_id] += r.views
    return totals.most_common(top), per_day


def monthly_stats(user_id, months=6):                         # Q6 FR-25
    visits_per_month, cuisines = {}, Counter()
    for b in month_buckets(n=months):
        rows = list(execute("q6_month", (user_id, b)))
        visits_per_month[b] = len(rows)
        cuisines.update(r.cuisine for r in rows)
    return visits_per_month, cuisines.most_common()
