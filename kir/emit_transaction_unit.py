"""A unit of execution that OWNS ITS OWN transaction, outside the emitter's
shared Transaction.

Why a separate carrier, not just another call inside the existing wrapper.
`kir/authoring.py:8861` opens ONE `Transaction __t` for the whole program, and
every op's body runs INSIDE it (`kir/spec.py:124`). `SketchEditScope.Start`
requires that NO transaction be active; inserting it into that wrapper does
not give a compile error, it gives a live Revit refusal. A precedent already
exists in the tree — `spec.SOLO_OPS` (`kir/spec.py:128`): an op that owns its
own transactions is obligated to be the ONLY one in the program, otherwise
`PLAN_SOLO_OP`.

The requirement is read VERBATIM from the `RevitAPI.xml` of the real 2023 and
2026 packages (the texts are byte-identical), not paraphrased:

    SketchEditScope.Start: "SketchEditScope can only be started when there is
    no transaction active, thus it does not work for commands running in
    automatic transaction mode."

    T:SketchEditScope: "Start/end of a SketchEditScope will start/end a
    transaction group. After a SketchEditScope is started, an application can
    start transactions and edit the sketch."

That is, the transaction is not cancelled, it MOVES INSIDE the scope, and
none should exist outside it. This module carries that same law through to a
SCHEDULE with an explicit phase order:

    observe-before → unit → observe-after → receipt

The unit does NOT go through `compile_program`/`prepare_execution`: there the
source is unavoidably wrapped in the frame carrying `Transaction __t`. It is
wrapped by `wrap_connector_source` directly, and its source enters its own
SHA in full.

The boundaries of this slice, named HERE, not in a report:

* there was no live Revit; everything below is an offline plan and
  COMPILATION against the real `RevitAPI.dll` 2023 and 2026 (see
  `kir/tests/test_connector_compiler_conformance.py`);
* `identity_replacement="in_place"` — the only implemented policy: the
  existing type ITSELF is edited, and ALL of its users see it. The
  `duplicate_and_reassign` policy is declared and REFUSES, rather than being
  silently substituted;
* the scope of a type's users is obligated to arrive MEASURED. An unknown
  scope is a `type_user_scope_unknown` refusal, not an empty list;
* `floor_sketch_opening` (11.09.2026, after the native witness of 09.09):
  the loop is checked as a SIMPLE polygon in the plan, and the unit itself
  reads the floor's profile before any effect — the loop must lie strictly
  inside exactly one outer boundary, cross nothing, touch nothing and sit in
  no existing opening; after the commit the floor's area must have DROPPED by
  the loop's area, otherwise the unit's own `TransactionGroup` rolls the edit
  back and the receipt says so. Native witness `UnitFloorOutsideLoop`
  (kir-live-20260909, BatchG1): a 2×2 m loop outside a 10×8 m floor produced
  a second island, 80 → 84 m², and the old unit answered `ok=true`,
  `committed_verified`, because it counted loops (+1) and nothing else.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from typing import Any, Mapping, Sequence

from kir.emit_core import _cs
from kir.project import _freeze, _thaw
from kir.revit_connector import (ContextPrecondition, RuntimeTarget,
                                 wrap_connector_source)

TRANSACTION_UNIT_SCHEMA = "kir-transaction-unit/1"
TRANSACTION_UNIT_PLAN_SCHEMA = "kir-transaction-unit-plan/1"
TRANSACTION_UNIT_RESERVATION_SCHEMA = "kir-transaction-unit-reservation/1"

#: The ELEMENT REPLACEMENT record on a type change. The schema name and the
#: obligatory `old_unique_id`/`new_unique_id` pair are set by the lead; the
#: carrier on the Python side is written by the identity agent
#: (`kir/create_publication.py`), which is entitled to read
#: `IDENTITY_REPLACEMENT_ROW` as the contract of fields this unit puts in.
#:
#: 🔴 WHY THE RECORD IS NEEDED AT ALL. `RevitAPI.xml` for
#: `Element.ChangeTypeId` says verbatim: «In rare cases, applying a change in
#: type will result in a new element being created… In this situation the new
#: element id is returned». The old element is dead at that point. The first
#: revision of the unit read the after-observation by the OLD UniqueId, got
#: null, and declared `after_observation_disagrees` — that is, a FAILURE ON A
#: SUCCESSFUL REPLACEMENT. Found by the identity agent, `:903-912`; a
#: replacement is a lawful outcome, and it must be RECORDED, not treated as a
#: discrepancy.
IDENTITY_REPLACEMENT_SCHEMA = "kir-create-identity-replacement/1"
IDENTITY_REPLACEMENT_ROW = ("schema", "old_unique_id", "new_unique_id", "identity_replaced",
                            "old_element_id", "new_element_id")

#: The transaction's owner for a phase. `emitter` never occurs here: that is
#: exactly the point.
UNIT_OWNER = "unit"
SKETCH_OWNER = "sketch_edit_scope"

#: How many OF ITS OWN transactions the unit of each owner opens.
#: For `sketch_edit_scope` it is also exactly one — but INSIDE the edit
#: scope, exactly as RevitAPI.xml requires: «an application can start
#: transactions and edit».
_OWN_TRANSACTIONS = {UNIT_OWNER: 1, SKETCH_OWNER: 1}

#: Section → transaction owner. A closed list; a foreign section is a
#: refusal.
SECTIONS = {"wall_type_layer_width": UNIT_OWNER,
            "floor_sketch_opening": SKETCH_OWNER}

IDENTITY_REPLACEMENT_POLICIES = ("in_place", "duplicate_and_reassign")
IMPLEMENTED_IDENTITY_REPLACEMENT = ("in_place", "duplicate_and_reassign")

#: Section (and a separate branch within a section) → the MINIMUM Revit
#: version.
#:
#: 🔴 THE NUMBERS ARE MEASURED BY COMPILATION, NOT TAKEN FROM DOCUMENTATION.
#: A run on 07.09 against the real RevitAPI 2021/2022/2023/2026:
#:
#:   floor_sketch_opening on 2021 → CS1061: 'Floor' does not contain a
#:       definition for 'SketchId';
#:   StartWithNewSketch on 2021 → CS0246: the type `SketchEditScope` does not
#:       exist at all; on 2022 → CS1061: the type exists, the method does
#:       not. `RevitAPI.xml` confirms this separately: the member is marked
#:       `[since] 2023`.
#:
#: A refusal is obligated to arrive IN THE PLAN, not from a compiler at the
#: far end of the wire: before this fix, `prepare_transaction_unit` handed a
#: target-2021 caller a source that does not build, and this would have been
#: learned from someone else's diagnostics.
SECTION_MIN_VERSION = {"wall_type_layer_width": 2021,
                       "floor_sketch_opening": 2022,
                       "floor_sketch_opening_new_sketch": 2023}

_FEET_MM = 304.8
#: The tolerance for checking an observed layer width, mm. The same order of
#: magnitude as `ops_families.create_wall_type`
#: (`tolerances={"layer_mm": 0.5}`).
LAYER_TOLERANCE_MM = 0.5
MAX_PROTECTED_SCOPE = 128
MAX_TYPE_USERS = 4096
MAX_SKETCH_LOOP_POINTS = 256

_NOT_ESTABLISHED = {
    "native_execution": "not_run",
    "engineering_acceptance": "not_established",
    "geometric_validity": "not_evaluated",
    "type_user_side_effects": "declared_not_verified",
    "live_revit": "never_run",
}


class TransactionUnitRefusal(ValueError):
    """The unit's refusal. The code is for the machine, the message is for
    the human."""

    def __init__(self, code: str, message: str = ""):
        super().__init__(message or code)
        self.code = code
        self.message = message or code


def _require(condition, code, message=""):
    if not condition:
        raise TransactionUnitRefusal(code, message)


def _digest(payload) -> str:
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True,
                                     allow_nan=False, separators=(",", ":")).encode("utf-8")).hexdigest()


def _mm(value, name):
    _require(type(value) in (int, float) and value == value and abs(value) < 1e9,
             "invalid_length", f"{name}: ожидалось конечное число миллиметров")
    return float(value)


def _feet_literal(mm: float) -> str:
    # The representation is pinned HERE: there is one divisor, the literal is
    # deterministic, and it enters the source's SHA. Rounding on the C# side
    # is forbidden.
    return repr(float(mm) / _FEET_MM)


def _uid(value, name):
    _require(type(value) is str and value.strip() and len(value) <= 512,
             "invalid_unique_id", f"{name}: ожидался непустой UniqueId")
    return value


# ─────────────────────────────────────────────────────────── plan ──


@dataclass(frozen=True, slots=True, init=False)
class TransactionUnitPlan:
    """A fresh plan of a single unit. A loaded record never becomes one."""

    section: str
    transaction_owner: str
    target: RuntimeTarget
    precondition: ContextPrecondition
    unique_id: str
    identity_replacement: str
    digest: str
    _diff: object = field(repr=False)
    _ownership: object = field(repr=False)
    #: What the plan claims and what it does not — per plan, because the
    #: opening unit (11.09.2026) checks geometry and witnesses area itself,
    #: while the wall unit still establishes neither. Part of the digest.
    _claims: object = field(repr=False)

    def __init__(self, *args, **kwargs):
        raise TypeError("используйте plan_*; сохранённая запись — не свежий план")

    @property
    def diff(self):
        return _thaw(self._diff)

    @property
    def ownership(self):
        return _thaw(self._ownership)

    @property
    def protected_unique_ids(self) -> tuple:
        return tuple(self.ownership["protected_unique_ids"])

    def to_dict(self) -> dict:
        return {"schema": TRANSACTION_UNIT_PLAN_SCHEMA, "section": self.section,
                "transaction_owner": self.transaction_owner,
                "target": self.target.to_dict(), "precondition": self.precondition.to_dict(),
                "unique_id": self.unique_id, "identity_replacement": self.identity_replacement,
                "diff": self.diff, "ownership": self.ownership,
                "plan_digest": self.digest, "claims": _thaw(self._claims)}


@dataclass(frozen=True, slots=True, init=False)
class RetainedTransactionUnitPlan:
    """An inert reloaded record: it is checked, but NOT executed.

    A separate type on purpose. Otherwise a process restart would turn a
    JSON file into proof of a fresh observation, and that is exactly the
    substitution `PreparedExecution.__init__` forbids for its own carrier.
    """

    plan_digest: str
    _payload: object = field(repr=False)

    def __init__(self, *args, **kwargs):
        raise TypeError("используйте load_transaction_unit_plan")

    def to_dict(self):
        return _thaw(self._payload)

    @property
    def section(self):
        return self.to_dict()["section"]

    def matches(self, plan: TransactionUnitPlan) -> bool:
        """Whether this is the same plan — BYTE FOR BYTE, not "looks alike
        field by field"."""
        _require(type(plan) is TransactionUnitPlan, "transaction_unit_plan_required")
        return plan.digest == self.plan_digest and plan.to_dict() == self.to_dict()


