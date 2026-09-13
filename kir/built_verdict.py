"""THE JUDGE OF THE BUILT — Revit is re-read and judged by THE SAME rules.

WHAT THIS CLOSES
=================
The product is a loop::

    intent → program → assembly in Revit → RE-READING → verdict → intent

Every arrow had been built except one, and always the same one: **the
built was never re-read**. What was judged was the DECLARATION by the
program (`ModelSource.PROGRAM`), and that was called checking the result.
Hence "NOT EVALUATED" on 73 of 73 overnight attempts, and the
impossibility of growing the project's main metric — *how many times
checkability changed the model's decision*: there was nothing to check
against except the model's own words.

🔴 THERE IS NOT ONE NEW RULE AND NOT ONE NEW PIECE OF GEOMETRY HERE. The
whole chain already existed and had no consumer:

====================================  ============================================
`address.receipt_map`                 the "op → ElementId" map, guaranteed by KIR-X008
`reextract.build_reextract_cs`        ONE bridge body keyed exactly to the named ids
`reextract.parse_reextract_rows`      bridge rows → `L0Element`
`design_check.spatial_model_from_l0`  `ModelSource.PARSE`
`design_check.compare`                two verdicts about one building, by name
`design_check.compare_geometry`       PER ELEMENT, in millimeters
====================================  ============================================

The last two, before 17.08.2026, were called ONLY by tests. This module is
their first live consumer, and it does nothing beyond that.

THE COST IS MEASURED, NOT ESTIMATED (17.08.2026, live `13A-RD-AR-K2`, 310 558 elements)
==========================================================================================
===================================  ==========
bridge floor (empty round trip, min of 3)  **0.14 s**
narrow reread N=1                     1.17 s
narrow reread N=10                    1.04 s
narrow reread N=50                    1.10 s
narrow reread N=200                   1.11 s
full `checker/extractor.cs`           8.31 s
===================================  ==========

🔴 **THE SLOPE OVER N IS ZERO** (−0.34 ms/element over the 1…200 range),
and this is not a curious fact but the property the whole splice stands
on. The body of `reextract._ROW_BODY_CS` walks the ENTIRE
`FilteredElementCollector` and only then filters by a `HashSet` of the
needed ids: what is paid for is WALKING THE DOCUMENT, not the number of
ids. So the cost is constant — ~1.1 s per turn, **+6.3% of a turn** against
the 17–18 s duration measured on 16.08, of which 84.6% is spent waiting on
the model.

The same measurement retires two ceilings that stood in the tree in place
of a number: 120 s (`checker/extractor.py:131`) and 600 s
(`tools/arena/habitability_probe.py:73`). The real figure is 8.31 s,
meaning they were inflated 14-fold and 72-fold. A ceiling is not a
measurement.

WHY THIS SPLICE, NOT THE THREE-DOOR SEAM (`client.py::shadow_evaluate`)
==========================================================================
The `_WRITE_TOOLS` seam covers 99% of live writes against 0.9% here, and
by COST it would have passed (see the table). What ruled it out was not
the measurement but the KIND OF QUESTION: the "declared vs. built"
discrepancy exists only where there IS something DECLARED.
`execute_revit_code` and `apply_revit_write` carry no program at all —
there is nothing to compare the built result against there. This verdict's
reach equals KIR's reach **by construction**, not by cost, and no splice
will widen it.

The question of the built work's quality ("is this a building at all")
does not depend on the program and legitimately lives at that other seam —
it is separate work with a separate cost (8.31 s) and is not done here.

WHAT THIS MODULE DOES NOT DO
==============================
* **DOES NOT HOLD UP THE TURN.** The owner's decision of 17.08: a verdict
  about the built work REPORTS. The instrument is young, its false-alarm
  rate is unknown, and it must not be allowed to gate the engineer's work
  until a body of discrepancy statistics has accumulated. Tightening comes
  later.
* **DOES NOT THROW.** The write to Revit has already happened; dropping
  the turn because of the judge would mean trading a write that already
  took place for the absence of feedback.
* **DOES NOT RE-PARSE THE BUILDING.** Exactly the elements created by this
  turn are read. A full re-read would pull in other people's elements
  along with ours and would cost 0.326 s + 12.2 ms per element
  (`decompile/extract.py:436`) — on 310 thousand elements, that is an
  hour.

BOUNDARIES NAMED BY A NUMBER, NOT LEFT UNSAID
================================================
🔴 **WITHOUT LEVELS THE JUDGE SEES NOT ONE WALL, AND THIS IS MEASURED
(17.08).** A trial on five real L0 rows from a tower: `L0Document` without
a header → `spatial model` gives **0 walls out of 5**, `walls: 0` in the
witness's counters. The cause is in
`design_check._levels_from_l0`: `known_levels` is built from
`document.levels`, and an element with an unknown level never reaches the
model. An empty verdict would then read as "everything matched" — our own
named defect, the zero of a quantity nobody computed.

So the header is taken from the **grounding snapshot**: the `levels` pool
(`open_model.py:383`) carries exactly `{id, name, elevation_mm}`, i.e. a
ready-made `LevelInfo`, and it is the same live document the write already
grounded against. A second read is not bought.

What the header does not have, and what we do not fabricate:

* **there are no rooms.** The live chat write does not read them, and a
  contour cannot be invented. So rules that judge by room stay `vacuous` —
  for their own honest reason, not because of our silence;
* **a level created BY THIS TURN does not become a level**:
  `_levels_from_l0` reads the header, not the elements, and the snapshot
  is taken BEFORE the write. Named here, not left unsaid.

A REFUSAL IS THE THIRD OUTCOME, NOT AN EMPTY VERDICT
=======================================================
The bridge stays silent · the id is not found (the element was deleted
between the commit and the re-read) · a row failed to parse · the judge is
unavailable — all of this is `built.state != "judged"` with a NAMED
reason. Not one of these outcomes is allowed to look like "built
correctly": `reextract` already refuses in typed form (`ReExtractError`,
invariant I2), and the refusal is carried through here rather than
collapsed into `None`.

ABOUT INVARIANT I5
====================
`reextract.py` declares *"I5: nothing imports this on a hot path."* The
measurement above authorized the hot path, and the invariant is rewritten
as an HONEST line with a number in `reextract.py` itself, rather than
silently bypassed.
"""
from __future__ import annotations

import logging
import os
from kir import env  # noqa: E402
from typing import Any, Mapping, Sequence

logger = logging.getLogger(__name__)

#: Kill switch. Defaults to ON, and that is a decision, not an oversight: a
#: capability the model would have to guess to ask for does not exist for it
#: (measured 16.08 — recon was eating 43% of turns for exactly that reason:
#: the default stayed silent).
#: An explicit `0` disables the module byte for byte: not a single key in the receipt.
ENV_FLAG = "KIR_BUILT_VERDICT"

#: Ceiling of a single run. Not ours: `reextract.REEXTRACT_BATCH` refuses above 200.
#: The chat door is capped at 20 operations of the author's budget, so only a
#: multi-arity operand can hit this ceiling — and when it does, the truncation IS NAMED.
MAX_IDS = 200

#: Run ceiling, ms. Measured 17.08: narrow read-back 1.04–1.17 s on a document
#: of 310,558 elements. Fifteen seconds is ×13 the measured worst case — that
#: is headroom for a document we haven't seen, not a "round number."
TIMEOUT_MS = 15000

SCHEMA = "kir-built-verdict/1"

