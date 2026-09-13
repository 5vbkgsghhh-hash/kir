"""THE BUILDING'S JUDGE — a session's batch travels to the verdict and comes back AS A RECEIPT.

WHAT THIS FIXES (measured 04.08). The batch was already being assembled in
prod, and assembled correctly: the journal accumulates the session's
programs, `plan_stream._slice_for` hands them out UNMERGED, `transfer.redeem()`
returns `list[list[dict]]`, the chat door runs it one at a time. But it
traveled to the SHOWROOM and the EXECUTOR — the person and Revit. It NEVER
reached the JUDGE: `design_check.check_bundle` had exactly one prod caller —
`course.design_check` inside the sandbox, i.e. only when the model itself
thought to assemble the batch by hand and ask.

WHY THIS IS NOT A MINOR MATTER. The building's unit is the BATCH, and that
is not a convenience: by Revit's law, `create_stairs` must be the sole op of
its program (KIR-L002), so a two-floor building's body CANNOT contain the
stairs, and without stairs HAB010 blocks every occupied floor above grade.
Each link on its own is unfit BY CONSTRUCTION. Judging a link while staying
silent about the batch means always telling the model the same lie.

WHERE THIS MODULE LIVES ON THE PACKAGE MAP. This is the RETURN path, like
`transfer`: it reads the journal and knows the verdict (i.e. the compiler),
so no module of the "outbound" path (`journal`, `plan_stream`, `showroom`)
may import it — otherwise the one-wayness of the stream, proven by
`test_live_plan_stream.py`, would become false through it. The one and only
importer is `kir/serving.py`, the chat door.

WHAT THIS MODULE DOES NOT DO:

* It does NOT judge at the admin door (`handle_revit_ir_bulk`). There the
  author is the rebuild materializer (measured 30.07, Snowdon Towers: 6,335
  ops, 26 programs in chunks of 250), not the model, and there is no reader
  for a receipt at all;
* It does NOT decide what "a mandatory rule" is. Its own list of rules would
  become a second judge of the same question; here only what the checker
  said is relayed;
* It does NOT raise exceptions. A building verdict is feedback, not a
  postcondition: a broken judge has no right to cost a turn in which Revit
  is already writing.

THE BATCH'S SECOND READER IS THE CLASH CHECK (`kir.clash_bundle`, flag
`KUKAI_IR_CLASH`, OFF by default). The reason it lives here and not in
`design_check`: a clash is a relation between TWO elements, and a reference
across a program boundary is illegal (`KIR-V002`) — so the two disciplines
can never end up in the same program, and a session's batch is the ONLY
place where the compiler holds links from different authors at the same
time. A finding travels into the receipt as EVIDENCE: it does not enter
`verdict`, does not land in `blocking`, and cannot refuse the turn — a false
refusal of a correct build costs more here than a missed finding. Flag off
⇒ not one new key and not one new byte in `message_ru`.

════════════════════════════════════════════════════════════════════════════
VERDICT AND CLASHES ARE TWO DIFFERENT THINGS, AND THEY ARE SEPARATED HERE (wave 10.08.2026)
════════════════════════════════════════════════════════════════════════════

THE VERDICT IS THE MODEL'S FEEDBACK. It exists to TEACH the author: it has a
reader, and that reader is the model. A rebuild has no model-author at
all (a materializer is not a model), so excluding the admin door from the
verdict STANDS AND STAYS.

CLASHES ARE A BUILDING AUDIT. A rebuild that produced mutually intersecting
geometry is broken regardless of whether it teaches anyone. "No one to read
it" is an argument about the verdict, and it does NOT carry over to clashes.

BEFORE THIS WAVE, CLASHES INHERITED THE EXCLUSION WHOLESALE, AND NOT IN ONE
WAY BUT TWO — the second was never once noticed, because it is silent:

  1. `_clash_block` was called ONLY inside `judge`, and `judge` only from the
     chat door. The one route by which whole buildings are assembled
     (`handle_revit_ir_bulk`) never saw a clash check at all;
  2. AND EVEN AT THE CHAT DOOR, clashes were silently lost on any building
     larger than the VERDICT CAP. `judge` returned via `_over_cap` BEFORE the
     line `clash = _clash_block(...)`, meaning the cap "1,200 operations / 64
     programs", chosen for the cost of `check_bundle` (~0.4 ms per
     operation), also switched off the clash check, which has its own three
     caps and its own cost. The comment one line below meanwhile asserted
     the opposite: "Clashes are counted INDEPENDENTLY of the fitness
     verdict". Measured: the Snowdon Towers rebuild — 6,335 operations, i.e.
     five times above the verdict cap; any batch of that size got "verdict
     not computed" and NOT A WORD about clashes — silence that reads as "no
     clashes".

Hence `clash_only` — AN ENTRY POINT FOR THOSE WHO NEED ONLY THE AUDIT. It
reads the same journal and the same batch, does not build a verdict at all,
and knows nothing of its caps. In `judge`, clashes are now counted BEFORE
the verdict cap and get attached to both outcomes, so "the building is too
large for a verdict" no longer means "clashes were not counted".
"""
from __future__ import annotations

import logging
import os
from typing import Any, Mapping, Sequence

from kir.live import journal as _journal
from kir import env  # noqa: E402

logger = logging.getLogger(__name__)

__all__ = (
    "BUILDING_SCHEMA",
    "clash_only",
    "enabled",
    "judge",
    "programs_seen",
)

BUILDING_SCHEMA = "kir-building-verdict/1"

_FLAG = "KIR_BUILDING_VERDICT"


def enabled() -> bool:
    """The switch. Off = behavior before this wave (no verdict)."""
    return env.get(_FLAG, "1") != "0"


def _int_env(name: str, default: int, *, low: int, high: int) -> int:
    try:
        value = int(env.get(name, "") or default)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, value))


#: CAPS, AND THEY ARE NOT ROUND NUMBERS. Measured 04.08 on the prod box, an
#: honest batch (body + stairs, rooms close, rules speak up): 22 ops — 13 ms,
#: 190 — 94 ms, 400 — 197 ms, 820 — 340 ms, 1660 — 681 ms. Linear, ~0.4 ms per
#: operation. The cap is chosen so the worst case costs ~0.5 s against a live
#: write to Revit that takes tens of seconds. An overshoot is NAMED by a
#: number, not silently dropped as the verdict: "the building is too big" and
#: "the building was not checked" are different statements, and the model
#: would read the second one as "everything is fine".
def _max_ops() -> int:
    return _int_env("KIR_BUILDING_VERDICT_OPS", 1_200, low=20, high=40_000)


