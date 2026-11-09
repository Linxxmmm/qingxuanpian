"""界面层自检：用离屏模式把主要交互跑一遍，确认没有明显断裂。

    QT_QPA_PLATFORM=offscreen python tools/ui_test.py
"""

from __future__ import annotations

import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QPointF, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from core.project import Project  # noqa: E402
from ui import theme  # noqa: E402
from ui.main_window import MainWindow  # noqa: E402
from ui.viewer import ViewerDialog  # noqa: E402

PASS, FAIL = [], []


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    print(f"  {'✓' if ok else '✗'} {name}{(' — ' + detail) if detail else ''}")


def wait_until(app: QApplication, cond, timeout: float = 15.0) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.02)
    return False


def main() -> int:
    src = ROOT / "sample2"
    work = ROOT / "_uitest"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir()
    for f in sorted(src.glob("*.jpg"))[:12]:
        shutil.copy2(f, work / f.name)

    app = QApplication(sys.argv[:1])
    app.setFont(theme.font())
    app.setStyleSheet(theme.QSS)

    window = MainWindow()
    window.quiet = True
    window.show()
    window.open_folder(work)

    ok = wait_until(app, lambda: window.model.rowCount() > 0
                    and window.status_text.text().startswith(("已是最新", "分析完成")))
    check("打开文件夹后载入照片", ok, f"{window.model.rowCount()} 张")

    check("硬伤被识别出来", window.project.counts()["flagged"] > 0,
          f"命中 {window.project.counts()['flagged']} 张")

    # ---- 打分 ----
    first = window.model.items[0]
    window.score_item(first["id"], 5)
    c = window.project.counts()
    check("打分写入并计入精选", c["pick"] == 1, f"精选 {c['pick']} 张")

    window.set_filter("pick")
    check("筛选为精选时只显示 1 张", window.model.rowCount() == 1,
          f"{window.model.rowCount()} 张")
    window.set_filter("all")

    # ---- 星级只有 1–5 ----
    window.score_item(first["id"], 0)
    check("打 0 分无效，最低 1 星", window.project.store.by_id(first["id"])["score"] == 1,
          f"分数 {window.project.store.by_id(first['id'])['score']}")
    window.score_item(first["id"], 9)
    check("超过 5 星按 5 星封顶", window.project.store.by_id(first["id"])["score"] == 5,
          f"分数 {window.project.store.by_id(first['id'])['score']}")
    window.score_item(first["id"], 5)

    # ---- 归档对话框：一键全部 ----
    from ui.main_window import ArchiveDialog

    for item, score in zip(window.model.items[:6], (5, 4, 4, 3, 1, 1)):
        window.score_item(item["id"], score)
    window.refresh_view()
    dlg = ArchiveDialog(window.project, window)
    dlg.show()
    app.processEvents()
    check(
        "归档对话框默认能一键全部归档",
        dlg.all_btn.isEnabled() and dlg.total == 6 and "一键全部归档" in dlg.all_btn.text(),
        f"{dlg.all_btn.text()}",
    )
    dlg._archive_all()
    check(
        "一键全部包含三个分档",
        sorted(dlg.buckets()) == ["maybe", "pick", "reject"],
        f"{dlg.buckets()}",
    )
    dlg.close()

    # ---- 归档 + 撤销 ----
    result = window.project.archive("pick", "move")
    check("归档搬走了 1 张", result["count"] == 1,
          f"{result['count']} 张 · {result['dest']} · counts={window.project.counts()}")
    check("精选文件夹里确实有文件", (work / "精选").exists()
          and len(list((work / "精选").glob("*.jpg"))) == 1)
    undone = window.project.undo(result["log_id"])
    check("撤销把文件搬回来了", undone["restored"] == 1
          and len(list((work / "精选").glob("*.jpg"))) == 0)

    # ---- 看图打分 ----
    viewer = ViewerDialog(window.model.items, window.project.root, 0, window)
    captured = []
    viewer.score_changed.connect(lambda pid, sc: captured.append((pid, sc)))
    viewer._set_score(4)
    viewer.step(1)
    check("看图界面能打分和翻页", bool(captured) and viewer.index == 1,
          f"{captured}")

    # 看图必须是原图分辨率，不能被缩过
    from PIL import Image as PILImage

    viewer.index = 0
    viewer._load()
    raw = PILImage.open(work / viewer.items[0]["path"])
    got = (viewer._image.width(), viewer._image.height()) if viewer._image else (0, 0)
    check("看图按原图分辨率加载", got == raw.size, f"{got[0]}×{got[1]} vs 原图 {raw.size[0]}×{raw.size[1]}")

    # ---- 缩放 + 旋转 ----
    viewer.resize(1200, 800)
    app.processEvents()
    fit_rect = viewer.image_rect()
    viewer.zoom_by(2.0)
    zoomed_rect = viewer.image_rect()
    check(
        "滚轮/加号能放大",
        zoomed_rect.width() > fit_rect.width() * 1.8,
        f"{fit_rect.width():.0f}→{zoomed_rect.width():.0f}px",
    )
    viewer.fit()
    check("适配能回到 1 倍", abs(viewer._zoom - 1.0) < 1e-6 and
          abs(viewer.image_rect().width() - fit_rect.width()) < 1.0)

    before = viewer.image_rect()
    viewer.rotate(90)
    after = viewer.image_rect()
    check(
        "旋转 90° 后画面宽高对调",
        viewer._rotation == 90
        and (before.width() < before.height()) != (after.width() < after.height()),
        f"{before.width():.0f}×{before.height():.0f} → "
        f"{after.width():.0f}×{after.height():.0f}",
    )
    viewer.rotate(-90)
    check("反向旋转能转回来", viewer._rotation == 0, f"{viewer._rotation}°")

    # 放大后拖拽平移，且不会被拖出画面
    viewer.zoom_by(3.0)
    area = viewer.area_rect()
    viewer._pan = QPointF(99999, 99999)
    viewer._clamp_pan()
    clamped = viewer._pan
    check(
        "平移有边界，不会把图拖飞",
        clamped.x() < 99999 and clamped.y() < 99999,
        f"pan=({clamped.x():.0f},{clamped.y():.0f}) 区域 {area.width():.0f}px",
    )
    viewer.fit()

    # ---- 密度切换 ----
    window._set_density("XL")
    check("切到 XL 变成 2 列", window.grid.cols == 2, f"{window.grid.cols} 列")
    window._set_density("S")
    check("切到 S 变成 5 列", window.grid.cols == 5, f"{window.grid.cols} 列")

    # ---- 看图工具条放在图片底部正中 ----
    viewer.fit()
    rects = viewer._tool_rects()
    bar = viewer._bar_rect()
    area = viewer.area_rect()
    names = [name for name, _r in rects]
    check(
        "工具条有 5 个图标且顺序正确",
        names == ["zoom_out", "zoom_in", "fit", "rot_left", "rot_right"],
        "、".join(names),
    )
    check(
        "工具条贴在图片底部中间",
        bar.top() > viewer.height() * 0.6
        and abs(bar.center().x() - viewer.width() / 2) <= 2
        and area.bottom() - bar.bottom() < 40,
        f"中心 x={bar.center().x():.0f}/{viewer.width() / 2:.0f}，"
        f"距图片底 {area.bottom() - bar.bottom():.0f}px",
    )
    zoom_before = viewer._zoom
    viewer._tool_action("zoom_in")
    check("点放大图标能放大", viewer._zoom > zoom_before, f"{zoom_before:.2f}→{viewer._zoom:.2f}")
    viewer._tool_action("rot_right")
    check("点右转图标能旋转", viewer._rotation == 90, f"{viewer._rotation}°")
    viewer.fit()

    # ---- 顶栏可以换文件夹 ----
    check(
        "顶栏有「更换」按钮且能点",
        window.switch_btn.isVisible() and "更换" in window.switch_btn.text(),
        window.switch_btn.text(),
    )
    check(
        "文件夹路径可点击重选",
        hasattr(window.path_label, "clicked"),
        type(window.path_label).__name__,
    )

    window.close()
    shutil.rmtree(work, ignore_errors=True)

    print(f"\n通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
    if FAIL:
        print("失败项：" + "、".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
