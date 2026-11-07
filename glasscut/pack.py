"""Exact guillotine packer for a handful of rectangular panes."""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction

from glasscut.model import CutError
from glasscut.units import format_inches


@dataclass(frozen=True)
class PaneSpec:
    id: str
    width: Fraction
    height: Fraction


@dataclass(frozen=True)
class LeafPane:
    pane_id: str
    width: Fraction
    height: Fraction


@dataclass(frozen=True)
class LeafWaste:
    width: Fraction
    height: Fraction


@dataclass(frozen=True)
class Cut:
    """A through-cut of the current piece.

    ``axis`` ``V`` is a vertical score ``at`` inches from the left edge.
    ``axis`` ``H`` is a horizontal score ``at`` inches from the bottom edge.
    ``first`` is the left or bottom piece. ``second`` is the right or top piece.
    ``kerf`` is the gap consumed by the score, between the two pieces.
    """

    axis: str
    at: Fraction
    width: Fraction
    height: Fraction
    kerf: Fraction
    first: Node
    second: Node


Node = LeafPane | LeafWaste | Cut


@dataclass(frozen=True)
class PlacedPane:
    pane_id: str
    x: Fraction
    y: Fraction
    width: Fraction
    height: Fraction


@dataclass(frozen=True)
class Offcut:
    x: Fraction
    y: Fraction
    width: Fraction
    height: Fraction


# Waste snapped off a score has to be wide enough to grip and lever.
MIN_LEVERAGE = Fraction(3)


def pack_sheet(
    stock_width: Fraction,
    stock_height: Fraction,
    panes: list[PaneSpec],
    kerf: Fraction = Fraction(0),
    min_leverage: Fraction = MIN_LEVERAGE,
) -> tuple[Fraction, Fraction, Node] | None:
    """Pack panes onto the stock, trying both orientations of the sheet.

    The listed orientation is kept when both leave the same residual.
    Returns the sheet width (horizontal), height (vertical), and cut tree.
    """
    best: tuple[Fraction, Fraction, Node] | None = None
    best_score: tuple | None = None
    seen: set[tuple[Fraction, Fraction]] = set()
    for width, height in (
        (stock_width, stock_height),
        (stock_height, stock_width),
    ):
        if (width, height) in seen:
            continue
        seen.add((width, height))
        node = pack_panes(width, height, panes, kerf, min_leverage)
        if node is None:
            continue
        ranked = score(node)
        if best_score is None or ranked > best_score:
            best = (width, height, node)
            best_score = ranked
    return best


