@echo off
setlocal EnableExtensions
title Credit Desk
cd /d "%~dp0"
echo ================================================================
echo   CREDIT DESK
echo ================================================================

if not exist "%~dp0app.py" goto :noapp

rem ------------------------------------------------------------------------------------
rem  OPTIONAL SWITCHES (remove "rem " at the start of a line to turn it on)
rem  Open with NO sign-in page at all:
rem set "CREDIT_DESK_REQUIRE_LOGIN=0"
rem  Start WITHOUT the sample loans and decisions (set this BEFORE the very first start):
rem set "CREDIT_DESK_SAMPLE_DATA=0"
rem ------------------------------------------------------------------------------------

rem ---- 1. find Python 3 ----
call :findpython
if defined PY goto :start

rem ---- 2. no Python: try to install it automatically (Windows 10/11 have winget) ----
echo Python is not installed on this computer. Installing it now (one time only)...
winget --version >nul 2>&1
if errorlevel 1 goto :nopython
winget install -e --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
call :findpython
if not defined PY goto :nopython

:start
%PY% "%~dp0launch.py"
echo.
pause
exit /b 0

rem ---- helpers ------------------------------------------------------------------------
:findpython
set "PY="
py -3 --version >nul 2>&1 && set "PY=py -3" && exit /b 0
python --version >nul 2>&1 && set "PY=python" && exit /b 0
for %%V in (314 313 312 311 310) do (
  if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python%%V\python.exe" set "PY="%LOCALAPPDATA%\Programs\Python\Python%%V\python.exe""
  if not defined PY if exist "%ProgramFiles%\Python%%V\python.exe" set "PY="%ProgramFiles%\Python%%V\python.exe""
)
exit /b 0

:noapp
echo The app files were not found next to this file.
echo If you opened it from inside the ZIP, first right-click the ZIP and choose
echo "Extract All...", then open the extracted folder and double-click this file again.
pause
exit /b 1

:nopython
echo.
echo Python could not be installed automatically.
echo 1. The download page will open now. Download and run the Python installer.
echo 2. IMPORTANT: tick the box "Add python.exe to PATH" on the first screen.
echo 3. Then double-click "START Credit Desk (Windows)" again.
start "" https://www.python.org/downloads/
pause
exit /b 1
