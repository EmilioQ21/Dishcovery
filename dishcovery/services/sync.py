"""Cross-database write helper.

MongoDB is always written first (source of truth). Each derived write (Cassandra, Dgraph,
ChromaDB) runs through `propagate`; if it fails, the operation is stored in the MongoDB
`sync_queue` collection and can be replayed later with `retry_pending()`
(CLI: `python -m dishcovery.client.cli sync retry`)."""
import traceback
from datetime import datetime, timezone

from dishcovery.connection.mongo import get_db

_HANDLERS = {}


def handler(op):
    def deco(fn):
        _HANDLERS[op] = fn
        return fn
    return deco


def propagate(op, payload):
    """Run a derived write now; on failure queue it. Returns True if it succeeded."""
    try:
        _HANDLERS[op](payload)
        return True
    except Exception as exc:  # noqa: BLE001 - any engine error must be queued, not lost
        get_db().sync_queue.insert_one({"op": op, "payload": payload, "error": "%s: %s" % (type(exc).__name__, exc),
                                        "attempts": 1, "created_at": datetime.now(timezone.utc)})
        traceback.print_exc(limit=1)
        return False


def pending():
    return list(get_db().sync_queue.find().sort("created_at", 1))


def retry_pending():
    done = failed = 0
    for job in pending():
        try:
            _HANDLERS[job["op"]](job["payload"])
            get_db().sync_queue.delete_one({"_id": job["_id"]})
            done += 1
        except Exception as exc:  # noqa: BLE001
            get_db().sync_queue.update_one({"_id": job["_id"]}, {"$inc": {"attempts": 1},
                                                                 "$set": {"error": str(exc)}})
            failed += 1
    return done, failed
