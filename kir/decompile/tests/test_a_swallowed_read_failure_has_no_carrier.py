"""CLASS: a READ failure ships as ordinary absence, without a bearer.

One technique across six bearers (triage 02.09.2026): an empty ``catch``
in the emitted C#, or a silent default in Python, swallows a READ
REFUSAL, and it exits byte-for-byte identical to genuine absence. The law
this file is written against stands in the canon verbatim (§18.2): for
every requested id — either a ROW or a TYPED RECEIPT, silence is
forbidden; and alongside it: "a missing index and an empty index are
DIFFERENT facts," just as "the stage failed on the element" differs from
"the stage said nothing at all."

WHAT THIS FILE IS NOT — named because shape 54 was bought exactly this
way. The guard does NOT search for the literal ``catch { }``: the literal
is merely the APPEARANCE of the first case, and rewriting whitespace
inside the braces would slip past it silently. What is asked is a
STRUCTURAL property: for every ``catch`` block of the emitted text, the
BODY is taken (by bracket matching), comments are stripped out of it, and
an empty remainder is declared mute. ``catch (Exception __e) {   /* … */  }``
is just as mute as ``catch{}``.

WHAT IS CHECKED SEPARATELY AND NOT HERE, AND THIS IS NOT "CANNOT BE DONE"
(mandate clause 11a). The bodies COMPILE: seven builders across six Revit
versions — 42 of 42 OK against real Autodesk reference assemblies via the
:52412 service and `host_shim`, plus the `build_reextract_cs` bypass
branch on a 64-bit id (6 more). The instrument's FAIL control has been
run: removing the ``__GeomReadFailed`` declaration produces CS0103 at five
call sites. This check is not built in here because it requires a HOST
PORT that bare KIR does not have, by contract.

WHAT NEITHER OF THE TWO PROVES: the emitted body is a fragment of Revit's
Execute method, and only Revit EXECUTES it. A live throw from a live
accessor is NOT removed by this file and cannot be; what is checked is the
TEXT of the emission — exactly what the already-standing neighbor
``test_census_category_failure`` checks.
"""
from __future__ import annotations

import re
import unittest

from kir.decompile.curtain_extract import (
    CURTAIN_EXTRACT_SCHEMA_VERSION,
    CellAddressState,
    CurtainFailureReason,
    CurveState,
    build_curtain_extract_cs,
    extract_curtain_topology,
)
from kir.decompile.extract import build_category_batch_cs, build_metadata_cs
from kir.decompile.geometry_store import (
    GEOMETRY_HELPER_CS,
    parse_geometry,
)
from kir.decompile.schema import L0Document
from kir.decompile.geom_extract import build_geometry_extract_cs
from kir.decompile import reextract as RE
from kir.decompile.reextract import (
    ReExtractError,
    build_reextract_cs,
    build_room_reextract_cs,
    parse_reextract_rows,
)
from kir.decompile.sketch_extract import build_sketch_extract_cs


def mask_comments_and_strings(cs: str) -> str:
    """Text of the same length, with comments and literals replaced by
    spaces.

    🔴 THE INSTRUMENT LIED ABOUT ITSELF ON THE VERY FIRST RUN, and this is
    written down here rather than cleaned up. The first revision searched
    for ``catch`` in the raw text and counted 103 mute ones across eight
    bodies. Five of them were the WORD ``catch`` inside a COMMENT —
    including inside paragraphs explaining why there is no longer an
    empty ``catch`` here. In other words, the instrument counted its own
    prose about the defect as instances of the defect, and the number grew
    from the defect being fixed.

    Masking preserves LENGTH and line breaks, so offsets and line numbers
    remain the source text's own numbers, and curly braces inside literals
    no longer throw off the matching.
    """

    out = list(cs)
    index = 0
    length = len(cs)

    def blank(start: int, stop: int) -> None:
        for position in range(start, min(stop, length)):
            if out[position] != "\n":
                out[position] = " "

    while index < length:
        char = cs[index]
        if char == "/" and index + 1 < length and cs[index + 1] == "/":
            stop = cs.find("\n", index)
            stop = length if stop < 0 else stop
            blank(index, stop)
            index = stop
        elif char == "/" and index + 1 < length and cs[index + 1] == "*":
            stop = cs.find("*/", index + 2)
            stop = length if stop < 0 else stop + 2
            blank(index, stop)
            index = stop
        elif char == "@" and index + 1 < length and cs[index + 1] == '"':
            stop = index + 2
            while stop < length:
                if cs[stop] == '"':
                    if stop + 1 < length and cs[stop + 1] == '"':
                        stop += 2
                        continue
                    stop += 1
                    break
                stop += 1
            blank(index, stop)
            index = stop
        elif char in '"\'':
            quote = char
            stop = index + 1
            while stop < length:
                if cs[stop] == "\\":
                    stop += 2
                    continue
                if cs[stop] == quote:
                    stop += 1
                    break
                stop += 1
            blank(index, stop)
            index = stop
        else:
            index += 1
    return "".join(out)


