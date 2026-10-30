@echo off
setlocal
rem Balance of Power - one-click setup and launcher using a Python venv.
rem Guide: USTANOVKA-RU.txt, section 3.4.
rem
rem Usage:  setup-venv-windows.bat [venv folder]
rem   The venv folder defaults to %LOCALAPPDATA%\bop-venv.  Override it with the
rem   first argument or with the BOP_VENV environment variable (the argument
rem   wins).  Keep it short, ASCII only, on a LOCAL disk.
rem
rem What it does, in order:
rem   1. If started from a network share (\\server\...), copies the game to
rem      %LOCALAPPDATA%\BalanceOfPower with robocopy and runs from there:
rem      a venv, .pyc files and Qt plugins must not depend on the share.
rem      BOP_NO_LOCAL_COPY=1 disables this, BOP_LOCAL_COPY=1 forces it.
rem   2. Creates the venv if it is missing.
rem   3. Installs PyQt5 into it, unless PyQt5 already imports.  If a "wheels"
rem      folder sits next to this file, it installs from there, without the
rem      internet; otherwise from PyPI.
rem   4. Starts the game with the venv's python.exe.
rem A second run skips steps 2 and 3 when everything is already in place.
rem
rem Style notes, same as start-windows.bat: ASCII only, CRLF line endings,
rem labels and goto instead of long if-blocks.  Keep round brackets, ampersands,
rem pipes and angle brackets out of echo lines, and never read the errorlevel
rem variable inside a block.  Paths are always quoted.  Nothing here needs
rem PowerShell or administrator rights.

rem pushd, not cd: it also works when the folder is on a network share (UNC).
pushd "%~dp0"
if errorlevel 1 goto nofolder
title Balance of Power - venv setup

if not defined LOCALAPPDATA set "LOCALAPPDATA=%USERPROFILE%\AppData\Local"
set "HERE=%~dp0"
set "WHEELS=%~dp0wheels"
set "GAMEDIR=%LOCALAPPDATA%\BalanceOfPower"

set "VENV=%LOCALAPPDATA%\bop-venv"
if defined BOP_VENV set "VENV=%BOP_VENV%"
if not "%~1"=="" set "VENV=%~1"
rem A trailing backslash would swallow the closing quote in "...\" arguments.
if "%VENV:~-1%"=="\" set "VENV=%VENV:~0,-1%"
set "VPY=%VENV%\Scripts\python.exe"

rem Do not let a stray Python setup of the machine leak into the venv.
set "PYTHONHOME="
set "PYTHONPATH="
rem Compile into a per-user cache instead of writing next to the sources.
set "PYTHONPYCACHEPREFIX=%LOCALAPPDATA%\balance-of-power\pycache"

rem ---- 1. local copy when started from a network share ----------------------
set "WANTCOPY="
if defined BOP_NO_LOCAL_COPY goto after_copy
if "%HERE:~0,2%"=="\\" set "WANTCOPY=1"
if defined BOP_LOCAL_COPY set "WANTCOPY=1"
if not defined WANTCOPY goto after_copy
echo Copying the game to this PC, once. Later runs copy only what changed...
rem /E not /MIR: nothing in the target folder is ever deleted.
robocopy "%~dp0." "%GAMEDIR%" /E /XD wheels __pycache__ tests /XF *.pyc /NFL /NDL /NJH /NJS /NP >nul
if errorlevel 8 goto copy_failed
if not exist "%GAMEDIR%\main.py" goto copy_failed
pushd "%GAMEDIR%"
if errorlevel 1 goto copy_failed
goto after_copy

:copy_failed
echo.
echo Could not copy the game to "%GAMEDIR%".
echo Running it from the network folder instead; it may be slower.
echo.

:after_copy

rem ---- 2. the venv ----------------------------------------------------------
rem An existing venv whose python.exe runs is reused as it is.
if not exist "%VPY%" goto find_python
"%VPY%" -c "import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)" >nul 2>nul
if errorlevel 1 goto venv_broken
goto check_pyqt5

:find_python
rem Pick the first interpreter that really runs and is Python 3.8 or newer.
rem This skips the Microsoft Store "python.exe" stub, which exists on PATH
rem but only opens the Store.
set "PY="
py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)" >nul 2>nul
if not errorlevel 1 set "PY=py -3"
if defined PY goto have_python
python -c "import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)" >nul 2>nul
if not errorlevel 1 set "PY=python"
if defined PY goto have_python

