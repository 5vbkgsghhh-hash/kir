"""The side stage reads the SAME document as the main extraction.

MEASUREMENT 30.07, snapshot ``backend/data/decompile/snowdon_elec_v1`` — linked
electrical, captured from a plumbing window. The main extraction already knew how to read
the link, but the side stages did not: their collectors looked for the requested ids in the HOST.

    stage                        receipts    of which element_unresolved
    family_placement                 1837                       1770
    annotation                         89                         87
    curve / sketch / curtain      1 / 1 / 1                        3

And that was the BETTER half of the trouble. The second is worse: for 20 ids the host RETURNED an element with
the same numeric id, and the stage recorded it as a link row. Link element
``1442277`` is ``OST_ElectricalEquipment``, while in the placement index its
family is ``Tee - Generic`` (a HOST plumbing tee); ``1442799`` is
``OST_ConduitFitting``, ``Elbow - Generic`` in the index. An empty receipt loudly
says "did not read"; a row like this lies silently, and there is nothing to refute it with —
the two documents have DIFFERENT id spaces, and their numbers happen to coincide.

Hence the law that the tests below guard: ALL accesses to a document within
ONE emitted body go to ONE document (``__src``), and
the only legitimate access to the host is looking up the LINK ITSELF.
"""
from __future__ import annotations

import asyncio
import json
import re
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from kir.decompile import pipeline as pipe
from kir.decompile.annotation_extract import build_annotation_extract_cs
from kir.decompile.curtain_extract import build_curtain_extract_cs
from kir.decompile.curve_extract import build_curve_extract_cs
from kir.decompile.extract import _source_binding_cs
from kir.decompile.family_placement_extract import (
    build_family_placement_extract_cs,
)
from kir.decompile.geom_extract import (
    GEOMETRY_EXTRACT_SCHEMA_VERSION,
    build_geometry_extract_cs,
)
from kir.decompile.group_extract import build_group_extract_cs
from kir.decompile.mep_system_extract import build_mep_system_extract_cs
from kir.decompile.side_contract import source_binding_cs
from kir.decompile.sketch_extract import build_sketch_extract_cs
from kir.decompile.tag_extract import build_tag_extract_cs
from kir.decompile.tests.test_pipeline import FakePipelineBridge
from kir.code_safety import validate_code_safety

TITLE = "Snowdon Towers Sample Electrical"

#: Every side stage — one body per source. The list is complete
#: ON PURPOSE: a stage forgotten here is exactly the case that produced 1837
#: receipts, and the only defense against it is enumerating all the collectors.
STAGES = {
    "annotation": lambda title: build_annotation_extract_cs(
        ["1442277"], link_title=title),
    "tag": lambda title: build_tag_extract_cs(
        ["1442277"], revit_version=2024, link_title=title),
    "mep_system": lambda title: build_mep_system_extract_cs(
        ["1442277"], link_title=title),
    "family_placement": lambda title: build_family_placement_extract_cs(
        ["1442277"], link_title=title),
    "curve": lambda title: build_curve_extract_cs(
        ["1442277"], link_title=title),
    "sketch": lambda title: build_sketch_extract_cs(
        ["1442277"], link_title=title),
    "curtain": lambda title: build_curtain_extract_cs(
        ["1442277"], link_title=title),
    "group": lambda title: build_group_extract_cs(link_title=title),
    "geometry": lambda title: build_geometry_extract_cs(
        ["1442277"], link_title=title),
}


