@echo off
cd /d "%~dp0"
"C:\Users\user\AppData\Local\Python\bin\python.exe" -m uvicorn agent.main:app --host 0.0.0.0 --port 8000
