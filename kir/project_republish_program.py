# -*- coding: utf-8 -*-
"""A republish PLAN -> the derived KIR program that carries it out.

    republish_program(plan, program) -> DerivedRepublish

🔴 WHAT THIS IS FOR. `kir.project_republish` decides WHAT must happen to each
output of a project that was published before (`kir-republish-plan/1`). This
module turns that decision into the only thing an emitter accepts: a KIR
program. Nothing is decided here — a converter that made its own choices would
be a second planner, and the two would drift.

🔴 THE MEASUREMENT THIS SERVES (live Revit 2023, 13.09.2026). A repeat
publication today has no middle: either `stale_or_failed` and an atomic
rollback (`live-20260913-slice-receipt.json`: walls 4/4/4, floors 1/1/1,
instances 3915/3915/3915), or every output built again
(`live-20260913-slice-opening-receipt.json`: walls 4→8→12, floors 1→2→3,
instances 3913→3938→3968, +25 per repeat). The pair of numbers this program is
answerable to is therefore **новых экземпляров 0 И отказов `stale_or_failed` 0**.

🔴 THE OP FORM IS SECTION N'S, AND IT IS NOT YET IN THE REGISTRY. `set_param`,
`move_elements` and `delete` address by `{"by": "unique_id"}` and carry
`expected_identity` / `expected_current`; N is landing that входная форма in
`kir/spec.py` / `kir/authoring_validation.py` this wave (those files are N's to
the end of it). This module is written AGAINST that form on purpose: when N
lands it, the compile lane turns green without a line changing here. Until then
the shape is checked, and the compiler's refusal is recorded as a NUMBER, not
hidden — see `kir/tests/test_a_republish_plan_becomes_a_program.py`.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from hashlib import sha256
from typing import Any

from kir.project import ProjectError
from kir.project_republish import ACTIONS, REPUBLISH_PLAN_SCHEMA

#: The derived program's own schema marker — it rides in `intent`, not as an
#: envelope key: `build()` hands the compiler EXACTLY the JSON it accepts, and
#: an unfamiliar envelope key is `KIR-P003`.
DERIVED_INTENT = "republish"


class RepublishProgramError(ProjectError):
    """The plan could not be turned into a program. Carries a named code."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"{code}: {message}")


def _canonical(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


@dataclass(frozen=True, slots=True)
class DerivedRepublish:
    """The program plus what the emitter must be told ALONGSIDE it.

    `expected_identities` is not decoration: `keep` rows are proved by the
    prologue's guard inside the writing transaction (contract §2, review point
    П3), not by a read op per output.
    """

    program: dict
    expected_identities: tuple
    destructive: bool
    plan_digest: str
    counts: dict
    digest: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "digest", sha256(_canonical(self.to_dict())).hexdigest())

    def to_dict(self) -> dict:
        return {"schema": "kir-republish-program/1", "program": self.program,
                "expected_identities": [dict(row) for row in self.expected_identities],
                "destructive": self.destructive, "plan_digest": self.plan_digest,
                "counts": dict(self.counts),
                "claims": {"native_execution": "not_run", "dispatch_permission": "none",
                           "engineering_acceptance": "not_established"}}

    def created_op_ids(self) -> tuple:
        return tuple(op["id"] for op in self.program["ops"] if op["op"].startswith("create_"))


def _uid(row: dict) -> str:
    identity = row.get("identity_before") or {}
    unique = identity.get("unique_id")
    if not unique:
        raise RepublishProgramError("row_without_identity",
                                    f"{row.get('output_id')}: {row.get('action')} без личности")
    return unique


def _selector(row: dict) -> dict:
    """The addressing form section N is landing: by UniqueId, pinned by the triple."""
    return {"by": "unique_id", "value": _uid(row)}


def _expected(row: dict) -> dict:
    """`expected_identity` for the emitter — EXACTLY the two fields it takes.

    🔴 THE SHAPE IS THE REGISTRY'S, AND IT IS NARROWER THAN THE PLAN'S TRIPLE.
    Section N landed the входная форма on 13.09.2026 (`fc6ef65`), and
    `kir/authoring_validation.py:1668` refuses anything but
    `{unique_id, version_guid}` — `schema_version` and `element_id` are the
    PLAN's bookkeeping, not the operation's. The plan keeps carrying all four
    (that is what addresses the element and what the ledger holds); the OPERATION
    gets the two it is contracted for. Measured: with four keys the derived
    program answered KIR-T001 «ожидается {unique_id, version_guid}».

    `version_guid` travels with its caveat: on an unsaved document it is the
    DOCUMENT's episode, not the element's version (contract §2, review point П6).
    It is carried, never read as "and it did not change either".
    """
    identity = dict(row.get("identity_before") or {})
    return {"unique_id": identity.get("unique_id"),
            "version_guid": identity.get("version_guid")}