def _strip_comments(code: str) -> str:
    """Strip C# comments, WITHOUT touching string literals.

    Needed exactly so that a mention of ``doc`` in an explanation (in
    ``sketch_extract`` the signature ``Railing.Create(doc, ...)`` is quoted)
    is not counted as reading the document, and a real read inside a literal is not
    hidden behind a stray ``//``.
    """
    out: list[str] = []
    i = 0
    n = len(code)
    while i < n:
        ch = code[i]
        if ch == '"':
            out.append(ch)
            i += 1
            while i < n:
                if code[i] == "\\" and i + 1 < n:
                    out.append(code[i])
                    out.append(code[i + 1])
                    i += 2
                    continue
                out.append(code[i])
                closing = code[i] == '"'
                i += 1
                if closing:
                    break
            continue
        if ch == "/" and i + 1 < n and code[i + 1] == "/":
            while i < n and code[i] != "\n":
                i += 1
            continue
        if ch == "/" and i + 1 < n and code[i + 1] == "*":
            i += 2
            while i + 1 < n and not (code[i] == "*" and code[i + 1] == "/"):
                i += 1
            i += 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)


class SideStageSourceBindingTests(unittest.TestCase):

    def test_without_a_link_the_source_is_the_host(self) -> None:
        for stage, build in STAGES.items():
            with self.subTest(stage=stage):
                code = build(None)
                self.assertIn("Document __src = doc;", code)
                self.assertNotIn("__srcLi", code)
                self.assertNotIn("linked document not found", code)

    def test_with_a_link_the_source_is_resolved_by_title(self) -> None:
        for stage, build in STAGES.items():
            with self.subTest(stage=stage):
                code = build(TITLE)
                self.assertIn("GetLinkDocument", code)
                self.assertIn(f'"{TITLE}"', code)
                self.assertNotIn("Document __src = doc;", code)

    def test_a_missing_link_is_a_loud_refusal_not_an_empty_read(self) -> None:
        """"There is nothing in the link" is indistinguishable from success — so it is forbidden."""
        for stage, build in STAGES.items():
            with self.subTest(stage=stage):
                code = build(TITLE)
                self.assertIn("if (__src == null) throw", code)
                self.assertIn("linked document not found or not loaded", code)

    def test_every_read_in_a_body_goes_to_the_same_document(self) -> None:
        """The only legitimate access to the host is looking up the LINK ITSELF.

        What is checked is not "there is no ``doc`` collector," but something stronger: after
        subtracting the link preamble, the word ``doc`` does not occur in the body AT ALL.
        It was exactly ``doc.GetElement`` (not a collector) that sent 1770 ids of the placement
        stage into receipts and slipped in 20 foreign rows.
        """
        for stage, build in STAGES.items():
            for link_title in (None, TITLE):
                with self.subTest(stage=stage, link=bool(link_title)):
                    code = build(link_title)
                    binding = source_binding_cs(link_title)
                    self.assertIn(binding, code)
                    rest = _strip_comments(code.replace(binding, "", 1))
                    leaked = sorted({
                        match.group(0)
                        for match in re.finditer(r"\bdoc\b[^\s]{0,14}", rest)})
                    self.assertEqual(
                        [], leaked,
                        f"{stage}: тело читает хозяина вместо источника")

    def test_the_binding_is_emitted_before_the_first_read(self) -> None:
        """A local C# variable is not visible above its declaration.

        A stage where the binding arrived AFTER the helpers would fail to compile
        under Roslyn, rather than "read the wrong thing" — but finding this out would be
        possible only live, from the window that is currently occupied by decompiling.
        """
        for stage, build in STAGES.items():
            for link_title in (None, TITLE):
                with self.subTest(stage=stage, link=bool(link_title)):
                    code = build(link_title)
                    self.assertTrue(
                        code.startswith(source_binding_cs(link_title)),
                        f"{stage}: привязка источника не первая в теле")

    def test_emitted_bodies_stay_safe_for_both_sources(self) -> None:
        for stage, build in STAGES.items():
            for link_title in (None, TITLE):
                with self.subTest(stage=stage, link=bool(link_title)):
                    self.assertIsNone(validate_code_safety(build(link_title)))

    def test_the_title_is_a_c_sharp_literal_not_an_injection(self) -> None:
        """The document's name comes from outside and must travel as a literal."""
        for stage, build in STAGES.items():
            with self.subTest(stage=stage):
                code = build('Weird" ; DoEvil(); //')
                self.assertNotIn('"Weird" ;', code)
                self.assertIn('Weird\\"', code)

    def test_the_side_binding_is_the_same_text_as_the_main_one(self) -> None:
        """Two bindings would mean two truths about what is read; hence there is one.

        ``extract._source_binding_cs`` and ``side_contract.source_binding_cs``
        must produce BYTE-FOR-BYTE the same C#: the law "one body — one document"
        is checked against the text, and diverging texts would make the check
        green while the behavior differed.
        """
        for link_title in (None, TITLE, 'Weird" ; DoEvil(); //'):
            with self.subTest(link=link_title):
                self.assertEqual(
                    _source_binding_cs(link_title),
                    source_binding_cs(link_title))


