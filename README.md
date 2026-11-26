# Dishcovery

Restaurant and dish discovery for the Guadalajara metro area, built on four NoSQL databases,
each used for the part of the problem it handles best:

| Database  | Role | Examples |
|-----------|------|----------|
| **MongoDB**   | Source of truth: users, sessions, restaurants, dishes, reviews, lists | profile, restaurant detail, `$geoNear`, `$text` + `$facet`, rating pipelines |
| **Cassandra** | Time-ordered, write-heavy activity, one table per access pattern | food passport, recent activity, search history, trending dishes |
| **Dgraph**    | Social and taste graph (multi-hop questions) | followers, feed, "people like you also loved…", friends of friends |
| **ChromaDB**  | Embeddings + RAG chatbot | "something spicy and cheap near campus", similar dishes, Q&A with sources |

Every entity has the **same id in all four databases** (`user_0001`, `rest_0001`, `dish_0001`, `rev_0001`).
MongoDB is written first; the application then propagates derived copies to Cassandra, Dgraph and
ChromaDB. A failed derived write is stored in the MongoDB `sync_queue` collection and can be replayed
(`python -m dishcovery sync retry`).

## Folder structure

```
code/
├── README.md  requirements.txt  .env.example  docker-compose.yml  pytest.ini
├── data/
│   ├── core_seed.json            records from the Intermediate Revision (kept unchanged)
│   └── dishcovery_data.json      full dataset (generated, deterministic)
├── dishcovery/
│   ├── config.py                 all settings, read from environment variables / .env
│   ├── connection/               one client per engine + LLM client
│   ├── schema/                   mongo_schema.py ($jsonSchema + indexes), schema.cql, schema.dql, init_all.py
│   ├── loading/                  generate_data.py, load_all.py
│   ├── queries/                  mongo_queries.py, cassandra_queries.py, dgraph_queries.py, chroma_queries.py
│   ├── services/                 business logic and cross-database writes (users, catalog, reviews, activity, social, chatbot, sync)
│   └── client/cli.py             command line client (also an interactive shell)
└── tests/                        pytest acceptance tests, one or more per requirement -> tests/results/results.md
```

## Prerequisites

- Python 3.10 – 3.13 (on 3.12+ `pyasyncore` is installed automatically for cassandra-driver)
- Docker Desktop (or local installs of MongoDB 7, Cassandra 4.1 and Dgraph)
- Internet the first time: pip packages and the embedding model (~80 MB, downloaded automatically by Chroma)
- Optional: an API key for an OpenAI-compatible LLM (Groq has a free tier) for generated chatbot answers

## Installation

```powershell
cd code
python -m venv venv
venv\Scripts\activate            # macOS/Linux: source venv/bin/activate
pip install -r requirements.txt
copy .env.example .env           # macOS/Linux: cp .env.example .env   -> then set LLM_API_KEY
```

## 1. Start the databases

```powershell
docker compose up -d
docker compose ps                # wait until dishcovery-cassandra shows (healthy), about 1-2 minutes
```

Ratel (Dgraph UI): http://localhost:8000 → connect to `http://localhost:8080`.

## 2. Create the schemas and load the data

```powershell
python -m dishcovery status                    # the 4 databases must answer OK
python -m dishcovery.loading.load_all          # creates every schema (wipes old data) and loads the dataset
```

`load_all` first runs `python -m dishcovery.schema.init_all --reset`, which creates:

- **MongoDB**: 7 collections with `$jsonSchema` validators, unique/compound/2dsphere/text/TTL indexes
- **Cassandra**: keyspace `dishcovery` and 6 query tables (`dishcovery/schema/schema.cql`)
- **Dgraph**: predicates, indexes, `@upsert`, `@reverse`, `@count` and 5 types (`dishcovery/schema/schema.dql`)
- **ChromaDB**: collections `dishes`, `reviews`, `restaurants` (cosine distance, all-MiniLM-L6-v2)

Then it loads 40 users, 60 restaurants, 223 dishes, ~600 reviews, ~770 visits, ~150 searches, 17 lists,
~220 follow edges and 14 days of dish views. Every user's password is **`dishcovery123`**.
To regenerate the dataset: `python -m dishcovery.loading.generate_data` (same seed → same ids).

## 3. Run the client

```powershell
python -m dishcovery --help
python -m dishcovery shell               # interactive mode: connections stay open (best for the demo)
```