def catch_blocks(cs: str) -> list[tuple[int, str | None]]:
    """(offset, BODY) for every ``catch`` in the C# text.

    ``None`` instead of a body means a ``catch`` without a block — a
    defect in its own right. The parse is structural: the optional filter
    in parentheses is skipped, the body is taken by matching braces.
    """

    cs = mask_comments_and_strings(cs)
    found: list[tuple[int, str | None]] = []
    for match in re.finditer(r"\bcatch\b", cs):
        index = match.end()
        while index < len(cs) and cs[index].isspace():
            index += 1
        if index < len(cs) and cs[index] == "(":
            depth = 0
            while index < len(cs):
                if cs[index] == "(":
                    depth += 1
                elif cs[index] == ")":
                    depth -= 1
                    if depth == 0:
                        index += 1
                        break
                index += 1
            while index < len(cs) and cs[index].isspace():
                index += 1
        if index >= len(cs) or cs[index] != "{":
            found.append((match.start(), None))
            continue
        depth = 0
        end = index
        while end < len(cs):
            if cs[end] == "{":
                depth += 1
            elif cs[end] == "}":
                depth -= 1
                if depth == 0:
                    break
            end += 1
        found.append((match.start(), cs[index + 1:end]))
    return found


def _without_comments(body: str) -> str:
    body = re.sub(r"/\*.*?\*/", "", body, flags=re.S)
    body = re.sub(r"//[^\n]*", "", body)
    return body.strip()


def is_silent(body: str | None) -> bool:
    return body is None or _without_comments(body) == ""


def silent_catch_lines(cs: str) -> list[int]:
    return [
        cs.count("\n", 0, offset) + 1
        for offset, body in catch_blocks(cs)
        if is_silent(body)
    ]


def _bodies() -> dict[str, str]:
    """The input is assembled by PRODUCTION CODE, not hand-copied.

    A hand-written fixture would be guarding itself: this same
    measurement has already been bought by this tree ("a fixture from a
    reconciled pair," shape 48).
    """

    return {
        "extract.build_metadata_cs": build_metadata_cs(),
        "extract.build_category_batch_cs":
            build_category_batch_cs("OST_Walls"),
        "curtain_extract.build_curtain_extract_cs":
            build_curtain_extract_cs(["1"]),
        "geom_extract.build_geometry_extract_cs":
            build_geometry_extract_cs(["1"]),
        "sketch_extract.build_sketch_extract_cs":
            build_sketch_extract_cs(["1"]),
        "reextract.build_reextract_cs": build_reextract_cs(["1"]),
        "reextract.build_room_reextract_cs": build_room_reextract_cs(["1"]),
        "geometry_store.GEOMETRY_HELPER_CS": GEOMETRY_HELPER_CS,
    }


