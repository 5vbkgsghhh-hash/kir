# -*- coding: utf-8 -*-
"""FINAL RESULT of the mandate, line 2: the round trip of an EXISTING capture.

    python examples/final_result_capture_walkthrough.py --root NEW_DIR
    python examples/final_result_capture_walkthrough.py --root NEW_DIR --capture DIR

Mandate `.work/stabilize-SujqrS/OFFLINE_KIR_MARATHON_RU.md`, section "Final
result and the boundary of honesty," requires verbatim: "A separate existing
capture goes through the round trip with explicit losses."

🔴 THE BUILDING HERE IS REAL, NOT SYNTHETIC. By default this takes the run of
corpus `bench_A` (4,223 elements of a decompiled Revit project). The synthetic
demonstration (`capture_api demo`) remains a FALLBACK path for a machine
without the corpus, and in that case it is NAMED in the response by the
`corpus: synthetic` field: substituting a real building with a made-up one and
staying silent about it would mean measuring the wrong thing.

🔴 EACH STEP IS A SEPARATE PROCESS. "Survived the process closing" is a
property of DISK, not of memory: an in-process loop stays just as green even
with a completely lost save, because the nodes remained in a live object.
Nothing but the directory is left between steps.

🔴 LOSSES ARE NAMED BY ADDRESS, NOT BY STRING LENGTH. The `ledger` prints four
states as SUMS (`represented | approximate | source_data | unknown`) and each
loss with its `element_id`, `unique_id`, field name, state, and carrier.
"N characters lost" does not count as an answer here.

🔴 THE CORPUS IS ONLY READ. The scenario writes into ITS OWN directory; the
sha256 of every file of the source run is taken before and after and is
required to match. An attempt to save inside the corpus is a separate
negative control, and it is required to fail BY NAME
(`target_inside_capture`), not by filesystem permissions.

🔴 WHAT IS NOT HERE, AND THIS IS PRINTED AT EVERY STEP. Revit is not launched,
there is no native execution, no observed BIM model, no real LLM
(`real_llm_calls: 0`). Not a single green step CLOSES live acceptance: the
fact that the C# compiled does not mean it ran in Revit.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

#: Default corpus run. The same one behind the ledger numbers in
#: `docs/CAPTURE_OFFLINE_EDIT_RU.md` and the pins in `kir/decompile/tests/`.
CORPUS = Path(os.environ.get(
    "KIR_CAPTURE_CORPUS",
    "/opt/kukai-rebuild1/backend/backend/data/decompile/bench_A"))

#: Addresses of the real building. They are a property of the BUILDING, not a
#: convenience of the scenario: door 286533 hangs on wall 286530, floor 286551
#: carries an opening ring. The values (`offset_mm`, the ring itself) are NOT
#: typed by hand: they are read at step 3 from the `read` response, and
#: `before` is taken from the same place.
CORPUS_DOOR, CORPUS_FLOOR = "286533", "286551"

NOT_RUN = {"native_execution": "not_run", "live_model_observed": False,
           "revit_started": False, "real_llm_calls": 0,
           "whole_project_acceptance": "not_established",
           "lossless_reconstruction": "not_claimed"}

EXIT_OK, EXIT_BROKEN, EXIT_REFUSED = 0, 1, 2


class StepFailed(RuntimeError):
    """A step did not hold. Carries a tree address so red has an owner."""

    def __init__(self, address: str, detail: str):
        super().__init__(f"{address}: {detail}")
        self.address, self.detail = address, detail


def _row(step, instrument, numbers, proved, *, red=None, not_run=None):
    """The honesty row for one step: what is proved by a NUMBER and what was NOT run."""
    return {"step": step, "instrument": instrument, "numbers": numbers,
            "proved": proved, "red": red,
            "not_run": {**NOT_RUN, **(not_run or {})},
            "holds": red is None}


def _cli(*argv, expect: int = EXIT_OK, timeout: float = 900.0) -> dict:
    """One step — one process `python -m kir.decompile.capture_api`.

    🔴 THE PACKAGE PATH IS NOT IMPOSED. The environment is inherited as-is: in
    the tree `PYTHONPATH` sets it, for an installed wheel the venv itself
    does. If the scenario substituted its own path, it would measure the tree
    even when asked to measure the installed package.
    """
    child = subprocess.run(
        [sys.executable, "-m", "kir.decompile.capture_api", *argv],
        capture_output=True, text=True, timeout=timeout,
        env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
    if child.returncode != expect:
        raise StepFailed("kir/decompile/capture_api.py",
                         f"{argv[0]}: код {child.returncode} вместо {expect}; "
                         f"{(child.stderr or child.stdout)[-400:]}")
    try:
        return json.loads(child.stdout)
    except json.JSONDecodeError as failure:
        raise StepFailed("kir/decompile/capture_api.py",
                         f"{argv[0]}: ответ не разобран ({failure})") from failure


def _digests(directory: Path) -> dict:
    """sha256 of EVERY file in the directory, including nested sidecars.

    Not size and not mtime: a write of the same length would slip past both.
    """
    out = {}
    for item in sorted(Path(directory).rglob("*")):
        if item.is_file():
            digest = hashlib.sha256()
            with item.open("rb") as handle:
                for block in iter(lambda: handle.read(1 << 20), b""):
                    digest.update(block)
            out[str(item.relative_to(directory))] = digest.hexdigest()
    return out


def _ring_of(op_params) -> list | None:
    """The opening ring of the raised floor — both shapes of the lifter.

    This is NOT a second law: the edit is checked by
    `geom.check_holes_relation` in the same turn as the forward path. Here
    only the value being edited is LOCATED.
    """
    contour = (op_params or {}).get("contour")
    holes = None
    if isinstance(contour, dict) and isinstance(contour.get("holes"), list):
        holes = contour["holes"]
    elif isinstance((op_params or {}).get("holes"), list):
        holes = op_params["holes"]
    if not holes or not isinstance(holes[0], list) or not holes[0]:
        return None
    return [[float(point[0]), float(point[1])] for point in holes[0]]


def _shrunk(ring: list, by: float = 1000.0) -> list:
    """Ring shrunk inward: the edit is REQUIRED to stay inside the slab."""
    xs = [point[0] for point in ring]
    ys = [point[1] for point in ring]
    x0, x1, y0, y1 = min(xs) + by, max(xs) - by, min(ys) + by, max(ys) - by
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


# ── 1. OPEN THE EXISTING RUN ────────────────────────────────────────────────
def step_open(capture: Path, synthetic: bool) -> dict:
    seen = _cli("open", "--capture", str(capture))
    binding = seen.get("source_binding") or {}
    missing = [name for name in ("lineage", "source_sha256", "source_version",
                                 "profiles") if not binding.get(name)]
    if missing:
        raise StepFailed("kir/decompile/capture_api.py:source_binding",
                         f"привязка не названа полями {missing}")
    numbers = {"elements": seen["elements"], "nodes": seen["nodes"],
               "edits": seen["edits"], "profiles": seen["profiles"],
               "side_indexes": len(seen["side_indexes"]),
               "missing_side_indexes": len(seen["missing_side_indexes"]),
               "integrity": seen["integrity"],
               "binding_fields": len(binding) - 1,
               "corpus": "synthetic" if synthetic else str(capture)}
    if seen["edits"] != 0:
        raise StepFailed("kir/decompile/capture_edit.py:open_capture",
                         "у только что открытого прогона уже есть правки")
    return _row("1. открыть существующий capture",
                "python -m kir.decompile.capture_api open", numbers,
                f"прогон открыт: {seen['elements']} элементов, "
                f"{len(seen['side_indexes'])} боковых индексов, привязка названа "
                f"четырьмя полями")


# ── 2. LEDGER: FOUR STATES AS NUMBERS, LOSSES AS ADDRESSES ─────────────────
def step_ledger(capture: Path) -> dict:
    seen = _cli("ledger", "--capture", str(capture), "--limit", "5")
    by_state = seen["by_state"]
    if sorted(by_state) != sorted(seen["states"]):
        raise StepFailed("kir/decompile/field_ledger.py",
                         f"состояния вне закрытого списка: {sorted(by_state)}")
    if sum(by_state.values()) != seen["nonempty"]:
        raise StepFailed("kir/decompile/field_ledger.py",
                         "сумма состояний не сходится с непустыми полями")
    if by_state["represented"] + seen["lost"] != seen["nonempty"]:
        raise StepFailed("kir/decompile/field_ledger.py",
                         "`represented` разошлось с `nonempty - lost`")
    if seen["unclassified"]:
        raise StepFailed("kir/decompile/field_ledger.py",
                         f"НЕ РАЗОБРАНО {seen['unclassified']} потерь")
    addressed = [row for row in seen["rows"]
                 if row["element_id"] and row["unique_id"]]
    if len(addressed) != len(seen["rows"]):
        raise StepFailed("kir/decompile/capture_api.py:capture_ledger",
                         "строка потерь без адреса: назвать её нечем")
    states_named = {item["state"] for row in seen["rows"] for item in row["lost"]}
    if not states_named <= set(seen["states"]):
        raise StepFailed("kir/decompile/field_ledger.py",
                         f"состояние вне списка у строки потерь: {states_named}")
    numbers = {"profiles": seen["profiles"], "elements": seen["elements"],
               "nonempty": seen["nonempty"], "lost": seen["lost"],
               **{f"state_{name}": count for name, count in sorted(by_state.items())},
               "by_why": seen["by_why"], "addressed": seen["addressed"],
               "rows_total": seen["rows_total"], "printed_rows": len(seen["rows"]),
               "states_named_in_rows": sorted(states_named)}
    return _row("2. ведомость полей по четырём состояниям",
                "python -m kir.decompile.capture_api ledger", numbers,
                f"{seen['nonempty']} непустых полей разложены на четыре "
                f"состояния ({by_state['represented']} представлено при режиме "
                f"чтения `{seen['profiles']}`), и каждая потеря названа адресом",
                not_run={"lossless_reconstruction": "not_claimed"})


# ── 3. READ THE ELEMENT: VALUES, HOST, FIELD STATES ────────────────────────
def step_read(capture: Path, door: str, floor: str) -> dict:
    seen = _cli("read", "--capture", str(capture), "--element", door)
    slab = _cli("read", "--capture", str(capture), "--element", floor)
    states = {item["state"] for item in seen["fields"]}
    if "represented" not in states:
        raise StepFailed("kir/decompile/capture_api.py:read_element",
                         "у двери нет ни одного представленного поля")
    if not states - {"represented"}:
        raise StepFailed("kir/decompile/capture_api.py:read_element",
                         "у двери НЕТ потерь — обратный путь без потерь не бывает")
    ring = _ring_of(slab["op_params"])
    if ring is None:
        raise StepFailed("kir/decompile/capture_edit.py:_holes_of",
                         f"{floor}: кольца отверстия в узле нет — править нечего")
    numbers = {"door": door, "category": seen["category"], "op": seen["op_name"],
               "host": (seen["host"] or {}).get("element_id"),
               "host_category": (seen["host"] or {}).get("category"),
               "depends_on": len(seen["depends_on"]),
               "referenced_by": len(seen["referenced_by"]),
               "fields": len(seen["fields"]),
               "supported": len(seen["supported"]),
               "editable_fields": list(seen["editable_fields"]),
               "states_of_this_element": sorted(states),
               "floor": floor, "ring_points": len(ring),
               "offset_mm": seen["op_params"].get("offset_mm")}
    return _row("3. прочитать элемент и его связи",
                "python -m kir.decompile.capture_api read", numbers,
                f"{door}: {seen['category']} как {seen['op_name']}, хозяин "
                f"{(seen['host'] or {}).get('element_id')}, у каждого непустого "
                f"поля названо состояние ({sorted(states)})",
                not_run={"lossless_reconstruction": "not_claimed"})


# ── 4. A PREVIEW THAT WRITES NOTHING ────────────────────────────────────────
def step_propose(capture: Path, edits: list) -> dict:
    before = _digests(capture)
    seen = _cli("propose", "--capture", str(capture),
                *[flag for edit in edits
                  for flag in ("--edit", json.dumps(edit, ensure_ascii=False))])
    after = _digests(capture)
    moved = sorted(name for name in set(before) | set(after)
                   if before.get(name) != after.get(name))
    if moved:
        raise StepFailed("kir/decompile/capture_api.py:propose_patch",
                         f"предпросмотр ЗАПИСАЛ: {moved[:5]}")
    if not all(row["admissible"] for row in seen["proposals"]):
        raise StepFailed("kir/decompile/capture_api.py:propose_patch",
                         f"правка не допущена: "
                         f"{[row['refusal'] for row in seen['proposals']]}")
    diffs = [len(row["diff"]) for row in seen["proposals"]]
    if not all(diffs):
        raise StepFailed("kir/decompile/capture_api.py:propose_patch",
                         "допустимая правка не показала НИ ОДНОГО отличия")
    numbers = {"proposals": len(seen["proposals"]), "admissible": sum(
        1 for row in seen["proposals"] if row["admissible"]),
        "diff_leaves": diffs, "wrote_nothing": seen["wrote_nothing"],
        "files_watched": len(before), "files_changed": len(moved),
        "open_questions": [len(row["open_questions"]) for row in seen["proposals"]]}
    return _row("4. предпросмотр без единой записи",
                "python -m kir.decompile.capture_api propose", numbers,
                f"{len(seen['proposals'])} правки показали {diffs} отличий и не "
                f"тронули ни одного из {len(before)} файлов прогона")


# ── 5–6. TWO EDITS, SEPARATED BY A PROCESS CLOSE ───────────────────────────
def step_apply_door(capture: Path, edit: dict, out: Path) -> dict:
    seen = _cli("apply", "--capture", str(capture),
                "--edit", json.dumps(edit, ensure_ascii=False), "--out", str(out))
    applied = seen["applied"][0]
    if applied["refusal"] is not None:
        raise StepFailed("kir/decompile/capture_edit.py:edit_element",
                         f"правка двери отказала: {applied['refusal']}")
    if len(applied["changed_ops"]) != 1:
        raise StepFailed("kir/decompile/capture_edit.py:edit_element",
                         f"тронут не один узел: {applied['changed_ops']}")
    if not Path(seen["saved"]).is_dir():
        raise StepFailed("kir/decompile/capture_edit.py:save",
                         "сохранение назвало каталог, которого нет")
    numbers = {"element": applied["element_id"],
               "changed_ops": len(applied["changed_ops"]),
               "untouched": applied["untouched_count"],
               "diff_leaves": len(applied["diff"]), "edits": seen["edits"],
               "saved": seen["saved"], "saved_files": len(_digests(Path(seen["saved"])))}
    return _row("5. приложить правку двери и сохранить в НОВЫЙ каталог",
                "python -m kir.decompile.capture_api apply --out", numbers,
                f"тронут ровно 1 узел, {applied['untouched_count']} элементов не "
                f"тронуты, {seen['edits']} правка легла в новый каталог")


def step_apply_opening(previous: Path, edit: dict, out: Path) -> dict:
    """The second change — from a NEW process, over the directory saved by the first."""
    seen = _cli("apply", "--capture", str(previous),
                "--edit", json.dumps(edit, ensure_ascii=False), "--out", str(out))
    applied = seen["applied"][0]
    if applied["refusal"] is not None:
        raise StepFailed("kir/decompile/capture_edit.py:_edit_opening",
                         f"правка отверстия отказала: {applied['refusal']}")
    if seen["edits"] != 2:
        raise StepFailed("kir/decompile/capture_edit.py:save",
                         f"первая правка не пережила закрытия процесса: "
                         f"правок {seen['edits']}, ожидалось 2")
    check = _cli("read", "--capture", str(out), "--element", edit["element_id"])
    ring = _ring_of(check["op_params"])
    want = [[float(x), float(y)] for x, y in edit["change"]["opening_contour_mm"]]
    if ring != want:
        raise StepFailed("kir/decompile/capture_edit.py:_edit_opening",
                         f"кольцо в сохранённом каталоге не то: {ring}")
    numbers = {"element": applied["element_id"],
               "changed_ops": len(applied["changed_ops"]),
               "untouched": applied["untouched_count"],
               "edits_after_reopen": seen["edits"], "saved": seen["saved"],
               "ring_in_saved": ring}
    return _row("6. продолжить вторым изменением из НОВОГО процесса",
                "python -m kir.decompile.capture_api apply (процесс B)", numbers,
                f"первая правка пережила закрытие процесса ({seen['edits']} правки "
                f"в журнале), второе изменение легло на кольцо отверстия")


# ── 7. THE CORPUS IS UNTOUCHED ──────────────────────────────────────────────
def step_corpus_untouched(capture: Path, before: dict, edit: dict, out: Path) -> dict:
    """🔴 THE CONTROL TAKES A VALID EDIT, NOT AN INVALID ONE.

    The first version called `apply --element 0` and got `unknown_element`
    BEFORE the matter reached saving: a refusal did arrive, but the WRONG
    ONE, and the step would be green even if a write inside someone else's
    run went through. Here the edit is VALID, and it is specifically the
    save that is required to refuse.
    """
    after = _digests(capture)
    moved = sorted(name for name in set(before) | set(after)
                   if before.get(name) != after.get(name))
    refusal = _cli("apply", "--capture", str(capture),
                   "--edit", json.dumps(edit, ensure_ascii=False),
                   "--out", str(capture / "__inside__"), expect=EXIT_REFUSED)
    code = (refusal.get("refusal") or {}).get("code")
    if code is None:
        # The seam's refusal arrives as an edit row, not at the top level —
        # in that case saving never reached the refusal at all, and this is
        # a DIFFERENT refusal.
        code = next((row["refusal"]["code"] for row in refusal.get("applied") or ()
                     if row.get("refusal")), None)
    # This refusal has TWO names, and they mean different things:
    # `target_inside_source` — the target is inside the SAME run that is
    # open; `target_inside_capture` — inside SOMEONE ELSE'S. Collapsing them
    # into one would lose which exact snapshot is protected.
    if code not in ("target_inside_source", "target_inside_capture"):
        raise StepFailed("kir/decompile/capture_edit.py:save",
                         f"запись внутрь прогона отказала не по имени: {code}")
    if (capture / "__inside__").exists():
        raise StepFailed("kir/decompile/capture_edit.py:save",
                         "отказ оставил каталог внутри чужого прогона")
    final = _digests(capture)
    moved_after_refusal = sorted(name for name in set(before) | set(final)
                                 if before.get(name) != final.get(name))
    red = None
    if moved or moved_after_refusal:
        red = {"address": str(capture),
               "what": f"исходный прогон изменён: {(moved + moved_after_refusal)[:5]}"}
    numbers = {"files": len(before), "changed": len(moved),
               "l0_sha256_before": before.get("L0.jsonl", "")[:16],
               "l0_sha256_after": final.get("L0.jsonl", "")[:16],
               "l0_identical": before.get("L0.jsonl") == final.get("L0.jsonl"),
               "refusal_code": code,
               "target_created": (capture / "__inside__").exists(),
               "own_output": str(out)}
    return _row("7. исходный прогон не тронут ни байтом",
                "sha256 каждого файла + отказ target_inside_capture", numbers,
                f"{len(before)} файлов прогона побайтно те же, а запись внутрь "
                f"него отказана по имени `{code}`",
                red=red, not_run={"corpus_written": False})


# ── 8. THE EXPORT COMPILES, AND REFUSALS ARE NAMED ─────────────────────────
def step_export(capture: Path, csharp: Path) -> dict:
    seen = _cli("export", "--capture", str(capture), "--csharp-dir", str(csharp))
    files = sorted(csharp.glob("*.cs"))
    if seen["compiled"] < 1:
        raise StepFailed("kir/decompile/capture_edit.py:export_program",
                         "не переведено НИ ОДНОЙ программы")
    if len(files) != seen["compiled"]:
        raise StepFailed("examples/final_result_capture_walkthrough.py",
                         f"файлов C# {len(files)}, а переведено {seen['compiled']}")
    codes = sorted({code for row in seen["refusals"] for code in row.get("codes", ())})
    if seen["compiled"] < seen["programs"] and not codes:
        raise StepFailed("kir/decompile/capture_edit.py:export_program",
                         "часть программ не переведена, и отказ не назван кодом")
    numbers = {"programs": seen["programs"], "compiled": seen["compiled"],
               "refusals": len(seen["refusals"]), "refusal_codes": codes,
               "cs_files": len(files),
               "bytes": sum(item.stat().st_size for item in files)}
    return _row("8. экспорт правленого capture компилируется",
                "python -m kir.decompile.capture_api export --csharp-dir", numbers,
                f"{seen['compiled']} из {seen['programs']} программ переведены в "
                f"C# ({len(files)} файлов); непереведённые названы кодами {codes}",
                not_run={"native_execution": "not_run", "revit_started": False})


# ── run ──────────────────────────────────────────────────────────────────────
def run(root, capture=None) -> list:
    """Eight steps of the round trip. A red step does not interrupt the run."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    source = Path(capture) if capture else CORPUS
    synthetic = not (source / "L0.jsonl").exists() and not (source / "L0.jsonl.gz").exists()
    if synthetic:
        source = root / "synthetic"
        made = _cli("demo", "--out", str(source))
        door, floor = made["door"], made["floor"]
    else:
        door, floor = CORPUS_DOOR, CORPUS_FLOOR
    rows: list = []

    def guarded(name, instrument, call):
        try:
            return call()
        except StepFailed as failure:
            return _row(name, instrument, {}, "не доказано",
                        red={"address": failure.address, "what": failure.detail})
        except Exception as failure:  # noqa: BLE001 — red with a name, not a trace
            return _row(name, instrument, {}, "не доказано",
                        red={"address": "examples/final_result_capture_walkthrough.py",
                             "what": f"{type(failure).__name__}: {failure}"[:400]})

    opened = guarded("1. открыть существующий capture", "capture open",
                     lambda: step_open(source, synthetic))
    rows.append(opened)
    if not opened["holds"]:
        return rows
    rows.append(guarded("2. ведомость полей по четырём состояниям", "capture ledger",
                        lambda: step_ledger(source)))
    read = guarded("3. прочитать элемент и его связи", "capture read",
                   lambda: step_read(source, door, floor))
    rows.append(read)
    if not read["holds"]:
        return rows

    # Preparing the edits is also under a guard: without it, if this broke,
    # the run would end in a trace instead of a red row with an address.
    try:
        was = read["numbers"]["offset_mm"]
        slab = _cli("read", "--capture", str(source), "--element", floor)
        ring = _shrunk(_ring_of(slab["op_params"]))
    except Exception as failure:  # noqa: BLE001
        rows.append(_row("4. предпросмотр без единой записи", "capture propose", {},
                         "не доказано",
                         red={"address": "kir/decompile/capture_api.py:read_element",
                              "what": f"{type(failure).__name__}: {failure}"[:400]}))
        return rows
    door_edit = {"element_id": door, "change": {"offset_mm": float(was) + 300.0},
                 "before": {"offset_mm": was}}
    opening_edit = {"element_id": floor,
                    "change": {"opening_index": 0, "opening_contour_mm": ring}}
    before = _digests(source)

    rows.append(guarded("4. предпросмотр без единой записи", "capture propose",
                        lambda: step_propose(source, [door_edit, opening_edit])))
    step1, step2 = root / "step1", root / "step2"
    first = guarded("5. приложить правку двери и сохранить в НОВЫЙ каталог",
                    "capture apply --out",
                    lambda: step_apply_door(source, door_edit, step1))
    rows.append(first)
    if first["holds"]:
        rows.append(guarded("6. продолжить вторым изменением из НОВОГО процесса",
                            "capture apply (процесс B)",
                            lambda: step_apply_opening(step1, opening_edit, step2)))
    else:
        rows.append(_row("6. продолжить вторым изменением из НОВОГО процесса",
                         "capture apply (процесс B)", {}, "не доказано",
                         red={"address": "kir/decompile/capture_edit.py:save",
                              "what": "шаг 5 не сохранил каталог — продолжать нечего"}))
    rows.append(guarded("7. исходный прогон не тронут ни байтом", "sha256 + отказ",
                        lambda: step_corpus_untouched(source, before, door_edit, step2)))
    target = step2 if step2.is_dir() else (step1 if step1.is_dir() else source)
    rows.append(guarded("8. экспорт правленого capture компилируется",
                        "capture export --csharp-dir",
                        lambda: step_export(target, root / "cs")))
    return rows


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, metavar="NEW_DIR",
                        help="новый каталог: в нём появятся step1, step2 и C#")
    parser.add_argument("--capture", default=None,
                        help=f"каталог прогона; по умолчанию {CORPUS}")
    args = parser.parse_args(argv)
    rows = run(args.root, args.capture)
    for row in rows:
        print(json.dumps(row, ensure_ascii=False, sort_keys=True))
    red = [row for row in rows if row["red"]]
    print(json.dumps({"schema": "kir-capture-walkthrough/1",
                      "steps": len(rows), "held": len(rows) - len(red),
                      "red": [{"step": row["step"], **row["red"]} for row in red],
                      "claims": {"live_revit": "not_run", "full_product": "not_claimed",
                                 "real_llm_calls": 0,
                                 "lossless_reconstruction": "not_claimed"}},
                     ensure_ascii=False))
    # The exit code carries the verdict — see the same note in
    # `final_result_walkthrough.py`. A red step may not return 0.
    return 1 if red else 0


if __name__ == "__main__":
    raise SystemExit(main())