def load_transaction_unit_plan(value: Mapping) -> RetainedTransactionUnitPlan:
    """Restart: read the saved plan and RECOMPUTE its digest."""
    _require(isinstance(value, Mapping), "invalid_retained_plan")
    payload = _thaw(_freeze(dict(value)))
    _require(payload.get("schema") == TRANSACTION_UNIT_PLAN_SCHEMA, "unknown_retained_plan_schema")
    for name in ("section", "transaction_owner", "target", "precondition", "unique_id",
                 "identity_replacement", "diff", "ownership", "plan_digest", "claims"):
        _require(name in payload, "incomplete_retained_plan", f"нет поля {name}")
    _require(payload["section"] in SECTIONS, "unknown_section")
    _require(SECTIONS[payload["section"]] == payload["transaction_owner"],
             "transaction_owner_conflict", "владелец транзакции не тот, что у секции")
    stated = payload["plan_digest"]
    body = {k: v for k, v in payload.items() if k != "plan_digest"}
    _require(_digest(body) == stated, "retained_plan_digest_mismatch",
             "сохранённый план не сходится со своим дайджестом")
    retained = object.__new__(RetainedTransactionUnitPlan)
    object.__setattr__(retained, "plan_digest", stated)
    object.__setattr__(retained, "_payload", _freeze(payload))
    return retained


def _bound_observation(observation, target, precondition):
    """The observation is obligated to belong to THE SAME document and THE
    SAME C0 revision."""
    _require(getattr(observation, "target", None) == target,
             "observation_target_differs", "наблюдение снято на другом runtime/документе")
    _require(getattr(observation, "precondition", None) == precondition,
             "observation_c0_differs",
             "наблюдение снято на другой ревизии; свежий контекст не заменяет C0")


def _type_user_scope(type_users, target, precondition):
    """The scope of a type's users. An unknown scope is a REFUSAL, not an
    empty list."""
    _require(isinstance(type_users, Mapping), "type_user_scope_unknown",
             "нужна измеренная область пользователей типа")
    for name in ("query_source_sha256", "unique_ids", "complete"):
        _require(name in type_users, "type_user_scope_unknown", f"нет поля {name}")
    _require(type_users["complete"] is True, "type_user_scope_incomplete",
             "усечённая выборка пользователей типа не годится как область")
    uids = tuple(type_users["unique_ids"])
    _require(len(uids) <= MAX_TYPE_USERS, "type_user_scope_budget")
    _require(all(type(u) is str and u.strip() for u in uids), "type_user_scope_unknown")
    _require(len(set(uids)) == len(uids), "duplicate_type_user")
    sha = type_users["query_source_sha256"]
    _require(type(sha) is str and len(sha) == 64 and all(c in "0123456789abcdef" for c in sha),
             "type_user_scope_unknown", "область должна быть привязана к исходнику запроса")
    return uids, sha


def _observed_row(observation, unique_id):
    """The observation row by UniqueId. A foreign address is a refusal, not
    an empty row.

    Carriers hold rows differently (a `dict` for both today, a list for a
    future one). The key is always the REQUESTED UniqueId, and the match is
    checked against it, not against order.
    """
    rows = observation.rows
    if isinstance(rows, Mapping):
        table = dict(rows)
    else:
        table = {}
        for row in rows:
            _require(isinstance(row, Mapping), "invalid_observation_row")
            table[row.get("requested_unique_id")] = row
    # TWO guards, and their codes are DIFFERENT on purpose. The first is
    # responsible for "an address outside the scope" — that is what makes a
    # foreign UID foreign. The second catches something else: a row placed
    # in the table under the wrong name. A shared code would hide that
    # removing the first changes the NAMED cause, and a mutation of the
    # first would have stayed green — which is exactly what happened in the
    # 07.09 run, while the codes matched.
    _require(unique_id in table, "foreign_unique_id",
             "UniqueId вне области наблюдения; чужой адрес не наблюдался")
    row = table[unique_id]
    _require(row.get("requested_unique_id") in (None, unique_id), "observation_row_mislabelled",
             "ряд наблюдения лежит не под своим requested_unique_id")
    _require(row.get("status") == "observed", "target_not_observed",
             f"элемент не наблюдён: {row.get('reason')}")
    return row


def _protected(values, forbidden):
    scope = tuple(values or ())
    _require(len(scope) <= MAX_PROTECTED_SCOPE, "protected_scope_budget")
    for uid in scope:
        _uid(uid, "protected_unique_id")
        _require(uid not in forbidden, "protected_scope_conflict",
                 "изменяемый объект не может быть одновременно защищённым")
    _require(len(set(scope)) == len(scope), "duplicate_protected_identity")
    return scope


def plan_wall_type_layer_width(observation, *, unique_id: str, layer_index: int,
                               width_mm: float, target: RuntimeTarget,
                               precondition: ContextPrecondition, type_users: Mapping,
                               protected_unique_ids: Sequence[str] = (),
                               identity_replacement: str = "in_place",
                               new_type_name: str | None = None,
                               reassign_unique_ids: Sequence[str] | None = None) -> TransactionUnitPlan:
    """A plan to change the width of ONE WallType layer — in place or by
    duplication.

    A fresh `TypeDefinitionObservation` of the same document and the same
    revision is required. The remaining layers are enumerated IN THE PLAN by
    name with their widths: "preserving the other layers" is NUMBERS in a
    diff, not a promise.

    `identity_replacement="in_place"` — the type ITSELF is edited, and ALL of
    its users see it. `"duplicate_and_reassign"` — a DUPLICATE is created
    with the changed layer stack, and only `reassign_unique_ids` ⊆ the
    measured scope is switched to it; the original type stays INTACT, and
    this is checked with numbers before and after.

    🔴 WHAT THE PLAN DOES NOT KNOW ABOUT THE DUPLICATE'S NAME. The
    document's type names are not part of the observation, and they cannot
    be invented here. The plan rejects only the obvious case — a name equal
    to the source type's name. The real collision guard stands IN C# BEFORE
    ANY EFFECT (`FilteredElementCollector` by `Name`), exactly like the
    existing type factory (`kir/authoring.py:4457`).
    """
    from kir.type_definition_observation import TypeDefinitionObservation

    _require(type(observation) is TypeDefinitionObservation,
             "type_definition_observation_required",
             "нужно свежее разобранное наблюдение определения типа")
    _require(type(target) is RuntimeTarget and type(precondition) is ContextPrecondition,
             "invalid_input", "нужны типизированные target и precondition")
    _bound_observation(observation, target, precondition)
    _uid(unique_id, "unique_id")
    _require(identity_replacement in IDENTITY_REPLACEMENT_POLICIES,
             "unknown_identity_replacement")
    _require(identity_replacement in IMPLEMENTED_IDENTITY_REPLACEMENT,
             "identity_replacement_not_implemented",
             f"политика {identity_replacement} названа, но не реализована этим срезом")
    duplicating = identity_replacement == "duplicate_and_reassign"
    if not duplicating:
        _require(new_type_name is None and reassign_unique_ids is None,
                 "duplicate_arguments_without_policy",
                 "имя дубля и область перевода имеют смысл только у duplicate_and_reassign")

    row = _observed_row(observation, unique_id)
    definition = row.get("type_definition") or {}
    _require(definition.get("status") == "observed", "type_definition_unavailable",
             f"определение типа недоступно: {definition.get('reason')}")
    value = definition.get("value") or {}
    layers = list(value.get("layers") or ())
    _require(layers, "compound_structure_missing", "у наблюдённого типа нет слоёв")
    _require(value.get("is_vertically_homogeneous") is True, "non_simple_compound_structure",
             "пирог с горизонтальными разрывами этим срезом не правится")
    _require(type(layer_index) is int and 0 <= layer_index < len(layers),
             "layer_index_out_of_range", f"слоёв наблюдено {len(layers)}")

    after_mm = _mm(width_mm, "width_mm")
    _require(after_mm > 0.0, "invalid_layer_width", "ширина слоя обязана быть положительной")
    before_mm = _mm(layers[layer_index].get("width_mm"), "наблюдённая width_mm")
    _require(abs(after_mm - before_mm) > LAYER_TOLERANCE_MM, "no_change_planned",
             "предложенная ширина совпадает с наблюдённой в пределах допуска")

    users, users_sha = _type_user_scope(type_users, target, precondition)
    protected = _protected(protected_unique_ids, {unique_id})
    reassign = ()
    if duplicating:
        _require(type(new_type_name) is str and new_type_name.strip()
                 and len(new_type_name) <= 128, "duplicate_name_required",
                 "имя дубля обязано быть непустой строкой")
        _require(not (set(new_type_name) & set('{}[]|;<>?`~')), "duplicate_name_invalid",
                 "имя типа не принимает символы, перечисленные RevitAPI.xml у Duplicate")
        _require(new_type_name != value.get("name"), "duplicate_name_collides",
                 "имя дубля совпадает с именем исходного типа")
        _require(reassign_unique_ids is not None
                 and not isinstance(reassign_unique_ids, (str, bytes)),
                 "reassign_scope_required", "нужен список переводимых пользователей")
        reassign = tuple(reassign_unique_ids)
        _require(reassign, "reassign_scope_empty",
                 "пустая область перевода: дубль без пользователей — не изменение")
        _require(len(set(reassign)) == len(reassign), "duplicate_reassign_identity")
        for uid in reassign:
            _uid(uid, "reassign_unique_id")
        outside = [uid for uid in reassign if uid not in set(users)]
        _require(not outside, "reassign_outside_type_user_scope",
                 "перевод вне измеренной области пользователей: " + ", ".join(outside[:4]))
        _require(unique_id not in reassign, "reassign_includes_the_type_itself")

    preserved = [{"index": i, "width_mm": _mm(layer.get("width_mm"), "width_mm"),
                  "function": layer.get("function")}
                 for i, layer in enumerate(layers) if i != layer_index]
    # THE SUM, NOT JUST THE LAYERS. Every layer matching individually does
    # not yet mean the assembly's thickness is the same: a layer could have
    # appeared or disappeared where the plan did not enumerate it. So the
    # layer stack's total is checked as well.
    observed_total = _mm(value.get("total_width_mm"), "total_width_mm")
    layer_sum = sum(_mm(layer.get("width_mm"), "width_mm") for layer in layers)
    _require(abs(observed_total - layer_sum) <= LAYER_TOLERANCE_MM,
             "observed_total_disagrees_with_layers",
             f"наблюдённая сумма {observed_total} против суммы слоёв {layer_sum}")
    all_layers = [{"index": i, "width_mm": _mm(layer.get("width_mm"), "width_mm"),
                   "function": layer.get("function")} for i, layer in enumerate(layers)]
    diff = {"kind": "layer_width",
            "changed": [{"index": layer_index, "before_mm": before_mm, "after_mm": after_mm,
                         "function": layers[layer_index].get("function")}],
            "preserved_layers": preserved,
            "observed_layer_count": len(layers),
            "observed_total_width_mm": layer_sum,
            "expected_total_width_mm": layer_sum - before_mm + after_mm,
            "tolerance_mm": LAYER_TOLERANCE_MM}
    ownership = {"transaction_owner": UNIT_OWNER,
                 "changed_unique_ids": [unique_id],
                 "identity_replacement": identity_replacement,
                 "identity_replacement_effect":
                     "существующий тип правится на месте; UniqueId сохраняется, "
                     "изменение видят ВСЕ перечисленные пользователи типа",
                 "type_user_unique_ids": list(users),
                 "type_user_count": len(users),
                 "type_user_scope_source_sha256": users_sha,
                 "protected_unique_ids": list(protected),
                 "observation_source_sha256": observation.source_sha256,
                 "observation_digest": observation.digest}
    if duplicating:
        retained = [uid for uid in users if uid not in set(reassign)]
        # The DUPLICATE's layer stack changes; the ORIGINAL changes NOTHING,
        # and this is recorded as numbers for EVERY layer, not by the word
        # "intact".
        diff["kind"] = "layer_width_on_duplicate"
        diff["source_layers_unchanged"] = all_layers
        diff["source_total_width_mm"] = layer_sum
        diff["duplicate_layers"] = [dict(row, width_mm=after_mm) if row["index"] == layer_index
                                    else dict(row) for row in all_layers]
        ownership["changed_unique_ids"] = list(reassign)
        ownership["source_type_unique_id"] = unique_id
        ownership["source_type_preserved"] = True
        ownership["new_type_name"] = new_type_name
        ownership["reassign_unique_ids"] = list(reassign)
        ownership["reassign_count"] = len(reassign)
        ownership["retained_on_source_unique_ids"] = retained
        ownership["identity_replacement_effect"] = (
            "заводится ДУБЛЬ типа с изменённым пирогом; исходный тип и его "
            f"UniqueId целы, на дубль переводится {len(reassign)} из {len(users)} "
            "пользователей, остальные остаются на исходном типе")
    return _build_plan("wall_type_layer_width", target, precondition, unique_id,
                       identity_replacement, diff, ownership)