#: 🔴 A RATCHET, AND IT IS LOCKED BY EQUALITY, NOT BY AN INEQUALITY.
#:
#: The numbers were taken 02.09.2026 by running this same file on a
#: FROZEN copy (``git archive HEAD``) and on the tree after the wave:
#: **97 -> 79**. Equality, not "<=",
#: because a ratchet that distinguishes only GROWTH cannot tell the
#: DIRECTION of a discrepancy (canon, "the ratchet on a generated block"):
#: an improvement must force someone to read the diff and lower the
#: number by hand, or the next wave will close three mute ones and not
#: notice that it introduced a fourth.
#:
#: The number here is NOT a measure of quality. It is a measure of WHAT WE
#: DO NOT SEE: every mute catch is a read refusal that slipped into the
#: artifact indistinguishably from a fact about the building. Bodies share
#: helpers (``__PutGeometry`` rides in both extract and reextract), so the
#: column cannot be summed — it is a count of PLACES IN THE TEXT, not a
#: count of distinct sites.
SILENT_CATCH_BUDGET: dict[str, int] = {
    # was 12
    "extract.build_metadata_cs": 11,
    # was 31 (the body absorbs GEOMETRY_HELPER_CS in full)
    "extract.build_category_batch_cs": 27,
    # was 10
    "curtain_extract.build_curtain_extract_cs": 7,
    "geom_extract.build_geometry_extract_cs": 0,
    # was 1
    "sketch_extract.build_sketch_extract_cs": 0,
    # was 29
    "reextract.build_reextract_cs": 24,
    "reextract.build_room_reextract_cs": 10,
    # was 4
    "geometry_store.GEOMETRY_HELPER_CS": 0,
}


class ЧислоНемыхПерехватовЗаперто(unittest.TestCase):
    """The class does not grow silently: it has a NUMBER, and that number
    lives in the tree."""

    def test_каждое_тело_держит_объявленное_число(self) -> None:
        measured = {
            name: len(silent_catch_lines(cs))
            for name, cs in _bodies().items()
        }
        self.assertEqual(
            measured, SILENT_CATCH_BUDGET,
            "число немых `catch` разошлось с объявленным. ВВЕРХ — заведён "
            "новый глотатель отказа чтения (§18.2: молчание запрещено). "
            "ВНИЗ — его починили: опусти число здесь, прочитав диф, а не "
            "подгоняя.")

    def test_разбор_видит_и_фильтр_и_комментарий(self) -> None:
        """The parser itself must distinguish the appearances — otherwise
        it guards only one.

        A control on the parser, not on the product: three spellings of
        one mute catch, and one that is NOT mute.
        """
        self.assertEqual(silent_catch_lines("try { } catch { }"), [1])
        self.assertEqual(silent_catch_lines("try { } catch {\n\n}"), [1])
        self.assertEqual(
            silent_catch_lines("try { } catch (Exception __e) { // тишина\n}"),
            [1])
        self.assertEqual(
            silent_catch_lines("try { } catch { __row[\"k\"] = \"x\"; }"), [])


