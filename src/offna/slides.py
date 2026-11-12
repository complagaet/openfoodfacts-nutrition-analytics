import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from pptx import Presentation
from pptx.presentation import Presentation as Deck
from pptx.util import Inches, Pt

from offna.config import PROJECT_ROOT

DOCS = PROJECT_ROOT / "docs"
RESULTS = DOCS / "results"
FIGURES = DOCS / "figures"
OUTLINE = DOCS / "SLIDES.md"
OUTPUT = DOCS / "slides.pptx"
TITLE_ROW = re.compile(r"^\| (\d+) \| ([^|]+) \| ([^|]+) \| ([^|]+) \|$")
NOTE = re.compile(r"^\*\*(\d+)\.\*\* (.+)$")
SLIDE_WIDTH = Inches(13.333)
SLIDE_HEIGHT = Inches(7.5)
BODY_FONT = Pt(18)
TABLE_FONT = Pt(12)
OWNER_PLACEHOLDER = "_TBD_"


@dataclass
class Slide:
    number: int
    title: str
    owner: str
    bullets: list[str] = field(default_factory=list)
    table: list[list[str]] | None = None
    figure: str | None = None
    notes: str = ""


def parse_outline(text: str) -> dict[int, Slide]:
    slides: dict[int, Slide] = {}
    for line in text.splitlines():
        row = TITLE_ROW.match(line.strip())
        if row and row.group(1).isdigit():
            number = int(row.group(1))
            slides[number] = Slide(number, row.group(2).strip(), row.group(4).strip(), [row.group(3).strip()])
    for line in text.splitlines():
        note = NOTE.match(line.strip())
        if note and int(note.group(1)) in slides:
            slides[int(note.group(1))].notes = note.group(2).strip()
    return slides


def load(name: str) -> dict:
    return json.loads((RESULTS / f"{name}.json").read_text(encoding="utf-8"))


def fmt(value: float, digits: int = 3) -> str:
    return f"{value:.{digits}f}".replace(".", ",")


def benchmark_table() -> list[list[str]]:
    rows = [["Вход", "Движок", "Медиана, с", "Пик RSS, МиБ"]]
    for label, block in load("benchmark")["results"].items():
        for engine in block["engines"]:
            rows.append(
                [
                    f"{label} ({block['rows']:,})",
                    engine["engine"],
                    fmt(engine["median_s"]),
                    fmt(engine["peak_rss_mib_max"], 0),
                ]
            )
    return rows


def model_table() -> list[list[str]]:
    report = load("model_report")
    rows = [["Метод", "macro-F1 (когорта правила)", "Accuracy"]]
    for model in report["models"]:
        metrics = model["rule_covered_test"]
        rows.append([model["model"], fmt(metrics["macro_f1"]), fmt(metrics["accuracy"])])
    for name, rule in report["rules"].items():
        rows.append([name, fmt(rule["rule_covered_test"]["macro_f1"]), fmt(rule["rule_covered_test"]["accuracy"])])
    return rows


def contribution_table() -> list[list[str]]:
    blocks = ["Данные и ETL", "Аудит и EDA", "Движки и SQL", "Nutri-Score", "Интерфейс и сдача"]
    return [["Блок", "Ответственный (решает команда)"], *[[block, OWNER_PLACEHOLDER] for block in blocks]]


def enrich(slides: dict[int, Slide]) -> None:
    etl, snapshot, version = load("etl_report"), load("full_snapshot"), load("model_report")["version_evidence"]
    dtype = etl["dtype_first_batch"]
    slides[3].bullets.append(f"Ревизия HF {snapshot['hf_revision'][:12]}…, sha256 {snapshot['sha256'][:12]}…")
    slides[5].bullets.append(
        f"{etl['rows_in']:,} строк за {fmt(etl['seconds'], 1)} с, пик RSS {fmt(etl['peak_rss_mib'], 0)} МиБ; "
        f"пачка: {fmt(dtype['default_mib'], 1)} → {fmt(dtype['optimised_mib'], 1)} МиБ"
    )
    slides[6].figure = "fig2_missing_by_country.png"
    slides[7].table = benchmark_table()
    slides[9].figure = "fig1_grade_share_by_food_group.png"
    slides[10].bullets.append(
        f"Где версии расходятся ({version['rows_where_2021_and_2023_differ']:,}): метка = 2023 в "
        f"{version['of_those_label_equals_2023']:.2%}"
    )
    slides[11].table = model_table()
    slides[12].table = contribution_table()


def add_text(slide, slide_spec: Slide, top: float, height: float) -> None:
    frame = slide.shapes.add_textbox(Inches(0.6), Inches(top), Inches(12.1), Inches(height)).text_frame
    frame.word_wrap = True
    for index, bullet in enumerate(slide_spec.bullets):
        paragraph = frame.paragraphs[0] if index == 0 else frame.add_paragraph()
        paragraph.text = f"• {bullet}"
        paragraph.font.size = BODY_FONT


def add_table(slide, rows: list[list[str]], top: float) -> None:
    shape = slide.shapes.add_table(len(rows), len(rows[0]), Inches(0.6), Inches(top), Inches(12.1), Inches(0.4))
    for r, row in enumerate(rows):
        for c, value in enumerate(row):
            cell = shape.table.cell(r, c)
            cell.text = value
            cell.text_frame.paragraphs[0].font.size = TABLE_FONT


def render(deck: Deck, spec: Slide) -> None:
    slide = deck.slides.add_slide(deck.slide_layouts[5])
    slide.shapes.title.text = f"{spec.number}. {spec.title}"
    add_text(slide, spec, 1.4, 1.6)
    if spec.table:
        add_table(slide, spec.table, 3.0)
    if spec.figure:
        slide.shapes.add_picture(str(FIGURES / spec.figure), Inches(2.5), Inches(2.9), height=Inches(4.4))
    owner = slide.shapes.add_textbox(Inches(9.5), Inches(7.0), Inches(3.6), Inches(0.4)).text_frame
    owner.text = f"Докладчик: {spec.owner}"
    slide.notes_slide.notes_text_frame.text = spec.notes


def build_slides(output: Path = OUTPUT) -> dict:
    slides = parse_outline(OUTLINE.read_text(encoding="utf-8"))
    enrich(slides)
    deck = Presentation()
    deck.slide_width, deck.slide_height = SLIDE_WIDTH, SLIDE_HEIGHT
    for number in sorted(slides):
        render(deck, slides[number])
    deck.save(output)
    return {"slides": len(slides), "output": output.name, "bytes": output.stat().st_size}
