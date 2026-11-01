"""Replay only known synthetic cases; raw customer prompts are never reconstructed."""

import time
import uuid
from .demo import RunRequest, execute


async def replay_trace(store, trace_id, variant="guarded"):
    with store.lock:
        row = store.db.execute(
            "SELECT payload FROM runs WHERE json_extract(payload,'$.trace_id')=? LIMIT 1",
            (trace_id,),
        ).fetchone()
    if not row:
        raise ValueError(
            "Only recorded built-in fixture runs can be replayed; arbitrary traces need a separately authored sanitized test"
        )
    import json

    original = json.loads(row[0])
    result = await execute(
        RunRequest(
            scenario=original["scenario"],
            variant=variant,
            runtime="scripted",
            transport="inprocess",
        ),
        store,
    )
    case = {
        "id": str(uuid.uuid4()),
        "created_at": time.time(),
        "source_trace_id": trace_id,
        "scenario": original["scenario"],
        "variant": variant,
        "replay_trace_id": result["trace_id"],
        "passed": result["passed"],
        "mode": "replay of the built-in synthetic scenario, not the original model output",
    }
    store.put("replay_cases", case)
    return case
