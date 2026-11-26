import json
from functools import lru_cache

import pydgraph

from dishcovery import config


@lru_cache(maxsize=1)
def get_client():
    stub = pydgraph.DgraphClientStub(config.DGRAPH_HOST)
    return pydgraph.DgraphClient(stub)


def query(dql, variables=None):
    """Run a read-only DQL query and return (data, server_latency_ms)."""
    txn = get_client().txn(read_only=True)
    try:
        res = txn.query(dql, variables=variables)
        latency_ms = res.latency.total_ns / 1e6 if res.latency else None
        return json.loads(res.json), latency_ms
    finally:
        txn.discard()


def mutate(set_obj=None, delete_obj=None):
    txn = get_client().txn()
    try:
        res = txn.mutate(set_obj=set_obj, del_obj=delete_obj, commit_now=True)
        return res
    finally:
        txn.discard()


def upsert(dql_query, set_nquads=None, del_nquads=None, cond=None):
    """Upsert block: query + conditional mutation in one atomic request."""
    txn = get_client().txn()
    try:
        mu = txn.create_mutation(set_nquads=set_nquads or "", del_nquads=del_nquads or "", cond=cond)
        req = txn.create_request(query=dql_query, mutations=[mu], commit_now=True)
        return txn.do_request(req)
    finally:
        txn.discard()


def ping():
    query("{ q(func: has(dgraph.type), first: 1) { uid } }")
    return True
