"""Live-model extractor: run the read-only C# extractor (extractor.cs) on a Revit doc via the
op_revit operator channel, then NORMALIZE the raw payload into a checker SpatialModel — assigning
each room's RoomFunction with classify.py (the §4 normalization seam; this is where classify.py
goes live). Only the operator-authorized device is permitted (safety).

`normalize()` is pure (no I/O) and unit-tested without a live model; `extract()` does the live
read-only exec.
"""
from __future__ import annotations

import json
import os
from kir import env  # noqa: E402  (a dependency-free submodule — creates no cycle)
import subprocess
from pathlib import Path

from kir.checker.classify import (
    classify_names_via_host,
    classify_room,
    unrecognised_names,
)
from kir.checker.flags import checker_v2_enabled
from kir.checker.spatial_model import SpatialModel

#: THE OPERATOR CHANNEL IS A PROPERTY OF THE INSTALLATION, NOT A PACKAGE
#: CONSTANT.
#:
#: 🔴 TWO ABSOLUTE PATHS INTO THE HOST'S TREE AND A RAW IDENTIFIER OF SOMEONE
#: ELSE'S MACHINE USED TO STAND HERE (removed 27.08.2026). The package is
#: published as a separate repository under Apache-2.0, and the canon had
#: already named such a line a leak back on 09.08: "a raw device identifier
#: in a file that ships publicly is a leak, not a TODO." On top of that, it
#: was a PATH that exists on no machine but one: for a stranger, `subprocess`
#: walked a nonexistent path and raised `FileNotFoundError` — a refusal with
#: no reason and no next move.
#:
#: The verdict on the device was already carried out in `serving.py` on
#: 15.08.2026, and the condition was recorded there too: the carrier of the
#: constraint is the INSTALLATION'S CONFIGURATION, and only that. This file
#: carried a SECOND copy of the rule for twelve days — precisely the named
#: tree defect the whole canon is written against: a value is declared in one
#: place and read in another, and nothing forces them to agree. The two
#: allow-lists would have diverged on the very first device, and they would
#: have diverged SILENTLY.
_OP_PYTHON_ENV = "KIR_OP_PYTHON"
_OP_SCRIPT_ENV = "KIR_OP_SCRIPT"
_CS = Path(__file__).with_name("extractor.cs")


class OperatorChannelMissing(RuntimeError):
    """The operator channel was not named by the installation — there is
    nothing to read the live model with.

    🔴 A SUBCLASS OF ``RuntimeError`` ON PURPOSE, and this is a condition of
    the fix, not a convenience. Call sites already catch ``RuntimeError`` and
    treat the failure as "could not be read"; were this a new root of the
    hierarchy, the cut would change the behavior of existing branches — and a
    cut that changes behavior is no longer a cut. The same argument is
    recorded verbatim at ``ports.PortMissing``.

    A separate kind is needed per form 34: an instrument whose measured
    action can FAIL TO HAPPEN must have its own LOUD "did not happen" outcome
    — otherwise "cheap" and "not done" arrive as the same value.
    """


def operator_channel() -> tuple[str, str]:
    """(interpreter, script) of the operator channel — from the installation's
    environment.

    An unset variable is a NAMED refusal, not a silent fallback to someone
    else's path: we have no right to guess a stranger's installation, and a
    silent substitution would bring back exactly the leak this input was set
    up to remove.
    """
    vpy = (env.get(_OP_PYTHON_ENV) or "").strip()
    op = (env.get(_OP_SCRIPT_ENV) or "").strip()
    missing = [name for name, value in
               ((_OP_PYTHON_ENV, vpy), (_OP_SCRIPT_ENV, op)) if not value]
    if missing:
        raise OperatorChannelMissing(
            "канал оператора не задан этой установкой: " + ", ".join(missing)
            + ". Живое чтение модели невозможно. СЛЕДУЮЩИЙ ХОД: выставь "
            f"{_OP_PYTHON_ENV} (интерпретатор с доступом к каналу) и "
            f"{_OP_SCRIPT_ENV} (скрипт `op_revit.py` установки), либо работай "
            "офлайн — `normalize()` чист и живой модели не требует.")
    return vpy, op


