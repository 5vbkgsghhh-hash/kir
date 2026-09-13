"""FAMILY AUTHORING: the door, the flexibility witness, and the version
split.

WHAT THIS FILE GUARDS, IN THE WORDS OF THE MEASUREMENT, NOT THE INTENT.

A live run on 21.08.2026 (Revit 2026) showed that a family parameter
WITHOUT binding passes completely silently: `Высота_KIR` was changed from
800 to 1600, and the volume stayed at 192 000 000 = 600 x 400 x 800. With
binding, the same measurement gives 192 000 000 -> 384 000 000, a ratio of
2.0000. So what must be guarded is not «is there an Associate call» (it
can be written and still not work), but the MEASUREMENT OF DOUBLING
ITSELF in the emitted program — and it must be guarded by MUTATION,
because a marker whose removal leaves the certificate green proves
nothing.
"""
from __future__ import annotations

import pytest

from kir import spec, translation_cert as tc
from kir.authoring import _SOLO_PROGRAMS
from kir.compiler import compile_program, plan_program
from kir import ground as ground_mod
from kir.reverse_contract import (REVERSE_CONTRACTS, ReverseGuarantee,
                                       ReverseMode)


_BASE = {
    "op": "author_family", "id": "AF1",
    "family_name": "KIR_Куб", "type_name": "Куб 600x400",
    "profile": {"outer": {"shape": "rect", "origin": [0, 0],
                          "size_mm": [600, 400]}},
    "height_mm": 800, "flex_param": "Высота_KIR",
}


def _program(**extra) -> dict:
    return {"ir_version": "1.0", "intent": "авторское семейство",
            "ops": [{**_BASE, **extra}]}


def _cs(ver: str = "2026", **extra) -> str:
    out = compile_program(_program(**extra), ver, snapshot={})
    assert out.ok, [(d.code, d.message_ru) for d in out.diagnostics]
    return out.csharp


def _grounded(**extra) -> dict:
    planned = plan_program(_program(**extra))
    return ground_mod.ground_program(planned, {}).to_ops()[0]


# ── the door ─────────────────────────────────────────────────────────────

def test_door_is_solo_and_registered():
    """The keys of `_SOLO_PROGRAMS` must match `spec.SOLO_OPS`.

    The same invariant the three staircase ops live by: a name that lands
    in one list but not the other will drift into the WRONG program
    template and get the wrong emission instead of a refusal.
    """
    assert "author_family" in spec.SOLO_OPS
    assert set(_SOLO_PROGRAMS) == set(spec.SOLO_OPS)


def test_solo_op_refuses_a_neighbour():
    """Nothing can be wedged between the authoring steps: the family
    document does not survive the program boundary, so there can be no
    neighbor."""
    prog = _program()
    prog["ops"].append({"op": "create_wall", "id": "W1",
                        "p0_mm": [0, 0], "p1_mm": [3000, 0],
                        "level": {"by": "element_id", "value": 42}})
    out = compile_program(prog, "2026", snapshot={})
    assert not out.ok
    assert any("author_family" in (d.message_ru or "") for d in out.diagnostics)


# ── flexibility as an obligation ────────────────────────────────────────

def test_flex_is_measured_by_doubling_not_by_reading_a_field():
    """The program must contain a MEASUREMENT of the doubling, not a read
    of the parameter."""
    cs = _cs()
    assert "AssociateElementParameterToFamilyParameter" in cs
    # Doubling: the value is set, the document is regenerated, the volume
    # is read.
    assert "U(1600.0)" in cs
    assert cs.count("Regenerate()") >= 3
    assert "2.0 * __v1_AF1" in cs
    # ...and the value is RESTORED, or the family would end up twice as
    # tall.
    assert cs.count("U(800.0)") >= 2