#: Twice the loop's area (shoelace) must exceed this, in mm²: a collinear
#: or degenerate loop has no inside for an opening to be.
_MIN_LOOP_AREA2_MM2 = 1e-6


def _loop_area2(points: Sequence[tuple[float, float]]) -> float:
    """Twice the SIGNED area of the polygon (shoelace)."""
    total = 0.0
    for index, (x0, y0) in enumerate(points):
        x1, y1 = points[(index + 1) % len(points)]
        total += x0 * y1 - x1 * y0
    return total


def _cross(o, a, b) -> float:
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def _on_segment(q, a, b) -> bool:
    """`q` lies ON segment `ab` (collinear and within its box)."""
    if _cross(a, b, q) != 0.0:
        return False
    return (min(a[0], b[0]) <= q[0] <= max(a[0], b[0])
            and min(a[1], b[1]) <= q[1] <= max(a[1], b[1]))


def _segments_meet(a, b, c, d) -> bool:
    """Segments `ab` and `cd` share at least one point (crossing OR touching)."""
    d1, d2 = _cross(c, d, a), _cross(c, d, b)
    d3, d4 = _cross(a, b, c), _cross(a, b, d)
    if ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0)) and 0.0 not in (d1, d2, d3, d4):
        return True
    return (_on_segment(a, c, d) or _on_segment(b, c, d)
            or _on_segment(c, a, b) or _on_segment(d, a, b))


def _loop_is_simple(points: Sequence[tuple[float, float]]) -> bool:
    """A SIMPLE polygon: non-adjacent edges never meet, adjacent edges share
    only their common vertex (no fold-back spike)."""
    n = len(points)
    for i in range(n):
        for j in range(i + 1, n):
            a, b = points[i], points[(i + 1) % n]
            c, d = points[j], points[(j + 1) % n]
            if j == i + 1 or (i == 0 and j == n - 1):
                # Adjacent: the far ends must not lie on the neighbour's edge.
                shared = points[j] if j == i + 1 else points[0]
                far_i = points[i] if j == i + 1 else points[1]
                far_j = points[(j + 1) % n] if j == i + 1 else points[n - 1]
                if _on_segment(far_i, shared, far_j) or _on_segment(far_j, shared, far_i):
                    return False
            elif _segments_meet(a, b, c, d):
                return False
    return True


def plan_floor_sketch_opening(observation, *, unique_id: str, loop_mm: Sequence[Sequence[float]],
                              target: RuntimeTarget, precondition: ContextPrecondition,
                              protected_unique_ids: Sequence[str] = (),
                              allow_new_sketch: bool = False) -> TransactionUnitPlan:
    """A plan for one opening in a Floor's sketch.

    The transaction's owner is `SketchEditScope`: it REQUIRES no active
    Transaction, so the step cannot live inside the emitter's frame.

    `allow_new_sketch=False` (the default) — a floor WITHOUT a sketch remains
    a `sketch_missing` refusal. A sketch cannot be created silently:
    `StartWithNewSketch` gives the element something it did not have, and
    that is a separate decision for the author, not an implementation detail
    of the opening. With `True`, the branch reverses: the before-observation
    is OBLIGATED to see `SketchId == InvalidElementId`, otherwise
    `sketch_already_present` — per `RevitAPI.xml`, the method throws an
    ArgumentException «The ElementId elementId already has a sketch
    defined».

    WHAT THE PLAN CHECKS AND WHAT THE UNIT CHECKS (11.09.2026). The
    observation row carries no geometry, so the plan can only judge the loop
    ITSELF: a simple polygon (no crossing or touching edges, no fold-back)
    with a non-zero area. Everything that needs the floor's profile — the
    loop lying strictly inside exactly one outer boundary, crossing nothing,
    touching nothing, sitting in no existing opening — is read by the unit
    from `Sketch.Profile` BEFORE the edit scope opens, and refused before any
    effect. After the commit the unit reads the floor's area again and
    demands a DROP of about the loop's area; a disagreement rolls the edit
    back through the unit's own `TransactionGroup` (`state="rolled_back"`).
    """
    from kir.revit_observation import ElementObservation

    _require(type(observation) is ElementObservation, "element_observation_required",
             "нужно свежее разобранное наблюдение элемента")
    _require(type(target) is RuntimeTarget and type(precondition) is ContextPrecondition,
             "invalid_input", "нужны типизированные target и precondition")
    _bound_observation(observation, target, precondition)
    _uid(unique_id, "unique_id")
    _observed_row(observation, unique_id)

    points = [tuple(_mm(v, "loop point") for v in point) for point in (loop_mm or ())]
    _require(3 <= len(points) <= MAX_SKETCH_LOOP_POINTS, "invalid_sketch_loop",
             "петля отверстия — минимум три точки")
    _require(all(len(p) == 2 for p in points), "invalid_sketch_loop",
             "точки петли задаются парой (x, y) в мм плоскости эскиза")
    _require(len(set(points)) == len(points), "invalid_sketch_loop",
             "совпадающие точки петли")
    _require(_loop_is_simple(points), "invalid_sketch_loop",
             "петля отверстия самопересекается или складывается на себя")
    area2 = _loop_area2(points)
    _require(abs(area2) > _MIN_LOOP_AREA2_MM2, "invalid_sketch_loop",
             "петля отверстия вырождена: площадь равна нулю")
    _require(type(allow_new_sketch) is bool, "invalid_input",
             "allow_new_sketch — строго bool, не «истинное значение»")
    protected = _protected(protected_unique_ids, {unique_id})
    diff = {"kind": "sketch_opening", "added_loops": [[list(p) for p in points]],
            "existing_loops": "preserved_unchanged",
            "loop_point_count": len(points),
            "loop_area_mm2": abs(area2) / 2.0,
            "allow_new_sketch": allow_new_sketch,
            "expected_sketch_before": "absent" if allow_new_sketch else "present",
            # The unit's own acceptance, named in the plan so a reader of the
            # saved plan knows what a `committed_verified` receipt stands on.
            "unit_acceptance": {
                "before_effect": "loop_inside_one_outer_boundary_no_crossing_no_touching_no_existing_opening",
                "after_commit": "floor_area_dropped_by_loop_area_else_rolled_back"}
            if not allow_new_sketch else {
                "before_effect": "no_profile_to_check_against",
                "after_commit": "one_loop_present_area_recorded_not_judged"}}
    ownership = {"transaction_owner": SKETCH_OWNER,
                 "changed_unique_ids": [unique_id],
                 "identity_replacement": "in_place",
                 "identity_replacement_effect":
                     "правится эскиз существующего пола; UniqueId пола сохраняется",
                 "protected_unique_ids": list(protected),
                 "observation_source_sha256": observation.source_sha256,
                 "allow_new_sketch": allow_new_sketch,
                 "requires_no_active_transaction": True}
    claims = dict(_NOT_ESTABLISHED)
    if not allow_new_sketch:
        claims["geometric_validity"] = "checked_by_unit_before_effect"
        claims["engineering_acceptance"] = "area_witnessed_by_unit_or_rolled_back"
    return _build_plan("floor_sketch_opening", target, precondition, unique_id,
                       "in_place", diff, ownership,
                       version_keys=("floor_sketch_opening_new_sketch",) if allow_new_sketch else (),
                       claims=claims)


def _require_version(target, keys):
    """Every named capability is obligated to exist in THIS version of the
    API."""
    version = int(target.revit_version)
    for key in keys:
        minimum = SECTION_MIN_VERSION[key]
        if version < minimum:
            raise TransactionUnitRefusal(
                f"section_unsupported_on_version:{key}:{version}",
                f"{key} требует Revit {minimum} и старше; цель — {version}")


def _build_plan(section, target, precondition, unique_id, identity_replacement, diff, ownership,
                *, version_keys=(), claims=None):
    _require_version(target, (section,) + tuple(version_keys))
    plan = object.__new__(TransactionUnitPlan)
    body = {"schema": TRANSACTION_UNIT_PLAN_SCHEMA, "section": section,
            "transaction_owner": SECTIONS[section], "target": target.to_dict(),
            "precondition": precondition.to_dict(), "unique_id": unique_id,
            "identity_replacement": identity_replacement, "diff": diff,
            "ownership": ownership,
            "claims": dict(_NOT_ESTABLISHED) if claims is None else dict(claims)}
    for name, value in {"section": section, "transaction_owner": SECTIONS[section],
                        "target": target, "precondition": precondition,
                        "unique_id": unique_id, "identity_replacement": identity_replacement,
                        "digest": _digest(body), "_diff": _freeze(diff),
                        "_ownership": _freeze(ownership),
                        "_claims": _freeze(body["claims"])}.items():
        object.__setattr__(plan, name, value)
    return plan


__all__ = ["TRANSACTION_UNIT_SCHEMA", "TRANSACTION_UNIT_PLAN_SCHEMA",
           "IDENTITY_REPLACEMENT_SCHEMA", "IDENTITY_REPLACEMENT_ROW",
           "TRANSACTION_UNIT_RESERVATION_SCHEMA", "SECTIONS", "UNIT_OWNER", "SKETCH_OWNER",
           "IDENTITY_REPLACEMENT_POLICIES", "IMPLEMENTED_IDENTITY_REPLACEMENT",
           "LAYER_TOLERANCE_MM", "TransactionUnitRefusal", "TransactionUnitPlan",
           "RetainedTransactionUnitPlan", "load_transaction_unit_plan",
           "plan_wall_type_layer_width", "plan_floor_sketch_opening"]


# ─────────────────────────────────────────────── C# emission of the unit ──

#: The Revit-refusal handler class. Declared AT namespace LEVEL: the contract
#: of `wrap_connector_source` — the body closes Execute and leaves a method
#: stub open, the wrapper itself appends the three closing braces.
_HELPERS = """
} }
public sealed class __KirUnitFailures : IFailuresPreprocessor
{
    public static readonly List<string> Seen = new List<string>();
    public FailureProcessingResult PreprocessFailures(FailuresAccessor accessor)
    {
        foreach (FailureMessageAccessor __m in accessor.GetFailureMessages())
            Seen.Add(__m.GetDescriptionText());
        return FailureProcessingResult.Continue;
    }
}
"""

