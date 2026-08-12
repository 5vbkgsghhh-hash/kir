"""KIR witness telemetry — эмпирическая семантика Revit из прода (волна A6).

Каждое ЖИВОЕ исполнение KIR-программы уже возвращает witness-ридбэк — но он
умирал в ответе инструмента. Этот модуль персистит тройки
(op-скелет, версия, witness/violations) в append-only JSONL: накапливается
корпус реального поведения Revit по версиям (фактические допуски, причуды API,
частоты отказов) — каждый прод-запуск становится тестом. Консюмер (приоры
толерансов) — отдельная волна.

Дисциплина coverage_feed: fail-open целиком (сбой записи никогда не ломает
turn), никаких сырых координат — только скелет-хэш параметров (числа → "#",
как в compile_cache-нормализаторе, но над JSON), кап на размер записи.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
from datetime import datetime, timezone
from typing import Any, Mapping, Optional

from kukai.ir.install_paths import install_data_path

try:  # Linux production; tests keep a portable no-op fallback.
    import fcntl
except ImportError:  # pragma: no cover - Windows development only
    fcntl = None

logger = logging.getLogger(__name__)

_ENV = "KIR_WITNESS_PATH"
# §18.5: отсутствие пути = фид ВЫКЛЮЧЕН, а не запись в чужую ФС.
_DEFAULT = None
# Фолбэк оставлен потому, что KIR_WITNESS_PATH нет в прод-.env, а .env трогать
# нельзя: без него корпус свидетелей на проде замолчал бы молча. Раньше признаком
# служил isdir("/opt/kukai-rebuild1") — то есть «путь есть НА МАШИНЕ», а не «мы из
# него запущены»; замер 02.08 показал, что процесс из worktree резолвился в
# ПРОДОВЫЙ корпус. Теперь адрес принадлежит установке, из которой импортирован
# модуль (install_paths — один авторитет на четыре бывшие конвенции).


def _feed_path():
    path = os.environ.get(_ENV)
    if path:
        return path
    if path is None:
        owned = install_data_path("telemetry", "kir_witness.jsonl")
        if owned is not None:
            return str(owned)
    return _DEFAULT
# Потолок записи обязан покрывать САМУЮ БОЛЬШУЮ исполнимую программу, иначе
# корпус меряет её долю. Замерено 31.07 живым кругом по образцу Snowdon: 26
# чанков, 6344 исполнения, в журнал попало 833 — треть. Из-за этого
# `create_duct` не добрал свидетельств (34 записанных против 181
# исполненного) и не перешагнул 95%, НЕ ОТКАЗАВ НИ РАЗУ. Компилятор отработал
# безупречно; недобрал измеритель — третий раз за день.
#
# Планка не на глаз: `MAX_VALIDATED_OPS` — потолок программы после раскрытия
# макросов, то есть по построению ничто исполнимое больше не бывает. Импорт
# отложен внутрь, чтобы телеметрия не тянула компилятор при загрузке.
#
# Цена замерена, а не оценена: строка на 250 операций весит ~25 КБ, весь круг
# ~640 КБ при нынешнем корпусе в мегабайт. Скелет-хэши и «числа → #»
# сохраняются — координаты по-прежнему не покидают модель.
def _max_ops_per_record() -> int:
    try:
        from kukai.ir.compiler import MAX_VALIDATED_OPS
        return int(MAX_VALIDATED_OPS)
    except Exception:  # noqa: BLE001 — телеметрия не имеет права падать
        return 320


_MAX_OPS_PER_RECORD = _max_ops_per_record()
_MAX_VIOLATIONS = 10
#: Потолок ОДНОЙ строки свободного текста в записи. Не новый: ровно столько
#: корпус хранит у каждого нарушения с самого появления фида
#: (`violations` = `str(v)[:200]`), и личность отказа едет по той же мерке —
#: заводить второй потолок для текста той же природы значило бы иметь две
#: дисциплины размера вместо одной.
_MAX_TEXT = 200
_WRITE_LOCK = threading.Lock()
_ZERO_CHECKSUM = "0" * 64


class WitnessChainError(ValueError):
    """The v2 witness telemetry checksum chain is malformed or modified."""


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _row_checksum(previous: str, body: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        previous.encode("ascii") + b"\0" + _canonical(dict(body))
    ).hexdigest()


def _acceptance_summary(value: Any) -> dict[str, Any] | None:
    """Index immutable evidence without copying model scope names."""

    if not isinstance(value, Mapping):
        return None
    summary = {}
    for key in (
        "schema_version", "state", "reason", "run_id", "evidence_digest",
        "registration_digest", "expectation_digest",
        "mutation_expectation_digest", "plan_digest", "revit_version",
        "journal_checksum", "journal_finalized",
    ):
        item = value.get(key)
        if isinstance(item, str):
            summary[key] = item[:128]
        elif key == "journal_finalized" and isinstance(item, bool):
            summary[key] = item
    registration = value.get("registration")
    if isinstance(registration, Mapping):
        for key in ("run_id", "plan_digest", "expectation_digest"):
            item = registration.get(key)
            if isinstance(item, str):
                summary.setdefault(key, item[:128])
    journal = value.get("journal")
    if isinstance(journal, Mapping):
        summary["journal"] = {
            key: journal[key]
            for key in ("durable", "run_id", "sequence", "checksum")
            if key in journal and isinstance(
                journal[key], (str, int, bool))
        }
    return summary or None


def _last_chain_state(handle) -> tuple[str, bool]:
    """Return (previous checksum, reset marker) under the file lock."""

    handle.seek(0)
    last = None
    for line in handle:
        if line.strip():
            last = line
    if last is None:
        return _ZERO_CHECKSUM, False
    try:
        row = json.loads(last)
    except json.JSONDecodeError as exc:
        raise WitnessChainError("witness feed has an invalid JSON tail") from exc
    if not isinstance(row, dict) or row.get("v") != 2:
        # A v1 prefix remains readable, but v2 explicitly names the new chain
        # segment instead of pretending the legacy row had a checksum.
        return _ZERO_CHECKSUM, True
    checksum = row.get("checksum")
    if (not isinstance(checksum, str) or len(checksum) != 64
            or any(char not in "0123456789abcdef" for char in checksum)):
        raise WitnessChainError("witness feed tail checksum is malformed")
    body = {key: value for key, value in row.items() if key != "checksum"}
    previous = body.get("prev_checksum")
    if not isinstance(previous, str) or _row_checksum(previous, body) != checksum:
        raise WitnessChainError("witness feed tail checksum is invalid")
    return checksum, False


def verify_witness_chain(path: str) -> int:
    """Verify every v2 segment in a mixed legacy/v2 witness log."""

    expected = _ZERO_CHECKSUM
    after_legacy = False
    verified = 0
    with open(path, "r", encoding="utf-8") as source:
        for index, line in enumerate(source):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise WitnessChainError(
                    f"invalid witness JSON at row {index}") from exc
            if not isinstance(row, dict) or row.get("v") != 2:
                expected = _ZERO_CHECKSUM
                after_legacy = True
                continue
            checksum = row.get("checksum")
            body = {key: value for key, value in row.items()
                    if key != "checksum"}
            previous = body.get("prev_checksum")
            reset = body.get("chain_reset") is True
            if after_legacy and not reset:
                raise WitnessChainError(
                    f"v2 row {index} failed to name its legacy chain reset")
            if not after_legacy and reset:
                raise WitnessChainError(
                    f"v2 row {index} contains an unexplained chain reset")
            if previous != expected:
                raise WitnessChainError(
                    f"witness checksum chain broke at row {index}")
            if (not isinstance(checksum, str)
                    or _row_checksum(expected, body) != checksum):
                raise WitnessChainError(
                    f"witness row {index} was modified")
            expected = checksum
            after_legacy = False
            verified += 1
    return verified


def _skeleton(value: Any) -> Any:
    """Числовые листья → "#" (координаты/размеры не покидают модель),
    структура/строки-селекторы сохраняются — этого достаточно, чтобы ключевать
    поведение «формы» опа без утечки геометрии заказчика."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return "#"
    if isinstance(value, dict):
        return {k: _skeleton(v) for k, v in sorted(value.items())}
    if isinstance(value, list):
        return [_skeleton(v) for v in value]
    return value


