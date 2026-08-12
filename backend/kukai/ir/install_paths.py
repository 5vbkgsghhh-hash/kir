"""One authority for the installation a KIR import belongs to.

Four modules (`witness_feed`, `coverage_feed`, `shadow`, `acceptance_journal`)
answered "where does my data live?" with the same absolute production path,
each guarded by ``os.path.isdir("/opt/kukai-rebuild1")``.  That condition asks
whether the path EXISTS ON THIS MACHINE, not whether the running code was
imported FROM it — so on the production box every worktree, test sandbox and
offline experiment resolved to the PRODUCTION corpora.  Measured 2026-08-02: a
process started in a sibling worktree returned
`/opt/kukai-rebuild1/backend/data/telemetry/kir_witness.jsonl`.

Nothing was measured wrong by it — the corpora carry no worktree rows — but an
instrument any neighbour can append to is not an instrument, and this package
holds its measuring tools to the same discipline as the measured system.

The rule, stated once instead of four times: **data belongs to the installation
this module was imported from**.  A source checkout owns ``backend/data/…``
wherever it happens to live, which is why the production path keeps resolving
exactly as before while a worktree now owns its own.  An embedded or packaged
import owns no writable installation and says so, rather than claiming a
neighbour's.

Each caller keeps its OWN policy for the ``None`` answer: the telemetry feeds
fall silent (they are fail-open by contract), while acceptance evidence refuses
the write pre-effect with ``KIR-A005``.  That difference is deliberate and must
not be flattened into this module.
"""
from __future__ import annotations

import pathlib

#: ``<install>/backend/kukai/ir/install_paths.py`` -> ``<install>``
_INSTALL_ROOT = pathlib.Path(__file__).resolve().parents[3]


def install_root() -> pathlib.Path | None:
    """The source checkout this module was imported from, or ``None``.

    The marker is ``backend/kukai``: it is what makes an installation a source
    tree that owns a data directory, and it is checked on the resolved path of
    THIS file, so the answer cannot be borrowed from a neighbouring checkout.
    """

    if (_INSTALL_ROOT / "backend" / "kukai").is_dir():
        return _INSTALL_ROOT
    return None


def install_data_path(*parts: str) -> pathlib.Path | None:
    """Resolve a path under this installation's ``backend/data``, or ``None``."""

    root = install_root()
    if root is None:
        return None
    return root.joinpath("backend", "data", *parts)


__all__ = ["install_data_path", "install_root"]