class ШестьНосителейВолны(unittest.TestCase):
    """By name — the sites for whose sake the wave was set up in the
    first place."""

    def test_f340_принадлежность_линии_не_теряет_отказ(self) -> None:
        """F-340: internal access to SketchPlane left behind ``none``.

        ``none`` means "captured and NOT determined" — a fact about the
        LINE. A throw from the internal accessor left behind exactly
        that, and a fact about our READING shipped as a fact about the
        model. The state has a name (``LineOwner.READ_FAILED``), and it
        must be set here.
        """
        self.assertIn("try { __sp = __ce.SketchPlane; }", GEOMETRY_HELPER_CS)
        self.assertNotIn(
            "try { __sp = __ce.SketchPlane; } catch { }", GEOMETRY_HELPER_CS,
            "немой перехват вернулся: отказ чтения плоскости снова "
            "неотличим от «плоскости нет»")

    def test_f340_габарит_и_положение_называют_отказ(self) -> None:
        """F-340: bbox and Location are two independent reads, both
        mute."""
        self.assertIn('"geom_read_failed"', GEOMETRY_HELPER_CS)
        for field in ("bbox", "location", "rotation", "sketch_plane"):
            self.assertIn(
                f'__GeomReadFailed(__row, "{field}")', GEOMETRY_HELPER_CS,
                f"чтение {field} не оставляет квитанции")

    def test_f038_отказ_наборов_снимает_ЗАМЕР_а_не_ставит_ноль(self) -> None:
        """F-038: a failed worksets collector reported a full model.

        ``worksets_closed`` and ``worksharing`` are NOT WRITTEN AT ALL when
        the read fails: no key means "not measured"
        (``L0Document.partial_read_measured``), whereas a zero would mean
        "measured, everything open."
        """
        body = mask_comments_and_strings(build_metadata_cs())
        self.assertIn("__wsThrew", body, "признак отказа чтения наборов "
                                         "не заведён")
        guard = body.find("if (!__wsThrew)")
        self.assertGreater(guard, 0, "сторож `if (!__wsThrew)` отсутствует")
        for key in ("__worksetsClosed", "__worksharing;"):
            written = body.find("] = " + key)
            self.assertGreater(
                written, guard,
                f"{key} пишется ДО сторожа: упавший коллектор снова "
                "неотличим от полностью прочитанной модели")

    def test_f210_видимость_имеет_три_исхода(self) -> None:
        """F-210: "the measurement did not happen" arrived as the number
        0.

        The expectation is DERIVED from the protocol's declared constants,
        not copied in here as a third bearer: a list of outcomes that
        drifted from the emission would stay silent exactly where it must
        scream (shape 48).
        """
        body = build_reextract_cs(["1"])
        self.assertIn(f'"{RE.ACTIVE_VIEW_VISIBILITY_STATE_KEY}"', body)
        for state in RE.ACTIVE_VIEW_VISIBILITY_STATES:
            self.assertIn(f'"{state}"', body, f"исход {state} не назван")
        self.assertIn(f'"{RE.ACTIVE_VIEW_VISIBILITY_ERROR_KEY}"', body)
        # THE NUMBER SHIPS ONLY WHEN MEASURED: the consumer reads the
        # field as an integer, and for it `null` means "there was no
        # block," not "a visible zero."
        masked = mask_comments_and_strings(body)
        written = masked.find("] =\n    __visState ==")
        self.assertGreater(
            written, 0,
            "счёт видимости пишется безусловно — несостоявшийся замер снова "
            "неотличим от настоящего нуля")

    def test_f213_пропуск_без_улики_больше_не_снимает_недостачу(self) -> None:
        """F-213: the parser subtracted out ANY id named by the response
        itself.

        The input is the WIRE form of the bridge's response; there is no
        production code to assemble it offline (C# inside Revit produces
        it), so the field names are taken from the protocol's DECLARED
        constants rather than copied by hand: the emission writes them
        under the same name, and this is checked below by a separate
        assertion.
        """
        unproved = {
            "elements": [],
            RE.SKIPPED_TYPES_KEY: ["42"],
        }
        with self.assertRaises(ReExtractError):
            parse_reextract_rows(unproved, requested_ids=["42"])

        proved = dict(unproved, **{
            RE.SKIPPED_TYPE_PROOF_KEY: [
                {"element_id": "42", RE.SKIPPED_PROOF_CLASS_FIELD: "WallType"},
            ],
        })
        self.assertEqual(
            parse_reextract_rows(proved, requested_ids=["42"]), [])

        # The bridge has no right to answer a question it was not asked.
        intruder = {
            "elements": [],
            RE.SKIPPED_TYPES_KEY: ["99"],
            RE.SKIPPED_TYPE_PROOF_KEY: [
                {"element_id": "99", RE.SKIPPED_PROOF_CLASS_FIELD: "WallType"},
            ],
        }
        with self.assertRaises(ReExtractError):
            parse_reextract_rows(intruder, requested_ids=["42"])

        # AND THE SECOND HALF: the emission must PRODUCE the evidence. A
        # parser that requires a field the bridge does not send would shut
        # down re-reading entirely — a refusal bought by its own fix.
        body = build_reextract_cs(["1"])
        self.assertIn(f'"{RE.SKIPPED_TYPE_PROOF_KEY}"', body)
        self.assertIn(f'"{RE.SKIPPED_PROOF_CLASS_FIELD}"', body)
        self.assertIn("__el.GetType().Name", body,
                      "класс пропущенного элемента не читается — улика "
                      "была бы словом моста о самом себе")

    def test_f072_неизвестный_род_геометрии_отказывает(self) -> None:
        """F-072: the traversal knew Solid/GeometryInstance/Mesh and
        stayed silent about anything else."""
        body = build_geometry_extract_cs(["1"])
        self.assertIn("geometry_object_kind_unsupported", body,
                      "у неизвестного рода GeometryObject нет отказа: "
                      "существующая геометрия пропадает из улик молча")

    def test_f076_непрочитанный_уклон_кровли_называет_себя(self) -> None:
        """F-076: a throw from DefinesSlope/SlopeAngle made the slope
        flat."""
        body = build_sketch_extract_cs(["1"])
        self.assertIn("__slopeReadFailed", body,
                      "отказ чтения уклона не имеет носителя: кровля "
                      "пересобирается более плоской, чем источник")

    def test_f058_детский_отказ_витража_не_становится_топологией(self) -> None:
        """F-058: a failed read of a child arrived as the default
        string.

        The expected literals are DERIVED from the state dictionaries, not
        copied by hand: if they drifted apart, hand-copied ones would keep
        both sides silent at once.
        """
        body = build_curtain_extract_cs(["1"])
        for state in (CurveState.READ_FAILED, CellAddressState.READ_FAILED):
            self.assertIn(
                f'"{state.value}"', body,
                f"эмиссия не умеет сказать {state.value}: отказ чтения "
                "ребёнка снова уедет топологией")
        # Three sites: grid lines, panels, mullions — each its own.
        self.assertEqual(body.count('"read_failed"'), 3)
        # And the wall has a reason under the SAME NAME as the other
        # indices.
        self.assertEqual(CurtainFailureReason.READ_FAILED.value,
                         CurveState.READ_FAILED.value)


