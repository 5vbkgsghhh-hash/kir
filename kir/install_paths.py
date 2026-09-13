"""One authority for the installation a KIR import belongs to.

Four modules (`witness_feed`, `coverage_feed`, `shadow`, `acceptance_journal`)
answered "where does my data live?" with the same absolute production path,
each guarded by ``os.path.isdir(<the host tree>)``.  That condition asks
whether the path EXISTS ON THIS MACHINE, not whether the running code was
imported FROM it — so on the production box every worktree, test sandbox and
offline experiment resolved to the PRODUCTION corpora.  Measured 2026-08-02: a
process started in an unrelated worktree resolved to the PRODUCTION telemetry
file of the host install.

Nothing was measured wrong by it — the corpora carry no worktree rows — but an
instrument any neighbour can append to is not an instrument, and this package
holds its measuring tools to the discipline of the measured
(`CLAUDE.md`, "The measuring instruments deserve the same discipline").

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

🔴 THE SECOND AUTHORITY IS THE HOST, AND THE RULE ABOVE IS NOT REPEALED BY
THIS BUT NARROWED (2026-08-28).  "Data belongs to the installation the module
was imported from" holds exactly as long as the installation CAN BE LEARNED
from the package's location.  After the split the package is published
separately and sits where there is no host tree above it at all: the marker
is not found, ``install_root()`` answers ``None`` ALWAYS — and eight of the
viewer's fourteen routes went down silently (``list_runs()`` -> 0 with 81
decompiles on disk).

A root variable does not fix this, and this is a MEASUREMENT, not an opinion:
the kinds live under different roots (the corpus at
``backend/backend/data/decompile``, the feeds at ``backend/data/telemetry``),
because the host's decompile-output root is a RELATIVE path resolved by the
service's working directory.  Nobody has a single root.  Hence the port
:data:`kir.ports.INSTALL_DATA`: the host names the DIRECTORY OF THE KIND, the
package derives it from nowhere, and the order of authorities becomes
**operator → host → marker-based inference → None**.  As long as nobody has
closed the port, this module's behavior is unchanged BYTE-FOR-BYTE.
"""
# 🔴 PROVENANCE MOVED OUT OF THE DOCSTRING ON 2026-09-01 — A DOOR VERSUS A
# JOURNAL. The module docstring is a PUBLIC DOOR: `help()` prints it to a
# reader of the published package, and the address of our own machine tells
# them nothing. The knowledge is not erased — it is here, in the journal,
# where it belongs:
# 🔴 THIS MODULE STOPPED BEING A SECOND DOOR INTO THE ENVIRONMENT ON
# 2026-09-02. It used to query `os.environ` itself, i.e. it was a second
# place one had to remember — and `KIR_INSTALL_ROOT`, should it ever grow a
# past name, would be read here under ONE name only, bypassing `env.RENAMED`.
# Now it is a consumer of the door just like everyone else; behavior with the
# variable unset stays the same BYTE-FOR-BYTE.
#     the guard that asked the wrong question   os.path.isdir("/opt/kukai-rebuild1")
#     measured 2026-08-02: a process started in /home/claude/kir-product-lead
#     returned /opt/kukai-rebuild1/backend/data/telemetry/kir_witness.jsonl
from __future__ import annotations

import pathlib

from kir import env

#: The installation, named by the OPERATOR. The first authority: the package
#: is now published separately and may sit where there is no host tree at
#: all — yet the installation still has data, known only to whoever installed it.
_INSTALL_ROOT_ENV = "KIR_INSTALL_ROOT"

#: The host-tree marker: a directory that makes the installation the SOURCE
#: TREE that owns the data.
_HOST_MARKER = ("backend", "kukai")

