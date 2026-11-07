"""Choose sheet layouts that finish every window and buy as little glass as possible."""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction

from glasscut.model import CutError, Job, Pane, Stock
from glasscut.units import format_inches
from glasscut.pack import Node, Offcut, PaneSpec, PlacedPane, pack_sheet, realize, score


@dataclass(frozen=True)
class Placed:
    pane: Pane
    x: Fraction
    y: Fraction
    width: Fraction
    height: Fraction


@dataclass(frozen=True)
class SheetPlan:
    number: int
    stock: Stock
    width: Fraction
    height: Fraction
    source: str
    placed: tuple[Placed, ...]
    offcuts: tuple[Offcut, ...]
    steps: tuple[str, ...]

    @property
    def waste_area(self) -> Fraction:
        return sum((piece.width * piece.height for piece in self.offcuts), Fraction(0))


@dataclass(frozen=True)
class CutPlan:
    sheets: tuple[SheetPlan, ...]
    purchase: int

    @property
    def required(self) -> int:
        return len(self.sheets)

    @property
    def waste_area(self) -> Fraction:
        return sum((sheet.waste_area for sheet in self.sheets), Fraction(0))

    @property
    def glass_area(self) -> Fraction:
        return sum((sheet.width * sheet.height for sheet in self.sheets), Fraction(0))


@dataclass(frozen=True)
class _Pattern:
    stock_index: int
    item_mask: int
    width: Fraction
    height: Fraction
    node: Node
    pane_ids: frozenset[str]


def solve(job: Job) -> CutPlan:
    """Cut every pane. Buy as few sheets as possible, then waste the largest offcuts."""
    if not job.panes:
        raise CutError("the job has no panes")
    thicknesses = {pane.thickness for pane in job.panes}
    sheets: list[SheetPlan] = []
    purchase = 0
    for thickness in sorted(thicknesses):
        group = [pane for pane in job.panes if pane.thickness == thickness]
        stocks = [stock for stock in job.stock if stock.thickness == thickness]
        if not stocks:
            raise CutError(
                f"Pane {group[0].label} is {format_inches(group[0].thickness)}\" thick "
                "and matches no stock"
            )
        planned, bought = _solve_thickness(job, group, stocks)
        sheets.extend(planned)
        purchase += bought
    sheets = _number(_order(job, sheets))
    return CutPlan(tuple(sheets), purchase)


def _solve_thickness(
    job: Job,
    panes: list[Pane],
    stocks: list[Stock],
) -> tuple[list[SheetPlan], int]:
    by_id = {pane.id: pane for pane in panes}
    for pane in panes:
        spec = _spec(pane)
        if all(
            pack_sheet(stock.width, stock.height, [spec], job.kerf, job.min_leverage) is None
            for stock in stocks
        ):
            raise CutError(f"Pane {pane.label} does not fit on any sheet")

    windows = [window for window in job.windows if any(pane.id in by_id for pane in window.panes)]
    items: list[frozenset[str]] = []
    for window in windows:
        owned = [pane for pane in window.panes if pane.id in by_id]
        if len(owned) >= 2 and _fits_together(job, owned, stocks):
            items.append(frozenset(pane.id for pane in owned))
        else:
            items.extend(frozenset((pane.id,)) for pane in owned)

    if len(items) > 20:
        raise CutError(
            f"Too many pieces to search exactly ({len(items)} groups); this solver handles up to 20."
        )

    patterns = _patterns(job, items, panes, stocks)
    chosen, usage = _cover(items, patterns, stocks)
    sheets = [_sheet_from_pattern(pattern, stocks, by_id) for pattern in chosen]
    purchase = _purchase_count(usage, stocks)
    return sheets, purchase


def _fits_together(job: Job, panes: list[Pane], stocks: list[Stock]) -> bool:
    if len(panes) > 8:
        return False
    specs = [_spec(pane) for pane in panes]
    return any(
        pack_sheet(stock.width, stock.height, specs, job.kerf, job.min_leverage) is not None
        for stock in stocks
    )


def _patterns(
    job: Job,
    items: list[frozenset[str]],
    panes: list[Pane],
    stocks: list[Stock],
) -> list[_Pattern]:
    by_id = {pane.id: pane for pane in panes}
    found: list[_Pattern] = []
    count = len(items)
    for mask in range(1, 1 << count):
        pane_ids: set[str] = set()
        for bit in range(count):
            if mask & (1 << bit):
                pane_ids.update(items[bit])
        if len(pane_ids) > 8:
            continue
        specs = [_spec(by_id[pane_id]) for pane_id in sorted(pane_ids)]
        area = sum((spec.width * spec.height for spec in specs), Fraction(0))
        frozen = frozenset(pane_ids)
        for stock_index, stock in enumerate(stocks):
            if area > stock.width * stock.height:
                continue
            packed = pack_sheet(stock.width, stock.height, specs, job.kerf, job.min_leverage)
            if packed is None:
                continue
            width, height, node = packed
            found.append(_Pattern(stock_index, mask, width, height, node, frozen))
    return found


