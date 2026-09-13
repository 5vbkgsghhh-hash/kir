"""LINKED DOCUMENTS: exactly how much the search DID NOT SEE.

Clash does not see linked documents at all, and this is honest: `link` rows in L0
are counted, their elements do not get hulls, and the `federation` axis declares
`complete=false`. What is disputable is not the incompleteness, but the NUMBER
that names the incompleteness.

    snapshot.py:  snap.census.linked_elements_unscored = origin["links_in_l0"]

The name declares ELEMENTS of linked files («в потоке есть, оболочек им никто не
строил» — a comment on the field itself), the code reads the NUMBER OF LINK
ROWS. A model with three links of forty thousand elements each is reported as
three. This is our main class of defect: a quantity is declared in one place and
read in another, and nothing forces them to match.

AGGRAVATING, AND ALSO THE CURE: the real number IS MEASURED and thrown away on
the adjacent line. The extractor puts `element_count`, taken from
`GetLinkDocument()` (`ir/decompile/extract.py`), into the link row, while
`read_decompile` never opens the link row at all — only `links += 1`. Asking the
authority here is literally cheaper than declaring.

WHAT THESE TESTS DO NOT COVER. They prove that the number for incompleteness is
named correctly, and say NOTHING about whether clash will find a collision in the
linked file: it still does not see them by construction, hulls are not built for
linked elements, and there is no reduction to a single coordinate system on this
path. Loud and precise incompleteness is not federated clash, it is an honest
report of its absence.
"""
from __future__ import annotations

import json
import pathlib

import pytest

from kir.clash import detect as D
from kir.clash import snapshot as S


def _l0(tmp: pathlib.Path, links: list[dict], *,
        declared_link_count: int | None = None) -> pathlib.Path:
    """A synthetic L0 in the MEASURED shape of a live artifact.

    The shape of the link row is taken from the emitter (`extract.py`, the loop
    over `RevitLinkInstance`), not invented: `element_count` is filled in only
    when `GetLinkDocument()` returned a document, otherwise it stays `null`.
    """
    d = tmp / "run"
    d.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = [
        {"record": "header", "schema_version": "1.0",
         "document": {"census": [{"key": "OST_Walls", "count": 2,
                                  "name": "Стены"}],
                      "doc_name": "t", "change_stamp": "t"}}]
    for i in range(2):
        rows.append({"record": "element", "element": {
            "element_id": str(100 + i), "category": "OST_Walls",
            "bbox_min_mm": [i, 0, 0], "bbox_max_mm": [i + 1, 1, 1]}})
    for row in links:
        rows.append({"record": "link", "link": row})
    rows.append({"record": "category_status",
                 "status": {"category": "OST_Walls", "expected_count": 2,
                            "extracted_count": 2, "state": "complete",
                            "error": None}})
    rows.append({"record": "footer", "element_count": 2, "category_count": 1,
                 "link_count": (len(links) if declared_link_count is None
                                else declared_link_count),
                 "stream_complete": True})
    (d / "L0.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
        encoding="utf-8")
    return d


def _link(name: str, count: int | None) -> dict:
    return {"element_id": name, "name": name, "loaded": count is not None,
            "element_count": count, "bbox_min_mm": None, "bbox_max_mm": None,
            "discipline": "ar"}


def test_the_number_of_unscored_elements_is_not_the_number_of_links(tmp_path):
    """THE MAIN COUNTEREXAMPLE. Three links, forty thousand elements, report «3»."""
    d = _l0(tmp_path, [_link("ar", 12_000), _link("kr", 20_000),
                       _link("ov", 8_000)])
    snap = S.build_from_decompile(d)
    assert snap.origin["links_in_l0"] == 3
    assert snap.census.linked_elements_unscored == 40_000, (
        "число названо ЭЛЕМЕНТАМИ, а посчитаны строки-связи")


def test_a_count_that_was_not_read_is_named_never_guessed(tmp_path):
    """The link is not loaded — `GetLinkDocument()` is empty, there IS NO number.

    Substituting zero here would replace one lie with another: "the link has zero
    elements" and "the link's element count was not read" are different
    statements, and the second is honest.
    """
    d = _l0(tmp_path, [_link("ar", 12_000), _link("kr", None),
                       _link("ov", None)])
    snap = S.build_from_decompile(d)
    assert snap.census.linked_elements_unscored == 12_000
    assert snap.census.links_without_element_count == 2
    assert snap.origin["links_in_l0"] == 3
    manifest = snap.join_manifest()
    assert manifest["linked_elements_unscored"] == 12_000
    assert manifest["links_without_element_count"] == 2


