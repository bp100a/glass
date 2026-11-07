"""Job file: stock, windows, adjustment, and thickness."""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

import yaml

from glasscut.units import format_inches, parse_inches


class CutError(Exception):
    """The job cannot be cut as specified."""


@dataclass(frozen=True)
class Stock:
    width: Fraction
    height: Fraction
    thickness: Fraction
    on_hand: int
    purchasable: bool = True

    @property
    def label(self) -> str:
        return (
            f"{format_inches(self.width)}\" x {format_inches(self.height)}\" "
            f"x {format_inches(self.thickness)}\""
        )


@dataclass(frozen=True)
class Pane:
    id: str
    window_id: str
    window_name: str
    name: str
    rough_width: Fraction
    rough_height: Fraction
    cut_width: Fraction
    cut_height: Fraction
    thickness: Fraction

    @property
    def label(self) -> str:
        return f"{self.window_name} {self.name}"


@dataclass(frozen=True)
class Window:
    id: str
    name: str
    panes: tuple[Pane, ...]


@dataclass(frozen=True)
class Job:
    adjustment: Fraction
    thickness: Fraction
    kerf: Fraction
    min_leverage: Fraction
    stock: tuple[Stock, ...]
    windows: tuple[Window, ...]
    source: Path | None = None

    @property
    def panes(self) -> tuple[Pane, ...]:
        return tuple(pane for window in self.windows for pane in window.panes)


def load_job(path: Path) -> Job:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise CutError(f"{path} must contain a mapping")
    try:
        adjustment = parse_inches(raw["adjustment"])
        thickness = parse_inches(raw["thickness"])
    except KeyError as exc:
        raise CutError(f"{path} is missing {exc.args[0]}") from exc
    kerf = parse_inches(raw.get("kerf", 0))
    min_leverage = parse_inches(raw.get("min_leverage", "3"))
    if adjustment < 0 or kerf < 0 or thickness <= 0 or min_leverage < 0:
        raise CutError("adjustment and kerf must be zero or positive, and thickness must be positive")
    stock = tuple(_load_stock(item) for item in _require_list(raw, "stock"))
    if not stock:
        raise CutError("stock must list at least one sheet size")
    seen: set[str] = set()
    windows: list[Window] = []
    for item in _require_list(raw, "windows"):
        window = _load_window(item, adjustment, thickness, seen)
        windows.append(window)
    if not windows:
        raise CutError("windows must list at least one window")
    return Job(adjustment, thickness, kerf, min_leverage, stock, tuple(windows), path)


def _require_list(raw: dict, key: str) -> list:
    value = raw.get(key)
    if not isinstance(value, list):
        raise CutError(f"{key} must be a list")
    return value


def _load_stock(item: object) -> Stock:
    if not isinstance(item, dict):
        raise CutError("each stock entry must be a mapping")
    try:
        width = parse_inches(item["width"])
        height = parse_inches(item["height"])
        thickness = parse_inches(item["thickness"])
        on_hand = item["on_hand"]
    except KeyError as exc:
        raise CutError(f"stock entry is missing {exc.args[0]}") from exc
    if isinstance(on_hand, bool) or not isinstance(on_hand, int) or on_hand < 0:
        raise CutError("on_hand must be a non-negative integer")
    if width <= 0 or height <= 0 or thickness <= 0:
        raise CutError("stock width, height, and thickness must be positive")
    purchasable = item.get("purchasable", True)
    if not isinstance(purchasable, bool):
        raise CutError("purchasable must be true or false")
    return Stock(width, height, thickness, on_hand, purchasable)


def _load_window(
    item: object,
    adjustment: Fraction,
    default_thickness: Fraction,
    seen: set[str],
) -> Window:
    if not isinstance(item, dict):
        raise CutError("each window must be a mapping")
    window_id = item.get("id")
    if not isinstance(window_id, str) or not window_id.strip():
        raise CutError("each window needs an id")
    window_id = window_id.strip()
    window_name = item.get("name", window_id)
    if not isinstance(window_name, str) or not window_name.strip():
        raise CutError(f"window {window_id} needs a name")
    window_name = window_name.strip()
    panes_raw = item.get("panes")
    if not isinstance(panes_raw, list) or not panes_raw:
        raise CutError(f"window {window_id} needs a panes list")
    panes: list[Pane] = []
    for pane in panes_raw:
        if not isinstance(pane, dict):
            raise CutError(f"window {window_id} has a pane that is not a mapping")
        name = pane.get("name")
        if not isinstance(name, str) or not name.strip():
            raise CutError(f"window {window_id} has a pane without a name")
        name = name.strip()
        pane_id = f"{window_id}:{name}"
        if pane_id in seen:
            raise CutError(f"duplicate pane {window_id} {name}")
        seen.add(pane_id)
        try:
            rough_w = parse_inches(pane["width"])
            rough_h = parse_inches(pane["height"])
        except KeyError as exc:
            raise CutError(f"pane {window_id} {name} is missing {exc.args[0]}") from exc
        thickness = parse_inches(pane.get("thickness", default_thickness))
        cut_w = rough_w - adjustment
        cut_h = rough_h - adjustment
        if cut_w <= 0 or cut_h <= 0:
            raise CutError(f"pane {window_id} {name} is smaller than the adjustment")
        if thickness <= 0:
            raise CutError(f"pane {window_id} {name} needs a positive thickness")
        panes.append(
            Pane(
                pane_id,
                window_id,
                window_name,
                name,
                rough_w,
                rough_h,
                cut_w,
                cut_h,
                thickness,
            )
        )
    return Window(window_id, window_name, tuple(panes))
