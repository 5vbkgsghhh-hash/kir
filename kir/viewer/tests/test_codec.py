"""The scene bytes contract. Every test is a REFUTATION of a specific way to
lie with the picture, not a check that the code merely ran.

The measurement this format exists for (10.08.2026, demo-v3, 84 120 hulls):
naive JSON at 21.08 MB against 4.84 MB here (0.77 MB after gzip). Bytes won
not on size but on the browser not having to parse 84 120 objects on the
main thread.
"""

import json
import struct
import unittest

from kir.viewer.codec import SCENE_MAGIC, STRIDE, SceneBuilder


def _decode(blob):
    assert blob[:8] == SCENE_MAGIC
    head_len = struct.unpack_from("<I", blob, 8)[0]
    header = json.loads(blob[12:12 + head_len].decode("utf-8"))
    return header, 12 + head_len


class CodecShape(unittest.TestCase):

    def test_header_declares_the_exact_body_length(self):
        """A header that lies about a body's length hands the client
        shifted buffers, and SILENTLY — the picture will assemble, just the
        wrong one."""
        builder = SceneBuilder()
        kind, slot = builder.add_box((0, 0, 0), (1000, 2000, 3000))
        builder.add_element(element_id="a", category="OST_Walls", level="L1",
                            trust=0, fidelity=2, kind=kind, slot=slot)
        blob = builder.finish({})
        header, base = _decode(blob)
        self.assertEqual(header["body_bytes"], len(blob) - base)
        self.assertEqual(
            header["body_bytes"],
            sum(b["length"] for b in header["buffers"]))

    def test_every_per_element_buffer_has_exactly_one_record_per_element(self):
        """A per-element buffer shorter than the census means elements with
        no attributes — that is, a building part of which has no honesty
        state."""
        builder = SceneBuilder()
        for i in range(7):
            kind, slot = builder.add_box((i, 0, 0), (i + 1, 1, 1))
            builder.add_element(element_id=f"e{i}", category="OST_Walls",
                                level="L1", trust=0, fidelity=2,
                                kind=kind, slot=slot)
        header, _ = _decode(builder.finish({}))
        sizes = {b["name"]: b["length"] for b in header["buffers"]}
        for name in ("elem_kind", "elem_trust", "elem_fidelity", "elem_cat",
                     "elem_level", "elem_slot"):
            self.assertEqual(sizes[name], 7 * STRIDE[name], name)

    def test_capsule_of_n_points_makes_n_minus_one_instances(self):
        """A polyline is a UNION of segments (`clash.geom.Capsule`). One
        instance for the whole polyline would draw a straight line where
        the run is jointed."""
        builder = SceneBuilder()
        kind, slot = builder.add_capsule(
            [(0, 0, 0), (100, 0, 0), (100, 100, 0), (100, 100, 100)], 25.0)
        builder.add_element(element_id="p", category="OST_PipeCurves",
                            level="L1", trust=0, fidelity=1, kind=kind,
                            slot=slot)
        header, _ = _decode(builder.finish({}))
        self.assertEqual(header["counts"]["capsule"], 3)

    def test_single_point_capsule_still_produces_one_instance(self):
        """A degenerate axis has no right to DISAPPEAR: a missing element is
        indistinguishable from an element that never existed."""
        builder = SceneBuilder()
        builder.add_capsule([(0, 0, 0)], 10.0)
        header, _ = _decode(builder.finish({}))
        self.assertEqual(header["counts"]["capsule"], 1)

    def test_prism_offsets_are_monotone_and_close_the_vertex_buffer(self):
        """Offsets are prefix sums. Non-monotonic ones give a negative
        chunk length, and unclosed ones give a silently truncated last
        footing."""
        builder = SceneBuilder()
        builder.add_prism((((0, 0), (10, 0), (10, 10)),
                           ((20, 20), (30, 20), (30, 30), (20, 30))), 0.0, 3000.0)
        blob = builder.finish({})
        header, base = _decode(blob)
        spans = {b["name"]: (base + b["offset"], b["length"])
                 for b in header["buffers"]}
        off, length = spans["prism_ofs"]
        values = struct.unpack_from(f"<{length // 4}I", blob, off)
        self.assertEqual(values[0], 0)
        self.assertTrue(all(values[i] <= values[i + 1]
                            for i in range(len(values) - 1)))
        self.assertEqual(values[-1] * STRIDE["prism_xy"],
                         spans["prism_xy"][1])

    def test_degenerate_box_keeps_its_zero_extent(self):
        """A zero-volume bounding box is 38.2 % of demo-v3. Inflating it to
        something visible would mean drawing a volume that is not in the
        data."""
        builder = SceneBuilder()
        builder.add_box((0, 0, 500), (1000, 1000, 500))
        blob = builder.finish({})
        header, base = _decode(blob)
        off = next(base + b["offset"] for b in header["buffers"]
                   if b["name"] == "box")
        _, _, _, _, _, half_z = struct.unpack_from("<6f", blob, off)
        self.assertEqual(half_z, 0.0)

    def test_origin_is_published_not_implied(self):
        """The codec subtracts a common origin so that float32 lands on the
        building's size, not on the distance to the geodetic system's
        origin. The client must be able to recover the absolute value —
        meaning the origin must travel in the header."""
        builder = SceneBuilder(origin_mm=(1_000_000.0, 2_000_000.0, 0.0))
        builder.add_box((1_000_000.0, 2_000_000.0, 0.0),
                        (1_001_000.0, 2_001_000.0, 3000.0))
        header, base = _decode(builder.finish({}))
        self.assertEqual(header["origin_mm"], [1_000_000.0, 2_000_000.0, 0.0])
        self.assertEqual(header["units"], "mm")

    def test_ids_are_one_per_element_and_recoverable(self):
        builder = SceneBuilder()
        for name in ("11", "22", "33"):
            kind, slot = builder.add_box((0, 0, 0), (1, 1, 1))
            builder.add_element(element_id=name, category="OST_Walls",
                                level=None, trust=0, fidelity=2, kind=kind,
                                slot=slot)
        blob = builder.finish({})
        header, base = _decode(blob)
        span = next(b for b in header["buffers"] if b["name"] == "ids")
        text = blob[base + span["offset"]:
                    base + span["offset"] + span["length"]].decode("utf-8")
        self.assertEqual(text.split("\n"), ["11", "22", "33"])

