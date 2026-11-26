"""Check-ins, passport, activity, search history, trending and personal stats (FR-20..FR-25)."""
from dishcovery.queries import cassandra_queries as cq
from dishcovery.queries import dgraph_queries as dq
from dishcovery.queries import mongo_queries as mq
from dishcovery.services.catalog import get_restaurant


def checkin(user_id, restaurant_id):                                  # FR-20
    rest = get_restaurant(restaurant_id)
    ts = cq.record_checkin(user_id, rest)
    return rest, ts


def passport(user_id, limit=50):                                      # FR-21
    return cq.passport(user_id, limit)


def recent_activity(user_id, limit=20):                               # FR-22
    return cq.recent_activity(user_id, limit)


def search_history(user_id, limit=10):                                # FR-23
    return cq.search_history(user_id, limit)


def trending(city, days=7, top=10):                                   # FR-24
    ranking, per_day = cq.trending(city, days, top)
    dish_names = mq.names("dishes", [d for d, _ in ranking])
    return [(d, dish_names.get(d, d), v) for d, v in ranking], per_day


def personal_stats(user_id, months=6):                                # FR-25 (3 databases)
    visits_per_month, cuisines = cq.monthly_stats(user_id, months)
    graph_cuisines, rating_groups = dq.taste_profile(user_id)
    return {
        "visits_per_month": visits_per_month,                         # Cassandra
        "most_visited_cuisines": cuisines,                             # Cassandra
        "reviews_by_cuisine": mq.review_stats_by_cuisine(user_id),     # MongoDB $lookup + $group
        "graph_cuisines": graph_cuisines,                              # Dgraph count + val
        "rating_distribution": rating_groups,                          # Dgraph @groupby
    }