class SideStageSourceWiringTests(unittest.TestCase):
    """WIRING, not just emission.

    The annotation wave of 30.07 passed all thirty of its tests and died at
    the seam: the defect was not in the stage and not in its C#, but in what
    the stage's tests did not touch. The source is exactly the same seam: a
    correct ``build_*_cs`` means nothing until the pipeline has passed it
    ``link_title``.
    """

    #: The full set of registered side stages. The list is CLOSED
    #: deliberately: a new stage that forgets the source must fail this
    #: test, not silently carry off another one and a half thousand ids in
    #: the receipt.
    REGISTERED = {
        "curve", "curtain", "sketch", "family_placement", "group",
        "annotation", "dimension", "tag", "mep_system", "geometry",
        # `join` was added on 18.08 together with the joins stage. It landed
        # here not through the author's care, but because the LIST TURNED RED
        # on its registration and demanded a decision — exactly what it is
        # closed for. The stage does hand off a source: the body starts with
        # `source_binding_cs`, and the "does it read the host" check passes
        # on both sides.
        "join",
    }

    def test_the_factory_hands_the_source_to_every_registered_stage(self):
        builders = pipe._default_cs_builders(
            revit_version=2024, link_title=TITLE)
        self.assertEqual(self.REGISTERED, set(builders))
        binding = source_binding_cs(TITLE)
        for stage, build in builders.items():
            with self.subTest(stage=stage):
                code = build(["1442277"])
                self.assertTrue(
                    code.startswith(binding),
                    f"{stage}: конвейер собрал тело без источника")
                rest = _strip_comments(code.replace(binding, "", 1))
                self.assertEqual(
                    [], sorted({m.group(0) for m in re.finditer(
                        r"\bdoc\b[^\s]{0,14}", rest)}),
                    f"{stage}: тело конвейера читает хозяина")

    def test_the_host_is_the_source_when_no_link_is_asked_for(self):
        for stage, build in pipe._default_cs_builders(
                revit_version=2024).items():
            with self.subTest(stage=stage):
                self.assertIn("Document __src = doc;", build(["1442277"]))

    def test_a_whole_run_asks_the_link_in_every_call_it_makes(self):
        """Through the WHOLE pipeline: side stages and probe D2 around them.

        The probe here is not decoration: a guard that counts the HOST
        around a stage reading a link would agree with itself under any edit
        inside the link — that is, it would stop being a guard while
        staying green.
        """
        bodies: list[str] = []

        class Recording(FakePipelineBridge):
            async def __call__(self, code: str, *, timeout_ms: int):
                bodies.append(code)
                return await super().__call__(code, timeout_ms=timeout_ms)

        with TemporaryDirectory() as tmp:
            bridge = Recording(link_title=TITLE)
            result = asyncio.run(pipe.run_decompile(
                bridge, out_dir=tmp, change_stamp="link-wiring-v1",
                link_title=TITLE))
        self.assertTrue(result.ok, msg=result.to_dict())
        # The stages this model actually feeds with ids.
        # `join` was placed between `group` and `geometry` on 18.08 — ORDER
        # here is significant and is therefore checked as a list, not a set:
        # side stages run one after another, and a reordering would be a
        # different run.
        self.assertEqual(
            ["curve", "sketch", "curtain", "family_placement", "group",
             "join", "geometry"],
            [call for call in bridge.side_calls
             if call != "open_model_profile"])

        binding = source_binding_cs(TITLE)
        # The revision guard is the ONLY legitimate read of the host beyond
        # looking up the link: it fingerprints the HOST document, and does
        # not catch a concurrent edit on the link (the ``_source_binding_cs``
        # caveat).
        guard = pipe._REVISION_FINGERPRINT_CS
        side = [
            code for code in bodies
            if any(marker in code for marker in (
                "kir-decompile-curve-extract", "kir-decompile-sketch-extract",
                "kir-decompile-curtain-extract",
                "kir-decompile-family-placement-extract",
                "kir-decompile-group-extract",
                GEOMETRY_EXTRACT_SCHEMA_VERSION))
        ]
        self.assertGreaterEqual(len(side), 6)
        for code in side:
            self.assertIn(binding, code)
            rest = _strip_comments(
                code.replace(guard, "", 1).replace(binding, "", 1))
            self.assertEqual(
                [], sorted({m.group(0) for m in re.finditer(
                    r"\bdoc\b[^\s]{0,14}", rest)}))

        probes = [code for code in bodies
                  if '{"count", __total}, {"levels", __scopes}' in code]
        self.assertTrue(probes, "проба Д2 не эмитировалась вовсе")
        for code in probes:
            self.assertIn(binding, code)

    def test_an_index_from_another_document_is_not_reused(self) -> None:
        """A row counter does not tell the host from the link apart — the
        source must.

        The catalog ``snowdon_elec_v1`` is a live example: its side indexes
        were taken by a link request and read from the host. The schema is
        correct, the row count is the same, the counter is flawless. Reusing
        such an index on a run against the link means inheriting someone
        else's document through the disk — even after the emission has been
        fixed.
        """
        with TemporaryDirectory() as tmp:
            host = FakePipelineBridge()
            first = asyncio.run(pipe.run_decompile(
                host, out_dir=tmp, change_stamp="link-reuse-v1"))
            self.assertTrue(first.ok, msg=first.to_dict())
            manifest = json.loads(
                (Path(tmp) / pipe._SIDE_MANIFEST_NAME).read_text("utf-8"))
            self.assertEqual(
                {None},
                {row["source"] for row in manifest["stages"].values()})

            # The same catalog, but now the LINK is being asked: no stage
            # has the right to arrive from disk.
            linked = FakePipelineBridge(link_title=TITLE)
            second = asyncio.run(pipe.run_decompile(
                linked, out_dir=tmp, change_stamp="link-reuse-v1",
                link_title=TITLE))
            self.assertTrue(second.ok, msg=second.to_dict())
            # `join` was added on 18.08 together with the joins stage. The
            # list is CLOSED deliberately: a new stage must demand a
            # decision rather than slip through in silence — and it did,
            # turning this line red.
            for stage in ("curve", "sketch", "curtain", "family_placement",
                          "group", "join", "geometry"):
                self.assertIn(stage, linked.side_calls)
            manifest = json.loads(
                (Path(tmp) / pipe._SIDE_MANIFEST_NAME).read_text("utf-8"))
            self.assertEqual(
                {TITLE},
                {row["source"] for row in manifest["stages"].values()})

            # And the same source a second time — reused, as it was.
            again = FakePipelineBridge(link_title=TITLE)
            third = asyncio.run(pipe.run_decompile(
                again, out_dir=tmp, change_stamp="link-reuse-v1",
                link_title=TITLE))
            self.assertTrue(third.ok, msg=third.to_dict())
            self.assertEqual([], [
                call for call in again.side_calls
                if call != "open_model_profile"])


if __name__ == "__main__":
    unittest.main()