class BodyIsAlignedForTypedArrays(unittest.TestCase):
    """A TEST REFUTING THE 10.08 DEFECT, found by a client-side check.

    The body followed right after a header of arbitrary length, so `new
    Float32Array(buffer, offset, …)` threw `RangeError: start offset of
    Float32Array should be a multiple of 4` — meaning EVERY scene failed to
    open. On demo-v3 the header gave `base % 4 == 3`.

    Separately embarrassing: the codec's comment CLAIMED that views are
    built without copying, and that was an untruth of exactly the kind this
    whole package is written against. A comment is a specification; a
    specification the code does not fulfill is a defect, not a typo.
    """

    def _blob(self, elements):
        builder = SceneBuilder()
        for i in range(elements):
            kind, slot = builder.add_box((i, 0, 0), (i + 1, 1, 1))
            builder.add_element(element_id=f"e{i}",
                                category=f"OST_Cat{i % 3}",
                                level=f"L{i % 2}", trust=0, fidelity=2,
                                kind=kind, slot=slot,
                                label="тип " + "я" * (i % 7))
        return builder.finish({"run": "проба " + "х" * (elements % 11)})

    def test_body_starts_on_a_four_byte_boundary_for_any_header_length(self):
        """The header length is arbitrary: string tables and the census
        travel in it. Iterating over lengths is the only way to prove the
        padding works, not by accident."""
        for elements in range(1, 40):
            blob = self._blob(elements)
            _, base = _decode(blob)
            self.assertEqual(base % 4, 0, f"elements={elements}")

    def test_every_four_byte_buffer_starts_aligned(self):
        """Aligning the start of the body is not enough: a buffer that
        follows an odd-length neighbor will drift on its own. The buffer
        order is what holds this, and it is checked here, not in a
        comment."""
        for elements in (1, 5, 17, 33):
            blob = self._blob(elements)
            header, base = _decode(blob)
            for span in header["buffers"]:
                if span["stride"] in (4, 8, 24, 28):
                    self.assertEqual((base + span["offset"]) % 4, 0,
                                     f"{span[chr(110)+chr(97)+chr(109)+chr(101)]} elements={elements}")
                elif span["stride"] == 2:
                    self.assertEqual((base + span["offset"]) % 2, 0,
                                     f"elements={elements}")

    def test_padding_keeps_the_header_valid_json(self):
        """Padded with spaces, not zeros: a zero byte would break the header
        parse, and the scene would fail already at the JSON."""
        header, _ = _decode(self._blob(3))
        self.assertIsInstance(header, dict)
        self.assertIn("buffers", header)


