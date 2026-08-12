"""Хранение журнала здания — единственный провод `journal` наружу.

`journal.py` умеет всё, что умеет журнал: цепочку хешей, откат, аудит,
детерминированное воспроизведение состояния на любой ревизии.  Чего он НЕ
умеет — узнать, что вчерашний разбор и сегодняшний относятся к одному
зданию, и куда этот журнал положить.  Ровно этого и не хватало: 471 строка
и 22 теста лежали на складе с собственной пометкой докстринга «opt-in gate
for future pipeline wiring».

Пробел, который закрывается, называется коротко: **у здания не было
истории**.  На диске 52 свёрнутых разбора, и по замеру 09.08.2026 они
складываются в 10 зданий по `passport.json::doc_name` — у фасада
`SOB6.2_UPO_L_DOO_FAS_R23_kuklev.d.s` их ВОСЕМНАДЦАТЬ.  Система при этом не
помнила ни того, что это одно здание, ни того, что между двумя чтениями
изменилось: чтобы ответить «что поменялось с прошлого раза», приходилось
держать оба `tree.json` и считать различие заново.  Модель, которой нужен
`base_doc_stamp` для дельта-пересборки, брать его было неоткуда — только из
памяти оператора.

Этот модуль не считает НИЧЕГО нового.  Дельту считает `journal.commit_trees`
(и через него `rebuild.delta_between`), применимость проверяет он же; здесь
только персистентность и отчёт, между `journal` и двумя его потребителями:

* `decompile/pipeline.py` — живой путь: разбор ДОПИСЫВАЕТ ревизию в журнал
  своего здания (флаг `KUKAI_IR_JOURNAL`, по умолчанию ВЫКЛ) и кладёт рядом
  с `tree.json` квитанцию `journal.json` о том, что именно дописал;
* `ir/serving.py::handle_revit_rebuild` — читатель: `base_doc_stamp` со
  значением `@journal` разрешается в ПРЕДЫДУЩУЮ ревизию того же здания, и
  разрешённое имя едет в ответе.

ЖУРНАЛ ЛЕЖИТ РЯДОМ С РАЗБОРАМИ, а не внутри одного из них: `_journals/` в
каталоге, где живут каталоги прогонов.  Он общий для всех ревизий здания —
это и есть его смысл; лежи он внутри прогона, «прошлый разбор того же
здания» снова пришлось бы искать перебором.

КЛЮЧ ЖУРНАЛА — ИМЯ ДОКУМЕНТА, и к нему ВСЕГДА приписан дайджест ПОЛНОГО
имени.  Санитайзер без дайджеста склеил бы «А Б» и «А_Б» в один файл, то
есть слил бы истории двух разных зданий молча — тот же урок, что уже
записан в `serving._decompile_out_dir`.

ГРАНИЦА, КОТОРУЮ НАДО НАЗЫВАТЬ, А НЕ ПРЯТАТЬ: цепочка хешей `journal/1`
подписывает СОСТОЯНИЯ и ДЕЛЬТЫ — «чем здание было и что в нём изменилось».
Сопроводительные строки ревизий (`doc_stamp`, `out_dir`, время) в цепочку не
входят и подделываются незаметно.  Подменённая дельта ловится, подменённая
подпись «откуда она взялась» — нет.

И ВТОРАЯ, ИЗМЕРЕННАЯ: `doc_name` — имя файла, а не тождество здания.
Замер 09.08.2026 по 52 разборам: `k2_ar_rd_v6`/`v7` несут
`13A-RD-AR-K2_v33`, а `k2_ar_rd_v8` — `13A-RD-AR-K2_v33_kuklev.d.s`, то есть
«сохранить как» РАЗРЫВАЕТ журнал, и пара, на которой мерили дельта-
пересборку, попала бы в два разных лога.  Это не тихая склейка (две истории
не смешиваются), но это потерянная связь, и предупреждение о ней едет в
квитанции: `previous_doc_stamp: null` при непустом каталоге разборов значит
ровно «здание с таким именем читается впервые».
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from kukai.ir.decompile.journal import (
    JOURNAL_VERSION,
    BuildingJournal,
    JournalError,
    commit_trees,
    new_journal,
)

LOG_SCHEMA = "kir-building-log/1"
REPORT_SCHEMA = "kir-journal-report/1"

#: Каталог общих журналов рядом с каталогами прогонов.
LOG_DIRNAME = "_journals"

__all__ = [
    "LOG_DIRNAME",
    "LOG_SCHEMA",
    "REPORT_SCHEMA",
    "building_key",
    "history_report",
    "load_log",
    "log_path",
    "previous_stamp",
    "record_revision",
]


# ---------------------------------------------------------------------------
# Ключ и путь
# ---------------------------------------------------------------------------


def building_key(doc_name: str) -> str:
    """Имя файла журнала для документа `doc_name`.

    Дайджест полного имени приписывается ВСЕГДА, а не только когда санитайзер
    что-то испортил: два документа, различающиеся лишь символом, который
    санитайзер схлопывает, обязаны получить разные файлы.  Читаемый префикс
    остаётся только затем, чтобы каталог `_journals/` можно было понять
    глазами.
    """

    name = doc_name if isinstance(doc_name, str) else ""
    digest = hashlib.sha256(name.encode("utf-8")).hexdigest()[:16]
    safe = "".join(
        ch if (ch.isalnum() or ch in "-_.") else "_" for ch in name)
    prefix = safe.strip("._")[:80] or "document"
    return f"{prefix}-{digest}"


def log_path(root: str | os.PathLike[str], doc_name: str) -> Path:
    """`<root>/_journals/<ключ>.json` — журнал ОДНОГО здания."""

    return Path(root) / LOG_DIRNAME / f"{building_key(doc_name)}.json"


# ---------------------------------------------------------------------------
# Чтение / запись
# ---------------------------------------------------------------------------


def _atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=str(path.parent), delete=False,
        prefix=path.name + ".", suffix=".tmp")
    try:
        json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
        handle.flush()
        os.fsync(handle.fileno())
    finally:
        handle.close()
    os.replace(handle.name, path)


def load_log(path: str | os.PathLike[str]) -> dict[str, Any] | None:
    """Прочитать журнал здания; `None` — файла нет.

    Отсутствие файла и НЕЧИТАЕМЫЙ файл — разные факты, и разными они здесь и
    остаются: битый или подделанный журнал поднимает `JournalError`, а не
    возвращает `None`.  Иначе «журнал сломан» стало бы неотличимо от «здание
    читается впервые», и следующий прогон завёл бы новый журнал поверх
    сломанного, стерев улику.
    """

    file_path = Path(path)
    if not file_path.is_file():
        return None
    try:
        payload = json.loads(file_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise JournalError(f"журнал {file_path} не читается: {exc}") from exc
    if not isinstance(payload, Mapping) or payload.get("schema") != LOG_SCHEMA:
        raise JournalError(
            f"журнал {file_path}: схема не {LOG_SCHEMA}")
    revisions = payload.get("revisions")
    if not isinstance(revisions, list) or not revisions:
        raise JournalError(f"журнал {file_path}: нет ни одной ревизии")
    # `from_dict` сам зовёт `verify()` — цепочка проверяется на КАЖДОМ чтении,
    # а не только при записи.
    journal = BuildingJournal.from_dict(payload["journal"])
    if len(journal) != len(revisions):
        raise JournalError(
            f"журнал {file_path}: {len(revisions)} сопроводительных строк "
            f"против {len(journal)} событий цепочки")
    return dict(payload)


def journal_of(log: Mapping[str, Any]) -> BuildingJournal:
    """Разобрать журнал из лога (с проверкой цепочки)."""

    return BuildingJournal.from_dict(log["journal"])


# ---------------------------------------------------------------------------
# Отчёт
# ---------------------------------------------------------------------------


def _refusal(exc: BaseException, **extra: Any) -> dict[str, Any]:
    """Отказ, который видно.  Никогда не притворяется пустой историей."""

    return {
        "schema": REPORT_SCHEMA,
        "journal_version": JOURNAL_VERSION,
        "ok": False,
        "appended": False,
        "error": {"type": type(exc).__name__, "message": str(exc)},
        **extra,
    }


def _delta_summary(journal: BuildingJournal, revision: int) -> dict[str, Any]:
    event = journal.changes_at(revision)
    delta = event.delta
    return {
        "touched": delta.touched_count,
        "emitted": delta.emitted_count,
        "retired": delta.retired_count,
        "relocated": delta.relocated_count,
        "reused": delta.reused_count,
        "summary": list(event.summary),
    }


def history_report(log: Mapping[str, Any]) -> dict[str, Any]:
    """История здания: ревизии, что изменилось на каждой, цела ли цепочка."""

    try:
        journal = journal_of(log)
    except (JournalError, KeyError, TypeError, ValueError) as exc:
        return _refusal(exc, doc_name=log.get("doc_name"))

    rows: list[dict[str, Any]] = []
    for row in log["revisions"]:
        index = int(row["revision"])
        entry = {
            "revision": index,
            "doc_stamp": row.get("doc_stamp"),
            "out_dir": row.get("out_dir"),
            "recorded_at": row.get("recorded_at"),
            "revit_version": row.get("revit_version"),
            "leaves": row.get("leaves"),
            "event_hash": journal.events[index].event_hash,
        }
        if index > 0:
            entry["delta"] = _delta_summary(journal, index)
        rows.append(entry)
    return {
        "schema": REPORT_SCHEMA,
        "journal_version": JOURNAL_VERSION,
        "ok": True,
        "appended": False,
        "doc_name": log.get("doc_name"),
        "key": log.get("key"),
        "head_revision": journal.head_revision,
        "revisions_total": len(journal),
        "head_hash": journal.events[-1].event_hash,
        "revisions": rows,
    }


def previous_stamp(
    log: Mapping[str, Any], doc_stamp: str,
) -> tuple[str | None, str | None]:
    """Штамп ревизии ПЕРЕД `doc_stamp` в этом журнале.

    Возвращает `(штамп, причина_отказа)`.  Берётся ПОСЛЕДНЕЕ вхождение
    штампа: один и тот же `doc_stamp` можно перечитать, и «предыдущая»
    означает предыдущую по журналу, а не первую историческую.
    """

    revisions = list(log.get("revisions") or ())
    found = None
    for row in revisions:
        if row.get("doc_stamp") == doc_stamp:
            found = int(row["revision"])
    if found is None:
        return None, "not_in_journal"
    if found == 0:
        return None, "is_base_revision"
    return str(revisions[found - 1].get("doc_stamp") or ""), None


# ---------------------------------------------------------------------------
# Запись ревизии — то самое, что зовёт живой разбор
# ---------------------------------------------------------------------------


def _row(
    *, revision: int, doc_stamp: str, out_dir: str, revit_version: str,
    leaves: int, event_hash: str,
) -> dict[str, Any]:
    return {
        "revision": revision,
        "doc_stamp": doc_stamp,
        "out_dir": out_dir,
        "revit_version": revit_version,
        "leaves": leaves,
        "recorded_at": datetime.now(timezone.utc).isoformat(
            timespec="seconds"),
        "event_hash": event_hash,
    }


def _leaf_count(tree: Any) -> int:
    from kukai.ir.decompile.fold import iter_l1_leaves
    return sum(1 for _ in iter_l1_leaves(tree))


def record_revision(
    root: str | os.PathLike[str],
    *,
    doc_name: str,
    doc_stamp: str,
    out_dir: str,
    tree: Any,
    revit_version: str = "",
) -> dict[str, Any]:
    """Дописать этот разбор в журнал его здания; вернуть квитанцию.

    Первый разбор здания заводит журнал с БАЗОВОЙ ревизией (состояние, без
    дельты).  Каждый следующий читает `tree.json` головной ревизии и зовёт
    `commit_trees`, который сам откажет, если это дерево не воспроизводит
    состояние головы — то есть если журнал и разборы разъехались.

    Ни один отказ не заводит журнал заново и не дописывает «примерно верную»
    ревизию: журнал, в который однажды попала неправда, хуже отсутствующего,
    потому что выглядит одинаково с честным.
    """

    base = {
        "schema": REPORT_SCHEMA,
        "journal_version": JOURNAL_VERSION,
        "doc_name": doc_name,
        "key": building_key(doc_name),
        "doc_stamp": doc_stamp,
    }
    path = log_path(root, doc_name)
    try:
        log = load_log(path)
    except (JournalError, KeyError, TypeError, ValueError) as exc:
        # Битый/подделанный журнал — ОТКАЗ, а не «начнём новый»: перезапись
        # стёрла бы ровно то свидетельство, ради которого цепочка и заведена.
        return _refusal(exc, **base, log_path=str(path),
                        reason="log_unreadable")

    try:
        leaves = _leaf_count(tree)
    except (KeyError, TypeError, ValueError) as exc:
        return _refusal(exc, **base, log_path=str(path),
                        reason="tree_unreadable")

    if log is None:
        try:
            journal = new_journal(tree)
        except (JournalError, KeyError, TypeError, ValueError) as exc:
            return _refusal(exc, **base, log_path=str(path),
                            reason="base_not_foldable")
        rows = [_row(revision=0, doc_stamp=doc_stamp, out_dir=str(out_dir),
                     revit_version=revit_version, leaves=leaves,
                     event_hash=journal.events[0].event_hash)]
        _write(path, doc_name, journal, rows)
        return {
            **base, "ok": True, "appended": True, "log_path": str(path),
            "revision": 0, "head_revision": 0, "revisions_total": 1,
            "kind": "base", "leaves": leaves,
            "previous_doc_stamp": None,
            "head_hash": journal.events[0].event_hash,
        }

    rows = list(log["revisions"])
    head_row = rows[-1]
    head_stamp = str(head_row.get("doc_stamp") or "")
    if head_stamp == doc_stamp:
        # Тот же штамп перечитан заново: это не новая ревизия здания, а
        # повторное чтение той же.  Дописывать пустую дельту значило бы
        # засорять историю событиями, которых не было.
        journal = journal_of(log)
        return {
            **base, "ok": True, "appended": False, "log_path": str(path),
            "reason": "already_head",
            "revision": journal.head_revision,
            "head_revision": journal.head_revision,
            "revisions_total": len(journal),
            "previous_doc_stamp": (
                str(rows[-2].get("doc_stamp")) if len(rows) > 1 else None),
            "head_hash": journal.events[-1].event_hash,
        }

    head_tree_path = Path(str(head_row.get("out_dir") or "")) / "tree.json"
    if not head_tree_path.is_file():
        return _refusal(
            FileNotFoundError(
                f"дерева головной ревизии нет: {head_tree_path}"),
            **base, log_path=str(path), reason="head_tree_missing",
            head_doc_stamp=head_stamp)
    try:
        head_tree = json.loads(head_tree_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return _refusal(exc, **base, log_path=str(path),
                        reason="head_tree_unreadable",
                        head_doc_stamp=head_stamp)

    try:
        journal = journal_of(log)
        # `commit_trees` откажет сам, если `head_tree` не воспроизводит
        # состояние головы: каталог прогона могли перезаписать другим
        # зданием под тем же штампом, и дельта считалась бы от чужой базы.
        journal = commit_trees(journal, head_tree, tree)
    except (JournalError, KeyError, TypeError, ValueError) as exc:
        return _refusal(exc, **base, log_path=str(path),
                        reason="not_applicable_to_head",
                        head_doc_stamp=head_stamp)

    revision = journal.head_revision
    rows.append(_row(
        revision=revision, doc_stamp=doc_stamp, out_dir=str(out_dir),
        revit_version=revit_version, leaves=leaves,
        event_hash=journal.events[revision].event_hash))
    _write(path, doc_name, journal, rows)
    return {
        **base, "ok": True, "appended": True, "log_path": str(path),
        "revision": revision, "head_revision": revision,
        "revisions_total": len(journal), "kind": "delta", "leaves": leaves,
        "previous_doc_stamp": head_stamp,
        "head_hash": journal.events[revision].event_hash,
        "delta": _delta_summary(journal, revision),
    }


def _write(
    path: Path, doc_name: str, journal: BuildingJournal,
    rows: list[dict[str, Any]],
) -> None:
    _atomic_write_json(path, {
        "schema": LOG_SCHEMA,
        "journal_version": JOURNAL_VERSION,
        "doc_name": doc_name,
        "key": building_key(doc_name),
        "revisions": rows,
        "journal": journal.to_dict(),
    })
