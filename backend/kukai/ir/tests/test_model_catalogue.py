"""КАТАЛОГ ДОКУМЕНТА В РУКАХ СКРИПТА — перечисление становится ПРАВИЛОМ.

ЗАМЕР, РАДИ КОТОРОГО ЭТО СДЕЛАНО (14.08.2026, `data/telemetry/
kir_rejections.jsonl`, 1558 строк = 314 ПОПЫТОК авторства, 16.07–14.08):
«слепота к каталогу» — **29.9% попыток**, крупнейший класс отказов. До этой
волны в пространстве авторского скрипта было 98 имён, и НИ ОДНО не читало
документ, в который скрипт пишет: `spec()` печатает реестр, `course()` — курс,
`preview()` рисует ПРОГРАММУ, `design_check()` судит её же. Имена типов,
уровней и осей автор угадывал.

ЧТО ЗДЕСЬ ПРОВЕРЯЕТСЯ, И ЧЕГО НЕ ОБЕЩАЕТСЯ.

Проверяется, что каталог ДОЕЗЖАЕТ и что перечисление превращается в правило:
`for lvl in model.levels()` вместо выписанных этажей. Это и есть перевод
внимания с API на геометрию — а не «меньше отказов», которое лишь следствие.

НЕ обещается геометрия здания: снапшот заземления несёт КАТАЛОГИ и не несёт ни
одной стены и ни одной комнаты (замерено — `OfClass(typeof(Wall))` и
`OST_Rooms` встречаются в `open_model.py` НОЛЬ раз). «Комнаты без окна» этим
объектом не отвечаются, и ни один метод не должен намекать, что отвечаются.

ГЛАВНЫЙ ТЕСТ ФАЙЛА — НЕ ПЕРВЫЙ, А ПОСЛЕДНИЙ: власть осталась у заземления.
Каталог — снимок на момент чтения; если он устарел, программа всё равно
перезаземляется по СВЕЖЕМУ снимку и отказывает. Без этого теста новая
способность была бы новым способом построить неверное молча.
"""
from __future__ import annotations

import asyncio
import unittest

from kukai.ir import serving
from kukai.ir.compiler import compile_program
from kukai.ir.sandbox import ModelCatalog, execute_author_script, _model_pools

CATALOGUE = {
    "levels": [
        {"id": 1, "name": "Этаж 1", "elevation_mm": 0},
        {"id": 2, "name": "Этаж 2", "elevation_mm": 3000},
        {"id": 3, "name": "Этаж 3", "elevation_mm": 6000},
    ],
    "grids": [{"id": 7, "name": "А"}, {"id": 8, "name": "Б"}],
    "wall_types": [{"id": 40, "name": "Кирпич 380", "instances": 500},
                   {"id": 41, "name": "ГКЛ 100", "instances": 12}],
    # Служебное: факты о ЧТЕНИИ, а не о здании. Скрипту видны быть не должны.
    "__document_fingerprint": {"title": "Дом"},
    "levels__total": 3,
    "levels__truncated": True,
}

#: Тот самый переход, ради которого всё: этаж НЕ выписан, а выведен из каталога.
RULE_SCRIPT = """
envelope(intent="по этажу на каждый уровень документа")
for lvl in model.levels():
    create_wall(p0_mm=[0, 0], p1_mm=[6000, 0],
                level=by_name(lvl["name"]), height_mm=3000)
"""


def test_the_script_writes_a_rule_over_the_real_levels():
    """Три уровня в документе -> три стены, и ни один этаж не выписан руками."""
    result = execute_author_script(RULE_SCRIPT, model=CATALOGUE)
    assert result.ok, result.refusal and result.refusal.as_dict()
    assert len(result.ops) == len(CATALOGUE["levels"]) == 3
    named = [op["level"]["value"] for op in result.ops]
    assert named == ["Этаж 1", "Этаж 2", "Этаж 3"], named


def test_without_a_catalogue_the_name_still_exists_and_says_why():
    """Отсутствие имени читалось бы как «такой способности нет» — а она есть.

    Поэтому `model` кладётся ВСЕГДА, и пустой каталог отвечает названной
    причиной, которую модель может прочитать и починить свой ход.
    """
    result = execute_author_script(RULE_SCRIPT)
    assert not result.ok
    detail = result.refusal.as_dict()
    assert "каталог документа не подан" in str(detail), detail


def test_an_unknown_pool_names_what_did_arrive():
    """Молчаливый пустой список означал бы «таких типов в документе нет»."""
    result = execute_author_script(
        'envelope(intent="x")\nmodel.types("двери")\n', model=CATALOGUE)
    assert not result.ok
    detail = str(result.refusal.as_dict())
    assert "двери" in detail and "wall_types" in detail, detail


