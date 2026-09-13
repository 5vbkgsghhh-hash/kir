"""SHAPELY AND NUMPY IN THE AUTHOR'S SCRIPT — BEHIND A FLAG, OFF BY
DEFAULT.

WHY AT ALL. The sandbox whitelist is exactly `math`/`itertools`/
`functools`, so the author is forced every time to hand-write polygon
offsets, circle-to-polyline sampling, and boolean operations:
`course/recipes.py::_SILHOUETTE` contains both a homemade circle sampler
and its own deviation certificate in millimeters. Meanwhile shapely and
numpy ALREADY live in prod — `ir/design_check.py` and
`modeling/checker/*`, which `live/verdict.py` leads to; they are closed
off only for the author's sandbox.

WHAT HOLDS SAFETY WHEN THE FLAG IS ON. Not the whitelist — it was never
the boundary to begin with (see §"WHAT THIS SANDBOX DOES NOT DO" in
`sandbox.py`). The OS layers hold it: a separate process, namespaces, an
empty root, RLIMIT_FSIZE=0, RLIMIT_NPROC=0, a network namespace with no
routes. A C extension is arbitrary machine code inside the child's
address space, and ONLY the kernel can contain it. So this checks not
only "shapely worked" but also that, with the flag on, NOT A SINGLE
layer weakened: the root is empty, there is no network, writing is
forbidden.

THE ORDER IS DELIBERATE. Absence first (flag off ⇒ nothing changed and
the refusal is typed), then presence. A capability turned on before its
default absence is proven is a capability that is always on.

    venv/bin/python3.12 -m pytest kir/tests/test_author_geometry_libs.py -q
"""
from __future__ import annotations

import os
import unittest

from kir import diag, sandbox

#: The reference script proving «the flag being off shifted nothing».
#: The digests below were taken from the code BEFORE the change (`git
#: show 15d5b206`), with the same interpreter, the same language module.
#: A signature that is "probably the same" is not a signature.
_PINNED_SOURCE = (
    'lvl = create_level(elev_mm=0, name="Этаж 1")\n'
    'create_wall(p0_mm=(0, 0), p1_mm=(5000, 0), level=lvl, height_mm=3000)\n'
)
_PINNED_AUTHOR_DIGEST = (
    "49ccb2790a1b7db67862458067270a7f2566faee8254ada3f746ebd41e7ae4e5")
_PINNED_PROGRAM_DIGEST = (
    "24c19929c1b7c95a0f73189287a12e562b91079584b061a78551f696d1436a93")

#: The policy for the flag being OFF. It matches the prod gateway
#: exactly when the flag is cleared, and does NOT match when it's
#: raised: `serving._sandbox_policy()` also passes
#: `allowed_imports=allowed_imports_for_env()`, while here the
#: whitelist is frozen at the class default. The earlier version of
#: this line read as "exactly prod and nothing more" — prose wider than
#: the code (form 9): cases with the flag raised must take
#: `live_policy()`, and they do.
_PROD_POLICY = sandbox.SandboxPolicy(replay_check=True)

#: shapely computes the contour, KIR lays the slab. The sample this is
#: copied from is `tools/design/examples/contour_shapely.py`; the same
#: computation lives there WITHOUT the sandbox, and that is exactly the
#: gap this flag closes.
_CONTOUR_SCRIPT = '''
from shapely.geometry import LineString

spine = LineString([(0.0, 0.0), (30000.0, 4000.0), (60000.0, 0.0)])
ribbon = spine.buffer(7000.0, cap_style="flat", join_style="round")
simple = ribbon.simplify(250.0)
pts = [[round(float(x), 1), round(float(y), 1)]
       for x, y in simple.exterior.coords[:-1]]

# ПРИБЛИЖЕНИЕ, НАЗВАННОЕ ЧИСЛОМ. `simplify` обещает не больше допуска; сколько
# вышло на самом деле, знает только разность площадей к периметру.
drift = ribbon.symmetric_difference(simple).area / ribbon.exterior.length
print(f"контур: {len(ribbon.exterior.coords) - 1} вершин -> {len(pts)}, "
      f"отклонение {drift:.0f} мм")

lvl = create_level(elev_mm=0, name="Этаж 1")
create_floor_by_contour(contour={"outer": {"shape": "poly", "points_mm": pts}},
                        level=lvl, type="Монолит 200")
'''


