"""Every op that builds geometry must have a witness that can see geometry.

Three times in one night a postcondition passed over wrong geometry, and each
time for the same reason: the witness checked what the emitter had just set
rather than what the author had asked for.

* a wall's location line — compared an enum ordinal, while the wall body stood
  where it always had;
* a slanted column — demanded back a level parameter the emitter deliberately
  never wrote;
* a pitched roof — asked whether the roof had gained ANY height, and accepted
  one built at 38 degrees instead of 45.

A witness written in the same hour, by the same hand, as the emission it
guards inherits that emission's blind spots. The only obligation that does not
is one phrased against geometry Revit reports back independently: a location,
a curve endpoint, a bounding box, an elevation.

So this is a structural rule, not a review habit: an emitter that creates
geometry must reference at least one of those. The allowlist below is for ops
that genuinely create none, and every entry states why.
"""

from __future__ import annotations

import pathlib
import re
import unittest

from kukai.ir.record_ratchet import CLOSE_BY, Entry, Ledger

_IR_DIR = pathlib.Path(__file__).resolve().parents[1]

#: Helpers whose whole purpose is a geometric obligation.
#:
#: ``_network_geometry_post`` joined the list on 2026-08-09, and the delay is
#: the lesson. It has read every created segment's ``LocationCurve`` endpoints
#: back since 2026-07-27 (commits ``97892ce5``/``557d55fc``), but the emitters
#: consume it as ``seg, dia, etol, dtol = _network_geometry_post(...)`` and the
#: delegation rule below only follows ``return f(...)``. So the detector could
#: not see a witness that was there, reported the two route ops as naked, and
#: the debt list below froze that phantom by name — where it then survived two
#: audits, because a name on a debt list reads as a measurement.
#:
#: An instrument that covers part of its range is worse than an absent one: it
#: answers, and the answer is believed. The rule for this tuple is therefore
#: narrow on purpose — a helper belongs here only if its WHOLE purpose is a
#: geometric obligation. Following every call transitively instead was measured
#: on 2026-08-09 and rejected: it clears ``_emit_wall_foundation_struct`` too,
#: whose geometry genuinely is not witnessed, so the loosening buys two true
#: answers at the price of one false one.
#:
#: ``emit_xyz_to_view2d_cs(`` joined on 2026-08-09 and satisfies the narrow
#: rule above exactly: its WHOLE purpose is to read a point off a BUILT element
#: back into the owner view's axes (``rel = P − Origin; u = rel·Right;
#: v = rel·Up``). It exists because the annotation family's inverse must be
#: IDENTICAL to its forward map, not merely similar, and one law cannot live in
#: three emitters.
_GEOMETRY_HELPERS = ("endpoint_witness(", "bbox_extents_witness(",
                     "_network_geometry_post(", "emit_xyz_to_view2d_cs(")

