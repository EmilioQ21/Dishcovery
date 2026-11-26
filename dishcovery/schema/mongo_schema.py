"""MongoDB: collections, $jsonSchema validators and indexes.

Every validator and index carries the rule it enforces / the query it serves (FR ids)."""
from pymongo import ASCENDING, DESCENDING, GEOSPHERE, TEXT, IndexModel

from dishcovery.connection.mongo import get_db

ID_PATTERN = {
    "user": "^user_[0-9]{4,}$",
    "rest": "^rest_[0-9]{4,}$",
    "dish": "^dish_[0-9]{4,}$",
    "rev": "^rev_[0-9]{4,}$",
    "list": "^list_[0-9]{4,}$",
}
PRICE_LEVEL = {"bsonType": "int", "minimum": 1, "maximum": 4}

VALIDATORS = {
    # FR-01..FR-05, FR-12, FR-13
    "users": {
        "bsonType": "object",
        "required": ["_id", "email", "password_hash", "name", "created_at"],
        "properties": {
            "_id": {"bsonType": "string", "pattern": ID_PATTERN["user"]},
            "email": {"bsonType": "string", "pattern": "^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$",
                      "description": "must be a valid e-mail address"},
            "password_hash": {"bsonType": "string", "minLength": 20,
                              "description": "bcrypt hash, never the plain password"},
            "name": {"bsonType": "string", "minLength": 1, "maxLength": 80},
            "city": {"bsonType": "string"},
            "bio": {"bsonType": "string", "maxLength": 300},
            "photo_url": {"bsonType": "string"},
            "preferences": {
                "bsonType": "object",
                "properties": {
                    "cuisines": {"bsonType": "array", "items": {"bsonType": "string"}},
                    "dietary": {"bsonType": "array", "items": {
                        "enum": ["vegetarian", "vegan", "gluten_free", "lactose_free", "halal", "kosher"]}},
                    "price_range": {"bsonType": "array", "minItems": 2, "maxItems": 2, "items": PRICE_LEVEL},
                },
            },
            "favorites": {
                "bsonType": "object",
                "properties": {
                    "restaurants": {"bsonType": "array", "uniqueItems": True, "items": {"bsonType": "string"}},
                    "dishes": {"bsonType": "array", "uniqueItems": True, "items": {"bsonType": "string"}},
                },
            },
            "created_at": {"bsonType": "date"},
        },
    },
    # FR-02 (login / logout)
    "sessions": {
        "bsonType": "object",
        "required": ["_id", "user_id", "created_at", "expires_at"],
        "properties": {
            "_id": {"bsonType": "string", "minLength": 32},
            "user_id": {"bsonType": "string", "pattern": ID_PATTERN["user"]},
            "created_at": {"bsonType": "date"},
            "expires_at": {"bsonType": "date"},
        },
    },
    # FR-06, FR-08..FR-11
    "restaurants": {
        "bsonType": "object",
        "required": ["_id", "name", "cuisine", "price_level", "location", "address"],
        "properties": {
            "_id": {"bsonType": "string", "pattern": ID_PATTERN["rest"]},
            "name": {"bsonType": "string", "minLength": 1},
            "cuisine": {"bsonType": "array", "minItems": 1, "items": {"bsonType": "string"}},
            "price_level": PRICE_LEVEL,
            "description": {"bsonType": "string"},
            "location": {
                "bsonType": "object",
                "required": ["type", "coordinates"],
                "properties": {
                    "type": {"enum": ["Point"]},
                    "coordinates": {"bsonType": "array", "minItems": 2, "maxItems": 2,
                                    "items": {"bsonType": ["double", "int"]}},
                },
                "description": "GeoJSON Point [longitude, latitude]",
            },
            "address": {"bsonType": "object", "required": ["city"],
                        "properties": {"city": {"bsonType": "string"}}},
            "hours": {"bsonType": "object"},
            "attributes": {"bsonType": "object",
                           "additionalProperties": {"bsonType": "bool"},
                           "description": "flags such as terrace, pet_friendly (booleans only)"},
            "menu_summary": {"bsonType": "array", "items": {
                "bsonType": "object", "required": ["dish_id", "name", "price"]}},
            "rating_avg": {"bsonType": ["double", "int"], "minimum": 0, "maximum": 5},
            "rating_count": {"bsonType": "int", "minimum": 0},
        },
    },
    # FR-07
    "dishes": {
        "bsonType": "object",
        "required": ["_id", "restaurant_id", "name", "price", "price_level"],
        "properties": {
            "_id": {"bsonType": "string", "pattern": ID_PATTERN["dish"]},
            "restaurant_id": {"bsonType": "string", "pattern": ID_PATTERN["rest"]},
            "restaurant_name": {"bsonType": "string"},
            "name": {"bsonType": "string", "minLength": 1},
            "price": {"bsonType": ["double", "int"], "minimum": 0},
            "price_level": PRICE_LEVEL,
            "description": {"bsonType": "string"},
            "tags": {"bsonType": "array", "items": {"bsonType": "string"}},
            "vegetarian": {"bsonType": "bool"},
            "rating_avg": {"bsonType": ["double", "int"], "minimum": 0, "maximum": 5},
            "rating_count": {"bsonType": "int", "minimum": 0},
        },
    },
    # FR-15, FR-16
    "reviews": {
        "bsonType": "object",
        "required": ["_id", "user_id", "restaurant_id", "rating", "text", "created_at"],
        "properties": {
            "_id": {"bsonType": "string", "pattern": ID_PATTERN["rev"]},
            "user_id": {"bsonType": "string", "pattern": ID_PATTERN["user"]},
            "restaurant_id": {"bsonType": "string", "pattern": ID_PATTERN["rest"]},
            "dish_id": {"bsonType": ["string", "null"]},
            "rating": {"bsonType": "int", "minimum": 1, "maximum": 5,
                       "description": "integer rating from 1 to 5"},
            "text": {"bsonType": "string", "minLength": 3, "maxLength": 2000},
            "created_at": {"bsonType": "date"},
            "updated_at": {"bsonType": "date"},
        },
    },
    # FR-14
    "lists": {
        "bsonType": "object",
        "required": ["_id", "user_id", "name", "items"],
        "properties": {
            "_id": {"bsonType": "string", "pattern": ID_PATTERN["list"]},
            "user_id": {"bsonType": "string", "pattern": ID_PATTERN["user"]},
            "name": {"bsonType": "string", "minLength": 1, "maxLength": 60},
            "items": {"bsonType": "array", "items": {
                "bsonType": "object", "required": ["type", "ref_id"],
                "properties": {"type": {"enum": ["restaurant", "dish"]},
                               "ref_id": {"bsonType": "string"}}}},
        },
    },
    # Writes to Cassandra/Dgraph/Chroma that failed and must be retried (cross-database consistency)
    "sync_queue": {
        "bsonType": "object",
        "required": ["op", "payload", "created_at", "attempts"],
        "properties": {
            "op": {"bsonType": "string"},
            "payload": {"bsonType": "object"},
            "error": {"bsonType": "string"},
            "attempts": {"bsonType": "int", "minimum": 0},
            "created_at": {"bsonType": "date"},
        },
    },
}

