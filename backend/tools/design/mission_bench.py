"""Стенд миссии §19.3 — одна модель, один корпус зданий, два языка.

Тезис миссии — «модели ЛЕГЧЕ выразить здание в KIR, чем в Revit-C#» — до сих
пор ни разу не был числом. Здесь он становится парным замером: тот же снапшот
модели получает тот же бриф здания дважды, один раз с инструментом `revit_ir`
(рука A), один раз с `execute_revit_code` и литеральным C# (рука B, «raw
Revit-C#»), и обе эмиссии проходят ЧЕРЕЗ ОДИН И ТОТ ЖЕ Roslyn.

Что этот стенд меряет и чего не меряет (estimand, §7.3 ревизии v2):

* меряется ПОВЕРХНОСТЬ ЯЗЫКА — сколько сабмитов и раундов ремонта стоит довести
  замысел до принимаемой формы, и насколько отказ языка пригоден для ремонта;
* НЕ меряется правильность здания. Офлайн её проверить нечем: рука A могла бы
  предъявить состав и связность из принятых программ, у руки B офлайнового
  исполнения нет вообще. Доменный оракул поэтому отобран У ОБЕИХ рук (§7.3
  №7 — «либо обеим в доменных терминах, либо никому»), а не отдан одной;
* у обеих рук нет автофиксеров, нет RAG, нет подсказок по составу. Справочный
  бюджет НЕ выравнивается искусственно: он считается и публикуется
  (`prompt_tokens`), потому что «сколько справки нужно языку» — это свойство
  языка, а не помеха замеру.

Асимметрия судей называется до чисел, а не после (§18.1 спеки — перепись перед
процентами). Обе руки судит один Roslyn на одной версии 2023, но у руки A
перед ним стоит ещё одна ступень — `kir_accept`, типизированный разбор с
границами и постусловиями. Ступени пишутся РАЗДЕЛЬНО (`kir_accept`,
`roslyn_pass`), и сравнивать по оси компиляции честно только `roslyn_pass`:
ревью кодекса (№1, №2) опрокинуло исходное допущение, что «зелень KIR строже» —
`compile_program()` Roslyn не звал вовсе, так что старое «принято» и «сишарп
компилируется» были про разное.

    python tools/design/mission_bench.py --task house --blocks 2 --rounds 20
    python tools/design/mission_bench.py --all --blocks 6 --out runs/mb-1

Пилот НЕ запускается этим модулем автоматически: число прогонов на ячейку
считается по дисперсии пилота (§7.8), а пилот запускает лид.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
import statistics
import subprocess
import sys
import time
import urllib.error
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from kukai.compile_client import CompileClient                    # noqa: E402
from kukai.ir import spec                                         # noqa: E402
from kukai.llm.revit_execution_pipeline import wrap_user_code     # noqa: E402
from tools.design import kir_dojo                                 # noqa: E402
from tools.design.kir_dojo import TASKS, call_model               # noqa: E402

BACKEND = pathlib.Path(__file__).resolve().parents[2]

#: Версия Revit, на которой судятся ОБЕ руки. Одна, а не шесть: стенд меряет
#: не переносимость, а стоимость выражения, и разная матрица версий у рук
#: сделала бы «зелень» двух рук разными событиями.
JUDGE_VERSION = "2023"


# ─────────────────────────────────────────────────────────── брифы без языка

#: Те же семь зданий, что в `kir_dojo.TASKS`, но сказанные ЧИСТО в терминах
#: здания. Оригинальные брифы дожо называли операции KIR прямо в тексте
#: («двери в каждое помещение, помещения (create_room)») и описывали формат
#: ответа инструмента — то есть половину задания рука A получала на своём
#: родном языке, а рука B на чужом. Ревью кодекса (№4) назвало это заражением
#: языком; здесь ни одного имени операции, ни слова про программы, вызовы и
#: формат ответа. `TASKS` при этом НЕ мутируется: у дожо свой контракт и свой
#: CLI, и он остаётся ровно таким, каким его меряли до стенда.
NEUTRAL_BRIEFS: dict[str, str] = {
    "house": (
        "Двухэтажный жилой дом в плане 12×9 м, высота этажа 3 м. Наружные "
        "стены по периметру обоих этажей, межэтажное перекрытие, скатная "
        "кровля, входная дверь и по два окна на каждом фасаде. "
        "Начало координат дома — (0, 0)."),
    "frame": (
        "Несущий каркас здания в плане 30×18 м: пять этажей по 3.3 м, колонны "
        "по сетке 6×6 м, ригели по периметру и по внутренним осям на каждом "
        "этаже. Начало координат — (0, 0)."),
    "eiffel": (
        "Эйфелева башня как решётчатая стальная конструкция: высота 300 м, "
        "квадратное основание 125×125 м, четыре наклонённых внутрь ребра, "
        "горизонтальные пояса по высоте и диагональные раскосы между поясами. "
        "Начало координат башни — (300000, 0)."),
    "spiral": (
        "Винтовая башня: 20 ярусов по 4 м, на каждом ярусе восемь стоек по "
        "окружности радиусом 12 м, каждый ярус повёрнут на 9° относительно "
        "предыдущего; между ярусами — кольцевые обвязочные балки. "
        "Начало координат — (0, 0)."),
    "dome": (
        "Решётчатый купол радиусом 30 м: шесть широтных колец и шестнадцать "
        "меридианов из стальных стержней. Центр купола — (0, 0)."),
    "skyscraper": (
        "Башня делового центра высотой около 250 м: 60 надземных этажей по "
        "4 м, плита в плане примерно 45×45 м, сужающаяся кверху.\n\n"
        "Конструкции: свайный фундамент, ядро жёсткости в центре, колонны по "
        "периметру и по внутренней сетке на каждом этаже, балки перекрытий в "
        "двух направлениях, плиты перекрытий.\n"
        "Архитектура: наружное остекление по всему периметру каждого этажа, "
        "внутренние перегородки и помещения на типовом этаже, дверь в каждое "
        "помещение, лестницы и лифтовые шахты в ядре, кровля.\n\n"
        "Нужно здание целиком, а не силуэт. Начало координат — (0, 0)."),
    "moscowcity": (
        "Высотная башня делового центра сложной формы: эллиптический план "
        "примерно 44×30 м в основании, который заметно сужается кверху и "
        "закручивается вокруг вертикальной оси; криволинейная стеклянная "
        "оболочка. Высота 250–300 м, 55–60 этажей по 4.5 м.\n\n"
        "Конструкции: свайное поле, ядро жёсткости, колонны по периметру "
        "эллипса и по внутреннему кольцу, балки перекрытий, плита на каждом "
        "этаже.\n"
        "Архитектура: сплошное остекление по периметру каждого этажа, "
        "внутренние перегородки и помещения на типовом этаже, двери, кровля."
        "\n\nФорма важнее количества. Начало координат — (0, 0)."),
}


def _check_briefs_cover_the_corpus() -> None:
    """Корпус у рук обязан быть один. Задание, у которого нет нейтрального
    брифа, сравнивать нечем — и молча выпасть оно не должно."""
    missing = sorted(set(TASKS) - set(NEUTRAL_BRIEFS))
    extra = sorted(set(NEUTRAL_BRIEFS) - set(TASKS))
    if missing or extra:
        raise ValueError(f"корпус разошёлся: нет брифа {missing}, лишние {extra}")


_check_briefs_cover_the_corpus()

#: Имена операций KIR не смеют встречаться в нейтральном брифе — это и есть
#: заражение языком, за которым проверка следит механически, а не на глаз.
def _check_briefs_are_language_free() -> None:
    leaked: dict[str, list[str]] = {}
    for key, text in NEUTRAL_BRIEFS.items():
        hits = sorted(op for op in spec.OPS if op in text)
        if hits:
            leaked[key] = hits
    if leaked:
        raise ValueError(f"в нейтральные брифы протёк язык KIR: {leaked}")


_check_briefs_are_language_free()


# ────────────────────────────────────────────────────────── системные промпты

#: Один скелет на две руки. Отличаются ровно три места: имя инструмента, чем
#: он принимает работу и как дробится крупное. Всё остальное — тот же текст,
#: потому что любая лишняя строка у одной из рук становится частью замера.
SYSTEM_TEMPLATE = """Ты — инженер-моделировщик. Твой единственный инструмент — \
`{tool}`: {tool_line}

