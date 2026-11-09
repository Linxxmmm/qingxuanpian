@echo off
chcp 936 >nul
pushd "%~dp0"

set "PYW="
set "PY="
set "RT=C:\Users\24377\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python"
if exist "%RT%\pythonw.exe" set "PYW=%RT%\pythonw.exe"
if exist "%RT%\python.exe" set "PY=%RT%\python.exe"

if not defined PYW call :findwindowless
if not defined PYW goto :nopython
if not defined PY call :findconsole
if not defined PY set "PY=%PYW%"

"%PY%" -c "import PySide6, PIL, numpy" >nul 2>nul
if errorlevel 1 goto :nodeps

start "" "%PYW%" "app.py" %*
popd
exit /b 0

:findwindowless
for /f "delims=" %%i in ('where pythonw 2^>nul') do if not defined PYW set "PYW=%%i"
exit /b 0

:findconsole
for /f "delims=" %%i in ('where python 2^>nul') do if not defined PY set "PY=%%i"
exit /b 0

:nodeps
echo.
echo   缺少运行依赖：PySide6、pillow、numpy 至少有一个没装。
echo.
echo   在命令行执行下面这一行，装完再双击本文件：
echo       "%PY%" -m pip install PySide6-Essentials pillow numpy
echo.
pause
popd
exit /b 1

:nopython
echo.
echo   没有找到 Python 3.10 以上的版本。
echo.
echo   1) 到 https://www.python.org/downloads/windows/ 下载安装，安装时勾选 Add python.exe to PATH
echo   2) 打开命令行执行：python -m pip install PySide6-Essentials pillow numpy
echo   3) 再双击本文件
echo.
pause
popd
exit /b 1