def test_reading_facts_never_reach_the_script():
    """`__document_fingerprint` и `*__total` — про ЧТЕНИЕ, а не про здание.

    Скрипт, ветвящийся на них, ветвился бы на нашей внутренней кухне, и его
    программа менялась бы от того, обрезал ли коллектор пул.
    """
    result = execute_author_script(
        'envelope(intent="x")\nprint(sorted(model.pools()))\n'
        'create_level(elev_mm=0, name="Э")\n', model=CATALOGUE)
    assert result.ok, result.refusal and result.refusal.as_dict()
    assert result.stdout.strip() == "['grids', 'levels', 'wall_types']"


def test_the_catalogue_is_signed_separately_from_the_source():
    """Третий подписант: правка скрипта отличима от дрейфа модели.

    Тот же довод, что у подписи среды в шапке `sandbox`: без отдельной подписи
    один `author_digest` удостоверял бы РАЗНЫЕ программы, и читатель не имел бы
    ни одного поля, чтобы понять, что изменилось — текст или здание.
    """
    one = execute_author_script(RULE_SCRIPT, model=CATALOGUE)
    fewer = {**CATALOGUE, "levels": CATALOGUE["levels"][:2]}
    two = execute_author_script(RULE_SCRIPT, model=fewer)
    assert one.author_digest == two.author_digest      # текст не менялся
    assert one.model_digest != two.model_digest        # здание менялось
    assert one.program_digest != two.program_digest    # и программа тоже
    assert len(two.ops) == 2


def test_no_catalogue_means_no_signature_rather_than_an_empty_one():
    """Пустая подпись читалась бы как «каталог был и оказался пуст»."""
    assert execute_author_script(
        'envelope(intent="x")\ncreate_level(elev_mm=0, name="Э")\n'
    ).model_digest == ""


def test_the_catalogue_is_read_only():
    """Скрипт, дописавший строку, подписал бы документ, которого нет."""
    catalogue = ModelCatalog({"levels": [{"id": 1, "name": "Э"}]}, "d")
    rows = catalogue.levels()
    rows[0]["name"] = "подмена"
    assert catalogue.levels()[0]["name"] == "Э"


# ─────────────────────────────────────────────────────────────────────────
# ЖИВОЙ ПУТЬ: каталог доезжает до скрипта и его подпись — до квитанции
# ─────────────────────────────────────────────────────────────────────────

class _Bridge:
    """Мост, отдающий ровно каталог. Считает, сколько раз его спросили."""

    def __init__(self, payload=CATALOGUE):
        self.payload = payload
        self.calls = 0


def _authored(args, bridge: _Bridge | None):
    """Прогнать дверь авторства, подменив ОДИН шов — добытчик каталога.

    Подменяется не мост и не песочница, а именно `_document_catalogue`: он и
    есть то новое, что здесь проверяется, и подмена ярусом ниже мерила бы
    заодно транспорт, к которому этот тест отношения не имеет.
    """
    original = serving._document_catalogue

    async def fake(llm_client, bridge_callback):
        if bridge is None:
            return None
        bridge.calls += 1
        return bridge.payload

    serving._document_catalogue = fake                      # type: ignore[assignment]
    try:
        return asyncio.run(serving._authored_input(args, object(), object()))
    finally:
        serving._document_catalogue = original              # type: ignore[assignment]


def test_the_catalogue_reaches_the_script_through_the_live_door():
    bridge = _Bridge()
    authored = _authored({"program_py": RULE_SCRIPT}, bridge)
    assert authored.refusal is None, authored.refusal
    assert len(authored.args["program"]["ops"]) == 3
    assert bridge.calls == 1
    assert authored.model_digest
    assert authored.receipt["model_digest"] == authored.model_digest


def test_a_json_program_pays_nothing_for_this():
    """Обычный путь JSON сюда не заходит — ни одного лишнего рейса к мосту."""
    bridge = _Bridge()
    authored = _authored(
        {"program": {"ir_version": "1.0",
                     "ops": [{"op": "query_count", "id": "q", "kind": "wall"}]}},
        bridge)
    assert authored.refusal is None
    assert bridge.calls == 0
    assert authored.model_digest == ""


def test_a_silent_bridge_does_not_cancel_the_turn():
    """Каталог — удобство. Неудача вспомогательного чтения не отменяет ход."""
    authored = _authored(
        {"program_py": 'envelope(intent="x")\ncreate_level(elev_mm=0, name="Э")\n'},
        None)
    assert authored.refusal is None, authored.refusal
    assert authored.model_digest == ""


