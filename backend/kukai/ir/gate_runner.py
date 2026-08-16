"""6/6 compile-gate runner — the prod-path gate (SPEC §5, discipline item 4).

Wraps emitted Execute-bodies with the SAME wrap_user_code the serving pipeline
uses and drives the live kukai-compile.service (:52412) across all six Revit
versions. Exit code != 0 on any failure. Run:

    PYTHONPATH=backend backend/venv/bin/python -m kukai.ir.gate_runner

ЧТО ЭТИ ЧИСЛА УТВЕРЖДАЮТ, И ЧЕГО НЕ УТВЕРЖДАЮТ (12.08.2026). Вопрос ворот —
**собирается ли эмитированный C# на шести версиях Revit**, и ответ на него
честный: арбитр здесь — настоящие reference-сборки Autodesk, их sha256 печатается
рядом с итогом. Но всё, что требует заземления, заземляется против СИНТЕТИЧЕСКОЙ
фикстуры (`GROUND_SNAPSHOT_ORIGIN` ниже), а не против настоящего документа.
Значит «OK» у такой программы есть утверждение о фикстуре, и доля таких
компиляций теперь ПЕЧАТАЕТСЯ вместе с числом, а не помнится.

Почему это не педантизм: зона НАБОР померила 12.08, что у фикстуры не хватало
пула `roof_types`, и `create_roof`/`create_extrusion_roof` не заземлялись по
умолчанию нигде. Обошлось одним красным только потому, что пул объявлен
НЕОБЯЗАТЕЛЬНЫМ; обязательный в той же позиции обрушил бы ворота целиком — и
выглядело бы это как «оп сломан», а не как «модель бедна». Полнота фикстуры есть
свойство ВОРОТ, а не только набора.
"""
from __future__ import annotations

import asyncio
import math
import os
import random
import sys
import tempfile

os.environ.setdefault("KIR_REJECTIONS_PATH",
                      os.path.join(tempfile.gettempdir(), "kir_gate_queue.jsonl"))

from kukai.compile_client import CompileClient                     # noqa: E402
# 🔴 ПОЛУМЕРА, И ОНА НАЗВАНА (15.08.2026). Здесь стоял ВЕРХНЕУРОВНЕВЫЙ импорт
# продукта, из-за которого `kukai/ir/` — пакет, публикуемый отдельным
# репозиторием, — не импортировался без `kukai/llm`. Импорт стал отложенным:
# пакет теперь импортируется чисто, а продукт нужен только чтобы ворота
# ЗАПУСТИТЬ.
#
# ПОЧЕМУ НЕ ПЕРЕЕЗД, КОТОРЫЙ БЫЛ БЫ ЧЕСТНЕЕ. По предмету `wrap_user_code`
# компиляторная: она про эмитированный C#. Но её литералы
# (`WRAPPER_HEADER`/`WRAPPER_FOOTER`) пришпилены AST-СТОРОЖЕМ ДРИФТА, который
# держит ТРИ копии обёртки попарно синхронными (`chat_ws` legacy,
# `kukai/modeling/tests/bridge/test_exec_wrapper_sync.py`,
# `tests/test_revit_execution_pipeline.py`) и разбирает ИСХОДНИК того модуля.
# Переезд владельца без перенаправления этой схемы либо ломает сторожа, либо
# МОЛЧА его ослабляет — а три копии одной величины и есть именной дефект
# дерева. Это волна, а не строка, и до неё импорт остаётся отложенным.
def _wrap_user_code(code: str) -> str:
    from kukai.llm.revit_execution_pipeline import wrap_user_code
    return wrap_user_code(code)


wrap_user_code = _wrap_user_code
from kukai.ir import spec                                          # noqa: E402
# ВЕРСИЯ РЕВИТА ИМЕЕТ ОДИН ИСТОЧНИК. Литерал `"2023"` в умолчании параметра
# был СЕДЬМЫМ местом, выводящим версию, и его поймал закрытый реестр
# `tests/test_revit_version_has_one_source.py` — ровно за тем он и заведён.
from kukai.ir import revit_version as _rv                          # noqa: E402
from kukai.ir.compiler import compile_program                      # noqa: E402
from kukai.ir.op_contract import audit_contract_kernel             # noqa: E402
from kukai.ir.tests.test_golden import PROGRAMS                    # noqa: E402
from kukai.ir.tests.test_pbt import gen_program                    # noqa: E402

N_PBT = 25
SEED = 62026

#: Откуда ворота берут снимок для заземления. Синтетическая ФИКСТУРА, а не
#: настоящий документ: у неё заведомо меньше типов, пулов и элементов. Для
#: вопроса ворот («собирается ли C# на шести версиях») это законно, потому что
#: вопрос про КОМПИЛЯЦИЮ. Но любое «OK» у программы, требующей снимка, есть
#: утверждение о фикстуре, и печатать это обязано само число — см. итоговый
#: блок `main()`. Круговая сверка разворота фикстурой заземляться НЕ ВПРАВЕ:
#: там вопрос «воспроизводит ли разворот ЭТО здание», и бедность модели дала
#: бы расхождения от себя самой (решение директора 12.08 — снимок того
#: прогона, `open_model.profile.json`, есть в 73 прогонах из 80 — перемерено
#: 15.08.2026; прежняя запись «70 из 77» устарела вместе с корпусом).
GROUND_SNAPSHOT_ORIGIN = "kukai.ir.tests.fixtures.GROUND_SNAPSHOT"

# ═════════════════════════════════════════════════════════════════════════
# ВТОРАЯ ПОЛОСА: ЗАЗЕМЛЕНИЕ НАСТОЯЩИМ ДОКУМЕНТОМ
#
# Первая полоса отвечает «собирается ли C# на шести версиях» и заземляется
# ФИКСТУРОЙ. Вторая отвечает на ДРУГОЙ вопрос: «а заземляется ли эта программа
# документом, который кто-то действительно спроектировал». Ответы независимы, и
# складывать их нельзя: программа может собираться на всех шести и не иметь ни
# одного настоящего документа, которым её можно заземлить.
#
# МОСТА И ЖИВОГО РЕВИТА НЕ ТРЕБУЕТСЯ: каждый сохранённый разбор несёт
# `open_model.profile.json`, а `OpenModelProfile.to_ground_snapshot()` (модуль
# `open_model`) уже умеет превратить его в снимок той же формы, что фикстура.
# Здесь не пишется ни одного нового конвертера — спрашивается существующий.
#
# 🔴 ЧИСЛО, КОТОРОЕ ЛЕГКО ПРОЧЕСТЬ НЕВЕРНО. `required_pools` в профиле — это
# КОНСТАНТНЫЙ список из 36 имён, который штампуется в каждый профиль. «Объединение
# по корпусу = 36 = required» поэтому истинно и ПУСТО: оно говорит о списке, а не
# о содержимом. Замер 15.08.2026 по 73 профилям прода: пулов с НЕПУСТЫМИ
# записями — 28 из 36, а восемь не наполняются НИ В ОДНОМ разборе
# (`area_load_types`, `area_reinforcement_types`, `foundation_symbols`,
# `line_load_types`, `point_load_types`, `rebar_bar_types`, `rebar_hook_types`,
# `truss_types`). Отбор ниже спрашивает ЗАПИСИ, а не имена.

#: Корень сохранённых разборов. Тот же адрес, что читают `serving` и
#: `course.corpus` — одно имя переменной на весь проект.
REAL_PROFILE_ROOT = os.environ.get(
    "KUKAI_DECOMPILE_DATA",
    os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))), "backend", "data", "decompile"))

#: Как достать корпус, если его нет в этом дереве. Стоит РЯДОМ с отказом, а не
#: в чьей-то памяти: «сторож без прибора обязан отказывать в категории, которую
#: нельзя спутать с „находок нет“».
#:
#: 🔴 АДРЕС УСТАНОВКИ СЮДА НЕ ПИШЕТСЯ. Этот файл уезжает в опенсорс, и
#: абсолютный путь развёртывания в исполняемом коде — утечка, а не подсказка
#: (`tests/test_authority_boundaries.py` держит это запретом, и он поймал
#: первую редакцию строки). Подсказка называет ПЕРЕМЕННУЮ и форму адреса;
#: конкретный адрес принадлежит установке и живёт в её окружении.
REAL_PROFILE_FETCH_HINT = (
    "профилей не найдено. Корпус машинно-локален и в чекаут не входит; "
    "укажите его адрес переменной KUKAI_DECOMPILE_DATA — она ждёт каталог, в "
    "котором лежат подкаталоги разборов с файлом open_model.profile.json")


def pools_required_by(program: dict) -> frozenset[str]:
    """Пулы, которых программа требует ПОСЛЕ раскрытия макросов.

    Спрашивается РЕЕСТР (`OpSpec.grounded`), а не имена операций: пул с
    подстановкой `{category}` разрешается значением самой операции, потому что
    у колонны архитектурный и конструктивный пулы РАЗНЫЕ, и выбрать один
    значило бы заземлить половину программ не тем каталогом.

    Раскрытие макросов обязательно по той же причине, по которой оно
    обязательно у `_needs_snapshot`: стек прячет трубы, а требование пула
    несёт именно спрятанная операция.
    """
    from kukai.ir import macros as _macros

    ops = program.get("ops", [])
    try:
        ops = _macros.expand(ops)
    except Exception:          # noqa: BLE001 — компилятор откажет и назовёт причину
        pass
    need: set[str] = set()
    for op in ops if isinstance(ops, list) else []:
        if not isinstance(op, dict):
            continue
        ospec = spec.OPS.get(op.get("op"))
        if ospec is None:
            continue
        for _param, pool, _required in ospec.grounded:
            if "{category}" in pool:
                pool = pool.format(
                    category=op.get("category") or "structural")
            need.add(pool)
    return frozenset(need)


def load_real_profiles(root: str = "") -> list[tuple[str, dict, frozenset[str]]]:
    """`(имя прогона, снимок, множество НЕПУСТЫХ пулов)`, по имени прогона.

    Порядок детерминирован именем: ворота обязаны отвечать одинаково на двух
    прогонах подряд, а порядок каталога таковым не является.

    Пул с пустыми `entries` в множество НЕ ВХОДИТ: он объявлен и ничего не
    предлагает, а заземление по имени в пустом каталоге — отказ. Считать такой
    пул «имеющимся» значило бы получить зелёное там, где выбирать не из чего.
    """
    import glob as _glob
    import json as _json

    from kukai.ir.open_model import OpenModelProfile

    root = root or REAL_PROFILE_ROOT
    found: list[tuple[str, dict, frozenset[str]]] = []
    pattern = os.path.join(root, "*", "open_model.profile.json")
    for path in sorted(_glob.glob(pattern)):
        run = os.path.basename(os.path.dirname(path))
        try:
            with open(path, encoding="utf-8") as fh:
                profile = OpenModelProfile.from_dict(_json.load(fh))
            snapshot = profile.to_ground_snapshot()
        except Exception:      # noqa: BLE001 — битый профиль не роняет ворота
            continue
        filled = frozenset(
            name for name, rows in snapshot.items()
            if isinstance(rows, list) and rows)
        found.append((run, snapshot, filled))
    return found


def ground_on_real_document(
        program: dict,
        profiles: list[tuple[str, dict, frozenset[str]]],
        *, revit_version: str = _rv.DEFAULT_VERSION
        ) -> tuple[str, dict] | str:
    """Первый настоящий документ, которым программа ЗАЗЕМЛЯЕТСЯ, или причина.

    Возвращает `(имя прогона, снимок)` либо строку-причину — три исхода, а не
    два, и это ровно то различие, ради которого функция существует:

    * `нет профиля с пулами …` — ни один разбор корпуса не несёт нужных
      каталогов. Это факт о КОРПУСЕ;
    * `KIR-G101 …` / любой код отказа — каталоги есть, но программа названа
      словарём, которого в этих зданиях нет. Это факт о ПРОГРАММЕ;
    * успех — программа заземлена настоящим зданием.

    ПОЧЕМУ ПЕРЕБОР, А НЕ «ПЕРВЫЙ ПОДХОДЯЩИЙ». Первая редакция брала первый
    профиль, чьи пулы непусты, и получила 10 заземлённых из 69 при 29 отказах
    `KIR-G101` — все на одном и том же здании, оказавшемся первым по алфавиту.
    Пулы у него были, а ИМЕНА ТИПОВ — свои. «Заземляется ли программа настоящим
    документом» есть вопрос про СУЩЕСТВОВАНИЕ такого документа, поэтому
    перебираются все кандидаты. Выбор без перебора — выбор без акта
    различения.
    """
    need = pools_required_by(program)
    if not need:
        # 🔴 ФОРМА 18, ПОЙМАННАЯ ОБРАТНЫМ КОНТРОЛЕМ НА СЕБЕ САМОМ. Программа,
        # которой не нужен НИ ОДИН пул, «заземляется» любым профилем, включая
        # заведомо пустой: `need <= filled` истинно для пустого множества
        # всегда. Первая редакция считала такие успехом и раздувала число —
        # зелёное, полученное без акта различения. Заземлять здесь нечего, и
        # это ТРЕТИЙ исход, а не разновидность успеха.
        return "заземлять нечего: программа не требует ни одного пула"
    candidates = [(run, snap) for run, snap, filled in profiles
                  if need <= filled]
    if not candidates:
        missing = sorted(need - frozenset().union(
            *[filled for _r, _s, filled in profiles]) if profiles else need)
        return ("нет профиля с пулами: "
                + ", ".join(missing or sorted(need)))
    last = "?"
    for run, snapshot in candidates:
        try:
            out = compile_program(program, revit_version=revit_version,
                                  snapshot=snapshot, bulk=True)
        except Exception as exc:            # noqa: BLE001
            last = type(exc).__name__
            continue
        if out.ok:
            return run, snapshot
        last = out.diagnostics[0].code if out.diagnostics else "?"
    return f"{last}, перебрано профилей: {len(candidates)}"

