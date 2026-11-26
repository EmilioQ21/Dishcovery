"""One module per engine. Each exposes a lazily created, cached client so the whole
application shares a single connection per database."""
from .cassandra import get_session
from .chroma import get_chroma, get_collection
from .dgraph import get_client
from .llm import chat_completion, llm_configured
from .mongo import get_db

__all__ = ["get_db", "get_session", "get_client", "get_chroma", "get_collection",
           "chat_completion", "llm_configured"]
