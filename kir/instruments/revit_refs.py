"""Where on THIS box the REAL Revit reference assemblies live.

Why a separate instrument. The "C# compilation against installed APIs" strip
(`kir/tests/test_connector_compiler_conformance.py`) required three env vars,
and without them called `pytest.skip`. On the box, as of 09-07, the assemblies
for all six versions WERE PRESENT — in the NuGet cache — yet the strip stayed
silent, and the silence read as "clean". Turning that same strip on with just
the variables immediately produced 2 red results that nobody had seen.

Hence this module's rule: **a skip must name the REASON and the PLACES it
searched**. "Not configured" is not a reason if nobody said what is missing.

Search order (the first winner wins, the source is printed):

1. `KIR_TEST_REVIT_REFS_ROOT` — a directory `<year>/RevitAPI.dll` (the
   operator's explicit will; copies and symlinks use the same one);
2. the NuGet cache — `revit_all_main_versions_api_x64/<year>.0.0/lib/*/RevitAPI.dll`
   under `$NUGET_PACKAGES`, `~/.nuget/packages` and `/root/.nuget/packages`.

The environment is read ONLY through the `kir.env.get` door: there is one in
the package, it knows the old names, and the live service of the owner's
editing of names does not notice it. A bare `os.environ` was here — the guard
`kir/tests/test_the_environment_has_one_door.py` named all five lines by
number (55, 75, 85, 114, 130) the same hour the file landed on disk.

A directory named "2026" is NOT proof of the version: the version is read
from metadata by the runner itself (`CompilerConformance.Tests/Program.cs`),
and it is the one that refuses if identity disagrees with the file name. Here
only the EXISTENCE of both assemblies of the pair is checked.

Run as an instrument:

    python tools/revit_refs.py            # 2021…2026
    python tools/revit_refs.py 2023 2026
"""
from __future__ import annotations

from pathlib import Path
import sys

from kir import env
from kir.registry_base import REVIT_VERSIONS

#: The pair must be complete: the compiler will not accept RevitAPI without
#: RevitAPIUI (`Compiler.LoadReferences` throws "RevitAPIUI reference is missing").
REQUIRED = ("RevitAPI", "RevitAPIUI")
NUGET_PACKAGE = "revit_all_main_versions_api_x64"
#: 🔴 13.09.2026. This used to be a SECOND table of years written out by hand.
#: The values agreed with the registry, so nothing was visibly wrong — and that
#: is exactly what the guard `test_the_authority_is_not_copied` calls a copy: the
#: day the registry gains or drops a year, the instrument keeps compiling against
#: the old set and reports success about versions nobody supports any more.
#: The owner of the list is `kir.registry_base.REVIT_VERSIONS`.
ALL_VERSIONS = REVIT_VERSIONS

#: Framework references. net48 for 2021-2024, net8.0 for 2025-2026 — exactly
#: the same split as in the connector's `Directory.Build.props`.
LEGACY_MAX_VERSION = 2024
NET48_DEFAULT = ("microsoft.netframework.referenceassemblies.net48/1.0.3/"
                 "build/.NETFramework/v4.8")
NET8_GLOB = "packs/Microsoft.NETCore.App.Ref/*/ref/net8.0"


class ReferencesUnavailable(RuntimeError):
    """No references. The message must list where it searched."""


def _nuget_roots() -> list[Path]:
    roots, seen = [], set()
    for candidate in (env.get("NUGET_PACKAGES"),
                      str(Path.home() / ".nuget/packages"),
                      "/root/.nuget/packages"):
        if not candidate:
            continue
        path = Path(candidate)
        if str(path) not in seen:
            seen.add(str(path))
            roots.append(path)
    return roots


def _pair(directory: Path) -> dict[str, Path] | None:
    found = {name: directory / (name + ".dll") for name in REQUIRED}
    return found if all(path.is_file() for path in found.values()) else None


def searched_places(version: str) -> list[str]:
    """All the places the instrument looked. Printed in the refusal reason."""
    places = []
    configured = env.get("KIR_TEST_REVIT_REFS_ROOT")
    places.append(f"KIR_TEST_REVIT_REFS_ROOT={configured or '(не задан)'}"
                  + (f" -> {Path(configured) / version}" if configured else ""))
    for root in _nuget_roots():
        places.append(str(root / NUGET_PACKAGE / f"{version}.0.0" / "lib" / "*"))
    return places


