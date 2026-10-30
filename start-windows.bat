@echo off
rem Balance of Power - launcher for Windows.
rem
rem Messages are ASCII on purpose: a .bat carrying Cyrillic breaks under the
rem default console code page.  The Russian guide is USTANOVKA-RU.txt.
rem The control flow uses labels rather than "if ... cmd && cmd", whose meaning
rem in batch depends on the previous command's errorlevel.  Avoid round brackets
rem inside echo lines that sit in an if-block: they end the block early.
rem This file must keep CRLF line endings (labels/goto misbehave with LF only).
rem
rem Everything this script writes goes to %LOCALAPPDATA%\balance-of-power (never
rem to the roaming profile, which is synced at logoff):
rem   libs\<python tag>   PyQt5, installed with pip --target
rem   pycache             compiled .pyc files (the game folder may be read-only)
rem   app                 local copy of the game, made only when started from a
rem                       network share (\\server\...), so play does not depend
rem                       on the share.  Set BOP_NO_LOCAL_COPY=1 to disable,
rem                       BOP_LOCAL_COPY=1 to force it from a mapped drive.

rem pushd, not cd: it also works when the folder is on a network share (UNC).
pushd "%~dp0"
if errorlevel 1 goto nofolder
title Balance of Power

if not defined LOCALAPPDATA set "LOCALAPPDATA=%USERPROFILE%\AppData\Local"
set "BOPDATA=%LOCALAPPDATA%\balance-of-power"
set "WHEELS=%~dp0wheels"
set "HERE=%~dp0"

rem Compile into a per-user cache instead of writing next to the sources.
set "PYTHONPYCACHEPREFIX=%BOPDATA%\pycache"

rem Run from a local copy when the game lives on a network share.
set "WANTCOPY="
if defined BOP_NO_LOCAL_COPY goto after_copy
if "%HERE:~0,2%"=="\\" set "WANTCOPY=1"
if defined BOP_LOCAL_COPY set "WANTCOPY=1"
if not defined WANTCOPY goto after_copy
echo Copying the game to this PC, once. Later starts only copy what changed...
robocopy "%~dp0." "%BOPDATA%\app" /MIR /XD wheels docs tests __pycache__ /XF *.pyc /NFL /NDL /NJH /NJS /NP >nul
if errorlevel 8 goto copy_failed
if not exist "%BOPDATA%\app\main.py" goto copy_failed
pushd "%BOPDATA%\app"
if errorlevel 1 goto copy_failed
goto after_copy

:copy_failed
echo.
echo Could not copy the game to %BOPDATA%\app.
echo Running it from the network folder instead; it may be slower.
echo.

:after_copy

rem Pick the first interpreter that really runs and is Python 3.8 or newer.
rem This skips the Microsoft Store "python.exe" stub, which exists on PATH
rem but only opens the Store.
set "PY="
py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)" >nul 2>nul
if not errorlevel 1 set "PY=py -3"
if defined PY goto check_pyqt5
python -c "import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)" >nul 2>nul
if not errorlevel 1 set "PY=python"
if defined PY goto check_pyqt5

echo.
echo Python 3.8 or newer (3.8-3.14, 64-bit) was not found, or it is not on PATH.
echo (The Microsoft Store "python" shortcut does not count.)
echo.
echo Install Python 3 from https://www.python.org/downloads/ and tick
echo "Add python.exe to PATH" during setup, then run this file again.
echo See USTANOVKA-RU.txt for the full instructions.
echo.
pause
popd
exit /b 1

:nofolder
echo.
echo Cannot open the game folder: %~dp0
echo.
pause
exit /b 1

:check_pyqt5
rem PyQt5 lives in a folder per Python version and bitness: its sip helper
rem is built for exactly one interpreter.
set "TAG=py"
for /f "tokens=1,2" %%a in ('%PY% -c "import sys;print(sys.version_info[1],sys.maxsize>2**32)"') do set "TAG=py3%%a-%%b"
set "LIBS=%BOPDATA%\libs\%TAG%"
set "PYTHONPATH=%LIBS%;%PYTHONPATH%"
%PY% -c "import PyQt5" >nul 2>nul
if not errorlevel 1 goto play

echo.
echo PyQt5 is not installed. It is needed once.
echo.
if exist "%WHEELS%\*" goto install_offline
echo Installing from the internet. Behind a proxy, set HTTPS_PROXY first.
%PY% -m pip install --disable-pip-version-check --upgrade --retries 1 --timeout 15 --target "%LIBS%" PyQt5
goto install_done

:install_offline
echo Installing from the local "wheels" folder, no internet needed...
%PY% -m pip install --disable-pip-version-check --upgrade --no-index --find-links "%WHEELS%" --target "%LIBS%" PyQt5

:install_done
%PY% -c "import PyQt5" >nul 2>nul
if not errorlevel 1 goto play

echo.
echo Could not install PyQt5 automatically.  No internet, or a proxy?  Run by hand:
echo.
echo     %PY% -m pip install --target "%LIBS%" PyQt5
echo     (proxy: add  --proxy http://host:port  to that command)
echo.
echo Offline: put the PyQt5 wheel files into a "wheels" folder next to this file.
echo See USTANOVKA-RU.txt, sections 3.3 and 8.
echo.
pause
popd
exit /b 1

:play
%PY% main.py
if errorlevel 1 (
    echo.
    echo The game stopped with an error. What happened is printed above;
    echo USTANOVKA-RU.txt section 8 lists the usual causes.
    echo.
    pause
)
popd