#: The helpers only the floor unit needs. Kept OUT of `_HELPERS`: the wall
#: unit compiles against Revit 2021, where `SketchEditScope` does not exist.
_FLOOR_HELPERS = """
// Plane 2D geometry of sketch loops, in feet, in the world XY chart of a
// HORIZONTAL sketch plane. No Revit call inside: what is judged here is
// judged the same way in every version.
public static class __KirLoop2D
{
    public static double Area2(List<double[]> p)
    {
        double s = 0.0;
        for (int i = 0, n = p.Count; i < n; i++)
        {
            double[] a = p[i], b = p[(i + 1) % n];
            s += a[0] * b[1] - b[0] * a[1];
        }
        return s;
    }
    public static double Cross(double[] o, double[] a, double[] b)
    { return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]); }
    // Even-odd ray casting. A point ON an edge is the business of Clearance.
    public static bool Contains(List<double[]> p, double x, double y)
    {
        bool inside = false;
        for (int i = 0, j = p.Count - 1; i < p.Count; j = i++)
        {
            double xi = p[i][0], yi = p[i][1], xj = p[j][0], yj = p[j][1];
            if ((yi > y) != (yj > y))
            {
                double xc = xi + (y - yi) * (xj - xi) / (yj - yi);
                if (x < xc) inside = !inside;
            }
        }
        return inside;
    }
    public static int VerticesInside(List<double[]> ring, List<double[]> pts)
    {
        int count = 0;
        foreach (double[] v in pts) if (Contains(ring, v[0], v[1])) count++;
        return count;
    }
    public static double DistanceToSegment(double px, double py, double[] a, double[] b)
    {
        double dx = b[0] - a[0], dy = b[1] - a[1], l2 = dx * dx + dy * dy;
        double t = l2 <= 0.0 ? 0.0 : ((px - a[0]) * dx + (py - a[1]) * dy) / l2;
        if (t < 0.0) t = 0.0; else if (t > 1.0) t = 1.0;
        double qx = a[0] + t * dx - px, qy = a[1] + t * dy - py;
        return Math.Sqrt(qx * qx + qy * qy);
    }
    public static double DistanceToRing(List<double[]> ring, double x, double y)
    {
        double best = double.MaxValue;
        for (int i = 0, n = ring.Count; i < n; i++)
        {
            double d = DistanceToSegment(x, y, ring[i], ring[(i + 1) % n]);
            if (d < best) best = d;
        }
        return best;
    }
    // Smallest distance from any vertex of one ring to the edges of the other, both ways.
    public static double Clearance(List<double[]> p, List<double[]> q)
    {
        double best = double.MaxValue;
        foreach (double[] v in p) { double d = DistanceToRing(q, v[0], v[1]); if (d < best) best = d; }
        foreach (double[] v in q) { double d = DistanceToRing(p, v[0], v[1]); if (d < best) best = d; }
        return best;
    }
    // Proper crossing: the interiors of two segments meet in one point.
    public static bool SegmentsCross(double[] a, double[] b, double[] c, double[] d)
    {
        double d1 = Cross(c, d, a), d2 = Cross(c, d, b), d3 = Cross(a, b, c), d4 = Cross(a, b, d);
        return ((d1 > 0 && d2 < 0) || (d1 < 0 && d2 > 0)) && ((d3 > 0 && d4 < 0) || (d3 < 0 && d4 > 0));
    }
    public static bool RingsCross(List<double[]> p, List<double[]> q)
    {
        for (int i = 0, n = p.Count; i < n; i++)
            for (int j = 0, m = q.Count; j < m; j++)
                if (SegmentsCross(p[i], p[(i + 1) % n], q[j], q[(j + 1) % m])) return true;
        return false;
    }
    // Simple polygon: no two non-adjacent edges cross.
    public static bool IsSimple(List<double[]> p)
    {
        int n = p.Count;
        if (n < 3) return false;
        for (int i = 0; i < n; i++)
            for (int j = i + 1; j < n; j++)
            {
                if (j == i + 1 || (i == 0 && j == n - 1)) continue;
                if (SegmentsCross(p[i], p[(i + 1) % n], p[j], p[(j + 1) % n])) return false;
            }
        return true;
    }
}
// The unit's own TransactionGroup: whatever the unit did inside it is
// undone as ONE step, and the receipt learns whether that undo happened.
public static class __KirUnitGroup
{
    public static bool Abandon(TransactionGroup group, SketchEditScope scope)
    {
        try { if (scope != null && scope.IsActive) scope.Cancel(); } catch { }
        try
        {
            if (group != null && group.HasStarted() && !group.HasEnded())
                return group.RollBack() == TransactionStatus.RolledBack;
        }
        catch { }
        return false;
    }
}
"""

_HELPERS_TAIL = """
public static class __KirUnitPad { public static void Pad() {
"""

_PREAMBLE = """var __receipt = new Dictionary<string, object>();
__receipt["schema"] = {schema};
__receipt["section"] = {section};
__receipt["transaction_owner"] = {owner};
__receipt["plan_digest"] = {digest};
__receipt["unique_id"] = {uid};
__receipt["phase"] = "entered";
__receipt["effect"] = "none";
__receipt["ok"] = false;
// НЕГАТИВ ДО START. Единица владеет транзакцией сама; активная транзакция
// эмиттера — не «неудобство», а причина живого отказа SketchEditScope.
if (doc.IsModifiable)
{{
    __receipt["refusal"] = "active_transaction_forbids_unit";
    return __receipt;
}}
Element __el = doc.GetElement({uid});
if (__el == null) {{ __receipt["refusal"] = "unit_target_missing"; return __receipt; }}
// Числовой адрес не доказывает принадлежность: сверяем САМ UniqueId.
if (__el.UniqueId != {uid})
{{ __receipt["refusal"] = "unit_target_identity"; return __receipt; }}
"""


def _wall_type_layer_width_cs(plan: TransactionUnitPlan) -> str:
    diff = plan.diff
    changed = diff["changed"][0]
    index, count = changed["index"], diff["observed_layer_count"]
    before_ft, after_ft = _feet_literal(changed["before_mm"]), _feet_literal(changed["after_mm"])
    tol_ft = _feet_literal(diff["tolerance_mm"])
    total_before_ft = _feet_literal(diff["observed_total_width_mm"])
    total_after_ft = _feet_literal(diff["expected_total_width_mm"])
    # ALL n-1 untouched layers are checked, not just the target's neighbors:
    # a layer the plan says nothing about is exactly the case this check
    # exists for.
    preserved = "".join(
        f'if (Math.Abs(__before[{row["index"]}].Width - {_feet_literal(row["width_mm"])}) > {tol_ft})\n'
        f'{{ __receipt["refusal"] = "preserved_layer_changed_since_observation";\n'
        f'  __receipt["preserved_layer_index"] = {row["index"]}; return __receipt; }}\n'
        for row in diff["preserved_layers"])
    # The same AFTER the commit: "we changed one layer" is proven by the
    # rest not having changed, not by the target having become the desired
    # one.
    preserved_after = "".join(
        f'    if (Math.Abs(__after[{row["index"]}].Width - {_feet_literal(row["width_mm"])}) > {tol_ft})\n'
        f'    {{ __receipt["refusal"] = "preserved_layer_changed_by_unit";\n'
        f'      __receipt["preserved_layer_index"] = {row["index"]}; return __receipt; }}\n'
        for row in diff["preserved_layers"])
    return (_PREAMBLE.format(schema=_cs(TRANSACTION_UNIT_SCHEMA), section=_cs(plan.section),
                             owner=_cs(plan.transaction_owner), digest=_cs(plan.digest),
                             uid=_cs(plan.unique_id))
            + f"""HostObjAttributes __ht = __el as HostObjAttributes;
if (__ht == null) {{ __receipt["refusal"] = "unit_target_kind"; return __receipt; }}
CompoundStructure __cs = __ht.GetCompoundStructure();
if (__cs == null) {{ __receipt["refusal"] = "compound_structure_missing"; return __receipt; }}
IList<CompoundStructureLayer> __before = __cs.GetLayers();
// ФАЗА 1 — observe-before. Пишутся ВСЕ слои: «сохранение остального» проверяется
// числами до и после, а не обещанием, что тронут ровно один индекс.
var __beforeRows = new List<object>();
for (int __i = 0; __i < __before.Count; __i++)
    __beforeRows.Add(new Dictionary<string, object> {{
        {{ "index", __i }}, {{ "width_ft", __before[__i].Width }},
        {{ "function", __before[__i].Function.ToString() }} }});
__receipt["observe_before"] = __beforeRows;
__receipt["phase"] = "observed_before";
if (__before.Count != {count})
{{ __receipt["refusal"] = "layer_count_changed_since_observation"; return __receipt; }}
if (Math.Abs(__before[{index}].Width - {before_ft}) > {tol_ft})
{{ __receipt["refusal"] = "layer_width_changed_since_observation"; return __receipt; }}
{preserved}// Сумма пирога — отдельная величина, а не следствие сверки слоёв:
// совпадение каждого перечисленного слоя не запрещает ПОЯВЛЕНИЮ слоя, которого
// план не знал. Толщина конструкции поэтому проверяется целым, до и после.
double __sumBefore = 0.0;
for (int __i = 0; __i < __before.Count; __i++) __sumBefore += __before[__i].Width;
__receipt["total_width_before_ft"] = __sumBefore;
if (Math.Abs(__sumBefore - {total_before_ft}) > {tol_ft})
{{ __receipt["refusal"] = "total_width_changed_since_observation"; return __receipt; }}
// ФАЗА 2 — единица. СВОЯ транзакция, открытая и закрытая здесь.
using (Transaction __ut = new Transaction(doc, "KIR unit: wall type layer width"))
{{
    if (__ut.Start() != TransactionStatus.Started)
    {{ __receipt["refusal"] = "unit_transaction_not_started"; return __receipt; }}
    var __fho = __ut.GetFailureHandlingOptions();
    __fho.SetFailuresPreprocessor(new __KirUnitFailures());
    __fho.SetForcedModalHandling(false);
    __ut.SetFailureHandlingOptions(__fho);
    try
    {{
        __cs.SetLayerWidth({index}, {after_ft});
        __ht.SetCompoundStructure(__cs);
    }}
    catch (Exception __ex)
    {{
        try {{ if (__ut.HasStarted() && !__ut.HasEnded()) __ut.RollBack(); }} catch {{ }}
        __receipt["refusal"] = "unit_set_failed";
        __receipt["detail"] = __ex.Message;
        return __receipt;
    }}
    var __status = __ut.Commit();
    __receipt["commit_status"] = __status.ToString();
    if (__status != TransactionStatus.Committed)
    {{
        try {{ if (__ut.HasStarted() && !__ut.HasEnded()) __ut.RollBack(); }} catch {{ }}
        __receipt["refusal"] = "unit_transaction_not_committed";
        return __receipt;
    }}
    // НЕГАТИВ ПОСЛЕ COMMIT: закрытость транзакции — свойство, а не надежда.
    if (!__ut.HasEnded())
    {{ __receipt["refusal"] = "unit_transaction_still_open"; return __receipt; }}
}}
// Коммит состоялся. Дальше НИЧТО не имеет права назвать это откатом.
__receipt["effect"] = "committed";
__receipt["phase"] = "unit_committed";
// 🔴 С ЭТОЙ СТРОКИ И ДО ПРОВЕРЕННОГО НАБЛЮДЕНИЯ СОСТОЯНИЕ ИМЕННО ТАКОЕ.
// Обрыв где угодно дальше (перезапуск, потеря ответа, исключение в чтении)
// оставляет в квитанции "committed_unverified", а НЕ ok и НЕ откат: эффект
// состоялся, проверен он не был, и эти два факта нельзя складывать в один.
__receipt["state"] = "committed_unverified";
if (__KirUnitFailures.Seen.Count > 0) __receipt["revit_failures"] = __KirUnitFailures.Seen;
// ФАЗА 3 — observe-after НЕЗАВИСИМО: перечитываем из документа, а не из __cs.
try
{{
    Element __again = doc.GetElement({_cs(plan.unique_id)});
    HostObjAttributes __ht2 = __again as HostObjAttributes;
    if (__ht2 == null || __again.UniqueId != {_cs(plan.unique_id)})
    {{ __receipt["observe_after"] = "identity_lost"; return __receipt; }}
    CompoundStructure __cs2 = __ht2.GetCompoundStructure();
    if (__cs2 == null) {{ __receipt["observe_after"] = "compound_structure_missing"; return __receipt; }}
    IList<CompoundStructureLayer> __after = __cs2.GetLayers();
    var __afterRows = new List<object>();
    for (int __i = 0; __i < __after.Count; __i++)
        __afterRows.Add(new Dictionary<string, object> {{
            {{ "index", __i }}, {{ "width_ft", __after[__i].Width }},
            {{ "function", __after[__i].Function.ToString() }} }});
    __receipt["observe_after"] = __afterRows;
    __receipt["phase"] = "observed_after";
{preserved_after}    double __sumAfter = 0.0;
    for (int __i = 0; __i < __after.Count; __i++) __sumAfter += __after[__i].Width;
    __receipt["total_width_after_ft"] = __sumAfter;
    bool __good = __after.Count == {count}
        && Math.Abs(__after[{index}].Width - {after_ft}) <= {tol_ft}
        && Math.Abs(__sumAfter - {total_after_ft}) <= {tol_ft};
    __receipt["target_layer_verified"] = __good;
    __receipt["ok"] = __good;
    if (__good) __receipt["state"] = "committed_verified";
    else __receipt["refusal"] = "after_observation_disagrees";
}}
catch (Exception __ex2)
{{
    // ЧАСТИЧНЫЕ ФАКТЫ СОХРАНЯЮТСЯ: effect остаётся committed.
    __receipt["observe_after"] = "unavailable";
    __receipt["observe_after_detail"] = __ex2.Message;
    __receipt["refusal"] = "after_observation_unavailable";
}}
return __receipt;
""" + _HELPERS + _HELPERS_TAIL)


