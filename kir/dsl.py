"""KIR as a source language: python counts, IR proves.

    from kir import dsl
    from kir.dsl import *          # поверхность = реестр, целиком

    envelope(intent="комната 6×4 с дверью")
    lvl = create_level(elev_mm=0, name="Этаж 1")
    pts = [(0, 0), (6000, 0), (6000, 4000), (0, 4000)]
    walls = [create_wall(p0_mm=a, p1_mm=b, level=lvl, height_mm=3000)
             for a, b in zip(pts, pts[1:] + pts[:1])]
    create_door(host=walls[0], offset_mm=3000, symbol="Дверь 900x2100")
    prog = build()                      # ← обычный JSON KIR, больше ничего

`prog` goes into `compiler.plan_program` WITH NO SLACK. Python here is only
a FRONT END: it never touches Revit, knows nothing about transactions, and
cannot express anything that is not in the registry. The blast radius is
bounded by the IR, not by the sandbox.

HOW THIS MODULE DIFFERS FROM `sdk.py`
--------------------------------------
`sdk.py` (29.07) already births builders from the registry, and NONE of that
is rewritten here where the fact is single: parameter-kind classification and
numpy coercion are taken from it by reference (`sdk.SELECTOR_KINDS`,
`sdk._plain`, `sdk.OMIT`), and the test `test_dsl.py` holds both surfaces to
one registry name.

The difference is in four things, each of which changes the shape of the
language, not its convenience:

1. ACCUMULATION IS IMPLICIT. The call itself puts the op into the current
   program and returns a HANDLE. In sdk the call returns a dict that the
   author must hand to `p.add(...)`; the script reads as assembling a
   builder, not as a script.
2. THE HANDLE KNOWS WHETHER IT CAN BE REFERENCED. `sdk.Program.add` returns
   a `Ref` for ANY op — including the nine for which
   `ResultSpec.reference_kind is None` (`create_stairs`, `create_group`,
   `create_pipe_system`, `route_*`, `delete`, `set_param`, `change_type`,
   `set_curtain_panel`, `create_curtain_grid_line`, `move_elements`). Such a
   `Ref` reaches the compiler and gets KIR-L003 one or two layers later.
   Here the handle of a non-referenceable op refuses ON THE SPOT and names
   the reason straight out of `ResultSpec` itself.
3. SELECTORS ARE COERCED PER SLOT, NOT BY ONE FUNCTION. `sel`, `target`, and
   `target_w` have DIFFERENT admissible shapes (`target_w` does not know
   `by=name` at all — `authoring_validation._target_w_ok`), so a string in
   the target slot is an inexpressible form, not "let the compiler sort it
   out": coercion is sugar, and sugar must be unambiguous. Plus
   `disambiguate_by`, which until now could not be written from python any
   other way than by hand as a dict.
4. INTROSPECTION CARRIES THE BOUNDARIES. `inspect.signature` shows a
   parameter's kind and its limits from `ParamSpec`, the docstring shows the
   op's postcondition and the witness's tolerances. This is the answer to
   "how does the model learn about what it cannot see": not as a separate
   tier of documentation, but in a way native to python.

LAWS
------
* NOT ONE BUILDER IS HAND-WRITTEN. The surface is built on import from
  `spec.OPS` by a factory driven by `ParamSpec`. A new op in the registry is
  a new function at that same moment, with no assembly step and no file that
  has anything to go stale.
* NAMES EXACTLY AS IN THE REGISTRY. No abbreviations, no renamings: a second
  dictionary of names is a second source of truth. Expressiveness is drawn
  from python.
* NO SEMANTICS OF ITS OWN. The truth about correctness belongs to the
  compiler. The module checks exactly what is needed to assemble valid
  JSON at all: the op's name (signature), the parameter's being known
  (signature), the handle's shape, and the sugar's unambiguity. Everything
  else is `plan_program`.
"""

from __future__ import annotations

import os as _os
from kir import env as _env  # noqa: E402
import sys as _sys

import inspect
from typing import Any

from kir import registry_base as _rb
from kir import sdk, spec
from kir.compiler import (BUDGET_INTERNAL_BULK, DEFAULTABLE,
                               MAX_BULK_OPS, MAX_OPS_PER_PROGRAM)
from kir.diag import (
    Diagnostic, GROUND_BAD_SELECTOR, KirRefusal, PARSE_DUP_ID,
    PARSE_MISSING_FIELD, PARSE_UNKNOWN_FIELD, PLAN_LIMIT, TYPE_BAD_TYPE,
)

__all__ = [
    "OMIT", "DEFAULT", "Handle", "Program", "DslRefusal",
    "by_name", "by_element_id", "by_default", "by_ref", "family_type",
    "disambiguate",
    "program", "current", "reset", "envelope", "ops", "build", "plan",
    "op_names", "selector_forms", "MAX_BULK_OPS",
]

#: Sentinels are taken from `sdk`, not set up as our own: the value "field
#: not set" is one for the whole python front end, and a script mixing two
#: modules must not catch different omissions that print identically.
OMIT = sdk.OMIT
DEFAULT = sdk.DEFAULT

#: numpy/tuple -> whatever survives json.dumps. The fact is single — taken
#: by reference.
_plain = sdk._plain



#: 🔴 THE CEILING OF THE BUILDER ITSELF — AND IT USED TO BE THE AUTHOR'S
#: REAL BOUNDARY.
#:
#: Before 18.08.2026, `MAX_BULK_OPS` (300) stood here — an INTERNAL budget,
#: not the author's. The consequence was quiet and expensive: no matter what
#: author's budget was declared, the author PHYSICALLY could not assemble a
#: program bigger than 300 ops — the builder refused before any door did.
#: Raising the author's budget without this line would have been
#: decoration: the number in the canon would grow, while the author would
#: still hit the same old wall and read a refusal about SOMEONE ELSE's
#: budget.
#:
#: 🔴 THE FIRST EDIT OF THIS FIX WAS WRONG: I tied the ceiling to the
#: AUTHOR's budget and by doing so zeroed out the `program_py` door's
#: margin. Refuted by someone else's test in a single run. The builder is
#: an instrument of the SCRIPT door, and it must be measured against the
#: internal budget, the one that has margin.
#:
#: 🔴 THE DEBT WAS CLOSED 21.08.2026: chunking of a live turn is WIRED UP
#: to the prod door (`serving._drive_chunked_program`). A program that
#: does not fit into the bridge's frame no longer ships as one transaction
#: and no longer bounces — it goes as contiguous slices in AUTHOR ORDER,
#: and references between slices become the `element_id` from the receipts
#: of previous ones.
#:
#: WHAT THIS COSTS, AND WHAT IS NAMED INSTEAD OF THE DEBT: a split program
#: has `per_chunk` atomicity, and the receipt states this with three
#: top-level scalars. A program that fits into the frame goes as before —
#: as one transaction, byte for byte. The ceiling below remains a GUARD
#: AGAINST A RUNAWAY, not a transport boundary: nobody ever measured a
#: physical wall at 300, 300 was a DECLARED number.
#: 🔴 OVERRIDDEN BY THE ENVIRONMENT — THE SAME DISCIPLINE AS THE OTHER
#: THRESHOLDS OF THIS TREE, AND BOUGHT BY THE IMPOSSIBILITY OF VERIFYING IT
#: (21.08.2026).
#:
#: The test guarding "a budget refusal carries a CENSUS of what was
#: assembled" was building 401 ops against a ceiling of 300. After the
#: budget was raised on 20.08, the ceiling became 200,000, and the test
#: went red. The constant cannot be swapped out by the test: the script
#: executes in a SEPARATE PROCESS, and an edit in the parent never reaches
#: the child. And building 200,001 ops for the sake of the same assertion
#: means buying it with a run that dies from memory pressure (the
#: neighboring `test_op_budget_seam` showed this).
#:
#: A threshold that cannot be set from outside is a threshold whose
#: behavior is UNVERIFIABLE. Hence the variable — the operator needs it too,
#: if a runaway has to be caught at a smaller number.
_DSL_OP_CEILING = max(1, int(
    _env.get("KIR_DSL_OP_CEILING") or MAX_BULK_OPS))
# RESTORED: the builder is an instrument
#: of the SCRIPT door, and its margin over the author's budget is
#: load-bearing (see compiler.py)

#: 🔴 THE REGISTRY DEFAULT — ONE CARRIER FOR BOTH FRONT ENDS (02.09.2026).
#: The class moved to the place where the default is defined
#: (`registry_base`, next to `ParamSpec.default`), because there are TWO
#: front ends and ONE law for them. While it lived here, `sdk.py` did not
#: know about it and could not: `dsl` imports `sdk`, the reverse edge would
#: close a cycle — so builders were WRITING IN defaults on the op. The NAME
#: stays here (docstrings and tests know it), but it is the same object: the
#: class's identity does not fork.
_RegistryDefault = _rb.RegistryDefault
_is_registry_default = _rb.is_registry_default


class DslRefusal(KirRefusal):
    """A refusal of the LANGUAGE ITSELF, in the compiler's dictionary.

    A descendant of `KirRefusal` deliberately: the caller (sandbox, script,
    the fix loop) has one handling branch for all typed KIR refusals, and a
    front-end refusal must not demand a second one. `diagnostics` are the
    same `Diagnostic` objects with `code`/`field_name`/`candidates`, not
    text.
    """


def _refuse(**kw: Any) -> "DslRefusal":
    return DslRefusal([Diagnostic(**kw)])


def _exactly_bool(value: Any, field_name: str) -> bool:
    """`True`/`False` and nothing else. Otherwise — a typed refusal of the
    LANGUAGE.

    🔴 `bool(value)` USED TO STAND IN `build()`, AND THIS INCLUDED
    DEMOLITION BY THE WORD "NO" (04.09.2026). The same defect closed for
    `sdk` on 29.08 (F-239) lived here as a SECOND CARRIER and stayed open:
    python has TWO front ends, and the law was put on only one. Measured
    before the fix, verbatim:

        envelope(allow_destructive='false')  ->  "allow_destructive": true
        envelope(allow_destructive='0')      ->  "allow_destructive": true
        envelope(allow_destructive='no')     ->  "allow_destructive": true
        envelope(allow_destructive=1)        ->  "allow_destructive": true

    🔴 WHY THIS IS WORSE THAN AT `sdk`: HERE IT WAS INTERCEPTING A COMPILER
    REFUSAL. The compiler HAS a law and it is named — `compiler.py`,
    `TYPE_BAD_TYPE`, "allow_destructive must be true/false." It could NEVER
    have fired on a program assembled by this module: `bool()` in `build()`
    was turning the string into a LEGITIMATE `true` BEFORE the compiler ever
    saw it. That is, the front end was not "letting through" a wrong value —
    it was MAKING it right, and making it exactly the value that PERMITS
    demolition.

    A refusal, not a coercion, and the reasoning is the same one recorded at
    `sdk._exactly_bool`: "a string instead of a boolean" has no correct
    reading, and a truth dictionary of its own next to python's own ("no",
    "нет", "off", "0") is not a mechanism.

    THE LAW IS TAKEN FROM `sdk` BY REFERENCE, NOT REWRITTEN: the subject is
    single, and a second carrier of it is exactly the illness this fix
    cures. What changes here is only the CLOTHING of the refusal:
    `DslRefusal` in the compiler's dictionary, because the sandbox and the
    fix loop have one branch for typed KIR refusals (see `DslRefusal`), and
    a bare `TypeError` would demand a second one.
    """
    try:
        return sdk._exactly_bool(value, field_name)
    except TypeError as coercion:
        raise _refuse(code=TYPE_BAD_TYPE, field_name=field_name,
                      got=repr(value), expected="true или false",
                      message_ru=str(coercion))


