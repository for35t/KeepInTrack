@echo off
cd /d "%~dp0"
venv\Scripts\python.exe manage.py sync_shows >> sync.log 2>&1