def _one_change(row: dict) -> tuple:
    changes = row.get("changes") or {}
    if len(changes) != 1:
        raise RepublishProgramError(
            "update_touches_more_than_one_field",
            f"{row['output_id']}: {sorted(changes)} — операция изменения на месте "
            "меняет ОДНО поле; разбей план или поставь replace")
    (name, pair), = changes.items()
    if not (isinstance(pair, (list, tuple)) and len(pair) == 2):
        raise RepublishProgramError("change_is_not_a_pair",
                                    f"{row['output_id']}.{name}: ожидалось [было, стало]")
    return name, pair[0], pair[1]


def _delta(row: dict) -> list:
    """A rigid translation out of the plan's own before/after points."""
    changes = row.get("changes") or {}
    deltas = set()
    for name in ("p0_mm", "p1_mm"):
        if name not in changes:
            continue
        was, now = changes[name]
        if not (isinstance(was, (list, tuple)) and isinstance(now, (list, tuple))
                and len(was) == len(now)):
            raise RepublishProgramError("move_is_not_a_translation",
                                        f"{row['output_id']}.{name}: точки разной формы")
        deltas.add(tuple(round(float(b) - float(a), 6) for a, b in zip(was, now)))
    if len(deltas) != 1:
        raise RepublishProgramError(
            "move_is_not_a_translation",
            f"{row['output_id']}: концы сдвинуты по-разному — это не move_elements")
    delta = list(next(iter(deltas)))
    while len(delta) < 3:
        delta.append(0.0)
    return delta[:3]


def _update_op(row: dict, index: int) -> dict:
    reason = row.get("reason")
    base = {"id": f"upd-{index}", "expected_identity": _expected(row)}
    if reason == "parameter_changed":
        if row.get("update_via") != "builtin_parameter" or not row.get("parameter"):
            raise RepublishProgramError(
                "parameter_has_no_route",
                f"{row['output_id']}: правка параметра без `builtin_parameter` — "
                "отображаемое имя на нерусском/русском документе не совпадёт")
        _, was, now = _one_change(row)
        return {**base, "op": "set_param", "target": _selector(row),
                "param": row["parameter"],
                "value": {"value": now, "unit": "mm"},
                "expected_current": {"value": was, "unit": "mm"}}
    if reason == "geometry_moved":
        return {**base, "op": "move_elements", "targets": [_selector(row)],
                "delta_mm": _delta(row)}
    if reason == "type_changed":
        _, was, now = _one_change(row)
        return {**base, "op": "change_type", "target": _selector(row),
                "type": now, "expected_current": was}
    raise RepublishProgramError("update_reason_has_no_operation",
                                f"{row['output_id']}: причина {reason!r} не даёт операции "
                                "изменения на месте")


def _delete_op(row: dict, index: int) -> dict:
    return {"id": f"del-{index}", "op": "delete", "target": _selector(row),
            "expected_identity": _expected(row)}


def _reground(payload: dict, created: set, identities: dict, owner: str) -> dict:
    """A carried-over `create` still points at outputs that ALREADY EXIST.

    🔴 MEASURED BY THIS MODULE'S OWN INSTRUMENT, 13.09.2026. The floor whose
    contour changed is re-created; its `level` was `{by: ref}` to a level that
    this derived program does NOT create (the level is a `keep`). The compiler
    answered KIR-L003 — «ссылка на выход, которого в программе нет» — and it was
    right. So every reference that does not point INSIDE the derived program is
    re-grounded to the identity the plan already holds for it. A reference with
    neither is a named refusal, never a guess.
    """
    def walk(value):
        if isinstance(value, dict):
            if value.get("by") == "ref" and isinstance(value.get("value"), str):
                target = value["value"]
                if target in created:
                    return dict(value)
                identity = identities.get(target)
                if not identity:
                    raise RepublishProgramError(
                        "carried_reference_without_identity",
                        f"{owner}: ссылка на {target}, которого нет ни в программе, "
                        "ни в ledger'е — заземлить нечем")
                # 🔴 BY element_id, NOT unique_id. A `sel` slot (a level, a type)
                # takes `name | element_id | default | ref` — it does not know
                # `unique_id` at all; only WRITE targets (`target_w`) do.
                # Measured 13.09.2026 after section N landed the form: a
                # re-grounded `level` came back KIR-T001 «level — селектор …
                # получено {"by": "unique_id"}». The ledger carries both, so the
                # fix is to hand each slot the form it actually accepts.
                element_id = identity.get("element_id")
                if element_id is None:
                    raise RepublishProgramError(
                        "carried_reference_without_an_element_id",
                        f"{owner}: у {target} в ledger'е нет element_id, а слот-селектор "
                        "принимает только его; unique_id этому слоту не подходит")
                return {"by": "element_id", "value": element_id}
            return {key: walk(item) for key, item in value.items()}
        if isinstance(value, list):
            return [walk(item) for item in value]
        return value

    return walk(payload)


