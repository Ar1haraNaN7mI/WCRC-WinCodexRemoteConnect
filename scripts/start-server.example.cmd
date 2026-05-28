@echo off
setlocal
cd /d "%~dp0\.."

REM Edit PORT and BASE_DIR before use. CERT_DIR defaults to .\certs.
set PORT=49606
set BASE_DIR=C:\Users\Administrator\Desktop
set CERT_DIR=%CD%\certs

python -m wcrc.remote_exec_server ^
  --host 0.0.0.0 ^
  --port %PORT% ^
  --ca "%CERT_DIR%\ca.crt" ^
  --cert "%CERT_DIR%\server.crt" ^
  --key "%CERT_DIR%\server.key" ^
  --base-dir "%BASE_DIR%" ^
  --allow-shell ^
  --timeout 300 ^
  --log "%CD%\remote_exec_server.log"
