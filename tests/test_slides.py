import pytest

pptx = pytest.importorskip("pptx")


def test_outline_has_twelve_slides_with_notes_and_visible_owner_placeholders() -> None:
    from offna.slides import OUTLINE, parse_outline

    slides = parse_outline(OUTLINE.read_text(encoding="utf-8"))
    assert sorted(slides) == list(range(1, 13))
    assert all(slide.notes for slide in slides.values())
    assert all(slide.owner == "_TBD_" for slide in slides.values())


def test_deck_renders_tables_figures_and_notes(tmp_path) -> None:
    from offna.slides import build_slides

    result = build_slides(tmp_path / "deck.pptx")
    deck = pptx.Presentation(str(tmp_path / "deck.pptx"))
    assert result["slides"] == len(deck.slides) == 12
    shapes = [shape for slide in deck.slides for shape in slide.shapes]
    assert sum(shape.has_table for shape in shapes if hasattr(shape, "has_table")) >= 3
    assert sum(shape.shape_type == 13 for shape in shapes) >= 2
    assert all(slide.notes_slide.notes_text_frame.text for slide in deck.slides)
