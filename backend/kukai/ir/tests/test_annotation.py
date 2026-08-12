"""ops_annotation gates (a)(b)(d)(e)(f): create_dimension/create_tag/create_text
— VIEW-SPACE type law (docspace.py, REUSED not reinvented), version-drift on
IndependentTag.Create (the family's real drift, per KIR_DOC_SPEC.md warning
and confirmed against the live compile-gate), size-from-intent via runtime
View.Scale (create_text.width_mm), commit-gate invariants, and the
VIEW-BINDING LAW witness shape. See KIR_DOC_SPEC.md for the design.

FLAGGED GAPS this test file documents (not invented around — see
ops_annotation.py module docstring and each emitter's docstring):
  - dim_type/tag_type/text_type resolve as element_id-pinned target_w, NOT
    sole-entry/candidates-from-catalog (no views/sheets/*_types snapshot pool
    exists yet — a Fable-level registry_base.py change).
  - create_dimension's line direction (28.07, live E5 measurement — see
    DimensionLineOrientation): RUNTIME-derived from the FIRST resolved
    reference's plane normal, projected into the view plane — the line runs
    ACROSS the measured faces, not along a fixed view axis, so it generalizes
    to walls running either way in plan. CLOSED 09.08: the old
    View.RightDirection fallback is gone, because a candidate whose normal
    cannot project into the view plane is no longer a usable candidate at all
    — the gap it described cannot be reached.
  - create_dimension is offline-proven only (compiles 6/6, both isolations).
    A LIVE Revit run is still required for the 09.08 reference classes:
    family instances (GetSymbolGeometry + instance transform) and datums
    (Curve references under IncludeNonVisibleObjects) have never been placed
    by a real Revit — only the straight-wall recipe has (28.07, 3000.0 mm).
  - create_text's font HEIGHT is NOT a param (TextNoteType-owned, shared by
    every instance of that type — there is no per-instance height API);
    width_mm (TextNote.Width, the one per-instance sheet-space size Revit
    DOES expose) is modeled instead, size-from-intent via view_scale read at
    RUNTIME from the resolved view (never a python-side guess).
  - create_text's leader_to is best-effort (leader End moved to the target's
    view-projected bbox midpoint) — there is no Revit API that snaps a
    leader onto an arbitrary element.
  - VIEW-BINDING LAW (target/refs visible in in_view) is witness-only in v1
    (no ground-time visibility pool exists yet) — this is exactly what the
    spec itself says GROUND cannot yet prove; ViewBindingWitness below proves
    the witness CODE checks it, not that a live model satisfies it (that
    needs a live Revit round-trip, out of this test's reach)."""
import os
import random
import tempfile
import unittest

os.environ.setdefault("KIR_REJECTIONS_PATH",
                      os.path.join(tempfile.gettempdir(), "kir_test_queue.jsonl"))

from kukai.ir.authoring_validation import (  # noqa: E402
    _TEXT_CONTENT_MAX_CHARS,
)
from kukai.ir import spec  # noqa: E402
from kukai.ir.compiler import compile_program  # noqa: E402
from kukai.ir.tests.fixtures import GROUND_SNAPSHOT as SNAPSHOT  # noqa: E402

IN_VIEW = {"by": "element_id", "value": 900}     # id-pinned (no views pool yet)


def _prog(ops, intent="annotation-test", **env):
    p = {"ir_version": "1.0", "intent": intent, "ops": ops}
    p.update(env)
    return p


def _wall(oid="W1", **kw):
    op = {"op": "create_wall", "id": oid, "p0_mm": [0, 0], "p1_mm": [6000, 0],
          "level": {"by": "name", "value": "Этаж 1"}}
    op.update(kw)
    return op


def _dim(oid="D1", **kw):
    op = {"op": "create_dimension", "id": oid, "in_view": IN_VIEW,
          "refs": [{"by": "ref", "value": "W1"},
                   {"by": "element_id", "value": 12345}],
          "line_at": [3000, 500]}
    op.update(kw)
    return op


def _tag(oid="T1", **kw):
    op = {"op": "create_tag", "id": oid, "in_view": IN_VIEW,
          "target": {"by": "ref", "value": "W1"}, "at": [3000, 800]}
    op.update(kw)
    return op


def _text(oid="X1", **kw):
    op = {"op": "create_text", "id": oid, "in_view": IN_VIEW,
          "at": [1000, 1000], "content": "Проверка текста"}
    op.update(kw)
    return op


class ViewSpaceTypeLaw(unittest.TestCase):
    """(a)+(d): the invention's core law reused verbatim from docspace.py —
    proved here at the FULL compile_program level (not just the docspace
    unit, which test_docspace.py already covers), across all three ops."""

    def test_3d_point_in_dimension_line_at_refused(self):
        out = compile_program(_prog([_wall(), _dim(line_at=[100, 200, 300])]),
                              snapshot=SNAPSHOT)
        self.assertFalse(out.ok)
        d = [x for x in out.diagnostics if x.code == "KIR-T001"][0]
        self.assertIn("3D-точка", d.message_ru)
        self.assertIn("вида", d.message_ru)

    def test_3d_point_in_tag_at_refused(self):
        out = compile_program(_prog([_wall(), _tag(at=[100, 200, 300])]),
                              snapshot=SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertIn("KIR-T001", [d.code for d in out.diagnostics])

    def test_3d_point_in_text_at_refused(self):
        out = compile_program(_prog([_text(at=[100, 200, 300])]), snapshot=SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertIn("KIR-T001", [d.code for d in out.diagnostics])

    def test_annotation_far_from_the_view_origin_is_accepted(self):
        """Аннотация в 50 м от начала вида законна. Замерено 27.07: у плана
        `View.Origin` = (0,0,0) с мировыми осями, а стены настоящего здания
        лежат по Y в 82 693 … 110 160 мм — прежняя граница ±10 м не давала
        разметить в нём ничего. Отличить утёкшую модельную координату от
        далёкой законной аннотации по величине нельзя; отличает арность, и она
        проверяется тестом выше (KIR-T001 на трёхкомпонентную точку)."""
        out = compile_program(_prog([_text(at=[50_000, 0])]), snapshot=SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:3])
        out = compile_program(_prog([_text(at=[200_000, 105_000])]), snapshot=SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:3])

    def test_coordinate_beyond_the_workable_extent_still_refused(self):
        """Санитарная граница остаётся — та же, что у модельных точек."""
        out = compile_program(_prog([_text(at=[99_000_000, 0])]), snapshot=SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertIn("KIR-T002", [d.code for d in out.diagnostics])

    def test_valid_view2d_point_accepted_everywhere(self):
        out = compile_program(_prog([_wall(), _dim(), _tag(), _text()]),
                              snapshot=SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:3])

    def test_model_point_dimensions_are_explicit(self):
        """Wall PtXY rejects a Z, pipe PtModel3D requires it, and the same
        3-tuple remains invalid in annotation view-space."""
        out = compile_program(_prog([_wall(p1_mm=[6000, 0, 500])]), snapshot=SNAPSHOT)
        self.assertFalse(out.ok)
        pipe = compile_program(_prog([{
            "op": "create_pipe", "id": "P1", "p0_mm": [0, 0, 500],
            "p1_mm": [6000, 0, 500],
            "level": {"by": "element_id", "value": 42},
        }]), snapshot=SNAPSHOT)
        self.assertTrue(pipe.ok, [d.as_dict() for d in pipe.diagnostics])
        out2 = compile_program(_prog([_wall(), _tag(at=[6000, 0, 500])]),
                               snapshot=SNAPSHOT)
        self.assertFalse(out2.ok)