SIZED_CABLE_TRAY_GATE_NAME = "auth_cable_tray_sized"
SIZED_CABLE_TRAY_GATE_MARKERS = (
    "RBS_CABLETRAY_WIDTH_PARAM",
    "RBS_CABLETRAY_HEIGHT_PARAM",
)


def register_sized_cable_tray_gate(programs: dict[str, dict]) -> None:
    """Put the sectioned cable-tray emitter branch in the live gate corpus."""
    if SIZED_CABLE_TRAY_GATE_NAME in programs:
        raise RuntimeError(f"duplicate gate program: {SIZED_CABLE_TRAY_GATE_NAME}")
    programs[SIZED_CABLE_TRAY_GATE_NAME] = {
        "ir_version": "1.0",
        "intent": "кабельный лоток 300x100",
        "ops": [{
            "op": "create_cable_tray",
            "id": "CT2",
            "p0_mm": [0, 5000, 3000],
            "p1_mm": [6000, 5000, 3000],
            "level": {"by": "element_id", "value": 42},
            "width_mm": 300,
            "height_mm": 100,
        }],
    }


def sized_cable_tray_branch_reached(csharp: str) -> bool:
    """True only when the emitted body contains both section operands."""
    return all(marker in csharp for marker in SIZED_CABLE_TRAY_GATE_MARKERS)

#: Представительные id для тел боковых стадий. Эмитированный C# инвариантен к
#: ЧИСЛУ id по форме, поэтому двух хватает; важно лишь, что они настоящие
#: числовые id, а не заглушки, — числовой разбор внутри тела реален.
GATE_SIDE_STAGE_IDS = ["19227219", "456"]

#: Программа -> САМАЯ РАННЯЯ версия Revit, на которой она вообще строится.
#: Ниже неё `KIR-E003` — это ПРАВИЛЬНЫЙ ответ, а не «известная дыра»: операция
#: честно сказала, что на этой версии её в API нет. Ворота обязаны отличать
#: это от сломанной эмиссии, иначе зелёный требовал бы молча построить
#: что-нибудь другое — ровно тот Гудхарт, ради борьбы с которым отказ и
#: заведён.
#:
#: ДАННЫМИ, А НЕ УСЛОВИЕМ (09.08.2026). До этого дня здесь стоял список имён
#: и жёсткое `ver == "2021"`, то есть выразить можно было ровно одну границу.
#: Волна площадки принесла вторую: класса `Toposolid` нет до 2024, значит
#: `site_topography_toposolid` отказывает на ТРЁХ версиях, и старая форма
#: записала бы два из трёх правильных отказов в провалы ворот. Граница —
#: свойство операции, поэтому она и стоит числом рядом с программой.
E003_EXPECTED_BELOW: dict[str, str] = {
    # 2022: holes у перекрытия/плиты фундамента — путь Floor.Create(loops).
    "auth_floor_holes": "2022",
    "auth_contour_l": "2022",
    "struct_foundation_slab_holes_2021": "2022",
    "struct_foundation_slab": "2022",
    # Пришёл со сведением 13.08.2026 и уронил ворота: программа новая, список
    # её не знал. Добавлено ПО СТРОЕНИЮ, а не по имени — имя тут обманчиво
    # похоже на соседа, и этого мало. Замерено: обе программы суть ОДИН
    # `create_foundation` с одинаковым набором параметров, включая `holes`;
    # обе отказывают на 2021 и обе зелены на 2022; текст диагностики совпадает
    # побайтно — «отверстия в фундаментной плите не поддержаны на Revit 2021».
    # Граница одна и та же, потому и число одно и то же.
    "struct_foundation_slab_two_holes": "2022",
    # 2022: Ceiling.Create; legacy doc.Create.NewCeiling не существует ни на
    # одной из шести версий (замерено), то есть сворачивать некуда.
    "arch_ceiling": "2022",
    "arch_ceiling_contour": "2022",
    # 2024: класса Toposolid нет раньше (CS0246 на 2021/2022/2023 — замерено
    # компиляцией 09.08). Поверхность рельефа (site_topography_surface) сюда
    # НЕ входит: она строится 6/6, и это разные элементы разных категорий.
    "site_topography_toposolid": "2024",
    # 2025: и эта граница ЕДИНСТВЕННАЯ, чья причина лежит НЕ в Revit API, а в
    # замыкании ссылок РАЗВЁРНУТОГО плагина (12.08.2026). Члены существуют на
    # всех шести, и ворота компилировали тело 6/6 зелёным — но весь API
    # многоэтажного марша типизирован `ISet<ElementId>`, а deployed/net48 не
    # ссылается на `System.dll` и `ISet` в его замыкании нет
    # (declared 43 сборки / 3003 типа, deployed 42 / 2007 — разница РОВНО в
    # System.dll). Тело собиралось у нас и давало бы CS0012 у пользователя.
    # Отказ снимается вместе с причиной: судья — не память, а
    # tests/test_emitted_csharp_client_closure.py, профиль deployed.
    "datums_multistory_stairs": "2025",
}

#: Стадии, чей C# едет в Revit, но которых НЕТ в реестре конвейера. Tier G
#: теперь является live-стадией ``geometry`` и берётся из того же реестра, так
#: что честный остаток пуст. Новая обходная стадия обязана быть названа здесь.
UNREGISTERED_GATE_STAGES = frozenset()


def side_stage_gate_bodies(revit_version: str) -> dict[str, str]:
    """C# КАЖДОЙ боковой стадии, эмитированный ДЛЯ ЭТОЙ версии Revit.

    ПОЧЕМУ ЭТО ФУНКЦИЯ, А НЕ СПИСОК ИМПОРТОВ ВНУТРИ ``main``. До 30.07 здесь
    лежал ручной словарь из четырёх строителей: ``family_placement`` /
    ``group`` / ``curtain`` / ``sketch``. Стадий было девять. Пять из них —
    ``curve``, ``geometry`` и три новых (аннотации, системы MEP, марки) — ворота
    не видели, и одна из них не собиралась на трети поставляемых версий:

        CS1503: Argument 1: cannot convert from 'long' to
        'Autodesk.Revit.DB.BuiltInParameter'

    Разбор 59-этажной башни на R2023 повторял этот отказ по кругу полтора
    часа с ``bridge_roundtrips=0``. Ручной словарь не мог этого поймать по
    построению: чтобы стадия попала в ворота, кто-то должен был вспомнить.

    Теперь источник строителей ОДИН — реестр конвейера. Стадия, добавленная в
    реестр, попадает в ворота сама; стадия, добавленная мимо реестра, обязана
    быть названа в :data:`UNREGISTERED_GATE_STAGES`, иначе сверка имён
    (``test_side_stage_contract.SideStageGateCoverageTests``) валит сборку.

    ЭМИССИЯ ПОД ВЕРСИЮ, А НЕ ОДИН ТЕКСТ ШЕСТЬ РАЗ: у марок C# зависит от
    версии по построению (шов ``TaggedLocalElementId`` /
    ``GetTaggedLocalElementIds`` на 2022). Ворота, эмитирующие однажды,
    проверяли бы одну поверхность шесть раз — дефект, который
    ``tools/compile_gate_offline.py`` уже описал в своём докстринге.
    """
    from kukai.ir.decompile import pipeline as _pipe
    return {
        stage: builder(GATE_SIDE_STAGE_IDS)
        for stage, builder in _pipe._default_cs_builders(revit_version).items()
    }


def acceptance_gate_body() -> str:
    """Representative live L2 reread, compiled on every shipped Revit API."""

    from kukai.ir.acceptance import derive_expectation
    from kukai.ir.acceptance_live import build_scope_census_cs
    from kukai.ir.compiler import plan_program
    from kukai.ir.contracts import DocumentFingerprint

    planned = plan_program({
        "ir_version": "1.0",
        "ops": [
            {"op": "create_wall", "id": "W1",
             "p0_mm": [0, 0], "p1_mm": [6000, 0],
             "level": {"by": "name", "value": "Gate L1"}},
            {"op": "create_pipe", "id": "P1",
             "p0_mm": [0, 0, 2700], "p1_mm": [6000, 0, 2700],
             "level": {"by": "element_id", "value": 42},
             "diameter_mm": 50},
        ],
    })
    expectation = derive_expectation(
        planned, level_names_by_id={42: "Gate L1"})
    return build_scope_census_cs(
        expectation,
        DocumentFingerprint(
            title="KIR gate COPY",
            path_name="gate.rvt",
            project_uid="kir-gate-project",
        ),
        run_id="0" * 32,
        phase="before",
    )


def mutation_acceptance_gate_body(revit_version: str) -> str:
    """Representative atomic census + exact-mutation reread for one API."""

    from kukai.ir.acceptance import derive_expectation
    from kukai.ir.acceptance_mutation import derive_mutation_expectation
    from kukai.ir.acceptance_probe import build_acceptance_probe_cs
    from kukai.ir.compiler import plan_program
    from kukai.ir.contracts import DocumentFingerprint

    planned = plan_program({
        "ir_version": "1.0",
        "allow_destructive": True,
        "ops": [
            {"op": "create_wall", "id": "W1",
             "p0_mm": [0, 0], "p1_mm": [6000, 0],
             "level": {"by": "name", "value": "Gate L1"}},
            {"op": "set_param", "id": "S1",
             "target": {"by": "element_id", "value": 101},
             "param": "Comments", "value": "KIR gate"},
            {"op": "move_elements", "id": "M1",
             "targets": [{"by": "element_id", "value": 102}],
             "delta_mm": [100, 0, 500]},
            {"op": "change_type", "id": "T1",
             "target": {"by": "element_id", "value": 103},
             "type": {"by": "element_id", "value": 900}},
            {"op": "delete", "id": "D1",
             "target": {"by": "element_id", "value": 104}},
        ],
    })
    document = DocumentFingerprint(
        title="KIR gate COPY",
        path_name="gate.rvt",
        project_uid="kir-gate-project",
    )
    return build_acceptance_probe_cs(
        plan_digest=planned.plan_digest,
        scope_expectation=derive_expectation(planned),
        mutation_expectation=derive_mutation_expectation(planned),
        document=document,
        run_id="1" * 32,
        phase="before",
        revit_version=revit_version,
    )



#: The Revit assemblies the compile service actually references, hashed here
#: so a gate number stops being a number without an address. "1938 live
#: compile checks" says nothing about WHAT it compiled against, and until
#: now the service could not answer: prod `/health` returns COUNTS only —
#: no names, no digests — while the canary carries a `referenceManifestDigest`
#: and per-version digests prod does not know as concepts.
#:
#: Computed SIDEWAYS, from the same NuGet package the service loads
#: (`RoslynCompiler.LoadAllRevitVersions`), so this needs no endpoint, no
#: rebuild and no restart of a deployed service.
#:
#: BOUNDARY, stated here rather than in a report: this is a manifest of the
#: REVIT references only. The system (net8/net48) references are NOT in it
#: and cannot be, sideways: they come from the service process's own
#: TRUSTED_PLATFORM_ASSEMBLIES, a property of the runtime it was started
#: under — which is also why prod reads 48 and the canary 47. Their role is
#: PARITY WITH THE BRIDGE, and that is guarded separately by drift guards on
#: both sides (`AssemblyWhitelistSyncTests.cs`, `test_assembly_whitelist_sync.py`),
#: not by this manifest. Their absence here is a gap in DESCRIPTION, not in
#: protection. Approximating them would be worse than omitting them: an empty
#: column is visible, a substituted one is not.
_REVIT_REF_DLLS = ("RevitAPI.dll", "RevitAPIUI.dll", "AdWindows.dll",
                   "UIFramework.dll")


