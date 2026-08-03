"""Transport-neutral parsing of declarative bridge result envelopes.

The bridge may wrap a result once, but execution-state classification must be
identical for ordinary KIR serving and the A5 live recovery adapter.  Keeping
that parser here prevents either orchestrator from inventing its own failure
semantics.
"""
from __future__ import annotations

from typing import Any, Optional


def extract_error(exec_res: Any) -> Optional[dict]:
    """Return a failure signal from the top or first nested result layer."""

    nested = exec_res.get("result") if isinstance(exec_res, dict) else None
    for layer in (exec_res, nested):
        if not isinstance(layer, dict):
            continue
        err = layer.get("error")
        state = str(layer.get("state", "")).lower()
        if (err or layer.get("ok") is False or layer.get("success") is False
                or state in ("error", "failed")):
            return {"error": err if err else state or "error", "layer": layer}
        if state == "timeout_unconfirmed":
            return {"error": "timeout_unconfirmed", "layer": layer}
    return None


# Historical private spelling retained for compatibility with serving probes.
_extract_error = extract_error