class ViewBindingReferences(unittest.TestCase):
    """(a): in_view/target/refs/*_type resolve as target_w (element_id | ref
    to an earlier create_* op) — the id-pinned/ref-only pattern (no
    views/sheets snapshot pool exists yet, flagged gap, see module docstring).
    """

    def test_in_view_by_element_id_to_a_view(self):
        """in_view resolves an element_id-pinned view (no views pool yet, so
        this stays id-pinned, not sole-entry/candidates-from-catalog — see
        module docstring). NOTE (28.07): despite this test's PRIOR name
        (``test_in_view_by_ref_to_earlier_create``) and docstring claiming to
        document the DAG-``ref`` shape, its body always used ``element_id`` —
        the ``ref`` shape was never actually exercised anywhere in this file.
        See ``test_in_view_by_ref_is_refused_typed`` below for the real
        ``ref`` case, which turned out to be permanently uncompilable, not
        merely untested (create_view doesn't exist in v1, per spec's own
        anti-scope note — no op ever produces a View-typed local)."""
        out = compile_program(_prog([
            _wall(),
            _tag(in_view={"by": "element_id", "value": 900}),
        ]), snapshot=SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:3])

    def test_in_view_by_ref_is_refused_typed(self):
        """28.07 finding (per_op gate run): in_view: {by: ref} compiled
        (compile_program().ok is True) but the emitted cast
        ``__el_<ref> as View`` is a GUARANTEED Roslyn CS0039 — no op in the
        entire KIR surface creates a View-typed local (Wall/FamilyInstance/
        Pipe/.../ none derive from or to View), so ANY ref target is
        statically unrelated to View and `as` between unrelated
        non-polymorphic Revit API classes never compiles. This is not a
        per-model accident to catch live in the compile gate — it is refused
        HERE, at emission/plan time, typed, for every ref value."""
        out = compile_program(_prog([
            _wall(),
            _tag(in_view={"by": "ref", "value": "W1"}),
        ]), snapshot=SNAPSHOT)
        self.assertFalse(
            out.ok, "in_view ref must be a typed refusal, not compiled C#")
        # The registry now declares this directly on ParamSpec, so the
        # impossible reference dies at structural typecheck (T), before
        # ground/emission has any reason to inspect it.
        matches = [d for d in out.diagnostics if d.code == "KIR-T001"]
        self.assertTrue(matches, [d.as_dict() for d in out.diagnostics][:5])
        self.assertEqual(matches[0].field_name, "in_view")
        self.assertIn("ref", matches[0].message_ru.lower())
        # Same refusal for create_dimension/create_text — _annot_view_res is
        # the ONE shared resolver for all three annotation ops.
        for op_factory in (_dim, _text):
            out2 = compile_program(_prog([
                _wall(),
                op_factory(in_view={"by": "ref", "value": "W1"}),
            ]), snapshot=SNAPSHOT)
            self.assertFalse(out2.ok, op_factory.__name__)
            self.assertTrue(
                any(d.code == "KIR-T001" for d in out2.diagnostics),
                [d.as_dict() for d in out2.diagnostics][:5])

    def test_target_by_ref_to_earlier_wall(self):
        out = compile_program(_prog([_wall(), _tag(target={"by": "ref", "value": "W1"})]),
                              snapshot=SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:3])
        self.assertIn("(Element)__el_W1", out.csharp)

    def test_refs_needs_at_least_two(self):
        out = compile_program(_prog([_wall(), _dim(
            refs=[{"by": "element_id", "value": 111}])]), snapshot=SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertIn("KIR-T001", [d.code for d in out.diagnostics])

    def test_refs_rejects_duplicate_ref_zero_size(self):
        out = compile_program(_prog([_wall(), _dim(
            refs=[{"by": "element_id", "value": 111},
                  {"by": "element_id", "value": 111}])]), snapshot=SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertIn("KIR-T002", [d.code for d in out.diagnostics])

    def test_optional_type_selectors_omittable(self):
        """dim_type/tag_type/text_type/leader_to all optional — omitting them
        must not raise a spurious missing-selector diagnostic (the bug the
        earlier draft of target_w's validate() branch had before the
        `if sel is None and not p.required: continue` guard)."""
        out = compile_program(_prog([_wall(), _dim(), _tag(), _text()]),
                              snapshot=SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:3])
        self.assertNotIn("dim_type", out.csharp.split("create_dimension")[1].split("create_tag")[0]
                         if "create_tag" in out.csharp else out.csharp)

    def test_explicit_dim_type_used(self):
        out = compile_program(_prog([_wall(), _dim(
            dim_type={"by": "element_id", "value": 6001})]), snapshot=SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:3])
        self.assertIn("DimensionType", out.csharp)
        self.assertIn("new ElementId(6001)", out.csharp)

    def test_explicit_leader_to_adds_leader_code(self):
        out = compile_program(_prog([_wall(), _text(
            leader_to={"by": "ref", "value": "W1"})]), snapshot=SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:3])
        self.assertIn("AddLeader(TextNoteLeaderTypes.TNLT_STRAIGHT_L)", out.csharp)


class TextWidthFromViewScale(unittest.TestCase):
    """create_text.width_mm — the ONE per-instance sheet-space size Revit
    exposes (TextNote.Width; font height is TextNoteType-owned, flagged as
    NOT modeled in the emitter docstring). Compiler-owned size-from-intent:
    the model states mm-on-SHEET, the emitted C# multiplies by View.Scale
    READ AT RUNTIME from the resolved view (never a python-side guess) —
    mirrors docspace.view_scale_to_model_mm's formula without being able to
    call it directly (view_scale isn't known until in_view resolves)."""

    def test_width_mm_uses_runtime_view_scale_not_hardcoded(self):
        out = compile_program(_prog([_text(width_mm=60.0)]), snapshot=SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:3])
        cs = out.csharp
        self.assertIn("(double)__vw_X1.Scale", cs)
        self.assertIn("60.0 * (double)__vw_X1.Scale", cs)
        # the six-arg overload (with width) must be used, not the five-arg one
        self.assertIn("TextNote.Create(doc, __vw_X1.Id, (__vw_X1.Origin", cs)
        self.assertIn("U(__wmm_X1)", cs)

    def test_omitted_width_uses_five_arg_overload_unchanged(self):
        """Regression: width_mm is fully optional — the plain 5-arg
        TextNote.Create must stay byte-identical to before this feature."""
        out = compile_program(_prog([_text()]), snapshot=SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:3])
        self.assertNotIn("__vw_X1.Scale", out.csharp)
        self.assertNotIn("U(__wmm", out.csharp)

    def test_perspective_view_scale_guard_present(self):
        """View.Scale is "meaningless for perspective views" (revitapidocs) —
        <=0 is the typed runtime guard (compile-time cannot know if in_view
        resolves to a perspective 3D view; this is necessarily a runtime
        check, proven present in the emitted code, not asserted live)."""
        out = compile_program(_prog([_text(width_mm=60.0)]), snapshot=SNAPSHOT)
        self.assertTrue(out.ok)
        self.assertIn("__vw_X1.Scale <= 0", out.csharp)
        self.assertIn("масштаб вида не определён", out.csharp)

    def test_width_mm_out_of_bounds_refused(self):
        for bad in (0.0, -5.0, 10_000.0):
            with self.subTest(width_mm=bad):
                out = compile_program(_prog([_text(width_mm=bad)]), snapshot=SNAPSHOT)
                self.assertFalse(out.ok)
                self.assertIn("KIR-T002", [d.code for d in out.diagnostics])

    def test_width_witness_readback_present(self):
        out = compile_program(_prog([_text(width_mm=60.0)]), snapshot=SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:3])
        self.assertIn('__rb["width_mm"]', out.csharp)


