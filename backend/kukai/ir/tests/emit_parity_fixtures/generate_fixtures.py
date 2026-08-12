"""Emit-parity fixture generator (wave A2, byte-guarantee mechanism).

Run ONCE against the PRE-refactor emitter (base prod-live 4e5cf13d) to freeze
the "old bytes" of the whole emission corpus; `test_emit_model_byte_parity`
then recomputes every emission against the frozen hashes after each migration
step.  ANY divergence fails the wave — "update the golden" is forbidden here.

Corpus (maximal EMITTER coverage, not just the gate):
  * test_golden.PROGRAMS               — every reviewed golden program;
  * test_emitter_scope_contract.PROGRAMS — the per-family corner fixtures that
    deliberately exercise every optional branch of all 26 emitters;
  * the gate runner's authoring programs (auth_wall/auth_mixed/auth_stack/
    auth_grid_array/auth_stairs/auth_native_group/mod_setparam_delete shapes),
    reassembled from the same committed sources;
  * seeded query PBT programs (test_pbt.gen_program, gate SEED) + all-kinds +
    query_types pools (query family: unaffected by the post refactor, kept as
    cheap insurance);
  * test_emission_guard_contract.PROGRAMS — the guard-site corpus (2026-07-28):
    line-tracing every emitter showed the corpus above never reached 11 of the
    105 op-local guard-sites, so a change inside one of them moved no frozen
    byte at all.  These programs close that hole (105/105 reached).

Modes: atomic AND per_op isolation for every write program (per_op rewrites
post gating — both paths must stay byte-identical), x all 6 Revit versions
(respecting each fixture's __min_ver__).

DECISION (документировано): fixtures are SHA-256 HASHES, not full files —
~1500 emissions x 10-30KB would be tens of MB of noise; hashes give the same
guarantee.  For debugging a mismatch, run this script with --dump DIR to write
the CURRENT emissions as files and diff against a pre-change --dump.

Determinism: seeded PRNG only, sorted keys, no clocks.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import random
import sys
import tempfile

os.environ.setdefault("KIR_REJECTIONS_PATH",
                      os.path.join(tempfile.gettempdir(), "kir_parity_queue.jsonl"))

from kukai.ir import ground as ground_mod  # noqa: E402
from kukai.ir import spec  # noqa: E402
from kukai.ir.authoring import emit_program  # noqa: E402
from kukai.ir.compiler import _parse_and_check, compile_program  # noqa: E402
from kukai.ir.tests.fixtures import GROUND_SNAPSHOT  # noqa: E402
from kukai.ir.tests.test_emission_guard_contract import (  # noqa: E402
    PROGRAMS as GUARD_PROGRAMS,
)
from kukai.ir.tests.test_emitter_scope_contract import (  # noqa: E402
    PROGRAMS as SCOPE_PROGRAMS,
)
from kukai.ir.tests.test_golden import PROGRAMS as GOLDEN_PROGRAMS  # noqa: E402
from kukai.ir.tests.test_pbt import gen_program  # noqa: E402

VERSIONS = ("2021", "2022", "2023", "2024", "2025", "2026")
GATE_SEED = 62026
N_PBT = 25

FIXTURE_PATH = pathlib.Path(__file__).parent / "corpus_hashes.json"

# key-prefix -> rationale.  The ONLY sanctioned byte changes of wave A2; each
# must be pinned by its OWN golden/test.  Shared by the pytest wrapper and the
# standalone --check.
INTENDED_CHANGES: dict[str, str] = {
    # ── Подрезка участка под врезку отвода — законная (30.07) ──────────────
    # ЖИВОЙ ЗАМЕР на образце Snowdon Towers Sample Plumbing (Revit 2026).
    # Свидетель CONNECT требовал «конец участка == заказанный узел ±5 мм» на
    # ОБОИХ концах и на связной системе не мог выполниться никогда: Revit
    # ставит в узле отвод и подрезает соседние участки под его грань.
    # Различающий опыт снял вопрос: система из ОДНОГО участка проходила
    # (id 1738981, one_system=true), из двух — нарушены оба конца стыка, из
    # трёх — все три. Топология (BFS по коннекторам) проходила ВЕЗДЕ, то есть
    # система собиралась связной, а сверка объявляла её неверной. Это и есть
    # причина, по которой три сетевых операции за всю историю не построили
    # ничего.
    #
    # Проверка переехала из КОРОБКИ вокруг узла в ОСИ УЧАСТКА: t — сколько
    # ушло вдоль, d — сколько сошло с оси. Свободный конец (узел степени 1)
    # держит прежние ±5 мм; стыкованный вправе отступить внутрь, но не дальше
    # половины и не сходя с прямой. Послабление даётся ровно по одной степени
    # свободы; уход с оси и перелёт наружу по-прежнему нарушение.
    #
    # Прямая труба и прямой воздуховод — это система из одного участка, они
    # ходят через тот же свидетель, поэтому их байты тоже сдвинулись при
    # НЕИЗМЕННОЙ семантике (оба конца свободны -> те же ±5 мм, просто круглый
    # допуск вместо кубического).
    # Замена пина: kukai/ir/tests/test_system_segment_trim.py — границы
    # допуска и то, что эмиссия РАЗЛИЧАЕТ роды концов.
    # Вторая правка ТОГО ЖЕ дня в тех же программах: отказ по диаметру
    # разведён на два случая. Прежде «__dp == null || значение разошлось» был
    # одним условием, и прямоугольный воздуховод получал «diameter mismatch»
    # — модель пошла бы подбирать число вместо того, чтобы понять, что у
    # прямоугольного сечения диаметра НЕ БЫВАЕТ. Формы сечения нет в пуле
    # заземления, отказать на компиляции нечем, поэтому разведены ветви в
    # исполнении. Замена пина: kukai/ir/tests/test_duct_diameter_shape.py.
    "guard:duct_straight": "подрезка под отвод + диагноз отсутствующего диаметра",
    "guard:pipe_straight_reducer": "подрезка под отвод: проверка в осях участка",
    "guard:pipe_straight_same_diameter": "подрезка под отвод: проверка в осях участка",
    # ── Витражная ячейка: реген перед сеткой + улика вместо пустоты (28.07) ─
    # ЖИВЫЕ ПРОБЫ на фасаде SOB6.2 (Revit 2023), два замера подряд:
    #   П1 — витражная стена ОДНА, в точных координатах упавшего чанка:
    #        ok, свидетель 3/3, концы совпали. Стена не виновата;
    #   П4 — та же стена + `set_curtain_panel` в ОДНОЙ транзакции:
    #        KIR-X003 и отказ ровно из четырёх слов: «ChangePanelType: ».
    #        Revit бросил с ПУСТЫМ Message.
    # Две правки, обе структурные:
    #   1. `doc.Regenerate()` перед всякой работой с сеткой: панели и линии
    #      разрезки рождаются регенерацией, а не вызовом Wall.Create — тот же
    #      класс, что «коннекторы читаются только после регена» (CONNECT) и
    #      `Activate()+Regenerate()` в _symbol_res. Реген НЕ обёрнут в catch:
    #      по документации сборок провал регенерации означает испорченный
    #      документ, и владелец транзакции обязан оборвать её, а не молчать;
    #   2. отказ ChangePanelType называет себя: класс исключения, внутреннее
    #      исключение, классы панели и нового типа (GetPanelIds по той же
    #      документации отдаёт и Panel, и Wall), id носителя, адрес ячейки и
    #      признак разблокированности (GetUnlockedPanelIds существует ровно
    #      потому, что запертую панель менять нельзя).
    # Ни одной проверки не добавлено и не убрано; свидетели те же. Замена
    # пина: kukai/ir/tests/test_curtain_panel_op.py —
    # TheGridIsRegeneratedBeforeItIsRead + TheFailureNamesItself.
    #   3. ОТПИРАНИЕ ячейки перед сменой типа. Пробы П6 (готовый носитель)
    #      и П7 (PanelType вместо WallType) вернули ОДНО И ТО ЖЕ:
    #      «InvalidOperationException: (пустое сообщение Revit) …
    #      РАЗБЛОКИРОВАНА=НЕТ». П6 сняла транзакцию, П7 — вид типа; остался
    #      замок. Панель, порождённая типом носителя, у Revit «type-driven»
    #      (BuiltInFailures.CurtainWallFailures.
    #      TypePanelsFronNonRectCellsUnlocked: «Type-driven panels … were
    #      UNLOCKED and left unchanged»). Отпирается Element.Pinned — у
    #      Panel сеттера замка нет, Lock живёт у Mullion. Обратно панель не
    #      запирается: 53 поднятые ячейки фасада заменённые, значит в
    #      оригинале их отперли руками. Замена пина:
    #      TheTypeDrivenPanelIsUnlockedFirst.
    #   4. ЗАМЕНА ЭЛЕМЕНТА. Проба П8 (после отпирания): исключение ушло,
    #      вызов исполнился, а свидетель поймал «тип панели в ячейке не
    #      равен запрошенному» — читалась СТАРАЯ ячейка. По документации
    #      сборок ChangePanelType возвращает «the modified panel element»;
    #      для типа СТЕНЫ это НОВЫЙ элемент. Свидетель теперь берёт
    #      занявшего: возвращённый элемент, если он состоит в списке панелей
    #      этой сетки, иначе — перечитанный по адресу; тип читается из
    #      модели после Regenerate, а не с возврата. В квитанции — оба id.
    #      Замена пина: ChangingTheTypeReplacesTheElement.
    #   5. ДОГОН ТИПА и ПРОСТРАНСТВЕННАЯ ПРИВЯЗКА. Прямые эксперименты
    #      E1-E4 на живом носителе: (E1) ChangePanelType с типом СТЕНЫ
    #      строит стену ЧУЖОГО типа — типа разрезки носителя, — молча, без
    #      исключения; (E3) лечится `ret.ChangeTypeId(тип)`, чей возврат -1
    #      (InvalidElementId) есть обычный успех, а не отказ — документация
    #      сборок описывает ровно этот случай как ЕДИНСТВЕННЫЙ, где смена
    #      типа порождает новый элемент; (E2) стена-занявший НИКОГДА не
    #      появляется в GetPanelIds — ни после Regenerate, ни после Commit,
    #      — поэтому проверка членством для неё ложно-отрицательна всегда и
    #      заменена привязкой к оси носителя (замер дал 0.0 мм, допуск 50 мм
    #      на дуги). Замена пина: TheRequestedTypeIsChasedNotAssumed +
    #      AWallOccupantIsBoundBySpaceNotByTheGridList.
    "scope:curtain_cell|":
        "витражная ветка: Regenerate перед чтением сетки, отпирание "
        "type-driven ячейки, говорящий отказ ChangePanelType, занявший "
        "ячейку как операнд свидетеля, догон типа через ChangeTypeId и "
        "привязка стены-занявшего к оси носителя "
        "(живые пробы П1/П4/П6/П7/П8 и эксперименты E1-E4, 28.07)",
    # ── Хост вынесен в область объявлений (28.07) ──────────────────────────
    # `__pfh_` объявлялся через `var` ВНУТРИ блока операции, а свидетель хоста
    # читает его уже ПОСЛЕ закрытия этого блока. В атомарной обёртке шов не
    # виден, в per-op — виден: живая пересборка ЭОМ (9344 опа) упала на
    # `CS0103: The name '__pfh_e1278883' does not exist in the current
    # context`, ни один элемент не создан.
    #
    # Правка ровно одна и структурная: объявление переехало туда, где всегда
    # жил `__el_`, а внутри блока осталось присваивание. Ни одной проверки не
    # добавлено и не убрано; изменение затронуло 12 эмиссий — этот golden на
    # шести версиях × две изоляции, и больше ничего.
    "golden:place_family_point_and_curve|":
        "объявление хоста `__pfh_` поднято в область объявлений: свидетель "
        "хоста живёт за пределами per-op блока (CS0103 на живом ЭОМ)",
    # ── Диаметр сегмента получил СВОЙ ключ свидетеля (27.07) ───────────────
    # `_network_obligations` принимал `diameter_bip` и НЕ ИСПОЛЬЗОВАЛ его ни
    # разу: сертификат не знал про проверку диаметра, хотя эмиттер её ставил.
    # Значит удаление проверки из эмиттера оставляло сертификат «доказанным»
    # — ровно та дыра, ради закрытия которой сертификат заведён.
    #
    # Причина глубже отсутствующей строки: свидетели концов и диаметра ехали
    # ПОД ОДНИМ ключом «endpoints», а обязательства разряжаются по ключу.
    # Обязательство, разряжаемое чужим ключом, неотличимо от отсутствующего.
    #
    # Байты сдвинулись только позицией: формально проверено, что множество
    # строк эмиссии ДО и ПОСЛЕ совпадает (8 и 4 строки переставлены, ноль
    # добавлено, ноль удалено). Допуск, сообщения и BuiltInParameter те же.
    # Обоснование этих двух ключей сведено ниже с более ранним изменением
    # CONNECT. Два объявления одного ключа опасны: Python молча оставляет
    # последнее и теряет одну из причин разрешённого изменения golden.
    # ── Схема ключей по видам: пачки по 20 → одна запись на вид (27.07) ─────
    # `query:all_kinds_NN` нумеровались смещением в списке всех видов, поэтому
    # добавление ЛЮБОГО вида пересобирало состав пачек и «расхаживало» байты у
    # видов, которых правка не касалась. Живой случай: таблица выросла 21 → 51
    # (разделы КР/ОВ/ВК/ЭОМ, которых в ней почти не было), эмиттер не изменился
    # ни на байт — а храповик показал 12 расхождений. Ключ по ИМЕНИ вида
    # (`query:kind_<name>`) делает рост таблицы строго аддитивным.
    #
    # Что эмиссия НЕ менялась — проверено отдельно и предметно: те же 25
    # PBT-программ, порождённые прежним набором из 21 вида, дали на новом коде
    # 150 совпадений байт-в-байт и 0 расхождений.
    #
    # Храповик, щёлкающий на изменение соседней таблицы, а не эмиссии, учит
    # штамповать этот самый список не глядя — и перестаёт ловить то, ради чего
    # заведён. Это единственная причина трогать схему.
    "query:all_kinds_":
        "снятая схема ключей: пачки по 20 видов заменены записью на вид "
        "(query:kind_<name>), рост таблицы видов теперь аддитивен; эмиссия "
        "не менялась — 150/150 байт-в-байт на прежних PBT-программах",
    "gate:auth_native_group|":
        "create_group member-POSTs added by design (A2, pinned by the "
        "native_group golden)",
    "scope:native_group|":
        "same deliberate member-POSTs, scope-contract fixture of the same op",
    "golden:full_house_v1|":
        "place_family Z-фикс 2026-07-21: NewFamilyInstance трактует z точки "
        "как офсет над уровнем — эмитим z−Elevation (старые байты = живой "
        "double-count по z); pinned by full_house_v1 golden + "
        "PlaceFamilyLevelRelativeZ in test_authoring",
    "scope:full_house|":
        "same place_family Z-фикс, scope-contract fixture of the same corpus",
    # ── F5 v4 (2026-07-27): зеркала на hosted БОЛЬШЕ НЕТ ────────────────────
    # Гибрид v3.1 держал mirror-COPY как fallback при CanFlip*=false. Живой
    # замер на SOB6.2 (R2023, 178 опов окрестности, три прогона на своих
    # полосах — artifacts/mirror_cause*.json) показал, чего он стоил: с
    # зеркалом три опа отказывают «зеркальная копия недоступна», И ПРИ ЭТОМ
    # геометрию теряют ТРИ ДРУГИЕ двери на другом хосте — оказываются в точке
    # [0,0] вообще без тела. Без флипов везде: 0 отказов, 0 нарушений, 0
    # поломок. Без флипов только у трёх отказавших: поломка переезжает на
    # четвёртый оп. Значит MirrorElements(mirrorCopies=true) на hosted-
    # экземпляре портит документ ЗА ПРЕДЕЛАМИ своего опа, и per-op
    # SubTransaction этого не удерживает.
    #
    # Вместе с механизмом сняты его ограничитель (__kirLockedMirror_*, порог
    # _A5_LOCKED_MIRRORS_PER_HOST, текст про cap): код, охраняющий
    # несуществующее, читается как охрана существующего. Недостигнутый флип
    # теперь НАЗЫВАЕТ причину — вердикт дочитывает CanFlip* у живого элемента.
    "golden:hosted_door_flips|":
        "F5 v4 2026-07-27: снята ветка mirror-COPY у hosted (живой замер: "
        "рушила ЧУЖИЕ двери), вердикты флипов дочитывают CanFlip* и называют "
        "причину; pinned by hosted_door_flips golden + "
        "F5EmitFlips.test_flip_locked_door_never_mirrors и LiftEmitRoundTrip "
        "в test_hosted_flips_wall_vertical",
    "scope:hosted_flips_wall_vertical|":
        "same F5 v4 изменение, scope-contract fixture of the same corpus",
    # ── CONNECT: система выводится Revit на коммите, а не строится нами ──────
    # Замерено 27.07 на живом Revit 2023 (connect.py §A): Pipe.Create с
    # systemTypeId УЖЕ кладёт оба коннектора в автосозданную систему
    # (MEPSystem=«Канализация 1» при IsConnected=false), поэтому
    # doc.Create.NewPipingSystem/NewMechanicalSystem отвечал «Some of the
    # input connectors have been used» и ВСЕ ЧЕТЫРЕ графовых опа не строили
    # ничего ни разу. При этом после Commit Revit сливает системы сам (две
    # трубы через ConnectTo вернулись обе с #21201856). Старые байты
    # закрепляли неработающую конструкцию: вызов фабрики удалён, проверка
    # «одна система» переехала из внутритранзакционного постусловия в
    # пост-коммитный свидетель (mep_system_ids/one_system), а гарантией
    # внутри транзакции осталась связность (BFS по живому графу коннекторов).
    "golden:route_pipe_system_riser_branch|":
        "CONNECT: удалён NewPipingSystem, добавлен пост-коммитный readback; "
        "pinned by route_pipe_system_riser_branch golden + "
        "SystemMembershipMEP в test_mep. Сертификат: диаметр вынесен в свой "
        "свидетель (ключ diameter) сразу за концами; множество строк эмиссии "
        "не изменилось, только порядок",
    "golden:route_duct_system_tee|":
        "то же для ОВ (NewMechanicalSystem); pinned by route_duct_system_tee "
        "golden + SystemMembershipMEP в test_mep. Сертификат: то же "
        "вынесение диаметра в собственный ключ свидетеля",
    "scope:pipe_system|":
        "то же изменение у create_pipe_system; pinned by "
        "SystemMembershipIsDerivedNotForced в test_connect",
    "scope:route_pipe|":
        "то же изменение, scope-contract fixture route_pipe_system",
    "scope:route_duct|":
        "то же изменение, scope-contract fixture route_duct_system",
    # ── лестница больше не оставляет Revit с модальным окном ─────────────────
    # Наблюдалось живьём 27.07: create_stairs построил лестницу, и мост умер
    # на ШЕСТИ следующих вызовах подряд («Execution was cancelled before Revit
    # started it») — у пользователя это «КУКИ завис после лестницы», навсегда.
    # Причина офлайн-воспроизводима: это единственный оп со своим шаблоном
    # программы, и в нём не было ни SetFailuresPreprocessor, ни
    # SetForcedModalHandling(false), ни удаления предупреждений — всего того,
    # что emit_program ставит каждой обычной программе. Старые байты
    # закрепляли зависание.
    "gate:auth_stairs|":
        "лестничная транзакция получила обработчик отказов + подавление "
        "модальности, а её обработчик на StairsEditScope.Commit теперь тоже "
        "снимает предупреждения; pinned by StairsMustNotLeaveAModalDialog "
        "в test_hangs_and_lies",
    # ── beam_types больше не отдаёт то, чем оп не может воспользоваться ──────
    # Замерено 27.07: все 36 семейств каркаса реального здания —
    # FamilyPlacementType.OneLevelBased, а create_beam эмитит
    # NewFamilyInstance(Line, …), который на точечном семействе возвращает
    # null. Факт известен на ground ⇒ там и должен давать честное KIR-G104
    # «пусто в модели» вместо рантайм-null.
    "query:types_all_pools|":
        "коллектор beam_types фильтрует по FamilyPlacementType "
        "(CurveDrivenStructural/CurveBased); pinned by "
        "BeamPoolMustNotOfferPointPlacedFamilies в test_hangs_and_lies",
    # ── два дефекта свидетеля уровня, оба замерены живой пробой 27.07 ───────
    # (а) Переход по BIP-цепочке проверял `HasValue`, а он истинен и для
    #     InvalidElementId: у балки FAMILY_LEVEL_PARAM = HasValue:True /
    #     AsElementId:-1. Цепочка обрывалась на ПУСТОМ звене и сравнивала «-1»
    #     с ожидаемым id, обвиняя правильный элемент. Переход теперь требует
    #     настоящий ElementId — это меняет эмиссию всем опам, чей свидетель
    #     идёт по цепочке.
    # (б) У балки требовать равенства уровня было НЕЛЬЗЯ вовсе: Revit ВЫВОДИТ
    #     опорный уровень из отметки кривой. Передан L_01 @ 0 мм, кривая на
    #     Z=3000 -> привязка ушла к L_01ДОО1_+2.500. Постусловие требовало
    #     того, чего API не обещает. Заменено на настоящий инвариант «опорный
    #     уровень существует» + чтение полученного уровня в свидетель; сама
    #     балка пришпилена обоими концами в 3D с допуском 5 мм.
    "golden:struct_beam|":
        "свидетель уровня балки: равенство заменено на существование + чтение "
        "reference_level в результат; pinned by "
        "BeamLevelWitnessMustReadTheParameterABeamActuallyHas (test_hangs_and_lies) "
        "и BeamCommitGateInvariants (test_struct)",
    "golden:struct_foundation_isolated|":
        "переход цепочки требует настоящий ElementId (дефект «а»)",
    "golden:struct_foundation_slab|":
        "то же (дефект «а»)",
    "scope:struct|":
        "то же, scope-contract fixture структурных опов",
    "scope:contour|":
        "то же, scope-contract fixture create_floor_by_contour",
    "scope:floor_holes|":
        "то же, scope-contract fixture create_floor с отверстиями",
    # ── откат обязан назвать причину (общий футер всех авторинг-программ) ────
    # Сборка здания целиком умерла на «transaction commit status: RolledBack»
    # и больше не сказала НИЧЕГО. Revit откатывает так, встретив отказ уровня
    # ERROR: __KirMainFailures снимал предупреждения и намеренно не гасил
    # ошибку — но и не запоминал её, поэтому причина терялась. Живая проба
    # 27.07 показала, что текст доступен через FailuresAccessor
    # (GetSeverity + GetDescriptionText). Молчащий откат — тот самый немой
    # исход, который этот компилятор запрещает, поэтому прибор ставится в
    # ОБЩИЙ футер: разделять политику отказов на две — хуже, чем один раз
    # перевыпустить корпус. Расходятся все авторинг-программы, по три места:
    # Seen.Clear() перед операциями, сбор ошибок, текст в отказе.
    "gate:auth_grid_array|":
        "общий футер: откат называет причину; pinned by RollbackMustNameItsCause в test_hangs_and_lies",
    "gate:auth_mixed|":
        "общий футер: откат называет причину; pinned by RollbackMustNameItsCause в test_hangs_and_lies",
    "gate:auth_stack|":
        "общий футер: откат называет причину; pinned by RollbackMustNameItsCause в test_hangs_and_lies",
    "gate:auth_wall|":
        "общий футер: откат называет причину; pinned by RollbackMustNameItsCause в test_hangs_and_lies",
    "gate:mod_setparam_delete|":
        "общий футер: откат называет причину; pinned by RollbackMustNameItsCause в test_hangs_and_lies",
    "golden:authoring_wall_arc|":
        "общий футер: откат называет причину; pinned by RollbackMustNameItsCause в test_hangs_and_lies",
    "golden:authoring_wall_pipe_grid|":
        "общий футер: откат называет причину; pinned by RollbackMustNameItsCause в test_hangs_and_lies",
    "golden:modify_setparam_delete|":
        "общий футер: откат называет причину; pinned by RollbackMustNameItsCause в test_hangs_and_lies",
    "golden:stack_two_storeys|":
        "общий футер: откат называет причину; pinned by RollbackMustNameItsCause в test_hangs_and_lies",
    "golden:wall_base_offset|":
        "общий футер: откат называет причину; pinned by RollbackMustNameItsCause в test_hangs_and_lies",
    "golden:wall_top_attached|":
        "общий футер: откат называет причину; pinned by RollbackMustNameItsCause в test_hangs_and_lies",
    # ── create_dimension: геометрические ссылки вместо ссылок на элемент (28.07) ─
    # Живая проба П11 (E5, FAS_R23, Revit 2023): «NewDimension: The
    # references are not geometric references» — ReferenceArray принимает
    # только геометрические ссылки (грань/ребро), а старая эмиссия клала
    # `new Reference(элемент)`. Ворота этого не ловили (компилировалось 6/6),
    # ловил только живой Revit. Правка (обе структурные):
    #   1. на ref: Wall -> HostObjectUtils.GetSideFaces(Exterior)[0]; иначе
    #      (или носитель не отдал грань) -> общий фолбэк, геометрия с
    #      Options{ComputeReferences=true, View=вид}, первая PlanarFace с
    #      непустой Reference; ничего не нашлось -> типизированный отказ;
    #   2. линия размера: направление теперь берётся из нормали ПЕРВОЙ
    #      разрешённой грани (перечитана GetGeometryObjectFromReference),
    #      спроецированной в плоскость вида — E5 доказал живьём, что линия
    #      обязана идти ПОПЕРЁК измеряемых граней, а не вдоль фиксированной
    #      View.RightDirection; RightDirection остаётся фолбэком, когда
    #      нормаль не читается. Снят гард "line_at reproduced (geometry)":
    #      измеренное ЗНАЧЕНИЕ зависит от выбора граней (Exterior/Interior),
    #      сравнивать не с чем — значение уходит только в квитанцию.
    # Замена пина: DimensionLineOrientation в test_annotation.py.
    #
    # ── ДОБАВЛЕНО 28.07 (тем же днём): Regenerate перед добычей ссылок ─────
    # Живой повтор П11 ПОСЛЕ правки выше упал ТЕМ ЖЕ типизированным отказом
    # («refs[0]: у элемента нет геометрической ссылки для размера»), но по
    # ДРУГОЙ причине: у свежесозданной стены нет граней до Regenerate —
    # GetSideFaces пуст, geometry-фолбэк тоже пуст (Element.Geometry нуждается
    # в регенерированной геометрии не меньше). Замерено: между Wall.Create и
    # GetSideFaces в атомарной сборке Regenerate не эмитировался вовсе —
    # автопрогон emit_program ("v0 rule", walls_since_regen) регенерирует
    # только перед create_room. per_op — тот же закон: ни SubTransaction.
    # Commit(), ни Transaction.Commit() не документированы как регенерирующие
    # (RevitAPI.xml молчит про это в обе стороны), регенерация — всегда
    # отдельный явный Document.Regenerate(). Правка: безусловный
    # doc.Regenerate() первой строкой create-блока этого опа, БЕЗ try/catch
    # (тот же закон, что у set_curtain_panel: провал регенерации — испорченный
    # документ, транзакция обязана оборваться, не промолчать).
    "scope:annotation|":
        "общий футер: откат называет причину; pinned by RollbackMustNameItsCause "
        "в test_hangs_and_lies. ДОБАВЛЕНО 28.07: геометрические ссылки "
        "(GetSideFaces/geometry-фолбэк) + направление линии размера по нормали "
        "первой грани — pinned by DimensionLineOrientation. ДОБАВЛЕНО 28.07 "
        "(живой повтор П11): doc.Regenerate() перед добычей ссылок, atomic и "
        "per_op — pinned by test_regenerate_before_reference_extraction_"
        "atomic/_per_op/test_regenerate_is_not_wrapped_in_catch",
    "scope:annotation_explicit|":
        "общий футер: откат называет причину; pinned by RollbackMustNameItsCause "
        "в test_hangs_and_lies. ДОБАВЛЕНО 28.07: геометрические ссылки "
        "(GetSideFaces/geometry-фолбэк) + направление линии размера по нормали "
        "первой грани — pinned by DimensionLineOrientation. ДОБАВЛЕНО 28.07 "
        "(живой повтор П11): doc.Regenerate() перед добычей ссылок, atomic и "
        "per_op — pinned by test_regenerate_before_reference_extraction_"
        "atomic/_per_op/test_regenerate_is_not_wrapped_in_catch",
    "scope:arc_wall|":
        "общий футер: откат называет причину; pinned by RollbackMustNameItsCause в test_hangs_and_lies",
    "scope:families|":
        "общий футер: откат называет причину; pinned by RollbackMustNameItsCause в test_hangs_and_lies",
    "scope:mep_runs|":
        "общий футер: откат называет причину; pinned by RollbackMustNameItsCause в test_hangs_and_lies",
    "scope:modify|":
        "общий футер: откат называет причину; pinned by RollbackMustNameItsCause в test_hangs_and_lies",
    "scope:pipe_grid|":
        "общий футер: откат называет причину; pinned by RollbackMustNameItsCause в test_hangs_and_lies",
    "scope:roof|":
        "общий футер: откат называет причину; pinned by RollbackMustNameItsCause в test_hangs_and_lies",
    # ── отказ ОДНОГО опа стал ТИПОМ, а не «каким-то исключением» (28.07) ────
    # per_op-изоляция выбирала семантику отказа ПОСТ-ОБРАБОТКОЙ эмиссии:
    # `create.replace("__t.RollBack(); return __Refuse(", "throw __OpRefuse(")`.
    # Это вера в дословность фразы, набранной руками в 105 местах четырёх
    # файлов: эмиттер, написавший гард иначе, молча сохранял семантику ЦЕЛОЙ
    # программы внутри SubTransaction — отказ одного опа откатывал уже
    # закоммиченных соседей.  Замерено на этой ветке до правок: все четыре
    # варианта написания проходили молча.
    #
    # Тела операций НЕ СДВИНУЛИСЬ НИ НА БАЙТ — это доказано законом, а не
    # списком хешей: PerOpBodiesEqualTheRetiredRewrite сверяет per_op-тело
    # КАЖДОЙ операции корпуса с `atomic.replace(...)` посимвольно.  Разошёлся
    # только КАРКАС per_op-программы, и ровно в трёх местах: __OpRefuse строит
    # sentinel-тип __KirOpRefusal вместо InvalidOperationException, у него
    # появилась своя catch-ветка (несёт Oid отказанного опа), а неожиданное
    # исключение получило ярлык `internal` — управляемое решение компилятора
    # больше не путается с поломкой Revit API.  Атомарные байты не двигались
    # вовсе (549 эмиссий, ноль расхождений).
    #
    # Ключи перечислены ПОИМЁННО, а не префиксом программы: префикс снял бы с
    # ратчета и атомарные байты тех же программ — то есть ослабил бы его там,
    # где он как раз обязан держать.
    "golden:native_group|2021|per_op":
        "sentinel-тип отказа опа (__KirOpRefusal) + своя catch-ветка; тела\n         операций байт-в-байт прежние — pinned by test_emission_guard_contract",
    "golden:native_group|2022|per_op":
        "sentinel-тип отказа опа (__KirOpRefusal) + своя catch-ветка; тела\n         операций байт-в-байт прежние — pinned by test_emission_guard_contract",
    "golden:native_group|2023|per_op":
        "sentinel-тип отказа опа (__KirOpRefusal) + своя catch-ветка; тела\n         операций байт-в-байт прежние — pinned by test_emission_guard_contract",
    "golden:native_group|2024|per_op":
        "sentinel-тип отказа опа (__KirOpRefusal) + своя catch-ветка; тела\n         операций байт-в-байт прежние — pinned by test_emission_guard_contract",
    "golden:native_group|2025|per_op":
        "sentinel-тип отказа опа (__KirOpRefusal) + своя catch-ветка; тела\n         операций байт-в-байт прежние — pinned by test_emission_guard_contract",
    "golden:native_group|2026|per_op":
        "sentinel-тип отказа опа (__KirOpRefusal) + своя catch-ветка; тела\n         операций байт-в-байт прежние — pinned by test_emission_guard_contract",
    "scope:place_family_hosted|2021|per_op":
        "sentinel-тип отказа опа (__KirOpRefusal) + своя catch-ветка; тела\n         операций байт-в-байт прежние — pinned by test_emission_guard_contract",
    "scope:place_family_hosted|2022|per_op":
        "sentinel-тип отказа опа (__KirOpRefusal) + своя catch-ветка; тела\n         операций байт-в-байт прежние — pinned by test_emission_guard_contract",
    "scope:place_family_hosted|2023|per_op":
        "sentinel-тип отказа опа (__KirOpRefusal) + своя catch-ветка; тела\n         операций байт-в-байт прежние — pinned by test_emission_guard_contract",
    "scope:place_family_hosted|2024|per_op":
        "sentinel-тип отказа опа (__KirOpRefusal) + своя catch-ветка; тела\n         операций байт-в-байт прежние — pinned by test_emission_guard_contract",
    "scope:place_family_hosted|2025|per_op":
        "sentinel-тип отказа опа (__KirOpRefusal) + своя catch-ветка; тела\n         операций байт-в-байт прежние — pinned by test_emission_guard_contract",
    "scope:place_family_hosted|2026|per_op":
        "sentinel-тип отказа опа (__KirOpRefusal) + своя catch-ветка; тела\n         операций байт-в-байт прежние — pinned by test_emission_guard_contract",
    "scope:wall_location_line|2021|per_op":
        "sentinel-тип отказа опа (__KirOpRefusal) + своя catch-ветка; тела\n         операций байт-в-байт прежние — pinned by test_emission_guard_contract",
    "scope:wall_location_line|2022|per_op":
        "sentinel-тип отказа опа (__KirOpRefusal) + своя catch-ветка; тела\n         операций байт-в-байт прежние — pinned by test_emission_guard_contract",
    "scope:wall_location_line|2023|per_op":
        "sentinel-тип отказа опа (__KirOpRefusal) + своя catch-ветка; тела\n         операций байт-в-байт прежние — pinned by test_emission_guard_contract",
    "scope:wall_location_line|2024|per_op":
        "sentinel-тип отказа опа (__KirOpRefusal) + своя catch-ветка; тела\n         операций байт-в-байт прежние — pinned by test_emission_guard_contract",
    "scope:wall_location_line|2025|per_op":
        "sentinel-тип отказа опа (__KirOpRefusal) + своя catch-ветка; тела\n         операций байт-в-байт прежние — pinned by test_emission_guard_contract",
    "scope:wall_location_line|2026|per_op":
        "sentinel-тип отказа опа (__KirOpRefusal) + своя catch-ветка; тела\n         операций байт-в-байт прежние — pinned by test_emission_guard_contract",
    # ── level-guard больше не утверждает дрейф на ЛЮБОМ null-касте (31.07) ───
    # KIR-X003 — крупнейшая куча живых провалов (22 из 41 базовых опов).
    # `_level_expr` эмитила ОДНО статическое сообщение на
    # `doc.GetElement(id) as Level == null`: «уровень не найден (модель
    # изменилась после grounding)» — а `_translate_runtime` (serving.py)
    # решает «дрейф» ИЛИ «рантайм-отказ» по подстроке «после grounding» в
    # этом самом сообщении. Подстрока лежит в guard'е САМА, поэтому проверка
    # была тавтологией: любой null-каст — от ЛЮБОЙ причины — читался как
    # «модель уехала», хотя `as Level` возвращает null ещё и тогда, когда id
    # существует, но указывает не на Level.
    #
    # Живая улика (journalctl kukai-backend, 27.07, create_beam x16, два
    # прогона ~74 мин друг от друга, один редактор, один локальный файл):
    # X003 сказал «уровень не найден (модель изменилась после grounding)»
    # через 130-460мс ПОСЛЕ того, как ground_snapshot тот же каталог уровней
    # только что вернул. Физически мало времени для ручной правки модели.
    #
    # Guard теперь читает `doc.GetElement(id)` В ОТДЕЛЬНУЮ переменную ДО
    # каста и различает: raw == null -> прежний текст (дрейф, без изменений);
    # raw != null -> «id уровня резолвится не в Level, а в <Type> — причина
    # (дрейф модели или неверный id) не определена рантаймом». Вторая ветка
    # НЕ обвиняет grounding: `ground.py` документирует `by: element_id` как
    # ПРЕДНАМЕРЕННЫЙ pass-through (тип/существование перепроверяются ТОЛЬКО
    # здесь, рантаймом — см. докстринг модуля), так что неверный id мог
    # прийти и со стороны вызывающего. Сообщение называет НАБЛЮДАЕМЫЙ факт и
    # честно отказывается угадывать причину — та же дисциплина, что
    # RefusalMessageMustNotInventACause уже применила к "NewFamilyInstance
    # вернул null" / "NewElbowFitting: failed to insert elbow", на слой
    # глубже (там угадывал `_translate_runtime` по сырому тексту Revit,
    # здесь — сам C#-guard, заранее, за Revit).
    #
    # `_level_expr` — общий хелпер (14 сайтов вызова: стены, балки, колонны,
    # фундаменты, помещения, полы, потолки, ограждения, группы, place_family,
    # MEP-системы), поэтому байты сдвинулись везде, где параметр `level`
    # резолвится НЕ через `by: ref` (ref не проходит через guard вовсе).
    # Ни одна проверка не добавлена и не убрана — только текст отказа плюс
    # одна лишняя строка объявления (`Element __lv_raw_*`).
    # Замена пина: LevelGuardMustNotClaimDriftForAWrongType в
    # test_hangs_and_lies.py; golden'ы authoring_wall_pipe_grid,
    # authoring_wall_arc, route_pipe_system_riser_branch,
    # route_duct_system_tee, struct_beam, struct_foundation_isolated,
    # struct_foundation_slab, arch_ceiling, arch_railing_path,
    # place_family_point_and_curve, hosted_door_flips, wall_base_offset,
    # wall_top_attached, native_group (atomic), annotation_full_set,
    # annotation_explicit_types.
    "gate:auth_contour_default|":
        "level-guard: разведены «исчез» и «не тот тип» (KIR-X003, 31.07); "
        "pinned by LevelGuardMustNotClaimDriftForAWrongType",
    "gate:auth_contour_explicit|":
        "level-guard: разведены «исчез» и «не тот тип» (KIR-X003, 31.07); "
        "pinned by LevelGuardMustNotClaimDriftForAWrongType",
    "guard:column_vertical|":
        "level-guard: разведены «исчез» и «не тот тип» (KIR-X003, 31.07); "
        "pinned by LevelGuardMustNotClaimDriftForAWrongType",
    "guard:contour_typed|":
        "level-guard: разведены «исчез» и «не тот тип» (KIR-X003, 31.07); "
        "pinned by LevelGuardMustNotClaimDriftForAWrongType",
    "guard:floor_typed|":
        "level-guard: разведены «исчез» и «не тот тип» (KIR-X003, 31.07); "
        "pinned by LevelGuardMustNotClaimDriftForAWrongType",
    "guard:group_mixed_members|":
        "level-guard: разведены «исчез» и «не тот тип» (KIR-X003, 31.07); "
        "pinned by LevelGuardMustNotClaimDriftForAWrongType",
    "guard:roof_typed|":
        "level-guard: разведены «исчез» и «не тот тип» (KIR-X003, 31.07); "
        "pinned by LevelGuardMustNotClaimDriftForAWrongType",
    "scope:wall_location_line|2021|atomic":
        "level-guard: разведены «исчез» и «не тот тип» (KIR-X003, 31.07); "
        "pinned by LevelGuardMustNotClaimDriftForAWrongType",
    "scope:wall_location_line|2022|atomic":
        "level-guard: разведены «исчез» и «не тот тип» (KIR-X003, 31.07); "
        "pinned by LevelGuardMustNotClaimDriftForAWrongType",
    "scope:wall_location_line|2023|atomic":
        "level-guard: разведены «исчез» и «не тот тип» (KIR-X003, 31.07); "
        "pinned by LevelGuardMustNotClaimDriftForAWrongType",
    "scope:wall_location_line|2024|atomic":
        "level-guard: разведены «исчез» и «не тот тип» (KIR-X003, 31.07); "
        "pinned by LevelGuardMustNotClaimDriftForAWrongType",
    "scope:wall_location_line|2025|atomic":
        "level-guard: разведены «исчез» и «не тот тип» (KIR-X003, 31.07); "
        "pinned by LevelGuardMustNotClaimDriftForAWrongType",
    "scope:wall_location_line|2026|atomic":
        "level-guard: разведены «исчез» и «не тот тип» (KIR-X003, 31.07); "
        "pinned by LevelGuardMustNotClaimDriftForAWrongType",
    "golden:native_group|2021|atomic":
        "level-guard: разведены «исчез» и «не тот тип» (KIR-X003, 31.07); "
        "pinned by LevelGuardMustNotClaimDriftForAWrongType",
    "golden:native_group|2022|atomic":
        "level-guard: разведены «исчез» и «не тот тип» (KIR-X003, 31.07); "
        "pinned by LevelGuardMustNotClaimDriftForAWrongType",
    "golden:native_group|2023|atomic":
        "level-guard: разведены «исчез» и «не тот тип» (KIR-X003, 31.07); "
        "pinned by LevelGuardMustNotClaimDriftForAWrongType",
    "golden:native_group|2024|atomic":
        "level-guard: разведены «исчез» и «не тот тип» (KIR-X003, 31.07); "
        "pinned by LevelGuardMustNotClaimDriftForAWrongType",
    "golden:native_group|2025|atomic":
        "level-guard: разведены «исчез» и «не тот тип» (KIR-X003, 31.07); "
        "pinned by LevelGuardMustNotClaimDriftForAWrongType",
    "golden:native_group|2026|atomic":
        "level-guard: разведены «исчез» и «не тот тип» (KIR-X003, 31.07); "
        "pinned by LevelGuardMustNotClaimDriftForAWrongType",
}


def _exempt(key: str) -> bool:
    return any(key.startswith(prefix) for prefix in INTENDED_CHANGES)


def _gate_authoring_programs() -> dict[str, dict]:
    """The gate runner's authoring shapes, from the same committed sources."""

    from kukai.ir.tests.test_authoring import _prog, _wall

    programs: dict[str, dict] = {}
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
    programs["auth_stack"] = {
        "ir_version": "1.0", "intent": "стек 5 этажей",
        "ops": [{"op": "stack", "id": "sec", "levels": 5, "h_mm": 3000,
                 "floor": [
                     {"op": "create_wall", "id": "W1", "p0_mm": [0, 0],
                      "p1_mm": [6000, 0], "height_mm": 2800},
                     {"op": "create_pipe", "id": "P1", "p0_mm": [0, 0, 2700],
                      "p1_mm": [3000, 0, 2700], "diameter_mm": 50},
                 ]}]}
    programs["auth_grid_array"] = {
        "ir_version": "1.0", "intent": "сетка осей 4x3",
        "ops": [{"op": "grid_array", "id": "net", "nx": 4, "ny": 3,
                 "dx_mm": 6000, "dy_mm": 4500, "prefix_y": "А"}]}
    programs["auth_stairs"] = {
        "ir_version": "1.0", "intent": "лестничный марш",
        "ops": [{"op": "create_stairs", "id": "S1",
                 "p0_mm": [0, 0], "p1_mm": [5000, 0],
                 "base_level": {"by": "element_id", "value": 42},
                 "top_level": {"by": "element_id", "value": 43},
                 "width_mm": 1200}]}
    # codex #9 (2026-07-29, tasks/b8f3v4r97.output сессии eeccfb91): the
    # ONLY non-exempt frozen coverage of create_floor_by_contour was
    # "guard:contour_typed" (explicit type, no offset) — the DEFAULT-type
    # branch existed only as "scope:contour", which INTENDED_CHANGES has
    # exempted since the 27.07 level-chain fix and never un-exempted, so
    # "the whole previous emission is proven byte-exact" was a claim
    # stronger than any enforced test. Own dict (this file's, not
    # SCOPE_PROGRAMS/GUARD_PROGRAMS) so it never collides with either
    # corpus and is NEVER exempt by construction — both type branches,
    # neither carries height_offset_mm (codex's own "БЕЗ offset").
    programs["auth_contour_default"] = {
        "ir_version": "1.0",
        "intent": "плита по контуру, тип по умолчанию, без смещения",
        "ops": [
            {"op": "create_floor_by_contour", "id": "FCD1",
             "contour": {"outer": {"shape": "rect", "origin": [0, 0],
                                   "size_mm": [8000, 6000]}},
             "level": {"by": "name", "value": "Этаж 1"}},
        ]}
    programs["auth_contour_explicit"] = {
        "ir_version": "1.0",
        "intent": "плита по контуру, явный тип, без смещения",
        "ops": [
            {"op": "create_floor_by_contour", "id": "FCE1",
             "contour": {"outer": {"shape": "rect", "origin": [0, 0],
                                   "size_mm": [8000, 6000]}},
             "level": {"by": "name", "value": "Этаж 1"},
             "type": {"by": "name", "value": "Монолит 200"}},
        ]}

    def _grp_wall(oid, x0, y0, x1, y1):
        return {"op": "create_wall", "id": oid, "p0_mm": [x0, y0],
                "p1_mm": [x1, y1],
                "level": {"__grounded__": {"id": 42, "name": None,
                                           "via": "element_id"}},
                "height_mm": 3000.0,
                "type": {"__grounded__": {"id": None, "name": None,
                                          "via": "doc_default",
                                          "in_emit": "__doc_default__"}}}

    programs["auth_native_group"] = {
        "ir_version": "1.0",
        "intent": "типовой этаж как нативная группа",
        "ops": [{"op": "create_group", "id": "GRP1", "name": "Типовой этаж",
                 "members": [_grp_wall("W1", 30000, 23000, 36000, 23000),
                             _grp_wall("W2", 36000, 23000, 36000, 27000)],
                 "placements": [[0, 0, 6600], [0, 0, 13200]]}]}
    programs["mod_setparam_delete"] = {
        "ir_version": "1.0",
        "intent": "параметр + удаление", "allow_destructive": True,
        "ops": [
            {"op": "create_level", "id": "L1", "elev_mm": 12000, "name": "Тех"},
            {"op": "set_param", "id": "S1",
             "target": {"by": "ref", "value": "L1"},
             "param": "Комментарии", "value": "создан KIR"},
            {"op": "set_param", "id": "S2",
             "target": {"by": "element_id", "value": 7777},
             "param": "Комментарии", "value": "обработано KIR"},
            {"op": "delete", "id": "DEL1",
             "target": {"by": "element_id", "value": 8888}},
        ]}
    return programs