def _cs_array(values) -> str:
    """A C# string array. The list is emitted as a LOOP, not unrolled code:
    a type's user scope can run to thousands of elements, and unrolling
    would hit the source-size budget before it hit meaning."""
    return "new string[] { " + ", ".join(_cs(str(v)) for v in values) + " }"


def _wall_type_duplicate_cs(plan: TransactionUnitPlan) -> str:
    diff, ownership = plan.diff, plan.ownership
    changed = diff["changed"][0]
    index, count = changed["index"], diff["observed_layer_count"]
    after_ft = _feet_literal(changed["after_mm"])
    tol_ft = _feet_literal(diff["tolerance_mm"])
    source_total_ft = _feet_literal(diff["source_total_width_mm"])
    dup_total_ft = _feet_literal(diff["expected_total_width_mm"])
    uid = _cs(plan.unique_id)
    name = _cs(ownership["new_type_name"])
    replacement_schema = _cs(IDENTITY_REPLACEMENT_SCHEMA)
    # The source layer stack is obligated to stay INTACT — layer by layer,
    # not just by sum.
    source_before = "".join(
        f'if (Math.Abs(__before[{row["index"]}].Width - {_feet_literal(row["width_mm"])}) > {tol_ft})\n'
        f'{{ __receipt["refusal"] = "source_layer_changed_since_observation";\n'
        f'  __receipt["source_layer_index"] = {row["index"]}; return __receipt; }}\n'
        for row in diff["source_layers_unchanged"])
    source_after = "".join(
        f'    if (Math.Abs(__srcAfter[{row["index"]}].Width - {_feet_literal(row["width_mm"])}) > {tol_ft})\n'
        f'    {{ __receipt["refusal"] = "source_type_was_modified";\n'
        f'      __receipt["source_layer_index"] = {row["index"]}; return __receipt; }}\n'
        for row in diff["source_layers_unchanged"])
    dup_after = "".join(
        f'    if (Math.Abs(__dupLayers[{row["index"]}].Width - {_feet_literal(row["width_mm"])}) > {tol_ft})\n'
        f'    {{ __receipt["refusal"] = "duplicate_layer_disagrees";\n'
        f'      __receipt["duplicate_layer_index"] = {row["index"]}; return __receipt; }}\n'
        for row in diff["duplicate_layers"])
    return (_PREAMBLE.format(schema=_cs(TRANSACTION_UNIT_SCHEMA), section=_cs(plan.section),
                             owner=_cs(plan.transaction_owner), digest=_cs(plan.digest),
                             uid=uid)
            + f"""__receipt["identity_replacement"] = "duplicate_and_reassign";
ElementType __srcType = __el as ElementType;
HostObjAttributes __ht = __el as HostObjAttributes;
if (__srcType == null || __ht == null)
{{ __receipt["refusal"] = "unit_target_kind"; return __receipt; }}
CompoundStructure __cs = __ht.GetCompoundStructure();
if (__cs == null) {{ __receipt["refusal"] = "compound_structure_missing"; return __receipt; }}
IList<CompoundStructureLayer> __before = __cs.GetLayers();
string[] __reassign = {_cs_array(ownership["reassign_unique_ids"])};
string[] __retained = {_cs_array(ownership["retained_on_source_unique_ids"])};
ElementId __srcId = __el.Id;
// ФАЗА 1 — observe-before: пирог исходного типа и тип КАЖДОГО переводимого.
var __beforeRows = new List<object>();
for (int __i = 0; __i < __before.Count; __i++)
    __beforeRows.Add(new Dictionary<string, object> {{
        {{ "index", __i }}, {{ "width_ft", __before[__i].Width }},
        {{ "function", __before[__i].Function.ToString() }} }});
if (__before.Count != {count})
{{ __receipt["refusal"] = "layer_count_changed_since_observation"; return __receipt; }}
{source_before}double __sumBefore = 0.0;
for (int __i = 0; __i < __before.Count; __i++) __sumBefore += __before[__i].Width;
if (Math.Abs(__sumBefore - {source_total_ft}) > {tol_ft})
{{ __receipt["refusal"] = "total_width_changed_since_observation"; return __receipt; }}
var __usersBefore = new List<object>();
for (int __i = 0; __i < __reassign.Length; __i++)
{{
    Element __u = doc.GetElement(__reassign[__i]);
    if (__u == null)
    {{ __receipt["refusal"] = "reassign_target_missing";
       __receipt["missing_unique_id"] = __reassign[__i]; return __receipt; }}
    ElementId __ut = __u.GetTypeId();
    __usersBefore.Add(new Dictionary<string, object> {{
        {{ "unique_id", __reassign[__i] }}, {{ "type_id_before", __ut.ToString() }} }});
    // Перевести можно только то, что СЕЙЧАС сидит на исходном типе: иначе
    // «переназначение» тихо утащило бы чужой элемент с чужого типа.
    if (!__ut.Equals(__srcId))
    {{ __receipt["refusal"] = "reassign_target_not_on_source_type";
       __receipt["unexpected_unique_id"] = __reassign[__i]; return __receipt; }}
}}
__receipt["observe_before"] = new Dictionary<string, object> {{
    {{ "source_layers", __beforeRows }}, {{ "source_total_width_ft", __sumBefore }},
    {{ "reassign_targets", __usersBefore }} }};
__receipt["phase"] = "observed_before";
// КОЛЛИЗИЯ ИМЕНИ — ДО ЛЮБОГО ЭФФЕКТА. Имя дубля приходит из плана, значит
// столкновение это НАШ предмет: Revit ответил бы исключением уже после того,
// как транзакция открыта, и отказ пришёл бы дороже.
int __named = 0;
var __types = new FilteredElementCollector(doc).OfClass(typeof(ElementType));
foreach (ElementType __t in __types)
{{ if (String.Equals(__t.Name, {name}, StringComparison.Ordinal)) __named++; }}
__receipt["name_matches_before"] = __named;
if (__named > 0)
{{ __receipt["refusal"] = "duplicate_name_collides"; return __receipt; }}
// ФАЗА 2 — единица. СВОЯ транзакция: дубль, его пирог, перевод выбранных.
ElementId __dupId = ElementId.InvalidElementId;
string __dupUid = null;
var __moved = new List<object>();
// UniqueId, по которому наблюдение-ПОСЛЕ будет искать каждого переведённого.
// Совпадает со старым, пока замены не было; при замене — адрес НОВОГО элемента.
string[] __replacement = new string[__reassign.Length];
using (Transaction __ut2 = new Transaction(doc, "KIR unit: duplicate wall type"))
{{
    if (__ut2.Start() != TransactionStatus.Started)
    {{ __receipt["refusal"] = "unit_transaction_not_started"; return __receipt; }}
    var __fho = __ut2.GetFailureHandlingOptions();
    __fho.SetFailuresPreprocessor(new __KirUnitFailures());
    __fho.SetForcedModalHandling(false);
    __ut2.SetFailureHandlingOptions(__fho);
    try
    {{
        // `GetCompoundStructure` отдаёт КОПИЮ: правка __cs и применение её к
        // ДУБЛЮ не трогают исходный тип. Именно поэтому «старый тип цел» —
        // свойство кода, а не обещание.
        __cs.SetLayerWidth({index}, {after_ft});
        ElementType __dupType = __srcType.Duplicate({name});
        HostObjAttributes __dupHost = __dupType as HostObjAttributes;
        if (__dupHost == null)
        {{
            try {{ if (__ut2.HasStarted() && !__ut2.HasEnded()) __ut2.RollBack(); }} catch {{ }}
            __receipt["refusal"] = "duplicate_kind_unexpected"; return __receipt;
        }}
        __dupHost.SetCompoundStructure(__cs);
        __dupId = __dupType.Id;
        __dupUid = __dupType.UniqueId;
        for (int __i = 0; __i < __reassign.Length; __i++)
        {{
            Element __u = doc.GetElement(__reassign[__i]);
            // Снимаем адрес и тип ДО вызова: при замене старый объект мёртв,
            // и обращение к нему после вызова — уже не чтение, а гадание.
            ElementId __wasId = __u.Id;
            ElementId __wasType = __u.GetTypeId();
            ElementId __newElement = __u.ChangeTypeId(__dupId);
            bool __replaced = __newElement != null
                && !__newElement.Equals(ElementId.InvalidElementId)
                && !__newElement.Equals(__wasId);
            Element __live = doc.GetElement(__replaced ? __newElement : __wasId);
            __replacement[__i] = __live == null ? null : __live.UniqueId;
            __moved.Add(new Dictionary<string, object> {{
                {{ "schema", {replacement_schema} }},
                {{ "old_unique_id", __reassign[__i] }},
                {{ "new_unique_id", __replacement[__i] }},
                {{ "identity_replaced", __replaced }},
                {{ "old_element_id", __wasId.ToString() }},
                {{ "new_element_id", __replaced ? __newElement.ToString() : __wasId.ToString() }},
                {{ "type_id_before", __wasType.ToString() }} }});
        }}
    }}
    catch (Exception __ex)
    {{
        try {{ if (__ut2.HasStarted() && !__ut2.HasEnded()) __ut2.RollBack(); }} catch {{ }}
        __receipt["refusal"] = "unit_set_failed";
        __receipt["detail"] = __ex.Message;
        return __receipt;
    }}
    var __status = __ut2.Commit();
    __receipt["commit_status"] = __status.ToString();
    if (__status != TransactionStatus.Committed)
    {{
        try {{ if (__ut2.HasStarted() && !__ut2.HasEnded()) __ut2.RollBack(); }} catch {{ }}
        __receipt["refusal"] = "unit_transaction_not_committed"; return __receipt;
    }}
    if (!__ut2.HasEnded())
    {{ __receipt["refusal"] = "unit_transaction_still_open"; return __receipt; }}
}}
__receipt["effect"] = "committed";
__receipt["phase"] = "unit_committed";
__receipt["state"] = "committed_unverified";
__receipt["new_type_unique_id"] = __dupUid;
__receipt["new_type_element_id"] = __dupId.ToString();
__receipt["reassigned"] = __moved;
// Ведомость замен ОТДЕЛЬНЫМ полем: потребителю нужна пара old/new, а не
// разбор чужой структуры фазы. Схему и пару полей назвал ведущий.
__receipt["identity_replacements"] = __moved;
__receipt["identity_replacement_schema"] = {replacement_schema};
if (__KirUnitFailures.Seen.Count > 0) __receipt["revit_failures"] = __KirUnitFailures.Seen;
// ФАЗА 3 — observe-after независимым перечитыванием ОБОИХ типов и всех users.
try
{{
    Element __srcAgain = doc.GetElement({uid});
    HostObjAttributes __srcHost = __srcAgain as HostObjAttributes;
    if (__srcHost == null || __srcAgain.UniqueId != {uid})
    {{ __receipt["observe_after"] = "source_identity_lost"; return __receipt; }}
    CompoundStructure __srcCs = __srcHost.GetCompoundStructure();
    if (__srcCs == null)
    {{ __receipt["observe_after"] = "source_structure_missing"; return __receipt; }}
    IList<CompoundStructureLayer> __srcAfter = __srcCs.GetLayers();
    if (__srcAfter.Count != {count})
    {{ __receipt["refusal"] = "source_type_was_modified"; return __receipt; }}
{source_after}    double __srcSum = 0.0;
    for (int __i = 0; __i < __srcAfter.Count; __i++) __srcSum += __srcAfter[__i].Width;
    if (Math.Abs(__srcSum - {source_total_ft}) > {tol_ft})
    {{ __receipt["refusal"] = "source_type_was_modified"; return __receipt; }}
    Element __dupAgain = __dupUid == null ? null : doc.GetElement(__dupUid);
    HostObjAttributes __dupHost2 = __dupAgain as HostObjAttributes;
    if (__dupHost2 == null)
    {{ __receipt["observe_after"] = "duplicate_identity_lost"; return __receipt; }}
    CompoundStructure __dupCs = __dupHost2.GetCompoundStructure();
    if (__dupCs == null)
    {{ __receipt["observe_after"] = "duplicate_structure_missing"; return __receipt; }}
    IList<CompoundStructureLayer> __dupLayers = __dupCs.GetLayers();
    if (__dupLayers.Count != {count})
    {{ __receipt["refusal"] = "duplicate_layer_disagrees"; return __receipt; }}
{dup_after}    double __dupSum = 0.0;
    for (int __i = 0; __i < __dupLayers.Count; __i++) __dupSum += __dupLayers[__i].Width;
    if (Math.Abs(__dupSum - {dup_total_ft}) > {tol_ft})
    {{ __receipt["refusal"] = "duplicate_layer_disagrees"; return __receipt; }}
    var __after = new List<object>();
    bool __good = true;
    for (int __i = 0; __i < __reassign.Length; __i++)
    {{
        // 🔴 ЧИТАЕМ ЖИВОЙ АДРЕС. По старому UniqueId после настоящей замены
        // документ отдаёт null, и «успех» превратился бы в отказ.
        string __liveUid = __replacement[__i];
        Element __u = __liveUid == null ? null : doc.GetElement(__liveUid);
        ElementId __now = __u == null ? ElementId.InvalidElementId : __u.GetTypeId();
        bool __ok = __u != null && __now.Equals(__dupAgain.Id);
        __after.Add(new Dictionary<string, object> {{
            {{ "schema", {replacement_schema} }},
            {{ "old_unique_id", __reassign[__i] }},
            {{ "new_unique_id", __liveUid }},
            {{ "identity_replaced", __liveUid != null && __liveUid != __reassign[__i] }},
            {{ "type_id_after", __now.ToString() }},
            {{ "moved", __ok }} }});
        // Потерянный адрес — ОТДЕЛЬНАЯ причина, а не «не совпал тип»:
        // «элемента нет» и «элемент на чужом типе» — разные факты.
        if (__u == null) __receipt["refusal"] = "reassigned_element_unreadable";
        if (!__ok) __good = false;
    }}
    // Оставленные на исходном типе — тоже свидетели: перевод обязан быть
    // РОВНО по названной области, а не «по всем, кого зацепило».
    var __stay = new List<object>();
    for (int __i = 0; __i < __retained.Length; __i++)
    {{
        Element __u = doc.GetElement(__retained[__i]);
        ElementId __now = __u == null ? ElementId.InvalidElementId : __u.GetTypeId();
        bool __ok = __u != null && __now.Equals(__srcAgain.Id);
        __stay.Add(new Dictionary<string, object> {{
            {{ "unique_id", __retained[__i] }}, {{ "type_id_after", __now.ToString() }},
            {{ "stayed", __ok }} }});
        if (!__ok) __good = false;
    }}
    __receipt["observe_after"] = new Dictionary<string, object> {{
        {{ "source_total_width_ft", __srcSum }}, {{ "duplicate_total_width_ft", __dupSum }},
        {{ "reassigned", __after }}, {{ "retained_on_source", __stay }} }};
    __receipt["phase"] = "observed_after";
    __receipt["ok"] = __good;
    if (__good) __receipt["state"] = "committed_verified";
    else __receipt["refusal"] = "after_observation_disagrees";
}}
catch (Exception __ex2)
{{
    __receipt["observe_after"] = "unavailable";
    __receipt["observe_after_detail"] = __ex2.Message;
    __receipt["refusal"] = "after_observation_unavailable";
}}
return __receipt;
""" + _HELPERS + _HELPERS_TAIL)