class NegativeAnnotation(unittest.TestCase):
    CASES_NEED_WALL = [
        # 3D leaked into every view-space field
        (lambda: [_wall(), _dim(line_at=[1, 2, 3])], "KIR-T001"),
        (lambda: [_wall(), _tag(at=[1, 2, 3])], "KIR-T001"),
        # malformed points
        (lambda: [_wall(), _tag(at=[1])], "KIR-T001"),
        (lambda: [_wall(), _tag(at="not-a-point")], "KIR-T001"),
        # dimension geometry laws
        (lambda: [_wall(), _dim(refs=[])], "KIR-T001"),
        (lambda: [_wall(), _dim(refs=[{"by": "element_id", "value": 1},
                                      {"by": "element_id", "value": 1}])], "KIR-T002"),
        # required fields absent (target_w's existing TYPE_BAD_TYPE path —
        # same convention as create_window/create_door's host, KIR-T001, not
        # a dedicated missing-field code; consistent with the rest of v1)
        (lambda: [_wall(), {"op": "create_tag", "id": "T1", "at": [1, 2],
                            "target": {"by": "ref", "value": "W1"}}], "KIR-T001"),
        (lambda: [_wall(), {"op": "create_tag", "id": "T1", "in_view": IN_VIEW,
                            "at": [1, 2]}], "KIR-T001"),
        (lambda: [{"op": "create_text", "id": "X1", "in_view": IN_VIEW,
                   "at": [1, 2]}], "KIR-P005"),          # content missing -> str_long required
    ]
    CASES_NO_WALL = [
        (lambda: [_text(content="")], "KIR-T001"),        # empty content
        # Длина берётся ИЗ КОНСТАНТЫ, а не переписывается числом: прежний
        # случай зашил 2001, потолок был поднят с измеренного здания (максимум
        # 4763 символа при пределе 2000), и тест молча перестал проверять
        # границу. Отказ по длине — это KIR-T002 (границы), а не KIR-T001
        # (тип): раньше оба отказа делили одно сообщение и одно и то же
        # «непустая строка» приходило на слишком ДЛИННЫЙ текст.
        (lambda: [_text(content="x" * (_TEXT_CONTENT_MAX_CHARS + 1))],
         "KIR-T002"),
        # 50 м от начала вида — ЗАКОННО (см. test_annotation_far_from_the_
        # view_origin_is_accepted); в негативном корпусе остаётся только то,
        # что вне рабочего предела модели.
        (lambda: [_text(at=[99_000_000, 0])], "KIR-T002"),  # вне ~16 км
    ]

    def test_corpus(self):
        for maker, want in self.CASES_NEED_WALL + self.CASES_NO_WALL:
            ops = maker()
            with self.subTest(want=want, ops=str(ops)[:80]):
                out = compile_program(_prog(ops), snapshot=SNAPSHOT)
                self.assertFalse(out.ok)
                codes = [d.code for d in out.diagnostics]
                self.assertNotIn("KIR-P000", codes)
                self.assertTrue(any(c == want for c in codes),
                                f"want {want}, got {codes}")


