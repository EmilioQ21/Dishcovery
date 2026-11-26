from functools import lru_cache

from pymongo import MongoClient

from dishcovery import config


@lru_cache(maxsize=1)
def get_mongo_client():
    return MongoClient(config.MONGO_URI, serverSelectionTimeoutMS=5000, tz_aware=True)


def get_db():
    return get_mongo_client()[config.MONGO_DB]


def ping():
    get_mongo_client().admin.command("ping")
    return True
