"""Users, sessions, profile, preferences, favorites and lists (FR-01..FR-05, FR-12..FR-14)."""
import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
from pymongo.errors import DuplicateKeyError

from dishcovery import config
from dishcovery.connection.mongo import get_db
from dishcovery.queries import cassandra_queries as cq
from dishcovery.queries import dgraph_queries as dq
from dishcovery.services.errors import AuthError, DishcoveryError, NotFound
from dishcovery.services.ids import next_id
from dishcovery.services.sync import handler, propagate

PUBLIC = {"password_hash": 0}
EDITABLE = {"name", "city", "bio", "photo_url"}


@handler("dgraph_upsert_user")
def _dg_user(p):
    dq.upsert_user(p)


@handler("cassandra_activity")
def _cass_activity(p):
    cq.log_activity(p["user_id"], p["event_type"], p["target_type"], p["target_id"], p.get("details"), p.get("ts"))


def log(user_id, event_type, target_type, target_id, details=None):
    propagate("cassandra_activity", {"user_id": user_id, "event_type": event_type, "target_type": target_type,
                                     "target_id": target_id, "details": details or {},
                                     "ts": datetime.now(timezone.utc)})


# ------------------------------------------------------------------ FR-01 register
def register(email, password, name, city="Guadalajara"):
    if len(password) < 8:
        raise DishcoveryError("password must have at least 8 characters")
    user = {"_id": next_id("users"), "email": email.strip().lower(),
            "password_hash": bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12)).decode(),
            "name": name, "city": city, "bio": "",
            "preferences": {"cuisines": [], "dietary": [], "price_range": [1, 4]},
            "favorites": {"restaurants": [], "dishes": []}, "created_at": datetime.now(timezone.utc)}
    try:
        get_db().users.insert_one(user)
    except DuplicateKeyError as exc:
        if "_id" in ((exc.details or {}).get("keyPattern") or {}):
            raise   # id collision (two registrations at the same instant): retry
        raise DishcoveryError("an account with this e-mail already exists") from exc
    propagate("dgraph_upsert_user", {"_id": user["_id"], "name": name, "city": city})
    return get_user(user["_id"])


# ------------------------------------------------------------------ FR-02 login / logout
def login(email, password):
    user = get_db().users.find_one({"email": email.strip().lower()})
    if not user or not bcrypt.checkpw(password.encode(), user["password_hash"].encode()):
        raise AuthError("invalid e-mail or password")
    now = datetime.now(timezone.utc)
    token = secrets.token_hex(24)
    get_db().sessions.insert_one({"_id": token, "user_id": user["_id"], "created_at": now,
                                  "expires_at": now + timedelta(hours=config.SESSION_HOURS)})
    return token, user["_id"]


def logout(token):
    return get_db().sessions.delete_one({"_id": token}).deleted_count == 1


def user_from_token(token):
    s = get_db().sessions.find_one({"_id": token, "expires_at": {"$gt": datetime.now(timezone.utc)}})
    if not s:
        raise AuthError("not logged in (or the session expired): run `login` first")
    return s["user_id"]


# ------------------------------------------------------------------ FR-03 / FR-04 profile and preferences
def get_user(user_id):
    u = get_db().users.find_one({"_id": user_id}, PUBLIC)
    if not u:
        raise NotFound("user %s not found" % user_id)
    return u


def update_profile(user_id, **fields):
    changes = {k: v for k, v in fields.items() if k in EDITABLE and v is not None}
    if not changes:
        raise DishcoveryError("nothing to update (editable: %s)" % ", ".join(sorted(EDITABLE)))
    get_db().users.update_one({"_id": user_id}, {"$set": changes})
    u = get_user(user_id)
    if {"name", "city"} & set(changes):
        propagate("dgraph_upsert_user", {"_id": user_id, "name": u["name"], "city": u.get("city", "")})
    return u


def set_preferences(user_id, cuisines=None, dietary=None, price_range=None):
    prefs = get_user(user_id).get("preferences", {})
    if cuisines is not None:
        prefs["cuisines"] = [c.strip().lower() for c in cuisines if c.strip()]
    if dietary is not None:
        prefs["dietary"] = [d.strip().lower() for d in dietary if d.strip()]
    if price_range is not None:
        lo, hi = int(price_range[0]), int(price_range[1])
        if not 1 <= lo <= hi <= 4:
            raise DishcoveryError("price range must be two levels between 1 and 4, low <= high")
        prefs["price_range"] = [lo, hi]
    get_db().users.update_one({"_id": user_id}, {"$set": {"preferences": prefs}})
    return prefs


# ------------------------------------------------------------------ FR-05 delete account
def delete_account(user_id):
    from dishcovery.services import reviews as review_service
    get_user(user_id)
    for r in get_db().reviews.find({"user_id": user_id}, {"_id": 1}):
        review_service.delete_review(user_id, r["_id"])
    db = get_db()
    db.lists.delete_many({"user_id": user_id})
    db.sessions.delete_many({"user_id": user_id})
    db.users.delete_one({"_id": user_id})
    dq.delete_user(user_id)
    cq.delete_user_data(user_id)
    return True


# ------------------------------------------------------------------ FR-12 / FR-13 favorites
def add_favorite(user_id, kind, ref_id):
    coll = {"restaurant": "restaurants", "dish": "dishes"}[kind]
    if not get_db()[coll].find_one({"_id": ref_id}, {"_id": 1}):
        raise NotFound("%s %s not found" % (kind, ref_id))
    get_db().users.update_one({"_id": user_id}, {"$addToSet": {"favorites.%s" % coll: ref_id}})
    log(user_id, "favorite", kind, ref_id)
    return get_user(user_id)["favorites"]


def remove_favorite(user_id, kind, ref_id):
    coll = {"restaurant": "restaurants", "dish": "dishes"}[kind]
    get_db().users.update_one({"_id": user_id}, {"$pull": {"favorites.%s" % coll: ref_id}})
    return get_user(user_id)["favorites"]


# ------------------------------------------------------------------ FR-14 custom lists
def create_list(user_id, name):
    doc = {"_id": next_id("lists"), "user_id": user_id, "name": name, "items": []}
    try:
        get_db().lists.insert_one(doc)
    except DuplicateKeyError as exc:
        raise DishcoveryError("you already have a list called %r" % name) from exc
    log(user_id, "list", "list", doc["_id"], {"name": name})
    return doc


def _own_list(user_id, list_id):
    lst = get_db().lists.find_one({"_id": list_id, "user_id": user_id})
    if not lst:
        raise NotFound("list %s not found for this user" % list_id)
    return lst


def add_to_list(user_id, list_id, kind, ref_id):
    _own_list(user_id, list_id)
    get_db().lists.update_one({"_id": list_id}, {"$addToSet": {"items": {"type": kind, "ref_id": ref_id}}})
    return _own_list(user_id, list_id)


def remove_from_list(user_id, list_id, ref_id):
    _own_list(user_id, list_id)
    get_db().lists.update_one({"_id": list_id}, {"$pull": {"items": {"ref_id": ref_id}}})
    return _own_list(user_id, list_id)


def get_lists(user_id):
    return list(get_db().lists.find({"user_id": user_id}))


def delete_list(user_id, list_id):
    _own_list(user_id, list_id)
    get_db().lists.delete_one({"_id": list_id})