#: Properties Revit computes from the model itself, so an emitter cannot
#: satisfy them merely by having written a parameter.
#:
#: ГОЛЫЙ ``Origin`` УБРАН 09.08.2026, И ЭТО НЕ ОСЛАБЛЕНИЕ, А ПОЧИНКА. Он
#: спасал ровно два эмиттера, и в ОБОИХ совпадал с ``__vw_{s}.Origin`` —
#: началом ВИДА, то есть входом вычисления, а не чтением построенного
#: элемента. Ровно тот же дефект, что нашла волна нагрузок 09.08 у
#: ``create_line_load`` (``Plane.CreateByNormalAndOrigin`` содержит подстроку
#: «Origin»), — и на этот раз он прятал не ложный пропуск, а ЛОЖНОЕ
#: ПРОХОЖДЕНИЕ: ``_emit_angular_dimension`` и ``_emit_tag`` объявлялись
#: одетыми по слову в АРГУМЕНТЕ СОЗДАНИЯ.
#:
#: Оба одеты по-настоящему, и вместо совпадения здесь стоят их настоящие
#: свидетели:
#:   ``.Value ?? double.NaN`` — ``Dimension.Value``/``AngularDimension.Value``:
#:       расстояние (угол) между ССЫЛКАМИ, которое Revit вычисляет из модели
#:       сам, и подписано оно ``(geometry)``. Форма нарочно узкая: голое
#:       ``.Value`` совпало бы с идиомой ``ElementId.Value`` 2024-26 и снова
#:       раздавало бы одетость по совпадению;
#:   ``.TagHeadPosition``  — положение головки ПОСТРОЕННОЙ марки.
_GEOMETRY_READS = (
    "Location", "get_BoundingBox", "GetEndPoint", ".Point",
    "FacingOrientation", "HandOrientation", ".Elevation",
    ".Value ?? double.NaN", ".TagHeadPosition",
    # wave/analysis (09.08). ПРИБОР РАСШИРЕН, А НЕ ОСЛАБЛЕН, и повод —
    # найденный им же ложный ПРОПУСК: `create_line_load` проходил проверку
    # только потому, что строка `Plane.CreateByNormalAndOrigin` содержит
    # «Origin», — то есть по совпадению подстроки в АРГУМЕНТЕ СОЗДАНИЯ, а не
    # по своему настоящему свидетелю. Настоящий у него — `StartPoint`/
    # `EndPoint`, а у пути эвакуации — `PathStart`/`PathEnd`/`GetCurves`, у
    # площадной нагрузки — `GetLoops`. Все они ровно того рода, ради которого
    # список существует (шапка модуля: «location, curve endpoint, bounding
    # box, elevation»): Revit возвращает их у ПОСТРОЕННОГО элемента, и
    # эмиттер не может удовлетворить их, просто записав параметр.
    ".StartPoint", ".EndPoint", ".PathStart", ".PathEnd",
    "GetCurves", "GetLoops",
    # wave/site (2026-08-09). Три чтения ТОГО ЖЕ КЛАССА, что и все выше:
    # элемент сам отдаёт свою геометрию, и эмиттер не может удовлетворить их
    # тем, что записал параметр.
    #   GetBoundary()        — граница площадки/подобласти, то есть эскиз,
    #                          который Revit СОХРАНИЛ (а не тот, что мы
    #                          передали: сравнение идёт после развёртки
    #                          Curve.Tessellate);
    #   GetPoints()          — точки построенной топоповерхности;
    #   SlabShapeVertices    — вершины формы толщи рельефа (у неё GetPoints()
    #                          не существует ни на одной версии — замерено).
    # Список расширяется ТОЛЬКО так: новым НЕЗАВИСИМЫМ чтением, а не именем
    # параметра, который эмиттер сам же и пишет.
    "GetBoundary", "GetPoints", "SlabShapeVertices",
    # wave/sweep (2026-08-09). ЧТЕНИЕ РОВНО ТОГО ЖЕ КЛАССА, и это стоит
    # сказать точно, потому что имя выглядит как аксессор параметра, а им не
    # является: `HostedSweep.get_ReferenceCurve(Reference)` — индексируемое
    # свойство ПОСТРОЕННОГО навесного профиля, возвращающее кривую, которую он
    # ПРОЛОЖИЛ по названной ссылке на ребро. Эмиттер удовлетворить его не
    # может ничем: он передал ссылку, а кривую вернул элемент, и `null`
    # означает, что Revit ссылку не взял — то есть профиль обводит НЕ ТОТ
    # периметр, который просили. Ровно то, ради чего список существует.
    "get_ReferenceCurve",
    # wave/datums (09.08.2026): ТЕЛО, посчитанное Revit. Список выше знал
    # только точки и габарит по осям мира, а выдавленная кровля меряется ПО
    # НОРМАЛИ своей рабочей плоскости — нормаль горизонтальна, но
    # произвольна, и осевой bbox смешал бы ход выдавливания с размахом
    # профиля. Обход тела (`get_Geometry` -> Solid -> Edge -> `Tessellate`)
    # — самая сильная форма независимого чтения, какая тут есть: эмиттер не
    # может удовлетворить её, записав параметр. Прибор, знающий часть
    # диапазона, опаснее отсутствующего — поэтому список РАСШИРЕН, а не
    # обойдён исключением.
    "get_Geometry", "Tessellate",
    # wave/detail (2026-08-09). ПРИБОР СНОВА РАСШИРЕН ПО СОБСТВЕННОМУ ЖЕ
    # НАЙДЕННОМУ ПРОПУСКУ, и повод тот же, что был у волны нагрузок: марка и
    # текст проходили эту проверку ТОЛЬКО из-за подстроки «Origin» в
    # `__vw_<s>.Origin` — то есть по началу координат ВИДА, которое эмиттер
    # берёт сам, а не по чему-либо, прочитанному у построенного элемента.
    # Совпадение вскрылось, когда обратная формула переехала в docspace и
    # «Origin» из текста эмиттера марки исчез: детектор объявил `_emit_tag`
    # голым, хотя его свидетель (`TagHeadPosition`) не менялся ни на байт.
    # Настоящие независимые чтения этого семейства названы здесь:
    #   TagHeadPosition — где Revit ПОСТАВИЛ головку марки;
    #   .Coord          — где Revit ПОСТАВИЛ текстовую заметку;
    #   GetBoundaries   — граница построенной заливки.
    "TagHeadPosition", ".Coord", "GetBoundaries",
)

