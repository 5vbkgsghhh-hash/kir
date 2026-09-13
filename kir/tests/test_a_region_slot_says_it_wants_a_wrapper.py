"""The help for a region slot must not hide the wrapper the slot requires.

🔴 BOUGHT WITH FOUR ROUNDS, BY FOUR INDEPENDENT AUTHORS (13.09.2026, team
rehearsal). `create_floor_by_contour.contour` takes a REGION —
`{outer: shape, holes?: [shape…]}` — while the slot's help rendered only the
SHAPE grammar `rect | l | poly`. Two people and two model branches each read
"shape", wrote a shape, and spent one of three rounds on the refusal. The
refusal itself was correct the whole time; the help and the refusal simply said
different things, which is the two-carrier failure this tree keeps paying for.

The phrase now has ONE carrier, `contour.REGION_FORM_RU`, and this file pins
both users of it: the refusal and the region help.
"""
from kir import contour


def test_the_refusal_and_the_help_quote_the_same_phrase():
    from kir.diag import Diagnostic  # noqa: F401  (shape of the refusal channel)

    diagnostics = []
    result = contour.validate_region({"shape": "poly", "points_mm": [[0, 0], [1, 0], [1, 1]]},
                                     None, "op", "contour", diagnostics)
    assert result is None, "a bare shape is not a region"
    assert len(diagnostics) == 1
    assert contour.REGION_FORM_RU in diagnostics[0].message_ru, diagnostics[0].message_ru
    assert contour.REGION_FORM_RU in contour.region_forms_text("contour")


def test_the_help_shows_the_wrapper_before_the_shapes():
    text = contour.region_forms_text("contour")
    assert text.index(contour.REGION_FORM_RU) < text.index("форма —"), (
        "the outer half must be read first: an author who sees the shapes first "
        "writes a shape, which is exactly what happened four times")
    for shape in ("rect", "poly"):
        assert f'"shape":"{shape}"' in text, shape


def test_the_phrase_is_not_written_twice_in_the_tree():
    """A second hand-written copy is how the help and the refusal drifted apart."""
    import pathlib

    root = pathlib.Path(contour.__file__).resolve().parents[1]
    literal = "регион — {outer: форма, holes?: [формы]}"
    carriers = []
    for path in root.rglob("*.py"):
        if "/tests/" in path.as_posix() or path.name.startswith("test_"):
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if literal in text:
            carriers.append(path.relative_to(root).as_posix())
    assert carriers == ["kir/contour.py"], carriers
