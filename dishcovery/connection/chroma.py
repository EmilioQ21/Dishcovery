from functools import lru_cache

import chromadb
from chromadb.utils import embedding_functions

from dishcovery import config

COLLECTIONS = ("dishes", "reviews", "restaurants")


@lru_cache(maxsize=1)
def get_chroma():
    if config.CHROMA_MODE == "http":
        return chromadb.HttpClient(host=config.CHROMA_HOST, port=config.CHROMA_PORT)
    return chromadb.PersistentClient(path=config.CHROMA_PATH)


@lru_cache(maxsize=1)
def get_embedding_function():
    """all-MiniLM-L6-v2 (384-d). Chroma ships it as an ONNX model, so no PyTorch is needed.
    Any other name is loaded with sentence-transformers (pip install sentence-transformers),
    e.g. EMBEDDING_MODEL=paraphrase-multilingual-MiniLM-L12-v2 for Spanish text."""
    if config.EMBEDDING_MODEL == "all-MiniLM-L6-v2":
        return embedding_functions.ONNXMiniLM_L6_V2()
    return embedding_functions.SentenceTransformerEmbeddingFunction(model_name=config.EMBEDDING_MODEL)


def get_collection(name):
    return get_chroma().get_collection(name, embedding_function=get_embedding_function())


def create_collection(name, recreate=False):
    """Collection with cosine distance and the configured embedding model recorded in its metadata."""
    client = get_chroma()
    if recreate:
        try:
            client.delete_collection(name)
        except Exception:
            pass
    meta = {"hnsw:space": "cosine", "embedding_model": config.EMBEDDING_MODEL}
    return client.get_or_create_collection(name, metadata=meta, embedding_function=get_embedding_function())


def ping():
    get_chroma().heartbeat()
    return True
