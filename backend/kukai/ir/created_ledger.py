"""Долговременный след СОЗДАННОГО: id каждого элемента, независимо от `ok`.

ЗАЧЕМ. 13.08.2026 живой прогон дал два элемента, оставшихся в модели
оператора без единого следа их номеров. Исход был `execution: committed` при
`ok: false` (`KIR-A006`/`KIR-A007`: запись состоялась, независимая приёмка
разошлась или не завершилась) — то есть Revit построил, а программа объявила
неуспех. Дальше искали id по ТРЁМ серверным записям:

    свидетель (`kir_witness.jsonl`)   вердикт `op_outcomes: {"MS1": "created"}`
    журнал приёмки                    дайджесты, `run_id`, `sequence`
    отказы (`kir_rejections.jsonl`)   коды, поля, кандидаты

**Числа нет ни в одной.** Квитанция жила исключительно в теле HTTP-ответа, и
разбор этого тела был единственным местом, где id вообще существовали. В тот
раз спасло РУЧНОЕ чтение модели; на флоте из тринадцати устройств вручную не
читает никто, и созданное-и-нигде-не-названное есть мусор в ЧУЖОЙ модели без
следов.

ЧТО ЭТОТ МОДУЛЬ ДЕЛАЕТ И ЧЕГО НЕ ДЕЛАЕТ. Он пишет строку на КАЖДЫЙ ход,
дошедший до исполнения, и делает это СРАЗУ после ответа моста — раньше, чем
работает приёмка, потому что именно приёмка и объявляет неуспех в тех двух
кодах. Он НЕ убирает ничего и не решает, что делать со следом: уборка по
такому списку — отдельное решение с отдельным риском (`created_ledger`
сообщает, что элемент есть; принадлежит ли он ещё нам — вопрос к документу).
Сначала след обязан перестать теряться.

ЧИТАЕТСЯ ПАВЛОАД, А НЕ ПРОГРАММА. Разница решающая и она же — контроль:
откатанная программа обязана оставить строку с ПУСТЫМ списком, а не со
списком заявленных опов. Список того, что мы СОБИРАЛИСЬ создать, при откате
совпал бы по виду со списком созданного и превратил бы реестр в генератор
ложных следов — наш именованный класс: величина, названная в одном месте,
читается из другого, и ничто не заставляет их совпасть.

ГРАНИЦА, КОТОРУЮ НЕЛЬЗЯ ЗАМОЛЧАТЬ. Реестр знает ровно то, что ДОШЛО до
сервера. Если мост оборвался до ответа, исход типизирован `unconfirmed`, и
номеров не существует нигде, кроме самого Revit, — этот модуль такого случая
не закрывает и не притворяется, что закрывает. Он закрывает другой, и
измеренно частый: ответ пришёл, элементы созданы, а ход объявил неуспех.

ОТКАЗ САМОГО РЕЕСТРА НЕ ИМЕЕТ ПРАВА ОТМЕНИТЬ ЗАПИСЬ. Успешная запись в Revit
не становится неуспешной оттого, что мы не смогли записать про неё строку.
Но и молчать нельзя: неудача пишется в соседний файл `*.errors.jsonl` и в
лог уровня ERROR. Тихой деградации здесь нет — есть названное место, куда
смотреть.
"""

from __future__ import annotations

import json
import logging
import os
import pathlib
from typing import Any, Mapping, Sequence

from kukai.ir.install_paths import install_data_path

logger = logging.getLogger(__name__)

LEDGER_DIR_ENV = "KIR_CREATED_LEDGER_DIR"
SCHEMA_VERSION = "kir-created-ledger/1"

def created_keys() -> tuple[str, ...]:
    """Ключи строки результата, несущие ИМЕННО созданное. ПОЛНЫЙ ПО ПОСТРОЕНИЮ.

    🔴 БЫЛ РУКОПИСНЫМ КОРТЕЖЕМ И ТЕРЯЛ ЧЕТЫРЕ ОПЕРАЦИИ (замер 15.08.2026).
    Стояло `("id", "ids", "created_ids")`, объявленное «закрытым и неполным по
    признанию». Замер по реестру показал две вещи разом:

    * `ids` и `created_ids` не объявлены НИ ОДНИМ опом — две мёртвые строки,
      угаданные по виду имени, а не спрошенные у авторитета;
    * `segment_ids` — поле идентичности ЧЕТЫРЁХ созидающих опов
      (`create_pipe_system`, `create_room_separator`, `route_duct_system`,
      `route_pipe_system`), и его в кортеже не было. **Их созданные элементы
      не оставляли в реестре следа вовсе** — ровно та потеря, ради запрета
      которой этот модуль написан. В живом корпусе (1913 строк на 15.08) таких
      ходов **28**.

    Теперь ключи ВЫВОДЯТСЯ у реестра (`address.created_identity_fields`):
    поля `ResultSpec.identity_field` всех опов с `EffectKind.CREATE`. Новый
    созидающий оп попадает сюда сам; забыть его нельзя, потому что списка,
    который можно забыть, больше нет. Род списка сменился с «закрытый, но не
    полный» на **полный по построению**, и это разные вещи: там пустая строка
    значила «не знаем», здесь — «такого поля у реестра нет».
    """

    from kukai.ir.address import created_identity_fields

    return created_identity_fields()