#: Clearance the new loop must keep from every existing profile edge, and
#: that every existing vertex must keep from the new loop: 1 mm. Two loops
#: closer than that are, for Revit's sketch, one touching contour.
LOOP_CLEARANCE_MM = 1.0
#: The floor's area after the commit must have dropped by the loop's area,
#: within this band of the loop's area. Below the band material was NOT
#: removed as drawn (a second island adds material, a loop over a shaft
#: removes less); above it the drop is larger than the drawing — a sloped
#: top face reports up to 1/cos of the plan area, and 1.5 admits 48°.
AREA_DROP_RATIO_MIN = 0.98
AREA_DROP_RATIO_MAX = 1.5
_M2_PER_FT2 = 0.09290304


def _floor_sketch_opening_cs(plan: TransactionUnitPlan) -> str:
    loop = plan.diff["added_loops"][0]
    points = "".join(
        f"__new.Add(new double[] {{ {_feet_literal(x)}, {_feet_literal(y)} }});\n" for x, y in loop)
    new_sketch = bool(plan.diff.get("allow_new_sketch"))
    allow_literal = "true" if new_sketch else "false"
    clearance = _feet_literal(LOOP_CLEARANCE_MM)
    if new_sketch:
        # `StartWithNewSketch` throws an ArgumentException if a sketch
        # ALREADY exists (RevitAPI.xml, verbatim). So the before-observation
        # is obligated to see exactly its ABSENCE, and "already exists" is a
        # refusal, not a silent fallback to Start.
        sketch_gate = (
            'if (__sketchId != ElementId.InvalidElementId)\n'
            '{ __receipt["refusal"] = "sketch_already_present"; return __receipt; }\n'
            'int __loopsBefore = 0;\n'
            'int __outerCount = 0, __innerCount = 0, __host = -1;\n'
            '// There is no profile yet: the plane is read INSIDE the scope, where the\n'
            '// sketch comes into being, and the loop cannot be judged against anything.\n'
            'double __z = 0.0;\n')
        scope_start = "__scope.StartWithNewSketch(__el.Id);"
        # The sketch APPEARED inside the edit scope: it is taken fresh from
        # the document, not from the before-observation, where it did not
        # exist by the branch's own definition.
        live_sketch = "doc.GetElement(__fl.SketchId) as Sketch"
        plane_inside = (
            'Plane __plane1 = __plane.GetPlane();\n'
            '        if (Math.Abs(__plane1.Normal.Z) < 0.999999)\n'
            '        {\n'
            '            try { if (__st.HasStarted() && !__st.HasEnded()) __st.RollBack(); } catch { }\n'
            '            __KirUnitGroup.Abandon(__group, __scope);\n'
            '            __receipt["refusal"] = "sketch_plane_not_horizontal"; return __receipt;\n'
            '        }\n'
            '        __z = __plane1.Origin.Z;\n')
        expected_after = "__loopsAfter == 1"
        # A new sketch is not an opening in an existing boundary: the area is
        # RECORDED, not judged, and the plan says so in `unit_acceptance`.
        area_judgement = (
            'bool __areaGood = true;\n'
            '    __receipt["area_judged"] = false;\n')
    else:
        sketch_gate = (
            'if (__sketchId == ElementId.InvalidElementId)\n'
            '{ __receipt["refusal"] = "sketch_missing"; return __receipt; }\n'
            'Sketch __sketch = doc.GetElement(__sketchId) as Sketch;\n'
            'if (__sketch == null) { __receipt["refusal"] = "sketch_unreadable"; return __receipt; }\n'
            'int __loopsBefore = __sketch.Profile.Size;\n'
            + _PROFILE_READ.replace("__CLEARANCE__", clearance))
        scope_start = "__scope.Start(__sketchId);"
        live_sketch = "__sketch"
        plane_inside = ""
        expected_after = "__loopsAfter == __loopsBefore + 1"
        area_judgement = (
            'double __drop = __areaBefore - __areaAfter;\n'
            '    double __ratio = __loopArea > 0.0 ? __drop / __loopArea : 0.0;\n'
            f'    bool __areaGood = __areaAfter < __areaBefore && __ratio >= {AREA_DROP_RATIO_MIN!r}'
            f' && __ratio <= {AREA_DROP_RATIO_MAX!r};\n'
            '    __receipt["area_judged"] = true;\n'
            f'    __receipt["area_drop_m2"] = __drop * {_M2_PER_FT2!r};\n'
            '    __receipt["area_drop_ratio"] = __ratio;\n')
    return (_PREAMBLE.format(schema=_cs(TRANSACTION_UNIT_SCHEMA), section=_cs(plan.section),
                             owner=_cs(plan.transaction_owner), digest=_cs(plan.digest),
                             uid=_cs(plan.unique_id))
            + f"""Floor __fl = __el as Floor;
if (__fl == null) {{ __receipt["refusal"] = "unit_target_kind"; return __receipt; }}
ElementId __sketchId = __fl.SketchId;
// The loop, in feet, in the world XY chart. The z of the sketch plane is
// taken from the plane itself, never assumed: NewModelCurve refuses a curve
// that is not in the plane, and a floor on an upper level is not at z=0.
var __new = new List<double[]>();
{points}double __loopArea = Math.Abs(__KirLoop2D.Area2(__new)) / 2.0;
if (__new.Count < 3 || __loopArea <= 0.0 || !__KirLoop2D.IsSimple(__new))
{{ __receipt["refusal"] = "loop_self_intersecting"; return __receipt; }}
{sketch_gate}// The area is the after-witness of the opening: without it the unit
// could not tell an opening from an island, so it does not start.
Parameter __areaP = __fl.get_Parameter(BuiltInParameter.HOST_AREA_COMPUTED);
if (__areaP == null || !__areaP.HasValue)
{{ __receipt["refusal"] = "floor_area_unreadable"; return __receipt; }}
double __areaBefore = __areaP.AsDouble();
// ФАЗА 1 — observe-before: the profile as it is, the area as it is.
__receipt["observe_before"] = new Dictionary<string, object> {{
    {{ "sketch_id", __sketchId.ToString() }}, {{ "profile_loops", __loopsBefore }},
    {{ "outer_loops", __outerCount }}, {{ "inner_loops", __innerCount }},
    {{ "host_loop_index", __host }},
    {{ "area_m2", __areaBefore * {_M2_PER_FT2!r} }}, {{ "loop_area_m2", __loopArea * {_M2_PER_FT2!r} }},
    {{ "new_sketch_allowed", {allow_literal} }} }};
__receipt["phase"] = "observed_before";
// ФАЗА 2 — единица. The unit owns a TransactionGroup: the scope's commits
// live inside it, and a disagreement after the commit undoes them as one.
// SketchEditScope.Start requires that no TRANSACTION be active (checked
// above); a group is not a transaction, and the native witness of 09.09
// ran this very unit inside an outer group.
TransactionGroup __group = new TransactionGroup(doc, "KIR unit: floor sketch opening");
if (__group.Start() != TransactionStatus.Started)
{{ __receipt["refusal"] = "unit_group_not_started"; return __receipt; }}
SketchEditScope __scope = new SketchEditScope(doc, "KIR unit: floor sketch opening");
try
{{
    {scope_start}
    using (Transaction __st = new Transaction(doc, "KIR unit: sketch loop"))
    {{
        if (__st.Start() != TransactionStatus.Started)
        {{
            __KirUnitGroup.Abandon(__group, __scope);
            __receipt["refusal"] = "unit_transaction_not_started";
            return __receipt;
        }}
        Sketch __live = {live_sketch};
        if (__live == null)
        {{
            try {{ if (__st.HasStarted() && !__st.HasEnded()) __st.RollBack(); }} catch {{ }}
            __KirUnitGroup.Abandon(__group, __scope);
            __receipt["refusal"] = "sketch_unreadable"; return __receipt;
        }}
        SketchPlane __plane = __live.SketchPlane;
        {plane_inside}var __pts = new List<XYZ>();
        foreach (double[] __v in __new) __pts.Add(new XYZ(__v[0], __v[1], __z));
        for (int __i = 0; __i < __pts.Count; __i++)
        {{
            XYZ __a = __pts[__i];
            XYZ __b = __pts[(__i + 1) % __pts.Count];
            doc.Create.NewModelCurve(Line.CreateBound(__a, __b), __plane);
        }}
        var __status = __st.Commit();
        __receipt["commit_status"] = __status.ToString();
        if (__status != TransactionStatus.Committed)
        {{
            try {{ if (__st.HasStarted() && !__st.HasEnded()) __st.RollBack(); }} catch {{ }}
            __KirUnitGroup.Abandon(__group, __scope);
            __receipt["refusal"] = "unit_transaction_not_committed";
            return __receipt;
        }}
    }}
    __scope.Commit(new __KirUnitFailures());
}}
catch (Exception __ex)
{{
    __KirUnitGroup.Abandon(__group, __scope);
    __receipt["refusal"] = "sketch_edit_scope_failed";
    __receipt["detail"] = __ex.Message;
    return __receipt;
}}
// НЕГАТИВ ПОСЛЕ COMMIT: область правки обязана быть закрыта.
if (__scope.IsActive)
{{
    __KirUnitGroup.Abandon(__group, __scope);
    __receipt["refusal"] = "sketch_edit_scope_still_active"; return __receipt;
}}
__receipt["effect"] = "committed";
__receipt["phase"] = "unit_committed";
// Until the after-observation AGREES the state is exactly this; a break
// anywhere below turns into a rollback of the group, never into ok.
__receipt["state"] = "committed_unverified";
if (__KirUnitFailures.Seen.Count > 0) __receipt["revit_failures"] = __KirUnitFailures.Seen;
// ФАЗА 3 — observe-after: the sketch re-read, the area re-read.
try
{{
    Element __again = doc.GetElement({_cs(plan.unique_id)});
    Floor __fl2 = __again as Floor;
    if (__fl2 == null || __again.UniqueId != {_cs(plan.unique_id)})
    {{
        bool __undoneId = __KirUnitGroup.Abandon(__group, null);
        __receipt["observe_after"] = "identity_lost";
        __receipt["effect"] = __undoneId ? "rolled_back" : "committed";
        __receipt["state"] = __undoneId ? "rolled_back" : "committed_unverified";
        __receipt["refusal"] = "after_observation_disagrees";
        return __receipt;
    }}
    Sketch __sketch2 = doc.GetElement(__fl2.SketchId) as Sketch;
    Parameter __areaP2 = __fl2.get_Parameter(BuiltInParameter.HOST_AREA_COMPUTED);
    if (__sketch2 == null || __areaP2 == null || !__areaP2.HasValue)
    {{
        bool __undoneRead = __KirUnitGroup.Abandon(__group, null);
        __receipt["observe_after"] = __sketch2 == null ? "sketch_unreadable" : "floor_area_unreadable";
        __receipt["effect"] = __undoneRead ? "rolled_back" : "committed";
        __receipt["state"] = __undoneRead ? "rolled_back" : "committed_unverified";
        __receipt["refusal"] = "after_observation_unavailable";
        return __receipt;
    }}
    int __loopsAfter = __sketch2.Profile.Size;
    double __areaAfter = __areaP2.AsDouble();
    __receipt["sketch_id_after"] = __fl2.SketchId.ToString();
    __receipt["observe_after"] = new Dictionary<string, object> {{
        {{ "profile_loops", __loopsAfter }}, {{ "area_m2", __areaAfter * {_M2_PER_FT2!r} }} }};
    __receipt["phase"] = "observed_after";
    bool __loopsGood = {expected_after};
    {area_judgement}    bool __good = __loopsGood && __areaGood;
    __receipt["loop_added"] = __loopsGood;
    __receipt["area_removed"] = __areaGood;
    if (__good)
    {{
        __group.Assimilate();
        __receipt["ok"] = true;
        __receipt["state"] = "committed_verified";
    }}
    else
    {{
        // The edit is undone as one step: a receipt that disagrees with
        // its own drawing leaves nothing behind in the document.
        bool __undone = __KirUnitGroup.Abandon(__group, null);
        __receipt["effect"] = __undone ? "rolled_back" : "committed";
        __receipt["state"] = __undone ? "rolled_back" : "committed_unverified";
        __receipt["refusal"] = __loopsGood ? "opening_area_disagrees" : "after_observation_disagrees";
    }}
}}
catch (Exception __ex2)
{{
    bool __undoneEx = __KirUnitGroup.Abandon(__group, null);
    __receipt["observe_after"] = "unavailable";
    __receipt["observe_after_detail"] = __ex2.Message;
    __receipt["effect"] = __undoneEx ? "rolled_back" : "committed";
    __receipt["state"] = __undoneEx ? "rolled_back" : "committed_unverified";
    __receipt["refusal"] = "after_observation_unavailable";
}}
return __receipt;
""" + _HELPERS + _FLOOR_HELPERS + _HELPERS_TAIL)


