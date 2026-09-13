# -*- coding: utf-8 -*-
"""The public door to a saved building: read an element, propose an edit, apply it.

🔴 WHAT THIS MODULE ADDS, AND WHAT IT DOES NOT. It is NOT a second agentic runtime, nor
a second database: editing goes through the same `capture_edit.edit_element`/`save`, a field's
state is taken from the FOREIGN `field_ledger` ledger, the `before` binding is checked by the
same law (`capture_edit._before_values` + `_canon`) that checks it when
a saved journal is replayed. Exactly three things are added here that the
seam did not have:

* `read_element` — the element's HOST and DEPENDENCIES, and the STATE of each field per
  the ledger (`represented | approximate | source_data | unknown`), rather than by
  its own formula "the name occurs in the node's text";
* `propose_patch` — admissibility, an ACTUAL diff, and unresolved questions WITHOUT
  a single record: neither in the in-memory capture, nor on disk (the guard is a byte-for-byte
  snapshot of the directory before and after, `test_a_public_door_reads_and_refuses.py`);
* `apply_patch` — the same edit, but with a `before` check and a BINDING TO THE SOURCE:
  an edit journal taken from ANOTHER capture is refused by name, rather than being applied to
  a foreign building by address coincidence.

🔴 ADAPTATION TO `ProjectRevision`/`ChangeProposal` IS DESCRIBED, NOT BUILT.
The existing contracts express it as follows:

    kir.project_merge.ChangeProposal(base, candidate, scope, author, reason)
        base/candidate — two `ProjectRevision` values of ONE `project_id`, where
        `candidate.parent_revision == base.revision_id`;
    kir.project_merge.ProposalScope(instances=…, modules=…, project_fields=…)
        — a write grant issued by the RECEIVING side, not a proposal to oneself;
    kir.project_merge.merge_proposal(proposal, current, authorized_scope=…)
        — a clean three-way merge with no store;
    kir.project_merge.accept_proposal(store, proposal, expected_revision=…,
                                      authorized_scope=…) — a CAS append into
        `ProjectStore` with an ancestor check.

That is, `apply_patch` here is exactly `candidate` without a store: `before`
plays the role of `base`, `source_binding` plays the role of `project_id` and a proven ancestor
(see `source_binding`), and `diff` plays the role of the merge report. What capture DOES NOT HAVE, and what
would have to be set up: `ProjectRevision` requires `project_id`/`revision_id`/
`parent_revision`, while capture's identity is `lineage` + `source_version`, and
it keeps no linear revision history at all. So the new ProjectStore seam
is PROPOSED HERE IN PROSE (a shift report), not written: writing it without having
a `revision_id` would mean setting up a second, parallel database — exactly what the mandate
forbids.
"""
from __future__ import annotations

import argparse
import copy
import dataclasses
import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Mapping

from kir.decompile import capture_edit as _CE
from kir.decompile.capture_edit import Capture, CaptureEditError, open_capture, save

__all__ = ["API_SCHEMA", "Applied", "ElementRead", "FieldState", "Link",
           "OpeningRing", "Proposal",
           "apply_patch", "capture_ledger", "main", "propose_patch", "read_element",
           "source_binding", "write_demo_capture"]

API_SCHEMA = "kir-capture-api/1"

#: What `source_binding` names. The list is CLOSED: a binding to which an arbitrary
#: field could be added would stop being a binding.
#:
#: 🔴 `capture_revision` WAS ADDED ON 07.09.2026 BY MEASUREMENT. The four earlier fields
#: answer the question "will the SAME THING come up" — they include exactly what
#: the lifter reads. The lifter does not read the document's revision at all, and swapping
#: `revision.proof.json` (`bench_A` -> `k4_geom_wave2`, with L0 and the sidecars byte-for-byte
#: the same) went through silently: a patch taken from ONE revision of the house landed on ANOTHER,
#: and `source_binding` did not name this. The fifth field answers a different question —
#: WHAT the thing we are editing was captured FROM.
#:
#: A patch WITHOUT this field is still accepted: `_binding_refusal` checks
#: only the named fields, and the old binding is read with its own, smaller
#: guarantee — the same way an old edit row is read in `capture_edit`.
_BINDING_FIELDS = ("lineage", "source_sha256", "source_version", "profiles",
                   "capture_revision")

#: What this contract can CHANGE on an element of this category. A single source —
#: the seam's own closed lists: a second dictionary about the same thing would drift apart from it.
#: 🔴 `OST_SWallRectOpening` WAS ADDED ON 08.09.2026. An opening in a wall is not "yet another
#: opening category" but a DIFFERENT thing: a separate element with its own op,
#: `create_opening(variety="wall_rect")`, whose size and position are given by two
#: opposite corners. So its field list is also its own, from the same
#: single source — the seam's own closed lists.
_EDITABLE = {"OST_Doors": _CE._DOOR_FIELDS,
             "OST_Floors": _CE._OPENING_FIELDS,
             "OST_Ceilings": _CE._OPENING_FIELDS,
             "OST_SWallRectOpening": _CE._WALL_OPENING_FIELDS}


# ── response types ────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class FieldState:
    """One L0 field and ITS STATE PER THE LEDGER, not by our own formula."""

    field: str
    value: Any
    state: str
    why: str | None = None
    carrier: str | None = None
    in_op_contract: bool | None = None
    recovered_from: str | None = None

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)


@dataclass(frozen=True)
class Link:
    """The element's relation to a neighbor. `via` names BY WHAT it is proven."""

    relation: str
    element_id: str
    category: str | None
    type_name: str | None
    via: str

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)


