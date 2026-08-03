from __future__ import annotations

import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from kukai.ir.decompile.sketch_extract import (
    PROFILE_INDEX_SCHEMA_VERSION,
    SKETCH_EXTRACT_SCHEMA_VERSION,
    CurveKind,
    ProfileExtraction,
    ProfileLoop,
    SketchPayloadError,
    build_sketch_extract_cs,
    extract_sketch_profiles,
)
from kukai.llm.revit_execution_pipeline import wrap_user_code
from kukai.security.validation import validate_code_safety


REPO_ROOT = next(
    ancestor
    for ancestor in Path(__file__).resolve().parents
    if (ancestor / "backend" / "pyproject.toml").is_file()
    and (ancestor / "backend" / "kukai" / "ir").is_dir()
)
BACKEND_ROOT = (REPO_ROOT / "backend").resolve()
PYTHON_EXECUTABLE = Path(sys.executable).resolve()
REVIT_VERSIONS = ("2021", "2022", "2023", "2024", "2025", "2026")


def _nuget_packages_root() -> Path:
    configured = (os.environ.get("NUGET_PACKAGES") or "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return Path.home() / ".nuget" / "packages"


def _loop(
    points: list[list[float | int]],
    *,
    kinds: list[str] | None = None,
    midpoints: list[list[float | int] | None] | None = None,
) -> dict:
    count = len(points)
    return {
        "points_mm": points,
        "curve_kinds": kinds or ["line"] * count,
        "arc_midpoints_mm": midpoints or [None] * count,
    }


def _element(
    element_id: str,
    *,
    category: str = "OST_Floors",
    loops: list[dict] | None = None,
    available: bool = True,
    reason: str | None = None,
    stairs_run_paths: list[dict] | None = None,
) -> dict:
    return {
        "element_id": element_id,
        "category": category,
        "profile_available": available,
        "loops": loops if loops is not None else [],
        "reason": reason,
        "stairs_run_paths": (
            stairs_run_paths if stairs_run_paths is not None else []),
    }


def _payload(*elements: dict) -> dict:
    return {
        "schema_version": SKETCH_EXTRACT_SCHEMA_VERSION,
        "elements": list(elements),
    }


RECTANGLE = _loop([[0, 0], [6000, 0], [6000, 4000], [0, 4000]])


class SyntheticProfileAcceptanceTests(unittest.TestCase):
    def test_rectangle_has_one_four_point_exterior(self) -> None:
        extraction = extract_sketch_profiles(_payload(
            _element("101", loops=[RECTANGLE])))

        row = extraction.profile_index["101"]
        self.assertTrue(row["profile_available"])
        self.assertEqual(row["exterior_loop"], [
            [0.0, 0.0], [6000.0, 0.0],
            [6000.0, 4000.0], [0.0, 4000.0],
        ])
        self.assertEqual(len(row["exterior_loop"]), 4)
        self.assertEqual(row["holes"], [])
        self.assertEqual(row["curve_kinds"], [["line"] * 4])

    def test_courtyard_is_retained_as_one_hole_never_flattened(self) -> None:
        # Deliberately use the same winding for both loops.  Classification is
        # by actual containment/area, not an undocumented winding assumption.
        courtyard = _loop([
            [2000, 1000], [4000, 1000], [4000, 3000], [2000, 3000],
        ])
        extraction = extract_sketch_profiles(_payload(
            _element("102", loops=[courtyard, RECTANGLE])))

        row = extraction.profile_index["102"]
        self.assertTrue(row["profile_available"])
        self.assertEqual(len(row["exterior_loop"]), 4)
        self.assertEqual(len(row["holes"]), 1)
        self.assertEqual(row["holes"][0], [
            [2000.0, 1000.0], [4000.0, 1000.0],
            [4000.0, 3000.0], [2000.0, 3000.0],
        ])
        self.assertEqual(len(row["curve_kinds"]), 2)

    def test_arc_kind_and_exact_midpoint_are_preserved_not_chorded(self) -> None:
        arc_edged = _loop(
            [[0, 0], [6000, 0], [6000, 4000], [0, 4000]],
            kinds=["line", "arc", "line", "line"],
            midpoints=[None, [7000, 2000], None, None],
        )
        extraction = extract_sketch_profiles(_payload(
            _element("103", loops=[arc_edged])))

        row = extraction.profile_index["103"]
        self.assertTrue(row["profile_available"])
        self.assertEqual(len(row["exterior_loop"]), 4)
        self.assertEqual(row["curve_kinds"][0][1], "arc")
        self.assertEqual(row["arc_midpoints"][0][1], [7000.0, 2000.0])
        self.assertNotIn([7000.0, 2000.0], row["exterior_loop"])

    def test_unavailable_is_honest_and_has_no_bbox_fabrication(self) -> None:
        extraction = extract_sketch_profiles(_payload(_element(
            "104", available=False, reason="dependent Sketch count is 0")))

        self.assertEqual(
            extraction.profile_index["104"],
            {"profile_available": False},
        )
        encoded = extraction.to_json()
        self.assertNotIn("bbox", encoded.lower())
        self.assertIn("dependent Sketch count is 0", encoded)

    def test_bbox_fields_are_protocol_errors_not_candidate_contours(self) -> None:
        row = _element(
            "105", available=False, reason="Sketch.Profile unavailable")
        row["bbox_min_mm"] = [0, 0, 0]
        row["bbox_max_mm"] = [6000, 4000, 300]
        with self.assertRaisesRegex(SketchPayloadError, "unexpected bbox"):
            extract_sketch_profiles(_payload(row))

    def test_disjoint_loops_fail_closed_instead_of_becoming_a_hole(self) -> None:
        disjoint = _loop([
            [10000, 0], [11000, 0], [11000, 1000], [10000, 1000],
        ])
        extraction = extract_sketch_profiles(_payload(
            _element("106", loops=[RECTANGLE, disjoint])))

        self.assertEqual(
            extraction.profile_index["106"],
            {"profile_available": False},
        )
        self.assertIn("disjoint", extraction.failures[0].reason)

    def test_unsupported_curve_kind_fails_the_whole_element_closed(self) -> None:
        spline = _loop(
            [[0, 0], [6000, 0], [6000, 4000], [0, 4000]],
            kinds=["line", "nurb_spline", "line", "line"],
        )
        extraction = extract_sketch_profiles(_payload(
            _element("107", loops=[spline])))
        self.assertFalse(extraction.entry_for("107").profile_available)
        self.assertIn("line/arc", extraction.failures[0].reason)

    def test_wrapped_bridge_envelope_is_supported_without_guessing(self) -> None:
        extraction = extract_sketch_profiles({
            "ok": True,
            "result": {"ok": True, "result": _payload(
                _element("108", loops=[RECTANGLE]))},
        })
        self.assertTrue(extraction.entry_for("108").profile_available)


class StairsRunPathTests(unittest.TestCase):
    def test_parent_profile_unavailable_but_real_run_path_is_retained(self) -> None:
        run = {
            "run_id": "501",
            "path_available": True,
            "points_mm": [[0, 0], [2500, 0], [5000, 2000]],
            "curve_kinds": ["line", "arc"],
            "arc_midpoints_mm": [None, [4000, 500]],
            "reason": None,
        }
        extraction = extract_sketch_profiles(_payload(_element(
            "500",
            category="OST_Stairs",
            available=False,
            reason="stairs parent has no single reliable closed Sketch profile",
            stairs_run_paths=[run],
        )))

        self.assertEqual(
            extraction.profile_index["500"],
            {"profile_available": False},
        )
        path = extraction.stairs_run_path_index["500"]["501"]
        self.assertTrue(path["path_available"])
        self.assertEqual(path["curve_kinds"], ["line", "arc"])
        self.assertEqual(path["arc_midpoints_mm"][1], [4000.0, 500.0])

    def test_unavailable_run_path_has_no_synthetic_geometry(self) -> None:
        run = {
            "run_id": "511",
            "path_available": False,
            "points_mm": [],
            "curve_kinds": [],
            "arc_midpoints_mm": [],
            "reason": "run was not generated yet",
        }
        extraction = extract_sketch_profiles(_payload(_element(
            "510",
            category="OST_Stairs",
            available=False,
            reason="no single stairs profile",
            stairs_run_paths=[run],
        )))
        self.assertEqual(
            extraction.stairs_run_path_index["510"]["511"],
            {"path_available": False},
        )
        self.assertTrue(any(
            "run was not generated" in failure.reason
            for failure in extraction.failures))


class SideIndexPersistenceTests(unittest.TestCase):
    def _mixed_extraction(self) -> ProfileExtraction:
        arc_edged = _loop(
            [[0, 0], [6000, 0], [6000, 4000], [0, 4000]],
            kinds=["line", "arc", "line", "line"],
            midpoints=[None, [7000, 2000], None, None],
        )
        return extract_sketch_profiles(_payload(
            _element("20", available=False, reason="no Sketch"),
            _element("3", loops=[arc_edged]),
        ))

    def test_json_round_trip_is_lossless_and_canonical(self) -> None:
        original = self._mixed_extraction()
        encoded = original.to_json()
        restored = ProfileExtraction.from_json(encoded)

        self.assertEqual(restored, original)
        self.assertEqual(restored.to_json(), encoded)
        decoded = json.loads(encoded)
        self.assertEqual(
            decoded["schema_version"], PROFILE_INDEX_SCHEMA_VERSION)
        self.assertEqual(set(decoded["profile_index"]), {"3", "20"})

    def test_unavailable_persisted_record_rejects_hidden_contours(self) -> None:
        row = self._mixed_extraction().to_dict()
        row["profile_index"]["20"]["exterior_loop"] = [[0, 0]]
        with self.assertRaisesRegex(SketchPayloadError, "unexpected exterior"):
            ProfileExtraction.from_dict(row)

    def test_duplicate_element_ids_are_rejected(self) -> None:
        with self.assertRaisesRegex(SketchPayloadError, "duplicate"):
            extract_sketch_profiles(_payload(
                _element("3", loops=[RECTANGLE]),
                _element("3", loops=[RECTANGLE]),
            ))

    def test_deterministic_under_two_pythonhashseed_values(self) -> None:
        script = textwrap.dedent(
            f"""
            from kukai.ir.decompile.sketch_extract import extract_sketch_profiles
            payload = {repr(_payload(
                _element("20", available=False, reason="no Sketch"),
                _element("3", loops=[RECTANGLE]),
            ))}
            print(extract_sketch_profiles(payload).to_json())
            """
        )
        outputs = []
        for seed in ("7", "991"):
            env = dict(os.environ)
            env["PYTHONHASHSEED"] = seed
            env["PYTHONPATH"] = str(BACKEND_ROOT)
            completed = subprocess.run(
                [str(PYTHON_EXECUTABLE), "-c", script],
                cwd=BACKEND_ROOT,
                env=env,
                text=True,
                capture_output=True,
                timeout=30,
                check=True,
            )
            outputs.append(completed.stdout)
        self.assertEqual(outputs[0], outputs[1])

    def test_direct_profile_loop_requires_arc_midpoint(self) -> None:
        with self.assertRaisesRegex(SketchPayloadError, "requires.*midpoint"):
            ProfileLoop(
                points_mm=((0.0, 0.0), (1.0, 0.0)),
                curve_kinds=(CurveKind.ARC, CurveKind.ARC),
                arc_midpoints_mm=(None, None),
            )


class EmittedCSharpContractTests(unittest.TestCase):
    def test_body_is_deterministic_read_only_and_static_safe(self) -> None:
        body = build_sketch_extract_cs()
        self.assertEqual(body, build_sketch_extract_cs())
        self.assertIsNone(validate_code_safety(body))
        for required in (
            "Sketch.Profile",
            "GetDependentElements(null)",
            "__roof.GetProfiles()",
            "__roof.GetProfile()",
            "GetStairsRuns()",
            "GetStairsPath()",
            "UnitUtils.ConvertFromInternalUnits",
            "UnitTypeId.Millimeters",
            '"arc"',
            "Evaluate(0.5, true)",
            ".Id.ToString()",
        ):
            self.assertIn(required, body)
        for forbidden in (
            "get_BoundingBox", "get_Geometry", "Tessellate", "Transaction",
            "304.8", "IntegerValue",
        ):
            self.assertNotIn(forbidden, body)

    def test_collections_and_elements_are_ordered_deterministically(self) -> None:
        body = build_sketch_extract_cs()
        # ШЕСТЬ коллекторов: пол, кровля, лестница и дописанные волной захвата
        # 29.07 потолок + два рода ограждений (OST_StairsRailing и
        # OST_Railings). Плюс СЕДЬМАЯ сортировка — марши внутри лестницы.
        # Числа держатся здесь намеренно: коллектор без .OrderBy отдаёт строки
        # в порядке Revit, и тогда два прогона по одной модели дают разные
        # байты индекса, а вся проверка воспроизводимости становится ложной.
        collectors = 6
        self.assertEqual(body.count(".OrderBy("), collectors + 1)
        self.assertIn("long.Parse(__id.ToString())", body)
        self.assertEqual(
            body.count("WhereElementIsNotElementType()"), collectors)

    @unittest.skipUnless(shutil.which("dotnet"), "dotnet SDK is unavailable")
    def test_in_process_roslyn_gate_compiles_provisioned_refs_and_fails_closed(self) -> None:
        """Run all provisioned refs and prove an incomplete service won't start."""

        compile_source = BACKEND_ROOT / "compile-service"
        self.assertTrue((compile_source / "CompileService.csproj").exists())
        package_root = (
            _nuget_packages_root() / "revit_all_main_versions_api_x64"
        )
        missing_versions = tuple(
            version for version in REVIT_VERSIONS
            if not all((
                package_root / f"{version}.0.0" / "lib" /
                ("net8.0" if int(version) >= 2025 else "net48") / dll
            ).is_file() for dll in ("RevitAPI.dll", "RevitAPIUI.dll"))
        )
        gate_versions = tuple(
            version for version in REVIT_VERSIONS
            if version not in missing_versions)
        with tempfile.TemporaryDirectory() as directory:
            temp_root = Path(directory)
            compile_copy = temp_root / "compile-service"
            # ProjectReference otherwise refreshes tracked bin/obj artifacts in
            # the worktree.  Compile an exact source copy so this acceptance
            # gate remains non-mutating with respect to frozen files.
            shutil.copytree(
                compile_source,
                compile_copy,
                ignore=shutil.ignore_patterns("bin", "obj"),
            )
            compile_project = compile_copy / "CompileService.csproj"

            if missing_versions:
                completed = subprocess.run(
                    ["dotnet", "run", "--project", str(compile_project),
                     "-c", "Release"],
                    cwd=BACKEND_ROOT,
                    text=True,
                    capture_output=True,
                    timeout=180,
                    check=False,
                )
                details = completed.stdout + completed.stderr
                self.assertNotEqual(completed.returncode, 0, details)
                self.assertIn("Compile service startup refused", details)
                for version in missing_versions:
                    self.assertIn(version, details)

            gate_dir = temp_root / "harness"
            gate_dir.mkdir()
            project_reference = str(compile_project).replace("&", "&amp;")
            (gate_dir / "SketchGate.csproj").write_text(textwrap.dedent(f"""
                <Project Sdk="Microsoft.NET.Sdk">
                  <PropertyGroup>
                    <OutputType>Exe</OutputType>
                    <TargetFramework>net8.0</TargetFramework>
                    <ImplicitUsings>enable</ImplicitUsings>
                    <Nullable>enable</Nullable>
                    <NuGetAudit>false</NuGetAudit>
                  </PropertyGroup>
                  <ItemGroup>
                    <ProjectReference Include="{project_reference}" />
                  </ItemGroup>
                </Project>
            """).strip() + "\n", encoding="utf-8")
            (gate_dir / "Program.cs").write_text(textwrap.dedent("""
                using CompileService;
                using Microsoft.Extensions.Logging.Abstractions;

                var source = Console.In.ReadToEnd();
                var compiler = new RoslynCompiler(
                    NullLogger<RoslynCompiler>.Instance);
                var failures = 0;
                foreach (var version in new string[] { __VERSIONS__ })
                {
                    var result = compiler.Compile(source, version);
                    Console.WriteLine(
                        $"{version}:{(result.Success ? "OK" : "FAIL")}");
                    foreach (var error in result.Errors.Take(8))
                        Console.WriteLine(
                            $"  {error.Code} L{error.Line}: {error.Message}");
                    if (!result.Success) failures++;
                }
                Environment.ExitCode = failures == 0 ? 0 : 1;
            """).replace(
                "__VERSIONS__",
                ", ".join(json.dumps(version) for version in gate_versions),
            ).strip() + "\n", encoding="utf-8")
            from kukai.ir.compiler import compile_rebuild_chunk
            from kukai.ir.decompile.extract import build_category_probe_cs
            from kukai.ir.decompile.group_extract import (
                build_group_extract_cs,
            )
            from kukai.ir.decompile.pipeline import _revision_guard_cs

            a5 = compile_rebuild_chunk({
                "ir_version": "1.0",
                "ops": [{
                    "op": "create_wall", "id": "W", "p0_mm": [0, 0],
                    "p1_mm": [1000, 0], "height_mm": 3000,
                    "level": {"by": "element_id", "value": 42},
                    "type": {"by": "element_id", "value": 901},
                }],
            }, stamp_scope="a5:0123456789ab:0123456789abcdef",
                expected_document={
                    "title": "Copy A5", "path_name": "", "project_uid": "u",
                })
            self.assertTrue(a5.ok, [d.as_dict() for d in a5.diagnostics])
            sources = {
                "sketch": wrap_user_code(build_sketch_extract_cs()),
                "group_level_binding_v2": wrap_user_code(
                    build_group_extract_cs()),
                "revision_guard": wrap_user_code(_revision_guard_cs(
                    build_category_probe_cs("OST_Walls"))),
                "a5_guarded_write": wrap_user_code(a5.csharp),
            }
            outcomes: dict[str, tuple[int, str]] = {}
            for label, source in sources.items():
                completed = subprocess.run(
                    ["dotnet", "run", "--project",
                     str(gate_dir / "SketchGate.csproj"), "-c", "Release"],
                    input=source,
                    cwd=BACKEND_ROOT,
                    text=True,
                    capture_output=True,
                    timeout=180,
                    check=False,
                )
                outcomes[label] = (
                    completed.returncode,
                    completed.stdout + completed.stderr,
                )
        for label, (returncode, details) in outcomes.items():
            self.assertEqual(returncode, 0, f"{label}:\n{details}")
            for version in gate_versions:
                self.assertIn(f"{version}:OK", details, label)
            self.assertEqual(
                details.count(":OK"), len(gate_versions),
                f"{label}:\n{details}")
            for version in missing_versions:
                self.assertNotIn(f"{version}:OK", details, label)

    @unittest.skipUnless(shutil.which("dotnet"), "dotnet SDK is unavailable")
    def test_configured_override_lets_the_gate_start_on_a_reduced_matrix(
        self,
    ) -> None:
        """An explicit ``KUKAI_COMPILE_REQUIRED_VERSIONS`` override lets the
        service start (ready) on exactly the versions a machine provisions.

        The fail-closed refusal throws *before* ``app.Run()`` and exits the
        process (proven by the sibling test).  A ready start instead binds the
        socket and serves forever, so this cannot assert on an exit code: it
        launches the real ``Program.cs`` in the background, polls ``/ready``
        over HTTP, and asserts the service advertises exactly the configured
        subset with nothing missing — i.e. the refusal branch was NOT taken.
        """
        package_root = (
            _nuget_packages_root() / "revit_all_main_versions_api_x64"
        )
        provisioned = tuple(
            version for version in REVIT_VERSIONS
            if all((
                package_root / f"{version}.0.0" / "lib" /
                ("net8.0" if int(version) >= 2025 else "net48") / dll
            ).is_file() for dll in ("RevitAPI.dll", "RevitAPIUI.dll"))
        )
        if not provisioned:
            self.skipTest("no provisioned Revit reference sets to require")

        with tempfile.TemporaryDirectory() as directory:
            temp_root = Path(directory)
            compile_copy = temp_root / "compile-service"
            # Build a source copy so `dotnet run` cannot refresh the worktree's
            # tracked bin/obj (same non-mutating discipline as the sibling gate).
            shutil.copytree(
                BACKEND_ROOT / "compile-service",
                compile_copy,
                ignore=shutil.ignore_patterns("bin", "obj"),
            )
            compile_project = compile_copy / "CompileService.csproj"

            # An ephemeral loopback port — never collide with a real compile
            # service already bound to 52412 on this host.
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
                probe.bind(("127.0.0.1", 0))
                port = probe.getsockname()[1]

            log_path = temp_root / "service.log"
            env = {
                **os.environ,
                "KUKAI_COMPILE_REQUIRED_VERSIONS": ",".join(provisioned),
                "Urls": f"http://127.0.0.1:{port}",
            }
            log_sink = log_path.open("wb")
            try:
                service = subprocess.Popen(
                    ["dotnet", "run", "--project", str(compile_project),
                     "-c", "Release"],
                    cwd=BACKEND_ROOT,
                    env=env,
                    stdout=log_sink,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
                try:
                    payload = self._await_ready(
                        service, port, log_path, timeout=240)
                finally:
                    self._terminate_group(service)
            finally:
                log_sink.close()

        self.assertEqual(payload.get("status"), "ready", payload)
        self.assertEqual(
            sorted(payload.get("requiredVersions") or []),
            sorted(provisioned), payload)
        self.assertEqual(payload.get("missingVersions"), [], payload)
        # A ready gate advertises exactly the provisioned subset: required and
        # available coincide, nothing missing.
        self.assertEqual(
            sorted(payload.get("versions") or []), sorted(provisioned), payload)

    def _await_ready(
        self, service: "subprocess.Popen[bytes]", port: int, log_path: Path,
        *, timeout: float,
    ) -> dict:
        """Poll ``/ready`` until the service answers, or fail with its log.

        Once the socket is bound the startup guard has already passed (it throws
        before binding), so a reachable ``/ready`` is definitively ready; an
        early process exit means it refused.
        """
        deadline = time.monotonic() + timeout
        url = f"http://127.0.0.1:{port}/ready"
        last_error: object = None
        while time.monotonic() < deadline:
            exit_code = service.poll()
            if exit_code is not None:
                self.fail(
                    f"compile service exited early (code {exit_code}) instead "
                    f"of starting ready under the override:\n"
                    f"{self._read_log(log_path)}")
            try:
                with urllib.request.urlopen(url, timeout=5) as response:
                    return json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as http_error:
                # 503 = bound but degraded: a definitive failure (it should have
                # refused to bind at all), not a not-yet-listening blip.
                detail = http_error.read().decode("utf-8", "replace")
                self.fail(
                    f"/ready returned {http_error.code} under the override "
                    f"instead of a ready 200:\n{detail}\n---\n"
                    f"{self._read_log(log_path)}")
            except (urllib.error.URLError, OSError) as err:
                last_error = err  # still building / not yet bound: retry
                time.sleep(1.0)
        self.fail(
            f"compile service was not ready within {timeout:.0f}s "
            f"(last error: {last_error}):\n{self._read_log(log_path)}")

    @staticmethod
    def _read_log(log_path: Path) -> str:
        try:
            return log_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return "<no log captured>"

    @staticmethod
    def _terminate_group(service: "subprocess.Popen[bytes]") -> None:
        """Tear down the whole ``dotnet run`` process group (run + app child)."""
        if service.poll() is not None:
            return
        for sig, wait in ((signal.SIGTERM, 30), (signal.SIGKILL, 10)):
            try:
                os.killpg(os.getpgid(service.pid), sig)
            except (ProcessLookupError, PermissionError):
                service.kill()
            try:
                service.wait(timeout=wait)
                return
            except subprocess.TimeoutExpired:
                continue


if __name__ == "__main__":
    unittest.main()