def pack_panes(
    width: Fraction,
    height: Fraction,
    panes: list[PaneSpec],
    kerf: Fraction = Fraction(0),
    min_leverage: Fraction = MIN_LEVERAGE,
) -> Node | None:
    """Pack every pane into a width-by-height rectangle, or return None.

    Each score runs the full width or the full length of the current piece.
    A pane sits in a corner. The remainder is split off with one through-cut,
    and the two residual rectangles are packed the same way. Waste snapped
    off a score is at least ``min_leverage`` inches, so the strip can be levered.
    """
    if len(panes) > 8:
        raise CutError("this solver packs at most 8 panes on a sheet")
    specs = {pane.id: pane for pane in panes}
    if len(specs) != len(panes):
        raise CutError("duplicate pane id")
    memo: dict[tuple[Fraction, Fraction, frozenset[str]], Node | None] = {}

    def solve(rect_w: Fraction, rect_h: Fraction, ids: frozenset[str]) -> Node | None:
        key = (rect_w, rect_h, ids)
        if key in memo:
            return memo[key]
        if not ids:
            result: Node | None = LeafWaste(rect_w, rect_h)
        else:
            result = _place_any(rect_w, rect_h, ids)
        memo[key] = result
        return result

    def _place_any(rect_w: Fraction, rect_h: Fraction, ids: frozenset[str]) -> Node | None:
        best: Node | None = None
        best_score: tuple | None = None
        for pane_id in sorted(ids):
            spec = specs[pane_id]
            orientations = [(spec.width, spec.height)]
            if spec.width != spec.height:
                orientations.append((spec.height, spec.width))
            rest = ids - {pane_id}
            for pane_w, pane_h in orientations:
                if pane_w > rect_w or pane_h > rect_h:
                    continue
                for axis in ("V", "H"):
                    candidate = _place(rect_w, rect_h, pane_id, pane_w, pane_h, rest, axis)
                    if candidate is None:
                        continue
                    ranked = score(candidate)
                    if best_score is None or ranked > best_score:
                        best = candidate
                        best_score = ranked
        return best

    def _place(
        rect_w: Fraction,
        rect_h: Fraction,
        pane_id: str,
        pane_w: Fraction,
        pane_h: Fraction,
        rest: frozenset[str],
        axis: str,
    ) -> Node | None:
        pane = LeafPane(pane_id, pane_w, pane_h)
        if axis == "V":
            above_h, above_kerf = _residual(rect_h, pane_h, kerf)
            right_w, right_kerf = _residual(rect_w, pane_w, kerf)
            if above_h < 0 or right_w < 0:
                return None
            if not _can_snap(above_h, min_leverage) or not _can_snap(right_w, min_leverage):
                return None

            def build(above: Node | None, right: Node | None) -> Node:
                if above is None:
                    left: Node = pane
                else:
                    left = Cut("H", pane_h, pane_w, rect_h, above_kerf, pane, above)
                if right is None:
                    return left
                return Cut("V", pane_w, rect_w, rect_h, right_kerf, left, right)

            return _partition(rest, (pane_w, above_h), (right_w, rect_h), build)

        beside_w, beside_kerf = _residual(rect_w, pane_w, kerf)
        above_h, above_kerf = _residual(rect_h, pane_h, kerf)
        if beside_w < 0 or above_h < 0:
            return None
        if not _can_snap(beside_w, min_leverage) or not _can_snap(above_h, min_leverage):
            return None

        def build_h(beside: Node | None, above: Node | None) -> Node:
            if beside is None:
                bottom: Node = pane
            else:
                bottom = Cut("V", pane_w, rect_w, pane_h, beside_kerf, pane, beside)
            if above is None:
                return bottom
            return Cut("H", pane_h, rect_w, rect_h, above_kerf, bottom, above)

        return _partition(rest, (beside_w, pane_h), (rect_w, above_h), build_h)

    def _partition(rest, box_a, box_b, build) -> Node | None:
        items = sorted(rest)
        best: Node | None = None
        best_score: tuple | None = None
        for mask in range(1 << len(items)):
            group_a = frozenset(items[i] for i in range(len(items)) if mask & (1 << i))
            group_b = rest - group_a
            node_a = _region(box_a, group_a)
            if group_a and node_a is None:
                continue
            if not group_a and node_a is False:
                continue
            node_b = _region(box_b, group_b)
            if group_b and node_b is None:
                continue
            if not group_b and node_b is False:
                continue
            if node_a is False or node_b is False:
                continue
            candidate = build(node_a, node_b)
            ranked = score(candidate)
            if best_score is None or ranked > best_score:
                best = candidate
                best_score = ranked
        return best

    def _region(box, group: frozenset[str]) -> Node | None | bool:
        box_w, box_h = box
        if box_w <= 0 or box_h <= 0:
            return False if group else None
        return solve(box_w, box_h, group)

    return solve(width, height, frozenset(specs))


def _residual(total: Fraction, used: Fraction, kerf: Fraction) -> tuple[Fraction, Fraction]:
    """Return the free length beyond ``used`` and the kerf of the cut that frees it."""
    if used == total:
        return Fraction(0), Fraction(0)
    gap = kerf
    return total - used - gap, gap


def _can_snap(waste: Fraction, min_leverage: Fraction) -> bool:
    """A flush edge needs no snap. Any waste strip must be thick enough to lever."""
    return waste == 0 or waste >= min_leverage


def score(node: Node) -> tuple:
    """Larger is better: the biggest residual piece, then fewer scores."""
    areas = tuple(sorted(waste_areas(node), reverse=True))
    return (areas, -cut_count(node))


def waste_areas(node: Node) -> list[Fraction]:
    areas: list[Fraction] = []

    def walk(current: Node) -> None:
        if isinstance(current, LeafWaste):
            if current.width > 0 and current.height > 0:
                areas.append(current.width * current.height)
            return
        if isinstance(current, Cut):
            walk(current.first)
            walk(current.second)
            if current.kerf > 0:
                span = current.height if current.axis == "V" else current.width
                areas.append(current.kerf * span)

    walk(node)
    return areas


def cut_count(node: Node) -> int:
    if isinstance(node, Cut):
        return 1 + cut_count(node.first) + cut_count(node.second)
    return 0


