"""RELEASE GATE: build the wheel FROM THE TREE and run its self-test in a clean venv.

    python3.12 tools/release_gate.py                 # build and run
    python3.12 tools/release_gate.py --keep <dir>    # keep the venv for inspection

🔴 WHY. Before 01.09.2026, what people install and what we measure were
DIFFERENT trees: the publish was assembled by a manual UPLOAD, and every
"stranger's road" number was taken from the wheel built from the tree, not
from the artifact. That day's measurement:

    the PyPI artifact           14 of 24 canon commands failed
    tests in the artifact       0
    the suite manifest          did not ship at all

This gate answers exactly one question and does not pretend to answer more:
**can a wheel built FROM THIS TREE, installed where there is neither KUKAI,
nor ports, nor a corpus, run its own test suite?**

WHAT IT DOES NOT DO, AND THIS IS NAMED:
  * it does NOT publish and does NOT touch the network (other than installing
    the wheel's dependencies);
  * it does NOT check behavior in Revit: the 6/6 gate requires a host port
    that a stranger does NOT HAVE BY CONSTRUCTION;
  * it does NOT compare the tree against the published branch — that is a
    separate divergence instrument, and it lives in the audit (machine-local:
    `/opt/kir-audit/stranger/published_gate.py`), not in the package: a path
    into a foreign tree inside the repository is exactly that second boundary
    channel.

THE RETURN CODE IS SPLIT BY MEANING, like `kir.selftest`'s:
    0  the gate RAN, everything green
    1  the gate RAN, there is red
    2  the gate DID NOT RUN (the build, install, or cleanliness check failed)
"""
from __future__ import annotations

import argparse
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile
import zipfile

REPO = pathlib.Path(__file__).resolve().parent.parent

PASSED, FAILED, NOT_RUN = 0, 1, 2


def _run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    """A run with the return code WITHOUT a pipe: a pipe would return `tail`'s
    code, not ours."""
    return subprocess.run(cmd, capture_output=True, text=True, timeout=3600, **kw)



_IGNORE_EVERYWHERE = shutil.ignore_patterns(".git", "*.egg-info", "__pycache__",
                                            ".pytest_cache", ".work", ".venv",
                                            "venv", "node_modules")


def _ignore_build_output(dir_: str, names: list) -> set:
    """`build/` and `dist/` are cut ONLY at the root of the tree.

    🔴 The pattern `ignore_patterns("dist")` cut any directory with that name —
    and along with the build output, a packaged asset directory went with it
    (07.09.2026: `kir/app/viewer/dist`, the browser window's bundle, which the
    wheel then shipped without; found by the install instrument
    `test_the_final_result_holds_from_an_installed_package.py`). The window was
    removed on 13.09.2026 and the package carries no asset directory today, but
    the rule stays where it is: the next `dist` inside the package must not be
    cut by a pattern meant for the build output at the root.
    """
    ignored = set(_IGNORE_EVERYWHERE(dir_, names))
    if pathlib.Path(dir_).resolve() == REPO.resolve():
        ignored |= {n for n in names if n in ("build", "dist")}
    return ignored

def build_wheel(outdir: pathlib.Path) -> tuple[pathlib.Path | None, str]:
    """Build the sdist and the wheel FROM IT.

    🔴 EXACTLY VIA THE SDIST. `build --wheel` builds from the tree and
    therefore does NOT SEE the hole already stumbled on: a file not named in
    `MANIFEST.in` is present in the tree and absent from the source
    distribution, and `pip install --no-binary` goes exactly through the
    source distribution.
    """
    src = tempfile.mkdtemp(prefix="kir-src-")
    # A copy of the tree: the build writes `build/` and `*.egg-info`, and
    # `build/` in this repository IS TRACKED — running the gate directly in
    # the tree would leave it dirty by upward of sixty files (KIR_PLAN
    # §0.1.1).
    shutil.copytree(REPO, pathlib.Path(src) / "tree", ignore=_ignore_build_output)
    p = _run([sys.executable, "-m", "build", "--outdir", str(outdir)],
             cwd=str(pathlib.Path(src) / "tree"))
    if p.returncode != 0:
        return None, ("сборка не прошла: " + (p.stderr or p.stdout)[-600:] +
                      "\n   СЛЕДУЮЩИЙ ХОД: pip install build")
    wheels = sorted(outdir.glob("*.whl"))
    if not wheels:
        return None, "сборка вернула 0, но колеса нет"
    return wheels[-1], ""


def wheel_carries_its_gate(whl: pathlib.Path) -> tuple[int, int, bool]:
    """How many suite files there are and whether there is a manifest — BY THE CONTENTS of the archive."""
    names = set(zipfile.ZipFile(whl).namelist())
    has_manifest = "kir/gate_manifest.json" in names
    if not has_manifest:
        return 0, 0, False
    man = json.loads((REPO / "kir" / "gate_manifest.json").read_text(encoding="utf-8"))
    need = man["набор"]
    got = [n for n in need if f"kir/{n}" in names]
    return len(got), len(need), True


