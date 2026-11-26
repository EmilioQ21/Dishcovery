"""Load data/dishcovery_data.json into the four databases using the same ids everywhere.

    python -m dishcovery.loading.load_all              # recreate schemas (wipes data) and load everything
    python -m dishcovery.loading.load_all --only chroma

The file is created by `python -m dishcovery.loading.generate_data` (run automatically if missing).
MongoDB is loaded first (source of truth); the other stores receive derived copies.
"""
import argparse
import json
import time
from datetime import date, datetime, timedelta

import bcrypt

from dishcovery import config
from dishcovery.schema import init_all

DATA_FILE = config.DATA_DIR / "dishcovery_data.json"


def to_dt(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")) if isinstance(s, str) else s


def load_data():
    if not DATA_FILE.exists():
        from dishcovery.loading import generate_data
        generate_data.main([])
    return json.loads(DATA_FILE.read_text(encoding="utf-8"))


def index_data(data):
    return ({r["_id"]: r for r in data["restaurants"]}, {d["_id"]: d for d in data["dishes"]},
            {u["_id"]: u for u in data["users"]})


# ------------------------------------------------------------------ MongoDB
def load_mongo(data):
    from dishcovery.connection.mongo import get_db
    from dishcovery.queries import mongo_queries as mq
    db = get_db()
    salt = bcrypt.gensalt(rounds=10)
    pw_hash = bcrypt.hashpw(data["demo_password"].encode(), salt).decode()
    users = []
    for u in data["users"]:
        doc = dict(u, password_hash=pw_hash, created_at=to_dt(u["created_at"]))
        users.append(doc)
    menus = {}
    for d in data["dishes"]:
        menus.setdefault(d["restaurant_id"], []).append({"dish_id": d["_id"], "name": d["name"], "price": d["price"]})
    restaurants = [dict(r, created_at=to_dt(r["created_at"]), menu_summary=menus.get(r["_id"], []),
                        rating_avg=0.0, rating_count=0) for r in data["restaurants"]]
    dishes = [dict(d, rating_avg=0.0, rating_count=0) for d in data["dishes"]]
    reviews = [dict(r, created_at=to_dt(r["created_at"])) for r in data["reviews"]]
    db.users.insert_many(users)
    db.restaurants.insert_many(restaurants)
    db.dishes.insert_many(dishes)
    db.reviews.insert_many(reviews)
    db.lists.insert_many(data["lists"])
    mq.refresh_all_ratings()   # Pipeline A for every restaurant and dish
    print("  MongoDB   users=%d restaurants=%d dishes=%d reviews=%d lists=%d (password for every user: %s)" % (
        len(users), len(restaurants), len(dishes), len(reviews), len(data["lists"]), data["demo_password"]))


# ------------------------------------------------------------------ Cassandra
def load_cassandra(data):
    from dishcovery.queries import cassandra_queries as cq
    rests, dishes, users = index_data(data)
    visits, visits_month, activity, reviews, searches = [], [], [], [], []
    for v in data["visits"]:
        a, b = cq.visit_rows(v["user_id"], v["visited_at"], rests[v["restaurant_id"]])
        visits.append(a)
        visits_month.append(b)
        activity.append(cq.activity_row(v["user_id"], v["visited_at"], "checkin", "restaurant", v["restaurant_id"],
                                        {"name": rests[v["restaurant_id"]]["name"]}))
    for r in data["reviews"]:
        dish_name = dishes[r["dish_id"]]["name"] if r.get("dish_id") else None
        reviews.append(cq.review_row(r, users[r["user_id"]]["name"], dish_name))
        activity.append(cq.activity_row(r["user_id"], r["created_at"], "review",
                                        "dish" if r.get("dish_id") else "restaurant",
                                        r.get("dish_id") or r["restaurant_id"],
                                        {"review_id": r["_id"], "rating": r["rating"]}))
    from cassandra.util import uuid_from_time
    for s in data["searches"]:
        ts = cq.utc(s["searched_at"])
        searches.append((s["user_id"], ts, uuid_from_time(ts), s["query_text"], s["filters"]))
        activity.append(cq.activity_row(s["user_id"], ts, "search", "query", s["query_text"], s["filters"]))
    cq.execute_many("ins_visit", visits)
    cq.execute_many("ins_visit_month", visits_month)
    cq.execute_many("ins_review", reviews)
    cq.execute_many("ins_search", searches)
    cq.execute_many("ins_activity", activity)
    views, today = [], date.today()
    for city, per_dish in data["dish_views_days_ago"].items():
        for dish_id, counts in per_dish.items():
            for days_ago, n in enumerate(counts):
                if n:
                    views.append((n, city, today - timedelta(days=days_ago), dish_id))
    cq.execute_many("inc_view", views, concurrency=16)
    print("  Cassandra visits=%d reviews=%d searches=%d activity=%d dish-view counters=%d" % (
        len(visits), len(reviews), len(searches), len(activity), len(views)))


# ------------------------------------------------------------------ Dgraph
def load_dgraph(data):
    from dishcovery.connection.dgraph import mutate
    nodes = []
    cuisines = sorted({c for r in data["restaurants"] for c in r["cuisine"]})
    for c in cuisines:
        nodes.append({"uid": "_:c_" + c.replace(" ", "_"), "dgraph.type": "Cuisine", "cuisine_name": c})
    for u in data["users"]:
        nodes.append({"uid": "_:" + u["_id"], "dgraph.type": "User", "user_id": u["_id"], "name": u["name"],
                      "city": u.get("city", ""),
                      "follows": [{"uid": "_:" + f} for f in data["follows"].get(u["_id"], [])]})
    for r in data["restaurants"]:
        nodes.append({"uid": "_:" + r["_id"], "dgraph.type": "Restaurant", "restaurant_id": r["_id"],
                      "name": r["name"], "city": r["address"]["city"], "price_level": r["price_level"],
                      "has_cuisine": [{"uid": "_:c_" + c.replace(" ", "_")} for c in r["cuisine"]]})
    for d in data["dishes"]:
        nodes.append({"uid": "_:" + d["_id"], "dgraph.type": "Dish", "dish_id": d["_id"], "name": d["name"],
                      "price_level": d["price_level"], "served_at": {"uid": "_:" + d["restaurant_id"]}})
    for r in data["reviews"]:
        n = {"uid": "_:" + r["_id"], "dgraph.type": "Review", "review_id": r["_id"], "rating": r["rating"],
             "created_at": r["created_at"], "author": {"uid": "_:" + r["user_id"]},
             "of_restaurant": {"uid": "_:" + r["restaurant_id"]}}
        if r.get("dish_id"):
            n["dish"] = {"uid": "_:" + r["dish_id"]}
        nodes.append(n)
    mutate(set_obj=nodes)
    print("  Dgraph    nodes=%d (users=%d restaurants=%d dishes=%d reviews=%d cuisines=%d) follows=%d" % (
        len(nodes), len(data["users"]), len(data["restaurants"]), len(data["dishes"]), len(data["reviews"]),
        len(cuisines), sum(len(v) for v in data["follows"].values())))


# ------------------------------------------------------------------ ChromaDB
def load_chroma(data):
    from dishcovery.queries import chroma_queries as ch
    rests, dishes, _ = index_data(data)
    t0 = time.time()
    ch.upsert("dishes", [d["_id"] for d in data["dishes"]],
              [ch.dish_document(d, rests[d["restaurant_id"]]) for d in data["dishes"]],
              [ch.dish_metadata(d, rests[d["restaurant_id"]]) for d in data["dishes"]])
    names = lambda r: (rests[r["restaurant_id"]]["name"], dishes[r["dish_id"]]["name"] if r.get("dish_id") else None)
    ch.upsert("reviews", [r["_id"] for r in data["reviews"]],
              [ch.review_document(r, *names(r)) for r in data["reviews"]],
              [ch.review_metadata(r, *names(r)) for r in data["reviews"]])
    menu = {}
    for d in data["dishes"]:
        menu.setdefault(d["restaurant_id"], []).append(d["name"])
    ch.upsert("restaurants", [r["_id"] for r in data["restaurants"]],
              [ch.restaurant_document(r, menu.get(r["_id"], [])) for r in data["restaurants"]],
              [ch.restaurant_metadata(r) for r in data["restaurants"]])
    print("  ChromaDB  dishes=%d reviews=%d restaurants=%d embedded with %s in %.1fs" % (
        len(data["dishes"]), len(data["reviews"]), len(data["restaurants"]), config.EMBEDDING_MODEL, time.time() - t0))


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--only", nargs="*", choices=["mongo", "cassandra", "dgraph", "chroma"])
    p.add_argument("--no-reset", action="store_true", help="do not recreate the schemas first")
    args = p.parse_args(argv)
    targets = args.only or ["mongo", "cassandra", "dgraph", "chroma"]
    if not args.no_reset:
        init_all.main(["--reset", "--only", *targets])
    data = load_data()
    t0 = time.time()
    print("Loading %s ..." % DATA_FILE.name)
    for name, fn in (("mongo", load_mongo), ("cassandra", load_cassandra), ("dgraph", load_dgraph), ("chroma", load_chroma)):
        if name in targets:
            fn(data)
    print("Done in %.1fs" % (time.time() - t0))


if __name__ == "__main__":
    main()
