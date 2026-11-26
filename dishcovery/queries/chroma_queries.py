"""ChromaDB: what gets embedded, semantic search with metadata filters, and RAG."""
from dishcovery import config
from dishcovery.connection.chroma import get_collection


# ------------------------------------------------------------------ documents (what is embedded)
def dish_document(dish, rest):
    return ("%s. %s Tags: %s. Served at %s (cuisine: %s; %s). Price: %s MXN." % (
        dish["name"], dish.get("description", ""), ", ".join(dish.get("tags", [])), rest["name"],
        ", ".join(rest["cuisine"]), rest["address"]["city"], dish["price"]))


def dish_metadata(dish, rest):
    return {"dish_id": dish["_id"], "restaurant_id": rest["_id"], "restaurant_name": rest["name"],
            "cuisine": rest["cuisine"][0], "price_level": int(dish["price_level"]),
            "city": rest["address"]["city"], "vegetarian": bool(dish.get("vegetarian", False))}


def review_document(review, rest_name, dish_name=None):
    about = "%s at %s" % (dish_name, rest_name) if dish_name else rest_name
    return "Review of %s, rated %d/5: %s" % (about, review["rating"], review["text"])


def review_metadata(review, rest_name, dish_name=None):
    return {"review_id": review["_id"], "restaurant_id": review["restaurant_id"], "restaurant_name": rest_name,
            "dish_id": review.get("dish_id") or "", "dish_name": dish_name or "",
            "user_id": review["user_id"], "rating": int(review["rating"])}


def restaurant_document(rest, dish_names):
    return "%s. %s food in %s, %s. %s Menu: %s." % (
        rest["name"], ", ".join(rest["cuisine"]).capitalize(), rest["address"].get("neighborhood", ""),
        rest["address"]["city"], rest.get("description", ""), ", ".join(dish_names))


def restaurant_metadata(rest):
    attrs = rest.get("attributes", {})
    return {"restaurant_id": rest["_id"], "name": rest["name"], "cuisine": rest["cuisine"][0],
            "price_level": int(rest["price_level"]), "city": rest["address"]["city"],
            "terrace": bool(attrs.get("terrace", False)), "pet_friendly": bool(attrs.get("pet_friendly", False))}


# ------------------------------------------------------------------ writes (sync from MongoDB)
def upsert(collection, ids, documents, metadatas, batch=200):
    coll = get_collection(collection)
    for i in range(0, len(ids), batch):
        coll.upsert(ids=ids[i:i + batch], documents=documents[i:i + batch], metadatas=metadatas[i:i + batch])


def delete(collection, ids):
    get_collection(collection).delete(ids=list(ids))


# ------------------------------------------------------------------ helpers
def where_all(conditions):
    conditions = [c for c in conditions if c]
    if not conditions:
        return None
    return conditions[0] if len(conditions) == 1 else {"$and": conditions}


def _hits(res):
    out = []
    for i, doc_id in enumerate(res["ids"][0]):
        out.append({"id": doc_id, "distance": round(float(res["distances"][0][i]), 4),
                    "document": res["documents"][0][i], "metadata": res["metadatas"][0][i]})
    return out


def query(collection, text=None, embedding=None, n=5, where=None):
    kwargs = {"n_results": n, "include": ["documents", "metadatas", "distances"]}
    if where:
        kwargs["where"] = where
    if embedding is not None:
        kwargs["query_embeddings"] = [embedding]
    else:
        kwargs["query_texts"] = [text]
    return _hits(get_collection(collection).query(**kwargs))


def preference_filters(prefs):
    """FR-35: the user's MongoDB preferences become Chroma metadata filters."""
    conds = []
    if prefs:
        pr = prefs.get("price_range")
        if pr:
            conds.append({"price_level": {"$lte": int(pr[1])}})
        if "vegetarian" in prefs.get("dietary", []) or "vegan" in prefs.get("dietary", []):
            conds.append({"vegetarian": True})
    return conds