def not_created_keys() -> dict[str, str]:
    """Поля идентичности, НЕ несущие созданного, — каждое с причиной.

    `deleted_id` исключён не по упущению: удалённого элемента в модели уже
    нет, следить не за чем. `moved_ids` — по той же причине с другой стороны:
    элемент существовал до хода. Реестр отвечает на «что я оставил», а не «что
    я трогал». Раньше названо было только первое, второе выпадало молча.
    """

    from kukai.ir.address import identity_field_reasons

    return identity_field_reasons()


def ledger_path() -> pathlib.Path | None:
    """Файл реестра, либо ``None`` — установки без записываемого корня.

    Явно пустое значение переменной ВЫКЛЮЧАЕТ реестр: развёртывание обязано
    иметь возможность сказать это нарочно, а не через отсутствие каталога.
    """

    if LEDGER_DIR_ENV in os.environ:
        configured = os.environ.get(LEDGER_DIR_ENV, "").strip()
        if not configured:
            return None
        return pathlib.Path(configured) / "kir_created_ids.jsonl"
    root = install_data_path("telemetry")
    if root is None:
        return None
    return root / "kir_created_ids.jsonl"


def extract_created(payload: Any) -> dict[str, list[str]]:
    """id созданного, по идентификатору опа, ИЗ ОТВЕТА МОСТА.

    Пустой словарь — законный и содержательный ответ: он значит «ход дошёл
    до исполнения и не создал ничего», что при откате есть правда.  Именно
    поэтому строка пишется всегда, а не только при непустом списке: «нет
    строки» и «строка с пустым списком» — разные факты, и первый неотличим
    от «реестр не работал».
    """

    out: dict[str, list[str]] = {}
    if not isinstance(payload, Mapping):
        return out
    keys = created_keys()
    for oid, row in payload.items():
        if not isinstance(row, Mapping):
            continue
        ids: list[str] = []
        for key in keys:
            v = row.get(key)
            if isinstance(v, (str, int)) and not isinstance(v, bool):
                ids.append(str(v))
            elif isinstance(v, Sequence) and not isinstance(v, (str, bytes)):
                ids.extend(str(x) for x in v)
        if ids:
            out[str(oid)] = ids
    return out


def _write_line(path: pathlib.Path, row: Mapping[str, Any]) -> None:
    """Дописать и ЗАФИКСИРОВАТЬ на диске: fsync файла и каталога.

    Без fsync каталога строка переживает падение процесса, но не падение
    машины — а реестр существует ровно для случаев, когда что-то оборвалось.
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        os.write(fd, line.encode("utf-8"))
        os.fsync(fd)
    finally:
        os.close(fd)
    dfd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(dfd)
    finally:
        os.close(dfd)


def record_created(
    payload: Any,
    *,
    query_id: str = "",
    turn_id: str = "",
    action_id: str = "",
    revit_version: str = "",
    plan_digest: str = "",
    family: str = "",
    ts: str = "",
) -> dict[str, Any] | None:
    """Записать созданное. Никогда не бросает; возвращает записанную строку.

    Возврат ``None`` значит РОВНО ОДНО: реестр выключен или установка не
    владеет записываемым корнем.  Неудача записи возвращает строку и кладёт
    причину в соседний файл — чтобы «не писали» и «не смогли записать» не
    выглядели одинаково.
    """

    created = extract_created(
        payload.get("result", payload) if isinstance(payload, Mapping)
        else payload)
    if not ts:
        # Метку ставит РЕЕСТР, а не вызывающий: у строки, чья дата приходит
        # снаружи, дата — свойство звонящего, а не события. Параметр остаётся
        # ради тестов, которым нужна воспроизводимая строка.
        from datetime import datetime, timezone
        ts = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    row: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "ts": ts,
        "query_id": query_id,
        "turn_id": turn_id,
        "action_id": action_id,
        "revit_version": revit_version,
        "plan_digest": plan_digest,
        "family": family,
        "created": created,
        "created_count": sum(len(v) for v in created.values()),
    }
    path = ledger_path()
    if path is None:
        return None
    try:
        _write_line(path, row)
    except Exception as exc:  # noqa: BLE001 — запись в Revit уже состоялась
        logger.error("created_ledger: строку не записать (%s): %s",
                     path, exc)
        try:
            _write_line(path.with_suffix(".errors.jsonl"),
                        {"schema_version": SCHEMA_VERSION, "ts": ts,
                         "query_id": query_id, "error": str(exc)[:300],
                         "created_count": row["created_count"]})
        except Exception:  # noqa: BLE001 — больше сделать нечего
            logger.exception("created_ledger: и файл ошибок недоступен")
    return row


__all__ = ["LEDGER_DIR_ENV", "SCHEMA_VERSION", "created_keys",
           "extract_created", "ledger_path", "not_created_keys",
           "record_created"]
