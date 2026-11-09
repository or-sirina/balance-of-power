@echo off
py -3 "%~dp0..\tools\run_godot.py" %*
exit /b %errorlevel%
