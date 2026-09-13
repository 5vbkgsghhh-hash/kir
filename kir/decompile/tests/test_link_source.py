"""It is possible to read NOT ONLY the host: a link is a document too.

MEASURED 2026-07-30 on the public Snowdon Towers federation. Linked
documents are ALREADY open in the session (``Application.Documents.Size``
returned 5), and ``RevitLinkInstance.GetLinkDocument()`` hands back a ready
``Document``. So reading a link requires opening NOTHING — it is enough to
build collectors against it.

We could not have opened the link with a dialog anyway:
``UIApplication.OpenAndActivateDocument`` is documented as "may not be
called from inside an event handler", and our C# runs exactly there; a live
probe returned null without throwing an exception.

Each link is captured with ITS OWN snapshot and its own stamp — so neither
composite keys, nor a federated census, nor a dialect fix are needed. The
tests below guard exactly what makes this true: ALL collectors of one body
read THE SAME document, and a missing link is a loud refusal, not an empty
read.
"""
from __future__ import annotations

import re
import unittest

from kir.decompile.extract import (
    build_category_batch_cs,
    build_category_probe_cs,
    build_metadata_cs,
)
from kir.code_safety import validate_code_safety

TITLE = "Snowdon Towers Sample Architectural"


def _bodies(link_title):
    return {
        "batch": build_category_batch_cs("OST_Walls", link_title=link_title),
        "probe": build_category_probe_cs("OST_Walls", link_title=link_title),
        "metadata": build_metadata_cs(link_title=link_title),
    }


class SourceBindingTests(unittest.TestCase):

    def test_without_a_link_the_source_is_the_host(self) -> None:
        for name, code in _bodies(None).items():
            with self.subTest(body=name):
                self.assertIn("Document __src = doc;", code)
                # Resolving the link by name is not emitted at all.
                self.assertNotIn("__srcLi", code)
                self.assertNotIn("linked document not found", code)

    def test_the_document_identity_follows_the_source(self) -> None:
        """The name, project information, and worksets belong to the document BEING READ.

        Otherwise a link's snapshot would write the HOST's name into the L0
        header, and every subsequent check would run against a foreign
        identity without noticing the substitution.
        """
        code = build_metadata_cs(link_title=TITLE)
        for expr in ("__src.Title", "__src.ProjectInformation",
                     "__src.IsWorkshared", "FilteredWorksetCollector(__src)"):
            self.assertIn(expr, code)
        for expr in ("doc.Title", "doc.ProjectInformation", "doc.IsWorkshared"):
            self.assertNotIn(expr, code)

    def test_with_a_link_the_source_is_resolved_by_title(self) -> None:
        for name, code in _bodies(TITLE).items():
            with self.subTest(body=name):
                self.assertIn("GetLinkDocument", code)
                self.assertIn(f'"{TITLE}"', code)
                self.assertNotIn("Document __src = doc;", code)

    def test_a_missing_link_is_a_loud_refusal_not_an_empty_read(self) -> None:
        """An empty read would look like "there is nothing in the link"."""
        code = build_category_batch_cs("OST_Walls", link_title=TITLE)
        self.assertIn("if (__src == null) throw", code)
        self.assertIn("linked document not found or not loaded", code)

    def test_every_collector_in_a_body_reads_the_same_document(self) -> None:
        """Mixing the host and the link in one body is a silent lie.

        The census would count the host while elements arrived from the
        link; the census law would catch the discrepancy WITHOUT NAMING the
        reason. So no collector built against ``doc`` may remain in the
        body.
        """
        for name, code in _bodies(TITLE).items():
            with self.subTest(body=name):
                leaked = re.findall(r"FilteredElementCollector\(doc\)", code)
                # The one legitimate reference to the host is finding THE LINK ITSELF.
                allowed = code.count(
                    "foreach (RevitLinkInstance __srcLi in new "
                    "FilteredElementCollector(doc)")
                self.assertEqual(
                    len(leaked), allowed,
                    f"{name}: коллектор читает хозяина вместо связи")

    def test_emitted_bodies_stay_safe_for_both_sources(self) -> None:
        for link_title in (None, TITLE):
            for name, code in _bodies(link_title).items():
                with self.subTest(body=name, link=bool(link_title)):
                    self.assertIsNone(validate_code_safety(code))

    def test_the_title_is_a_c_sharp_literal_not_an_injection(self) -> None:
        """The document name arrives from outside and must travel as a literal."""
        code = build_category_batch_cs(
            "OST_Walls", link_title='Weird" ; DoEvil(); //')
        # A quote inside the name must arrive escaped, rather than
        # closing the literal and opening an executable tail.
        self.assertNotIn('"Weird" ;', code)
        self.assertIn('Weird\\"', code)