#: THE BRIDGE PHASE NAME IS ITS OWN, NOT THE GENERIC `read`.
#:
#: The judge's run must be distinguishable from every other read in the logs,
#: telemetry, and order guards: `test_serving_acceptance` pins that the last
#: write phase is `acceptance_after`, and an unnamed `read` right after it
#: would read as part of acceptance. It IS NOT: acceptance is independent and
#: complete, and this is a separate read that decides nothing and reverses
#: nothing.
PHASE = "built_reread"


def enabled() -> bool:
    """Whether the built-verdict judge is enabled. An explicit `0`/`off`/`false` disables it."""
    raw = env.get(ENV_FLAG)
    if raw is None:
        return True
    return raw.strip().lower() not in ("0", "off", "false", "no", "")


def _flat_ids(element_map: Any) -> tuple[list[str], dict[str, str], int]:
    """Receipt map → (list of ids, `op_id → element_id`, how many were dropped).

    🔴 THE ARITY UNPACKING IS EXPLICIT, and the argument isn't ours:
    `compare_geometry`'s own docstring requires `{oid: only for oid, (only,)
    in ...}` — because what's compared are walls, openings, and rooms, all of
    arity ONE. A multi-arity op (`create_pipe_system`, `route_*`,
    `move_elements`, `create_room_separator` — five writers out of 66) does
    not make it into the translation, and the number dropped IS RETURNED, not
    lost silently.
    """
    ids: list[str] = []
    translate: dict[str, str] = {}
    dropped = 0
    if not isinstance(element_map, Mapping):
        return ids, translate, dropped
    for oid, value in element_map.items():
        row = value if isinstance(value, (list, tuple)) else [value]
        row = [str(x) for x in row if x is not None and str(x).strip()]
        if not row:
            continue
        ids.extend(row)
        if len(row) == 1:
            translate[str(oid)] = row[0]
        else:
            dropped += 1
    # Sorting is numeric: the bridge body returns rows in this order, and the
    # `_require_exact_ids` check compares sets, not sequences.
    seen: set[str] = set()
    ordered: list[str] = []
    for eid in ids:
        if eid not in seen and eid.isdigit():
            seen.add(eid)
            ordered.append(eid)
    ordered.sort(key=int)
    return ordered, translate, dropped


def _levels_from_snapshot(snapshot: Any) -> tuple[Any, ...]:
    """Levels of the live document from the grounding snapshot → a `LevelInfo` tuple.

    The `levels` pool (`open_model.py:383`) is already reduced to `{id, name,
    elevation_mm}` — exactly the `LevelInfo` fields. A row with no elevation
    is skipped: a level with no elevation isn't a level, and one cannot be
    invented.
    """
    from kir.decompile.schema import LevelInfo

    rows: Any = None
    if isinstance(snapshot, Mapping):
        rows = snapshot.get("levels")
    else:
        pools = getattr(snapshot, "pools", None)
        if isinstance(pools, Mapping):
            rows = pools.get("levels")
    out: list[Any] = []
    for row in (rows or ()):
        if not isinstance(row, Mapping):
            continue
        rid, elev = row.get("id"), row.get("elevation_mm")
        if rid is None or elev is None:
            continue
        try:
            out.append(LevelInfo(id=str(rid), name=str(row.get("name") or ""),
                                 elevation_mm=float(elev)))
        except Exception:  # noqa: BLE001 — a broken pool row is not a verdict
            continue
    # 🔴 ORDER IS PART OF THE `L0Document` CONTRACT, AND A LIVE RUN FOUND THIS
    # (17.08.2026). The grounding pool returns levels in Revit collector
    # order; `L0Document.__post_init__` requires sorting by elevation and
    # refuses with `L0SchemaError: levels must be sorted by elevation`. In the
    # lab this is invisible BY CONSTRUCTION: the fixture has one level, and on
    # a single element every order is valid. The live document has 59 — and
    # the very first run against a real Revit produced a refusal. A control
    # on a degenerate input is green by construction; a guard now stands for
    # this with TWO levels in reverse order.
    out.sort(key=lambda lvl: lvl.elevation_mm)
    return tuple(out)


def _levels_plus_this_turn(levels: tuple, ops: Sequence[Mapping[str, Any]],
                           element_map: Any) -> tuple:
    """Snapshot levels PLUS the ones created by this turn. Order by elevation is the contract.

    Duplicate ids are impossible by construction: a created id comes from
    this same turn's map, and it wasn't in the snapshot (the snapshot was
    taken earlier). Nevertheless the set-based check still runs —
    "impossible" and "verified" are different words.
    """
    from kir.decompile.schema import LevelInfo

    if not isinstance(element_map, Mapping):
        return levels
    было = {lvl.id for lvl in levels}
    добавлено: list[Any] = []
    for op in ops or ():
        if not isinstance(op, Mapping) or op.get("op") != "create_level":
            continue
        elev = op.get("elev_mm")
        адреса = element_map.get(op.get("id"))
        if elev is None or not isinstance(адреса, (list, tuple)) or not адреса:
            continue
        for адрес in адреса:
            if str(адрес) in было:
                continue
            try:
                добавлено.append(LevelInfo(id=str(адрес),
                                           name=str(op.get("name") or ""),
                                           elevation_mm=float(elev)))
                было.add(str(адрес))
            except Exception:  # noqa: BLE001 — a broken row is not a verdict
                continue
    if not добавлено:
        return levels
    out = list(levels) + добавлено
    out.sort(key=lambda lvl: lvl.elevation_mm)
    return tuple(out)


def datum_ops(snapshot: Any, taken_ids: Sequence[str] = ()) -> list[dict[str, Any]]:
    """Levels of the live document → `create_level` operations BEFORE the author's program.

    🔴 WITHOUT THIS, NOT ONLY OUR SIDE IS DEGENERATE BUT SO IS THE ONE
    ALREADY IN PROD (measured 17.08.2026, three programs, the same wall)::

        create_level + wall by=ref       → walls in model 1
        create_level + wall by=name      → walls in model 1
        wall on an EXISTING level        → walls in model 0

    `spatial_model_from_program` resolves the level selector ONLY against a
    `create_level` FROM THE SAME PROGRAM: datums of the live document are
    unknown to it. And a live chat session almost always builds on a level
    that already exists — meaning the verdict about the DECLARED is
    degenerate on exactly the product's main case, and degenerate silently:
    zero walls reads as "nothing to say," not as "the instrument went
    blind." The same holds on the decompile side: `_levels_from_l0` builds
    `known_levels` from the header, and an element with an unknown level
    never reaches the model (tested on five real L0 rows from the tower — 0
    of 5 walls).

    THEREFORE THE DATUM IS FED TO BOTH SIDES FROM ONE SOURCE — the grounding
    snapshot the write already grounded against. This is NOT decompile
    leaking into the program (the `spatial_model_from_program` prohibition
    remains in force to the letter: not a single field is taken from L0): the
    level is a fact about the LIVE DOCUMENT, and both sides get it
    identically.

    The op's id = the Revit ElementId of the level, the name = its name. Both
    selectors, `by=name` and `by=element_id`, resolve against such an op, and
    the wall's `level_id` comes out identical on both sides.

    An id collision with an author operation is a NAMED skip, not a silent
    override: overwriting the author's `id` would mean judging the wrong
    program.
    """
    taken = {str(x) for x in taken_ids}
    out: list[dict[str, Any]] = []
    for level in _levels_from_snapshot(snapshot):
        if level.id in taken:
            continue
        out.append({"op": "create_level", "id": level.id,
                    "elev_mm": float(level.elevation_mm),
                    "name": level.name or level.id})
    return out