def _max_programs() -> int:
    return _int_env("KIR_BUILDING_VERDICT_PROGRAMS", 64, low=2, high=512)


#: The cap on the VERDICT's text — and the name now names what is measured.
#: The channel here is not the sandbox's `stdout` (4000) but the body of the
#: tool's result, yet it is paid for out of the same model context.
#:
#: WHY IT WAS RENAMED (measured 11.08.2026). It used to be called `_TEXT_CAP`,
#: "the RECEIPT's text cap", and `_describe` cut to it — i.e. ONLY the
#: verdict half. Further down, `_with_clash` appended the clash check's text
#: into the SAME `message_ru` field, with its own cap of 2,700:
#:
#:     snowdon_plumb_v4: verdict 359 <= 2,600, clashes 2,504 <= 2,700,
#:                       the `message_ru` FIELD 2,865 — LARGER than "the receipt cap"
#:
#: In the worst case, a field named by a cap of 2,600 carries 2,600 + 2,700.
#: This is the same shape as the rest of this week's cases: a value is
#: DECLARED in one place and READ in another, and nothing forces them to
#: agree.
_VERDICT_TEXT_CAP = 2_600

#: THE BUDGET OF THE FIELD THAT CARRIES BOTH HALVES. Derived, not assigned:
#: the sum of two caps, each of which stays with its own half.
#:
#: THERE IS DELIBERATELY NO SHARED TRIM. Cutting by the sum would let one
#: half eat into the other — the verdict would crowd out findings, or the
#: reverse — and that is exactly the defect the clash receipt's budget was
#: cured of: honest text crowding out the truth. The halves are bounded
#: separately, the sum is NAMED and visible (`receipt_chars`), and its growth
#: is no longer silent.



def _clash_text_cap() -> int:
    """The second half's cap — ASKED FROM THE ONE THAT WRITES IT.

    A copy of the number here would drift apart from the original at the very
    next edit, and the field's budget would end up describing a state that
    does not exist — the very kind of defect this constant cures.
    """
    try:
        from kir import clash_bundle as _clash

        return int(_clash._TEXT_CAP)
    except Exception:  # noqa: BLE001 — the module is missing: there will be no second half
        logger.debug("clash text cap unavailable", exc_info=True)
        return 0


RECEIPT_TEXT_BUDGET = _VERDICT_TEXT_CAP + _clash_text_cap()


#: THE FLOOR OF THE BRIEF VERDICT'S BUDGET. The frame (preamble + waiver
#: block) on a building with long reasons can eat almost the whole cap;
#: without a floor the verdict would collapse into a heading, and "no
#: violations shown" would become indistinguishable from "no violations".
#: The number is ASSIGNED, not derived, and rests on the 20.08 measurement:
#: the heading, the source, the built line, and one blocking rule with an
#: example take up ~560 characters on the tower — printing less is pointless.
_BRIEF_FLOOR = 600

#: The cap on ONE silence reason in the machine field. Measured 20.08 on the
#: tower: the longest reason is 346 characters, median 184; eleven rules at
#: 240 give ~2.6 KB worst case — and this is a FIELD, not model text: it does
#: not enter `message_ru` and does not move `receipt_chars`.
_SILENT_REASON_CAP = 240

#: RESERVE FOR SOMEONE ELSE'S TRUNCATION SIGNATURE, AND IT IS NEEDED BECAUSE
#: THE TRUNCATION OVERSHOOTS ITS OWN LIMIT. `render_verdict_brief` cuts text
#: to `limit`, then APPENDS the line "… verdict truncated at N characters
#: (+M); in full — `render_verdict()`" — i.e. it returns more than it was
#: asked for. Measured 20.08 on the tower: asked for 1974, got back 2046, an
#: overshoot of 72.
#:
#: Without the reserve, the overshoot ate into the outer cap, and the outer
#: truncation cut the TAIL — and here the tail is the waiver block with its
#: reasons. So fixing one silence would eat another. The reserve is set at
#: twice the measured overshoot: the signature grows with the number of
#: digits, not with the building's size.
_CUT_SIGNATURE_RESERVE = 144


def programs_seen(key: _journal.SessionKey) -> int:
    """How many programs the journal has ASSIGNED to this session, ever.

    Computed from `next_seq`, not from the list's length: eviction shortens
    the list, and "did it grow this turn" read by length would say "no
    growth" precisely on an overflowing journal — i.e. on the largest
    building.
    """
    entry = _journal.get(key)
    return entry.next_seq if entry is not None else 0