# ─────────────────────────────────────────────────────────────────────────
# ГЛАВНОЕ: ВЛАСТЬ ОСТАЛАСЬ У ЗАЗЕМЛЕНИЯ
# ─────────────────────────────────────────────────────────────────────────

def test_a_stale_catalogue_cannot_build_the_wrong_thing_through_a_selector():
    """Каталог устарел, скрипт назвал ушедший уровень — заземление ОТКАЗЫВАЕТ.

    Это и есть цена входа для новой способности. Каталог — снимок на момент
    чтения, а не живая модель; если бы устаревшее чтение доезжало до постройки,
    мы бы завели новый способ построить неверное МОЛЧА — ровно то, против чего
    стоит весь пакет.

    ЧЕСТНАЯ ВТОРАЯ ПОЛОВИНА, названная здесь, а не спрятанная: защищён
    СЕЛЕКТОР, а не ЧИСЛО. Скрипт, ветвящийся на `len(model.levels())`, породит
    другую программу, и заземление её спокойно заземлит — потому что она
    корректна, просто не та, что автор написал бы сегодня. Каталог поэтому
    обязан быть свежим чтением, а не памятью о прошлом ходе.
    """
    result = execute_author_script(RULE_SCRIPT, model=CATALOGUE)
    assert result.ok and len(result.ops) == 3

    # Документ уехал: третьего этажа больше нет.
    live = {"levels": CATALOGUE["levels"][:2],
            "wall_types": CATALOGUE["wall_types"]}
    out = compile_program({"ir_version": "1.0", "ops": result.ops},
                          snapshot=live, bulk=True)
    assert not out.ok
    codes = [d.code for d in out.diagnostics]
    assert "KIR-G101" in codes, [d.as_dict() for d in out.diagnostics]


def test_the_control_can_fail():
    """Контроль-FAIL: без каталога правило не пишется вовсе.

    Прибор, который не умеет упасть, ничего не удостоверяет: если бы скрипт
    собирал три стены и БЕЗ каталога, первый тест этого файла не измерял бы
    ничего.
    """
    assert not execute_author_script(RULE_SCRIPT).ok
    assert execute_author_script(RULE_SCRIPT, model=CATALOGUE).ok


# ═════════════════════════════════════════════════════════════════════════
# ТРИ ИСХОДА ОДНОГО ВОПРОСА — и каждый обязан звучать по-своему (15.08.2026)
#
# ФОРМА 11 («один код для двух исходов»), найденная в этом же файле при
# сведении ветки. `ModelCatalog.__init__` держал `if kept:`, а `_model_pools`
# — такой же фильтр на входе, и пул, ПРИШЕДШИЙ ПУСТЫМ, выбрасывался наравне
# с пулом, которого не присылали. Дальше оба отвечали «пула нет в этом
# снимке», причём вторая половина фразы («Пришли: (каталог не подан)») была
# ложной: каталог был подан.
#
# Различие решает, ЧТО автору делать, и потому не косметическое:
#
#   пул пуст          факт О ЗДАНИИ — типов такого рода в документе нет.
#                     Верный ответ — пустой кортеж, и по нему автор ветвится;
#   пула не прислали  факт О НАС — не спросили. Верный ответ — ОТКАЗ,
#                     потому что «нет» здесь неправда;
#   каталога нет      офлайн-прогон. Верный ответ — свой, третий отказ.
#
# Дороже всего третий случай у `levels()`: документа Ревита без уровней не
# бывает, и тихий пустой кортеж там означал НАШ пробел чтения, а читался бы
# как факт о здании.
# ═════════════════════════════════════════════════════════════════════════

_ONE_LEVEL = {"levels": [{"id": "8001", "name": "Этаж 1"}]}