#: Ops that create no geometry at all. Each entry is a claim that has to stay
#: true, not a way to silence the check.
_NO_GEOMETRY = {
    "_emit_create_type": "creates a TYPE; no instance exists to measure",
    "_emit_load_family": "loads a family file; places nothing",
    "_emit_setparam": "writes a parameter on an element it did not create",
    "_emit_delete": "removes elements; the absence is checked by count",
    # ``_emit_pipe_system`` left this list on 2026-08-09. Its entry claimed the
    # op "declares a system" and creates no geometry of its own — but the op
    # calls ``Pipe.Create`` once per authored edge, so it builds every metre of
    # pipe in the network. The claim was false, and it needed no exemption
    # anyway: the same ``_network_geometry_post`` the route ops use reads those
    # segments' endpoints back. An exemption resting on a false claim is worse
    # than no exemption, because it survives review by sounding like one.
    # set_curtain_panel carries no coordinate at all: host + cell address +
    # type. The cell's shape is cut by the host's curtain grid, which this op
    # neither creates nor moves — exactly set_param's position, one level up
    # (a TYPE instead of a value). The claim that has to stay true: the day
    # this op gains a coordinate (a grid line, an offset), this entry is false
    # and must go, because then a wrong shape could commit silently.
    "_emit_set_curtain_panel": "assigns a TYPE to an existing grid cell; the "
                               "op carries no coordinate and cuts no grid",
    # wave/datums (09.08.2026). Многоэтажная лестница ДЕЙСТВИТЕЛЬНО порождает
    # геометрию — марши на каждом подключённом уровне. Но весь вход опа это
    # ОДНА ссылка на элемент и МНОЖЕСТВО ссылок на уровни: ни одной
    # координаты автор не называет, а форму маршей Revit копирует с
    # оригинала. Сравнивать полученную геометрию НЕ С ЧЕМ — любое сравнение
    # свелось бы к «уровень равен уровню», то есть к проверке, которая не
    # может упасть, а такая хуже отсутствующей.
    # Что проверяется вместо неё: ТОЧНОЕ равенство множеств уровней,
    # перечитанное из документа, без допуска.
    # ЗАЯВЛЕНИЕ, КОТОРОЕ ОБЯЗАНО ОСТАВАТЬСЯ ВЕРНЫМ: в тот день, когда у опа
    # появится хоть одна координата, эта запись становится ложью и должна
    # уйти.
    "_emit_multistory_stairs_datum": "replicates an EXISTING stair across "
                                     "named levels; the op carries no "
                                     "coordinate at all, so no authored "
                                     "number exists to compare geometry "
                                     "against",
    # CLASH-починка (28.07): change_type is set_param's own exemption one
    # level up — a TYPE change on an element it did not create, no
    # coordinate anywhere in the op. Its witness (GetTypeId() re-read) is
    # semantic/identity, not geometric, on purpose: Element.ChangeTypeId
    # moves nothing (the rare new-element case is still the SAME location,
    # per RevitAPI.xml — a curtain-panel<->wall type swap, not a move). The
    # claim that has to stay true: the day this op gains a coordinate
    # (e.g. a re-host), this entry is false and must go.
    "_emit_change_type": "changes an element's TYPE; no coordinate — the "
                         "rare new-element case (RevitAPI.xml) still commits "
                         "the SAME location, so nothing here moves",
    # wave/sweep (2026-08-09). ЭТО ЕДИНСТВЕННОЕ ОСВОБОЖДЕНИЕ В ЭТОМ СЛОВАРЕ,
    # ОПИРАЮЩЕЕСЯ НА ДОКУМЕНТИРОВАННЫЙ ФАКТ API, А НЕ НА УСТРОЙСТВО НАШЕГО
    # ОПА, и поэтому его стоит прочитать целиком, прежде чем «починить».
    #
    # Тело у карниза есть. Координаты у ОПЕРАЦИИ — нет, и завести её нельзя:
    # RevitAPI.xml всех ШЕСТИ версий пишет у `WallSweep.Create` дословно «The
    # wall sweep's profile and type are taken from the wall sweep type
    # properties. The values set in the WallSweepInfo are ignored.» То есть
    # расстояние и смещение задаёт ТИП, заранее загруженный в документ, а не
    # вызов; поля для них у операции нет вовсе, и читать обратно нечего.
    # Позиция ровно та же, что у `_emit_set_curtain_panel`: хозяин + тип, и ни
    # одной координаты.
    #
    # ЧТО ЗДЕСЬ НЕ УТВЕРЖДАЕТСЯ: что форма карниза не важна. Утверждается, что
    # её выбирает АВТОР ТИПА, а не эта программа, и что предъявить свидетеля
    # на чужой выбор значило бы предъявить проверку, которая не может
    # провалиться, — по закону этого дома хуже отсутствующей.
    #
    # УТВЕРЖДЕНИЕ, КОТОРОЕ ОБЯЗАНО ОСТАВАТЬСЯ ИСТИННЫМ: в тот день, когда у
    # операции появится хоть одна координата (расстояние, смещение от стены,
    # угол), эта строка станет ложной и обязана уйти — потому что с этого дня
    # неверная форма сможет закоммититься молча.
    "_emit_wall_sweep": "hangs a profile whose position is taken ENTIRELY "
                        "from the pre-loaded type (RevitAPI.xml, all six "
                        "versions); the op carries no coordinate at all",
}


