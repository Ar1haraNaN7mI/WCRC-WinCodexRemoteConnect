$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

# Edit these values before use.
$Port = 49606
$BaseDir = "C:\Users\Administrator\Desktop"
$CertDir = Join-Path (Get-Location) "certs"

python -m wcrc.remote_exec_server `
  --host 0.0.0.0 `
  --port $Port `
  --ca (Join-Path $CertDir "ca.crt") `
  --cert (Join-Path $CertDir "server.crt") `
  --key (Join-Path $CertDir "server.key") `
  --base-dir $BaseDir `
  --allow-shell `
  --timeout 300 `
  --log (Join-Path (Get-Location) "remote_exec_server.log")
