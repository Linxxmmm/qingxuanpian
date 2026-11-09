"""网格模型与绘制：缩略图列表 + 自绘的星级/硬伤角标。

用 QListView + 自绘 delegate，而不是 QListWidget.setIcon：
这样才能完全控制圆角、角标位置、选中态，也才撑得住上千张照片。
"""

from __future__ import annotations

import math
from typing import Callable

from PySide6.QtCore import QAbstractListModel, QModelIndex, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontMetrics,
    QImage,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import QListView, QStyle, QStyledItemDelegate, QStyleOptionViewItem

from core import analyze
from core.const import flag_short

from . import theme
from .workers import ThumbJob, ThumbSignals, pool

PHOTO_ROLE = Qt.UserRole + 1


class PhotoModel(QAbstractListModel):
    """持有当前筛选结果；缩略图异步加载，加载完通知视图重绘。"""

    def __init__(self, thumbs, parent=None):
        super().__init__(parent)
        self.thumbs = thumbs
        self.items: list[dict] = []
        self._images: dict[tuple[str, int], QImage] = {}
        self._pending: set[tuple[str, int]] = set()
        self._thumb_size = 320
        self.thumb_signals = ThumbSignals()
        self.thumb_signals.loaded.connect(self._on_loaded)
        self._pool = pool(3)

    # ---------------- Qt 模型接口 ----------------
    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.items)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid() or index.row() >= len(self.items):
            return None
        item = self.items[index.row()]
        if role == PHOTO_ROLE:
            return item
        if role == Qt.DisplayRole:
            return item["name"]
        if role == Qt.ToolTipRole:
            return f"{item['name']}\n{theme_ratio(item)}"
        return None

    def flags(self, index):
        base = super().flags(index)
        if index.isValid():
            base |= Qt.ItemIsSelectable | Qt.ItemIsEnabled
        return base

    # ---------------- 数据装载 ----------------
    def set_items(self, items: list[dict]) -> None:
        self.beginResetModel()
        self.items = list(items)
        self.endResetModel()

    def item_at(self, row: int) -> dict | None:
        if 0 <= row < len(self.items):
            return self.items[row]
        return None

    def update_scores(self, ids: set[int], score: int) -> None:
        """外部改了分数后，只刷新受影响的行。"""
        for row, item in enumerate(self.items):
            if item["id"] in ids:
                item["score"] = score
                self.dataChanged.emit(self.index(row), self.index(row), [])

    def set_thumb_size(self, size: int) -> None:
        size = self.thumbs.closest_size(size)
        if size != self._thumb_size:
            self._thumb_size = size
            self._images.clear()
            self._pending.clear()

    # ---------------- 缩略图 ----------------
    def image_for(self, item: dict) -> QImage | None:
        key = (item["path"], self._thumb_size)
        img = self._images.get(key)
        if img is not None:
            return img
        if key not in self._pending:
            self._pending.add(key)
            self._pool.start(
                ThumbJob(
                    self.thumbs, item["path"], item.get("mtime", 0),
                    self._thumb_size, self.thumb_signals, priority=1,
                )
            )
        return None

    def _on_loaded(self, rel: str, size: int, image: QImage) -> None:
        key = (rel, size)
        self._pending.discard(key)
        if image.isNull():
            return
        self._images[key] = image
        if size != self._thumb_size:
            return
        for row, item in enumerate(self.items):
            if item["path"] == rel:
                self.dataChanged.emit(self.index(row), self.index(row), [])


def theme_ratio(item: dict) -> str:
    w, h = item.get("width") or 0, item.get("height") or 0
    if w and h:
        return f"{w} × {h}"
    return "尺寸未知"


