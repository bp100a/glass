"""PDF cutting report: stock, panes, sheet drawings, and waste."""

from __future__ import annotations

from fractions import Fraction
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

from glasscut.model import Job
from glasscut.optimize import CutPlan, SheetPlan
from glasscut.units import format_inches, format_quantity

MARGIN = 48
PAGE_W, PAGE_H = letter


def write_report(job: Job, plan: CutPlan, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pdf = canvas.Canvas(str(path), pagesize=letter)
    pdf.setTitle("Glass cut plan")
    _summary(pdf, job, plan)
    pdf.showPage()
    _schedule(pdf, job, plan)
    pdf.showPage()
    for sheet in plan.sheets:
        _sheet_page(pdf, job, plan, sheet)
        pdf.showPage()
    pdf.save()


def _summary(pdf: canvas.Canvas, job: Job, plan: CutPlan) -> None:
    y = _heading(pdf, "Glass cut plan")
    source = job.source.name if job.source else "job file"
    y = _text(pdf, y, f"Source: {source}")
    y = _text(pdf, y, f"Adjustment: {format_inches(job.adjustment)}\"")
    y = _text(pdf, y, f"Thickness: {format_inches(job.thickness)}\"")
    y = _text(
        pdf,
        y,
        f"Each score runs the full width or length of the piece in hand. "
        f"Snap waste is at least {format_inches(job.min_leverage)}\".",
        size=9,
        gap=12,
    )
    if job.kerf:
        y = _text(pdf, y, f"Kerf: {format_inches(job.kerf)}\"")
    y -= 8
    y = _text(pdf, y, "Input stock", size=13, font="Helvetica-Bold", gap=18)
    if not job.stock:
        y = _text(pdf, y, "None")
    for stock in job.stock:
        buyable = "purchasable" if stock.purchasable else "not purchasable"
        y = _text(pdf, y, f"{stock.label} - {stock.on_hand} on hand, {buyable}")
    y -= 8
    on_hand = sum(stock.on_hand for stock in job.stock)
    y = _text(pdf, y, f"Sheets required: {plan.required}")
    y = _text(pdf, y, f"Taken from stock: {plan.required - plan.purchase}")
    y = _text(pdf, y, f"Sheets to buy: {plan.purchase}")
    y = _text(pdf, y, f"On hand: {on_hand}")
    y -= 8
    y = _text(pdf, y, "Windows", size=13, font="Helvetica-Bold", gap=18)
    for window in job.windows:
        pane_bits = []
        for pane in window.panes:
            sheet_number = _sheet_number(plan, pane.id)
            where = f"sheet {sheet_number}" if sheet_number else "not cut"
            pane_bits.append(f"{pane.name} on {where}")
        status = "completed" if all(_sheet_number(plan, pane.id) for pane in window.panes) else "not completed"
        y = _text(pdf, y, f"{window.name} ({window.id}) - {status} - {', '.join(pane_bits)}")
    missing = [window.id for window in job.windows if not all(_sheet_number(plan, pane.id) for pane in window.panes)]
    y = _text(pdf, y, "Not completed: " + (", ".join(missing) if missing else "none"))
    y -= 8
    y = _text(pdf, y, "Waste", size=13, font="Helvetica-Bold", gap=18)
    y = _text(pdf, y, _waste_line(plan.waste_area, plan.glass_area))
    for sheet in plan.sheets:
        names = ", ".join(piece.pane.label for piece in sheet.placed)
        y = _text(
            pdf,
            y,
            f"Sheet {sheet.number} ({names}): {_area(sheet.waste_area)}",
            size=9,
            gap=12,
        )


def _schedule(pdf: canvas.Canvas, job: Job, plan: CutPlan) -> None:
    y = _heading(pdf, "Pane schedule")
    y = _text(
        pdf,
        y,
        "Rough sizes are the openings. Cut size subtracts the adjustment from width and from height.",
        size=9,
        gap=16,
    )
    columns = (48, 165, 215, 275, 415, 540)
    headers = ("Window", "Pane", "Thickness", "Rough opening", "Cut size", "Sheet")
    y -= 6
    pdf.setFont("Helvetica-Bold", 9)
    for x, header in zip(columns, headers, strict=True):
        pdf.drawString(x, y, header)
    y -= 8
    pdf.setStrokeColor(colors.black)
    pdf.line(MARGIN, y, PAGE_W - MARGIN, y)
    y -= 14
    pdf.setFont("Helvetica", 8)
    for window in job.windows:
        for pane in window.panes:
            values = (
                window.name,
                pane.name,
                f"{format_inches(pane.thickness)}\"",
                f"{format_inches(pane.rough_width)}\" x {format_inches(pane.rough_height)}\"",
                f"{format_inches(pane.cut_width)}\" x {format_inches(pane.cut_height)}\"",
                str(_sheet_number(plan, pane.id) or "-"),
            )
            for x, value in zip(columns, values, strict=True):
                pdf.drawString(x, y, value)
            y -= 16
            if y < MARGIN:
                pdf.showPage()
                y = _heading(pdf, "Pane schedule (continued)")


def _sheet_page(pdf: canvas.Canvas, job: Job, plan: CutPlan, sheet: SheetPlan) -> None:
    names = ", ".join(piece.pane.label for piece in sheet.placed)
    y = _heading(pdf, f"Sheet {sheet.number} of {plan.required} - {sheet.source}")
    y = _text(pdf, y, names, font="Helvetica-Bold")
    y = _text(
        pdf,
        y,
        f"Stock {sheet.stock.label}. Orient this piece with "
        f"{format_inches(sheet.width)}\" horizontal and {format_inches(sheet.height)}\" vertical.",
        size=9,
        gap=14,
    )
    box_top = y - 8
    box_w = PAGE_W - 2 * MARGIN
    box_h = 300
    scale = min(box_w / float(sheet.width), box_h / float(sheet.height))
    draw_w = float(sheet.width) * scale
    draw_h = float(sheet.height) * scale
    origin_x = MARGIN
    origin_y = box_top - draw_h
    _draw_sheet(pdf, sheet, origin_x, origin_y, scale)
    pdf.setFillColor(colors.black)
    pdf.setFont("Helvetica", 8)
    pdf.drawCentredString(origin_x + draw_w / 2, origin_y - 12, f"{format_inches(sheet.width)}\"")
    pdf.saveState()
    pdf.translate(origin_x - 14, origin_y + draw_h / 2)
    pdf.rotate(90)
    pdf.drawCentredString(0, 0, f"{format_inches(sheet.height)}\"")
    pdf.restoreState()

    y = origin_y - 28
    y = _text(pdf, y, "Cut list", size=12, font="Helvetica-Bold", gap=16)
    if sheet.steps:
        for number, step in enumerate(sheet.steps, start=1):
            y = _wrapped(pdf, y, f"{number}. {step}", size=9, gap=12)
    else:
        y = _text(pdf, y, "The sheet is already the finished pane. No score is required.", size=9)
    y -= 4
    y = _text(pdf, y, "Panes", size=12, font="Helvetica-Bold", gap=16)
    for piece in sheet.placed:
        pane = piece.pane
        y = _wrapped(
            pdf,
            y,
            f"{pane.label}: cut {format_inches(pane.cut_width)}\" x {format_inches(pane.cut_height)}\" "
            f"(rough {format_inches(pane.rough_width)}\" x {format_inches(pane.rough_height)}\"), "
            f"placed {format_inches(piece.width)}\" horizontal by {format_inches(piece.height)}\" vertical, "
            f"{format_inches(piece.x)}\" from the left and {format_inches(piece.y)}\" from the bottom.",
            size=9,
            gap=12,
        )
    y -= 4
    y = _text(pdf, y, "Offcuts", size=12, font="Helvetica-Bold", gap=16)
    if not sheet.offcuts:
        y = _text(pdf, y, "None", size=9)
    for offcut in sheet.offcuts:
        y = _text(
            pdf,
            y,
            f"{format_inches(offcut.width)}\" x {format_inches(offcut.height)}\" "
            f"at {format_inches(offcut.x)}\" from the left, {format_inches(offcut.y)}\" from the bottom.",
            size=9,
            gap=12,
        )
    _text(pdf, y, f"Waste from this sheet: {_area(sheet.waste_area)}", size=10, font="Helvetica-Bold")


def _draw_sheet(pdf: canvas.Canvas, sheet: SheetPlan, origin_x: float, origin_y: float, scale: float) -> None:
    def box(x: Fraction, y: Fraction, w: Fraction, h: Fraction) -> tuple[float, float, float, float]:
        return (
            origin_x + float(x) * scale,
            origin_y + float(y) * scale,
            float(w) * scale,
            float(h) * scale,
        )

    sheet_w = float(sheet.width) * scale
    sheet_h = float(sheet.height) * scale
    pdf.setFillColor(colors.Color(0.96, 0.96, 0.94))
    pdf.rect(origin_x, origin_y, sheet_w, sheet_h, stroke=0, fill=1)
    for offcut in sheet.offcuts:
        x, y, w, h = box(offcut.x, offcut.y, offcut.width, offcut.height)
        pdf.setFillColor(colors.white)
        pdf.rect(x, y, w, h, stroke=0, fill=1)
        _hatch(pdf, x, y, w, h)
        pdf.setStrokeColor(colors.black)
        pdf.setLineWidth(0.8)
        pdf.rect(x, y, w, h, stroke=1, fill=0)
        _label(
            pdf,
            x,
            y,
            w,
            h,
            [f"{format_inches(offcut.width)}\" x {format_inches(offcut.height)}\""],
        )
    for piece in sheet.placed:
        x, y, w, h = box(piece.x, piece.y, piece.width, piece.height)
        pdf.setFillColor(colors.Color(0.78, 0.88, 0.96))
        pdf.setStrokeColor(colors.HexColor("#1f4e79"))
        pdf.setLineWidth(1)
        pdf.rect(x, y, w, h, stroke=1, fill=1)
        size_line = f"{format_inches(piece.width)}\" x {format_inches(piece.height)}\""
        if not _label(pdf, x, y, w, h, [piece.pane.window_name, piece.pane.name, size_line]):
            _label(pdf, x, y, w, h, [f"{piece.pane.window_id} {piece.pane.name}", size_line])
    pdf.setStrokeColor(colors.black)
    pdf.setLineWidth(1.5)
    pdf.rect(origin_x, origin_y, sheet_w, sheet_h, stroke=1, fill=0)


def _hatch(pdf: canvas.Canvas, x: float, y: float, w: float, h: float) -> None:
    pdf.saveState()
    path = pdf.beginPath()
    path.rect(x, y, w, h)
    pdf.clipPath(path, stroke=0, fill=0)
    pdf.setStrokeColor(colors.Color(0.55, 0.55, 0.55))
    pdf.setLineWidth(0.4)
    step = 6
    start = -h
    while start < w:
        pdf.line(x + start, y, x + start + h, y + h)
        start += step
    pdf.restoreState()


def _label(pdf: canvas.Canvas, x: float, y: float, w: float, h: float, lines: list[str]) -> bool:
    size = 8
    while size >= 6:
        if all(stringWidth(line, "Helvetica", size) <= w - 8 for line in lines):
            break
        size -= 1
    else:
        return False
    line_gap = size + 2
    block = line_gap * len(lines) - 2
    if block > h - 6:
        return False
    pdf.setFillColor(colors.black)
    pdf.setFont("Helvetica", size)
    baseline = y + (h + block) / 2 - size
    for line in lines:
        pdf.drawCentredString(x + w / 2, baseline, line)
        baseline -= line_gap
    return True


def _heading(pdf: canvas.Canvas, title: str) -> float:
    pdf.setFillColor(colors.black)
    pdf.setFont("Helvetica-Bold", 16)
    y = PAGE_H - MARGIN
    pdf.drawString(MARGIN, y, title)
    return y - 22


def _text(
    pdf: canvas.Canvas,
    y: float,
    text: str,
    size: int = 10,
    font: str = "Helvetica",
    gap: int = 14,
) -> float:
    pdf.setFillColor(colors.black)
    pdf.setFont(font, size)
    pdf.drawString(MARGIN, y, text)
    return y - gap


def _wrapped(pdf: canvas.Canvas, y: float, text: str, size: int = 9, gap: int = 12) -> float:
    width = PAGE_W - 2 * MARGIN
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        trial = word if not current else f"{current} {word}"
        if stringWidth(trial, "Helvetica", size) <= width:
            current = trial
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    for line in lines:
        y = _text(pdf, y, line, size=size, gap=gap)
    return y


def _sheet_number(plan: CutPlan, pane_id: str) -> int | None:
    for sheet in plan.sheets:
        if any(piece.pane.id == pane_id for piece in sheet.placed):
            return sheet.number
    return None


def _area(sq_in: Fraction) -> str:
    return f"{format_quantity(sq_in)} sq in ({format_quantity(sq_in / 144)} sq ft)"


def _waste_line(waste: Fraction, glass: Fraction) -> str:
    percent = Fraction(0) if glass == 0 else waste / glass * 100
    return f"Waste: {_area(waste)}, {format_quantity(percent, 1)}% of the glass used"