# ─────────────────────────────────────────────────────────────────── handles

class Handle:
    """The address of an op in the program — and, if the registry allows it,
    a reference to it.

    Returned by EVERY call. Referenceability is not a matter of convenience,
    it is a typed contract of `ResultSpec`: a group and a deleted element
    both have identity evidence, yet no correct forward reference exists for
    them. That is why the handle of a non-referenceable op exists (its `id`
    can be read off it), but it cannot silently pass as `{"by": "ref"}`.
    """

    __slots__ = ("id", "op", "_spec", "_node")

    def __init__(self, id: str, op: str, spec_: spec.OpSpec,  # noqa: A002
                 node: dict | None = None) -> None:
        self.id = id
        self.op = op
        self._spec = spec_
        # THE CALL, NOT JUST THE OP. For `create_wall_type` the result kind
        # is decided by `host_kind`, and the handle must know THE KIND OF
        # ITS OWN CALL: otherwise `create_floor(type=...)` in python would
        # look like it accepts a "wall" handle, and the compiler would
        # refuse it on the next step — a divergence between two of our own
        # carriers of one piece of knowledge, our own named defect.
        self._node = node or {}

    # ── what it knows about itself ────────────────────────────────────────
    @property
    def referenceable(self) -> bool:
        return self._spec.result_for(self._node).referenceable

    @property
    def reference_kind(self) -> spec.ReferenceKind | None:
        return self._spec.result_for(self._node).reference_kind

    @property
    def op_spec(self) -> spec.OpSpec:
        return self._spec

    def as_selector(self) -> dict:
        """`{"by": "ref", "value": id}` — or a refusal with a named cause."""
        if not self.referenceable:
            raise _refuse(
                code=TYPE_BAD_TYPE, op_id=self.id, field_name="by=ref",
                expected="оп с ResultSpec.reference_kind",
                got=f"{self.op} -> {self._unreferenceable_reason()}",
                message_ru=(
                    f"на «{self.op}» нельзя сослаться: {self._unreferenceable_reason()}. "
                    "Ссылку внутри программы даёт только оп, чей результат — "
                    "ОДНА идентичность с объявленным reference_kind; адресуй "
                    "такой элемент по element_id после исполнения"))
        return {"by": "ref", "value": self.id}

    def _unreferenceable_reason(self) -> str:
        result = self._spec.result
        card = result.identity_cardinality
        if card is spec.IdentityCardinality.NONE:
            return "результат не несёт идентичности вовсе (query)"
        if card is spec.IdentityCardinality.MANY:
            return (f"результат — МНОЖЕСТВО идентичностей "
                    f"({result.identity_field}), единичной ссылки не бывает")
        return (f"результат несёт идентичность ({result.identity_field}), но "
                "reference_kind не объявлен")

    # ── WHAT THE HANDLE CANNOT DO — AND SAYS SO ITSELF ────────────────────
    #
    # MEASUREMENT 04.08, the second most frequent class of a weak model's
    # refusal (6 of 21):
    #
    #     wall_types = query_types(pool='wall_types')
    #     wall_type_ext = wall_types[0]['id']     ← TypeError: not subscriptable
    #     wall_types = list(query_types(...))     ← TypeError: not iterable
    #
    # Both lines are the most natural thing in the world, and both got a
    # bare python TypeError without a single word on HOW IT SHOULD BE DONE.
    # Both runs started with exactly this and lost two turns each before the
    # first program that assembled.
    #
    # WHY NOT MAKE THEM WORK. Because there is no honest semantics: for a
    # reading op the result does not exist at all AT THE MOMENT THE PROGRAM
    # IS WRITTEN (`ResultSpec.identity_cardinality is NONE`, a READ effect)
    # — it will appear in Revit at execution. `[0]` would have to return
    # "whichever type came first," i.e. choose silently on the author's
    # behalf; this is exactly the silently-wrong result the language must
    # make inexpressible. So the second path remains, and it too is named
    # by the law: a refusal must NAME THE CORRECT FORM VERBATIM.
    def _no_value(self, attempt: str) -> "DslRefusal":
        card = self._spec.result.identity_cardinality
        if self._spec.effect is spec.EffectKind.READ:
            what = (f"`{self.op}` — ЧИТАЮЩИЙ оп: его ответ появляется при "
                    f"исполнении в Revit, а в скрипте его нет вовсе")
            how = ("СЛЕДУЮЩИЙ ХОД — две честные формы, обе рабочие:\n"
                   "  • НЕ ЧИТАЯ: адресуй по ИМЕНИ (type=\"Наружная 300\") "
                   "либо оставь умолчание документа (type=DEFAULT) — выбор "
                   "будет НАЗВАН, а лестница умолчаний живёт в ground.py;\n"
                   "  • ЧИТАЯ: пошли программу, где этот оп стоит один — "
                   "{id, name} придут в КВИТАНЦИИ этого же хода, и следующая "
                   "программа поставит element_id.")
        elif card is spec.IdentityCardinality.MANY:
            what = (f"`{self.op}` создаёт МНОЖЕСТВО элементов, но в СКРИПТЕ их "
                    f"нет: они появятся при исполнении")
            how = ("СЛЕДУЮЩИЙ ХОД: адресуй их после исполнения по element_id "
                   "из квитанции — единичной ссылки на них не бывает.")
        else:
            what = (f"`{self.op}` возвращает ОДНУ ручку, а не список")
            how = ("СЛЕДУЮЩИЙ ХОД: передай ручку в слот целиком (level=lvl, "
                   "host=wall). Нужен список — собери его САМ, питоном: "
                   "walls = [create_wall(...) for a, b in пары].")
        return _refuse(
            code=TYPE_BAD_TYPE, op_id=self.id, field_name=attempt,
            expected="ручка = АДРЕС операции в программе",
            got=f"{attempt} у Handle({self.op})",
            message_ru=(f"{what}. Ручка — АДРЕС операции в программе, а не её "
                        f"результат, поэтому {attempt} тут невозможен.\n{how}"))

    def __getitem__(self, key: Any) -> Any:
        raise self._no_value(f"индекс [{key!r}]")

    def __iter__(self):
        # `list(handle)`/`for x in handle`/unpacking — they all arrive here.
        raise self._no_value("перебор (for / list() / распаковка)")

    def __len__(self) -> int:
        raise self._no_value("len()")

    def __bool__(self) -> bool:
        # EXPLICIT, AND THIS IS NOT A FORMALITY. Without `__bool__`,
        # truthiness would be computed via `__len__` — that is, a refusal.
        # `if wall_types else None` was written by a weak model already on
        # its first turn (wB t01), and turning an emptiness check into a
        # crash would mean setting up a NEW trap in place of the one that
        # was fixed. The handle always exists: it is an address, not a
        # result.
        return True

    def __repr__(self) -> str:
        kind = self.reference_kind.value if self.reference_kind else "НЕ ССЫЛКА"
        return f"Handle({self.id!r}, {self.op}, {kind})"

    def __eq__(self, other: Any) -> bool:
        return (isinstance(other, Handle) and other.id == self.id
                and other.op == self.op)

    def __hash__(self) -> int:
        return hash(("Handle", self.op, self.id))


# ────────────────────────────────────────────────────── selector shapes

#: Parameter kinds that in JSON look like ONE selector, and kinds that look
#: like a LIST of selectors. The classification is taken from `sdk` — it
#: already exists there and is already under guard
#: (`sdk.unclassified_kinds()`); a second such list would drift apart at
#: exactly the moment a new parameter kind appears, i.e. at the worst
#: possible moment. Here these sets are only SPLIT by their admissible
#: shapes.
_SELECTOR_KINDS = frozenset(sdk.SELECTOR_KINDS)
_SELECTOR_LIST_KINDS = frozenset(sdk.SELECTOR_LIST_KINDS)


def selector_forms(op_name: str, param_name: str) -> tuple[str, ...]:
    """Which `by=` shapes THIS slot of THIS op accepts.

    Derived from `ParamSpec.kind` and `ref_kinds`, i.e. from the registry —
    except for one: `family_type` lives only on `place_family.symbol`. This
    fact is today recorded THREE TIMES (here, `schema_gen._op_schema`,
    `authoring_validation.validate`), because the registry does not carry
    it; its place is a flag on `ParamSpec`, and until then the line below is
    a deliberate repetition, not an oversight.
    """
    ospec = spec.OPS[op_name]
    p = next(p for p in ospec.params if p.name == param_name)
    return _forms(ospec, p)


def _forms(ospec: spec.OpSpec, p: spec.ParamSpec) -> tuple[str, ...]:
    if p.kind == "sel":
        forms = ["name", "element_id", "default"]
        if ospec.name == "place_family" and p.name == "symbol":
            forms.append("family_type")
        if p.ref_kinds:
            forms.append("ref")
        return tuple(forms)
    if p.kind == "target":
        # query_inspect: a name is admissible, but requires `kind` alongside
        # it (compiler.py).
        return ("element_id", "name")
    if p.kind == "sel_list":
        # The plural of the `sel` kind: the same shapes as the singular,
        # minus `family_type` (it lives only on place_family.symbol and
        # never comes as a list). Its own branch, not a union with `sel`,
        # because the author needs to SAY that this is a list — and that is
        # what the caller does.
        forms = ["name", "element_id", "default"]
        if p.ref_kinds:
            forms.append("ref")
        return tuple(forms)
    # 🔴 `targets_w` СНЯТ 13.09.2026: ТАКОГО ВИДА В РЕЕСТРЕ НЕТ (заявка N 3).
    # `spec.PARAM_KINDS` закрыт и проверяется при импорте реестра, а этого имени
    # в нём нет ни разу — и ни один оп его не носит. Мёртвое имя в перечислении
    # ничего не ломает и ровно поэтому опасно: рядом лежит ЖИВОЙ `refs_w`
    # (`move_elements.targets`), и читающий эти строки мог решить, что
    # существуют оба. Второй носитель вымысла — тот же дефект, что и второй
    # носитель правды.
    if p.kind in ("target_w", "refs_w"):
        # _target_w_ok: a PINNED id or a reference within the program. There
        # is no name here and there cannot be — the write target is resolved
        # before emission, not in C#.
        return ("element_id", "ref") if p.ref_kinds else ("element_id",)
    raise AssertionError(f"{ospec.name}.{p.name}: вид {p.kind!r} не селектор")


#: Fields with which an op NAMES what it creates. Needed by the refusal so
#: that the advice "match by name" names a SPECIFIC field, not a genre.
_NAMING_FIELDS: tuple[str, ...] = ("new_name", "name")