#: THE SEARCH ANCHOR — the directory where the package ACTUALLY SITS, not a
#: level counted up from it. The name is kept unchanged DELIBERATELY: sibling
#: test suites patch it (`mock.patch("kir.install_paths._INSTALL_ROOT", …)`) to
#: express "what if the package sat in this installation instead". The
#: property they check still holds today; breaking them for the sake of a
#: rename would mean changing a neighbor's behavior for one's own aesthetics.
_INSTALL_ROOT = pathlib.Path(__file__).resolve().parent


def _derived_root() -> pathlib.Path | None:
    """The root derived FROM THE PACKAGE'S LOCATION, not counted in steps upward.

    🔴 REPLACED ``parents[3]``, AND THAT COUNT BROKE TWICE. Measured
    2026-08-27, three layouts with one command:

        backend/kukai/ir/install_paths.py  parents[3] -> <install>  correct
        backend/kir/install_paths.py       parents[3] -> /opt       off by one level
        /opt/kir/kir/install_paths.py      parents[3] -> /          filesystem root

    The count went wrong as early as the ``kukai/ir`` -> ``kir`` rename, and
    nobody noticed: the docstring was corrected, the arithmetic was not. The
    08-27 split finished it off down to ``/``, where no marker ever exists,
    and ``install_root()`` started answering ``None`` ALWAYS. Eight consumers
    silently fell into their own ``None`` policy: six telemetry feeds went
    quiet (they are fail-open by contract, and silence is indistinguishable
    from "nothing to write"), acceptance started refusing pre-effect.

    Exactly the shape on which, after the same split, the sandbox burned down
    (``f518b05``): "count not in steps upward, but from where the package
    actually sits — the layout changes, this does not".

    So what is here is not a number of steps but a CLIMB TO THE MARKER from
    :data:`_INSTALL_ROOT` — the directory where the package actually sits. The
    path is resolved from THIS file, so the answer still cannot be borrowed
    from a neighboring tree; and patching the anchor in test suites keeps
    expressing "what if the package sat right here instead".
    """
    anchor = pathlib.Path(_INSTALL_ROOT)
    for candidate in (anchor, *anchor.parents):
        if candidate.joinpath(*_HOST_MARKER).is_dir():
            return candidate
    return None


def install_root() -> pathlib.Path | None:
    """The source checkout this module was imported from, or ``None``.

    Order of authorities: first the OPERATOR (``KIR_INSTALL_ROOT``), then
    inference from the package's location via the ``backend/kukai`` marker.

    ``None`` remains a LEGITIMATE answer: an embedded or packaged import has
    no writable installation, and it says so rather than claiming a
    neighbor's. Each consumer keeps its OWN policy for the ``None`` answer
    (feeds fall silent, acceptance refuses pre-effect) — that distinction must
    not be flattened here. The REASON for the silence can be asked of
    :func:`install_root_refusal`.
    """
    named = (env.get(_INSTALL_ROOT_ENV) or "").strip()
    if named:
        return pathlib.Path(named)
    return _derived_root()


def install_root_refusal() -> str | None:
    """WHY there is no root — in words; ``None`` if a root exists.

    🔴 WHY A SEPARATE ENTRY POINT, NOT AN EXCEPTION. ``install_root()``'s
    answer cannot change: eight consumers hold their policies on it, and
    turning ``None`` into a raise would flatten the distinction the docstring
    above declares deliberate.

    But staying silent is not an option either: form 50 states that an
    observation mode with no journal is indistinguishable from being turned
    off. The telemetry feeds have been silent since 08-27, and any honest
    analysis would read that absence as a fact ABOUT THE SUBJECT ("the model
    did not stumble"), not about us ("there is nobody to ask").

    Hence a third path: the answer does not change, and the SILENCE gains a
    reason that can be asked about.
    """
    if install_root() is not None:
        return None
    # 🔴 NO ROOT — DOES NOT YET MEAN NO DATA (2026-08-28). The second
    # authority answers BY KIND and forms no root: saying "data is not
    # addressable" while the port is live would be lying in exactly the
    # direction this entry point was set up against. The variable name is
    # named on BOTH branches: the reader must not have to guess which move
    # is left to them.
    if _host_supplies_data():
        return (
            f"корень установки не назван ({_INSTALL_ROOT_ENV} пуста, маркера "
            f"`{'/'.join(_HOST_MARKER)}` над пакетом нет), но каталоги данных "
            "называет ХОЗЯИН портом «data.install_paths» — спрашивай "
            "install_data_path(<род>), а не корень. Род, которого хозяин не "
            "назвал, остаётся неадресуемым, и это его отдельная тишина.")
    return (
        f"установка не названа: {_INSTALL_ROOT_ENV} не задана, хозяин не "
        "закрыл порт «data.install_paths», и дерева-хозяина "
        f"(маркер `{'/'.join(_HOST_MARKER)}`) над пакетом нет. Данные этой "
        "установки не адресуются: фиды телеметрии МОЛЧАТ, приёмка отказывает "
        f"пред-эффектно. СЛЕДУЮЩИЙ ХОД: хозяину — закрыть порт; оператору — "
        f"задать {_INSTALL_ROOT_ENV} каталогом установки, которой принадлежат "
        "данные.")


