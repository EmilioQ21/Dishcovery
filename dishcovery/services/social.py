"""Social graph features (FR-26..FR-31)."""
from dishcovery.queries import dgraph_queries as dq
from dishcovery.queries import mongo_queries as mq
from dishcovery.services.errors import DishcoveryError
from dishcovery.services.users import get_user, log


def follow(user_id, other_id):                                        # FR-26
    if user_id == other_id:
        raise DishcoveryError("you cannot follow yourself")
    get_user(other_id)
    dq.follow(user_id, other_id)
    log(user_id, "follow", "user", other_id)


def unfollow(user_id, other_id):                                      # FR-26
    dq.unfollow(user_id, other_id)
    log(user_id, "unfollow", "user", other_id)


def followers(user_id):                                               # FR-27
    return dq.followers(user_id)


def feed(user_id, n=20):                                              # FR-28: Dgraph ids -> MongoDB content
    ids, _ = dq.feed_review_ids(user_id, n)
    return mq.reviews_by_ids(ids) if ids else []


def recommend(user_id, n=10):                                         # FR-29
    return dq.recommend(user_id, n)


def suggest_people(user_id, n=10):                                    # FR-30
    return dq.suggest_people(user_id, n)


def network_picks(user_id, restaurant_id):                            # FR-31
    return dq.network_picks(user_id, restaurant_id)