def _all_function_bodies() -> dict[str, str]:
    """Every top-level function in the IR package, keyed by bare name.

    Emitters delegate freely -- doors and windows to the hosted emitter, beams
    and foundations into struct_emit -- so an analysis that stops at
    authoring.py reports four false defects. It did, before this followed them.
    """
    out: dict[str, str] = {}
    for path in sorted(_IR_DIR.glob("*.py")):
        src = path.read_text(encoding="utf-8")
        starts = [(m.group(1), m.start())
                  for m in re.finditer(r"^def (\w+)\(", src, re.M)]
        for i, (name, start) in enumerate(starts):
            end = starts[i + 1][1] if i + 1 < len(starts) else len(src)
            out.setdefault(name, src[start:end])
    return out


def _emitters() -> dict[str, str]:
    """The op emitters, taken from the dispatch table rather than from names.

    ``_emit_`` is not a reliable marker: compiler.py has ``_emit_collector``
    and ``_emit_row``, which build query C# and place nothing. Reading
    ``_EMITTERS`` asks the code which functions actually author elements.
    """
    table = (_IR_DIR / "authoring.py").read_text(encoding="utf-8")
    start = table.index("_EMITTERS = {")
    # Balanced scan: the table closes on the same line as its last entry, so
    # searching for a lone brace finds the wrong one -- or none at all.
    depth, end = 0, start
    for end in range(table.index("{", start), len(table)):
        if table[end] == "{":
            depth += 1
        elif table[end] == "}":
            depth -= 1
            if depth == 0:
                break
    names = set(re.findall(r":\s*(_emit_\w+)", table[start:end]))
    assert names, "the emitter dispatch table could not be read"
    bodies = _all_function_bodies()
    return {n: bodies[n] for n in sorted(names) if n in bodies}