def _op_id(op: Any) -> Optional[str]:
    """Идентификатор операции — то, чем адресуются `op_outcomes` и
    `violations`.

    31.07: без него корпус НЕ УМЕЛ назвать отказавшую операцию. Строка знала,
    что в программе были `create_wall` и `create_door`, и отдельно знала, что
    нарушение принадлежит `PD`, — а связать одно с другим было нечем, и провал
    приходилось приписывать обеим. Так `create_wall` и вышел 64.2% при
    построенной стене.

    Утечки не добавляет: те же идентификаторы уже лежат в `op_outcomes` и
    дословно внутри `violations`. Кап тот же, что у ключей `op_outcomes`."""
    if not isinstance(op, dict):
        return None
    raw = op.get("id")
    return str(raw)[:64] if raw is not None else None


def op_skeleton_hash(op: Any) -> str:
    """Стабильный скелет-хэш одного опа (без volatile id).

    id намеренно ИСКЛЮЧЁН: скелет обязан пережить переименование операции.
    Поэтому идентификатор пишется РЯДОМ с хэшем, а не внутрь него."""
    if not isinstance(op, dict):
        return "malformed"
    body = {k: v for k, v in op.items() if k != "id"}
    blob = json.dumps(_skeleton(body), ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:16]


def _text(value: Any) -> Optional[str]:
    """Одна строка свободного текста для корпуса, или None — «нечего писать».

    Пустая строка НЕ пишется: поле, присутствующее и пустое, читалось бы как
    «причина была и она пуста», а это третий факт, которого никто не сообщал.
    """
    if value is None:
        return None
    text = str(value).strip()
    return text[:_MAX_TEXT] if text else None