def _without_deleted(element_map: Any, ops: Sequence[Mapping[str, Any]]) -> Any:
    """Remove from the map what the turn DELETED: for deletion, absence is success.

    🔴 BOUGHT BY A LIVE TURN 17.08.2026, CLEANING UP AFTER ITSELF. A program
    of eleven `delete`s went through in full — `committed` / `satisfied` /
    `accepted` — and this instrument printed:

        built NOT RE-READ: the re-read did not match the promised —
        re-extract requested/seen mismatch: missing=18830661,…,18830671

    The eleven "missing" ids were exactly the ELEVEN DELETED WALLS. The
    instrument held proof of success in its hands and read it as a refusal,
    because it was asking "is it in place, as created?" of a program that
    created nothing. The question cannot be valid for every effect at once.

    The distinction is asked of the REGISTRY (`EffectKind.DELETE`), not of
    the op's name: a list of names would have drifted from the registry
    exactly as every handwritten table here has drifted. A mixed program
    (create and delete) is judged by what was created, and the deleted
    silently does not enter the numerator.

    WHAT THIS DOES NOT DO is named honestly: deletion is not CONFIRMED here,
    it merely stops being a false refusal. Proof of deletion lives in
    mutation acceptance (`acceptance_mutation`), which has a predicate meant
    for exactly that; the built-verdict judge has none.
    """
    if not isinstance(element_map, Mapping):
        return element_map
    try:
        from kir import spec as _spec
        from kir.registry_base import EffectKind
    except Exception:  # noqa: BLE001 — the registry wasn't consulted: judge as before
        return element_map
    deleted: set[str] = set()
    for op in ops or ():
        if not isinstance(op, Mapping):
            continue
        entry = _spec.OPS.get(str(op.get("op") or ""))
        if entry is not None and getattr(entry, "effect", None) is EffectKind.DELETE:
            oid = str(op.get("id") or "")
            if oid:
                deleted.add(oid)
    if not deleted:
        return element_map
    return {k: v for k, v in element_map.items() if str(k) not in deleted}


def _why_refused(payload: Mapping[str, Any]) -> tuple[str, str]:
    """WHY the re-read didn't happen — by a NAMED cause, not a flag.

    🔴 BOUGHT BY A LIVE TURN 17.08.2026 ON THE OWNER'S TOWER. Four walls went
    up (`committed` / `satisfied` / `accepted`), and this block printed:

        built NOT RE-READ: the bridge answered with an error — True

    Both halves of that line were false. THE BRIDGE WAS NEVER CALLED AT
    ALL — the pipeline record of that same turn reads: `bridge_roundtrips:
    0`, `attempts: 0`, `state: blocked`, `err_code: kir.precondition_unmet`.
    And "True" is the BOOLEAN from the `error` key, substituted into the
    cause slot: `str(payload["error"])`. The instrument named the wrong
    source and named no cause.

    The real cause was lying right next to it, in the open: the `message`
    key carried "KIR refused execution before effect: dispatch
    revit_ir:built_reread is neither the bound regular-write lane nor a named
    unbound dispatch," and `err.code` carried the taxonomy code.

    This is a named defect of this tree, in an instrument written for
    exactly this purpose: a value is DECLARED in one place ("the bridge
    answered") and READ in another (a flag instead of the message), and
    nothing made them agree.

    The order of sources runs from most specific to most general; the
    general flag is taken ONLY when nothing named exists, and then it is
    honestly declared a cause without a name.
    """
    message = str(payload.get("message") or "").strip()
    err = payload.get("err")
    code = ""
    if isinstance(err, Mapping):
        code = str(err.get("code") or "").strip()
    if message:
        return ("перечитывание отклонено до моста" if code.endswith(
            "precondition_unmet") else "перечитывание не состоялось",
            (f"[{code}] " if code else "") + message[:240])
    if code:
        return ("перечитывание не состоялось", f"[{code}] причина не названа")
    # Neither a message nor a code — only the flag. So we say exactly that: source unknown.
    return ("перечитывание не состоялось",
            "источник отказа не назвал причину (только флаг `error`)")


def _refusal(reason: str, detail: str = "") -> dict[str, Any]:
    """An instrument refusal is a THIRD outcome. It never looks like "it matched"."""
    block: dict[str, Any] = {
        "schema": SCHEMA,
        "state": "refused",
        "reason": reason,
        "message_ru": ("построенное НЕ ПЕРЕЧИТАНО: %s%s. Это отказ прибора, а "
                       "не подтверждение, что Revit собрал заявленное"
                       % (reason, (" — " + detail) if detail else "")),
    }
    return block


#: A FIX THAT DEPENDS ON THE DOCUMENT POOL: rule -> pool, without which it
#: cannot be carried out.
#:
#: 🔴 THE LAW WAS ALREADY WRITTEN IN THIS TREE AND EVEN MEASURED — but
#: applied to only one carrier. `ground._empty_pool_next_move` (13.08.2026)
#: says, word for word: "a refusal that names an infeasible move is worse
#: than a refusal that names none: it looks like help and costs a round that
#: could not have succeeded." Measured there too: of 22 empty pools, the move
#: is feasible for TWO.
#:
#: This law never reached the fitness verdict. A live run on 27.08 on a
#: structural file (AVT3_KR_MBPB): the judge issues `HAB030` and advises "Add
#: a window to the room's exterior wall" — while there are NO window families
#: in the document, NOT ONE. This was verified within the same hour by our
#: own program: `create_window` refused with `KIR-G104 window_symbols: empty
#: in the model`. That is, an author who trusted the hint would spend a round
#: on an operation that could not have succeeded.
#:
#: The table is SHORT ON PURPOSE: a census of the hints across all fitness
#: rules yields EXACTLY ONE that requires a family from the pool. Guessing at
#: the rest would mean inventing a subject.
_ПОЧИНКА_ТРЕБУЕТ_ПУЛА = {"HAB030": ("window_symbols", "окон", "окно")}


def _пул_пуст(snapshot: Any, имя: str) -> bool:
    """Whether the document pool is empty. A `None` snapshot does NOT count as empty.

    The difference matters: "the document has no windows" is a fact about
    the building, "there is no snapshot" is a fact about our own turn, and
    conflating them means repeating the named defect in a new spot. When we
    don't know, we stay silent.
    """
    ряды: Any = None
    if isinstance(snapshot, Mapping):
        ряды = snapshot.get(имя)
    else:
        пулы = getattr(snapshot, "pools", None)
        if isinstance(пулы, Mapping):
            ряды = пулы.get(имя)
    if ряды is None:
        return False
    try:
        return len(ряды) == 0
    except TypeError:
        return False


#: How many violations ride along in the receipt. A number from the same
#: family as `ground._CANDIDATES_SHOWN`: a list that can't be read by eye
#: doesn't help the reader choose, and the remainder must be NAMED as a
#: number.
_BLOCKING_SHOWN = 6

#: How many WARNINGS ride alongside the blocking ones.
#:
#: 🔴 SHOWING ONLY THE BLOCKING ONES WAS NOT ENOUGH (27.08.2026, a live
#: four-room apartment). The receipt printed "rules violated: 1" — and the
#: reader concluded that was ALL. Yet the report right next to it carried a
#: warning: the kitchen has no exterior window. Rule HAB030 covers both
#: living rooms and kitchens, but at different severities
#: (`_DAYLIT_SEVERITY` = {living: blocking, kitchen: warning}), and the
#: second half of the finding never reached the author.
#:
#: Silence read as "there is nothing more" is our named defect. That's why
#: the counts of warnings and "for the record" items are printed ALWAYS,
#: even when the lines themselves didn't fit: the reader must see that there
#: is more behind the verdict.
_WARNINGS_SHOWN = 3