#: ``return other(...)`` or ``return mod.other(...)`` and nothing else of
#: substance: the obligation lives in the callee.
_DELEGATION = re.compile(r"return\s+(?:\w+\.)?(\w+)\(", re.M)


#: Строка комментария Python и тройная докстрока — это ПРОЗА, а не код.
_PROSE = re.compile(r'^\s*#.*$|"""(?:.|\n)*?"""|\'\'\'(?:.|\n)*?\'\'\'', re.M)


def _code_only(body: str) -> str:
    """Тело функции без комментариев и докстрок.

    ПРИЧИНА, ПО КОТОРОЙ ЭТО ПОЯВИЛОСЬ 09.08.2026, ДОРОЖЕ САМОЙ ФУНКЦИИ.
    ``_emit_dimension`` — 361 строка, самый разбираемый оп того дня —
    проходил проверку геометрической честности ПО ОДНОМУ СОВПАДЕНИЮ, и
    совпадение было со словом ``Origin`` внутри английской ПРОЗЫ:

        # position of Origin ALONG the line — is an emergent property of where

    Это даже не эмитируемый C#. Прибор отвечал «одет» по комментарию, и
    ответ был бы поверен, потому что прибор с именем убедительнее человека.
    Ровно то, о чём предупреждает канон: инструмент, покрывающий ЧАСТЬ своего
    диапазона, опаснее отсутствующего.

    Направление у починки одно и оно намеренное: вычёркивание прозы может
    сделать эмиттер ГОЛЫМ (ложная тревога — дешёвая), но не может сделать
    голого одетым.
    """
    return _PROSE.sub("", body)


def _has_geometric_witness(body: str, depth: int = 2) -> bool:
    code = _code_only(body)
    if (any(h in code for h in _GEOMETRY_HELPERS)
            or any(t in code for t in _GEOMETRY_READS)):
        return True
    if depth <= 0:
        return False
    bodies = _all_function_bodies()
    return any(_has_geometric_witness(bodies[target], depth - 1)
               for target in _DELEGATION.findall(code)
               if target in bodies)


