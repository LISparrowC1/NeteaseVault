"""Program icon: a music note (top-left) interlocking with a download arrow
(bottom-right). Transparent background, one accent colour, negative space where the
two shapes meet.
"""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

ACCENT = "#2E7BE7"


def _note_path(s: float) -> QPainterPath:
    path = QPainterPath()
    path.setFillRule(Qt.WindingFill)
    path.addEllipse(QRectF(s * 0.08, s * 0.42, s * 0.28, s * 0.19))
    path.addRect(QRectF(s * 0.285, s * 0.10, s * 0.085, 0.42 * s))
    flag = QPainterPath()
    flag.moveTo(s * 0.32, s * 0.10)
    flag.cubicTo(s * 0.48, s * 0.13, s * 0.54, s * 0.22, s * 0.56, s * 0.34)
    flag.cubicTo(s * 0.48, s * 0.26, s * 0.40, s * 0.23, s * 0.32, s * 0.23)
    flag.closeSubpath()
    path.addPath(flag)
    return path.simplified()


def _arrow_path(s: float) -> QPainterPath:
    path = QPainterPath()
    path.setFillRule(Qt.WindingFill)
    path.addRect(QRectF(s * 0.47, s * 0.34, s * 0.15, s * 0.30))
    head = QPainterPath()
    head.moveTo(s * 0.30, s * 0.60)
    head.lineTo(s * 0.79, s * 0.60)
    head.lineTo(s * 0.545, s * 0.92)
    head.closeSubpath()
    path.addPath(head)
    return path.simplified()


def paint_icon(painter: QPainter, size: int) -> None:
    painter.setRenderHint(QPainter.Antialiasing, True)
    s = float(size)
    accent = QColor(ACCENT)

    # erase a gap around the arrow so the two shapes read as interlocking
    painter.setCompositionMode(QPainter.CompositionMode_Clear)
    gap = QPen(QColor(0, 0, 0, 255), max(2.0, s * 0.075))
    gap.setJoinStyle(Qt.RoundJoin)
    gap.setCapStyle(Qt.RoundCap)
    painter.setPen(gap)
    painter.setBrush(Qt.NoBrush)
    painter.drawPath(_arrow_path(s))

    painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
    painter.setPen(Qt.NoPen)
    painter.setBrush(accent)
    painter.drawPath(_note_path(s))
    painter.drawPath(_arrow_path(s))


def icon_pixmap(size: int) -> QPixmap:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    paint_icon(painter, size)
    painter.end()
    return pixmap


def app_icon() -> QIcon:
    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        icon.addPixmap(icon_pixmap(size))
    return icon