class AxesRideOnEveryElement(unittest.TestCase):
    """Axes are a SEPARATE buffer, not a bit in `elem_fidelity`.

    The questions differ: "is the shape accurate" and "was the axis taken
    up for checking". Gluing them together would mean repeating exactly the
    conflation that made `unwitnessed_axes` have to be set up separately
    from the witness's green triple.
    """

    def _blob(self, axes_values):
        builder = SceneBuilder()
        for i, axes in enumerate(axes_values):
            kind, slot = builder.add_box((i, 0, 0), (i + 1, 1, 1))
            builder.add_element(element_id=f"e{i}", category="OST_Walls",
                                level="L1", trust=0, fidelity=2, kind=kind,
                                slot=slot, axes=axes)
        return builder.finish({})

    def test_one_byte_per_element(self):
        blob = self._blob([0, 4, 255, 7])
        header, _ = _decode(blob)
        span = next(b for b in header["buffers"] if b["name"] == "elem_axes")
        self.assertEqual(span["length"], 4)
        self.assertEqual(span["stride"], 1)

    def test_values_survive_the_round_trip(self):
        values = [0, 1, 2, 4, 7, 255]
        blob = self._blob(values)
        header, base = _decode(blob)
        span = next(b for b in header["buffers"] if b["name"] == "elem_axes")
        raw = struct.unpack_from(f"<{len(values)}B", blob,
                                 base + span["offset"])
        self.assertEqual(list(raw), values)

    def test_the_default_is_unjudgeable_and_not_clean(self):
        """A caller that forgot to pass the axes must get a gray "not
        looked at", not a green "checked". A default that errs toward
        green is a silent witness hidden in the signature."""
        builder = SceneBuilder()
        kind, slot = builder.add_box((0, 0, 0), (1, 1, 1))
        builder.add_element(element_id="e", category="OST_Walls", level=None,
                            trust=0, fidelity=2, kind=kind, slot=slot)
        blob = builder.finish({})
        header, base = _decode(blob)
        span = next(b for b in header["buffers"] if b["name"] == "elem_axes")
        self.assertEqual(
            struct.unpack_from("<B", blob, base + span["offset"])[0], 255)

    def test_the_bit_order_is_published_for_the_client(self):
        """A client that kept its own copy of the bit order would drift
        apart from the server on the very first new axis at the owner of
        the obligations table."""
        header, _ = _decode(self._blob([0]))
        self.assertEqual(header["axes_order"],
                         ["geometry", "topology", "semantic"])
        self.assertEqual(header["axes_unjudgeable"], 255)


class AxesContractMatchesHonesty(unittest.TestCase):
    """The codec duplicates the axis order BY VALUE, in order to stay clean
    stdlib.

    The duplication is legitimate exactly as long as a test holds it in
    place: without one, `honesty` would introduce a fourth axis, the codec
    would keep publishing three, and the client would read someone else's
    bits as its own — silently.
    """

    def test_order_and_sentinel_agree_with_the_vocabulary(self):
        from kir.viewer import codec, honesty
        self.assertEqual(codec._AXES_ORDER, honesty.AXES_ORDER)
        self.assertEqual(codec._AXES_UNJUDGEABLE, honesty.AXES_UNJUDGEABLE)

    def test_the_sentinel_cannot_collide_with_a_real_mask(self):
        """The mask occupies as many bits as there are axes. The signal
        "nothing to judge by" must sit outside their range, or three
        skipped axes would read as "not looked at"."""
        from kir.viewer import honesty
        self.assertGreater(honesty.AXES_UNJUDGEABLE,
                           (1 << len(honesty.AXES_ORDER)) - 1)