#: Known debt, frozen by name.
#:
#: ``_emit_route_pipe_system`` and ``_emit_route_duct_system`` LEFT this list on
#: 2026-08-09, and the correction is worth more than the removal. Their entry
#: said the two ops "verify none of it geometrically: a pipe laid along the
#: wrong path satisfies every postcondition they have". That was untrue when it
#: was written and stayed untrue for thirteen days: both ops have re-read every
#: created segment's ``LocationCurve`` endpoints against the authored node pair
#: since 2026-07-27, and the corpus proves the witness bites — on live Revit
#: 2026 at 2026-07-30T13:49:56 ``route_duct_system`` rolled back on
#: ``R1: segment 0/1/2 endpoints (geometry)``, and the same op ran clean at
#: 14:38:08. What was missing was not the witness but the detector's ability to
#: see it (see ``_GEOMETRY_HELPERS``).
#:
#: The entry that was genuinely open on those two — never named here — was the
#: reference LEVEL: a required authored parameter that both emitters pass
#: straight into ``Pipe.Create``/``Duct.Create`` and neither read back, while
#: ``acceptance._LEVEL_FROM_PARAM`` already built its post-commit census on the
#: claim that it holds. Closed 2026-08-09 by the ``reference_level`` witness.
#:
#: A wall foundation DOES build a solid, so ``_NO_GEOMETRY`` would be a lie
#: here — this is debt, and it is named as such. What is missing is not the
#: code but the NUMBER: how far the footing projects past its wall and where
#: its underside sits have never been measured (zero WallFoundation instances
#: across every stored decompile, grep 2026-08-09), so any bbox comparison
#: would be a bound authored by reasoning — the defect class this repository
#: names in its own canon. Its topology witness is exact and tolerance-free
#: (WallId equality re-read from the document), which is why the op is safe to
#: ship naked-of-geometry and not safe to ship with an invented tolerance.
#: One live run closes this; another hour of reasoning cannot.
#:
#: С 09.08.2026 ЭТО ЖУРНАЛ, А НЕ МНОЖЕСТВО ИМЁН (``record_ratchet``), и повод
#: — история двух строк выше. Имя в списке долгов ЧИТАЕТСЯ КАК ЗАМЕР: два
#: аудита подряд прочитали ``route_pipe_system`` именно так, при живом
#: свидетеле, стоявшем с 27.07. Множество имён не умеет сказать ни когда
#: решение принято, ни кто и к какому дню обязан ответить, — а без этого
#: честная запись живёт ровно до тех пор, пока о ней помнят.
_KNOWN_NAKED = Ledger(
    "witness_geometry._KNOWN_NAKED",
    {
        "_emit_wall_foundation_struct": Entry(
            CLOSE_BY, "2026-08-09", "2026-09-08",
            "лента строит настоящее тело, поэтому _NO_GEOMETRY здесь был бы "
            "ложью: не хватает не кода, а ЧИСЛА — свес подошвы за стену и "
            "отметка низа не замерены ни разу (ноль экземпляров WallFoundation "
            "во всех сохранённых разборах, grep 09.08), а допуск, выведенный "
            "рассуждением, — тот самый класс дефекта, которым этот дом уже "
            "заворачивал верные постройки. Топология точна и без допуска "
            "(WallId перечитан из документа). Закрывает ОДИН живой прогон"),
    },
    instrument=(
        "_has_geometric_witness() над телом эмиттера из таблицы _EMITTERS: "
        "строка держится, пока имя стоит в naked; прибор чинили дважды "
        "(09.08 — делегирование распаковкой кортежа и совпадение по прозе)"))


