"""PDF timetable export for the CCSync class schedule.

A4 portrait, official LSPU-ACAD-SF-003-style layout:
Republic / university / province, College of Computer Studies, class schedule,
program-year-section line, 7-column period grid and prepared-by block.

The official LSPU seal and Bagong Pilipinas mark are read from
  frontend/static/images/lspu-seal.png
  frontend/static/images/bagong-pilipinas.png
"""
from io import BytesIO
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Image,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
IMAGES_DIR = PROJECT_ROOT / "frontend" / "static" / "images"

PAGE_WIDTH = A4[0]
MARGIN_X = 48
CONTENT_WIDTH = PAGE_WIDTH - 2 * MARGIN_X  # 499.3 pt
COL_WIDTH = CONTENT_WIDTH / 7              # 71.3 pt
HEADER_ROW_HEIGHT = 15
BODY_ROW_HEIGHT = 20.16

SEMESTER_LINE = "First Semester, Academic Year 2026-2027"
PERIODS = [
    "7:00-7:30", "7:30-8:00", "8:00-8:30", "8:30-9:00",
    "9:00-9:30", "9:30-10:00", "10:00-10:30", "10:30-11:00",
    "11:00-11:30", "11:30-12:00", "12:00-12:30", "12:30-1:00",
    "1:00-1:30", "1:30-2:00", "2:00-2:30", "2:30-3:00",
    "3:00-3:30", "3:30-4:00", "4:00-4:30", "4:30-5:00",
]
BLACK = colors.HexColor("#000000")
INK = colors.HexColor("#111111")


def _register_university_font():
    """Use the Old English face that matches the official form when available."""
    candidates = (
        Path(r"C:\Program Files\Microsoft Office\root\vfs\Fonts\private\OLDENGL.TTF"),
        Path(r"C:\Program Files (x86)\Microsoft Office\root\vfs\Fonts\private\OLDENGL.TTF"),
        Path(r"C:\Windows\Fonts\OLDENGL.TTF"),
    )
    for path in candidates:
        if path.exists():
            try:
                pdfmetrics.registerFont(TTFont("OldEnglish", str(path)))
                return "OldEnglish"
            except Exception:
                continue
    return "Times-BoldItalic"


UNIVERSITY_FONT = _register_university_font()


def _style(name, **kwargs):
    base = dict(fontName="Helvetica", fontSize=9, leading=11, textColor=INK)
    base.update(kwargs)
    return ParagraphStyle(name, **base)


_S_HEAD = lambda name, size, font="Helvetica", leading=None: _style(
    name,
    alignment=TA_CENTER,
    fontName=font,
    fontSize=size,
    leading=leading or size + 2,
)
_S_ENTITY = _style("entity", alignment=TA_CENTER, fontName="Times-Roman", fontSize=10, leading=12.5)
_S_CELL = _style("cell", alignment=TA_CENTER, fontSize=8, leading=10, spaceBefore=0, spaceAfter=0)
_S_PERIOD = _style("period", alignment=TA_CENTER, fontSize=8, leading=10)
_S_NOTE = _style("note", alignment=TA_CENTER, fontSize=7.5, leading=9.5, fontName="Helvetica-Oblique")
_S_PREPARED = _style("prepared", alignment=TA_LEFT, fontSize=8.8, leading=11)
_S_SIG = _style("sig", alignment=TA_CENTER, fontSize=8.5, leading=12, fontName="Helvetica-Bold")
_S_SIG_SUB = _style("sig_sub", alignment=TA_CENTER, fontSize=9, leading=11)


def _ordinal(year):
    return {1: "1st", 2: "2nd", 3: "3rd", 4: "4th"}.get(int(year), str(year))


def _program_name(program):
    return {
        "BSCS": "Bachelor of Science in Computer Science",
        "BSIT": "Bachelor of Science in Information Technology",
    }.get((program or "").upper(), program)


def _logo(name, width):
    png = IMAGES_DIR / f"{name}.png"
    jpg = IMAGES_DIR / f"{name}.jpg"
    path = png if png.exists() else jpg if jpg.exists() else None
    if not path:
        return Spacer(1, 1)
    return Image(str(path), width=width, height=width, kind="proportional")


def _event_index(event):
    start_row = int((float(event["start"]) - 7) * 2) + 1
    span = max(1, int(round((float(event["end"]) - float(event["start"])) * 2)))
    return start_row, span


def _cell_lines(kind, event):
    code = event["course"]
    room = event["room"]
    marker = "ONLINE" if event["delivery"] == "Online" else ("LAB" if event["session_type"] == "Laboratory" else "LEC")
    if kind == "instructor":
        third = event["section"]
    elif kind == "section":
        third = event["instructor"]
    else:  # room
        third = f"{event['instructor']} - {event['section']}"
    return [code, third, room, f"({marker})"]


def _cell_html(lines):
    out = []
    for index, line in enumerate(lines):
        out.append(f"<b>{line}</b>" if index == 0 else str(line))
    return "<br/>".join(out)


_HEADERS = ["PERIOD", "MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY"]


