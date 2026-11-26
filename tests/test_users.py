"""FR-01..FR-05 and FR-12..FR-14 (MongoDB, plus the Dgraph copy of the user)."""
import uuid

import pytest
from conftest import DEMO_USER, PASSWORD, dgraph_one
from pymongo.errors import WriteError

from dishcovery.services import users
from dishcovery.services.errors import AuthError, DishcoveryError


@pytest.mark.fr("FR-01")
def test_register_user_and_reject_duplicate_email(fresh_user, db, evidence):
    """Input: new e-mail + password. Expected: users document created (bcrypt hash), User node in Dgraph, duplicate e-mail rejected."""
    doc = db.users.find_one({"_id": fresh_user["_id"]})
    assert doc and doc["password_hash"].startswith("$2b$") and doc["password_hash"] != PASSWORD
    node = dgraph_one('{ u(func: eq(user_id, "%s")) { user_id name } }' % fresh_user["_id"])
    assert node and node["name"] == fresh_user["name"]
    with pytest.raises(DishcoveryError, match="already exists"):
        users.register(fresh_user["email"].upper(), PASSWORD, "Someone else")
    evidence("created %s in MongoDB + Dgraph; duplicate e-mail -> E11000 (ux_email)" % fresh_user["_id"])


@pytest.mark.fr("FR-01")
def test_register_rejects_invalid_email_by_validator():
    """Input: e-mail without @. Expected: the $jsonSchema validator rejects the document."""
    with pytest.raises(WriteError):
        users.register("not-an-email", PASSWORD, "Bad Email")


@pytest.mark.fr("FR-02")
def test_login_and_logout(fresh_user, evidence):
    """Steps: login with valid / invalid password, then logout. Expected: session token only for valid credentials; token invalid after logout."""
    token, uid = users.login(fresh_user["email"], PASSWORD)
    assert uid == fresh_user["_id"] and users.user_from_token(token) == uid
    with pytest.raises(AuthError):
        users.login(fresh_user["email"], "wrong-password")
    assert users.logout(token)
    with pytest.raises(AuthError):
        users.user_from_token(token)
    evidence("valid login -> session %s...; wrong password -> AuthError; after logout token rejected" % token[:8])


@pytest.mark.fr("FR-03")
def test_edit_profile(fresh_user, evidence):
    """Input: new name, city and bio. Expected: fields persist when the profile is read again (and the Dgraph name follows)."""
    users.update_profile(fresh_user["_id"], name="Renamed User", city="Guadalajara", bio="Loves birria")
    u = users.get_user(fresh_user["_id"])
    assert (u["name"], u["city"], u["bio"]) == ("Renamed User", "Guadalajara", "Loves birria")
    assert dgraph_one('{ u(func: eq(user_id, "%s")) { name } }' % fresh_user["_id"])["name"] == "Renamed User"
    evidence(u["name"] + " / " + u["city"])


@pytest.mark.fr("FR-04")
def test_set_preferences(fresh_user, evidence):
    """Input: cuisines, dietary, price range 1-2. Expected: saved in users.preferences; invalid range rejected."""
    users.set_preferences(fresh_user["_id"], ["mexican", "japanese"], ["vegetarian"], [1, 2])
    prefs = users.get_user(fresh_user["_id"])["preferences"]
    assert prefs == {"cuisines": ["mexican", "japanese"], "dietary": ["vegetarian"], "price_range": [1, 2]}
    with pytest.raises(DishcoveryError):
        users.set_preferences(fresh_user["_id"], price_range=[3, 1])
    evidence(prefs)


@pytest.mark.fr("FR-05")
def test_delete_account(db, evidence):
    """Steps: register, delete account. Expected: user removed from MongoDB and Dgraph, login fails."""
    email = "delete_%s@example.com" % uuid.uuid4().hex[:8]
    u = users.register(email, PASSWORD, "To Delete")
    users.delete_account(u["_id"])
    assert db.users.find_one({"_id": u["_id"]}) is None
    assert dgraph_one('{ u(func: eq(user_id, "%s")) { uid } }' % u["_id"]) is None
    with pytest.raises(AuthError):
        users.login(email, PASSWORD)
    evidence("%s deleted; login -> AuthError" % u["_id"])


@pytest.mark.fr("FR-12")
def test_favorite_restaurant(fresh_user, evidence):
    """Input: rest_0001 added twice. Expected: stored once in favorites.restaurants ($addToSet), removable."""
    users.add_favorite(fresh_user["_id"], "restaurant", "rest_0001")
    fav = users.add_favorite(fresh_user["_id"], "restaurant", "rest_0001")
    assert fav["restaurants"] == ["rest_0001"]
    assert "rest_0001" not in users.remove_favorite(fresh_user["_id"], "restaurant", "rest_0001")["restaurants"]
    evidence(fav)


@pytest.mark.fr("FR-13")
def test_favorite_dish(fresh_user, evidence):
    """Input: dish_0006. Expected: id added to favorites.dishes; unknown dish rejected."""
    fav = users.add_favorite(fresh_user["_id"], "dish", "dish_0006")
    assert "dish_0006" in fav["dishes"]
    with pytest.raises(DishcoveryError):
        users.add_favorite(fresh_user["_id"], "dish", "dish_9999")
    evidence(fav)


@pytest.mark.fr("FR-14")
def test_custom_lists(fresh_user, evidence):
    """Steps: create 'Want to try', add a restaurant and a dish, remove one, repeat the name. Expected: items updated; duplicate name rejected."""
    lst = users.create_list(fresh_user["_id"], "Want to try")
    users.add_to_list(fresh_user["_id"], lst["_id"], "restaurant", "rest_0005")
    lst2 = users.add_to_list(fresh_user["_id"], lst["_id"], "dish", "dish_0006")
    assert len(lst2["items"]) == 2
    lst3 = users.remove_from_list(fresh_user["_id"], lst["_id"], "rest_0005")
    assert lst3["items"] == [{"type": "dish", "ref_id": "dish_0006"}]
    with pytest.raises(DishcoveryError):
        users.create_list(fresh_user["_id"], "Want to try")
    evidence("%s items=%s" % (lst["_id"], lst3["items"]))


@pytest.mark.fr("FR-02")
def test_demo_user_can_log_in():
    """Input: seeded demo account (emilio@example.com / dishcovery123). Expected: login succeeds."""
    token, uid = users.login("emilio@example.com", PASSWORD)
    assert uid == DEMO_USER
    users.logout(token)
