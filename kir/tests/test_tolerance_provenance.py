"""TOLERANCE PROVENANCE — a promised number must have an address in the registry.

``translation_cert`` proves that a witness EXISTS for every promised clause;
about WHERE the number that this witness compares against came from, it
says nothing at all.  Before 03.08 all 35 write ops were `PROVEN`, while
eleven of them promised millimeters in `post` that the registry could not name.

Sample defect (`create_type`, 27.07): the check declared
``tol_key="param_mm"``, while the C# compared against a hardcoded ``0.5``.  A reference into
the void that no test saw: the key was just a string, and nobody
ever asked whether it resolves.

THREE LAWS (the formulation is in ``emit_model.py``, where the first two also hold BY
CONSTRUCTION; here they are checked, and the third lives only here):

  1. MINTING — a tolerance enters the emission only as a :class:`Tolerance` object,
     minted from ``spec.OPS[op].tolerances[key]``;
  2. READ, NOT DECLARED — a witness that declares a tolerance must contain in
     its C# the exact string that this object itself rendered;
  3. PROMISE ↔ REGISTRY ↔ EMISSION — every ``±<число>`` from ``OpSpec.post``
     is addressable in the registry, and every registry entry reaches the emitted C#.

The classes below are one per law/side:

  * L0 — constructor: the three forms of the defect are not constructible;
  * L1 — registry: the promised number is addressable;
  * L2 — emission: the declared key resolves;
  * L3 — emission: the declared provenance is REAL (a perturbing oracle);
  * L4 — registry: there are no dead numbers;
  * L5 — corpus: the certifying corpus builds EVERY branch of the tolerance;
  * L6 — certificate: every emitted witness is checked by someone.

L3 and L4 are not decoration: they make a HALFWAY fix impossible.  Adding the
missing numbers to the registry without teaching the emitters to read them paints L1/L2
green and L3/L4 red (measured by simulation on 03.08).  It is only green
with the registry and the emitter together.

Run selectively (the full suite is 5 GB RSS):

    venv/bin/python3.12 -m pytest kir/tests/test_tolerance_provenance.py -q
"""
from __future__ import annotations

import os
import re
import tempfile
import unittest

os.environ.setdefault(
    "KIR_REJECTIONS_PATH",
    os.path.join(tempfile.gettempdir(), "kir_tolprov_queue.jsonl"))

from kir import ground as ground_mod                      # noqa: E402
from kir import spec                                      # noqa: E402
from kir import contour as contour_mod  # noqa: E402
from kir.authoring import _EMITTERS, _SOLO_PROGRAMS  # noqa: E402
from kir.compiler import _parse_and_check                 # noqa: E402
from kir.emit_model import (                              # noqa: E402
    BarePost,
    EmitModelError,
    WitnessCheck,
    render_staged_post,
    tolerance,
)
from kir.tests.fixtures import GROUND_SNAPSHOT            # noqa: E402
from kir.tests.test_emitter_scope_contract import (       # noqa: E402
    PROGRAMS,
    VERSIONS,
)

WRITE_OPS = sorted(
    name for name, op_spec in spec.OPS.items()
    if op_spec.family in spec.WRITE_FAMILIES)

# ---------------------------------------------------------------------------
# Corpus
# ---------------------------------------------------------------------------

# Ops that own THEIR OWN program template are not listed in `_EMITTERS`, so the
# corpus feeds them separately.  As of 10.08.2026 there are TWO of them, and both are fed: an instrument
# that sees only half the class is more dangerous than a missing one — the test bed would slip
# past both the vacuum bypass and the tolerance provenance, silently.
_STAIRS_OP = {
    "op": "create_stairs", "id": "ST1", "p0_mm": [0, 0], "p1_mm": [3000, 0],
    "base_level": {"__grounded__": {"via": "id", "id": 42}},
    "top_level": {"__grounded__": {"via": "id", "id": 43}},
    "width_mm": 1200,
}

