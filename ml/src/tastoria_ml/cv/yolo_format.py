"""Box conversions to YOLO txt format (class xc yc w h, normalised), pure python."""

from __future__ import annotations

from dataclasses import dataclass

MIN_SIDE = 0.004  # boxes thinner than ~2.5 px at 640 are dropped


@dataclass(frozen=True)
class Box:
    cls: int
    xc: float
    yc: float
    w: float
    h: float
    group_of: bool = False

    def line(self) -> str:
        return f"{self.cls} {self.xc:.6f} {self.yc:.6f} {self.w:.6f} {self.h:.6f}"


def from_corners_norm(cls: int, x0: float, y0: float, x1: float, y1: float, group_of: bool = False) -> Box | None:
    """Normalised corner box (Open Images XMin/YMin/XMax/YMax) -> clipped YOLO box, None if degenerate."""
    x0, x1 = sorted((min(max(x0, 0.0), 1.0), min(max(x1, 0.0), 1.0)))
    y0, y1 = sorted((min(max(y0, 0.0), 1.0), min(max(y1, 0.0), 1.0)))
    w, h = x1 - x0, y1 - y0
    if w < MIN_SIDE or h < MIN_SIDE:
        return None
    return Box(cls, (x0 + x1) / 2, (y0 + y1) / 2, w, h, group_of)


def from_voc(cls: int, xmin: float, ymin: float, xmax: float, ymax: float, width: int, height: int) -> Box | None:
    """Pascal VOC pixel box -> YOLO box (VOC xmin/ymin are 1-based in the spec but exporters vary; we
    treat them as pixel edges, an error of at most one pixel)."""
    return from_corners_norm(cls, xmin / width, ymin / height, xmax / width, ymax / height)


def write_label(boxes: list[Box]) -> str:
    return "".join(b.line() + "\n" for b in boxes)