def build_corpus() -> dict[str, dict]:
    """(source-prefixed name) -> program.  Deterministic assembly order."""

    corpus: dict[str, dict] = {}
    for name, prog in GOLDEN_PROGRAMS.items():
        corpus[f"golden:{name}"] = prog
    for name, prog in SCOPE_PROGRAMS.items():
        corpus[f"scope:{name}"] = prog
    for name, prog in _gate_authoring_programs().items():
        corpus[f"gate:{name}"] = prog
    for name, prog in GUARD_PROGRAMS.items():
        corpus[f"guard:{name}"] = prog
    rng = random.Random(GATE_SEED)
    for i in range(N_PBT):
        corpus[f"pbt:{i:02d}"] = gen_program(rng)
    # ОДНА запись на вид, а не пачки по 20.
    #
    # Пачки нумеровались смещением, поэтому добавление вида пересобирало
    # состав кусков и «расхаживало» замороженные байты у видов, которых
    # правка не касалась (27.07: +30 видов ⇒ 12 расхождений в all_kinds при
    # неизменном эмиттере). Ключ по ИМЕНИ вида делает рост таблицы строго
    # аддитивным: новый вид приносит новый ключ и не двигает ни одного
    # старого. Храповик обязан щёлкать на изменение эмиссии, а не на
    # изменение соседней таблицы — иначе его перестают читать.
    for kind in sorted(spec.KINDS):
        corpus[f"query:kind_{kind}"] = {
            "ir_version": "1.0",
            "ops": [{"op": "query_count", "id": "k0", "kind": kind}]}
    qt_pools = spec.OPS["query_types"].params[0].choices
    corpus["query:types_all_pools"] = {
        "ir_version": "1.0",
        "intent": "какие типы существуют в каждом закрытом пуле",
        "ops": [{"op": "query_types", "id": f"t{j}", "pool": p}
                for j, p in enumerate(qt_pools)]}
    return corpus