class DimensionLineOrientation(unittest.TestCase):
    """28.07 live measurement (E5 direct-exec experiment, FAS_R23, Revit
    2023 — see wave report): П11 (create_wall×2 + create_dimension,
    refs=[WA,WB]) refused live with «NewDimension: The references are not
    geometric references. Parameter name: references» — the OLD emission
    built ``new Reference(<element>)``, a bare ELEMENT reference;
    NewDimension only accepts GEOMETRIC references (a face/edge). The gate
    never caught this — it compiles 6/6 offline, only a live Revit call
    refuses it.

    E5 also proved the RECIPE: two parallel walls (axes 3000mm apart, same
    type), ``HostObjectUtils.GetSideFaces(wall, ShellLayerType.Exterior)``
    on each (1 reference apiece), a dimension line built PERPENDICULAR to
    the walls through line_at — ``NewDimension`` succeeded, value 3000.0mm,
    References.Size=2. The perpendicular-through-line_at law generalizes
    here as: the line's DIRECTION is the first resolved reference's
    PlanarFace.FaceNormal (read back via
    ``Element.GetGeometryObjectFromReference``, confirmed identical API
    2021..2026 by reflection), projected into the view plane — i.e. the
    line runs ACROSS the measured faces, whichever way they happen to face
    in plan. The ANCHOR point (line_at, u/w) is unchanged; only the
    direction generalizes.

    09.08: the View.RightDirection fallback is GONE. The direction is the
    in-view-plane normal the resolver ALREADY proved non-degenerate for the
    first reference (a candidate whose normal cannot project into the view
    plane is not a usable candidate at all), so there is nothing left to
    fall back from — see DimensionReferenceClasses below.
    """

    def test_element_reference_construction_is_gone(self):
        """Falsifying pin: pre-fix, this assertion FAILS — the emitted C#
        contained exactly ``new Reference(__rf_D1_0)`` (captured live before
        the fix, see wave report and E5's live refusal text above)."""
        cs = compile_program(_prog([_wall(), _dim()]), snapshot=SNAPSHOT).csharp
        self.assertNotIn("new Reference(__rfEl_D1_0)", cs)
        self.assertNotIn("new Reference(__rf_D1_0)", cs)
        self.assertNotIn("new Reference(__rfEl_D1_1)", cs)
        self.assertNotIn("new Reference(__rf_D1_1)", cs)

    def test_wall_ref_uses_get_side_faces(self):
        out = compile_program(_prog([_wall(), _dim()]), snapshot=SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:3])
        cs = out.csharp
        self.assertIn("HostObjectUtils.GetSideFaces(", cs)
        self.assertIn("ShellLayerType.Exterior", cs)

    def test_non_wall_ref_uses_geometry_fallback(self):
        """_dim()'s SECOND ref (a plain element_id, 12345) is not a same-
        program create_wall — its runtime category is unknown at compile
        time, so the Wall check itself is a RUNTIME ``as Wall`` on every
        ref, not a Python-side branch; both refs get the SAME emitted
        shape, and whichever isn't a live Wall falls through to this."""
        out = compile_program(_prog([_wall(), _dim()]), snapshot=SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:3])
        cs = out.csharp
        self.assertIn("new Options()", cs)
        self.assertIn(".ComputeReferences = true", cs)
        self.assertIn(".View = __vw_D1", cs)
        self.assertIn("as PlanarFace", cs)
        self.assertIn("as Solid", cs)

    def test_no_geometric_reference_is_a_typed_refusal(self):
        out = compile_program(_prog([_wall(), _dim()]), snapshot=SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:3])
        self.assertIn(
            "у элемента нет геометрической ссылки для размера", out.csharp)

    def test_line_direction_is_the_first_reference_plane_normal(self):
        out = compile_program(_prog([_wall(), _dim(line_at=[3000, 500])]),
                              snapshot=SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:3])
        cs = out.csharp
        self.assertIn("GetGeometryObjectFromReference(", cs)
        self.assertIn(".FaceNormal", cs)
        self.assertIn(".Normalize()", cs)
        # 09.08 falsifying pin: the direction is the resolver's own normal
        # for ref 0, not a view axis. Pre-09.08 the emission opened with
        # ``XYZ __dimDir_D1 = __vw_D1.RightDirection;`` and only overwrote it
        # when a normal happened to be readable — this assertion FAILS there.
        self.assertIn("__dimDir_D1 = __gn_D1_0;", cs)
        self.assertNotIn("__dimDir_D1 = __vw_D1.RightDirection", cs)

    def test_line_anchor_still_through_line_at(self):
        """The ANCHOR point is unchanged — only the direction generalizes."""
        out = compile_program(_prog([_wall(), _dim(line_at=[3000, 500])]),
                              snapshot=SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:3])
        cs = out.csharp
        self.assertIn("RightDirection.Multiply(U(3000.0))", cs)
        self.assertIn("UpDirection.Multiply(U(500.0))", cs)

    def test_regenerate_before_reference_extraction_atomic(self):
        """28.07 live П11-repeat (post-fix): the same live typed refusal
        FIRED — «refs[0]: у элемента нет геометрической ссылки для
        размера» — but for a DIFFERENT, structural reason: a freshly
        created wall has NO faces until the document is regenerated
        (GetSideFaces empty, geometry-fallback walk ALSO empty pre-regen —
        confirmed by the coordinator's own measurement: grep Regenerate
        between the wall's Wall.Create and this op's GetSideFaces == False
        in the atomic emission). emit_program's own per-op loop only
        auto-regenerates before create_room ("v0 rule", walls_since_regen)
        — create_dimension referencing a same-program wall (or ANY
        same-program element, not just walls — the geometry-fallback path
        needs it equally) was never covered. Falsifying pin: pre-fix, no
        Regenerate() call sits between the wall's creation and this op's
        first reference extraction.

        09.08: the extraction moved from an unrolled GetSideFaces call into
        the ``__dimGeom_<s>`` resolver, so the boundary this test measures is
        the CALL SITE, not the helper's definition (which now lives in decl,
        ahead of everything by construction)."""
        out = compile_program(_prog([_wall(), _dim()]), snapshot=SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:3])
        cs = out.csharp
        i_wall_create = cs.rfind("Wall.Create", 0, cs.find("create_dimension"))
        i_resolve = cs.find("__dimGeom_D1(__rf_D1_0")
        self.assertGreater(i_wall_create, -1)
        self.assertGreater(i_resolve, -1)
        between = cs[i_wall_create:i_resolve]
        self.assertIn("doc.Regenerate();", between)

    def test_regenerate_before_reference_extraction_per_op(self):
        """Same law, per_op isolation: each op owns its own SubTransaction,
        and neither SubTransaction.Commit() nor Transaction.Commit() is
        documented to regenerate (RevitAPI.xml — regeneration is always an
        explicit, separate Document.Regenerate() call); a wall created in
        an EARLIER, already-committed SubTransaction is not guaranteed to
        have live faces when create_dimension's OWN SubTransaction starts,
        so the explicit call is required here too, not just atomic."""
        out = compile_program(_prog([_wall(), _dim()]), snapshot=SNAPSHOT,
                              isolation="per_op")
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:3])
        cs = out.csharp
        i_wall_create = cs.rfind("Wall.Create", 0, cs.find("create_dimension"))
        i_resolve = cs.find("__dimGeom_D1(__rf_D1_0")
        self.assertGreater(i_wall_create, -1)
        self.assertGreater(i_resolve, -1)
        between = cs[i_wall_create:i_resolve]
        self.assertIn("doc.Regenerate();", between)

    def test_regenerate_is_not_wrapped_in_catch(self):
        """Established design decision (curtain wave, 28.07, same rationale
        documented at set_curtain_panel): RevitAPI.xml is explicit —
        Document.Regenerate()'s RegenerationFailedException means the
        document is CORRUPTED ("even reading from it is illegal") and the
        transaction owner "must be aborted", never caught-and-ignored. The
        new call here follows the same law, not a bespoke one."""
        cs = compile_program(_prog([_wall(), _dim()]), snapshot=SNAPSHOT).csharp
        idx = cs.find("create_dimension")
        segment = cs[idx:idx + 400]
        self.assertIn("doc.Regenerate();", segment)
        self.assertNotIn("try { doc.Regenerate()", segment)


class DimensionReferenceClasses(unittest.TestCase):
    """09.08 — WHAT WAS STILL WRONG after 28.07 fixed the element reference.

    28.07 taught the emitter one recipe (a straight ``Wall`` via
    ``HostObjectUtils.GetSideFaces``) — the one shape the live E5 experiment
    measured — and left a generic walk that tested only ``go as Solid`` at the
    TOP LEVEL of the geometry. Two whole classes of element can never produce
    a Solid there, so both answered with the typed refusal «у элемента нет
    геометрической ссылки для размера» no matter what:

      * FAMILY INSTANCES (column, beam, door, window, furniture, generic
        model) — RevitAPI.xml, GeometryInstance type summary: "The most common
        situation where GeometryInstances are encountered is in Family
        instances." Revit stores ONE copy of the symbol geometry and
        transforms it per instance;
      * DATUMS (grid, level, reference plane) and model lines — a ``Curve``,
        not a Solid, and only visible at all with
        ``Options.IncludeNonVisibleObjects``. The registry entry for this op
        advertises "элементов ИЛИ ОСЕЙ" in its own comment, so a grid
        dimension was a promise the emitter could not keep.

    The trap inside the repair, and why this test names it explicitly: the
    OBVIOUS unwrap is ``GetInstanceGeometry()``, and RevitAPI.xml says of it
    (and of ``GetSymbolGeometry(Transform)``) verbatim: "because it returns a
    copy the references found in the geometry objects contained in this
    element are not suitable for creating new Revit elements referencing the
    original element (for example, dimensioning). Only the geometry returned
    by GetSymbolGeometry() with no transform can be used for that purpose."
    That is the SAME class of defect 28.07 fixed — a reference NewDimension
    throws on — and it compiles 6/6, so only a live run or this pin catches
    it. ``GetSymbolGeometry()`` returns symbol-LOCAL coordinates, so the
    reference comes from one accessor and the position from
    ``GeometryInstance.Transform``; taking both from the same call is wrong
    either way round."""

    def _cs(self):
        out = compile_program(_prog([_wall(), _dim()]), snapshot=SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:3])
        return out.csharp

    def test_reference_handed_to_newdimension_is_geometric(self):
        """The ReferenceArray is fed ONLY from the resolver's ``out``
        parameter, never from an element. Falsifying pin: any return to
        ``new Reference(<element>)`` — the pre-28.07 shape — fails here."""
        cs = self._cs()
        self.assertIn("__refs_D1.Append(__gref_D1_0);", cs)
        self.assertIn("__refs_D1.Append(__gref_D1_1);", cs)
        self.assertIn("__dimGeom_D1(__rf_D1_0, null, out __gref_D1_0,", cs)
        # the only source of __gref_* is the resolver, and the resolver only
        # ever assigns a Reference it read OFF geometry (face/curve/side face)
        self.assertNotIn("new Reference(__rf_D1_0)", cs)
        self.assertNotIn("new Reference(__rf_D1_1)", cs)
        self.assertNotIn("__gref_D1_0 = new Reference(", cs)

    def test_family_instances_use_symbol_geometry_not_instance_geometry(self):
        cs = self._cs()
        self.assertIn("as GeometryInstance", cs)
        self.assertIn("__gi.GetSymbolGeometry()", cs)
        # the documented-unsuitable accessors must never appear
        self.assertNotIn("GetInstanceGeometry(", cs)
        self.assertNotIn("GetSymbolGeometry(Transform", cs)

    def test_symbol_geometry_is_placed_back_by_the_instance_transform(self):
        """Symbol geometry is in the symbol's local space; the point and the
        normal that the VALUE witness compares against must be in MODEL space,
        so they ride through GeometryInstance.Transform (composed, so nested
        families compose too)."""
        cs = self._cs()
        self.assertIn("__tf.Multiply(__gi.Transform)", cs)
        self.assertIn("__tf.OfPoint(__pf.Origin)", cs)
        self.assertIn("__tf.OfVector(__pf.FaceNormal)", cs)

    def test_datums_and_model_lines_resolve_through_curve_references(self):
        """Grids/levels/reference planes expose a Curve, and only when
        IncludeNonVisibleObjects is set. Falsifying pin: pre-09.08 the walk
        had no Curve branch and no such option, so `create_dimension` on the
        grids its own registry entry advertises always refused."""
        cs = self._cs()
        self.assertIn(".IncludeNonVisibleObjects = true", cs)
        self.assertIn("__go as Curve", cs)
        self.assertIn("__cv.Reference", cs)
        # the datum's measured plane is the vertical plane through the line
        self.assertIn("CrossProduct(__vw_D1.ViewDirection)", cs)

    def test_face_choice_is_not_arbitrary(self):
        """Solid.Faces has no documented order, so "the first planar face of
        A against the first planar face of B" is a number with no meaning.
        Ref 0 fixes the measurement normal and later refs PREFER a candidate
        parallel to it — using Revit's own IsZeroLength, so no threshold is
        invented in this emitter."""
        cs = self._cs()
        self.assertIn("__dimGeom_D1(__rf_D1_0, null,", cs)
        self.assertIn("__dimGeom_D1(__rf_D1_1, __gn_D1_0,", cs)
        self.assertIn("__ip.CrossProduct(__want).IsZeroLength()", cs)
        self.assertIn("__ip.IsZeroLength()", cs)