def test_a_sum_of_zero_must_not_read_as_a_model_without_links(tmp_path):
    """A TRAP OF THE SAME CLASS, AND IT IS WORSE THAN THE ORIGINAL.

    If federation completeness were decided by the SUM of elements, a model whose
    links are all unloaded would give a sum of 0 and read as a model WITHOUT
    links — that is, the report would turn green exactly where it saw the
    least. They can only be told apart by all three numbers at once, which is why
    all three are published.
    """
    d = _l0(tmp_path, [_link("ar", None), _link("kr", None)])
    snap = S.build_from_decompile(d)
    assert snap.census.linked_elements_unscored == 0
    assert snap.census.links_without_element_count == 2
    assert snap.origin["links_in_l0"] == 2

    clean = S.build_from_decompile(_l0(tmp_path / "clean", []))
    assert clean.census.linked_elements_unscored == 0
    assert clean.census.links_without_element_count == 0
    assert clean.origin["links_in_l0"] == 0


def test_a_model_without_links_publishes_three_zeroes(tmp_path):
    """The flip side: without links, all three numbers are required to be zero,
    otherwise the new counter simply paints everything red and stops meaning
    anything."""
    snap = S.build_from_decompile(_l0(tmp_path, []))
    assert snap.census.linked_elements_unscored == 0
    assert snap.census.links_without_element_count == 0
    assert snap.origin["links_in_l0"] == 0


def test_the_footer_link_count_must_match_the_stream(tmp_path):
    """The footer declares `link_count`, and to this day NO ONE has read
    it — even though `element_count` and `category_count` from the same footer
    are cross-checked against the stream and fail the run. A link lost during
    writing left the census self-consistent — exactly the hole the footer
    cross-check was set up for (review No. 10)."""
    d = _l0(tmp_path, [_link("ar", 12_000)], declared_link_count=4)
    with pytest.raises(S.SnapshotIntegrityError):
        S.build_from_decompile(d)


def test_the_federation_axis_is_wired_to_all_three_corrected_numbers(tmp_path):
    """THE RATCHET FIRED — AND THIS IS ITS CORRECT OUTCOME, NOT A REGRESSION.

    Here stood `test_completeness_still_ignores_federation_and_this_is_the_
    open_gap`: it asserted today's truth — `completeness_of()` HAS NO
    federation axis, so `detect(require_complete=True)` declares a search on a
    model with links complete — and it was required to turn red once the axis
    arrived. The axis arrived in the wave of 11.08.2026, the ratchet turned red,
    and its failure pointed exactly at the wiring. That was its purpose.

    Now the wiring is checked: the axis is required to publish ALL THREE numbers,
    because apart they do not substitute for one another.
    """
    d = _l0(tmp_path, [_link("ar", 12_000), _link("kr", 20_000),
                       _link("ov", None)])
    axis = S.build_from_decompile(d).coverage_axes(
        geometry_scope="mvp")["federation"]
    assert axis["linked_elements_unscored"] == 32_000
    assert axis["links_without_element_count"] == 1
    assert axis["links_in_l0"] == 3
    assert axis["complete"] is False
    assert D.completeness_of(S.build_from_decompile(d))["complete"] is False


def test_completeness_keys_on_links_not_on_the_sum_of_their_elements(tmp_path):
    """THE MERGE CONDITION, AND WITHOUT IT THE WAVE WOULD HAVE SHIPPED A NEW
    SILENTLY-WRONG OUTCOME.

    The axis was written when `linked_elements_unscored` held the NUMBER OF
    LINKS: then `linked == 0` meant "no links" and was correct BY ACCIDENT. The
    counter was fixed and now holds ELEMENTS — and the same expression became a
    lie on exactly the worst models: for a building all of whose links are
    unloaded, `element_count` is not read for a single one, the sum is zero, and
    the search would declare itself COMPLETE where it saw NOTHING AT ALL.

    Across the corpus this is not an edge case but the rule: 316 links out of 386
    have no number.
    """
    d = _l0(tmp_path, [_link("ar", None), _link("kr", None)])
    axis = S.build_from_decompile(d).coverage_axes(
        geometry_scope="mvp")["federation"]
    assert axis["linked_elements_unscored"] == 0
    assert axis["links_in_l0"] == 2
    assert axis["complete"] is False, (
        "поиск объявлен полным на здании, все связи которого выгружены — "
        "сумма элементов равна нулю ПОТОМУ ЧТО не прочитана ни одна")


def test_the_axis_stays_green_on_a_document_with_no_links(tmp_path):
    """The flip side: without links, the axis is required to be green, otherwise
    it just paints everything red and stops meaning anything.

    WHAT THESE THREE TESTS DO NOT COVER: they say nothing about whether it is
    CORRECT to treat incomplete federation as grounds for REFUSAL. 54 of 67
    decompiles have links, so refusing at snapshot construction would disable
    clash on eight buildings out of ten, and the direction chosen is "loud and
    precise", not "prohibitive". This is a DECISION, not a property of the code,
    and the next reader is entitled to reconsider it if the number changes.
    """
    axis = S.build_from_decompile(_l0(tmp_path, [])).coverage_axes(
        geometry_scope="mvp")["federation"]
    assert axis["complete"] is True
    assert axis["linked_elements_unscored"] == 0
    assert axis["links_without_element_count"] == 0
    assert axis["links_in_l0"] == 0
