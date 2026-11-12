"""Monochrome outline icons drawn with QPainter (no image assets)."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

from . import theme


def _canvas(size: int = 40) -> tuple[QPixmap, QPainter]:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)
    pen = QPen(QColor(theme.TEXT_DIM), 2.4)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)
    return pixmap, painter


def _playlist(p: QPainter) -> None:
    for y in (11, 20, 29):
        p.drawLine(QPointF(8, y), QPointF(26, y))
    p.drawLine(QPointF(32, 10), QPointF(32, 26))
    path = QPainterPath()
    path.moveTo(32, 26)
    path.cubicTo(28, 28, 26, 30, 27, 32)
    path.cubicTo(28, 34, 31, 33, 32, 31)
    p.drawPath(path)


def _heart_broken(p: QPainter) -> None:
    path = QPainterPath()
    path.moveTo(20, 32)
    path.cubicTo(8, 24, 8, 14, 14, 12)
    path.cubicTo(18, 11, 20, 14, 20, 16)
    p.drawPath(path)
    path2 = QPainterPath()
    path2.moveTo(20, 16)
    path2.cubicTo(20, 14, 22, 11, 26, 12)
    path2.cubicTo(32, 14, 32, 24, 20, 32)
    p.drawPath(path2)
    p.drawLine(QPointF(20, 13), QPointF(17, 20))
    p.drawLine(QPointF(17, 20), QPointF(23, 24))


def _invalid(p: QPainter) -> None:
    p.drawEllipse(QRectF(9, 9, 22, 22))
    p.drawLine(QPointF(14, 26), QPointF(26, 14))


def _download(p: QPainter) -> None:
    p.drawLine(QPointF(20, 9), QPointF(20, 24))
    p.drawLine(QPointF(14, 19), QPointF(20, 25))
    p.drawLine(QPointF(26, 19), QPointF(20, 25))
    p.drawLine(QPointF(11, 29), QPointF(29, 29))


def _review(p: QPainter) -> None:
    p.drawEllipse(QRectF(9, 9, 22, 22))
    path = QPainterPath()
    path.moveTo(17, 17)
    path.cubicTo(17, 13, 24, 13, 24, 17)
    path.cubicTo(24, 20, 20, 20, 20, 22)
    p.drawPath(path)
    p.drawPoint(QPointF(20, 27))


def _failed(p: QPainter) -> None:
    path = QPainterPath()
    path.moveTo(20, 9)
    path.lineTo(31, 30)
    path.lineTo(9, 30)
    path.closeSubpath()
    p.drawPath(path)
    p.drawLine(QPointF(20, 16), QPointF(20, 22))
    p.drawPoint(QPointF(20, 26))


def _downloaded(p: QPainter) -> None:
    p.drawEllipse(QRectF(9, 9, 22, 22))
    p.drawLine(QPointF(14, 20), QPointF(18, 24))
    p.drawLine(QPointF(18, 24), QPointF(26, 15))


def _spectrum(p: QPainter) -> None:
    bars = (10, 17, 24, 14, 29, 20, 12, 23)
    for index, height in enumerate(bars):
        x = 8 + index * 3.2
        p.drawLine(QPointF(x, 30), QPointF(x, 30 - height))


_BUILDERS = {
    "playlist": _playlist,
    "heart_broken": _heart_broken,
    "invalid": _invalid,
    "download": _download,
    "review": _review,
    "failed": _failed,
    "downloaded": _downloaded,
    "spectrum": _spectrum,
}


def outline_icon(name: str, color: str | None = None) -> QIcon:
    pixmap, painter = _canvas()
    if color:
        pen = painter.pen()
        pen.setColor(QColor(color))
        painter.setPen(pen)
    _BUILDERS.get(name, _playlist)(painter)
    painter.end()
    return QIcon(pixmap)


LIST_ICONS = {
    "all": "playlist",
    "removed": "heart_broken",
    "invalid": "invalid",
    "waiting": "download",
    "review": "review",
    "failed": "failed",
    "downloaded": "downloaded",
}
