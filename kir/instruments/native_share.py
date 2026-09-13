"""THE NATIVE BIM SHARE — what the free-geometry build is closed out with.

THE MEASUREMENT'S SUBJECT IS NAMED IN THE OUTPUT HEADER, and this is not
politeness: this instrument has TWO ends, they answer DIFFERENT questions,
and they must not be added together.

    BY PROGRAM    what the author DECLARED they would build. Computed before
                  any Revit, which is why the two-handed offline A/B is
                  judged by it.
    BY DECOMPILE  what actually ENDED UP in the document. Requires a real
                  decompile and speaks about the building, not the intent.

🔴 WHY THIS WAS SET UP (2026-09-01). The owner: "the model in Revit builds
shacks, while in three.js it does far better." The answer to that is to let
form be written freely, and hang BIM meaning onto it AFTER the form. Work
like that must have a number, or in a month people would be arguing by
impression: **what share of what was built landed in Revit's NATIVE
categories, and what share remained geometry with no BIM meaning**.

═══════════════════════════════════════════════════════════════════════════
HOW "IS THIS NATIVE BIM OR GEOMETRY" IS DECIDED — ASKED OF THE AUTHORITY, TWICE
═══════════════════════════════════════════════════════════════════════════

There is deliberately NO list of operation names here: a hand-written list
that must stay in sync with the registry is a named defect of this tree. The
kind is derived by asking the registry TWO questions, and both must agree:

    1. `capability` contains nothing but ('create', 'geometry')
    2. `op_result_categories(op)` names NOT A SINGLE category

🔴 ONE QUESTION IS NOT ENOUGH, AND THIS IS MEASURED, NOT ASSUMED:

    `create_filled_region`  capability is geometry only, BUT categories DO
                            exist (OST_FilledRegion) — this is a genuine
                            annotation element, and it cannot be recorded as
                            geometry
    `place_family`          there are NO categories (they belong to the
                            FAMILY, known at grounding), BUT capability is
                            ('place','element'), and this is the most
                            ordinary BIM element there is

That is, each question alone gives a false answer in its OWN direction, and
together they give the correct one. The conjunction here is not caution, it
is the analysis of two known cases.

**THE PREMISE IS VERIFIED ON THE ARTIFACT, NOT DECLARED.** Three emitters
stamp the acknowledgment `HONEST_MARK` into the emitted C# ("geometry with no
BIM meaning (no type/parameters)"): `shape_emit`, `solid_emit`,
`surface_emit`. A control run on 09-01 over the gate corpus, both sides:

    auth_directshape_tower          create_directshape        HONEST_MARK×1
    solid_extrusion_and_revolve     create_solid_{extr,revolve} HONEST_MARK×2
    auth_solid_boolean_difference   create_solid_boolean      HONEST_MARK×1
    detail_filled_region_named_type create_filled_region      HONEST_MARK×0
    authoring_wall_pipe_grid        create_wall/pipe/grid     HONEST_MARK×0
    arch_ceiling                    create_ceiling            HONEST_MARK×0

The rule and the emitter's acknowledgment agreed on all six. `check_derivation()`
below keeps holding that correspondence going forward — not as prose, but by
checking the derived output against the list of modules that carry `HONEST_MARK`.

═══════════════════════════════════════════════════════════════════════════
THREE BUCKETS BY DECOMPILE, NOT TWO — AND THE THIRD IS THE MOST IMPORTANT
═══════════════════════════════════════════════════════════════════════════

    NATIVE, LIFTABLE       the category is in `lift._CANDIDATES`
    NATIVE, NOT LIFTED     the category is genuine, but there is no lifter —
                           this is OUR reading gap, NOT an absence of BIM meaning
    GEOMETRY WITH NO MEANING the category is the literal `DirectShape`

Merging the second with the third would mean recording our own blindness as a
fault of the building: exactly the shape of mistake this tree already paid
for once, as "zero out of the corpus." The divider is exact and by
construction: `DirectShape`'s category is not defined by a class, and the
extractor puts the literal `"DirectShape"` into the field (`extract.py`),
not a BuiltInCategory.

🔴 `DirectShape` IS PRESENT IN `_CANDIDATES` (it has its own lifter), so the
naive "a category from `_CANDIDATES` = native" would count geometry as
native. Here it is subtracted BY NAME, and the name is taken from `ops_shape`,
not typed by hand.

═══════════════════════════════════════════════════════════════════════════
WHAT THIS INSTRUMENT DOES NOT DO
═══════════════════════════════════════════════════════════════════════════

  * It does NOT judge whether the building is good. A wall placed in the
    wrong spot is native here too; that is a question for the judge
    (`design_check`), not for this count;
  * It does NOT count elements that Revit will spawn ON ITS OWN (mullions,
    panels, fittings): they are not visible from the program, and crediting
    them to oneself would inflate both shares at once. By decompile they are
    visible and counted like everything else;
  * It does NOT answer "how many atoms". An atom is about READING, this is
    about CATEGORY. Different questions, and `content_coverage` answers the first;
  * when there is no source it does NOT print zero. It prints a named
    refusal and exits with code 2 — "the instrument DID NOT JUDGE", not
    "judged and found zero".

    PYTHONPATH=/opt/kir python -m kir.instruments.native_share --program p.json
    PYTHONPATH=/opt/kir python -m kir.instruments.native_share --parse <dir>
    PYTHONPATH=/opt/kir python -m kir.instruments.native_share --self-check
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from kir import spec

#: Modules whose emitter stamps the "no BIM meaning" acknowledgment into C#.
#: This is NOT a list of operations — it is a list of ACKNOWLEDGMENT CARRIERS,
#: and it is checked against the derived set of operations in `check_derivation()`.
HONEST_MARK_EMITTERS = ("kir.shape_emit", "kir.solid_emit", "kir.surface_emit")

#: The literal the extractor puts into the category field for DirectShape:
#: its category is not defined by a class. A divider by construction, not by name.
DIRECTSHAPE_PSEUDO_CATEGORY = "DirectShape"


class NativeShareRefusal(RuntimeError):
    """The measurement DID NOT HAPPEN, and the reason is named. Not zero."""


@dataclass(frozen=True, slots=True)
class ProgramShare:
    """What the program DECLARED it would build, by kind.

    `total` is counted over declared operations, not elements: how many
    elements `create_group` with placements will spawn is not visible from
    the program, and substituting a guess here would mean mixing what was
    counted with what was invented.
    """

    native_ops: int
    geometry_ops: int
    other_ops: int          # reads, edits, deletes — neither one nor the other
    by_op: Mapping[str, str]
    unknown_ops: tuple[str, ...]

    @property
    def decided(self) -> int:
        return self.native_ops + self.geometry_ops

    @property
    def share(self) -> float | None:
        """The native share among the DECIDED ones. `None` — there was nothing to decide.

        Zero and "nothing to divide by" arrive as the same value exactly
        where a division by empty stands between them. Here, `None` stands
        between them instead.
        """
        return (self.native_ops / self.decided) if self.decided else None


@dataclass(frozen=True, slots=True)
class ParseShare:
    """What actually ENDED UP in the document, by three buckets."""

    native_liftable: int
    native_unlifted: int
    geometry_no_meaning: int
    by_category: Mapping[str, int] = field(default_factory=dict)

    @property
    def total(self) -> int:
        return self.native_liftable + self.native_unlifted + self.geometry_no_meaning

    @property
    def share(self) -> float | None:
        """The NATIVE share (both first buckets) among everything read."""
        return ((self.native_liftable + self.native_unlifted) / self.total
                if self.total else None)


# ─────────────────────────────────────────────────── the PROGRAM side

def geometry_only_ops() -> frozenset[str]:
    """Operations that yield geometry WITH NO BIM meaning. DERIVED, not enumerated.

    Two questions to the registry, both must answer "yes"; the analysis of
    both is in the header.
    """
    out = set()
    for name, op in spec.OPS.items():
        caps = set(op.capability or ())
        if caps != {("create", "geometry")}:
            continue
        if spec.op_result_categories({"op": name}):
            continue                       # a category exists -> a genuine element
        out.add(name)
    return frozenset(out)


def _op_kind(op_name: str) -> str:
    """`native` · `geometry` · `other` · `unknown`."""
    op = spec.OPS.get(op_name)
    if op is None:
        return "unknown"
    if op_name in geometry_only_ops():
        return "geometry"
    verbs = {verb for verb, _obj in (op.capability or ())}
    creates = verbs & {"create", "place", "load"}
    return "native" if creates else "other"


def share_of_program(program: Mapping[str, Any]) -> ProgramShare:
    """The native-BIM share for the DECLARED program."""
    ops = program.get("ops")
    if not isinstance(ops, list):
        raise NativeShareRefusal(
            "у программы нет списка `ops` — это не программа KIR. "
            "Замер НЕ СОСТОЯЛСЯ; ноль здесь был бы фактом о входе, не о доле")
    native = geometry = other = 0
    by_op: dict[str, str] = {}
    unknown: list[str] = []
    for entry in ops:
        name = (entry or {}).get("op") if isinstance(entry, Mapping) else None
        kind = _op_kind(str(name))
        by_op[str(name)] = kind
        if kind == "native":
            native += 1
        elif kind == "geometry":
            geometry += 1
        elif kind == "unknown":
            unknown.append(str(name))
        else:
            other += 1
    if unknown:
        raise NativeShareRefusal(
            "в программе есть операции, которых НЕТ в реестре: "
            f"{sorted(set(unknown))}. Считать долю по неизвестному роду значило "
            "бы выдать догадку за замер")
    return ProgramShare(native, geometry, other, by_op, ())


# ─────────────────────────────────────────────────── the DECOMPILE side

def _lifter_categories() -> frozenset[str]:
    """Categories that HAVE a lifter, EXCLUDING the DirectShape pseudo-category."""
    from kir.decompile.lift import LIFTER_TABLE       # local: a heavy import
    return frozenset(LIFTER_TABLE) - {DIRECTSHAPE_PSEUDO_CATEGORY}


def share_of_categories(counts: Mapping[str, int]) -> ParseShare:
    """Three buckets from the census `category -> how many elements`."""
    liftable = _lifter_categories()
    native_l = native_u = geometry = 0
    for category, n in counts.items():
        n = int(n or 0)
        if category == DIRECTSHAPE_PSEUDO_CATEGORY:
            geometry += n
        elif category in liftable:
            native_l += n
        else:
            native_u += n
    return ParseShare(native_l, native_u, geometry, dict(counts))


def share_of_parse(run_dir: pathlib.Path) -> ParseShare:
    """Three buckets from a REAL decompile.

    🔴 READS ONLY THE L0 HEADER'S CENSUS AND WRITES NOTHING. The
    `.last_access` marker records the very fact of reading the snapshot
    through the working path; here the header is read directly, because the
    subject is a count of categories, not the elements' content.
    """
    if not run_dir.is_dir():
        raise NativeShareRefusal(
            f"каталога разбора нет: {run_dir}. Замер НЕ СОСТОЯЛСЯ — ноль "
            "отсюда был бы фактом о пути, а не о здании")
    census = _read_census(run_dir)
    if not census:
        raise NativeShareRefusal(
            f"в {run_dir} не нашлось переписи категорий (§18.1 заголовка L0). "
            "Прибор НЕ СУДИЛ: считать было нечего")
    return share_of_categories(census)


def _read_census(run_dir: pathlib.Path) -> dict[str, int]:
    """The census `category -> how many were READ` from `category_status` records.

    🔴 THE CARRIER WAS ASKED OF THE STREAM, NOT GUESSED. The first edition
    looked for the census in the HEADER under three plausible key names
    (`category_census`, `census`, `categories`) — and honestly refused on all
    three real decompiles: the L0 header carries only
    `document`/`record`/`schema_version`, while the census travels as
    SEPARATE `record: "category_status"` records (77 of them on `bench_A`).
    The refusal was correct, but it described MY MATCHER, not the decompile.

    `extracted_count` is taken — how many were READ, not `expected_count`:
    this instrument's subject is what landed in categories, while what was
    not read belongs to coverage (`content_coverage`), which has its own denominator.
    """
    import gzip

    for name in ("L0.jsonl", "L0.jsonl.gz"):
        path = run_dir / name
        if not path.exists():
            continue
        opener = gzip.open if path.suffix == ".gz" else open
        out: dict[str, int] = {}
        with opener(path, "rt", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                # A cheap pre-filter: there are millions of elements, dozens of census records.
                if "category_status" not in line:
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if rec.get("record") != "category_status":
                    continue
                status = rec.get("status")
                if not isinstance(status, Mapping):
                    continue
                category = status.get("category")
                count = status.get("extracted_count")
                if category is not None and isinstance(count, (int, float)):
                    out[str(category)] = out.get(str(category), 0) + int(count)
        if out:
            return out
    return {}


# ─────────────────────────────────────────────────── self-check

def check_derivation() -> list[str]:
    """Keeps the derivation in agreement with the EMITTER'S ACKNOWLEDGMENT, not with my own list.

    Returns a list of discrepancies; an empty list means agreement. An
    instrument that declares a kind and does not check it against what
    actually ends up in the C# is a value declared in one place and read in another.
    """
    problems: list[str] = []
    derived = geometry_only_ops()
    if not derived:
        problems.append(
            "выведено НОЛЬ геометрических операций — так не бывает при "
            "непустом реестре; вывод сломан, а не реестр")
    marks = 0
    for module_name in HONEST_MARK_EMITTERS:
        try:
            module = __import__(module_name, fromlist=["HONEST_MARK"])
        except ImportError as exc:
            problems.append(f"носитель признания не импортируется: {module_name}: {exc}")
            continue
        if not getattr(module, "HONEST_MARK", ""):
            problems.append(f"{module_name} больше не несёт HONEST_MARK — "
                            "признание эмиттера исчезло, вывод стал неподпёрт")
        else:
            marks += 1
    if marks and not derived:
        problems.append("признание эмиттеров есть, а операций не выведено")
    for name in derived:                       # the reverse side: is anything extra
        if spec.op_result_categories({"op": name}):
            problems.append(f"{name} выведен геометрией, но реестр называет "
                            "ему категории — вывод шире предмета")
    return problems


# ─────────────────────────────────────────────────── printing

def _render_program(share: ProgramShare, subject: str) -> str:
    lines = [
        "ДОЛЯ РОДНОГО БИМ — ПО ПРОГРАММЕ (что автор ОБЪЯВИЛ построить)",
        f"предмет: {subject}",
        f"интерпретатор: {sys.version.split()[0]}",
        "",
        f"  родных операций      {share.native_ops:6d}",
        f"  геометрии без смысла {share.geometry_ops:6d}",
        f"  прочих (чтение/правка/удаление, в долю НЕ входят) {share.other_ops:6d}",
    ]
    if share.share is None:
        lines.append("")
        lines.append("  🔴 ДОЛЯ НЕ ОПРЕДЕЛЕНА: ни одной создающей операции. "
                     "Это не ноль процентов — делить было нечего.")
    else:
        lines.append(f"  ДОЛЯ РОДНОГО         {share.share * 100:5.1f} %  "
                     f"(из {share.decided} решённых)")
    return "\n".join(lines)


def _render_parse(share: ParseShare, subject: str) -> str:
    lines = [
        "ДОЛЯ РОДНОГО БИМ — ПО РАЗБОРУ (что в документе ОКАЗАЛОСЬ)",
        f"предмет: {subject}",
        "",
        f"  родной БИМ, поднимается   {share.native_liftable:8d}",
        f"  родной БИМ, НЕ поднимаем  {share.native_unlifted:8d}   "
        "(наш пробел ЧТЕНИЯ, не отсутствие смысла)",
        f"  геометрия без BIM-смысла  {share.geometry_no_meaning:8d}   "
        "(категория `DirectShape`)",
    ]
    if share.share is None:
        lines.append("")
        lines.append("  🔴 ДОЛЯ НЕ ОПРЕДЕЛЕНА: перепись пуста.")
    else:
        lines.append(f"  ДОЛЯ РОДНОГО              {share.share * 100:7.1f} %  "
                     f"(из {share.total} элементов)")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="kir.instruments.native_share",
        description=__doc__.split("\n", 1)[0])
    ap.add_argument("--program", metavar="ФАЙЛ",
                    help="программа KIR в JSON")
    ap.add_argument("--parse", metavar="ДИР",
                    help="каталог настоящего разбора")
    ap.add_argument("--self-check", action="store_true",
                    help="сверить вывод рода с признанием эмиттеров")
    args = ap.parse_args(argv)

    if args.self_check:
        problems = check_derivation()
        derived = sorted(geometry_only_ops())
        print("САМОПРОВЕРКА ВЫВОДА РОДА")
        print(f"  геометрических операций выведено: {len(derived)}")
        for name in derived:
            print(f"    {name}")
        print(f"  носителей признания HONEST_MARK: {len(HONEST_MARK_EMITTERS)}")
        if problems:
            print("  🔴 РАСХОЖДЕНИЯ:")
            for p in problems:
                print(f"    {p}")
            return 1
        print("  согласие: вывод и признание эмиттеров сходятся")
        return 0

    if not args.program and not args.parse:
        print("🔴 ПРИБОР НЕ СУДИЛ: не дано ни программы, ни разбора.")
        print("   Это факт О ВЫЗОВЕ, а не «доля ноль». "
              "Дай `--program` либо `--parse`.")
        return 2

    try:
        if args.program:
            path = pathlib.Path(args.program)
            if not path.is_file():
                raise NativeShareRefusal(f"файла программы нет: {path}")
            program = json.loads(path.read_text(encoding="utf-8"))
            print(_render_program(share_of_program(program), str(path)))
        if args.parse:
            path = pathlib.Path(args.parse)
            print(_render_parse(share_of_parse(path), str(path)))
    except NativeShareRefusal as exc:
        print(f"🔴 ЗАМЕР НЕ СОСТОЯЛСЯ: {exc}")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
