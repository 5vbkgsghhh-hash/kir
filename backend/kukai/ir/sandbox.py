"""KIR author-script sandbox — исполнение ПИТОНА, который пишет программу IR.

Модель пишет питон, питон исполняется здесь, до всякой компиляции, и НИКОГДА
не касается Revit. Наружу выходит ровно одна вещь: список операций IR, который
дальше идёт обычным конвейером доказательства (plan_program → ground → emit →
witness → приёмка → ворота).

ГРАНИЦА БЕЗОПАСНОСТИ — ЭТО IR-ШЛЮЗ, А НЕ ЭТА ПЕСОЧНИЦА.
Что бы скрипт ни натворил, единственный его выход — JSON программы, и этот
JSON целиком проходит типизированную проверку компилятора. Поэтому песочница
защищает БОКС (процесс, память, диск, сеть), а не модель доказательства, и её
модель угроз — ЗАПУТАВШАЯСЯ НЕЙРОСЕТЬ, а не злоумышленник: бесконечный цикл,
распухание памяти, случайное обращение к диску, недетерминизм. Что из этого
следует честно — в §«ЧЕГО ЭТА ПЕСОЧНИЦА НЕ ДЕЛАЕТ» ниже.

СЛОИ ИЗОЛЯЦИИ (снизу вверх — от жёсткого к обучающему):

  L0  ОТДЕЛЬНЫЙ ПРОЦЕСС. Родитель не заложник чужого кода: ни одного вызова
      exec() в нашем адресном пространстве. Интерпретатор фиксирован путём,
      argv — вектор (никакого shell), окружение собрано нами с нуля.
  L1  ПРОСТРАНСТВА ИМЁН (unshare user+mount+net). Сеть физически недостижима:
      в новом netns нет ни одного маршрута. Проверяется ЗАМЕРОМ на каждом
      запуске (`probe_network`), и при политике "required" недостижимость сети
      — предусловие запуска: не создалось пространство → скрипт не исполняется.
  L2  ПУСТОЙ КОРЕНЬ (chroot в пустой каталог после всех импортов). Даже код,
      сбежавший из ограниченных builtins к настоящему `open`, не найдёт ни
      одного файла: /etc/passwd не существует в его корне.
  L3  RLIMIT. RLIMIT_FSIZE=0 (писать нечего — в квитанцию идёт только IR),
      RLIMIT_AS (память), RLIMIT_CPU (процессорное время), RLIMIT_NPROC=0
      (ни fork, ни subprocess), RLIMIT_NOFILE, RLIMIT_CORE=0 (прод не должен
      получить дамп на диск).
  L4  СТЕНА. Таймаут на самом subprocess + снятие всей группы процессов.
  L5  БЕЛЫЙ СПИСОК ИМПОРТОВ (не чёрный: чёрный всегда неполон). Ровно
      math / itertools / functools + сам DSL, который отдан скрипту уже
      импортированным. Хук на __import__ скрипта + страж в sys.meta_path.
  L6  ОГРАНИЧЕННЫЕ BUILTINS. Не «удалить», а ЗАМЕНИТЬ на заглушку, которая
      объясняет, почему имени нет: NameError ничему не учит.
  L7  ТИПИЗИРОВАННЫЙ ОТКАЗ. Питоновское исключение НИКОГДА не выходит наружу
      сырым трейсбеком: код KIR-B*, род исключения, сообщение, НОМЕР СТРОКИ В
      ИСХОДНИКЕ МОДЕЛИ и сама строка. Кадры нашего конвейера в отказ не идут —
      модели чинить надо СВОЙ код.
  L8  ЭКРАН ВЫХОДА. Отдельный канал результата (не stdout: мусор от print не
      может испортить разбор), проверка JSON-представимости с указанием пути,
      потолок на число операций и байты, экран недетерминизма (адрес объекта
      в выходе), опциональная ПОВТОРНАЯ прогонка с сверкой дайджеста.

ПОЧЕМУ НЕДЕТЕРМИНИЗМ ЗАПРЕЩЁН ЖЁСТКО, А НЕ ПО ВКУСУ: исходник скрипта
подписывается в квитанции (`author_digest` ниже). Подпись недетерминированного
скрипта не подписывает ничего — при повторной прогонке она удостоверяет другую
программу. Отсюда: запрещены random/time/datetime/os/secrets/uuid, фиксирован
PYTHONHASHSEED=0 (порядок обхода множеств строк), убран id().

ЧЕГО ЭТА ПЕСОЧНИЦА НЕ ДЕЛАЕТ (честно, потому что настоящая граница — шлюз):
  * не является защитой от целенаправленного побега из ограниченных builtins.
    Классический путь `().__class__.__base__.__subclasses__()` → чужие
    `__globals__` → настоящий `__import__` в CPython не закрывается ничем,
    кроме отдельного интерпретатора. Он и не закрывается: сбежавший код
    оказывается в пустом корне, без сети, без права записи, без fork, с
    потолком CPU и памяти — и с единственным выходом через IR-шлюз;
  * не мешает скрипту выдать СЕМАНТИЧЕСКИ дурную программу: это работа
    plan_program/ground/приёмки, а не песочницы;
  * не ловит недетерминизм, не оставляющий следа в выходе (например ветвление
    по repr объекта, дающее один и тот же ответ). Опция `replay_check`
    ловит только то, что меняет ВЫХОД, и это всё, что вообще наблюдаемо;
  * RLIMIT_AS ограничивает адресное пространство, а не RSS: пиковый RSS
    ребёнка меряется отдельно (`peak_rss_kb`) и в отчёт идёт замером.

КОНТРАКТ С ЯЗЫКОМ (`kukai/ir/dsl.py`, пишет другой агент):
  «исполнить исходник — вернуть список операций либо типизированный отказ».
  Песочница НЕ знает грамматики языка. Она:
    1. импортирует модуль языка ДО изоляции и кладёт его публичные имена прямо
       в пространство скрипта (плюс алиас `kir`), поэтому импорт языка скрипту
       не нужен и запрещён;
    2. после исполнения собирает программу первым сработавшим способом:
       drain-функция языка (`_DRAIN_CANDIDATES`, живой носитель —
       `dsl.take_ops()`) → СОБСТВЕННАЯ переменная скрипта (`ops`/`program`/…)
       → вызов `build()`. «Собственная» проверяется тождеством: `ops` из языка
       инжектировано всегда, и принять его за переменную автора значило бы
       превратить «скрипт ничего не собрал» в «скрипт вернул функцию»;
    3. приводит операции к JSON и отдаёт наверх вместе с конвертом
       (`ir_version`/`intent`/`defaults`/`allow_destructive`).
  Модули (ModuleType) из пространства языка НЕ инжектируются никогда: если
  dsl.py делает `import os`, скрипт не получит `os` через чёрный ход.

ЦЕНА (замер 03.08 на прод-боксе, python3.12): счастливый путь на 40 операций —
121 мс медиана, пик RSS 24 МБ; программа на 104 операции — 170 мс. Параллельные
запуски стоят линейно: N × (memory_mb + ~21 МБ интерпретатора), и это единственное,
за чем должен следить вызывающий, если решит гонять песочницу пачкой.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from kukai.ir.diag import (
    Diagnostic,
    SANDBOX_BAD_RESULT,
    SANDBOX_CRASH,
    SANDBOX_FORBIDDEN_BUILTIN,
    SANDBOX_FORBIDDEN_IMPORT,
    SANDBOX_MEMORY,
    SANDBOX_NONDETERMINISM,
    SANDBOX_NO_OPS,
    SANDBOX_OUTPUT_LIMIT,
    SANDBOX_RUNTIME,
    SANDBOX_SYNTAX,
    SANDBOX_TIMEOUT,
    SANDBOX_UNAVAILABLE,
)

# ─────────────────────────────────────────────────────────────────────────────
# Константы контракта
# ─────────────────────────────────────────────────────────────────────────────

#: Имя, под которым исходник модели виден интерпретатору. Служебное: по нему
#: отбираются кадры трейсбека, принадлежащие МОДЕЛИ, и отбрасываются наши.
SCRIPT_FILENAME = "<kir-script>"

#: Ровно то, что разрешено импортировать. Белый список, не чёрный.
ALLOWED_IMPORTS: tuple[str, ...] = ("math", "itertools", "functools")

#: ПЕРЕКЛЮЧАТЕЛИ ОПЕРАТОРА, доезжающие до ребёнка. Белый список, не чёрный, и
#: короткий намеренно: окружение ребёнка собирается нами с нуля, а не
#: наследуется, поэтому «забыли перенести» здесь выглядит как «оператор
#: выключил» — молчаливое несогласие со службой, которое никак не наблюдаемо.
#: Скрипту они не видны: `os` ему недоступен ни импортом, ни инжекцией.
#: Детерминизм не страдает — это положение тумблера, а не время и не случайность.
ENV_PASSTHROUGH: tuple[str, ...] = ("KUKAI_CHECKER_V2",)
_ENV_PASSTHROUGH = ENV_PASSTHROUGH

#: Транспортный потолок песочницы. НЕ путать с бюджетами компилятора
#: (MAX_OPS_PER_PROGRAM=20 авторский / MAX_VALIDATED_OPS=320 послемакросный):
#: те считаются ПОЗЖЕ и меряют замысел автора, а этот меряет трубу.
MAX_SCRIPT_OPS = 5000
MAX_RESULT_BYTES = 8 * 1024 * 1024
MAX_SOURCE_BYTES = 256 * 1024
MAX_STDOUT_CHARS = 4000
MAX_JSON_DEPTH = 32

#: Умолчания ресурсов. Подобраны так, чтобы прод-бокс не заметил запуска:
#: 256 МБ адресного пространства — это ~254 МБ пикового RSS в худшем случае
#: (замер: распухание строкой упирается ровно в предел).
DEFAULT_CPU_SECONDS = 5.0
DEFAULT_WALL_SECONDS = 8.0
DEFAULT_MEMORY_MB = 256
DEFAULT_RECURSION_LIMIT = 500
DEFAULT_NOFILE = 64

#: Порядок опроса языка: первая сработавшая функция забирает накопленные опы.
_DRAIN_CANDIDATES = ("take_ops", "drain_ops", "drain", "collect_ops",
                     "collect", "pop_ops", "emitted_ops", "flush_ops")
#: Переменные скрипта, в которых может лежать готовая программа.
_NS_CANDIDATES = ("ops", "OPS", "program", "PROGRAM", "result", "RESULT")
#: Функции скрипта, которые вернут программу, если она не в переменной.
_BUILD_CANDIDATES = ("build", "build_program", "main")

#: Поля конверта программы, которые скрипт вправе выставить сам. Совпадают с
#: `known_top` компилятора: конверт должен доезжать целиком, иначе вызывающий
#: пересобирает его на глазок и теряет то, что автор указал явно.
_ENVELOPE_KEYS = ("ir_version", "intent", "defaults", "allow_destructive")

#: След дефолтного repr — адрес объекта. Единственный вид недетерминизма,
#: который ВИДЕН в выходе, поэтому он и ловится экраном, а не проповедью.
_ADDRESS_RE = re.compile(r"<[^<>]{0,120}?\bat 0x[0-9a-fA-F]{4,}>")

_CLONE_NEWNS = 0x00020000
_CLONE_NEWUSER = 0x10000000
_CLONE_NEWNET = 0x40000000


# ─────────────────────────────────────────────────────────────────────────────
# Политика
# ─────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class SandboxPolicy:
    """Что именно разрешено этому запуску. Всё числовое — здесь, чтобы отказ
    мог НАЗВАТЬ исчерпанный предел, а не сказать «слишком много»."""

    cpu_seconds: float = DEFAULT_CPU_SECONDS
    wall_seconds: float = DEFAULT_WALL_SECONDS
    memory_mb: int = DEFAULT_MEMORY_MB
    max_ops: int = MAX_SCRIPT_OPS
    max_result_bytes: int = MAX_RESULT_BYTES
    max_source_bytes: int = MAX_SOURCE_BYTES
    max_stdout_chars: int = MAX_STDOUT_CHARS
    recursion_limit: int = DEFAULT_RECURSION_LIMIT
    nofile: int = DEFAULT_NOFILE
    allowed_imports: tuple[str, ...] = ALLOWED_IMPORTS

    #: "required"  — нет сетевого пространства имён ⇒ запуск отменяется
    #:               (fail-closed: обещание «ноль сети» либо доказано, либо нет);
    #: "best_effort" — пробуем, при отказе ядра работаем дальше и пишем это
    #:               в `isolation` честно;
    #: "off"       — не трогать пространства имён (для боксов без userns).
    network: str = "required"
    #: chroot в пустой каталог после импортов. Выключается, если язык
    #: докладывает ЛЕНИВЫЙ импорт (см. KIR-B012: отказ назовёт этот тумблер).
    filesystem_isolation: bool = True
    #: Замер сети на каждом запуске вместо намерения.
    probe_network: bool = True
    #: Прогнать скрипт дважды и сверить дайджест программы. Дорого вдвое,
    #: зато превращает «недетерминизм запрещён» из правила в замер.
    replay_check: bool = False

    #: Модуль, публичные имена которого кладутся в пространство скрипта.
    #:
    #: `course.language` — это `dsl` ПЛЮС четыре имени курса (`course`,
    #: `recipe`, `score`, `unit`), склеенные без собственной семантики. Язык от
    #: этого не меняется: скрипт, написанный под `kukai.ir.dsl`, работает здесь
    #: без единой правки — объекты функций те же.
    #:
    #: ПОЧЕМУ УМОЛЧАНИЕ, А НЕ ОПЦИЯ. Курс за выключателем — это курс, которого
    #: для модели не существует; сегодня же измерено, чем такое кончается:
    #: `create_group` вызван НОЛЬ раз на 51 574 поднятых операции, а `sdk.py`
    #: пролежал отличным и недостижимым пять недель. Способность, до которой
    #: нет пути от настоящей точки входа, не существует (закон достижимости,
    #: `tests/capability_reachability`).
    #:
    #: Цена постоянного присутствия замерена и мала: указатель 176 токенов,
    #: типичный запрос урока ~1 076, весь курс 10 808 — против 7 140 у
    #: `skill.py`, которые платятся КАЖДЫМ запросом.
    dsl_module: str = "kukai.ir.course.language"
    extra_sys_path: tuple[str, ...] = ()
    python_exe: str = ""

    def child_config(self) -> dict:
        return {
            "cpu_seconds": self.cpu_seconds,
            "wall_seconds": self.wall_seconds,
            "memory_mb": self.memory_mb,
            "max_ops": self.max_ops,
            "max_result_bytes": self.max_result_bytes,
            "max_stdout_chars": self.max_stdout_chars,
            "recursion_limit": self.recursion_limit,
            "nofile": self.nofile,
            "allowed_imports": list(self.allowed_imports),
            "network": self.network,
            "filesystem_isolation": self.filesystem_isolation,
            "probe_network": self.probe_network,
            "dsl_module": self.dsl_module,
            "extra_sys_path": list(self.extra_sys_path),
        }


DEFAULT_POLICY = SandboxPolicy()


# ─────────────────────────────────────────────────────────────────────────────
# Отказ
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class SandboxRefusal:
    """Типизированный отказ песочницы.

    `message_ru` — ровно то, что увидит модель. Внутренних кадров в нём нет
    никогда; операторская подробность живёт в `detail` и наверх не показывается.
    """

    code: str
    message_ru: str
    kind: str                       # род: имя класса исключения либо механизм
    #: чья это ошибка. "author" — чинит модель; "sandbox" — чиним мы;
    #: "unknown" — процесс умер, не сказав.
    blame: str = "author"
    line: Optional[int] = None      # НОМЕР СТРОКИ В ИСХОДНИКЕ МОДЕЛИ
    line_text: Optional[str] = None
    #: цепочка строк скрипта снизу вверх (вызвана из…), только кадры модели
    script_frames: list[int] = field(default_factory=list)
    detail: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        out = {
            "code": self.code,
            "message_ru": self.message_ru,
            "kind": self.kind,
            "blame": self.blame,
        }
        if self.line is not None:
            out["line"] = self.line
        if self.line_text is not None:
            out["line_text"] = self.line_text
        if self.script_frames:
            out["script_frames"] = list(self.script_frames)
        if self.detail:
            out["detail"] = dict(self.detail)
        return out

    def render(self) -> str:
        """Текст отказа глазами модели: код, суть, место."""
        head = f"{self.code}: {self.message_ru}"
        if self.line is not None:
            text = (self.line_text or "").strip()
            head += f"\nстрока {self.line}"
            if text:
                head += f": {text}"
            if len(self.script_frames) > 1:
                chain = " ← ".join(str(n) for n in reversed(self.script_frames))
                head += f"\nцепочка строк скрипта: {chain}"
        return head

    def to_diagnostic(self) -> Diagnostic:
        """Проекция на общий конверт диагностик компилятора."""
        return Diagnostic(code=self.code, message_ru=self.render())

    @classmethod
    def from_dict(cls, raw: dict) -> "SandboxRefusal":
        return cls(
            code=str(raw.get("code") or SANDBOX_UNAVAILABLE),
            message_ru=str(raw.get("message_ru") or ""),
            kind=str(raw.get("kind") or "unknown"),
            blame=str(raw.get("blame") or "unknown"),
            line=raw.get("line"),
            line_text=raw.get("line_text"),
            script_frames=list(raw.get("script_frames") or []),
            detail=dict(raw.get("detail") or {}),
        )


@dataclass
class SandboxResult:
    """Итог исполнения: либо операции, либо отказ. Третьего нет."""

    ok: bool
    ops: list[dict] = field(default_factory=list)
    refusal: Optional[SandboxRefusal] = None
    #: подпись ТОЧНЫХ байт исходника — то, что уходит в квитанцию
    author_digest: str = ""
    #: дайджест выданной программы: сверяется при replay_check
    program_digest: str = ""
    #: конверт, если скрипт его выставил (intent/defaults/allow_destructive)
    envelope: dict = field(default_factory=dict)
    #: что скрипт напечатал. Это ОБРАТНАЯ СВЯЗЬ модели, а не канал результата:
    #: результат идёт отдельным дескриптором и мусором из print не портится.
    stdout: str = ""
    #: ЗАМЕРЕННОЕ (не задуманное) состояние изоляции этого запуска
    isolation: dict = field(default_factory=dict)
    duration_s: float = 0.0
    #: пик RSS ИМЕННО ЭТОГО запуска (`VmHWM` ребёнка, КБ). Ноль — значит
    #: ребёнок умер, не сказав: врать родительским водоразделом нельзя, он
    #: зависит от того, кто бежал раньше (см. `_read_vm_hwm`).
    peak_rss_kb: int = 0

    def as_dict(self) -> dict:
        out = {
            "ok": self.ok,
            "author_digest": self.author_digest,
            "program_digest": self.program_digest,
            "op_count": len(self.ops),
            "isolation": self.isolation,
            "duration_s": round(self.duration_s, 4),
            "peak_rss_kb": self.peak_rss_kb,
        }
        if self.ok:
            out["ops"] = self.ops
            if self.envelope:
                out["envelope"] = self.envelope
        elif self.refusal is not None:
            out["refusal"] = self.refusal.as_dict()
        if self.stdout:
            out["stdout"] = self.stdout
        return out


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _program_digest(ops: list, envelope: dict) -> str:
    payload = json.dumps({"ops": ops, "envelope": envelope},
                         ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"), allow_nan=False)
    return _digest(payload.encode("utf-8"))


# ─────────────────────────────────────────────────────────────────────────────
# РОДИТЕЛЬ
# ─────────────────────────────────────────────────────────────────────────────

def _backend_root() -> str:
    # .../backend/kukai/ir/sandbox.py → .../backend
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _refuse(code: str, message: str, *, kind: str, blame: str = "author",
            **detail: Any) -> SandboxRefusal:
    return SandboxRefusal(code=code, message_ru=message, kind=kind, blame=blame,
                          detail=detail)


def execute_author_script(source: str,
                          *,
                          policy: SandboxPolicy = DEFAULT_POLICY) -> SandboxResult:
    """Исполнить исходник модели и вернуть операции IR либо типизированный отказ.

    Единственная публичная точка. Ничего не бросает наружу: любой сбой —
    включая наш собственный — приходит как `SandboxResult(ok=False, refusal=…)`.
    """
    started = time.perf_counter()
    digest = _digest(source.encode("utf-8", "surrogatepass"))

    if not source.strip():
        return SandboxResult(
            ok=False, author_digest=digest,
            duration_s=time.perf_counter() - started,
            refusal=_refuse(
                SANDBOX_NO_OPS,
                "исходник пуст: скрипт обязан собрать хотя бы одну операцию IR",
                kind="EmptySource"),
        )

    raw = source.encode("utf-8", "surrogatepass")
    if len(raw) > policy.max_source_bytes:
        return SandboxResult(
            ok=False, author_digest=digest,
            duration_s=time.perf_counter() - started,
            refusal=_refuse(
                SANDBOX_OUTPUT_LIMIT,
                f"исходник {len(raw)} байт при пределе {policy.max_source_bytes}: "
                f"скрипт, который пишет программу, столько не весит — "
                f"вероятно, в него вклеены данные вместо кода",
                kind="SourceTooLarge",
                source_bytes=len(raw), limit=policy.max_source_bytes),
        )

    first = _run_once(raw, policy)
    first.author_digest = digest
    first.duration_s = time.perf_counter() - started

    if first.ok and policy.replay_check:
        second = _run_once(raw, policy)
        if not second.ok:
            second.author_digest = digest
            second.duration_s = time.perf_counter() - started
            return second
        if second.program_digest != first.program_digest:
            first.ok = False
            first.refusal = _refuse(
                SANDBOX_NONDETERMINISM,
                "две прогонки одного исходника дали РАЗНЫЕ программы. "
                "Подпись исходника (author_digest) в этом случае не удостоверяет "
                "ничего. Ищите источник разброса: обход множества/словаря, "
                "сравнение объектов по адресу, попытку взять время или случайность",
                kind="ReplayMismatch", blame="author",
                digest_run1=first.program_digest, digest_run2=second.program_digest)
            first.ops = []
        first.isolation = dict(first.isolation)
        first.isolation["replay_checked"] = True
        first.duration_s = time.perf_counter() - started

    return first


def _run_once(raw_source: bytes, policy: SandboxPolicy) -> SandboxResult:
    """Один запуск ребёнка. Возвращает результат ЛЮБОЙ ценой, без исключений."""
    import resource  # локально: родителю он нужен только для замера

    exe = policy.python_exe or sys.executable
    read_fd, write_fd = os.pipe()
    jail = tempfile.mkdtemp(prefix="kir_jail_")

    env = {
        "PYTHONPATH": os.pathsep.join([_backend_root(), *policy.extra_sys_path]),
        # ДЕТЕРМИНИЗМ: без этого порядок обхода множеств строк меняется от
        # запуска к запуску, и подпись исходника перестаёт что-либо значить.
        "PYTHONHASHSEED": "0",
        "PYTHONIOENCODING": "utf-8",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
        "LC_ALL": "C.UTF-8",
        "TZ": "UTC",
        "PATH": "",
        "KIR_SANDBOX_CFG": json.dumps(policy.child_config()),
        "KIR_SANDBOX_RESULT_FD": str(write_fd),
        "KIR_SANDBOX_JAIL": jail,
    }
    # Переключатели оператора — см. ENV_PASSTHROUGH. Окружение ребёнка собрано
    # нами с нуля: не перенесённый тумблер здесь читается как «выключен».
    for name in ENV_PASSTHROUGH:
        value = os.environ.get(name)
        if value is not None:
            env[name] = value
    argv = [exe, "-s", "-B", "-c",
            "import kukai.ir.sandbox as _s; _s._child_main()"]

    rss_before = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    chunks: list[bytes] = []

    def _drain() -> None:
        try:
            while True:
                block = os.read(read_fd, 65536)
                if not block:
                    break
                chunks.append(block)
        except OSError:
            pass

    reader = threading.Thread(target=_drain, daemon=True)
    proc = None
    timed_out = False
    stderr_text = ""
    try:
        try:
            proc = subprocess.Popen(
                argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, env=env, cwd=jail,
                pass_fds=(write_fd,), start_new_session=True,
                close_fds=True,
            )
        except OSError as exc:
            return SandboxResult(ok=False, refusal=_refuse(
                SANDBOX_UNAVAILABLE,
                "песочница не запустилась: интерпретатор не стартовал",
                kind=type(exc).__name__, blame="sandbox", error=str(exc)))

        os.close(write_fd)
        write_fd = -1
        reader.start()

        try:
            _, err = proc.communicate(input=raw_source, timeout=policy.wall_seconds)
        except subprocess.TimeoutExpired:
            timed_out = True
            _kill_group(proc)
            try:
                _, err = proc.communicate(timeout=5.0)
            except Exception:
                err = b""
        stderr_text = (err or b"").decode("utf-8", "replace")
        reader.join(timeout=5.0)
    finally:
        for fd in (read_fd, write_fd):
            if fd >= 0:
                try:
                    os.close(fd)
                except OSError:
                    pass
        # rmdir мало: RLIMIT_FSIZE=0 запрещает СОДЕРЖИМОЕ, но не мешает создать
        # пустой файл, и такой файл оставил бы каталог на проде навсегда.
        shutil.rmtree(jail, ignore_errors=True)

    # РОДИТЕЛЬСКОЕ ЧИСЛО — УЛИКА, А НЕ ПОКАЗАНИЕ, и вот почему.
    # ru_maxrss у RUSAGE_CHILDREN — высшая вода по всем пожатым детям, и она
    # вдобавок собрана из ДЕТСКИХ ru_maxrss, каждое из которых унаследовано от
    # родителя при fork (замер в _read_vm_hwm). Значит прирост доказывает лишь
    # «не меньше», и то в однопоточном вызывающем. Пик запуска приходит из
    # самого ребёнка через VmHWM; сюда падает только след для операторского
    # разбора, когда ребёнок умер, не сказав ничего.
    rss_after = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    children_growth = max(0, rss_after - rss_before)

    payload_bytes = b"".join(chunks)
    if len(payload_bytes) > policy.max_result_bytes:
        return SandboxResult(ok=False, refusal=_refuse(
            SANDBOX_OUTPUT_LIMIT,
            f"скрипт выдал больше {policy.max_result_bytes} байт — "
            f"это транспортный предел песочницы, а не бюджет компилятора",
            kind="ResultTooLarge", blame="author", bytes=len(payload_bytes)))

    payload = _parse_result_channel(payload_bytes)
    if payload is None:
        if payload_bytes:
            stderr_text += "\n[sandbox] result channel unparsable"
        return _classify_dead_child(proc, timed_out, policy, stderr_text,
                                    children_growth)

    # peak_rss_kb приходит ТОЛЬКО из ребёнка (VmHWM). Подменять его
    # родительской уликой нельзя: получилось бы число, которое зависит от
    # того, кто бежал в суите ДО нас.
    result = _result_from_payload(payload, policy)
    if children_growth:
        result.isolation.setdefault("children_rss_growth_kb", children_growth)
    return result


def _parse_result_channel(payload_bytes: bytes) -> Optional[dict]:
    """Разбор канала результата.

    Канал отдельный от stdout именно для того, чтобы print скрипта не мог его
    испортить. Но сбежавший код теоретически может написать в дескриптор
    напрямую, поэтому вторая попытка — последняя непустая строка."""
    if not payload_bytes:
        return None
    text = payload_bytes.decode("utf-8", "replace")
    for candidate in (text, *reversed(text.strip().splitlines())):
        try:
            got = json.loads(candidate)
        except Exception:
            continue
        if isinstance(got, dict) and "ok" in got:
            return got
    return None


def _kill_group(proc: "subprocess.Popen") -> None:
    """Снять всю группу: ребёнок форкать не может (NPROC=0), но группа —
    единственный способ не оставить сироту, если политика форк разрешила."""
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            proc.kill()
        except Exception:
            pass


def _classify_dead_child(proc, timed_out: bool, policy: SandboxPolicy,
                         stderr_text: str, children_growth: int) -> SandboxResult:
    """Ребёнок не отдал результата. Классифицируем по тому, ЧЕМ он умер.

    `peak_rss_kb` здесь ОСТАЁТСЯ НУЛЁМ, и это честно: пик приходит из ребёнка
    (VmHWM), а мёртвый ребёнок ничего не сказал. Родительский прирост кладётся
    в улику отказа, а не в поле показания — иначе число зависело бы от того,
    кто бежал перед нами."""
    rc = proc.returncode if proc is not None else None
    tail = stderr_text.strip()[-1500:]
    trace = children_growth or None

    if timed_out:
        return SandboxResult(ok=False, refusal=_refuse(
            SANDBOX_TIMEOUT,
            f"скрипт не завершился за {policy.wall_seconds:g} с по стене и снят. "
            f"Вероятнее всего — цикл без выхода. Строку назвать не могу: процесс "
            f"снят снаружи, а не остановлен изнутри. "
            f"Пределы: процессорное время {policy.cpu_seconds:g} с, стена "
            f"{policy.wall_seconds:g} с",
            kind="WallTimeout", blame="author",
            wall_seconds=policy.wall_seconds, stderr_tail=tail,
            children_rss_growth_kb=trace))

    if rc is not None and rc < 0:
        signum = -rc
        name = signal.Signals(signum).name if signum in set(
            s.value for s in signal.Signals) else f"SIG{signum}"
        if signum == signal.SIGXCPU:
            return SandboxResult(ok=False, refusal=_refuse(
                SANDBOX_TIMEOUT,
                f"скрипт исчерпал жёсткий предел процессорного времени "
                f"({policy.cpu_seconds:g} с) и снят ядром. Так бывает, когда "
                f"цикл без выхода проглотил и мягкое предупреждение тоже "
                f"(перехватывать BaseException в скрипте не надо)",
                kind=name, blame="author", cpu_seconds=policy.cpu_seconds,
                children_rss_growth_kb=trace))
        if signum == signal.SIGSEGV:
            return SandboxResult(ok=False, refusal=_refuse(
                SANDBOX_CRASH,
                "интерпретатор упал на этом скрипте (SIGSEGV). Обычные причины — "
                "очень глубокая вложенность выражения, рекурсия без базового "
                "случая или обращение к памяти в обход языка. Программа не "
                "собрана; процесс был отдельным, поэтому падение никого не задело",
                kind=name, blame="author", stderr_tail=tail))
        if signum == signal.SIGKILL:
            return SandboxResult(ok=False, refusal=_refuse(
                SANDBOX_MEMORY,
                f"процесс скрипта снят ядром (SIGKILL) без сообщения. Обычно это "
                f"нехватка памяти: предел этого запуска — {policy.memory_mb} МБ",
                kind=name, blame="unknown", memory_mb=policy.memory_mb,
                stderr_tail=tail, children_rss_growth_kb=trace))
        return SandboxResult(ok=False, refusal=_refuse(
            SANDBOX_CRASH,
            f"процесс скрипта снят сигналом {name} и не отдал результата",
            kind=name, blame="unknown", stderr_tail=tail))

    return SandboxResult(ok=False, refusal=_refuse(
        SANDBOX_UNAVAILABLE,
        "песочница не отдала результата — это наш дефект, а не ошибка скрипта",
        kind="NoResult", blame="sandbox", returncode=rc, stderr_tail=tail))


def _result_from_payload(payload: dict, policy: SandboxPolicy) -> SandboxResult:
    isolation = dict(payload.get("isolation") or {})
    stdout = str(payload.get("stdout") or "")
    peak = int(payload.get("peak_rss_kb") or 0)

    if payload.get("ok"):
        ops = payload.get("ops") or []
        envelope = dict(payload.get("envelope") or {})
        return SandboxResult(
            ok=True, ops=list(ops), envelope=envelope, stdout=stdout,
            isolation=isolation, peak_rss_kb=peak,
            program_digest=_program_digest(list(ops), envelope))

    refusal = SandboxRefusal.from_dict(payload.get("refusal") or {})
    return SandboxResult(ok=False, refusal=refusal, stdout=stdout,
                         isolation=isolation, peak_rss_kb=peak)


# ─────────────────────────────────────────────────────────────────────────────
# РЕБЁНОК
# ─────────────────────────────────────────────────────────────────────────────

class _CpuExhausted(BaseException):
    """SIGXCPU, поднятый как исключение. Наследник BaseException НАМЕРЕННО:
    `except Exception` в скрипте не должен его проглатывать."""

    def __init__(self, lineno: Optional[int]):
        super().__init__("cpu time exhausted")
        self.lineno = lineno


class _ForbiddenImport(BaseException):
    def __init__(self, module: str):
        super().__init__(module)
        self.module = module


class _ForbiddenBuiltin(BaseException):
    def __init__(self, name: str):
        super().__init__(name)
        self.name = name


class _CappedWriter:
    """sys.stdout скрипта. Мусор из print не идёт в канал результата вообще —
    он идёт СЮДА, обрезается по потолку и возвращается модели как обратная связь."""

    def __init__(self, cap: int):
        self.cap = cap
        self.parts: list[str] = []
        self.size = 0
        self.dropped = 0

    def write(self, s) -> int:
        text = s if isinstance(s, str) else str(s)
        room = self.cap - self.size
        if room > 0:
            self.parts.append(text[:room])
            self.size += min(room, len(text))
        if len(text) > max(room, 0):
            self.dropped += len(text) - max(room, 0)
        return len(text)

    def flush(self) -> None:
        return None

    def isatty(self) -> bool:
        return False

    def getvalue(self) -> str:
        out = "".join(self.parts)
        if self.dropped:
            out += f"\n[обрезано ещё {self.dropped} символов]"
        return out


def _import_reason(module: str, allowed: tuple[str, ...]) -> str:
    """Почему конкретного модуля нет — по семьям.

    Отказ обязан УЧИТЬ: «модуль не разрешён» модель прочитает как каприз и
    попробует соседний, а «недетерминизм ломает подпись» закрывает всю семью
    сразу."""
    root = module.split(".")[0]
    allow = ", ".join(allowed)
    nondet = {"random", "secrets", "uuid", "time", "datetime", "calendar",
              "statistics", "hashlib", "hmac", "tempfile"}
    system = {"os", "sys", "subprocess", "shutil", "pathlib", "io", "glob",
              "ctypes", "signal", "resource", "multiprocessing", "threading",
              "importlib", "builtins", "gc", "inspect", "sysconfig", "pty"}
    net = {"socket", "urllib", "http", "requests", "ftplib", "smtplib",
           "asyncio", "ssl", "telnetlib", "xmlrpc", "webbrowser"}
    if root in nondet:
        return (f"НЕДЕТЕРМИНИЗМ ЗАПРЕЩЁН: исходник скрипта подписывается в "
                f"квитанции, и подпись недетерминированного скрипта не "
                f"подписывает ничего. Нужен разброс — впишите числа явно. "
                f"Разрешено ровно: {allow}")
    if root in system:
        return (f"доступа к системе у скрипта нет: наружу выходит ровно одна "
                f"вещь — программа IR. Разрешено ровно: {allow}")
    if root in net:
        return (f"сети нет вовсе: скрипт исполняется в отдельном сетевом "
                f"пространстве имён без единого маршрута. Разрешено ровно: {allow}")
    return (f"белый список импортов закрыт: разрешено ровно {allow} "
            f"(и язык KIR, который уже доступен без импорта)")


_BUILTIN_REASONS = {
    "open": "файлов нет: скрипт исполняется в пустом корне и без права записи "
            "(RLIMIT_FSIZE=0). Всё, что нужно программе, пишется операциями IR",
    "eval": "исполнение сгенерированного текста запрещено: скрипт подписывается "
            "в квитанции, а подписать можно только то, что читается глазами",
    "exec": "исполнение сгенерированного текста запрещено: скрипт подписывается "
            "в квитанции, а подписать можно только то, что читается глазами",
    "compile": "исполнение сгенерированного текста запрещено: скрипт подписывается "
               "в квитанции, а подписать можно только то, что читается глазами",
    "input": "интерактивного ввода нет: скрипт исполняется без человека рядом",
    "id": "id() — это адрес объекта, то есть недетерминизм: он меняется от "
          "запуска к запуску и делает подпись исходника бессмысленной",
    "globals": "интроспекция пространства имён скрипту не нужна: программа "
               "собирается вызовами языка",
    "locals": "интроспекция пространства имён скрипту не нужна: программа "
              "собирается вызовами языка",
    "vars": "интроспекция пространства имён скрипту не нужна: программа "
            "собирается вызовами языка",
    "breakpoint": "отладчика здесь нет: процесс исполняется без терминала",
    # НАЗЫВАЕТ ДОСТИЖИМОЕ, А НЕ ЖАНР. До 04.08 отказ отсылал «в подсказку» —
    # это верно и бесполезно: подсказка приходит один раз и не отвечает на
    # «какие слоты у ЭТОГО опа». Замер того же дня: слабая модель потратила 13
    # из 27 отказов на угадывание слотов по одному за ход. Докстрока каждой
    # функции языка собрана из реестра (`dsl._docstring`: слоты, виды,
    # границы, постусловие) и читается ПРЯМО В СКРИПТЕ — то есть в тот же ход,
    # без второго раунда. Проверено исполнением в песочнице, а не выведено.
    "help": "интерактивной справки нет, но форма опа читается в самом скрипте: "
            "print(create_wall.__doc__) печатает ВСЕ слоты с видами, границами "
            "и постусловием — в квитанцию ЭТОГО ЖЕ хода",
    "exit": "выходить не надо: программа считается собранной, когда скрипт "
            "дошёл до конца",
    "quit": "выходить не надо: программа считается собранной, когда скрипт "
            "дошёл до конца",
    "__import__": "импорт вызывается через инструкцию import и ограничен белым "
                  "списком",
}

_SAFE_BUILTIN_NAMES = (
    "abs", "all", "any", "ascii", "bin", "bool", "bytearray", "bytes",
    "callable", "chr", "complex", "dict", "dir", "divmod", "enumerate",
    "filter", "float", "format", "frozenset", "getattr", "hasattr", "hash",
    "hex", "int", "isinstance", "issubclass", "iter", "len", "list", "map",
    "max", "min", "next", "object", "oct", "ord", "pow", "print", "range",
    "repr", "reversed", "round", "set", "setattr", "delattr", "slice",
    "sorted", "staticmethod", "classmethod", "property", "str", "sum",
    "super", "tuple", "type", "zip", "True", "False", "None",
    "NotImplemented", "Ellipsis", "__build_class__",
    # исключения — чтобы скрипт мог писать нормальный except
    "BaseException", "Exception", "ArithmeticError", "AssertionError",
    "AttributeError", "IndexError", "KeyError", "LookupError", "MemoryError",
    "NameError", "NotImplementedError", "OverflowError", "RecursionError",
    "RuntimeError", "StopIteration", "TypeError", "ValueError",
    "ZeroDivisionError", "UnicodeError", "FloatingPointError",
)


def _child_main() -> None:  # pragma: no cover — исполняется в другом процессе
    """Точка входа ребёнка. Всё, что здесь падает, обязано выйти отказом."""
    import builtins
    import ctypes
    import dataclasses
    import gc
    import resource
    import types

    result_fd = int(os.environ.get("KIR_SANDBOX_RESULT_FD", "-1"))
    jail = os.environ.get("KIR_SANDBOX_JAIL", "")
    try:
        cfg = json.loads(os.environ.get("KIR_SANDBOX_CFG") or "{}")
    except Exception:
        cfg = {}

    state: dict = {"isolation": {}, "stdout": "", "source_lines": [],
                   "hwm_fd": -1}

    def emit(payload: dict) -> None:
        payload.setdefault("isolation", state["isolation"])
        payload.setdefault("stdout", state["stdout"])
        payload.setdefault("peak_rss_kb", _read_vm_hwm(state["hwm_fd"]))
        try:
            data = json.dumps(payload, ensure_ascii=False,
                              allow_nan=False).encode("utf-8")
        except Exception as exc:
            data = json.dumps({
                "ok": False,
                "refusal": {"code": SANDBOX_UNAVAILABLE, "blame": "sandbox",
                            "kind": type(exc).__name__,
                            "message_ru": "результат не сериализуется"},
            }).encode("utf-8")
        cap = int(cfg.get("max_result_bytes") or MAX_RESULT_BYTES)
        if len(data) > cap:
            data = json.dumps({
                "ok": False,
                "refusal": {
                    "code": SANDBOX_OUTPUT_LIMIT, "blame": "author",
                    "kind": "ResultTooLarge",
                    "message_ru": (f"результат {len(data)} байт при транспортном "
                                   f"пределе песочницы {cap}"),
                },
            }, ensure_ascii=False).encode("utf-8")
        view = memoryview(data)
        while view:
            written = os.write(result_fd, view[:65536])
            view = view[written:]
        try:
            os.close(result_fd)
        except OSError:
            pass

    def refuse(code: str, message: str, *, kind: str, blame: str = "author",
               line: Optional[int] = None, frames: Optional[list] = None,
               **detail: Any) -> None:
        text = None
        if line is not None and 1 <= line <= len(state["source_lines"]):
            text = state["source_lines"][line - 1]
        payload = {
            "ok": False,
            "refusal": {
                "code": code, "message_ru": message, "kind": kind,
                "blame": blame, "line": line, "line_text": text,
                "script_frames": frames or ([line] if line else []),
                "detail": {k: v for k, v in detail.items() if v is not None},
            },
        }
        emit(payload)
        sys.exit(0)

    # ── 1. исходник приходит по stdin, потом stdin отбирается ────────────────
    try:
        raw = sys.stdin.buffer.read()
    except Exception:
        raw = b""
    try:
        devnull = os.open(os.devnull, os.O_RDWR)
        os.dup2(devnull, 0)
    except OSError:
        pass
    try:
        source = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        refuse(SANDBOX_SYNTAX,
               f"исходник не в UTF-8: {exc.reason} на байте {exc.start}",
               kind="UnicodeDecodeError")
        return
    state["source_lines"] = source.splitlines()

    # ── 2. прогрев: ВСЁ, что понадобится, импортируется ДО chroot ────────────
    for entry in reversed(cfg.get("extra_sys_path") or []):
        if entry and entry not in sys.path:
            sys.path.insert(0, entry)

    allowed = tuple(cfg.get("allowed_imports") or ALLOWED_IMPORTS)
    warm: dict[str, Any] = {}
    import importlib
    warm_names = list(allowed) + [
        "collections", "collections.abc", "numbers", "decimal", "fractions",
        "copy", "reprlib", "operator", "keyword", "linecache", "encodings.idna",
        "codecs", "abc", "enum", "typing", "re", "string", "textwrap",
    ]
    for name in warm_names:
        try:
            warm[name] = importlib.import_module(name)
        except Exception:
            pass

    dsl_module = cfg.get("dsl_module") or "kukai.ir.dsl"
    dsl = None
    dsl_error = ""
    try:
        dsl = importlib.import_module(dsl_module)
    except Exception as exc:
        dsl_error = f"{type(exc).__name__}: {exc}"
    state["isolation"]["dsl_module"] = dsl_module if dsl else f"unavailable ({dsl_error})"

    # ── 3. изоляция: пространства имён → пустой корень → лимиты ──────────────
    # Дескриптор на /proc/self/status берётся ЗДЕСЬ, пока /proc ещё виден:
    # после chroot путь недостижим, а открытый дескриптор перечитывается.
    # Это единственный честный источник пика ЭТОГО процесса (см. _read_vm_hwm).
    try:
        state["hwm_fd"] = os.open("/proc/self/status", os.O_RDONLY)
    except OSError:
        state["hwm_fd"] = -1
    state["isolation"]["peak_rss_source"] = (
        "VmHWM" if state["hwm_fd"] >= 0 else "unavailable")

    net_policy = str(cfg.get("network") or "required")
    ns_state = "off"
    if net_policy in ("required", "best_effort"):
        try:
            libc = ctypes.CDLL("libc.so.6", use_errno=True)
            rc = libc.unshare(_CLONE_NEWUSER | _CLONE_NEWNS | _CLONE_NEWNET)
            if rc == 0:
                ns_state = "user+mount+net"
            else:
                ns_state = f"unavailable (errno {ctypes.get_errno()})"
        except Exception as exc:
            ns_state = f"unavailable ({type(exc).__name__})"
    state["isolation"]["namespaces"] = ns_state
    state["isolation"]["uid"] = os.getuid()
    # Идентификатор сетевого пространства имён — замер, который можно СВЕРИТЬ
    # с родительским: совпал ⇒ никакой изоляции сети нет, что бы ни обещала
    # политика. Снимается до chroot, пока /proc ещё виден.
    try:
        state["isolation"]["netns"] = os.readlink("/proc/self/ns/net")
    except OSError:
        state["isolation"]["netns"] = "unknown"

    if net_policy == "required" and not ns_state.startswith("user"):
        refuse(SANDBOX_UNAVAILABLE,
               f"сетевое пространство имён не создано ({ns_state}), а политика "
               f"требует НУЛЯ СЕТИ. Запуск отменён до исполнения скрипта. "
               f"Боксу без непривилегированных user namespaces нужно поставить "
               f"policy.network='best_effort'",
               kind="NamespaceUnavailable", blame="sandbox")
        return

    # Замер вместо намерения: сеть недостижима — доказывается сокетом.
    # Но только когда изоляция ЗАЯВЛЕНА: если её выключили сознательно,
    # проверять нечего, а лишний исходящий пакет с прод-бокса — не наше дело.
    state["isolation"]["network_probe"] = "not probed"
    if cfg.get("probe_network") and net_policy != "off":
        state["isolation"]["network_probe"] = _probe_network()
        if (net_policy == "required"
                and state["isolation"]["network_probe"] == "reachable"):
            refuse(SANDBOX_UNAVAILABLE,
                   "замер показал, что сеть достижима, хотя политика требует "
                   "нуля сети. Запуск отменён до исполнения скрипта",
                   kind="NetworkReachable", blame="sandbox")
            return

    # ── ЯЗЫК ДОГРУЖАЕТ ТО, ЧТО НУЖНО ИМЕННО ЭТОМУ ИСХОДНИКУ ──────────────────
    #
    # ОКНО РОВНО ЗДЕСЬ, между пространствами имён и пустым корнем, и оба его
    # края — ЗАМЕР, а не осторожность.
    #
    # НЕ РАНЬШЕ, чем `unshare`: модуль вердикта тянет numpy, а numpy поднимает
    # пул потоков OpenBLAS — и `unshare(CLONE_NEWUSER)` в многопоточном процессе
    # отвечает EINVAL. Замер 03.08: прогрев до `unshare` СОРВАЛ КАЖДЫЙ запуск,
    # который звал `design_check`, — политика `network="required"` честно
    # отменяла ход (KIR-B012) ещё до исполнения скрипта.
    #
    # НЕ ПОЗЖЕ, чем chroot: shapely и numpy подгружают свои .so с диска, а в
    # пустом корне диска нет. И тем более не позже стража импортов
    # (`_MetaGuard`): он поднял бы KIR-B004 с номером строки МОДЕЛИ, послав
    # чинить исправный скрипт.
    #
    # ПОЧЕМУ УСЛОВНО. Замер: модуль вердикта — +536 мс и +43 МБ, а скрипт
    # исполняется ДВАЖДЫ (`replay_check`) при счастливом пути в 121 мс.
    # РЕШАЕТ ЯЗЫК: грамматики песочница не знает (см. §КОНТРАКТ) и знать не
    # должна. Хук необязателен; его исключение сюда не выходит — непрогретый
    # модуль это отсутствующая способность, а не сорванный ход.
    warm_hook = getattr(dsl, "warm_for_source", None) if dsl is not None else None
    if callable(warm_hook):
        try:
            state["isolation"]["warmed"] = list(warm_hook(source) or ())
        except Exception as exc:
            state["isolation"]["warmed"] = f"failed ({type(exc).__name__}: {exc})"

    # БЮДЖЕТ ПАМЯТИ СНИМАЕТСЯ ПОСЛЕ ВСЕХ НАШИХ ИМПОРТОВ, И ЭТО НЕ МЕЛОЧЬ.
    #
    # `memory_mb` обещает СКРИПТУ столько-то мегабайт СВЕРХ занятого, поэтому
    # предел = «сколько занято сейчас» + бюджет. Замерено 03.08 ровно тем, что
    # это правило нарушили: снимок брался ДО прогрева, прогретые numpy/shapely
    # (адресного пространства они резервируют кратно больше, чем занимают RSS)
    # съедали бюджет скрипта, и программа на 298 операций умирала на выходе
    # MemoryError'ом ВНУТРИ json.dumps — то есть отказом «результат не
    # сериализуется» вместо честного «не хватило памяти». Ход терялся целиком.
    #
    # Позже нельзя: /proc после chroot недостижим (см. `_read_vm_hwm`).
    try:
        vm_bytes = _self_vm_size()
    except Exception:
        vm_bytes = 64 * 1024 * 1024

    fs_state = "off"
    if cfg.get("filesystem_isolation") and jail:
        try:
            os.chroot(jail)
            os.chdir("/")
            fs_state = "chroot"
        except Exception as exc:
            fs_state = f"unavailable ({type(exc).__name__}: {exc})"
    state["isolation"]["filesystem"] = fs_state

    # SIGXFSZ по умолчанию УБИВАЕТ процесс. Игнорируем его, чтобы запись в файл
    # стала обычной OSError(EFBIG) — то есть обучающим отказом, а не молчанием.
    try:
        signal.signal(signal.SIGXFSZ, signal.SIG_IGN)
    except Exception:
        pass

    def _on_xcpu(signum, frame):
        lineno = None
        f = frame
        while f is not None:
            if f.f_code.co_filename == SCRIPT_FILENAME:
                lineno = f.f_lineno
                break
            f = f.f_back
        raise _CpuExhausted(lineno)

    try:
        signal.signal(signal.SIGXCPU, _on_xcpu)
    except Exception:
        pass

    mem_bytes = int(cfg.get("memory_mb") or DEFAULT_MEMORY_MB) * 1024 * 1024
    cpu_s = float(cfg.get("cpu_seconds") or DEFAULT_CPU_SECONDS)
    limits = {}
    for name, value in (
        ("RLIMIT_FSIZE", (0, 0)),                    # писать нечего
        ("RLIMIT_CORE", (0, 0)),                     # прод не получит дамп
        ("RLIMIT_NPROC", (0, 0)),                    # ни fork, ни subprocess
        ("RLIMIT_NOFILE", (int(cfg.get("nofile") or DEFAULT_NOFILE),) * 2),
        ("RLIMIT_AS", (vm_bytes + mem_bytes, vm_bytes + mem_bytes)),
        ("RLIMIT_CPU", (max(1, int(cpu_s)), max(1, int(cpu_s)) + 2)),
    ):
        try:
            resource.setrlimit(getattr(resource, name), value)
            limits[name] = value[0]
        except (ValueError, OSError) as exc:
            limits[name] = f"failed ({exc})"
    state["isolation"]["limits"] = limits
    state["isolation"]["memory_mb"] = int(cfg.get("memory_mb") or DEFAULT_MEMORY_MB)
    state["isolation"]["cpu_seconds"] = cpu_s

    sys.setrecursionlimit(int(cfg.get("recursion_limit") or DEFAULT_RECURSION_LIMIT))
    # Окружение стирается целиком, КРОМЕ операторских переключателей.
    # Стёртый переключатель — это не «безопаснее», это МОЛЧАЛИВОЕ НЕСОГЛАСИЕ с
    # оператором: код, читающий флаг живьём (`checker.flags.checker_v2_enabled`
    # — так задумано, чтобы правка на службе действовала со следующей проверки),
    # в этом процессе прочитал бы «выключено» при включённом на службе и выдал
    # бы отказ «включите то, что уже включено». Для скрипта разницы нет: его
    # `os` недоступен в любом случае, а сам список — белый и короткий.
    kept = {name: os.environ[name] for name in _ENV_PASSTHROUGH
            if name in os.environ}
    os.environ.clear()
    os.environ.update(kept)

    # ── 4. компиляция исходника ──────────────────────────────────────────────
    try:
        code = compile(source, SCRIPT_FILENAME, "exec")
    except SyntaxError as exc:
        refuse(SANDBOX_SYNTAX,
               f"скрипт не разобран Python: {exc.msg}",
               kind=type(exc).__name__, line=exc.lineno,
               offset=exc.offset)
        return
    except ValueError as exc:                     # нулевые байты и подобное
        refuse(SANDBOX_SYNTAX, f"скрипт не разобран Python: {exc}",
               kind=type(exc).__name__)
        return
    except MemoryError:
        refuse(SANDBOX_MEMORY,
               f"разбор исходника не уложился в {cfg.get('memory_mb')} МБ",
               kind="MemoryError")
        return
    except RecursionError:
        refuse(SANDBOX_SYNTAX,
               "выражение слишком глубоко вложено — интерпретатор не смог его "
               "разобрать. Разбейте его на промежуточные переменные",
               kind="RecursionError")
        return

    # ── 5. пространство скрипта ──────────────────────────────────────────────
    real_import = builtins.__import__

    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
        if level != 0:
            raise _ForbiddenImport(("." * level) + (name or ""))
        root = (name or "").split(".")[0]
        if name in allowed or (root in allowed and name == root):
            return real_import(name, globals, locals, fromlist, level)
        raise _ForbiddenImport(name or "")

    class _MetaGuard:
        """Второй рубеж: ловит импорт в обход builtins.__import__."""

        def find_module(self, fullname, path=None):
            return self.find_spec(fullname, path)

        def find_spec(self, fullname, path=None, target=None):
            root = fullname.split(".")[0]
            if root in allowed:
                return None
            raise _ForbiddenImport(fullname)

    safe_builtins: dict[str, Any] = {}
    for bname in _SAFE_BUILTIN_NAMES:
        if hasattr(builtins, bname):
            safe_builtins[bname] = getattr(builtins, bname)
    safe_builtins["__import__"] = guarded_import

    def _make_stub(bname: str):
        def _stub(*_a, **_kw):
            raise _ForbiddenBuiltin(bname)
        _stub.__name__ = bname
        return _stub

    for bname in _BUILTIN_REASONS:
        if bname != "__import__":
            safe_builtins[bname] = _make_stub(bname)

    ns: dict[str, Any] = {
        "__name__": "kir_author_script",
        "__builtins__": safe_builtins,
        "__doc__": None,
    }
    if dsl is not None:
        exported = getattr(dsl, "__all__", None)
        names = list(exported) if exported else [
            n for n in vars(dsl) if not n.startswith("_")]
        for n in names:
            value = getattr(dsl, n, None)
            # МОДУЛИ НЕ ИНЖЕКТИРУЕМ НИКОГДА: если dsl.py делает `import os`,
            # скрипт не должен получить `os` через чёрный ход инжекции.
            if isinstance(value, types.ModuleType):
                continue
            ns[n] = value
        ns["kir"] = dsl

    stdout = _CappedWriter(int(cfg.get("max_stdout_chars") or MAX_STDOUT_CHARS))
    real_stdout, real_stderr = sys.stdout, sys.stderr
    sys.stdout = stdout
    sys.stderr = stdout
    sys.meta_path.insert(0, _MetaGuard())

    def script_frames(tb) -> list[int]:
        out = []
        while tb is not None:
            if tb.tb_frame.f_code.co_filename == SCRIPT_FILENAME:
                out.append(tb.tb_lineno)
            tb = tb.tb_next
        return out

    def restore() -> None:
        sys.stdout, sys.stderr = real_stdout, real_stderr
        state["stdout"] = stdout.getvalue()
        for finder in list(sys.meta_path):
            if isinstance(finder, _MetaGuard):
                sys.meta_path.remove(finder)

    def fail_from_exception(exc: BaseException, frames: list[int]) -> None:
        """ОДНА точка перевода питоновского исключения в типизированный отказ.

        Одна, а не две, потому что исключение из `build()` — та же ошибка
        модели, что исключение из тела скрипта, и код отказа обязан совпадать."""
        line = frames[-1] if frames else None
        if isinstance(exc, _ForbiddenImport):
            module = exc.module
            if module.split(".")[0] == (dsl_module or "").split(".")[0]:
                reason = ("язык уже доступен без импорта: пишите "
                          "create_wall(...) или kir.create_wall(...)")
            else:
                reason = _import_reason(module, allowed)
            refuse(SANDBOX_FORBIDDEN_IMPORT,
                   f"импорт '{module}' запрещён. {reason}",
                   kind="ForbiddenImport", line=line, frames=frames,
                   module=module, allowed=list(allowed))
        elif isinstance(exc, _ForbiddenBuiltin):
            reason = _BUILTIN_REASONS.get(exc.name, "имя закрыто белым списком")
            refuse(SANDBOX_FORBIDDEN_BUILTIN,
                   f"'{exc.name}' в скрипте недоступен. {reason}",
                   kind="ForbiddenBuiltin", line=line, frames=frames,
                   name=exc.name)
        elif isinstance(exc, _CpuExhausted):
            refuse(SANDBOX_TIMEOUT,
                   f"скрипт не завершился за {cpu_s:g} с процессорного времени — "
                   f"вероятно, цикл без выхода. Пределы этого запуска: "
                   f"процессорное время {cpu_s:g} с, стена "
                   f"{cfg.get('wall_seconds')} с",
                   kind="CpuTimeout", line=exc.lineno or line,
                   cpu_seconds=cpu_s)
        elif isinstance(exc, MemoryError):
            refuse(SANDBOX_MEMORY,
                   f"скрипт превысил предел памяти {cfg.get('memory_mb')} МБ "
                   f"(адресное пространство). Не накапливайте данные в цикле: "
                   f"программа IR — это операции, а не массив",
                   kind="MemoryError", line=line, frames=frames,
                   memory_mb=cfg.get("memory_mb"))
        elif isinstance(exc, RecursionError):
            refuse(SANDBOX_RUNTIME,
                   f"рекурсия глубже {sys.getrecursionlimit()} кадров — "
                   f"вероятно, нет базового случая",
                   kind="RecursionError", line=line, frames=frames[-6:])
        elif isinstance(exc, NameError) and dsl is None:
            # Имени нет, потому что НЕ ЗАГРУЗИЛСЯ ЯЗЫК. Это наш дефект, и
            # отказ обязан сказать это прямо: иначе модель будет чинить свой
            # исправный скрипт по подсказке «name is not defined».
            refuse(SANDBOX_UNAVAILABLE,
                   f"язык KIR не загрузился ({dsl_error}), поэтому имени из "
                   f"скрипта нет: {exc}. Это дефект песочницы, а не скрипта",
                   kind="NameError", blame="sandbox", line=line, frames=frames,
                   dsl_module=dsl_module, dsl_error=dsl_error)
        else:
            message = str(exc).strip() or type(exc).__name__
            refuse(SANDBOX_RUNTIME, f"{type(exc).__name__}: {message}",
                   kind=type(exc).__name__, line=line, frames=frames)

    # ── 6. исполнение ────────────────────────────────────────────────────────
    try:
        exec(code, ns)
    except SystemExit as exc:
        restore()
        if exc.code not in (None, 0):
            refuse(SANDBOX_RUNTIME,
                   f"скрипт завершился досрочно с кодом {exc.code}; программа "
                   f"считается собранной, только когда скрипт дошёл до конца",
                   kind="SystemExit")
            return
    except BaseException as exc:                  # noqa: BLE001 — это и есть шов
        frames = script_frames(sys.exc_info()[2])
        if isinstance(exc, MemoryError):
            # Освобождаем ПЕРЕД тем, как строить отказ: иначе форматирование
            # текста само упрётся в тот же предел.
            ns.clear()
            gc.collect()
        restore()
        fail_from_exception(exc, frames)
        return

    # ── 7. сбор программы ────────────────────────────────────────────────────
    try:
        harvested, how = _harvest(ns, dsl)
    except BaseException as exc:                  # noqa: BLE001
        frames = script_frames(sys.exc_info()[2])
        if isinstance(exc, MemoryError):
            ns.clear()
            gc.collect()
        restore()
        fail_from_exception(exc, frames)
        return
    restore()

    state["isolation"]["harvest"] = how

    envelope: dict = {}
    if isinstance(harvested, dict):
        if "ops" not in harvested:
            refuse(SANDBOX_BAD_RESULT,
                   "скрипт вернул словарь без ключа 'ops': программа — это "
                   "список операций либо конверт {'ops': [...]}",
                   kind="BadEnvelope", keys=sorted(harvested)[:12])
            return
        for key in _ENVELOPE_KEYS:
            if key in harvested:
                envelope[key] = harvested[key]
        harvested = harvested["ops"]

    if harvested is None:
        refuse(SANDBOX_NO_OPS,
               "скрипт отработал без ошибок, но не выдал ни одной операции. "
               "Программа собирается вызовами языка (например create_wall(...)); "
               "альтернатива — присвоить список операций переменной ops",
               kind="NoOps",
               candidates=list(_NS_CANDIDATES[:4]))
        return

    if isinstance(harvested, (str, bytes)):
        refuse(SANDBOX_BAD_RESULT,
               f"программа пришла как {type(harvested).__name__}, а нужен "
               f"список операций. Строка — это не программа IR",
               kind="BadResultType", got=type(harvested).__name__)
        return
    if not isinstance(harvested, (list, tuple)):
        refuse(SANDBOX_BAD_RESULT,
               f"программа пришла как {type(harvested).__name__}, а нужен "
               f"список операций",
               kind="BadResultType", got=type(harvested).__name__)
        return

    ops_raw = list(harvested)
    if not ops_raw:
        refuse(SANDBOX_NO_OPS,
               "скрипт отработал, но программа пуста: ни одной операции. "
               "Пустая программа ничего не доказывает и до Revit не доходит",
               kind="EmptyProgram")
        return

    max_ops = int(cfg.get("max_ops") or MAX_SCRIPT_OPS)
    if len(ops_raw) > max_ops:
        refuse(SANDBOX_OUTPUT_LIMIT,
               f"скрипт выдал {len(ops_raw)} операций при транспортном пределе "
               f"песочницы {max_ops}. Это НЕ авторский бюджет компилятора "
               f"(20 авторских / 320 после раскрытия макросов) — тот считается "
               f"дальше по конвейеру",
               kind="TooManyOps", ops=len(ops_raw), limit=max_ops)
        return

    ops: list = []
    for i, op in enumerate(ops_raw):
        norm = _normalize_op(op, dataclasses)
        if norm is None:
            refuse(SANDBOX_BAD_RESULT,
                   f"ops[{i}] — это {type(op).__name__}, а операция должна быть "
                   f"объектом языка или словарём",
                   kind="BadOpType", index=i, got=type(op).__name__)
            return
        ops.append(norm)

    problem = _check_jsonable(ops, "ops", 0)
    if problem is not None:
        path, reason = problem
        refuse(SANDBOX_BAD_RESULT,
               f"{path}: {reason}. В программе IR живут только числа, строки, "
               f"булевы, null, списки и словари",
               kind="NotJsonable", path=path)
        return
    problem = _check_jsonable(envelope, "envelope", 0) if envelope else None
    if problem is not None:
        path, reason = problem
        refuse(SANDBOX_BAD_RESULT, f"{path}: {reason}",
               kind="NotJsonable", path=path)
        return

    try:
        serialized = json.dumps({"ops": ops, "envelope": envelope},
                                ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        refuse(SANDBOX_BAD_RESULT, f"программа не переводится в JSON: {exc}",
               kind=type(exc).__name__)
        return

    hit = _ADDRESS_RE.search(serialized)
    if hit is not None:
        refuse(SANDBOX_NONDETERMINISM,
               f"в программе оказался адрес объекта: {hit.group(0)}. Это repr "
               f"объекта, который меняется от запуска к запуску — программа "
               f"перестаёт быть воспроизводимой. Передавайте значения, а не "
               f"объекты",
               kind="ObjectAddressInOutput", sample=hit.group(0))
        return

    emit({"ok": True, "ops": ops, "envelope": envelope})
    sys.exit(0)


def _read_vm_hwm(fd: int) -> int:
    """Пик RSS ЭТОГО процесса (`VmHWM`, КБ) через заранее открытый дескриптор.

    ПОЧЕМУ НЕ `getrusage(RUSAGE_SELF).ru_maxrss`, как было сначала. Замер
    03.08: ребёнок, порождённый fork+exec, ПОЛУЧАЕТ водораздел родителя и
    держит его как свой. Тощий родитель (11.8 МБ) → ребёнок докладывает
    11868 КБ при настоящем VmHWM 9844; жирный родитель (403 МБ) → тот же
    ребёнок докладывает 403708 КБ при настоящем VmHWM 9804, и даже после
    распухания на 120 МБ цифра не шевелится (унаследованный максимум выше).
    То есть это показание НЕ О ЭТОМ ПРОЦЕССЕ. Наш собственный набор ловил
    этим два ложных падения: зелено в одиночку, красно в суите — а красный
    тест в суите отучает читать красное вообще.

    `VmHWM` живёт в mm_struct и обнуляется на exec, поэтому меряет ровно этот
    запуск. Дескриптор открывается ДО chroot и перечитывается через
    lseek(0): после chroot путь /proc недостижим (проверено: FileNotFoundError),
    а уже открытый дескриптор отдаёт свежие значения."""
    if fd < 0:
        return 0
    try:
        os.lseek(fd, 0, os.SEEK_SET)
        blob = os.read(fd, 8192).decode("ascii", "replace")
    except OSError:
        return 0
    for line in blob.splitlines():
        if line.startswith("VmHWM:"):
            parts = line.split()
            if len(parts) >= 2 and parts[1].isdigit():
                return int(parts[1])
    return 0


def _self_vm_size() -> int:
    """Текущее адресное пространство процесса (байты).

    RLIMIT_AS считает ВЕСЬ процесс, включая уже загруженный интерпретатор.
    Поэтому предел скрипта = «сколько занято сейчас» + бюджет, иначе бюджет
    молча съедался бы нашими же импортами."""
    with open("/proc/self/statm", "rb") as fh:
        pages = int(fh.read().split()[0])
    return pages * os.sysconf("SC_PAGE_SIZE")


def _probe_network() -> str:
    """Замер, а не намерение: пробуем соединиться и докладываем, чем кончилось."""
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.5)
        try:
            s.connect(("1.1.1.1", 53))
            return "reachable"
        except OSError as exc:
            return f"unreachable ({exc.errno}: {exc.strerror})"
        finally:
            s.close()
    except Exception as exc:
        return f"unreachable ({type(exc).__name__})"


def _harvest(ns: dict, dsl) -> tuple[Any, str]:
    """Забрать программу первым сработавшим способом контракта с языком.

    Имена языка инжектированы прямо в пространство скрипта, поэтому `ops` и
    `build` там есть ВСЕГДА. Собственной переменной скрипта считается только
    та, что ПЕРЕКРЫЛА инжектированное имя, — иначе «скрипт ничего не собрал»
    выглядело бы как «скрипт вернул функцию», и ремонт ушёл бы не туда."""

    def is_own(name: str, value: Any) -> bool:
        return dsl is None or value is not getattr(dsl, name, None)

    if dsl is not None:
        for name in _DRAIN_CANDIDATES:
            fn = getattr(dsl, name, None)
            if callable(fn):
                got = fn()
                if got:
                    return got, f"dsl.{name}()"
    for name in _NS_CANDIDATES:
        value = ns.get(name)
        if (isinstance(value, (list, tuple, dict)) and value
                and is_own(name, value)):
            return value, f"ns.{name}"
    for name in _BUILD_CANDIDATES:
        fn = ns.get(name)
        if callable(fn):
            return fn(), (f"{name}()" if is_own(name, fn) else f"dsl.{name}()")
    for name in _NS_CANDIDATES:                   # пустой, но объявленный
        if name in ns and is_own(name, ns[name]):
            return ns[name], f"ns.{name}"
    return None, "none"


def _normalize_op(op: Any, dataclasses_mod) -> Optional[dict]:
    """Операция языка → словарь. Форму объекта не угадываем: спрашиваем."""
    if isinstance(op, dict):
        return dict(op)
    for method in ("to_dict", "as_dict", "asdict", "to_json", "dict",
                   "model_dump"):
        fn = getattr(op, method, None)
        if callable(fn):
            try:
                got = fn()
            except Exception:
                continue
            if isinstance(got, dict):
                return got
    if dataclasses_mod.is_dataclass(op) and not isinstance(op, type):
        try:
            return dataclasses_mod.asdict(op)
        except Exception:
            return None
    return None


def _check_jsonable(value: Any, path: str, depth: int):
    """Проверка представимости в JSON С УКАЗАНИЕМ ПУТИ.

    json.dumps сообщает «Object of type X is not JSON serializable» без места;
    отказ без места — это второй раунд ремонта."""
    if depth > MAX_JSON_DEPTH:
        return (path, f"вложенность глубже {MAX_JSON_DEPTH}")
    if value is None or isinstance(value, (bool, str)):
        return None
    if isinstance(value, int):
        if abs(value) > 2 ** 63:
            return (path, "целое не помещается в 64 бита")
        return None
    if isinstance(value, float):
        if value != value:
            return (path, "NaN — числа NaN в JSON нет")
        if value in (float("inf"), float("-inf")):
            return (path, "бесконечность — её в JSON нет")
        return None
    if isinstance(value, dict):
        for k, v in value.items():
            if not isinstance(k, str):
                return (f"{path}.{k!r}",
                        f"ключ типа {type(k).__name__}, а нужен строковый")
            problem = _check_jsonable(v, f"{path}.{k}", depth + 1)
            if problem is not None:
                return problem
        return None
    if isinstance(value, (list, tuple)):
        for i, v in enumerate(value):
            problem = _check_jsonable(v, f"{path}[{i}]", depth + 1)
            if problem is not None:
                return problem
        return None
    return (path, f"значение типа {type(value).__name__}")


__all__ = [
    "SandboxPolicy",
    "SandboxRefusal",
    "SandboxResult",
    "DEFAULT_POLICY",
    "execute_author_script",
    "SCRIPT_FILENAME",
    "ALLOWED_IMPORTS",
    "MAX_SCRIPT_OPS",
]