def _by_name_next_move(ospec: spec.OpSpec, p: spec.ParamSpec,
                       handle: "Handle") -> str:
    """THE NEXT MOVE for a handle that landed in a slot without the `ref`
    shape.

    MEASUREMENT 04.08 (run wB, turns 5 and 11): the refusal was CORRECT — it
    named the slot's shapes — but the advice led into a pit. The model read
    "the slot accepts name/element_id/default," while the name is not in
    the snapshot yet: this SAME batch creates both the type and the level.
    The correct answer is "matched by the name you just gave yourself," and
    it is verified by the plan, not merely derived:
        create_type(new_name='Наружная 300') + create_wall(type='Наружная 300')
        -> plan_program accepted 3 ops.
    For `create_stairs`, the batch rule adds to this: the op is SOLO
    (KIR-L002), meaning the level comes from a neighboring link, and only by
    name.
    """
    produced = handle.op_spec
    named = next((f.name for f in produced.params
                  if f.name in _NAMING_FIELDS), None)
    if ospec.name in spec.SOLO_OPS:
        # TWO SOLO OPS — TWO DIFFERENT NEXT MOVES, AND THIS IS NOT
        # POLITENESS (10.08.2026). The advice "match BY NAME" is correct for
        # the flight's level: `base_level` is a selector of kind `sel`, and
        # it has the `name` shape. For the landing, though, the reference
        # lands in `stairs` of kind `target_w`, and it has NO `name` shape
        # AND CANNOT HAVE ONE (`_forms`: the write target is resolved before
        # emission, not in C#). The earlier text would send the author to
        # write `stairs="Этаж 1"` — advice leading straight into a second
        # refusal, exactly the "pit" that the 04.08 measurement set up this
        # helper against.
        if p.kind in ("target_w", "refs_w"):  # `targets_w` снят: вида нет
            return (f"СЛЕДУЮЩИЙ ХОД — ФОРМА ПАЧКИ, а не ссылка: "
                    f"`{ospec.name}` обязан быть ЕДИНСТВЕННЫМ опом своей "
                    f"программы (KIR-L002, StairsEditScope владеет своими "
                    f"транзакциями), поэтому опа `{handle.op}` в ней нет и "
                    f"ссылаться не на что. Цель записи адресуется ТОЛЬКО "
                    f"element_id уже построенного элемента: сначала звено, "
                    f"которое его строит, затем это — "
                    f"{p.name}={{\"by\": \"element_id\", \"value\": <id из "
                    f"квитанции того звена>}}. Вердикт бери у ПАЧКИ целиком "
                    f"— design_check([...]), — иначе он осудит звено вместо "
                    f"здания.")
        return (f"СЛЕДУЮЩИЙ ХОД — ФОРМА ПАЧКИ, а не ссылка: `{ospec.name}` "
                f"обязан быть ЕДИНСТВЕННЫМ опом своей программы (KIR-L002, "
                f"StairsEditScope владеет своими транзакциями). Значит здание "
                f"— это ПАЧКА: тело отдельно, лестница отдельно. Уровень "
                f"создаёт программа тела, а лестничная видит его ПО ИМЕНИ: "
                f"{p.name}=\"Этаж 1\". Вердикт бери у ПАЧКИ целиком — "
                f"design_check([тело, лестница]), — иначе он осудит звено "
                f"вместо здания.")
    if named:
        return (f"СЛЕДУЮЩИЙ ХОД: ты создаёшь это опом `{handle.op}` (id "
                f"«{handle.id}») в этой же программе — сошлись на него ПО "
                f"ИМЕНИ, которое сам ему дал в `{named}`: "
                f"{p.name}=\"<{named} этого опа>\". Имя разрешается при "
                f"исполнении, когда оп уже отработал, поэтому порядок опов "
                f"внутри программы это чинит, а ссылка — нет.")
    return (f"СЛЕДУЮЩИЙ ХОД: этот слот адресуется каталогом (name/element_id), "
            f"а не соседним опом. Возьми имя типа из `query_types` либо оставь "
            f"умолчание документа ({p.name}=DEFAULT).")


#: How a selector slot is filled — ONE definition for two readers.
#:
#: The first reader is the language refusal (`_selector_error` below). The
#: second reader is the model's documentation
#: (`tool_doc._selector_forms_in_python`). This used to live as a LOCAL
#: variable inside the refusal, and the docs, having no access to it,
#: described the dialect IN THEIR OWN WORDS: twenty-five handwritten
#: selector dictionaries in the rendered text and not a single mention of
#: the short form the language has accepted from the very start. The
#: classic "declared here, read over there"; the cure is not cross-checking
#: two copies, but there being one copy.
#:
#: The order of the keys goes from the SHORTEST form to the most cumbersome:
#: the reader takes the first one, and the first one must be the one that
#: leaves no room for error.
_SELECTOR_HINTS: dict[str, str] = {
    "name": 'голая строка `level="Этаж 1"` -> {"by":"name"}',
    "element_id": "голое целое `level=1100` -> {\"by\":\"element_id\"}",
    "ref": "ручка соседнего опа -> {\"by\":\"ref\"}",
    "default": 'DEFAULT / by_default() -> {"by":"default"}',
    "family_type": "family_type(category, family_name, type_name)",
}


def _no_ref_reason(ospec: spec.OpSpec, p: spec.ParamSpec) -> str:
    """WHY a reference is not allowed here — in the model's words, not the contract's.

    🔴 BOUGHT BY A MEASUREMENT (13.09.2026, RQ7 preparation, expressibility
    matrix P05). The FIRST refusal an author sees for
    `create_stairs(base_level=<уровень этой же программы>)` came from the DSL
    stage and said «ссылка … не разрешена типизированным контрактом параметра
    (ref_kinds пуст)». That is TRUE and USELESS: it describes the contract's
    plumbing, while the reason is a property of the BUILDING — the op owns its
    own transactions, so it is the only op of its program, and the level
    therefore comes from a neighbouring one BY NAME.

    The planner says exactly that, and says it well (`kir/compiler.py:1862`,
    KIR-L002: «единственный оп своей программы … Здание — это ПАЧКА программ …
    доступен лестничной по ИМЕНИ»). But the planner speaks SECOND — only once
    the program is assembled. The author meets the DSL first, and meeting the
    plumbing first is what sends them to guess.

    🔴 TWO CARRIERS OF ONE SENTENCE ARE HELD BY A PIN, NOT BY HOPE:
    `kir/tests/test_a_solo_op_says_why_before_the_planner_does.py` asserts that
    this text and the planner's KIR-L002 carry the SAME words. The compiler is
    section N's to the end of this wave, so the sentence is not moved there —
    it is tied.
    """
    if ospec.name in spec.SOLO_OPS:
        return (f"`{ospec.name}` владеет собственными транзакциями и потому "
                f"обязан быть ЕДИНСТВЕННЫМ опом своей программы (KIR-L002) — "
                f"в ней нет соседа, на которого можно сослаться")
    return ("ссылка внутри программы этому слоту не разрешена типизированным "
            "контрактом параметра (ref_kinds пуст)")


def _selector_error(ospec: spec.OpSpec, p: spec.ParamSpec, value: Any,
                    reason: str, next_move: str = "") -> DslRefusal:
    forms = _forms(ospec, p)
    hints = _SELECTOR_HINTS
    message = (f"{ospec.name}.{p.name}: {reason}. Слот принимает "
               f"{list(forms)}; словарь-селектор всегда можно написать "
               f"явно ({', '.join(hints[f] for f in forms)})")
    if next_move:
        message += "\n" + next_move
    return _refuse(
        code=GROUND_BAD_SELECTOR, field_name=p.name,
        expected=list(forms), got=repr(value), candidates=[hints[f] for f in forms],
        message_ru=message)


def _coerce_selector(ospec: spec.OpSpec, p: spec.ParamSpec, value: Any) -> Any:
    """A python value -> a selector. SUGAR, not a second dictionary.

    An explicit form (a ready-made dict) passes through UNTOUCHED — it is
    judged by the compiler. The sugar refuses only where the shape simply
    does not exist: a coercion that cannot be unambiguous is better not made
    at all.
    """
    forms = _forms(ospec, p)
    if isinstance(value, dict):
        return _plain(value)                     # the author said it explicitly — we do not touch it
    if isinstance(value, Handle):
        if "ref" not in forms:
            raise _selector_error(ospec, p, value, _no_ref_reason(ospec, p),
                                  _by_name_next_move(ospec, p, value))
        return value.as_selector()               # it will refuse on its own if it is not referenceable
    if isinstance(value, sdk.Ref):               # reciprocity with sdk scripts
        if "ref" not in forms:
            raise _selector_error(ospec, p, value, "ref этому слоту не разрешён")
        return {"by": "ref", "value": value.id}
    if value is DEFAULT:
        if "default" not in forms:
            raise _selector_error(ospec, p, value,
                                  "у этого слота нет формы by=default")
        return {"by": "default"}
    if isinstance(value, bool):
        raise _selector_error(ospec, p, value, "bool — не адрес элемента")
    if isinstance(value, int):
        if "element_id" not in forms:            # unreachable today; we do not stay silent
            raise _selector_error(ospec, p, value, "у слота нет формы element_id")
        return {"by": "element_id", "value": int(value)}
    if isinstance(value, str):
        if "name" not in forms:
            raise _selector_error(
                ospec, p, value,
                "у этого слота НЕТ формы by=name — цель записи адресуется "
                "element_id или ссылкой на соседний оп")
        return {"by": "name", "value": value}
    raise _selector_error(ospec, p, value, "не селектор")


# ── explicit forms (sugar is optional; disambiguate_by lives only here) ──

def disambiguate(param: str, value: Any) -> dict:
    """`disambiguate_by` — narrowing by a parameter.

    Checked EVEN when only one candidate remains (`ground.py`): otherwise
    "give me Ø100" would silently get Ø200, and from the outside this is
    indistinguishable from success.
    """
    return {"param": param, "value": _plain(value)}


def by_name(value: str, *, kind: str | None = None,
            disambiguate_by: dict | None = None) -> dict:
    """`{"by": "name"}`. `kind` is needed where the language requires naming
    the element's kind together with the name (`query_inspect.target`)."""
    out: dict[str, Any] = {"by": "name", "value": value}
    if kind is not None:
        out["kind"] = kind
    if disambiguate_by is not None:
        out["disambiguate_by"] = dict(disambiguate_by)
    return out


def by_element_id(value: int) -> dict:
    """`{"by": "element_id"}` — pinned; existence will be checked by a guard
    in C#."""
    return {"by": "element_id", "value": int(value)}


def by_default(*, disambiguate_by: dict | None = None) -> dict:
    """`{"by": "default"}` — the ladder in `ground.py`: the document's
    default, the sole one in the pool, the NAMED most_used default,
    otherwise a refusal."""
    out: dict[str, Any] = {"by": "default"}
    if disambiguate_by is not None:
        out["disambiguate_by"] = dict(disambiguate_by)
    return out


def by_ref(target: Any) -> dict:
    """`{"by": "ref"}` from a handle, an `sdk.Ref`, or an id string."""
    if isinstance(target, Handle):
        return target.as_selector()
    if isinstance(target, sdk.Ref):
        return {"by": "ref", "value": target.id}
    if isinstance(target, str):
        return {"by": "ref", "value": target}
    raise _refuse(code=TYPE_BAD_TYPE, field_name="by=ref", got=repr(target),
                  expected="Handle | sdk.Ref | str",
                  message_ru="ссылка строится из ручки опа или его id")


def family_type(category: str, family_name: str, type_name: str) -> dict:
    """A catalog selector: category + family + type, exactly one match."""
    return {"by": "family_type", "category": category,
            "family_name": family_name, "type_name": type_name}


# ───────────────────────────────────────── introspection: types and bounds

class _Ann:
    """The annotation text. `inspect` prints non-types via `repr`, so the
    parameter's kind and its bounds are visible right in the signature, not
    only in the docstring."""

    __slots__ = ("text",)

    def __init__(self, text: str) -> None:
        self.text = text

    def __repr__(self) -> str:
        return self.text

    def __eq__(self, other: Any) -> bool:
        return isinstance(other, _Ann) and other.text == self.text

    def __hash__(self) -> int:
        return hash(("_Ann", self.text))


def _bounds(p: spec.ParamSpec) -> str:
    if p.min_val is None and p.max_val is None:
        return ""
    lo = "" if p.min_val is None else f"{p.min_val:g}"
    hi = "" if p.max_val is None else f"{p.max_val:g}"
    return f" {lo}..{hi}"