if __name__ == "__main__":
    unittest.main()


class ВсякоеЧтениеТелаИдётВИСТОЧНИК(unittest.TestCase):
    """🔴 THE GUARD ABOVE READ HALF ITS OWN INPUT, MEASURED 2026-08-25.

    `test_every_collector_in_a_body_reads_the_same_document` asks only about
    `FilteredElementCollector(doc)`. It does not see direct reads through
    the same `doc` — and there are five of them in the batch body plus one
    in the probe:

        doc.GetElement(__e.GetTypeId())   the element's type
        doc.GetElement(__levelId)         the level (in the shared helper)
        doc.GetElement(__phaseId)         the phase
        doc.IsWorkshared                  whether the document is workshared
        doc.GetWorksetTable()             the workset

    When reading a LINK, `__src` is the linked document and `doc` is the
    host, and these are DIFFERENT id spaces with overlapping numbers. A
    link element's type is looked up in the host: if the host happens to
    have an element with the same number (measured 2026-07-30 on
    snowdon_elec_v1: 1837 receipts and 20 foreign rows), all 43 probes ask
    for the WRONG type, its millimeters land in params, and the receipt
    writes an honest `type_hit`. Silently wrong numbers with a green
    outcome. If the element does not exist, all 43 answer `not_applicable`
    — a false "this class has no such parameter".

    ON THE SAME LINE the type name is resolved CORRECTLY, through
    `__src.GetElement`. One element, two truths about its own type.

    THE LAW'S TEMPLATE IS ALREADY IN THE TREE: the `metadata` body has not
    one direct `doc.` and reaches the host through the NAMED
    `__federationRoot` — seven times. So the law is enforceable, not merely
    desirable.
    """

    #: The one legitimate reference to the host is FINDING THE LINK ITSELF,
    #: and it builds a collector (`FilteredElementCollector(doc)`) rather than
    #: reading `doc.X`. Everything else genuinely needed from the host must
    #: call it by the name `__federationRoot`: a name makes the intent
    #: readable, `doc` does not.
    def test_в_теле_связи_нет_прямых_чтений_хозяина(self) -> None:
        for name, code in _bodies(TITLE).items():
            with self.subTest(body=name):
                без_комментариев = re.sub(r"//[^\n]*", "", code)
                утечки = re.findall(r"(?<![\w_.])doc\.\w+", без_комментариев)
                self.assertEqual(
                    sorted(set(утечки)), [],
                    f"{name}: {len(утечки)} чтений идут в ХОЗЯИНА, а тело "
                    f"читает СВЯЗЬ. Числа пространств совпадают, поэтому "
                    f"промах даёт не отказ, а чужое значение с зелёной "
                    f"квитанцией. Нужен __src — либо __federationRoot, если "
                    f"хозяин нужен по существу.")

    def test_КОНТРОЛЬ_образец_закона_остаётся_чистым(self) -> None:
        """`metadata` was clean before this fix and must remain so: otherwise
        there is no telling whether I fixed the law or bent it to fit the
        bodies."""
        код = build_metadata_cs(link_title=TITLE)
        self.assertNotIn("doc.", re.sub(r"//[^\n]*", "", код))
        self.assertIn("__federationRoot", код)

    def test_КОНТРОЛЬ_без_связи_источник_остаётся_хозяином(self) -> None:
        """Replacing `doc` with `__src` is safe exactly because, without a link,
        the binding declares `Document __src = doc;`. If that stops being
        true, the whole fix silently becomes wrong."""
        from kir.decompile.side_contract import source_binding_cs
        self.assertIn("Document __src = doc;", source_binding_cs(None))
