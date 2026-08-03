"""shape_emit — эмиссия create_directshape (парный файл к ops_shape.py, ровно
как arch_emit.py к ops_arch.py и struct_emit.py к ops_struct.py).

Своя зона волны: этот модуль не трогает ни один другой ops_*.py и ни один
другой *_emit.py. authoring.py получает аддитивно импорт и одну строку в
_EMITTERS — тот же минимальный шов, которым подключились волны каркаса и АР.

Переиспользовано из authoring.py БЕЗ ИЗМЕНЕНИЙ (импортом, не копией): _cs,
_safe, _stamp_block, _stamp_readback. Все имена Revit API взяты из замера на
живом компайл-сервисе (:52412, 2021-2026, 29.07) — таблица замера в шапке
ops_shape.py.

ФОРМА ЭМИССИИ И ПОЧЕМУ ИМЕННО ТАКАЯ. Вершинный массив выписывается ОДИН раз,
треугольники — массивом целых индексов, грани собираются циклом:

    XYZ[] __vx_S = new XYZ[] { P(...), ... };      // каждая вершина однажды
    int[] __tx_S = new int[] { i, j, k, ... };     // 3 числа на грань
    for (...) __tb_S.AddFace(new TessellatedFace(new List<XYZ>{ ... }, ...));

Прямолинейная альтернатива — выписать три точки на каждую грань — раздувает
исходник втрое (вершина закрытого меша принадлежит в среднем шести граням) и,
что важнее, ТЕРЯЕТ структуру: по такому C# уже не видно, где кончается вход и
начинается его развёртка. В нынешней форме эмитированный C# содержит ровно те
два массива, что были в IR, поэтому обратный разбор эмиссии точен побайтово, а
не приблизителен (см. parse_emitted_mesh ниже и round-trip тест).

Замер размера (тот же сервис, 2021 и 2026) — линейно, без обрыва: 1 600
треугольников = 49 КБ / 26 мс, 12 544 = 412 КБ / 187 мс. Предел реестра
MAX_TRIANGLES=4096 взят по этому замеру с запасом; разбор числа — в шапке
mesh.py.

TARGET=MESH / FALLBACK=SALVAGE — И ПОЧЕМУ НЕ ABORT, ХОТЯ ХОТЕЛОСЬ ИМЕННО ЕГО.

Первая редакция этого эмиттера ставила Target=Mesh и Fallback=Abort по прямому
рассуждению: Salvage («использовать все ПРИГОДНЫЕ данные») — это буквально
тихое усечение входа, часть граней молча не доедет, элемент появится, и
снаружи это успех; Abort же обещал громкий отказ. Рассуждение было верным,
вывод — нет.

Ворота Roslyn на эту пару ЗЕЛЁНЫЕ 6/6: перечисления существуют, свойства
существуют, C# собирается на всех шести версиях. А в RevitAPI.xml эталонного
пакета, в примечании к TessellatedShapeBuilder.Build, дословно (проверено в
2021 и в 2026 — текст идентичен):

    Currently only "Solid/Abort", "AnyGeometry/Mesh" and "Mesh/Salvage"
    target/fallback combinations are supported.

То есть Mesh/Abort — НЕ поддерживаемая комбинация, и узнали бы мы об этом
первым живым прогоном, а не компиляцией. Ровно тот класс, ради которого имена
здесь проверяются замером: собралось — не значит построит.

Поддерживаемых пар три, и выбор между ними — снова о честности:

  * Solid/Abort      — требует замкнутого тела; открытая оболочка (а это
                       половина осмысленных мешей) была бы отвергнута;
  * AnyGeometry/Mesh — Revit сам решает, солид или меш, и разница снаружи не
                       видна, хотя смысл результата разный;
  * Mesh/Salvage     — всегда меш, но Salvage молчит об отброшенном.

Взята Mesh/Salvage, и молчание Salvage закрыто НЕ надеждой, а свидетелем:
проверка числа граней вычитывает Mesh.NumTriangles с ПОСТРОЕННОГО элемента и
сверяет с числом присланных треугольников. Отбросил Salvage хоть одну грань —
постусловие не выполнено, транзакция откатывается, пользователь видит
названный отказ. Там, где API не умеет падать громко, громкость делает
свидетель; это и есть разделение труда, на котором стоит компилятор.

Поэтому свидетель числа граней здесь НЕСУЩИЙ, а не украшение: удалить его —
значит вернуть тихое усечение.
"""
from __future__ import annotations

