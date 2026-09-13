"""HOW MANY KIR TESTS KNOW THE HOST'S TREE — A NUMBER THAT DID NOT EXIST.

🔴 WHY (01.09.2026, the owner's question "am I running someone else's
code without knowing it").

The KIR↔product boundary is guarded by a number, and it is correct:
`test_kir_boundary_to_the_product_is_a_closed_list` holds **zero**
TOP-LEVEL product imports from `kir/`. But an import is not the only
way to know a foreign tree. A test can know it BY PATH:
`/opt/kukai-rebuild1`, `KIR_HOST_ROOT`, `backend/…` — and then it is
environment-dependent in exactly the same way, with no number tracking
it.

Measured 01.09 by grep, before this instrument: product imports **0**,
files with path knowledge — **25**. The first is guarded; nobody counts
the second.

WHAT THIS INSTRUMENT SAYS AND WHAT IT DOES NOT SAY

  * it says: how many test files know the host's tree, by which METHOD
    (a hardcoded path · a variable · reading a port), and whether the
    file ships in the package;
  * it does NOT say whether this is a defect. Some such tests are
    legitimate: a seam claim about BOTH trees must DECLARE the host's
    configuration, and the canon explicitly allows this. The instrument
    separates "declares via a variable/port" from "hardcoded as a
    literal" — the latter is exactly a machine-local path inside an
    environment-agnostic package;
  * it does NOT go into the host's tree and does not check whether it
    exists: the subject here is the KIR SOURCE, not the machine.

    python3.12 tools/host_path_census.py
    python3.12 tools/host_path_census.py --поимённо
"""
from __future__ import annotations

import argparse
import ast
import pathlib
import re
import sys
import tomllib

ROOT = pathlib.Path(__file__).resolve().parent.parent

#: The literal path to the host's tree. The list is CLOSED and named:
#: widening the mask to any `/opt/...` would mean pulling in foreign
#: roots the package makes no promises about.
_ЛИТЕРАЛ = re.compile(r"/opt/kukai-rebuild1|/opt/kukai\b")
#: Knowledge via DECLARATION — an environment variable or a port. This
#: is a legitimate method.
_ОБЪЯВЛЕНО = re.compile(r"KIR_HOST_ROOT|KUKAI_HOST_ROOT|ports\.(ask|ENTRY_POINTS|INSTALL_DATA)")


def _поставляется() -> set[str]:
    """Files that land in the wheel. Read from the FILE, not from memory."""
    keep = ROOT / "pyproject.toml"
    if not keep.is_file():
        return set()
    return set(tomllib.loads(keep.read_text(encoding="utf-8"))["tool"]["kir"]["wheel"]["keep"])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--поимённо", action="store_true", dest="поимённо")
    args = ap.parse_args()

    keep = _поставляется()
    литерал, объявлено, оба, импорт_продукта = [], [], [], []
    всего = 0
    неразобрано = []

    for p in sorted((ROOT / "kir").rglob("*.py")):
        if "__pycache__" in p.parts:
            continue
        тест = "tests" in p.parts or p.name.startswith("test_")
        if not тест:
            continue
        всего += 1
        rel = str(p.relative_to(ROOT))
        text = p.read_text(encoding="utf-8", errors="replace")
        л, о = bool(_ЛИТЕРАЛ.search(text)), bool(_ОБЪЯВЛЕНО.search(text))
        if л and о:
            оба.append(rel)
        elif л:
            литерал.append(rel)
        elif о:
            объявлено.append(rel)
        try:
            tree = ast.parse(text)
        except SyntaxError as e:
            неразобрано.append(f"{rel}: {e}")
            continue
        for n in ast.walk(tree):
            mods = []
            if isinstance(n, ast.Import):
                mods = [a.name for a in n.names]
            elif isinstance(n, ast.ImportFrom) and n.module:
                mods = [n.module]
            if any(m == "kukai" or m.startswith("kukai.") for m in mods):
                импорт_продукта.append(f"{rel}:{n.lineno}")

    знают = len(литерал) + len(объявлено) + len(оба)
    print(f"тестовых файлов в пакете                : {всего}")
    print(f"знают дерево хозяина                    : {знают}")
    print(f"  ТОЛЬКО через объявление (законно)     : {len(объявлено)}")
    print(f"  объявляют И несут литерал             : {len(оба)}")
    print(f"  🔴 ТОЛЬКО литералом, без объявления   : {len(литерал)}")
    print(f"ИМПОРТИРУЮТ пакет продукта              : {len(импорт_продукта)}"
          f"   <- это стережёт отдельный храповик")
    в_поставке = [f for f in литерал + оба if f in keep]
    print(f"🔴 из знающих ХОЗЯИНА едет в колесе      : {len(в_поставке)}"
          f"{' — ' + ', '.join(в_поставке) if в_поставке else ''}")
    if неразобрано:
        print(f"🔴 не разобралось (это НЕ ноль)          : {len(неразобрано)}")
        for s in неразобрано:
            print(f"   {s}")

    if args.поимённо:
        for имя, гр in (("ТОЛЬКО ЛИТЕРАЛОМ", литерал), ("ОБА", оба),
                        ("ОБЪЯВЛЕНО", объявлено)):
            print(f"\n{имя} ({len(гр)}):")
            for f in гр:
                print(f"   {f}")
        if импорт_продукта:
            print(f"\nИМПОРТ ПРОДУКТА ({len(импорт_продукта)}):")
            for f in импорт_продукта:
                print(f"   {f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
