"""Dgraph: social and taste graph. Writes are upsert blocks keyed by the shared ids
(@upsert predicates), reads are multi-hop traversals with count / sum / val / math / @groupby."""
import re

from dishcovery.connection import dgraph as dg

_ID = re.compile(r"^(user|rest|dish|rev)_[0-9]{4,}$")


def _id(value):
    if not _ID.match(value or ""):
        raise ValueError("invalid id: %r" % value)
    return value


def _upsert_json(query, set_obj=None, del_obj=None, cond=None):
    txn = dg.get_client().txn()
    try:
        mu = txn.create_mutation(set_obj=set_obj, del_obj=del_obj, cond=cond)
        return txn.do_request(txn.create_request(query=query, mutations=[mu], commit_now=True))
    finally:
        txn.discard()


# ------------------------------------------------------------------ writes
def upsert_user(user):                                           # FR-01 / FR-03
    q = '{ u as var(func: eq(user_id, "%s")) }' % _id(user["_id"])
    _upsert_json(q, set_obj={"uid": "uid(u)", "dgraph.type": "User", "user_id": user["_id"],
                             "name": user["name"], "city": user.get("city", "")})


def delete_user(user_id):                                        # FR-05
    q = '{ u as var(func: eq(user_id, "%s")) { f as ~follows } }' % _id(user_id)
    dg.upsert(q, del_nquads="uid(u) * * .\nuid(f) <follows> uid(u) .")


def upsert_restaurant(rest):                                     # FR-06
    cuisines = rest["cuisine"]
    q = "{ r as var(func: eq(restaurant_id, \"%s\")) %s }" % (
        _id(rest["_id"]), " ".join('c%d as var(func: eq(cuisine_name, "%s"))' % (i, c.replace('"', ""))
                                  for i, c in enumerate(cuisines)))
    _upsert_json(q, set_obj={
        "uid": "uid(r)", "dgraph.type": "Restaurant", "restaurant_id": rest["_id"], "name": rest["name"],
        "city": rest["address"]["city"], "price_level": rest["price_level"],
        "has_cuisine": [{"uid": "uid(c%d)" % i, "dgraph.type": "Cuisine", "cuisine_name": c}
                        for i, c in enumerate(cuisines)]})


def upsert_dish(dish):                                           # FR-07
    q = '{ d as var(func: eq(dish_id, "%s")) r as var(func: eq(restaurant_id, "%s")) }' % (
        _id(dish["_id"]), _id(dish["restaurant_id"]))
    _upsert_json(q, cond="@if(eq(len(r), 1))", set_obj={
        "uid": "uid(d)", "dgraph.type": "Dish", "dish_id": dish["_id"], "name": dish["name"],
        "price_level": dish["price_level"], "served_at": {"uid": "uid(r)"}})


def upsert_review(review):                                       # FR-15 / FR-16
    created = review["created_at"]
    created = created if isinstance(created, str) else created.isoformat()
    parts = ['r as var(func: eq(review_id, "%s"))' % _id(review["_id"]),
             'u as var(func: eq(user_id, "%s"))' % _id(review["user_id"]),
             's as var(func: eq(restaurant_id, "%s"))' % _id(review["restaurant_id"])]
    obj = {"uid": "uid(r)", "dgraph.type": "Review", "review_id": review["_id"], "rating": int(review["rating"]),
           "created_at": created, "author": {"uid": "uid(u)"}, "of_restaurant": {"uid": "uid(s)"}}
    cond = "@if(eq(len(u), 1) AND eq(len(s), 1)"
    if review.get("dish_id"):
        parts.append('d as var(func: eq(dish_id, "%s"))' % _id(review["dish_id"]))
        obj["dish"] = {"uid": "uid(d)"}
        cond += " AND eq(len(d), 1)"
    res = _upsert_json("{ %s }" % " ".join(parts), set_obj=obj, cond=cond + ")")
    return res


def delete_review(review_id):                                    # FR-16
    dg.upsert('{ r as var(func: eq(review_id, "%s")) }' % _id(review_id), del_nquads="uid(r) * * .")


def follow(follower_id, followee_id):                            # FR-26
    q = '{ a as var(func: eq(user_id, "%s")) b as var(func: eq(user_id, "%s")) }' % (_id(follower_id), _id(followee_id))
    dg.upsert(q, set_nquads="uid(a) <follows> uid(b) .", cond="@if(eq(len(a), 1) AND eq(len(b), 1))")


def unfollow(follower_id, followee_id):                          # FR-26
    q = '{ a as var(func: eq(user_id, "%s")) b as var(func: eq(user_id, "%s")) }' % (_id(follower_id), _id(followee_id))
    dg.upsert(q, del_nquads="uid(a) <follows> uid(b) .")


# ------------------------------------------------------------------ reads
Q_FOLLOWERS = """
query followers($id: string) {
  user(func: eq(user_id, $id)) {
    user_id
    name
    following_count: count(follows)
    followers_count: count(~follows)
    following: follows (orderasc: name) { user_id name }
    followers: ~follows (orderasc: name) { user_id name }
  }
}"""

Q_FEED = """
query feed($id: string, $n: int) {
  var(func: eq(user_id, $id)) { follows { ~author { recent as uid } } }
  feed(func: uid(recent), orderdesc: created_at, first: $n) {
    review_id
    rating
    created_at
    author { user_id name }
  }
}"""

