@echo off
setlocal
cd /d "%~dp0"
set QT_QPA_PLATFORM=
set PADDLE_PDX_CACHE_HOME=%~dp0.paddlex_cache
set PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True
if not exist ".venv\Scripts\python.exe" goto noenv
echo Starting Enterprise Environmental Data Extractor...
uv run --no-sync python -m doc_extractor
if errorlevel 1 goto failed
goto end
:noenv
echo [ERROR] .venv\Scripts\python.exe not found.
echo Please run "uv sync" in this project directory first.
pause
goto end
:failed
echo.
echo [ERROR] Application exited with code %errorlevel%.
echo Log file: %~dp0logs\doc_extractor.log
pause
:end
endlocal