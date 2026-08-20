@echo off
cd /d "%~dp0"
REM --no-proxy-headers: por defecto uvicorn confia en el X-Forwarded-For de
REM cualquiera que conecte desde 127.0.0.1 y reescribe request.client con ese
REM valor. En local eso incluye al propio navegador/curl, asi que sin este
REM flag cualquiera puede elegir la IP con la que lo limita el rate limiting
REM (probado). Quien decide en que header confiar es la app, via
REM PROXIES_CONFIABLES (ver agent/rate_limit.py), no el servidor.
"C:\Users\user\AppData\Local\Python\bin\python.exe" -m uvicorn agent.main:app --host 0.0.0.0 --port 8000 --no-proxy-headers
