"""FR-06..FR-11 (MongoDB catalog, copies in Dgraph and ChromaDB)."""
import pytest
from conftest import dgraph_one
from pymongo.errors import WriteError

from dishcovery.connection.chroma import get_collection
from dishcovery.services import catalog


@pytest.mark.fr("FR-06")
def test_register_restaurant(temp_restaurant, db, evidence):
    """Input: name, cuisines, price, GeoJSON point, hours, attributes. Expected: document in MongoDB, Restaurant node in Dgraph, embedding in ChromaDB."""
    doc = db.restaurants.find_one({"_id": temp_restaurant["_id"]})
    assert doc["location"]["type"] == "Point" and len(doc["location"]["coordinates"]) == 2
    assert set(doc["hours"]) == {"mon", "tue", "wed", "thu", "fri", "sat", "sun"}
    node = dgraph_one('{ r(func: eq(restaurant_id, "%s")) { name has_cuisine { cuisine_name } } }' % temp_restaurant["_id"])
    assert {c["cuisine_name"] for c in node["has_cuisine"]} == {"mexican", "street food"}
    assert get_collection("restaurants").get(ids=[temp_restaurant["_id"]])["ids"] == [temp_restaurant["_id"]]
    evidence("%s in MongoDB, Dgraph (2 cuisines), ChromaDB" % temp_restaurant["_id"])


@pytest.mark.fr("FR-06")
def test_restaurant_validator_rejects_bad_price(db):
    """Input: price_level 9. Expected: rejected by the restaurants $jsonSchema validator."""
    with pytest.raises(WriteError):
        db.restaurants.insert_one({"_id": "rest_9998", "name": "Bad", "cuisine": ["x"], "price_level": 9,
                                   "location": {"type": "Point", "coordinates": [-103.4, 20.6]}, "address": {"city": "Zapopan"}})


@pytest.mark.fr("FR-07")
def test_add_dish(temp_restaurant, db, evidence):
    """Input: dish name, price, tags. Expected: dish in dishes and in the embedded menu_summary, Dish->Restaurant edge, dish embedding."""
    d = catalog.add_dish(temp_restaurant["_id"], "Taco de birria", 35, "Beef birria taco with consome", ["spicy"], False)
    assert db.dishes.find_one({"_id": d["_id"]})["restaurant_id"] == temp_restaurant["_id"]
    menu = db.restaurants.find_one({"_id": temp_restaurant["_id"]})["menu_summary"]
    assert any(m["dish_id"] == d["_id"] for m in menu)
    node = dgraph_one('{ d(func: eq(dish_id, "%s")) { served_at { restaurant_id } } }' % d["_id"])
    assert node["served_at"]["restaurant_id"] == temp_restaurant["_id"]
    assert get_collection("dishes").get(ids=[d["_id"]])["ids"] == [d["_id"]]
    evidence("%s -> dishes, menu_summary, served_at edge, Chroma" % d["_id"])


@pytest.mark.fr("FR-08")
def test_restaurant_detail_single_read(evidence):
    """Input: rest_0001. Expected: one document read returns menu, hours, attributes and rating."""
    r = catalog.get_restaurant("rest_0001")
    for field in ("menu_summary", "hours", "attributes", "rating_avg", "rating_count", "location", "address"):
        assert field in r
    assert len(r["menu_summary"]) >= 2 and r["rating_count"] > 0
    evidence("%s: %d menu items, rating %.2f (%d)" % (r["name"], len(r["menu_summary"]), r["rating_avg"], r["rating_count"]))


@pytest.mark.fr("FR-09")
def test_search_by_cuisine_and_price(evidence):
    """Input: cuisine=mexican, max price 2. Expected: only mexican restaurants with price <= 2, sorted by rating desc."""
    res = catalog.search(cuisine="mexican", max_price=2)["results"]
    assert res
    assert all("mexican" in r["cuisine"] and r["price_level"] <= 2 for r in res)
    ratings = [r["rating_avg"] for r in res]
    assert ratings == sorted(ratings, reverse=True)
    evidence(", ".join("%s(%.1f)" % (r["name"], r["rating_avg"]) for r in res[:4]))


@pytest.mark.fr("FR-09")
def test_text_search_with_facets(evidence):
    """Input: text 'ramen'. Expected: matching restaurants plus facet counts by cuisine, price and city ($facet)."""
    res = catalog.search(text="ramen")
    assert res["results"] and any("ramen" in r["name"].lower() for r in res["results"])
    assert sum(f["n"] for f in res["by_price_level"]) == len(res["results"]) or len(res["results"]) == 10
    assert res["by_cuisine"] and res["by_city"]
    evidence("%d results; by_cuisine=%s" % (len(res["results"]), res["by_cuisine"][:3]))


@pytest.mark.fr("FR-10")
def test_nearby_restaurants(evidence):
    """Input: ITESO coordinates, 2 km. Expected: $geoNear results sorted by distance, all within 2000 m."""
    res = catalog.near(meters=2000)
    assert res
    d = [r["distance_m"] for r in res]
    assert d == sorted(d) and d[-1] <= 2000
    evidence(", ".join("%s %dm" % (r["name"], r["distance_m"]) for r in res[:4]))


@pytest.mark.fr("FR-11")
def test_filter_by_attributes(db, evidence):
    """Input: terrace=true and pet_friendly=true. Expected: only restaurants with both flags, same count as a direct count."""
    res = catalog.filter_attributes(terrace=True, pet_friendly=True)
    assert all(r["attributes"]["terrace"] and r["attributes"]["pet_friendly"] for r in res)
    expected = db.restaurants.count_documents({"attributes.terrace": True, "attributes.pet_friendly": True})
    assert len(res) == min(expected, 20)
    evidence("%d restaurants with terrace + pet friendly" % len(res))