_LANDING_OP = {
    "op": "create_stairs_landing", "id": "LG1",
    "stairs": {"by": "element_id", "value": 4242},
    "elevation_mm": 1500.0,
    "contour": {"outer": {"shape": "rect", "origin": [5000.0, 0.0],
                          "size_mm": [2400.0, 1200.0]}},
    "__region__": contour_mod.validate_region(
        {"outer": {"shape": "rect", "origin": [5000.0, 0.0],
                   "size_mm": [2400.0, 1200.0]}}, [], "LG1", "contour", []),
}

_RUN_OP = {
    "op": "create_stairs_run", "id": "RN1",
    "stairs": {"by": "element_id", "value": 4242},
    "p0_mm": [0.0, 0.0], "p1_mm": [3000.0, 0.0],
    "base_elevation_mm": 1800.0, "justification": "center",
}

# 🔴 THE FOURTH TENANT (21.08.2026), AND ALSO THE FIRST TIME THE GUARD BELOW
# FIRED FOR ITS INTENDED PURPOSE. `author_family` entered `SOLO_OPS` on 21.08 and got no
# sample: the corpus crashed on import and THREE test files stopped
# collecting AT ALL — `test_tolerance_provenance`, `test_witness_vacuity`, and
# `test_sector_bbox_tessellation`. Exactly what the check against the registry was
# set up for: the solo op did not silently vanish from the traversal, it brought the corpus down.
#
# The sample is given GROUNDED (`__region__` computed by the same
# `contour.validate_region` as the neighbors), otherwise the tolerance provenance would be judging
# a profile that does not exist.
_FAMILY_OP = {
    "op": "author_family", "id": "AF1",
    "family_name": "KIR_Провенанс", "type_name": "Тип 600x400",
    "template": "generic_model", "height_mm": 800.0,
    "flex_param": "Высота_KIR",
    "profile": {"outer": {"shape": "rect", "origin": [0.0, 0.0],
                          "size_mm": [600.0, 400.0]}},
    "__region__": contour_mod.validate_region(
        {"outer": {"shape": "rect", "origin": [0.0, 0.0],
                   "size_mm": [600.0, 400.0]}}, [], "AF1", "contour", []),
}

# 🔴 THE FIFTH TENANT (23.08.2026) — AND THE GUARD FIRED A SECOND TIME, IN EXACTLY THE SAME WAY.
# `transfer_family` entered `SOLO_OPS` together with the wave of the directory move and
# got no sample; the corpus crashed on import, and the same three files stopped
# COLLECTING. The cost is named by a measurement from a neighboring session, not by reasoning: pytest
# does not drop just three files but the ENTIRE part — «Interrupted: 3 errors during
# collection», 144 files did not run at all. That is, the guard is honest, but it takes
# hostages, and the price for it must be paid in the same commit that introduces the solo op.
#
# The sample is not grounded (`grounded=()` for this op — there is nothing to ground) and carries
# no numeric fields AT ALL: `transfer_family` has three parameters, all strings.
# That is precisely its contribution to tolerance provenance — zero tolerances with a non-empty
# program, that is, exactly the branch on which law L5 must stay silent rather than be
# absent.
_TRANSFER_OP = {
    "op": "transfer_family", "id": "TF1",
    "source_document": "MNVNK_ATR_PD_B14_K3_AR_R2022",
    "family_name": "ATR_Окно_ГОСТ 30674",
    "type_name": "1480x1400",
}

_SOLO_INSTANCES = {"create_stairs": _STAIRS_OP,
                   "create_stairs_landing": _LANDING_OP,
                   "create_stairs_run": _RUN_OP,
                   "author_family": _FAMILY_OP,
                   "transfer_family": _TRANSFER_OP}