echo.
echo Python 3.8 or newer was not found, or it is not on PATH.
echo The Microsoft Store "python" shortcut does not count.
echo.
echo Install Python 3 64-bit from https://www.python.org/downloads/ ,
echo choose "Install for me only" and tick "Add python.exe to PATH",
echo then run this file again.
echo If "python" opens the Microsoft Store, switch its alias off:
echo Settings, Apps, Manage app execution aliases.
echo See USTANOVKA-RU.txt, section 2.
echo.
goto fail

:have_python
%PY% -c "import sys; sys.exit(0 if sys.maxsize > 2**32 else 1)" >nul 2>nul
if errorlevel 1 echo Warning: this Python is 32-bit. 64-bit Python is required; PyQt5 may fail to install or load.

echo Creating the virtual environment in "%VENV%" ...
%PY% -m venv "%VENV%"
if errorlevel 1 goto venv_failed
if not exist "%VPY%" goto venv_failed
goto check_pyqt5

:venv_failed
echo.
echo Could not create the virtual environment in "%VENV%".
echo Possible causes:
echo   - the Python installation has no venv or pip: run the Python installer
echo     again, choose Modify, and tick "pip" under Optional Features;
echo   - the folder cannot be written: run this file again with another place,
echo     for example   setup-venv-windows.bat C:\bop-venv
echo   - a half-made folder is left over: delete it and run this file again.
echo.
goto fail

:venv_broken
echo.
echo The virtual environment in "%VENV%" does not work.
echo Usually the Python it was made from was removed or upgraded.
echo Delete that folder and run this file again, it will be recreated.
echo.
goto fail

rem ---- 3. PyQt5 ---------------------------------------------------------------
:check_pyqt5
"%VPY%" -c "import PyQt5.QtCore, PyQt5.QtGui, PyQt5.QtWidgets" >nul 2>nul
if not errorlevel 1 goto play

echo.
echo PyQt5 is not installed in the venv yet. It is needed once.
echo.
set "REQ=-r requirements.txt"
if not exist "requirements.txt" set REQ="PyQt5>=5.15"
if exist "%WHEELS%\*" goto install_offline

:install_online
echo Installing from the internet. Behind a proxy, set HTTPS_PROXY first.
"%VPY%" -m pip install --disable-pip-version-check --retries 1 --timeout 15 %REQ%
goto install_done

:install_offline
echo Installing from the local "wheels" folder, no internet needed...
"%VPY%" -m pip install --disable-pip-version-check --no-index --find-links "%WHEELS%" %REQ%
if not errorlevel 1 goto install_done
echo.
echo The wheels folder did not have everything for this Python. Trying the internet...
goto install_online

:install_done
"%VPY%" -c "import PyQt5.QtCore, PyQt5.QtGui, PyQt5.QtWidgets" >nul 2>nul
if not errorlevel 1 goto play

echo.
echo PyQt5 is still not usable. What Python says:
"%VPY%" -c "import PyQt5.QtCore, PyQt5.QtGui, PyQt5.QtWidgets"
echo.
echo If pip could not download anything, the network blocks PyPI:
echo   - proxy: run  set HTTPS_PROXY=http://user:password@host:port  and start
echo     this file again from the same window;
echo   - certificate error: see USTANOVKA-RU.txt, section 3.2;
echo   - no internet at all: ask the teacher for the "wheels" folder and put it
echo     next to this file, or run  pip install --no-index --find-links
echo     with the path of that folder.
echo If Python reports  DLL load failed  the PC may lack the Microsoft Visual C++
echo 2015-2022 x64 runtime, or Python is 32-bit; see the troubleshooting table.
echo.
goto fail

rem ---- 4. play ----------------------------------------------------------------
:play
"%VPY%" main.py
if errorlevel 1 goto game_failed
popd
exit /b 0

:game_failed
echo.
echo The game stopped with an error. What happened is printed above;
echo USTANOVKA-RU.txt section 8 lists the usual causes.
echo.
pause
popd
exit /b 1

:nofolder
echo.
echo Cannot open the game folder: "%~dp0"
echo.
pause
exit /b 1

:fail
pause
popd
exit /b 1
