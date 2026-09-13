"""Read-only CLI over saved-project clash analysis, not native BIM acceptance."""
from __future__ import annotations

import json
import math
import sys


def register(project_sub):
    parser = project_sub.add_parser(
        "clash-report", help="отчёт по телам сохранённого проекта, без изменения проекта")
    parser.add_argument("database", help="существующий ProjectStore SQLite, не JSON folded-tree")
    parser.add_argument("--revision", metavar="ID", help="точная сохранённая ревизия; по умолчанию head")
    parser.add_argument("--exact", action="store_true", help="запросить точную фазу; её ограничения остаются в отчёте")
    parser.add_argument("--clearance-mm", default="0", metavar="N",
                        help="конечный неотрицательный зазор в мм; 0 — требование зазора не задано")
    parser.set_defaults(func=run)


def _failed(code: str, error=None):
    # Exception classes identify the failed boundary without serializing source,
    # arbitrary exception objects, or an incomplete success report.
    payload = {"report_obtained": False, "read_only": True,
               "error": {"code": code}, "native_execution": "not_run"}
    if error is not None:
        payload["error"]["type"] = type(error).__name__
    print(json.dumps(payload, ensure_ascii=True, allow_nan=False))
    from kir.__main__ import NOT_DONE  # the CLI exit contract has one owner; deferred to avoid the cycle
    return NOT_DONE


def run(args) -> int:
    try:
        if isinstance(args.clearance_mm, bool):
            raise ValueError("not a number")
        clearance = float(args.clearance_mm)
        if not math.isfinite(clearance) or clearance < 0:
            raise ValueError("not a finite nonnegative length")
    except (ValueError, TypeError, OverflowError):
        print("invalid_clearance_mm: нужен конечный зазор >= 0 мм", file=sys.stderr)
        return _failed("invalid_clearance_mm")

    from kir.project_store import ProjectStore, ProjectStoreError

    try:
        store = ProjectStore.open(args.database, readonly=True)
    except (OSError, ValueError, ProjectStoreError) as error:
        return _failed("project_store_unavailable", error)
    if args.revision is not None:
        try:
            store.get(args.revision)
        except (OSError, ValueError, ProjectStoreError) as error:
            return _failed("revision_unavailable", error)

    from kir.clash.project_analysis import analyze_project

    try:
        report = analyze_project(store, revision_id=args.revision, exact=args.exact,
                                 tolerance_policy={"clearance_mm": clearance})
        # Preserve the existing report and its denominators/limits verbatim.
        encoded = json.dumps(report.to_dict(), ensure_ascii=True, allow_nan=False)
    except Exception as error:  # CLI boundary: a failed analysis is never an empty green report
        return _failed("clash_report_unavailable", error)
    print(encoded)
    # 🔴 THE DENOMINATORS GO ON THE SCREEN, NOT ONLY INTO THE JSON (13.09.2026).
    # Salvaged from the discarded second clash verb of the plan-015 patch: a
    # reader who does not parse the JSON cannot tell "no findings" from "almost
    # nothing was looked at". Both ratios come from the report itself.
    print(f"НАЙДЕНО {len(report.findings)}; пар сравнено {report.pairs_compared} "
          f"из {report.pairs_possible}; тел с геометрией "
          f"{report.bodies_with_geometry} из {report.bodies_declared}.",
          file=sys.stderr)
    if not report.search_complete:
        # A partial search that keeps quiet reads as "nothing found".
        print("🔴 ПОИСК НЕПОЛНЫЙ — что именно не осмотрено, названо в analysis_limits.",
              file=sys.stderr)
    print("Отчёт получен: код 0 не означает отсутствия коллизий. "
          "Смотри findings, not_evaluated и analysis_limits; проект и Revit не изменены.",
          file=sys.stderr)
    from kir.__main__ import ANSWERED
    return ANSWERED
