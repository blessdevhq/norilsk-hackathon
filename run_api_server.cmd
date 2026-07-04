@echo off
cd /d "%~dp0"
"%LOCALAPPDATA%\hermes\hermes-agent\venv\Scripts\python.exe" -m uvicorn api:app --host 127.0.0.1 --port 8000