def _почему(verdict: Any, snapshot: Any = None) -> dict[str, Any]:
    """The violations responsible for this verdict. Empty if there are none.

    🔴 ADDED 27.08.2026 FROM A LIVE RUN, AND THIS IS NOT RECEIPT DECORATION.
    Built a real room in a live building (4 walls, floor, door, room — 7 of 7
    elements). The judge answered, word for word:

        verdict on the BUILT: Verdict.FAIL · on the DECLARED: Verdict.FAIL

    and NOWHERE named which rule was violated. All that was listed were the
    discrepancies BETWEEN the two sides — a different subject: they say the
    declared and the built diverged, and say nothing about what is wrong
    with the built. The author gets a sentence with no charge and cannot
    make the next move.

    THE VALUE WAS ONE ATTRIBUTE AWAY FROM THE LETTER. `check_design` returns
    a `DesignVerdict`, whose `verdict` is `self.report.verdict`, right next
    to the same `report` in full, with `blocking`/`warnings`/`info` fields.
    The judge read `.verdict` and threw away `.report`. Every `Violation`
    carries `rule_id`, `msg`, `refs`, and `fix_hint` — a READY-MADE fix
    string.

    Exactly our named defect: a value is DECLARED in one place, READ in
    another, and nothing forced them to agree. Only here the cost wasn't a
    round, but the impossibility of fixing anything at all.
    """
    отчёт = getattr(verdict, "report", None)

    def _строки(имя: str, потолок: int) -> tuple[list[dict[str, Any]], int]:
        ряды = list(getattr(отчёт, имя, None) or [])
        вышло: list[dict[str, Any]] = []
        for v in ряды[:потолок]:
            строка = {"rule": str(getattr(v, "rule_id", "") or "?"),
                      "msg": str(getattr(v, "msg", "") or "")[:400]}
            подсказка = str(getattr(v, "fix_hint", "") or "")[:400]
            if подсказка:
                строка["fix"] = подсказка
            ссылки = list(getattr(v, "refs", None) or [])[:8]
            if ссылки:
                строка["refs"] = [str(r) for r in ссылки]
            # THE FIX CHECKS AGAINST THE DOCUMENT. See `_ПОЧИНКА_ТРЕБУЕТ_ПУЛА`.
            треб = _ПОЧИНКА_ТРЕБУЕТ_ПУЛА.get(строка["rule"])
            if треб and _пул_пуст(snapshot, треб[0]):
                пул, род, штука = треб
                строка["fix_unreachable"] = пул
                строка["fix"] = (
                    "🔴 В ЭТОМ ДОКУМЕНТЕ ПОЧИНКА НЕВЫПОЛНИМА: семейств %s нет "
                    "ни одного (пул `%s` пуст), и `create_window` откажет "
                    "`KIR-G104`. СНАЧАЛА принеси семейство — `load_family` или "
                    "`transfer_family` — и только потом ставь %s. Если "
                    "помещение не жилое, верный ход другой: назвать его так, "
                    "чтобы правило к нему не относилось."
                    % (род, пул, штука))
            вышло.append(строка)
        return вышло, len(ряды)

    блок, блок_всего = _строки("blocking", _BLOCKING_SHOWN)
    предупр, предупр_всего = _строки("warnings", _WARNINGS_SHOWN)
    _, к_сведению = _строки("info", 0)
    return {"blocking": блок, "blocking_total": блок_всего,
            "warnings": предупр, "warnings_total": предупр_всего,
            "info_total": к_сведению}


def _вердикт_плоско(block: Mapping[str, Any]) -> str:
    """The verdict AND its CAUSE in one flat string — to survive collapsing.

    🔴 WITHOUT THIS, THE JUDGE'S ENTIRE WORK LIVES FOR EXACTLY ONE ROUND
    (27.08.2026, found by dissecting a live 662-second turn).

    `chat_helpers._summarize_tool_result` collapses EVERY list and EVERY dict
    into «<объект, N полей — свёрнуто>»; only top-level scalars survive.
    Measured on a real receipt from a live building: 30,460 -> 1,534
    characters, and NOTHING was left of the verdict — `built` is a dict, so
    it gets collapsed whole, together with `verdict_built_because`, which I
    added that same morning.

    Meanwhile `built_note` SURVIVED and said: «построенное перечитано:
    элементов 7 · расхождений с заявленным НЕТ». That is, on the second
    round the model read a line that looks like SUCCESS, while the verdict
    was FAIL with a room unfit for habitation. This is worse than absence:
    absence forces a question, a false success does not.

    Hence the cost visible in the trace: 60 KB of reasoning and dozens of
    re-checks of model state — the author was re-deriving what they had
    already been told a round earlier.
    """
    вердикт = str(block.get("verdict_built") or "").replace("Verdict.", "")
    if not вердикт:
        return ""
    части = ["вердикт %s" % вердикт]
    вина = block.get("verdict_built_because") or []
    всего = int(block.get("verdict_built_because_total") or len(вина))
    if вина:
        первое = вина[0]
        части.append("%s: %s" % (первое.get("rule"),
                                 str(первое.get("msg") or "")[:160]))
        if первое.get("fix"):
            части.append("ЧИНИТЬ: %s" % str(первое["fix"])[:160])
        if всего > 1:
            части.append("и ещё %d нарушений" % (всего - 1))
    предупр = int(block.get("verdict_built_warnings_total") or 0)
    if предупр:
        части.append("предупреждений %d" % предупр)
    return " · ".join(части)


#: TWO COMPARATORS AND TWO KEYS FOR THEIR FAILURE — ONE LIST, NOT THREE
#: COPIES. Both places that ask "did the comparison happen" (the `_message`
#: prose and the flat `note`) must ask THE EXACT SAME THING: diverging
#: copies of this list are exactly the mechanism by which one carrier gets
#: fixed while the other keeps lying.
_СРАВНИТЕЛИ: tuple[tuple[str, str], ...] = (
    ("вердиктов", "compare_error"),
    ("геометрии", "compare_geometry_error"),
)


def _сорванные_сверки(block: Mapping[str, Any]) -> list[tuple[str, str]]:
    """Which of the comparators did NOT run — with the verbatim cause for each."""
    return [(имя, str(block.get(ключ))) for имя, ключ in _СРАВНИТЕЛИ
            if block.get(ключ)]


def _уцелевшие_сверки(block: Mapping[str, Any]) -> list[str]:
    return [имя for имя, ключ in _СРАВНИТЕЛИ if not block.get(ключ)]