# 15.08.2026 — the THIRD tenant, and it is this one on which the way of losing them silently was closed.
# Before, the table was kept by hand: a solo op forgotten here would drop OUT
# of both the vacuum traversal and the tolerance provenance immediately, and both would report "clean".
# Now the roster is checked against the REGISTRY on import: the fourth solo op will either
# get a sample, or bring down the corpus — but it will not silently vanish from it.
if set(_SOLO_INSTANCES) != set(spec.SOLO_OPS):
    raise AssertionError(
        "корпус соло-опов разошёлся с реестром: нет образца у "
        + ", ".join(sorted(set(spec.SOLO_OPS) - set(_SOLO_INSTANCES)))
        + "; лишние: "
        + ", ".join(sorted(set(_SOLO_INSTANCES) - set(spec.SOLO_OPS))))

# Conditional fields that open a branch with a tolerance.
_FORCE = {"base_offset_mm": 150, "top_offset_mm": -250,
          "diameter_mm": 200, "height_offset_mm": 2700}


def _shipped_instances():
    """(op_name, grounded_op, version) for the corpus carried by the repository."""

    out = []
    for _pname, prog in PROGRAMS.items():
        min_ver = prog.get("__min_ver__", "2021")
        # The upper bound on the version is the same symmetry as in the corpus
        # itself (see its header): the load wave refuses in a TYPED way on
        # 2024-2026, and requiring emission from it there would mean requiring it to
        # silently build something else instead.
        max_ver = prog.get("__max_ver__", VERSIONS[-1])
        prog = {k: v for k, v in prog.items()
                if k not in ("__min_ver__", "__max_ver__")}
        grounded = ground_mod.ground(_parse_and_check(prog), GROUND_SNAPSHOT)
        for ver in [v for v in VERSIONS if min_ver <= v <= max_ver]:
            for op in grounded:
                out.append((op["op"], op, ver))
    for ver in VERSIONS:
        for name, solo_op in _SOLO_INSTANCES.items():
            out.append((name, solo_op, ver))
    return out


def _full_instances():
    """The corpus plus the branches it might fail to reach."""

    out = list(_shipped_instances())
    for name, op, ver in list(out):
        if name in spec.SOLO_OPS:
            continue
        forced = dict(op)
        for field, value in _FORCE.items():
            forced.setdefault(field, value)
        # The WorkPlaneBased place_family overload deliberately refuses the
        # TwoLevelsBased offsets.  The generic branch-forcing corpus must not
        # manufacture a combination the public planner cannot express.
        if name == "place_family" and "ref_dir" in forced:
            forced.pop("base_offset_mm", None)
            forced.pop("top_offset_mm", None)
        out.append((name, forced, ver))
    return out


SHIPPED = _shipped_instances()
FULL = _full_instances()


def _checks(name, op, ver):
    """The WitnessCheck objects that the op emits ([] for the string genre)."""

    if name in spec.SOLO_OPS:
        return []
    _decl, _create, post, _rb = _EMITTERS[name](op, ver, "kir:tolprov")
    if isinstance(post, BarePost):
        post = list(post.checks)
    return list(post) if isinstance(post, (list, tuple)) else []


def _rendered(name, op, ver):
    """Everything the op emits, as one string (for the perturbation diff)."""

    if name in spec.SOLO_OPS:
        return _SOLO_PROGRAMS[name](op, ver)
    decl, create, post, rb = _EMITTERS[name](op, ver, "kir:tolprov")
    if isinstance(post, BarePost):
        post = list(post.checks)
    return "".join(render_staged_post(op["id"], post)) + (decl or "") + (create or "") + (rb or "")


# ---------------------------------------------------------------------------
# L0 — CONSTRUCTOR: the three forms of the defect are not constructible
# ---------------------------------------------------------------------------