#: Предел ОДНОЙ строки формы составного слота. Не вкус: канал контракта
#: 3300 знаков (`course.LESSON_CAP`), и самый тесный оп реестра держит запас
#: 530 (`create_ceiling`, замерено 13.09.2026 живой резалкой). Потолок ниже
#: умножается на число РАЗНЫХ составных видов в одном опе, и произведение
#: обязано остаться внутри запаса — пин `test_a_composite_slot_prints_its_form.py`
#: пересчитывает запас сам и краснеет, если реестр вырос.
_FORM_CAP = 150

#: Ссылка «как у X выше» весит около 20 знаков; свёртывать подсказку короче
#: этого — платить каналом за ухудшение читаемости.
_COLLAPSE_MIN = 60

_РУССКИЕ_ТИПЫ = {"number": "число", "integer": "целое", "string": "строка",
                 "boolean": "да|нет", "null": "null"}


def _schema_of(ospec: spec.OpSpec) -> dict:
    """Схема опа из ОДНОГО носителя — `kir/schema_gen.py`.

    Ленивый импорт и кэш на оп: `schema_gen` тянет геометрию, а `dsl`
    грузится на каждом ходу.
    """
    cached = _SCHEMA_CACHE.get(ospec.name)
    if cached is None:
        try:
            from kir.schema_gen import _op_schema
            cached = (_op_schema(ospec) or {}).get("properties") or {}
        except Exception:  # noqa: BLE001 — форма слота не стоит хода
            cached = {}
        _SCHEMA_CACHE[ospec.name] = cached
    return cached


_SCHEMA_CACHE: dict[str, dict] = {}


def _short_schema(node: Any, depth: int = 0) -> str:
    """Схема → ОДНА строка формы, на русском и без JSON-шума.

    Переводит не всё, а то, чем слот ОТКАЗЫВАЕТ: имена ключей, что
    обязательно, тип и границы значения, словарь перечисления. Больше —
    в справке самого вида (`description` схемы) и в постусловии.
    """
    if not isinstance(node, dict):
        return "?"
    if "const" in node:
        return repr(node["const"])
    if "enum" in node:
        значения = [str(v) for v in node["enum"]]
        текст = "|".join(значения)
        if len(текст) > 60:
            текст = "|".join(значения[:4]) + "|…"
        return "«" + текст + "»"
    for ключ in ("oneOf", "anyOf"):
        if ключ in node:
            варианты = [_short_schema(v, depth + 1) for v in node[ключ][:3]]
            хвост = " | …" if len(node[ключ]) > 3 else ""
            return " | ".join(варианты) + хвост
    тип = node.get("type")
    if isinstance(тип, list):
        return "|".join(_РУССКИЕ_ТИПЫ.get(t, str(t)) for t in тип) + _границы(node)
    if тип == "array":
        if depth >= 2:
            return "[…]"
        внутри = _short_schema(node.get("items") or {}, depth + 1)
        сколько = ""
        lo, hi = node.get("minItems"), node.get("maxItems")
        if lo is not None or hi is not None:
            сколько = f" ×{lo if lo is not None else ''}..{hi if hi is not None else ''}"
        return f"[{внутри}{сколько}]"
    if тип == "object":
        if depth >= 2:
            return "{…}"
        свойства = node.get("properties") or {}
        обязательные = set(node.get("required") or ())
        куски = []
        for имя, под in свойства.items():
            звёздочка = "" if имя in обязательные else "?"
            куски.append(f"{имя}{звёздочка}: {_short_schema(под, depth + 1)}")
        return "{" + ", ".join(куски) + "}"
    if тип in _РУССКИЕ_ТИПЫ:
        return _РУССКИЕ_ТИПЫ[тип] + _границы(node)
    return "значение"


def _границы(node: dict) -> str:
    """Границы значения — и СТРОГОСТЬ границы вместе с ними.

    🔴 СТРОГОСТЬ НАЗВАНА, ПОТОМУ ЧТО ЗА ЕЁ МОЛЧАНИЕ УЖЕ ЗАПЛАЧЕНО
    (13.09.2026, живой прогон после починки, `cassettes-after-fix/shed-D.json`).
    Форма уклона печаталась как `0..90`, а в схеме стоит `exclusiveMinimum: 0`:
    модель написала `slopes=[30, 0, 30, 0]` — по значению на ребро, как и
    просили, — и получила отказ, потому что ровный скат обозначается `null`, а
    не нулём. Включительная запись строгой границы — это не приблизительность,
    а ЛОЖНОЕ РАЗРЕШЕНИЕ: она называет законным ровно то значение, которым оп
    отказывает.
    """
    строгий_низ = "exclusiveMinimum" in node
    строгий_верх = "exclusiveMaximum" in node
    lo = node.get("minimum", node.get("exclusiveMinimum"))
    hi = node.get("maximum", node.get("exclusiveMaximum"))
    if node.get("type") == "string" or "string" in (node.get("type") or ()):
        cap = node.get("maxLength")
        return f"<={cap}" if cap is not None else ""
    if lo is None and hi is None:
        return ""
    def _g(v: Any) -> str:
        return "" if v is None else (f"{v:g}" if isinstance(v, (int, float)) else str(v))
    низ = ("" if lo is None else ((">" if строгий_низ else "") + _g(lo)))
    верх = ("" if hi is None else (("<" if строгий_верх else "") + _g(hi)))
    return f" {низ}..{верх}"


def _composite_form(ospec: spec.OpSpec, p: spec.ParamSpec) -> str | None:
    """ФОРМА составного слота — ОДНА функция на весь реестр.

    🔴 ЗАКОН, А НЕ ПЕРЕЧЕНЬ. До 13.09.2026 форму печатал ОДИН вид — `region`
    (заявка 003), а остальные 28 составных видов печатали ГОЛОЕ ИМЯ РОДА, и
    хвост каждого их отказа кончался словами «приведи X к виду выше», где
    вида выше не было. Цена замерена в тот же день (замер DeepSeek ↔ СДК,
    `.work/prod-20260913/rq7-prep/deepseek_sdk/`): у руки со срезом раздела
    ВСЕ ТРИ попытки на сарае ушли в перебор соседних имён одного ключа слоя
    стены — `thickness_mm`, `thickness`, `width` при принятом `width_mm`, —
    потому что отказ называл ЛИШНИЕ ключи и молчал о ПРИНЯТЫХ. Ни одна
    догадка не попала; программа с готовым сараем так и не собралась.

    🔴 ОДИН МЕХАНИЗМ, А НЕ ДВА. Текст формы НЕ ПИШЕТСЯ ЗДЕСЬ: он ВЫВОДИТСЯ
    из схемы, которую реестр уже отдаёт двери (`kir/schema_gen.py`, там же
    границы, словари перечислений и обязательность). Второй рукописный
    носитель той же фразы — ровно тот дефект, против которого написана
    заявка 003, и повторять его нельзя. Исключение одно и оно НАЗВАНО:
    `region` берёт текст у `kir.contour` (`region_forms_text`), потому что
    обёртку `{outer, holes?}` — ту половину, которую переврали четыре
    независимых автора, — этот модуль несёт как единственный носитель, и
    пин N (`test_a_region_slot_says_it_wants_a_wrapper.py`) держит именно
    его слова. Развилка стоит В ОДНОЙ функции: механизм один, у него одна
    названная ветка, а не два механизма.
    """
    if p.kind == "region":
        from kir.contour import region_forms_text
        текст = region_forms_text(p.name)
        приставка = f"{p.name}: "
        return "\n".join(
            line[len(приставка):] if line.startswith(приставка) else line
            for line in текст.splitlines())
    node = _schema_of(ospec).get(p.name)
    if not isinstance(node, dict):
        # НЕЧЕГО СКАЗАТЬ — МОЛЧИМ. Вид без ветки в схеме (или оп, чья схема
        # не собралась) получает прежнее голое имя рода: выдуманная форма
        # хуже молчания, и её проверит ход.
        return None
    форма = _short_schema(node)
    if форма in ("?", "значение") or len(форма) < 3:
        return None
    if len(форма) > _FORM_CAP:
        форма = форма[:_FORM_CAP - 1] + "…"
    return f"{p.kind}: {форма}"


def _annotation(ospec: spec.OpSpec, p: spec.ParamSpec) -> _Ann:
    if p.kind in _SELECTOR_KINDS or p.kind in _SELECTOR_LIST_KINDS:
        forms = "|".join(_forms(ospec, p))
        refs = ("(" + ",".join(k.value for k in p.ref_kinds) + ")"
                if p.ref_kinds else "")
        listed = "[]" if p.kind in _SELECTOR_LIST_KINDS else ""
        return _Ann(f"{p.kind}{listed}: {forms}{refs}")
    if p.kind == "enum":
        return _Ann("enum{" + "|".join(map(str, p.choices)) + "}")
    if p.kind in ("mm", "num", "int", "deg"):
        return _Ann(f"{p.kind}{_bounds(p)}")
    if p.kind in ("str", "str_long"):
        cap = p.max_val if p.max_val is not None else 64
        return _Ann(f"{p.kind}<={cap}")
    if p.kind == "region":
        # 🔴 "THE SHAPE ABOVE" CANNOT BE A SINGLE WORD. Measurement
        # 25.08.2026: the tail of every slot refusal ends with "coerce X to
        # the shape above," and the shape was the annotation — for `region`,
        # the bare word "region." The author was getting:
        #
        #     contour.outer: ребро 0 описано дугой более одного раза
        #         contour  region
        #     СЛЕДУЮЩИЙ ХОД: приведи contour к виду выше; …
        #
        # That is, the move is unexecutable by construction. Yet the shape
        # is GENERATED right nearby — `contour.shape_forms_text` renders all
        # three shapes with all the fields from the registry, and its
        # docstring says outright that there is no handwritten copy here on
        # purpose. What was generated existed and was not being read.
        #
        # A local import: `contour` pulls in geometry, and `dsl` loads on
        # every turn.
        # 🔴 `region_forms_text`, А НЕ `shape_forms_text` (13.09.2026). Форма
        # без ОБЁРТКИ — правда о внутренней половине и молчание о внешней, а
        # читается как полный ответ: ту же ошибку сделали ЧЕТЫРЕ независимых
        # автора (матрицы T03 и P03/P04, оба Sonnet-исполнителя репетиции) и
        # пятым — прибор раздела S. Обёртку `{outer, holes?}` теперь несёт один
        # носитель, `kir.contour.REGION_FORM_RU`, и генератор ставит её ПЕРЕД
        # формами.
        # The slot name is printed by the caller once (`_slot_tail`: «    contour
        # <вид>»), and the generator puts it at the head of EACH of its two
        # texts — the wrapper and the shapes. Without stripping it the author
        # reads «contour contour: регион …», and stripping only the FIRST line
        # leaves «contour: форма …» in the middle of the slot's own help.
        # Само снятие приставки живёт теперь в `_composite_form` — там же, где
        # развилка «регион ↔ схема», чтобы носитель был один.
        return _Ann(_composite_form(ospec, p) or p.kind)
    # 🔴 ОСТАЛЬНЫЕ СОСТАВНЫЕ ВИДЫ — ПО ТОМУ ЖЕ ЗАКОНУ (13.09.2026).
    #
    # Двадцать восемь видов из двадцати девяти печатали здесь ГОЛОЕ ИМЯ РОДА,
    # и каждый их отказ кончался словами «приведи X к виду выше», где вида
    # выше не было. Замер того же дня назвал цену: три попытки из трёх ушли в
    # перебор `thickness_mm` → `thickness` → `width` при принятом `width_mm`.
    # Причина — не перечень видов, а ОТСУТСТВИЕ ЗАКОНА: форму печатал тот
    # вид, для которого её однажды написали руками. Теперь форма ВЫВОДИТСЯ из
    # схемы для любого вида, у которого схема есть, а у кого её нет — прежнее
    # голое имя, потому что выдуманная форма хуже молчания.
    форма = _composite_form(ospec, p)
    return _Ann(форма if форма is not None else p.kind)


