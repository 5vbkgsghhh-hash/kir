"""SHAPE CONSTRUCTORS ARE CHECKED THROUGH THE REAL SANDBOX, NOT AROUND IT.

The NAKAZ, §5: a lab green is not a live green, and the boundary the
tests go around is the boundary where two greens diverge. This file went
through exactly what was predicted: `extrude` worked offline and, on a
LIVE run, returned `KIR-B004: import of 'shapely.validation' is
forbidden` with `blame: author` — that is, a self-intersection message
was replaced with blaming the author for OUR OWN import. The fourth
occurrence of a defect the warm-up table documents three times over. So
here every case goes THROUGH `execute_author_script` under PROD'S POLICY.

VOLUME AS A WITNESS. The mesh is checked not by counting faces but by
VOLUME via the divergence theorem: it catches both unclosed surfaces and
a flipped normal at once. The first draft of `extrude` produced exactly
ONE THIRD of the expected volume — the top cap faced downward, because
the triangle winding was DECLARED rather than computed. And the base is
taken at TWO elevations: with `base_z=0` the bottom cap contributes zero
to the integral at ANY orientation, meaning the check at zero is
degenerate and misses half the possible error.
"""
from __future__ import annotations

import os
import unittest


#: Reachability of the geometry libraries FOR THE SANDBOX CHILD. Asked
#: ONCE per run, and BY RUNNING, not by reading the environment: `None`
#: means it was never asked, `""` means they are reachable, a non-empty
#: string is the reason in words.
_GEOMETRY_REACH: "str | None" = None


def _geometry_libs_refusal() -> str:
    """The reason the geometry libraries are unreachable, or an empty
    string.

    🔴 ASKED OF THE CHILD, NOT OF THE PARENT, AND THIS DISTINCTION CARRIES
    WEIGHT. `import shapely` succeeds for the parent and fails for the
    child, and they did not diverge by accident: the sandbox launches the
    child with `-s` and `PYTHONNOUSERSITE=1`, i.e. it DELIBERATELY
    excludes the user site directory (this is a layer of isolation, not
    an oversight), while pip installed shapely/numpy exactly there.

    Measured on 27.08.2026, a control in BOTH directions, with the same
    interpreter:

        env -i PYTHONPATH=/opt/kir PYTHONNOUSERSITE=1 python3.12 -s -B
            -c 'import shapely'   -> ModuleNotFoundError
        env -i PYTHONPATH=/opt/kir                    python3.12    -B
            -c 'import shapely'   -> PRESENT, ~/.local/lib/python3.12/site-packages

    Asking the PARENT's environment would mean asking the wrong process
    and getting a green where the child is blind. So this runs a real
    launch under the real prod policy, not a check via
    `importlib.util.find_spec`.
    """
    global _GEOMETRY_REACH
    if _GEOMETRY_REACH is not None:
        return _GEOMETRY_REACH
    from kir import sandbox, serving
    saved = os.environ.get(sandbox.AUTHOR_GEOMETRY_LIBS_FLAG)
    os.environ[sandbox.AUTHOR_GEOMETRY_LIBS_FLAG] = "1"
    try:
        # An op in the probe is MANDATORY: a script with not a single op
        # is refused by the sandbox itself, and we would read ITS refusal
        # as the libraries being absent.
        probe = sandbox.execute_author_script(
            'import shapely\nimport numpy\n'
            'create_level(elev_mm=0, name="_проба достижимости")\n',
            policy=serving._sandbox_policy())
    finally:
        if saved is None:
            os.environ.pop(sandbox.AUTHOR_GEOMETRY_LIBS_FLAG, None)
        else:
            os.environ[sandbox.AUTHOR_GEOMETRY_LIBS_FLAG] = saved
    if probe.ok:
        _GEOMETRY_REACH = ""
        return _GEOMETRY_REACH
    code = getattr(probe.refusal, "code", "?")
    text = (getattr(probe.refusal, "message_ru", "") or "")[:90]
    _GEOMETRY_REACH = (
        f"geometry-библиотеки НЕДОСТИЖИМЫ РЕБЁНКУ песочницы ({code}: {text}). "
        "Ребёнок идёт с `-s` и PYTHONNOUSERSITE=1 — пользовательский "
        "site-каталог исключён НАМЕРЕННО, это слой изоляции, а shapely/numpy "
        "стоят именно там. СЛЕДУЮЩИЙ ХОД: поставить их туда, куда ребёнок "
        "смотрит (общесистемно либо в venv службы), ЛИБО назвать каталог явно "
        "через SandboxPolicy.extra_sys_path. Снимать `-s` НЕЛЬЗЯ: он и есть "
        "изоляция — без него ребёнок увидит весь домашний каталог."
    )
    return _GEOMETRY_REACH


