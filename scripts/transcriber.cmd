@echo off
rem Launcher for transcriber (used by the desktop shortcut).
title transcriber
cd /d "%~dp0.."

where uv >nul 2>nul
if errorlevel 1 (
    echo uv is not found. Install it from https://docs.astral.sh/uv/ and try again.
    pause
    exit /b 1
)

uv run transcriber %*

rem Keep the window open only if the app failed (Ctrl+C / exit code 130 is fine).
if errorlevel 1 if not errorlevel 130 pause
