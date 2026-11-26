"""MongoDB queries and aggregation pipelines (source of truth for every entity)."""
from dishcovery import config
from dishcovery.connection.mongo import get_db


# ------------------------------------------------------------------ catalog reads
def restaurant_detail(restaurant_id):                          # FR-08: one read
    return get_db().restaurants.find_one({"_id": restaurant_id})


def restaurant_dishes(restaurant_id):                          # FR-07/08 (ix_restaurant)
    return list(get_db().dishes.find({"restaurant_id": restaurant_id}).sort("price", 1))


def search_by_filters(cuisine=None, max_price=None, limit=10):  # FR-09 (ix_cuisine_price_rating)
    q = {}
    if cuisine:
        q["cuisine"] = cuisine
    if max_price:
        q["price_level"] = {"$lte": int(max_price)}
    return get_db().restaurants.find(q, {"name": 1, "cuisine": 1, "price_level": 1, "rating_avg": 1,
                                         "rating_count": 1, "address.city": 1}).sort("rating_avg", -1).limit(limit)


def text_search_with_facets(text, max_price=None, limit=10):    # FR-09 ($text + $facet)
    match = {"$text": {"$search": text}}
    if max_price:
        match["price_level"] = {"$lte": int(max_price)}
    pipeline = [
        {"$match": match},
        {"$addFields": {"score": {"$meta": "textScore"}}},
        {"$facet": {
            "results": [{"$sort": {"score": -1, "rating_avg": -1}}, {"$limit": limit},
                        {"$project": {"name": 1, "cuisine": 1, "price_level": 1, "rating_avg": 1,
                                      "address.city": 1, "score": 1}}],
            "by_cuisine": [{"$unwind": "$cuisine"}, {"$group": {"_id": "$cuisine", "n": {"$sum": 1}}},
                           {"$sort": {"n": -1}}],
            "by_price_level": [{"$group": {"_id": "$price_level", "n": {"$sum": 1}}}, {"$sort": {"_id": 1}}],
            "by_city": [{"$group": {"_id": "$address.city", "n": {"$sum": 1}}}, {"$sort": {"n": -1}}],
        }},
    ]
    return next(get_db().restaurants.aggregate(pipeline))


def nearby(lon=None, lat=None, max_meters=2000, max_price=None, limit=20):   # FR-10 Pipeline C
    lon = config.DEFAULT_LOCATION[0] if lon is None else lon
    lat = config.DEFAULT_LOCATION[1] if lat is None else lat
    geo = {"near": {"type": "Point", "coordinates": [lon, lat]}, "distanceField": "distance_m",
           "maxDistance": max_meters, "spherical": True}
    if max_price:
        geo["query"] = {"price_level": {"$lte": int(max_price)}}
    return list(get_db().restaurants.aggregate([
        {"$geoNear": geo}, {"$limit": limit},
        {"$project": {"name": 1, "cuisine": 1, "price_level": 1, "rating_avg": 1, "distance_m": {"$round": ["$distance_m", 0]}}},
    ]))


def filter_by_attributes(limit=20, **flags):                    # FR-11
    q = {"attributes.%s" % k: v for k, v in flags.items()}
    return list(get_db().restaurants.find(q, {"name": 1, "attributes": 1, "cuisine": 1}).limit(limit))


# ------------------------------------------------------------------ ratings (Pipeline A, B)
def rating_of(field, value):                                     # FR-18 Pipeline A
    res = list(get_db().reviews.aggregate([
        {"$match": {field: value}},
        {"$group": {"_id": "$" + field, "avg": {"$avg": "$rating"}, "count": {"$sum": 1}}},
    ]))
    if not res:
        return 0.0, 0
    return round(float(res[0]["avg"]), 2), int(res[0]["count"])


def refresh_ratings(restaurant_id, dish_id=None):
    """Recompute and store rating_avg / rating_count (computed pattern) so reads stay O(1)."""
    db = get_db()
    avg, cnt = rating_of("restaurant_id", restaurant_id)
    db.restaurants.update_one({"_id": restaurant_id}, {"$set": {"rating_avg": avg, "rating_count": cnt}})
    if dish_id:
        avg_d, cnt_d = rating_of("dish_id", dish_id)
        db.dishes.update_one({"_id": dish_id}, {"$set": {"rating_avg": avg_d, "rating_count": cnt_d}})
    return avg, cnt


def refresh_all_ratings():
    db = get_db()
    for key, coll in (("restaurant_id", db.restaurants), ("dish_id", db.dishes)):
        coll.update_many({}, {"$set": {"rating_avg": 0.0, "rating_count": 0}})
        for row in db.reviews.aggregate([
            {"$match": {key: {"$ne": None}}},
            {"$group": {"_id": "$" + key, "avg": {"$avg": "$rating"}, "count": {"$sum": 1}}},
        ]):
            coll.update_one({"_id": row["_id"]}, {"$set": {"rating_avg": round(float(row["avg"]), 2),
                                                           "rating_count": int(row["count"])}})