#: The profile read BEFORE the scope opens, and the judgement of the new
#: loop against it. Every refusal here happens before any effect. Curves are
#: tessellated (a line gives its two ends, an arc a polyline) and chained by
#: proximity, because a sketch's CurveArray does not promise head-to-tail
#: direction. Nesting depth by even-odd containment: even = an outer
#: boundary, odd = an existing opening.
_PROFILE_READ = r"""Plane __plane0 = __sketch.SketchPlane.GetPlane();
if (Math.Abs(__plane0.Normal.Z) < 0.999999)
{ __receipt["refusal"] = "sketch_plane_not_horizontal"; return __receipt; }
double __z = __plane0.Origin.Z;
var __loops = new List<List<double[]>>();
foreach (CurveArray __ca in __sketch.Profile)
{
    var __ring = new List<double[]>();
    foreach (Curve __c in __ca)
    {
        IList<XYZ> __t = __c.Tessellate();
        if (__t == null || __t.Count < 2) continue;
        var __seq = new List<XYZ>(__t);
        if (__ring.Count > 0)
        {
            double[] __last = __ring[__ring.Count - 1];
            XYZ __f = __seq[0], __l = __seq[__seq.Count - 1];
            double __df = (__f.X - __last[0]) * (__f.X - __last[0]) + (__f.Y - __last[1]) * (__f.Y - __last[1]);
            double __dl = (__l.X - __last[0]) * (__l.X - __last[0]) + (__l.Y - __last[1]) * (__l.Y - __last[1]);
            if (__dl < __df) __seq.Reverse();
        }
        foreach (XYZ __q in __seq)
        {
            if (__ring.Count > 0)
            {
                double[] __last = __ring[__ring.Count - 1];
                if (Math.Abs(__last[0] - __q.X) < 1e-9 && Math.Abs(__last[1] - __q.Y) < 1e-9) continue;
            }
            __ring.Add(new double[] { __q.X, __q.Y });
        }
    }
    if (__ring.Count > 1)
    {
        double[] __a0 = __ring[0], __an = __ring[__ring.Count - 1];
        if (Math.Abs(__a0[0] - __an[0]) < 1e-9 && Math.Abs(__a0[1] - __an[1]) < 1e-9) __ring.RemoveAt(__ring.Count - 1);
    }
    if (__ring.Count >= 3) __loops.Add(__ring);
}
if (__loops.Count == 0) { __receipt["refusal"] = "profile_unreadable"; return __receipt; }
var __depth = new int[__loops.Count];
for (int __i = 0; __i < __loops.Count; __i++)
    for (int __j = 0; __j < __loops.Count; __j++)
        if (__i != __j && __KirLoop2D.Contains(__loops[__j], __loops[__i][0][0], __loops[__i][0][1])) __depth[__i]++;
int __outerCount = 0, __innerCount = 0;
for (int __i = 0; __i < __loops.Count; __i++) { if (__depth[__i] % 2 == 0) __outerCount++; else __innerCount++; }
// The host: the DEEPEST outer boundary holding every vertex of the loop.
int __host = -1;
for (int __i = 0; __i < __loops.Count; __i++)
{
    if (__depth[__i] % 2 != 0) continue;
    int __in = __KirLoop2D.VerticesInside(__loops[__i], __new);
    if (__in == __new.Count) { if (__host < 0 || __depth[__i] > __depth[__host]) __host = __i; }
    else if (__in > 0)
    {
        __receipt["refusal"] = "loop_crosses_profile";
        __receipt["detail"] = "vertices inside outer boundary " + __i.ToString() + ": " + __in.ToString() + " of " + __new.Count.ToString();
        return __receipt;
    }
}
if (__host < 0)
{
    __receipt["refusal"] = "loop_outside_profile";
    __receipt["detail"] = "no outer boundary of the profile holds the loop; outer loops: " + __outerCount.ToString();
    return __receipt;
}
for (int __j = 0; __j < __loops.Count; __j++)
{
    if (__KirLoop2D.RingsCross(__new, __loops[__j]))
    { __receipt["refusal"] = "loop_crosses_profile"; __receipt["detail"] = "edge crossing with profile loop " + __j.ToString(); return __receipt; }
    if (__KirLoop2D.Clearance(__new, __loops[__j]) < __CLEARANCE__)
    { __receipt["refusal"] = "loop_touches_profile"; __receipt["detail"] = "closer than 1 mm to profile loop " + __j.ToString(); return __receipt; }
    if (__j != __host && __KirLoop2D.VerticesInside(__new, __loops[__j]) > 0)
    { __receipt["refusal"] = "loop_encloses_existing_loop"; __receipt["detail"] = "profile loop " + __j.ToString() + " lies inside the new loop"; return __receipt; }
    // An opening DIRECTLY in the host (one level deeper, held by it): the
    // loop may not sit in it. An island's own openings are deeper still and
    // are judged through their own host, not through this one.
    if (__depth[__j] == __depth[__host] + 1
        && __KirLoop2D.Contains(__loops[__host], __loops[__j][0][0], __loops[__j][0][1])
        && __KirLoop2D.VerticesInside(__loops[__j], __new) > 0)
    { __receipt["refusal"] = "loop_inside_existing_opening"; __receipt["detail"] = "the loop lies in existing opening " + __j.ToString(); return __receipt; }
}
"""


