"""Chatbot and semantic search (FR-32..FR-35): MongoDB gives location and preferences,
ChromaDB gives meaning, the LLM writes the answer from the retrieved passages."""
from dishcovery.queries import chroma_queries as ch
from dishcovery.queries import mongo_queries as mq
from dishcovery.services.users import get_user


def ask(question, user_id=None, personalize=True, near_me=False, meters=3000, use_llm=True):   # FR-32 / FR-35
    prefs = get_user(user_id).get("preferences") if (user_id and personalize) else None
    restaurant_ids = [r["_id"] for r in mq.nearby(max_meters=meters, limit=50)] if near_me else None
    return ch.answer(question, prefs=prefs, restaurant_ids=restaurant_ids, use_llm=use_llm)


def recommend_text(text, max_price=None, near_me=False, meters=2000, vegetarian=None, n=5):  # FR-33
    restaurant_ids = [r["_id"] for r in mq.nearby(max_meters=meters, limit=50)] if near_me else None
    if near_me and not restaurant_ids:
        return []
    return ch.semantic_dishes(text, n=n, max_price=max_price, restaurant_ids=restaurant_ids, vegetarian=vegetarian)


def similar(dish_id, n=5):                                            # FR-34
    return ch.similar_dishes(dish_id, n)


def personalized(user_id, text="something good for lunch", n=5):     # FR-35
    prefs = get_user(user_id).get("preferences", {})
    conds = ch.preference_filters(prefs)
    return ch.query("dishes", text=text, n=n, where=ch.where_all(conds)), ch.where_all(conds)