def top_dishes_by_cuisine(min_votes=3, top=5, cuisine=None):     # FR-19 Pipeline B
    pipeline = [
        {"$match": {"dish_id": {"$ne": None}}},
        {"$group": {"_id": "$dish_id", "avg": {"$avg": "$rating"}, "votes": {"$sum": 1}}},
        {"$match": {"votes": {"$gte": min_votes}}},
        {"$lookup": {"from": "dishes", "localField": "_id", "foreignField": "_id", "as": "dish"}},
        {"$unwind": "$dish"},
        {"$lookup": {"from": "restaurants", "localField": "dish.restaurant_id", "foreignField": "_id", "as": "rest"}},
        {"$unwind": "$rest"},
        {"$unwind": "$rest.cuisine"},
    ]
    if cuisine:
        pipeline.append({"$match": {"rest.cuisine": cuisine}})
    pipeline += [
        {"$sort": {"avg": -1, "votes": -1}},
        {"$group": {"_id": "$rest.cuisine", "top": {"$push": {
            "dish_id": "$_id", "dish": "$dish.name", "restaurant": "$rest.name",
            "avg": {"$round": ["$avg", 2]}, "votes": "$votes"}}}},
        {"$project": {"top": {"$slice": ["$top", top]}}},
        {"$sort": {"_id": 1}},
    ]
    return list(get_db().reviews.aggregate(pipeline))


def review_stats_by_cuisine(user_id):                            # FR-25 (Mongo side, $lookup)
    return list(get_db().reviews.aggregate([
        {"$match": {"user_id": user_id}},
        {"$lookup": {"from": "restaurants", "localField": "restaurant_id", "foreignField": "_id",
                     "pipeline": [{"$project": {"cuisine": {"$first": "$cuisine"}}}], "as": "rest"}},
        {"$unwind": "$rest"},
        {"$group": {"_id": "$rest.cuisine", "reviews": {"$sum": 1}, "avg_rating": {"$avg": "$rating"}}},
        {"$project": {"reviews": 1, "avg_rating": {"$round": ["$avg_rating", 2]}}},
        {"$sort": {"reviews": -1}},
    ]))


def reviews_by_ids(review_ids):                                  # FR-28: content for Dgraph's ids
    db = get_db()
    return list(db.reviews.aggregate([
        {"$match": {"_id": {"$in": list(review_ids)}}},
        {"$sort": {"created_at": -1}},
        {"$lookup": {"from": "users", "localField": "user_id", "foreignField": "_id",
                     "pipeline": [{"$project": {"name": 1}}], "as": "user"}},
        {"$lookup": {"from": "restaurants", "localField": "restaurant_id", "foreignField": "_id",
                     "pipeline": [{"$project": {"name": 1}}], "as": "rest"}},
        {"$lookup": {"from": "dishes", "localField": "dish_id", "foreignField": "_id",
                     "pipeline": [{"$project": {"name": 1}}], "as": "dish"}},
        {"$project": {"rating": 1, "text": 1, "created_at": 1, "user": {"$first": "$user.name"},
                      "restaurant": {"$first": "$rest.name"}, "dish": {"$first": "$dish.name"}}},
    ]))


def names(collection, ids):
    return {d["_id"]: d["name"] for d in get_db()[collection].find({"_id": {"$in": list(ids)}}, {"name": 1})}


# ------------------------------------------------------------------ explain() evidence
def explain_main_queries():
    """Winning plan of the main queries: IXSCAN / GEO_NEAR / TEXT = an index is used."""
    db = get_db()
    out = {}

    def plan_stages(plan):
        stages, stack = [], [plan]
        while stack:
            p = stack.pop()
            if not isinstance(p, dict):
                continue
            if "stage" in p:
                stages.append(p["stage"] + ("(" + p["indexName"] + ")" if "indexName" in p else ""))
            for k in ("inputStage", "queryPlan"):
                if k in p:
                    stack.append(p[k])
            stack.extend(p.get("inputStages", []))
        return stages

    def explain_find(name, coll, flt, sort=None, limit=None):
        cur = db[coll].find(flt)
        if sort:
            cur = cur.sort(sort)
        if limit:
            cur = cur.limit(limit)
        e = cur.explain()
        stats = e.get("executionStats", {})
        out[name] = {"stages": plan_stages(e["queryPlanner"]["winningPlan"]),
                     "docsExamined": stats.get("totalDocsExamined"), "keysExamined": stats.get("totalKeysExamined"),
                     "nReturned": stats.get("nReturned")}

    explain_find("FR-02 login by email", "users", {"email": "emilio@example.com"})
    explain_find("FR-09 cuisine + price sorted by rating", "restaurants",
                 {"cuisine": "mexican", "price_level": {"$lte": 2}}, [("rating_avg", -1)], 10)
    explain_find("FR-09 text search", "restaurants", {"$text": {"$search": "ramen"}})
    explain_find("FR-11 terrace filter", "restaurants", {"attributes.terrace": True})
    explain_find("FR-07 dishes of a restaurant", "dishes", {"restaurant_id": "rest_0001"})
    explain_find("FR-17/18 latest reviews of a restaurant", "reviews", {"restaurant_id": "rest_0001"},
                 [("created_at", -1)], 10)
    e = db.command("explain", {"aggregate": "restaurants", "cursor": {}, "pipeline": [
        {"$geoNear": {"near": {"type": "Point", "coordinates": config.DEFAULT_LOCATION},
                      "distanceField": "d", "maxDistance": 2000, "spherical": True}}]}, verbosity="queryPlanner")
    stages = e.get("stages", [{}])
    first = stages[0].get("$geoNearCursor", stages[0].get("$cursor", {})) if stages else e
    winning = (first.get("queryPlanner") or e.get("queryPlanner") or {}).get("winningPlan", {})
    out["FR-10 $geoNear within 2 km"] = {"stages": plan_stages(winning)}
    return out