@dataclass(frozen=True)
class OpeningRing:
    """One opening of the element: the number and the ring — OR a reason why they are absent.

    🔴 THERE IS NO EMPTY LIST HERE, AND THIS IS A DECISION. An empty `openings` would read
    as "there are no openings", and that is THREE different facts: the element came up as an atom,
    the op came up but there are no rings in the profile, the element is not a profile carrier at all.
    A reader who does not distinguish them goes to fix the wrong thing. So when
    rings are absent, the list carries EXACTLY ONE record with `why` and empty
    `index`/`contour_mm`.
    """

    index: int | None
    contour_mm: list | None
    why: str | None = None

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)


@dataclass(frozen=True)
class ElementRead:
    element_id: str
    unique_id: str | None
    category: str | None
    type_name: str | None
    level_name: str | None
    node_kind: str | None
    op_name: str | None
    #: L0 fields whose ledger state is `represented`. This is exactly the "complete,
    #: SUPPORTED values": the rest are named in `fields` by their own state.
    supported: dict
    #: The parameters of the op the element became. Empty for an atom.
    op_params: dict
    host: Link | None
    depends_on: tuple
    referenced_by: tuple
    fields: tuple
    editable_fields: tuple
    #: The CURRENT values of exactly those fields that `editable_fields` names.
    #:
    #: 🔴 SET UP ON 08.09.2026 AT THE DOOR READER'S REQUEST. `supported` answers
    #: a different question — which L0 ROW fields are represented — and the door's `offset_mm`
    #: is not among them at all: it lives in the node's `op_params`. A reader who needed
    #: to show "what is there now" would have to assemble the projection itself, that is, set up
    #: A SECOND law about the value under edit.
    #:
    #: Computed by THE SAME `capture_edit._before_values` that an edit uses to take
    #: its own `before` and that an applied patch is checked against. One law for three
    #: questions ("what is there now", "what did the edit expect", "is that what's there") —
    #: meaning there is nowhere for them to drift apart.
    editable_now: dict
    #: The element's openings: rings OR a reason why they are absent. Computed by the same
    #: `capture_edit._holes_of` + `_points_of` that the edit itself uses to read them:
    #: the node's shape DIFFERS between buildings (`params.holes` versus `params.contour.holes`),
    #: and a second lookup over the node would be testing our knowledge of the shape, not the fact.
    openings: tuple
    #: What computed the fields' state. `field_ledger` is a foreign ledger.
    field_states_from: str = "kir.decompile.field_ledger"

    def to_dict(self) -> dict:
        return {"schema": API_SCHEMA, "element_id": self.element_id,
                "unique_id": self.unique_id, "category": self.category,
                "type_name": self.type_name, "level_name": self.level_name,
                "node_kind": self.node_kind, "op_name": self.op_name,
                "supported": dict(self.supported), "op_params": dict(self.op_params),
                "host": None if self.host is None else self.host.to_dict(),
                "depends_on": [item.to_dict() for item in self.depends_on],
                "referenced_by": [item.to_dict() for item in self.referenced_by],
                "fields": [item.to_dict() for item in self.fields],
                "editable_fields": list(self.editable_fields),
                "editable_now": dict(self.editable_now),
                "openings": [item.to_dict() for item in self.openings],
                "field_states_from": self.field_states_from}


@dataclass(frozen=True)
class Proposal:
    """A preview. `wrote_nothing` is not a promise but a property: there is nothing to write."""

    element_id: str
    admissible: bool
    refusal: dict | None
    diff: tuple
    notes: tuple
    open_questions: tuple
    before: dict
    wrote_nothing: bool = True

    def to_dict(self) -> dict:
        return {"schema": API_SCHEMA, "element_id": self.element_id,
                "admissible": self.admissible, "refusal": self.refusal,
                "diff": [dict(item) for item in self.diff], "notes": list(self.notes),
                "open_questions": list(self.open_questions), "before": dict(self.before),
                "wrote_nothing": self.wrote_nothing}


@dataclass(frozen=True)
class Applied:
    element_id: str
    refusal: dict | None
    changed_ops: tuple
    untouched_count: int
    notes: tuple
    diff: tuple
    edits: int

    def to_dict(self) -> dict:
        return {"schema": API_SCHEMA, "element_id": self.element_id,
                "refusal": self.refusal, "changed_ops": list(self.changed_ops),
                "untouched_count": self.untouched_count, "notes": list(self.notes),
                "diff": [dict(item) for item in self.diff], "edits": self.edits}


# ── binding to the source ───────────────────────────────────────────────────
def source_binding(capture: Capture) -> dict:
    """What binds the edit to THIS building. The same fields `save` fixes in place.

    🔴 WITHOUT IT THE ADDRESS IS A COINCIDENCE. Numeric `element_id` values coincide across two
    buildings by construction, and a patch taken from a foreign capture would apply silently. Here
    exactly the four fields `capture_meta.json` already writes are named:
    identity (`lineage`), the snapshot (`source_sha256`), the WHOLE source together with
    the side indexes (`source_version`), the reading profile (`profiles`), and the DOCUMENT
    REVISION the capture was taken from (`capture_revision`).
    """
    return {"schema": API_SCHEMA,
            **{name: getattr(capture, name) for name in _BINDING_FIELDS}}


def _binding_refusal(capture: Capture, binding: Mapping | None) -> dict | None:
    if binding is None:
        return None
    if not isinstance(binding, Mapping):
        return {"code": "bad_source_binding",
                "detail": f"привязка обязана быть объектом, получено {type(binding).__name__}",
                "address": str(capture.path)}
    mine = source_binding(capture)
    differ = sorted(name for name in _BINDING_FIELDS
                    if name in binding and binding[name] != mine[name])
    if not differ:
        return None
    return {"code": "patch_binds_to_another_capture",
            "detail": (f"патч привязан к другому исходнику: разошлись {differ}; "
                       f"у патча { {name: binding[name] for name in differ} }, "
                       f"здесь { {name: mine[name] for name in differ} }"),
            "address": str(capture.path)}