def _cover(
    items: list[frozenset[str]],
    patterns: list[_Pattern],
    stocks: list[Stock],
) -> tuple[list[_Pattern], list[int]]:
    by_item: list[list[_Pattern]] = [[] for _ in items]
    for pattern in patterns:
        bit = 0
        mask = pattern.item_mask
        while mask:
            if mask & 1:
                by_item[bit].append(pattern)
            mask >>= 1
            bit += 1

    full = (1 << len(items)) - 1
    best: tuple[tuple, list[_Pattern], list[int]] | None = None

    def search(remaining: int, usage: list[int], chosen: list[_Pattern]) -> None:
        nonlocal best
        if remaining == 0:
            bought = _bounded_purchase(usage, stocks)
            if bought is None:
                return
            ranked = _objective(chosen, bought)
            if best is None or ranked < best[0]:
                best = (ranked, list(chosen), list(usage))
            return
        bought = _bounded_purchase(usage, stocks)
        if bought is None:
            return
        total = len(chosen)
        if best is not None:
            best_bought, best_total = best[0][0], best[0][1]
            if bought > best_bought or (bought == best_bought and total >= best_total):
                return
        item = (remaining & -remaining).bit_length() - 1
        for pattern in by_item[item]:
            if pattern.item_mask & remaining != pattern.item_mask:
                continue
            usage[pattern.stock_index] += 1
            search(remaining ^ pattern.item_mask, usage, chosen + [pattern])
            usage[pattern.stock_index] -= 1

    search(full, [0] * len(stocks), [])
    if best is None:
        raise CutError(
            "No exact layout covers every pane. This solver places at most 8 panes "
            "on a sheet and keeps a window together when its panes fit on one sheet."
        )
    return best[1], best[2]


def _objective(chosen: list[_Pattern], purchased: int) -> tuple:
    offcuts = []
    for pattern in chosen:
        areas = score(pattern.node)[0]
        offcuts.append(areas[0] if areas else Fraction(0))
    offcuts.sort(reverse=True)
    return (purchased, len(chosen), tuple(-area for area in offcuts))


def _bounded_purchase(usage: list[int], stocks: list[Stock]) -> int | None:
    try:
        return _purchase_count(usage, stocks)
    except CutError:
        return None


def _purchase_count(usage: list[int], stocks: list[Stock]) -> int:
    bought = 0
    for count, stock in zip(usage, stocks, strict=True):
        extra = count - stock.on_hand
        if extra > 0:
            if not stock.purchasable:
                raise CutError(
                    f"Need {count} sheets of {stock.label}, but only {stock.on_hand} "
                    "are on hand and this stock is not purchasable"
                )
            bought += extra
    return bought


def _sheet_from_pattern(pattern: _Pattern, stocks: list[Stock], by_id: dict[str, Pane]) -> SheetPlan:
    placed_raw, offcuts, steps = realize(pattern.node, pattern.width, pattern.height)
    placed = tuple(_placed(raw, by_id) for raw in placed_raw)
    return SheetPlan(
        number=0,
        stock=stocks[pattern.stock_index],
        width=pattern.width,
        height=pattern.height,
        source="",
        placed=placed,
        offcuts=tuple(offcuts),
        steps=tuple(steps),
    )


def _placed(raw: PlacedPane, by_id: dict[str, Pane]) -> Placed:
    pane = by_id[raw.pane_id]
    return Placed(pane, raw.x, raw.y, raw.width, raw.height)


def _order(job: Job, sheets: list[SheetPlan]) -> list[SheetPlan]:
    window_order = {window.id: index for index, window in enumerate(job.windows)}
    pane_order = {pane.id: index for index, pane in enumerate(job.panes)}

    def key(sheet: SheetPlan) -> tuple[int, int]:
        return min(
            (window_order[piece.pane.window_id], pane_order[piece.pane.id]) for piece in sheet.placed
        )

    return sorted(sheets, key=key)


def _number(sheets: list[SheetPlan]) -> list[SheetPlan]:
    used: dict[int, int] = {}
    numbered: list[SheetPlan] = []
    for index, sheet in enumerate(sheets, start=1):
        stock_id = id(sheet.stock)
        used[stock_id] = used.get(stock_id, 0) + 1
        source = "on hand" if used[stock_id] <= sheet.stock.on_hand else "purchase"
        numbered.append(
            SheetPlan(
                index,
                sheet.stock,
                sheet.width,
                sheet.height,
                source,
                sheet.placed,
                sheet.offcuts,
                sheet.steps,
            )
        )
    return numbered


def _spec(pane: Pane) -> PaneSpec:
    return PaneSpec(pane.id, pane.cut_width, pane.cut_height)


def window_sheets(plan: CutPlan) -> dict[str, list[int]]:
    """Sheet numbers that produce each window, in cut order."""
    found: dict[str, list[int]] = {}
    for sheet in plan.sheets:
        for piece in sheet.placed:
            found.setdefault(piece.pane.window_id, [])
            if sheet.number not in found[piece.pane.window_id]:
                found[piece.pane.window_id].append(sheet.number)
    return found
