@echo off
setlocal
cd /d "%~dp0"
title ALDS setup
echo ALDS setup
echo.

where py >nul 2>nul
if errorlevel 1 goto nopython
py -3.12 -c "import sys" >nul 2>nul
if errorlevel 1 goto nopython

if exist ".venv\Scripts\python.exe" goto install
echo Creating the Python environment in the .venv folder...
py -3.12 -m venv .venv
if errorlevel 1 goto failed

:install
echo Installing the requirements. The first time downloads about 2 GB and takes a few minutes.
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements.txt
if errorlevel 1 goto failed

echo.
call "%~dp0alds.bat" check
if errorlevel 1 goto failed
echo.
echo Done. Double-click alds-gui.bat to start the program.
echo To try every step on one episode first:  alds.bat selftest "D:\anime\episode.mkv"
echo.
pause
exit /b 0

:nopython
echo Python 3.12 was not found.
echo Install it from https://www.python.org/downloads/ and keep the "py launcher" option ticked,
echo then double-click setup.bat again.
echo.
pause
exit /b 1

:failed
echo.
echo The setup stopped. Read the messages above; double-click setup.bat again to continue from there.
echo.
pause
exit /b 1