# ── reading ─────────────────────────────────────────────────────────────────
def _ledger_row(capture: Capture, element):
    """A ledger row FOR ONE element, computed by a foreign law.

    ALL nodes are supplied: `field_ledger` resolves registry references by the node's `_id`, and
    a trimmed node list would give a DIFFERENT verdict about the same field. Verified
    by the guard `test_a_public_door_reads_and_refuses.py`: a row from here must
    match the ledger row built over the whole capture.
    """
    from kir.decompile.field_ledger import field_ledger

    ledger = field_ledger(SimpleNamespace(elements=[element]), capture.nodes)
    return ledger.rows[0] if ledger.rows else None


def _refs_in(node: Mapping) -> list:
    """Where a node refers to: `{"ref": "<node's _id>"}` in its parameters, with the address."""
    found: list = []

    def walk(value, path):
        if isinstance(value, Mapping):
            target = value.get("ref")
            if isinstance(target, str):
                found.append((target, path))
            for name, item in value.items():
                walk(item, f"{path}.{name}" if path else str(name))
        elif isinstance(value, (list, tuple)):
            for index, item in enumerate(value):
                walk(item, f"{path}[{index}]")

    walk(node.get("params") or {}, "params")
    return found


def _link(capture: Capture, element_id, relation: str, via: str) -> Link:
    element = capture.elements.get(str(element_id))
    return Link(relation=relation, element_id=str(element_id),
                category=getattr(element, "category", None),
                type_name=getattr(element, "type_name", None), via=via)


#: Categories whose profile CAN carry opening rings. The same list
#: `capture_edit.edit_element` uses to allow a ring edit: a second list
#: about the same thing would drift apart from it.
_RING_HOSTS = ("OST_Floors", "OST_Ceilings")


def _openings_of(capture: Capture, element, node) -> tuple:
    """The element's opening rings — BY THE SEAM'S LAW, not by our own lookup over the node.

    🔴 OUR OWN LOOKUP HERE WOULD BE A SECOND LAW, AND IT WOULD ALREADY BE LYING. The node's shape
    DIFFERS between buildings: for `bench_A`, `k4_geom_wave2`, and `len_ar_me_r24_v1` the rings
    lie in `params.holes`, for `k2v33_join2` — in `params.contour.holes`
    (the 07.09.2026 measurement, `test_one_rule_holds_on_four_different_buildings`).
    A reader that looked for rings itself would be testing its own knowledge of the shape.
    So `capture_edit._holes_of` and `_points_of` are called — the same ones by which
    `_edit_opening` reads and edits a ring.
    """
    category = getattr(element, "category", None)
    key = str(getattr(element, "element_id", "") or "")
    if category not in _RING_HOSTS:
        return (OpeningRing(index=None, contour_mm=None, why=(
            f"{category}: кольца отверстий несёт профиль перекрытия или "
            f"потолка ({', '.join(_RING_HOSTS)}); у этой категории профиля с "
            f"кольцами нет")),)
    if (node or {}).get("kind") != "op":
        reason = ((node or {}).get("reason") or {}).get("code")
        return (OpeningRing(index=None, contour_mm=None, why=(
            f"{key} поднят атомом ({reason or 'причина не названа'}): "
            f"операции с профилем нет, читать кольца не в чем")),)
    holes, path = _CE._holes_of(node)
    if not holes:
        return (OpeningRing(index=None, contour_mm=None, why=(
            f"{key} поднят опом {node.get('op_name')!r}, но колец в его "
            f"профиле нет: отверстий у этого элемента не захвачено")),)
    out = []
    for index, hole in enumerate(holes):
        points = _CE._points_of(hole)
        out.append(OpeningRing(
            index=index,
            contour_mm=None if points is None else copy.deepcopy(points),
            why=None if points is not None else (
                f"отверстие {index} ({path}) задано не кольцом точек "
                f"({type(hole).__name__}) — прочитать контур нечем")))
    return tuple(out)


def _editable_now(capture: Capture, element, editable_fields: tuple) -> dict:
    """The CURRENT values of the editable fields — by the `_before_values` law.

    🔴 WHY VIA `_before_values`, AND NOT A PROJECTION OF `op_params`. The edit field's name
    and the node parameter's name do NOT ALWAYS match: for a door, `offset_mm` truly is
    `params.offset_mm`, while for a wall opening the field `opening_p0_mm` lies in
    `params.p0_mm`, and for a floor opening `opening_contour_mm` is in fact a ring
    inside `params.holes[i]`. A projection by name coincidence would give the door
    the truth, and the other two — emptiness, silently.

    `_before_values` is the very law by which an edit takes its `before` and
    by which `apply_patch` checks "is that what's there". One law, three questions.
    """
    key = str(getattr(element, "element_id", "") or "")
    probe = dict.fromkeys(editable_fields)
    if "opening_index" in probe:
        # Zero is not invention but the CONTRACT'S OWN DEFAULT: `_edit_opening`
        # reads `change.get("opening_index", 0)`, meaning a patch without a number
        # edits precisely the zeroth ring. What must be shown is what the edit will touch.
        probe["opening_index"] = 0
    return dict(_CE._before_values(capture, key, probe))