def _min_ver(prog: dict) -> str:
    return prog.get("__min_ver__", "2021")


#: Служебные ключи ОБВЯЗКИ, которых в конверте программы нет: снимать их
#: обязан КАЖДЫЙ читатель корпуса, иначе схема ответит KIR-P003 «неизвестное
#: поле» и программа не дойдёт до эмиттера вовсе.
#:
#: `__ver__` добавлен в этот список при слиянии 09.08, и цена его отсутствия
#: показательна. Волна нагрузок завела ВТОРОЙ такой ключ рядом с уже
#: существовавшим `__min_ver__` (у неё пин обратный: свободная нагрузка живёт
#: только на 2021-2023, то есть это ПОТОЛОК, а не пол, поэтому переименовать
#: его в `__min_ver__` нельзя) — и научила снимать его РОВНО ОДНОГО читателя,
#: `test_golden`. Читателей же три, и оба остальных молча ослепли:
#:   * `gate_runner` отдавал KIR-P003 на всех шести версиях;
#:   * этот корпус ловил KirRefusal и делал `continue`, из-за чего три опа
#:     нагрузок НЕ ДОХОДИЛИ ДО ЭМИТТЕРА НИ РАЗУ — и анти-Гудхарт-тест
#:     `test_the_corpus_actually_reaches_a_guard_in_every_kind` показал 49
#:     видов против 52 в `_EMITTERS`. Это ровно тот случай, ради которого он
#:     написан: паритетный корпус выглядел бы чистым, потому что до трёх
#:     операций он просто не добирался.
_HARNESS_KEYS = ("__min_ver__", "__ver__")


