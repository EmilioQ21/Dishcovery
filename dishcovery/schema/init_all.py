"""Create every structure in the four databases.

    python -m dishcovery.schema.init_all            # create (idempotent)
    python -m dishcovery.schema.init_all --reset    # drop everything first (wipes data)
"""
import argparse
import re
import time
from pathlib import Path

from dishcovery import config

HERE = Path(__file__).resolve().parent


def init_mongo(reset):
    from dishcovery.schema import mongo_schema
    names = mongo_schema.create(drop=reset)
    print("  MongoDB   collections with $jsonSchema validators + indexes:", ", ".join(names))


def cql_statements(path=HERE / "schema.cql"):
    text = re.sub(r"--[^\n]*", "", path.read_text(encoding="utf-8"))
    return [s.strip() for s in text.split(";") if s.strip()]


def init_cassandra(reset):
    from dishcovery.connection.cassandra import get_session
    session = get_session(keyspace=False)
    if reset:
        session.execute("DROP KEYSPACE IF EXISTS %s" % config.CASSANDRA_KEYSPACE, timeout=120)
    statements = cql_statements()
    for stmt in statements:
        session.execute(stmt.replace("dishcovery.", config.CASSANDRA_KEYSPACE + ".")
                        .replace("KEYSPACE IF NOT EXISTS dishcovery", "KEYSPACE IF NOT EXISTS " + config.CASSANDRA_KEYSPACE),
                        timeout=120)
    tables = [r.table_name for r in session.execute(
        "SELECT table_name FROM system_schema.tables WHERE keyspace_name = %s", (config.CASSANDRA_KEYSPACE,))]
    print("  Cassandra keyspace %s, tables: %s" % (config.CASSANDRA_KEYSPACE, ", ".join(sorted(tables))))


def init_dgraph(reset):
    import pydgraph

    from dishcovery.connection.dgraph import get_client
    client = get_client()
    if reset:
        client.alter(pydgraph.Operation(drop_all=True))
    client.alter(pydgraph.Operation(schema=(HERE / "schema.dql").read_text(encoding="utf-8")))
    print("  Dgraph    schema applied (5 types, 6 edges, exact/term/trigram/int/hour indexes, @upsert, @reverse)")


def init_chroma(reset):
    from dishcovery.connection.chroma import COLLECTIONS, create_collection
    for name in COLLECTIONS:
        create_collection(name, recreate=reset)
    print("  ChromaDB  collections %s (model %s, cosine distance)" % (", ".join(COLLECTIONS), config.EMBEDDING_MODEL))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--reset", action="store_true", help="drop existing structures and data first")
    parser.add_argument("--only", choices=["mongo", "cassandra", "dgraph", "chroma"], nargs="*")
    args = parser.parse_args(argv)
    steps = {"mongo": init_mongo, "cassandra": init_cassandra, "dgraph": init_dgraph, "chroma": init_chroma}
    t0 = time.time()
    print("Creating schemas%s..." % (" (reset)" if args.reset else ""))
    for name, fn in steps.items():
        if args.only and name not in args.only:
            continue
        fn(args.reset)
    print("Done in %.1fs" % (time.time() - t0))


if __name__ == "__main__":
    main()