def test_flex_guard_is_load_bearing_under_mutation(monkeypatch):
    """Cut out the doubling guard — the certificate must turn RED.

    The marker chosen is THE ARITHMETIC ITSELF (`2.0 * __v1_`), not an API
    name: the 21.08 measurement showed that `Associate...` can be written
    and still not work. The same lesson `create_stairs` paid for with the
    `__actR` marker instead of `DesiredRisersNumber`.
    """
    op = _grounded(place_at=[1000, 2000, 0])
    assert tc.certify_op(op, "2026").proven

    original = _SOLO_PROGRAMS["author_family"]

    def _mutant(o, ver, intent="", **kw):
        text = original(o, ver, intent, **kw)
        # We remove exactly the flexibility verdict, leaving everything
        # else in place.
        return text.replace("2.0 * __v1_AF1", "__v1_AF1")

    monkeypatch.setitem(_SOLO_PROGRAMS, "author_family", _mutant)
    cert = tc.certify_op(op, "2026")
    assert not cert.proven
    assert any("flex" in gap.lower() or "FLEX" in gap for gap in cert.gaps)


def test_flex_param_is_required_never_defaulted():
    """`ParamSpec.default` for the `str` kind is DEAD
    (`authoring_validation` fetches `op.get(p.name)` with no default), so
    an optional field here would give a promise in the schema and a
    `KeyError` in emission. Both fields are declared mandatory, and this
    test keeps them that way."""
    params = {p.name: p for p in spec.OPS["author_family"].params}
    assert params["flex_param"].required
    assert params["type_name"].required
    assert params["family_name"].required
    for name in ("flex_param", "type_name", "family_name"):
        assert params[name].default is None, (
            f"{name}: у рода str умолчание не применяется — оно было бы "
            "обещанием, которого валидатор не выполняет")

    prog = _program()
    prog["ops"][0].pop("flex_param")
    out = compile_program(prog, "2026", snapshot={})
    assert not out.ok
    assert any(d.field_name == "flex_param" for d in out.diagnostics)


# ── template: dependency on the environment ─────────────────────────────

def test_template_path_is_asked_of_revit_never_written_as_a_literal():
    cs = _cs()
    assert "doc.Application.FamilyTemplatePath" in cs
    # Not a single absolute path: the directory is supplied by the user's
    # machine.
    assert "ProgramData" not in cs
    assert "C:\\" not in cs.split("__cand_AF1")[0]
    # The check comes as the FIRST step — before the document is created.
    assert cs.index("FamilyTemplatePath") < cs.index("NewFamilyDocument")


def test_template_refusal_names_the_path_and_what_is_there():
    """«Not found» would leave the author standing exactly where he
    started."""
    cs = _cs()
    assert "искали имена: Метрическая система, типовая модель.rft" in cs
    assert 'GetFiles(' in cs and '"*.rft"' in cs
    assert ".rft в каталоге: " in cs


# ── foreign state: a claimed name, someone else's file, an unclosed
# document ───────────────────────────────────────────────────────────────

def test_existing_family_name_refuses_and_counts_the_instances():
    cs = _cs()
    assert "уже есть семейство" in cs
    assert "Экземпляров затронуло бы" in cs


def test_existing_rfa_is_never_overwritten():
    cs = _cs()
    assert "__sao_AF1.OverwriteExistingFile = false;" in cs
    assert "файл семейства уже существует" in cs


def test_family_document_is_closed_on_every_exit():
    cs = _cs()
    assert "Close(false)" in cs
    tail = cs[cs.index("catch (__KirFamilyRefusal"):]
    assert tail.index("finally") < tail.index("Close(false)")


def test_a_refused_program_leaves_no_rfa_on_disk():
    """Rolling back the transaction does not delete the file — `finally`
    does."""
    cs = _cs()
    assert "__kept_AF1 = true;" in cs
    assert "System.IO.File.Delete(__rfa_AF1)" in cs
    assert "if (!__kept_AF1)" in cs


# ── version split ───────────────────────────────────────────────────────

@pytest.mark.parametrize("ver,expect,forbid", [
    ("2021", "BuiltInParameterGroup.PG_GEOMETRY, ParameterType.Length",
     "GroupTypeId.Geometry"),
    ("2022", "GroupTypeId.Geometry, SpecTypeId.Length",
     "BuiltInParameterGroup"),
    ("2026", "GroupTypeId.Geometry, SpecTypeId.Length",
     "BuiltInParameterGroup"),
])
def test_add_parameter_overload_follows_the_version(ver, expect, forbid):
    """Two overloads with DIFFERENT argument types; the windows overlap
    only on 2022. Measured with the chat door against real builds and
    re-verified by mutation on 21.08: the modern spelling on 2021 gives
    CS0103 `GroupTypeId`, the old spelling on 2026 gives CS0103
    `BuiltInParameterGroup` and CS0122 `ParameterType`."""
    cs = _cs(ver)
    assert expect in cs
    assert forbid not in cs