def revit_reference_manifest() -> tuple[dict[str, str], list[str]]:
    """(version -> digest, problems). Mirrors the service's own path logic."""
    # `os` берётся МОДУЛЬНЫЙ (строка 13). Локальный `import os` здесь был, и
    # его ловил test_authority_boundaries: затенение модульного имени
    # функциональным — та самая форма, где два имени одного модуля живут в
    # одном файле и расходятся молча при правке одного из них.
    import hashlib

    root = os.environ.get("NUGET_PACKAGES") or os.path.expanduser(
        "~/.nuget/packages")
    base = os.path.join(root, "revit_all_main_versions_api_x64")
    manifest: dict[str, str] = {}
    problems: list[str] = []
    if not os.path.isdir(base):
        return manifest, [f"NuGet package dir absent: {base}"]
    for ver in spec.REVIT_VERSIONS:
        lib = os.path.join(base, f"{ver}.0.0", "lib",
                           "net8.0" if ver >= "2025" else "net48")
        if not os.path.isdir(lib):
            problems.append(f"{ver}: lib dir absent ({lib})")
            continue
        h = hashlib.sha256()
        missing = []
        for dll in _REVIT_REF_DLLS:          # order is part of the digest
            path = os.path.join(lib, dll)
            if not os.path.isfile(path):
                missing.append(dll)
                continue
            with open(path, "rb") as fh:
                for chunk in iter(lambda: fh.read(1 << 20), b""):
                    h.update(chunk)
        if missing:
            problems.append(f"{ver}: missing {', '.join(missing)}")
            continue
        manifest[ver] = h.hexdigest()
    return manifest, problems


def model_binding_guard_inputs() -> tuple[dict, object, dict]:
    """The (snapshot, profile, expected_document) triple the guard compiles.

    ONE source. The profile and the snapshot must be derived from the same
    object, because `compiler.py` recomputes the profile from whatever
    snapshot it is handed and refuses `KIR-G107` when the digests differ.
    Until 2026-08-11 this block built the profile from a mutated copy and
    passed the UNMUTATED original to `compile_program` — the pair was
    asserted in one place and read in another, and nothing forced them to
    agree. The gate then counted six checks for a body it never compiled.

    Returned as a triple rather than left inline so a test can compile the
    gate's OWN inputs; the harness is the consumer that went unmeasured.
    """
    import copy

    from kukai.ir.open_model import OpenModelProfile
    from kukai.ir.tests.fixtures import GROUND_SNAPSHOT

    snapshot = copy.deepcopy(GROUND_SNAPSHOT)
    for level in snapshot["levels"]:
        element_id = int(level["id"])
        level["unique_id"] = f"gate-level-{element_id}"
        level["version_guid"] = f"{element_id:032x}"
    snapshot["levels__total"] = len(snapshot["levels"])
    return (
        snapshot,
        OpenModelProfile.from_ground_snapshot(snapshot),
        {"title": "KIR gate COPY", "path_name": "",
         "project_uid": "kir-gate-project"},
    )