def layout_pieces(node: Node) -> tuple[list[PlacedPane], list[Offcut]]:
    """Absolute coordinates of panes and offcuts, origin at the bottom-left."""
    panes: list[PlacedPane] = []
    offcuts: list[Offcut] = []

    def walk(current: Node, x: Fraction, y: Fraction) -> None:
        if isinstance(current, LeafPane):
            panes.append(PlacedPane(current.pane_id, x, y, current.width, current.height))
            return
        if isinstance(current, LeafWaste):
            if current.width > 0 and current.height > 0:
                offcuts.append(Offcut(x, y, current.width, current.height))
            return
        walk(current.first, x, y)
        if current.axis == "V":
            walk(current.second, x + current.at + current.kerf, y)
            if current.kerf > 0:
                offcuts.append(Offcut(x + current.at, y, current.kerf, current.height))
        else:
            walk(current.second, x, y + current.at + current.kerf)
            if current.kerf > 0:
                offcuts.append(Offcut(x, y + current.at, current.width, current.kerf))

    walk(node, Fraction(0), Fraction(0))
    return panes, offcuts


def cut_steps(node: Node) -> list[str]:
    """Shop scores, each measured on the piece produced by the previous snap."""
    steps: list[str] = []

    def walk(current: Node, label: str) -> None:
        if not isinstance(current, Cut):
            return
        across = current.height if current.axis == "V" else current.width
        direction = "vertically" if current.axis == "V" else "horizontally"
        edge = "left" if current.axis == "V" else "bottom"
        span = "height" if current.axis == "V" else "width"
        steps.append(
            f"On {label}, score {direction} the full {format_inches(across)}\" {span}, "
            f"{format_inches(current.at)}\" from the {edge} edge. Snap."
        )
        if current.axis == "V":
            walk(current.first, f"the left piece of {label}")
            walk(current.second, f"the right piece of {label}")
        else:
            walk(current.first, f"the bottom piece of {label}")
            walk(current.second, f"the top piece of {label}")

    walk(node, "the sheet")
    return steps


def promote_full_width_waste(node: Node) -> Node:
    """Snap a full-width waste strip off the whole piece before nested scores.

    A top-edge cut that still spans the stock width is pulled out to the first
    score. The cut between the panes then runs edge to edge on what remains,
    and each pane's length is trimmed on its own strip.
    """
    if not isinstance(node, Cut):
        return node
    node = Cut(
        node.axis,
        node.at,
        node.width,
        node.height,
        node.kerf,
        promote_full_width_waste(node.first),
        promote_full_width_waste(node.second),
    )
    while True:
        bubbled = _bubble_full_span_waste(node)
        if bubbled is node:
            return node
        node = bubbled


def _bubble_full_span_waste(node: Node) -> Node:
    if not isinstance(node, Cut) or node.kerf != 0:
        return node
    inner = node.second
    if not isinstance(inner, Cut) or inner.axis != node.axis or inner.kerf != 0:
        return node
    if not isinstance(inner.second, LeafWaste):
        return node
    spans = (node.axis == "H" and inner.width == node.width) or (
        node.axis == "V" and inner.height == node.height
    )
    if not spans:
        return node
    outer_at = node.at + inner.at
    if node.axis == "H":
        kept = Cut("H", node.at, node.width, outer_at, Fraction(0), node.first, inner.first)
        return Cut("H", outer_at, node.width, node.height, Fraction(0), kept, inner.second)
    kept = Cut("V", node.at, outer_at, node.height, Fraction(0), node.first, inner.first)
    return Cut("V", outer_at, node.width, node.height, Fraction(0), kept, inner.second)


def realize(
    node: Node,
    width: Fraction,
    height: Fraction,
) -> tuple[list[PlacedPane], list[Offcut], list[str]]:
    """Panes, offcuts, and scores, after checking that they tile the sheet."""
    node = promote_full_width_waste(node)
    placed, offcuts = layout_pieces(node)
    rects: list[tuple[Fraction, Fraction, Fraction, Fraction]] = [
        (piece.x, piece.y, piece.width, piece.height) for piece in (*placed, *offcuts)
    ]
    area = sum(w * h for _, _, w, h in rects)
    if area != width * height:
        raise CutError("internal layout error: pieces do not fill the sheet")
    for piece in placed + offcuts:
        if (
            piece.x < 0
            or piece.y < 0
            or piece.x + piece.width > width
            or piece.y + piece.height > height
        ):
            raise CutError("internal layout error: a piece sits outside the sheet")
    for i, left in enumerate(rects):
        for right in rects[i + 1 :]:
            if _overlaps(left, right):
                raise CutError("internal layout error: pieces overlap")
    return placed, offcuts, cut_steps(node)


def _overlaps(
    left: tuple[Fraction, Fraction, Fraction, Fraction],
    right: tuple[Fraction, Fraction, Fraction, Fraction],
) -> bool:
    lx, ly, lw, lh = left
    rx, ry, rw, rh = right
    return lx < rx + rw and rx < lx + lw and ly < ry + rh and ry < ly + lh