# ------------------------------------------------------------------ semantic queries
def semantic_dishes(text, n=5, max_price=None, restaurant_ids=None, vegetarian=None, extra=None):  # FR-33
    conds = list(extra or [])
    if max_price:
        conds.append({"price_level": {"$lte": int(max_price)}})
    if restaurant_ids:
        conds.append({"restaurant_id": {"$in": list(restaurant_ids)}})
    if vegetarian:
        conds.append({"vegetarian": True})
    return query("dishes", text=text, n=n, where=where_all(conds))


def similar_dishes(dish_id, n=5):                                            # FR-34
    coll = get_collection("dishes")
    got = coll.get(ids=[dish_id], include=["embeddings"])
    if not len(got["ids"]):
        raise KeyError(dish_id)
    emb = [float(x) for x in got["embeddings"][0]]
    own_name = coll.get(ids=[dish_id], include=["documents"])["documents"][0].split(".")[0]
    seen, out = {own_name}, []
    # the same dish name is served at several restaurants: skip copies of the dish itself and repeated names
    for h in query("dishes", embedding=emb, n=n * 6):
        name = h["document"].split(".")[0]
        if h["id"] != dish_id and name not in seen:
            seen.add(name)
            out.append(h)
    return out[:n]


def embed(texts):
    from dishcovery.connection.chroma import get_embedding_function
    return [[float(x) for x in v] for v in get_embedding_function()(list(texts))]


# ------------------------------------------------------------------ RAG (FR-32, FR-35)
NO_ANSWER = ("I could not find anything in Dishcovery related to your question. "
             "Try asking about a dish, a type of food or a restaurant in Guadalajara.")

SYSTEM_PROMPT = (
    "You are the Dishcovery food assistant for Guadalajara, Mexico. Answer ONLY with the information in the "
    "context. Cite every fact with the source tag in brackets, for example [S2]. If the context does not "
    "answer the question, say that Dishcovery has no information about it. Keep the answer under 120 words. ")


def system_prompt():
    lang = config.LLM_ANSWER_LANGUAGE
    if lang.lower() == "auto":
        return SYSTEM_PROMPT + "Answer in the same language as the question."
    return SYSTEM_PROMPT + "Always answer in %s, even if the question is in another language." % lang


def retrieve(question, where_dishes=None, n_dishes=4, n_reviews=4, n_restaurants=2, max_distance=None):
    max_distance = config.CHROMA_MAX_DISTANCE if max_distance is None else max_distance
    hits = []
    for coll, n, where in (("dishes", n_dishes, where_dishes), ("reviews", n_reviews, None),
                           ("restaurants", n_restaurants, None)):
        for h in query(coll, text=question, n=n, where=where):
            h["collection"] = coll
            hits.append(h)
    relevant = sorted([h for h in hits if h["distance"] <= max_distance], key=lambda h: h["distance"])
    return relevant, hits


def build_prompt(question, sources):
    context = "\n".join("[S%d] (%s %s) %s" % (i + 1, s["collection"][:-1], s["id"], s["document"])
                        for i, s in enumerate(sources))
    return "Context:\n%s\n\nQuestion: %s" % (context, question)


def answer(question, prefs=None, restaurant_ids=None, use_llm=True, max_distance=None):
    from dishcovery.connection.llm import chat_completion, llm_configured
    conds = preference_filters(prefs)
    if restaurant_ids:
        conds.append({"restaurant_id": {"$in": list(restaurant_ids)}})
    where = where_all(conds)
    relevant, all_hits = retrieve(question, where_dishes=where, max_distance=max_distance)
    result = {"question": question, "filters": where, "sources": relevant, "candidates": all_hits,
              "threshold": config.CHROMA_MAX_DISTANCE if max_distance is None else max_distance}
    if not relevant:
        result.update(answer=NO_ANSWER, found=False, llm_used=False, prompt=None)
        return result
    prompt = build_prompt(question, relevant)
    result.update(found=True, prompt=prompt)
    if use_llm and llm_configured():
        result.update(answer=chat_completion(system_prompt(), prompt), llm_used=True, model=config.LLM_MODEL)
    else:
        top = relevant[:3]
        result.update(llm_used=False, answer="(LLM not configured: showing the most relevant passages) " +
                      " ".join("[S%d] %s" % (i + 1, s["document"]) for i, s in enumerate(top)))
    return result
