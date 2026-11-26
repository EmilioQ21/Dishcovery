"""FR-15..FR-19: the cross-database review write and the rating queries."""
import pytest
from conftest import dgraph_one

from dishcovery.connection.chroma import get_collection
from dishcovery.queries import cassandra_queries as cq
from dishcovery.queries import mongo_queries as mq
from dishcovery.services import reviews
from dishcovery.services.errors import DishcoveryError


@pytest.mark.fr("FR-15")
def test_write_review_reaches_all_four_databases(fresh_user, db, evidence):
    """Input: 5-star review of dish_0006 at rest_0004. Expected: MongoDB doc, Cassandra row (newest first), Dgraph Review node with edges, Chroma embedding, rating recomputed."""
    before = db.restaurants.find_one({"_id": "rest_0004"})["rating_count"]
    r, status = reviews.write_review(fresh_user["_id"], "rest_0004", 5, "Amazing birria, very spicy consome.", "dish_0006")
    assert status == {"mongodb": True, "cassandra": True, "dgraph": True, "chromadb": True}
    assert db.restaurants.find_one({"_id": "rest_0004"})["rating_count"] == before + 1
    assert cq.restaurant_reviews("rest_0004", 1)[0].review_id == r["_id"]
    node = dgraph_one('{ r(func: eq(review_id, "%s")) { rating author { user_id } dish { dish_id } of_restaurant { restaurant_id } } }' % r["_id"])
    assert node["rating"] == 5 and node["author"]["user_id"] == fresh_user["_id"]
    assert node["dish"]["dish_id"] == "dish_0006" and node["of_restaurant"]["restaurant_id"] == "rest_0004"
    assert get_collection("reviews").get(ids=[r["_id"]])["ids"] == [r["_id"]]
    evidence("%s written to %s" % (r["_id"], ", ".join(k for k, v in status.items() if v)))


@pytest.mark.fr("FR-15")
def test_review_constraints(fresh_user):
    """Input: rating 6, then a second review of the same dish. Expected: validator rejects 6; unique index rejects the duplicate."""
    with pytest.raises(DishcoveryError, match="validator"):
        reviews.write_review(fresh_user["_id"], "rest_0001", 6, "Too many stars", "dish_0001")
    reviews.write_review(fresh_user["_id"], "rest_0001", 4, "Good pastor", "dish_0001")
    with pytest.raises(DishcoveryError, match="already reviewed"):
        reviews.write_review(fresh_user["_id"], "rest_0001", 5, "Again", "dish_0001")


@pytest.mark.fr("FR-16")
def test_edit_and_delete_review(fresh_user, db, evidence):
    """Steps: write 2 stars, edit to 4, delete. Expected: every database reflects the edit, then the deletion; restaurant rating recomputed."""
    r, _ = reviews.write_review(fresh_user["_id"], "rest_0002", 2, "Rice was cold.", "dish_0003")
    reviews.edit_review(fresh_user["_id"], r["_id"], rating=4, text="Second visit was much better.")
    assert db.reviews.find_one({"_id": r["_id"]})["rating"] == 4
    assert dgraph_one('{ r(func: eq(review_id, "%s")) { rating } }' % r["_id"])["rating"] == 4
    row = cq.restaurant_reviews("rest_0002", 1)[0]
    assert row.review_id == r["_id"] and row.rating == 4 and "better" in row.text
    assert "better" in get_collection("reviews").get(ids=[r["_id"]])["documents"][0]
    reviews.delete_review(fresh_user["_id"], r["_id"])
    assert db.reviews.find_one({"_id": r["_id"]}) is None
    assert dgraph_one('{ r(func: eq(review_id, "%s")) { uid } }' % r["_id"]) is None
    assert all(x.review_id != r["_id"] for x in cq.restaurant_reviews("rest_0002", 5))
    assert get_collection("reviews").get(ids=[r["_id"]])["ids"] == []
    avg, n = mq.rating_of("restaurant_id", "rest_0002")
    assert db.restaurants.find_one({"_id": "rest_0002"})["rating_avg"] == avg
    evidence("%s edited 2->4 in 4 DBs, then deleted from 4 DBs" % r["_id"])


@pytest.mark.fr("FR-16")
def test_cannot_edit_someone_elses_review(fresh_user):
    """Input: fresh user edits rev_0001 (owned by user_0001). Expected: rejected."""
    with pytest.raises(DishcoveryError):
        reviews.edit_review(fresh_user["_id"], "rev_0001", rating=1)


@pytest.mark.fr("FR-17")
def test_restaurant_reviews_newest_first(db, evidence):
    """Input: restaurant with the most reviews. Expected: Cassandra returns at most 10 rows, ordered by created_at desc."""
    rid = next(db.reviews.aggregate([{"$group": {"_id": "$restaurant_id", "n": {"$sum": 1}}},
                                     {"$sort": {"n": -1}}, {"$limit": 1}]))["_id"]
    rows = reviews.restaurant_reviews(rid, 10)
    assert 0 < len(rows) <= 10
    dates = [r.created_at for r in rows]
    assert dates == sorted(dates, reverse=True)
    evidence("%s: %d rows, %s .. %s" % (rid, len(rows), dates[0], dates[-1]))


@pytest.mark.fr("FR-18")
def test_average_rating_matches_manual_calculation(db, evidence):
    """Input: rest_0001 and dish_0001. Expected: Pipeline A average = manual average = stored rating_avg."""
    for field, value, coll in (("restaurant_id", "rest_0001", "restaurants"), ("dish_id", "dish_0001", "dishes")):
        ratings = [r["rating"] for r in db.reviews.find({field: value})]
        avg, n = mq.rating_of(field, value)
        assert n == len(ratings) and abs(avg - sum(ratings) / len(ratings)) < 0.01
        assert db[coll].find_one({"_id": value})["rating_avg"] == avg
    evidence("rest_0001 avg=%.2f (%d reviews)" % reviews.ratings(restaurant_id="rest_0001"))


@pytest.mark.fr("FR-19")
def test_top_dishes_by_cuisine(evidence):
    """Input: min 3 votes, top 5. Expected: per cuisine, <= 5 dishes with >= 3 votes, sorted by average desc."""
    groups = reviews.top_dishes(min_votes=3, top=5)
    assert groups
    for g in groups:
        assert len(g["top"]) <= 5 and all(t["votes"] >= 3 for t in g["top"])
        avgs = [t["avg"] for t in g["top"]]
        assert avgs == sorted(avgs, reverse=True)
    mex = next(g for g in groups if g["_id"] == "mexican")
    evidence("mexican: " + ", ".join("%s @ %s %.2f" % (t["dish"], t["restaurant"], t["avg"]) for t in mex["top"][:3]))