class _ProdPolicy(unittest.TestCase):
    """The run uses PROD'S OWN BUILT policy, not a hand-assembled one.

    🔴 SECOND DRAFT, AND THE REASON IS NAMED. The first draft set the flag
    directly in `os.environ` — caught by the environment guard. The
    second swung to the other extreme: it hand-assembled
    `SandboxPolicy(allowed_imports=ALLOWED_IMPORTS+GEOMETRY_IMPORTS)`
    without touching the environment — and thereby checked a policy THAT
    DOES NOT EXIST IN PROD. Prod builds the list live on every turn
    (`serving._sandbox_policy()` via `allowed_imports_for_env()`), and a
    hand-made copy is a second carrier of the same quantity — our own
    named defect.

    The NAKAZ, §5: every boundary the tests go around is a boundary where
    two greens diverge; the sandbox is named there as the first of four.
    So setting the flag and restoring the environment are taken from the
    READY-MADE carrier (`test_author_geometry_libs._FlagCase`), rather
    than written again here.
    """

    def setUp(self) -> None:
        from kir import sandbox
        self._saved = os.environ.get(sandbox.AUTHOR_GEOMETRY_LIBS_FLAG)
        os.environ[sandbox.AUTHOR_GEOMETRY_LIBS_FLAG] = "1"

    def tearDown(self) -> None:
        from kir import sandbox
        if self._saved is None:
            os.environ.pop(sandbox.AUTHOR_GEOMETRY_LIBS_FLAG, None)
        else:
            os.environ[sandbox.AUTHOR_GEOMETRY_LIBS_FLAG] = self._saved

    def policy(self):
        from kir import serving
        return serving._sandbox_policy()

    def run_script(self, source: str):
        from kir import sandbox
        return sandbox.execute_author_script(source, policy=self.policy())

    def require_geometry_libs(self) -> None:
        """Precondition for a test that has nothing to check without
        shapely/numpy.

        🔴 THE SKIP IS PER-CASE, NOT PER-CLASS, AND THIS IS A DECISION.
        Both classes contain tests that don't need the libraries (policy
        comparison, group handles) — they are GREEN today, and covering
        them with the skip would hide working code together with the
        untestable.

        And a skip here is MORE HONEST than a red (form 35): a red
        sitting in a suite for a week, declared «must always be green»,
        becomes BACKGROUND NOISE, and the next signal of the same kind is
        invisible against it. A skip with a named reason is visible; a
        vacuous green is not.

        The precondition is asked BY RUNNING THE CHILD (see
        `_geometry_libs_refusal`), so it cannot go stale: install the
        libraries where the child looks, and the tests will start
        running on their own, with no edit to this file.
        """
        reason = _geometry_libs_refusal()
        if reason:
            self.skipTest(reason)