Правила ринга:

* Строй ТОЛЬКО через `{tool}`. Другого инструмента нет.
* {batching}
* Отказ — это данные. Прочитай его, исправь названное, повтори.
* Координаты — в миллиметрах, все геометрические расчёты делай сам и точно.
* Не описывай план текстом. Вызывай инструмент.
* Когда объект собран полностью — напиши "ГОТОВО"."""

KIR_TOOL_LINE = ("типизированные операции над моделью Revit. Компилятор владеет "
                 "единицами, версиями API и транзакциями; он проверяет каждую "
                 "программу и отказывает с названной причиной.")
KIR_BATCHING = ("Одна программа — не более 20 операций. Крупное собирается "
                "ПАЧКОЙ вызовов: вызывай инструмент столько раз, сколько "
                "нужно, пока объект не собран целиком.")

CS_TOOL_LINE = ("литеральный C#, который исполняется в Revit. Ты владеешь "
                "единицами, версиями API и транзакциями сам; код проверяется "
                "компилятором C# и отказывает с названной причиной.")
CS_BATCHING = ("Один вызов — одно тело метода. Крупное собирается ПАЧКОЙ "
               "вызовов: вызывай инструмент столько раз, сколько нужно, пока "
               "объект не собран целиком.")

#: Контракт руки B слово в слово по PHASE 0 прода (`execute_revit_code`,
#: USE_REVIT_CODER=0): та же сигнатура, те же пространства имён, то же
#: требование транзакции. Описание здесь СВОЁ, а не импортированное: прод-схема
#: несёт ещё шесть полей (task, model_context, previous_code, expects, …),
#: которые к замеру языка отношения не имеют и раздули бы справочный бюджет
#: руки B чужой работой.
CS_TOOL_DESCRIPTION = (
    "Выполнить работу с моделью Revit литеральным C#. "
    "Код исполняется как тело метода "
    "`public static object Execute(Document doc, UIDocument uidoc)`. "
    "Доступны пространства имён Autodesk.Revit.*, System, System.Linq, "
    "System.Collections.Generic, System.Text. "
    "Код обязан вернуть значение. "
    "Любая запись в модель должна быть обёрнута в Transaction. "
    "Нельзя System.IO, System.Net, System.Diagnostics.Process — "
    "никаких файловых и сетевых операций.")


def cs_tool_defs() -> list[dict]:
    return [{
        "type": "function",
        "function": {
            "name": "execute_revit_code",
            "description": CS_TOOL_DESCRIPTION,
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {"type": "string",
                             "description": "Литеральный C# — тело метода Execute."},
                },
                "required": ["code"],
            },
        },
    }]


# ────────────────────────────────────────────────────────────── судья Roslyn

@dataclass
class CompileVerdict:
    """Один проход через Roslyn."""
    passed: bool
    errors: list[dict] = field(default_factory=list)
    judge_ms: float = 0.0
    #: Сервис не ответил. Это факт стенда, а не отказ модели: засчитать его
    #: отказом значило бы приписать модели ошибку, которой она не делала.
    unavailable: bool = False


class RoslynJudge:
    """Один Roslyn на обе руки, через тот же клиент, что и боевые ворота.

    `CompileClient` асинхронный, а цикл стенда синхронный (модель ходит через
    urllib). Свой цикл событий живёт здесь и переживает весь прогон: клиент
    httpx привязывается к циклу, на котором создан, и цикл на вызов рвал бы
    соединение каждый раз.
    """

    def __init__(self, *, version: str = JUDGE_VERSION, client: Any = None,
                 base_url: str | None = None):
        self.version = version
        self._client = client
        self._base_url = base_url
        self._loop = None
        self.calls = 0

    def _ready(self):
        import asyncio
        if self._loop is None or self._loop.is_closed():
            self._loop = asyncio.new_event_loop()
        if self._client is None:
            self._client = (CompileClient(self._base_url) if self._base_url
                            else CompileClient())
        return self._loop, self._client

    def compile(self, body: str) -> CompileVerdict:
        """Тело метода -> вердикт. Обёртка — та же `wrap_user_code`, что в
        проде и в воротах: судить эмиссию другим враппером значит судить не то,
        что поедет на устройство."""
        loop, client = self._ready()
        wrapped = wrap_user_code(body or "")
        t0 = time.perf_counter()
        try:
            res = loop.run_until_complete(client.check(wrapped, self.version))
        except Exception as exc:  # noqa: BLE001 — сервис вне нашего процесса
            return CompileVerdict(False, [{"code": "SVC",
                                           "message": f"{type(exc).__name__}: {exc}"}],
                                  (time.perf_counter() - t0) * 1000, True)
        ms = (time.perf_counter() - t0) * 1000
        self.calls += 1
        if res is None:
            return CompileVerdict(False, [{"code": "SVC", "message": "нет ответа"}],
                                  ms, True)
        errs = [{"code": e.code, "message": e.message,
                 "line": e.line, "column": e.column} for e in res.errors]
        return CompileVerdict(bool(res.success), errs, ms)

    def preflight(self) -> bool:
        """Живая проверка ровно той версии, на которой судим.

        `CompileClient.health()` требует полную шестиверсионную матрицу — это
        контракт БОЕВЫХ ворот, а стенду нужна одна версия, и падать из-за
        отсутствующей 2021 он не должен."""
        v = self.compile("return 1;")
        return v.passed and not v.unavailable

    def close(self) -> None:
        if self._loop is not None and not self._loop.is_closed():
            try:
                self._loop.run_until_complete(self._client.close())
            except Exception:  # noqa: BLE001 — закрытие не должно ронять прогон
                pass
            self._loop.close()
        self._loop = None


# ──────────────────────────────────────────────────────────────── нормализация

#: Пять полей, из которых состоит пригодный для ремонта отказ. Доля
#: присутствующих — это `diagnostic_completeness`; асимметрия здесь ожидаемая и
#: она-то и есть предмет замера: у KIR отказ несёт ожидаемое значение и список
#: кандидатов, у Roslyn — строку и колонку.
DIAG_FIELDS = ("code", "location", "expected", "got", "candidates")


def normalize_kir_diag(d: dict) -> dict:
    loc = [d.get(k) for k in ("op_index", "op_id", "field_name")]
    return {
        "arm_code": d.get("code"),
        "code": d.get("code"),
        "location": next((x for x in loc if x is not None), None),
        "expected": d.get("expected"),
        "got": d.get("got"),
        "candidates": d.get("candidates") or None,
        "message": d.get("message_ru") or d.get("message"),
        "root": f"{d.get('code')}@{d.get('field_name') or d.get('op_id') or '-'}",
    }


def normalize_cs_error(e: dict) -> dict:
    line = e.get("line")
    return {
        "arm_code": e.get("code"),
        "code": e.get("code"),
        "location": f"L{line}:{e.get('column')}" if line else None,
        "expected": None,
        "got": None,
        "candidates": None,
        "message": e.get("message"),
        "root": str(e.get("code") or "?"),
    }


def diagnostic_completeness(diags: Iterable[dict]) -> float | None:
    """Средняя доля заполненных полей отказа. None — если отказов не было."""
    rows = [d for d in diags]
    if not rows:
        return None
    shares = [sum(1 for f in DIAG_FIELDS if d.get(f) not in (None, [], ""))
              / len(DIAG_FIELDS) for d in rows]
    return round(statistics.fmean(shares), 3)


#: Известные материализаторы Revit-API. Считаются ТОЛЬКО как
#: `static_create_call_sites` и только со словами «не эффект»: строка в тексте
#: не элемент в модели, и ревью (№10) вынесло этот счёт из сравнительных
#: метрик — офлайн он не отличает работающий код от правдоподобного.
CREATE_CALL_SITES = re.compile(
    r"\b(?:Wall\.Create|Floor\.Create|FootPrintRoof|ExtrusionRoof"
    r"|NewFamilyInstance|NewRoom|NewTag|NewTextNote|NewDimension"
    r"|Level\.Create|Grid\.Create(?:Linear|Arc)?|Pipe\.Create|Duct\.Create"
    r"|CableTray\.Create|Stairs\.Create|StairsRun\.CreateStraightRun"
    r"|Group\.Create|Document\.Create|doc\.Create\.)\s*\(")


def static_create_call_sites(text: str) -> int:
    return len(CREATE_CALL_SITES.findall(text or ""))


_TOKENIZER = None


def count_tokens(text: str) -> int:
    """Токены справочного бюджета.

    Считаются `cl100k_base`, а НЕ токенизатором прод-модели: её словарь нам
    недоступен. Число поэтому сравнимо между руками (одна линейка) и не
    сравнимо с чужими публикациями — так и написано в артефакте.
    """
    global _TOKENIZER
    if _TOKENIZER is None:
        import tiktoken
        _TOKENIZER = tiktoken.get_encoding("cl100k_base")
    return len(_TOKENIZER.encode(text or ""))


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()[:12]


# ─────────────────────────────────────────────────────────────────────── руки

@dataclass
class Submission:
    """Один сабмит: что модель предъявила и что с ним стало."""
    request_idx: int
    round_idx: int
    submission_idx: int
    #: Ступени пишутся раздельно и НИКОГДА не складываются в одну «зелень».
    kir_accept: bool | None
    roslyn_pass: bool
    diagnostics: list[dict]
    stage: str
    body_sha: str
    body_chars: int
    create_call_sites: int
    judge_ms: float
    extra: dict = field(default_factory=dict)


class Arm:
    """Общий скелет руки: промпт, инструмент, разбор сабмита, судья."""

    key = ""
    label = ""
    tool_name = ""

    def system_prompt(self) -> str:
        raise NotImplementedError

    def tools(self) -> list[dict]:
        raise NotImplementedError

    def body_of(self, args: dict) -> Any:
        """Аргументы вызова -> то, что судится."""
        raise NotImplementedError

    def judge(self, body: Any, roslyn: RoslynJudge) -> Submission:
        raise NotImplementedError

    def normalized(self, body: Any) -> str:
        """Текст сабмита для сравнения «изменился ли повтор»."""
        raise NotImplementedError

    def reference_budget(self) -> dict:
        sys_t = count_tokens(self.system_prompt())
        tool_t = count_tokens(json.dumps(self.tools(), ensure_ascii=False))
        return {"system_tokens": sys_t, "tool_tokens": tool_t,
                "reference_tokens": sys_t + tool_t}


class KirArm(Arm):
    key, label, tool_name = "A_kir", "KIR", "revit_ir"

    def __init__(self) -> None:
        self.snapshot = kir_dojo.ground_snapshot()

    def system_prompt(self) -> str:
        return SYSTEM_TEMPLATE.format(tool=self.tool_name,
                                      tool_line=KIR_TOOL_LINE,
                                      batching=KIR_BATCHING)

    def tools(self) -> list[dict]:
        return kir_dojo.tool_defs()

    def body_of(self, args: dict) -> Any:
        return args.get("program", args)

    def normalized(self, body: Any) -> str:
        try:
            return json.dumps(body, sort_keys=True, ensure_ascii=False)
        except TypeError:
            return repr(body)

    def judge(self, body: Any, roslyn: RoslynJudge) -> Submission:
        t0 = time.perf_counter()
        # Эмиссия просится ИМЕННО той версии, на которой её потом судят:
        # эмиссия per-version (SPEC 11.2), и код, собранный под 2026, на
        # референсах 2023 может не собраться по причине, к языку отношения не
        # имеющей. Такой отказ записался бы в стоимость KIR — то есть стенд
        # предъявил бы руке A дефект собственной оснастки.
        res = kir_dojo.judge(body, self.snapshot,
                             revit_version=roslyn.version)
        kir_ms = (time.perf_counter() - t0) * 1000
        if res.get("harness_error"):
            return Submission(0, 0, 0, None, False,
                              [{"code": "HARNESS", "message": res["harness_error"],
                                "root": "HARNESS"}],
                              "harness_error", _sha(self.normalized(body)),
                              len(self.normalized(body)), 0, kir_ms)
        if not res.get("ok"):
            diags = [normalize_kir_diag(d) for d in res.get("diagnostics", [])]
            return Submission(0, 0, 0, False, False, diags, "kir_refused",
                              _sha(self.normalized(body)),
                              len(self.normalized(body)), 0, kir_ms)
        # Принято языком — теперь ТА ЖЕ эмиссия идёт в ТОТ ЖЕ Roslyn, что судит
        # руку B. Без этой ступени «зелень» двух рук была бы разными событиями
        # (ревью №1, №2): `compile_program()` Roslyn не зовёт вовсе.
        cs = res.get("csharp") or ""
        v = roslyn.compile(cs)
        diags = [normalize_cs_error(e) for e in v.errors]
        return Submission(
            0, 0, 0, True, v.passed, diags,
            "ok" if v.passed else ("judge_unavailable" if v.unavailable
                                   else "roslyn_failed"),
            _sha(self.normalized(body)), len(self.normalized(body)),
            static_create_call_sites(cs), kir_ms + v.judge_ms,
            {"cs_chars": len(cs),
             "elements": kir_dojo.elements_in(body),
             "judge_unavailable": v.unavailable})


class CSharpArm(Arm):
    key, label, tool_name = "B_csharp", "raw Revit-C#", "execute_revit_code"

    def system_prompt(self) -> str:
        return SYSTEM_TEMPLATE.format(tool=self.tool_name,
                                      tool_line=CS_TOOL_LINE,
                                      batching=CS_BATCHING)

    def tools(self) -> list[dict]:
        return cs_tool_defs()

    def body_of(self, args: dict) -> Any:
        code = args.get("code")
        return code if isinstance(code, str) else json.dumps(args, ensure_ascii=False)

    def normalized(self, body: Any) -> str:
        return re.sub(r"\s+", " ", str(body or "")).strip()

    def judge(self, body: Any, roslyn: RoslynJudge) -> Submission:
        v = roslyn.compile(str(body or ""))
        diags = [normalize_cs_error(e) for e in v.errors]
        return Submission(
            0, 0, 0, None, v.passed, diags,
            "ok" if v.passed else ("judge_unavailable" if v.unavailable
                                   else "roslyn_failed"),
            _sha(self.normalized(body)), len(str(body or "")),
            static_create_call_sites(str(body or "")), v.judge_ms,
            {"judge_unavailable": v.unavailable})


ARMS: dict[str, Callable[[], Arm]] = {"A_kir": KirArm, "B_csharp": CSharpArm}


# ────────────────────────────────────────────────────────── грамматика событий

DONE_RE = re.compile(r"\bготово\b", re.I)

#: Симметричный ответ инструмента. Ни состава, ни связности, ни счёта
#: элементов: доменный оракул отобран у обеих рук (§7.3 №7), а несимметричный
#: ответ сам стал бы преимуществом одной из рук.
ACCEPTED_RESULT = {"status": "принято", "note": "Компилятор принял этот вызов."}


def run_arm(arm: Arm, task_key: str, *, rounds: int, roslyn: RoslynJudge,
            verbose: bool = False) -> dict:
    """Один прогон одной руки над одним зданием.

    Грамматика событий (§7.5) держится здесь и только здесь:

    * `request_idx` — обращение к модели, включая повтор после пустого ответа;
    * `round_idx` — ответ, в котором модель что-то СДЕЛАЛА (пустой не считается
      и бюджет не ест — иначе половина раундов уходит на дыры, замеренные
      27.07);
    * `submission_idx` — предъявленный на суд вызов; в одном раунде их может
      быть несколько.
    """
    brief = NEUTRAL_BRIEFS[task_key]
    messages = [{"role": "system", "content": arm.system_prompt()},
                {"role": "user", "content": brief}]
    tools = arm.tools()
    budget = arm.reference_budget()

    rec: dict[str, Any] = {
        "arm": arm.key, "arm_label": arm.label, "task": task_key,
        "budget_rounds": rounds,
        "brief_tokens": count_tokens(brief),
        **budget,
        "prompt_tokens_initial": budget["reference_tokens"] + count_tokens(brief),
        "requests": 0, "rounds": 0, "submissions": 0,
        "empty_replies": 0, "no_call_rounds": 0, "transport_errors": [],
        "kir_accept_pass": 0, "kir_accept_fail": 0,
        "roslyn_pass": 0, "roslyn_fail": 0, "judge_unavailable": 0,
        "declared_done": False,
        "model_ms": 0.0, "judge_ms": 0.0,
        "events": [], "transcript": [],
    }
    subs: list[Submission] = []
    request_idx = round_idx = 0
    t_start = time.perf_counter()

    while round_idx < rounds and request_idx < rounds * 3:
        request_idx += 1
        rec["requests"] = request_idx
        t0 = time.perf_counter()
        try:
            resp = call_model(messages, tools)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            rec["model_ms"] += (time.perf_counter() - t0) * 1000
            rec["transport_errors"].append({"request_idx": request_idx,
                                            "error": str(exc)})
            break
        rec["model_ms"] += (time.perf_counter() - t0) * 1000

        choice = (resp.get("choices") or [{}])[0]
        msg = choice.get("message") or {}
        calls = msg.get("tool_calls") or []
        text = (msg.get("content") or "").strip()

        if not calls and not text:
            rec["empty_replies"] += 1
            rec["events"].append({"request_idx": request_idx, "kind": "empty"})
            continue

        round_idx += 1
        rec["rounds"] = round_idx
        messages.append({"role": "assistant", "content": msg.get("content") or "",
                         "tool_calls": calls or None})

        if not calls:
            rec["no_call_rounds"] += 1
            rec["transcript"].append({"kind": "text", "round_idx": round_idx,
                                      "text": text})
            if DONE_RE.search(text):
                rec["declared_done"] = True
                rec["events"].append({"request_idx": request_idx,
                                      "round_idx": round_idx, "kind": "declared_done"})
                break
            messages.append({"role": "user", "content":
                             f"Ты не вызвал инструмент. Вызови `{arm.tool_name}` "
                             f"и продолжай."})
            continue

        for call in calls:
            fn = (call.get("function") or {}).get("name")
            raw = (call.get("function") or {}).get("arguments") or "{}"
            rec["submissions"] += 1
            sub_idx = rec["submissions"]
            try:
                args = json.loads(raw)
            except json.JSONDecodeError as exc:
                sub = Submission(request_idx, round_idx, sub_idx, None, False,
                                 [{"code": "BADJSON", "message": str(exc),
                                   "root": "BADJSON"}],
                                 "bad_json", _sha(raw), len(raw), 0, 0.0)
            else:
                if fn != arm.tool_name:
                    sub = Submission(request_idx, round_idx, sub_idx, None, False,
                                     [{"code": "NOTOOL",
                                       "message": f"нет инструмента {fn}",
                                       "root": "NOTOOL"}],
                                     "wrong_tool", _sha(raw), len(raw), 0, 0.0)
                else:
                    body = arm.body_of(args)
                    sub = arm.judge(body, roslyn)
                    sub.request_idx, sub.round_idx = request_idx, round_idx
                    sub.submission_idx = sub_idx
                    sub.extra["normalized"] = arm.normalized(body)
                    sub.extra["body"] = body

            subs.append(sub)
            rec["judge_ms"] += sub.judge_ms
            if sub.kir_accept is True:
                rec["kir_accept_pass"] += 1
            elif sub.kir_accept is False:
                rec["kir_accept_fail"] += 1
            if sub.stage == "judge_unavailable":
                rec["judge_unavailable"] += 1
            elif sub.roslyn_pass:
                rec["roslyn_pass"] += 1
            else:
                rec["roslyn_fail"] += 1

            rec["events"].append({
                "request_idx": sub.request_idx, "round_idx": sub.round_idx,
                "submission_idx": sub.submission_idx, "kind": "submission",
                "stage": sub.stage, "kir_accept": sub.kir_accept,
                "roslyn_pass": sub.roslyn_pass,
                "codes": [d.get("code") for d in sub.diagnostics][:5],
                "judge_ms": round(sub.judge_ms, 1)})
            # Тело сабмита пишется ЦЕЛИКОМ. Без него запись прогона — это
            # столбик исходов, по которому нельзя построить то, ради чего
            # транскрипты и собираются: карту мест, где модель думает
            # по-сишарпному. Хэш отвечает на «то же самое или новое», текст —
            # на «что именно».
            rec["transcript"].append({
                "kind": "submission",
                "round_idx": sub.round_idx, "submission_idx": sub.submission_idx,
                "stage": sub.stage, "body_sha": sub.body_sha,
                "body_chars": sub.body_chars,
                "create_call_sites": sub.create_call_sites,
                "body": sub.extra.get("body"),
                "diagnostics": sub.diagnostics})

            if verbose:
                print(f"  [{arm.key}] s{sub.submission_idx} {sub.stage} "
                      f"{[d.get('code') for d in sub.diagnostics][:3]}", flush=True)

            result = (dict(ACCEPTED_RESULT) if sub.roslyn_pass else
                      {"status": "отказ",
                       "diagnostics": [
                           {k: v for k, v in d.items()
                            if k not in ("root",) and v not in (None, [], "")}
                           for d in sub.diagnostics[:8]]})
            rec["transcript"][-1]["tool_reply"] = result
            messages.append({"role": "tool",
                             "tool_call_id": call.get("id", ""),
                             "content": json.dumps(result, ensure_ascii=False)})

    rec["wall_s"] = round(time.perf_counter() - t_start, 2)
    rec["model_ms"] = round(rec["model_ms"], 1)
    rec["judge_ms"] = round(rec["judge_ms"], 1)
    rec.update(outcome_metrics(subs, rounds=rounds,
                               declared_done=rec["declared_done"]))
    return rec


def outcome_metrics(subs: list[Submission], *, rounds: int,
                    declared_done: bool) -> dict:
    """Метрики §7.5 из последовательности сабмитов.

    Правостороннее цензурирование, а не ∞: прогон, который не дошёл до зелени
    за бюджет, — это НАБЛЮДЕНИЕ «дольше бюджета», и медиана по таким наборам
    считается с оглядкой на них, а не по подставленной бесконечности.
    """
    first_pass = next((s.submission_idx for s in subs if s.roslyn_pass), None)
    first_kir = next((s.submission_idx for s in subs if s.kir_accept), None)

    repair_rounds = 0
    for prev, cur in zip(subs, subs[1:]):
        if not prev.roslyn_pass and (cur.extra.get("normalized")
                                     != prev.extra.get("normalized")):
            repair_rounds += 1

    # repair@1: у отказа есть следующий сабмит — исчезла ли из него названная
    # причина? Причина нормализуется до пары код+поле (KIR) или кода (C#), так
    # что «поправил другое место того же вида» не засчитывается за ремонт.
    tries, fixed = 0, 0
    for prev, cur in zip(subs, subs[1:]):
        roots = {d.get("root") for d in prev.diagnostics if d.get("root")}
        if prev.roslyn_pass or not roots:
            continue
        tries += 1
        if not (roots & {d.get("root") for d in cur.diagnostics}):
            fixed += 1

    all_diags = [d for s in subs for d in s.diagnostics]
    return {
        "attempts_to_compile_pass": first_pass,
        "censored": first_pass is None,
        "attempts_to_kir_accept": first_kir,
        "repair_rounds": repair_rounds,
        "repair_at_1": round(fixed / tries, 3) if tries else None,
        "repair_at_1_n": tries,
        "diagnostic_completeness": diagnostic_completeness(all_diags),
        "refusal_codes": _tally(d.get("code") for d in all_diags),
        # `task_pass` — единственный первичный исход, и он НЕ доменный:
        # офлайн ни у одной руки нет способа доказать, что здание правильное
        # (рука B не исполняется вовсе). Поэтому здесь честный суррогат —
        # «хоть один сабмит скомпилировался И модель объявила готовность», а
        # доменный оракул откладывается до живой фазы. Иначе одна рука судилась
        # бы по зданию, вторая по тексту.
        "task_pass": bool(first_pass is not None and declared_done),
        "static_create_call_sites": sum(s.create_call_sites for s in subs),
        "elements_from_accepted": sum(int(s.extra.get("elements") or 0)
                                      for s in subs if s.roslyn_pass),
    }


def _tally(items: Iterable[Any]) -> dict[str, int]:
    out: dict[str, int] = {}
    for it in items:
        if it is None:
            continue
        out[str(it)] = out.get(str(it), 0) + 1
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))


# ──────────────────────────────────────────────────────────── парные блоки

def run_block(task_key: str, *, rounds: int, roslyn: RoslynJudge, order: str,
              block: int, bench_id: str, verbose: bool = False) -> list[dict]:
    """Один парный блок: обе руки на одном брифе, в названном порядке."""
    keys = ["A_kir", "B_csharp"] if order == "AB" else ["B_csharp", "A_kir"]
    out = []
    for k in keys:
        arm = ARMS[k]()
        if verbose:
            print(f"=== блок {block} {order}: {k} / {task_key} ===", flush=True)
        rec = run_arm(arm, task_key, rounds=rounds, roslyn=roslyn, verbose=verbose)
        rec.update({"bench_id": bench_id, "block": block, "order": order})
        out.append(rec)
    return out


def fingerprints(*, rounds: int, blocks: int) -> dict:
    """Замораживается всё, от чего число зависит.

    Вывод формулируется про КОНКРЕТНЫЙ снапшот модели и КОНКРЕТНЫЙ коммит
    компилятора (§7.8) — без этих полей запись прогона не воспроизводима и
    сравнивать два прогона нельзя.
    """
    def _git(*args: str) -> str:
        try:
            return subprocess.run(["git", *args], cwd=BACKEND, capture_output=True,
                                  text=True, timeout=10).stdout.strip()
        except Exception:  # noqa: BLE001
            return "?"

    arms = {k: cls() for k, cls in ARMS.items()}
    return {
        "model": kir_dojo._env("KUKAI_CODEXPROXY_MODEL", "gpt-5.6-terra"),
        "proxy_url": kir_dojo._env("KUKAI_CODEXPROXY_URL", "http://127.0.0.1:8317"),
        "backend_commit": _git("rev-parse", "HEAD"),
        "backend_dirty": bool(_git("status", "--porcelain")),
        "ir_version": spec.IR_VERSION,
        "judge_revit_version": JUDGE_VERSION,
        "ops_in_registry": len(spec.OPS),
        "compiler_sha": _sha((BACKEND / "kukai" / "ir" / "compiler.py")
                             .read_text("utf-8", "replace")),
        "fixtures_sha": _sha(json.dumps(kir_dojo.ground_snapshot(),
                                        sort_keys=True, ensure_ascii=False)),
        "briefs_sha": _sha(json.dumps(NEUTRAL_BRIEFS, sort_keys=True,
                                      ensure_ascii=False)),
        "system_prompt_sha": {k: _sha(a.system_prompt()) for k, a in arms.items()},
        "tool_doc_sha": {k: _sha(json.dumps(a.tools(), ensure_ascii=False))
                         for k, a in arms.items()},
        "reference_tokens": {k: a.reference_budget()["reference_tokens"]
                             for k, a in arms.items()},
        "tokenizer": "cl100k_base (не токенизатор прод-модели)",
        "rounds_budget": rounds,
        "blocks": blocks,
        "wrapper": "kukai.llm.revit_execution_pipeline.wrap_user_code",
    }


# ───────────────────────────────────────────────────────────────────── отчёт

#: Печатается ПЕРВОЙ строкой отчёта, до любого числа. Перепись перед
#: процентами: читатель должен узнать, чем руки неравны, раньше, чем увидит,
#: какая выиграла.
HEADER_STATEMENT = (
    "**Асимметрия судей и estimand — читать до чисел.** Обе руки судит ОДИН "
    "Roslyn на одной версии {ver}, но у руки A перед ним стоит ещё ступень "
    "`kir_accept` (типизированный разбор, границы, постусловия), которой у "
    "руки B нет в природе: сравнение по оси компиляции честно только по "
    "`roslyn_pass`, а `kir_accept` — промежуточная ступень, не «зелень». "
    "Estimand — ПОВЕРХНОСТЬ ЯЗЫКА: чего стоит довести замысел до принимаемой "
    "формы и годится ли отказ для ремонта. Правильность здания здесь НЕ "
    "меряется: офлайн её нечем проверить у руки B, поэтому доменный оракул "
    "отобран у ОБЕИХ рук, а `task_pass` — суррогат «скомпилировалось и модель "
    "объявила готовность». `static_create_call_sites` — НЕ ЭФФЕКТ: это строки "
    "в тексте, а не элементы в модели. Корпус — dev-set, настроенный на KIR; "
    "публикуемое число требует held-out корпуса.")


def censored_median(values: list[int | None], budget: int) -> str:
    """Медиана с правосторонним цензурированием, названным вслух."""
    seen = [v for v in values if v is not None]
    n_cens = len(values) - len(seen)
    if not seen:
        return f"— (все {n_cens} цензурированы на {budget})"
    med = statistics.median(seen)
    tail = f"; {n_cens} цензурировано на {budget}" if n_cens else ""
    return f"{med:g} (n={len(seen)}{tail})"


def summarize(records: list[dict], fp: dict) -> str:
    lines = [HEADER_STATEMENT.format(ver=fp["judge_revit_version"]), ""]
    lines.append(f"Модель: `{fp['model']}` · коммит `{fp['backend_commit'][:12]}`"
                 f"{' (дерево грязное)' if fp['backend_dirty'] else ''} · "
                 f"брифы `{fp['briefs_sha']}` · бюджет {fp['rounds_budget']} "
                 f"раундов · блоков {fp['blocks']}")
    lines.append("")
    lines.append(f"Справочный бюджет (не выравнивался, публикуется): "
                 f"A={fp['reference_tokens']['A_kir']} токенов, "
                 f"B={fp['reference_tokens']['B_csharp']} токенов "
                 f"({fp['tokenizer']}).")
    lines.append("")
    lines.append("| задание | рука | task_pass | сабмитов до roslyn_pass | "
                 "repair_rounds | repair@1 | полнота отказа | "
                 "create-сайты (не эффект) | model_ms | judge_ms |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|")

    def _mean(vals: list) -> str:
        clean = [v for v in vals if v is not None]
        return f"{statistics.fmean(clean):.2f}" if clean else "—"

    by_cell: dict[tuple[str, str], list[dict]] = {}
    for r in records:
        by_cell.setdefault((r["task"], r["arm"]), []).append(r)
    for (task, arm), rows in sorted(by_cell.items()):
        cells = [
            task, arm,
            f"{sum(1 for r in rows if r['task_pass'])}/{len(rows)}",
            censored_median([r["attempts_to_compile_pass"] for r in rows],
                            fp["rounds_budget"]),
            f"{statistics.median([r['repair_rounds'] for r in rows]):g}",
            _mean([r["repair_at_1"] for r in rows]),
            _mean([r["diagnostic_completeness"] for r in rows]),
            str(sum(r["static_create_call_sites"] for r in rows)),
            f"{statistics.median([r['model_ms'] for r in rows]):.0f}",
            f"{statistics.median([r['judge_ms'] for r in rows]):.0f}",
        ]
        lines.append("| " + " | ".join(cells) + " |")
    lines.append("")
    lines.append("Цензурирование: «сабмитов до roslyn_pass» считается только по "
                 "прогонам, которые дошли; недошедшие названы отдельно и НЕ "
                 "заменены бесконечностью.")
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────── CLI

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", action="append", choices=sorted(NEUTRAL_BRIEFS))
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--rounds", type=int, default=20)
    ap.add_argument("--blocks", type=int, default=2,
                    help="парных блоков на задание; чётное — порядок AB/BA "
                         "чередуется, иначе порядок станет смещением")
    ap.add_argument("--out", default="runs/mission_bench-1",
                    help="префикс: <out>.jsonl + <out>.md")
    ap.add_argument("--judge-url", default=None)
    ap.add_argument("--model", default=None,
                    help="ступень лестницы моделей: переопределяет "
                         "KUKAI_CODEXPROXY_MODEL на время этого прогона "
                         "(иначе берётся из .env/окружения, как раньше)")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args(argv)

    if a.blocks % 2:
        print(f"--blocks обязан быть чётным (дано {a.blocks}): при нечётном "
              f"одна из рук ходит первой чаще, и порядок становится смещением")
        return 2

    if a.model:
        # `_env()` в kir_dojo смотрит СНАЧАЛА в os.environ, потом в .env — эта
        # строка и есть переопределение ступени; она видна во всех местах,
        # которые читают модель через `_env` (call_model, fingerprints), без
        # правки самого dojo.
        import os as _os
        _os.environ["KUKAI_CODEXPROXY_MODEL"] = a.model

    keys = sorted(NEUTRAL_BRIEFS) if a.all else (a.task or ["house"])
    roslyn = RoslynJudge(base_url=a.judge_url)
    if not roslyn.preflight():
        print(f"FATAL: compile-сервис не судит {JUDGE_VERSION} — прогон без "
              f"судьи дал бы отказы, которых модель не делала")
        return 2

    bench_id = f"mb-{int(time.time())}"
    fp = fingerprints(rounds=a.rounds, blocks=a.blocks)
    records: list[dict] = []
    try:
        for task_key in keys:
            for block in range(a.blocks):
                order = "AB" if block % 2 == 0 else "BA"
                records += run_block(task_key, rounds=a.rounds, roslyn=roslyn,
                                     order=order, block=block, bench_id=bench_id,
                                     verbose=not a.quiet)
    finally:
        roslyn.close()

    out = pathlib.Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.with_suffix(".jsonl").open("w", encoding="utf-8") as f:
        f.write(json.dumps({"kind": "run_header", "bench_id": bench_id,
                            "fingerprints": fp,
                            "statement": HEADER_STATEMENT.format(
                                ver=fp["judge_revit_version"])},
                           ensure_ascii=False) + "\n")
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    report = summarize(records, fp)
    out.with_suffix(".md").write_text(report + "\n", encoding="utf-8")
    print(report)
    print(f"\nwrote {len(records)} записей → {out.with_suffix('.jsonl')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