class L0_TheDefectIsUnconstructible(unittest.TestCase):
    """A technique of this house: ``WitnessCheck`` cannot be constructed without ``__post.Add``,
    and the F3 class of defects died BY CONSTRUCTION.  The same has been done with the tolerance —
    below are three forms, each of which used to live silently."""

    def test_a_key_the_registry_cannot_answer_refuses_at_minting(self) -> None:
        """A key into the void (the create_type defect) — refused at minting."""

        with self.assertRaises(EmitModelError):
            tolerance("create_wall", "нет_такого_ключа_mm")
        with self.assertRaises(EmitModelError):
            tolerance("нет_такого_опа", "endpoint_mm")

    def test_a_bare_key_string_is_not_a_provenance(self) -> None:
        """Provenance can no longer be declared as a bare string: there is no field, and a
        substituted string/number is a typed refusal."""

        with self.assertRaises(TypeError):
            WitnessCheck(
                obligation_key="k", reader_cs="",
                verdict_cs='    if (x > 5.0) __post.Add("m");\n',
                message="m", tol_key="endpoint_mm")      # type: ignore[call-arg]
        with self.assertRaises(EmitModelError):
            WitnessCheck(
                obligation_key="k", reader_cs="",
                verdict_cs='    if (x > 5.0) __post.Add("m");\n',
                message="m", tol="endpoint_mm")          # type: ignore[arg-type]

    def test_a_declared_but_unread_tolerance_is_unconstructible(self) -> None:
        """A declared tolerance next to a number typed in by hand — exactly the
        create_type defect; now such a check cannot be CONSTRUCTED."""

        tol = tolerance("create_wall", "endpoint_mm")
        with self.assertRaises(EmitModelError):
            WitnessCheck(
                obligation_key="endpoints", reader_cs="",
                # the number is the same, but it did not come from the object
                verdict_cs='    if (d > 5.0) __post.Add("m");\n',
                message="m", tol=tol)
        # but through the object — it builds
        ok = WitnessCheck(
            obligation_key="endpoints", reader_cs="",
            verdict_cs=f'    if (d > {tol}) __post.Add("m");\n',
            message="m", tol=tol)
        self.assertEqual(ok.tol_key, "endpoint_mm")

    def test_the_registry_number_is_the_one_emitted(self) -> None:
        """Minting returns the REGISTRY value, not its own."""

        self.assertEqual(
            tolerance("create_wall", "endpoint_mm").value,
            float(spec.OPS["create_wall"].tolerances["endpoint_mm"]))


# ---------------------------------------------------------------------------
# L1 — REGISTRY: the promised number is addressable
# ---------------------------------------------------------------------------

# `±5mm`, `±0.1deg`, `±50` ... and the non-quantitative `±tol`.
_PROMISED = re.compile(r"±\s*(?:(\d+(?:\.\d+)?)|(tol)\b)")


class L1_PromisedNumberIsAddressable(unittest.TestCase):
    """If ``OpSpec.post`` promises ``±<n>`` (or ``±tol``), this number must
    reside in ``OpSpec.tolerances``.  A promise that the registry cannot name
    will be checked by neither the reviewer, nor acceptance, nor the decompiler."""

    def test_every_prose_tolerance_has_a_registry_home(self) -> None:
        offenders = []
        for name in WRITE_OPS:
            op_spec = spec.OPS[name]
            promises = _PROMISED.findall(op_spec.post)
            if not promises:
                continue
            values = {float(v) for v in op_spec.tolerances.values()}
            if not op_spec.tolerances:
                offenders.append(
                    f"{name}: post promises "
                    f"{[a or b for a, b in promises]} but tolerances == {{}}")
                continue
            for number, _unquantified in promises:
                if number and float(number) not in values:
                    offenders.append(
                        f"{name}: post promises ±{number} but the registry "
                        f"holds {sorted(values)}")
        self.assertEqual(
            [], offenders,
            "\nопы, обещающие допуск, которого реестр назвать не может:\n  "
            + "\n  ".join(offenders))

    def test_tolerances_are_positive_finite_numbers(self) -> None:
        """A zero/negative tolerance makes the check either infeasible,
        or meaningless (carried over from the previous edition of the module)."""

        for op_name, op_spec in sorted(spec.OPS.items()):
            for key, value in (getattr(op_spec, "tolerances", None)
                               or {}).items():
                with self.subTest(op=op_name, key=key):
                    self.assertIsInstance(value, (int, float))
                    self.assertNotIsInstance(value, bool)
                    self.assertGreater(float(value), 0.0)