def _volume(mesh: dict) -> float:
    """Volume via an INDEPENDENT instrument: a constructor agreeing with
    itself is not an argument.

    🔴 THE ORIGIN OF THE REFERENCE FRAME IS TAKEN INSIDE THE BODY, AND
    THIS IS NOT A COPY OF THE PRODUCT, BUT THE SAME CLASS OF DEFECT IN THE
    INSTRUMENT. On 02.09.2026 it was found in `mesh._mesh_volume` that
    summing tetrahedra FROM THE COORDINATE ORIGIN makes the volume verdict
    a property of where the body happens to stand: at 10 000 000 mm the
    same body gave -44466.307 mm³ instead of 200.2225. This instrument
    computed in exactly the same way and would have lied in exactly the
    same way — it's just that no case below sits farther than 10 000 mm
    from zero, so the question was never asked. An instrument that is
    correct only over part of its range is more dangerous than one that
    is absent: the next person to add a translated case here would have
    gotten a red from the INSTRUMENT and gone off to fix the mesh.

    The translation is an identity, not a tolerance: the EXACT equalities
    below (12 000 000, 7 200 000, 21 600 000 mm³, and a moment of
    ±144 000) were run under both drafts and matched TO THE BIT, so no
    obligation has been weakened.
    """
    v = mesh["vertices_mm"]
    ox = (min(p[0] for p in v) + max(p[0] for p in v)) / 2.0
    oy = (min(p[1] for p in v) + max(p[1] for p in v)) / 2.0
    oz = (min(p[2] for p in v) + max(p[2] for p in v)) / 2.0
    total = 0.0
    for i, j, k in mesh["triangles"]:
        a = [v[i][0] - ox, v[i][1] - oy, v[i][2] - oz]
        b = [v[j][0] - ox, v[j][1] - oy, v[j][2] - oz]
        c = [v[k][0] - ox, v[k][1] - oy, v[k][2] - oz]
        total += (a[0] * (b[1] * c[2] - c[1] * b[2])
                  - a[1] * (b[0] * c[2] - c[0] * b[2])
                  + a[2] * (b[0] * c[1] - c[0] * b[1]))
    return total / 6.0


class ВыдавливаниеСтроитЗамкнутоеТело(unittest.TestCase):

    def test_the_volume_instrument_itself_is_right(self):
        """The instrument is checked on a known input BEFORE the subject:
        the unit cube."""
        cube = {"vertices_mm": [[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0],
                                [0, 0, 1], [1, 0, 1], [1, 1, 1], [0, 1, 1]],
                "triangles": [[0, 2, 1], [0, 3, 2], [4, 5, 6], [4, 6, 7],
                              [0, 1, 5], [0, 5, 4], [1, 2, 6], [1, 6, 5],
                              [2, 3, 7], [2, 7, 6], [3, 0, 4], [3, 4, 7]]}
        assert abs(_volume(cube) - 1.0) < 1e-12

    def test_volume_matches_area_times_height_on_two_elevations(self):
        from kir.mesh import extrude
        from shapely.geometry import Polygon
        cases = {
            "коробка": Polygon([(0, 0), (6000, 0), (6000, 4000), (0, 4000)]),
            "L с дырой": Polygon(
                [(0, 0), (10000, 0), (10000, 4000), (4000, 4000),
                 (4000, 10000), (0, 10000)],
                [[(1000, 1000), (2500, 1000), (2500, 2500), (1000, 2500)]]),
            "вогнутая": Polygon(
                [(0, 0), (9000, 0), (9000, 3000), (6000, 3000), (6000, 1000),
                 (3000, 1000), (3000, 3000), (0, 3000)]),
        }
        for name, poly in cases.items():
            for base in (0.0, 12345.0):     # zero hides the bottom's orientation
                with self.subTest(форма=name, отметка=base):
                    mesh = extrude(poly, 3300.0, base_z_mm=base)
                    want = poly.area * 3300.0
                    assert abs(_volume(mesh) - want) <= 1e-9 * want

    def test_it_refuses_by_name_and_never_silently_repairs(self):
        from kir.mesh import extrude
        from kir.diag import KirRefusal
        square = [[0, 0], [6000, 0], [6000, 4000], [0, 4000]]
        cases = {
            "самопересечение": ([[0, 0], [6000, 4000], [6000, 0], [0, 4000]], 3000),
            "два угла": ([[0, 0], [6000, 0]], 3000),
            "нулевая высота": (square, 0),
            "высота не число": (square, "три"),
        }
        for name, (contour, height) in cases.items():
            with self.subTest(случай=name):
                with self.assertRaises(KirRefusal) as caught:
                    extrude(contour, height)
                diag = caught.exception.diagnostics[0]
                assert diag.code.startswith("KIR-"), diag.code
                assert diag.message_ru, "отказ обязан нести причину словами"