class _FlagCase(unittest.TestCase):
    """The toggle is ALWAYS cleared: the suite runs in random order."""

    def setUp(self) -> None:
        self._saved = os.environ.get(sandbox.AUTHOR_GEOMETRY_LIBS_FLAG)
        os.environ.pop(sandbox.AUTHOR_GEOMETRY_LIBS_FLAG, None)

    def tearDown(self) -> None:
        if self._saved is None:
            os.environ.pop(sandbox.AUTHOR_GEOMETRY_LIBS_FLAG, None)
        else:
            os.environ[sandbox.AUTHOR_GEOMETRY_LIBS_FLAG] = self._saved

    def turn_on(self) -> None:
        os.environ[sandbox.AUTHOR_GEOMETRY_LIBS_FLAG] = "1"

    def live_policy(self) -> sandbox.SandboxPolicy:
        """The policy EXACTLY as the prod gateway builds it at this
        moment."""
        from kir import serving
        return serving._sandbox_policy()


class TheFlagIsOffAndNothingMoved(_FlagCase):
    """THE ABSENT STAYS ABSENT."""

    def test_the_default_whitelist_is_untouched(self) -> None:
        self.assertFalse(sandbox.author_geometry_libs_enabled())
        self.assertEqual(sandbox.allowed_imports_for_env(),
                         sandbox.ALLOWED_IMPORTS)
        # 🔴 THE LITERAL HERE IS DELIBERATE, AND IT IS NOT A DUPLICATE
        # AUTHORITY. It holds a THIRD claim absent from its two
        # neighbors: the base list does not grow SILENTLY. Asking
        # `sandbox.ALLOWED_IMPORTS` here would mean writing `x == x` — a
        # green with no act of distinction (form 18). Updating it is
        # work, and it must remain work: on 20.08 the list grew from
        # three names to seven, and every new name is named at the
        # constant itself, together with the reason.
        self.assertEqual(sandbox.ALLOWED_IMPORTS,
                         ("math", "itertools", "functools",
                          "collections", "dataclasses", "typing", "__future__"))
        self.assertEqual(self.live_policy().allowed_imports,
                         sandbox.ALLOWED_IMPORTS)

    def test_the_flag_name_is_the_one_the_gate_reads(self) -> None:
        """The constant and the literal inside the gate cannot drift
        apart.

        The literal sits there not by oversight: `tools/capability_map.py`
        searches for flags with a REGEX over the text, and a call
        through the constant would be invisible to the inventory — the
        flag would become invisible, i.e. sitting in storage by
        construction. This test, not an agreement, holds the names from
        drifting apart.
        """
        self.assertEqual(sandbox.AUTHOR_GEOMETRY_LIBS_FLAG,
                         "KUKAI_IR_AUTHOR_GEOMETRY_LIBS")
        os.environ[sandbox.AUTHOR_GEOMETRY_LIBS_FLAG] = "1"
        self.assertTrue(sandbox.author_geometry_libs_enabled())
        os.environ[sandbox.AUTHOR_GEOMETRY_LIBS_FLAG] = "0"
        self.assertFalse(sandbox.author_geometry_libs_enabled())

    def test_the_digests_of_an_untouched_script_did_not_move(self) -> None:
        """Signatures taken from the code BEFORE the change must match
        down to the character."""
        result = sandbox.execute_author_script(_PINNED_SOURCE,
                                               policy=_PROD_POLICY)
        self.assertTrue(result.ok, result.refusal and result.refusal.render())
        self.assertEqual(result.author_digest, _PINNED_AUTHOR_DIGEST)
        self.assertEqual(result.program_digest, _PINNED_PROGRAM_DIGEST)

    def test_importing_shapely_is_a_typed_refusal_naming_the_line(self) -> None:
        """THE REFUSAL PATH. A raw traceback never makes it out."""
        source = ("lvl = create_level(elev_mm=0, name=\"Этаж 1\")\n"
                  "from shapely.geometry import Polygon\n")
        result = sandbox.execute_author_script(source, policy=_PROD_POLICY)
        self.assertFalse(result.ok)
        refusal = result.refusal
        self.assertEqual(refusal.code, diag.SANDBOX_FORBIDDEN_IMPORT)
        self.assertEqual(refusal.blame, "author")
        self.assertEqual(refusal.line, 2)
        self.assertEqual(refusal.line_text,
                         "from shapely.geometry import Polygon")
        self.assertIn("shapely.geometry", refusal.render())
        self.assertEqual(refusal.detail["allowed"],
                         list(sandbox.ALLOWED_IMPORTS))
        self.assertNotIn("Traceback", refusal.render())
        # On refusal, the program does not go out at all — half a
        # program is worse than a refusal: it looks built.
        self.assertEqual(result.ops, [])

    def test_numpy_is_refused_the_same_way(self) -> None:
        result = sandbox.execute_author_script("import numpy\n",
                                               policy=_PROD_POLICY)
        self.assertFalse(result.ok)
        self.assertEqual(result.refusal.code, diag.SANDBOX_FORBIDDEN_IMPORT)
        self.assertEqual(result.refusal.line, 1)

    def test_a_submodule_of_a_non_package_is_still_refused(self) -> None:
        """The rule «a submodule travels with its PACKAGE» opened
        nothing in stdlib: `math` is not a package, and `math.foo`
        refuses exactly as it always did."""
        result = sandbox.execute_author_script("import math.foo\n",
                                               policy=_PROD_POLICY)
        self.assertFalse(result.ok)
        self.assertEqual(result.refusal.code, diag.SANDBOX_FORBIDDEN_IMPORT)