class DimensionValueIsGated(unittest.TestCase):
    """09.08 — the measured value stopped being receipt-only.

    28.07's note said no expectation existed because "which faces get chosen
    changes the value". True while the face was arbitrary; false once the
    resolver knows which PLANE it handed over. The witness re-derives the
    number from those planes and compares against Revit's own report.

    What is signed is narrow ON PURPOSE: NOT "the operator's intended
    distance" (exterior vs interior face is unknowable to a compiler) but
    "the number Revit printed is the distance between the geometry this
    dimension is bound to". Failures it exists for: a family-instance
    transform composed wrongly, a reference that re-associated on
    regeneration, a segment/reference correspondence other than the
    documented one — each of which used to be a plausible number in the
    receipt under a green witness."""

    def _cs(self, refs=None):
        ops = [_wall(), _dim()] if refs is None else [
            _wall(),
            {"op": "create_dimension", "id": "D1", "in_view": IN_VIEW,
             "refs": refs, "line_at": [3000, 500]}]
        out = compile_program(_prog(ops), snapshot=SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:3])
        return out.csharp

    def test_the_witness_reads_the_result_not_the_call(self):
        cs = self._cs()
        self.assertIn("__el_D1.Value ?? double.NaN", cs)
        self.assertIn("__el_D1.NumberOfSegments > 1", cs)
        self.assertIn("__el_D1.Segments", cs)
        self.assertIn("__sg_D1.Value ?? double.NaN", cs)

    def test_the_expectation_is_derived_from_the_resolved_planes(self):
        cs = self._cs()
        self.assertIn("__proj_D1.Add(__gpt_D1_0.DotProduct(__dimDir_D1));", cs)
        self.assertIn("__proj_D1.Add(__gpt_D1_1.DotProduct(__dimDir_D1));", cs)
        self.assertIn("__proj_D1.Sort();", cs)
        self.assertIn("__expect_D1.Add(__proj_D1[__pi + 1] - __proj_D1[__pi]);",
                      cs)

    def test_multi_segment_dimension_gates_every_segment(self):
        """RevitAPI.xml: Dimension.Value "will not have a value ... for linear
        dimensions with more than one segment", and Segments map to references
        "in order" — so a 3-ref dimension needs 2 expectations, not one.
        Falsifying pin: a single-value read would leave a 3-ref dimension
        gated by a check that cannot fail."""
        cs = self._cs(refs=[{"by": "element_id", "value": 1},
                            {"by": "element_id", "value": 2},
                            {"by": "element_id", "value": 3}])
        self.assertEqual(3, cs.count("__proj_D1.Add(__gpt_D1_"))
        self.assertIn("__got_D1.Count != __expect_D1.Count", cs)

    def test_no_tolerance_number_is_invented_or_registered(self):
        """The comparison runs against Revit's own coincidence tolerance,
        read from the running application — so there is no literal in the C#
        and no entry in the registry to drift out of sync."""
        cs = self._cs()
        self.assertIn("double __vtol_D1 = doc.Application.VertexTolerance;", cs)
        self.assertIn("> __vtol_D1", cs)
        self.assertEqual({}, spec.OPS["create_dimension"].tolerances)

    def test_the_verdict_signs_the_geometry_axis(self):
        cs = self._cs()
        self.assertIn(
            "D1: measured value is not the distance between the referenced "
            "geometry (geometry)", cs)