class EveryGeometryOpIsWitnessedGeometrically(unittest.TestCase):
    def test_no_new_emitter_guards_only_what_it_set(self):
        naked = {name for name, body in _emitters().items()
                 if name not in _NO_GEOMETRY
                 and not _has_geometric_witness(body)}

        self.assertEqual(
            sorted(naked - set(_KNOWN_NAKED)), [],
            "these emitters create geometry and no postcondition can see it, "
            "so a wrong shape commits silently: "
            + ", ".join(sorted(naked - set(_KNOWN_NAKED))))

    def test_the_debt_list_shrinks_and_never_goes_stale(self):
        # A ratchet: once an emitter earns a geometric witness its name has to
        # leave this list, or the list stops describing anything real.
        naked = {name for name, body in _emitters().items()
                 if name not in _NO_GEOMETRY
                 and not _has_geometric_witness(body)}

        self.assertEqual(
            sorted(set(_KNOWN_NAKED) - naked), [],
            "these are listed as debt but are witnessed now — drop them: "
            + ", ".join(sorted(set(_KNOWN_NAKED) - naked)))

    def test_the_allowlist_names_only_real_emitters(self):
        # An entry left behind after a rename would silently exempt nothing —
        # or worse, keep exempting an op that has since grown geometry.
        missing = sorted(set(_NO_GEOMETRY) - set(_emitters()))

        self.assertEqual(missing, [], f"allowlist names no such emitter: {missing}")

    def test_every_exemption_carries_a_reason(self):
        for name, reason in _NO_GEOMETRY.items():
            with self.subTest(emitter=name):
                self.assertGreater(
                    len(reason.split()), 3,
                    f"{name} is exempt without saying why")

    def test_the_detector_recognises_a_naked_emitter(self):
        # Guard the guard: if the token list stopped matching, the check above
        # would pass vacuously for every op forever.
        self.assertFalse(_has_geometric_witness(
            'checks = [WitnessCheck(verdict_cs="__el.get_Parameter(X)")]'))

    def test_a_word_in_prose_is_not_a_witness(self):
        """ОПРОВЕРГАЮЩИЙ ТЕСТ ПОД НАСТОЯЩИЙ ДЕФЕКТ, найденный 09.08.2026.

        Дословная строка из ``_emit_dimension`` — английский комментарий, в
        котором есть слово ``Origin``. До починки прибор объявлял по ней весь
        эмиттер геометрически засвидетельствованным. Тело нарочно содержит
        ЕЩЁ и настоящий свидетель того же опа: тест обязан доказывать, что
        снята именно ПРОЗА, а не что ``Origin`` перестал существовать.
        """
        prose_only = (
            'def _emit_x(op):\n'
            '    """Docstring: get_BoundingBox is discussed, never called."""\n'
            '    # position of Origin ALONG the line — is an emergent property\n'
            '    return [WitnessCheck(verdict_cs="__el.get_Parameter(X)")]\n')
        self.assertFalse(
            _has_geometric_witness(prose_only),
            "слово в комментарии засчитано как свидетель — прибор снова меряет "
            "часть своего диапазона и отвечает «одет» тому, кто гол")

        real = prose_only.replace(
            'verdict_cs="__el.get_Parameter(X)"',
            'verdict_cs="__got = __el.Value ?? double.NaN;"')
        self.assertTrue(
            _has_geometric_witness(real),
            "вычёркивание прозы съело и настоящий свидетель — починка не "
            "имеет права двигать вердикт на исправном коде")

    def test_the_view_origin_is_an_input_and_never_a_witness(self):
        """Второй род того же дефекта: совпадение в АРГУМЕНТЕ СОЗДАНИЯ.

        ``__vw_.Origin`` — начало ВИДА, вход вычисления. Эмиттер удовлетворяет
        его тем, что сам же его и прочитал, поэтому свидетелем он быть не
        может по определению из шапки модуля. Та же форма, что у найденного
        волной нагрузок ``Plane.CreateByNormalAndOrigin``.
        """
        self.assertFalse(_has_geometric_witness(
            'code = f"XYZ __aO_{s} = __vw_{s}.Origin;\\n"\n'
            'checks = [WitnessCheck(verdict_cs="__el.get_Parameter(X)")]'))

    def test_every_debt_entry_carries_a_decision_and_a_deadline(self):
        """Храповик формы. Долг без дня, в который кто-то обязан ответить, —
        это не учёт, а архив: ровно так ``route_pipe_system`` простоял здесь
        тринадцать дней при живом свидетеле."""
        from kukai.ir import record_ratchet as rr
        self.assertEqual(
            rr.check_form(_KNOWN_NAKED.entries,
                          verdicts=_KNOWN_NAKED.verdicts,
                          standing=_KNOWN_NAKED.standing), [])
        overdue, stale = rr.check_expiry(_KNOWN_NAKED.entries)
        self.assertEqual(
            [n for n, _ in overdue], [],
            "срок вышел: перемерить прибором и закрыть, удалить либо написать "
            "решение заново — но не подвинуть дату")
        self.assertEqual(
            [n for n, _ in stale], [],
            "решение старше REVIEW_DAYS — подтвердить или пересмотреть")

    def test_the_detector_follows_one_delegation(self):
        # _emit_door is three lines long and hands everything to the hosted
        # emitter; treating it as naked was the detector's own first bug.
        self.assertTrue(_has_geometric_witness(
            "def _emit_door(op, ver, stamp):\n"
            "    return _emit_hosted(op, ver, stamp, 'door')\n"))

    def test_the_detector_accepts_each_geometric_form(self):
        for token in _GEOMETRY_HELPERS + _GEOMETRY_READS:
            with self.subTest(token=token):
                self.assertTrue(_has_geometric_witness(f"checks = [{token}]"))


if __name__ == "__main__":
    unittest.main()