def _grid_table(events, kind):
    days = ["MON", "TUE", "WED", "THU", "FRI", "SAT"]
    day_col = {day: index + 1 for index, day in enumerate(days)}
    table = [
        [
            Paragraph(label, _style(f"h{index}", alignment=TA_CENTER, fontName="Helvetica-Bold", fontSize=8, leading=10))
            for index, label in enumerate(_HEADERS)
        ]
    ]
    for period in PERIODS:
        table.append([Paragraph(period, _S_PERIOD)] + [""] * 6)

    occupied, span_cmds = set(), []
    for event in events:
        col = day_col.get(event["day"])
        if col is None:
            continue
        start_row, span = _event_index(event)
        if start_row < 1 or start_row + span - 1 > len(PERIODS):
            continue
        if any((col, row) in occupied for row in range(start_row, start_row + span)):
            continue
        occupied.update((col, row) for row in range(start_row, start_row + span))
        table[start_row][col] = Paragraph(_cell_html(_cell_lines(kind, event)), _S_CELL)
        if span > 1:
            span_cmds.append(("SPAN", (col, start_row), (col, start_row + span - 1)))

    grid = Table(
        table,
        colWidths=[COL_WIDTH] * 7,
        rowHeights=[HEADER_ROW_HEIGHT] + [BODY_ROW_HEIGHT] * len(PERIODS),
    )
    style = TableStyle(
        [
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("GRID", (0, 0), (-1, -1), 1.0, BLACK),
            ("BOX", (0, 0), (-1, -1), 1.4, BLACK),
            ("LINEBELOW", (0, 0), (-1, 0), 1.4, BLACK),
            ("LINEAFTER", (0, 0), (0, -1), 1.4, BLACK),
            ("LEFTPADDING", (0, 0), (-1, -1), 1.5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 1.5),
            ("TOPPADDING", (0, 0), (-1, -1), 0.5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0.5),
        ]
    )
    for command in span_cmds:
        style.add(*command)
    grid.setStyle(style)
    return grid


def _entity_subtitle(entity):
    kind = entity["kind"]
    if kind == "section":
        program = entity.get("program_name") or _program_name(entity.get("program"))
        return (
            f"Program: <u><b>{program}</b></u> "
            f'<font size="8.3">Year: {_ordinal(entity.get("year"))} &nbsp; Section: {entity.get("section_letter", "")}</font>'
        )
    if kind == "instructor":
        return f"Instructor: <u><b>{entity['name']}</b></u>"
    if kind == "room":
        return (
            f"Room: <u><b>{entity['name']}</b></u> "
            f'<font size="8.3">Type: {entity.get("room_type", "Lecture")}</font>'
        )
    return entity["name"]


def _header_block():
    mid_top = [
        Paragraph("Republic of the Philippines", _S_HEAD("rep", 10.5, font="Times-Roman", leading=12.5)),
        Spacer(1, 2),
        Paragraph("Laguna State Polytechnic University", _S_HEAD("univ", 14, font=UNIVERSITY_FONT, leading=17)),
        Paragraph("Province of Laguna", _S_HEAD("prov", 10.5, font="Times-Roman", leading=12.5)),
    ]
    mid_bottom = [
        Spacer(1, 1),
        Paragraph("COLLEGE OF COMPUTER STUDIES", _S_HEAD("college", 10, font="Helvetica-Bold", leading=12.5)),
        Spacer(1, 10.5),
        Paragraph("CLASS SCHEDULE", _S_HEAD("cls", 10, font="Helvetica-Bold", leading=12.5)),
        Paragraph(SEMESTER_LINE, _S_HEAD("sem", 9, font="Helvetica", leading=11.5)),
    ]
    return Table(
        [
            [_logo("lspu-seal", 57), mid_top, _logo("bagong-pilipinas", 45)],
            ["", mid_bottom, ""],
        ],
        colWidths=[120, CONTENT_WIDTH - 240, 120],
        rowHeights=[57, 48],
        style=TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ("LEFTPADDING", (0, 0), (0, 0), 50),
            ("RIGHTPADDING", (2, 0), (2, 0), 50),
            ("TOPPADDING", (2, 0), (2, 0), 9.5),
            ("LEFTPADDING", (1, 0), (1, 1), 6),
            ("RIGHTPADDING", (1, 0), (1, 1), 6),
        ]),
    )


def _entity_flowables(entity):
    flowables = [
        _header_block(),
        Spacer(1, 9.5),
        Paragraph(_entity_subtitle(entity), _S_ENTITY),
        Spacer(1, 10),
        _grid_table(entity["events"], entity["kind"]),
    ]
    has_nstp_note = bool(entity.get("show_nstp_note"))
    if has_nstp_note:
        flowables += [Spacer(1, 3), Paragraph("NSTP - Sunday 7:00 AM - 5:00 PM (first-year students)", _S_NOTE)]
    flowables += [
        Spacer(1, 13 if has_nstp_note else 26),
        Paragraph("Prepared by:", _S_PREPARED),
        Spacer(1, 12),
        Paragraph("MIA V. VILLARICA, DIT", _S_SIG),
        Paragraph("Associate Dean of the College of Computer Studies", _S_SIG_SUB),
    ]
    return flowables


def create_export(entities, file_name=None):
    if not entities:
        raise ValueError("Select at least one instructor, section, or room.")
    output = BytesIO()
    document = SimpleDocTemplate(
        output,
        pagesize=A4,
        # SimpleDocTemplate adds 6 pt of frame padding on every side.
        leftMargin=MARGIN_X - 6,
        rightMargin=MARGIN_X - 6,
        topMargin=48.5,
        bottomMargin=34,
        title="CCSync Class Schedules",
    )
    story = []
    for index, entity in enumerate(entities):
        if index:
            story.append(PageBreak())
        story.extend(_entity_flowables(entity))
    document.build(story)
    output.seek(0)

    safe_name = "".join(char for char in (file_name or "") if char.isalnum() or char in " ._-").strip()[:64]
    if not safe_name:
        safe_name = "CCSync-Schedules"
    if not safe_name.lower().endswith(".pdf"):
        safe_name += ".pdf"
    return output, "application/pdf", safe_name
