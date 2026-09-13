"""The "single authority of coordinates" must know ALL coordinates.

🔴 WHAT THIS FILE COST. `fold._COORDINATE_FIELDS` names itself the single
list of coordinate fields: it is read by BOTH consumers — `component
._translate_leaf` (Δ-transfer of the component) and canon-localization. A
field missing from it does not move on transfer AND makes the canon NOT
translation-invariant, which is why merkle fails to merge two identical
apartments standing in different places.

The list itself recorded that this lesson was paid for TWICE: "xyz" (07-21,
furniture did not move) and "position_mm" (07-29, the cutline of a
stained-glass window stayed in place, reassembly died). The 08-25
measurement found SEVEN MORE, by running `_translate_leaf` on the delta
(630000, 12000, 0):

    field         op                          was
    top_xy        create_column               tilt 300 mm -> -629 700 mm
    points_mm     create_topography · floor contour · adaptive
    via_mm        contour splines
    path          create_flex_duct/pipe · railing · room_separator · grid
    path_mm       create_solid_sweep
    profile_mm    create_extrusion_roof
    axis_xy_mm    create_solid_revolve

About the column, in numbers: the bottom moves 630 m away, the top stays
put, and the 300 mm tilt becomes −629 700 mm — the column ends up lying
horizontally. About the axis of revolution: the op's postcondition computes
the volume as the profile's moment RELATIVE TO the axis, meaning a shift of
the profile without the axis would change the body's volume.

WHY A GUARD, NOT SEVEN NAMES. Three times in a row the name was added by
hand, and a fourth time came. The registry knows the kind of each parameter
(`pt_xy`, `path3`, `pts_xyz`), and `contour.SHAPE_FORMS` knows the fields of
the area. Both areas are GENERATED, and the guard checks them against the
list both ways: a new positional field must receive a decision — either a
coordinate or a named exception. There is no third option.

A BOUNDARY THAT IS NAMED, NOT IMPLIED. The authority looks up a field by
NAME, and names are NOT unique across ops: for `load_family` the parameter
`path` is a path to a FILE, of kind `str`. Here that is harmless (a string
is not a list, and transfer does not touch it), but relying on such luck is
not allowed, so the guard walks by KIND, not by name.
"""

from __future__ import annotations

import unittest

from kir import spec
from kir.contour import SHAPE_FORMS
from kir.decompile.component import _translate_leaf
from kir.decompile.fold import _ANGLE_FIELDS, _COORDINATE_FIELDS

#: Parameter kinds of the registry that carry an ABSOLUTE position.
#: `dir_xyz` is deliberately excluded: a direction does not change on transfer.
#: `pt_view2d` is a point in VIEW space (a sheet), not in the model.
ПОЗИЦИОННЫЕ_РОДА = frozenset({
    "pt_xy", "pt_xyz", "pts", "pts_list", "pts_xyz", "path", "path3",
})

#: Positional by KIND, but NOT subject to transfer — each with a reason.
#: The list must stay short: that is precisely the price of the kind being
#: readable by machine while the meaning is readable by a human.
НЕ_ПЕРЕНОСИТСЯ = {
    "delta_mm": "смещение, а не положение: move_elements двигает НА него, "
                "и сдвиг самого смещения удвоил бы перенос",
    "place_at": "точка внутри документа СЕМЕЙСТВА, а не проекта: "
                "у author_family своё начало координат",
    "anchor_uv_mm": "UV на плоскости профиля протяжки, а не мировые мм",
}

#: Area fields that carry coordinates. `points_mm` is the `poly` slot;
#: `via_mm` lives INSIDE the `splines` slot ({edge, via_mm}) and is
#: therefore named by hand.
КООРДИНАТЫ_ОБЛАСТИ = frozenset({"origin", "points_mm", "via_mm"})

#: Area slots that do NOT carry coordinates. A ratchet: a new slot must
#: receive a decision, not slip through.
СЛОТЫ_ОБЛАСТИ_БЕЗ_КООРДИНАТ = frozenset({
    "size_mm", "cut_mm", "corner", "rotation_deg", "arcs", "splines",
})

ДЕЛЬТА = (630000.0, 12000.0, 0.0)


def _позиционные_имена() -> dict[str, set[str]]:
    из_реестра: dict[str, set[str]] = {}
    for имя_опа, оп in spec.OPS.items():
        for p in оп.params:
            if str(p.kind) in ПОЗИЦИОННЫЕ_РОДА:
                из_реестра.setdefault(p.name, set()).add(имя_опа)
    return из_реестра


class АвторитетПолонПоРеестру(unittest.TestCase):

    def test_каждое_позиционное_поле_решено(self):
        """No positional field of the registry passes silently: it is
        either a coordinate or a NAMED exception."""
        нерешённые = {
            имя: sorted(опы)
            for имя, опы in _позиционные_имена().items()
            if имя not in _COORDINATE_FIELDS and имя not in НЕ_ПЕРЕНОСИТСЯ
        }
        self.assertEqual(
            нерешённые, {},
            f"{len(нерешённые)} позиционных полей вне единственного авторитета "
            f"и без названной причины: {нерешённые}. Такое поле не поедет при "
            f"Δ-переносе и сделает канон не трансляционно-инвариантным.")

    def test_исключения_не_протухли(self):
        """An exception whose parameter is no longer in the registry is a
        list that reads as complete while describing yesterday."""
        живые = set(_позиционные_имена())
        мёртвые = sorted(set(НЕ_ПЕРЕНОСИТСЯ) - живые)
        self.assertEqual(мёртвые, [],
                         f"исключения без параметра в реестре: {мёртвые}")

    def test_исключение_и_координата_не_пересекаются(self):
        """A field cannot be both transferable and not. Two truths about
        one quantity is a named defect of this tree."""
        оба = sorted(set(НЕ_ПЕРЕНОСИТСЯ) & set(_COORDINATE_FIELDS))
        self.assertEqual(оба, [], f"поле решено дважды и по-разному: {оба}")


