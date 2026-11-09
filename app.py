"""轻选片 · 本地选片助手

启动方式：
    python app.py                      # 打开上次的文件夹
    python app.py D:\\照片\\婚礼          # 直接打开指定文件夹
    python app.py D:\\照片 --shot ui.png --delay 4000   # 截图自检（开发用）
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import QApplication

sys.path.insert(0, str(Path(__file__).resolve().parent))

from core import paths  # noqa: E402
from ui import theme  # noqa: E402
from ui.main_window import MainWindow  # noqa: E402


def _install_excepthook() -> None:
    """任何没接住的异常都落进日志，用户可以直接把文件发过来。"""
    import traceback

    def hook(exc_type, exc, tb):
        text = "".join(traceback.format_exception(exc_type, exc, tb))
        path = paths.log_path()
        if path is not None:
            try:
                with open(path, "a", encoding="utf-8") as handle:
                    handle.write("\n[未捕获异常]\n")
                    handle.write(text)
                    handle.write("\n")
            except Exception:
                pass
        print(text, file=sys.stderr)

    sys.excepthook = hook


def parse_args(argv: list[str]) -> tuple[Path | None, str | None, int, str]:
    folder: Path | None = None
    shot: str | None = None
    delay = 3500
    mode = "grid"
    i = 1
    while i < len(argv):
        arg = argv[i]
        if arg == "--shot" and i + 1 < len(argv):
            shot = argv[i + 1]
            i += 2
            continue
        if arg == "--delay" and i + 1 < len(argv):
            delay = int(argv[i + 1])
            i += 2
            continue
        if arg == "--mode" and i + 1 < len(argv):
            mode = argv[i + 1]
            i += 2
            continue
        if not arg.startswith("-") and folder is None:
            folder = Path(arg)
        i += 1
    return folder, shot, delay, mode


def main() -> int:
    folder, shot, delay, mode = parse_args(sys.argv)
    _install_excepthook()

    QApplication.setAttribute(Qt.AA_DontUseNativeMenuBar, False)
    app = QApplication(sys.argv[:1])
    app.setApplicationName("轻选片")
    app.setOrganizationName("LitePick")
    app.setFont(QFont(theme.FONT_FAMILY, theme.FS_BODY))
    app.setStyleSheet(theme.QSS)
    app.setWindowIcon(QIcon(theme.asset("app.png")))

    window = MainWindow()
    window.quiet = bool(shot)
    window.show()

    if folder and folder.is_dir():
        QTimer.singleShot(120, lambda: window.open_folder(folder))

    if shot:
        def _capture() -> None:
            target = _open_mode(window, mode) or window
            QTimer.singleShot(900, lambda: _save(target, shot, app))

        QTimer.singleShot(delay, _capture)

    return app.exec()


def _open_mode(window: MainWindow, mode: str):
    """截图自检用：把指定对话框打开，返回要截的窗口。"""
    if mode == "viewer":
        from ui.viewer import ViewerDialog

        dialog = ViewerDialog(window.model.items, window.project.root, 1, window)
        dialog.showFullScreen()
        return dialog
    if mode == "viewer_zoom":
        # 截图自检：放大到 2 倍并转 90°，看缩放/旋转的实际效果
        from ui.viewer import ViewerDialog

        dialog = ViewerDialog(window.model.items, window.project.root, 1, window)
        dialog.showFullScreen()
        dialog.rotate(90)
        dialog.zoom_by(2.0)
        return dialog
    if mode == "burst":
        from ui.burst import BurstDialog

        groups = window.project.store.group_list()
        dialog = BurstDialog(
            window.project.thumbs, window.project.root, groups,
            window.project.store.group_members, window,
        )
        dialog.show()
        return dialog
    if mode.startswith("archive"):
        from ui.main_window import ArchiveDialog

        # 截图自检时先给前 10 张打不同分数，三个分档才都有内容
        for item, score in zip(window.model.items[:10], [5, 5, 4, 5, 3, 4, 2, 5, 3, 1]):
            window.score_item(item["id"], score)
        window.refresh_view()
        dialog = ArchiveDialog(window.project, window)
        dialog.show()
        return dialog
    if mode == "densityS":
        window._set_density("S")
    elif mode == "densityXL":
        window._set_density("XL")
    elif mode == "scored":
        # 演示用：给前 10 张打不同分数，让三个分档都有内容
        for item, score in zip(window.model.items[:10], [5, 5, 4, 5, 3, 4, 2, 5, 3, 1]):
            window.score_item(item["id"], score)
        window.refresh_view()
    return None


def _save(widget, path: str, app) -> None:
    pix = widget.grab()
    pix.save(path)
    print(f"saved {path} ({pix.width()}x{pix.height()})")
    app.quit()


if __name__ == "__main__":
    raise SystemExit(main())