def read_element(capture: Capture, addr) -> ElementRead:
    """The whole element: supported values, host, dependencies, field states.

    A field's state is NOT computed here: it is taken from `field_ledger`
    (`represented | approximate | source_data | unknown`). A formula of our own would give
    a second answer to the same question — exactly what the earlier counting law was lying about,
    in six cases out of eight (see the `field_ledger` header).
    """
    key = str(addr)
    element = capture.elements.get(key)
    if element is None:
        raise CaptureEditError("unknown_element", f"{key}: в этом capture его нет", key)
    node = capture.by_source.get(key)
    row = _ledger_row(capture, element)
    states: list = []
    supported: dict = {}
    if row is not None:
        for name in row.kept:
            supported[name] = getattr(element, name, None)
            states.append(FieldState(field=name, value=supported[name],
                                     state="represented"))
        for lost in row.lost:
            states.append(FieldState(field=lost.field,
                                     value=getattr(element, lost.field, None),
                                     state=lost.state, why=lost.why, carrier=lost.carrier,
                                     in_op_contract=lost.in_op_contract,
                                     recovered_from=lost.recovered_from))
    states.sort(key=lambda item: item.field)

    host_id = str(getattr(element, "host_id", "") or "")
    host = _link(capture, host_id, "hosted_by", "L0.host_id") if host_id else None
    depends_on: list = []
    if host is not None:
        depends_on.append(host)
    node_id = str((node or {}).get("_id") or "")
    by_node_id = {str(item.get("_id")): item for item in capture.nodes if item.get("_id")}
    for target, path in _refs_in(node or {}):
        other = by_node_id.get(target)
        source = None if other is None else other.get("source_element_id")
        if source is None:
            continue
        if host is not None and str(source) == host.element_id:
            continue
        depends_on.append(_link(capture, source, "references", f"L1.{path}"))
    referenced_by: list = []
    for other in capture.nodes:
        source = other.get("source_element_id")
        if source is None or str(source) == key or not node_id:
            continue
        for target, path in _refs_in(other):
            if target == node_id:
                referenced_by.append(_link(capture, source, "referenced_by",
                                           f"L1.{source}.{path}"))
    for other in capture.document.elements:
        if str(getattr(other, "host_id", "") or "") == key:
            referenced_by.append(_link(capture, other.element_id, "hosts", "L0.host_id"))
    referenced_by.sort(key=lambda item: (item.element_id, item.relation))

    editable_fields = tuple(_EDITABLE.get(element.category or "", ()))
    return ElementRead(
        element_id=key, unique_id=getattr(element, "unique_id", None),
        category=element.category, type_name=getattr(element, "type_name", None),
        level_name=getattr(element, "level_name", None),
        node_kind=(node or {}).get("kind"), op_name=(node or {}).get("op_name"),
        supported=supported, op_params=dict((node or {}).get("params") or {}),
        host=host, depends_on=tuple(depends_on), referenced_by=tuple(referenced_by),
        fields=tuple(states),
        editable_fields=editable_fields,
        editable_now=_editable_now(capture, element, editable_fields),
        openings=_openings_of(capture, element, node))


def capture_ledger(capture: Capture, *, limit: int = 20) -> dict:
    """The ledger of the WHOLE capture: four states as NUMBERS and losses as ADDRESSES.

    🔴 WHY IT WAS SET UP (07.09.2026), AND THIS IS A MEASUREMENT, NOT A CONVENIENCE. Before this day the
    ledger as a whole had no public door at all: `read` answered about ONE
    element, and `capture_edit.losses()` about the whole capture, but WITHOUT state,
    only with the reason's kind. That is, a person the instructions promise four
    states to could get them only per element — 4 223 calls for `bench_A`,
    and not a single number for the building.

    🔴 THERE IS NO SECOND COUNTING LAW HERE. The numbers are counted by `field_ledger` — the same and
    only law by which `read_element` and `losses()` count them. Here there is
    only a SUMMARY and addresses: a formula of our own would give a second answer about one thing
    (this is exactly what the earlier "by substring" count was lying about, see the `field_ledger` header).

    🔴 THE NUMBER IS A PROPERTY OF THE READING PROFILE, AND THE ANSWER NAMES THIS. The measurement on `bench_A`
    on 07.09.2026: `represented` = 26 330 (`profiles="none"`), 26 282 (`editable` —
    `open_capture`'s default), 26 272 (`all`). The more sketch index is
    supplied to the lifter, the FEWER represented fields: the index makes nodes richer,
    and some fields lose their named carrier. So `profiles` travels
    in the response next to the numbers — a ledger without the reading profile is incomplete.

    `limit` trims only the LIST of rows, not the sums: `rows_total` names
    how many there are in total, and `truncated` — how many were not printed.
    """
    from kir.decompile.field_ledger import STATES, field_ledger

    ledger = field_ledger(capture.document, capture.nodes)
    totals = ledger.totals
    lost_rows = ledger.lost_rows()
    ordered = sorted(lost_rows, key=lambda row: (-len(row.lost), str(row.element_id)))
    shown = ordered if limit is None or limit < 0 else ordered[:limit]
    rows = [{"element_id": row.element_id, "unique_id": row.unique_id,
             "category": row.category, "op_name": row.op_name,
             "node_kind": row.node_kind, "kept": len(row.kept),
             "lost": [{"field": item.field, "state": item.state, "why": item.why,
                       "carrier": item.carrier} for item in row.lost]}
            for row in shown]
    return {"schema": API_SCHEMA, "path": str(capture.path),
            "lineage": capture.lineage, "profiles": capture.profiles,
            "source_version": capture.source_version,
            "states": list(STATES),
            "elements": totals["elements"],
            "nonempty": totals["nonempty"],
            "lost": totals["lost"],
            "by_state": dict(totals["by_state"]),
            "by_why": dict(totals["by_why"]),
            "unclassified": totals["unclassified"],
            "addressed": ledger.addressed,
            "rows_total": len(lost_rows),
            "truncated": len(lost_rows) - len(rows),
            "rows": rows,
            "reading_mode_note": (
                "числа — свойство режима чтения `profiles`: ведомость считается "
                "по УЗЛАМ, поднятым этим режимом, и другой режим даёт другое "
                "число о том же здании")}


# ── preview and edit ──────────────────────────────────────────────────────
def _preview_clone(capture: Capture) -> Capture:
    """A copy safe to make mistakes on. The nodes are deep copies, the document is shared.

    `edit_element` writes ONLY to the nodes and to `capture.edits` (verified by reading
    every branch of the seam: `params.update`, `holes[index] = …`, `capture.edits.append`),
    so the document can be shared. `by_source` is not rebuilt by a second
    law — it is carried over BY THE NODE'S PLACE: two laws about one mapping
    would drift apart wherever an element has two nodes.
    """
    nodes = copy.deepcopy(capture.nodes)
    positions = {id(node): index for index, node in enumerate(capture.nodes)}
    by_source = {key: nodes[positions[id(node)]]
                 for key, node in capture.by_source.items() if id(node) in positions}
    return dataclasses.replace(capture, nodes=nodes, by_source=by_source,
                               edits=list(capture.edits), catalog=dict(capture.catalog),
                               export_refusals=list(capture.export_refusals))


