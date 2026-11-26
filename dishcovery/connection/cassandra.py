from functools import lru_cache

from cassandra.auth import PlainTextAuthProvider
from cassandra.cluster import Cluster

from dishcovery import config


@lru_cache(maxsize=1)
def get_cluster():
    auth = None
    if config.CASSANDRA_USER:
        auth = PlainTextAuthProvider(config.CASSANDRA_USER, config.CASSANDRA_PASSWORD)
    return Cluster(config.CASSANDRA_HOSTS, port=config.CASSANDRA_PORT, auth_provider=auth)


@lru_cache(maxsize=2)
def _session(keyspace):
    return get_cluster().connect(keyspace) if keyspace else get_cluster().connect()


def get_session(keyspace=True):
    """Shared session. With keyspace=True it is bound to the dishcovery keyspace
    (which must exist: run the schema init first); keyspace=False is used to create it."""
    return _session(config.CASSANDRA_KEYSPACE if keyspace else None)


def ping():
    _session(None).execute("SELECT release_version FROM system.local")
    return True
