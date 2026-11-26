"""Query optimization evidence (not a requirement on its own): indexes are really used."""
from datetime import datetime

import pytest

from dishcovery.queries import cassandra_queries as cq
from dishcovery.queries import dgraph_queries as dq
from dishcovery.queries import mongo_queries as mq


@pytest.mark.fr("OPT")
def test_mongo_main_queries_use_indexes(evidence):
    """Expected: every main MongoDB query uses an index (IXSCAN, TEXT or GEO_NEAR), never COLLSCAN."""
    plans = mq.explain_main_queries()
    for name, p in plans.items():
        stages = " ".join(p["stages"])
        assert "COLLSCAN" not in stages, name
        assert any(s in stages for s in ("IXSCAN", "TEXT", "GEO_NEAR", "EXPRESS", "IDHACK")), (name, stages)
    evidence("; ".join("%s: %s" % (k, "<-".join(v["stages"])) for k, v in plans.items())[:300])


@pytest.mark.fr("OPT")
def test_cassandra_reads_one_partition(evidence):
    """Expected: the trace of Q1 shows a single-partition read."""
    rs = cq.execute("q1_activity", ("user_0001", cq.ym(datetime.now()), 20), trace=True)
    events = [e.description.lower() for e in rs.get_query_trace(max_wait_sec=5).events]
    assert any("single-partition" in e or "single partition" in e for e in events)
    evidence(next(e for e in events if "partition" in e))


@pytest.mark.fr("OPT")
def test_dgraph_traversals_are_fast(evidence):
    """Expected: the 5-hop recommendation query runs in under 500 ms on the server."""
    lat = dq.latency_report()
    assert lat["FR-29 recommendations (5 hops)"] < 500
    evidence(lat)
