@echo off
setlocal
pushd "%~dp0"

set "PYW="
set "PY="
set "RT=C:\Users\24377\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python"
if exist "%RT%\pythonw.exe" set "PYW=%RT%\pythonw.exe"
if exist "%RT%\python.exe" set "PY=%RT%\python.exe"

if not defined PYW for /f "delims=" %%i in ('where pythonw 2^>nul') do if not defined PYW set "PYW=%%i"
if not defined PY for /f "delims=" %%i in ('where python 2^>nul') do if not defined PY set "PY=%%i"
if not defined PYW for /d %%d in ("%LOCALAPPDATA%\Programs\Python\Python3*") do if not defined PYW if exist "%%d\pythonw.exe" set "PYW=%%d\pythonw.exe"
if not defined PY for /d %%d in ("%LOCALAPPDATA%\Programs\Python\Python3*") do if not defined PY if exist "%%d\python.exe" set "PY=%%d\python.exe"
if not defined PYW for /d %%d in ("C:\Python3*") do if not defined PYW if exist "%%d\pythonw.exe" set "PYW=%%d\pythonw.exe"
if not defined PY for /d %%d in ("C:\Python3*") do if not defined PY if exist "%%d\python.exe" set "PY=%%d\python.exe"
if not defined PYW for /d %%d in ("C:\Program Files\Python3*") do if not defined PYW if exist "%%d\pythonw.exe" set "PYW=%%d\pythonw.exe"
if not defined PY for /d %%d in ("C:\Program Files\Python3*") do if not defined PY if exist "%%d\python.exe" set "PY=%%d\python.exe"
if not defined PY if defined PYW set "PY=%PYW%"
if not defined PYW goto nopython

start "" "%PYW%" "launch.pyw" %*
popd
exit /b 0

:nopython
echo.
echo   Python 3.10+ was not found on this computer.
echo.
echo   1. Install it from https://www.python.org/downloads/windows/
echo      (tick "Add python.exe to PATH" during setup)
echo   2. Then run in a terminal: python -m pip install PySide6-Essentials pillow numpy
echo   3. Double-click this file again.
echo.
pause
popd
exit /b 1
