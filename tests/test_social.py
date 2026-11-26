"""FR-26..FR-31: Dgraph traversals."""
import pytest
from conftest import DEMO_USER

from dishcovery.queries import dgraph_queries as dq
from dishcovery.services import social


@pytest.mark.fr("FR-26")
def test_follow_and_unfollow(fresh_user, evidence):
    """Steps: fresh user follows user_0002, then unfollows. Expected: edge created, visible as ~follows, then removed."""
    social.follow(fresh_user["_id"], "user_0002")
    assert "user_0002" in dq.following_ids(fresh_user["_id"])
    assert fresh_user["_id"] in {x["user_id"] for x in dq.followers("user_0002")["followers"]}
    social.unfollow(fresh_user["_id"], "user_0002")
    assert "user_0002" not in dq.following_ids(fresh_user["_id"])
    evidence("follows edge created and removed")


@pytest.mark.fr("FR-27")
def test_followers_and_following(evidence):
    """Input: user_0001. Expected: both directions (follows and ~follows) with counts equal to the lists."""
    f = social.followers(DEMO_USER)
    assert f["following_count"] == len(f["following"]) > 0
    assert f["followers_count"] == len(f["followers"]) > 0
    evidence("following %d, followers %d" % (f["following_count"], f["followers_count"]))


@pytest.mark.fr("FR-28")
def test_feed_from_followed_users(db, evidence):
    """Input: user_0001. Expected: review ids come only from followed users (Dgraph), content from MongoDB, newest first."""
    following = dq.following_ids(DEMO_USER)
    ids, raw = dq.feed_review_ids(DEMO_USER, 20)
    assert ids and all(r["author"]["user_id"] in following for r in raw)
    feed = social.feed(DEMO_USER, 20)
    assert {r["_id"] for r in feed} == set(ids)
    dates = [r["created_at"] for r in feed]
    assert dates == sorted(dates, reverse=True)
    evidence("%d reviews from %d followed users" % (len(feed), len(following)))


@pytest.mark.fr("FR-29")
def test_recommendations_exclude_tried_dishes(evidence):
    """Input: user_0001. Expected: dishes rated 4-5 by similar users, none already rated by me, sorted by score (math)."""
    recs = social.recommend(DEMO_USER, 10)
    assert recs
    tried = dq.rated_dish_ids(DEMO_USER)
    assert not tried & {r["dish_id"] for r in recs}
    scores = [r["score"] for r in recs]
    assert scores == sorted(scores, reverse=True)
    assert all(1 <= r["avg_rating"] <= 5 for r in recs)
    evidence(", ".join("%s (%d votes, avg %.2f)" % (r["name"], r["votes"], r["avg_rating"]) for r in recs[:3]))


@pytest.mark.fr("FR-30")
def test_people_suggestions(evidence):
    """Input: user_0001. Expected: friends of friends, excluding me and people I follow, ranked by mutual connections."""
    s = social.suggest_people(DEMO_USER)
    following = dq.following_ids(DEMO_USER)
    assert s and all(x["user_id"] != DEMO_USER and x["user_id"] not in following for x in s)
    mutual = [x["mutual_connections"] for x in s]
    assert mutual == sorted(mutual, reverse=True)
    evidence(", ".join("%s (%d)" % (x["name"], x["mutual_connections"]) for x in s[:3]))


@pytest.mark.fr("FR-31")
def test_network_picks_at_restaurant(db, evidence):
    """Input: user_0001 + a restaurant where followed users rated dishes 4-5. Expected: only that restaurant's dishes, liked by people I follow."""
    following = list(dq.following_ids(DEMO_USER))
    row = db.reviews.find_one({"user_id": {"$in": following}, "rating": {"$gte": 4}, "dish_id": {"$ne": None}})
    assert row, "dataset should contain a 4-5 star review by someone user_0001 follows"
    picks = social.network_picks(DEMO_USER, row["restaurant_id"])
    menu = {d["_id"] for d in db.dishes.find({"restaurant_id": row["restaurant_id"]})}
    assert picks and {p["dish_id"] for p in picks} <= menu
    for p in picks:
        authors = {x["author"]["user_id"] for x in p.get("liked_by", []) if x.get("author")}
        assert authors and authors <= set(following)
    evidence("%s: %s" % (row["restaurant_id"], ", ".join("%s avg %.2f" % (p["name"], p["avg_rating"]) for p in picks)))
