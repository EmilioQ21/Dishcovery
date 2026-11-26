"""Central configuration. Every connection setting is read from environment variables
(loaded from a .env file in the project root if present). See .env.example."""
import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:  # python-dotenv is optional, plain env vars still work
    pass


def _env(name, default=None, cast=str):
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return cast(value)


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"

# MongoDB
MONGO_URI = _env("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB = _env("MONGO_DB", "dishcovery")

# Cassandra
CASSANDRA_HOSTS = [h.strip() for h in _env("CASSANDRA_HOSTS", "127.0.0.1").split(",")]
CASSANDRA_PORT = _env("CASSANDRA_PORT", 9042, int)
CASSANDRA_KEYSPACE = _env("CASSANDRA_KEYSPACE", "dishcovery")
CASSANDRA_USER = _env("CASSANDRA_USER")
CASSANDRA_PASSWORD = _env("CASSANDRA_PASSWORD")

# Dgraph (gRPC port, used by pydgraph)
DGRAPH_HOST = _env("DGRAPH_HOST", "localhost:9080")

# ChromaDB: "persistent" (local folder) or "http" (Chroma server)
CHROMA_MODE = _env("CHROMA_MODE", "persistent")
CHROMA_PATH = _env("CHROMA_PATH", ".chroma")
if not Path(CHROMA_PATH).is_absolute():
    CHROMA_PATH = str(PROJECT_ROOT / CHROMA_PATH)
CHROMA_HOST = _env("CHROMA_HOST", "localhost")
CHROMA_PORT = _env("CHROMA_PORT", 8000, int)
# Embedding model: all-MiniLM-L6-v2 (384 dimensions, ONNX build bundled with Chroma), cosine distance.
EMBEDDING_MODEL = _env("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
# A retrieved chunk is "relevant" only if its cosine distance is <= this value.
CHROMA_MAX_DISTANCE = _env("CHROMA_MAX_DISTANCE", 0.65, float)

# LLM: any OpenAI-compatible chat completions endpoint (Groq, OpenAI, Gemini, Ollama...).
LLM_BASE_URL = _env("LLM_BASE_URL", "https://api.groq.com/openai/v1")
LLM_API_KEY = _env("LLM_API_KEY")
LLM_MODEL = _env("LLM_MODEL", "openai/gpt-oss-20b")
LLM_TIMEOUT = _env("LLM_TIMEOUT", 60, int)
# Language of the chatbot answers ("English", "Spanish"...), or "auto" = same language as the question
LLM_ANSWER_LANGUAGE = _env("LLM_ANSWER_LANGUAGE", "English")

# Client
SESSION_FILE = Path(_env("DISHCOVERY_SESSION_FILE", str(PROJECT_ROOT / ".session")))
SESSION_HOURS = _env("SESSION_HOURS", 24, int)
# Reference point used by "near me" queries in the demo (ITESO campus) [lon, lat]
DEFAULT_LOCATION = [_env("DEFAULT_LON", -103.4160, float), _env("DEFAULT_LAT", 20.6075, float)]