class КольцоПрофиляПЛОСКОЕ_ИЛИ_ОТКАЗ(unittest.TestCase):
    """🔴 ONE RING IN TWO SHAPES PRODUCED TWO DIFFERENT WRONG OUTCOMES.

    The extrusion contour and the sweep profile are read as FLAT: their
    third coordinate means nothing, because the height comes from
    `height_mm` and the direction from `path`. This was never said
    anywhere, and so the same ring at elevation 50 mm behaved in two
    different ways:

      * as a raw list — it was ACCEPTED, and Z silently vanished (a
        silent input rewrite, exactly the kind that has already cost this
        house 96.77% of the groups);
      * as the same ring given as a shapely Polygon with `has_z` — it
        raised `TypeError: pair() takes 2 positional arguments but 3 were
        given`, i.e. OUR OWN crash with no code, no field, and no next
        step.

    Neither of the two outcomes is a refusal. The law here is one: the
    kind is read FROM THE SHAPE OF THE VALUE, and an extra coordinate is
    NAMED.
    """

    ПЛОСКОЕ = [[0., 0.], [1000., 0.], [1000., 1000.], [0., 1000.]]
    ОБЪЁМНОЕ = [[0., 0., 50.], [1000., 0., 50.],
                [1000., 1000., 50.], [0., 1000., 50.]]

    def test_a_raw_three_dimensional_ring_is_refused_not_flattened(self):
        from kir.diag import KirRefusal
        from kir.mesh import extrude
        with self.assertRaises(KirRefusal) as поймано:
            extrude(self.ОБЪЁМНОЕ, 1000.)
        диагностика = поймано.exception.diagnostics[0]
        self.assertEqual(диагностика.field_name, "contour[0]")
        self.assertIn("50", диагностика.message_ru,
                      "отказ обязан ПЕЧАТАТЬ отброшенную координату")

    def test_a_shapely_polygon_with_z_is_refused_the_same_way(self):
        """Same input, different shape — must produce the SAME refusal
        code."""
        from shapely.geometry import Polygon
        from kir.diag import KirRefusal
        from kir.mesh import extrude
        сырое = None
        try:
            extrude(self.ОБЪЁМНОЕ, 1000.)
        except KirRefusal as e:
            сырое = e.diagnostics[0].code
        with self.assertRaises(KirRefusal) as поймано:
            extrude(Polygon([tuple(p) for p in self.ОБЪЁМНОЕ]), 1000.)
        self.assertEqual(поймано.exception.diagnostics[0].code, сырое)

    def test_a_three_dimensional_sweep_profile_is_refused_too(self):
        """The sweep profile goes through the same parsing and must
        refuse via its field."""
        from kir.diag import KirRefusal
        from kir.mesh import sweep
        with self.assertRaises(KirRefusal) as поймано:
            sweep(self.ОБЪЁМНОЕ, [[0., 0., 0.], [1000., 0., 0.]])
        self.assertEqual(поймано.exception.diagnostics[0].field_name,
                         "profile[0]")

    def test_a_flat_ring_still_builds_in_both_forms(self):
        """🔴 THE SECOND OUTCOME. Without it, a change to «reject every
        ring» would pass all three checks above."""
        from shapely.geometry import Polygon
        from kir.mesh import extrude
        списком = extrude(self.ПЛОСКОЕ, 1000.)
        полигоном = extrude(Polygon([tuple(p) for p in self.ПЛОСКОЕ]), 1000.)
        self.assertEqual(len(списком["triangles"]),
                         len(полигоном["triangles"]))
        self.assertTrue(списком["triangles"])


