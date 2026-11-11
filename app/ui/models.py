"""List model + delegate that paint a netease-style track row.

Title on the first line with a quality badge pinned right; artist · album · duration
underneath in grey. While a song is downloading a thin progress bar runs along the
bottom of its row. Implemented as a delegate rather than per-row widgets so a
700-track list stays smooth.
"""
from __future__ import annotations

from PySide6.QtCore import QAbstractListModel, QModelIndex, QRect, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QStyle, QStyledItemDelegate, QStyleOptionViewItem

from ..core import states
from . import theme

TRACK_ROLE = Qt.UserRole + 1
ROW_HEIGHT = 58


class TrackModel(QAbstractListModel):
    def __init__(self, rows: list | None = None):
        super().__init__()
        self._rows: list = list(rows or [])
        self.progress: dict[int, float] = {}

    def set_rows(self, rows: list) -> None:
        self.beginResetModel()
        self._rows = list(rows)
        self.endResetModel()

    def set_progress(self, song_id: int, value: float | None) -> None:
        if value is None:
            self.progress.pop(song_id, None)
        else:
            self.progress[song_id] = value
        for index, row in enumerate(self._rows):
            if int(row["song_id"]) == song_id:
                self.dataChanged.emit(self.index(index), self.index(index))
                break

    def clear_progress(self) -> None:
        had = bool(self.progress)
        self.progress.clear()
        if had and self._rows:
            self.dataChanged.emit(self.index(0), self.index(len(self._rows) - 1))

    def row_at(self, index: int):
        if 0 <= index < len(self._rows):
            return self._rows[index]
        return None

    def rows(self) -> list:
        return self._rows

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._rows)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        if role == TRACK_ROLE:
            return row
        if role == Qt.DisplayRole:
            return row["title"]
        return None


class TrackDelegate(QStyledItemDelegate):
    def __init__(self, parent=None, list_key: str = states.LIST_ALL):
        super().__init__(parent)
        self.list_key = list_key

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:  # noqa: N802
        return QSize(option.rect.width(), ROW_HEIGHT)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        row = index.data(TRACK_ROLE)
        if row is None:
            return
        model = index.model()
        song_id = int(row["song_id"])
        progress = getattr(model, "progress", {}).get(song_id)

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)

        rect = option.rect
        if option.state & QStyle.State_Selected:
            painter.fillRect(rect, QColor(theme.SELECTED))
        elif option.state & QStyle.State_MouseOver:
            painter.fillRect(rect, QColor(theme.HOVER))

        dim = self.list_key in states.CLOUD_VIEW_LISTS and row["cloud_playable"] == 0
        left = rect.left() + 18
        right = min(rect.right(), painter.viewport().width() - 1) - 18

        title_font = QFont(option.font)
        title_font.setPointSizeF(11.5)
        title_font.setBold(True)
        painter.setFont(title_font)
        painter.setPen(QColor(theme.TEXT_FAINT if dim else theme.TEXT))

        quality = theme.quality_label(row["cloud_max_quality"])
        badge_font = QFont(option.font)
        badge_font.setPointSizeF(8.5)
        badge_font.setBold(True)
        badge_width = QFontMetrics(badge_font).horizontalAdvance(quality) + 16 if quality else 0

        title_rect = QRect(left, rect.top() + 9, right - left - badge_width - 10, 22)
        metrics = QFontMetrics(title_font)
        painter.drawText(title_rect, Qt.AlignLeft | Qt.AlignVCenter,
                         metrics.elidedText(str(row["title"] or ""), Qt.ElideRight, title_rect.width()))

        if quality:
            painter.setFont(badge_font)
            painter.setPen(QPen(QColor(theme.quality_color(row["cloud_max_quality"]))))
            painter.drawText(QRect(right - badge_width, rect.top() + 11, badge_width, 18),
                             Qt.AlignRight | Qt.AlignVCenter, quality)

        sub_font = QFont(option.font)
        sub_font.setPointSizeF(9.5)
        painter.setFont(sub_font)
        painter.setPen(QColor(theme.TEXT_FAINT if dim else theme.TEXT_DIM))
        parts = [row["artist"] or "", row["album"] or "", _duration(row["duration_ms"])]
        subtitle = " · ".join(part for part in parts if part)
        sub_rect = QRect(left, rect.top() + 31, right - left, 18)
        painter.drawText(sub_rect, Qt.AlignLeft | Qt.AlignVCenter,
                         QFontMetrics(sub_font).elidedText(subtitle, Qt.ElideRight, sub_rect.width()))

        label, color = _state_label(row, self.list_key)
        if progress is not None:
            label = f"下载中 {int(progress * 100)}%"
            color = theme.ACCENT
        if label:
            painter.setFont(sub_font)
            painter.setPen(QColor(color))
            width = QFontMetrics(sub_font).horizontalAdvance(label)
            painter.drawText(QRect(right - width, rect.top() + 31, width, 18),
                             Qt.AlignRight | Qt.AlignVCenter, label)

        if progress is not None:
            bar = QRect(left, rect.bottom() - 6, right - left, 3)
            painter.fillRect(bar, QColor(theme.DIVIDER))
            filled = QRect(bar.left(), bar.top(),
                           int(bar.width() * max(0.0, min(1.0, progress))), bar.height())
            painter.fillRect(filled, QColor(theme.ACCENT))
        else:
            painter.setPen(QPen(QColor(theme.DIVIDER)))
            painter.drawLine(rect.left() + 18, rect.bottom(), rect.right() - 18, rect.bottom())
        painter.restore()


def _state_label(row, list_key: str) -> tuple[str, str]:
    """Badge text depends on the view.

    A local list must describe the local state only; showing 「已取消喜欢」 inside
    已下载 mixes two unrelated axes. Cloud lists describe the cloud state.
    """
    local = row["local_state"] or states.NONE
    local_only = row["local_only"] if "local_only" in row.keys() else 0

    if list_key == states.LIST_ALL:
        if row["cloud_playable"] == 0:
            return "失效", theme.STATE_COLORS["invalid"]
        if local_only:
            return "本地", theme.STATE_COLORS["downloaded"]
        if local == states.DOWNLOADED:
            return "已下载", theme.STATE_COLORS["downloaded"]
        if local == states.PENDING_REVIEW:
            return "待确认", theme.STATE_COLORS["pending_review"]
        return "等待下载", theme.STATE_COLORS["none"]

    if list_key == states.LIST_REMOVED:
        return "已取消喜欢", theme.STATE_COLORS["removed_cloud"]
    if list_key == states.LIST_INVALID:
        return "失效", theme.STATE_COLORS["invalid"]

    # Local views: waiting / review / downloaded / failed.
    # A file whose cloud record is gone is "本地" — that is the only thing the user
    # can act on here, and it must not require a re-sync to appear.
    if local_only or row["cloud_present"] == 0:
        return "本地", theme.STATE_COLORS["downloaded"]
    return (states.LOCAL_LABELS.get(local, ""),
            theme.STATE_COLORS.get(local, theme.TEXT_FAINT))


def _duration(value) -> str:
    if not value:
        return ""
    seconds = int(value) // 1000
    return f"{seconds // 60}:{seconds % 60:02d}"
