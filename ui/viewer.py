"""全屏看图：深色沉浸式界面，方向键翻页、数字键打星、滚轮缩放、可旋转。

对应设计稿 ⑤ 全屏评分，并在其上补了放大镜该有的操作：
滚轮/± 缩放（以光标为中心）、拖拽平移、R/⇧R 旋转 90°、F 回到适配窗口。
"""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRect, QRectF, Qt, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QImage,
    QPainter,
    QPainterPath,
    QPen,
    QTransform,
)
from PySide6.QtWidgets import QDialog, QWidget

from core import analyze

from . import theme

_STAR_R = 15.0
_STAR_GAP = 42.0

# 缩放范围：1.0 = 适配窗口，最大放大到 8 倍（够看毛孔了）
_ZOOM_MIN = 1.0
_ZOOM_MAX = 8.0
_ZOOM_STEP = 1.18


class ViewerDialog(QDialog):
    """单张大图浏览，底部五颗星可直接打分，支持缩放/旋转/平移。"""

    score_changed = Signal(int, int)   # photo_id, score

    def __init__(self, items: list[dict], root, index: int = 0, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.items = items
        self.root = root
        self.index = max(0, min(index, len(items) - 1))

        self._image: QImage | None = None      # 解码后的原图（未旋转）
        self._rotated: QImage | None = None    # 按当前角度旋转后的缓存
        self._error = ""
        self._rotation = 0                     # 0 / 90 / 180 / 270
        self._zoom = 1.0                       # 1.0 = 适配窗口
        self._pan = QPointF(0, 0)              # 相对居中位置的偏移（屏幕像素）
        self._hover: str | None = None
        self.setMouseTracking(True)
        self._drag_from: QPointF | None = None
        self._drag_pan = QPointF(0, 0)
        self._dragged = False

        self.setCursor(Qt.ArrowCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self._load()

    # ------------------------------------------------------------ 图片
    def current(self) -> dict | None:
        if 0 <= self.index < len(self.items):
            return self.items[self.index]
        return None

    def _load(self) -> None:
        item = self.current()
        self._image = None
        self._rotated = None
        self._error = ""
        self._zoom = 1.0
        self._pan = QPointF(0, 0)
        self._rotation = 0
        if item:
            try:
                # max_side=0：按原图分辨率解码，不缩不放
                img = analyze.load_full(self.root / item["path"], 0)
                data = img.tobytes("raw", "RGB")
                self._image = QImage(
                    data, img.width, img.height, img.width * 3, QImage.Format_RGB888
                ).copy()
            except Exception as exc:
                self._error = f"{type(exc).__name__}: {exc}"
        self.update()

    # ------------------------------------------------------------ 缩放 / 旋转
    def area_rect(self) -> QRectF:
        """图片可用区域：上方留 56px 状态条，下方留 140px 打分条。"""
        return QRectF(self.rect()).adjusted(0, 56, 0, -140)

    def _display_image(self) -> QImage | None:
        if self._image is None or self._image.isNull():
            return None
        if self._rotation == 0:
            return self._image
        if self._rotated is None:
            transform = QTransform().rotate(self._rotation)
            self._rotated = self._image.transformed(transform, Qt.SmoothTransformation)
        return self._rotated

    def _fit_scale(self) -> float:
        image = self._display_image()
        area = self.area_rect()
        if image is None or not image.width() or not image.height():
            return 1.0
        return min(
            area.width() / image.width(), area.height() / image.height()
        )

    def image_rect(self) -> QRectF:
        """当前缩放/平移下图片在屏幕上的矩形。"""
        image = self._display_image()
        area = self.area_rect()
        if image is None:
            return QRectF()
        scale = self._fit_scale() * self._zoom
        w, h = image.width() * scale, image.height() * scale
        center = area.center() + self._pan
        return QRectF(center.x() - w / 2, center.y() - h / 2, w, h)

    def _clamp_pan(self) -> None:
        """放大后平移不能把图拖出画面（适配状态下图比窗口小，就锁死居中）。"""
        image = self._display_image()
        area = self.area_rect()
        if image is None:
            self._pan = QPointF(0, 0)
            return
        scale = self._fit_scale() * self._zoom
        w, h = image.width() * scale, image.height() * scale
        max_x = max(0.0, (w - area.width()) / 2)
        max_y = max(0.0, (h - area.height()) / 2)
        self._pan = QPointF(
            min(max(self._pan.x(), -max_x), max_x),
            min(max(self._pan.y(), -max_y), max_y),
        )

    def set_zoom(self, zoom: float, anchor: QPointF | None = None) -> None:
        """缩放；传 anchor（通常是光标位置）就围绕它放大，否则围绕画面中心。"""
        old_zoom = self._zoom
        new_zoom = min(_ZOOM_MAX, max(_ZOOM_MIN, zoom))
        if abs(new_zoom - old_zoom) < 1e-4:
            return
        if anchor is not None and prev_rect_is_valid(self):
            area = self.area_rect()
            center = area.center() + self._pan
            ratio = new_zoom / old_zoom
            self._pan = QPointF(
                anchor.x() - (anchor.x() - center.x()) * ratio - area.center().x(),
                anchor.y() - (anchor.y() - center.y()) * ratio - area.center().y(),
            )
        self._zoom = new_zoom
        self._clamp_pan()
        self.update()

    def zoom_by(self, factor: float, anchor: QPointF | None = None) -> None:
        self.set_zoom(self._zoom * factor, anchor)

    def rotate(self, degrees: int) -> None:
        self._rotation = (self._rotation + degrees) % 360
        self._rotated = None
        self._pan = QPointF(0, 0)
        if self._zoom > 1.0:
            # 转 90° 后原来的放大位置已经没意义了，回到适配再看
            self._zoom = 1.0
        self.update()

    def fit(self) -> None:
        self._zoom = 1.0
        self._pan = QPointF(0, 0)
        self.update()

    # ------------------------------------------------------------ 鼠标
    def mousePressEvent(self, event) -> None:
        pos = event.position()

        for name, rect in self._tool_rects():
            if rect.contains(pos):
                self._tool_action(name)
                return

        for i, rect in enumerate(self._star_rects(), start=1):
            if rect.contains(pos):
                self._set_score(i)
                return

        if event.button() == Qt.LeftButton and self._zoom > 1.0:
            self._drag_from = pos
            self._drag_pan = QPointF(self._pan)
            self._dragged = False
            self.setCursor(Qt.ClosedHandCursor)
            return

        # 没放大时，点左半边上一张、右半边下一张
        if self._zoom <= 1.0:
            self.step(-1 if pos.x() < self.width() / 2 else 1)

    def mouseMoveEvent(self, event) -> None:
        if self._drag_from is None:
            # 鼠标没按下时，只更新工具条按钮的悬停高亮
            pos = event.position()
            hover = None
            for name, rect in self._tool_rects():
                if rect.contains(pos):
                    hover = name
                    break
            if hover != self._hover:
                self._hover = hover
                self.setCursor(Qt.PointingHandCursor if hover else Qt.ArrowCursor)
                self.update()
            return
        delta = event.position() - self._drag_from
        if abs(delta.x()) > 2 or abs(delta.y()) > 2:
            self._dragged = True
        self._pan = self._drag_pan + delta
        self._clamp_pan()
        self.update()

    def leaveEvent(self, event) -> None:
        if self._hover is not None:
            self._hover = None
            self.update()
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self._drag_from = None
        self.setCursor(Qt.ArrowCursor)

    def wheelEvent(self, event) -> None:
        angle = event.angleDelta().y()
        if not angle:
            return
        if event.modifiers() & Qt.ShiftModifier:
            self.step(-1 if angle > 0 else 1)
            return
        self.zoom_by(_ZOOM_STEP if angle > 0 else 1 / _ZOOM_STEP, event.position())

    def keyPressEvent(self, event) -> None:
        key = event.key()
        if key in (Qt.Key_Escape, Qt.Key_Return, Qt.Key_Enter):
            if self._zoom > 1.0:
                self.fit()
            else:
                self.close()
        elif key in (Qt.Key_Left, Qt.Key_PageUp):
            self.step(-1)
        elif key in (Qt.Key_Right, Qt.Key_PageDown, Qt.Key_Space):
            self.step(1)
        elif Qt.Key_1 <= key <= Qt.Key_5:
            self._set_score(key - Qt.Key_0)
        elif key in (Qt.Key_Plus, Qt.Key_Equal):
            self.zoom_by(_ZOOM_STEP)
        elif key in (Qt.Key_Minus, Qt.Key_Underscore):
            self.zoom_by(1 / _ZOOM_STEP)
        elif key == Qt.Key_F:
            self.fit()
        elif key == Qt.Key_R:
            self.rotate(-90 if event.modifiers() & Qt.ShiftModifier else 90)
        else:
            super().keyPressEvent(event)

    def step(self, delta: int) -> None:
        target = self.index + delta
        if 0 <= target < len(self.items):
            self.index = target
            self._load()

    def _set_score(self, score: int) -> None:
        item = self.current()
        if not item:
            return
        item["score"] = score
        self.score_changed.emit(item["id"], score)
        self.update()

    # ------------------------------------------------------------ 工具条
    # 顺序：缩小 / 放大 / 适配 / 左转 / 右转；画在图片底部正中间
    _TOOLS = (
        ("zoom_out", "缩小"),
        ("zoom_in", "放大"),
        ("fit", "适配窗口"),
        ("rot_left", "向左旋转 90°"),
        ("rot_right", "向右旋转 90°"),
    )
    _BTN = 38.0
    _BTN_GAP = 6.0
    _BAR_PAD = 8.0
    _BAR_H = 54.0

    def _bar_rect(self) -> QRectF:
        """底部居中的工具条外框。"""
        inner = len(self._TOOLS) * self._BTN + (len(self._TOOLS) - 1) * self._BTN_GAP
        width = inner + self._BAR_PAD * 2
        area = self.area_rect()
        return QRectF((self.width() - width) / 2, area.bottom() - self._BAR_H - 14,
                      width, self._BAR_H)

    def _tool_rects(self) -> list[tuple[str, QRectF]]:
        bar = self._bar_rect()
        y = bar.top() + (bar.height() - self._BTN) / 2
        x = bar.left() + self._BAR_PAD
        out: list[tuple[str, QRectF]] = []
        for name, _tip in self._TOOLS:
            out.append((name, QRectF(x, y, self._BTN, self._BTN)))
            x += self._BTN + self._BTN_GAP
        return out

    def _tool_action(self, name: str) -> None:
        if name == "zoom_in":
            self.zoom_by(_ZOOM_STEP)
        elif name == "zoom_out":
            self.zoom_by(1 / _ZOOM_STEP)
        elif name == "fit":
            self.fit()
        elif name == "rot_left":
            self.rotate(-90)
        elif name == "rot_right":
            self.rotate(90)

    def _paint_tools(self, p: QPainter) -> None:
        bar = self._bar_rect()
        # 半透明深色胶囊，压在任何照片上都看得清
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(QColor(10, 11, 13, 170)))
        p.drawRoundedRect(bar, bar.height() / 2, bar.height() / 2)

        for name, rect in self._tool_rects():
            highlighted = name == self._hover or (name == "fit" and self._zoom <= 1.01)
            if highlighted:
                p.setPen(Qt.NoPen)
                p.setBrush(QBrush(QColor(255, 255, 255, 40 if name == self._hover else 26)))
                p.drawRoundedRect(rect, 10, 10)
            self._paint_tool_icon(p, name, rect)

        # 放大时在胶囊右边标百分比
        if self._zoom > 1.01:
            p.setPen(QPen(QColor(255, 255, 255, 215)))
            p.setFont(theme.font(12, bold=True))
            p.drawText(
                QRectF(bar.right() + 12, bar.top(), 90, bar.height()),
                Qt.AlignVCenter | Qt.AlignLeft,
                f"{int(round(self._zoom * 100))}%",
            )

    def _paint_tool_icon(self, p: QPainter, name: str, rect: QRectF) -> None:
        """纯手画图标：放大镜、四角展开括号、环形旋转箭头。"""
        c = rect.center()
        pen = QPen(QColor(255, 255, 255, 230), 1.9)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)

        if name in ("zoom_in", "zoom_out"):
            r = 6.3
            lens = QPointF(c.x() - 1.8, c.y() - 1.8)
            p.drawEllipse(lens, r, r)
            p.drawLine(QPointF(lens.x() + 4.6, lens.y() + 4.6),
                       QPointF(c.x() + 8.2, c.y() + 8.2))
            p.drawLine(QPointF(lens.x() - 3.0, lens.y()), QPointF(lens.x() + 3.0, lens.y()))
            if name == "zoom_in":
                p.drawLine(QPointF(lens.x(), lens.y() - 3.0), QPointF(lens.x(), lens.y() + 3.0))
        elif name == "fit":
            d, arm = 7.4, 4.4
            for sx, sy in ((-1, -1), (1, -1), (-1, 1), (1, 1)):
                corner = QPointF(c.x() + sx * d, c.y() + sy * d)
                p.drawLine(corner, QPointF(corner.x() - sx * arm, corner.y()))
                p.drawLine(corner, QPointF(corner.x(), corner.y() - sy * arm))
        else:  # rot_left / rot_right
            spin = -1 if name == "rot_left" else 1
            r = 7.8
            p.drawArc(QRectF(c.x() - r, c.y() - r, 2 * r, 2 * r),
                      int(55 * 16), int(250 * 16 * spin))
            # 箭头画在弧的一端，指向切线方向
            ang = math.radians(55)
            tip = QPointF(c.x() + r * math.cos(ang), c.y() - r * math.sin(ang))
            p.drawLine(tip, QPointF(tip.x() + 3.4 * spin, tip.y() + 2.6))
            p.drawLine(tip, QPointF(tip.x() - 1.2 * spin, tip.y() + 3.6))

    # ------------------------------------------------------------ 绘制
    def _star_rects(self) -> list[QRectF]:
        y = self.height() - 104
        total = _STAR_GAP * 4
        start_x = self.width() / 2 - total / 2
        rects = []
        for i in range(5):
            cx = start_x + i * _STAR_GAP
            rects.append(QRectF(cx - 20, y - 20, 40, 40))
        return rects

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        p.fillRect(self.rect(), QBrush(QColor("#0A0B0D")))

        image = self._display_image()
        area = self.area_rect()
        if image is not None:
            p.save()
            p.setClipRect(area)
            target = self.image_rect()
            # 图片后面垫一层更深，让边界清楚
            p.fillRect(target.adjusted(-1, -1, 1, 1), QBrush(QColor("#000000")))
            p.drawImage(target, image)
            p.restore()
        else:
            p.setPen(QPen(QColor(theme.FAINT)))
            p.setFont(theme.font(14))
            p.drawText(area, Qt.AlignCenter, self._error or "无法读取这张照片")

        self._paint_top(p)
        self._paint_tools(p)
        self._paint_bottom(p)
        p.end()

    def _paint_top(self, p: QPainter) -> None:
        # 工具条已经移到底部，右上角只留页码
        right = int(self.width() - 24)
        p.setPen(QPen(QColor(255, 255, 255, 200)))
        p.setFont(theme.font(13))
        p.drawText(QRect(24, 18, max(80, right - 120), 24), Qt.AlignLeft, self._clock_note())
        text = f"{self.index + 1} / {len(self.items)}"
        p.setPen(QPen(QColor(255, 255, 255, 235)))
        p.drawText(QRect(0, 18, right, 24), Qt.AlignRight, text)

    def _clock_note(self) -> str:
        item = self.current() or {}
        if self._image and not self._image.isNull():
            note = f"{self._image.width()} × {self._image.height()} 原图"
            if self._rotation:
                note += f" · 已旋转 {self._rotation}°"
            return note
        w, h = item.get("width") or 0, item.get("height") or 0
        return f"{w} × {h}" if w and h else ""

    def _paint_bottom(self, p: QPainter) -> None:
        item = self.current() or {}
        base_y = self.height() - 152

        p.setPen(QPen(QColor(255, 255, 255, 240)))
        p.setFont(theme.font(15, bold=True))
        p.drawText(QRect(32, base_y, self.width() - 64, 26), Qt.AlignLeft, item.get("name", ""))

        score = int(item.get("score") or 0)
        for i, rect in enumerate(self._star_rects(), start=1):
            self._paint_star(p, rect.center(), filled=i <= score)

        p.setPen(QPen(QColor(255, 255, 255, 120)))
        p.setFont(theme.font(11))
        p.drawText(
            QRect(0, self.height() - 58, self.width(), 20),
            Qt.AlignCenter,
            "滚轮或点底部图标放大 · 拖拽平移 · R 旋转 · 点星星或按 1-5 打分 · ←/→ 切换 · Esc 关闭",
        )

    @staticmethod
    def _paint_star(p: QPainter, center: QPointF, filled: bool) -> None:
        path = QPainterPath()
        for k in range(10):
            angle = math.pi / 2 + k * math.pi / 5
            radius = _STAR_R if k % 2 == 0 else _STAR_R * 0.42
            px = center.x() - radius * math.cos(angle)
            py = center.y() - radius * math.sin(angle)
            if k == 0:
                path.moveTo(px, py)
            else:
                path.lineTo(px, py)
        path.closeSubpath()
        if filled:
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(theme.C_GOLD))
        else:
            p.setPen(QPen(QColor(255, 255, 255, 110), 1.6))
            p.setBrush(Qt.NoBrush)
        p.drawPath(path)


def prev_rect_is_valid(viewer: ViewerDialog) -> bool:
    """锚点缩放只在图片确实可见时有意义。"""
    image = viewer._display_image()
    return bool(image and not image.isNull())