# ---------------------------------------------------------------------------
# L2 — EMISSION: the declared key resolves
# ---------------------------------------------------------------------------

class L2_TolKeyResolves(unittest.TestCase):
    """``WitnessCheck.tol_key`` is a declaration of the number's origin.  A key
    that is not in ``tolerances`` of ITS OWN op is the create_type defect."""

    def test_no_tol_key_points_into_the_void(self) -> None:
        offenders = set()
        for name, op, ver in FULL:
            for chk in _checks(name, op, ver):
                if chk.tol_key is None:
                    continue
                if chk.tol_key not in spec.OPS[name].tolerances:
                    offenders.add(
                        f"{name}.{chk.obligation_key}: tol_key="
                        f"{chk.tol_key!r} not in tolerances="
                        f"{spec.OPS[name].tolerances}")
        self.assertEqual(
            set(), offenders,
            "\nсвидетели, чей заявленный провенанс не разрешается:\n  "
            + "\n  ".join(sorted(offenders)))


# ---------------------------------------------------------------------------
# L3 — EMISSION: the declared provenance is REAL (a perturbing oracle)
# ---------------------------------------------------------------------------

class L3_DeclaredProvenanceIsReal(unittest.TestCase):
    """Touch the number in the registry — the C# of every witness that declared it
    reads it MUST move.  A witness with a resolvable key that does not
    read it is the same lie, only with a valid key."""

    def test_poking_the_registry_moves_the_witness(self) -> None:
        offenders = []
        for name in WRITE_OPS:
            tolerances = spec.OPS[name].tolerances
            instances = [(n, o, v) for n, o, v in FULL if n == name]
            for key, value in list(tolerances.items()):
                claimants = [
                    (n, o, v, c) for n, o, v in instances
                    for c in _checks(n, o, v) if c.tol_key == key]
                if not claimants:
                    continue
                tolerances[key] = float(value) * 1000.0 + 7.77
                try:
                    moved = any(
                        next((x for x in _checks(n, o, v)
                              if x.obligation_key == c.obligation_key),
                             None) != c
                        for n, o, v, c in claimants)
                finally:
                    tolerances[key] = value
                if not moved:
                    offenders.append(
                        f"{name}.{key}: witnesses declare tol_key={key!r} but "
                        "their C# does not change when the registry does")
        self.assertEqual(
            [], offenders,
            "\nдекоративный tol_key (объявлен, но не прочитан):\n  "
            + "\n  ".join(offenders))


# ---------------------------------------------------------------------------
# L4 — REGISTRY: there are no dead numbers
# ---------------------------------------------------------------------------

class L4_NoDeadRegistryNumber(unittest.TestCase):
    """Every ``tolerances`` entry must reach the emitted C#.
    A number in the registry that nobody reads is the mirror defect: it looks
    like a centralized tolerance, while the real gate stands somewhere else."""

    def test_every_tolerance_key_reaches_the_emission(self) -> None:
        baseline = {i: _rendered(*inst) for i, inst in enumerate(FULL)}
        offenders = []
        for name in WRITE_OPS:
            tolerances = spec.OPS[name].tolerances
            for key, value in list(tolerances.items()):
                tolerances[key] = float(value) * 1000.0 + 7.77
                try:
                    moved = any(
                        _rendered(*FULL[i]) != baseline[i]
                        for i in range(len(FULL)) if FULL[i][0] == name)
                finally:
                    tolerances[key] = value
                if not moved:
                    offenders.append(
                        f"{name}.tolerances[{key!r}] = {value} — ничего из "
                        f"того, что эмитирует {name}, его не читает")
        self.assertEqual(
            [], offenders,
            "\nмёртвые числа реестра:\n  " + "\n  ".join(offenders))