def _leaves(value, path: str, out: dict) -> None:
    if isinstance(value, Mapping):
        for name, item in value.items():
            _leaves(item, f"{path}.{name}" if path else str(name), out)
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _leaves(item, f"{path}[{index}]", out)
    else:
        out[path] = value


def _diff(before: Mapping | None, after: Mapping | None) -> tuple:
    """The node's ACTUAL diff, by leaf. An empty diff on an accepted edit is a lie."""
    left, right = {}, {}
    _leaves(before or {}, "", left)
    _leaves(after or {}, "", right)
    rows = []
    for path in sorted(set(left) | set(right)):
        if path not in left or path not in right or left[path] != right[path]:
            rows.append({"path": path, "before": left.get(path), "after": right.get(path)})
    return tuple(rows)


def _before_refusal(capture: Capture, key: str, patch: Mapping,
                    before: Mapping | None) -> dict | None:
    """A check of the expected prior value — by THE SAME law as the journal's."""
    if not before:
        return None
    if not isinstance(before, Mapping):
        return {"code": "bad_before_value",
                "detail": f"before обязан быть объектом, получено {type(before).__name__}",
                "address": key}
    current = _CE._before_values(capture, key, patch)
    differ = sorted(name for name in before
                    if _CE._canon(current.get(name)) != _CE._canon(before[name]))
    if not differ:
        return None
    return {"code": "edit_before_value_mismatch",
            "detail": (f"патч ожидал по адресу {key} "
                       f"{ {name: before[name] for name in differ} }, а там лежит "
                       f"{ {name: current.get(name) for name in differ} }: значение "
                       f"под правкой уехало"),
            "address": key}


def _open_questions(capture: Capture, key: str, patch: Mapping) -> tuple:
    """What this edit does NOT resolve: fields the language here cannot express."""
    element = capture.elements.get(key)
    if element is None:
        return ()
    questions = []
    row = _ledger_row(capture, element)
    if row is not None:
        for lost in row.lost:
            questions.append(f"{lost.field}: {lost.state} ({lost.why}) — "
                             f"правкой этого контракта не выражается")
    if not _EDITABLE.get(element.category or "", ()):
        questions.append(f"{element.category}: контракт правит только "
                         f"{sorted(_EDITABLE)} — остальное отказ по имени")
    return tuple(sorted(questions))


def propose_patch(capture: Capture, addr, patch: Mapping[str, Any], *,
                  before: Mapping | None = None,
                  source_binding: Mapping | None = None) -> Proposal:
    """Admissibility, a diff PREVIEW, and unresolved questions. WRITES NOTHING.

    Neither to the in-memory capture, nor to disk: the edit is replayed on a deep copy
    of the nodes (`_preview_clone`), and no row is added to `capture.edits`. The guard
    takes a byte-for-byte snapshot of the capture directory before and after.
    """
    key = str(addr)
    change = patch if isinstance(patch, Mapping) else {}
    refusal = _binding_refusal(capture, source_binding)
    if refusal is None:
        refusal = _before_refusal(capture, key, change, before)
    expected = dict(_CE._before_values(capture, key, change))
    if refusal is not None:
        return Proposal(element_id=key, admissible=False, refusal=refusal, diff=(),
                        notes=(), open_questions=_open_questions(capture, key, change),
                        before=expected)
    clone = _preview_clone(capture)
    was = copy.deepcopy(clone.by_source.get(key))
    result = _CE.edit_element(clone, key, patch)
    now = clone.by_source.get(key)
    return Proposal(element_id=key, admissible=result.refusal is None,
                    refusal=result.refusal,
                    diff=() if result.refusal is not None else _diff(was, now),
                    notes=tuple(result.notes),
                    open_questions=_open_questions(capture, key, change),
                    before=expected)


def apply_patch(capture: Capture, addr, patch: Mapping[str, Any], *,
                before: Mapping | None = None,
                source_binding: Mapping | None = None) -> Applied:
    """An edit of the REAL capture — via `edit_element`, with a `before` check.

    A refusal here is RETURNED AS A CODE, not thrown as a codeless exception: the caller
    needs to tell "the binding is foreign" apart from "the value drifted" apart from "the wrong field",
    and it could not do that with `except` branches.
    """
    key = str(addr)
    change = patch if isinstance(patch, Mapping) else {}
    refusal = _binding_refusal(capture, source_binding)
    if refusal is None:
        refusal = _before_refusal(capture, key, change, before)
    if refusal is not None:
        return Applied(element_id=key, refusal=refusal, changed_ops=(),
                       untouched_count=0, notes=(), diff=(), edits=len(capture.edits))
    was = copy.deepcopy(capture.by_source.get(key))
    result = _CE.edit_element(capture, key, patch)
    now = capture.by_source.get(key)
    return Applied(element_id=key, refusal=result.refusal,
                   changed_ops=tuple(result.changed_ops),
                   untouched_count=result.untouched_count, notes=tuple(result.notes),
                   diff=() if result.refusal is not None else _diff(was, now),
                   edits=len(capture.edits))


# ── synthetic building for the instructions and the guards ─────────────────
#: A level of the demonstration building. One wall, two doors in it, one
#: floor with an opening — exactly what this contract can edit.
_DEMO_LEVEL = {"id": "500", "name": "Этаж 1", "elevation_mm": 0.0}
DEMO_WALL, DEMO_DOOR, DEMO_DOOR_2, DEMO_FLOOR = "1001", "1002", "1004", "1003"
#: An opening in the demo building's wall. Written ONLY on an explicit request
#: (`write_demo_capture(..., wall_opening=True)`): without it the demo remains
#: byte-for-byte the same four-element building the instructions, the scenario
#: guard, and acceptance stand on.
DEMO_WALL_OPENING = "1005"


