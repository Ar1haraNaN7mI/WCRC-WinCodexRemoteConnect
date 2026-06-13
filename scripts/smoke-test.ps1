$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

python -m py_compile wcrc\config.py wcrc\make_certs.py wcrc\remote_exec_client.py wcrc\remote_exec_server.py wcrc\setup_wizard.py

$SmokeDir = Join-Path (Get-Location) "output\smoke-certs"
Remove-Item -LiteralPath $SmokeDir -Recurse -Force -ErrorAction SilentlyContinue
python -m wcrc.make_certs --out $SmokeDir --server-ip 127.0.0.1 --days 1

foreach ($file in @("ca.crt", "server.crt", "server.key", "client.crt", "client.key")) {
  if (!(Test-Path (Join-Path $SmokeDir $file))) {
    throw "Missing generated file: $file"
  }
}

$GuidedDir = Join-Path (Get-Location) "output\smoke-guided-setup"
Remove-Item -LiteralPath $GuidedDir -Recurse -Force -ErrorAction SilentlyContinue
python -c "from pathlib import Path; from wcrc.setup_wizard import SetupSettings, create_setup_files; create_setup_files(SetupSettings(public_host='127.0.0.1', output_dir=Path(r'$GuidedDir'), days=1, base_dir=r'$env:TEMP'))"

foreach ($file in @(
  "wcrc-client.json",
  "wcrc-command.cmd",
  "run-whoami.ps1",
  "README-WCRC-SETUP.txt",
  "wcrc-server-bundle.zip",
  "server-bundle\wcrc-server.json",
  "server-bundle\start-server.cmd",
  "server-bundle\certs\ca.crt",
  "server-bundle\certs\server.crt",
  "server-bundle\certs\server.key"
)) {
  if (!(Test-Path (Join-Path $GuidedDir $file))) {
    throw "Missing guided setup file: $file"
  }
}

if (Test-Path (Join-Path $GuidedDir "server-bundle\certs\client.key")) {
  throw "Guided server bundle must not contain client.key"
}

Write-Host "Smoke test passed."