def prove_clean(py: pathlib.Path) -> tuple[bool, str]:
    """Cleanliness is PROVEN, not declared.

    Three ways of a false "yes" are closed at once: `-I` strips `PYTHONPATH`
    and the user site, `cwd=/` removes the launch directory from `sys.path`,
    and an empty environment removes the variables we set ourselves.
    """
    #: 🔴 13.09.2026: THE TREE THIS GATE BUILDS FROM WAS NOT THE TREE IT LOOKED
    #: FOR. The check named `/opt/kir` as a literal, so on a machine whose
    #: working tree is anywhere else it could not fire. Measured: a `.pth` file
    #: in the fresh venv putting THE VERY TREE the wheel was built from on
    #: `sys.path`, and the gate still answered «чистота: True». A module that
    #: packaging forgot would then be imported from the tree and the installed
    #: self-test would be green about a package that does not carry it — the
    #: exact substitution this gate exists to refuse. `/opt/kir` is kept as a
    #: second, historical address: it is a different tree, and a stranger's
    #: machine has neither.
    trees = sorted({str(REPO), "/opt/kir"})
    probe = (
        "import json,sys,os,importlib.util as u,importlib.metadata as md,kir;"
        f"trees={trees!r};"
        "print(json.dumps({"
        "'file':kir.__file__,'ver':getattr(kir,'__version__','нет'),"
        "'want':kir._DIST,"
        "'dists':sorted(md.packages_distributions().get('kir',[])),"
        "'tree_in_path':sorted({p for p in sys.path for t in trees"
        " if p==t or p.startswith(t+'/')}),"
        "'kukai':u.find_spec('kukai') is not None,"
        "'env':[k for k in os.environ if k.startswith(('KIR_','KUKAI_'))]}))")
    p = subprocess.run([str(py), "-I", "-c", probe], capture_output=True,
                       text=True, cwd="/", env={"PATH": "/usr/bin:/bin"}, timeout=300)
    if p.returncode != 0:
        return False, f"проба не поднялась: {(p.stderr or '')[-400:]}"
    d = json.loads(p.stdout)
    bad = []
    if d["tree_in_path"]:
        bad.append(f"дерево исходников в sys.path: {d['tree_in_path']}")
    if d["kukai"]:
        bad.append("`kukai` импортируется — это НЕ чистая среда")
    if d["env"]:
        bad.append(f"переменные среды заданы: {d['env']}")
    #: 🔴 03.09.2026: prod answered «не установлен» while actually being
    #: installed — the dist-info sat under the DEAD name `kir`, while the code
    #: asks for `kir-building`. An install that cannot name itself has no
    #: right to be called "clean": the first thing asked in a bug report is
    #: the version.
    if d["dists"] != [d["want"]]:
        bad.append(f"верхний модуль `kir` объявляют {d['dists']}, "
                   f"а код спрашивает `{d['want']}`")
    if "не установлен" in d["ver"]:
        bad.append(f"версия отвечает «{d['ver']}» — установка себя не называет")
    return (not bad), (f"{d['file']} · версия {d['ver']}"
                       + ("" if not bad else " · 🔴 " + "; ".join(bad)))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="tools/release_gate.py", description=__doc__)
    ap.add_argument("--keep", metavar="ДИР",
                    help="работать в этом каталоге и не убирать его")
    args = ap.parse_args(argv)

    work = pathlib.Path(args.keep) if args.keep else pathlib.Path(
        tempfile.mkdtemp(prefix="kir-release-"))
    work.mkdir(parents=True, exist_ok=True)
    print(f"ВОРОТА РЕЛИЗА · дерево {REPO} · рабочий каталог {work}\n")

    dist = work / "dist"
    whl, why = build_wheel(dist)
    if whl is None:
        print(f"🔴 ВОРОТА НЕ СОСТОЯЛИСЬ: {why}")
        return NOT_RUN
    print(f"  колесо      {whl.name}")

    got, need, has_manifest = wheel_carries_its_gate(whl)
    if not has_manifest:
        print("🔴 ВОРОТА НЕ СОСТОЯЛИСЬ: в колесе нет `kir/gate_manifest.json` — "
              "набор ворот назвать нечем.\n"
              "   СЛЕДУЮЩИЙ ХОД: манифест обязан лежать ВНУТРИ пакета.")
        return NOT_RUN
    print(f"  набор в колесе  {got} из {need}")
    if got < need:
        print("🔴 ВОРОТА НЕ СОСТОЯЛИСЬ: колесо собрано без части своего набора "
              "(`pyproject.toml: tool.kir.wheel.keep`).")
        return NOT_RUN

    venv = work / "venv"
    if _run([sys.executable, "-m", "venv", str(venv)]).returncode != 0:
        print("🔴 ВОРОТА НЕ СОСТОЯЛИСЬ: venv не создался")
        return NOT_RUN
    pip, py = venv / "bin" / "pip", venv / "bin" / "python"
    p = _run([str(pip), "install", "-q", f"{whl}[dev]"])
    if p.returncode != 0:
        print(f"🔴 ВОРОТА НЕ СОСТОЯЛИСЬ: установка не прошла:\n{(p.stderr or p.stdout)[-600:]}")
        return NOT_RUN

    ok, said = prove_clean(py)
    print(f"  чистота     {said}")
    if not ok:
        print("🔴 ВОРОТА НЕ СОСТОЯЛИСЬ: среда не чиста — число отсюда было бы "
              "о нашей машине, а не о пакете.")
        return NOT_RUN

    print("\n— САМОТЕСТ УСТАНОВЛЕННОГО ПАКЕТА " + "—" * 40)
    proc = subprocess.run([str(py), "-I", "-m", "kir.selftest"], cwd="/",
                          env={"PATH": "/usr/bin:/bin", "HOME": str(work)})
    print("—" * 72)
    if proc.returncode == 0:
        print("ВОРОТА РЕЛИЗА: ДА — колесо из дерева прогоняет свой набор без КУКАЯ.")
        return PASSED
    if proc.returncode == 1:
        print("ВОРОТА РЕЛИЗА: НЕТ — набор прогнан и в нём есть красные.")
        return FAILED
    print(f"🔴 ВОРОТА НЕ СОСТОЯЛИСЬ: самотест вернул {proc.returncode} "
          "(не судили). Это НЕ «ноль красных».")
    return NOT_RUN


if __name__ == "__main__":
    sys.exit(main())