class ЧерезНастоящуюПесочницу(_ProdPolicy):

    def test_the_policy_is_the_one_prod_builds(self):
        """SEAM DISCRIMINATOR: the policy must be PROD'S OWN BUILD, not a
        copy.

        Without it the test would silently slide back to a hand-made
        list, and the constructors would turn green again on a policy
        that does not exist in prod. What is checked is not object
        equality but two observable properties of the prod build: the
        whitelist is read LIVE (the flag is already raised in setUp), and
        `replay_check` — a second run with a digest comparison — is
        present.
        """
        from kir import sandbox, serving
        policy = self.policy()
        assert policy is serving._sandbox_policy(), (
            "политика собрана не прод-шлюзом")
        assert set(sandbox.GEOMETRY_IMPORTS) <= set(policy.allowed_imports), (
            f"прод-сборка не подняла геометрические библиотеки при поднятом "
            f"флаге: {policy.allowed_imports}")
        assert policy.replay_check, (
            "прод гоняет скрипт ДВАЖДЫ и сверяет дайджест — тест без этого "
            "проверяет более слабый путь, чем живой")

    def test_a_computed_plan_reaches_both_a_bim_floor_and_a_body(self):
        self.require_geometry_libs()
        result = self.run_script(
            'from shapely.geometry import Polygon\n'
            'create_level(elev_mm=0, name="Этаж 1")\n'
            'plate = Polygon([(0,0),(12000,0),(12000,9000),(0,9000)]).difference(\n'
            '        Polygon([(3000,3000),(6000,3000),(6000,6000),(3000,6000)]))\n'
            'create_floor_by_contour(contour=region(plate), level="Этаж 1")\n'
            'create_directshape(mesh=extrude(plate, 200), '
            'category="generic_model", name="та же фигура телом")\n')
        assert result.ok, getattr(result.refusal, "message_ru", "")
        names = [op["op"] for op in result.ops]
        assert names == ["create_level", "create_floor_by_contour",
                         "create_directshape"], names
        contour = result.ops[1]["contour"]
        assert contour["outer"]["shape"] == "poly"
        assert len(contour["holes"]) == 1, "дыра плана обязана дожить до пола"

    def test_the_refusal_path_blames_the_contour_and_not_the_author_import(self):
        """🔴 THE LIVE DEFECT OF 19.08 THIS TEST WAS WRITTEN FOR."""
        self.require_geometry_libs()
        result = self.run_script('create_directshape(mesh=extrude('
                      '[[0,0],[6000,4000],[6000,0],[0,4000]], 3000), '
                      'category="generic_model", name="X")\n')
        assert not result.ok
        text = result.refusal.message_ru
        assert "импорт" not in text, (
            "отказ обвиняет автора за НАШ ленивый импорт вместо того, чтобы "
            f"назвать самопересечение контура: {text[:160]}")
        # 🔴 THE CODE IS ASKED FOR AS A FIELD, NOT AS A SUBSTRING IN THE
        # TEXT. Before 25.08 the script door folded a typed language
        # refusal into a generic `KIR-B006` and glued the real code into
        # the TEXT (`"DslRefusal: KIR-T004: …"`). The test read the text
        # because there was nowhere else to read it from. Now the code
        # travels as a field, and `field_name`/`got` name the slot and
        # the value — asking for them is stricter than searching for a
        # substring.
        assert result.refusal.code == "KIR-T004", (
            f"отказ пришёл кодом {result.refusal.code!r}: "
            f"по нему нельзя ветвиться на самопересечение")
        assert result.refusal.detail.get("field_name") == "contour", (
            f"отказ не называет слот: {result.refusal.detail!r}")

    def test_a_group_is_buildable_from_handles(self):
        """🔴 THE HOLE CLOSED ON 19.08: the language's main multiplier was
        unreachable."""
        result = self.run_script(
            'create_level(elev_mm=0, name="Э1")\n'
            'pts=[(0,0),(6000,0),(6000,4000),(0,4000)]\n'
            'walls=[create_wall(p0_mm=list(a), p1_mm=list(b), level="Э1", '
            'height_mm=3300) for a,b in zip(pts, pts[1:]+pts[:1])]\n'
            'create_group(members=walls, placements=[[c*7000, r*5000] '
            'for r in range(8) for c in range(5)], name="панель")\n')
        assert result.ok, getattr(result.refusal, "message_ru", "")
        assert [op["op"] for op in result.ops] == ["create_level",
                                                   "create_group"], (
            "члены обязаны быть ИЗЪЯТЫ из программы, а не стоять дважды")
        group = result.ops[1]
        assert len(group["members"]) == 4
        assert len(group["placements"]) == 40

    def test_a_handle_taken_twice_refuses_by_name(self):
        result = self.run_script(
            'create_level(elev_mm=0, name="Э1")\n'
            'w = create_wall(p0_mm=[0,0], p1_mm=[3000,0], level="Э1", '
            'height_mm=3000)\n'
            'create_group(members=[w], placements=[[0,0]], name="раз")\n'
            'create_group(members=[w], placements=[[9000,0]], name="два")\n')
        assert not result.ok, "один оп не может быть членом двух групп"
        assert "нет" in result.refusal.message_ru