class AngularDimensionFamily(unittest.TestCase):
    """09.08 — the dimension family the census had never examined, VERIFIED
    per version against the six reference assemblies through the live Roslyn
    service (localhost:52412), never against docs and never against
    ``backend/data/revit_api_db.json``:

      AngularDimension.Create(doc, view, Arc, IList<Reference>, DimensionType)
                                              2021 2022 2023 2024 2025 2026
      LinearDimension.Create(doc,view,Line,IList<Reference>)   —  —  —  — X X
      RadialDimension.Create(doc,view,Reference,bool)          —  —  —  — X X
      ArcLengthDimension.Create(doc,view,Arc,Reference,IList)  —  —  —  — X X
      doc.Create.NewDiameterDimension                          —  —  —  —  — —
      doc.FamilyCreate.NewDiameterDimension                    X  X  X  X  X X

    Three of those readings decided what got built, and each is a measurement,
    not a judgement:

    * AngularDimension is NOT 2025+ — it is 2017-era and compiles on all six,
      so it needs no version refusal at all and is shipped here;
    * NewDiameterDimension (and NewRadialDimension / NewAngularDimension /
      NewModelText) is CS1061 on ``doc.Create`` on every version and compiles
      only on ``doc.FamilyCreate`` — it lives on ``FamilyItemFactory``, i.e.
      the FAMILY EDITOR. KIR authors project documents, so there is no version
      on which a project-side diameter dimension exists. A typed version
      refusal would be the wrong shape of honesty here: the axis is not the
      Revit version, it is the document kind;
    * LinearDimension.Create is 2025+ and does exactly what
      ``doc.Create.NewDimension`` already does on all six — shipping it would
      add a version axis and no capability."""

    def _ang(self, oid="A1", **kw):
        op = {"op": "create_angular_dimension", "id": oid, "in_view": IN_VIEW,
              "refs": [{"by": "ref", "value": "W1"},
                       {"by": "element_id", "value": 12345}],
              "at": [1500, 1500]}
        op.update(kw)
        return op

    def _cs(self, ver="2021", **kw):
        out = compile_program(_prog([_wall(), self._ang(**kw)]),
                              revit_version=ver, snapshot=SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:3])
        return out.csharp

    def test_no_version_branch_because_the_api_has_none(self):
        """Same emission on the oldest and the newest shipped version, up to
        the ElementId literal form the whole compiler already branches on."""
        old = self._cs("2021")
        new = self._cs("2026")
        self.assertIn("AngularDimension.Create(doc, __vw_A1, __arc_A1,", old)
        self.assertIn("AngularDimension.Create(doc, __vw_A1, __arc_A1,", new)

    def test_the_arc_is_derived_from_the_two_references(self):
        """The API demands the references be "rays of the arc passed", so the
        arc cannot be an author-supplied decoration: vertex = the 2x2 solve of
        the two reference planes in the view basis, radius = distance to `at`,
        rays signed toward `at`."""
        cs = self._cs()
        self.assertIn("double __adet_A1 = __aa0_A1 * __ab1_A1 - "
                      "__aa1_A1 * __ab0_A1;", cs)
        self.assertIn("XYZ __avx_A1 = __aO_A1", cs)
        self.assertIn("if (__ad0_A1.DotProduct(__arv_A1) < 0.0) "
                      "__ad0_A1 = __ad0_A1.Negate();", cs)
        self.assertIn("Arc.Create(__avx_A1, __arv_A1.GetLength(), 0.0, "
                      "__asw_A1, __ad0_A1, __ay_A1)", cs)

    def test_parallel_references_are_a_typed_refusal_with_a_derived_bound(self):
        """Both normals are unit and lie in the view plane, so the determinant
        IS sin of the angle between them — the parallelism test is Revit's own
        AngleTolerance, not an epsilon someone picked."""
        cs = self._cs()
        self.assertIn("Math.Abs(__adet_A1) <= doc.Application.AngleTolerance",
                      cs)
        self.assertIn("refs: ссылки параллельны — у угла нет вершины", cs)

    def test_the_angle_is_gated_against_the_arc_we_built(self):
        cs = self._cs()
        self.assertIn("__agot_A1 = __el_A1.Value ?? double.NaN;", cs)
        self.assertIn("Math.Abs(__agot_A1 - __asw_A1) > "
                      "doc.Application.AngleTolerance", cs)
        self.assertIn(
            "A1: measured angle is not the sweep of the arc built from the "
            "references (geometry)", cs)
        self.assertEqual(
            {}, spec.OPS["create_angular_dimension"].tolerances)

    def test_default_dimension_type_is_asked_of_the_document(self):
        cs = self._cs()
        self.assertIn("ElementTypeGroup.AngularDimensionType", cs)
        self.assertIn("в документе нет типа углового размера по умолчанию", cs)
        explicit = self._cs(dim_type={"by": "element_id", "value": 6001})
        self.assertNotIn("ElementTypeGroup.AngularDimensionType", explicit)

    def test_exactly_two_refs(self):
        """Derived from the construction, not chosen: the vertex is the
        intersection of TWO planes."""
        three = compile_program(_prog([_wall(), self._ang(refs=[
            {"by": "element_id", "value": 1},
            {"by": "element_id", "value": 2},
            {"by": "element_id", "value": 3}])]), snapshot=SNAPSHOT)
        self.assertFalse(three.ok)
        self.assertIn("KIR-T001", [d.code for d in three.diagnostics])
        one = compile_program(_prog([_wall(), self._ang(
            refs=[{"by": "element_id", "value": 1}])]), snapshot=SNAPSHOT)
        self.assertFalse(one.ok)

    def test_the_reference_resolver_is_shared_with_create_dimension(self):
        """Not a second copy: the same helper set, so the GeometryInstance /
        datum-curve classes the linear op learned on 09.08 are available here
        by construction rather than by remembering to port them."""
        cs = self._cs()
        self.assertIn("void __dimGeom_A1(", cs)
        self.assertIn("__gi.GetSymbolGeometry()", cs)
        self.assertIn(".IncludeNonVisibleObjects = true", cs)
        # an ANGLE wants non-parallel refs, so the parallel-preference the
        # linear op passes for ref 1 must NOT be passed here
        self.assertIn("__dimGeom_A1(__rf_A1_1, null,", cs)


class CommitGateInvariants(unittest.TestCase):
    """(e): the emitted C# must structurally guarantee 12.5 for the
    annotation family too — one txn, rollback-on-catch, commit strictly
    after postcondition checks, every op stamped+witnessed."""

    def _cs(self):
        out = compile_program(_prog([_wall(), _dim(), _tag(), _text()],
                                    intent="полный набор аннотаций"),
                              snapshot=SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:3])
        return out.csharp

    def test_single_transaction(self):
        self.assertEqual(self._cs().count("new Transaction"), 1)

    def test_commit_strictly_after_regenerate_and_checks(self):
        cs = self._cs()
        i_regen = cs.index("doc.Regenerate()")
        i_check = cs.index("__post.Count > 0")
        i_commit = cs.index("__t.Commit()")
        self.assertLess(i_regen, i_check)
        self.assertLess(i_check, i_commit)
        self.assertEqual(cs.count("__t.Commit()"), 1)

    def test_rollback_on_catch_present(self):
        cs = self._cs()
        self.assertIn("if (__t.HasStarted() && !__t.HasEnded()) __t.RollBack();", cs)
        self.assertIn("throw;", cs)

    def test_every_annotation_op_stamped_and_witnessed(self):
        cs = self._cs()
        for oid in ("D1", "T1", "X1"):
            self.assertIn(f":{oid}", cs)
            self.assertIn(f'__results["{oid}"]', cs)
        self.assertIn("ALL_MODEL_INSTANCE_COMMENTS", cs)

    def test_deterministic_emit(self):
        p = _prog([_wall(), _dim(), _tag(), _text()], intent="determinism")
        a = compile_program(p, snapshot=SNAPSHOT).csharp
        b = compile_program(p, snapshot=SNAPSHOT).csharp
        self.assertEqual(a, b)

    def test_all_vars_read_in_witness_are_hoisted_to_decl(self):
        """Regression for the exact bug the live gate caught in an earlier
        draft (CS0103 __tg_T1 does not exist — a witness-read var declared
        only inside the txn body instead of in `decl`). Structural proof:
        __tg_<oid> must appear in the pre-transaction decl block."""
        cs = self._cs()
        pre_txn = cs.split("using (Transaction")[0]
        self.assertIn("Element __tg_T1 = null;", pre_txn)


