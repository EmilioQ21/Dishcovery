"""Restaurants and dishes (FR-06..FR-11, FR-23 search history, FR-24 dish views)."""
from datetime import datetime, timezone

from dishcovery.connection.mongo import get_db
from dishcovery.queries import cassandra_queries as cq
from dishcovery.queries import chroma_queries as ch
from dishcovery.queries import dgraph_queries as dq
from dishcovery.queries import mongo_queries as mq
from dishcovery.services.errors import DishcoveryError, NotFound
from dishcovery.services.ids import next_id
from dishcovery.services.sync import handler, propagate

DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def price_level_for(price):
    return 1 if price <= 90 else 2 if price <= 180 else 3 if price <= 300 else 4


@handler("dgraph_upsert_restaurant")
def _dg_rest(p):
    dq.upsert_restaurant(get_restaurant(p["restaurant_id"]))


@handler("chroma_upsert_restaurant")
def _ch_rest(p):
    r = get_restaurant(p["restaurant_id"])
    menu = [d["name"] for d in mq.restaurant_dishes(r["_id"])]
    ch.upsert("restaurants", [r["_id"]], [ch.restaurant_document(r, menu)], [ch.restaurant_metadata(r)])


@handler("dgraph_upsert_dish")
def _dg_dish(p):
    dq.upsert_dish(get_dish(p["dish_id"]))


@handler("chroma_upsert_dish")
def _ch_dish(p):
    d = get_dish(p["dish_id"])
    r = get_restaurant(d["restaurant_id"])
    ch.upsert("dishes", [d["_id"]], [ch.dish_document(d, r)], [ch.dish_metadata(d, r)])


@handler("cassandra_search")
def _cass_search(p):
    ts = cq.record_search(p["user_id"], p["query_text"], p.get("filters"), p.get("ts"))
    cq.log_activity(p["user_id"], "search", "query", p["query_text"], p.get("filters"), ts)


@handler("cassandra_dish_view")
def _cass_view(p):
    cq.add_dish_view(p["city"], p["dish_id"])


# ------------------------------------------------------------------ restaurants
def get_restaurant(restaurant_id):                                  # FR-08: one document read
    r = mq.restaurant_detail(restaurant_id)
    if not r:
        raise NotFound("restaurant %s not found" % restaurant_id)
    return r


def create_restaurant(name, cuisine, price_level, lon, lat, city, street="", neighborhood="", description="",
                      attributes=None, hours=None):                 # FR-06
    rest = {"_id": next_id("restaurants"), "name": name, "cuisine": [c.strip().lower() for c in cuisine],
            "price_level": int(price_level), "description": description,
            "location": {"type": "Point", "coordinates": [float(lon), float(lat)]},
            "address": {"street": street, "neighborhood": neighborhood, "city": city, "state": "Jalisco"},
            "hours": hours or {d: {"open": "09:00", "close": "22:00"} for d in DAYS},
            "attributes": {k: bool(v) for k, v in (attributes or {}).items()},
            "menu_summary": [], "rating_avg": 0.0, "rating_count": 0, "created_at": datetime.now(timezone.utc)}
    get_db().restaurants.insert_one(rest)
    propagate("dgraph_upsert_restaurant", {"restaurant_id": rest["_id"]})
    propagate("chroma_upsert_restaurant", {"restaurant_id": rest["_id"]})
    return rest


def search(text=None, cuisine=None, max_price=None, user_id=None, limit=10):   # FR-09 (+FR-23)
    if user_id:
        filters = {k: v for k, v in (("cuisine", cuisine), ("price", max_price)) if v}
        propagate("cassandra_search", {"user_id": user_id, "query_text": text or cuisine or "",
                                       "filters": filters, "ts": datetime.now(timezone.utc)})
    if text:
        return mq.text_search_with_facets(text, max_price, limit)
    return {"results": list(mq.search_by_filters(cuisine, max_price, limit))}


def near(lon=None, lat=None, meters=2000, max_price=None, limit=20):       # FR-10
    return mq.nearby(lon, lat, meters, max_price, limit)


def filter_attributes(**flags):                                         # FR-11
    if not flags:
        raise DishcoveryError("give at least one attribute, e.g. terrace=true")
    return mq.filter_by_attributes(**flags)


# ------------------------------------------------------------------ dishes
def get_dish(dish_id):
    d = get_db().dishes.find_one({"_id": dish_id})
    if not d:
        raise NotFound("dish %s not found" % dish_id)
    return d


def add_dish(restaurant_id, name, price, description="", tags=None, vegetarian=False):   # FR-07
    rest = get_restaurant(restaurant_id)
    dish = {"_id": next_id("dishes"), "restaurant_id": restaurant_id, "restaurant_name": rest["name"],
            "name": name, "price": price, "price_level": price_level_for(price), "description": description,
            "tags": [t.strip().lower() for t in (tags or []) if t.strip()], "vegetarian": bool(vegetarian),
            "rating_avg": 0.0, "rating_count": 0}
    db = get_db()
    db.dishes.insert_one(dish)
    db.restaurants.update_one({"_id": restaurant_id},
                              {"$push": {"menu_summary": {"dish_id": dish["_id"], "name": name, "price": price}}})
    propagate("dgraph_upsert_dish", {"dish_id": dish["_id"]})
    propagate("chroma_upsert_dish", {"dish_id": dish["_id"]})
    propagate("chroma_upsert_restaurant", {"restaurant_id": restaurant_id})
    return dish


def view_dish(dish_id):                                              # FR-24 (counter += 1)
    d = get_dish(dish_id)
    r = get_restaurant(d["restaurant_id"])
    propagate("cassandra_dish_view", {"city": r["address"]["city"], "dish_id": dish_id})
    return d, r