def _return_annotation(ospec: spec.OpSpec) -> _Ann:
    if ospec.result_by_param is not None:
        # THE PARAMETER DECIDES THE KIND — and the signature must name WITH
        # WHAT, not pick one kind out of four: a signature naming "a wall"
        # for an op that can produce a roof type lies to the reader before
        # the compiler ever does.
        pname, table = ospec.result_by_param
        kinds = ", ".join(
            f"{value}->«{rspec.reference_kind.value}»"
            for value, rspec in table.items())
        return _Ann(f"Handle[ссылка, род решает {pname}: {kinds}]")
    if ospec.result.referenceable:
        return _Ann(f"Handle[ссылка «{ospec.result.reference_kind.value}»]")
    return _Ann("Handle[НЕ ссылка: by=ref этим опом не производится]")


def _docstring(ospec: spec.OpSpec) -> str:
    result = ospec.result
    if result.referenceable:
        result_line = (f"одна идентичность ({result.identity_field}); НА НЕЁ "
                       f"МОЖНО СОСЛАТЬСЯ как «{result.reference_kind.value}»")
    elif result.identity_cardinality is spec.IdentityCardinality.NONE:
        result_line = "идентичности нет (чтение)"
    elif result.identity_cardinality is spec.IdentityCardinality.MANY:
        result_line = (f"МНОЖЕСТВО идентичностей ({result.identity_field}); "
                       "ссылки внутри программы не даёт")
    else:
        result_line = (f"одна идентичность ({result.identity_field}), но "
                       "reference_kind не объявлен — ссылки не даёт")

    lines = [
        f"`{ospec.name}` — {ospec.family}, эффект {ospec.effect.value}"
        f"{', ПИШЕТ В МОДЕЛЬ' if ospec.writes_model else ''}.",
        "",
        f"Результат: {result_line}.",
        "",
        "ПОСТУСЛОВИЕ (контракт опа; проверяется свидетелем в транзакции):",
        f"    {ospec.post}",
        "",
        "Параметры — из реестра (kir/ops_*.py), не из этого файла:",
    ]
    # 🔴 THE OBSERVATION ABOUT THE HOST STANDS ABOVE THE PARAMETERS, AND
    # THIS IS NOT LAYOUT. It changes the WAY THE CALL IS MADE (how many
    # operations to put into one program), while the parameters answer the
    # question "what to fill it with," which comes UP AFTER. Read after the
    # slot list, it would arrive exactly too late for the work the warning
    # is meant to save. The reasoning and the cost are at the `caveat` field
    # itself.
    if getattr(ospec, "caveat", ""):
        lines[3:3] = ["🔴 ВАЖНО ПРИ ВЫЗОВЕ: " + ospec.caveat, ""]
    grounded = {name: pool for name, pool, _req in ospec.grounded}
    width = max((len(p.name) for p in ospec.params), default=0)
    # 🔴 THE FULL REGION FORM IS PRINTED ONCE PER CONTRACT, NOT ONCE PER SLOT.
    #
    # MEASURED 13.09.2026, and it cost a tail. The contract channel is 3300
    # characters (`course.LESSON_CAP`), and only the postcondition's PROSE can
    # be compressed: a contract whose text without prose already exceeds the
    # channel loses its END — where the parameter bounds and the witness
    # tolerances live. `create_solid_blend` is the one op in the registry with
    # TWO region slots (`profile`, `profile_top`), so the whole catalogue of
    # shapes was printed twice; after the wrapper line was added to the region
    # help it came to 3143 without prose against a channel of 3300 with a
    # margin of 2 — «хвост НЕ ДОЕХАЛ».
    #
    # The answer is not to weaken the channel and not to drop the wrapper —
    # the wrapper is the half four authors got wrong. It is to stop REPEATING
    # the identical catalogue: the second region slot names the wrapper (the
    # part that is actually mistaken) and points one line up for the shapes.
    # 🔴 ПРАВИЛО РАСШИРЕНО С РЕГИОНА НА ВСЕ СОСТАВНЫЕ ВИДЫ (13.09.2026).
    # Как только форму печатает не один вид, а двадцать девять, повтор
    # одинаковой формы внутри одного контракта перестаёт быть редкостью
    # (`create_wall`: два слота `pt_xy`; `create_solid_blend`: два региона), и
    # съеденный канал — та же потеря хвоста, что уже была оплачена однажды.
    # Свёртка делается ТОЛЬКО при ПОБУКВЕННОМ равенстве форм: два слота одного
    # рода в одном опе могут иметь разные схемы, и «как у X выше» стало бы
    # тогда ложью.
    # 🔴 СВЁРТКА КЛЮЧУЕТСЯ ПЕЧАТАЕМЫМ ТЕКСТОМ, А НЕ РОДОМ СЛОТА.
    #
    # Найдено сразу же собственным набором (13.09.2026, `test_course`): ключом
    # стоял РОД, и два слота одного рода с РАЗНОЙ подсказкой слились в одну
    # ложь — `type sel: как у `level` выше`, хотя у `level` пул `levels`, а у
    # `type` — `wall_types`, и печатается это разными строками
    # (`sel: …ref(level)` против `…ref(wall_type)`). Ту же цену заплатил
    # `top_offset_mm`: у `mm` подсказка и так короткая, и ссылка вверх выходила
    # ДЛИННЕЕ самой подсказки.
    #
    # Свёртка законна ровно при двух условиях: текст ПОБУКВЕННО тот же (иначе
    # это ложь) и он длиннее ссылки (иначе это не экономия). Порог назван
    # числом, а не вкусом: ссылка весит около 20 знаков.
    показанные: dict[str, str] = {}
    for p in ospec.params:
        текст = str(_annotation(ospec, p))
        первый = показанные.get(текст)
        if первый is not None and len(текст) > _COLLAPSE_MIN:
            if p.kind == "region":
                from kir.contour import REGION_FORM_RU
                bits = [f"{REGION_FORM_RU}; формы — как у `{первый}` выше"]
            else:
                bits = [f"{p.kind}: как у `{первый}` выше"]
        else:
            bits = [текст]
            показанные.setdefault(текст, p.name)
        bits.append("ОБЯЗАТЕЛЬНЫЙ" if p.required else "необязательный")
        if p.default is not None:
            bits.append(f"умолчание {p.default!r}")
        if p.name in grounded:
            bits.append(f"заземляется по пулу «{grounded[p.name]}»")
        lines.append(f"    {p.name:<{width}}  {'; '.join(bits)}")
    if not ospec.params:
        lines.append("    (нет)")
    # THE REGISTRY MAY NOT KNOW WHAT IS REQUIRED, AND THEN IT MUST SAY SO
    # OUT LOUD.
    #
    # MEASUREMENT 13.08.2026 (audit of the language axis). `p.required`
    # expresses UNCONDITIONAL requiredness, and the registry has no other
    # kind: `OpSpec` has eleven fields, and not one of them expresses a
    # relation between parameters. Conditional requiredness ("a point
    # requires level, a curve requires host") lives in handwritten branches
    # of the compiler and never rises into the registry.
    #
    # For an op with NOT A SINGLE parameter declared required, this text
    # used to read as "can be called empty" — and that is WRONG, not merely
    # incomplete: `place_family` with only a `symbol` is rejected by
    # `KIR-P007` ("no position given"). Such an op in the registry is
    # exactly one out of 69 (measured), but the condition is checked by
    # DERIVATION, not by name: the next such op will get this line on its
    # own, with no edit needed here.
    #
    # Why exactly this much is said. Naming HERE which fields are
    # conditional would mean writing out a second instance of a rule that
    # lives in the compiler — exactly the defect `SOLO_OPS` exists in one
    # line to forbid. The rule itself arrives via `OP_NOTES` below, it has
    # one source.
    if ospec.params and not any(p.required for p in ospec.params):
        lines += [
            "",
            "РЕЕСТР НЕ ОБЪЯВЛЯЕТ У ЭТОГО ОПА НИ ОДНОГО ОБЯЗАТЕЛЬНОГО ПАРАМЕТРА,",
            "и это НЕ разрешение вызвать его пустым: обязательность здесь",
            "УСЛОВНА (зависит от того, какой вариант вызова выбран) и потому",
            "проверяется компилятором, а не реестром. Что именно требуется в",
            "каждом варианте — ниже, в ловушке этого опа.",
        ]
    if ospec.tolerances:
        lines += ["", "Допуски свидетеля (реестр — единственный их источник):"]
        lines += [f"    {k} = {v:g}" for k, v in sorted(ospec.tolerances.items())]
    # THE REASON "DON'T LEAN ON THIS WITHOUT CHECKING" LIVES HERE, NOT IN
    # THE INSTRUMENT'S DESCRIPTION (09.08.2026, merge of the night waves).
    #
    # The measurement that forced the move: at 62 operations the
    # description grew to 30,440 against a ceiling of 30,000, and the
    # ceiling is not a matter of taste — it equals the declared ~10,000
    # tokens of the model's context (3.00 characters per token, measured on
    # this same text). The docstring of the test itself forbids raising it:
    # "from here on the text must not grow, it must displace itself."
    #
    # The displacement is done by cost, not by importance. The LIST of
    # unverified ops stays in the description — the model must know that an
    # op is unverified before it ever picks it. The REASON is needed
    # exactly when the model has already asked about this op, and it
    # arrives through the same `spec(op)` / `__doc__` as the rest of the
    # contract. Text that is always loaded is paid for on EVERY turn; a
    # docstring is paid for only on the turn it is asked about.
    #
    # The import is lazy on purpose: `tool_doc` pulls in `skill`, and that
    # pulls in `macros` and `compiler`, and a module-level import here would
    # close the graph into a cycle.
    from kir.tool_doc import OP_NOTES, UNPROVEN
    # THE OP'S OWN TRAPS — THE SECOND HALF OF THE SAME MOVE AS THE REASON
    # BELOW (09.08.2026). A trap that names one op and is only needed after
    # it has been CHOSEN (a group's construction, an envelope requirement on
    # `delete`, a fitting family on a route) used to sit in the
    # instrument's description and was paid for on EVERY turn — including
    # every one where this op is not even in the program. Here it is paid
    # for exactly on the turn it is asked about. No measurement was lost in
    # the move: `test_tool_doc` holds both sides of the seam — the text must
    # BE here and must be ABSENT from the description.
    for note in OP_NOTES.get(ospec.name, ()):
        lines += ["", "ЛОВУШКА ЭТОГО ОПА (замерена живьём):", f"    {note}"]
    entry = UNPROVEN.get(ospec.name)
    if entry is not None:
        # `.reason`, not the record itself: the journal also carries a
        # verdict and two dates — that bookkeeping is FOR US, and it is not
        # addressed to the model. Printing the whole record would hand the
        # author `Entry(verdict=…, decided_on=…)` instead of advice.
        lines += ["", "НЕ ОПИРАЙСЯ БЕЗ ПРОВЕРКИ:", f"    {entry.reason}"]
    lines += [
        "",
        "Вызов кладёт оп в текущую программу и возвращает ручку; `id` можно",
        "задать явно, иначе он выдаётся детерминированно.",
    ]
    return "\n".join(lines)


