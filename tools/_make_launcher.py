"""生成 启动轻选片.bat。

关键约束（踩过坑）：
1. 必须是 CRLF 行尾，否则 cmd 会错位解析（"start" 变成 "art"）。
2. 内容必须是纯 ASCII。批处理里只要出现中文（且编码与控制台代码页不一致），
   后面的命令会整体错位，报 "'art' 不是内部或外部命令" 这类怪错。
   因此中文提示全部放到 launch.pyw 里，用 Windows MessageBoxW 显示。
"""

from pathlib import Path

RT = r"C:\Users\24377\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python"

lines = [
    "@echo off",
    "setlocal",
    'pushd "%~dp0"',
    "",
    'set "PYW="',
    'set "PY="',
    f'set "RT={RT}"',
    'if exist "%RT%\\pythonw.exe" set "PYW=%RT%\\pythonw.exe"',
    'if exist "%RT%\\python.exe" set "PY=%RT%\\python.exe"',
    "",
    "if not defined PYW for /f \"delims=\" %%i in ('where pythonw 2^>nul') do if not defined PYW set \"PYW=%%i\"",
    "if not defined PY for /f \"delims=\" %%i in ('where python 2^>nul') do if not defined PY set \"PY=%%i\"",
    # PATH 里没有时，再到几个常见安装位置找一遍
    "if not defined PYW for /d %%d in (\"%LOCALAPPDATA%\\Programs\\Python\\Python3*\") do if not defined PYW if exist \"%%d\\pythonw.exe\" set \"PYW=%%d\\pythonw.exe\"",
    "if not defined PY for /d %%d in (\"%LOCALAPPDATA%\\Programs\\Python\\Python3*\") do if not defined PY if exist \"%%d\\python.exe\" set \"PY=%%d\\python.exe\"",
    "if not defined PYW for /d %%d in (\"C:\\Python3*\") do if not defined PYW if exist \"%%d\\pythonw.exe\" set \"PYW=%%d\\pythonw.exe\"",
    "if not defined PY for /d %%d in (\"C:\\Python3*\") do if not defined PY if exist \"%%d\\python.exe\" set \"PY=%%d\\python.exe\"",
    "if not defined PYW for /d %%d in (\"C:\\Program Files\\Python3*\") do if not defined PYW if exist \"%%d\\pythonw.exe\" set \"PYW=%%d\\pythonw.exe\"",
    "if not defined PY for /d %%d in (\"C:\\Program Files\\Python3*\") do if not defined PY if exist \"%%d\\python.exe\" set \"PY=%%d\\python.exe\"",
    'if not defined PY if defined PYW set "PY=%PYW%"',
    "if not defined PYW goto nopython",
    "",
    'start "" "%PYW%" "launch.pyw" %*',
    "popd",
    "exit /b 0",
    "",
    ":nopython",
    "echo.",
    "echo   Python 3.10+ was not found on this computer.",
    "echo.",
    "echo   1. Install it from https://www.python.org/downloads/windows/",
    "echo      (tick \"Add python.exe to PATH\" during setup)",
    "echo   2. Then run in a terminal: python -m pip install PySide6-Essentials pillow numpy",
    "echo   3. Double-click this file again.",
    "echo.",
    "pause",
    "popd",
    "exit /b 1",
]

path = Path(__file__).resolve().parent.parent / "启动轻选片.bat"
path.write_bytes(("\r\n".join(lines) + "\r\n").encode("ascii"))
data = path.read_bytes()
print("bytes:", len(data), "CRLF:", data.count(b"\r\n"), "ascii-only:", not any(b > 127 for b in data))