class ViewBindingWitness(unittest.TestCase):
    """(f): the VIEW-BINDING LAW witness shape — proves the emitted C# CHECKS
    target-visible-in-in_view post-commit (semantic_ok), not that a live
    model satisfies it (spec's own admission: no ground-time visibility pool
    exists yet, so witness is the only layer that CAN prove it; a live Revit
    round-trip is out of this test's reach, flagged honestly, not asserted)."""

    def test_tag_checks_tagged_element_matches_target(self):
        out = compile_program(_prog([_wall(), _tag()]), snapshot=SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:3])
        cs = out.csharp
        self.assertIn("__tg_T1.Id.ToString()", cs)
        self.assertIn("VIEW-BINDING LAW", cs)
        self.assertIn("TagHeadPosition", cs)
        self.assertIn("tag belongs to wrong view (topology)", cs)
        self.assertIn("tag head differs from at (geometry)", cs)

    def test_dimension_checks_reference_count_topology(self):
        out = compile_program(_prog([_wall(), _dim()]), snapshot=SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:3])
        self.assertIn("References do not match requested refs (topology)", out.csharp)
        self.assertIn("__actual_D1.Count != __requested_D1.Count", out.csharp)
        self.assertIn(".SequenceEqual(", out.csharp)
        self.assertNotIn("HashSet<string>", out.csharp)
        self.assertIn("dimension belongs to wrong view (topology)", out.csharp)

    def test_text_checks_content_verbatim_semantic(self):
        out = compile_program(_prog([_text(content='Стена "Т-1" — 100%')]),
                              snapshot=SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:3])
        self.assertIn("content не совпадает после чтения (semantic)", out.csharp)
        self.assertIn("text belongs to wrong view (topology)", out.csharp)
        self.assertIn("text position unreadable (geometry)", out.csharp)

    def test_text_leader_request_is_verified_not_best_effort_success(self):
        out = compile_program(_prog([_wall(), _text(
            leader_to={"by": "ref", "value": "W1"})]), snapshot=SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics])
        cs = out.csharp
        self.assertIn("__leaderTargetVisible_X1", cs)
        self.assertIn("leader target not visible in view", cs)
        self.assertIn("leader endpoint does not match target", cs)

    def test_text_witness_trims_trailing_cr_both_sides(self):
        """REGRESSION (live semantic test, 2026-07-17): Revit appends a
        trailing \r to TextNote.Text on commit/regen ("KIR TEST 123" reads
        back as "KIR TEST 123\r") — the OLD raw `!=` exact-equality check
        NEVER matched, so semantic_ok was always false -> RollBack -> the
        text was NEVER actually committed, on every single create_text op.
        Fix: TrimEnd('\\r','\\n') on BOTH sides before comparing (not
        weakened to Contains — still an exact match modulo the trailing
        CR/LF Revit itself adds). This proves the fix shape structurally
        (the emitted C# calls TrimEnd on both operands); the live re-test
        confirms it actually stops rolling back on a real document."""
        out = compile_program(_prog([_text(content="KIR TEST 123")]),
                              snapshot=SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:3])
        cs = out.csharp
        self.assertIn(
            'if ((__el_X1.Text ?? "").TrimEnd(\'\\r\', \'\\n\') != '
            '"KIR TEST 123".TrimEnd(\'\\r\', \'\\n\'))',
            cs)
        # the OLD raw exact-equality shape (no TrimEnd at all) must be gone
        self.assertNotIn('if ((__el_X1.Text ?? "") != "KIR TEST 123")', cs)

    def test_dimension_has_no_gated_geometry_check(self):
        """28.07 (live E5 measurement, see DimensionLineOrientation and the
        emitter's own docstring): the PRIOR __ow-only check (2026-07-17
        fix, still gating the perpendicular offset) is gone too — once the
        line's DIRECTION itself became geometry-derived (the first
        reference's face normal, not a fixed view axis), "offset along
        UpDirection" stopped being a meaningful invariant in general (the
        axis perpendicular to a face-normal-derived line is not always
        UpDirection). Combined with the measured VALUE depending on which
        faces resolve (Exterior/Interior) and Dimension.Curve staying
        ALWAYS UNBOUND (Revit API Developer Guide, "Dimensions and
        Constraints"), the compiler has no independent "expected" geometry
        left to gate — the honest postcondition is existence + References
        topology (ViewBindingWitness above) + view binding; the numeric
        value still reaches the caller via readback, un-gated."""
        out = compile_program(_prog([_wall(), _dim(line_at=[3000, 500])]),
                              snapshot=SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:3])
        cs = out.csharp
        self.assertNotIn("line_at смещён", cs)
        self.assertNotIn("dimension position unreadable", cs)
        self.assertIn('__rb["value_mm"]', cs)
        self.assertNotIn("__ou_D1 - 3000.0", cs)
        self.assertNotIn(
            'Math.Abs(__ou_D1 - 3000.0) > 200.0 || Math.Abs(__ow_D1 - 500.0) > 200.0',
            cs)


class TagVersionAxis(unittest.TestCase):
    """create_tag is the family's real version-drift op (KIR_DOC_SPEC.md
    warning, confirmed against revitapidocs AND the live compile-gate):
    <=2021 has ONLY the TagMode overload (no symId slot at all); >=2022 adds
    the explicit-type overload used whenever tag_type is given."""

    def test_2021_uses_tagmode_overload_no_symid(self):
        out = compile_program(_prog([_wall(), _tag()]), revit_version="2021",
                              snapshot=SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:3])
        self.assertIn("TagMode.TM_ADDBY_CATEGORY", out.csharp)
        self.assertNotIn("IndependentTagType", out.csharp)

    def test_2022_omitted_type_still_uses_tagmode(self):
        """Omitted tag_type uses the SAME TagMode path on every version —
        Revit itself picks a default tag type for the omitted-type overload
        (no GetDefaultElementTypeId guess for a loadable tag family)."""
        out = compile_program(_prog([_wall(), _tag()]), revit_version="2022",
                              snapshot=SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:3])
        self.assertIn("TagMode.TM_ADDBY_CATEGORY", out.csharp)

    def test_explicit_tag_type_on_2021_is_typed_e_version_refusal(self):
        out = compile_program(_prog([_wall(), _tag(
            tag_type={"by": "element_id", "value": 5555})]),
            revit_version="2021", snapshot=SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertIn("KIR-E003", [d.code for d in out.diagnostics])

    def test_explicit_tag_type_on_2022_uses_symid_overload(self):
        out = compile_program(_prog([_wall(), _tag(
            tag_type={"by": "element_id", "value": 5555})]),
            revit_version="2022", snapshot=SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:3])
        cs = out.csharp
        self.assertNotIn("TagMode", cs)
        self.assertIn("IndependentTag.Create(doc, __ttel_T1.Id, __vw_T1.Id,", cs)

    def test_bound_witness_api_drifts_2021_vs_2023(self):
        """TaggedLocalElementId (property) exists <=2021; the multi-target
        readback exists >=2022 and TaggedLocalElementId is REMOVED (not just
        deprecated) on >=2023 — the emitter must never emit both in one body
        (a runtime try/catch of a non-existent member does not compile).

        The >=2022 member is ``GetTaggedLocalElements`` and NOT
        ``GetTaggedLocalElementIds``: the latter returns ``ISet<ElementId>``,
        and ``ISet<>`` on net48 lives in ``System.dll``, which the DEPLOYED
        plugin does not reference (CS0012, measured live 2026-08-04).
        """
        # NOTE: "TaggedLocalElementId" is a literal substring of
        # "GetTaggedLocalElements" — check the PROPERTY-access shape
        # (".TaggedLocalElementId", no parens) so the two don't false-positive
        # against each other.
        out21 = compile_program(_prog([_wall(), _tag()]), revit_version="2021",
                                snapshot=SNAPSHOT)
        self.assertIn(".TaggedLocalElementId.ToString()", out21.csharp)
        self.assertNotIn("GetTaggedLocalElements", out21.csharp)
        out23 = compile_program(_prog([_wall(), _tag()]), revit_version="2023",
                                snapshot=SNAPSHOT)
        self.assertIn("GetTaggedLocalElements()", out23.csharp)
        self.assertNotIn("GetTaggedLocalElementIds", out23.csharp)
        self.assertNotIn(".TaggedLocalElementId.ToString()", out23.csharp)