def judge(key: _journal.SessionKey, *,
          since_seq: int | None = None) -> dict[str, Any] | None:
    """Judge EVERYTHING the session declared, as one building. Never
    raises.

    `None` means "nothing to say" (no journal, turned off, the judge
    unavailable as a module) — and this is the only case where the
    receipt stays silent. Everything else, including a refusal from the
    verdict door and exceeding the ceiling, comes back as text: silence
    reads as "everything is fine".

    `since_seq` is the TURN BOUNDARY for the collision check, and in
    chat it costs more than at the admin door, because here the receipt
    is read by the MODEL. A model that sees "45 CLASHES" where 45 already
    stood before it (measured on 11.08 during the rebuild of
    `snowdon_plumb_v4` — exactly this case) will behave in one of two
    ways, and both are harmful: either it starts fixing something it did
    not break, editing SOMEONE ELSE'S geometry, or it reports to the
    engineer that it broke the building.

    THE ADDITION IS STRICTLY ADDITIVE: `None` leaves the collision block
    exactly as it was — the `none` basis, with no `introduced` key at
    all. A zero standing in for "wasn't asked" is forbidden here just as
    it is everywhere in this tree.
    """
    try:
        entry = _journal.get(key)
        if entry is None or not entry.records:
            return None
        if not enabled():
            # THE THIRD PLACE WHERE THE CLASH CHECK INHERITED SOMEONE
            # ELSE'S SWITCH. `enabled()` reads
            # `KUKAI_KIR_BUILDING_VERDICT` — the VERDICT flag — and
            # before this fix it also switched off the collision check
            # along the way, even though that has its own flag,
            # `KUKAI_IR_CLASH`. Two switches on one wire: turning off the
            # model's feedback meant turning off the building audit too.
            #
            # With `KUKAI_IR_CLASH` off (prod's state) `_clash_block`
            # returns `None`, so `judge` returns `None` — the behavior is
            # unchanged, LETTER FOR LETTER. The difference appears in
            # exactly one configuration: verdict off, audit on.
            standing = entry.standing()
            clash = _clash_block(
                [{"ops": [dict(op) for op in record.ops]}
                 for record in standing], entry.sections,
                new_from=_new_from(standing, since_seq))
            if not clash:
                return None
            return {"schema": BUILDING_SCHEMA,
                    "programs": len(standing),
                    "ops": sum(r.op_count for r in standing),
                    "programs_evicted": entry.programs_evicted,
                    **_slice_head(entry),
                    "verdict": "",
                    "message_ru": str(clash.get("message_ru") or ""),
                    "clash": clash}
        # 🔴 WHAT IS JUDGED IS WHAT IS STANDING, NOT EVERYTHING
        # DECLARED. A program that never reached the model, or was
        # rolled back, is no longer an intent: the author no longer
        # means it, and keeping it in the batch would mean judging a
        # ghost. Before 16.08 the batch was built from ALL records — that
        # is, a rejected program took part in the building's verdict on
        # equal footing with a built one.
        standing = entry.standing()
        pack = [{"ops": [dict(op) for op in record.ops]}
                for record in standing]
        head: dict[str, Any] = {
            "schema": BUILDING_SCHEMA,
            "programs": len(pack),
            "ops": sum(record.op_count for record in standing),
            "programs_evicted": entry.programs_evicted,
            "datums_fed": _datums_fed(entry),
            **_slice_head(entry),
        }
        # Collisions are counted INDEPENDENTLY of the fitness verdict:
        # `KIR-V002` refuses the verdict when a reference crosses a
        # program boundary — but the geometry of both programs is
        # declared regardless, and staying silent about them standing in
        # the same place would be a refusal for the wrong reason.
        #
        # THIS IS COUNTED BEFORE THE VERDICT'S CEILING, and this is
        # ORDER, NOT TASTE. This line used to stand AFTER `_over_cap`,
        # meaning the word "independently" in the comment above was a lie
        # for every building larger than 1,200 operations: the ceiling,
        # chosen for `check_bundle`'s cost, also disabled the check that
        # has its OWN three ceilings. The Snowdon Towers rebuild (6,335
        # operations) got not a word about collisions — silently.
        clash = _clash_block(pack, entry.sections,
                             new_from=_new_from(standing, since_seq))
        over = _over_cap(head)
        if over is not None:
            return _with_clash({**head, "verdict": "", "message_ru": over},
                               clash)
        try:
            from kir import design_check as _verdict
        except Exception as exc:  # noqa: BLE001 — the judge module failed to load
            logger.debug("building verdict import failed", exc_info=True)
            return _with_clash({**head, "verdict": "",
                                "message_ru": f"{_preamble(head)}\nВЕРДИКТ О ЗДАНИИ "
                                              f"НЕДОСТУПЕН: {type(exc).__name__}: "
                                              f"{exc}"}, clash)
        try:
            report = _verdict.check_bundle(
                _pack_with_datums(pack, entry),
                building_id="здание этой сессии (пачка программ)")
        except _verdict.VerdictInputError as exc:
            # A NAMED refusal from the door is a signal, not a failure:
            # KIR-V002 says a reference crossed a program boundary,
            # KIR-V003 says a link is unbuildable. The AUTHOR fixes both,
            # and they must learn about it here, not on the device.
            return _with_clash({**head, "verdict": "",
                                "message_ru": f"{_preamble(head)}\n{exc.render()}"},
                               clash)
        except _verdict.DesignCheckUnavailable as exc:
            return _with_clash({**head, "verdict": "",
                                "message_ru": f"{_preamble(head)}\n"
                                              f"ВЕРДИКТ О ЗДАНИИ НЕДОСТУПЕН: "
                                              f"{exc}"}, clash)
        block = _with_clash({**head, **_describe(report, head, _verdict)}, clash)
        return _with_assembly(block, report, pack)
    except Exception:  # noqa: BLE001 — ABSOLUTE fail-open, see the header
        logger.debug("building verdict failed (fail-open)", exc_info=True)
        return None


