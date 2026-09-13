"""THE SIGNATURE OF WHAT IS SHOWN DOES NOT DEPEND ON THE DELIVERY PATH
(F-008).

🔴 WHAT THIS GUARDS. Triangle indices in the stream are GLOBAL, and the
client REBASES them on merge (`scene-data.js`, `mergeScenes`). So one and
the same mesh, arriving as a TAIL, was signed by the server with its own
frame's indices (`0,1,2`), and by the client with the merged scene's indices
(`3,4,5`). Measured 29.08.2026:

    digest(whole)      = 73ea9fad66f809ff
    digest(base+tail)  = bd9551b401d2217f     <- MISMATCHED

and `live/transfer.py` answered `Refusal.SHOWN_MISMATCH`: the «Отправить в
Ревит» button was DEAD for anyone who kept the window open past one poll AND
built a `create_directshape`.

🔴 WHY THE GUARD IS SHAPED THIS WAY. A check that "the signatures are equal"
on an input WITHOUT MESHES is green by construction — and meshes are a
minority in today's fixtures. So here the SAME geometry is taken, delivered
by TWO paths, and it is guaranteed to contain a mesh. The second half (rule
2) is `test_целое_не_сдвинулось`: without it, a fix of "always rebase" would
slip past this file, and it would break agreement with the client on the
WHOLE scene.

🔴 AND THE CONNECTION IS GUARDED SEPARATELY, NOT JUST THE VALUE. The builder
could have a correct field that nobody fills in: the connection runs through
TWO modules (`live/showroom.scene_mesh_base` -> `viewer/live_scene`), and it
breaks silently. `test_витрину_действительно_спрашивают` counts the calls.
"""
from __future__ import annotations

import unittest
from unittest import mock

from kir.live import showroom as _showroom
from kir.viewer.live_scene import scene_from_programs

КЛЮЧ = ("проба-устройство", "проба-документ")

_ТЕЛО = {"vertices_mm": [[0, 0, 0], [1000, 0, 0], [0, 1000, 0]],
         "triangles": [[0, 1, 2]]}


def _оп(идент: str, сдвиг: float):
    меш = {"vertices_mm": [[x + сдвиг, y, z]
                           for x, y, z in _ТЕЛО["vertices_mm"]],
           "triangles": _ТЕЛО["triangles"]}
    return {"op": "create_directshape", "id": идент, "mesh": меш,
            "category": "generic_model", "name": идент}


def _программа(ops):
    return {"ir_version": "1.0", "intent": "проба", "ops": ops}


def _кадр(программы, *, whole: bool, first_position: int = 1) -> str:
    """A session frame. `первая позиция` is NOT decoration: it is part of
    the element identifier (`p2/d2` versus `p1/d2`), so the tail must carry
    ITS OWN position, the same one it would have inside the whole. Otherwise
    the test would be comparing DIFFERENT elements and turning red about its
    own artifact — I got caught by this myself while writing it in one
    pass.
    """
    # 🔴 THE ORIGIN IS PINNED, JUST AS ON THE LIVE PATH. `scene_from_session`
    # takes `live_origin(datums)` and passes it to BOTH frames: "the delta
    # must land in the same coordinate system as the base"
    # (`live_scene.py:449-451`). Without pinning, each frame computes the
    # origin from ITS OWN bounding box, coordinates get written as offsets
    # from different points, and the signatures would diverge for A SECOND
    # reason — not the indices. I got caught by this myself while writing
    # the guard: it was turning red about its own artifact, not about the
    # subject.
    _blob, meta = scene_from_programs(
        программы, doc_key="проба", session_key=КЛЮЧ, whole=whole,
        first_position=first_position, origin_mm=(0.0, 0.0, 0.0))
    return meta["shown_digest"]


class ПодписьНеЗависитОтПутиДоставки(unittest.TestCase):

    def setUp(self) -> None:
        _showroom.scene_reset(КЛЮЧ)

    def test_целое_и_база_плюс_хвост_дают_одну_подпись(self):
        ПЕРВАЯ = _программа([_оп("d1", 0.0)])
        ВТОРАЯ = _программа([_оп("d2", 5000.0)])
        целое = _кадр([ПЕРВАЯ, ВТОРАЯ], whole=True)
        _showroom.scene_reset(КЛЮЧ)
        _кадр([ПЕРВАЯ], whole=True)
        хвост = _кадр([ВТОРАЯ], whole=False, first_position=2)
        self.assertTrue(целое, "подписи нет — витрина не накопила ничего")
        self.assertEqual(
            хвост, целое,
            "подпись показанного поехала за ПУТЁМ ДОСТАВКИ: та же геометрия, "
            "два пути, разные подписи — кнопка переноса откажет "
            "SHOWN_MISMATCH")

    def test_целое_не_сдвинулось(self):
        """THE SECOND HALF: the fix must be ADDITIVE.

        For a whole scene the vertex base is zero by construction, and its
        bytes must stay the same — otherwise the server would agree with
        itself and disagree with the client, which already computes
        correctly on a whole scene.
        """
        сцена = [_программа([_оп("d1", 0.0)]), _программа([_оп("d2", 5000.0)])]
        целое = _кадр(сцена, whole=True)
        _showroom.scene_reset(КЛЮЧ)
        снова = _кадр(сцена, whole=True)
        self.assertEqual(снова, целое, "целая сцена сменила подпись")

    def test_витрину_действительно_спрашивают(self):
        """The connection runs through two modules and breaks SILENTLY.
        We count the calls."""
        обращений: list[tuple] = []
        настоящая = _showroom.scene_mesh_base

        def счётчик(key):
            обращений.append(key)
            return настоящая(key)

        _кадр([_программа([_оп("d1", 0.0)])], whole=True)
        with mock.patch.object(_showroom, "scene_mesh_base", счётчик):
            _кадр([_программа([_оп("d2", 5000.0)])], whole=False,
                  first_position=2)
        self.assertEqual(обращений, [КЛЮЧ],
                         "хвост построен, а базу вершин у витрины не спросили")

    def test_у_целого_базу_не_спрашивают(self):
        """And the reverse half: for a whole scene there is NOTHING to ask.

        Without it the guard above stays green even for a fix of "always
        ask", and that fix would shift the whole scene's signature.
        """
        обращений: list[tuple] = []
        with mock.patch.object(_showroom, "scene_mesh_base",
                               lambda key: обращений.append(key) or 0):
            _кадр([_программа([_оп("d1", 0.0)])], whole=True)
        self.assertEqual(обращений, [], "у целой сцены спросили базу вершин")


if __name__ == "__main__":
    unittest.main()
