"""PULL REQUEST FOR THE BUILDING: propose a change WITHOUT APPLYING it.

WHAT WAS MISSING, AND IT IS NOT MACHINERY. The machinery is all built and
measured::

    merkle   DAG ×1.18…×9.96 smaller than the tree
    journal  replays EXACTLY: 18/18, 5/5, 3/3, 2/2 revisions across four chains
    rebuild  ×6.05 / ×9 / ×2.2 programs against a full rebuild, ×174 ops on a 6-op edit
    merge3   ALL THREE verdicts on six real triples
    merge_guard  the only wire carrying merge3 outward, default policy — REFUSAL

What was missing was DISPLAY: `/admin/kir/rebuild`, given a fresh decompile,
calls the guard and — if it lets it through — BUILDS. There was nowhere to
look at the decision without building anything. The pull request is exactly
that pause: the decision is shown, the document is untouched.

🔴 THREE VERDICTS ARE THREE DECISIONS, NOT "OK / ERROR". The difference
between the second and the first carries weight, and the product must SHOW
it, not average it away::

    precondition_confirmed  the fresh decompile EQUALS the base. The delta's
                            precondition is VERIFIED — a promise became a
                            measurement
    diverged_clean          the document moved on, but there is no conflict.
                            The precondition is NOT confirmed: the delta will
                            land on top of ANOTHER building, and that is said
                            out loud
    diverged_conflicting    both sides edited the same thing. This is a
                            DECISION ("here is what conflicts"), not an
                            instrument failure

Silently conflating the second with the first is exactly the
silently-wrong outcome the whole package stands against: "the delta is valid
only if the document already carries the base building" — the one named hole
in live rebuilding.

WHAT THIS LAYER DOES NOT DO, AND THIS TRAVELS IN THE RESPONSE AS A FIELD, NOT
LIVING IN THE DOCSTRING. A pull request that does not name its own silences is
just another diff, and there are plenty of those. The list is closed
(`NOT_CHECKED`), and every line is a boundary that cannot be crossed here:

* **exactly where** — `merge3`'s state is a MULTISET of canonical ops; a
  canonical op has neither identifiers nor references. Hence "three operators
  of such-and-such kind conflict", not "this particular wall conflicts".
  Addressability is dropped INTENTIONALLY: the offline proof of T-APPLY rests
  on it;
* **buildings are not merged** — what still gets built is the delta A→B. The
  guard answers one question: is it safe to build it. "We will merge the
  edits" would sound nicer and would be a lie;
* **demolition is not carried out** — the delta NAMES the elements to remove
  and does not remove them (`retire_not_executed`): no map "base sheet →
  ElementId of the built copy" exists;
* **the document is not asked** — all three sides are DECOMPILES ON DISK. If
  the "fresh" decompile is stale, the verdict goes stale with it; freshness
  is a property of whoever took it, and there is nothing to check it against
  offline;
* **whether the proposed building is fit for purpose is judged SEPARATELY** —
  that is code compliance (`viewer.normcontrol`), and it is the one that names
  which rules lacked input. The guard says "safe to build", not "will make a
  good building".
"""
from __future__ import annotations

import json
import logging
import pathlib
from typing import Any

logger = logging.getLogger(__name__)

__all__ = ("DELTA_TREE_MB_CEILING", "NOT_CHECKED", "PROPOSAL_SCHEMA",
           "ProposalUnavailable", "VERDICT_RU", "proposal")

PROPOSAL_SCHEMA = "kir-building-pull-request/1"

#: THE CAP ON THE PREDICTED DELTA SIZE, IN MEGABYTES OF THE COLLAPSED TREE.
#:
#: "How much work is this" — the first thing the pull request lacked, and it
#: cannot be attached unconditionally. Measured 20.08.2026,
#: `delta_rebuild_plan` on real pairs (this box, python 3.12.13)::
#:
#:     tree 1.4 MB   plan  1.39 s   leaves B   1 457, delta     10
#:     tree 5.6 MB   plan  5.64 s   leaves B   5 218, delta  2 726
#:     tree 5.7 MB   plan  5.08 s   leaves B   5 585, delta    369
#:     tree 89 MB    plan 96.75 s   leaves B 115 880, delta 25 125, peak RSS 811 MB
#:
#: The slope is roughly ONE SECOND PER MEGABYTE of tree, and the tail runs
#: past the budget of any turn: 96.75 s against 14–18 s for a whole live turn.
#: The threshold is ASSIGNED, not derived (four points are not a law), and
#: sits at about 8 s of the budget.
#:
#: The measure is FILE SIZE, because it is free (`stat`), while the number of
#: leaves is known only AFTER the plan, that is, after the price is already
#: paid. The predictor is coarse and named coarse; it decides "compute or
#: refuse", not report a value.
DELTA_TREE_MB_CEILING = 8.0