class ThreeOutcomesOfOneQuestion(unittest.TestCase):

    def test_an_empty_pool_is_a_fact_about_the_building(self):
        """Пул пришёл пустым — это ответ, а не отказ."""
        cat = ModelCatalog({**_ONE_LEVEL, "wall_types": []})
        self.assertEqual(cat.types("wall_types"), ())
        self.assertIn("wall_types", cat.pools())

    def test_a_pool_that_was_never_sent_refuses_and_says_whose_fault(self):
        """Пула не прислали — отказ, и он называет это фактом о ЧТЕНИИ."""
        cat = ModelCatalog(dict(_ONE_LEVEL))
        with self.assertRaises(KeyError) as caught:
            cat.types("wall_types")
        text = str(caught.exception)
        self.assertIn("НЕ ПРИСЛАЛИ", text)
        self.assertIn("levels", text)          # называет то, что ПРИШЛО

    def test_an_absent_catalogue_is_its_own_third_answer(self):
        with self.assertRaises(RuntimeError):
            ModelCatalog(None).levels()

    def test_levels_never_answers_a_silent_empty_tuple(self):
        """Самый дорогой случай: документа без уровней не бывает."""
        with self.assertRaises(KeyError):
            ModelCatalog({"wall_types": [{"id": "9", "name": "К"}]}).levels()

    def test_the_intake_filter_does_not_undo_the_distinction(self):
        """ОБА конца, иначе прибор закрывает часть диапазона.

        Каталог различал бы три исхода, а до него доезжало бы два: фильтр
        `_model_pools` стоит РАНЬШЕ и ронял пустой пул сам.
        """
        pools = _model_pools({**_ONE_LEVEL, "wall_types": []})
        self.assertIn("wall_types", pools, "пустой пул срезан на входе")
        self.assertEqual(pools["wall_types"], [])

    def test_the_control_can_fail(self):
        """КОНТРОЛЬ-FAIL: восстановление `if kept:` обязано покраснеть.

        Без него все пять проверок выше зелены по построению на любом
        каталоге, где пустых пулов не бывает.
        """
        as_before = {name: rows
                     for name, rows in {**_ONE_LEVEL, "wall_types": []}.items()
                     if rows}                                  # прежний фильтр
        self.assertNotIn("wall_types", as_before)
        with self.assertRaises(KeyError):
            ModelCatalog(as_before).types("wall_types")


# ─────────────────────────────────────────────────────────────────────────
# РЕЙС ТОЛЬКО ЗА ТЕМ, ЧТО СКРИПТ СПРОСИЛ
#
# Замер 16.08.2026, журнал прода, `EXEC_PIPELINE_RECORD op=script_catalogue`:
# рейс за каталогом стоит 3675 и 3262 мс и платился на КАЖДОМ ходе
# `program_py`. Разложение хода того же дня: модель 84.6 %, мост и Ревит
# 13.1 %, наш питон 0.44 % — то есть лишний рейс был вторым по величине
# куском хода после ожидания модели.
#
# Проверка надёжна не по удобству: каталог доезжает до скрипта РОВНО одним
# способом — именем в пространстве имён, а `globals`/`locals` скрипту
# запрещены как билтины. Не назвал имени — прочитать не может.
# ─────────────────────────────────────────────────────────────────────────

_NO_CATALOGUE = """
envelope(intent="стена без единого вопроса к документу")
create_wall(p0_mm=[0, 0], p1_mm=[6000, 0], level=by_name("Этаж 1"), height_mm=3000)
"""


def test_a_script_that_never_names_the_catalogue_pays_no_roundtrip():
    """ГЛАВНОЕ ЧИСЛО ВОЛНЫ: рейсов было 1, стало 0 — при том же результате."""
    bridge = _Bridge()
    authored = _authored({"program_py": _NO_CATALOGUE}, bridge)
    assert authored.refusal is None, authored.refusal
    assert len(authored.args["program"]["ops"]) == 1
    assert bridge.calls == 0, "рейс за каталогом, которого скрипт не спрашивал"


def test_a_script_that_names_it_still_gets_it():
    """Контроль с другой стороны границы: способность не отнята."""
    bridge = _Bridge()
    authored = _authored({"program_py": RULE_SCRIPT}, bridge)
    assert authored.refusal is None, authored.refusal
    assert bridge.calls == 1
    assert len(authored.args["program"]["ops"]) == 3
    assert authored.model_digest


def test_the_guess_errs_only_toward_the_extra_roundtrip():
    """Ошибка допустима в ОДНУ сторону, и это проверяется, а не обещается.

    Упоминание в комментарии каталогом не является — но рейс всё равно
    платится. Лишний рейс есть сегодняшняя цена; пропущенный был бы потерей
    способности у автора, который её попросил.
    """
    bridge = _Bridge()
    authored = _authored(
        {"program_py": '# про model тут только слово\n' + _NO_CATALOGUE},
        bridge)
    assert authored.refusal is None, authored.refusal
    assert bridge.calls == 1, "подстрока обязана ошибаться в сторону рейса"


def test_the_name_is_the_one_the_sandbox_actually_injects():
    """РАТЧЕТ. Переименуют имя в песочнице — рейс начнёт пропускаться МОЛЧА,
    и автор получит пустой каталог, не узнав почему. Тождество держит тест."""
    from kukai.ir import sandbox

    assert serving._CATALOGUE_NAME in sandbox.HOST_NAMES, (
        "имя каталога разошлось с пространством скрипта: %r против %s"
        % (serving._CATALOGUE_NAME, sorted(sandbox.HOST_NAMES)))