# ─────────────────────────────────────── the factory: a surface from the registry

def _call_head(ospec: spec.OpSpec) -> str:
    """ONE call-signature line: required, `*`, optional, `id`.

    Extracted out of `_call_form` because a second reader asks for it —
    `course.spec()`, which prints an op's contract on the model's request.
    Assembled anew there, this line would be a second opinion on slot order
    and would drift from the `_bind_refusal` refusal exactly when both texts
    are read one after the other.
    """
    required = [p for p in ospec.params if p.required]
    optional = [p for p in ospec.params if not p.required]
    head = ", ".join([p.name for p in required]
                     + (["*"] if optional else [])
                     + [f"{p.name}=…" for p in optional] + ["id=…"])
    return f"{ospec.name}({head})"


def _call_form(ospec: spec.OpSpec) -> str:
    """ALL of an op's slots in one reference — what the 04.08 measurement
    cost to buy.

    Counted across 27 refusals from two weak-model runs: 13 of them (the
    most frequent class, twice the next one) are a bare python `TypeError`
    from `Signature.bind`, "missing a required argument: 'variety'." It is
    correct and useless: it names ONE slot out of six and says nothing about
    `variety` being an enum of two values. The model was learning the
    signature ONE BIT AT A TIME: run wB, turns 4-15 — eleven in a row,
    missing → unexpected → missing. So the refusal prints the shape WHOLE:
    one turn instead of eleven.
    """
    required = [p for p in ospec.params if p.required]
    optional = [p for p in ospec.params if not p.required]
    rows = [f"    {_call_head(ospec)}"]
    width = max((len(p.name) for p in ospec.params), default=0)
    if required:
        rows.append("  ОБЯЗАТЕЛЬНЫЕ:")
        rows += [f"    {p.name:<{width}}  {_annotation(ospec, p)}"
                 for p in required]
    if optional:
        rows.append("  НЕОБЯЗАТЕЛЬНЫЕ (без них оп законен):")
        for p in optional:
            row = f"    {p.name:<{width}}  {_annotation(ospec, p)}"
            if p.default is not None:
                row += f"; умолчание {p.default!r} (ВПИШЕТ РЕЕСТР, не ты)"
            rows.append(row)
    return "\n".join(rows)


#: THE ANSWER TO THE REMAINDER OF THE CLASS, MEASURED ON THE FIXED SURFACE.
#:
#: The refusal prints the shape of ONE op — the one the script broke on.
#: Next it will break on the next unfamiliar one, and in the 04.08 run,
#: after the fix, this is visible directly: turn 2 —
#: `create_opening.variety`, turn 3 — `create_railing.variety`. One op per
#: turn instead of one slot per turn — better, but not free.
#:
#: The docstring of every language function is assembled from the registry
#: (`_docstring`) and is available RIGHT IN THE SCRIPT:
#: `print(create_railing.__doc__)`. This was said NOWHERE — not in the
#: instrument's description, not in the course — the capability was dark.
#: Verified by execution in the sandbox: the full list of slots prints with
#: kinds, bounds, and the postcondition, into the receipt of THAT SAME turn.
_DOC_HINT = ("ФОРМУ ЛЮБОГО ОПА МОЖНО ПРОЧЕСТЬ ДО ВЫЗОВА, не тратя ход: "
             "print(<имя_опа>.__doc__) — слоты, виды, границы и постусловие "
             "придут в квитанцию этого же хода. Незнакомые опы дешевле "
             "распечатать разом, чем узнавать по одному отказу за ход.")


def _bind_refusal(ospec: spec.OpSpec, exc: TypeError,
                  args: tuple, kwargs: dict) -> DslRefusal:
    """A bare `TypeError` from `Signature.bind` -> a typed KIR refusal.

    THE LAW (lead, 04.08): a refusal must name the NEXT MOVE, not just the
    diagnosis. The standard is KIR-L001 in `Program._append`: budget,
    culprit, what to do. The same here: what is missing, what is extra, and
    the WHOLE call shape — so the next move closes all slots at once, not
    just one.
    """
    known = {p.name for p in ospec.params} | {"id"}
    required = [p.name for p in ospec.params if p.required]
    unexpected = [k for k in kwargs if k not in known]
    filled = set(required[:len(args)]) | set(kwargs)
    missing = [n for n in required if n not in filled]
    form = _call_form(ospec)
    given = ", ".join(sorted(kwargs)) or "(ни одного именованного)"
    if len(args) > len(required):
        given += f"; позиционных {len(args)} при {len(required)} обязательных"

    if unexpected:
        return _refuse(
            code=PARSE_UNKNOWN_FIELD, field_name=unexpected[0],
            expected=sorted(known), got=unexpected,
            candidates=sorted(known),
            message_ru=(
                f"`{ospec.name}`: слота {', '.join(repr(u) for u in unexpected)}"
                f" у этого опа НЕТ. Поверхность языка — это реестр целиком, "
                f"и лишнее поле не отбрасывается молча: оно значит, что ты "
                f"держишь в голове другой оп.\n{form}\n"
                f"СЛЕДУЮЩИЙ ХОД: убери лишнее либо возьми имя из списка выше "
                f"(размеры почти везде идут с суффиксом `_mm`), и СРАЗУ сверь "
                f"остальные слоты — они все перечислены здесь.\n{_DOC_HINT}"))
    if missing:
        return _refuse(
            code=PARSE_MISSING_FIELD, field_name=missing[0],
            expected=required, got=given, candidates=missing,
            message_ru=(
                f"`{ospec.name}`: не задан ОБЯЗАТЕЛЬНЫЙ слот "
                f"{', '.join('`' + m + '`' for m in missing)}. "
                f"Умолчания у него нет намеренно — угаданный за автора выбор "
                f"неотличим снаружи от названного.\n{form}\n"
                f"Ты передал: {given}.\n"
                f"СЛЕДУЮЩИЙ ХОД: допиши недостающее и СРАЗУ сверь остальные "
                f"слоты по списку выше — второй такой отказ стоит ещё хода."
                f"\n{_DOC_HINT}"))
    return _refuse(
        code=TYPE_BAD_TYPE, field_name="(вызов)", expected=required, got=given,
        message_ru=(f"`{ospec.name}`: вызов не сходится с формой опа "
                    f"({exc}).\n{form}\n"
                    f"Ты передал: {given}.\n"
                    f"СЛЕДУЮЩИЙ ХОД: передавай слоты ПО ИМЕНИ — необязательные "
                    f"иначе позиционно не принимаются вовсе."))


def _make_op_fn(ospec: spec.OpSpec):
    P = inspect.Parameter
    # The registry interleaves required and optional, python cannot: a
    # parameter without a default cannot come after a parameter that has
    # one. So in the signature the required ones come first (as in sdk.py),
    # while IN JSON the fields are written IN REGISTRY ORDER — the program
    # is read by eye.
    params = [P(p.name, P.POSITIONAL_OR_KEYWORD,
                annotation=_annotation(ospec, p))
              for p in ospec.params if p.required]
    params += [P(p.name, P.KEYWORD_ONLY,
                 default=(OMIT if p.default is None
                          else _RegistryDefault(p.default)),
                 annotation=_annotation(ospec, p))
               for p in ospec.params if not p.required]
    # `id` is not a registry parameter, it is the op's ADDRESS: neighbors
    # reference the op by it.
    params.append(P("id", P.KEYWORD_ONLY, default=OMIT,
                    annotation=_Ann("str<=64 (иначе выдаётся сам)")))
    sig = inspect.Signature(params, return_annotation=_return_annotation(ospec))

    def op_fn(*args: Any, **kwargs: Any) -> Handle:
        try:
            bound = sig.bind(*args, **kwargs)
        except TypeError as exc:
            # A bare `TypeError` used to leave here for the model as is —
            # see `_bind_refusal`.
            raise _bind_refusal(ospec, exc, args, kwargs) from None
        bound.apply_defaults()
        oid = bound.arguments.pop("id")
        payload: dict[str, Any] = {}
        for p in ospec.params:                 # REGISTRY ORDER
            value = bound.arguments[p.name]
            # A MARKER, NOT CLASS IDENTITY — the reasoning and the
            # measurement are at the marker itself
            # (`_RegistryDefault.__kir_registry_default__`). `isinstance` is
            # left alongside: it is correct in ordinary life and cheaper,
            # while the marker catches the case where the module was
            # reloaded and there are now two classes.
            if (value is OMIT or value is None
                    or _is_registry_default(value)):
                continue
            payload[p.name] = _coerce(ospec, p, value)
        return current()._append(ospec, payload, oid)

    op_fn.__name__ = ospec.name
    op_fn.__qualname__ = ospec.name
    op_fn.__module__ = __name__
    op_fn.__signature__ = sig
    op_fn.__doc__ = _docstring(ospec)
    op_fn.op_spec = ospec
    return op_fn


def _coerce_members(ospec: spec.OpSpec, p: spec.ParamSpec, value: Any) -> Any:
    """Handles -> GROUP MEMBERS, pulled out of the program. Measured
    19.08.2026.

    🔴 WHY THIS WAS A HOLE, NOT AN INCONVENIENCE. `create_group` is the
    language's one and only repeater (a panel of 19 operations at 40 spots =
    760 elements in one program), and in the marathon building the WHOLE
    frame lived inside its members: 372 placements. Yet from `program_py`
    the group could not be built AT ALL: the call returns a handle, a handle
    is not JSON-representable, and the sandbox answered `KIR-B008: a value
    of type Handle`. That is, the language's main multiplier was available
    ONLY through the handwritten `program` — and python, for whose
    expressiveness the whole thing was started, turned out WEAKER than the
    dictionary at this exact spot.

    The shape of the contradiction: accumulation in `dsl` is IMPLICIT (the
    call itself puts the op into the program), while a group member is an
    op that MUST NOT BE in the program, it lies INSIDE the group. So the
    handle here is not a "reference," it is a WITHDRAWAL: the op is pulled
    out of the program and moves into the members. Hence also the one
    legitimate order — build the members first, then assemble the group out
    of them.

    A handle pulled out twice, and a handle from someone else's program,
    give a NAMED refusal: silently returning an empty list would mean
    building a group with no members, and that is exactly "a zero of a
    quantity nobody was counting."
    """
    if not isinstance(value, (list, tuple)):
        raise _refuse(
            code=TYPE_BAD_TYPE, field_name=p.name,
            expected="список ручек либо готовых операций",
            got=type(value).__name__,
            message_ru=(f"{ospec.name}.{p.name}: члены группы — СПИСОК. "
                        f"Собери их обычными вызовами и передай ручки: "
                        f"`w = create_wall(...); create_group(members=[w], ...)`"))
    # 🔴 TWO PASSES, AND THIS IS NOT CAUTION, IT IS A PROPERTY (F-097,
    # 29.08.2026). The withdrawal used to sit INSIDE parsing: `prog.take`
    # was called on every handle immediately, and the check of the
    # remaining members happened AFTER. An illegal member N+1 carried away
    # with it members 0..N, already pulled out of the program, and did not
    # return them.
    #
    # The cost is not in the lost ops, it is in the NEXT MOVE: the author
    # fixed exactly what the refusal pointed at, repeated the call
    # legitimately — and got a SECOND refusal, about a DIFFERENT member,
    # whose cause lay in the FIRST attempt ("operation 'wall1' is not in the
    # program"). The model, reading the last refusal, went off to fix an op
    # that does not exist, because we ourselves had eaten it.
    #
    # The property: until the whole list is declared legitimate, NOTHING
    # disappears from `prog.ops`. Returning what was withdrawn would instead
    # require restoring not only the membership, but the ORDER of the ops
    # too — i.e. setting up a second implementation of the rule "where an op
    # stands," which would drift from the first. Leaving it alone is cheaper
    # than fixing it.
    prog = current()
    claimed: set[str] = set()
    for i, item in enumerate(value):
        if isinstance(item, Handle):
            # Presence can be asked ANY WAY AT ALL, but only `take` performs
            # the withdrawal: it is the one point of withdrawal and must
            # remain the only one.
            present = any(op.get("id") == item.id for op in prog.ops)
            if not present or item.id in claimed:
                raise _refuse(
                    code=TYPE_BAD_TYPE, op_id=item.id,
                    field_name=f"{p.name}[{i}]",
                    expected="ручка операции ЭТОЙ программы, ещё не взятой",
                    got=item.id,
                    message_ru=(
                        f"{ospec.name}.{p.name}[{i}]: операции «{item.id}» в "
                        f"программе нет. Так бывает в двух случаях, и оба "
                        f"чинятся по-разному: ручка УЖЕ ушла в другую группу "
                        f"(один оп не может быть членом двух групп — построй "
                        f"его второй раз) либо ручка из программы, законченной "
                        f"`build()`/`reset()` раньше")
                    if not present else (
                        f"{ospec.name}.{p.name}[{i}]: ручка «{item.id}» стоит "
                        f"в этом списке ДВАЖДЫ. Один оп не может быть членом "
                        f"группы дважды — построй его второй раз и передай "
                        f"вторую ручку"))
            claimed.add(item.id)
        elif not isinstance(item, dict):
            raise _refuse(
                code=TYPE_BAD_TYPE, field_name=f"{p.name}[{i}]",
                expected="ручка операции либо готовая операция словарём",
                got=type(item).__name__,
                message_ru=(
                    f"{ospec.name}.{p.name}[{i}]: член группы — это ОПЕРАЦИЯ. "
                    f"Передай ручку вызова (`w = create_wall(...)`), а не "
                    f"{type(item).__name__}"))
    # THE SECOND PASS. The list has already been declared legitimate as a
    # whole — only now does the program change.
    out: list = []
    for item in value:
        out.append(prog.take(item.id) if isinstance(item, Handle)
                   else _plain(item))
    return out