# ---------------------------------------------------------------------------
# L5 — CORPUS: the certifying corpus builds EVERY branch of the tolerance
# ---------------------------------------------------------------------------

class L5_CorpusReachesEveryTolerance(unittest.TestCase):
    """The certificate proves exactly what the corpus assembles: a tolerance branch that
    the corpus does not reach is certified only in the NEGATIVE ("the witness is
    correctly absent"), and a hardcoded number inside it is invisible.
    The corpus is part of the proof, so it must be complete."""

    def test_shipped_corpus_exercises_every_tolerance_key(self) -> None:
        baseline = {i: _rendered(*inst) for i, inst in enumerate(SHIPPED)}
        unreached = []
        for name in WRITE_OPS:
            tolerances = spec.OPS[name].tolerances
            for key, value in list(tolerances.items()):
                tolerances[key] = float(value) * 1000.0 + 7.77
                try:
                    moved = any(
                        _rendered(*SHIPPED[i]) != baseline[i]
                        for i in range(len(SHIPPED)) if SHIPPED[i][0] == name)
                finally:
                    tolerances[key] = value
                if not moved:
                    unreached.append(f"{name}.{key}")
        self.assertEqual(
            [], unreached,
            "\nветки допусков, которых сертифицирующий корпус не строит "
            "(сертификат не увидит в них хардкода):\n  "
            + "\n  ".join(unreached))


# ---------------------------------------------------------------------------
# L6 — CERTIFICATE: every emitted witness is checked by someone
# ---------------------------------------------------------------------------

# Witnesses that are defense in depth, rather than an `OpSpec.post` clause.
# Format: (op, key) -> why it is legitimately outside the REFINEMENT bijection.
_UNPROMISED_WITNESSES = {
    ("create_group", "placed"):
        "extra: post обещает экземпляры, а не отдельную пробу размещения",
    ("create_group", "member_0"):
        "перепроверка участника; его собственный post это уже обещает",
    ("create_group", "member_1"):
        "перепроверка участника; его собственный post это уже обещает",
    # 🔴 FOUND ON 21.08.2026 AND STOOD INVISIBLE FOR A DAY. This file did not
    # collect at all — the solo op `author_family` entered the registry without a sample
    # and brought the corpus down on import — and law L6 stayed silent right along with it.
    # A red for a known reason was hiding the next one, a form named after this very house.
    #
    # WHY UNPROMISED, RATHER THAN CERTIFIED. For the solid's neighbors
    # (`create_solid_extrusion`, `create_solid_revolve`), `cap_area` is a
    # full-fledged obligation. For the sweep, the witness is CONDITIONAL: it
    # is emitted only `if caps_clean`, and "clean end faces" are computed
    # INSIDE the emitter from the path's geometry, and this is not visible from the op itself.
    # An obligation without a gate would demand a witness from a sweep
    # with miters, where there is none — that is, it would paint correct emission red.
    #
    # TO PROMISE IT, TWO MOVES ARE NEEDED: a clause in the sweep's `OpSpec.post` (it is
    # not there — unlike extrusion) and a gate that reads end-face cleanliness from the
    # GROUNDED op, rather than from the emitter. The second is real work: right now
    # this knowledge lives in only one place, and it is correct there.
    ("create_solid_sweep", "cap_area"):
        "extra: свидетель условный (`if caps_clean`), условие вычисляется в "
        "эмиттере и по опу не видно; `OpSpec.post` протяжки площадь торца не "
        "обещает вовсе",
    # 🔴 HERE STOOD TWO `move_elements` ENTRIES (hosted_inserts,
    # locked_dimensions), AND THEY WERE REMOVED ON THE SAME DAY, 22.08.2026. They had been added
    # honestly — the ripple-of-consequences guards were being emitted, and there was no
    # obligation behind them yet, because `translation_cert` belonged to a different fork on that
    # wave. The obligations were added; the entries left TOGETHER with them.
    #
    # They must not drift apart: an entry that outlives its own truth silences law L6 for
    # its key SILENTLY — the guard stops being required, and nobody will
    # notice it being removed. It is exactly this form that the test below holds in place.
}