def _refuse_a_colliding_name(row: dict, payload: dict) -> None:
    """A replacement that keeps the old NAME reproduces the live refusal.

    🔴 MEASURED, NOT FEARED. On Revit 2023 on 13.09.2026 exactly this shape
    answered `stale_or_failed` — «тип с этим адресом уже существует с другим
    составом; изменение существующего типа — отдельная операция» — and `atomic`
    rolled the whole publication back (`live-20260913-slice-receipt.json`,
    `acceptance.publish_2`). The language has no "change an existing type" on
    purpose (`kir/authoring.py:4577-4580`, the owner's decision), so a type
    replacement ALWAYS carries a new name (contract §2). Emitting it without one
    would mean sending a program whose refusal we already know.
    """
    named = [field for field in ("new_name", "name") if field in payload]
    if not named:
        return
    field_name = named[0]
    changes = row.get("changes") or {}
    if field_name in changes:
        return
    raise RepublishProgramError(
        "replace_would_collide_with_the_existing_name",
        f"{row['output_id']}: замена держит прежнее {field_name}="
        f"{payload[field_name]!r}. Живьём это `stale_or_failed` «тип с этим "
        "адресом уже существует с другим составом» и откат всей публикации "
        "(live-20260913-slice-receipt.json). СЛЕДУЮЩИЙ ХОД: дай замене новое "
        f"{field_name} в программе-источнике")