def authorized_devices() -> tuple[str, ...]:
    """Allowed devices — asked of the installation's SOLE authority.

    🔴 WHY THE IMPORT IS LAZY AND WHY SPECIFICALLY ``serving``. The rule "the
    operator sets the list via ``KUKAI_ADMIN_DEVICES``; an unset variable =
    EMPTY = closed" lives in ``serving.admin_devices()`` and NOWHERE ELSE
    (verified by grepping for the variable: a single reader). Writing a
    second parse of the same string here would set up a second carrier for
    one rule. It is lazy because ``serving`` is heavy (measurement 27.08:
    0.45 s to import), and this input already spins up a subprocess with a
    two-minute timeout.

    🔴 AN HONEST CAVEAT: this is the FIRST import from the ``kir`` core into
    ``checker``, which the canon describes as a parallel world ("NO import
    from kir"). The full answer is to move ``admin_devices`` into a light
    module that both sides read; it is not done here because ``serving.py``
    belongs, at this hour, to a neighboring wave. Named, not left unsaid.
    """
    from kir.serving import admin_devices
    return admin_devices()


def _synthesize_stairs(rooms: list, levels: list) -> list:
    """Infer vertical stair runs from лестница (stair-landing) rooms that stack across consecutive
    levels. The materializer creates an aligned лестница room per floor but no Stair ELEMENT, so
    without this the floors aren't vertically connected in the checker's graph (HAB010 + upper-floor
    egress would fail). Each aligned pair on consecutive levels becomes a Stair bridging them.
    """
    lev = {l["id"]: l for l in levels}
    landings = [r for r in rooms if r.get("function") == "лестница" and r.get("boundary")]
    groups: dict = {}
    for r in landings:
        b = r["boundary"]
        cx = round(sum(p[0] for p in b) / len(b) / 500.0) * 500   # group by ~aligned footprint
        cy = round(sum(p[1] for p in b) / len(b) / 500.0) * 500
        groups.setdefault((cx, cy), []).append(r)
    v2 = checker_v2_enabled()
    out = []
    for (core_x, core_y), grp in sorted(groups.items()):
        grp.sort(key=lambda r: lev.get(r["level_id"], {}).get("elevation_mm", 0.0))
        for i in range(len(grp) - 1):
            lo, hi = grp[i], grp[i + 1]
            lo_l, hi_l = lev.get(lo["level_id"]), lev.get(hi["level_id"])
            if not lo_l or not hi_l:
                continue
            # 🔴 "CONSECUTIVE LEVELS" WAS SAID IN THE DOCSTRING AND CHECKED
            # NOWHERE (30.08.2026, audit finding F-320). Sorting by elevation
            # gives neighbors BY LIST, not by building. Measurement: landings
            # on L0 and L2 with no landing on L1 produced `synth_L0_L2` — a
            # stair through an UNSERVED floor; two aligned landings on ONE
            # SAME level produced `synth_L1_L1` with `base_z == top_z`, a
            # stair from a level into itself. The graph then counts
            # connectivity through a passage nobody extracted, and HAB010
            # falls silent: the building looks SAFER than it is. For egress
            # rules this is the worst kind of miss.
            #
            # What is asked is the level's ORDINAL NUMBER: elevation cannot
            # be relied on, it knows nothing about a skipped floor.
            lo_i, hi_i = lo_l.get("index"), hi_l.get("index")
            if lo_i is None or hi_i is None or hi_i != lo_i + 1:
                continue
            if v2:
                # v2 (extract truth, not fabrication): the inferred link keeps the graph
                # connected but carries NO invented dimensions — kind='inferred' makes
                # HAB011 refuse to certify it (WARNING) instead of self-certifying with
                # pass-by-construction 1100/17/280 values.
                out.append({
                    # 🔴 A NAME WITHOUT A CORE MERGED DIFFERENT STAIRS (F-335).
                    # Two cores on the same pair of floors got ONE id, and
                    # `nx.Graph.add_node` updates attributes on an existing
                    # node — so a single node ended up connected to all four
                    # landings, meaning a PATH appeared between independent
                    # cores that does not exist in the building. The core's
                    # key is already computed by the grouping above — no need
                    # to set up a second carrier of identity.
                    "id": f"synth_{lo['level_id']}_{hi['level_id']}"
                          f"_{int(core_x)}_{int(core_y)}",
                    "base_level_id": lo["level_id"], "top_level_id": hi["level_id"],
                    "base_z": float(lo_l.get("elevation_mm", 0.0)),
                    "top_z": float(hi_l.get("elevation_mm", 0.0)),
                    "run_width_mm": None, "riser_count": None, "tread_depth_mm": None,
                    "footprint": lo["boundary"], "kind": "inferred",
                    # The top of this edge is the level of the landing ABOVE,
                    # found by us; the author said nothing about the stair
                    # between them (see `stair_provenance`).
                    "top_level_source": "inferred_link",
                })
            else:
                out.append({
                    # 🔴 A NAME WITHOUT A CORE MERGED DIFFERENT STAIRS (F-335).
                    # Two cores on the same pair of floors got ONE id, and
                    # `nx.Graph.add_node` updates attributes on an existing
                    # node — so a single node ended up connected to all four
                    # landings, meaning a PATH appeared between independent
                    # cores that does not exist in the building. The core's
                    # key is already computed by the grouping above — no need
                    # to set up a second carrier of identity.
                    "id": f"synth_{lo['level_id']}_{hi['level_id']}"
                          f"_{int(core_x)}_{int(core_y)}",
                    "base_level_id": lo["level_id"], "top_level_id": hi["level_id"],
                    "base_z": float(lo_l.get("elevation_mm", 0.0)),
                    "top_z": float(hi_l.get("elevation_mm", 0.0)),
                    "run_width_mm": 1100.0, "riser_count": 17, "tread_depth_mm": 280.0,
                    "footprint": lo["boundary"],
                })
    return out