def _strip(prog: dict) -> dict:
    return {k: v for k, v in prog.items() if k not in _HARNESS_KEYS}


def _is_write(prog: dict) -> bool:
    try:
        ops = prog.get("ops", [])
        return bool(ops) and any(
            spec.OPS.get(op.get("op"),
                         spec.OPS["query_count"]).family
            in spec.WRITE_FAMILIES
            for op in ops if isinstance(op, dict) and op.get("op") in spec.OPS)
    except Exception:
        return False


def emit_corpus(dump_dir: pathlib.Path | None = None) -> dict[str, str]:
    """Return {key: sha256} over every (program, version, mode) emission."""

    corpus = build_corpus()
    hashes: dict[str, str] = {}
    for name in sorted(corpus):
        raw = corpus[name]
        prog = _strip(raw)
        for ver in VERSIONS:
            if ver < _min_ver(raw):
                continue
            out = compile_program(prog, revit_version=ver,
                                  snapshot=GROUND_SNAPSHOT)
            if not out.ok:
                # A version-gated typed refusal (e.g. floor holes on 2021) is
                # ITSELF part of parity: the refusal codes are frozen so the
                # refactor can neither un-refuse nor re-code them.
                codes = ",".join(sorted(d.code for d in out.diagnostics))
                hashes[f"{name}|{ver}|atomic"] = f"refused:{codes}"
                continue
            _record(hashes, dump_dir, f"{name}|{ver}|atomic", out.csharp)
            # per_op isolation for write programs (macro ops like stack /
            # grid_array expand during parse; stairs is sole-op template —
            # emit_program handles all of them).
            if _is_write(prog):
                normed = _parse_and_check(prog)
                grounded = ground_mod.ground(normed, GROUND_SNAPSHOT)
                intent = prog.get("intent", "")
                per_op_cs = emit_program(
                    grounded, ver, intent if isinstance(intent, str) else "",
                    isolation="per_op")
                _record(hashes, dump_dir, f"{name}|{ver}|per_op", per_op_cs)
    return hashes


