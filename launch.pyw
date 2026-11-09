"""启动入口：先检查依赖，缺什么就用系统弹窗说清楚，然后再打开界面。

这么做的原因：用 pythonw 启动时没有控制台，安装依赖缺失的错误只会一闪而过，
用户看到的就只是"双击没反应"。这里用 ctypes 直接调 Windows 的 MessageBoxW，
不依赖任何第三方库，中文也不会乱码。
"""

from __future__ import annotations

import sys
import traceback

REQUIRED = ("PySide6", "PIL", "numpy")
INSTALL_CMD = "python -m pip install PySide6-Essentials pillow numpy"


def popup(title: str, text: str) -> None:
    """没有控制台时的兜底提示（Windows MessageBoxW）。"""
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, text, title, 0x10)
    except Exception:
        print(f"{title}: {text}", file=sys.stderr)


def check() -> list[str]:
    missing = []
    for name in REQUIRED:
        try:
            __import__(name)
        except Exception:
            missing.append(name)
    return missing


def main() -> int:
    missing = check()
    if missing:
        popup(
            "轻选片 启动失败",
            "缺少运行依赖：" + "、".join(missing) + "\n\n"
            "请在命令行里执行下面这一行，装完再双击「启动轻选片.bat」：\n\n"
            f"    {INSTALL_CMD}\n",
        )
        return 1

    try:
        from app import main as run

        return run()
    except Exception:
        detail = traceback.format_exc()
        try:
            from core import paths

            log = paths.log_path()
        except Exception:
            log = None
        if log is not None:
            try:
                with open(log, "a", encoding="utf-8") as handle:
                    handle.write(detail + "\n")
            except Exception:
                pass
        popup(
            "轻选片 启动失败",
            "启动时出错了：\n\n"
            + detail.strip().splitlines()[-1]
            + ("\n\n详细日志：" + str(log) if log else ""),
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