class ПротяжкаВедётПрофильПоЛоманой(unittest.TestCase):
    """`sweep` is the second shape constructor to close a NAMED census
    debt.

    What is checked is not «does it work» but EQUALITY WITH A
    CLOSED-FORM VALUE: the body's volume is compared against an
    analytical one, computed without a single line of the product. A
    constructor agreeing with itself is not proof.
    """

    ПРЯМОУГОЛЬНИК = [[-30, -20], [30, -20], [30, 20], [-30, 20]]   # 60×40
    ПЛОЩАДЬ = 60.0 * 40.0

    def test_a_straight_path_gives_area_times_length_exactly(self):
        """A straight path — an EXACT equality, with no tolerance.

        A tolerance here would be a concession: the body is prismatic,
        the arithmetic is rational, and a discrepancy would mean a
        defect, not a rounding error.
        """
        from kir.mesh import sweep
        body = sweep(self.ПРЯМОУГОЛЬНИК, [[0, 0, 0], [5000, 0, 0]])
        assert _volume(body) == self.ПЛОЩАДЬ * 5000.0, (
            f"объём {_volume(body)} против {self.ПЛОЩАДЬ * 5000.0}")

    def test_a_vertical_path_does_not_lose_its_frame(self):
        """A path along Z: the default "up" axis lands ALONG the
        tangent, and the frame must fall back to a spare axis instead of
        degenerating."""
        from kir.mesh import sweep
        body = sweep(self.ПРЯМОУГОЛЬНИК, [[0, 0, 0], [0, 0, 3000]])
        assert _volume(body) == self.ПЛОЩАДЬ * 3000.0

    def test_the_miter_matches_closed_form_geometry(self):
        """🔴 A CONTROL THAT PINS THE MITER ITSELF, NOT AGREEMENT WITH
        ITSELF.

        For a profile whose center is offset by `e` to the right of the
        path, turning through an angle θ changes the volume by EXACTLY
        `2·A·e·tg(θ/2)`, and the sign flips with the direction of the
        turn. A centered profile therefore gives zero.

        This equality is EXTERNAL: it is derived from the miter's
        geometry, not from our code, so a mistake in the bisector, in
        the offset, or in the frame breaks it.

        🔴 WHAT THIS CONTROL DOES NOT PROVE, AND THIS IS A MEASUREMENT,
        NOT A DISCLAIMER. The docstring's first draft claimed that the
        check «volume equals area×length» would be GREEN under a wrong
        offset sign, and that the offset profile catches exactly that.
        Run and checked: with the sign flipped, the centered profile
        gives 12 000 000 against 21 600 000 — i.e. the naive check would
        have caught the same mutation too. The claim is withdrawn.
        What the offset case gives ON TOP of it is named honestly and
        narrowly: it pins the miter's MAGNITUDE and the sign change
        under a mirrored turn, against a closed-form value. Whether it
        catches STRICTLY MORE mutations is not measured, and so it is
        not claimed.
        """
        import math
        from kir.mesh import sweep

        путь_налево = [[0, 0, 0], [5000, 0, 0], [5000, 4000, 0]]
        путь_направо = [[0, 0, 0], [5000, 0, 0], [5000, -4000, 0]]
        длина = 9000.0
        смещение = 30.0
        сдвинутый = [[0, -20], [60, -20], [60, 20], [0, 20]]
        ожидание = 2.0 * self.ПЛОЩАДЬ * смещение * math.tan(math.pi / 4)

        центр = _volume(sweep(self.ПРЯМОУГОЛЬНИК, путь_налево))
        assert центр == self.ПЛОЩАДЬ * длина, (
            f"отцентрованный профиль на усе обязан дать площадь×путь ровно, "
            f"получено {центр}")

        налево = _volume(sweep(сдвинутый, путь_налево)) - self.ПЛОЩАДЬ * длина
        направо = _volume(sweep(сдвинутый, путь_направо)) - self.ПЛОЩАДЬ * длина
        assert abs(налево + ожидание) < 1e-6, f"поворот налево: {налево}"
        assert abs(направо - ожидание) < 1e-6, f"поворот направо: {направо}"

    def test_it_refuses_a_turn_too_sharp_for_the_profile(self):
        """A miter that eats more than half of the neighboring segment
        is a refusal WITH A NUMBER."""
        from kir.diag import KirRefusal
        from kir.mesh import sweep
        широкий = [[-900, -20], [900, -20], [900, 20], [-900, 20]]
        with self.assertRaises(KirRefusal) as поймано:
            sweep(широкий, [[0, 0, 0], [1000, 0, 0], [1000, 1000, 0]])
        сообщение = поймано.exception.diagnostics[0].message_ru
        assert "ус митры" in сообщение and "900.0" in сообщение, сообщение

    def test_the_sharp_turn_guard_is_what_refuses(self):
        """🔴 A FAIL CONTROL, TARGETED: we remove ONE quantity, we expect
        the build to still happen.

        Without it, «failed» and «failed AT THIS SPECIFIC guard» are
        indistinguishable: the body could have failed on the mesh
        validator and looked the same.

        🔴 A MEASUREMENT TRAP, PAID FOR HERE ON 19.08.2026, FOR WHOEVER
        WILL MUTATE `mesh.py` AS A FILE RATHER THAN IN MEMORY. A sign
        mutation (`-` to `+`) DOES NOT CHANGE THE FILE SIZE, and rolling
        it back within the same second does not change the mtime at
        whole-second resolution either — Python considers the mutated
        version's `.pyc` valid and uses it. Result: the source is clean,
        a `diff` against the backup is empty, grep shows the correct
        sign, and the behavior is mutated. Half an hour was spent
        hunting a defect that was not in the code.
        The rule from this: when rolling back a FILE mutation, remove
        `__pycache__`, or you are measuring bytecode, not code. A
        mutation through a module object (as here,
        `M._MITER_SPAN_FRACTION`) has none of this disease at all — and
        it is therefore the preferred method.
        """
        from kir import mesh as M
        широкий = [[-900, -20], [900, -20], [900, 20], [-900, 20]]
        путь = [[0, 0, 0], [1000, 0, 0], [1000, 1000, 0]]
        было = M._MITER_SPAN_FRACTION
        M._MITER_SPAN_FRACTION = 1e9
        try:
            построено = M.sweep(широкий, путь)
        finally:
            M._MITER_SPAN_FRACTION = было
        assert построено["triangles"], (
            "со снятым пределом уса тело обязано СТРОИТЬСЯ — иначе отказ выше "
            "приходил не от этого сторожа")

    def test_it_refuses_a_reversal_and_a_repeated_point(self):
        from kir.diag import KirRefusal
        from kir.mesh import sweep
        with self.assertRaises(KirRefusal) as разворот:
            sweep(self.ПРЯМОУГОЛЬНИК, [[0, 0, 0], [3000, 0, 0], [0, 0, 0]])
        assert "180" in разворот.exception.diagnostics[0].message_ru
        with self.assertRaises(KirRefusal) as дубль:
            sweep(self.ПРЯМОУГОЛЬНИК, [[0, 0, 0], [0, 0, 0], [3000, 0, 0]])
        assert дубль.exception.diagnostics[0].field_name == "path[1]"

    def test_the_refusal_names_the_authors_own_field(self):
        """The author wrote `profile` — the refusal must say `profile`.

        The first draft called the generic contour parser, and it named
        the field `contour`: the author was sent to fix something he
        never wrote.
        """
        from kir.diag import KirRefusal
        from kir.mesh import extrude, sweep
        with self.assertRaises(KirRefusal) as по_протяжке:
            sweep([[0, 0], [100, 0]], [[0, 0, 0], [3000, 0, 0]])
        assert по_протяжке.exception.diagnostics[0].field_name == "profile"
        with self.assertRaises(KirRefusal) as по_выдавливанию:
            extrude([[0, 0], [100, 0]], 3000)
        assert по_выдавливанию.exception.diagnostics[0].field_name == "contour"