Demo walkthrough (inside `shell`, or prefix each line with `python -m dishcovery`):

```
login --email emilio@example.com --password dishcovery123
near                                     # FR-10 restaurants within 2 km of ITESO
search ramen                             # FR-09 text search + facets
restaurant show rest_0004                # FR-08 full detail in one read
review write --restaurant rest_0004 --dish dish_0006 --rating 5 --text "Best birria in town"   # FR-15: 4 databases
review list rest_0004                    # FR-17 Cassandra, newest first
feed                                     # FR-28 Dgraph ids -> MongoDB content
recommend                                # FR-29 5-hop recommendation
ask "Where can I eat good birria and what do people say about it?" --show-prompt   # FR-32 RAG
ask "How do I change a car tire?"        # FR-32 defined answer when nothing is relevant
discover "something spicy and cheap" --max-price 1 --near                          # FR-33
explain                                  # index / partition / latency evidence
```

All commands (FR = requirement covered):

| Area | Commands |
|------|----------|
| Users (FR-01..05) | `register`, `login`, `logout`, `whoami`, `profile`, `prefs`, `delete-account` |
| Favorites, lists (FR-12..14) | `fav add/remove/list`, `list create/add/remove/delete/show` |
| Catalog (FR-06..11) | `restaurant show/create`, `dish show/add/similar`, `search`, `near`, `filter` |
| Reviews (FR-15..19) | `review write/edit/delete/list/mine`, `ratings`, `top-dishes` |
| Activity (FR-20..25) | `checkin`, `passport`, `activity`, `searches`, `trending`, `stats` |
| Social (FR-26..31) | `follow [--unfollow]`, `followers`, `feed`, `recommend`, `suggest`, `picks` |
| Chatbot (FR-32..35) | `ask`, `discover`, `for-me`, `dish similar` |
| Admin | `status`, `explain`, `sync status/retry` |

## 4. Run the tests

```powershell
pytest                     # all acceptance tests (the databases must be loaded)
pytest -k FR15 -v          # one requirement
```

Each test is tagged with its requirement and documents its input, steps and expected result.
Results are written to `tests/results/results.md` (table for the report) and `results.json`.
Tests that create data (users, reviews, restaurants) delete it afterwards. The LLM test is skipped
when `LLM_API_KEY` is empty; the retrieval and "no answer" tests always run.

## Configuration

Every connection setting comes from environment variables (`.env`, see `.env.example`):
`MONGO_URI`, `CASSANDRA_HOSTS`, `CASSANDRA_PORT`, `DGRAPH_HOST`, `CHROMA_MODE`/`CHROMA_PATH`/`CHROMA_HOST`,
`EMBEDDING_MODEL`, `CHROMA_MAX_DISTANCE`, `LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY`.

## Changes since the Intermediate Revision

- Scripts per database were replaced by one application (connections, services, CLI, tests).
- Cassandra partitions are now bounded: `activity_by_user`, `visits_by_user_month` and
  `reviews_by_restaurant` are bucketed by month, `visits_by_user` by year, `searches_by_user` has a 180-day TTL.
- MongoDB: `$jsonSchema` validators on every collection, `sessions` collection with a TTL index (real
  login/logout), unique index `(user_id, restaurant_id, dish_id)` so restaurant-level reviews are also
  unique, `$facet` search, `sync_queue` for failed derived writes.
- Dgraph: `math` (average and score), `sum` and `@groupby` (rating distribution), `@upsert` on `cuisine_name`.
- ChromaDB: named model (all-MiniLM-L6-v2, cosine), real LLM call, relevance threshold with a fixed
  answer when nothing relevant is found, sources shown with every answer.
- Dataset: from 3 users / 5 restaurants / 12 reviews to 40 / 60 / ~600 (the original records are kept).

## Troubleshooting

- `NoHostAvailable` (Cassandra): it is still starting; wait for `(healthy)` in `docker compose ps`.
- First Chroma call is slow: it downloads the embedding model once (~80 MB).
- Chatbot says "LLM not configured": set `LLM_API_KEY` in `.env`. Without a key it still shows the retrieved passages.
- Too many / too few "no information" answers: tune `CHROMA_MAX_DISTANCE` (0.55 strict – 0.75 lenient).
- Reset everything: `python -m dishcovery.loading.load_all`.