def _windows_with_provenance(raw: dict, v2: bool) -> list:
    """Windows with a NAMED kind of the `area_m2` quantity (F-254, 30.08.2026).

    `extractor.cs` computes area as width times height EXACTLY when height was
    read; otherwise it uses `width x 1.4` — a substituted stand-in. The
    condition here is the SAME ONE, so the quantity's kind is derived without
    a second carrier: there is nowhere for them to drift apart.

    🔴 ONLY UNDER v2. Under v1 the field is not set and stays `"declared"` —
    that is, behavior is byte-for-byte unchanged, and the promise in
    `flags.py` gets no third exception.
    """
    windows = raw.get("windows", []) or []
    if not v2:
        return windows
    out = []
    for w in windows:
        h = w.get("height_mm")
        try:
            measured = h not in (None, "") and float(h) > 0.0
        except (TypeError, ValueError):
            measured = False
        out.append({**w, "area_source": "measured" if measured else "nominal"})
    return out


def normalize(raw: dict) -> dict:
    """Turn the raw C# extraction into a SpatialModel-valid dict: assign each room.function via
    the RU lexicon (classify.py), backfill has_window/window_area from windows[]. Pure.

    v2 (KIR_CHECKER_V2=1) extracts TRUTH instead of fabricating:
      * height_mm: missing/zero stays None (v1 rewrote it to 2700 via `or 2700.0`) and
        height_source is preserved from the C# payload ("bounded"/"param");
      * apartment_id: stamped from the Revit department parameter when present;
      * doors: is_exterior is NEVER trusted from the raw payload (the v1 'one side
        null' heuristic mass-produces fake street exits) — derive.py re-establishes
        exteriority positively from envelope membership; host_wall_id is preserved;
      * windows: measured height/location pass through for the geometric join;
      * stairs: real parameters pass through as-is (None stays None — HAB011 says
        'cannot verify' instead of silently skipping), and _synthesize_stairs emits
        dimension-free kind='inferred' links."""
    v2 = checker_v2_enabled()
    raw_rooms = raw.get("rooms", []) or []
    # 🔴 A NAME OUR LEXICON DOES NOT KNOW IS NAMED BY THE HOST (28.08.2026).
    #
    # This is LIVE READING — the path of a person who downloaded the product
    # and opened THEIR OWN model. Measurement 28.08: the lexicon recognizes 0
    # of 66 names across six of eight languages, and the owner's decision is
    # NOT to grow the dictionary to completeness (see the header of
    # `classify.py`). So the missing piece is named by the host: with their
    # own dictionary, a parameter of their own template, an LLM — KIR does not
    # choose which.
    #
    # 🔴 WITHOUT A PROVIDER THIS IS A BYTE-FOR-BYTE NO-OP: `classify_names_via_host`
    # returns an empty dictionary, `by_host` is always None, and both lines
    # below produce exactly what they produced before the fix. This is a
    # condition of the fix, not a convenience — this tree is installed in live
    # prod's venv as EDITABLE (KIR_PLAN §0.1), and a fix that silently changes
    # behavior would ship to the service without a stop. Guarded by
    # `checker/tests/test_a_foreign_name_is_unverifiable_not_exempt.py`.
    host_named = classify_names_via_host(
        unrecognised_names(r.get("name", "") for r in raw_rooms))
    rooms = []
    win_area: dict[str, float] = {}
    for w in raw.get("windows", []) or []:
        rid = w.get("room_id")
        if rid:
            win_area[rid] = win_area.get(rid, 0.0) + float(w.get("area_m2", 0.0) or 0.0)
    for r in raw_rooms:
        rid = r["id"]
        name = r.get("name", "")
        by_host = host_named.get(name)
        if v2:
            h_raw = r.get("height_mm")
            height = float(h_raw) if h_raw not in (None, "") and float(h_raw) > 0.0 else None
            apartment = r.get("apartment_id") or (r.get("department") or "").strip() or None
        else:
            height = float(r.get("height_mm", 2700.0) or 2700.0)
            apartment = r.get("apartment_id")
        rooms.append({
            "id": rid, "name": name, "number": r.get("number", ""),
            "level_id": r["level_id"],
            "function": (by_host or classify_room(name)).value,
            # Live reading classifies by the NAME the author wrote in Revit
            # (`ROOM_NAME`) — kind `authored` (see `function_provenance`). A
            # name the lexicon did not recognize and that the HOST named is
            # kind `derived`: under `room_name` lies the author's string,
            # under `host_classifier` lies someone else's guess at what it
            # means, and such a function has no right to block the verdict.
            "function_source": "host_classifier" if by_host else "room_name",
            "area_m2": float(r.get("area_m2", 0.0) or 0.0),
            "height_mm": height,
            "height_source": (r.get("height_source") if v2 else None),
            "boundary": r.get("boundary", []) or [],
            # 🔴 ROOM VOIDS TRAVEL ON (S-01). Without this line the payload
            # key is swallowed by pydantic SILENTLY, and the package looks
            # installed: the capture is honest, the model is still shaft-less.
            "boundary_holes": r.get("boundary_holes", []) or [],
            "apartment_id": apartment,
            "has_window": rid in win_area,
            # Rounding removed (F-336): the value is compared against the
            # 1:8 threshold, and round(1.246, 2) = 1.25 gives exactly 0.125 —
            # HAB031 is silent. Rounding is allowed only for display, never
            # before the comparison.
            "window_area_m2": win_area.get(rid, 0.0),
        })
    doors = raw.get("doors", []) or []
    if v2:
        doors = [{**d, "is_exterior": False} for d in doors]  # derive.py decides
    return {
        "building_id": (raw.get("building_id") or "extracted").strip() or "extracted",
        "levels": raw.get("levels", []) or [],
        "rooms": rooms,
        "doors": doors,
        "windows": _windows_with_provenance(raw, v2),
        "stairs": (raw.get("stairs", []) or [])
                  + _synthesize_stairs(rooms, raw.get("levels", []) or []),
        "walls": raw.get("walls", []) or [],
    }