class TheFlagIsOnAndTheContourIsComputed(_FlagCase):
    """PRESENCE: the library computes the contour, KIR lays the slab."""

    def test_the_live_policy_widens_within_one_turn(self) -> None:
        """The toggle is read LIVE. A cached policy would mean that
        "turning the flag on" equals "restart four workers"."""
        self.assertEqual(self.live_policy().allowed_imports,
                         sandbox.ALLOWED_IMPORTS)
        self.turn_on()
        widened = self.live_policy()
        self.assertEqual(widened.allowed_imports,
                         sandbox.ALLOWED_IMPORTS + sandbox.GEOMETRY_IMPORTS)
        # EXACTLY one line of policy changed. Not a single isolation
        # layer moved — this is exactly «the kernel holds the C
        # extension, not the whitelist».
        default = sandbox.SandboxPolicy(replay_check=True)
        for name in ("network", "filesystem_isolation", "probe_network",
                     "replay_check", "memory_mb", "cpu_seconds",
                     "wall_seconds", "nofile", "max_ops"):
            self.assertEqual(getattr(widened, name), getattr(default, name),
                             f"флаг сдвинул слой изоляции: {name}")

    def test_shapely_computes_a_contour_and_kir_places_the_floor(self) -> None:
        """THE FILE'S MAIN TEST: buffer -> simplification ->
        create_floor_by_contour."""
        self.turn_on()
        result = sandbox.execute_author_script(_CONTOUR_SCRIPT,
                                               policy=self.live_policy())
        self.assertTrue(result.ok, result.refusal and result.refusal.render())
        ops = [op["op"] for op in result.ops]
        self.assertEqual(ops, ["create_level", "create_floor_by_contour"])

        floor = result.ops[1]
        points = floor["contour"]["outer"]["points_mm"]
        self.assertEqual(floor["contour"]["outer"]["shape"], "poly")
        self.assertGreaterEqual(len(points), 4)
        # Numbers, not objects: the IR program must be JSON-representable.
        for point in points:
            self.assertEqual(len(point), 2)
            for value in point:
                self.assertIsInstance(value, float)
        # The deviation is NAMED as a number and made it into this same
        # turn's receipt.
        self.assertIn("отклонение", result.stdout)
        self.assertIn("мм", result.stdout)

    def test_the_price_is_paid_only_by_the_script_that_names_it(self) -> None:
        """The SOURCE decides the warm-up. A script that never names
        shapely does not have to pay: +536 ms and +43 MB per launch, and
        the script executes TWICE."""
        self.turn_on()
        policy = self.live_policy()

        silent = sandbox.execute_author_script(_PINNED_SOURCE, policy=policy)
        self.assertTrue(silent.ok, silent.refusal and silent.refusal.render())
        self.assertEqual(silent.isolation["warmed_libs"], [])

        loud = sandbox.execute_author_script(_CONTOUR_SCRIPT, policy=policy)
        self.assertTrue(loud.ok, loud.refusal and loud.refusal.render())
        # The submodule is warmed up because the SOURCE NAMED it: `import
        # shapely` pulls in `shapely.geometry` but not `shapely.ops`, and
        # after the chroot there is no disk left — an unfound submodule
        # would become a refusal aimed at the wrong address.
        self.assertIn("shapely", loud.isolation["warmed_libs"])
        self.assertIn("shapely.geometry", loud.isolation["warmed_libs"])
        self.assertGreater(loud.peak_rss_kb, silent.peak_rss_kb)

    def test_the_program_is_signed_together_with_the_library_it_used(self) -> None:
        """The library that computed the contour is NAMED BY VERSION in
        that same receipt.

        This is the second half of the answer to «one building, two
        signatures»: extending the whitelist without signing the
        environment would mean building that very hole at full scale.
        """
        self.turn_on()
        result = sandbox.execute_author_script(_CONTOUR_SCRIPT,
                                               policy=self.live_policy())
        self.assertTrue(result.ok, result.refusal and result.refusal.render())
        rows = {m["name"]: m for m in result.environment["modules"]}
        self.assertEqual(sorted(rows),
                         sorted(sandbox.ALLOWED_IMPORTS
                                + sandbox.GEOMETRY_IMPORTS))
        self.assertEqual(rows["shapely"]["via"], "importlib.metadata")
        self.assertRegex(rows["shapely"]["version"], r"^\d+\.\d+")
        self.assertTrue(rows["shapely"]["loaded"])
        # GEOS drifts SEPARATELY from shapely and is signed separately.
        self.assertIn("geos_version", rows["shapely"]["native"])

        from kir import serving
        receipt = serving._authorship_receipt(
            result, source_bytes=len(_CONTOUR_SCRIPT.encode("utf-8")))
        self.assertEqual(receipt["environment"]["digest"], result.env_digest)

    def test_no_isolation_layer_was_relaxed(self) -> None:
        """A MEASUREMENT, NOT A PROMISE: with the flag on and shapely
        loaded, the root is still empty, there is no network, writing is
        forbidden, forking is forbidden."""
        self.turn_on()
        policy = self.live_policy()

        # The layers are measured on a SUCCESSFUL run that actually
        # loaded shapely: measuring isolation on a turn where the
        # library is absent would mean measuring the wrong thing.
        built = sandbox.execute_author_script(_CONTOUR_SCRIPT, policy=policy)
        self.assertTrue(built.ok, built.refusal and built.refusal.render())
        self.assertIn("shapely", built.isolation["warmed_libs"])
        isolation = built.isolation
        self.assertEqual(isolation["namespaces"], "user+mount+net")
        self.assertEqual(isolation["filesystem"], "chroot")
        self.assertTrue(isolation["network_probe"].startswith("unreachable"))
        self.assertEqual(isolation["limits"]["RLIMIT_FSIZE"], 0)
        self.assertEqual(isolation["limits"]["RLIMIT_NPROC"], 0)
        self.assertEqual(isolation["limits"]["RLIMIT_CORE"], 0)

        # And the restricted builtins are also in place: `open` remains
        # a stub explaining WHY it is absent. It deliberately derives
        # from BaseException — `except Exception` in the script must not
        # swallow it.
        probe = _CONTOUR_SCRIPT + 'open("/etc/passwd")\n'
        blocked = sandbox.execute_author_script(probe, policy=policy)
        self.assertFalse(blocked.ok)
        self.assertEqual(blocked.refusal.code, diag.SANDBOX_FORBIDDEN_BUILTIN)
        self.assertEqual(blocked.refusal.detail["name"], "open")
        self.assertEqual(blocked.isolation["filesystem"], "chroot")

    def test_a_module_outside_the_widened_list_is_still_refused(self) -> None:
        """The list is extended by exactly two libraries, not by
        «external modules» in general."""
        self.turn_on()
        result = sandbox.execute_author_script("import networkx\n",
                                               policy=self.live_policy())
        self.assertFalse(result.ok)
        self.assertEqual(result.refusal.code, diag.SANDBOX_FORBIDDEN_IMPORT)
        self.assertEqual(result.refusal.detail["allowed"],
                         list(sandbox.ALLOWED_IMPORTS
                              + sandbox.GEOMETRY_IMPORTS))


if __name__ == "__main__":
    unittest.main()
