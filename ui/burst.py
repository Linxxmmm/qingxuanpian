"""连拍组处理对话框：一组一组过，选一张留下，其余标为淘汰。

对应设计稿 ⑦ 连拍组去重。
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from core.const import FLAG_LABELS, flag_text

from . import theme


def _pixmap(cache, root, item: dict, side: int) -> QPixmap:
    img = cache.get(item["path"], item.get("mtime", 0), cache.closest_size(side))
    if img is None:
        return QPixmap()
    data = img.tobytes("raw", "RGB")
    from PySide6.QtGui import QImage

    qimg = QImage(data, img.width, img.height, img.width * 3, QImage.Format_RGB888).copy()
    return QPixmap.fromImage(qimg).scaled(
        side, side, Qt.KeepAspectRatio, Qt.SmoothTransformation
    )


class Thumb(QFrame):
    """组内一张候选图，点一下表示「留这张」。"""

    picked = Signal(int)

    def __init__(self, cache, root, item: dict, is_best: bool, ratio: float = 1.0, parent=None):
        super().__init__(parent)
        self.item = item
        self.setFixedSize(148, 168)
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet(
            f"QFrame {{ background: {theme.CARD}; border-radius: 12px;"
            f" border: {'2px solid ' + theme.ACCENT if is_best else '1px solid ' + theme.LINE}; }}"
        )
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)

        pic = QLabel()
        pic.setAlignment(Qt.AlignCenter)
        pm = _pixmap(cache, root, item, 260)
        if pm.isNull():
            pic.setText("无法预览")
            pic.setStyleSheet(f"color: {theme.FAINT};")
        else:
            pic.setPixmap(pm.scaled(128, 112, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        pic.setFixedHeight(112)
        lay.addWidget(pic)

        cap = QLabel()
        if is_best:
            cap.setText("BEST · 最清晰")
            cap.setStyleSheet(f"color: {theme.ACCENT}; font-weight: 600;")
        else:
            flags = int(item.get("flags") or 0)
            reason = flag_text(flags) or f"清晰度 {ratio:.2f}×"
            cap.setText(reason)
            cap.setStyleSheet(f"color: {theme.MUTED};")
        cap.setAlignment(Qt.AlignCenter)
        lay.addWidget(cap)

    def mousePressEvent(self, event) -> None:
        self.picked.emit(self.item["id"])


class GroupCard(QFrame):
    """一组连拍。"""

    keep_signal = Signal(object)

    def __init__(self, cache, root, group_no: int, members: list[dict], parent=None):
        super().__init__(parent)
        self.members = members
        self.done = False
        self.setStyleSheet(
            f"QFrame#Card {{ background: {theme.CARD}; border-radius: 16px;"
            f" border: 1px solid {theme.LINE}; }}"
        )
        self.setObjectName("Card")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 14, 16, 14)
        outer.setSpacing(10)

        head = QHBoxLayout()
        title = QLabel(f"连拍组 {group_no} · {len(members)} 张")
        title.setFont(theme.font(14, bold=True))
        hint = QLabel("已按清晰度排序，点任意一张表示「留这张」")
        hint.setStyleSheet(f"color: {theme.FAINT};")
        head.addWidget(title)
        head.addSpacing(8)
        head.addWidget(hint)
        head.addStretch(1)
        self.keep_btn = QPushButton(f"保留第 1 张，其余标为淘汰")
        self.keep_btn.setObjectName("Primary")
        self.skip_btn = QPushButton("跳过")
        self.skip_btn.setObjectName("Ghost")
        head.addWidget(self.skip_btn)
        head.addWidget(self.keep_btn)
        outer.addLayout(head)

        row = QHBoxLayout()
        row.setSpacing(10)
        self.thumbs: list[Thumb] = []
        best_sharp = members[0].get("sharp") or 0.0
        for i, member in enumerate(members[:4]):
            ratio = (member.get("sharp") or 0.0) / best_sharp if best_sharp else 1.0
            thumb = Thumb(cache, root, member, is_best=(i == 0), ratio=ratio)
            thumb.picked.connect(self._keep)
            row.addWidget(thumb)
            self.thumbs.append(thumb)
        if len(members) > 4:
            more = QLabel(f"+{len(members) - 4}")
            more.setAlignment(Qt.AlignCenter)
            more.setFixedSize(56, 168)
            more.setStyleSheet(
                f"color: {theme.MUTED}; background: {theme.LINE}; border-radius: 12px;"
                f" font-weight: 600;"
            )
            row.addWidget(more)
        row.addStretch(1)
        outer.addLayout(row)

    # ---------------- 交互 ----------------
    def _keep(self, keep_id: int) -> None:
        self.apply(keep_id)

    def apply(self, keep_id: int) -> None:
        scores = {}
        for member in self.members:
            scores[member["id"]] = 5 if member["id"] == keep_id else 1
        self.keep_signal.emit(scores)
        self.mark_done()

    def mark_done(self) -> None:
        self.done = True
        self.setStyleSheet(
            f"QFrame#Card {{ background: {theme.BG}; border-radius: 16px;"
            f" border: 1px dashed {theme.LINE}; }}"
        )
        for child in self.findChildren(QPushButton):
            child.setEnabled(False)


class BurstDialog(QDialog):
    """把所有连拍组一次过完。"""

    scores_ready = Signal(object)   # {photo_id: score}

    def __init__(self, cache, root, groups: list[dict], members_of, parent=None):
        super().__init__(parent)
        self.setWindowTitle("连拍组去重")
        height = min(760, 210 + 200 * max(1, len(groups)))
        self.resize(900, height)
        self.setStyleSheet(f"QDialog {{ background: {theme.BG}; }}")
        self._pending: dict[int, dict] = {}

        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 16)
        lay.setSpacing(12)

        head = QHBoxLayout()
        title = QLabel(f"发现 {len(groups)} 组连拍")
        title.setObjectName("DialogTitle")
        sub = QLabel("同一次按快门连拍的相似照片，留下最清晰的一张即可")
        sub.setStyleSheet(f"color: {theme.MUTED};")
        head.addWidget(title)
        head.addSpacing(10)
        head.addWidget(sub)
        head.addStretch(1)
        self.all_btn = QPushButton("全部保留最清晰的一张")
        self.all_btn.setObjectName("Primary")
        head.addWidget(self.all_btn)
        lay.addLayout(head)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        holder = QWidget()
        self.vbox = QVBoxLayout(holder)
        self.vbox.setContentsMargins(0, 0, 8, 0)
        self.vbox.setSpacing(12)

        self.cards: list[GroupCard] = []
        for i, group in enumerate(groups, start=1):
            members = members_of(group["group_id"])
            if not members:
                continue
            card = GroupCard(cache, root, i, members)
            card.keep_signal.connect(self._on_card_keep)
            self.cards.append(card)
            self.vbox.addWidget(card)
        self.vbox.addStretch(1)
        scroll.setWidget(holder)
        lay.addWidget(scroll, 1)

        foot = QHBoxLayout()
        self.tip = QLabel("所有操作都会立刻写入评分，关掉窗口也能在网格里看到")
        self.tip.setStyleSheet(f"color: {theme.FAINT};")
        foot.addWidget(self.tip)
        foot.addStretch(1)
        close_btn = QPushButton("完成")
        close_btn.setObjectName("Primary")
        close_btn.clicked.connect(self.accept)
        foot.addWidget(close_btn)
        lay.addLayout(foot)

        self.all_btn.clicked.connect(self._keep_all_best)

    # ---------------- 行为 ----------------
    def _on_card_keep(self, scores: dict) -> None:
        self._pending.update(scores)
        self.scores_ready.emit(dict(scores))

    def _keep_all_best(self) -> None:
        for card in self.cards:
            if not card.done and card.members:
                card.apply(card.members[0]["id"])
