"""The door's data directory — its OWN for every run.

🔴 WHY THIS FILE CAME TO EXIST (06.09.2026, E6). As of this day, `kir_write`
keeps a DURABLE record of an unresolved dispatch: without it the door
cannot promise that a repeat after a lost response will not duplicate the
write, and so it REFUSES pre-effect. The operator names the directory
(`KIR_MCP_PENDING_DIR`), or it is derived from the install
(`KIR_INSTALL_ROOT` / the host port `data.install_paths`).

In the test suite there is neither: there is no `backend/kukai` marker
above the tree, and `install_data_path("mcp")` honestly answers `None`.
So the directory is named HERE, and its own for every test — otherwise
the tests would share one durable record and knock each other over (the
shape "parallel smiths share one scratchpad" is already known to this
house).

What is substituted is the directory, not the behavior: the door itself
is not patched by the tests, and its refusal of "no directory named"
stays reachable — checked by a separate test that unsets the variable.
"""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def mcp_pending_dir(tmp_path, monkeypatch):
    from kir.mcp import live

    monkeypatch.setenv(live.PENDING_DIR_ENV, str(tmp_path / "mcp-data"))
    return tmp_path / "mcp-data"