def _with_assembly(block: dict[str, Any], report: Any,
                   pack: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Append an ASSEMBLY SUMMARY to the block — from the ALREADY
    COMPUTED verdict.

    WHY HERE, AND NOT AS A SEPARATE CALL. The judge has already been
    called on the line above, and its object exists. Calling
    `check_bundle` a second time for the summary would mean setting up
    TWO JUDGMENTS OF THE SAME THING, paying for them twice, and getting
    two answers that have nothing to guarantee they'll agree.

    WHAT IS ADDED, AND WHY TWO KEYS INSTEAD OF ONE:
      `assembly`      a structure — read by the model WITHIN THE TURN;
      `assembly_note` a flat string — the only one that SURVIVES history
                      collapsing (`chat_helpers._summarize_tool_result`
                      replaces every dict and list with "collapsed",
                      leaving scalars alone).

    Does NOT touch the block's prose (`message_ru`): that is for the
    person, the summary is for the model. A summary failure has no right
    to bring down the verdict — it is subordinate to it.
    """
    try:
        from kir import assembly_view as _av

        ops: list[Mapping[str, Any]] = []
        for entry in pack:
            ops.extend(op for op in (entry.get("ops") or ())
                       if isinstance(op, Mapping))
        walls = [str(op.get("id")) for op in ops
                 if op.get("op") == "create_wall" and op.get("id") is not None]
        # THE BATCH IS PASSED WHOLE: the second source (`preview`) reads
        # the PROGRAM, not the verdict, and without it the summary would
        # answer the same way for a healthy wall and for a duplicate —
        # measured on 15.08 with three programs.
        view = _av.observe_verdict(report, walls, programs=list(pack))
        block["assembly"] = view.to_dict()
        block["assembly_note"] = _av.digest(view)
    except Exception as exc:  # noqa: BLE001 — the summary is subordinate to the verdict
        # 🔴 SUBORDINATE DOES NOT MEAN SILENT (F-171). A summary failure
        # indeed has no right to bring down the verdict, and that
        # argument is correct; what was wrong was something else — that
        # the loss went NOWHERE. The reader saw a receipt WITHOUT
        # `assembly` and without a single word saying the summary
        # existed and failed to assemble, meaning there was nothing to
        # tell "nothing to say" apart from "could not". The channel
        # exists — the same block; there was simply nothing being put
        # into it.
        logger.debug("assembly view stamping failed", exc_info=True)
        block["assembly_note"] = (
            f"СВОДКА СБОРКИ НЕ СОБРАЛАСЬ: {type(exc).__name__}. Это НЕ «к "
            f"сборке вопросов нет» — наблюдения не строились вовсе")
    return block


def _new_from(records: Sequence[Any], since_seq: int | None) -> int | None:
    """`seq` of the turn boundary -> a POSITION in the batch, or `None` —
    no boundary was given.

    THE TRANSLATION LIVES HERE, BECAUSE ONLY HERE IS THERE A JOURNAL, and
    it is one for both doors: two translations would drift apart at the
    very first eviction. Evicting the head (`programs_evicted`) shifts
    POSITIONS and does not shift `seq`; treating the boundary as a
    position would mean declaring someone else's data as one's own,
    exactly on an overflowing journal — that is, on the largest building,
    where a mistake costs the most.

    A turn that added no program at all gives a boundary PAST the end of
    the batch: there are no new bodies, and "0 introduced" is an honest
    answer, not a consequence of a miss.

    🔴 IT TAKES THE SAME LIST THE BATCH WAS BUILT FROM, not the whole
    journal. It used to take `entry.records`, and that was correct
    exactly as long as the batch was all the records. Once cancelled ones
    started being filtered out (16.08), the positions would have drifted
    apart: every filtered-out program would shift the boundary by one,
    and "new in this turn" would silently include someone else's work.
    One list — one translation.
    """
    if since_seq is None:
        return None
    for index, record in enumerate(records, start=1):
        if getattr(record, "seq", -1) >= since_seq:
            return index
    return len(records) + 1


def clash_only(key: _journal.SessionKey, *,
               since_seq: int | None = None) -> dict[str, Any] | None:
    """AUDIT THE BUILDING WITHOUT A VERDICT. Never raises, never
    refuses.

    THE SEAM, AND WHY THIS ONE. The unit here is the SESSION JOURNAL,
    i.e. the same batch the verdict uses, and this is not a convenience
    but the only legitimate unit: a clash is a relationship BETWEEN TWO
    elements, a reference across a program boundary is illegitimate
    (`KIR-V002`), and a rebuild is cut into chunks of 250 operations
    (`compiler.MAX_BULK_OPS`) — meaning a pipe from chunk 7 and a wall
    from chunk 3 will NEVER meet within one program. Checking a chunk
    against itself is an instrument that is vacuous by construction,
    exactly like an MVP scope built on a mere declaration.

    The journal was already ready for this, and NOTHING had to change:
    the one insertion point, `plan_stream.publish`, sits in the shared
    body of both doors and marks the record `source="bulk"`, and the
    journal's ceilings (512 programs / 40,000 operations) fit an entire
    rebuild — measurement: Snowdon Towers, 6,335 operations in 26
    programs; `sob62_r23_v5`, 1,043 operations in 9.

    WHAT THIS ENTRY POINT DELIBERATELY DOES NOT DO — IT DOES NOT DECIDE
    WHEN TO CALL IT. Measurement of 10.08.2026
    (`/tmp/wiring/m_seam_cost.py`, a live rebuild of `snowdon_plumb_v4`,
    129 chunks, 31,971 operations): running against the ACCUMULATED
    batch on EVERY chunk costs 47.9 s, while a single run over the
    finished building costs 0.5 s. Ninety-four times more expensive for
    128 reports about an unfinished house that nobody reads. So "when"
    is decided by the door (`serving.py`), and this module only answers
    "what". The check has its own ceilings, and they are its own:
    `clash_bundle._max_elements`, `_max_bodies`, `_max_offers`,
    `_max_pairs`.

    `None` means EXACTLY "no flag" or "no journal". Everything else
    comes back as text: silence reads as "no collisions", and that is
    the most expensive lie there is.
    """
    try:
        entry = _journal.get(key)
        if entry is None or not entry.records:
            return None
        # 🔴 THE AUDIT IS CONDUCTED ON WHAT IS STANDING, NOT ON
        # EVERYTHING DECLARED (RT-28). This used to say `entry.records`,
        # meaning the clash batch also picked up the `refused_pre_effect`
        # program (never reached the model — nothing to change) and
        # `rolled_back` (reached it and was rolled back — no elements
        # remain). Geometry that is NOT in the model is enough to
        # generate a finding. Measurement: a box + a duct + A REPEAT OF
        # THE SAME DUCT, the repeat marked `rolled_back` —
        #
        #     BEFORE  duplicates 1, total_findings 1   ("at one spot")
        #     AFTER   duplicates 0, total_findings 0
        #     CONTROL (the same duplicate WITHOUT the rollback)
        #             duplicates 1
        #
        # The price is exactly what `judge`'s docstring names: an
        # engineer who sees a clash where there is nothing to clash about
        # either fixes someone else's intact geometry or reports that
        # they broke the building. `judge` has judged `entry.standing()`
        # since 16.08; this door did not get that fix, and the two doors
        # on one journal answered DIFFERENTLY about the same building.
        #
        # WHAT ALSO LEAVES THE BATCH WITH THIS SAME CHANGE, AND THIS IS
        # STATED, NOT LEFT UNSAID: `standing()` also removes
        # `running_unknown` and `committed_partial` — programs whose
        # outcome is NOT KNOWN. Their geometry may well be standing in
        # the model, and then a finding about it will not be seen here.
        # This fork is more honest than the old one (which lost both,
        # only silently) and belongs to `standing()` — the one
        # definition of "what the building currently has" for both
        # doors. Setting up a SECOND definition here would mean bringing
        # back the divergence between the doors that this fix exists to
        # remove.
        standing = entry.standing()
        pack = [{"ops": [dict(op) for op in record.ops]}
                for record in standing]
        # SEQ -> A POSITION IN THE BATCH, and the translation is done
        # HERE, BECAUSE ONLY HERE IS THERE A JOURNAL. Evicting the head
        # (`programs_evicted`) shifts POSITIONS and does not shift
        # `seq`; treating the boundary as a position would mean
        # declaring someone else's data as one's own, exactly on an
        # overflowing journal — that is, on the largest building, where
        # a mistake costs the most.
        #
        # A turn that added no program at all gives a boundary PAST the
        # end of the batch: then there are no new bodies, and "0
        # introduced" is an honest answer, not a consequence of a miss.
        # 🔴 `entry.records`, NOT `entry` — AND THIS WAS A SILENT BREAK
        # (17.08). On 16.08 `_new_from` started accepting THE SAME LIST
        # THE BATCH WAS BUILT FROM (its docstring states exactly this),
        # and two callers in `judge()` were switched over, but this one
        # was not. It was passing in the journal object, `enumerate`
        # raised `TypeError: 'SessionJournal' object is not iterable`,
        # and the ABSOLUTE fail-open below swallowed the exception and
        # returned `None`.
        #
        # The price is exactly in the fail-open: `None` at this entry
        # point means "no flag or no journal", and the admin door read
        # it as "no collisions found". Exactly the silence that
        # `clash_only`'s docstring calls the most expensive lie there
        # is — and it was silent about the ENTIRE bulk rebuild, the only
        # route by which whole buildings get assembled. Caught by a red
        # `test_clash_wiring` that nobody was reading.
        # 🔴 THE SAME LIST THE BATCH WAS BUILT FROM — this is
        # `_new_from`'s law, and the 17.08 fix (a list, NOT the journal
        # object) is held up by that same law: `standing` is a list,
        # `enumerate` takes it. Passing `entry.records` here, while the
        # batch is built from `standing`, would mean once again letting
        # the translation and the batch drift apart — exactly the defect
        # `_new_from`'s own docstring declares against.
        return _clash_block(pack, entry.sections,
                            new_from=_new_from(standing, since_seq))
    except Exception:  # noqa: BLE001 — ABSOLUTE fail-open, see the header
        logger.debug("clash-only failed (fail-open)", exc_info=True)
        return None


def _clash_block(pack: list[dict[str, Any]],
                 sections: Any = None,
                 new_from: int | None = None) -> dict[str, Any] | None:
    """The collision check — or `None` when there is none.

    `None` means EXACTLY "no flag": `bundle_clash_report` itself does
    not stay silent about any other outcome (exceeding the ceiling and an
    internal failure both come back as text). The wrapper is needed for
    the case the module does not cover at all — it failed to load as a
    module; and then that too is stated in words.

    `sections` is this session's TYPE geometry, captured by ground from
    the live model (`journal.remember_sections`). Without it, bodies are
    built only from the program's own numbers, and "no body" reads as
    "nobody knows the thickness"; with it, a slab and a column HAVE a
    body. `None` (ground did not answer) and `{}` (it answered, the
    types have no sections) are different facts, and here too they are
    different values.
    """
    try:
        from kir import clash_bundle as _clash

        return _clash.bundle_clash_report(pack, snapshot=sections,
                                          new_from=new_from)
    except Exception as exc:  # noqa: BLE001 — a check cannot cost the turn
        logger.debug("bundle clash import failed", exc_info=True)
        return {"schema": "kir-bundle-clash/1", "status": "unavailable",
                "message_ru": f"ПРОВЕРКА НА КОЛЛИЗИИ НЕДОСТУПНА: "
                              f"{type(exc).__name__}: {exc}"}


#: STRUCTURAL DETAILS OF INDIVIDUAL FINDINGS — what gets stripped when
#: the author introduced not a single clash. The clash prose is NOT
#: TOUCHED (see `_без_чужих_находок`).
_CLASH_PER_FINDING_KEYS = ("findings", "rules", "rung_actions")


def _без_чужих_находок(clash: dict[str, Any] | None) -> dict[str, Any] | None:
    """Strip the STRUCTURAL details of someone else's collisions. Leave
    the numbers and the prose alone.

    🔴 THE MEASUREMENT THAT BOUGHT THIS FIX (27.08.2026, a live build on
    AVT3_KR_MBPB). The model built 7 elements in an isolated zone and
    got back:

        building                 17,861 characters
          clash                  14,357   80.4 %
             of which findings    7,780   five findings at ~1,550 each
          the verdict itself        627    3.5 %

    And right next to it, in the same block: `introduced: 0`,
    `by_origin: {"both_prior": 423}`. For ALL 423 clashes, both sides
    were already standing in the model BEFORE this turn. The author had
    introduced not a single one — and got eight kilobytes of structural
    description of someone else's pairs.

    The argument was written in this file's header before I got here: a
    model that sees someone else's clashes either fixes something it did
    not break, or reports that it broke the building. The `introduced`
    count was set up on 11.08 for exactly this — it was being read, and
    nothing was being decided from it.

    🔴 THE FIRST VERSION OF THIS FUNCTION ALSO REPLACED THE PROSE, AND
    THAT WAS WRONG. Two tests in `test_clash_in_the_receipt` turned red
    and showed why: a clash text of 2,520 characters is NOT a retelling
    of the findings. There is exactly one retelling in it, taking up a
    fifth; the rest is HONESTY ABOUT COVERAGE:

        NO BODY (NOT SEEN): 3964 — … Skipped BY CONSTRUCTION, not by a
        threshold
        WALL JOINTS OUTSIDE THE CHECK: … the program does not express it
        NOMINAL ONLY: 82 — the capsule built from a nominal has no body
        DOES NOT SEE WHAT IS STANDING: only what the session declared
        was compared
        OUTSIDE THE CHECK, AND THIS CAN HIDE A COLLISION:
        author_family ×4, …

    This is "did not look ≠ no violations" — and it applies to the
    AUTHOR's own geometry too. Erasing it to save space would mean
    buying size at the price of truth. The prose stays word for word; one
    line about what was stripped is APPENDED to it.

    THREE OUTCOMES, AND THEY ARE DIFFERENT:

        the `introduced` key is ABSENT   the delta was not computed — we
                                          DO NOT KNOW whose findings these
                                          are. "Don't know" is not the
                                          same as "not yours"
        introduced == 0                  the details are stripped, the
                                          numbers and prose stay intact
        introduced > 0                   the whole block: what the
                                          author broke, they must see

    AND NOTHING IS DONE WHEN THERE ARE NO FINDINGS AT ALL
    (`total_findings == 0`): there is nothing to strip, and in that case
    the text carries something else — "not a single body", "nominal
    only". This is exactly where the first version turned red.
    """
    if not isinstance(clash, dict) or "introduced" not in clash:
        return clash
    try:
        внесено = int(clash.get("introduced") or 0)
        всего = int(clash.get("total_findings") or 0)
    except (TypeError, ValueError):
        return clash
    if внесено or всего <= 0:
        return clash
    снято = [k for k in _CLASH_PER_FINDING_KEYS if clash.get(k)]
    if not снято:
        return clash
    урезанный = {k: v for k, v in clash.items() if k not in снято}
    урезанный["findings_withheld"] = снято
    проза = str(clash.get("message_ru") or "").rstrip()
    приписка = (
        "ПОДРОБНОСТИ ЧУЖИХ СПОРОВ СНЯТЫ НАМЕРЕННО: внесено этой пачкой 0 из "
        "%d, значит чинить по ним нечего, а список чужих пар читается как «ты "
        "сломал здание». Числа и границы проверки выше целы; снято: %s."
        % (всего, ", ".join("`%s`" % k for k in снято)))
    урезанный["message_ru"] = (проза + "\n" + приписка) if проза else приписка
    return урезанный

def _with_clash(block: dict[str, Any],
                clash: dict[str, Any] | None) -> dict[str, Any]:
    """Attach the findings to the receipt and NAME THE FIELD'S SIZE —
    always.

    THE ABSENT STAYS ABSENT as far as FINDINGS go: with the flag off,
    there is no `clash` key and not a single new byte in the text.

    But `receipt_chars` travels with the flag in either position, and
    this is a fix (13.08.2026). It used to sit inside the "there is a
    clash" branch, so the instrument answered in only one of the two
    configurations — an instrument covering part of the range, which for
    us is more dangerous than an absent one: a reader who finds no key
    cannot tell "the field is empty" from "there was nobody to measure
    it".

    THIS IS THE ACTUAL RATIONALE, AND NOT THE ONE THAT SUGGESTS ITSELF.
    What suggests itself is "otherwise the size grows silently with the
    clash check off" — that is wrong, and is checked right on the spot:
    the verdict half is bounded by `_VERDICT_TEXT_CAP` and is trimmed
    WITH THE TRIM ANNOUNCED in the text itself (see further down the
    file). Nothing grows silently. The argument is not about lack of
    control, it is about COVERAGE: the field `message_ru` is present in
    EVERY receipt, so a number about it must be present in every one too.

    WHAT THIS COSTS THE STABILITY CHECK. The key set did not drift:
    `set(enabled) - set(disabled)` is still exactly `{"clash"}`. But the
    field-by-field comparison must exclude `receipt_chars` — in exactly
    the same place it excludes `message_ru`, and for the same reason:
    this is a FUNCTION of the text, and the text is appended to on
    purpose. Comparing a derived value while excluding the original
    would mean checking the same thing twice under a different name.
    """
    out = dict(block)
    # SOMEONE ELSE'S FINDINGS ARE STRIPPED HERE — in the single funnel
    # through which the clash reaches the receipt. See
    # `_без_чужих_находок`.
    clash = _без_чужих_находок(clash)
    if clash:
        out["clash"] = clash
        text = str(clash.get("message_ru") or "")
        if text:
            out["message_ru"] = (
                f"{block.get('message_ru') or ''}\n\n{text}".strip())
    # THE SUM — AS A NUMBER, AND IN THE ANSWER ITSELF. The field carries
    # TWO halves with two ceilings, and before this wave nobody knew its
    # own size: both halves checked themselves, but nobody checked the
    # FIELD. A quantity nobody watches grows silently — the same argument
    # as for `text_budget`.
    out["receipt_chars"] = len(str(out.get("message_ru") or ""))
    return out


def _pack_with_datums(pack: list[dict[str, Any]], entry: Any) -> list[dict[str, Any]]:
    """The session's datums — as a SEPARATE FIRST PROGRAM of the batch.

    🔴 WITHOUT THEM THE BATCH JUDGE IS BLIND TO ROOMS, AND BLIND
    SILENTLY. Measurement on the owner's live Revit, 03.09.2026, an
    apartment built from the "housing" recipe (23 elements, five rooms
    with real Revit ids `room1..room5`):

        batch as-is                  0 of 20 rules · blocking HAB000
                                      «model has no rooms — empty or
                                      failed extraction»
        batch + session datums       11 of 20 rules · nothing blocking

    The reason is exactly the same as for `built_verdict.datum_ops`
    (measurement of 17.08): `spatial_model_from_program` resolves a
    level selector ONLY against a `create_level` from THE SAME program.
    The apartment's level was created by a PAST TURN — so it is not in
    the batch, the room gets thrown out as "level outside the document",
    and all twenty housing rules stay silent. And "not evaluated" reads
    as "found nothing wrong": the same false zero, only on the feedback
    about the BUILDING.

    WHY A SEPARATE PROGRAM, NOT MIXED INTO EACH ONE. Checked by
    execution: a datum mixed into every program fixes nothing and breaks
    nothing, but the batch carries the law "a reference lives INSIDE the
    program" (`BundleContractError`), and putting someone else's
    operations into someone else's program would mean fighting that law
    by its shape. A separate datum program creates no references and
    accepts none. A REPEAT IS TOLERATED — measured: the same datum, both
    as a separate program and inside a neighboring one, gives the same
    rule count, so there is nothing to filter duplicates with and no
    reason to.

    The batch's head (`programs`, `ops`, `by_stage`), the clash check,
    and the assembly are all counted from the ORIGINAL batch: a datum is
    an input to the JUDGE, not a program of the author's, and it has no
    place in the building's bookkeeping.
    """
    датумы = [dict(op) for op in (getattr(entry, "datums", None) or ())]
    if not датумы:
        return pack
    return [{"ops": датумы}, *pack]


def _datums_fed(entry: Any) -> int:
    """How many session datums were fed to the judge. THE NUMBER IS
    VISIBLE IN THE RECEIPT.

    A quantity nobody watches silently becomes zero: this is exactly how
    the blindness to rooms survived until 03.09 — "0 of 20 rules" was
    indistinguishable from "the judge had nothing to be given".
    """
    return len(getattr(entry, "datums", None) or ())


def _slice_head(entry: Any) -> dict[str, Any]:
    """What the batch is built from — in numbers, not adverbs.

    Three quantities, and they are DIFFERENT; they cannot be folded into
    one "programs":
      `by_stage` — the journal's census by stage (zero is not printed);
      `built`    — how many programs are provably STANDING in the model;
      `dropped`  — how many were filtered out as cancelled (refused
                   before the write, rolled back).
    """
    census = entry.stage_census()
    built = len(entry.built())
    standing = len(entry.standing())
    return {
        "judged_slice": "standing",
        "by_stage": census,
        "built": built,
        "dropped_from_pack": len(entry.records) - standing,
    }


def _built_line(head: dict[str, Any]) -> str:
    """The line about what is BUILT. Always written, zero included.

    🔴 THE ZERO IS PRINTED HERE, and this does not contradict the rule
    "a zero of a quantity the instrument does not count is not a
    result": the quantity IS COUNTED, the instrument sees it, and its
    zero is a real fact, not the absence of a measurement. Silence,
    however, would have read as "built", because the word VERDICT stands
    all around it.

    The 16.08 measurement this line exists for: through the product's
    chat door, over 24 hours nothing was written to live Revit at all,
    while the journal was full — meaning "BUILDING VERDICT: FIT" was
    reachable over a building that does not exist.
    """
    built = int(head.get("built") or 0)
    dropped = int(head.get("dropped_from_pack") or 0)
    if built <= 0:
        line = ("🔴 ПОСТРОЕНО В REVIT: НИ ОДНОЙ ПРОГРАММЫ. Судится ЗАМЫСЕЛ, "
                "а не модель: сказанное ниже относится к тому, что программы "
                "ЗАЯВИЛИ, и ничего не утверждает о содержимом документа")
    else:
        line = (f"ПОСТРОЕНО В REVIT: {built} из {head['programs']} программ "
                f"пачки (остальные заявлены и ещё не подтверждены записью)")
    if dropped:
        # 🔴 "REFUSED OR ROLLED BACK" IS WRONG FOR A WHOLE THIRD OF WHAT
        # IS FILTERED OUT (F-167, measurement of 04.09.2026: in the live
        # census, `running_unknown` accounted for 95 of 117). The
        # journal says exactly the OPPOSITE about this stage, in its own
        # words: "there is NO evidence. Not 'not built', but 'we don't
        # know'", and a retry is forbidden for it for precisely the
        # reason that the write could have gone through. Folding it into
        # one line together with a pre-write refusal means declaring
        # something built to be non-existent — and this is exactly how
        # the judge was plausibly auditing a SMALLER building.
        #
        # ONLY THE NAME changes here, not the batch's composition:
        # whether to judge the unknown is a decision about the law, not
        # about a line, and it cannot be made silently.
        перепись = head.get("by_stage") or {}
        неизвестно = int(перепись.get("running_unknown") or 0)
        отсеяно_отказом = dropped - неизвестно
        куски = []
        if отсеяно_отказом > 0:
            куски.append(f"{отсеяно_отказом} — отказ до записи либо откат, "
                         f"замыслом они больше не являются")
        if неизвестно:
            куски.append(f"{неизвестно} — ИСХОД НЕИЗВЕСТЕН: улики нет, запись "
                         f"могла пройти, и повтор им запрещён. Это НЕ отказ; "
                         f"судится здание БЕЗ них")
        line += f"\nОТСЕЯНО ИЗ ПАЧКИ: {dropped} · " + " · ".join(куски)
    return line


def _preamble(head: dict[str, Any]) -> str:
    """THE DENOMINATOR BEFORE THE ASSERTION. A verdict read before what
    it is about is an assessment of nobody-knows-what; the first line
    always states WHAT was judged."""
    whole = ("то, что журнал ещё помнит" if head["programs_evicted"]
             else "всё, что эта сессия объявила")
    line = (f"ЗДАНИЕ ЦЕЛИКОМ (не эта одна программа): пачка из "
            f"{head['programs']} программ, {head['ops']} операций — {whole}, "
            f"судится как ОДНО здание")
    if head["programs_evicted"]:
        line += (f"\nВНИМАНИЕ: {head['programs_evicted']} самых ранних программ "
                 f"вытеснено из журнала — судится ХВОСТ здания, а не всё")
    return line + "\n" + _built_line(head)


def _over_cap(head: dict[str, Any]) -> str | None:
    if head["programs"] <= _max_programs() and head["ops"] <= _max_ops():
        return None
    return (f"{_preamble(head)}\nВЕРДИКТ О ЗДАНИИ НЕ СЧИТАЛСЯ: пачка больше "
            f"потолка хода ({_max_programs()} программ / {_max_ops()} "
            f"операций). Это НЕ «нарушений нет» — это «не смотрели». Спроси "
            f"вердикт сам по интересующей части: "
            f"`design_check([программа1, программа2, …])` в скрипте.")


def _silent_rules(report: Any) -> list[dict[str, str]]:
    """RULES THAT STAYED SILENT NOT BECAUSE OF A WAIVER — BY NAME AND
    WITH A REASON, IN A FIELD.

    🔴 WHY A FIELD, WHEN THIS IS ALREADY IN THE PROSE. It is in the
    prose, and it is LOST there exactly — measured on 20.08.2026 on the
    `13A-RD-AR-K2_v33` tower (2,442 rooms, 15,323 walls,
    `KUKAI_CHECKER_V2=1`):

        the full brief verdict            2230 characters
        `_describe` asked for             1600  ← a literal
        trimmed                           to 1602, 628 lost

    What was lost here was NOT the findings: the `lines` list in
    `render_verdict_brief` places the "NOT EVALUATED" block LAST, and the
    trim cuts the tail. That is, **the louder a building violates the
    rules, the more completely the account of what we did not look at
    disappears** — even though the judge module's own docstring demands
    that silence be printed LOUDER than findings. On the tower, only the
    list of eleven codes survived; the REASONS for the five rules that
    stayed silent for reasons other than a waiver — and their reason is
    exactly the address for the fix ("no input stair_landings_complete",
    "stairs present but none has measured geometry") — did not arrive by
    a single letter.

    The prose is trimmable BY CONSTRUCTION, the field is not. So the
    silence moves into the machine half of the receipt and stops
    depending on how much room the findings ate up. This does not
    replace the prose: there it is for the person, here it is so it
    cannot be lost.

    THINGS WAIVED BY THE PROFILE DO NOT END UP HERE: they have their own
    field (`rules_suspended`) and their own block with reasons
    (`_waiver_block`), and mixing them in would mean losing the
    difference between "the rule does not apply to this stage" and "the
    rule was missing an input, and here is which one". Nothing can fix
    the first, the second is an address for work.
    """
    coverage = getattr(report.report, "coverage", None)
    if coverage is None:
        return []
    suspended = set(report.rules_suspended or ())
    out: list[dict[str, str]] = []
    for outcome in getattr(coverage, "outcomes", ()) or ():
        if outcome.status.value == "evaluated" or outcome.rule_id in suspended:
            continue
        out.append({
            "rule_id": outcome.rule_id,
            # The reason must EXIST, not be implied: a rule that stayed
            # silent with no reason is indistinguishable from a rule
            # that was forgotten and never called.
            "reason": str(outcome.reason or "ПРИЧИНА НЕ НАЗВАНА")[:_SILENT_REASON_CAP],
        })
    return sorted(out, key=lambda row: row["rule_id"])


def _describe(report: Any, head: dict[str, Any], module: Any) -> dict[str, Any]:
    """Verdict -> receipt fields. Machine numbers, human text."""
    coverage = report.report.coverage
    suspended = list(report.rules_suspended)
    blocking = sorted({v.rule_id for v in report.report.blocking})
    verdict = report.verdict
    # 🔴 THE BUDGET IS DERIVED, NOT ASSIGNED. This used to hold the
    # literal `1_600`, while the half's own ceiling,
    # `_VERDICT_TEXT_CAP = 2_600`, was declared four hundred lines above
    # — with a docstring saying exactly that a quantity declared in one
    # place and read in another is our named defect. The price is
    # measured (see `_silent_rules`): on the tower the verdict was
    # trimmed to 1602 out of a full 2230, meaning 628 characters were
    # thrown away while 998 characters of budget went unused by ANYONE.
    # The frame (the preamble and the waiver block) is asked about
    # itself, not estimated by eye.
    frame = len(_preamble(head)) + sum(
        len(line) + 1 for line in _waiver_block(report, module))
    brief_budget = max(_BRIEF_FLOOR,
                       _VERDICT_TEXT_CAP - frame - 1 - _CUT_SIGNATURE_RESERVE)
    text = "\n".join(
        [_preamble(head), module.render_verdict_brief(report, limit=brief_budget)]
        + _waiver_block(report, module))
    if len(text) > _VERDICT_TEXT_CAP:
        text = (text[:_VERDICT_TEXT_CAP].rsplit("\n", 1)[0]
                + f"\n… обрезано на {_VERDICT_TEXT_CAP} символах")
    return {
        "verdict": (verdict.value if verdict is not None else ""),
        "rules_evaluated": report.rules_applied,
        "rules_total": report.rules_total,
        "rules_suspended": suspended,
        "rules_silent": _silent_rules(report),
        "blocking": blocking,
        "message_ru": text,
    }


def _waiver_block(report: Any, module: Any) -> list[str]:
    """A PASS via a waiver must read DIFFERENTLY from a PASS via
    satisfaction.

    THE MEASUREMENT this block exists for. One building, differing ONLY
    in the name of the room by the stairs: «Лестничная клетка» -> PASS,
    13 of 20 rules, HAB001 (second exit) and HAB010 (floor connectivity)
    EVALUATED; «Кладовая» -> PASS, 11 of 20, the same two rules WAIVED by
    the profile and never spoken of at all. Both lines, read naively:
    "PASS, 0 blocking".

    The checker itself does not catch this difference, and is not
    required to: a rule waived by the profile leaves via `continue`
    BEFORE being counted in `mandatory_not_evaluated`
    (`engine.run_checker`), and the list of mandatory-not-evaluated is
    EMPTY above in BOTH cases. The brief verdict names the waived rules,
    but sends the reason off to "see the full verdict", and the model
    never gets the full one: the channel is narrow.

    So here, exactly what is missing gets printed — the REASON for the
    waiver next to the names of the waived rules. The reason is taken
    from the profile, not made up: it is the very line that is the fix
    for the next turn («связность строится только через помещение с
    функцией ЛЕСТНИЦА»).

    THE TWO KINDS OF WAIVER ARE KEPT APART, AND KEPT APART
    STRUCTURALLY, NOT BY THE TEXT OF THE REASON. `DESIGN_STAGE.suspended`
    are waivers of THE STAGE ITSELF: they hold for any building (opening
    area is not expressed by the type, a wall has no "load-bearing"
    flag, the apartment oracle is measurably imprecise). Their reasons
    never change and take up ~1100 characters; printing them on EVERY
    writing turn means paying context for news that isn't any — and a
    warning that is always there is a warning the model stops reading
    after two turns. The other waivers are added by
    `design_stage_profile`, BY THIS WITNESS'S OWN MEASUREMENT, and those
    are the actual news and the address for the fix. The set
    subtraction here is not a heuristic: both sides are taken from the
    verdict itself, and no second rule for "what is constant here" gets
    set up.
    """
    profile = report.profile
    if profile is None or not report.rules_suspended:
        return []
    try:
        stage = set(module.DESIGN_STAGE.suspended)
    except Exception:  # noqa: BLE001 — the stage need not be the same
        stage = set()
    constant = [r for r in report.rules_suspended if r in stage]
    specific = [r for r in report.rules_suspended if r not in stage]
    lines = [f"СНЯТО, А НЕ ПРОЙДЕНО — правила, которые не высказывались вовсе "
             f"({len(report.rules_suspended)} из {report.rules_total}):"]
    grouped: dict[str, list[str]] = {}
    for rule_id in specific:
        try:
            reason = str(profile.suspension_reason(rule_id) or "")
        except Exception:  # noqa: BLE001 — the profile need not know every code
            reason = ""
        grouped.setdefault(reason, []).append(rule_id)
    for reason, rule_ids in grouped.items():
        lines.append(f"  ЭТИМ ЗДАНИЕМ {'/'.join(sorted(rule_ids))}: "
                     + (reason[:360] if reason else "причина не названа профилем"))
    if constant:
        lines.append(f"  СТАДИЕЙ (стоят при любом замысле, чинить нечем): "
                     f"{', '.join(sorted(constant))}")
    word = report.verdict.value if report.verdict is not None else ""
    if word == "pass":
        lines.append(
            f"ПРИГОДЕН здесь значит РОВНО «среди {report.rules_applied} "
            f"высказавшихся правил нарушений нет». Про остальные "
            f"{report.rules_total - report.rules_applied} не сказано НИЧЕГО — "
            f"снятое правило это не пройденное правило.")
    return lines