# ── receipt: the opposite of DirectShape, but without overpromising ─────

def test_receipt_claims_real_bim_semantics():
    cs = _cs(place_at=[1000, 2000, 0])
    assert '__rb["bim_semantics"] = "generic_model_family";' in cs
    assert '__rb["has_type"] = true;' in cs
    assert '__rb["human_editable"] = true;' in cs
    assert '__rb["schedulable_as_building_element"] = true;' in cs


def test_receipt_refuses_to_promise_a_schedule_without_an_instance():
    """Without an instance the field must be `null` with a reason, not
    `true`.

    A zero (or `true`) in place of the unverified is a form of defect
    already recorded here: for the twisted shape on 20.08, the receipt
    held `volume_mm3_expected: 0` against a measured 1.03e11.
    """
    cs = _cs()
    assert '__rb["schedulable_as_building_element"] = null;' in cs
    assert "schedulable_unverified_ru" in cs
    assert '__rb["bim_semantics"] = "generic_model_family_type";' in cs


def test_receipt_names_what_it_did_not_verify():
    cs = _cs(place_at=[0, 0, 0])
    assert "unverified_ru" in cs
    for fragment in ("план профиля ЖЁСТКИЙ", "категория семейства пришла ИЗ ШАБЛОНА",
                     "привязки к уровню"):
        assert fragment in cs


def test_receipt_carries_the_flex_numbers_not_a_flag():
    cs = _cs(place_at=[0, 0, 0])
    for field in ("volume_mm3_at_h", "volume_mm3_at_2h", "volume_ratio",
                  "volume_mm3_restored", "volume_tolerance_mm3"):
        assert f'__rb["{field}"]' in cs


# ── witness in the project: conditional, and its absence is checked too ─

def test_instance_witness_exists_only_when_an_instance_was_asked_for():
    placed = _cs(place_at=[1000, 2000, 0])
    bare = _cs()
    # THE PARENTHESIS IN THE MARKER IS NOT PEDANTRY: the name
    # `NewFamilyInstance` also appears in the guard's comment «active
    # document is a family», and without the parenthesis the marker would
    # catch prose instead of a call — exactly what the certificate's
    # `_code()` strips comments and strings to prevent.
    assert "NewFamilyInstance(" in placed and "NewFamilyInstance(" not in bare
    assert "__KirVol(__inst_AF1)" in placed
    assert "__KirVol(__inst_AF1)" not in bare
    for ver in ("2021", "2026"):
        assert tc.certify_op(_grounded(), ver).proven
        assert tc.certify_op(_grounded(place_at=[1, 2, 0]), ver).proven


# ── the reverse move ────────────────────────────────────────────────────

def test_reverse_contract_names_the_LIFTER_gap_now_that_capture_reads_params():
    """🔴 THIS GUARD WAS FLIPPED ON 21.08.2026, AND THE FLIP IS ITS JOB.

    The earlier version pinned the marker to `CAPTURE_GAP` with the
    argument: «the shape is captured (83.0% of 283 shapes, 21.08), but the
    PARAMETER and its binding are not read at all — the gap is in
    CAPTURE.» That argument was accurate for exactly one day.

    On 21.08, capture learned to read `FamilyManager.Parameters` and
    `GetAssociatedFamilyParameter` for every shape, and a live measurement
    («Проект1», 36 families) returned the reference set from the day
    before: `Высота_KIR` -> `EXTRUSION_END_PARAM` for bound families and a
    NAMED absence of binding for the rigid one. Leaving `capture_gap` in
    place would have sent the next person to fix a read that was already
    fixed.

    The guard turned red on the marker's change and demanded this be
    written here — exactly what it exists for. The `due` deadline is
    removed deliberately: it belongs ONLY to the capture gap, and the
    registry rejected the entry's first draft precisely over that
    deadline.
    """
    contract = REVERSE_CONTRACTS["author_family"]
    assert contract.mode is ReverseMode.LIFTER_GAP
    assert not contract.decided_on and not contract.due
    assert "GetAssociatedFamilyParameter" in contract.reason
    # There is no elevator operator, so there is no guarantee — and the
    # limit is named by the KINDS of shapes, not by the phrase «we can't
    # do it yet».
    assert contract.guarantee is ReverseGuarantee.NONE
    for kind in ("Sweep", "Blend", "Revolution"):
        assert kind in contract.limitation, (
            "предел обязан называть РОДА форм, которых оп не покрывает: "
            "лифтер, встреченный со Sweep, обязан отказать, а не поднять "
            "похожее")


