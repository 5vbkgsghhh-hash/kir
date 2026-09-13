"""ENVIRONMENT SIGNATURE: WHAT was written was already signed, WHAT IT WAS COMPUTED ON was not.

THE HOLE THESE TESTS CLOSE. `author_digest` is the sha256 of the script's TEXT
and nothing else (`sandbox.execute_author_script`). Neither the sandbox, nor the receipt,
nor the corpus signed the interpreter's version or the version of a single
library. There is exactly one consequence, and it is a heavy one: let shapely or GEOS update
underneath it between two audits of the same script — THE VERY SAME `author_digest`
would attest to DIFFERENT `program_digest` values, and there would be no field in the receipt
by which a reader could tell a script edit apart from environment drift. One building, two
signatures — on a layer that, before 09.08, was not signed at all.

`replay_check` does not catch this and cannot: it runs the script TWICE IN ONE
PROCESS on ONE installation and measures nondeterminism, not time.

The tests go from mechanism to receipt: a pure signing function → the block's presence
in the result of a real run → its presence in the gateway's receipt → the digest in
what actually lands on disk.

    venv/bin/python3.12 -m pytest kir/tests/test_environment_signature.py -q
"""
from __future__ import annotations

import sys
import types
import unittest

from kir import sandbox


class TheSignatureNamesTheEnvironment(unittest.TestCase):
    """A pure function: what gets signed and how it is obtained."""

    def test_interpreter_is_named(self) -> None:
        env = sandbox.environment_signature(("math",))
        self.assertEqual(env["python"],
                         ".".join(str(p) for p in sys.version_info[:3]))
        # The full string carries the build date and compiler: swapping the interpreter
        # while keeping the same "3.12.13" is visible only from here.
        self.assertIn(env["python"], env["python_build"])
        self.assertEqual(env["implementation"], sys.implementation.name)
        self.assertEqual(len(env["digest"]), 64)

    def test_every_importable_module_is_named_with_its_version(self) -> None:
        """EXACTLY the allowlist gets signed — not a hand-written list sitting next to it."""
        env = sandbox.environment_signature(sandbox.ALLOWED_IMPORTS)
        names = [m["name"] for m in env["modules"]]
        self.assertEqual(names, sorted(sandbox.ALLOWED_IMPORTS))
        for row in env["modules"]:
            # stdlib is versioned by the interpreter: it has no version of its own, and
            # the honest answer is to say so in words, not to substitute an empty string.
            self.assertEqual(row["version"], "stdlib")
            self.assertEqual(row["via"], "stdlib")

    def test_a_new_allowed_module_lands_in_the_signature_by_itself(self) -> None:
        """Extend the allowlist — the signature grows WITHOUT editing the list here.

        This is exactly the requirement that "the field is designed so that added modules
        fall into it automatically": a hand-written list would get forgotten to update
        on exactly the occasion when it matters.
        """
        probe = types.ModuleType("_kir_env_probe")
        probe.__version__ = "1.0.0"
        sys.modules["_kir_env_probe"] = probe
        try:
            env = sandbox.environment_signature(
                sandbox.ALLOWED_IMPORTS + ("_kir_env_probe",))
            row = next(m for m in env["modules"] if m["name"] == "_kir_env_probe")
            self.assertEqual(row["version"], "1.0.0")
            self.assertEqual(row["via"], "__version__")
            self.assertTrue(row["loaded"])
        finally:
            sys.modules.pop("_kir_env_probe", None)

    def test_the_digest_moves_when_a_library_version_moves(self) -> None:
        """THE FILE'S MAIN TEST: upgrading a library SHIFTS the signature.

        The script is untouched, `author_digest` is untouched — yet `env_digest` differs.
        This exact signal used to be absent from every field of the receipt.
        """
        probe = types.ModuleType("_kir_env_probe")
        probe.__version__ = "1.0.0"
        sys.modules["_kir_env_probe"] = probe
        try:
            before = sandbox.environment_signature(("_kir_env_probe",))["digest"]
            probe.__version__ = "1.0.1"          # the same script, a new build
            after = sandbox.environment_signature(("_kir_env_probe",))["digest"]
        finally:
            sys.modules.pop("_kir_env_probe", None)
        self.assertNotEqual(before, after)

    def test_the_digest_stands_still_when_nothing_moved(self) -> None:
        """A signature that shifts on its own certifies nothing."""
        first = sandbox.environment_signature(sandbox.ALLOWED_IMPORTS)["digest"]
        second = sandbox.environment_signature(sandbox.ALLOWED_IMPORTS)["digest"]
        self.assertEqual(first, second)

    def test_native_versions_are_named_when_the_module_is_loaded(self) -> None:
        """GEOS underneath shapely is also a version, and it drifts separately from shapely.

        It is looked up by the attribute's NAME, not by a list of libraries: a list would know about
        shapely and would not know about the next one.
        """
        probe = types.ModuleType("_kir_env_probe")
        probe.__version__ = "1.0.0"
        probe.geos_version = (3, 13, 1)
        probe.geos_version_string = "3.13.1"
        probe._private_version = "не должно попасть"
        sys.modules["_kir_env_probe"] = probe
        try:
            env = sandbox.environment_signature(("_kir_env_probe",))
            row = env["modules"][0]
            self.assertEqual(row["native"],
                             {"geos_version": "3.13.1",
                              "geos_version_string": "3.13.1"})
            before = env["digest"]
            probe.geos_version_string = "3.13.2"   # shapely unchanged, GEOS different
            after = sandbox.environment_signature(("_kir_env_probe",))["digest"]
        finally:
            sys.modules.pop("_kir_env_probe", None)
        self.assertNotEqual(before, after)

    def test_a_module_that_is_not_loaded_says_so(self) -> None:
        """«Нативных фактов нет» and «их не спросили» are different facts."""
        env = sandbox.environment_signature(("_kir_env_absent",))
        row = env["modules"][0]
        self.assertFalse(row["loaded"])
        self.assertEqual(row["version"], "unknown")
        self.assertNotIn("native", row)


