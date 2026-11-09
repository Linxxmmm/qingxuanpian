"""主窗口：顶部栏 + 左侧筛选 + 照片墙 + 底部状态条。"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

import time
import traceback

from core import paths as _paths
from core.const import BUCKET_DIRNAME, BUCKET_LABEL, flag_text
from core.project import Project

from . import theme, workers
from .photo_model import PhotoGrid, PhotoModel
from .viewer import ViewerDialog

FILTERS = [
    ("all", "全部照片"),
    ("none", "未评分"),
    ("pick", "精选 · 5★"),
    ("maybe", "待定 · 3-4★"),
    ("reject", "淘汰 · 1-2★"),
    ("flagged", "有硬伤"),
]


class ClickableLabel(QLabel):
    """可以点的文字（用来当「换文件夹」入口）。"""

    clicked = Signal()

    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self.setCursor(Qt.PointingHandCursor)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class ArchiveDialog(QDialog):
    """归档确认：选分档、选搬运方式。"""

    def __init__(self, project: Project, parent=None):
        super().__init__(parent)
        self.project = project
        self.setWindowTitle("归档照片")
        self.setFixedWidth(420)
        counts = project.counts()

        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 18)
        lay.setSpacing(12)

        title = QLabel("按打分归档")
        title.setObjectName("DialogTitle")
        lay.addWidget(title)
        sub = QLabel("把照片搬进同名子文件夹，可随时撤销")
        sub.setStyleSheet(f"color: {theme.MUTED};")
        lay.addWidget(sub)

        non_empty = [k for k in ("pick", "maybe", "reject") if counts[k] > 0]
        self.total = sum(counts[k] for k in ("pick", "maybe", "reject"))
        # 只有一个分档有内容时直接选中它；否则先不选，让用户点上面的大按钮
        self.bucket = non_empty[0] if len(non_empty) == 1 else None

        # 一键全部归档：点一下就把三个分档一次搬完（只写一条记录，撤销也一起回来）
        self.all_btn = QPushButton(
            f"一键全部归档（{self.total} 张）" if self.total else "没有可归档的照片"
        )
        self.all_btn.setObjectName("AllPrimary")
        self.all_btn.setEnabled(self.total > 0)
        self.all_btn.clicked.connect(self._archive_all)
        lay.addWidget(self.all_btn)
        if len(non_empty) >= 2:
            hint = QLabel(
                f"精选、待定、淘汰一次分好，共 {self.total} 张；"
                "也可以只归档其中一档 ↓"
            )
        else:
            hint = QLabel(f"按分数分到对应文件夹，共 {self.total} 张")
        hint.setStyleSheet(f"color: {theme.FAINT}; font-size: 12px;")
        hint.setWordWrap(True)
        lay.addWidget(hint)

        self.rows = {}
        for key in ("pick", "maybe", "reject"):
            row = QWidget()
            hl = QHBoxLayout(row)
            hl.setContentsMargins(0, 0, 0, 0)
            btn = QPushButton(
                f"{BUCKET_LABEL[key]}  →  {BUCKET_DIRNAME[key]} 文件夹"
                f"（{counts[key]} 张）"
            )
            btn.setCheckable(True)
            btn.setChecked(key == self.bucket)
            btn.setObjectName("Primary" if key == self.bucket else "")
            btn.setEnabled(counts[key] > 0)
            btn.clicked.connect(lambda _=False, k=key: self._select(k))
            hl.addWidget(btn)
            self.rows[key] = btn
            lay.addWidget(row)

        self.copy_box = QCheckBox("保留副本（不移动原图，多占一份空间）")
        self.copy_box.toggled.connect(lambda _=False: self._refresh())
        lay.addWidget(self.copy_box)

        self.summary = QLabel()
        self.summary.setStyleSheet(f"color: {theme.FAINT};")
        lay.addWidget(self.summary)

        foot = QHBoxLayout()
        foot.addStretch(1)
        cancel = QPushButton("取消")
        cancel.setObjectName("Ghost")
        cancel.clicked.connect(self.reject)
        ok = QPushButton("开始归档")
        ok.setObjectName("Primary")
        ok.setEnabled(self.bucket is not None)
        ok.clicked.connect(self.accept)
        foot.addWidget(cancel)
        foot.addWidget(ok)
        lay.addLayout(foot)

        self.ok = ok
        self._counts = counts
        self._refresh()

    def _archive_all(self) -> None:
        """一键全部归档：直接接受对话框，分档列表交给 buckets()。"""
        self.bucket = "all"
        self.accept()

    def _select(self, key: str) -> None:
        self.bucket = key
        for k, btn in self.rows.items():
            btn.setChecked(k == key)
            btn.setObjectName("Primary" if k == key else "")
            btn.style().unpolish(btn)
            btn.style().polish(btn)
        self._refresh()

    def _refresh(self) -> None:
        mode = "复制" if self.copy_box.isChecked() else "移动"
        self.ok.setEnabled(self.bucket is not None)
        if self.bucket == "all":
            parts = "、".join(
                f"{BUCKET_LABEL[k]} {self._counts.get(k, 0)}"
                for k in ("pick", "maybe", "reject")
                if self._counts.get(k, 0) > 0
            )
            self.summary.setText(f"将{mode} {self.total} 张（{parts}）")
        elif self.bucket is None:
            self.summary.setText(
                f"共 {self.total} 张待归档；"
                "点上方按钮全部分好，或选一档单独归档"
            )
        else:
            n = self._counts.get(self.bucket, 0)
            self.summary.setText(
                f"将{mode} {n} 张照片到「{BUCKET_DIRNAME[self.bucket]}」"
            )

    def buckets(self) -> list[str]:
        """要归档的分档列表：一键全部时是全部非空分档。"""
        if self.bucket == "all":
            return [k for k in ("pick", "maybe", "reject") if self._counts.get(k, 0) > 0]
        return [self.bucket] if self.bucket else []

    def mode(self) -> str:
        return "copy" if self.copy_box.isChecked() else "move"


class EmptyState(QWidget):
    """还没打开文件夹时显示。"""

    open_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setAlignment(Qt.AlignCenter)
        lay.setSpacing(14)

        dot = QLabel("◍")
        dot.setStyleSheet(f"color: {theme.ACCENT}; font-size: 44px;")
        dot.setAlignment(Qt.AlignCenter)
        lay.addWidget(dot)

        title = QLabel("轻选片")
        title.setObjectName("EmptyTitle")
        title.setAlignment(Qt.AlignCenter)
        lay.addWidget(title)

        hint = QLabel(
            "打开一个照片文件夹，打分后一键分到「精选 / 待定 / 淘汰」。\n"
            "自动标出失焦、过曝、分辨率过低的照片，只提示、不替你删。"
        )
        hint.setObjectName("EmptyHint")
        hint.setAlignment(Qt.AlignCenter)
        lay.addWidget(hint)

        btn = QPushButton("打开照片文件夹")
        btn.setObjectName("Primary")
        btn.setFixedWidth(200)
        btn.clicked.connect(self.open_requested.emit)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(btn)
        row.addStretch(1)
        lay.addLayout(row)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("轻选片")
        self.resize(1280, 840)
        self.project: Project | None = None
        self.filter_key = "all"
        self._jobs: list[workers.Job] = []
        self.skipped_note = ""
        self.skipped_detail = ""

        self.model = PhotoModel(thumbs=None)
        self._build_ui()
        self._bind_shortcuts()

        QTimer.singleShot(0, self._restore_state)

    # ------------------------------------------------------------ 界面
    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("Root")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        outer.addWidget(self._build_topbar())

        body = QWidget()
        body_lay = QHBoxLayout(body)
        body_lay.setContentsMargins(0, 0, 0, 0)
        body_lay.setSpacing(0)
        body_lay.addWidget(self._build_sidebar())

        self.stack = QStackedWidget()
        self.empty = EmptyState()
        self.empty.open_requested.connect(self.choose_folder)
        self.grid = PhotoGrid(self.model)
        self.grid.doubleClicked.connect(self._open_viewer_at)
        self.grid.customContextMenuRequested.connect(self._context_menu)
        self.grid.selectionModel().selectionChanged.connect(self._on_selection)
        self.stack.addWidget(self.empty)
        self.stack.addWidget(self.grid)
        body_lay.addWidget(self.stack, 1)
        outer.addWidget(body, 1)

        outer.addWidget(self._build_statusbar())

    def _build_topbar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("TopBar")
        bar.setFixedHeight(76)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(24, 12, 20, 12)
        lay.setSpacing(14)

        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        title = QLabel("轻选片")
        title.setObjectName("AppTitle")
        path_row = QHBoxLayout()
        path_row.setContentsMargins(0, 0, 0, 0)
        path_row.setSpacing(8)
        self.path_label = ClickableLabel("未打开文件夹")
        self.path_label.setObjectName("PathLabel")
        self.path_label.setToolTip("点这里可以换一个照片文件夹（Ctrl+O）")
        self.path_label.clicked.connect(self.choose_folder)
        # 换文件夹：选好一个文件夹之后也要能反悔
        self.switch_btn = QPushButton("更换文件夹")
        self.switch_btn.setObjectName("SwitchBtn")
        self.switch_btn.setToolTip("换一个照片文件夹（Ctrl+O）")
        self.switch_btn.setFixedHeight(23)
        self.switch_btn.setMinimumWidth(74)
        self.switch_btn.setCursor(Qt.PointingHandCursor)
        self.switch_btn.clicked.connect(self.choose_folder)
        path_row.addWidget(self.path_label)
        path_row.addSpacing(8)
        path_row.addWidget(self.switch_btn)
        path_row.addStretch(1)
        title_col.addWidget(title)
        title_col.addLayout(path_row)
        lay.addLayout(title_col)

        self.chip_total = QLabel("0 张")
        self.chip_scored = QLabel("已评 0")
        for chip in (self.chip_total, self.chip_scored):
            chip.setObjectName("StatChip")
            lay.addWidget(chip)

        # 照片目录不可写时常驻显示，避免用户找不到自己的打分
        self.storage_chip = QLabel("")
        self.storage_chip.setObjectName("WarnChip")
        self.storage_chip.hide()
        lay.addWidget(self.storage_chip)
        lay.addStretch(1)

        # 密度切换
        self.density_buttons: dict[str, QPushButton] = {}
        density_box = QWidget()
        dbin = QHBoxLayout(density_box)
        dbin.setContentsMargins(0, 0, 0, 0)
        dbin.setSpacing(4)
        for key in ("S", "M", "L", "XL"):
            b = QPushButton(key)
            b.setCheckable(True)
            b.setFixedSize(38, 30)
            b.setObjectName("DensityBtn")
            b.clicked.connect(lambda _=False, k=key: self._set_density(k))
            self.density_buttons[key] = b
            dbin.addWidget(b)
        density_box.setStyleSheet(
            f"QPushButton#DensityBtn {{ background: {theme.BG}; border-radius: 9px;"
            f" color: {theme.MUTED}; font-weight: 600; padding: 0; }}"
            f"QPushButton#DensityBtn:hover {{ background: {theme.LINE}; }}"
            f"QPushButton#DensityBtn:checked {{ background: {theme.INK}; color: #FFFFFF; }}"
        )
        lay.addWidget(density_box)

        self.scan_btn = QPushButton("重新扫描")
        self.scan_btn.clicked.connect(lambda: self.reload(sync=True))
        self.archive_btn = QPushButton("归档…")
        self.archive_btn.setObjectName("Primary")
        self.archive_btn.clicked.connect(self.open_archive)
        for b in (self.scan_btn, self.archive_btn):
            b.setEnabled(False)
            lay.addWidget(b)

        self.density_buttons["M"].setChecked(True)
        return bar

    def _build_sidebar(self) -> QWidget:
        side = QFrame()
        side.setObjectName("SideBar")
        side.setFixedWidth(208)
        lay = QVBoxLayout(side)
        lay.setContentsMargins(12, 14, 12, 14)
        lay.setSpacing(4)

        cap = QLabel("筛  选")
        cap.setObjectName("SideTitle")
        lay.addWidget(cap)

        self.nav_buttons: dict[str, QPushButton] = {}
        for key, label in FILTERS:
            btn = QPushButton(label)
            btn.setObjectName("NavItem")
            btn.setCheckable(True)
            btn.setChecked(key == "all")
            btn.clicked.connect(lambda _=False, k=key: self.set_filter(k))
            self.nav_buttons[key] = btn
            lay.addWidget(btn)

        lay.addStretch(1)

        self.recent_log = QLabel()
        self.recent_log.setWordWrap(True)
        self.recent_log.setStyleSheet(f"color: {theme.FAINT}; font-size: 11px;")
        lay.addWidget(self.recent_log)

        self.undo_btn = QPushButton("撤销上次归档")
        self.undo_btn.setObjectName("Ghost")
        self.undo_btn.setEnabled(False)
        self.undo_btn.clicked.connect(self.undo_last)
        lay.addWidget(self.undo_btn)
        return side

    def _build_statusbar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("StatusBar")
        bar.setFixedHeight(52)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(20, 8, 20, 8)
        lay.setSpacing(14)

        self.status_text = QLabel("打开一个照片文件夹开始")
        self.status_text.setObjectName("StatusText")
        lay.addWidget(self.status_text, 1)

        self.progress = QProgressBar()
        self.progress.setFixedWidth(220)
        self.progress.setTextVisible(False)
        self.progress.hide()
        lay.addWidget(self.progress)

        self.hint = QLabel("数字键打分 · 方向键切换 · 回车看大图")
        self.hint.setStyleSheet(f"color: {theme.FAINT};")
        lay.addWidget(self.hint)
        return bar

    def _bind_shortcuts(self) -> None:
        for key in "12345":
            QShortcut(QKeySequence(key), self, activated=lambda k=int(key): self.score_selection(k))
        QShortcut(QKeySequence("Ctrl+O"), self, activated=self.choose_folder)
        QShortcut(QKeySequence("Ctrl+Z"), self, activated=self.undo_last)
        QShortcut(QKeySequence("Ctrl+F"), self, activated=self.open_archive)
        QShortcut(QKeySequence("F5"), self, activated=lambda: self.reload(sync=True))
        QShortcut(QKeySequence("Return"), self, activated=self.open_viewer_current)
        QShortcut(QKeySequence("Space"), self, activated=self.open_viewer_current)

    # ------------------------------------------------------------ 打开 / 载入
    def choose_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "选择照片文件夹", str(Path.home()))
        if path:
            self.open_folder(Path(path))

    def open_folder(self, path: Path) -> None:
        try:
            project = Project(path)
        except Exception as exc:
            _log_exception("打开文件夹失败", exc)
            QMessageBox.critical(
                self,
                "打不开这个文件夹",
                f"{path}\n\n{exc}\n\n"
                "如果照片在只读盘或网络盘上，先把文件夹复制到本地磁盘再打开；"
                "也可以点「帮助 → 打开日志目录」把日志发给我看看。",
            )
            return
        if self.project is not None and self.project is not project:
            self.project.close()
        self.project = project
        self.restored_note = ""
        self._report_storage(project)
        self.model.thumbs = self.project.thumbs
        self.path_label.setText(str(path))
        self.store_setting("last_folder", str(path))
        for btn in (self.scan_btn, self.archive_btn):
            btn.setEnabled(True)
        self.stack.setCurrentWidget(self.grid)
        self.reload(sync=True)

    def _report_storage(self, project: Project) -> None:
        if project.portable:
            self.setWindowTitle(f"轻选片 — {project.root}")
            self.path_label.setToolTip(f"打分记录存在这个文件夹里：{project.data_dir}")
            self.storage_chip.hide()
            return
        mode = getattr(project, "mode", "appdata")
        where = "用户目录" if mode == "appdata" else "临时目录"
        # 顶栏路径会被裁切，所以位置提示做成常驻小标签 + 标题 + 悬停提示
        self.setWindowTitle(f"轻选片 — {project.root}（打分存于{where}）")
        self.path_label.setText(str(project.root))
        self.path_label.setToolTip(f"照片文件夹不可写，打分记录改存在{where}：{project.data_dir}")
        self.storage_chip.setText(f"打分存于{where}")
        self.storage_chip.setToolTip(f"照片文件夹不可写，打分记录改存在{where}：{project.data_dir}")
        self.storage_chip.show()
        self.set_status(f"照片文件夹不可写，打分记录改存在{where}（功能不受影响）")

    def reload(self, sync: bool = False) -> None:
        if not self.project:
            return
        if sync:
            self.set_busy("正在扫描文件夹…")
            self._run(
                self.project.sync,
                on_done=self._after_sync,
                busy=True,
            )
        else:
            self.refresh_view()

    def _after_sync(self, stats: dict) -> None:
        skipped = stats.get("skipped") or {}
        skipped_total = int(stats.get("skipped_total") or 0)
        unreadable = int(skipped.pop("(无法访问)", 0)) if skipped else 0
        # 归档把照片搬进子文件夹后路径变了，这里把旧分数接回来的张数
        self.restored_note = (
            f"恢复 {stats['restored']} 张的旧打分" if stats.get("restored") else ""
        )

        # 不管有没有跳过文件，都把这次扫描的结果写进日志：
        # 以后再出现"照片没全读出来"，看日志就知道是没认出来还是读不到
        if skipped or unreadable:
            detail = "、".join(f"{ext}×{n}" for ext, n in skipped.items())
            _write_log(
                f"扫描 {self.project.root}：认出 {stats.get('total', 0)} 张照片，"
                f"跳过 {skipped_total} 个（{detail}"
                + (f"；无法访问 {unreadable} 个" if unreadable else "")
                + "）"
            )
            self.skipped_note = f"已跳过 {skipped_total} 个未纳入的文件"
            self.skipped_detail = detail + (
                f"；其中有 {unreadable} 个文件无法访问" if unreadable else ""
            )
        else:
            self.skipped_note = ""
            self.skipped_detail = ""

        pending = len(self.project.store.pending_analysis(1_000_000))
        if pending:
            self.set_busy(f"正在分析 {pending} 张照片…")
            self.progress.show()
            self.progress.setRange(0, pending)
            job = workers.Job(self.project.analyze_all)
            job.signals.progress.connect(
                lambda done, total: (self.progress.setValue(done),
                                     self.status_text.setText(f"正在分析 {done}/{total}…"))
            )
            job.signals.finished.connect(self._after_analyze)
            job.signals.failed.connect(self._on_error)
            self._jobs.append(job)
            workers.pool(3).start(job)
        else:
            self._after_analyze(0)

    def _after_analyze(self, analyzed: int) -> None:
        self._finish_load(f"分析完成 {analyzed} 张" if analyzed else "已是最新")

    def _finish_load(self, note: str) -> None:
        self.progress.hide()
        self.refresh_view()
        parts = [note]
        if getattr(self, "restored_note", ""):
            parts.append(self.restored_note)
        if self.skipped_note:
            parts.append(self.skipped_note)
        parts.append(f"共 {self.model.rowCount()} 张")
        self.set_status(" · ".join(parts))
        if self.skipped_note:
            self.status_text.setToolTip(
                f"{self.skipped_note}（{self.skipped_detail}）——"
                "不是照片格式的文件不会出现在网格里；"
                "如果其中有你想选的照片，检查它的扩展名是否受支持。"
            )
        else:
            self.status_text.setToolTip("")

    # ------------------------------------------------------------ 视图
    def set_filter(self, key: str) -> None:
        self.filter_key = key
        for k, btn in self.nav_buttons.items():
            btn.setChecked(k == key)
        self.refresh_view()

    def _items_for_filter(self) -> list[dict]:
        store = self.project.store
        if self.filter_key == "flagged":
            return store.photos(flagged_only=True, order="path")
        return store.photos(bucket=self.filter_key)

    def refresh_view(self) -> None:
        if not self.project:
            return
        items = self._items_for_filter()
        self.model.set_items(items)
        self._update_counts()
        self.status_text.setText(f"{FILTERS_DICT.get(self.filter_key, '')}：{len(items)} 张")

    def _update_counts(self) -> None:
        c = self.project.counts() if self.project else {}
        self.chip_total.setText(f"{c.get('total', 0)} 张")
        scored = c.get("total", 0) - c.get("none", 0)
        self.chip_scored.setText(f"已评 {scored}")
        counts = {
            "all": c.get("total", 0),
            "none": c.get("none", 0),
            "pick": c.get("pick", 0),
            "maybe": c.get("maybe", 0),
            "reject": c.get("reject", 0),
            "flagged": c.get("flagged", 0),
        }
        for key, label in FILTERS:
            if key in self.nav_buttons:
                n = counts.get(key, 0)
                self.nav_buttons[key].setText(f"{label}    {n}" if n else label)
        self._update_recent_log()

    def _update_recent_log(self) -> None:
        if not self.project:
            return
        logs = self.project.logs(1)
        if not logs:
            self.recent_log.setText("还没有归档记录")
            self.undo_btn.setEnabled(False)
            return
        log = logs[0]
        if log["undone"]:
            self.recent_log.setText("上次归档已撤销")
            self.undo_btn.setEnabled(False)
            return
        # 一次归档多个分档时，dest 会很长，改说「N 个分档」免得折行
        targets = [t for t in str(log["dest"]).split("、") if t]
        dest = log["dest"] if len(targets) <= 1 else f"{len(targets)} 个分档"
        self.recent_log.setText(f"最近归档：{dest} · {log['count']} 张")
        self.undo_btn.setEnabled(True)

    # ------------------------------------------------------------ 打分
    def score_selection(self, score: int) -> None:
        if not self.project:
            return
        rows = self._selected_rows()
        if not rows:
            current = self.grid.currentIndex()
            if current.isValid():
                rows = [current.row()]
            else:
                return
        ids = {self.model.items[r]["id"] for r in rows if r < len(self.model.items)}
        if not ids:
            return
        self.project.store.set_score(list(ids), score)
        self.model.update_scores(ids, score)
        self._update_counts()
        # 打完分自动跳到下一张，符合"一路看一路打"的节奏
        last = max(rows)
        if score > 0 and last + 1 < self.model.rowCount():
            nxt = self.model.index(last + 1)
            self.grid.setCurrentIndex(nxt)
            self.grid.scrollTo(nxt)
        self.status_text.setText(f"已给 {len(ids)} 张打 {score} 星")

    def _selected_rows(self) -> list[int]:
        return sorted({i.row() for i in self.grid.selectionModel().selectedIndexes()})

    def _on_selection(self, *_args) -> None:
        rows = self._selected_rows()
        if len(rows) == 1 and rows[0] < len(self.model.items):
            item = self.model.items[rows[0]]
            parts = [item["name"]]
            if item.get("width"):
                parts.append(f"{item['width']}×{item['height']}")
            flags = flag_text(int(item.get("flags") or 0))
            if flags:
                parts.append(flags)
            self.status_text.setText("  ·  ".join(parts))

    # ------------------------------------------------------------ 密度
    def _set_density(self, key: str) -> None:
        cols = PhotoGrid.DENSITIES.get(key, 4)
        self.grid.set_density(cols)
        for k, btn in self.density_buttons.items():
            btn.setChecked(k == key)
        self.store_setting("density", key)

    # ------------------------------------------------------------ 看图
    def open_viewer_current(self) -> None:
        index = self.grid.currentIndex()
        self._open_viewer_at(index)

    def _open_viewer_at(self, index) -> None:
        if not index.isValid() or not self.project:
            return
        dialog = ViewerDialog(self.model.items, self.project.root, index.row(), self)
        dialog.score_changed.connect(self._viewer_scored)
        dialog.showFullScreen()
        dialog.exec()

    def _viewer_scored(self, photo_id: int, score: int) -> None:
        if not self.project:
            return
        self.project.store.set_score([photo_id], score)
        self.model.update_scores({photo_id}, score)
        self._update_counts()

    # ------------------------------------------------------------ 归档
    def open_archive(self) -> None:
        if not self.project:
            return
        dialog = ArchiveDialog(self.project, self)
        if dialog.exec() != QDialog.Accepted:
            return
        buckets = dialog.buckets()
        mode = dialog.mode()
        if not buckets:
            self.set_status("没有可归档的照片")
            return
        if len(buckets) == 1:
            self.set_busy(f"正在归档到「{BUCKET_DIRNAME[buckets[0]]}」…")
        else:
            self.set_busy(f"正在归档 {len(buckets)} 个分档…")
        job = workers.Job(self.project.archive, buckets, mode, want_callbacks=False)
        job.signals.finished.connect(self._after_archive)
        job.signals.failed.connect(self._on_error)
        self._jobs.append(job)
        workers.pool(2).start(job)

    def _after_archive(self, result: dict) -> None:
        self.refresh_view()
        msg = f"已归档 {result['count']} 张 → {result['dest']}"
        if result["skipped"]:
            msg += f"（跳过 {result['skipped']} 张）"
        self.set_status(msg)
        errors = result.get("errors") or []
        if errors:
            # 跳过多半是"文件被别的程序占用"，把原因留在提示里
            self.status_text.setToolTip("\n".join(errors))

    def undo_last(self) -> None:
        if not self.project:
            return
        logs = [x for x in self.project.logs(5) if not x["undone"]]
        if not logs:
            self.set_status("没有可撤销的归档")
            return
        log = logs[0]
        if QMessageBox.question(
            self, "撤销归档",
            f"把 {log['count']} 张照片从「{log['dest']}」搬回原位？"
        ) != QMessageBox.Yes:
            return
        result = self.project.undo(log["id"])
        self.refresh_view()
        if result.get("error"):
            self.set_status(result["error"])
        else:
            self.set_status(f"已撤销，还原 {result['restored']} 张")

    # ------------------------------------------------------------ 右键菜单
    def _context_menu(self, pos) -> None:
        index = self.grid.indexAt(pos)
        if not index.isValid() or not self.project:
            return
        self.grid.setCurrentIndex(index)
        item = self.model.items[index.row()]

        menu = self.grid.createStandardContextMenu()
        menu.clear()
        for score in range(6):
            label = "清除评分" if score == 0 else "★" * score
            act = QAction(label, menu)
            act.triggered.connect(lambda _=False, s=score: self.score_item(item["id"], s))
            menu.addAction(act)
        menu.addSeparator()
        reveal = QAction("在资源管理器中显示", menu)
        reveal.triggered.connect(lambda: self._reveal(item["path"]))
        menu.addAction(reveal)
        open_act = QAction("用默认程序打开", menu)
        open_act.triggered.connect(lambda: self._open_external(item["path"]))
        menu.addAction(open_act)
        menu.exec(self.grid.viewport().mapToGlobal(pos))

    def score_item(self, photo_id: int, score: int) -> None:
        self.project.store.set_score([photo_id], score)
        self.model.update_scores({photo_id}, score)
        self._update_counts()

    def _reveal(self, rel: str) -> None:
        path = self.project.root / rel
        if sys.platform.startswith("win"):
            subprocess.Popen(["explorer", "/select,", str(path)])
        else:
            subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(path.parent)])

    def _open_external(self, rel: str) -> None:
        path = self.project.root / rel
        if sys.platform.startswith("win"):
            subprocess.Popen(["cmd", "/c", "start", "", str(path)], shell=False)

    # ------------------------------------------------------------ 杂项
    def _run(self, fn, on_done=None, busy: bool = False, callbacks: bool = False) -> workers.Job:
        job = workers.Job(fn, want_callbacks=callbacks)
        if on_done:
            job.signals.finished.connect(on_done)
        job.signals.failed.connect(self._on_error)
        self._jobs.append(job)
        workers.pool().start(job)
        if busy:
            self.progress.setRange(0, 0)
            self.progress.show()
        return job

    def _on_error(self, message: str) -> None:
        self.progress.hide()
        self.status_text.setText("出错了")
        print("[job failed]\n" + message, file=sys.stderr)
        if getattr(self, "quiet", False):
            return
        QMessageBox.critical(self, "出错了", message)

    def set_busy(self, text: str) -> None:
        self.status_text.setText(text)
        self.progress.setRange(0, 0)
        self.progress.show()

    def set_status(self, text: str) -> None:
        self.progress.hide()
        self.status_text.setText(text)

    def store_setting(self, key: str, value) -> None:
        if self.project:
            self.project.store.set_setting(key, value)

    def _restore_state(self) -> None:
        from PySide6.QtCore import QSettings

        if getattr(self, "quiet", False):
            return  # 截图自检时不恢复上次的窗口大小和文件夹
        settings = QSettings("LitePick", "轻选片")
        geo = settings.value("geometry")
        if geo:
            self.restoreGeometry(geo)
        last = settings.value("last_folder")
        if last and Path(last).is_dir():
            self.open_folder(Path(last))

    def closeEvent(self, event) -> None:
        from PySide6.QtCore import QSettings

        settings = QSettings("LitePick", "轻选片")
        settings.setValue("geometry", self.saveGeometry())
        if self.project:
            self.project.close()
        super().closeEvent(event)


FILTERS_DICT = dict(FILTERS)


def _write_log(text: str) -> None:
    r"""把异常追加写进 %LOCALAPPDATA%\轻选片\logs\app.log，方便排查。"""
    path = _paths.log_path()
    if path is None:
        return
    try:
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        with open(path, "a", encoding="utf-8") as handle:
            handle.write("\n[" + stamp + "] " + text + "\n")
    except Exception:
        pass


def _log_exception(title: str, exc: BaseException) -> None:
    detail = f"{title}: {type(exc).__name__}: {exc}"
    _write_log(detail + "\n" + traceback.format_exc())