_BBOX_ONLY_ROW = {
    "geom_kind": "bbox_only", "curve_kind": None,
    "p0_mm": None, "p1_mm": None, "rotation_deg": None,
    "bbox_min_mm": None, "bbox_max_mm": None,
}

#: The L0 header from the F-038 registry repro, verbatim.
_HEADER = {
    "doc_name": "t", "revit_version": "2024", "units": "mm",
    "change_stamp": "s", "levels": [], "grids": [], "rooms": [],
    "project_info": {}, "elements": [],
}


class ТриСостоянияВместоДвух(unittest.TestCase):
    """The Python half: a read refusal is DISTINGUISHABLE, not merely
    recorded."""

    def test_f340_пустой_список_и_отсутствие_ключа_разные_факты(self) -> None:
        legacy = parse_geometry(dict(_BBOX_ONLY_ROW))
        clean = parse_geometry(dict(_BBOX_ONLY_ROW, geom_read_failed=[]))
        failed = parse_geometry(
            dict(_BBOX_ONLY_ROW, geom_read_failed=["bbox", "location"]))

        self.assertIsNone(legacy.read_failed)
        self.assertEqual(clean.read_failed, ())
        self.assertEqual(failed.read_failed, ("bbox", "location"))

        # What was not measured is NOT declared complete — that was
        # exactly the guess.
        self.assertFalse(legacy.capture_is_complete)
        self.assertTrue(clean.capture_is_complete)
        self.assertFalse(failed.capture_is_complete)

        # And all three are DISTINGUISHABLE at the output, not just
        # internally.
        shapes = [legacy.to_element_fields(), clean.to_element_fields(),
                  failed.to_element_fields()]
        self.assertNotIn("geom_read_failed", shapes[0])
        self.assertEqual(len({repr(sorted(s.items(), key=str))
                              for s in shapes}), 3)

    def test_f038_упавший_коллектор_наборов_не_объявляет_модель_полной(
            self) -> None:
        """The F-038 registry repro, verbatim, but with a THIRD input.

        Previously the outcome "the collector crashed" arrived
        byte-for-byte identical to "read everything, worksets open":
        `is_partial_read=False` with `partial_read_measured=True`. Now it
        has neither of the two keys — and `partial_read_measured` tells
        the truth.
        """
        read_ok = L0Document.from_dict(dict(
            _HEADER, worksharing=True,
            worksets=[{"id": "1", "name": "N", "open": True}],
            worksets_closed=0))
        # This is now what a response looks like when reading the
        # worksets throws: BOTH keys are absent (see `build_metadata_cs`).
        read_failed = L0Document.from_dict(dict(_HEADER, worksets=[]))

        self.assertTrue(read_ok.partial_read_measured)
        self.assertFalse(read_failed.partial_read_measured)
        self.assertFalse(read_ok.is_partial_read)
        self.assertFalse(read_failed.is_partial_read)
        # This is exactly the distinction that used to be missing: two
        # different facts no longer answer the question "was it measured"
        # identically.
        self.assertNotEqual(read_ok.partial_read_measured,
                            read_failed.partial_read_measured)