class TheSignatureReachesTheReceipt(unittest.TestCase):
    """A measurement, not an intention: the block makes it from the child into the result and the receipt."""

    POLICY = sandbox.SandboxPolicy(replay_check=True)
    SOURCE = ('lvl = create_level(elev_mm=0, name="Этаж 1")\n'
              'create_wall(p0_mm=(0, 0), p1_mm=(5000, 0), level=lvl, '
              'height_mm=3000)\n')

    def test_a_real_run_carries_the_signature(self) -> None:
        result = sandbox.execute_author_script(self.SOURCE, policy=self.POLICY)
        self.assertTrue(result.ok, result.refusal and result.refusal.render())
        self.assertEqual(len(result.environment["digest"]), 64)
        self.assertEqual(result.env_digest, result.environment["digest"])
        self.assertEqual([m["name"] for m in result.environment["modules"]],
                         sorted(sandbox.ALLOWED_IMPORTS))
        self.assertIn("environment", result.as_dict())
        # The repeat checks the environment too: an update landing exactly between the two runs
        # would make the first run's signature the signature of an environment that no longer exists.
        self.assertEqual(result.isolation["environment_replay"], "same")

    def test_a_refused_run_carries_it_too(self) -> None:
        """The signature of an environment in which the script did NOT assemble is evidence all the same."""
        result = sandbox.execute_author_script("1 / 0\n", policy=self.POLICY)
        self.assertFalse(result.ok)
        self.assertEqual(len(result.env_digest), 64)

    def test_the_gateway_receipt_carries_the_whole_block(self) -> None:
        """The auditor looks into the receipt — so the block lives in the receipt.

        In full, not as a single digest: the digest answers «did it drift», the block answers
        «exactly what», and the second question is asked by whoever already got a hit on the first.
        """
        from kir import serving

        result = sandbox.execute_author_script(self.SOURCE, policy=self.POLICY)
        receipt = serving._authorship_receipt(
            result, source_bytes=len(self.SOURCE.encode("utf-8")))
        self.assertEqual(receipt["environment"], result.environment)
        self.assertEqual(receipt["environment"]["digest"], result.env_digest)

    def test_the_receipt_stays_silent_when_no_child_ran(self) -> None:
        """What is absent stays absent: an empty block would say
        «environment unknown» where the truth is «the script did not run»."""
        from kir import serving

        result = sandbox.execute_author_script("   \n", policy=self.POLICY)
        self.assertFalse(result.ok)
        self.assertEqual(result.environment, {})
        self.assertNotIn("environment",
                         serving._authorship_receipt(result, source_bytes=4))


class TheSignatureReachesTheDisk(unittest.TestCase):
    """The receipt lives for one turn; the corpus outlives library upgrades."""

    def test_the_witness_feed_records_the_env_digest(self) -> None:
        import json
        import os
        import tempfile

        from kir import witness_feed

        with tempfile.TemporaryDirectory(prefix="kir_env_feed_") as tmp:
            path = os.path.join(tmp, "kir_witness.jsonl")
            previous = os.environ.get("KIR_WITNESS_PATH")
            os.environ["KIR_WITNESS_PATH"] = path
            try:
                witness_feed.record_witness(
                    program={"ops": [{"op": "create_wall", "id": "w1"}]},
                    family="write", revit_version="2026", ok=True,
                    witness=None, duration_ms=1.0,
                    author_digest="a" * 64, env_digest="b" * 64)
            finally:
                if previous is None:
                    os.environ.pop("KIR_WITNESS_PATH", None)
                else:
                    os.environ["KIR_WITNESS_PATH"] = previous
            with open(path, encoding="utf-8") as fh:
                row = json.loads(fh.readlines()[-1])
        self.assertEqual(row["author_digest"], "a" * 64)
        self.assertEqual(row["env_digest"], "b" * 64)

    def test_a_json_program_leaves_no_env_field(self) -> None:
        """No environment ever counted a program written as operations.
        An empty string in the corpus would read as «the script ran and did not sign»."""
        import json
        import os
        import tempfile

        from kir import witness_feed

        with tempfile.TemporaryDirectory(prefix="kir_env_feed_") as tmp:
            path = os.path.join(tmp, "kir_witness.jsonl")
            previous = os.environ.get("KIR_WITNESS_PATH")
            os.environ["KIR_WITNESS_PATH"] = path
            try:
                witness_feed.record_witness(
                    program={"ops": [{"op": "create_wall", "id": "w1"}]},
                    family="write", revit_version="2026", ok=True,
                    witness=None, duration_ms=1.0)
            finally:
                if previous is None:
                    os.environ.pop("KIR_WITNESS_PATH", None)
                else:
                    os.environ["KIR_WITNESS_PATH"] = previous
            with open(path, encoding="utf-8") as fh:
                row = json.loads(fh.readlines()[-1])
        self.assertNotIn("env_digest", row)
        self.assertNotIn("author_digest", row)


if __name__ == "__main__":
    unittest.main()