#: A CLOSED list of what this layer does NOT check. Closed means a new
#: boundary is added DELIBERATELY, not implied; and it travels in the
#: response, because silence left in the docstring is not reachable by the
#: reader of the response.
NOT_CHECKED: tuple[tuple[str, str], ...] = (
    ("где_именно",
     "состояние сравнивается МУЛЬТИМНОЖЕСТВОМ канонических опов — у них нет "
     "ни идентификаторов, ни ссылок. Спор называется РОДОМ и числом, а не "
     "элементом; адресность снята намеренно, на ней стоит офлайновое "
     "доказательство переносимости"),
    ("здания_не_сливаются",
     "построится дельта база→цель, а не слияние. Страж отвечает «безопасно "
     "ли строить», и только"),
    ("снос_не_исполняется",
     "дельта НАЗЫВАЕТ элементы к удалению и не удаляет: карты «лист базы → "
     "ElementId построенной копии» не существует (retire_not_executed)"),
    ("свежесть_разбора",
     "все три стороны — разборы НА ДИСКЕ. Устарел «свежий» разбор — устарел "
     "и вердикт; офлайн это не проверяется ничем"),
    ("пригодность_результата",
     "это нормоконтроль (/api/viewer/normcontrol), отдельный вопрос и "
     "отдельная цена. Здесь не сказано ничего о том, годно ли предложенное "
     "здание для жизни"),
)

#: A human-readable reading of the verdict. The key is the guard's word, the
#: value is the DECISION that follows from it. Without the second half,
#: `diverged_clean` reads as "everything is fine", when it means "the
#: precondition is NOT confirmed".
VERDICT_RU: dict[str, str] = {
    "precondition_confirmed":
        "УСЛОВИЕ ПРОВЕРЕНО: свежий разбор равен базе — дельта встанет ровно "
        "на то здание, от которого её считали. Это ЗАМЕР, а не обещание",
    "diverged_clean":
        "УСЛОВИЕ НЕ ПОДТВЕРЖДЕНО, спора нет: документ уехал от базы, но "
        "правки не спорят с дельтой. Строить можно — и знать, что дельта "
        "ляжет поверх ДРУГОГО здания, чем то, от которого её считали",
    "diverged_conflicting":
        "СПОР: обе стороны правили одно и то же, и дельта сотрёт чужую "
        "работу. Это решение, а не сбой — ниже названо, что именно спорит",
}


class ProposalUnavailable(RuntimeError):
    """The proposal is NOT ASSEMBLED, and the reason is named.

    A separate type, not an empty report: "0 conflicts" and "there was
    nothing to compare" are different facts, and the second wearing the
    first's costume reads as permission to build.
    """


