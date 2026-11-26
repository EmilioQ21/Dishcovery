"""FR-32..FR-35: ChromaDB semantic search and RAG."""
import pytest

from dishcovery.connection.llm import llm_configured
from dishcovery.queries import chroma_queries as ch
from dishcovery.queries import mongo_queries as mq
from dishcovery.services import chatbot


@pytest.mark.fr("FR-32")
def test_rag_retrieves_relevant_sources(evidence):
    """Input: 'Where can I eat good birria?'. Expected: relevant passages (distance <= threshold) about birria, cited as sources in the prompt."""
    res = chatbot.ask("Where can I eat good birria?", use_llm=False)
    assert res["found"] and res["sources"]
    assert all(s["distance"] <= res["threshold"] for s in res["sources"])
    assert any("birria" in s["document"].lower() for s in res["sources"][:3])
    assert "[S1]" in res["prompt"]
    evidence("top source %s (%.3f): %s" % (res["sources"][0]["id"], res["sources"][0]["distance"], res["sources"][0]["document"][:80]))


@pytest.mark.fr("FR-32")
@pytest.mark.skipif(not llm_configured(), reason="LLM_API_KEY not set in .env")
def test_rag_answer_from_llm_with_citations(evidence):
    """Input: same question with the LLM enabled. Expected: a non-empty answer that cites sources like [S1]."""
    res = chatbot.ask("Where can I eat good birria and what do people say about it?")
    assert res["llm_used"] and res["answer"] and "[S" in res["answer"]
    evidence(res["answer"][:250])


@pytest.mark.fr("FR-32")
def test_rag_defined_answer_when_nothing_is_relevant(evidence):
    """Input: 'How do I replace the clutch of a car?'. Expected: no passage passes the threshold and the fixed 'no information' answer is returned without calling the LLM."""
    res = chatbot.ask("How do I replace the clutch of a car transmission?")
    assert not res["found"] and res["answer"] == ch.NO_ANSWER and not res["llm_used"]
    evidence("closest distance %.3f > threshold %.2f" % (min(h["distance"] for h in res["candidates"]), res["threshold"]))


@pytest.mark.fr("FR-33")
def test_natural_language_with_price_and_location(evidence):
    """Input: 'something spicy and cheap', max price 1, within 2 km of ITESO. Expected: only cheap dishes from nearby restaurants, spicy first."""
    hits = chatbot.recommend_text("something spicy and cheap", max_price=1, near_me=True, meters=2000)
    near = {r["_id"] for r in mq.nearby(max_meters=2000, limit=50)}
    assert hits and all(h["metadata"]["price_level"] <= 1 and h["metadata"]["restaurant_id"] in near for h in hits)
    assert "spicy" in hits[0]["document"].lower() or "chile" in hits[0]["document"].lower()
    evidence(", ".join("%s %.3f" % (h["document"].split(".")[0], h["distance"]) for h in hits[:3]))


@pytest.mark.fr("FR-34")
def test_similar_dishes(evidence):
    """Input: dish_0003 (Salmon nigiri). Expected: nearest neighbours by embedding, excluding the dish itself and other copies of it; raw-fish dishes first."""
    hits = chatbot.similar("dish_0003", 5)
    names = [h["document"].split(".")[0] for h in hits]
    assert len(hits) == 5 and all(h["id"] != "dish_0003" for h in hits)
    assert "Salmon nigiri" not in names and len(set(names)) == 5
    assert any("fish" in h["document"].lower() or "sushi" in h["document"].lower() for h in hits[:2])
    evidence(", ".join(h["document"].split(".")[0] for h in hits))


@pytest.mark.fr("FR-35")
def test_preferences_become_filters(evidence):
    """Input: user_0003 (vegetarian, price 1-2). Expected: where filter built from MongoDB preferences; every suggestion vegetarian and price <= 2."""
    hits, where = chatbot.personalized("user_0003", "something filling for lunch")
    assert where == {"$and": [{"price_level": {"$lte": 2}}, {"vegetarian": True}]}
    assert hits and all(h["metadata"]["vegetarian"] and h["metadata"]["price_level"] <= 2 for h in hits)
    evidence("where=%s -> %s" % (where, ", ".join(h["document"].split(".")[0] for h in hits[:3])))
