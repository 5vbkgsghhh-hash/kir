"""Step 6 — bridge-future leak on cancellation.

The bridge wait_for popped `_pending_bridge_requests` on TimeoutError but NOT on
CancelledError (e.g. the 90s tool-budget cap cancels the tool). The orphaned
future stayed registered → a late bridge_response could resolve a committed
write that the model already saw as a timeout → re-issue → double-commit. The
cancel path must pop the future and re-raise.
"""
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "kukai" / "api" / "chat_ws.py"
BRIDGE_SRC = Path(__file__).resolve().parents[1] / "kukai" / "api" / "bridge_protocol.py"  # golden-path Phase 1


def test_bridge_future_popped_and_reraised_on_cancel():
    import re
    src = BRIDGE_SRC.read_text()
    # at least one CancelledError handler must pop the bridge future AND re-raise
    found = False
    for m in re.finditer(r"except asyncio\.CancelledError:", src):
        window = src[m.start(): m.start() + 400]
        if "_pending_bridge_requests.pop(req_id, None)" in window and "raise" in window:
            found = True
            break
    assert found, "no CancelledError handler pops the bridge future + re-raises"


def test_generate_report_filename_is_sanitized():
    """Step 6: LLM-controlled report filename must be stripped of directory
    components (Path.name) before it flows into files_dir/{id}_{name}."""
    from pathlib import Path as _P
    csrc = (_P(__file__).resolve().parents[1] / "kukai" / "llm" / "client.py").read_text()
    assert 'os.path.basename(args.get("filename"' in csrc
