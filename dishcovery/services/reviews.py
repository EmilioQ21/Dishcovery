"""Reviews: the main cross-database write (FR-15, FR-16) and rating reads (FR-17..FR-19).

write_review:  MongoDB insert (validator + unique index) -> recompute ratings (Pipeline A)
               -> Cassandra reviews_by_restaurant + activity_by_user
               -> Dgraph Review node with author / dish / of_restaurant edges
               -> ChromaDB reviews collection (embedding of the text)
All four stores use the same review_id."""
from datetime import datetime, timezone

from pymongo.errors import DuplicateKeyError, WriteError

from dishcovery.connection.mongo import get_db
from dishcovery.queries import cassandra_queries as cq
from dishcovery.queries import chroma_queries as ch
from dishcovery.queries import dgraph_queries as dq
from dishcovery.queries import mongo_queries as mq
from dishcovery.services.errors import DishcoveryError, NotFound
from dishcovery.services.ids import next_id
from dishcovery.services.sync import handler, propagate


def _names(review):
    db = get_db()
    user = db.users.find_one({"_id": review["user_id"]}, {"name": 1}) or {"name": ""}
    rest = db.restaurants.find_one({"_id": review["restaurant_id"]}, {"name": 1}) or {"name": ""}
    dish = db.dishes.find_one({"_id": review["dish_id"]}, {"name": 1}) if review.get("dish_id") else None
    return user["name"], rest["name"], dish["name"] if dish else None


def _review(review_id):
    r = get_db().reviews.find_one({"_id": review_id})
    if not r:
        raise NotFound("review %s not found" % review_id)
    return r


# ------------------------------------------------------------------ derived writes (replayable)
@handler("cassandra_upsert_review")
def _cass_review(p):
    r = _review(p["review_id"])
    user_name, _, dish_name = _names(r)
    cq.upsert_review(r, user_name, dish_name)
    if p.get("log_activity"):
        cq.log_activity(r["user_id"], "review", "dish" if r.get("dish_id") else "restaurant",
                        r.get("dish_id") or r["restaurant_id"], {"review_id": r["_id"], "rating": r["rating"]})


@handler("cassandra_delete_review")
def _cass_delete(p):
    cq.delete_review(p)


@handler("dgraph_upsert_review")
def _dg_review(p):
    dq.upsert_review(_review(p["review_id"]))


@handler("dgraph_delete_review")
def _dg_delete(p):
    dq.delete_review(p["review_id"])


@handler("chroma_upsert_review")
def _ch_review(p):
    r = _review(p["review_id"])
    _, rest_name, dish_name = _names(r)
    ch.upsert("reviews", [r["_id"]], [ch.review_document(r, rest_name, dish_name)],
              [ch.review_metadata(r, rest_name, dish_name)])


@handler("chroma_delete_review")
def _ch_delete(p):
    ch.delete("reviews", [p["review_id"]])


# ------------------------------------------------------------------ FR-15 write
def write_review(user_id, restaurant_id, rating, text, dish_id=None):
    db = get_db()
    if not db.restaurants.find_one({"_id": restaurant_id}, {"_id": 1}):
        raise NotFound("restaurant %s not found" % restaurant_id)
    if dish_id and not db.dishes.find_one({"_id": dish_id, "restaurant_id": restaurant_id}, {"_id": 1}):
        raise NotFound("dish %s is not served at %s" % (dish_id, restaurant_id))
    review = {"_id": next_id("reviews"), "user_id": user_id, "restaurant_id": restaurant_id,
              "dish_id": dish_id, "rating": int(rating), "text": text.strip(),
              "created_at": datetime.now(timezone.utc).replace(microsecond=0)}
    try:
        db.reviews.insert_one(review)
    except DuplicateKeyError as exc:
        raise DishcoveryError("you already reviewed this %s; edit your review instead"
                              % ("dish" if dish_id else "restaurant")) from exc
    except WriteError as exc:   # $jsonSchema validation (rating 1-5, text length...)
        raise DishcoveryError("review rejected by the database validator: rating must be 1-5 and text 3-2000 chars") from exc
    mq.refresh_ratings(restaurant_id, dish_id)
    status = {
        "mongodb": True,
        "cassandra": propagate("cassandra_upsert_review", {"review_id": review["_id"], "log_activity": True}),
        "dgraph": propagate("dgraph_upsert_review", {"review_id": review["_id"]}),
        "chromadb": propagate("chroma_upsert_review", {"review_id": review["_id"]}),
    }
    return review, status


# ------------------------------------------------------------------ FR-16 edit / delete
def edit_review(user_id, review_id, rating=None, text=None):
    r = _review(review_id)
    if r["user_id"] != user_id:
        raise DishcoveryError("you can only edit your own reviews")
    changes = {"updated_at": datetime.now(timezone.utc)}
    if rating is not None:
        changes["rating"] = int(rating)
    if text:
        changes["text"] = text.strip()
    try:
        get_db().reviews.update_one({"_id": review_id}, {"$set": changes})
    except WriteError as exc:
        raise DishcoveryError("change rejected by the database validator") from exc
    mq.refresh_ratings(r["restaurant_id"], r.get("dish_id"))
    status = {"mongodb": True,
              "cassandra": propagate("cassandra_upsert_review", {"review_id": review_id}),
              "dgraph": propagate("dgraph_upsert_review", {"review_id": review_id}),
              "chromadb": propagate("chroma_upsert_review", {"review_id": review_id})}
    return _review(review_id), status


def delete_review(user_id, review_id):
    r = _review(review_id)
    if r["user_id"] != user_id:
        raise DishcoveryError("you can only delete your own reviews")
    get_db().reviews.delete_one({"_id": review_id})
    mq.refresh_ratings(r["restaurant_id"], r.get("dish_id"))
    status = {"mongodb": True,
              "cassandra": propagate("cassandra_delete_review", {"_id": r["_id"], "restaurant_id": r["restaurant_id"],
                                                                 "created_at": r["created_at"]}),
              "dgraph": propagate("dgraph_delete_review", {"review_id": review_id}),
              "chromadb": propagate("chroma_delete_review", {"review_id": review_id})}
    return status


# ------------------------------------------------------------------ reads
def restaurant_reviews(restaurant_id, limit=10):                     # FR-17 (Cassandra)
    return cq.restaurant_reviews(restaurant_id, limit)


def ratings(restaurant_id=None, dish_id=None):                       # FR-18 (Pipeline A)
    if dish_id:
        return mq.rating_of("dish_id", dish_id)
    return mq.rating_of("restaurant_id", restaurant_id)


def top_dishes(cuisine=None, min_votes=3, top=5):                    # FR-19 (Pipeline B)
    return mq.top_dishes_by_cuisine(min_votes=min_votes, top=top, cuisine=cuisine)


def my_reviews(user_id, limit=20):
    return list(get_db().reviews.find({"user_id": user_id}).sort("created_at", -1).limit(limit))