def _curtain_wall_row(*, line_state: str) -> dict:
    """ONE curtain wall with one grid line in the given state.

    The wire form of the bridge's response; there is no production code
    to assemble it offline — C# inside Revit produces it. So the state's
    name is NOT hardcoded here: it arrives as a parameter from
    ``CurveState``, and the fact that the emission writes exactly that
    name is checked by a separate assertion against the C# text.
    """

    return {
        "wall_id": "500", "status": "ok",
        "reason": None, "typed_reason": None, "elapsed_ms": None,
        "host_kind": "wall",
        "default_panel_type_id": None,
        "default_panel_type_name": None,
        "default_panel_state": "not_captured",
        "default_panel_source": None,
        "auto_mullion_types": {"slots": {}, "state": "not_captured"},
        "grid_layout": {"slots": {}, "state": "not_captured"},
        "u_grid_lines": [{
            "line_id": "501",
            "curve_state": line_state,
            "p0_mm": None, "p1_mm": None,
            "existing_segment_count": 0,
            "skipped_segment_count": 0,
            "locked": None,
        }],
        "v_grid_lines": [], "panels": [], "mullions": [],
    }


class КвитанцияВитражаДоезжаетДоЧитателя(unittest.TestCase):
    """F-058, the second half: a fix is useless if nothing calls it.

    Canon shape 53: before counting a fix as done, ask WHO CALLS IT. The
    emission learned to say ``read_failed`` — but until decompile derives
    a receipt from that, the wall still ships as SUCCESSFUL.
    """

    def _extract(self, line_state: str):
        return extract_curtain_topology({
            "schema_version": CURTAIN_EXTRACT_SCHEMA_VERSION,
            "walls": [_curtain_wall_row(line_state=line_state)],
        })

    def test_прочитанная_стена_квитанции_не_получает(self) -> None:
        """PASS control: without a read refusal there must be NO receipt.

        Without it, the guard would stay green even for an instrument
        that slaps a receipt onto every wall indiscriminately — that is,
        one that fails to distinguish the subject at all.
        """
        extraction = self._extract(CurveState.CURVED_UNSUPPORTED.value)
        self.assertEqual(extraction.failures, ())
        self.assertEqual(len(extraction.records), 1)

    def test_непрочитанный_ребёнок_даёт_типизированную_квитанцию(self) -> None:
        extraction = self._extract(CurveState.READ_FAILED.value)
        # The index row REMAINS: the topology is honest for the part that
        # was read.
        self.assertEqual(len(extraction.records), 1)
        self.assertEqual(len(extraction.failures), 1)
        failure = extraction.failures[0]
        self.assertEqual(failure.wall_id, "500")
        self.assertEqual(failure.typed_reason,
                         CurtainFailureReason.READ_FAILED)
        self.assertIn("u_grid_lines=1", failure.reason)


if __name__ == "__main__":
    unittest.main()
