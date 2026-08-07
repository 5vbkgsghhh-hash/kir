#!/usr/bin/env python3
"""Живая пересборка разбора чанками через прод-путь.

Эндпойнт /admin/kir/rebuild умеет только сухой прогон: живая ветка возвращает
``live_rebuild_unimplemented`` — она не выключена флагом, её просто нет. Прежние
пересборки проекта гнались чем-то, чего в репозитории не осталось.

Драйвер делает ровно то, что делал бы живой rebuild: берёт листья L1 из
tree.json, материализует их в программы со сдвигом и гонит КАЖДУЮ через тот же
POST /admin/kir/run, которым идёт чат, — без LLM в петле, с теми же
свидетелями и теми же отказами.

Ничего не изобретает: чанкование и трансляция ссылок принадлежат
``leaves_to_program``, драйвер только возит программы по проводу и ведёт
квитанцию по каждой.

БЮДЖЕТ. Чанк материализатора меряется ВНУТРЕННИМ bulk-бюджетом
(``compiler.MAX_BULK_OPS``), а не авторским бюджетом программы модели — драйвер
просит внутреннюю дверь явно (``"bulk": true`` в теле /admin/kir/run). До
30.07 такой двери не существовало: драйвер резал чанки по 20 опов под чат-дверь,
и пересборка образца Snowdon Towers (6 343 элемента) стоила 318 раундов вместо
26. Размер чанка здесь БОЛЬШЕ НЕ НАЗНАЧАЕТСЯ: по умолчанию его выбирает сам
материализатор (одно место), аргумент командной строки остался только для проб.
"""
from __future__ import annotations

import json
import os
import pathlib
import sys
import time
import urllib.request

BACKEND = pathlib.Path("/opt/kukai-rebuild1/backend")
sys.path.insert(0, str(BACKEND))


def _token() -> str:
    for line in (BACKEND / ".env").read_text(encoding="utf-8").splitlines():
        if line.startswith("KUKAI_ADMIN_TOKEN="):
            return line.split("=", 1)[1].strip()
    raise SystemExit("нет KUKAI_ADMIN_TOKEN")


def _post(program: dict, doc: str, timeout_ms: int) -> dict:
    # ``bulk`` — ВНУТРЕННЯЯ дверь serving (serving.handle_revit_ir_bulk): её
    # бюджет считает чанки материализатора, а не программы, написанные моделью.
    # Из чата это поле недостижимо: тело запроса живёт за X-Admin-Token.
    body = json.dumps({"program": program, "doc_contains": doc,
                       "timeout_ms": timeout_ms, "bulk": True}).encode("utf-8")
    req = urllib.request.Request(
        "http://127.0.0.1:52411/admin/kir/run", data=body,
        headers={"Content-Type": "application/json", "X-Admin-Token": _token()})
    try:
        with urllib.request.urlopen(req, timeout=timeout_ms / 1000 + 60) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as exc:
        return {"http_error": exc.code,
                "body": exc.read().decode("utf-8", "replace")[:400]}
    except Exception as exc:  # noqa: BLE001 — обрыв провода тоже квитанция
        return {"transport_error": f"{type(exc).__name__}: {exc}"}