def find_version(version: str) -> tuple[dict[str, Path], str] | None:
    """A pair of assemblies for one version and a NAMED source, or None."""
    configured = env.get("KIR_TEST_REVIT_REFS_ROOT")
    if configured:
        pair = _pair(Path(configured) / version)
        if pair is not None:
            return pair, "KIR_TEST_REVIT_REFS_ROOT"
    for root in _nuget_roots():
        base = root / NUGET_PACKAGE / f"{version}.0.0" / "lib"
        if not base.is_dir():
            continue
        for directory in sorted(base.iterdir()):
            pair = _pair(directory)
            if pair is not None:
                return pair, str(directory)
    return None


def discover(versions=ALL_VERSIONS) -> dict[str, tuple[dict[str, Path], str]]:
    """What was found, by version. What was not found is simply absent — no silent lying."""
    found = {}
    for version in versions:
        result = find_version(version)
        if result is not None:
            found[version] = result
    return found


def framework_references(version: str) -> Path:
    """The framework (mscorlib / System.Runtime) for the version's target platform."""
    legacy = int(version) <= LEGACY_MAX_VERSION
    override = env.get("KIR_TEST_NET48_REFS" if legacy else "KIR_TEST_NET8_REFS")
    if override:
        path = Path(override)
        if not path.is_dir():
            raise ReferencesUnavailable(
                f"заданный каркас не существует: {path} "
                f"({'KIR_TEST_NET48_REFS' if legacy else 'KIR_TEST_NET8_REFS'})")
        return path
    if legacy:
        for root in _nuget_roots():
            path = root / NET48_DEFAULT
            if (path / "mscorlib.dll").is_file():
                return path
        raise ReferencesUnavailable(
            "нет каркаса net48; искал " + ", ".join(str(r / NET48_DEFAULT) for r in _nuget_roots())
            + "; задать KIR_TEST_NET48_REFS")
    for base in (env.get("DOTNET_ROOT"), "/usr/share/dotnet", "/usr/lib/dotnet"):
        if not base:
            continue
        packs = sorted(Path(base).glob(NET8_GLOB))
        if packs:
            return packs[-1]
    raise ReferencesUnavailable(
        "нет каркаса net8.0; искал <DOTNET_ROOT|/usr/share/dotnet|/usr/lib/dotnet>/"
        + NET8_GLOB + "; задать KIR_TEST_NET8_REFS")


def require(versions) -> dict[str, tuple[dict[str, Path], str]]:
    """Find, or REFUSE with a reason and a list of places. No silent skip."""
    versions = tuple(versions)
    found = discover(versions)
    missing = [version for version in versions if version not in found]
    if missing:
        lines = [f"эталонных сборок Revit нет для: {', '.join(missing)}"]
        for version in missing:
            lines.append(f"  {version}: искал " + " | ".join(searched_places(version)))
        lines.append("  ожидалась ПАРА " + " + ".join(name + ".dll" for name in REQUIRED))
        raise ReferencesUnavailable("\n".join(lines))
    return found


def describe(versions=ALL_VERSIONS) -> str:
    """One line per version: present/absent and FROM WHERE."""
    rows = []
    for version in versions:
        result = find_version(version)
        rows.append(f"{version} {'✓' if result else '✗'}"
                    + (f" ({result[1]})" if result else ""))
    return "эталоны: " + "  ".join(rows)


def main(argv) -> int:
    versions = tuple(argv[1:]) or ALL_VERSIONS
    unknown = [v for v in versions if v not in ALL_VERSIONS]
    if unknown:
        print("неизвестные версии: " + ", ".join(unknown), file=sys.stderr)
        return 2
    print(describe(versions))
    found = discover(versions)
    for version in versions:
        if version not in found:
            print(f"  {version}: искал " + " | ".join(searched_places(version)))
    for version in versions:
        try:
            print(f"  каркас {version}: {framework_references(version)}")
        except ReferencesUnavailable as error:
            print(f"  каркас {version}: НЕТ — {error}")
    return 0 if len(found) == len(versions) else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
