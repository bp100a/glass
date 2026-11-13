"""The window job: cut sizes, grouping, sheet count, and the PDF report."""

from __future__ import annotations

from fractions import Fraction
from pathlib import Path

import pytest
from pypdf import PdfReader

from glasscut.model import CutError, load_job
from glasscut.optimize import solve
from glasscut.pack import PaneSpec, pack_sheet
from glasscut.report import write_report
from glasscut.units import UnitError, format_inches, format_quantity, parse_inches

ROOT = Path(__file__).resolve().parents[1]
JOB_PATH = ROOT / "data" / "windows.yaml"

EXPECTED_CUTS = {
    ("LRM", "upper"): ("37 5/8", "28 3/16"),
    ("LRM", "lower"): ("37 5/8", "27 7/8"),
    ("DRM", "upper"): ("37 11/16", "28 1/4"),
    ("DRM", "lower"): ("37 11/16", "27 7/8"),
    ("DRS", "upper"): ("35 7/8", "28"),
    ("DRS", "lower"): ("35 7/8", "27 7/8"),
    ("LRW", "upper"): ("16 3/4", "28 1/4"),
    ("LRW", "lower"): ("16 5/8", "27 3/4"),
    ("DRW", "upper"): ("16 3/4", "28 3/16"),
    ("DRW", "lower"): ("16 3/4", "27 7/8"),
    ("LRE", "upper"): ("16 5/8", "28 1/4"),
    ("LRE", "lower"): ("16 3/4", "27 3/4"),
    ("DRE", "upper"): ("16 5/8", "28 3/8"),
    ("DRE", "lower"): ("16 5/8", "27 3/4"),
}

SMALL_WINDOWS = ("LRW", "DRW", "LRE", "DRE")
LARGE_WINDOWS = ("LRM", "DRM", "DRS")


@pytest.fixture(scope="module")
def job():
    return load_job(JOB_PATH)


@pytest.fixture(scope="module")
def plan(job):
    return solve(job)


def test_parse_inches():
    assert parse_inches("37 3/4") == Fraction(151, 4)
    assert parse_inches("37-3/4") == Fraction(151, 4)
    assert parse_inches("3/4") == Fraction(3, 4)
    assert parse_inches("28.25") == Fraction(113, 4)
    assert parse_inches(36) == 36
    assert parse_inches("1/16") == Fraction(1, 16)
    with pytest.raises(UnitError):
        parse_inches("1/3")


def test_job_adjustment_and_thickness(job):
    assert job.adjustment == Fraction(1, 8)
    assert job.min_leverage == 3
    assert job.thickness == Fraction(1, 8)
    assert job.stock[0].on_hand == 5
    assert job.stock[0].width == 36
    assert job.stock[0].height == 44
    assert job.stock[0].thickness == Fraction(1, 8)
    assert all(pane.thickness == Fraction(1, 8) for pane in job.panes)
    assert {window.id: window.name for window in job.windows} == {
        "LRM": "Living Room Middle",
        "DRM": "Dining Room Middle",
        "DRS": "Dining Room Side",
        "LRW": "Living Room West",
        "DRW": "Dining Room West",
        "LRE": "Living Room East",
        "DRE": "Dining Room East",
    }
    assert len(job.panes) == 14


def test_cut_sizes(job):
    found = {
        (pane.window_id, pane.name): (
            format_inches(pane.cut_width),
            format_inches(pane.cut_height),
        )
        for pane in job.panes
    }
    assert found == EXPECTED_CUTS


def test_large_window_does_not_share_a_sheet(job):
    specs = [_spec(pane) for pane in job.panes if pane.window_id == "LRM"]
    assert pack_sheet(Fraction(36), Fraction(44), specs, job.kerf) is None


def test_small_window_shares_a_sheet(job):
    specs = [_spec(pane) for pane in job.panes if pane.window_id == "LRW"]
    assert pack_sheet(Fraction(36), Fraction(44), specs, job.kerf) is not None


def test_full_job_buys_five_sheets(plan):
    assert plan.required == 10
    assert plan.purchase == 5
    assert [sheet.source for sheet in plan.sheets] == ["on hand"] * 5 + ["purchase"] * 5
    windows = [_window_ids(sheet) for sheet in plan.sheets]
    assert windows == [
        ["LRM"],
        ["LRM"],
        ["DRM"],
        ["DRM"],
        ["DRS"],
        ["DRS"],
        ["LRW"],
        ["DRW"],
        ["LRE"],
        ["DRE"],
    ]