def _demo_row(**overrides) -> dict:
    row = {"bbox_max_mm": None, "bbox_min_mm": None, "category": None,
           "category_ru": None, "curve_kind": None, "design_option": None,
           "element_id": None, "geom_kind": "bbox_only", "host_id": None,
           "host_source": None, "level_id": _DEMO_LEVEL["id"],
           "level_name": _DEMO_LEVEL["name"], "p0_mm": None, "p1_mm": None,
           "params": {}, "phase_created": {"id": "600", "name": "Стадия 1"},
           "rotation_deg": None, "type_id": None, "type_name": None,
           "unique_id": None, "workset": None}
    row.update(overrides)
    return row


def write_demo_capture(directory, *, wall_opening: bool = False) -> Path:
    """A synthetic capture: a four-element building, WITHOUT KUKAI or Revit.

    🔴 THIS IS A FIXTURE, NOT A MEASUREMENT. It exists precisely so that the
    instructions' commands (`docs/CAPTURE_OFFLINE_EDIT_RU.md`) run on a machine that has
    no parse corpus — and so that the scenario guard runs the REAL loop
    (open → read → edit → save → new process → export), not a
    stub. Corpus numbers are not derived from it and cannot be.

    🔴 `wall_opening=True` (08.09.2026) APPENDS A FIFTH ELEMENT — AN OPENING IN
    THE WALL, AND THIS IS AN EXTENSION, NOT A CHANGE OF FIXTURE. The default is `False`, in which case
    the snapshot is byte-for-byte the same as before: the instructions' commands, the scenario
    guard, and acceptance stand on the demo, and moving it silently would mean moving their subject.

    WHY A SYNTHETIC OPENING WAS NEEDED — A MEASUREMENT, NOT A CONVENIENCE. The
    08.09.2026 corpus census: openings in walls occur in 3 runs out of 93 (`mnvnk_k1_layers`
    120, `k4_geom_wave2` 51, `bench_A` 12 — 183 elements), and NOT ONE of the 183
    comes up as an op. A scan of all 1508 corpus files: occurrences of `opening_is_rect`
    and `opening_boundary_mm` — ZERO. The reason is named by date: the boundary reader
    (`extract._opening_boundary_reader_cs`) was set up on 04.09.2026, and the corpus was taken in
    August. That is, there is not a single "supported wall opening" in the corpus, and
    there is nothing to check the contract's positive path AGAINST THE CORPUS with.

    So a row of exactly the shape THAT SAME reader writes is built here:
    `opening_is_rect` (from `Opening.IsRectBoundary`) and
    `opening_boundary_mm` — TWO corners (`Opening.BoundaryRect`, documented as
    a pair). This is a fixture of FORM, not a measurement of a building, and it is not a corpus
    number. The negative path — 183 real openings across three real buildings —
    is checked on corpus slices, not here.
    """
    from kir.decompile.extract import EXTRACT_CATEGORIES

    target = Path(directory)
    target.mkdir(parents=True, exist_ok=True)
    header = {"record": "header", "schema_version": "1.0", "document": {
        "change_stamp": "capture-api-demo", "doc_name": "Демо-здание", "grids": [],
        "levels": [_DEMO_LEVEL], "revit_version": "2026", "rooms": [], "units": "mm",
        "project_info": {"address": None, "building_type_hint": None, "name": "Демо"}}}
    wall = _demo_row(category="OST_Walls", category_ru="Стены", element_id=DEMO_WALL,
                     geom_kind="curve", curve_kind="line",
                     p0_mm=[0.0, 0.0, 0.0], p1_mm=[12000.0, 0.0, 0.0],
                     bbox_min_mm=[0.0, -100.0, 0.0], bbox_max_mm=[12000.0, 100.0, 3000.0],
                     params={"WALL_ATTR_WIDTH_PARAM": 200, "WALL_USER_HEIGHT_PARAM": 3000},
                     type_id="1740", type_name="Типовой - 200мм",
                     unique_id="00000000-0000-0000-0000-000000000001-00000001")
    floor = _demo_row(category="OST_Floors", category_ru="Перекрытия",
                      element_id=DEMO_FLOOR, bbox_min_mm=[0.0, 0.0, -225.0],
                      bbox_max_mm=[12000.0, 8000.0, 0.0],
                      params={"FLOOR_HEIGHTABOVELEVEL_PARAM": 0}, type_id="3001",
                      type_name="Монолитный бетон 225мм",
                      unique_id="00000000-0000-0000-0000-000000000001-00000003")
    doors = [
        _demo_row(category="OST_Doors", category_ru="Двери", element_id=DEMO_DOOR,
                  geom_kind="point", p0_mm=[3000.0, 0.0, 0.0], rotation_deg=90.0,
                  bbox_min_mm=[2542.0, -100.0, 0.0], bbox_max_mm=[3458.0, 100.0, 2134.0],
                  host_id=DEMO_WALL, host_source="family_instance",
                  params={"FAMILY_HEIGHT_PARAM": 2134.0, "FAMILY_WIDTH_PARAM": 915.0,
                          "INSTANCE_SILL_HEIGHT_PARAM": 0},
                  type_id="2001", type_name="0915 x 2134 мм",
                  unique_id="00000000-0000-0000-0000-000000000001-00000002"),
        _demo_row(category="OST_Doors", category_ru="Двери", element_id=DEMO_DOOR_2,
                  geom_kind="point", p0_mm=[9000.0, 0.0, 0.0], rotation_deg=90.0,
                  bbox_min_mm=[8542.0, -100.0, 0.0], bbox_max_mm=[9458.0, 100.0, 2134.0],
                  host_id=DEMO_WALL, host_source="family_instance",
                  params={"FAMILY_HEIGHT_PARAM": 2134.0, "FAMILY_WIDTH_PARAM": 915.0,
                          "INSTANCE_SILL_HEIGHT_PARAM": 0},
                  type_id="2001", type_name="0915 x 2134 мм",
                  unique_id="00000000-0000-0000-0000-000000000001-00000004")]
    # A wall opening: a band 900..2100 mm in Z and 1000 mm along the wall, entirely
    # within the wall (0..12000 in X, height 3000). Two corners — exactly what
    # `Opening.BoundaryRect` gives back and what `NewOpening(Wall, XYZ, XYZ)` accepts.
    openings = [] if not wall_opening else [_demo_row(
        category="OST_SWallRectOpening", category_ru="Прямоугольный проем в стене",
        element_id=DEMO_WALL_OPENING, host_id=DEMO_WALL, host_source="opening",
        bbox_min_mm=[6000.0, -100.0, 900.0], bbox_max_mm=[7000.0, 100.0, 2100.0],
        opening_is_rect=True,
        opening_boundary_mm=[[6000.0, 0.0, 900.0], [7000.0, 0.0, 2100.0]],
        type_id="", type_name="",
        unique_id="00000000-0000-0000-0000-000000000001-00000005")]
    by_category = {"OST_Walls": [wall], "OST_Floors": [floor], "OST_Doors": doors,
                   "OST_SWallRectOpening": openings}
    rows, total = [header], 0
    # The category order is NOT a matter of taste: the L0 reader checks both the elements and the
    # statuses positionally against `EXTRACT_CATEGORIES` and refuses with `element collector is out of
    # category order`. So the table is walked in full, not with three rows.
    for category in EXTRACT_CATEGORIES:
        items = by_category.get(category, [])
        for item in items:
            rows.append({"record": "element", "collector": category, "element": item})
            total += 1
        rows.append({"record": "category_status", "status": {
            "category": category, "state": "complete", "extracted_count": len(items),
            "expected_count": len(items), "error": None, "section_receipts": None}})
    rows.append({"record": "footer", "stream_complete": True, "element_count": total,
                 "link_count": 0, "category_count": len(EXTRACT_CATEGORIES)})
    snapshot = "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n"
    (target / "L0.jsonl").write_text(snapshot, encoding="utf-8")
    # 🔴 THE REVISION PROOF TRAVELS INTO THE DEMO TOO — OTHERWISE THE FIXTURE TEACHES A FALSEHOOD.
    # A parse places `revision.proof.json` in 80 of 81 corpus runs, and since
    # 07.09.2026 `capture_edit` binds the edit to it
    # (`capture_revision_moved`). A demo without it would read as
    # `absent:no_revision_proof`, that is, the instructions' commands would show a
    # state a real run never has. The fingerprint here is
    # DERIVED FROM THE SNAPSHOT ITSELF and is therefore reproducible: there is no
    # invented number in the fixture.
    _digest = hashlib.sha256(snapshot.encode("utf-8")).hexdigest()
    (target / "revision.proof.json").write_text(json.dumps({
        "schema_version": "document-revision/1", "change_stamp": "capture-api-demo",
        "fingerprint": f"{total}:{_digest[:16]}:{_digest[16:32]}"},
        ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    (target / "sketch.index.json").write_text(json.dumps({
        "schema_version": "kir-decompile-sketch-index/1",
        "profile_index": {DEMO_FLOOR: {
            "exterior_loop": [[0.0, 0.0], [12000.0, 0.0], [12000.0, 8000.0], [0.0, 8000.0]],
            "holes": [[[2000.0, 2000.0], [5000.0, 2000.0],
                       [5000.0, 5000.0], [2000.0, 5000.0]]],
            "curve_kinds": [["line"] * 4, ["line"] * 4],
            "arc_midpoints": [[None] * 4, [None] * 4],
            "profile_available": True}}}, ensure_ascii=False), encoding="utf-8")
    return target


# ── CLI ────────────────────────────────────────────────────────────────────
#: Exit codes. A refusal (2) differs from a breakage (1): "the edit did not land, and here is
#: why" and "the tool broke" are different events, and a script must
#: tell them apart without parsing text.
EXIT_OK, EXIT_BROKEN, EXIT_REFUSED = 0, 1, 2


def _print(payload) -> None:
    json.dump(payload, sys.stdout, ensure_ascii=False, sort_keys=True, indent=1)
    sys.stdout.write("\n")


def _json_arg(text: str, what: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise CaptureEditError("bad_cli_json", f"{what}: {exc}", what) from exc


def _edits_from(args) -> list:
    """Edits with one command: `--edit` in full, or `--element` + `--patch`."""
    edits = []
    for text in args.edit or ():
        row = _json_arg(text, "--edit")
        if not isinstance(row, Mapping) or "element_id" not in row or "change" not in row:
            raise CaptureEditError("bad_cli_json",
                                   "--edit: ожидался объект {element_id, change[, before]}",
                                   "--edit")
        edits.append(row)
    if getattr(args, "element", None) is not None:
        edits.append({"element_id": args.element,
                      "change": _json_arg(args.patch or "{}", "--patch"),
                      "before": (_json_arg(args.before, "--before")
                                 if getattr(args, "before", None) else None)})
    if not edits:
        raise CaptureEditError("bad_cli_json", "не названо ни одной правки", "--edit")
    return edits


def _summary(capture: Capture) -> dict:
    return {"schema": API_SCHEMA, "path": str(capture.path), "lineage": capture.lineage,
            "elements": len(capture.elements), "nodes": len(capture.nodes),
            "edits": len(capture.edits), "integrity": capture.integrity,
            "edit_binding": capture.edit_binding, "profiles": capture.profiles,
            "capture_revision": capture.capture_revision,
            "revision_binding": capture.revision_binding,
            "side_indexes": list(capture.side_indexes),
            "missing_side_indexes": list(capture.missing_side_indexes),
            "source_binding": source_binding(capture)}


def _run(args) -> int:
    if args.command == "demo":
        target = write_demo_capture(args.out, wall_opening=args.wall_opening)
        answer = {"schema": API_SCHEMA, "capture": str(target),
                  "door": DEMO_DOOR, "second_door": DEMO_DOOR_2,
                  "floor": DEMO_FLOOR, "wall": DEMO_WALL}
        # The address is named ONLY when the opening was written: naming it always
        # would mean sending the reader to an address that is not in the snapshot.
        if args.wall_opening:
            answer["wall_opening"] = DEMO_WALL_OPENING
        _print(answer)
        return EXIT_OK
    capture = open_capture(args.capture, profiles=args.profiles)
    binding = _json_arg(args.binding, "--binding") if getattr(args, "binding", None) else None
    if args.command == "open":
        _print(_summary(capture))
        return EXIT_OK
    if args.command == "read":
        _print(read_element(capture, args.element).to_dict())
        return EXIT_OK
    if args.command == "ledger":
        _print(capture_ledger(capture, limit=args.limit))
        return EXIT_OK
    if args.command == "propose":
        rows, refused = [], False
        for row in _edits_from(args):
            proposal = propose_patch(capture, row["element_id"], row["change"],
                                     before=row.get("before"), source_binding=binding)
            refused = refused or not proposal.admissible
            rows.append(proposal.to_dict())
        _print({"schema": API_SCHEMA, "proposals": rows, "wrote_nothing": True})
        return EXIT_REFUSED if refused else EXIT_OK
    if args.command == "apply":
        rows, refused = [], False
        for row in _edits_from(args):
            applied = apply_patch(capture, row["element_id"], row["change"],
                                  before=row.get("before"), source_binding=binding)
            refused = refused or applied.refusal is not None
            rows.append(applied.to_dict())
        if refused:
            # 🔴 A REFUSAL IS NOT SAVED. Writing a capture, part of whose edits
            # were refused, would mean passing half the work off as the work — the same kind
            # of falsehood as "the change is there, there is no refusal".
            _print({"schema": API_SCHEMA, "applied": rows, "saved": None})
            return EXIT_REFUSED
        saved = save(capture, args.out) if args.out else None
        _print({"schema": API_SCHEMA, "applied": rows,
                "saved": None if saved is None else str(saved),
                "edits": len(capture.edits)})
        return EXIT_OK
    if args.command == "save":
        _print({"schema": API_SCHEMA, "saved": str(save(capture, args.out)),
                "edits": len(capture.edits)})
        return EXIT_OK
    if args.command == "export":
        programs, sources = _CE.export_program(capture, revit_version=args.revit_version)
        if args.csharp_dir:
            out = Path(args.csharp_dir)
            out.mkdir(parents=True, exist_ok=True)
            for index, source in enumerate(sources):
                if source:
                    (out / f"program_{index:03d}.cs").write_text(source, encoding="utf-8")
        _print({"schema": API_SCHEMA, "programs": len(programs),
                "compiled": sum(1 for source in sources if source),
                "refusals": capture.export_refusals, "csharp_dir": args.csharp_dir,
                "lineage": capture.lineage})
        return EXIT_OK
    raise CaptureEditError("unknown_command", args.command, args.command)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m kir.decompile.capture_api",
        description="Публичная дверь к сохранённому зданию: читать, предлагать, править.")
    sub = parser.add_subparsers(dest="command", required=True)

    demo = sub.add_parser("demo", help="написать синтетический capture для инструкции")
    demo.add_argument("--out", required=True)
    demo.add_argument("--wall-opening", action="store_true", dest="wall_opening",
                      help="дописать пятым элементом ПРОЁМ В СТЕНЕ "
                           "(снимок формы читателя границы; без флага демо "
                           "остаётся прежним зданием из четырёх элементов)")

    for name, help_text in (("open", "личность capture и чем он привязан"),
                            ("read", "элемент: значения, хозяин, связи, состояния полей"),
                            ("ledger", "ведомость ВСЕГО capture: четыре состояния "
                                       "числами и потери адресами"),
                            ("propose", "предпросмотр: diff и вопросы, БЕЗ записи"),
                            ("apply", "правка через edit_element и сохранение"),
                            ("save", "сохранить capture с накопленными правками"),
                            ("export", "вывезти программу и перевести её в C#")):
        item = sub.add_parser(name, help=help_text)
        item.add_argument("--capture", required=True)
        item.add_argument("--profiles", default="editable",
                          choices=("editable", "all", "none"))
        if name == "read":
            item.add_argument("--element", required=True)
        if name == "ledger":
            # The sums are always printed; only the list of rows is trimmed, and the response
            # names how many were left beyond the edge (`truncated`).
            item.add_argument("--limit", type=int, default=20,
                              help="сколько строк потерь напечатать (-1 — все)")
        if name in ("propose", "apply"):
            item.add_argument("--element")
            item.add_argument("--patch")
            item.add_argument("--before")
            item.add_argument("--edit", action="append")
            item.add_argument("--binding")
        if name in ("apply", "save"):
            item.add_argument("--out", required=(name == "save"))
        if name == "export":
            item.add_argument("--revit-version", default="2026")
            item.add_argument("--csharp-dir")
    return parser


def main(argv=None) -> int:
    args = _parser().parse_args(argv)
    try:
        return _run(args)
    except CaptureEditError as exc:
        # A seam refusal is printed in THE SAME shape as this contract's own refusal: the
        # script has one response parser, not two.
        _print({"schema": API_SCHEMA,
                "refusal": {"code": exc.code, "detail": str(exc), "address": exc.address}})
        return EXIT_REFUSED


if __name__ == "__main__":  # pragma: no cover — the process's entry point
    raise SystemExit(main())