class АвторитетПолонПоОбласти(unittest.TestCase):

    def test_координатные_поля_области_в_авторитете(self):
        нет = sorted(КООРДИНАТЫ_ОБЛАСТИ - _COORDINATE_FIELDS)
        self.assertEqual(нет, [],
                         f"поля области вне авторитета: {нет}. Контурный пол "
                         f"остался бы на исходном месте при переносе квартиры.")

    def test_новый_слот_области_не_просачивается(self):
        """A ratchet on the SCHEMA of the area: a slot for which no
        decision has been made here turns red the moment it is
        introduced, not a week later at the user's site."""
        слоты = {s.name for формы in SHAPE_FORMS.values() for s in формы}
        решено = КООРДИНАТЫ_ОБЛАСТИ | СЛОТЫ_ОБЛАСТИ_БЕЗ_КООРДИНАТ
        self.assertEqual(sorted(слоты - решено), [],
                         "у слота области нет решения о переносе")

    def test_КОНТРОЛЬ_угол_не_считается_координатой(self):
        """`rotation_deg` lives in its OWN list and is not subject to
        transfer: rotation does not change under a shift."""
        self.assertIn("rotation_deg", _ANGLE_FIELDS)
        self.assertNotIn("rotation_deg", _COORDINATE_FIELDS)


class ПереносПроверенПрогоном(unittest.TestCase):
    """The list alone is not enough: it could be complete and the transfer
    still not work. Here the question asked is about BEHAVIOR."""

    def _после(self, оп: str, params: dict) -> dict:
        return _translate_leaf({"op_name": оп, "params": params}, ДЕЛЬТА)["params"]

    def test_верх_наклонной_колонны_едет_вместе_с_низом(self):
        было = {"xy": [1000.0, 2000.0], "top_xy": [1300.0, 2000.0]}
        стало = self._после("create_column", dict(было))
        наклон_до = было["top_xy"][0] - было["xy"][0]
        наклон_после = стало["top_xy"][0] - стало["xy"][0]
        self.assertEqual(наклон_после, наклон_до,
                         f"наклон колонны сменился с {наклон_до} на "
                         f"{наклон_после}: верх не поехал за низом")

    def test_контур_пола_едет(self):
        стало = self._после("create_floor_by_contour", {"contour": {"outer": {
            "points_mm": [[0.0, 0.0], [4000.0, 0.0]],
            "splines": [{"edge": 0, "via_mm": [[100.0, 100.0]]}]}}})
        наружу = стало["contour"]["outer"]
        self.assertEqual(наружу["points_mm"][0], [630000.0, 12000.0])
        self.assertEqual(наружу["splines"][0]["via_mm"][0], [630100.0, 12100.0])

    def test_маршруты_и_профили_едут(self):
        случаи = [
            ("create_flex_duct", "path", [[0.0, 0.0, 3000.0]]),
            ("create_solid_sweep", "path_mm", [[0.0, 0.0, 0.0]]),
            ("create_extrusion_roof", "profile_mm", [[0.0, 0.0]]),
            ("create_topography", "points_mm", [[0.0, 0.0, 0.0]]),
            ("create_solid_revolve", "axis_xy_mm", [100.0, 200.0]),
        ]
        for оп, поле, значение in случаи:
            with self.subTest(оп=оп, поле=поле):
                стало = self._после(оп, {поле: значение})[поле]
                self.assertNotEqual(стало, значение,
                                    f"{оп}.{поле} остался на месте")

    def test_КОНТРОЛЬ_исключения_остаются_на_месте(self):
        """The instrument must also be able to NOT move something. A fix
        that shifted the `move_elements` offset would double the transfer —
        quieter and worse than the original defect."""
        for оп, поле, значение in (
                ("move_elements", "delta_mm", [10.0, 20.0, 0.0]),
                ("author_family", "place_at", [10.0, 20.0, 0.0]),
                ("create_solid_sweep", "anchor_uv_mm", [10.0, 20.0])):
            with self.subTest(оп=оп, поле=поле):
                стало = self._после(оп, {поле: list(значение)})[поле]
                self.assertEqual(стало, значение,
                                 f"{оп}.{поле} поехал, а не должен")

    def test_КОНТРОЛЬ_путь_к_файлу_не_координата(self):
        """For `load_family`, the field `path` is a string holding a path.
        The authority looks it up by name, and this is the only place
        where the name happens to coincide with the meaning of another kind."""
        стало = self._после("load_family", {"path": "C:/lib/Окно.rfa"})
        self.assertEqual(стало["path"], "C:/lib/Окно.rfa")


if __name__ == "__main__":
    unittest.main()
