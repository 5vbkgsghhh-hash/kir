"""Executable coverage contract between the KIR forward and reverse axes."""
from __future__ import annotations

import ast
import inspect
import json
import textwrap
import unittest
from collections import Counter

from kukai.ir import spec
from kukai.ir.decompile import lift, materialize
from kukai.ir.reverse_contract import (
    REVERSE_CONTRACTS,
    REVERSE_CONTRACT_SCHEMA,
    ReverseContractError,
    ReverseMode,
    assert_composed_emission,
    assert_lift_emission,
    reverse_contract_report,
)


class ReverseContractTests(unittest.TestCase):
    def test_manifest_is_exhaustive_over_live_write_registry(self):
        write_ops = {
            name for name, op_spec in spec.OPS.items()
            if op_spec.family in spec.WRITE_FAMILIES
        }
        self.assertEqual(set(REVERSE_CONTRACTS), write_ops)
        # 35 -> 37 (03.08.2026): +create_room_separator (волна разделителей)
        # и +create_opening (волна проёмов). Число здесь — ЗАМОК, а не
        # статистика: манифест обязан расти вместе с реестром, а не молча
        # отставать от него.
        # 37 -> 38 (09.08.2026): +create_wall_foundation, объявлен
        # capture_gap — L0 не несёт WallFoundation.WallId, а стена И ЕСТЬ
        # весь вход операции. Число direct-подъёмов при этом НЕ выросло,
        # и это ровно то, что замок обязан показывать.
        # 38 -> 43 (09.08.2026): волна ЭОМ/гибких/заготовок. Из пяти ровно
        # ОДНА (create_conduit) приехала с настоящим лифтером; четыре
        # остальные объявлены capture_gap, и это не отписка — у заготовок в
        # L0 нет бита IsPlaceholder, у гибких нет массива точек.
        # ЧИСЛО ПЕРЕСНЯТО `len(REVERSE_CONTRACTS)` НА СЛИТОМ ДЕРЕВЕ: обе
        # волны считали от 37, и «42» из ветки ЭОМ утопило бы ленточный
        # фундамент, не уронив ни одного теста.
        # 43 -> 44 (09.08.2026): +create_angular_dimension, capture_gap. Замок
        # сработал: у углового размера разрыв захвата на величину БОЛЬШЕ, чем
        # у линейного, — кроме вида-владельца и References пришлось бы поднять
        # ещё и дугу аннотации, которой в L0 1.0 нет вовсе.
        # 44 -> 46 (09.08.2026): волна каркаса — create_beam_system и
        # create_truss, обе capture_gap. Число direct-подъёмов НЕ выросло, и
        # это ровно тот показ, ради которого замок стоит: L0 читает
        # OST_StructuralFraming, то есть видит ПОРОЖДЁННЫЕ балки и стержни, а
        # не породившие их систему и ферму. Поднять их поштучно было бы ХУЖЕ
        # атома — объект исчез бы, а его раскладка выродилась в пачку
        # координат, которую нельзя перестроить.
        # 46 -> 50 (09.08.2026): волна нагрузок и пути эвакуации — все четыре
        # capture_gap, потому что L0 не читает ни нагрузок, ни линий пути
        # эвакуации вовсе. И ЭТОТ ЗАМОК СРАБОТАЛ ПРЯМО НА СЛИЯНИИ: волна
        # каркаса записала сюда «46», считая от 44 и не зная про нагрузки, —
        # число, взятое как есть, утопило бы все четыре операции ЭОМ-волны,
        # не уронив ни одного теста. 50 переснято `len(REVERSE_CONTRACTS)` на
        # слитом дереве, как и требует комментарий десятью строками выше.
        # 50 -> 53 (09.08.2026): волна площадки — create_topography,
        # create_building_pad, create_site_subregion. Все три CAPTURE_GAP, и
        # это ЗАМЕР, а не осторожность: в таблице категорий извлечения нет ни
        # OST_Topography, ни OST_Toposolid, ни OST_BuildingPad — конвейер их
        # не читает вовсе, значит строки L0 для подъёма не существует.
        # 53 -> 55 (09.08.2026): волна навесных профилей — create_wall_sweep и
        # create_slab_edge. Обе CAPTURE_GAP, и это ЗАМЕР той же проверкой: в
        # таблице категорий извлечения нет ни OST_Cornices, ни OST_Reveals, ни
        # OST_EdgeSlab. У стенного профиля к разрыву захвата добавляется ещё и
        # НЕУСТРАНИМАЯ часть: его положение не восстановимо ПО ПОСТРОЕНИЮ,
        # потому что Autodesk документирует его как свойство ТИПА, а не
        # вызова, — поэтому даже полный захват дал бы только хозяина, тип и
        # ориентацию (см. limitation контракта).
        # 55 -> 58 (09.08.2026, СЛИЯНИЕ). Волна датумов дала три контракта:
        # цепь осей DECOMPOSED (звенья поднимаются как create_grid, теряется
        # только принадлежность цепи), выдавленная кровля и многоэтажная
        # лестница — CAPTURE_GAP по ЗАМЕРУ (EXTRUSION_START/END и
        # ReferencePlane не встречаются в decompile/ ни разу, MultistoryStairs
        # — ни разу во всём пакете).
        #
        # И ЭТО ЧЕТВЁРТЫЙ РАЗ, КОГДА ЧИСЛО ЗДЕСЬ СТАЛО КОНФЛИКТОМ СЛИЯНИЯ.
        # История в комментариях выше называет 40, 46, 50, 53, 55, 47 — и
        # каждое было честно замерено на своей ветке. Объединение текста
        # оставило ДВА `assertEqual` подряд, из которых первое и падало.
        # Вывод не «сверять аккуратнее», а структурный: число ветвится вместе
        # с реестром, поэтому его берут ПРОГОНОМ `reverse_contract_report()`
        # в своём дереве, а записанное здесь — только след последнего замера.
        # 58 -> 60 (09.08.2026): волна тел — create_solid_extrusion и
        # create_solid_revolve, обе CAPTURE_GAP. Разрыв здесь ГЛУБЖЕ, чем у
        # прочих: элемент читается полностью, но построенный DirectShape
        # хранит B-rep, а не программу, которой его написали, — две разные
        # программы дают побайтово одинаковый элемент. Обратный ход требует
        # РАСПОЗНАВАНИЯ формы, а не ещё одного поля захвата.
        # ПЯТЫЙ РАЗ ЗА ДЕНЬ, КОГДА ЭТО ЧИСЛО — КОНФЛИКТ: волна тел написала
        # «46» против своей базы в 44. Переснято `len(REVERSE_CONTRACTS)` на
        # СВЕДЁННОМ дереве, ровно как требует абзац выше.
        # 60 -> 61 (09.08.2026): волна детализации — create_filled_region,
        # CAPTURE_GAP. Это ЗАМЕР по таблице категорий извлечения: ни
        # OST_FilledRegion, ни OST_MaskingRegion в ней нет. Разрыв ДВОЙНОЙ, и
        # вторая его половина ценнее первой: даже прочитанная
        # `GetBoundaries()` бесполезна без базиса вида-владельца — контур,
        # поднятый в мировые XY, на каждом разрезе означал бы другое место.
        # ШЕСТОЙ РАЗ ЗА ДЕНЬ: волна писала «54» против своей базы в 53.
        # Переснято `len(REVERSE_CONTRACTS)` на СВЕДЁННОМ дереве.
        # 61 -> 62 (10.08.2026): волна армирования — create_area_reinforcement,
        # CAPTURE_GAP. Замер, а не таксономия: категории OST_AreaRein нет в
        # `extract._CATEGORY_SPECS` вовсе, то есть чтение не встречает ни
        # системы армирования, ни её стержней; и в 38 сохранённых разборах с
        # переписью ноль таких элементов. Переснято `len(REVERSE_CONTRACTS)`
        # прогоном на ЭТОМ дереве, а не сложено с числом чужой ветки.
        # 61 -> 62 (10.08.2026): волна масс — create_face_wall, CAPTURE_GAP.
        # Режим выбран ЗАМЕРОМ, а не по привычке: OST_Walls извлечение читает,
        # но у `FaceWall` нет `LocationCurve` (CS0029 на всех шести — он не
        # `Wall`), а носителя и нормаль грани L0 не несёт ничем. Значит чинить
        # надо ЗАХВАТ, а не лифтер, и режим обязан говорить именно это.
        # 63 -> 64 (10.08.2026): волна лестниц — create_stairs_landing,
        # CAPTURE_GAP. Режим выбран ЗАМЕРОМ: категории OST_StairsLandings нет
        # в таблице извлечения, а строка `StairsLanding` не встречается ни в
        # одном файле `decompile/` (grep 10.08). Значит чинить надо ЗАХВАТ, а
        # не лифтер: `_lift_stairs` поднимает лестницу по её маршу и о
        # компонентах-площадках не знает вовсе, поэтому каждая площадка
        # разобранного здания теряется молча. Переснято прогоном на ЭТОМ
        # дереве, а не сложено с числом чужой ветки.
        self.assertEqual(len(REVERSE_CONTRACTS), 64)
        # 23 -> 24 (03.08.2026): create_railing переведён из capture_gap в
        # direct. Захват путей ограждений едет с 29.07, и k2_ar_rd_v9 несёт
        # 31 строку захвата — прежняя формулировка «L0 has neither a railing
        # path nor …» перестала быть правдой. Число здесь и есть тот замок,
        # который не даёт манифесту протухнуть молча.
        # 25 -> 26 (09.08.2026): +create_conduit. Лифтер написан той же
        # волной, что и оп: строка L0 короба неотличима по форме от лотка
        # (линейный MEPCurve, те же концы, тот же уровень, тот же тип), и
        # объявить DIRECT здесь можно ровно потому, что подъём существует.
        self.assertEqual(
            sum(contract.direct_same_op_lift
                for contract in REVERSE_CONTRACTS.values()),
            26,
        )
        with self.assertRaises(TypeError):
            REVERSE_CONTRACTS["delete"] = REVERSE_CONTRACTS["create_wall"]  # type: ignore[index]

    def test_every_category_candidate_is_direct_or_an_explicit_capture_gap(self):
        for category, candidate in lift._CANDIDATES.items():
            with self.subTest(category=category, op=candidate.op):
                contract = REVERSE_CONTRACTS[candidate.op]
                self.assertIn(
                    contract.mode,
                    (ReverseMode.DIRECT, ReverseMode.CAPTURE_GAP),
                )
                if contract.mode is ReverseMode.DIRECT:
                    self.assertIn(candidate.lifter_name, contract.entrypoints)

    def test_every_declared_direct_entrypoint_exists_and_names_the_emitted_op(self):
        for op_name, contract in REVERSE_CONTRACTS.items():
            if contract.mode is not ReverseMode.DIRECT:
                continue
            for entrypoint in contract.entrypoints:
                with self.subTest(op=op_name, entrypoint=entrypoint):
                    function = getattr(lift, entrypoint)
                    tree = ast.parse(textwrap.dedent(inspect.getsource(function)))
                    string_literals = {
                        node.value
                        for node in ast.walk(tree)
                        if isinstance(node, ast.Constant)
                        and isinstance(node.value, str)
                    }
                    self.assertIn(op_name, string_literals)

    def test_l1_emission_guard_refuses_non_direct_operations(self):
        self.assertEqual(assert_lift_emission("create_wall").op_name,
                         "create_wall")
        # create_railing уехал отсюда 03.08 вместе с подключением захвата;
        # на его месте — create_dimension, последний оставшийся capture_gap
        # (вида-владельца и Dimension.References чтение не снимает).
        for op_name in ("create_dimension", "delete", "load_family"):
            with self.subTest(op=op_name), self.assertRaises(
                    ReverseContractError):
                assert_lift_emission(op_name)

    def test_composed_group_emission_has_a_checked_entrypoint(self):
        """Сторожит ГРАММАТИКУ составного контракта, а НЕ достижимость.

        СНЯТА СВЕРКА СТРОКИ ИМЕНИ (11.08.2026). Здесь стояло

            self.assertEqual(contract.entrypoints,
                             ("component_to_group_program",))

        и это подтверждало НАПИСАНИЕ имени, а не существование того, что имя
        называет. Замер того же дня: у `component_to_group_program` НОЛЬ
        не-тестовых ссылок, её вход `place_group_ops` не зовёт никто вообще
        (даже тесты), сама она возвращает None при выключенном
        `native_group`, а `tests/test_capability_map_wiring.py` отдельно
        утверждает, что этот гейт мёртв. То есть строка совпадала, а выхода
        не было — величина утверждалась в одном месте и не читалась нигде.

        ЧЕМ ЗАМЕНЕНО, чтобы никто не восстановил её как «пропавшую
        проверку»: `kukai/ir/tests/test_reverse_entrypoints_exist.py` сверяет
        ДОСТИЖИМОСТЬ каждой объявленной точки входа (вызов, имя как значение
        или строка таблицы диспетчеризации — но НЕ собственный `__all__` и не
        сам текст контракта) и держит журнал точек входа, названных авансом,
        который падает С ОБЕИХ сторон: и когда авансовая точка стала
        достижимой, и когда появилась недостижимая без записи.

        Здесь остаётся то, что этому файлу и принадлежит: составной контракт
        ОБЯЗАН называть точку входа, и она обязана существовать как атрибут
        модуля; а оп, не объявленный составным, обязан отказать.
        """
        contract = assert_composed_emission("create_group")
        self.assertTrue(contract.entrypoints,
                        "составной контракт обязан называть точку входа")
        for entry in contract.entrypoints:
            with self.subTest(entrypoint=entry):
                self.assertTrue(callable(getattr(materialize, entry, None)),
                                "%s: точка входа не существует как атрибут "
                                "materialize" % entry)
        for op_name in ("create_wall", "delete", "load_family"):
            with self.subTest(op=op_name), self.assertRaises(
                    ReverseContractError):
                assert_composed_emission(op_name)

    def test_report_is_stable_json_and_exposes_honest_modes(self):
        report = reverse_contract_report()
        self.assertEqual(report["schema"], REVERSE_CONTRACT_SCHEMA)
        # 37 -> 38 (09.08.2026): create_wall_foundation, режим capture_gap.
        # 38 -> 43 (09.08.2026): пять операций волны ЭОМ; direct вырос ровно
        # на одну (create_conduit), остальные четыре — capture_gap.
        # 43 -> 44 (09.08.2026): create_angular_dimension, режим capture_gap;
        # direct не растёт — подъёма у него нет.
        # 44 -> 46 (09.08.2026): create_beam_system и create_truss, обе
        # capture_gap; direct не растёт — подъёма ни у одной из них нет.
        # 46 -> 50 (09.08.2026): волна нагрузок и пути эвакуации, все четыре
        # capture_gap. ПЕРЕСНЯТО `reverse_contract_report()` на слитом дереве:
        # обе волны считали от 44 порознь, и ни одна их цифра не верна.
        # 50 -> 53 (09.08.2026): три операции площадки, все CAPTURE_GAP;
        # direct не растёт. ТРИ волны назвали здесь 50, 46 и 40 — переснято
        # `reverse_contract_report()` на слитом дереве.
        # 53 -> 55 (09.08.2026): create_wall_sweep и create_slab_edge, обе
        # CAPTURE_GAP; direct не растёт — подъёма ни у одной из них нет, и у
        # стенного профиля его не будет НИКОГДА в полном виде: положение
        # профиля Autodesk документирует как свойство ТИПА, а не вызова,
        # поэтому даже полный захват вернул бы только хозяина, тип и
        # ориентацию. ПЕРЕСНЯТО `reverse_contract_report()` на этом дереве.
        # 44 -> 47 (09.08.2026): волна датумов. direct НЕ вырос ни на
        # одну: цепь осей объявлена DECOMPOSED (звенья поднимаются
        # как create_grid, теряется только принадлежность цепи), а
        # выдавленная кровля и многоэтажная лестница — CAPTURE_GAP
        # по ЗАМЕРУ: EXTRUSION_START/END и ReferencePlane не
        # встречаются в decompile/ ни разу, MultistoryStairs — ни
        # разу во всём пакете.
        # 58 -> 60 (09.08.2026): волна тел, оба опа CAPTURE_GAP; direct не
        # растёт — подъёма у них нет. ПЕРЕСНЯТО `reverse_contract_report()`
        # на сведённом дереве, а не сложено ни с одной из веток.
        # 60 -> 61 (09.08.2026): create_filled_region, режим capture_gap;
        # direct не растёт — подъёма у заливки нет и не будет, пока
        # извлечение не начнёт читать И границу, И базис вида.
        # 61 -> 62 (10.08.2026): армирование по области, режим capture_gap;
        # direct не растёт — подъёма у армирования нет и не будет, пока
        # извлечение не откроет категорию OST_AreaRein вообще.
        # 61 -> 62 (10.08.2026): create_face_wall, режим capture_gap;
        # direct не растёт — подъёма у стены по грани нет и не будет, пока
        # извлечение не начнёт читать И носителя, И нормаль родительской грани.
        # 63 -> 64 (10.08.2026): волна лестниц — create_stairs_landing,
        # CAPTURE_GAP. Режим выбран ЗАМЕРОМ: категории OST_StairsLandings нет
        # в таблице извлечения, а строка `StairsLanding` не встречается ни в
        # одном файле `decompile/` (grep 10.08). Значит чинить надо ЗАХВАТ, а
        # не лифтер: `_lift_stairs` поднимает лестницу по её маршу и о
        # компонентах-площадках не знает вовсе, поэтому каждая площадка
        # разобранного здания теряется молча. Переснято прогоном на ЭТОМ
        # дереве, а не сложено с числом чужой ветки.
        self.assertEqual(report["write_ops"], 64)
        self.assertEqual(report["direct_same_op_lifts"], 26)
        self.assertEqual(
            report["modes"],
            {
                "direct": 26,
                # 1 -> 2: create_opening объявлен capture_gap честно — L0 1.0
                # не несёт ни Opening.Host, ни границы проёма, и DIRECT здесь
                # обещал бы подъём, которого нет.
                # 2 -> 3 (09.08): create_wall_foundation — та же честность и
                # ровно та же причина: связи фундамента со стеной в L0 нет.
                # 3 -> 7 (09.08): волна ЭОМ. Заготовки (нет бита
                # IsPlaceholder в L0 — сегодня они поднимаются как обычные
                # труба/воздуховод, то есть круг пересобирает НЕ заготовку) и
                # гибкие участки (в L0 пара концов, а форма живёт в Points).
                # 7 -> 8 (09.08): create_angular_dimension, по той же
                # честности.
                # 8 -> 10 (09.08): волна каркаса — балочная система и ферма.
                # 10 -> 14 (09.08): волна нагрузок и пути эвакуации. L0 не
                # читает ни точечной/линейной/площадной нагрузки, ни линии
                # пути эвакуации — ни одной из четырёх категорий нет в таблице
                # извлечения вовсе, так что разрыв тут на весь оп, а не на
                # отдельное поле.
                # 14 -> 17 (09.08): три операции площадки. Их разрыв ГЛУБЖЕ
                # проёмного: у проёма строка L0 хотя бы читается, а site-
                # категории извлечение не открывает вообще, поэтому «стадия
                # не говорила» тут даже не наступает — стадии нет.
                # 17 -> 19 (09.08): create_wall_sweep и create_slab_edge.
                # 19 -> 21 (09.08, СЛИЯНИЕ): выдавленная кровля и
                # многоэтажная лестница из волны датумов. Объединение текста
                # оставило здесь ДВА ключа `capture_gap` и два `decomposed`
                # подряд — питон молча берёт последний, поэтому падало не то,
                # что разошлось. Ключи сведены, числа переснЯты прогоном:
                # 26 + 21 + 4 + 1 + 4 + 1 + 1 = 58 пишущих операций.
                # 21 -> 23 (09.08, СЛИЯНИЕ ВОЛНЫ ТЕЛ): выдавливание и
                # вращение. И ЗДЕСЬ ОПЯТЬ ОДИН СЛОВАРЬ И ДВА КЛЮЧА: волна тел
                # писала `capture_gap: 10` и `decomposed: 3` против своей
                # базы, объединение текста положило бы их РЯДОМ с 21 и 4 в
                # одном литерале, и питон молча оставил бы последний — то
                # есть набор падал бы не на том, что разошлось. Ключи сведены
                # по ОДНОМУ, числа переснЯты прогоном на этом дереве.
                # 23 -> 24 (09.08, СЛИЯНИЕ): заливка. Её разрыв ближе к проёмному, чем
                # к площадочному, но с собственной второй половиной: границу
                # прочитать МОЖНО (`GetBoundaries()` есть 6/6), а вот перевести
                # её в оси вида-владельца L0 сегодня нечем.
                # ТРЕТИЙ РАЗ ОДИН СЛОВАРЬ И ДВА КЛЮЧА: волна писала
                # `capture_gap: 18` / `decomposed: 3` против своей базы.
                # Ключи сведены по ОДНОМУ, числа переснЯты прогоном.
                # 24 -> 23 + lifter_gap 1 (09.08, СЛИЯНИЕ с волной захвата
                # хозяина): `create_wall_foundation` УШЁЛ из пробелов захвата,
                # потому что `WallFoundation.WallId` теперь читается (6/6) —
                # «захват не умеет» стало бы ложью. Сумма не изменилась,
                # изменился АДРЕС работы: не читать научить, а лифтер написать.
                # 23 -> 24 (10.08): create_area_reinforcement. Разрыв тут
                # ГЛУБЖЕ проёмного и одного рода с площадочным: категории
                # OST_AreaRein извлечение не открывает вовсе, значит «стадия
                # промолчала» здесь даже не наступает — стадии нет.
                # 24 -> 25 (10.08, СЛИЯНИЕ волны масс):
                # create_face_wall — стена по грани массы. Тот же
                # род разрыва: категории массы извлечение не
                # открывает, значит «стадия промолчала» здесь даже
                # не наступает — стадии нет.
                # 25 -> 26 (10.08, волна лестниц): create_stairs_landing.
                # Тот же род разрыва, что у армирования и стены по грани:
                # категории OST_StairsLandings извлечение не открывает вовсе,
                # значит «стадия промолчала» здесь даже не наступает — стадии
                # нет. И у площадки этот пробел стоит дороже, чем кажется:
                # марш-то читается, поэтому разобранное здание выглядит
                # ПОЛНЫМ, потеряв каждую промежуточную площадку.
                "capture_gap": 26,
                "lifter_gap": 1,
                "decomposed": 4,
                "composed": 1,
                "state_transition": 4,
                "pinned_existing": 1,
                "external_source": 1,
            },
        )
        self.assertEqual(
            [row["op"] for row in report["contracts"]],
            sorted(REVERSE_CONTRACTS),
        )
        self.assertEqual(
            json.dumps(report, ensure_ascii=False, sort_keys=True),
            json.dumps(reverse_contract_report(), ensure_ascii=False,
                       sort_keys=True),
        )
        self.assertEqual(
            Counter(row["mode"] for row in report["contracts"]),
            Counter(report["modes"]),
        )


if __name__ == "__main__":
    unittest.main()