#: (section, identity-replacement policy) → emitter. The key is a PAIR on
#: purpose: the policy changes not a detail but the subject itself — whether
#: an existing type is edited or a new one is created.
_EMITTERS = {("wall_type_layer_width", "in_place"): _wall_type_layer_width_cs,
             ("wall_type_layer_width", "duplicate_and_reassign"): _wall_type_duplicate_cs,
             ("floor_sketch_opening", "in_place"): _floor_sketch_opening_cs}


def emit_transaction_unit_cs(plan: TransactionUnitPlan) -> str:
    """The Execute body for the unit. Does NOT go through the
    `authoring.emit_program` frame."""
    _require(type(plan) is TransactionUnitPlan, "transaction_unit_plan_required",
             "сохранённая запись не эмитируется: нужен свежий план")
    key = (plan.section, plan.identity_replacement)
    _require(key in _EMITTERS, "unknown_section",
             f"нет эмиттера для {key}")
    return _EMITTERS[key](plan)


# ───────────────────────────────────── the prepared unit ──


@dataclass(frozen=True, slots=True, init=False)
class PreparedTransactionUnit:
    """A fresh preparation of the unit. A stored record is never loaded into
    this."""

    plan: TransactionUnitPlan = field(repr=False)
    target: RuntimeTarget
    precondition: ContextPrecondition
    operation_id: str
    source: str = field(repr=False)
    source_sha256: str

    def __init__(self, *args, **kwargs):
        raise TypeError("используйте prepare_transaction_unit(); запись — не свежая эмиссия")

    def binding_dict(self) -> dict:
        return {"schema": TRANSACTION_UNIT_SCHEMA, "target": self.target.to_dict(),
                "precondition": self.precondition.to_dict(), "operation_id": self.operation_id,
                "source_sha256": self.source_sha256, "plan_digest": self.plan.digest,
                "section": self.plan.section, "transaction_owner": self.plan.transaction_owner}

    def execute_request(self, credentials, *, request_id: str, timeout_ms: int = 120000) -> dict:
        from kir.revit_connector import SessionCredentials, _request
        _require(type(credentials) is SessionCredentials and credentials.target == self.target,
                 "target_mismatch", "единица принадлежит другому runtime/журналу")
        return _request(credentials, request_id, "execute", timeout_ms,
                        operation_id=self.operation_id, source=self.source,
                        source_sha256=self.source_sha256,
                        precondition=self.precondition.to_dict())

    def recovery_request(self, credentials, *, request_id: str) -> dict:
        """Read-only recovery. A restart does NOT reopen the effect."""
        from kir.revit_connector import _request
        return _request(credentials, request_id, "recover_receipt", 30000,
                        recovery_target=self.target.to_dict(), operation_id=self.operation_id)


def prepare_transaction_unit(plan: TransactionUnitPlan, *, operation_id: str) -> PreparedTransactionUnit:
    """Wrap the unit with ITS OWN wrapper, bypassing the frame carrying
    `Transaction __t`.

    The check does not take anyone's word for it: the assembled source is
    obligated to contain EXACTLY one transaction, opened by the unit itself,
    and not a single foreign frame `__t`.
    """
    from kir.revit_connector import MAX_SOURCE_CHARS, _uuid

    _require(type(plan) is TransactionUnitPlan, "transaction_unit_plan_required")
    identifier = _uuid(operation_id, "operation_id")
    body = emit_transaction_unit_cs(plan)
    source = wrap_connector_source(body)
    # A unit that ended up in the emitter's frame is this module's central
    # refusal. TWO GUARDS, TWO DIFFERENT CAUSES, AND BOTH ARE NECESSARY.
    # The first answers ONE question: did the body end up in the emitter's
    # frame (`__t` — its name, and only its name). The second answers
    # another: did the unit itself open an extra transaction under any name.
    # While their code was shared, removing the first left the test green —
    # the second answered with the same word, and the mutation stayed silent
    # (measured 07.09: 2 green out of 6 controls).
    _require("Transaction __t = new Transaction(doc," not in source,
             "transaction_owner_conflict",
             "тело единицы обёрнуто каркасом эмиттера; владение транзакцией потеряно")
    expected = _OWN_TRANSACTIONS[plan.transaction_owner]
    actual = source.count("new Transaction(doc")
    _require(actual == expected, "transaction_count_unexpected",
             f"единица открывает {actual} своих транзакций вместо {expected}")
    if plan.transaction_owner == SKETCH_OWNER:
        _require("new SketchEditScope(doc" in source, "sketch_scope_missing")
    _require("if (doc.IsModifiable)" in source, "no_start_negative_missing",
             "у единицы нет негатива «активная транзакция запрещает единицу»")
    _require(len(source.encode("utf-16-le")) // 2 <= MAX_SOURCE_CHARS,
             "source_budget_exceeded", "источник единицы превышает предел коннектора")
    prepared = object.__new__(PreparedTransactionUnit)
    for name, value in {"plan": plan, "target": plan.target, "precondition": plan.precondition,
                        "operation_id": identifier, "source": source,
                        "source_sha256": hashlib.sha256(source.encode("utf-8")).hexdigest()}.items():
        object.__setattr__(prepared, name, value)
    return prepared


# ──────────────────────────── effect reservation (no repeat) ──


def _ledger_lock(path):
    """Mutual exclusion BETWEEN PROCESSES for the duration of reading and
    writing the journal.

    🔴 BOUGHT BY THE 07.09 PROBE. The first revision read the journal, then
    wrote it via `os.replace`. In ONE process this looked flawless and the
    test was green. Two processes with the same plan both got past the
    reservation — 2 of 2, where exactly one is obligated to get through. A
    "no file — so it's allowed" check is worthless if a second process
    manages to slip in between the check and the write.
    """
    import fcntl

    handle = open(path + ".lock", "a+b")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
    except OSError:
        handle.close()
        raise
    return handle


def _release(handle):
    import fcntl

    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        handle.close()


def _read_reservation(path):
    import os

    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as handle:
        value = json.load(handle)
    _require(isinstance(value, dict) and value.get("schema") == TRANSACTION_UNIT_RESERVATION_SCHEMA,
             "unknown_reservation_schema")
    return value


def _encode(payload):
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, allow_nan=False).encode("utf-8")


def _create_reservation(path, payload):
    """The FIRST write — `O_EXCL` only, and this is not a duplicate of the
    lock.

    The lock serializes readers and writers WITHIN THIS TREE; `O_EXCL` is the
    one thing that remains true if a second writer did not take the lock (a
    foreign script, a different version, a manual run). Reserving an effect
    is too expensive a thing to rest on a single convention alone.
    """
    import os

    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        os.write(descriptor, _encode(payload))
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return payload


def _replace_reservation(path, payload):
    import os

    temp = f"{path}.{os.getpid()}.tmp"
    descriptor = os.open(temp, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        os.write(descriptor, _encode(payload))
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.replace(temp, path)
    return payload


def reserve_transaction_unit(prepared: PreparedTransactionUnit, *, ledger_path: str) -> dict:
    """Write the intent BEFORE the effect. A second pass over the same plan
    is a refusal.

    A process restart reads the same record: the `reserved` state means the
    effect MAY have occurred, and only a read-only recovery is allowed.
    A not_found from the far end is not proof that "nothing was started".

    The race between two PROCESSES is closed by the lock and `O_EXCL`; the
    probe `.work/marathon-fable-20260907/native/probe/race.py` prints how
    many reservations got through, and it is obligated to print 1.
    """
    _require(type(prepared) is PreparedTransactionUnit, "prepared_transaction_unit_required")
    payload = {"schema": TRANSACTION_UNIT_RESERVATION_SCHEMA, "state": "reserved",
               "operation_id": prepared.operation_id, "plan_digest": prepared.plan.digest,
               "source_sha256": prepared.source_sha256, "target": prepared.target.to_dict(),
               "precondition": prepared.precondition.to_dict(),
               "section": prepared.plan.section,
               "transaction_owner": prepared.plan.transaction_owner,
               "receipt": None, "claims": dict(_NOT_ESTABLISHED)}
    handle = _ledger_lock(ledger_path)
    try:
        existing = _read_reservation(ledger_path)
        if existing is not None:
            _require(existing["operation_id"] == prepared.operation_id
                     and existing["plan_digest"] == prepared.plan.digest
                     and existing["source_sha256"] == prepared.source_sha256,
                     "ledger_operation_conflict",
                     "в журнале уже другая единица под этим адресом")
            raise TransactionUnitRefusal(
                "effect_already_reserved",
                f"эффект уже зарезервирован (состояние {existing['state']}); "
                "перезапуск восстанавливает квитанцию, а не повторяет отправку")
        try:
            return _create_reservation(ledger_path, payload)
        except FileExistsError as error:
            # Someone else already holds the lock. A refusal, not an
            # overwrite.
            raise TransactionUnitRefusal(
                "effect_already_reserved",
                "журнал создан другим процессом между проверкой и записью") from error
    finally:
        _release(handle)


def settle_transaction_unit(prepared: PreparedTransactionUnit, *, ledger_path: str,
                            receipt: Mapping | None, outcome: str) -> dict:
    """Close the reservation with a fact. A partial fact is stored as a
    fact.

    `outcome` — `committed`, `refused`, or `unknown`. `unknown` does NOT
    become "it didn't happen": it stays in the journal and forbids a repeat
    submission.

    The receipt OUTRANKS the caller's own word here: if the unit itself said
    `state="committed_unverified"`, the outcome cannot be named `committed`.
    Otherwise a break in the middle of the after-observation would turn into
    "verified" with a single line on the Python side.
    """
    _require(type(prepared) is PreparedTransactionUnit, "prepared_transaction_unit_required")
    _require(outcome in ("committed", "refused", "unknown"), "unknown_outcome")
    stated = (receipt or {}).get("state") if isinstance(receipt, Mapping) else None
    if outcome == "committed":
        _require(stated == "committed_verified", "receipt_is_not_verified",
                 f"квитанция говорит {stated!r}; проверенным коммитом это не является")
    if stated == "committed_unverified":
        _require(outcome == "unknown", "receipt_says_unverified",
                 "коммит без проверенного наблюдения закрывается только как unknown")
    handle = _ledger_lock(ledger_path)
    try:
        existing = _read_reservation(ledger_path)
        _require(existing is not None, "reservation_missing", "эффект не резервировался до отправки")
        _require(existing["operation_id"] == prepared.operation_id
                 and existing["plan_digest"] == prepared.plan.digest,
                 "ledger_operation_conflict")
        _require(existing["state"] == "reserved", "reservation_already_settled")
        payload = dict(existing)
        payload["state"] = "settled"
        payload["outcome"] = outcome
        payload["receipt"] = _thaw(_freeze(dict(receipt))) if receipt is not None else None
        return _replace_reservation(ledger_path, payload)
    finally:
        _release(handle)


__all__ += ["PreparedTransactionUnit", "prepare_transaction_unit",
            "emit_transaction_unit_cs", "reserve_transaction_unit", "settle_transaction_unit"]