def test_refuses_when_the_active_document_is_itself_a_family():
    """`doc` can be an OPEN FAMILY EDITOR. In that case the same program
    would build a NESTED family and «work» while giving something other
    than what was asked for. The check comes as step zero — before the
    template and before the document."""
    cs = _cs()
    assert "if (doc.IsFamilyDocument)" in cs
    assert cs.index("doc.IsFamilyDocument") < cs.index("FamilyTemplatePath")


# ── A5 GUARDS FOR SOLO TEMPLATES: ONE NAME — ONE DECLARATION ────────────────
#
# 🔴 FOUND BY MEASUREMENT ON 21.08.2026, NOT BY READING.
# `_element_identity_guard` declares local `<prefix>_0/Uid_0/Version_0`
# variables. The solo template emits it TWICE — before the transaction and
# inside it — and with a single prefix C# responds with CS0136 ("A local
# named '__kirBinding_0' cannot be declared in this scope") ON ALL SIX
# VERSIONS. So an A5 run with identity proofs would have failed on the
# user's machine BEFORE Revit.
#
# The gate never saw this and never will: `model_binding_guard_inputs`
# does not build solo ops. The staircase's companions (landing, flight)
# had been passing a prefix from the very start; `create_stairs` — the
# oldest of the three — remained unfixed, meaning the copies got fixed and
# the original was left alone.
#
# The ratchet is DELIBERATELY OFFLINE: it does not call the compile
# service, it counts declarations in the text. An instrument requiring
# :52412 would stay silent wherever the service is absent.

_A5_IDS = None


def _a5_ids():
    global _A5_IDS
    if _A5_IDS is None:
        from kir.contracts import ElementIdentityProof
        _A5_IDS = (ElementIdentityProof(
            element_id=42,
            unique_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee-00001092",
            version_guid="0" * 32),)
    return _A5_IDS


_SOLO_CASES = {
    "author_family": ({
        "op": "author_family", "id": "AF1", "family_name": "F",
        "type_name": "T", "flex_param": "H", "height_mm": 800,
        "profile": {"outer": {"shape": "rect", "origin": [0, 0],
                              "size_mm": [600, 400]}},
        "place_at": [0, 0, 0]}, {}),
    "create_stairs": ({
        "op": "create_stairs", "id": "S1", "p0_mm": [0, 0], "p1_mm": [5000, 0],
        "base_level": {"by": "element_id", "value": 42},
        "top_level": {"by": "element_id", "value": 43}, "width_mm": 1200},
        {"levels": [{"id": 42, "name": "L1", "elevation_mm": 0},
                    {"id": 43, "name": "L2", "elevation_mm": 3000}]}),
}


@pytest.mark.parametrize("name", sorted(_SOLO_CASES))
def test_solo_templates_declare_each_a5_guard_symbol_once(name):
    import re
    from kir import authoring
    op, snapshot = _SOLO_CASES[name]
    ops = ground_mod.ground_program(
        plan_program({"ir_version": "1.0", "ops": [op]}), snapshot).to_ops()
    cs = authoring.emit_program(
        ops, "2026", "тест",
        expected_document={"title": "Проект1",
                           "path_name": "C:\\p\\Проект1.rvt",
                           "project_uid": "abc-123"},
        expected_identities=_a5_ids())
    decls = re.findall(r"^\s*Element (__kir\w*Binding\w*_\d+) = null;",
                       cs, re.MULTILINE)
    assert decls, f"{name}: сторож тождества вообще не эмитирован"
    dupes = {d for d in decls if decls.count(d) > 1}
    assert not dupes, (
        f"{name}: имя объявлено дважды {sorted(dupes)} — это CS0136 на всех "
        "шести версиях; второму сторожу нужен свой symbol_prefix")