def _tree(root: pathlib.Path, name: str) -> Any:
    """A decompile tree looked up by name. The refusal NAMES what is nearby.

    The list of neighbors in the refusal is not a courtesy: the decompile's
    name comes from a human, and "no such thing" without "but here are these"
    forces a guess.
    """
    # 🔴 `tree.json` GETS COMPRESSED (21.08.2026). Both the file itself and
    # THE LIST OF NEIGHBORS must know about `.gz`: a list built with a bare
    # `glob("*/tree.json")` would print «рядом есть (0)» on a compressed
    # corpus — a refusal that teaches the human there are no decompiles at
    # all.
    from kir.decompile.snapshot_io import (
        read_snapshot_text, snapshot_file_exists)
    path = root / name / "tree.json"
    if not snapshot_file_exists(path):
        known = sorted({p.parent.name for p in root.glob("*/tree.json")}
                       | {p.parent.name for p in root.glob("*/tree.json.gz")})
        raise ProposalUnavailable(
            f"у разбора {name!r} нет свёрнутого дерева ({path}). Это не "
            f"«изменений нет»: сравнивать было нечего. Рядом есть "
            f"({len(known)}): " + ", ".join(known[:10])
            + (" …" if len(known) > 10 else ""))
    try:
        return json.loads(read_snapshot_text(path, encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ProposalUnavailable(
            f"{path}: дерево не читается как JSON: {exc}") from None


def _tree_mb(root: pathlib.Path, name: str) -> float:
    # `snapshot_raw_size` — the size of the RAW bytes, even for a compressed
    # one. A bare `stat` on `.gz` throws, and an `inf` ("infinite amount of
    # work") would come from the cleaner, not from the building.
    from kir.decompile.snapshot_io import snapshot_raw_size
    size = snapshot_raw_size(root / name / "tree.json")
    return size / 1_048_576 if size else float("inf")


def _delta_size(root: pathlib.Path, base: str, target: str) -> dict[str, Any]:
    """HOW MUCH WORK THIS IS — or else a NAMED ABSENCE IN PLACE OF A NUMBER.

    There can be no made-up number here: either the plan is computed in full,
    or it is said WHY it was not computed and HOW to get it. An empty field
    would read as "no work at all", and that is the worst of the untruths
    available here — a proposal that looks cheap.
    """
    heavy = {name: round(_tree_mb(root, name), 1)
             for name in (base, target)
             if _tree_mb(root, name) > DELTA_TREE_MB_CEILING}
    if heavy:
        return {
            "known": False,
            "reason": (
                "прогноз НЕ СЧИТАН: дерево крупнее потолка %.0f МБ (%s). "
                "Замер 20.08: план стоит примерно секунду на мегабайт, и на "
                "башне это 96.75 с при живом ходе 14–18 с — счёт не влезает в "
                "ход. Это НЕ «работы нет»: величина не вычислялась. Взять её "
                "можно офлайн: tools/kir_rebuild.py %s %s"
                % (DELTA_TREE_MB_CEILING,
                   ", ".join("%s %.1f МБ" % (k, v) for k, v in sorted(heavy.items())),
                   base, target)),
        }
    from kir.decompile.rebuild_plan import delta_rebuild_plan, plan_report

    try:
        report = plan_report(delta_rebuild_plan(
            _tree(root, base), _tree(root, target),
            label_a=base, label_b=target))
    except ProposalUnavailable:
        raise
    except Exception as exc:  # noqa: BLE001 — the plan fails LOUDLY and that is data
        return {
            "known": False,
            "reason": ("прогноз НЕ СЧИТАН: план дельты отказал — %s: %s. Отказ "
                       "здесь дешевле, чем построить в модели половину здания"
                       % (type(exc).__name__, str(exc)[:160])),
        }
    return {
        "known": True,
        "full_leaves": report["full_leaves"],
        "delta_leaves": report["delta_leaves"],
        "delta_named": report["delta_named"],
        "delta_ref_closure": report["delta_ref_closure"],
        # 🔴 DEMOLITION IS NAMED AND NOT CARRIED OUT — the same boundary as in
        # NOT_CHECKED, and here it travels as A NUMBER: this many elements the
        # delta will mark for removal and NOT remove.
        "retire_named_not_executed": report["retire_leaves"],
        "identical": report["identical"],
    }


def proposal(base: str, current: str, target: str, *,
             root: pathlib.Path) -> dict[str, Any]:
    """A proposal to build `target` on top of the document that is currently
    `current`.

    BUILDS NOTHING AND TOUCHES NOTHING — reads three trees from disk and
    calls the prod guard. There is not a single judgment of its own about
    merging here: a second judge of the same question would diverge from the
    first on the very first edit.
    """
    from kir.decompile.merge_guard import guard_report

    report = guard_report(
        _tree(root, base), _tree(root, current), _tree(root, target),
        base_label=base, current_label=current, target_label=target)

    if not report.get("ok"):
        error = report.get("error") or {}
        raise ProposalUnavailable(
            f"страж слияния отказал: {error.get('type')}: "
            f"{error.get('message')}")

    verdict = str(report.get("verdict") or "")
    out: dict[str, Any] = {
        "schema": PROPOSAL_SCHEMA,
        "base": base,
        "current": current,
        "target": target,
        "verdict": verdict,
        # 🔴 A REFUSAL IS A FIRST-CLASS OUTCOME, NOT AN ERROR. The field
        # answers the question "will this land silently", and "no" here is a
        # normal answer from the product, one nobody apologizes for.
        "lands_silently": verdict != "diverged_conflicting",
        # AND THE DIFFERENCE BETWEEN A PROMISE AND A MEASUREMENT — AS A
        # SEPARATE FIELD, so that `diverged_clean` cannot pass for
        # `precondition_confirmed`.
        "precondition_verified": verdict == "precondition_confirmed",
        "decision_ru": VERDICT_RU.get(
            verdict, f"вердикт {verdict!r} не имеет чтения — это дефект НАШЕЙ "
                     f"стороны, а не свойство здания"),
        "conflicts_total": report.get("conflicts_total", 0),
        "conflicts_by_kind": report.get("conflicts_by_kind") or {},
        "conflicts": report.get("conflicts") or [],
        "conflicts_shown": report.get("conflicts_shown", 0),
        "auto_merged": report.get("auto_merged", 0),
        "identical_to_base": bool(report.get("identical_to_base")),
        "message_ru": report.get("message_ru", ""),
        # WHAT WAS NOT CHECKED — RIGHT NEXT TO WHAT WAS CHECKED, AND AS A
        # FIELD.
        "not_checked": [{"what": what, "why": why} for what, why in NOT_CHECKED],
    }
    # HOW MUCH WORK THIS IS — next to "is it safe", not instead of it.
    out["delta_size"] = _delta_size(root, base, target)
    return out