def note(block: Mapping[str, Any]) -> str:
    """A FLAT string about the built — the only thing that survives collapsing.

    Form 27 of the canon: `chat_helpers._summarize_tool_result` replaces
    EVERY dict and list with «свёрнуто», leaving only top-level scalars. A
    verdict that lives only in structure never reaches the model through
    history.
    """
    state = str(block.get("state") or "")
    if state != "judged":
        return "построенное: %s" % (block.get("message_ru") or state or "нет данных")
    read = block.get("elements_read")
    div = block.get("divergences") or []
    geo = block.get("geometry_divergences") or []
    # 🔴 ZERO RE-READ IS NOT AGREEMENT. Bought twice within one hour on
    # 21.08.
    #
    # `author_family` issues a DEFINITION: its identity is the type, and the
    # type is never placed — the instance is. Re-reading elements
    # deliberately discards types, and at first the judge refused outright
    # («перечитанное не сошлось»), naming a number instead of a cause. The
    # omission learned to name itself — and the judge instantly became
    # DEGENERATE: «элементов 0, расхождений НЕТ». The second is worse than
    # the first: a false refusal is visible, empty agreement reads as a
    # check.
    #
    # Canon: zero of an UNCOMPUTED value is printed as a WORD, not a number.
    asked = block.get("elements_asked")
    if isinstance(read, int) and read == 0 and isinstance(asked, int) and asked:
        return ("построенное НЕ ПЕРЕЧИТЫВАЛОСЬ: из %d заявленных личностей "
                "перечитать было НЕЧЕГО — все они типоразмеры либо иные "
                "определения, которые в модели не стоят. Это НЕ согласие: "
                "проверка не выполнялась. Экземпляр, если он создан, судится "
                "своим id" % asked)
    head = ("построенное перечитано: элементов %s" % read)
    seen = block.get("visible_in_active_view")
    if isinstance(seen, int) and isinstance(read, int):
        head += (" · ВИДНО в «%s» %d из %d"
                 % (block.get("active_view_name") or "?", seen, read))
    # 🔴 A FAILED COMPARISON PRINTED AS AGREEMENT — LD-06, measured
    # 04.09.2026.
    #
    # `judge`, when either of the two comparators fails, drops an EMPTY list
    # of discrepancies and records the cause in `compare_error` /
    # `compare_geometry_error`. Here these two keys were not consulted AT
    # ALL, and three different states produced ONE string, byte for byte:
    #
    #     compared, found nothing        -> «… · расхождений с заявленным НЕТ»
    #     the verdict comparator failed   -> THE SAME STRING
    #     the geometry comparator failed  -> THE SAME STRING
    #
    # This is exactly the argument recorded twenty lines above about zero
    # re-read: A FALSE REFUSAL IS VISIBLE, EMPTY AGREEMENT READS AS A CHECK.
    # The `_message` prose has been asking this question since 04.09
    # (F-125), but the flat string — the ONLY thing that survives history
    # collapsing — kept lying: the fix landed on one carrier out of two.
    сорвалось = _сорванные_сверки(block)
    if not div and not geo:
        # Checks that passed exactly are named by a NUMBER: otherwise
        # «сошлось» and «не смотрели» read the same — both strings are empty.
        agreed = int(block.get("geometry_agreements_total") or 0)
        if сорвалось:
            # Zero of an UNCOMPUTED value is printed as a WORD, not a number:
            # «расхождений НЕТ» cannot be said here in any form.
            tail = (" · 🔴 СВЕРКА НЕ ВЫПОЛНЯЛАСЬ, и «расхождений нет» здесь "
                    "СКАЗАТЬ НЕЛЬЗЯ: "
                    + " · ".join("сравнитель %s сорвался (%s)" % (имя, текст)
                                 for имя, текст in сорвалось))
            уцелел = _уцелевшие_сверки(block)
            if уцелел:
                tail += (" · сравнитель %s отработал: его числа верны, но "
                         "полной картины они не дают" % ", ".join(уцелел))
        else:
            tail = " · расхождений с заявленным НЕТ"
        if agreed:
            tail += " · сверок геометрии сошлось %d" % agreed
        note = block.get("visibility_note_ru")
        # THE VERDICT COMES BEFORE EVERYTHING ELSE: this is the only string
        # that will survive collapsing, and the reader must see the sentence
        # before the arithmetic about the number of re-read elements.
        приговор = _вердикт_плоско(block)
        return ((приговор + " · " if приговор else "") + head + tail
                + (" · " + note if note else ""))
    приговор = _вердикт_плоско(block)
    parts = ([приговор] if приговор else []) + [head]
    # AN INCOMPLETE COMPARISON COMES BEFORE THE NUMBERS IT QUALIFIES. The
    # discrepancies found do not cancel the fact that the second comparator
    # is silent not because it agrees: "verdict discrepancies" is simply
    # absent from the line, and absence reads as zero.
    if сорвалось:
        parts.append("🔴 СВЕРКА НЕПОЛНАЯ: "
                     + " · ".join("сравнитель %s сорвался (%s)" % (имя, текст)
                                  for имя, текст in сорвалось)
                     + " — числа ниже НЕ полны")
    if div:
        parts.append("расхождений вердикта %d" % len(div))
    if geo:
        parts.append("геометрия расходится в %d" % len(geo))
    first = (geo or div)[0]
    parts.append("первое: %s %s — заявлено %s, построено %s"
                 % (first.get("kind", ""), first.get("subject", ""),
                    first.get("program", first.get("b", "")),
                    first.get("parse", first.get("a", ""))))
    return " · ".join(parts)


def _divergence_rows(items: Sequence[Any], *,
                     cap: int) -> tuple[list[dict[str, Any]], int]:
    """Discrepancies into flat strings. Truncation IS RETURNED as a number.

    A truncated list with no total count is a separate defect of this tree,
    and it has already been fixed in `serving` three times over. Here the
    count rides alongside from the very start.
    """
    rows: list[dict[str, Any]] = []
    for item in items[:cap]:
        rows.append({
            "kind": str(getattr(item, "kind", "") or ""),
            "subject": str(getattr(item, "subject", "") or ""),
            # 🔴 FIELD NAMES WERE ASKED OF `Divergence`, NOT GUESSED. The
            # first edit read `.a`/`.b` — it has none, and `getattr(…, "")`
            # returned EMPTY STRINGS: the discrepancy printed as «заявлено ,
            # построено », i.e. the finding looked like a cosmetic glitch.
            # Caught by the very first run; canon form 7 in pure form.
            "parse": str(getattr(item, "parse", "") or ""),
            "program": str(getattr(item, "program", "") or ""),
            "cause": str(getattr(item, "cause", "") or ""),
        })
    return rows, len(items)


async def judge(
    *,
    reader: Any,
    element_map: Any,
    ops: Sequence[Mapping[str, Any]],
    snapshot: Any,
    doc_name: str = "",
    revit_version: str = "",
    change_stamp: str = "",
    cap: int = 12,
) -> dict[str, Any] | None:
    """Re-read what was created and reconcile with the declared. Never raises.

    `None` — the module is disabled: not a single key in the receipt, byte
    for byte as before this wave. Everything else is a block with `state`,
    and `state != "judged"` is a REFUSAL WITH A CAUSE, not agreement.

    `reader` — the same shape as in acceptance: `async (code, phase,
    timeout_ms)`. The module knows nothing about the bridge or the pipeline;
    it can be swapped out in a test with a single function, and that is
    exactly why it is a parameter here, not an import.
    """
    if not enabled():
        return None
    try:
        return await _judge_inner(
            reader=reader, element_map=element_map, ops=ops,
            snapshot=snapshot, doc_name=doc_name,
            revit_version=revit_version, change_stamp=change_stamp, cap=cap)
    except Exception as exc:  # noqa: BLE001 — an ABSOLUTE fail-open: Revit already wrote
        logger.debug("built verdict failed (fail-open)", exc_info=True)
        return _refusal("судья построенного сорвался",
                        "%s: %s" % (type(exc).__name__, str(exc)[:160]))