def _coerce(ospec: spec.OpSpec, p: spec.ParamSpec, value: Any) -> Any:
    if p.kind in _SELECTOR_KINDS:
        return _coerce_selector(ospec, p, value)
    if p.kind in _SELECTOR_LIST_KINDS:
        if not isinstance(value, (list, tuple)):
            raise _selector_error(ospec, p, value, "ожидается СПИСОК адресов")
        return [_coerce_selector(ospec, p, item) for item in value]
    if p.kind == "member_ops":
        return _coerce_members(ospec, p, value)
    return _plain(value)


#: The surface of the language. Exactly as many functions as there are ops
#: in the registry, always.
OP_FUNCTIONS: dict[str, Any] = {name: _make_op_fn(ospec)
                                for name, ospec in sorted(spec.OPS.items())}
globals().update(OP_FUNCTIONS)


def __getattr__(name: str):
    """An op the registry does not have — refused BY NAME, with a next move.

    🔴 BOUGHT BY A MEASUREMENT, 13.09.2026 (RQ7 preparation, refusal corpus
    case `m17`). A model that invents an operation — `create_balcony` — used
    to get python's own `AttributeError`: **50 characters, no next move, no
    hint that a registry even exists**. In an experiment where the model has
    three rounds, that is a dead end, not a round; and inventing a plausible
    name is the FIRST thing a model does when it does not know the surface.

    The refusal now says the same three things every other refusal in this
    tree says: what happened, what the boundary is, and what to do next. The
    nearest existing names are offered by `difflib` — not as a guess the
    author must trust, but next to `dsl.op_names()`, which is the whole truth.
    """
    if name.startswith("_"):
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import difflib

    known = sorted(spec.OPS)
    near = difflib.get_close_matches(name, known, n=3, cutoff=0.6)
    guess = f" Похожие имена: {', '.join(near)}." if near else ""
    raise AttributeError(
        f"в реестре KIR нет операции «{name}». Операций всего {len(known)}."
        f"{guess}"
        " СЛЕДУЮЩИЙ ХОД: возьми имя из dsl.op_names() (или dsl.op_names(writes=True)"
        " — только пишущие в модель); справка по слотам — help(dsl.<имя>).")


__all__ += sorted(OP_FUNCTIONS)


def op_names(*, writes: bool | None = None) -> list[str]:
    """Names of registry ops; `writes=True` — only those that write to the
    model."""
    return sorted(n for n, o in spec.OPS.items()
                  if writes is None or o.writes_model is writes)


# ───────────────────────────────────────────────────────────── the program

def _author_frames() -> list[int]:
    """Lines of the author's script that led to this call. Empty outside the
    sandbox.

    WITH NO IMPORT AND NO PERMISSION TO CRASH, by the same technique as
    `sandbox.course_reads`.

    🔴 WHY NOT `from kir.sandbox import author_frames`. The sandbox loads the
    language BY NAME (`dsl_module`, defaulting to `kir.dsl`) — an edge in
    the reverse direction would set up a dependency "the language requires
    its own launcher," and that is not true: the language lives perfectly
    well without the sandbox, just without provenance. By the moment the
    author's script calls an operation, `kir.sandbox` is ALREADY loaded in
    this process by itself, so it is enough to look in `sys.modules`.

    The walk is NOT duplicated: the rule for selecting the author's frames
    and the shape of the list live in `sandbox.author_frames`, here there is
    only its call.

    Empty is a legitimate and frequent outcome: the language was called
    directly, from a test or from `sdk`, and there is no author script at
    all.
    """
    try:
        module = _sys.modules.get("kir.sandbox")
        walk = getattr(module, "author_frames", None) if module else None
        return list(walk()) if callable(walk) else []
    except Exception:  # noqa: BLE001 — provenance must not be allowed to crash assembly
        return []


class Program:
    """One KIR program: the envelope, the ops, the handles.

    Accumulation is IMPLICIT: ops land here from calls, not from
    `add(...)`. A program is not the whole building: the v1 limit is the
    INTERNAL bulk budget (`MAX_BULK_OPS`), and exceeding it is a typed
    refusal, not a silent cutoff.
    """

    def __init__(self, *, intent: str | None = None,
                 allow_destructive: bool | None = None,
                 defaults: dict | None = None,
                 lineage: str | None = None) -> None:
        self.intent = intent
        self.lineage = lineage
        # THE FIRST OF THREE DOORS. The refusal must arrive at THE AUTHOR'S
        # LINE, not in `build()` forty calls later: by then the author no
        # longer remembers where they wrote a word instead of a boolean.
        self.allow_destructive = (
            None if allow_destructive is None
            else _exactly_bool(allow_destructive, "allow_destructive"))
        self.defaults = dict(defaults) if defaults else None
        self.ops: list[dict] = []
        self._seq: dict[str, int] = {}
        self._ids: set[str] = set()
        self._previous: "Program | None" = None
        #: PROVENANCE: `{id опа: [строки скрипта снаружи внутрь]}`.
        #: A sidecar, NOT a field of the operation: the compiler fails
        #: closed on an unfamiliar field (`KIR-P003`), and that is correct —
        #: provenance must not change the program's identity. `build()` does
        #: not hand it out by construction; it ships outward through a
        #: separate door, `take_lineage()`.
        self._lineage: dict[str, list[int]] = {}

    # ── accumulation ──────────────────────────────────────────────────────
    def _next_id(self, op_name: str) -> str:
        # The same scheme as `sdk._OpSink._next_id`: a program assembled by
        # two python front ends must get the SAME addresses, otherwise "the
        # same thing" stops being a verifiable comparison.
        n = self._seq.get(op_name, 0) + 1
        self._seq[op_name] = n
        stem = op_name[7:] if op_name.startswith("create_") else op_name
        return f"{stem}{n}"

    def take(self, oid: str) -> dict | None:
        """WITHDRAW an op from the program by address. Needed by the group —
        see `_coerce_members`.

        Returns the operation's own dict and removes it from `ops`; `None`
        if no such address exists in the program (already taken, or from
        someone else). The address is NOT freed back into `_ids` in the
        process: reissuing an id once taken would make two different
        operations indistinguishable in the receipt.
        """
        for i, op in enumerate(self.ops):
            if op.get("id") == oid:
                return self.ops.pop(i)
        return None

    def _census(self, top: int = 6) -> str:
        """What managed to accumulate, by kind. A line for a REFUSAL, not
        for a report."""
        tally: dict[str, int] = {}
        for op in self.ops:
            name = op.get("op", "?")
            tally[name] = tally.get(name, 0) + 1
        ordered = sorted(tally.items(), key=lambda kv: (-kv[1], kv[0]))
        shown = ", ".join(f"{name} {count}" for name, count in ordered[:top])
        if len(ordered) > top:
            shown += f", и ещё {len(ordered) - top} родов"
        return shown

    def _append(self, ospec: spec.OpSpec, payload: dict, oid: Any) -> Handle:
        if len(self.ops) >= _DSL_OP_CEILING:
            # D-7, MEASUREMENT 03.08. The refusal used to arrive WITHOUT the
            # one number it is read for: how much had accumulated and out of
            # what. Printing the totals, which the course tells the author
            # to put at the end of the script, does not execute AT ALL under
            # THIS refusal — the script was cut off at operation #301 — and
            # the receipt's `stdout` arrives empty. So the census must ride
            # IN THE REFUSAL ITSELF: otherwise the model learns that it hit
            # a wall, but not WHAT exactly multiplied, and the next move
            # starts from zero, blind. (Before 21.08.2026 the census was
            # read to decide WHERE TO CUT. Cutting is no longer needed —
            # chunking is wired to the door; the census is now read to find
            # the runaway loop. The same number, a different question.)
            raise _refuse(
                code=PLAN_LIMIT, field_name="ops", expected=f"<={_DSL_OP_CEILING}",
                got=len(self.ops) + 1,
                message_ru=(
                    f"исчерпан ВНУТРЕННИЙ bulk-бюджет ({BUDGET_INTERNAL_BULK}) "
                    f"— {_DSL_OP_CEILING} опов на программу. Это ЗАЩИТА ОТ "
                    "РУНАВЭЯ, а не предел транспорта: чанкование прямого хода "
                    "подключено к двери (21.08.2026), и программа, не влезающая "
                    "в кадр моста, идёт срезами сама — резать её в питоне "
                    "больше НЕ НАДО. Столько опов из одного цикла значит, что "
                    "цикл сорвался: проверь его границы.\n"
                    f"СОБРАНО ДО ОТКАЗА: {len(self.ops)} операций — "
                    f"{self._census()}. Наружу не выйдет НИ ОДНА: отказ "
                    f"песочницы обнуляет ход целиком, и печать в конце скрипта "
                    f"тоже не выполнилась. По этой переписи и ищи цикл, "
                    f"который размножился"))
        if oid is OMIT or oid is None:
            oid = self._next_id(ospec.name)
        elif not isinstance(oid, str) or not (1 <= len(oid) <= 64):
            raise _refuse(code=TYPE_BAD_TYPE, field_name="id", got=repr(oid),
                          expected="строка 1..64 символа",
                          message_ru="id опа — строка 1..64 символа")
        if oid in self._ids:
            raise _refuse(
                code=PARSE_DUP_ID, op_id=oid, field_name="id", got=oid,
                candidates=sorted(self._ids),
                message_ru=(f"id «{oid}» в этой программе уже занят: ручка — "
                            "адрес, и одинаковые адреса молча перевязали бы "
                            "ссылки на чужой оп"))
        self._ids.add(oid)
        # PROVENANCE IS CAPTURED HERE, BECAUSE THIS IS WHERE THE OP IS BORN.
        # `_append` is the one place in the whole language where an
        # operation lands in the program; capturing the address at every
        # `op_fn` would mean setting up seventy-seven carriers of one fact.
        frames = _author_frames()
        if frames:
            self._lineage[oid] = frames
        # `op` and `id` come first: the program is read by eye more often
        # than by a parser.
        self.ops.append({"op": ospec.name, "id": oid, **payload})
        return Handle(oid, ospec.name, ospec, payload)

    # ── the envelope ─────────────────────────────────────────────────────
    def envelope(self, *, intent: Any = OMIT, allow_destructive: Any = OMIT,
                 defaults: Any = OMIT, lineage: Any = OMIT) -> "Program":
        """The envelope's fields — the same as JSON's, there are no others
        (`ir_version` is set by the registry itself)."""
        if intent is not OMIT:
            self.intent = intent
        if lineage is not OMIT:
            self.lineage = lineage
        if allow_destructive is not OMIT:
            # THE SECOND DOOR. It is exactly through this that the envelope
            # is set by the script, and fixing only one `__init__` would
            # leave the author's main path free to lie.
            self.allow_destructive = (
                None if allow_destructive is None
                else _exactly_bool(allow_destructive, "allow_destructive"))
        if defaults is not OMIT:
            self.defaults = dict(defaults) if defaults else None
        return self

    def _defaults_json(self) -> dict:
        """Selectors for the whole program. Coerced by the same sugar, but
        against the `_defaults_schema` catalog — the envelope is not tied to
        one op."""
        out = {}
        for key, value in (self.defaults or {}).items():
            if isinstance(value, dict) or value is None:
                out[key] = _plain(value)
            elif isinstance(value, Handle):
                out[key] = value.as_selector()
            elif isinstance(value, sdk.Ref):
                out[key] = {"by": "ref", "value": value.id}
            elif value is DEFAULT:
                out[key] = {"by": "default"}
            elif isinstance(value, bool):
                raise _refuse(code=GROUND_BAD_SELECTOR, field_name="defaults",
                              got=repr(value), candidates=list(DEFAULTABLE),
                              message_ru="bool — не адрес элемента")
            elif isinstance(value, int):
                out[key] = {"by": "element_id", "value": int(value)}
            elif isinstance(value, str):
                out[key] = {"by": "name", "value": value}
            else:
                raise _refuse(code=GROUND_BAD_SELECTOR, field_name="defaults",
                              got=repr(value), candidates=list(DEFAULTABLE),
                              message_ru=f"defaults.{key} — не селектор")
        return out

    # ── the output ───────────────────────────────────────────────────────
    def build(self) -> dict:
        """EXACTLY the JSON the compiler accepts. Not a wrapper, not its own
        order, not its own fields."""
        out: dict[str, Any] = {"ir_version": spec.IR_VERSION}
        if self.intent is not None:
            out["intent"] = self.intent
        if self.lineage is not None:
            # Native identity is distinct from the source-line `_lineage` sidecar.
            out["lineage"] = self.lineage
        if self.allow_destructive is not None:
            # THE THIRD DOOR, AND THE VERY SPOT OF THE DEFECT. `bool(...)`
            # used to stand here. The field is public, and
            # `p.allow_destructive = "false"` by assignment bypasses both
            # doors above: without this line the law would hold only on the
            # author's good manners.
            out["allow_destructive"] = _exactly_bool(
                self.allow_destructive, "allow_destructive")
        if self.defaults:
            out["defaults"] = self._defaults_json()
        out["ops"] = [dict(op) for op in self.ops]
        return out

    def plan(self, *, bulk: bool = True):
        """`compiler.plan_program` — the ONE semantic entry point downward.

        `bulk=True` by default, and this follows from WHAT the author's unit
        is here. The author's budget (20) measures a program WRITTEN BY THE
        MODEL; it does not measure a program written by python — just as it
        does not measure a materializer's chunk. The author's thing here is
        the script, and its size is not expressed by an op budget at all.
        Whoever wants to measure the DSL's output by the author's budget
        calls `plan(bulk=False)` and gets the same refusal as chat does.
        """
        from kir.compiler import plan_program
        return plan_program(self.build(), bulk=bulk)

    # ── context ────────────────────────────────────────────────────────
    def __enter__(self) -> "Program":
        return self

    def __exit__(self, *exc: Any) -> bool:
        global _CURRENT
        if _CURRENT is self and self._previous is not None:
            _CURRENT = self._previous
        return False

    def __len__(self) -> int:
        return len(self.ops)

    def __iter__(self):
        return iter(self.ops)

    def __repr__(self) -> str:
        return f"Program({len(self.ops)} опов, intent={self.intent!r})"


