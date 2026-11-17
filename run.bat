@echo off
chcp 65001 >nul
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo 没找到 python，请先把 Python 加进 PATH。
    pause
    exit /b 1
)

python win_ocr_type.py %*
if errorlevel 1 (
    echo.
    echo 退出码：%errorlevel%
    pause
)