class PhotoDelegate(QStyledItemDelegate):
    """自绘一张照片卡片：圆角图 + 底部星级 + 顶部硬伤标。"""

    def __init__(self, model: PhotoModel, size_provider: Callable[[], int], parent=None):
        super().__init__(parent)
        self.model = model
        self.size_provider = size_provider

    def sizeHint(self, option, index) -> QSize:
        cell = self.size_provider()
        return QSize(cell, cell)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        item = index.data(PHOTO_ROLE)
        if not item:
            return
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)

        cell = self.size_provider()
        gap = 4
        rect = QRectF(option.rect).adjusted(gap, gap, -gap, -gap)
        radius = 8

        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)
        painter.setClipPath(path)

        image = self.model.image_for(item)
        if image is None or image.isNull():
            painter.fillRect(rect, QBrush(QColor("#E8EAEE")))
            if item.get("analyzed") and not item.get("width"):
                self._draw_placeholder(painter, rect, item)
        else:
            self._draw_cover(painter, rect, image)

        # 选中：描边 + 轻微压暗，不遮挡画面
        selected = bool(option.state & QStyle.State_Selected)
        if selected:
            painter.fillRect(rect, QBrush(QColor(0, 0, 0, 38)))
            painter.setClipping(False)
            pen = QPen(QColor(theme.INK), 2.4)
            painter.setPen(pen)
            painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), radius, radius)

        painter.setClipping(False)

        # 底部评分：0 星显示空心星，1-5 星显示金色实心
        self._draw_stars(painter, rect, int(item.get("score") or 0))

        # 顶部硬伤标
        label = flag_short(int(item.get("flags") or 0))
        if label:
            self._draw_badge(painter, rect, label)

        painter.restore()

    # ------------------------------------------------------------ 绘制细节
    @staticmethod
    def _draw_placeholder(painter: QPainter, rect: QRectF, item: dict) -> None:
        """读不出画面的照片（损坏文件、没内嵌预览的 RAW）也要占一格、能打分。"""
        painter.save()
        painter.setClipping(False)
        cx = rect.center().x()

        # 一个淡淡的"照片"轮廓，告诉用户这里本来有张图
        icon = QRectF(cx - 17, rect.center().y() - 26, 34, 26)
        painter.setPen(QPen(QColor("#B9BEC7"), 1.6))
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(icon, 4, 4)
        painter.drawLine(
            icon.left() + 4, icon.bottom() - 6, icon.left() + 13, icon.top() + 9
        )
        painter.drawLine(
            icon.left() + 13, icon.top() + 9, icon.right() - 4, icon.bottom() - 6
        )

        font = QFont()
        font.setPixelSize(12)
        painter.setFont(font)
        painter.setPen(QColor("#7C828C"))
        text_rect = QRectF(rect.left() + 6, rect.center().y() + 8, rect.width() - 12, 18)
        painter.drawText(text_rect, Qt.AlignHCenter | Qt.AlignTop, "无法预览")

        name = str(item.get("name") or "")
        if name:
            font.setPixelSize(11)
            painter.setFont(font)
            painter.setPen(QColor("#9AA0A8"))
            metrics = QFontMetrics(font)
            elided = metrics.elidedText(name, Qt.ElideMiddle, int(rect.width() - 16))
            painter.drawText(
                QRectF(rect.left() + 8, rect.center().y() + 26, rect.width() - 16, 16),
                Qt.AlignHCenter | Qt.AlignTop,
                elided,
            )
        painter.restore()

    @staticmethod
    def _draw_cover(painter: QPainter, rect: QRectF, image: QImage) -> None:
        """等比放大裁切填满格子（cover），不变形。"""
        iw, ih = image.width(), image.height()
        if not iw or not ih:
            return
        scale = max(rect.width() / iw, rect.height() / ih)
        w, h = iw * scale, ih * scale
        target = QRectF(
            rect.center().x() - w / 2, rect.center().y() - h / 2, w, h
        )
        painter.drawImage(target, image)

    @staticmethod
    def _draw_stars(painter: QPainter, rect: QRectF, score: int) -> None:
        if score <= 0:
            return
        r = 10.0
        # 1 星时宽度只有一颗星，别让胶囊缩成圆圈
        box_w = max(26.0, score * r * 0.95 + 14)
        box = QRectF(rect.left() + 8, rect.bottom() - 30, box_w, 22)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(QColor(0, 0, 0, 140)))
        painter.drawRoundedRect(box, 7, 7)

        painter.setBrush(QBrush(theme.C_GOLD))
        for i in range(score):
            cx = box.left() + (box.width() - (score * r * 0.95)) / 2 + i * r * 0.95 + r * 0.1
            cy = box.center().y()
            star = QPainterPath()
            # 五角星
            for k in range(10):
                angle = math.pi / 2 + k * math.pi / 5
                radius = r * 0.5 if k % 2 == 0 else r * 0.21
                px = cx + radius * math.cos(angle) * -1
                py = cy - radius * math.sin(angle)
                if k == 0:
                    star.moveTo(px, py)
                else:
                    star.lineTo(px, py)
            star.closeSubpath()
            painter.drawPath(star)

    @staticmethod
    def _draw_badge(painter: QPainter, rect: QRectF, text: str) -> None:
        from PySide6.QtGui import QFont, QFontMetrics

        f = QFont(theme.FONT_FAMILY, 10)
        f.setBold(True)
        painter.setFont(f)
        fm = QFontMetrics(f)
        w = fm.horizontalAdvance(text) + 14
        box = QRectF(rect.left() + 8, rect.top() + 8, w, 20)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(QColor(255, 90, 54, 235)))
        painter.drawRoundedRect(box, 10, 10)
        painter.setPen(QPen(QColor(255, 255, 255)))
        painter.drawText(box, Qt.AlignCenter, text)


class PhotoGrid(QListView):
    """按列数自适应格子大小的照片墙。"""

    density_changed = Signal(int)

    DENSITIES = {"S": 5, "M": 4, "L": 3, "XL": 2}

    def __init__(self, model: PhotoModel, parent=None):
        super().__init__(parent)
        self.photo_model = model
        self.cols = 4
        self.setModel(model)
        self.delegate = PhotoDelegate(model, self.cell_size, self)
        self.setItemDelegate(self.delegate)

        self.setViewMode(QListView.IconMode)
        self.setFlow(QListView.LeftToRight)
        self.setWrapping(True)
        self.setResizeMode(QListView.Adjust)
        self.setMovement(QListView.Static)
        self.setSpacing(0)
        self.setUniformItemSizes(True)
        self.setSelectionMode(QListView.ExtendedSelection)
        self.setVerticalScrollMode(QListView.ScrollPerPixel)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.verticalScrollBar().setSingleStep(24)
        self.setContextMenuPolicy(Qt.CustomContextMenu)

    # ---------------- 密度 ----------------
    def cell_size(self) -> int:
        viewport_w = max(self.viewport().width(), 120)
        padding = 16
        usable = viewport_w - padding * 2
        return max(140, int(usable / self.cols))

    def set_density(self, cols: int) -> None:
        self.cols = max(1, cols)
        self.photo_model.set_thumb_size(self.cell_size() * 2)
        self.setGridSize(QSize(self.cell_size(), self.cell_size()))
        self.density_changed.emit(self.cols)

    def density_key(self) -> str:
        for key, cols in self.DENSITIES.items():
            if cols == self.cols:
                return key
        return "M"

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.photo_model.set_thumb_size(self.cell_size() * 2)
        self.setGridSize(QSize(self.cell_size(), self.cell_size()))
