$ErrorActionPreference = "Stop"

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$CertDir = Join-Path $Root "certs"
$Bundle = Join-Path $Root "wcrc-server-bundle.zip"
$Stage = Join-Path $Root "output\server-bundle"

if (!(Test-Path (Join-Path $CertDir "ca.crt")) -or
    !(Test-Path (Join-Path $CertDir "server.crt")) -or
    !(Test-Path (Join-Path $CertDir "server.key"))) {
  throw "Missing server certificate files. Run: python -m wcrc.make_certs --server-ip <PUBLIC_IP>"
}

Remove-Item -LiteralPath $Stage -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Path (Join-Path $Stage "wcrc") | Out-Null
New-Item -ItemType Directory -Path (Join-Path $Stage "certs") | Out-Null

Copy-Item -LiteralPath (Join-Path $Root "wcrc\__init__.py") -Destination (Join-Path $Stage "wcrc\__init__.py")
Copy-Item -LiteralPath (Join-Path $Root "wcrc\config.py") -Destination (Join-Path $Stage "wcrc\config.py")
Copy-Item -LiteralPath (Join-Path $Root "wcrc\remote_exec_server.py") -Destination (Join-Path $Stage "wcrc\remote_exec_server.py")
Copy-Item -LiteralPath (Join-Path $Root "scripts\firewall-rule.example.cmd") -Destination (Join-Path $Stage "firewall-rule.example.cmd")
Copy-Item -LiteralPath (Join-Path $CertDir "ca.crt") -Destination (Join-Path $Stage "certs\ca.crt")
Copy-Item -LiteralPath (Join-Path $CertDir "server.crt") -Destination (Join-Path $Stage "certs\server.crt")
Copy-Item -LiteralPath (Join-Path $CertDir "server.key") -Destination (Join-Path $Stage "certs\server.key")

Set-Content -LiteralPath (Join-Path $Stage "start-server.cmd") -Encoding ASCII -Value @"
@echo off
setlocal
cd /d "%~dp0"

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
"@

Set-Content -LiteralPath (Join-Path $Stage "README-SERVER.txt") -Encoding UTF8 -Value @"
WCRC server bundle

1. Extract this zip on the target Windows server.
2. Edit start-server.cmd:
   - PORT must match the internal listening port exposed by your cloud provider.
   - BASE_DIR limits where commands may run.
3. If Windows Firewall blocks the port, run firewall-rule.example.cmd as Administrator after editing its port.
4. Run start-server.cmd and keep the console open.

Do not put client.key on the server.
"@

Remove-Item -LiteralPath $Bundle -Force -ErrorAction SilentlyContinue
Compress-Archive -Path (Join-Path $Stage "*") -DestinationPath $Bundle -Force
Write-Host "Created $Bundle"