def _stale_unpromised() -> list[str]:
    """Entries that are NO LONGER needed: an obligation has appeared under the key.

    🔴 THE SAME RULE AS FOR THE REGISTRY OF BARE READERS: an entry that has started
    PASSING fails the test no less than a new breakage would. Without this, the exemption
    lives forever and quietly disables the law — and law L6 consists precisely in
    EVERY emitted witness being either certified or named.
    """
    from kir import translation_cert as _tc

    stale: list[str] = []
    for op_name, key in sorted(_UNPROMISED_WITNESSES):
        ref = _tc._ensure_table().get(op_name)
        if ref is None:
            continue
        if any(o.key == key for o in ref.obligations):
            stale.append(f"{op_name}/{key}")
    return stale

#: A stub in place of the single excised witness. LIVE on purpose:
#: see the long comment where it is substituted.
_LIVE_STUB = WitnessCheck(
    obligation_key="__excised__", reader_cs="",
    verdict_cs='    if (__post == null) __post.Add("");\n',
    message="excised", style="guard")


class L6_EveryWitnessIsCertified(unittest.TestCase):
    """``audit_registry_coverage()`` matches a prose clause against an
    obligation by a SHARED WORD — that is, by a substring in different clothing.
    Measured 03.08: the route_* slope clause (KIR-X004) had no obligation of its
    own and passed the audit, because the word "segment" occurs both in
    the diameter one and the connectivity one; the witness WAS being emitted at the same time, and removing it
    left the certificate PROVEN.

    The form is mutation, exactly as discipline C5 of this repository requires: excising
    the real witness MUST bring down `proven`."""

    _SLOPED = [
        {"op": "route_pipe_system", "id": "RS1",
         "level": {"by": "element_id", "value": 42},
         "nodes": [{"id": "N1", "xyz_mm": [0, 0, 3000]},
                   {"id": "N2", "xyz_mm": [6000, 0, 2900]}],
         "segments": [{"from": "N1", "to": "N2",
                       "diameter_mm": 100, "slope_min_pct": 1.0}]},
        {"op": "route_duct_system", "id": "DS1",
         "level": {"by": "element_id", "value": 42},
         "nodes": [{"id": "N1", "xyz_mm": [0, 0, 3000]},
                   {"id": "N2", "xyz_mm": [6000, 0, 2900]}],
         "segments": [{"from": "N1", "to": "N2",
                       "diameter_mm": 200, "slope_min_pct": 1.0}]},
    ]

    def _corpus(self):
        for name, op, ver in FULL:
            if name not in spec.SOLO_OPS:
                yield name, op, ver
        for raw in self._SLOPED:
            grounded = ground_mod.ground(
                _parse_and_check({"ir_version": "1.0", "intent": "x",
                                  "ops": [raw]}), GROUND_SNAPSHOT)[0]
            for ver in VERSIONS:
                yield raw["op"], grounded, ver

    def test_the_stub_itself_is_not_vacuous(self) -> None:
        # Otherwise the oracle below would pass for the WRONG reason on the six ops with
        # a single witness: what would fail would not be the excised key, but the
        # stub itself. Guard the guard.
        from kir import translation_cert as cert_mod

        findings, partial = cert_mod.analyze_witness_cs(
            cert_mod._code(_LIVE_STUB.render()))
        self.assertEqual(findings, ())
        self.assertFalse(partial)

    def test_excising_a_witness_flips_the_certificate(self) -> None:
        from kir import translation_cert as cert_mod

        uncertified = set()
        seen = set()
        for name, op, ver in self._corpus():
            for chk in _checks(name, op, ver):
                key = chk.obligation_key
                if (name, key) in _UNPROMISED_WITNESSES or (name, key) in seen:
                    continue
                seen.add((name, key))
                real = _EMITTERS[name]

                def excised(o, v, stamp, isolation="atomic", _r=real, _k=key):
                    d, c, post, rb = _r(o, v, stamp, isolation)
                    bare = isinstance(post, BarePost)
                    checks = list(post.checks) if bare else list(post)
                    kept = [x for x in checks if x.obligation_key != _k]
                    if not kept:
                        # An empty post is not constructible (render_post refuses),
                        # so a stub is substituted: the block remains
                        # the correct shape, while the KEY under test has vanished.
                        #
                        # THE STUB MUST BE LIVE (09.08). It used to be
                        # `if (false) __post.Add("")` here. Ever since the
                        # certificate started catching a VACUOUS witness (a check whose
                        # __post.Add is unreachable), such a stub was ITSELF bringing down
                        # `proven` — and this oracle would pass even if the
                        # certificate were not looking at the excised KEY at all. Six
                        # ops carry exactly one witness (change_type,
                        # create_railing, create_type, delete, load_family,
                        # set_param), so the branch is live and the substitution would not be
                        # theoretical. `__post == null` is statically
                        # undecidable -> no finding -> the oracle again depends
                        # ONLY on the absence of the key.
                        kept = [_LIVE_STUB]
                    return d, c, (BarePost(tuple(kept)) if bare else kept), rb

                _EMITTERS[name] = excised
                try:
                    still = cert_mod.certify_op(op, ver).proven
                finally:
                    _EMITTERS[name] = real
                if still:
                    uncertified.add(f"{name}.{key}")
        self.assertEqual(
            set(), uncertified,
            "\nсвидетели, которых сертификат не проверяет (их удаление "
            "оставляет PROVEN) и которые не объявлены необещанными:\n  "
            + "\n  ".join(sorted(uncertified)))