def run_extractor_cs(device: str, timeout_ms: int = 120000) -> dict:
    """Execute the read-only extractor.cs on the operator-authorized device; return the raw dict.

    THE ORDER OF CHECKS MATTERS: ACCESS first, then CHANNEL. Otherwise an
    installation with no channel would print about environment variables to
    someone who would not have been let in anyway — that is, the refusal
    would name the wrong reason and send the reader to fix the wrong thing.
    """
    allowed = authorized_devices()
    if device not in allowed:
        raise PermissionError(
            f"device {device} is not authorized for extraction; "
            + ("список допуска этой установки ПУСТ — задай KUKAI_ADMIN_DEVICES "
               "(id устройств через запятую)" if not allowed
               else f"допущено устройств: {len(allowed)}"))
    vpy, op = operator_channel()
    p = subprocess.run(
        [vpy, op, "exec", device, "--code-file", str(_CS), "--timeout-ms", str(timeout_ms)],
        capture_output=True, text=True, timeout=timeout_ms / 1000 + 40,
    )
    r = json.loads(p.stdout)
    if r.get("status") != 200:
        raise RuntimeError(f"extractor exec failed: {json.dumps(r)[:300]}")
    res = (r.get("body") or {}).get("result")
    if not isinstance(res, dict) or res.get("error"):
        raise RuntimeError(f"extractor returned error: {json.dumps(res)[:300]}")
    return res


