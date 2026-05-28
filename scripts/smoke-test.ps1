$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

python -m py_compile wcrc\make_certs.py wcrc\remote_exec_client.py wcrc\remote_exec_server.py

$SmokeDir = Join-Path (Get-Location) "output\smoke-certs"
Remove-Item -LiteralPath $SmokeDir -Recurse -Force -ErrorAction SilentlyContinue
python -m wcrc.make_certs --out $SmokeDir --server-ip 127.0.0.1 --days 1

foreach ($file in @("ca.crt", "server.crt", "server.key", "client.crt", "client.key")) {
  if (!(Test-Path (Join-Path $SmokeDir $file))) {
    throw "Missing generated file: $file"
  }
}

Write-Host "Smoke test passed."