async def main() -> int:
    contract_problems = audit_contract_kernel()
    if contract_problems:
        print("FATAL: KIR operation contract kernel is inconsistent")
        for problem in contract_problems:
            print(f"  - {problem}")
        return 3

    client = CompileClient()
    if not await client.health():
        print("FATAL: compile service :52412 unavailable")
        return 2

    # `__ver__` — ПИН ЭТАЛОНА, А НЕ ПОЛЕ ПРОГРАММЫ, и снимать его обязаны оба
    # читателя `PROGRAMS`. Волна нагрузок завела этот ключ (эталон нагрузок
    # снимается на 2023, потому что свободная нагрузка живёт только на
    # 2021-2023) и научила снимать его `test_golden`, но не эти ворота, хотя
    # правку в них та же волна вносила — исключение E003 для 2024+ ниже. Итог:
    # ворота подавали ключ в конверт и получали KIR-P003 «неизвестное поле» на
    # ВСЕХ ШЕСТИ версиях, то есть исключение, написанное волной, не срабатывало
    # ни разу — программа падала раньше, чем доходила до него.
    # ЭТО НЕ АРИФМЕТИКА СЛИЯНИЯ, А НАСТОЯЩИЙ ДЕФЕКТ ВЕТКИ, и он показывает,
    # что ворота на ней до конца не доводили: снятый ключ даёт ровно то, что
    # волна и задумала — сборку на 2021-2023 и KIR-E003 на 2024-2026.
    programs: dict[str, dict] = {
        name: {k: v for k, v in prog.items() if k != "__ver__"}
        for name, prog in PROGRAMS.items()}
    rng = random.Random(SEED)
    for i in range(N_PBT):
        programs[f"pbt_{i:02d}"] = gen_program(rng)
    # Programs exercising every kind. A KIR program is capped at 20 ops, so
    # chunk instead of truncating: the old [:20] silently left the final kind
    # outside the live gate as soon as the registry grew to 21 entries.
    _kind_ops = [
        {"op": "query_count", "id": f"k{j}", "kind": kind}
        for j, kind in enumerate(sorted(spec.KINDS))
    ]
    for offset in range(0, len(_kind_ops), 20):
        programs[f"all_kinds_{offset // 20:02d}"] = {
            "ir_version": "1.0", "ops": _kind_ops[offset:offset + 20]}
    # fix/g102-disambiguate (2026-07-17): query_types — one program per
    # closed pool, proving every _TYPE_POOL_COLLECTOR_CS idiom (compiler.py)
    # actually compiles on all six versions (the two-table-lockstep guard
    # test_authoring.QueryTypes.test_all_sixteen_pools_compile_offline
    # proves offline; this is the same proof through the live gate).
    # ЧАНКОВАНИЕ ДОБАВЛЕНО ПРИ СЛИЯНИИ 09.08, и ошибка была ровно та, от
    # которой предупреждает блок `all_kinds_` двадцатью строками выше: пулов
    # стало БОЛЬШЕ ДВАДЦАТИ, и одна программа на все пулы уткнулась в
    # MAX_OPS_PER_PROGRAM — ворота отдали KIR-L001 на всех шести версиях.
    #
    # ЧЬЯ ЭТО ОШИБКА — ЗАМЕРЕНО ПО ВЕТКАМ, А НЕ ПРЕДПОЛОЖЕНО (число берётся из
    # собственного замка каждой ветки, `assertEqual(len(pools), N)`):
    # общее основание — 19 пулов (19 опов, предел не перейдён, ворота зелены);
    # волна каркаса — 20 (ровно предел, ещё проходит);
    # волна нагрузок — 23, то есть ПРЕДЕЛ БЫЛ ПЕРЕЙДЁН УЖЕ У НЕЁ, на своей
    # ветке, до всякого слияния; слитое дерево — 24.
    # Значит это НЕ арифметика слияния: ворота на ветке нагрузок падали и там,
    # ровно как и из-за `__ver__` выше. Две независимые поломки одних ворот в
    # одной ветке — признак того, что ворота на ней не запускались до конца.
    # Чанкуем, а не срезаем: `[:20]` тихо оставил бы последние пулы вне живых
    # ворот, то есть купил бы зелёный цвет ценой покрытия.
    _qt_pools = spec.OPS["query_types"].params[0].choices
    _qt_ops = [{"op": "query_types", "id": f"t{j}", "pool": p}
               for j, p in enumerate(_qt_pools)]
    for offset in range(0, len(_qt_ops), 20):
        programs[f"query_types_all_pools_{offset // 20:02d}"] = {
            "ir_version": "1.0",
            "intent": "какие типы существуют в каждом закрытом пуле",
            "ops": _qt_ops[offset:offset + 20]}
    # authoring family — grounded via the COMMITTED shared fixture (fixtures.py,
    # same snapshot unit tests and goldens use; a private harness copy is how
    # the 2026-07-16 checkpoint became non-reproducible from HEAD)
    from kukai.ir.tests.fixtures import GROUND_SNAPSHOT
    from kukai.ir.tests.test_authoring import _prog, _wall
    programs["auth_wall"] = _prog([_wall()], intent="стена 6м")
    programs["auth_mixed"] = _prog([
        _wall(),
        _wall(oid="W2", p0_mm=[0, 4000], p1_mm=[6000, 4000],
              type={"by": "name", "value": "ЖБ 200"}, height_mm=2800),
        {"op": "create_pipe", "id": "P1", "p0_mm": [0, 0, 2700],
         "p1_mm": [3000, 0, 2700], "level": {"by": "element_id", "value": 42},
         "diameter_mm": 50},
        {"op": "create_grid", "id": "G1", "p0_mm": [0, -1000],
         "p1_mm": [0, 9000], "name": "А"},
    ], intent="стены+труба+ось")
    register_sized_cable_tray_gate(programs)
    programs["auth_stack"] = {"ir_version": "1.0", "intent": "стек 5 этажей",
        "ops": [{"op": "stack", "id": "sec", "levels": 5, "h_mm": 3000,
                 "floor": [
                     {"op": "create_wall", "id": "W1", "p0_mm": [0, 0],
                      "p1_mm": [6000, 0], "height_mm": 2800},
                     {"op": "create_pipe", "id": "P1", "p0_mm": [0, 0, 2700],
                      "p1_mm": [3000, 0, 2700], "diameter_mm": 50},
                 ]}]}
    programs["auth_grid_array"] = {"ir_version": "1.0", "intent": "сетка осей 4x3",
        "ops": [{"op": "grid_array", "id": "net", "nx": 4, "ny": 3,
                 "dx_mm": 6000, "dy_mm": 4500, "prefix_y": "А"}]}
    programs["auth_stairs"] = {"ir_version": "1.0", "intent": "лестничный марш",
        "ops": [{"op": "create_stairs", "id": "S1",
                 "p0_mm": [0, 0], "p1_mm": [5000, 0],
                 "base_level": {"by": "element_id", "value": 42},
                 "top_level": {"by": "element_id", "value": 43},
                 "width_mm": 1200}]}
    # 09.08: ВТОРАЯ форма марша того же опа — винтовая
    # (StairsRun.CreateSpiralRun). Ветка, которой ворота не строят, ими не
    # проверена вовсе; ось версий у винта та же (метод есть и одинаков в
    # 2021-2026 по эталонным сборкам), поэтому ожидание — шесть OK, без
    # единого исключения в EXPECTED-списках.
    programs["auth_stairs_spiral"] = {"ir_version": "1.0",
        "intent": "винтовая лестница",
        "ops": [{"op": "create_stairs", "id": "S1",
                 "spiral": {"center_mm": [3000.0, 3000.0], "radius_mm": 1500.0,
                            "start_angle_deg": 0.0,
                            "included_angle_deg": 270.0, "clockwise": False},
                 "base_level": {"by": "element_id", "value": 42},
                 "top_level": {"by": "element_id", "value": 43},
                 "width_mm": 1200}]}
    # ВОЛНА ЛЕСТНИЦ (10.08.2026): площадка по эскизу — ВТОРОЙ оп со своим
    # шаблоном целой программы. Две строки, а не одна, потому что ветки
    # эмиссии у контура РАЗНЫЕ: прямоугольник печатает шесть `Line.CreateBound`
    # (`bulge == 0`), а многоугольник с дугой уводит в `Arc.Create` по трём
    # литеральным точкам, и ветка, которой ворота не строят, ими не проверена
    # вовсе — тот же довод, которым 09.08 заведён винтовой марш выше.
    programs["auth_stairs_landing"] = {"ir_version": "1.0",
        "intent": "промежуточная площадка лестницы",
        "ops": [{"op": "create_stairs_landing", "id": "LG1",
                 "stairs": {"by": "element_id", "value": 4242},
                 "contour": {"outer": {"shape": "rect",
                                       "origin": [5000.0, 0.0],
                                       "size_mm": [2400.0, 1200.0]}},
                 "elevation_mm": 1500.0}]}
    # ВТОРОЙ МАРШ (15.08.2026). ДВЕ программы, и вторая не для симметрии:
    # привязка марша — ЗАКРЫТОЕ перечисление Revit, а ветка, которой ворота не
    # строят, ими не проверена вовсе. `center` — умолчание, `left` — доказывает,
    # что имя члена доезжает до C# не литералом умолчания.
    programs["auth_stairs_run"] = {"ir_version": "1.0",
        "intent": "второй марш существующей лестницы",
        "ops": [{"op": "create_stairs_run", "id": "RN1",
                 "stairs": {"by": "element_id", "value": 4242},
                 "p0_mm": [0.0, 0.0], "p1_mm": [3000.0, 0.0],
                 "base_elevation_mm": 1500.0}]}
    programs["auth_stairs_run_left"] = {"ir_version": "1.0",
        "intent": "марш с левой привязкой",
        "ops": [{"op": "create_stairs_run", "id": "RN1",
                 "stairs": {"by": "element_id", "value": 4242},
                 "p0_mm": [0.0, 0.0], "p1_mm": [3000.0, 0.0],
                 "base_elevation_mm": 1500.0,
                 "justification": "left"}]}
    programs["auth_stairs_landing_arc"] = {"ir_version": "1.0",
        "intent": "площадка со скруглённой гранью",
        "ops": [{"op": "create_stairs_landing", "id": "LG1",
                 "stairs": {"by": "element_id", "value": 4242},
                 "contour": {"outer": {
                     "shape": "poly",
                     "points_mm": [[5000.0, 0.0], [7400.0, 0.0],
                                   [7400.0, 1200.0], [5000.0, 1200.0]],
                     "arcs": [{"edge": 1, "bulge": 0.3}]}},
                 "elevation_mm": 1500.0}]}
    # feat/native-groups: a native Revit group (create_group). Members are
    # PRE-GROUNDED authoring ops (the component-library bridge shape); the group
    # op grounds through with no snapshot dependency (grounded=()), and the two
    # placement deltas exercise the O0+delta emission on all six versions.
    def _grp_wall(oid, x0, y0, x1, y1):
        return {"op": "create_wall", "id": oid, "p0_mm": [x0, y0],
                "p1_mm": [x1, y1],
                "level": {"__grounded__": {"id": 42, "name": None,
                                           "via": "element_id"}},
                "height_mm": 3000.0,
                "type": {"__grounded__": {"id": None, "name": None,
                                          "via": "doc_default",
                                          "in_emit": "__doc_default__"}}}
    programs["auth_native_group"] = {"ir_version": "1.0",
        "intent": "типовой этаж как нативная группа",
        "ops": [{"op": "create_group", "id": "GRP1", "name": "Типовой этаж",
                 "members": [_grp_wall("W1", 30000, 23000, 36000, 23000),
                             _grp_wall("W2", 36000, 23000, 36000, 27000)],
                 "placements": [[0, 0, 6600], [0, 0, 13200]]}]}
    programs["mod_setparam_delete"] = {"ir_version": "1.0",
        "intent": "параметр + удаление", "allow_destructive": True,
        "ops": [
            {"op": "create_level", "id": "L1", "elev_mm": 12000, "name": "Тех"},
            {"op": "set_param", "id": "S1", "target": {"by": "ref", "value": "L1"},
             "param": "Комментарии", "value": "создан KIR"},
            {"op": "set_param", "id": "S2",
             "target": {"by": "element_id", "value": 7777},
             "param": "Смещение снизу", "value": {"value": 250, "unit": "mm"}},
            {"op": "delete", "id": "D1",
             "target": {"by": "element_id", "value": 8888}},
        ]}
    programs["auth_contour_arc"] = {"ir_version": "1.0", "intent": "контур с дугой",
        "ops": [{"op": "create_floor_by_contour", "id": "F1",
                 "contour": {"outer": {"shape": "poly",
                                       "points_mm": [[0,0],[8000,0],[8000,6000],[0,6000]],
                                       "arcs": [{"edge": 1, "radius_mm": 5000}]}},
                 "level": {"by": "element_id", "value": 42}}]}
    # CONTOUR обратным ходом (28.07): контур с ДУГОЙ и СМЕЩЕНИЕМ ОТ УРОВНЯ —
    # ровно та форма, которую теперь строит лифт для дуговых полов. Смещение
    # у 107 из 155 таких полов «демо-v3», поэтому ветка параметра обязана
    # компилироваться на всех шести версиях, а не только в тесте эмиссии.
    programs["auth_contour_arc_offset"] = {"ir_version": "1.0",
        "intent": "дуговой контур со смещением от уровня",
        "ops": [{"op": "create_floor_by_contour", "id": "F1",
                 "contour": {"outer": {"shape": "poly",
                                       "points_mm": [[13012.5, 58950.0],
                                                     [21287.0, 58950.0],
                                                     [14544.7, 55088.2]],
                                       "arcs": [{"edge": 2, "bulge": 0.2874}]}},
                 "level": {"by": "element_id", "value": 42},
                 "height_offset_mm": -700.0}]}
    programs["auth_pipe_system_tee"] = {"ir_version": "1.0", "intent": "тройник",
        "ops": [{"op": "create_pipe_system", "id": "SYS1", "level": {"by": "element_id", "value": 42},
                 "diameter_mm": 100,
                 "nodes": [{"id": "T", "xyz_mm": [0, 0, 0]}, {"id": "A", "xyz_mm": [3000, 0, 0]},
                           {"id": "B", "xyz_mm": [-3000, 0, 0]}, {"id": "C", "xyz_mm": [0, 3000, 0]}],
                 "segments": [{"from": "T", "to": "A"}, {"from": "T", "to": "B"}, {"from": "T", "to": "C"}]}]}
    from kukai.ir.tests.test_golden import PROGRAMS as _GP
    programs["auth_full_house"] = _GP["full_house_v1"]
    # wave/mep (2026-07-17): route_pipe_system / route_duct_system gate
    # coverage beyond the two golden programs (already included via PROGRAMS
    # above: route_pipe_system_riser_branch, route_duct_system_tee). Adds the
    # ring topology (CONNECT checklist's "кольцо — если домен допускает") and
    # a duct tee, so the 6-version gate exercises both fitting types
    # (elbow/tee) on BOTH domains, not just pipe.
    programs["auth_route_pipe_ring"] = {"ir_version": "1.0", "intent": "кольцевая сеть ВК",
        "ops": [{"op": "route_pipe_system", "id": "SYSR",
                 "level": {"by": "element_id", "value": 42}, "diameter_mm": 100,
                 "nodes": [{"id": "R1", "xyz_mm": [0, 0, 3000]}, {"id": "R2", "xyz_mm": [4000, 0, 3000]},
                           {"id": "R3", "xyz_mm": [4000, 4000, 3000]}, {"id": "R4", "xyz_mm": [0, 4000, 3000]}],
                 "segments": [{"from": "R1", "to": "R2"}, {"from": "R2", "to": "R3"},
                              {"from": "R3", "to": "R4"}, {"from": "R4", "to": "R1"}]}]}
    programs["auth_route_duct_chain"] = {"ir_version": "1.0", "intent": "магистраль ОВ",
        "ops": [{"op": "route_duct_system", "id": "SYSD",
                 "level": {"by": "element_id", "value": 42},
                 "nodes": [{"id": "D1", "xyz_mm": [0, 0, 3000]}, {"id": "D2", "xyz_mm": [6000, 0, 3000]},
                           {"id": "D3", "xyz_mm": [6000, 0, 2950]}],
                 "segments": [{"from": "D1", "to": "D2", "diameter_mm": 400},
                              {"from": "D2", "to": "D3", "diameter_mm": 200,
                               "slope_min_pct": 1.0}]}]}
    # fix/mep-fittings (2026-07-17): the exact live-semantic-test failure
    # shape — a straight (collinear) riser continuation used to force an
    # elbow onto a node with nothing to bend, and Revit refused at runtime
    # ("failed to insert elbow"). These two programs put the fixed
    # classify_junction branches ("connect" via Connector.ConnectTo, and
    # "transition" via NewTransitionFitting) through the real 6-version
    # compile gate, not just the offline unit/golden corpus — proving the
    # emit itself still compiles on every version with the new branches
    # live. auth_route_pipe_ring/auth_route_duct_chain above stay as the
    # pre-existing bend/branch coverage, unaffected by this fix.
    programs["auth_route_pipe_straight_riser"] = {
        "ir_version": "1.0", "intent": "прямой стояк ВК без изгиба (ConnectTo, не отвод)",
        "ops": [{"op": "route_pipe_system", "id": "SYSS",
                 "level": {"by": "element_id", "value": 42}, "diameter_mm": 100,
                 "nodes": [{"id": "S1", "xyz_mm": [0, 0, 0]}, {"id": "S2", "xyz_mm": [0, 0, 6000]},
                           {"id": "S3", "xyz_mm": [0, 0, 12000]}],
                 "segments": [{"from": "S1", "to": "S2"}, {"from": "S2", "to": "S3"}]}]}
    programs["auth_route_duct_straight_transition"] = {
        "ir_version": "1.0", "intent": "прямой переход диаметра ОВ на стыке (NewTransitionFitting)",
        "ops": [{"op": "route_duct_system", "id": "SYST",
                 "level": {"by": "element_id", "value": 42},
                 "nodes": [{"id": "S1", "xyz_mm": [0, 0, 3000]}, {"id": "S2", "xyz_mm": [5000, 0, 3000]},
                           {"id": "S3", "xyz_mm": [10000, 0, 3000]}],
                 "segments": [{"from": "S1", "to": "S2", "diameter_mm": 400},
                              {"from": "S2", "to": "S3", "diameter_mm": 250}]}]}
    # Витражные ячейки (дизайн 2026-07-28). Ворота обязаны компилировать ОБЕ
    # формы носителя (ref на стену этой же программы и пинованный
    # element_id — дизайн пишет `host: ref|element_id`) и ОБЕ формы селектора
    # типа (имя, которое эмиттер разрешает коллектором по двум пространствам
    # типов, и пинованный element_id). Адрес (0,0) — не «пустой», а сетка
    # 1×1: ровно тот частный случай, который дизайн запретил считать
    # оправданием отсутствия адреса.
    programs["auth_curtain_cell_grid"] = {"ir_version": "1.0",
        "intent": "витраж: разные типы в ячейках сетки существующей стены",
        "ops": [
            {"op": "set_curtain_panel", "id": "CP1",
             "host": {"by": "element_id", "value": 8145901}, "u": 0, "v": 0,
             "panel_type": {"by": "element_id", "value": 273445}},
            {"op": "set_curtain_panel", "id": "CP2",
             "host": {"by": "element_id", "value": 8145901}, "u": 2, "v": 1,
             "panel_type": {"by": "name", "value": "Стена НР_ВТ 200мм"}},
            {"op": "set_curtain_panel", "id": "CP3",
             "host": {"by": "element_id", "value": 8145901}, "u": 3, "v": 0,
             "panel_type": {"by": "name", "value": "Пустая панель"}},
        ]}
    # Линии разрезки витража (волна 29.07): ворота обязаны компилировать обе
    # формы носителя (ref на стену этой же программы и пинованный element_id)
    # и ОБА направления — isUGridLine у AddGridLine булев, и перепутанная
    # ветка не видна ничем, кроме живой модели.
    # RELATE, АДРЕС (волна 09.08). Ворота обязаны гонять ОБА семейства узлов
    # на всех шести версиях, и вот зачем именно ворота: адрес разрешается на
    # компиляции в ЛИТЕРАЛ, поэтому дефект в резолвере выглядит не как
    # ошибка компиляции, а как ПРАВИЛЬНО СОБИРАЮЩИЙСЯ C# с неверным числом.
    # Единственное, что здесь доказывают ворота, — что путь «адрес -> число ->
    # эмиссия» доходит до конца на 2021-2026; ЧТО за число выведено, держат
    # тесты (`test_relate.py`, побайтовая сверка с ручным вариантом).
    #
    # Программа сложена цепочкой намеренно: колонны адресованы ОТ ОСЕЙ, балка
    # — ОТ КОЛОНН, вторая стена — ОТ КОНЦА первой. Ни одной координаты балки
    # и стыка в тексте нет, и в этом весь смысл замера.
    programs["auth_address_grid_and_element"] = {"ir_version": "1.0",
        "intent": "адрес: колонны от осей, балка по верху колонн, стык стен",
        "ops": [
            {"op": "create_column", "id": "AC1", "xy": {"at_grid": ["1", "А"]},
             "level": {"by": "element_id", "value": 42},
             "top_level": {"by": "element_id", "value": 43},
             "symbol": {"by": "element_id", "value": 500}},
            {"op": "create_column", "id": "AC2",
             "xy": {"at_grid": [{"grid": "2", "offset_mm": 200,
                                 "toward": "1"}, "А"]},
             "level": {"by": "element_id", "value": 42},
             "top_level": {"by": "element_id", "value": 43},
             "symbol": {"by": "element_id", "value": 500}},
            {"op": "create_beam", "id": "AB1",
             "p0_mm": {"at_element": {"by": "ref", "value": "AC1"},
                       "point": "center", "z": "top"},
             "p1_mm": {"at_element": {"by": "ref", "value": "AC2"},
                       "point": "center", "z": "top"},
             "level": {"by": "element_id", "value": 43},
             "symbol": {"by": "element_id", "value": 1100}},
            {"op": "create_wall", "id": "AW1", "p0_mm": [0, 0],
             "p1_mm": [6000, 0], "height_mm": 3000,
             "level": {"by": "element_id", "value": 42}},
            {"op": "create_wall", "id": "AW2",
             "p0_mm": {"at_element": {"by": "ref", "value": "AW1"},
                       "point": "end"},
             "p1_mm": [6000, 4500], "height_mm": 3000,
             "level": {"by": "element_id", "value": 42}},
        ]}
    # wave/shape: произвольная геометрия мешем. Меш порождается МАТЕМАТИКОЙ
    # прямо здесь (витая башня), а не приносится списком литералов: гейт
    # должен гонять ту же форму, которой пользуются живьём, и оставаться
    # читаемым. 16 граней × 12 этажей + крышка и днище = 416 треугольников —
    # десятая часть замеренного предела MAX_TRIANGLES=4096.
    def _twisted_tower_mesh(sides=16, storeys=12, r0=6000.0, r1=3500.0,
                            h=36000.0, twist=140.0):
        verts, tris = [], []
        for k in range(storeys + 1):
            f = k / storeys
            r = r0 + (r1 - r0) * f
            a0 = math.radians(twist * f)
            for j in range(sides):
                a = a0 + 2 * math.pi * j / sides
                verts.append([r * math.cos(a), r * math.sin(a), h * f])
        for k in range(storeys):
            for j in range(sides):
                a, b = k * sides + j, k * sides + (j + 1) % sides
                c, d = (k + 1) * sides + j, (k + 1) * sides + (j + 1) % sides
                tris += [[a, b, d], [a, d, c]]
        bot = len(verts); verts.append([0.0, 0.0, 0.0])
        top = len(verts); verts.append([0.0, 0.0, h])
        for j in range(sides):
            tris.append([bot, (j + 1) % sides, j])
            tris.append([top, storeys * sides + j,
                         storeys * sides + (j + 1) % sides])
        return verts, tris

    _ds_verts, _ds_tris = _twisted_tower_mesh()
    # wave/solid (09.08): параметрическое тело. ТРИ программы, потому что у
    # эмиссии три необязательные ветки, и ворота обязаны собрать каждую:
    # отметка основания включает преобразование контура, дуга в профиле —
    # ветку Arc.Create, полный оборот меняет ожидаемую площадь торцов на ноль.
    # Ворота, собравшие одну ветку из трёх, — это «прибор на часть диапазона».
    programs["auth_solid_extrusion_plain"] = {
        "ir_version": "1.0", "intent": "выдавленное тело",
        "ops": [{"op": "create_solid_extrusion", "id": "SE1",
                 "profile": {"outer": {"shape": "rect", "origin": [0, 0],
                                       "size_mm": [4000, 3000]}},
                 "height_mm": 2500, "category": "generic_model",
                 "name": "призма"}]}
    programs["auth_solid_extrusion_arc_holes"] = {
        "ir_version": "1.0", "intent": "выдавливание с дугой, проёмами и отметкой",
        "ops": [{"op": "create_solid_extrusion", "id": "SE2",
                 "profile": {
                     "outer": {"shape": "poly",
                               "points_mm": [[0, 0], [6000, 0], [6000, 4000],
                                             [0, 4000]],
                               "arcs": [{"edge": 1, "bulge": 0.4}]},
                     "holes": [{"shape": "rect", "origin": [1000, 1000],
                                "size_mm": [1200, 1200]},
                               {"shape": "rect", "origin": [3000, 1500],
                                "size_mm": [900, 900]}]},
                 "height_mm": 1800, "base_z_mm": 3300, "category": "mass",
                 "name": "плита с проёмами"}]}
    # wave/mass (10.08): стена по наклонной грани массы. ДВЕ программы,
    # потому что у разрешения носителя ДВЕ ветки, и ворота обязаны собрать
    # обе: масса, которая УЖЕ СТОИТ (`element_id` — главный сценарий), и
    # масса, размещённая этой же программой (`ref` на place_family). Ворота,
    # собравшие одну ветку из двух, — это «прибор на часть диапазона».
    programs["auth_face_wall_placed_mass"] = {
        "ir_version": "1.0", "intent": "стена по скату размещённой массы",
        "ops": [{"op": "place_family", "id": "M1",
                 "symbol": {"by": "family_type", "category": "OST_Furniture",
                            "family_name": "Стол офисный",
                            "type_name": "Стол 1200"},
                 "xyz": [1000, 2000, 0],
                 "level": {"by": "name", "value": "Этаж 1"}},
                {"op": "create_face_wall", "id": "FW2",
                 "host": {"by": "ref", "value": "M1"},
                 "face_normal": [0.0, -0.5, 0.5],
                 "location_line": "wall_centerline",
                 "type": {"by": "name", "value": "ЖБ 200"}}]}
    programs["auth_solid_revolves"] = {
        "ir_version": "1.0", "intent": "тело вращения: сектор и полный оборот",
        "ops": [{"op": "create_solid_revolve", "id": "SR1",
                 "profile": {"outer": {"shape": "rect", "origin": [1000, 0],
                                       "size_mm": [800, 2400]}},
                 "axis_xy_mm": [5000, 4000], "sweep_deg": 270,
                 "category": "generic_model", "name": "сектор кольца"},
                {"op": "create_solid_revolve", "id": "SR2",
                 "profile": {
                     "outer": {"shape": "poly",
                               "points_mm": [[600, 0], [2000, 0], [2000, 500],
                                             [1200, 500], [1200, 3000],
                                             [600, 3000]]},
                     "holes": [{"shape": "rect", "origin": [800, 1000],
                                "size_mm": [300, 800]}]},
                 "axis_xy_mm": [20000, 0], "sweep_deg": 360, "base_z_mm": -1500,
                 "category": "site", "name": "колонна вращения"}]}
    programs["auth_floor_holes"] = {"ir_version": "1.0", "intent": "плита с проёмом",
        "ops": [{"op": "create_floor", "id": "F1",
                 "outline": [[0, 0], [8000, 0], [8000, 6000], [0, 6000]],
                 "holes": [[[3000, 2000], [5000, 2000], [5000, 4000], [3000, 4000]]],
                 "level": {"by": "name", "value": "Этаж 1"}}]}
    # Documentation family (ops_annotation.py): create_dimension/create_tag/
    # create_text had ZERO live 6-version compile coverage before 28.07 — the
    # per_op gate finding that closed the in_view:{by:ref} CS0039 hole (see
    # expected_refusals below) surfaced that this whole op family had never
    # been driven through the real compile service, atomic OR per_op, at
    # all. in_view here stays element_id (the only legal form after the fix).
    # host: element_id (28.07, audit's most frequent external scenario:
    # «поставь окно в МОЮ стену»). No wall op in this program on purpose —
    # the whole point is a host the program never creates. Runtime frame
    # (doc.GetElement(...) as Wall, LocationCurve, Curve.Evaluate(t, true))
    # goes through the live 6-version compile gate here, atomic AND per_op
    # (the per_op axis below), same bar as everything else in this table.
    # No expected-refusal entry needed: element_id is now a legal host.
    programs["auth_hosted_element_id"] = {"ir_version": "1.0",
        "intent": "дверь и окно на чужой стене (host по element_id)",
        "ops": [
            {"op": "create_door", "id": "D1",
             "host": {"by": "element_id", "value": 8145901},
             "offset_mm": 1500, "sill_mm": -100,
             "symbol": {"by": "name", "value": "Дверь 900x2100"}},
            {"op": "create_window", "id": "Win1",
             "host": {"by": "element_id", "value": 8145901},
             "offset_mm": 3000, "sill_mm": 900,
             "symbol": {"by": "name", "value": "Окно 1200x1500"}},
        ]}
    # A8 (13.08.2026): СИМВОЛ, СОЗДАННЫЙ ЭТОЙ ЖЕ ПРОГРАММОЙ, ПОТРЕБЛЯЕТСЯ ЕЮ ЖЕ.
    #
    # До этой правки `family_symbol` был ЕДИНСТВЕННЫМ родом ссылки во всём
    # языке, у которого есть производители и НОЛЬ потребителей: производят 2
    # опа (`create_type`, `load_family`), потребляет никто. Три других рода
    # потребляются десятками (`level` 33, `element` 16, `wall` 7) — то есть это
    # было не «мало покрыто», а НЕЗАМКНУТОЕ РЕБРО в графе языка, и увидеть его
    # можно было только переписью производителей против потребителей.
    #
    # Следствие было не академическим: здание нельзя авторить в документе, где
    # его каталога ещё нет. Отказ `KIR-G104` («пул пуст») не мог назвать
    # выполнимый следующий ход, потому что загрузить семейство и сослаться на
    # него в одной программе было НЕЛЬЗЯ.
    #
    # Программа ниже — доказательство, что теперь можно, и она в воротах именно
    # потому, что офлайн-компиляция шести версий и есть единственное, что здесь
    # проверяемо: живая транзакция (примет ли Revit свежезагруженный символ
    # сразу) остаётся заряженной для живого окна.
    programs["auth_load_family_then_place"] = {"ir_version": "1.0",
        "intent": "загрузить семейство и поставить его экземпляр в один ход",
        "ops": [
            {"op": "load_family", "id": "LF",
             "path": "C:\\Lib\\Doors\\M_Дверь.rfa",
             "type_name": "Дверь 900x2100"},
            {"op": "create_wall", "id": "W1",
             "p0_mm": [0, 0], "p1_mm": [6000, 0], "height_mm": 3000,
             "level": {"by": "element_id", "value": 42},
             "type": {"by": "element_id", "value": 100}},
            {"op": "create_door", "id": "D1",
             "host": {"by": "ref", "value": "W1"}, "offset_mm": 2000,
             "symbol": {"by": "ref", "value": "LF"}},
        ]}
    # CLASH-починка (28.07, оператор: ранний честный релиз): move_elements +
    # change_type. targets mixes ref (this program's own wall+pipe, so
    # ElementTransformUtils.MoveElements is proven on a LocationCurve pair
    # created in the SAME transaction) with element_id (an existing
    # element); change_type runs on the same created wall, byref, proving
    # the target_w path independent of host/type selector kind.
    # auth_move_and_change_type is NOT set here: it lives in `PROGRAMS`
    # and arrives through the seed above, so the golden pins exactly the
    # program the gate compiles.
    # families_create_type_full / families_load_family_whole are NOT set
    # here any more: they live in `PROGRAMS` and arrive through the seed
    # above. Keeping a literal here too would mean the gate compiles one
    # program while the golden pins another — silently — the moment the
    # name exists in both. One source.
    # ops_families gate (wave/families, 2026-07-17): create_type (FamilySymbol
    # duplication — the exact prod incident this wave fixes, RC columns coming
    # in as steel because no create_type existed) + load_family (Document.
    # LoadFamily/LoadFamilySymbol, wiki family-load-place.md FAM-034 pattern).
    programs["families_create_type_by_name_custom_params"] = {"ir_version": "1.0",
        "intent": "тип по имени источника с нестандартными именами параметров",
        "ops": [{"op": "create_type", "id": "T1",
                 "source_type": {"by": "name", "value": "К 300x300"},
                 "category": "structural", "new_name": "К 350x300",
                 "width_mm": 350, "param_width_name": "b"}]}
    programs["families_create_type_architectural"] = {"ir_version": "1.0",
        "intent": "архитектурная колонна нового сечения",
        "ops": [{"op": "create_type", "id": "T1",
                 "source_type": {"by": "element_id", "value": 501},
                 "category": "architectural", "new_name": "Колонна 400",
                 "width_mm": 400, "param_width_name": "Width"}]}
    programs["families_type_then_setparam_ref"] = {"ir_version": "1.0",
        "intent": "тип + правка комментария к типу по intra-program ref",
        "ops": [
            {"op": "create_type", "id": "T1",
             "source_type": {"by": "element_id", "value": 500},
             "category": "structural", "new_name": "ЖБ 400x400 v2",
             "width_mm": 400, "depth_mm": 400},
            {"op": "set_param", "id": "S1", "target": {"by": "ref", "value": "T1"},
             "param": "Комментарии типа", "value": "создан KIR"},
        ]}
    programs["families_load_family_named_type"] = {"ir_version": "1.0",
        "intent": "загрузить один именованный типоразмер",
        "ops": [{"op": "load_family", "id": "F1",
                 "path": r"C:\Lib\Doors\Standard.rfa", "type_name": "0900x2100"}]}
    rnga_fam = random.Random(SEED + 2)
    _fam_sources = [({"by": "element_id", "value": 500}, "structural"),
                    ({"by": "name", "value": "К 300x300"}, "structural"),
                    ({"by": "element_id", "value": 501}, "architectural")]
    for i in range(8):
        src, cat = rnga_fam.choice(_fam_sources)
        op = {"op": "create_type", "id": "T1", "source_type": src, "category": cat,
              "new_name": f"КИР-тип-{i}", "width_mm": float(rnga_fam.randint(50, 2000))}
        if rnga_fam.random() < 0.6:
            op["depth_mm"] = float(rnga_fam.randint(50, 2000))
        if rnga_fam.random() < 0.3:
            op["material"] = rnga_fam.choice(["Бетон", "Сталь", "Дерево"])
        programs[f"families_pbt_{i}"] = {"ir_version": "1.0",
            "intent": "families pbt", "ops": [op]}
    # wave/struct (2026-07-17): create_beam + create_foundation (both
    # varieties) gate coverage. struct_beam/struct_foundation_isolated/
    # struct_foundation_slab already included above via test_golden.PROGRAMS;
    # these add the version-axis edge case (slab holes refused pre-2022,
    # mirrors auth_floor_holes/auth_contour_l) plus a mixed authoring program
    # (beam + isolated footing sharing one txn/level, the realistic "колонна
    # + фундамент + балка" combo) and PBT coverage.
    programs["struct_foundation_slab_holes_2021"] = {"ir_version": "1.0",
        "intent": "плитный фундамент с проёмом (версионная граница)",
        "ops": [{"op": "create_foundation", "id": "F1", "variety": "slab",
                 "outline": [[0, 0], [8000, 0], [8000, 6000], [0, 6000]],
                 "holes": [[[3000, 2000], [5000, 2000], [5000, 4000], [3000, 4000]]],
                 "level": {"by": "name", "value": "Этаж 1"}}]}
    programs["struct_beam_and_isolated_footing"] = {"ir_version": "1.0",
        "intent": "колонна: фундамент + балка на одном уровне",
        "ops": [
            {"op": "create_foundation", "id": "F1", "variety": "isolated",
             "xy": [0, 0], "level": {"by": "element_id", "value": 42}},
            {"op": "create_foundation", "id": "F2", "variety": "isolated",
             "xy": [6000, 0], "level": {"by": "element_id", "value": 42}},
            {"op": "create_beam", "id": "B1", "p0_mm": [0, 0, 3000],
             "p1_mm": [6000, 0, 3000], "level": {"by": "element_id", "value": 42}},
        ]}
    # wave/wall-foundation (2026-08-09): struct_wall_foundation уже приехал
    # выше из test_golden.PROGRAMS и несёт обе ветви носителя. Здесь — то,
    # чего эталон дать не может: ЦЕПОЧКА из нескольких стен со своими лентами
    # в одной транзакции (у каждой опы своя переменная носителя и свой
    # свидетель — именно так ловится столкновение имён между соседями,
    # невидимое на программе из одного опа).
    programs["struct_wall_foundation_chain"] = {"ir_version": "1.0",
        "intent": "ленты под тремя стенами одной программой",
        "ops": [
            {"op": "create_wall", "id": "W1", "p0_mm": [0, 0], "p1_mm": [9000, 0],
             "level": {"by": "element_id", "value": 42}},
            {"op": "create_wall", "id": "W2", "p0_mm": [9000, 0], "p1_mm": [9000, 6000],
             "level": {"by": "element_id", "value": 42}},
            {"op": "create_wall_foundation", "id": "WF1",
             "wall": {"by": "ref", "value": "W1"},
             "type": {"by": "name", "value": "Ленточный 600x300"}},
            {"op": "create_wall_foundation", "id": "WF2",
             "wall": {"by": "ref", "value": "W2"}},
            {"op": "create_wall_foundation", "id": "WF3",
             "wall": {"by": "element_id", "value": 8145901},
             "type": {"by": "name", "value": "Ленточный 900x400"}},
        ]}
    # wave/framing (2026-08-09): балочная система и ферма. Оси версий у обеих
    # НЕТ (все четыре перегрузки BeamSystem.Create и единственная подпись
    # Truss.Create компилируются 6/6), поэтому ворота здесь стерегут не
    # развилку по версиям, а то, чего эталон дать не может: ДУГОВОЙ профиль
    # (питоновская развилка по bulge внутри одной эмиссии) и НЕСКОЛЬКО
    # операций одной волны в одной транзакции — именно так ловится
    # столкновение имён между соседями, невидимое на программе из одного опа.
    programs["struct_beam_system_arc_profile"] = {"ir_version": "1.0",
        "intent": "балочная система по дуговому эскизу",
        "ops": [{"op": "create_beam_system", "id": "BS1",
                 "profile": {"outer": {"shape": "poly",
                                       "points_mm": [[0, 0], [9000, 0],
                                                     [9000, 6000], [0, 6000]],
                                       "arcs": [{"edge": 1, "radius_mm": 8000}]}},
                 "direction_edge": 0,
                 "level": {"by": "name", "value": "Этаж 1"},
                 "symbol": {"by": "name", "value": "Балка 200x400"}}]}
    # wave/reinforcement (2026-08-10): армирование по области. Оси версий у
    # него НЕТ (обе перегрузки AreaReinforcement.Create компилируются 6/6),
    # поэтому ворота стерегут не развилку по версиям, а ровно то, чего
    # программа из одного опа дать не может: ОБЕ формы носителя (ref на плиту
    # этой же программы и element_id на уже стоящую), ОБЕ ветки типа
    # (документное умолчание и by:name), обе ветки крюка (пропуск = без
    # крюков и by:name) и НЕСКОЛЬКО таких опов в одной транзакции — так
    # ловится столкновение имён между соседями.
    rnga_reinf = random.Random(SEED + 7)
    for i in range(4):
        # УГОЛ — СЛУЧАЙНЫЙ И ВНЕ 0..360 ТОЖЕ. Направление периодично, границ у
        # него в реестре нет намеренно, и эмиссия обязана печатать конечные
        # cos/sin при любом входе: угол 725° и -30° — законные программы.
        programs[f"struct_area_reinforcement_pbt_{i}"] = {"ir_version": "1.0",
            "intent": "армирование по области pbt",
            "ops": [{"op": "create_area_reinforcement", "id": "AR1",
                     "host": {"by": "element_id",
                              "value": rnga_reinf.randint(1000, 9_000_000)},
                     "direction_deg": rnga_reinf.uniform(-720.0, 720.0),
                     "bar_type": {"by": "element_id", "value": 1902}}]}
    rnga_framing = random.Random(SEED + 5)
    for i in range(6):
        x0 = rnga_framing.randint(-50000, 50000)
        if rnga_framing.random() < 0.5:
            w = rnga_framing.randint(2000, 20000)
            h = rnga_framing.randint(2000, 20000)
            programs[f"struct_beam_system_pbt_{i}"] = {"ir_version": "1.0",
                "intent": "балочная система pbt",
                "ops": [{"op": "create_beam_system", "id": "BS1",
                         "profile": {"outer": {"shape": "rect",
                                               "origin": [x0, x0],
                                               "size_mm": [w, h]}},
                         "level": {"by": "element_id", "value": 42}}]}
        else:
            programs[f"struct_truss_pbt_{i}"] = {"ir_version": "1.0",
                "intent": "ферма pbt",
                "ops": [{"op": "create_truss", "id": "TR1",
                         "p0_mm": [x0, x0],
                         "p1_mm": [x0 + rnga_framing.randint(3000, 30000), x0],
                         "level": {"by": "element_id", "value": 42}}]}
    rnga_struct = random.Random(SEED + 3)
    for i in range(8):
        x0 = rnga_struct.randint(-50000, 50000)
        z0 = rnga_struct.randint(0, 4000)
        if rnga_struct.random() < 0.5:
            programs[f"struct_beam_pbt_{i}"] = {"ir_version": "1.0", "intent": "балка pbt",
                "ops": [{"op": "create_beam", "id": "B1",
                         "p0_mm": [x0, x0, z0],
                         "p1_mm": [x0 + rnga_struct.randint(1000, 15000), x0, z0],
                         "level": {"by": "element_id", "value": 42}}]}
        else:
            w = rnga_struct.randint(2000, 20000)
            h = rnga_struct.randint(2000, 20000)
            programs[f"struct_foundation_pbt_{i}"] = {"ir_version": "1.0", "intent": "фундамент pbt",
                "ops": [{"op": "create_foundation", "id": "F1", "variety": "slab",
                         "outline": [[x0, x0], [x0 + w, x0], [x0 + w, x0 + h], [x0, x0 + h]],
                         "level": {"by": "element_id", "value": 42}}]}
    rnga = random.Random(SEED + 1)
    from kukai.ir.tests.test_authoring import NASTY
    for i in range(8):
        x0 = rnga.randint(-50000, 50000)
        programs[f"auth_pbt_{i}"] = _prog([
            _wall(oid=f"W{j}", p0_mm=[x0, j * 3000], p1_mm=[x0 + 5000, j * 3000],
                  height_mm=rnga.randint(1000, 6000))
            for j in range(rnga.randint(1, 4))
        ], intent=rnga.choice(NASTY))

    def _needs_snapshot(p: dict) -> bool:
        """By op FAMILY over the EXPANDED op list — macros hide pool-needing
        ops (a stack's pipes), so detection must run post-expansion; and never
        by program name (the checkpoint-return lesson)."""
        from kukai.ir import macros as _macros
        ops = p.get("ops", [])
        try:
            ops = _macros.expand(ops)
        except Exception:
            pass          # compiler will refuse; no snapshot decision needed
        for o in ops if isinstance(ops, list) else []:
            os_ = spec.OPS.get(o.get("op")) if isinstance(o, dict) else None
            if os_ is not None and os_.family in spec.WRITE_FAMILIES:
                return True
        return False

    # per_op axis (promoted from the scratch gate_per_op.py prototype,
    # 28.07): the atomic-only loop below left every emitter's per_op branch
    # — the SubTransaction wrapper closing over an emitter's own locals,
    # exactly the shape that produced the load_family CS0136 __ok_<s>
    # collision — compiled ZERO times by this gate; the only place per_op
    # ever ran live was a real A5/bulk rebuild. A KNOWN, already-tracked
    # per_op-only defect (fix pending, not yet landed) is counted as an
    # EXPECTED regression here — visible in the printed row, added to
    # known_gaps, and EXCLUDED from `failures` — never a silent green hole
    # (name not in the dict) and never an untracked plain failure (name in
    # the dict but still counted against the pass/fail bit).
    PER_OP_KNOWN_GAPS: dict[str, str] = {
        # name -> reason. Empty by construction (28.07): the two per_op
        # defects this same wave's per_op gate found — load_family CS0136
        # __ok_<s> collision, in_view:{by:ref} CS0039 — are BOTH fixed. This
        # dict is the mechanism for the NEXT one, not a resting place for
        # old bugs already closed.
    }
    #: Программы, чьи опы честно ОТКАЗЫВАЮТ на 2024-2026 (см. ниже). Имена,
    #: а не признак «в программе есть нагрузка»: список должен быть
    #: перечитываемым глазом, ровно как соседний перечень потолков.
    ANALYSIS_LOAD_PROGRAMS = frozenset({"analysis_loads"})

    checks = 0
    known_gaps = 0
    failures = 0
    sized_cable_tray_branch_checks = 0
    #: Bodies the Roslyn service actually answered about. DERIVED from the
    #: calls themselves (`_compile_check` below is the only door), never
    #: incremented beside an attempt — so a check that is skipped cannot
    #: inflate it. `checks` counts ATTEMPTS and the two differ by exactly
    #: `not_compiled`; the summary prints all three, because a number that
    #: cannot tell "passed" from "never attempted" is not a measurement.
    compiled = 0
    #: reason -> how many attempts ended without any C# reaching Roslyn.
    #: A skipped check is a named category in the summary, never absent.
    not_compiled: dict[str, int] = {}

    def _skip(reason: str) -> None:
        not_compiled[reason] = not_compiled.get(reason, 0) + 1

    async def _compile_check(wrapped: str, ver: str):
        """The ONLY path to the compile service, so `compiled` cannot lie."""
        nonlocal compiled
        res = await client.check(wrapped, ver)
        if res is None:
            _skip("compile-service-no-answer")
        else:
            compiled += 1
        return res

    async def _gate_row(name: str, prog: dict, snapshot, isolation: str) -> list[str]:
        nonlocal checks, known_gaps, failures, sized_cable_tray_branch_checks
        row: list[str] = []
        for ver in spec.REVIT_VERSIONS:
            checks += 1
            out = compile_program(prog, revit_version=ver,
                                  snapshot=snapshot,
                                  isolation=isolation)   # per-version emit (SPEC 11.2)
            # wave/arch: у ПОТОЛКА отказ на 2021 — не «известная дыра», а
            # правильный ответ. Ceiling.Create появился в 2022, а
            # doc.Create.NewCeiling не существует ни на одной из шести версий
            # (замерено компиляцией), то есть построить потолок на 2021
            # нечем. Ворота обязаны отличать «операция честно сказала, что
            # на этой версии её нет» от «эмиссия сломалась»: без этой строки
            # зелёные ворота требовали бы от опа молча построить что-нибудь
            # другое — ровно тот Гудхарт, ради борьбы с которым отказ и
            # заведён.
            if ver < E003_EXPECTED_BELOW.get(name, "2021") \
                    and not out.ok \
                    and any(d.code == "KIR-E003" for d in out.diagnostics):
                row.append(f"{ver}:E003-EXPECTED")
                _skip("e003-expected-refusal")
                continue
            # wave/analysis (09.08): та же мысль, но ось версий смотрит В
            # ДРУГУЮ СТОРОНУ. Свободная (нехостированная) нагрузка ЕСТЬ на
            # 2021-2023 и убрана Autodesk из API в 2024 (замер: перегрузки без
            # `ElementId hostElemId` дают CS1503/CS1501 на всех трёх новых
            # версиях). Отказ на 2024-2026 — правильный ответ операции, а не
            # поломка эмиссии, и ворота обязаны это различать.
            if not out.ok and name in ANALYSIS_LOAD_PROGRAMS and ver >= "2024" \
                    and any(d.code == "KIR-E003" for d in out.diagnostics):
                row.append(f"{ver}:E003-EXPECTED")
                _skip("e003-expected-refusal")
                continue
            if not out.ok:
                if name in PER_OP_KNOWN_GAPS:
                    row.append(f"{ver}:KNOWN-GAP")
                    known_gaps += 1
                    _skip("known-gap-refusal")
                    continue
                print(f"FAIL {name}@{ver} [{isolation}]: KIR refused: "
                      f"{[d.code for d in out.diagnostics][:3]}")
                failures += 1
                row.append(f"{ver}:REFUSED")
                _skip("compiler-refused")
                continue
            if name == SIZED_CABLE_TRAY_GATE_NAME:
                if not sized_cable_tray_branch_reached(out.csharp):
                    print(f"FAIL {name}@{ver} [{isolation}]: sized cable-tray "
                          "emitter branch was not reached")
                    failures += 1
                    row.append(f"{ver}:BRANCH?")
                    _skip("emitter-branch-not-reached")
                    continue
                sized_cable_tray_branch_checks += 1
            wrapped = wrap_user_code(out.csharp)
            res = await _compile_check(wrapped, ver)
            if res is None:
                row.append(f"{ver}:SVC?")
                failures += 1
            elif res.success:
                row.append(f"{ver}:OK")
            elif name in PER_OP_KNOWN_GAPS:
                row.append(f"{ver}:KNOWN-GAP")
                known_gaps += 1
                for e in res.errors[:3]:
                    print(f"    {name} @{ver} [{isolation}, known gap: "
                          f"{PER_OP_KNOWN_GAPS[name]}] {e.code} L{e.line}: "
                          f"{e.message[:100]}")
            else:
                row.append(f"{ver}:FAIL")
                failures += 1
                for e in res.errors[:3]:
                    print(f"    {name} @{ver} [{isolation}] {e.code} L{e.line}: "
                          f"{e.message[:100]}")
        return row

    write_program_count = 0
    # Заземление — свойство ВОРОТ, а не только набора (найдено зоной НАБОР
    # 12.08). Всё, что требует снимка, заземляется против ФИКСТУРЫ, и потому
    # каждое такое «OK» есть утверждение о фикстуре, а не о настоящем
    # документе. Считаем долю здесь, чтобы напечатать её вместе с числом, а
    # не оставить в чьей-то памяти.
    program_compilations = 0
    fixture_grounded = 0
    # ВТОРАЯ ПОЛОСА. Корпус читается ОДИН раз: 73 профиля стоят ~1 с, а внутри
    # цикла это стало бы стоимостью, растущей с числом программ, — форма 10.
    real_profiles = load_real_profiles()
    real_grounded = 0
    real_remainder: list[tuple[str, str]] = []
    # ЕДИНИЦА ЗНАМЕНАТЕЛЯ. `fixture_grounded` считает КОМПИЛЯЦИИ (пишущая
    # программа входит дважды: atomic и per_op), а вторая полоса считает
    # ПРОГРАММЫ. Делить одно на другое значит сложить разные единицы — именной
    # дефект этого дерева. Поэтому у второй полосы свой счётчик программ.
    snapshot_programs = 0
    for name, prog in programs.items():
        needs_snapshot = _needs_snapshot(prog)
        snapshot = GROUND_SNAPSHOT if needs_snapshot else None
        program_compilations += 1
        if needs_snapshot:
            fixture_grounded += 1
        atomic_row = await _gate_row(name, prog, snapshot, "atomic")
        print(f"{name:24s} {' '.join(atomic_row)}")
        # Настоящий документ — ОТДЕЛЬНЫЙ вопрос, и его «OK» не заменяет
        # фикстурное: программа может собираться на всех шести и не иметь ни
        # одного здания, которым её можно заземлить. Считаем и то и другое.
        if needs_snapshot and real_profiles:
            snapshot_programs += 1
            real = ground_on_real_document(prog, real_profiles)
            if isinstance(real, tuple):
                real_run, real_snapshot = real
                real_grounded += 1
                real_row = await _gate_row(
                    name, prog, real_snapshot, "atomic")
                print(f"{name + '@' + real_run:24.24s} {' '.join(real_row)}")
            else:
                real_remainder.append((name, real))
        # per_op is only a DIFFERENT emission for write-family programs (the
        # query/read path ignores isolation entirely — compiling it twice
        # would be redundant, not honest new coverage). `_needs_snapshot`
        # already computes exactly this predicate (post-macro-expansion, by
        # op family, never by program name — same discipline as its own
        # docstring), so it doubles as the per_op eligibility check.
        if needs_snapshot:
            write_program_count += 1
            program_compilations += 1
            fixture_grounded += 1
            per_op_row = await _gate_row(
                name, prog, snapshot, "per_op")
            print(f"{name + '_per_op':24s} {' '.join(per_op_row)}")

    expected_sized_tray_checks = len(spec.REVIT_VERSIONS) * 2
    if sized_cable_tray_branch_checks != expected_sized_tray_checks:
        print("FAIL sized cable-tray gate coverage: "
              f"{sized_cable_tray_branch_checks}/"
              f"{expected_sized_tray_checks} branch emissions")
        failures += 1

    # Expected-refusal gate: valuable invariants proven in CI, not left to be
    # accidental failures. (coordinator return, 2026-07-16)
    expected_refusals = {
        "auth_no_snapshot": (_prog([_wall()], intent="без снапшота"), None, "KIR-G103"),
        # 28.07 per_op gate finding: in_view:{by:ref} used to compile
        # (ok=True) into a GUARANTEED Roslyn CS0039.  Forward-reference
        # compatibility is now a typed-IR responsibility, so the invalid
        # non-referenceable view input must stop at KIR-T001 before grounding
        # or emission (also pinned in test_result_semantics.py).
        # Волна ЭОМ 09.08. Совпадающие точки гибкой трассы — отказ НА
        # КОМПИЛЯЦИИ, а не на свидетеле: Autodesk пишет, что Revit такие
        # точки ВЫБРАСЫВАЕТ, то есть построил бы трассу с другим числом
        # точек. Свидетель поймал бы это следствие, но диагноз назвал бы
        # «геометрия не сошлась»; причина видна раньше, и ворота держат
        # именно её.
        "auth_flex_duplicate_point_refused": (
            {"ir_version": "1.0", "intent": "гибкая труба с совпадающими точками",
             "ops": [{"op": "create_flex_pipe", "id": "FPX",
                      "path": [[0, 0, 3000], [0, 0, 3000], [1000, 0, 3000]],
                      "level": {"by": "element_id", "value": 42}}]},
            GROUND_SNAPSHOT, "KIR-T002"),
        # RELATE, адрес от элемента (09.08). Верх колонны БЕЗ `top_level` в
        # программе не определён: высота приезжает из типоразмера, которого
        # программа не знает. Отказ обязан быть ОФЛАЙНОВЫМ и типизированным —
        # молча взятый «низ + что-нибудь» поставил бы балку на отметку,
        # которую свидетель принял бы (он сверяет с тем же числом).
        "auth_address_element_unbound_top_refused": (
            {"ir_version": "1.0", "intent": "балка по верху неприкреплённой колонны",
             "ops": [
                 {"op": "create_column", "id": "UC1", "xy": [0, 0],
                  "level": {"by": "element_id", "value": 42},
                  "symbol": {"by": "element_id", "value": 500}},
                 {"op": "create_beam", "id": "UB1",
                  "p0_mm": {"at_element": {"by": "ref", "value": "UC1"},
                            "point": "center", "z": "top"},
                  "p1_mm": [4000, 0, 3300],
                  "level": {"by": "element_id", "value": 42},
                  "symbol": {"by": "element_id", "value": 1100}}]},
            GROUND_SNAPSHOT, "KIR-G115"),
        "auth_in_view_ref_refused": (
            _prog([_wall(), {"op": "create_tag", "id": "TAG1",
                             "in_view": {"by": "ref", "value": "W1"},
                             "target": {"by": "ref", "value": "W1"},
                             "at": [3000, 800]}], intent="in_view ref"),
            GROUND_SNAPSHOT, "KIR-T001"),
    }
    for name, (prog, snap, want_code) in expected_refusals.items():
        out = compile_program(prog, revit_version="2026", snapshot=snap)
        codes = [d.code for d in out.diagnostics]
        if not out.ok and want_code in codes:
            print(f"{name:24s} EXPECTED-REFUSAL:{want_code} OK")
        else:
            print(f"FAIL {name}: want refusal {want_code}, got ok={out.ok} codes={codes}")
            failures += 1

    # serving ground-snapshot collector: emitted-adjacent C#, same 6/6 bar
    from kukai.ir.serving import _SNAPSHOT_CS
    wrapped_snap = wrap_user_code(_SNAPSHOT_CS)
    row = []
    for ver in spec.REVIT_VERSIONS:
        checks += 1
        res = await _compile_check(wrapped_snap, ver)
        if res is None:
            row.append(f"{ver}:SVC?"); failures += 1
        elif res.success:
            row.append(f"{ver}:OK")
        else:
            row.append(f"{ver}:FAIL"); failures += 1
            for e in res.errors[:3]:
                print(f"    snapshot_cs @{ver} {e.code} L{e.line}: {e.message[:100]}")
    print(f"{'serving_snapshot_cs':24s} {' '.join(row)}")

    # Open-model transaction guard: optional internal emission is outside the
    # legacy byte corpus, so compile it explicitly on all versions.  This also
    # proves the document guard and identity guard remain separated by valid
    # newlines before the first mutation.
    _guard_snapshot, _guard_profile, _guard_document = (
        model_binding_guard_inputs())
    row = []
    for ver in spec.REVIT_VERSIONS:
        checks += 1
        guarded = compile_program(
            programs["auth_wall"],
            revit_version=ver,
            snapshot=_guard_snapshot,
            expected_document=_guard_document,
            open_model_profile=_guard_profile,
        )
        if not guarded.ok:
            row.append(f"{ver}:REFUSED")
            failures += 1
            _skip("compiler-refused")
            # A refusal here used to print NOTHING while a Roslyn error
            # printed three lines, so the one failure mode the reader could
            # not see was the one that fired — and every reader guessed it
            # as a compile failure. Say the reason.
            print(f"FAIL model_binding_guard@{ver}: KIR refused: "
                  + "; ".join(f"{d.code} {d.message_ru}"
                              for d in guarded.diagnostics[:3]))
            continue
        res = await _compile_check(wrap_user_code(guarded.csharp), ver)
        if res is None:
            row.append(f"{ver}:SVC?"); failures += 1
        elif res.success:
            row.append(f"{ver}:OK")
        else:
            row.append(f"{ver}:FAIL"); failures += 1
            for e in res.errors[:3]:
                print(f"    model_binding_guard @{ver} {e.code} L{e.line}: "
                      f"{e.message[:100]}")
    print(f"{'model_binding_guard':24s} {' '.join(row)}")

    # Name<->ordinal tables, pinned against AUTODESK rather than against
    # ourselves. `WALL_LOCATION_LINE_ORDINALS` is read by BOTH the emitter
    # (authoring.py, `.Set(ORDINALS[name])`) and its witness (same lookup),
    # so the two cannot disagree: swap a name/ordinal PAIR and the user asks
    # for `wall_centerline`, Revit receives `CoreCenterline`, and the witness
    # confirms the value it just wrote. Measured 2026-08-12: that mutation
    # survives the whole test suite AND a green 6/6 gate. Every guard the
    # table had reads the table — including one that inverts a dict derived
    # by inverting it, which is a tautology true of any permutation.
    #
    # "Ask the authority" is our usual remedy and it fails here, because the
    # authority WAS our table. So ask an authority outside the repository:
    # the real RevitAPI assemblies. C# has no static_assert, but two `case`
    # labels with the same constant value is CS0152 — so a compile FAILURE
    # proves the equality, and a clean compile proves inequality. Both
    # directions are decidable, which is why this can also fail.
    #
    # SCOPE, measured, so this is not quoted later as a general shield:
    # `WALL_LOCATION_LINE_ORDINALS` is the ONLY such table in the registry
    # today. The form generalises; the coverage is one table.
    from kukai.ir.ops_authoring import WALL_LOCATION_LINE_ORDINALS

    #: our name -> the enum member Autodesk must agree it equals. CLOSED: a
    #: row added to the table without a member here fails the stage rather
    #: than being skipped, so the next addition forces a decision.
    _WALL_LL_CS_MEMBERS = {
        "wall_centerline": "WallCenterline",
        "core_centerline": "CoreCenterline",
        "finish_face_exterior": "FinishFaceExterior",
        "finish_face_interior": "FinishFaceInterior",
        "core_exterior": "CoreExterior",
        "core_interior": "CoreInterior",
    }

    def _enum_probe_cs(member: str, ordinal: int) -> str:
        return (
            "using Autodesk.Revit.DB;\n"
            "namespace Kukai { class UserCode { public void Execute() {\n"
            "    switch (0) {\n"
            f"        case (int)WallLocationLine.{member}: break;\n"
            f"        case {ordinal}: break;\n"
            "    }\n"
            "} } }\n")

    unmapped = sorted(set(WALL_LOCATION_LINE_ORDINALS) - set(_WALL_LL_CS_MEMBERS))
    if unmapped:
        print("FAIL wall-location-line enum pin: table rows with no Revit "
              f"member declared: {unmapped}")
        failures += 1
    row = []
    for ver in spec.REVIT_VERSIONS:
        agreed = 0
        for name, ordinal in sorted(WALL_LOCATION_LINE_ORDINALS.items()):
            member = _WALL_LL_CS_MEMBERS.get(name)
            if member is None:
                continue
            checks += 1
            res = await _compile_check(_enum_probe_cs(member, ordinal), ver)
            if res is None:
                print(f"FAIL wall_ll_enum@{ver} {name}: compile service "
                      "gave no answer")
                failures += 1
                continue
            if any(e.code == "CS0152" for e in res.errors):
                agreed += 1            # Autodesk says the pair is right
            elif res.success:
                print(f"FAIL wall_ll_enum@{ver}: Autodesk disagrees — "
                      f"{name} is NOT {ordinal} "
                      f"(WallLocationLine.{member} compiled beside case "
                      f"{ordinal} without a duplicate-label error)")
                failures += 1
            else:
                print(f"FAIL wall_ll_enum@{ver} {name}: inconclusive, "
                      f"{sorted({e.code for e in res.errors})}")
                failures += 1
        # The stage must be able to say NO: a deliberately wrong pair has to
        # COMPILE CLEANLY. Without this, "did not build" degrades into "did
        # not build for any reason" and the pin stops being an instrument.
        # The wrong ordinal is taken OUTSIDE the enum's value range, not from
        # a sibling row: a control drawn from the table stops being wrong the
        # moment the table is permuted, which is the coupling this whole stage
        # exists to break. 9999 is wrong under every permutation.
        checks += 1
        wrong = await _compile_check(
            _enum_probe_cs("WallCenterline", 9999), ver)
        if wrong is None or not wrong.success:
            print(f"FAIL wall_ll_enum@{ver}: CONTROL — a deliberately wrong "
                  "pair did not compile cleanly, so a passing pin proves "
                  f"nothing ({'no answer' if wrong is None else sorted({e.code for e in wrong.errors})})")
            failures += 1
            row.append(f"{ver}:CONTROL?")
            continue
        row.append(f"{ver}:{agreed}/{len(_WALL_LL_CS_MEMBERS)}")
    print(f"{'wall_ll_enum_pin':24s} {' '.join(row)}")

    # The independent acceptance body is not emitted by compile_program, so it
    # needs an explicit 6/6 proof just like the ground snapshot and decompile
    # side stages.  A Python shape test cannot detect a Revit API member drift.
    _acceptance_body = acceptance_gate_body()
    row = []
    for ver in spec.REVIT_VERSIONS:
        checks += 1
        res = await _compile_check(wrap_user_code(_acceptance_body), ver)
        if res is None:
            row.append(f"{ver}:SVC?"); failures += 1
        elif res.success:
            row.append(f"{ver}:OK")
        else:
            row.append(f"{ver}:FAIL"); failures += 1
            for e in res.errors[:3]:
                print(f"    acceptance_l2 @{ver} {e.code} L{e.line}: "
                      f"{e.message[:140]}")
    print(f"{'acceptance_l2':24s} {' '.join(row)}")

    # Mutation probes use LocationPoint/LocationCurve, GetParameters,
    # GetTypeId, UniqueId, and the version-split ElementId constructor.  They
    # are emitted per API version and must pass the same live compiler matrix.
    row = []
    for ver in spec.REVIT_VERSIONS:
        checks += 1
        res = await _compile_check(
            wrap_user_code(mutation_acceptance_gate_body(ver)), ver)
        if res is None:
            row.append(f"{ver}:SVC?"); failures += 1
        elif res.success:
            row.append(f"{ver}:OK")
        else:
            row.append(f"{ver}:FAIL"); failures += 1
            for e in res.errors[:3]:
                print(f"    acceptance_mutation @{ver} {e.code} L{e.line}: "
                      f"{e.message[:140]}")
    print(f"{'acceptance_mutation':24s} {' '.join(row)}")

    # DECOMPILE side-index bridge collectors: read-only Execute bodies emitted
    # by the extract builders.  Same 6/6 compile bar as serving_snapshot_cs —
    # the bridge round-trip is expensive, so a version-specific compile failure
    # must be caught here, not at a live-Revit run.  Bodies use only
    # representative ids/budgets (the emitted C# is id-count-invariant in
    # shape), and are EMITTED PER VERSION (see side_stage_gate_bodies).
    _side_rows: dict[str, list[str]] = {
        stage: [] for stage in side_stage_gate_bodies(spec.REVIT_VERSIONS[0])}
    for ver in spec.REVIT_VERSIONS:
        for _stage, _body in sorted(side_stage_gate_bodies(ver).items()):
            checks += 1
            res = await _compile_check(wrap_user_code(_body), ver)
            if res is None:
                _side_rows[_stage].append(f"{ver}:SVC?"); failures += 1
            elif res.success:
                _side_rows[_stage].append(f"{ver}:OK")
            else:
                _side_rows[_stage].append(f"{ver}:FAIL"); failures += 1
                for e in res.errors[:3]:
                    print(f"    боковая {_stage} @{ver} {e.code} L{e.line}: "
                          f"{e.message[:140]}")
    for _stage in sorted(_side_rows):
        print(f"{'боковая ' + _stage:24s} {' '.join(_side_rows[_stage])}")

    # БАЗОВОЕ ТЕЛО ИЗВЛЕЧЕНИЯ. До 31.07 ворота компилировали боковые стадии и
    # НЕ компилировали главную: `build_category_batch_cs` — тот самый код,
    # который читает каждый элемент каждого разбора. Дыра нашлась при добавке
    # `CEILING_HEIGHTABOVELEVEL_PARAM`: имя параметра было взято из
    # документации, а документация Autodesk расходится с её же сборками
    # (задача #78 — `SpatialElementTag.SpatialElement` описан в шести версиях
    # XML и отсутствует в шести DLL). Утверждать существование члена по
    # описанию — ровно то, от чего эти ворота и защищают.
    #
    # Трёх категорий достаточно и это ЗАМЕРЕНО, а не выбрано на глаз: блок
    # параметров общий для всех категорий (один набор `__Put*Param` на
    # элемент), различается только коллектор. Стена, потолок и перекрытие
    # берут три разных коллектора и один общий блок.
    from kukai.ir.decompile.extract import build_category_batch_cs
    for _cat in ("OST_Walls", "OST_Ceilings", "OST_Floors"):
        _row: list[str] = []
        _body = build_category_batch_cs(_cat)
        for ver in spec.REVIT_VERSIONS:
            checks += 1
            res = await _compile_check(wrap_user_code(_body), ver)
            if res is None:
                _row.append(f"{ver}:SVC?"); failures += 1
            elif res.success:
                _row.append(f"{ver}:OK")
            else:
                _row.append(f"{ver}:FAIL"); failures += 1
                for e in res.errors[:3]:
                    print(f"    извлечение {_cat} @{ver} {e.code} L{e.line}: "
                          f"{e.message[:140]}")
        print(f"{'извлечение ' + _cat:24s} {' '.join(_row)}")

    # УБОРКА ШТАМПОВ. Третья дыра одной породы, найденная за 31.07: ворота не
    # знали про `_orphan_sweep_cs` вовсе. Цена ошибки у этого генератора выше
    # средней — он единственный, кто УДАЛЯЕТ элементы из живой модели, и
    # несобирающаяся версия обнаружилась бы ровно в тот момент, когда человек
    # нажал «отменить построенное».
    #
    # Четыре варианта покрывают все ветви шаблона: предпросмотр против
    # удаления (разные блоки транзакции) и обе грамматики префикса — прогон A5
    # и хэш содержимого обычной программы. Страж отпечатка документа включён,
    # потому что он вставляет СВОЙ C# в оба блока.
    from kukai.ir.serving import DocumentFingerprint, _orphan_sweep_cs
    _fp = DocumentFingerprint(
        title="Ворота", path_name="gate.rvt", project_uid="gate-uid")
    _sweeps = {
        "a5 предпросмотр": ("kir:a5:" + "0" * 12 + ":" + "0" * 16 + ":", False),
        "a5 удаление": ("kir:a5:" + "0" * 12 + ":" + "0" * 16 + ":", True),
        "программа предпросмотр": ("kir:" + "0" * 8 + ":", False),
        "программа удаление": ("kir:" + "0" * 8 + ":", True),
    }
    for _label, (_prefix, _delete) in _sweeps.items():
        _row = []
        _body = _orphan_sweep_cs(
            _prefix, delete=_delete, document_fingerprint=_fp)
        for ver in spec.REVIT_VERSIONS:
            checks += 1
            res = await _compile_check(wrap_user_code(_body), ver)
            if res is None:
                _row.append(f"{ver}:SVC?"); failures += 1
            elif res.success:
                _row.append(f"{ver}:OK")
            else:
                _row.append(f"{ver}:FAIL"); failures += 1
                for e in res.errors[:3]:
                    print(f"    уборка {_label} @{ver} {e.code} L{e.line}: "
                          f"{e.message[:140]}")
        print(f"{'уборка ' + _label:24s} {' '.join(_row)}")

    await client.close()
    # Reconcile BEFORE the PASS/FAIL word is chosen, or the gate can print
    # PASS on the same line that records an accounting failure.
    if checks - compiled != sum(not_compiled.values()):
        print("FAIL gate accounting: attempts minus compiled "
              f"({checks - compiled}) does not equal the named skips "
              f"({sum(not_compiled.values())}) — a skip is going unnamed")
        failures += 1
    # `checks` counts ATTEMPTS; `compiled` counts bodies Roslyn answered.
    # They differ by exactly the skips, and every skip is named. Printing
    # only the attempt count is how "1896 live compile checks" came to
    # include 30 attempts that compiled nothing at all.
    #
    # THIS LINE GOES FIRST, AND THAT ORDER IS THE POINT. When it was printed
    # LAST, `tail -1` returned it — and it is byte-identical whether the gate
    # passed or failed, because a semantic failure (a wrong ordinal, a refused
    # program) changes no count here. A reader taking the last line got a
    # sentence that cannot say "no", and one of us nearly filed a red run as
    # green from exactly that. The VERDICT is now last, so the cheapest
    # possible reading is also the truthful one.
    print(f"\n      {checks} attempts = {compiled} compiled + "
          f"{checks - compiled} not compiled"
          + (" (" + ", ".join(f"{reason}: {count}" for reason, count
                              in sorted(not_compiled.items())) + ")"
             if not_compiled else ""))
    # The address of every number above. Printed BEFORE the verdict so the
    # verdict stays last, and printed even when incomplete — a manifest that
    # silently omits a version would be the defect this exists to close.
    _manifest, _mproblems = revit_reference_manifest()
    if _manifest:
        print("      Revit refs (" + ", ".join(_REVIT_REF_DLLS) + "), sha256/12:")
        print("        " + "  ".join(f"{v}:{d[:12]}"
                                     for v, d in sorted(_manifest.items())))
    for _p in _mproblems:
        print(f"      Revit refs UNAVAILABLE — {_p}")
    if not _manifest and not _mproblems:
        print("      Revit refs: manifest empty and no reason given — "
              "treat every count above as unaddressed")
    print("      system refs: NOT in this manifest (they belong to the "
          "service runtime); their role is Bridge parity, guarded by the "
          "drift guards on both sides")
    # ПРЕДМЕТ каждого числа выше, а не только его адрес. Печатается ПЕРЕД
    # вердиктом по тому же правилу, что и манифест: вердикт остаётся
    # последним. Найдено зоной НАБОР 12.08 — у фикстуры не хватало пула
    # `roof_types`, и обошлось дёшево лишь потому, что пул объявлен
    # необязательным; обязательный в той же позиции обрушил бы ворота
    # целиком, а выглядело бы это как «оп сломан». Полнота пулов фикстуры
    # пинится сверкой МНОЖЕСТВ у `spec.OPS` (зона НАБОР), не сверкой длин:
    # у производителя и у фикстуры было по 35 пулов при 34 совпадающих
    # именах, и любая проверка «сколько» подтвердила бы полноту.
    print(f"      заземление: {fixture_grounded} из {program_compilations} "
          f"компиляций программ идут против ФИКСТУРЫ "
          f"{GROUND_SNAPSHOT_ORIGIN} — не против настоящего документа. "
          f"Их «OK» есть утверждение о фикстуре")
    # ВТОРАЯ ПОЛОСА — РЯДОМ со строкой выше, а не вместо неё: это ответы на
    # РАЗНЫЕ вопросы, и замена одного другим потеряла бы оба.
    if not real_profiles:
        # Отказ, а не ноль. Ноль здесь читался бы как «настоящих документов
        # программы не выдерживают», тогда как правда — «мы не смотрели».
        print(f"      настоящий документ: ОТКАЗ ПРИБОРА — "
              f"{REAL_PROFILE_FETCH_HINT}")
    else:
        print(f"      настоящий документ: {real_grounded} из "
              f"{snapshot_programs} ПРОГРАММ, требующих снимка, заземлены "
              f"РАЗБОРОМ настоящего здания ({len(real_profiles)} профилей "
              f"корпуса) и собраны на шести версиях с ним. Знаменатель здесь "
              f"— программы, а не компиляции: строкой выше их "
              f"{fixture_grounded}, потому что пишущая входит дважды "
              f"(atomic и per_op)")
        # ЗАКРЫТЫЙ, НО НЕ ПОЛНЫЙ: пусто здесь значило бы «мы не знаем», а не
        # «остатка нет». Полнота недостижима — список ограничен корпусом,
        # который на этой машине может быть любым.
        for pname, why in real_remainder:
            print(f"        · {pname:32.32s} {why}")
    print(f"{'PASS' if failures == 0 else 'FAIL'}: "
          f"{len(programs)} programs (atomic) "
          f"+ {write_program_count} write programs (per_op), "
          f"x {len(spec.REVIT_VERSIONS)} versions each "
          f"+ {len(expected_refusals)} expected-refusal check(s), "
          f"{sized_cable_tray_branch_checks} sized-tray branch emission(s), "
          f"{compiled} live compile checks, "
          f"{known_gaps} known per_op gap(s) tracked separately, "
          f"{failures} failures")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
