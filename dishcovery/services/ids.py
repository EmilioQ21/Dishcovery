import re

from dishcovery.connection.mongo import get_db

PREFIX = {"users": "user", "restaurants": "rest", "dishes": "dish", "reviews": "rev", "lists": "list"}


def next_id(collection):
    """Next shared id (user_0041, rev_0607...). The _id index makes this a single index seek."""
    prefix = PREFIX[collection]
    last = get_db()[collection].find_one({"_id": {"$regex": "^%s_[0-9]+$" % prefix}}, {"_id": 1}, sort=[("_id", -1)])
    n = int(re.sub(r"\D", "", last["_id"])) + 1 if last else 1
    return "%s_%04d" % (prefix, n)