def _record(hashes: dict[str, str], dump_dir: pathlib.Path | None,
            key: str, csharp: str) -> None:
    hashes[key] = hashlib.sha256(csharp.encode("utf-8")).hexdigest()
    if dump_dir is not None:
        safe = key.replace("|", "__").replace(":", "_").replace("/", "_")
        (dump_dir / f"{safe}.cs").write_text(csharp, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dump", type=pathlib.Path, default=None,
                        help="also write full emissions to this directory")
    parser.add_argument("--check", action="store_true",
                        help="compare against the frozen fixture instead of "
                             "writing it")
    args = parser.parse_args()
    if args.dump is not None:
        args.dump.mkdir(parents=True, exist_ok=True)
    hashes = emit_corpus(args.dump)
    if args.check:
        frozen = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        mismatched = sorted(
            key for key in frozen
            if not _exempt(key) and hashes.get(key) != frozen[key])
        missing = sorted(
            key for key in set(frozen) - set(hashes) if not _exempt(key))
        extra = sorted(set(hashes) - set(frozen))
        if mismatched or missing:
            print(f"PARITY BROKEN: {len(mismatched)} mismatched, "
                  f"{len(missing)} missing, {len(extra)} extra")
            for key in mismatched[:20]:
                print("  mismatch:", key)
            return 1
        print(f"PARITY OK: {len(frozen)} emissions byte-identical"
              + (f" (+{len(extra)} new keys)" if extra else ""))
        return 0
    FIXTURE_PATH.write_text(
        json.dumps(hashes, indent=0, sort_keys=True) + "\n",
        encoding="utf-8")
    print(f"froze {len(hashes)} emission hashes -> {FIXTURE_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