def test_small_windows_are_alone_on_their_sheet(plan):
    for window_id in SMALL_WINDOWS:
        sheets = [sheet for sheet in plan.sheets if _window_ids(sheet) == [window_id]]
        assert len(sheets) == 1
        assert len(sheets[0].placed) == 2
        assert {piece.pane.name for piece in sheets[0].placed} == {"upper", "lower"}


def test_large_panes_are_alone(plan):
    for window_id in LARGE_WINDOWS:
        sheets = [sheet for sheet in plan.sheets if window_id in _window_ids(sheet)]
        assert len(sheets) == 2
        assert all(len(sheet.placed) == 1 for sheet in sheets)
        assert {piece.pane.name for sheet in sheets for piece in sheet.placed} == {"upper", "lower"}


def test_placements_match_cut_size_and_tile_the_sheet(plan):
    for sheet in plan.sheets:
        rects = []
        for piece in sheet.placed:
            assert {piece.width, piece.height} == {piece.pane.cut_width, piece.pane.cut_height}
            assert piece.x >= 0 and piece.y >= 0
            assert piece.x + piece.width <= sheet.width
            assert piece.y + piece.height <= sheet.height
            rects.append(piece)
        for offcut in sheet.offcuts:
            assert offcut.x >= 0 and offcut.y >= 0
            assert offcut.x + offcut.width <= sheet.width
            assert offcut.y + offcut.height <= sheet.height
            rects.append(offcut)
        area = sum(piece.width * piece.height for piece in rects)
        assert area == sheet.width * sheet.height
        for index, left in enumerate(rects):
            for right in rects[index + 1 :]:
                assert not _overlaps(left, right)
        assert sheet.steps
        assert all("full" in step for step in sheet.steps)
        assert all(min(offcut.width, offcut.height) >= Fraction(3) for offcut in sheet.offcuts)


def test_small_window_top_cut_then_full_width_division(plan):
    for window_id in SMALL_WINDOWS:
        sheet = next(sheet for sheet in plan.sheets if _window_ids(sheet) == [window_id])
        top = max(sheet.offcuts, key=lambda offcut: offcut.y)
        assert top.width == sheet.width
        assert format_inches(top.y) in sheet.steps[0]
        assert f"full {format_inches(sheet.width)}\" width" in sheet.steps[0]
        assert f"full {format_inches(sheet.width)}\" width" in sheet.steps[1]
        assert all("vertically" in step for step in sheet.steps[2:])


def test_pane_larger_than_every_sheet_names_the_pane(tmp_path: Path):
    path = tmp_path / "too-big.yaml"
    path.write_text(
        """
adjustment: "1/16"
thickness: "1/8"
stock:
  - width: 36
    height: 44
    thickness: "1/8"
    on_hand: 1
windows:
  - id: BIG
    panes:
      - name: giant
        width: 50
        height: 50
""",
        encoding="utf-8",
    )
    with pytest.raises(CutError, match="giant"):
        solve(load_job(path))


def test_pdf_report(job, plan, tmp_path: Path):
    path = tmp_path / "cut-plan.pdf"
    write_report(job, plan, path)
    reader = PdfReader(path)
    assert len(reader.pages) == 12
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    for window_id, window_name in (
        ("LRM", "Living Room Middle"),
        ("DRM", "Dining Room Middle"),
        ("DRS", "Dining Room Side"),
        ("LRW", "Living Room West"),
        ("DRW", "Dining Room West"),
        ("LRE", "Living Room East"),
        ("DRE", "Dining Room East"),
    ):
        assert window_id in text
        assert window_name in text
    assert "Sheets to buy: 5" in text
    assert "Adjustment: 1/8" in text
    assert "Thickness: 1/8" in text
    assert format_quantity(plan.waste_area) in text
    assert "completed" in text
    assert "Waste:" in text
    assert "Pane schedule" in text
    assert f"adjustment of {format_inches(job.adjustment)}" in text
    assert "Cut list" in text


def _spec(pane) -> PaneSpec:
    return PaneSpec(pane.id, pane.cut_width, pane.cut_height)


def _window_ids(sheet) -> list[str]:
    return sorted({piece.pane.window_id for piece in sheet.placed})


def _overlaps(left, right) -> bool:
    return (
        left.x < right.x + right.width
        and right.x < left.x + left.width
        and left.y < right.y + right.height
        and right.y < left.y + left.height
    )