#: Значения `refusal_cause` — ГДЕ в этой строке лежит причина красноты.
#:
#: Поле пишется ТОЛЬКО у не-зелёной строки: у успеха причины нет, и «отсутствие
#: причины» — не значение, а отсутствие. Зелёная строка обязана остаться
#: побайтно прежней (закон «absent stays absent»), поэтому здесь нет варианта
#: «none».
_CAUSE_DIAGNOSTIC = "diagnostic"    # причина названа кодом: `diag_code` и рядом
_CAUSE_VIOLATIONS = "violations"    # причина названа нарушениями постусловий
_CAUSE_ACCEPTANCE = "acceptance"    # коммит состоялся; красноту дала приёмка
_CAUSE_UNKNOWN = "unknown"          # НАЗВАННОЕ НЕЗНАНИЕ, см. блок ниже


def record_witness(*, program: Any, family: str, revit_version: str,
                   ok: bool, witness: Optional[dict], duration_ms: float,
                   diag_code: Optional[str] = None,
                   diag_op_id: Optional[str] = None,
                   diag_field: Optional[str] = None,
                   diag_message: Optional[str] = None,
                   diag_detail: Optional[str] = None,
                   violations: Optional[list] = None,
                   result_payload: Optional[dict] = None,
                   outcome: Optional[dict] = None,
                   acceptance_evidence: Optional[Mapping[str, Any]] = None,
                   author_digest: Optional[str] = None,
                   env_digest: Optional[str] = None,
                   ) -> None:
    """Записать одно ЖИВОЕ исполнение. Никогда не raises (fail-open)."""
    path = _feed_path()
    if not path:
        return
    try:
        from kukai.ir.midend import PLAN_SCHEMA, PlannedProgram
        planned = program if isinstance(program, PlannedProgram) else None
        raw_ops = (planned.to_ops() if planned is not None else
                   (program.get("ops") if isinstance(program, dict) else None) or [])
        ops = [{"op": o.get("op"), "id": _op_id(o), "skel": op_skeleton_hash(o)}
               for o in raw_ops[:_MAX_OPS_PER_RECORD] if isinstance(o, dict)]
        record: dict[str, Any] = {
            "v": 2,
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "source": "kir-witness",
            "revit_version": revit_version,
            "family": family,
            "ok": ok,
            "duration_ms": round(float(duration_ms), 1),
            "ops": ops,
        }
        if planned is not None:
            # Bind the telemetry row to the exact immutable plan lowered by
            # the compiler. No geometry is copied into the row; op skeletons
            # retain their existing numeric redaction.
            record["plan_schema"] = PLAN_SCHEMA
            record["plan_digest"] = planned.plan_digest
            record["source_op_count"] = planned.source_op_count
        # ПОДПИСЬ ИСХОДНИКА, ПОРОДИВШЕГО ПРОГРАММУ. Едет рядом с `plan_digest`
        # и ровно по тем же правилам: `plan_digest` отвечает «что было
        # скомпилировано», `author_digest` — «чем это написано». Поля нет
        # вовсе, когда программу написали операциями: пустая строка в корпусе
        # читалась бы как «скрипт был и не подписался».
        if isinstance(author_digest, str) and author_digest:
            record["author_digest"] = author_digest[:128]
            record["authored_in"] = "python"
        # ПОДПИСЬ СРЕДЫ — третье звено того же ряда. `plan_digest` отвечает
        # «что скомпилировано», `author_digest` — «чем это написано»,
        # `env_digest` — «на чём посчитано». Корпус append-only и переживает
        # обновления библиотек; без этого поля два ряда одного скрипта с
        # разными исходами неотличимы от недетерминизма, а причиной был апгрейд
        # shapely. Поля нет вовсе, когда программу написали операциями.
        if isinstance(env_digest, str) and env_digest:
            record["env_digest"] = env_digest[:128]
        if len(raw_ops) > _MAX_OPS_PER_RECORD:
            record["ops_truncated"] = len(raw_ops) - _MAX_OPS_PER_RECORD
        if witness is not None:
            record["witness"] = witness
        if isinstance(outcome, dict):
            # The outcome is the closed KIR wire contract, not an inferred
            # restatement of ``ok``.  In particular ``committed`` may coexist
            # with ``ok=false`` when a report-mode witness was violated.
            record["outcome"] = dict(outcome)
        acceptance = _acceptance_summary(acceptance_evidence)
        if acceptance is not None:
            record["acceptance_evidence"] = acceptance
        if diag_code is not None:
            record["diag_code"] = diag_code
        # ОПЕРАЦИЯ, КОТОРУЮ ДИАГНОСТИКА УЖЕ НАЗВАЛА.
        #
        # `serving._translate_runtime` кладёт `op_id` в диагностику, когда
        # рантайм его сообщил, — а телеметрия брала оттуда ОДИН код и адрес
        # выбрасывала. Цена замерена 09.08 на корпусе: 181 живая красная
        # строка несёт X003/X999 — коды, которые по построению не называют
        # виновного (различающий признак живёт в `detail`, а `detail` в корпус
        # не пишется). Все они уходят в «неприписываемо», и восстановить их
        # нечем. Поле стоит здесь, чтобы у следующих строк такой дыры не было;
        # утечки оно не добавляет — те же идентификаторы уже лежат в
        # `op_outcomes` и дословно внутри `violations`.
        if diag_op_id is not None:
            record["diag_op_id"] = str(diag_op_id)[:64]
        # ─── ЛИЧНОСТЬ ОТКАЗА ЦЕЛИКОМ, А НЕ ОДИН ЕЁ КОД ──────────────────────
        #
        # ЧТО ИЗМЕРЕНО (09.08.2026, перечислением ВСЕХ ключей ВСЕХ 1306 строк
        # `kir_witness.jsonl`): ни одна строка не несёт поля с сообщением
        # отказа — никакого. Следствие, тоже замеренное: из 204 красных строк
        # 165 неприписываемы ПО ПОСТРОЕНИЮ (79 X999, 41 unconfirmed, 38 X003,
        # 7 разноимённых без id). У X003 и X999 различающий признак живёт
        # РОВНО в `detail`, а `detail` телеметрия выбрасывала — поэтому целый
        # класс расследования оставался чтением текста рядом с корпусом
        # вместо запроса к корпусу. Ровно так 04.08 родился «компилятор 5 /
        # Revit 11» по 12 отказам `create_door`: не замер, а пересказ.
        #
        # ЧТО ЗДЕСЬ ЗАПИСЫВАЕТСЯ — только то, что диагностика УЖЕ несёт
        # (`Diagnostic`: code / op_id / field_name / message_ru, плюс `detail`
        # у рантайм-перевода). Ни одного нового факта: список закрыт ЗДЕСЬ, а
        # не у вызывающего, чтобы «записать заодно» нельзя было мимоходом.
        #
        # ЧТО РЕШЕНО ПО ПРИВАТНОСТИ. Корпус дописывается навсегда и лежит на
        # проде, поэтому вопрос не «можно ли», а «что именно».
        #   * `diag_message` — НАШ текст (`message_ru`), закрытый набор строк
        #     компилятора; данных модели в нём нет по построению;
        #   * `diag_detail` — слова САМОГО рантайма, и вот в них имя семейства
        #     или уровня встречается (отказ неповорачиваемой створки называет
        #     `FamilySymbol.Family.Name`). Пишем всё равно, и вот почему это
        #     не расширение периметра: тексты `violations` — той же природы и
        #     из той же модели — корпус хранит дословно с первого дня, файл
        #     открывается 0600 на КАЖДОЙ записи и принадлежит установке
        #     (`install_paths`), а без `detail` X999 остаётся без причины
        #     навсегда. Геометрия по-прежнему не покидает модель: числа в
        #     скелетах — «#», координат тут не было и нет.
        #   * потолок — общий `_MAX_TEXT` нарушений, а не новый.
        for key, value in (("diag_field", diag_field),
                           ("diag_message", diag_message),
                           ("diag_detail", diag_detail)):
            text = _text(value)
            if text is not None:
                record[key] = text
        if violations:
            record["violations"] = [str(v)[:_MAX_TEXT]
                                    for v in violations[:_MAX_VIOLATIONS]]
            # Усечение обязано быть НАЗВАНО. Двадцатибалочная программа с
            # двадцатью нарушениями оставляла в корпусе десять и ни следа о
            # том, что были ещё, — и читалась как «столько и было».
            if len(violations) > _MAX_VIOLATIONS:
                record["violations_truncated"] = len(violations) - _MAX_VIOLATIONS
        committed = (
            isinstance(outcome, dict)
            and outcome.get("execution") == "committed"
        )
        # ─── НЕИЗВЕСТНАЯ ПРИЧИНА — ЭТО ТОЖЕ ЗАПИСЬ ──────────────────────────
        #
        # У читателя корпуса красная строка без кода и без нарушений выглядит
        # ровно как строка, у которой причину не записали, — и различить
        # «причины не было названо» от «поле забыли» нечем. Поэтому не-зелёная
        # строка ВСЕГДА говорит, ГДЕ её причина, а последнее из значений
        # называет незнание вслух: `unknown` — это утверждение, а не пробел.
        #
        # Зелёной строки это не касается ни одним байтом: у успеха причины
        # нет, и её отсутствие обязано выглядеть как отсутствие.
        if not ok:
            record["refusal_cause"] = (
                _CAUSE_DIAGNOSTIC if diag_code is not None
                else _CAUSE_VIOLATIONS if violations
                else _CAUSE_ACCEPTANCE if committed
                else _CAUSE_UNKNOWN)
        if (ok or committed) and isinstance(result_payload, dict):
            # Пост-коммитные ридбэки по опам: только НЕгеометрические факты
            # (id создан/refused) — сами координаты остаются в модели.
            per_op = {}
            for oid, row in list(result_payload.items())[:_MAX_OPS_PER_RECORD]:
                if isinstance(row, dict):
                    per_op[str(oid)[:64]] = (
                        "refused" if "refused" in row
                        else "created" if ("id" in row or "deleted_id" in row)
                        else "other")
            if per_op:
                record["op_outcomes"] = per_op
                if len(result_payload) > _MAX_OPS_PER_RECORD:
                    record["op_outcomes_truncated"] = (
                        len(result_payload) - _MAX_OPS_PER_RECORD)
        directory = os.path.dirname(path) or "."
        existed = os.path.exists(path)
        os.makedirs(directory, exist_ok=True)
        flags = os.O_RDWR | os.O_CREAT | os.O_APPEND
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(path, flags, 0o600)
        try:
            # Existing telemetry from older releases may have inherited a
            # broad umask.  It carries result ids and execution metadata, so
            # narrow it on every successful open instead of protecting only
            # new files.
            os.fchmod(descriptor, 0o600)
            handle = os.fdopen(descriptor, "a+", encoding="utf-8")
        except Exception:
            os.close(descriptor)
            raise
        with _WRITE_LOCK, handle as f:
            if fcntl is not None:
                fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                previous, chain_reset = _last_chain_state(f)
                record["prev_checksum"] = previous
                if chain_reset:
                    record["chain_reset"] = True
                record["checksum"] = _row_checksum(previous, record)
                f.seek(0, os.SEEK_END)
                f.write(_canonical(record).decode("utf-8") + "\n")
                f.flush()
                os.fsync(f.fileno())
            finally:
                if fcntl is not None:
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        if not existed and hasattr(os, "O_DIRECTORY"):
            descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
    except Exception:  # noqa: BLE001 — fail-open по контракту телеметрии
        logger.debug("kir witness telemetry write failed (fail-open)",
                     exc_info=True)


__all__ = [
    "WitnessChainError",
    "op_skeleton_hash",
    "record_witness",
    "verify_witness_chain",
]
