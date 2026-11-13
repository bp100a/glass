# Glass cutting planner

A Python command-line tool that turns a YAML list of sheet stock and window panes into a guillotine cut plan. It cuts every pane, keeps both panes of a window on the same sheet whenever they fit, and writes a letter-size PDF with a to-scale drawing and an ordered score list for each sheet.

The included job, [`data/windows.yaml`](data/windows.yaml), is seven windows of 1/8" glass cut from 36" x 44" sheets. Five sheets are on hand. The plan uses 10 sheets and buys 5. Waste on that plan is 5869.80 sq in (40.76 sq ft, 37.1% of the glass used).

The design notes are in [`glass_cut_planner.plan.md`](glass_cut_planner.plan.md).

## Approach

Every measurement is a `fractions.Fraction`. The parser accepts mixed numbers (`37 3/4`, `37-3/4`), bare fractions, integers, and decimals that land on a sixteenth. The job's `adjustment` is subtracted once from each pane's width and once from its height. A pane is cut only from stock of the same thickness. Clear glass has no grain, so a pane may be rotated.

Cuts are guillotine scores. Each score runs the full width or the full length of the piece in hand. Waste snapped off a score must be at least `min_leverage` (3" in this job) so the strip can be levered. A flush edge needs no snap. Among legal layouts, the first score on a sheet frees the largest leftover rectangle.

A window is atomic when all of its panes fit on one empty sheet. Those panes are placed only as a complete set. On 36" x 44" stock the three large windows (Living Room Middle, Dining Room Middle, Dining Room Side) are not atomic: each pane takes its own sheet. The four small windows are atomic: both panes share one sheet. They are stacked as full-width bands. The first score snaps the top residual off the whole sheet, the second score divides the two panes from edge to edge, and each pane's length is then trimmed on its own strip.

The search enumerates the legal ways to fill one sheet, then solves an exact cover: every pane once, as few purchased sheets as possible, then as few sheets as possible, then the layout with the largest residual. The first `on_hand` sheets of each stock size are labeled on hand. Further sheets of a purchasable size are purchases.

## Run

Python 3.12 is required (`requires-python` is `>=3.12,<3.13`).

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[test]"
.\.venv\Scripts\python.exe -m glasscut data\windows.yaml -o out
.\.venv\Scripts\python.exe -m pytest
```

That writes `out/cut-plan.pdf` and prints:

```text
Sheets to buy: 5
Waste: 5869.80 sq in (40.76 sq ft, 37.1%)
```

## Job file

```yaml
adjustment: "1/8"
thickness: "1/8"
kerf: 0
min_leverage: 3
stock:
  - width: 36
    height: 44
    thickness: "1/8"
    on_hand: 5
windows:
  - id: LRM
    name: Living Room Middle
    panes:
      - name: upper
        width: "37 3/4"
        height: "28 5/16"
      - name: lower
        width: "37 3/4"
        height: 28
```

`kerf` defaults to 0. `min_leverage` defaults to 3". Stock is purchasable unless `purchasable: false`. A pane may set its own `thickness`; otherwise it uses the job thickness. `name` is the window name shown on the PDF. `id` stays the short code used to identify panes.

## Report

`out/cut-plan.pdf` has three parts:

1. A summary of the adjustment, thickness, stock, sheets required, sheets taken from stock, sheets to buy, every window and the sheets its panes come from, and waste in square inches, square feet, and percent.
2. A pane schedule that states the adjustment amount, then one row per pane with thickness, rough opening, cut size, and sheet number.
3. One page per sheet: a to-scale drawing, the ordered scores, the placed panes, the offcuts, and that sheet's waste.