Q_RECOMMEND = """
query recommend($id: string, $n: int) {
  me as var(func: eq(user_id, $id))
  # dishes I already rated
  var(func: uid(me)) { ~author { dish { tried as uid } } }
  # users who rated 4-5 the same dishes I rated 4-5
  var(func: uid(me)) {
    ~author @filter(ge(rating, 4)) {
      dish { ~dish @filter(ge(rating, 4)) { author @filter(NOT uid(me)) { similar as uid } } }
    }
  }
  # dishes those users rated 4-5 that I have not tried
  var(func: uid(similar)) { ~author @filter(ge(rating, 4)) { cand as dish @filter(NOT uid(tried)) } }
  # score each candidate inside the graph: votes, sum, average (math) and a combined score
  var(func: uid(cand)) {
    ~dish { r as rating }
    total as sum(val(r))
    n as count(~dish)
  }
  # a predicate can be counted only once per block, so the 4-5 star votes get their own block
  var(func: uid(cand)) { votes as count(~dish @filter(ge(rating, 4))) }
  var(func: uid(cand)) {
    avg as math(1.0 * total / n)
    score as math(votes * avg)
  }
  recommendations(func: uid(cand), orderdesc: val(score), first: $n) {
    dish_id
    name
    votes: val(votes)
    avg_rating: val(avg)
    score: val(score)
    served_at { restaurant_id name }
  }
}"""

Q_SUGGEST = """
query suggest($id: string, $n: int) {
  me as var(func: eq(user_id, $id)) { f as follows }
  var(func: uid(f)) { follows @filter(NOT uid(me) AND NOT uid(f)) { c as uid } }
  var(func: uid(c)) { mutual as count(~follows @filter(uid(f))) }
  suggestions(func: uid(c), orderdesc: val(mutual), first: $n) {
    user_id
    name
    city
    mutual_connections: val(mutual)
  }
}"""

Q_NETWORK_PICKS = """
query picks($uid: string, $rid: string) {
  var(func: eq(user_id, $uid)) { f as follows }
  var(func: eq(restaurant_id, $rid)) { ~served_at { rd as uid } }
  # dishes of this restaurant that people I follow rated 4-5
  var(func: uid(f)) { ~author @filter(ge(rating, 4)) { picked as dish @filter(uid(rd)) } }
  # overall average of each picked dish, computed in the graph
  var(func: uid(picked)) {
    ~dish { r as rating }
    total as sum(val(r))
    n as count(~dish)
    avg as math(1.0 * total / n)
  }
  network_picks(func: uid(picked), orderdesc: val(avg)) {
    dish_id
    name
    avg_rating: val(avg)
    total_reviews: val(n)
    liked_by: ~dish @filter(ge(rating, 4)) @cascade {
      rating
      author @filter(uid(f)) { user_id name }
    }
  }
}"""

Q_TASTE = """
query taste($id: string) {
  var(func: eq(user_id, $id)) { ~author { of_restaurant { R as uid } } }
  var(func: uid(R)) { has_cuisine { c as count(~has_cuisine @filter(uid(R))) } }
  cuisines(func: uid(c), orderdesc: val(c)) { cuisine_name restaurants_reviewed: val(c) }
  ratings(func: eq(user_id, $id)) {
    ~author @groupby(rating) { count(uid) }
  }
}"""


def _q(dql, **variables):
    data, latency = dg.query(dql, {("$" + k): str(v) for k, v in variables.items()})
    return data, latency


def followers(user_id):                                          # FR-27
    data, _ = _q(Q_FOLLOWERS, id=user_id)
    return (data.get("user") or [None])[0]


def feed_review_ids(user_id, n=20):                              # FR-28 (Dgraph side)
    data, _ = _q(Q_FEED, id=user_id, n=n)
    return [r["review_id"] for r in data.get("feed", [])], data.get("feed", [])


def recommend(user_id, n=10):                                    # FR-29
    data, _ = _q(Q_RECOMMEND, id=user_id, n=n)
    return data.get("recommendations", [])


def rated_dish_ids(user_id):
    data, _ = _q('query t($id: string) { u(func: eq(user_id, $id)) { ~author { dish { dish_id } } } }', id=user_id)
    revs = (data.get("u") or [{}])[0].get("~author", [])
    return {r["dish"]["dish_id"] for r in revs if r.get("dish")}


def following_ids(user_id):
    f = followers(user_id) or {}
    return {x["user_id"] for x in f.get("following", [])}


def suggest_people(user_id, n=10):                               # FR-30
    data, _ = _q(Q_SUGGEST, id=user_id, n=n)
    return data.get("suggestions", [])


def network_picks(user_id, restaurant_id):                       # FR-31
    data, _ = _q(Q_NETWORK_PICKS, uid=user_id, rid=restaurant_id)
    return data.get("network_picks", [])


def taste_profile(user_id):                                      # FR-25 (graph side, @groupby)
    data, _ = _q(Q_TASTE, id=user_id)
    groups = []
    for u in data.get("ratings", []):
        for block in u.get("~author", []):
            groups.extend(block.get("@groupby", []))
    return data.get("cuisines", []), sorted(groups, key=lambda g: -g.get("rating", 0))


def latency_report(user_id="user_0001", restaurant_id="rest_0001"):
    """Server-side latency of the main traversals (optimization evidence)."""
    out = {}
    for name, dql, v in [("FR-27 followers", Q_FOLLOWERS, {"id": user_id}),
                         ("FR-28 feed", Q_FEED, {"id": user_id, "n": 20}),
                         ("FR-29 recommendations (5 hops)", Q_RECOMMEND, {"id": user_id, "n": 10}),
                         ("FR-30 suggestions", Q_SUGGEST, {"id": user_id, "n": 10})]:
        _, ms = _q(dql, **v)
        out[name] = ms
    return out