class AnnotationPBT(unittest.TestCase):
    """(a): property-based over well-typed annotation programs — every
    generated program must compile-emit cleanly (brace balance, single txn,
    no accidental doc.Delete, deterministic-shape guards) across the version
    matrix's structural invariants (this is emit-shape PBT, same level as
    test_authoring.AuthoringPBT — the live 6-version compile-gate itself is
    exercised by gate_v11-style runs, not by this in-process suite)."""
    N = 80
    SEED = 20260717
    NASTY = ["Марка \"Т-1\"", "тип\\обратный", "100%", "…", "'кавычки'", "мм", "А-1"]

    def test_properties(self):
        rng = random.Random(self.SEED)
        for case in range(self.N):
            ops = [_wall()]
            for j in range(rng.randint(1, 4)):
                kind = rng.choice(["dim", "tag", "text"])
                oid = f"a{j}"
                u, w = rng.randint(-5000, 5000), rng.randint(-5000, 5000)
                if kind == "dim":
                    n_refs = rng.randint(2, 4)
                    ops.append(_dim(oid=oid, line_at=[u, w], refs=[
                        {"by": "element_id", "value": 1000 + k} for k in range(n_refs)]))
                elif kind == "tag":
                    ops.append(_tag(oid=oid, at=[u, w],
                                    leader=rng.random() < 0.5))
                else:
                    ops.append(_text(oid=oid, at=[u, w],
                                     content=rng.choice(self.NASTY)))
            out = compile_program(_prog(ops, intent=rng.choice(self.NASTY)),
                                  snapshot=SNAPSHOT)
            with self.subTest(case=case):
                self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:3])
                cs = out.csharp
                self.assertEqual(cs.count("{"), cs.count("}"), "braces")
                self.assertEqual(cs.count("new Transaction"), 1)
                self.assertNotIn("doc.Delete", cs)
                # Success-return is the body's final action; the trailing nested
                # __KirMainFailures/__KirPad classes are wrapper-pad scaffolding.
                self.assertIn("\n__results[\"ok\"] = true;\nreturn __results;\n", cs)


# ── (b) golden corpus — own annotation_*.golden.cs files, chibicc discipline
#    (SPEC 12.6a): snapshots update ONLY via KIR_UPDATE_GOLDEN=1 + review. A
#    SEPARATE dict from test_golden.PROGRAMS (own golden/ files, own prefix)
#    so this wave's file never touches the shared PROGRAMS dict other waves
#    also read from — no merge contention on that dict.
GOLDEN_DIR = os.path.join(os.path.dirname(__file__), "golden")

ANNOTATION_PROGRAMS = {
    # Every op in the family, one program, default/omitted optional types —
    # exercises the omitted-type TagMode path + doc.Create.NewDimension +
    # TextNote.Create together (the family-complete smoke, mirrors
    # test_golden's authoring_wall_pipe_grid role for this family).
    "annotation_full_set": {
        "ir_version": "1.0", "intent": "полный набор аннотаций: размер+марка+текст",
        "ops": [
            {"op": "create_wall", "id": "W1", "p0_mm": [0, 0], "p1_mm": [6000, 0],
             "level": {"by": "name", "value": "Этаж 1"},
             "type": {"by": "name", "value": "Кирпич 250"}},
            {"op": "create_dimension", "id": "D1", "in_view": IN_VIEW,
             "refs": [{"by": "ref", "value": "W1"},
                      {"by": "element_id", "value": 12345}],
             "line_at": [3000, 500]},
            {"op": "create_angular_dimension", "id": "A1", "in_view": IN_VIEW,
             "refs": [{"by": "ref", "value": "W1"},
                      {"by": "element_id", "value": 12345}],
             "at": [1500, 1500]},
            {"op": "create_tag", "id": "T1", "in_view": IN_VIEW,
             "target": {"by": "ref", "value": "W1"}, "at": [3000, 800]},
            {"op": "create_text", "id": "X1", "in_view": IN_VIEW,
             "at": [1000, 1000], "content": "Стена наружная"},
        ],
    },
    # Explicit catalog types on every optional slot + a leader — exercises
    # the DimensionType/symId-tag/TextNoteType/AddLeader paths together.
    "annotation_explicit_types": {
        "ir_version": "1.0", "intent": "аннотации с явными типами и выноской",
        "ops": [
            {"op": "create_wall", "id": "W1", "p0_mm": [0, 0], "p1_mm": [6000, 0],
             "level": {"by": "name", "value": "Этаж 1"}},
            {"op": "create_dimension", "id": "D1", "in_view": IN_VIEW,
             "refs": [{"by": "ref", "value": "W1"},
                      {"by": "element_id", "value": 12345}],
             "line_at": [3000, 500],
             "dim_type": {"by": "element_id", "value": 6001}},
            {"op": "create_angular_dimension", "id": "A1", "in_view": IN_VIEW,
             "refs": [{"by": "ref", "value": "W1"},
                      {"by": "element_id", "value": 12345}],
             "at": [1500, 1500],
             "dim_type": {"by": "element_id", "value": 6001}},
            {"op": "create_tag", "id": "T1", "in_view": IN_VIEW,
             "target": {"by": "ref", "value": "W1"}, "at": [3000, 800],
             "leader": True, "tag_type": {"by": "element_id", "value": 5555}},
            {"op": "create_text", "id": "X1", "in_view": IN_VIEW,
             "at": [1000, 1000], "content": "См. примечание",
             "text_type": {"by": "element_id", "value": 7000},
             "leader_to": {"by": "ref", "value": "W1"}},
        ],
    },
}


class Golden(unittest.TestCase):
    """(b): byte-stable emit corpus, own annotation_*.golden.cs files.
    annotation_explicit_types.tag_type forces the >=2022 symId branch, so it
    is golden-reviewed at revit_version="2022" (2021 would be a typed
    KIR-E003 refusal for that program, proven separately in TagVersionAxis)."""

    def test_golden(self):
        update = os.environ.get("KIR_UPDATE_GOLDEN") == "1"
        versions = {"annotation_full_set": "2026",
                    "annotation_explicit_types": "2022"}
        for name, prog in ANNOTATION_PROGRAMS.items():
            with self.subTest(name=name):
                out = compile_program(prog, revit_version=versions[name],
                                      snapshot=SNAPSHOT)
                self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:3])
                path = os.path.join(GOLDEN_DIR, f"{name}.golden.cs")
                if update:
                    with open(path, "w", encoding="utf-8") as fh:
                        fh.write(out.csharp)
                    continue
                self.assertTrue(os.path.exists(path),
                                f"{path} missing — run once with KIR_UPDATE_GOLDEN=1 and review")
                with open(path, encoding="utf-8") as fh:
                    want = fh.read()
                self.assertEqual(want, out.csharp,
                                 f"{name}: emit drifted from reviewed golden "
                                 f"(intentional? update via KIR_UPDATE_GOLDEN=1 + review)")


if __name__ == "__main__":
    unittest.main()
