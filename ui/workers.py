"""后台任务：扫描、分析、分组、缩略图、归档都在线程池里跑，界面不卡。

缩略图走独立的池（线程数少），避免大量缩略图把扫描分析挤到后面排队。
"""

from __future__ import annotations

import traceback
from typing import Callable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal
from PySide6.QtGui import QImage


class TaskSignals(QObject):
    progress = Signal(int, int)   # 已完成, 总数
    message = Signal(str)
    finished = Signal(object)
    failed = Signal(str)


class Job(QRunnable):
    """把一个可调用对象丢进线程池；fn 可以接收 progress/message 回调。"""

    def __init__(self, fn: Callable, *args, want_callbacks: bool = True, **kwargs):
        super().__init__()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.signals = TaskSignals()
        self.want_callbacks = want_callbacks
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    def run(self) -> None:
        try:
            kwargs = dict(self.kwargs)
            if self.want_callbacks:
                kwargs.setdefault("progress", self.signals.progress.emit)
                kwargs.setdefault("message", self.signals.message.emit)
                kwargs.setdefault("should_stop", lambda: self._cancelled)
            result = self.fn(*self.args, **kwargs)
            if not self._cancelled:
                self.signals.finished.emit(result)
        except Exception:
            try:
                self.signals.failed.emit(traceback.format_exc(limit=3))
            except RuntimeError:
                pass


def pool(max_threads: int = 4) -> QThreadPool:
    p = QThreadPool()
    if p.maxThreadCount() > max_threads:
        p.setMaxThreadCount(max_threads)
    return p


class ThumbSignals(QObject):
    loaded = Signal(str, int, QImage)


class ThumbJob(QRunnable):
    """按 (相对路径, 尺寸) 生成缩略图，结果以 QImage 回主线程。"""

    def __init__(self, cache, rel: str, mtime: float, size: int,
                 signals: ThumbSignals, priority: int = 0):
        super().__init__()
        self.cache = cache
        self.rel = rel
        self.mtime = mtime
        self.size = size
        self.signals = signals
        self.setAutoDelete(True)

    def run(self) -> None:
        try:
            img = self.cache.get(self.rel, self.mtime, self.size)
        except Exception:
            img = None
        if img is None:
            self._emit(QImage())
            return
        data = img.tobytes("raw", "RGB")
        qimg = QImage(data, img.width, img.height, img.width * 3, QImage.Format_RGB888)
        self._emit(qimg.copy())

    def _emit(self, qimg: QImage) -> None:
        # 窗口已经关掉（signals 被销毁）时安静退出，不要往控制台喷异常
        try:
            self.signals.loaded.emit(self.rel, self.size, qimg)
        except RuntimeError:
            pass