from kukai.ir.authoring import _cs, _safe, _stamp_block, _stamp_readback
from kukai.ir.emit_model import WitnessCheck
from kukai.ir.emit_utils import cs_line_comment_fragment, refuse_stmt
from kukai.ir.mesh import mesh_bbox
from kukai.ir.ops_shape import DIRECTSHAPE_CATEGORIES

#: Короткая метка в ALL_MODEL_MARK. Comments занят штампом владения A5
#: (_stamp_block), поэтому человекочитаемая этикетка едет в Mark — и ТОЛЬКО
#: если поле пустое: затирать чужое значение ради своей подписи значит начать
#: с той самой тихой правки, против которой всё это написано.
HONEST_MARK = "KIR DirectShape: геометрия без BIM-смысла (нет типа/параметров)"


def _xyz_literals(verts: list) -> str:
    return ", ".join(
        f"P({round(v[0], 2)}, {round(v[1], 2)}, {round(v[2], 2)})"
        for v in verts)


def emit_directshape(op: dict, ver: str, stamp: str,
                     isolation: str = "atomic") -> tuple[str, str, list, str]:
    """Меш -> DirectShape. Оси версий нет: всё, что здесь названо, замерено 6/6.

    Возвращает (decl, create, checks, readback) — контракт эмиттеров пакета.
    """
    oid = op["id"]
    s = _safe(oid)
    mesh = op["mesh"]
    verts = mesh["vertices_mm"]
    tris = mesh["triangles"]
    member = DIRECTSHAPE_CATEGORIES[op["category"]]
    n_tris = len(tris)

    # ОБЪЯВЛЕНИЯ — ВО ВНЕШНЕЙ ОБЛАСТИ. При isolation="per_op" блок создания и
    # блоки постусловий/квитанции попадают в РАЗНЫЕ области видимости, и
    # переменная, объявленная внутри create, свидетелю не видна (CS0103 —
    # ровно на этом шве уже падала первая версия эмиттера ограждений).
    decl = (f"DirectShape __el_{s} = null;\n"
            f"bool __lbl_{s} = false;\n"
            f"string __out_{s} = null;")

    idx = ", ".join(str(i) for t in tris for i in t)
    create = (
        f"// create_directshape {cs_line_comment_fragment(oid)} — "
        f"{len(verts)} вершин, {n_tris} треугольников\n"
        f"ElementId __cat_{s} = new ElementId(BuiltInCategory.{member});\n"
        # Категория проверяется У ДОКУМЕНТА, а не по нашей таблице: категория
        # может быть выключена в шаблоне проекта, и тогда CreateElement
        # отдаст null уже после того, как мы решили, что всё хорошо.
        f"if (!DirectShape.IsValidCategoryId(__cat_{s}, doc)) {{ "
        f"{refuse_stmt(oid, _cs('категория недопустима для DirectShape в этом документе'), isolation)} }}\n"
        f"XYZ[] __vx_{s} = new XYZ[] {{ {_xyz_literals(verts)} }};\n"
        f"int[] __tx_{s} = new int[] {{ {idx} }};\n"
        f"TessellatedShapeBuilder __tb_{s} = new TessellatedShapeBuilder();\n"
        f"__tb_{s}.OpenConnectedFaceSet(false);\n"
        f"for (int __i_{s} = 0; __i_{s} < __tx_{s}.Length; __i_{s} += 3)\n{{\n"
        f"    __tb_{s}.AddFace(new TessellatedFace(new List<XYZ> {{ "
        f"__vx_{s}[__tx_{s}[__i_{s}]], __vx_{s}[__tx_{s}[__i_{s} + 1]], "
        f"__vx_{s}[__tx_{s}[__i_{s} + 2]] }}, ElementId.InvalidElementId));\n}}\n"
        f"__tb_{s}.CloseConnectedFaceSet();\n"
        # Пара ровно из поддерживаемых (RevitAPI.xml, Build): Mesh/Salvage.
        # Молчание Salvage закрывает свидетель числа граней — см. шапку.
        f"__tb_{s}.Target = TessellatedShapeBuilderTarget.Mesh;\n"
        f"__tb_{s}.Fallback = TessellatedShapeBuilderFallback.Salvage;\n"
        f"__tb_{s}.Build();\n"
        f"TessellatedShapeBuilderResult __tr_{s} = __tb_{s}.GetBuildResult();\n"
        f"__out_{s} = __tr_{s}.Outcome.ToString();\n"
        f"if (__tr_{s}.Outcome == TessellatedShapeBuilderOutcome.Nothing) {{ "
        f"{refuse_stmt(oid, _cs('Revit не построил тело из этого меша (Outcome=Nothing)'), isolation)} }}\n"
        f"__el_{s} = DirectShape.CreateElement(doc, __cat_{s});\n"
        f"if (__el_{s} == null) {{ "
        f"{refuse_stmt(oid, _cs('создание DirectShape вернуло null'), isolation)} }}\n"
        f"__el_{s}.SetShape(__tr_{s}.GetGeometricalObjects());\n"
        f"__el_{s}.Name = {_cs(op['name'])};\n"
        # ЭТИКЕТКА В САМОЙ МОДЕЛИ. get_Parameter вернёт null, если параметра у
        # элемента нет — тогда этикетки просто не будет, и квитанция скажет
        # об этом честно (false), а не промолчит. Непустое чужое значение не
        # трогаем никогда.
        f"Parameter __mk_{s} = __el_{s}.get_Parameter(BuiltInParameter.ALL_MODEL_MARK);\n"
        f"if (__mk_{s} != null && !__mk_{s}.IsReadOnly && "
        f"string.IsNullOrEmpty(__mk_{s}.AsString()))\n"
        f"    __lbl_{s} = __mk_{s}.Set({_cs(HONEST_MARK)});\n"
        + _stamp_block(f"__el_{s}", f"{stamp}:{oid}"))

    from kukai.ir import spec
    tol = spec.OPS["create_directshape"].tolerances["bbox_mm"]
    xmin, ymin, zmin, xmax, ymax, zmax = mesh_bbox(verts)

    checks: list[WitnessCheck] = [
        # ГАБАРИТ ПО ТРЁМ ОСЯМ. Общий bbox_extents_witness проверяет только XY
        # — он писался для перекрытий, у которых Z задаёт уровень. У меша Z —
        # такая же полноправная координата входа, как X и Y, и свидетель,
        # молчащий о ней, подписал бы геометрию, которую не смотрел (§18.3).
        WitnessCheck(
            obligation_key="bbox",
            reader_cs=f"    var __bb_{s} = __el_{s}.get_BoundingBox(null);\n",
            verdict_cs=(
                f"    if (__bb_{s} == null) __post.Add({_cs(oid + ': нет BoundingBox')});\n"
                f"    else if (Math.Abs(MM(__bb_{s}.Min.X) - {round(xmin, 2)}) > {tol} || "
                f"Math.Abs(MM(__bb_{s}.Max.X) - {round(xmax, 2)}) > {tol} ||\n"
                f"             Math.Abs(MM(__bb_{s}.Min.Y) - {round(ymin, 2)}) > {tol} || "
                f"Math.Abs(MM(__bb_{s}.Max.Y) - {round(ymax, 2)}) > {tol} ||\n"
                f"             Math.Abs(MM(__bb_{s}.Min.Z) - {round(zmin, 2)}) > {tol} || "
                f"Math.Abs(MM(__bb_{s}.Max.Z) - {round(zmax, 2)}) > {tol})\n"
                f"        __post.Add({_cs(oid + ': bbox extents mismatch (geometry)')});\n"),
            message="bbox extents mismatch (geometry)",
            tol_key="bbox_mm", style="else_block"),
        # ЧИСЛО ГРАНЕЙ ЧИТАЕТСЯ С ПОСТРОЕННОГО ЭЛЕМЕНТА. Это не пересчёт
        # нашего же входа: get_Geometry возвращает то, что Revit реально
        # положил в элемент. Если он пересоберёт триангуляцию (склеит
        # компланарные грани), свидетель ОТКАЖЕТ — громко и с числами, а не
        # промолчит. Живьём это ещё не проверялось; направление отказа
        # выбрано так, чтобы неизвестное поведение проявилось шумом, а не
        # тишиной.
        WitnessCheck(
            obligation_key="triangles",
            reader_cs=(f"    int __tc_{s} = 0;\n"
                       f"    var __ge_{s} = __el_{s}.get_Geometry(new Options());\n"),
            verdict_cs=(
                f"    if (__ge_{s} == null) __post.Add({_cs(oid + ': построенная геометрия не читается (geometry)')});\n"
                f"    else\n    {{\n"
                f"        foreach (GeometryObject __go_{s} in __ge_{s})\n        {{\n"
                f"            Mesh __ms_{s} = __go_{s} as Mesh;\n"
                f"            if (__ms_{s} != null) __tc_{s} += __ms_{s}.NumTriangles;\n"
                f"        }}\n"
                f"        if (__tc_{s} != {n_tris})\n"
                f"            __post.Add({_cs(oid + f': built mesh triangle count != {n_tris} (geometry)')});\n"
                f"    }}\n"),
            message="built mesh triangle count mismatch (geometry)",
            style="guard"),
    ]

    # КВИТАНЦИЯ СВОЯ, А НЕ _readback_block: общий блок сообщает LocationCurve и
    # type_name, которых у DirectShape нет ПО ПОСТРОЕНИЮ, и молчит о том
    # единственном, что о нём обязательно сказать. Поля ниже — этикетка,
    # доезжающая до пользователя: не «мы построили здание», а «мы построили
    # меш, и вот чего у него нет».
    readback = (
        f"// witness {cs_line_comment_fragment(oid)}\n{{\n"
        f"    var __rb = new Dictionary<string, object>();\n"
        f"    __rb[\"id\"] = __el_{s}.Id.ToString();\n"
        f"    __rb[\"name\"] = __el_{s}.Name;\n"
        f"    __rb[\"category\"] = {_cs(op['category'])};\n"
        f"    __rb[\"triangles\"] = {n_tris};\n"
        f"    __rb[\"vertices\"] = {len(verts)};\n"
        f"    __rb[\"kind\"] = \"direct_shape_mesh\";\n"
        # Что Revit на самом деле собрал (Mesh/Sheet/Solid/Mixed/Nothing).
        # Пять членов, а не три; на первом живом прогоне это первое, что стоит
        # прочитать, и стоит оно одной строки.
        f"    __rb[\"build_outcome\"] = __out_{s};\n"
        f"    __rb[\"bim_semantics\"] = \"none\";\n"
        f"    __rb[\"has_type\"] = false;\n"
        f"    __rb[\"schedulable_as_building_element\"] = false;\n"
        f"    __rb[\"human_editable\"] = false;\n"
        f"    __rb[\"honest_label_written\"] = __lbl_{s};\n"
        f"    __rb[\"warning\"] = {_cs('DirectShape — геометрия без BIM-смысла: у элемента нет типа и параметров, в спецификации он не попадёт как строительный элемент, и вручную его не отредактировать. Это не стена/перекрытие/кровля, даже если выглядит похоже.')};\n"
        + _stamp_readback(f"__el_{s}") +
        f"    __results[{_cs(oid)}] = __rb;\n}}")

    return decl, create, checks, readback