def republish_program(plan, program, *, source_ops=None) -> DerivedRepublish:
    """Plan + the new program -> the derived program, in an order that is safe.

    🔴 THE ORDER IS THE CONTRACT'S, NOT THE ROW ORDER (§2, review point П5):
    ① create the new · ② rebind the dependants (`change_type`) · ③ delete the
    old. For a TYPE the opposite order is destructive by construction —
    deleting a type takes everything standing on it, and that cascade was
    measured live at 10 / 13 / 12 / **38** ids for a single deletion
    (`live-20260913-slice-cleanup-receipt.json`). Deletes therefore go LAST.
    """
    body = plan.to_dict() if hasattr(plan, "to_dict") else plan
    if not isinstance(body, dict) or body.get("schema") != REPUBLISH_PLAN_SCHEMA:
        raise RepublishProgramError("not_a_republish_plan",
                                    f"ожидалась схема {REPUBLISH_PLAN_SCHEMA}")
    payloads = dict(source_ops or {})
    if not payloads:
        source = program.to_program() if hasattr(program, "to_program") else program
        if not isinstance(source, dict) or not isinstance(source.get("ops"), list):
            raise RepublishProgramError("not_a_kir_program",
                                        "нужна программа KIR с массивом ops")
        payloads = {op["id"]: dict(op) for op in source["ops"] if isinstance(op.get("id"), str)}

    identities = {row["output_id"]: row["identity_before"]
                  for row in (body.get("rows") or ()) if row.get("identity_before")}
    #: Which addresses THIS program builds: a reference to one of them stays a
    #: reference; every other reference is re-grounded to a known identity.
    created_here = {row["output_id"] for row in (body.get("rows") or ())
                    if row["action"] in ("create", "replace")}
    creates, rebinds, updates, deletes, expected = [], [], [], [], []
    for row in body.get("rows") or ():
        action = row.get("action")
        if action not in ACTIONS:
            raise RepublishProgramError("action_outside_the_closed_list",
                                        f"{row.get('output_id')}: {action!r}")
        if action == "create" and row.get("identity_before"):
            # The planner cannot emit this; the converter still refuses to
            # execute it. A duplicate must be unspeakable on BOTH sides.
            raise RepublishProgramError(
                "create_over_known_identity",
                f"{row['output_id']}: создание поверх известного элемента")
        if action == "keep":
            expected.append(_expected(row))
            continue
        if action == "create":
            payload = payloads.get(row["output_id"])
            if payload is None:
                raise RepublishProgramError("created_output_is_not_in_the_program",
                                            f"{row['output_id']}: нечего создавать")
            creates.append(_reground(dict(payload), created_here, identities,
                                     row["output_id"]))
            continue
        if action == "update":
            expected.append(_expected(row))
            updates.append(_update_op(row, len(updates)))
            continue
        if action == "delete":
            expected.append(_expected(row))
            deletes.append(_delete_op(row, len(deletes)))
            continue
        # replace: ① new · ② rebind dependants · ③ delete old
        payload = payloads.get(row["output_id"])
        if payload is None:
            raise RepublishProgramError("replaced_output_is_not_in_the_program",
                                        f"{row['output_id']}: нечем заменить")
        # 🔴 THE REPLACEMENT GETS ITS OWN ADDRESS. Keeping the old one would put
        # a `create` on top of an element the ledger already knows — the very
        # thing the plan makes unspeakable — and it would read as a duplicate in
        # any census. The address is derived, so the same plan gives the same one.
        new_id = sha256(_canonical([row["output_id"], "replacement"])).hexdigest()
        _refuse_a_colliding_name(row, payload)
        creates.append(_reground({**payload, "id": new_id}, created_here, identities,
                                 row["output_id"]))
        if row.get("depends_on") and (payload.get("op") or "").endswith("_type"):
            # 🔴 A TYPE REPLACEMENT NEEDS TWO PROGRAMS, AND SAYING SO IS THE
            # ANSWER. `change_type.type` takes ONLY `element_id`
            # («type в v1 — только element_id (нет снапшот-пула типов по всем
            # категориям)»), and the new type has no id until it has been built.
            # So «create the type → rebind its users → delete the old» cannot be
            # ONE program; emitting it anyway would ship a program whose refusal
            # is already known. This is the same shape as `create_stairs` being
            # SOLO: a building is a BATCH of programs.
            raise RepublishProgramError(
                "replace_of_a_type_needs_two_programs",
                f"{row['output_id']}: у заменяемого типа {len(row['depends_on'])} "
                "носителей, а `change_type.type` принимает только element_id, "
                "которого у ещё не построенного типа нет. СЛЕДУЮЩИЙ ХОД: программа "
                "первая — создать новый тип и прочитать его id из квитанции; "
                "программа вторая — change_type носителям и delete старого")
        for dependant in row.get("depends_on") or ():
            # 🔴 A DEPENDANT IS AN ELEMENT IN THE MODEL, NOT AN OP OF THIS
            # PROGRAM. The first version addressed it `{by: ref}` and earned
            # KIR-L003 ("ссылка на выход, которого в программе нет") on every
            # replace — measured 13.09.2026 by this module's own instrument.
            # It is addressed the way every other existing element is: by the
            # identity the plan already carries for it.
            identity = identities.get(dependant)
            if not identity:
                raise RepublishProgramError(
                    "dependant_without_identity",
                    f"{row['output_id']}: зависимый {dependant} без личности — "
                    "перепривязать его не к чему")
            rebinds.append({"id": f"rebind-{len(rebinds)}", "op": "change_type",
                            "target": {"by": "unique_id", "value": identity["unique_id"]},
                            "expected_identity": _expected({"identity_before": identity}),
                            "type": {"by": "ref", "value": new_id}})
        expected.append(_expected(row))
        deletes.append(_delete_op(row, len(deletes)))

    ops = [*creates, *rebinds, *updates, *deletes]
    destructive = bool(deletes)
    envelope = {"ir_version": "1.0", "intent": f"{DERIVED_INTENT}: {body.get('project_id') or ''}"}
    if destructive:
        envelope["allow_destructive"] = True
    envelope["ops"] = ops
    counts = {"create": len(creates), "rebind": len(rebinds), "update": len(updates),
              "delete": len(deletes), "keep": sum(1 for row in (body.get("rows") or ())
                                                  if row["action"] == "keep")}
    if destructive != bool(body.get("destructive")):
        raise RepublishProgramError(
            "destructive_flag_disagrees_with_the_plan",
            f"план говорит destructive={body.get('destructive')}, программа — {destructive}")
    return DerivedRepublish(envelope, tuple(expected), destructive,
                            body.get("plan_digest") or "", counts)