INDEXES = {
    "users": [
        # FR-01 / FR-02: login lookup + duplicate e-mails rejected by the database
        IndexModel([("email", ASCENDING)], unique=True, name="ux_email"),
    ],
    "sessions": [
        # FR-02: sessions disappear automatically when they expire (TTL index)
        IndexModel([("expires_at", ASCENDING)], expireAfterSeconds=0, name="ttl_expires_at"),
        IndexModel([("user_id", ASCENDING)], name="ix_user"),
    ],
    "restaurants": [
        # FR-10: $geoNear requires a 2dsphere index
        IndexModel([("location", GEOSPHERE)], name="geo_location"),
        # FR-09: ESR rule (Equality, Sort, Range): cuisine (equality), rating_avg (sort), price_level (range),
        # so results come out of the index already sorted by rating, with no in-memory SORT stage
        IndexModel([("cuisine", ASCENDING), ("rating_avg", DESCENDING), ("price_level", ASCENDING)],
                   name="ix_cuisine_rating_price"),
        # FR-09: keyword search on name, cuisine and description
        IndexModel([("name", TEXT), ("cuisine", TEXT), ("description", TEXT)],
                   weights={"name": 10, "cuisine": 5, "description": 1}, name="txt_search"),
        # FR-11: most used attribute filters
        IndexModel([("attributes.terrace", ASCENDING)], name="ix_attr_terrace"),
        IndexModel([("attributes.vegetarian_options", ASCENDING)], name="ix_attr_vegetarian"),
        IndexModel([("attributes.pet_friendly", ASCENDING)], name="ix_attr_pet"),
    ],
    "dishes": [
        # FR-07 / FR-08: a restaurant's dishes without a collection scan
        IndexModel([("restaurant_id", ASCENDING)], name="ix_restaurant"),
    ],
    "reviews": [
        # FR-17 (Mongo side) / FR-18: latest reviews of a restaurant, ratings per restaurant
        IndexModel([("restaurant_id", ASCENDING), ("created_at", DESCENDING)], name="ix_rest_date"),
        # FR-18 / FR-19: ratings per dish
        IndexModel([("dish_id", ASCENDING)], name="ix_dish"),
        # FR-15 / FR-16: one review per user per (restaurant, dish); dish_id is null for a
        # restaurant-level review, so a user can also leave exactly one review per restaurant.
        IndexModel([("user_id", ASCENDING), ("restaurant_id", ASCENDING), ("dish_id", ASCENDING)],
                   unique=True, name="ux_user_rest_dish"),
        # FR-25 / FR-28: a user's reviews by date
        IndexModel([("user_id", ASCENDING), ("created_at", DESCENDING)], name="ix_user_date"),
    ],
    "lists": [
        # FR-14: a user cannot have two lists with the same name
        IndexModel([("user_id", ASCENDING), ("name", ASCENDING)], unique=True, name="ux_user_listname"),
    ],
    "sync_queue": [IndexModel([("created_at", ASCENDING)], name="ix_created")],
}


def create(drop=False):
    db = get_db()
    existing = set(db.list_collection_names())
    for name, schema in VALIDATORS.items():
        if drop and name in existing:
            db.drop_collection(name)
            existing.discard(name)
        if name in existing:
            db.command("collMod", name, validator={"$jsonSchema": schema},
                       validationLevel="strict", validationAction="error")
        else:
            db.create_collection(name, validator={"$jsonSchema": schema},
                                 validationLevel="strict", validationAction="error")
        if INDEXES.get(name):
            db[name].create_indexes(INDEXES[name])
    return sorted(VALIDATORS)