if __name__ == "__main__":
    unittest.main(verbosity=2)


class ОсвобождениеНеПереживаетСвоюПравду(unittest.TestCase):
    """🔴 AN ENTRY UNDER WHICH AN OBLIGATION HAS APPEARED SILENCES THE LAW.

    Measured on 22.08.2026, on itself. Two `move_elements` entries were added at
    midday (the ripple-of-consequences guards were being emitted, there was no obligation yet —
    `translation_cert` belonged to a different fork) and became redundant by evening,
    when the obligations were added. While they stand, L6 is NOT
    ASKED for these keys, and removing the guard would go unnoticed.

    The same law already stands at the registry of bare readers of the snapshot, and it
    fired there today: two entries were red starting from the commit that fixed them.
    """

    def test_no_exemption_outlives_its_obligation(self):
        stale = _stale_unpromised()
        self.assertEqual(
            stale, [],
            "у этих ключей ОБЯЗАТЕЛЬСТВО ЕСТЬ — вычеркни их из "
            f"_UNPROMISED_WITNESSES: {stale}")

    def test_the_guard_can_go_red(self):
        """FAIL CONTROL: the guard must catch it, otherwise it is decoration."""
        from kir import translation_cert as _tc

        ref = _tc._ensure_table().get("move_elements")
        self.assertIsNotNone(ref)
        live = {o.key for o in ref.obligations}
        self.assertIn("hosted_inserts", live,
                      "обязательство круга последствий обязано быть заведено")
        _UNPROMISED_WITNESSES[("move_elements", "hosted_inserts")] = "подделка"
        try:
            self.assertIn("move_elements/hosted_inserts", _stale_unpromised())
        finally:
            _UNPROMISED_WITNESSES.pop(("move_elements", "hosted_inserts"))