def receipts(raw: dict) -> dict:
    """Reading receipts: what did NOT arrive and why. A pure function.

    🔴 WHY A SEPARATE FUNCTION, NOT A MODEL FIELD. `SpatialModel` is the
    building; a reading failure is a fact about US. Were we to put it inside
    the model, rules would start judging our own failures on a par with
    geometry. But it must not be lost either: before 20.08.2026, `extract()`
    handed back a model in which 246 of 1230 doors had no link to a room, and
    from it there was no way to tell "the door leads nowhere" apart from "we
    could not ask."

    `total` versus `len(sample)` — BOTH, because the list is truncated on the
    C# side: one number instead of two would turn the truncation into a
    silent loss.

    🔴 "THE FIELD DID NOT ARRIVE" AND "THE FIELD ARRIVED AS ZERO" ARE
    DIFFERENT OUTCOMES, AND THIS WAS BOUGHT ON MYSELF (20.08.2026). The first
    edit wrote `int(counts.get("rooms_unplaced") or 0)`, meaning an OLD
    extractor that carries no such fields would have reported "unplaced is
    zero" — a statement about the building that nobody made. I parsed the
    `room_link` state correctly (`unknown`) that same hour, but not the two
    counters right next to it: the same shape, the same file, adjacent lines.
    That is why `None` means "the source did not report."
    """
    counts = raw.get("counts") or {}
    links: dict[str, int] = {}
    for kind in ("doors", "windows"):
        for row in raw.get(kind, []) or []:
            state = row.get("room_link") or "unknown"
            links[kind + ":" + state] = links.get(kind + ":" + state, 0) + 1

    def reported(container: dict, key: str) -> int | None:
        value = container.get(key)
        return int(value) if isinstance(value, (int, float)) else None

    return {
        "phase_name": raw.get("phase_name"),
        "total": reported(raw, "failures_total"),
        "sample": list(raw.get("failures") or []),
        "cap": raw.get("failures_cap"),
        "rooms_unplaced": reported(counts, "rooms_unplaced"),
        "rooms_placed": reported(counts, "rooms"),
        "room_link": links,
    }


def extract_with_receipts(device: str) -> tuple[SpatialModel, dict]:
    """Reading + receipt in ONE call. Prefer this entry point.

    They must not be returned separately: whoever takes the model without
    taking the receipt gets a building that looks complete.
    """
    raw = run_extractor_cs(device)
    return SpatialModel.model_validate(normalize(raw)), receipts(raw)


def extract(device: str) -> SpatialModel:
    """Read-only: extract the live Revit doc on `device` (authorized only) into a SpatialModel.

    ⚠️ THIS ENTRY POINT DISCARDS THE RECEIPT. Kept for existing callers; for
    any new work, use `extract_with_receipts`.
    """
    model, _ = extract_with_receipts(device)
    return model