class ОбъёмНеЗависитОтМестаСтоянкиТела(unittest.TestCase):
    """🔴 THE VOLUME VERDICT WAS A PROPERTY OF THE COORDINATES, NOT OF
    THE SHAPE.

    The volume was computed as a sum of tetrahedra FROM THE COORDINATE
    ORIGIN: each term grows as the cube of the coordinate, the answer
    stays small, and at legitimate coordinates catastrophic cancellation
    sets in. The same body therefore received different verdicts
    depending on where it stood:

        profile 1.415×1.415 along a 100 mm path, true volume 200.2225 mm³
        at the origin              200.2225      built
        moved to 10 000 000 mm     -44466.307    KIR-T004 «volume is not
                                                  positive»
        same, profile centered      7616.760      ACCEPTED, off by 38x

    The second row is worse than the first: the refusal is visible, but
    the accepted wrong number is not. The fix is to move the origin into
    the body itself: the volume of a closed surface does not depend AT
    ALL on the choice of origin, so this is not a tolerance and not an
    approximation.
    """

    СТОРОНА = 1.415
    ДЛИНА = 100.0

    def _тело(self, профиль, сдвиг):
        from kir.mesh import sweep
        x, y, z = сдвиг
        return sweep(профиль, [[x, y, z], [x + self.ДЛИНА, y, z]])

    def _объём(self, тело):
        from kir.mesh import _mesh_volume
        return _mesh_volume(тело["vertices_mm"], тело["triangles"])

    def test_the_same_body_gets_the_same_volume_wherever_it_stands(self):
        s, ждём = self.СТОРОНА, self.СТОРОНА ** 2 * self.ДЛИНА
        профили = {
            "в углу": [[0, 0], [s, 0], [s, s], [0, s]],
            "по центру": [[-s / 2, -s / 2], [s / 2, -s / 2],
                          [s / 2, s / 2], [-s / 2, s / 2]],
        }
        for имя, профиль in профили.items():
            for сдвиг in ((0., 0., 0.), (1e6, 1e6, 1e6),
                          (1e7, 1e7, 1e7), (-1e7, 1e7, -1e7)):
                with self.subTest(профиль=имя, сдвиг=сдвиг):
                    дало = self._объём(self._тело(профиль, сдвиг))
                    self.assertLessEqual(
                        abs(дало - ждём), 1e-6 * ждём,
                        f"на {сдвиг} объём {дало!r} против {ждём!r}")

    def test_the_volume_gate_still_refuses_an_inverted_body(self):
        """🔴 THE SECOND OUTCOME. Robustness must not buy itself a guard
        that cannot fail: a flipped winding must still be a refusal."""
        s = self.СТОРОНА
        тело = self._тело([[0, 0], [s, 0], [s, s], [0, s]], (1e7, 1e7, 1e7))
        вывернуто = {"vertices_mm": тело["vertices_mm"],
                     "triangles": [[t[0], t[2], t[1]]
                                   for t in тело["triangles"]]}
        self.assertLess(self._объём(вывернуто), 0.0)