def _host_supplies_data() -> bool:
    """Whether the host has closed the data-directories port. No product import, no query."""
    try:
        from kir import ports
        return ports.INSTALL_DATA in ports.supplied()
    except Exception:  # noqa: BLE001 — no port registry: treat it as not closed
        return False


def _named_by_the_host(parts: tuple[str, ...]) -> pathlib.Path | None:
    """The kind's directory, NAMED by the host through the port. No port — ``None``.

    🔴 WHY A SECOND AUTHORITY, MEASURED 2026-08-28. Marker-based inference is
    honest and, after the split, answers ``None`` always: above ``/opt/kir``
    there is no ``backend/kukai`` directory. This CANNOT be fixed with a root
    variable — the kinds live under different roots, and a run showed exactly
    that::

        KIR_INSTALL_ROOT=<backend>      decompile PRESENT · telemetry ABSENT
        KIR_INSTALL_ROOT=<repository>   the other way around

    The host holds the reason: the decompile-output root
    (``serving._DECOMPILE_OUT_ROOT``) is a RELATIVE path resolved by the
    service's working directory. Nobody has a single root, which is why what
    is asked for is the KIND'S DIRECTORY, not a root.

    A NO-OP IS THE CONDITION FOR THIS CHANGE, NOT MERE CAUTION. The tree is
    installed editable in the live service's venv; as long as nobody has set
    up the port, the answer here is ``None`` and the function below matches
    the previous behavior BYTE-FOR-BYTE.
    """
    if not parts:
        return None
    try:
        from kir import ports
    except Exception:  # noqa: BLE001 — no port registry: the previous path stands
        return None
    supplier = ports.ask(ports.INSTALL_DATA)
    if supplier is None:
        return None
    try:
        named = supplier.data_path(parts[0])
    except Exception:  # noqa: BLE001 — the host is not required to know every kind
        return None
    if not named:
        return None
    return pathlib.Path(named).joinpath(*parts[1:])


def install_data_path(*parts: str) -> pathlib.Path | None:
    """Resolve a path under this installation's ``backend/data``, or ``None``.

    Order of authorities: **operator** (``KIR_INSTALL_ROOT``) → **host** (port
    :data:`kir.ports.INSTALL_DATA`, by kind) → **marker-based inference** →
    ``None``. The shape of the answer under the first and third does not
    change: ``<root>/backend/data/...`` stays what it was — the policies of
    thirteen consumers rest on it.
    """

    named_root = (env.get(_INSTALL_ROOT_ENV) or "").strip()
    if named_root:
        return pathlib.Path(named_root).joinpath("backend", "data", *parts)

    by_host = _named_by_the_host(parts)
    if by_host is not None:
        return by_host

    root = _derived_root()
    if root is None:
        return None
    return root.joinpath("backend", "data", *parts)


__all__ = ["install_data_path", "install_root", "install_root_refusal"]