# ── обратный разбор ЭМИССИИ (офлайн round-trip) ─────────────────────────────

def parse_emitted_mesh(csharp: str, oid: str) -> dict:
    """Достаёт меш обратно из эмитированного C#.

    Существует потому, что round-trip обязан замыкаться на АРТЕФАКТЕ, а не на
    нашем намерении: сравнивать вход с той же питон-структурой, из которой мы
    его эмитировали, значит проверять переменную саму на себя. Здесь читается
    ровно тот текст, который поедет в Revit.

    Возвращает {"vertices_mm", "triangles"}; поднимает ValueError, если в
    тексте нет массивов этого опа.
    """
    import re

    s = _safe(oid)
    vm = re.search(r"XYZ\[\] __vx_" + re.escape(s) + r" = new XYZ\[\] \{(.*?)\};",
                   csharp, re.S)
    tm = re.search(r"int\[\] __tx_" + re.escape(s) + r" = new int\[\] \{(.*?)\};",
                   csharp, re.S)
    if vm is None or tm is None:
        raise ValueError(f"в эмиссии нет массивов меша для опа {oid!r}")
    verts = [[float(c) for c in m]
             for m in re.findall(
                 r"P\(\s*(-?[\d.eE+]+),\s*(-?[\d.eE+]+),\s*(-?[\d.eE+]+)\s*\)",
                 vm.group(1))]
    flat = [int(x) for x in re.findall(r"-?\d+", tm.group(1))]
    tris = [flat[k:k + 3] for k in range(0, len(flat), 3)]
    return {"vertices_mm": verts, "triangles": tris}