async def _judge_inner(
    *,
    reader: Any,
    element_map: Any,
    ops: Sequence[Mapping[str, Any]],
    snapshot: Any,
    doc_name: str,
    revit_version: str,
    change_stamp: str,
    cap: int,
) -> dict[str, Any] | None:
    from kir import design_check as _dc
    from kir.decompile import reextract as _re
    from kir.decompile.schema import L0Document, ProjectInfo

    ids, translate, plural_dropped = _flat_ids(_without_deleted(element_map, ops))
    if not ids:
        # EMPTY AND ABSENT ARE DIFFERENT FACTS. The map doesn't exist at all
        # (the write created nothing, or `element_map` never assembled) —
        # there is nothing to judge, and that is not an instrument refusal
        # but the absence of a subject.
        return None

    truncated = 0
    if len(ids) > MAX_IDS:
        truncated = len(ids) - MAX_IDS
        ids = ids[:MAX_IDS]

    # --- 1. RE-READ. One run, ~1.1 s (measured in the header) ----------------
    try:
        code = _re.build_reextract_cs(ids)
    except Exception as exc:  # noqa: BLE001 — a typed refusal from the body assembler
        return _refusal("тело перечитывания не собралось",
                        "%s: %s" % (type(exc).__name__, str(exc)[:160]))
    try:
        payload = await reader(code, PHASE, TIMEOUT_MS)
    except Exception as exc:  # noqa: BLE001 — the bridge is silent: that is a REFUSAL, not a zero
        return _refusal("мост не ответил на перечитывание",
                        "%s: %s" % (type(exc).__name__, str(exc)[:160]))
    if isinstance(payload, Mapping) and payload.get("error"):
        return _refusal(*_why_refused(payload))

    try:
        elements = _re.parse_reextract_rows(payload, requested_ids=ids)
    except _re.ReExtractError as exc:
        # I2: an id NOT FOUND is a typed refusal, not a skipped element. Here
        # it is exactly the main signal: an element created by the turn and
        # not found a second later is an event the model must be told about.
        return _refusal("перечитанное не сошлось с обещанным", str(exc)[:240])
    except Exception as exc:  # noqa: BLE001
        return _refusal("строки перечитывания не разобрались",
                        "%s: %s" % (type(exc).__name__, str(exc)[:160]))

    # --- 1b. RE-READ ROOMS AS A SECOND RUN ------------------------------------
    #
    # 🔴 `rooms=()` USED TO STAND HERE — A HARD EMPTY TUPLE, AND THAT IS NOT
    # "COULDN'T READ" BUT "DOESN'T READ BY CONSTRUCTION" (found live
    # 25.08.2026).
    #
    # The cost was the entire LOGICAL-CONSISTENCY judge at once. A real
    # 42 m² one-bedroom was built: seven walls, four doors, three windows, a
    # floor, a ceiling, and FOUR rooms; `KIR-X004` did not fire, meaning
    # Revit computed the areas and the rooms CLOSED. Yet the judge printed
    # twelve discrepancies, the first being «популяция rooms: заявлено 4,
    # построено 0». The rest poured in after it: `rooms_measured`,
    # `rooms_classified`, `doors_with_adjacency`, and `windows_joined`
    # («требует полигона помещения — полигонов А=0»), and the habitability
    # fitness rules `HAB002`/`HAB020` fell into `not_evaluated`.
    #
    # ALL TWELVE FOLLOW FROM ONE LINE. Verified by narrowing: the same zero
    # is produced by a minimal probe of FOUR walls and ONE room in an empty
    # spot — so this is not a property of the layout, nor an author's
    # defect.
    #
    # 🔴 AND THE BODY FOR READING ROOMS HAD BEEN BUILT THE WHOLE TIME.
    # `reextract.build_room_reextract_cs` + `parse_room_reextract` exist, are
    # covered by gates, and compile on six versions — NOBODY CALLED THEM.
    # That same morning I was fixing an undeclared `__src` in this very body
    # and did not notice it was unreachable: I was fixing the compilation of
    # dead code. Canon form 4 in pure form — a zero from an unreachable
    # corpus — and "built and not wired in," which this project calls its
    # primary form.
    #
    # THE RUN IS SEPARATE because the bodies differ: the element one
    # collects L0 rows by id, the room one collects boundary loops. A
    # failure of the second run does NOT bring down the whole judge: rooms
    # are the input to the fitness rules, and their absence is more honest
    # declared as a void with a cause than losing the verdict about the
    # walls.
    rooms: tuple = ()
    rooms_note = ""
    try:
        room_code = _re.build_room_reextract_cs(ids)
        room_payload = await reader(room_code, PHASE, TIMEOUT_MS)
        if isinstance(room_payload, Mapping) and room_payload.get("error"):
            rooms_note = "помещения не перечитаны: %s" % _why_refused(room_payload)[0]
        else:
            # 🔴 WITHOUT `requested_ids`, AND THIS IS NOT A WEAKENING OF THE
            # CHECK (25.08.2026). The collector's docstring promises, word
            # for word: «Non-room ids in `ids` are simply not matched (the
            # collector is OST_Rooms-scoped), so callers may pass the whole
            # created-id set». Yet the parser, given the list, demands an
            # EXACT match and fails: «room re-extract requested/seen
            # mismatch: missing=313918,…» — that is, on the walls, doors, and
            # windows of the same turn. The two ends of one contract
            # diverged, and the promise is wider than the behavior.
            #
            # Here the ENTIRE set of what was created is passed (otherwise
            # rooms would have to be guessed before reading), so a
            # completeness check against it is meaningless BY CONSTRUCTION.
            # Completeness of the element run is checked by its own call
            # above — with its own `requested_ids`, and that check is not
            # weakened.
            rooms = tuple(_re.parse_room_reextract(room_payload))
    except Exception as exc:  # noqa: BLE001
        rooms_note = ("помещения не перечитаны: %s: %s"
                      % (type(exc).__name__, str(exc)[:120]))

    # --- 2. ASSEMBLE THE DOCUMENT. The header comes from the grounding snapshot ---
    levels = _levels_from_snapshot(snapshot)
    # 🔴 PLUS LEVELS CREATED BY THIS SAME TURN. FOUND LIVE 03.09.2026, AND
    # THE COST WAS THE ENTIRE BUILT-VERDICT JUDGE FOR THE MAIN USER.
    #
    # The grounding snapshot is taken BEFORE the turn, so a level the turn
    # created is not in it. `design_check.spatial_model_from_l0` discards a
    # room whose `level_id` does not belong to the document («уровень вне
    # документа»), and discards ALL of them if the floor was built by the
    # same turn. Rule `HAB000` then declares «model has no rooms», even
    # though the very same receipt CARRIES `rooms_read: 5`. One receipt
    # contradicts itself, and on the worse side: "not evaluated" reads as
    # "nothing wrong was found."
    #
    # Measured on a real live Revit in 2026, the same apartment, differing
    # ONLY in the level's origin:
    #
    #     level CREATED by this turn       rooms 5 · HAB000 «нет помещений»
    #     level EXISTED before the turn    rooms 5 · NO blocking findings
    #
    # The elevation is taken from the OP (`elev_mm`), not from the re-read
    # level's dimension: it is declared by the author precisely, whereas the
    # level's dimension would have to be interpreted. The address comes from
    # the created-elements map: the real Revit id lives there.
    levels = _levels_plus_this_turn(levels, ops, element_map)
    try:
        document = L0Document(
            doc_name=doc_name or "(живой документ)",
            revit_version=str(revit_version or "0"),
            units="mm",
            change_stamp=change_stamp or "built-verdict",
            levels=levels, grids=(), rooms=rooms,
            project_info=ProjectInfo(), elements=tuple(elements))
    except Exception as exc:  # noqa: BLE001
        return _refusal("документ перечитанного не собрался",
                        "%s: %s" % (type(exc).__name__, str(exc)[:160]))

    # --- 3. JUDGE BOTH SIDES BY THE SAME RULES --------------------------------
    try:
        parse_model, parse_witness = _dc.spatial_model_from_l0(
            document, building_id="построенное этим ходом")
        parse_verdict = _dc.check_design(parse_model, parse_witness)
    except _dc.DesignCheckUnavailable as exc:
        # AN HONEST REFUSAL, NOT A SUBSTITUTION: the v1 path gives neither a
        # three-valued verdict nor coverage. Issuing it in place of the
        # stage's verdict would mean substituting the claim — the flag is
        # set in prod, not in the development tree.
        return _refusal("судья недоступен", str(exc)[:200])
    except Exception as exc:  # noqa: BLE001
        return _refusal("вердикт о построенном не вынесен",
                        "%s: %s" % (type(exc).__name__, str(exc)[:160]))

    program_verdict = None
    program_model = None
    program_error = ""
    authored = [dict(op) for op in ops]
    datums = datum_ops(snapshot, [str(op.get("id") or "") for op in authored])
    try:
        program_model, program_witness = _dc.spatial_model_from_ops(
            {"ir_version": "1.0", "ops": datums + authored},
            building_id="заявленное этим ходом")
        program_verdict = _dc.check_design(program_model, program_witness)
    except Exception as exc:  # noqa: BLE001 — the DECLARED side can refuse
        program_error = "%s: %s" % (type(exc).__name__, str(exc)[:160])

    # 🔴 THE THIRD QUESTION: CAN A HUMAN SEE IT. Rides the SAME run as the
    # re-read (`reextract` counts it itself, id-addressed), so it costs zero
    # extra trips to the bridge.
    #
    # 21.08.2026: the document had 925 generic models, and the active 3D
    # view showed ZERO — the section box stood in an empty spot at −52 km.
    # The witness said "built," the judge said "matches," acceptance said
    # "accepted," and all three were answering a DIFFERENT question. For a
    # product whose demonstration IS "look at what the AI built," an
    # unobservable build equals an unbuilt one — with the difference that it
    # looks like success.
    inner = payload.get("result") if isinstance(payload.get("result"), Mapping) \
        else payload
    visible = inner.get("active_view_visible") if isinstance(inner, Mapping) else None
    block: dict[str, Any] = {
        "schema": SCHEMA,
        "state": "judged",
        "elements_asked": len(ids),
        "elements_read": len(elements),
        "levels_known": len(levels),
        # A NUMBER, NOT A VOID: "zero rooms" and "rooms were not read" must
        # be distinguishable — before 25.08 they arrived as the same value.
        "rooms_read": len(rooms),
        "verdict_built": str(getattr(parse_verdict, "verdict", "") or ""),
        "source": "parse",
    }
    # A SENTENCE WITH NO CHARGE IS NOT A SENTENCE. See `_почему`.
    _разбор = _почему(parse_verdict, snapshot)
    if _разбор["blocking"]:
        block["verdict_built_because"] = _разбор["blocking"]
        block["verdict_built_because_total"] = _разбор["blocking_total"]
    if _разбор["warnings"]:
        block["verdict_built_warnings"] = _разбор["warnings"]
        block["verdict_built_warnings_total"] = _разбор["warnings_total"]
    if _разбор["info_total"]:
        block["verdict_built_info_total"] = _разбор["info_total"]
    if rooms_note:
        block["rooms_note_ru"] = rooms_note
    # ── THE BUILDING AS A SHAPE: O(changes) ALONGSIDE O(operations) ──────
    #
    # 🔴 WHY THIS LIVES HERE, NOT IN A SEPARATE INSTRUMENT. The judge is the
    # one place where the re-read elements are ALREADY in hand; computing
    # the shape anywhere else would mean reading the model a second time for
    # the same knowledge. The shape does NOT REPLACE the per-element verdict
    # and stands beside it: the verdict PROVES each element, the shape SHOWS
    # what happened to the building.
    #
    # MEASURED (21.08.2026, MNVNK, 33,944 elements): the delta is bounded at
    # 398 cells (52.6 KB) for ANY size of change, whereas a per-element
    # record of the whole model is 7.6 MB and grows linearly. The gain
    # depends on the SHAPE of the change (2x on a spot fix, 1055x on a new
    # floor) — quoting one number would mean picking a convenient one; the
    # value is in the CEILING, which the per-element record has none of at
    # all.
    if elements:
        from kir import stage_shape as _shape
        _sh = _shape.shape_of([
            {"category": getattr(e, "category", None),
             "level_name": getattr(e, "level_name", None),
             "bbox_min_mm": getattr(e, "bbox_min_mm", None),
             "bbox_max_mm": getattr(e, "bbox_max_mm", None)}
            for e in elements])
        block["stage_shape"] = _sh.to_dict()
        # The delta is computed FROM EMPTY: the judge sees what THIS write
        # built, not the whole building. It has no prior stage in hand, and
        # inventing one would mean declaring someone else's elements as its
        # own.
        block["stage_note_ru"] = _shape.delta_note_ru(
            _shape.shape_delta(None, _sh))
    if isinstance(visible, int):
        block["visible_in_active_view"] = visible
        block["active_view_name"] = str(
            (inner.get("active_view_name") if isinstance(inner, Mapping) else "")
            or "")
        block["active_view_section_box"] = bool(
            inner.get("active_view_section_box")
            if isinstance(inner, Mapping) else False)
        if visible < len(elements):
            block["visibility_note_ru"] = (
                "🔴 ПОСТРОЕНО, НО НЕ ВИДНО: в активном виде %r видно %d из %d. "
                "Свидетель и судья отвечают на другой вопрос — «построено» и "
                "«совпадает», а не «наблюдаемо». Смотри секущую рамку вида, "
                "видимость категорий, фильтры и фазу"
                % (block["active_view_name"], visible, len(elements)))
    if truncated:
        block["ids_truncated"] = truncated
        block["truncation_ru"] = (
            "перечитаны ПЕРВЫЕ %d элементов из %d: одно тело моста читает не "
            "больше %d (`reextract.REEXTRACT_BATCH`). Остальные НЕ судились"
            % (MAX_IDS, MAX_IDS + truncated, MAX_IDS))
    if plural_dropped:
        block["plural_ops_untranslated"] = plural_dropped
        block["plural_ru"] = (
            "%d операций множественной арности в перевод адресов не вошли: "
            "поэлементная сверка их геометрии не проводилась" % plural_dropped)

    # --- 4. DISCREPANCY IS THE MAIN PRODUCT -----------------------------------
    if program_verdict is None:
        block["program_side_ru"] = (
            "сторона ЗАЯВЛЕННОГО не собралась (%s): вердикт о построенном стоит "
            "один, сравнивать его не с чем" % program_error)
        block["message_ru"] = _message(block, [], [])
        return block

    block["verdict_declared"] = str(getattr(program_verdict, "verdict", "") or "")
    _разбор_з = _почему(program_verdict, snapshot)
    if _разбор_з["blocking"]:
        block["verdict_declared_because"] = _разбор_з["blocking"]
        block["verdict_declared_because_total"] = _разбор_з["blocking_total"]
    if _разбор_з["warnings"]:
        block["verdict_declared_warnings"] = _разбор_з["warnings"]
        block["verdict_declared_warnings_total"] = _разбор_з["warnings_total"]
    try:
        divergences = _dc.compare(parse_verdict, program_verdict)
    except Exception as exc:  # noqa: BLE001
        divergences = []
        block["compare_error"] = "%s: %s" % (type(exc).__name__, str(exc)[:120])
    try:
        geometry = _dc.compare_geometry(parse_model, program_model,
                                        translate=translate)
    except Exception as exc:  # noqa: BLE001
        geometry = []
        block["compare_geometry_error"] = "%s: %s" % (type(exc).__name__,
                                                      str(exc)[:120])

    rows, total = _divergence_rows(divergences, cap=cap)
    block["divergences"] = rows
    block["divergences_total"] = total
    # 🔴 AGREEMENT IS SEPARATED FROM DISCREPANCY BEFORE ANY COUNTING
    # (25.08.2026). `compare_geometry` returns ONE list that holds both: a
    # comparison that passed exactly arrives with kind `СВЕРКА`. While they
    # were counted together, the judge printed «геометрия расходится в 1»
    # alongside «совпало 80, макс 0.00 мм» — see the argument at the
    # constant itself. The split must be done by the READER, because the
    # reader is the one counting: the number of discrepancies lives here,
    # not in the comparator.
    agreed = [d for d in geometry if getattr(d, "kind", "") == _dc.СВЕРКА]
    diverged = [d for d in geometry if getattr(d, "kind", "") != _dc.СВЕРКА]
    geo_rows, geo_total = _divergence_rows(diverged, cap=cap)
    block["geometry_divergences"] = geo_rows
    block["geometry_divergences_total"] = geo_total
    agreed_rows, agreed_total = _divergence_rows(agreed, cap=cap)
    block["geometry_agreements"] = agreed_rows
    block["geometry_agreements_total"] = agreed_total
    block["message_ru"] = _message(block, rows, geo_rows)
    return block