class ПротяжкаЧерезНастоящуюПесочницу(_ProdPolicy):

    def test_a_rail_along_a_flight_reaches_a_directshape(self):
        """The same path the author takes: script, prod policy, program
        out."""
        self.require_geometry_libs()
        result = self.run_script(
            'rail = sweep([[-30, -20], [30, -20], [30, 20], [-30, 20]],\n'
            '             [[0, 0, 900], [4000, 0, 900], [4000, 0, 4800]])\n'
            'print("вершин", len(rail["vertices_mm"]))\n'
            'create_directshape(mesh=rail, category="generic_model", '
            'name="Поручень")\n')
        assert result.ok, getattr(result.refusal, "message_ru", result)
        assert [op["op"] for op in result.ops] == ["create_directshape"]
        assert "вершин 12" in result.stdout

    def test_the_lazy_import_of_the_refusal_path_is_warm(self):
        """The REFUSAL path pulls in `shapely.validation`, and it must
        be warmed up.

        Otherwise the author would get `KIR-B004: import forbidden` with
        `blame: author` instead of a message about his own profile — the
        fourth occurrence of this pattern was caught by a live run, not
        by reading.
        """
        # A "bowtie": self-intersection with ALL long edges. A short
        # edge here would have spoiled the experiment — the mesh would
        # have failed earlier, at the validator, and `explain_validity`
        # would never have been called at all. The first draft of this
        # test missed exactly this way: it checked a path it never
        # reached.
        self.require_geometry_libs()
        result = self.run_script(
            'sweep([[0,0],[1000,1000],[1000,0],[0,1000]], '
            '[[0,0,0],[3000,0,0]])\n')
        assert not result.ok
        assert result.refusal.code != "KIR-B004", (
            f"отказ подменён НАШИМ импортом и обвинил автора: "
            f"{result.refusal.message_ru}")
        assert "Self-intersection" in result.refusal.message_ru, (
            f"ждали сообщение `explain_validity` о самопересечении, пришло: "
            f"{result.refusal.message_ru[:160]}")



if __name__ == "__main__":
    unittest.main()
