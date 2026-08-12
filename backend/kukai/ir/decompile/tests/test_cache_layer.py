"""A/B gates and invalidation proofs for the кэш-слой wave.

Two content-addressed caches are exercised here:

* :class:`kukai.ir.compile_cache.CachedCompileClient` — verified against a
  fake compile client so the live Roslyn service (:52412) is never touched.
* :func:`kukai.ir.decompile.lift_cache.cached_lift_document_detailed` — verified
  against the real, deterministic offline lifter on synthetic documents.

The load-bearing assertions are:
  1. cache-path result is IDENTICAL to the fresh-path result (A/B gate);
  2. a change to any keyed input (one element, an index, the code version)
     changes the key and forces a recompute (invalidation);
  3. only successful compiles are cached; failures and unavailability are not.
"""

from __future__ import annotations

import asyncio
import copy
import json
import unittest
from dataclasses import replace
from pathlib import Path
from typing import Any, Optional

from kukai.compile_client import CompileError, CompileResult
from kukai.ir.compile_cache import (
    CachedCompileClient,
    compile_cache_key,
)
from kukai.ir.decompile import lift_cache
from kukai.ir.decompile.l1_schema import AtomReason
from kukai.ir.decompile.lift import (
    LiftDiagnostic,
    LiftResult,
    lift_document_detailed,
)
from kukai.ir.decompile.lift_cache import (
    cached_lift_document_detailed,
    deserialize_lift_result,
    lift_cache_key,
    serialize_lift_result,
)
from kukai.ir.decompile.schema import L0Document
from kukai.ir.decompile.extract import EXTRACT_CATEGORIES
from kukai.ir.decompile.tests.fixtures_decompile import (
    make_element,
    project1_metadata,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _document(
    elements: list[dict[str, Any]],
    *,
    change_stamp: str = "synthetic-cache-v1",
) -> L0Document:
    row = copy.deepcopy(project1_metadata())
    row["change_stamp"] = change_stamp
    row["elements"] = copy.deepcopy(elements)
    row["category_status"] = []
    return L0Document.from_dict(row)


def _bulk_document(total: int, *, change_stamp: str = "bulk") -> L0Document:
    row = copy.deepcopy(project1_metadata())
    row["change_stamp"] = change_stamp
    els = []
    for ordinal in range(total):
        cat = EXTRACT_CATEGORIES[ordinal % len(EXTRACT_CATEGORIES)]
        els.append(make_element(cat, 10_000 + ordinal, ordinal=ordinal))
    row["elements"] = els
    row["category_status"] = []
    return L0Document.from_dict(row)


class _FakeCompileClient:
    """Records calls; never opens a socket.  Stands in for CompileClient."""

    def __init__(self, result: Optional[CompileResult]) -> None:
        self._result = result
        self.calls: list[tuple[str, str]] = []
        self._available = False
        self.closed = False

    async def check(
        self, wrapped_code: str, revit_version: str
    ) -> Optional[CompileResult]:
        self.calls.append((wrapped_code, revit_version))
        self._available = self._result is not None
        return self._result

    async def health(self) -> bool:
        return True

    async def close(self) -> None:
        self.closed = True

    @property
    def available(self) -> bool:
        return self._available


def _ok() -> CompileResult:
    return CompileResult(success=True, errors=[])


def _fail() -> CompileResult:
    return CompileResult(
        success=False,
        errors=[CompileError(code="CS0246", message="nope", line=1, column=1)],
    )


# ---------------------------------------------------------------------------
# Exact compile-key semantics (the subtle bit)
# ---------------------------------------------------------------------------

class CompileKeyTests(unittest.TestCase):
    _toolchain = "sha256:toolchain-a"

    def test_numeric_literals_never_share_a_key(self) -> None:
        a = 'obj.CreateWall(__el, 0.0, 0.0, 6000.0, 2800.0, "Стена 200");'
        b = 'obj.CreateWall(__el, 1200.5, 500.0, 7200.0, 3000.0, "Стена 200");'
        self.assertNotEqual(
            compile_cache_key(
                a, "2026", toolchain_identity=self._toolchain
            ),
            compile_cache_key(
                b, "2026", toolchain_identity=self._toolchain
            ),
        )

    def test_constant_type_counterexample_never_aliases(self) -> None:
        # These values can select different overloads and do not necessarily
        # have the same compile verdict.  This is why skeleton normalization is
        # unsound even when strings/identifiers are tokenized perfectly.
        small = "M(2147483647);"
        large = "M(2147483648);"
        self.assertNotEqual(
            compile_cache_key(
                small, "2026", toolchain_identity=self._toolchain
            ),
            compile_cache_key(
                large, "2026", toolchain_identity=self._toolchain
            ),
        )

    def test_toolchain_and_revit_version_invalidate(self) -> None:
        code = "M(1);"
        baseline = compile_cache_key(
            code, "2026", toolchain_identity=self._toolchain
        )
        self.assertNotEqual(
            baseline,
            compile_cache_key(
                code, "2025", toolchain_identity=self._toolchain
            ),
        )
        self.assertNotEqual(
            baseline,
            compile_cache_key(
                code, "2026", toolchain_identity="sha256:toolchain-b"
            ),
        )

    def test_missing_toolchain_identity_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            compile_cache_key("M(1);", "2026", toolchain_identity="")


# ---------------------------------------------------------------------------
# CachedCompileClient A/B + invalidation gates
# ---------------------------------------------------------------------------

class CompileCacheGateTests(unittest.IsolatedAsyncioTestCase):
    _toolchain = "sha256:test-toolchain"

    def setUp(self) -> None:
        self._dir = Path(self.enterContext(_tempdir()))

    async def test_disabled_is_pure_passthrough(self) -> None:
        fake = _FakeCompileClient(_ok())
        cached = CachedCompileClient(fake, enabled=False, cache_dir=self._dir)
        for _ in range(3):
            self.assertEqual(await cached.check("f(1);", "2026"), _ok())
        # No caching -> the wrapped client was called every time.
        self.assertEqual(len(fake.calls), 3)

    async def test_ab_identity_and_single_backend_call(self) -> None:
        fake = _FakeCompileClient(_ok())
        cached = CachedCompileClient(
            fake,
            enabled=True,
            toolchain_identity=self._toolchain,
            cache_dir=self._dir,
        )

        # Fresh path (miss) vs cache path (hit) on byte-identical code.
        a = "obj.CreateWall(__el, 0.0, 6000.0, 2800.0);"
        first = await cached.check(a, "2026")
        second = await cached.check(a, "2026")

        self.assertEqual(first, second)  # A/B identity
        self.assertEqual(cached.hits, 1)
        self.assertEqual(cached.misses, 1)
        self.assertEqual(len(fake.calls), 1)

    async def test_different_numeric_values_do_not_alias(self) -> None:
        fake = _FakeCompileClient(_ok())
        cached = CachedCompileClient(
            fake,
            enabled=True,
            toolchain_identity=self._toolchain,
        )
        await cached.check("M(2147483647);", "2026")
        await cached.check("M(2147483648);", "2026")
        self.assertEqual(len(fake.calls), 2)
        self.assertEqual(cached.hits, 0)

    async def test_failures_are_not_cached(self) -> None:
        fake = _FakeCompileClient(_fail())
        cached = CachedCompileClient(
            fake,
            enabled=True,
            toolchain_identity=self._toolchain,
            cache_dir=self._dir,
        )
        await cached.check("bad();", "2026")
        await cached.check("bad();", "2026")
        # A failing compile is recomputed every time.
        self.assertEqual(len(fake.calls), 2)
        self.assertEqual(cached.hits, 0)

    async def test_unavailable_service_is_not_cached(self) -> None:
        fake = _FakeCompileClient(None)  # service down
        cached = CachedCompileClient(
            fake,
            enabled=True,
            toolchain_identity=self._toolchain,
            cache_dir=self._dir,
        )
        self.assertIsNone(await cached.check("f(1);", "2026"))
        self.assertIsNone(await cached.check("f(1);", "2026"))
        self.assertEqual(len(fake.calls), 2)

    async def test_revit_version_is_part_of_the_key(self) -> None:
        fake = _FakeCompileClient(_ok())
        cached = CachedCompileClient(
            fake,
            enabled=True,
            toolchain_identity=self._toolchain,
            cache_dir=self._dir,
        )
        await cached.check("f(1);", "2025")
        await cached.check("f(1);", "2026")
        self.assertEqual(len(fake.calls), 2)  # no cross-version hit

    async def test_disk_persistence_survives_new_client(self) -> None:
        fake1 = _FakeCompileClient(_ok())
        c1 = CachedCompileClient(
            fake1,
            enabled=True,
            toolchain_identity=self._toolchain,
            cache_dir=self._dir,
        )
        await c1.check("f(1);", "2026")
        self.assertEqual(len(fake1.calls), 1)

        # A brand-new client with an empty LRU still hits the on-disk entry.
        fake2 = _FakeCompileClient(_ok())
        c2 = CachedCompileClient(
            fake2,
            enabled=True,
            toolchain_identity=self._toolchain,
            cache_dir=self._dir,
        )
        result = await c2.check("f(1);", "2026")
        self.assertEqual(result, _ok())
        self.assertEqual(len(fake2.calls), 0)
        self.assertEqual(c2.hits, 1)

    async def test_disk_entry_is_invalidated_by_toolchain(self) -> None:
        fake1 = _FakeCompileClient(_ok())
        c1 = CachedCompileClient(
            fake1,
            enabled=True,
            toolchain_identity="sha256:toolchain-a",
            cache_dir=self._dir,
        )
        await c1.check("f(1);", "2026")

        fake2 = _FakeCompileClient(_ok())
        c2 = CachedCompileClient(
            fake2,
            enabled=True,
            toolchain_identity="sha256:toolchain-b",
            cache_dir=self._dir,
        )
        await c2.check("f(1);", "2026")
        self.assertEqual(len(fake2.calls), 1)
        self.assertEqual(c2.hits, 0)

    async def test_concurrent_identical_requests_are_coalesced(self) -> None:
        release = asyncio.Event()

        class _BlockingCompileClient(_FakeCompileClient):
            async def check(self, wrapped_code, revit_version):
                self.calls.append((wrapped_code, revit_version))
                await release.wait()
                return self._result

        fake = _BlockingCompileClient(_ok())
        cached = CachedCompileClient(
            fake,
            enabled=True,
            toolchain_identity=self._toolchain,
        )
        first = asyncio.create_task(cached.check("f(1);", "2026"))
        second = asyncio.create_task(cached.check("f(1);", "2026"))
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        self.assertEqual(len(fake.calls), 1)
        release.set()
        self.assertEqual(await first, _ok())
        self.assertEqual(await second, _ok())
        self.assertEqual(cached.coalesced, 1)

    async def test_enabled_without_toolchain_identity_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            CachedCompileClient(_FakeCompileClient(_ok()), enabled=True)

    async def test_close_delegates(self) -> None:
        fake = _FakeCompileClient(_ok())
        cached = CachedCompileClient(
            fake,
            enabled=True,
            toolchain_identity=self._toolchain,
            cache_dir=self._dir,
        )
        await cached.close()
        self.assertTrue(fake.closed)


# ---------------------------------------------------------------------------
# lift cache A/B + invalidation gates
# ---------------------------------------------------------------------------

class LiftCacheGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = Path(self.enterContext(_tempdir()))

    def _wall_doc(self, *, change_stamp: str = "wall-doc") -> L0Document:
        wall = make_element("OST_Walls", 5001, ordinal=0)
        col = make_element("OST_StructuralColumns", 5002, ordinal=1)
        return _document([wall, col], change_stamp=change_stamp)

    def test_serialize_roundtrip_is_byte_identical(self) -> None:
        result = lift_document_detailed(self._bulk())
        restored = deserialize_lift_result(
            json.loads(json.dumps(serialize_lift_result(result)))
        )
        self.assertEqual(
            json.dumps(serialize_lift_result(result), sort_keys=True),
            json.dumps(serialize_lift_result(restored), sort_keys=True),
        )
        # And the dataclass/enum shape is fully reconstructed.
        self.assertEqual(result.nodes, restored.nodes)
        for a, b in zip(result.diagnostics, restored.diagnostics):
            self.assertIsInstance(b.reason, AtomReason)
            self.assertEqual(a, b)

    def _bulk(self) -> L0Document:
        return _bulk_document(120, change_stamp="bulk-serialize")

    def test_disabled_matches_fresh_and_writes_nothing(self) -> None:
        doc = self._wall_doc()
        out = cached_lift_document_detailed(
            doc, enabled=False, cache_dir=self._dir
        )
        fresh = lift_document_detailed(doc)
        self.assertEqual(out.nodes, fresh.nodes)
        self.assertEqual(out.diagnostics, fresh.diagnostics)
        self.assertEqual(list(self._dir.iterdir()), [])  # no disk touch

    def test_ab_gate_cache_path_equals_fresh_path(self) -> None:
        doc = self._wall_doc()
        fresh = lift_document_detailed(doc)

        # miss (writes), then hit (reads).
        miss = cached_lift_document_detailed(
            doc, enabled=True, cache_dir=self._dir
        )
        hit = cached_lift_document_detailed(
            doc, enabled=True, cache_dir=self._dir
        )

        for candidate in (miss, hit):
            self.assertEqual(candidate.nodes, fresh.nodes)
            self.assertEqual(candidate.diagnostics, fresh.diagnostics)
            self.assertEqual(
                json.dumps(serialize_lift_result(candidate), sort_keys=True),
                json.dumps(serialize_lift_result(fresh), sort_keys=True),
            )
        # exactly one entry on disk.
        self.assertEqual(
            len([p for p in self._dir.iterdir() if p.suffix == ".json"]), 1
        )

    def test_hit_does_not_recompute(self) -> None:
        doc = self._wall_doc()
        original = lift_cache.lift_document_detailed
        try:
            cached_lift_document_detailed(
                doc, enabled=True, cache_dir=self._dir
            )
            calls = {"n": 0}

            def _spy(*args: Any, **kwargs: Any) -> LiftResult:
                calls["n"] += 1
                return original(*args, **kwargs)

            lift_cache.lift_document_detailed = _spy  # type: ignore[assignment]
            cached_lift_document_detailed(
                doc, enabled=True, cache_dir=self._dir
            )
            self.assertEqual(calls["n"], 0)  # served from disk, no lift
        finally:
            lift_cache.lift_document_detailed = original  # type: ignore[assignment]

    def test_changing_one_element_changes_the_key(self) -> None:
        doc = self._wall_doc()
        wall = make_element("OST_Walls", 5001, ordinal=0)
        wall["params"] = {"WALL_USER_HEIGHT_PARAM": 9999.0}  # different height
        col = make_element("OST_StructuralColumns", 5002, ordinal=1)
        mutated = _document([wall, col], change_stamp="wall-doc")

        self.assertNotEqual(lift_cache_key(doc), lift_cache_key(mutated))

    def test_changing_change_stamp_changes_the_key(self) -> None:
        a = self._wall_doc(change_stamp="stamp-a")
        b = self._wall_doc(change_stamp="stamp-b")
        self.assertNotEqual(lift_cache_key(a), lift_cache_key(b))

    def test_changing_index_changes_the_key(self) -> None:
        doc = self._wall_doc()
        idx_a = {"profile_index": {}, "stairs_run_path_index": {}}
        idx_b = {
            "profile_index": {"5001": {"profile_available": False}},
            "stairs_run_path_index": {},
        }
        self.assertNotEqual(
            lift_cache_key(doc, idx_a), lift_cache_key(doc, idx_b)
        )

    def test_changing_code_version_changes_the_key(self) -> None:
        doc = self._wall_doc()
        real = lift_cache._lift_source_hash
        try:
            lift_cache._lift_source_hash = lambda: "codehash-A"  # type: ignore[assignment]
            key_a = lift_cache_key(doc)
            lift_cache._lift_source_hash = lambda: "codehash-B"  # type: ignore[assignment]
            key_b = lift_cache_key(doc)
        finally:
            lift_cache._lift_source_hash = real  # type: ignore[assignment]
        self.assertNotEqual(key_a, key_b)

    def test_stale_code_version_forces_recompute(self) -> None:
        doc = self._wall_doc()
        # Write an entry under code-version A.
        real = lift_cache._lift_source_hash
        try:
            lift_cache._lift_source_hash = lambda: "codehash-A"  # type: ignore[assignment]
            cached_lift_document_detailed(
                doc, enabled=True, cache_dir=self._dir
            )
            entries_a = {p.name for p in self._dir.glob("*.json")}
            # Now the lifter "changes" -> a new key, a new entry, no stale hit.
            lift_cache._lift_source_hash = lambda: "codehash-B"  # type: ignore[assignment]
            out = cached_lift_document_detailed(
                doc, enabled=True, cache_dir=self._dir
            )
            entries_b = {p.name for p in self._dir.glob("*.json")}
        finally:
            lift_cache._lift_source_hash = real  # type: ignore[assignment]
        self.assertEqual(out.nodes, lift_document_detailed(doc).nodes)
        self.assertTrue(entries_b - entries_a)  # a fresh entry appeared


# ---------------------------------------------------------------------------
# tiny tempdir contextmanager (avoids importing pytest fixtures)
# ---------------------------------------------------------------------------

import contextlib
import tempfile


@contextlib.contextmanager
def _tempdir():
    path = tempfile.mkdtemp(prefix="kir-cache-test-")
    try:
        yield path
    finally:
        import shutil

        shutil.rmtree(path, ignore_errors=True)


class CanonicalJsonAgreement(unittest.TestCase):
    """The eight ``_canonical_json`` of this package must mean one thing.

    REFUTING TEST — both assertions fail on the code before 10.08.2026, where
    ``lift_cache._canonical_json`` omitted ``allow_nan=False`` and therefore
    emitted the non-JSON literals ``NaN`` / ``Infinity`` while the other seven
    raised.  Measured that day: on twelve finite probe shapes all eight agreed
    byte for byte, so this is the whole of the divergence, not a sample of it.
    """

    _MODULES = (
        "kukai.ir.midend",
        "kukai.ir.decompile.journal",
        "kukai.ir.decompile.lift_cache",
        "kukai.ir.decompile.geometry_acceptance",
        "kukai.ir.decompile.passport",
        "kukai.ir.decompile.merkle",
        "kukai.ir.acceptance_live",
        "kukai.ir.acceptance_mutation",
    )

    def _impls(self):
        import importlib

        out = {}
        for name in self._MODULES:
            fn = getattr(importlib.import_module(name), "_canonical_json", None)
            self.assertIsNotNone(fn, f"{name} lost its _canonical_json")
            out[name] = fn
        return out

    def test_every_canon_refuses_non_finite_numbers(self) -> None:
        for probe in ({"v": float("nan")}, {"v": float("inf")},
                      {"v": float("-inf")}):
            for name, fn in self._impls().items():
                with self.subTest(module=name, probe=repr(probe)):
                    with self.assertRaises(Exception):
                        fn(probe)

    def test_every_canon_agrees_on_finite_payloads(self) -> None:
        probes = (
            {"b": 1, "a": 2},
            {"name": "Кухня"},
            {"x": 1.0, "y": 1},
            {"z": -0.0},
            {"p": (1, 2, 3)},
            {"a": {}, "b": [], "c": None},
            {"n": 2 ** 53 + 1},
            {"ключ": "значение"},
            {"s": "a\tb\nc"},
        )
        impls = self._impls()
        for probe in probes:
            with self.subTest(probe=repr(probe)):
                outs = {fn(probe) for fn in impls.values()}
                self.assertEqual(
                    len(outs), 1,
                    f"the canons disagree on a finite payload: {outs}")


class NonFiniteMakesTheLiftEntryUncacheable(unittest.TestCase):
    """A NaN must force a MISS, never an exception out of key derivation.

    REFUTING TEST for the SHAPE of the fix, not only its presence: the naive
    repair (let ``allow_nan=False`` raise) would turn a document that keys
    fine today into a crashed run.  ``lift_cache``'s own law — stated in
    ``_lift_source_hash`` and ``_index_hash`` — is that it may cost a
    recompute and must never give a wrong answer, so both call sites answer
    with a distinct miss-forcing key instead.
    """

    def test_index_with_a_non_finite_value_keys_to_a_miss(self) -> None:
        from kukai.ir.decompile.lift_cache import _index_hash

        clean = _index_hash({"rows": [{"x": 1.0}]})
        dirty = _index_hash({"rows": [{"x": float("nan")}]})
        self.assertTrue(dirty.startswith("nonfinite:"), dirty)
        self.assertNotEqual(clean, dirty)

    def test_a_non_finite_index_does_not_kill_key_derivation(self) -> None:
        from kukai.ir.decompile.lift_cache import _index_hash

        # The point of the whole exercise: this call must RETURN.
        self.assertIsInstance(_index_hash({"x": float("inf")}), str)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