def main() -> int:
    stamp, doc, out_path = sys.argv[1], sys.argv[2], sys.argv[3]
    offset = [float(x) for x in sys.argv[4].split(",")] if len(sys.argv) > 4 else None

    from kukai.ir.decompile.fold import iter_l1_leaves
    from kukai.ir.decompile.materialize import leaves_to_program

    decompile_dir = BACKEND / "backend" / "data" / "decompile" / stamp
    tree_path = decompile_dir / "tree.json"
    tree = json.loads(tree_path.read_text(encoding="utf-8"))
    leaves = list(iter_l1_leaves(tree))
    # Размер чанка НЕ повторяется здесь литералом: по умолчанию его назначает
    # материализатор, а он же держит потолок MAX_BULK_OPS — тот самый, который
    # принимает внутренняя дверь. Два числа, названные в разных местах, и есть
    # тот шов, который стоил 318 раундов.
    chunk = int(sys.argv[5]) if len(sys.argv) > 5 else None
    materialize_kwargs: dict = {"offset_mm": offset}
    materialize_mode = "same_document"
    if os.getenv("KUKAI_IR_ATOM_ESCROW", "").strip().lower() in {
            "1", "true", "yes", "on"}:
        from kukai.ir.decompile.geom_extract import GeometryExtraction
        geometry_path = decompile_dir / "geometry.bundle.json"
        if not geometry_path.is_file():
            raise SystemExit(
                "KUKAI_IR_ATOM_ESCROW включён, но geometry.bundle.json нет")
        categories_by_id = {
            leaf["source_element_id"]: leaf["category"]
            for leaf in leaves
            if leaf.get("kind") == "atom"
        }
        geometry = GeometryExtraction.from_json(
            geometry_path.read_text(encoding="utf-8"),
            categories_by_id=categories_by_id,
        )
        materialize_mode = "escrow"
        materialize_kwargs.update({
            "mode": materialize_mode,
            "geometry": geometry,
        })
    if chunk is not None:
        materialize_kwargs["chunk_target"] = chunk
    result = leaves_to_program(leaves, **materialize_kwargs)
    programs = result.programs
    if not result.compiler_ready:
        refused = [
            check.as_dict() for check in result.plan_checks
            if not check.accepted
        ]
        refusal_receipt = {
            "stamp": stamp,
            "document": doc,
            "offset_mm": offset,
            "materialize_mode": materialize_mode,
            "compiler_ready": False,
            "plan_checks": [
                check.as_dict() for check in result.plan_checks
            ],
            "leaves": len(leaves),
            "skipped_leaves": len(result.skipped),
        }
        pathlib.Path(out_path).write_text(
            json.dumps(refusal_receipt, ensure_ascii=False, indent=1),
            encoding="utf-8")
        print("materializer produced compiler-refused chunks: "
              + json.dumps(refused[:8], ensure_ascii=False), flush=True)
        return 2
    plan_digests = [plan.plan_digest for plan in result.plans if plan is not None]
    sizes = [len(p.get("ops") or []) for p in programs]
    print(f"листьев {len(leaves)} -> программ {len(programs)} "
          f"(опов {sum(sizes)}, крупнейшая {max(sizes) if sizes else 0}); "
          f"пропущено листьев {len(result.skipped)}", flush=True)

    rows = []
    created_total = 0
    for index, program in enumerate(programs):
        t0 = time.monotonic()
        answer = _post(program, doc, 200_000)
        kir = (answer or {}).get("kir") or {}
        res = kir.get("result") or {}
        created = [k for k in res if k != "ok"]
        created_total += len(created)
        diag = (kir.get("diagnostics") or [{}])[0] if kir.get("diagnostics") else {}
        row = {
            "chunk": index,
            "plan_digest": plan_digests[index],
            "ops": len(program.get("ops") or []),
            "ok": bool(kir.get("ok")),
            "created": len(created),
            "elapsed_s": round(time.monotonic() - t0, 1),
            "code": diag.get("code"),
            "message": (diag.get("message_ru") or "")[:120],
            # `detail` НАЗЫВАЕТ опы без подтверждённой идентичности. Он важен
            # именно здесь: чанк идёт по-оповой изоляцией (compile_rebuild_chunk),
            # поэтому один плохой оп НЕ откатывает соседей — часть элементов
            # уже в модели, а `created` по такому чанку считается нулём.
            # Без этой строки квитанция молчала бы о том, ЧТО именно не сошлось.
            "detail": (diag.get("detail") or "")[:200],
            "violations": (kir.get("err") or {}).get("violations", [])[:3],
            "transport": answer.get("transport_error") or answer.get("http_error"),
        }
        rows.append(row)
        print(f"  чанк {index:>2}/{len(programs)}  опов {row['ops']:>4}  "
              f"ok={row['ok']}  создано {row['created']:>4}  "
              f"{row['elapsed_s']:>6}с  {row['code'] or ''} {row['message']}",
              flush=True)

    ok_count = sum(1 for r in rows if r["ok"])
    summary = {
        "stamp": stamp, "document": doc, "offset_mm": offset,
        "materialize_mode": materialize_mode,
        "bulk": True,
        "chunk_target": chunk,          # None = умолчание материализатора
        "plan_digests": plan_digests,
        "programs": len(programs), "chunks_ok": ok_count,
        "ops_total": sum(sizes), "largest_program_ops": max(sizes) if sizes else 0,
        "created_total": created_total,
        "leaves": len(leaves), "skipped_leaves": len(result.skipped),
        "atoms_escrowed": result.stats.atoms_escrowed,
        "escrow_evidence": [
            record.as_dict() for record in result.escrowed],
        "rows": rows,
    }
    pathlib.Path(out_path).write_text(
        json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nИТОГ: чанков ok {ok_count}/{len(programs)}, "
          f"создано элементов {created_total}\n-> {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