#: The module's current program. It lives in the module, not in an object,
#: for exactly one reason: so the script reads as a script.
#:
#: WHAT THIS COSTS IS SAID OUTRIGHT: module-level state is NOT thread-safe
#: and does not isolate two scripts spinning in one interpreter — they will
#: write ops into each other. A lock here would fix nothing (interleaved
#: calls stay interleaved) and would only hand out false reassurance.
#: Script isolation is a property of the SANDBOX (a fresh interpreter per
#: script); within one process it is provided by `reset()` and
#: `with program(...)`, and there is a test for it.
_CURRENT = Program()

#: Provenance captured by the last `take_ops()`. Separate from `_CURRENT`,
#: because `take_ops` zeroes out the program, and the sandbox only manages
#: to collect the sidecar on the following call. Zeroed by `take_lineage()`
#: for the same isolation reasoning as the program itself.
_DRAINED_LINEAGE: dict[str, list[int]] = {}


def current() -> Program:
    """The program that calls are currently accumulating into."""
    return _CURRENT


#: PROGRAMS THE AUTHOR LEFT BEHIND. The door executes the script's CURRENT
#: program; `reset()` starts a new one, and nobody will ever execute the
#: previous one.
#:
#: 🔴 MEASUREMENT 03.09.2026, AND THIS IS CAUGHT BY A COUNT ALONE. Our own
#: "жильё" recipe is written as TWO programs — that is what `KIR-L002`
#: demands: "a staircase owns its own transactions and lives in a separate
#: program." Through the live door only the SECOND is built, and the
#: staircase disappears silently: no refusal, no line, no field. The judge
#: then honestly prints "HAB011: there are NO staircases AT ALL in the
#: model, `create_stairs` was never called" — and sends the author off to
#: fix the program that DOES contain the call. Three habitation rules
#: (HAB001, HAB010, HAB012) stay silent for the same reason, meaning the
#: FIT verdict is unreachable for a program that we ourselves are teaching
#: people to write.
#:
#: What executes does NOT change here: that is a decision about
#: transactions, and it belongs to someone else. What is named here is the
#: LOSS — by the same law as `verdict_silent_because`.
_LEFT_BEHIND: list[dict[str, Any]] = []


def left_behind() -> tuple[dict[str, Any], ...]:
    """What the author left behind: the envelope and the operation count of
    each program."""
    return tuple(dict(item) for item in _LEFT_BEHIND)


def forget_left_behind() -> None:
    """Forget the bookkeeping (a process outliving a single script happens
    only in tests)."""
    _LEFT_BEHIND.clear()


def reset(**envelope_kw: Any) -> Program:
    """Start a new empty program. Returns it.

    The previous program, if it had operations, GOES INTO THE
    BOOKKEEPING: the door will build only the current one, and staying
    silent about this would cost the author half the house.
    """
    global _CURRENT
    прежняя = _CURRENT
    if прежняя is not None and getattr(прежняя, "ops", None):
        _LEFT_BEHIND.append({"intent": прежняя.intent,
                             "ops": len(прежняя.ops)})
    _CURRENT = Program(**envelope_kw)
    return _CURRENT


def program(*, intent: str | None = None,
            allow_destructive: bool | None = None,
            defaults: dict | None = None,
            lineage: str | None = None) -> Program:
    """An explicit program. Made current IMMEDIATELY, so this works both
    this way:

        with program(intent="этаж"):
            create_wall(...)

    and this way:

        p = program(intent="этаж")
        create_wall(...)
        prog = p.build()

    In the `with` form, the previous program is put back in place on exit.
    """
    global _CURRENT
    fresh = Program(intent=intent, allow_destructive=allow_destructive,
                    defaults=defaults, lineage=lineage)
    fresh._previous = _CURRENT
    _CURRENT = fresh
    return fresh


def envelope(*, intent: Any = OMIT, allow_destructive: Any = OMIT,
             defaults: Any = OMIT, lineage: Any = OMIT) -> Program:
    """The current program's envelope."""
    return current().envelope(intent=intent,
                              allow_destructive=allow_destructive,
                              defaults=defaults, lineage=lineage)


def ops() -> list[dict]:
    """The current program's ops, as they will ship into JSON."""
    return [dict(op) for op in current().ops]


def build() -> dict:
    """The current program's JSON."""
    return current().build()


def plan(*, bulk: bool = True):
    """`plan_program` over the current program."""
    return current().plan(bulk=bulk)


def take_ops() -> dict | None:
    """THE SANDBOX'S DOOR, not the author's. Collect what has accumulated
    and zero it out.

    `sandbox.py` polls the language under this name FIRST
    (`_DRAIN_CANDIDATES`), and it understands the envelope: a dict with an
    `ops` key is parsed into `intent`/`defaults`/`allow_destructive` plus
    the ops themselves. That is why `build()` is handed over here whole —
    otherwise an envelope set by the script would be lost silently.

    EMPTY means `None`, NOT an empty envelope. The sandbox's contract also
    allows a second path: the script puts a ready-made list into an `ops`
    variable. If drain returned a truthy value at zero accumulated, it would
    claim that path for itself and the script's variable would never fire.

    Zeroing here is not tidying, it is isolation: two scripts in one
    interpreter must not see each other's ops (see the comment at
    `_CURRENT`).

    Deliberately NOT in `__all__`: the sandbox calls it through the module,
    and the script's author has no reason to drain their own program — it
    is drained for them.
    """
    global _DRAINED_LINEAGE
    prog = current()
    if not prog.ops:
        return None
    out = prog.build()
    # PROVENANCE IS CAPTURED BEFORE `reset()`, OTHERWISE IT DIES ALONG WITH
    # THE PROGRAM. It cannot be put into `out` — `build()` hands out EXACTLY
    # the JSON the compiler accepts, and it rejects an unfamiliar envelope
    # key with `KIR-P003` (verified by execution). Hence a second door.
    _DRAINED_LINEAGE = dict(prog._lineage)
    reset()
    return out


def take_lineage() -> dict | None:
    """THE SANDBOX'S DOOR FOR PROVENANCE. Collect what `take_ops()` captured
    and zero it out.

    A separate door, not a field on `take_ops()`, for the same reason a
    sidecar is not a field of the operation: what `take_ops` hands out ships
    whole into the compiler, and an extra key there is a typed refusal.

    Zeroing, as with `take_ops`, is isolation: two scripts in one
    interpreter must not see each other's provenance.

    NOT in `__all__`: the script's author has nothing to do here, this door
    is for the sandbox.
    """
    global _DRAINED_LINEAGE
    out = _DRAINED_LINEAGE
    _DRAINED_LINEAGE = {}
    return out or None