def _message(block: Mapping[str, Any], rows: Sequence[Mapping[str, Any]],
             geo: Sequence[Mapping[str, Any]]) -> str:
    """Prose for a human. The numbers come from the block, not out of thin air."""
    lines = ["ПОСТРОЕННОЕ ПЕРЕЧИТАНО В REVIT: элементов %s из %s, уровней %s."
             % (block.get("elements_read"), block.get("elements_asked"),
                block.get("levels_known"))]
    built = block.get("verdict_built")
    declared = block.get("verdict_declared")
    if declared:
        lines.append("вердикт о ПОСТРОЕННОМ: %s · о ЗАЯВЛЕННОМ: %s"
                     % (built or "—", declared or "—"))
    # THE WHY COMES RIGHT AFTER THE VERDICT, NOT AT THE END AND NOT IN A
    # MACHINE FIELD. The order here is the same as for the receipt keys
    # (`serving._RECEIPT_ORDER_HEAD`): truncation cuts the tail, so the
    # charge must stand right next to the sentence.
    def _вина(заголовок: str, корень: str) -> None:
        блок = block.get("%s_because" % корень) or []
        блок_всего = int(block.get("%s_because_total" % корень) or len(блок))
        предупр = block.get("%s_warnings" % корень) or []
        предупр_всего = int(block.get("%s_warnings_total" % корень)
                            or len(предупр))
        сведения = int(block.get("%s_info_total" % корень) or 0)
        if not блок and not предупр and not сведения:
            return
        # NUMBERS OF ALL THREE KINDS — ALWAYS. "1 rule violated" without the
        # other two reads as "there is nothing more," and that is a
        # different claim.
        части = ["нарушено правил %d" % блок_всего]
        if предупр_всего:
            части.append("предупреждений %d" % предупр_всего)
        if сведения:
            части.append("к сведению %d" % сведения)
        lines.append("%s: %s" % (заголовок, " · ".join(части)))

        def _строки(ряды: list, всего: int, метка: str) -> None:
            if not ряды:
                return
            if всего > len(ряды):
                lines.append("  %s — ПОКАЗАНЫ %d ИЗ %d"
                             % (метка, len(ряды), всего))
            for v in ряды:
                строка = "  · %s: %s" % (v.get("rule"), v.get("msg"))
                if v.get("refs"):
                    строка += " [%s]" % ", ".join(v["refs"][:4])
                lines.append(строка)
                if v.get("fix"):
                    lines.append("    ЧИНИТЬ ТАК: %s" % v["fix"])

        _строки(блок, блок_всего, "блокирующие")
        if предупр:
            lines.append("  ПРЕДУПРЕЖДЕНИЯ (вердикт не блокируют):")
            _строки(предупр, предупр_всего, "предупреждения")

    _вина("ПОЧЕМУ ПОСТРОЕННОЕ", "verdict_built")
    _вина("ПОЧЕМУ ЗАЯВЛЕННОЕ", "verdict_declared")
    total = int(block.get("geometry_divergences_total") or 0)
    dtotal = int(block.get("divergences_total") or 0)
    # 🔴 A COMPARISON THAT DID NOT HAPPEN IS NOT AGREEMENT (F-125, confirmed
    # by execution 04.09.2026). A refusal from either of the two comparators
    # was replaced by an EMPTY list of discrepancies, the block stayed
    # `judged`, and the line shown to a human was LITERALLY THE SAME as for
    # a healthy turn:
    #
    #     both comparators failed  ->  «Расхождений … НЕ НАЙДЕНО.»
    #     compared and found none  ->  «Расхождений … НЕ НАЙДЕНО.»
    #
    # This is the same law recorded twenty lines above about zero re-read:
    # zero of an UNCOMPUTED value is printed as a WORD, not a number. The
    # errors were already sitting in the block (`compare_error`,
    # `compare_geometry_error`) — nobody had simply asked for them.
    сорвалось = _сорванные_сверки(block)
    if сорвалось:
        lines.append("🔴 СРАВНЕНИЕ НЕ ВЫПОЛНЯЛОСЬ, и «расхождений нет» здесь "
                     "СКАЗАТЬ НЕЛЬЗЯ: " + " · ".join(
                         "сравнитель %s сорвался (%s)" % (имя, текст)
                         for имя, текст in сорвалось))
        если_ещё = _уцелевшие_сверки(block)
        if если_ещё:
            lines.append("   второй сравнитель (%s) отработал; его числа ниже "
                         "верны, но полной картины они не дают"
                         % ", ".join(если_ещё))
    if not total and not dtotal and not сорвалось:
        lines.append("Расхождений между заявленным и построенным НЕ НАЙДЕНО.")
    else:
        if total:
            lines.append("ГЕОМЕТРИЯ РАСХОДИТСЯ: %d (показано %d)"
                         % (total, len(geo)))
            for row in geo:
                lines.append("  · %s %s: заявлено %s, построено %s"
                             % (row["kind"], row["subject"],
                                row["program"], row["parse"]))
        if dtotal:
            lines.append("вердикты расходятся в %d (показано %d)"
                         % (dtotal, len(rows)))
            for row in rows:
                lines.append("  · %s %s: заявлено %s, построено %s"
                             % (row["kind"], row["subject"],
                                row["program"], row["parse"]))
    for key in ("truncation_ru", "plural_ru", "program_side_ru"):
        if block.get(key):
            lines.append(str(block[key]))
    return "\n".join(lines)


__all__ = ["ENV_FLAG", "MAX_IDS", "PHASE", "SCHEMA", "TIMEOUT_MS", "datum_ops",
           "enabled", "judge",
           "note"]
