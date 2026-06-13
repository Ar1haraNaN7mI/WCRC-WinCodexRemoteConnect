# WCRC - WinCodex Remote Connect

WCRC is a small mutual-TLS remote command bridge for temporary server maintenance when SSH is unavailable or not exposed.

It was designed for a Windows cloud server with only a few public port mappings, but it also runs on Linux. The server accepts one JSON command per TLS connection, runs it inside a configured base directory, returns stdout/stderr, and writes an audit log.

## Security Model

- Mutual TLS is required. The server only accepts clients signed by your local CA.
- The client verifies the server certificate using the same CA.
- `client.key` stays on your local machine. Never upload it to the server.
- Commands are constrained to `--base-dir` for working directories.
- Shell mode is disabled unless the server is started with `--allow-shell`.
- The tool installs no persistence. Stop the server process when the maintenance window ends.

This is not a replacement for a hardened SSH deployment. Use it as an explicit, short-lived maintenance bridge.

## Requirements

- Python 3.10+
- `cryptography` for certificate generation
- No third-party dependency is required by the server/client runtime after certificates are generated
- `tkinter` for the optional guided setup window. It is included in the standard Windows Python installer.

Install dependencies locally:

```powershell
python -m pip install -r requirements.txt
```

Or install the project in editable mode:

```powershell
python -m pip install -e .
```

## Guided Setup Tutorial

The guided setup window is the recommended path for first-time use. It generates certificates, writes JSON config files, creates helper scripts, and builds a server-only zip that is safe to upload.

### Before You Start

Prepare these values:

- Server public IP or DNS, for example `203.0.113.10` or `server.example.com`.
- Public port that your local machine connects to, for example `18785`.
- Internal server listen port, for example `49606`.
- Server base directory, for example `C:\Users\Administrator\Desktop`.
- A way to copy one zip file to the server, such as RDP, a cloud console file manager, `scp`, or any approved file transfer method.

Port mapping can be confusing. If your cloud provider maps public port `18785` to server internal port `49606`, use:

```text
Public host: 203.0.113.10
Public port: 18785
Listen port: 49606
```

If there is no separate public port mapping, use the same value for `Public port` and `Listen port`.

### 1. Install Dependencies Locally

Run these commands on your local machine from the repository directory:

```powershell
cd C:\path\to\WCRC-WinCodexRemoteConnect
python --version
python -m pip install -r requirements.txt
```

Optional editable install:

```powershell
python -m pip install -e .
```

You only need `cryptography` while generating certificates. The generated server/client runtime code uses the Python standard library.

### 2. Open the Setup Window

Run:

```powershell
python -m wcrc.setup_wizard
```

Or, after editable install:

```powershell
wcrc-setup
```

If the window does not open because `tkinter` is missing, install or use the standard Python build from python.org on Windows.

### 3. Fill In the Wizard

Use the following field guide:

| Field | Example | Meaning |
| --- | --- | --- |
| `Public host` | `203.0.113.10` | The IP or DNS name used by the local client. This value is also added to the server certificate SAN. You can enter `host:port`; the wizard will reuse the port if the public port field still has the default value. |
| `Public port` | `18785` | The public or cloud-mapped TCP port used by the client. |
| `Extra IP SANs` | `10.0.0.5, 127.0.0.1` | Optional extra IPs accepted by TLS hostname verification. Leave empty for normal use. |
| `Extra DNS SANs` | `server.example.com` | Optional extra DNS names accepted by TLS hostname verification. Leave empty for normal use. |
| `Bind host` | `0.0.0.0` | Address the server process listens on. Use `0.0.0.0` for all interfaces or `127.0.0.1` for local-only testing. |
| `Listen port` | `49606` | Internal TCP port opened by the server process. |
| `Base directory` | `C:\Users\Administrator\Desktop` | Remote commands can only run inside this directory. A requested `--cwd` outside this path is rejected. |
| `Allow shell mode` | checked | Allows `--shell "..."` commands. If unchecked, only argv commands after `--` are accepted. |
| `Timeout seconds` | `300` | Maximum remote command runtime. Client-requested timeouts cannot exceed this server-side limit. |
| `Certificate days` | `30` | Validity period for the generated CA, server certificate, and client certificate. |
| `Output directory` | `output\guided-setup` | Local folder where the generated files are written. |

Click `Generate setup`. The status box should show the generated output path and the server bundle zip path.

### 4. Check the Generated Files

The output directory contains both local-only files and server upload files:

```text
output/guided-setup/
  certs/
    ca.crt
    ca.key
    client.crt
    client.key
    server.crt
    server.key
  wcrc/
  wcrc-client.json
  wcrc-command.cmd
  wcrc-shell.cmd
  run-whoami.ps1
  README-WCRC-SETUP.txt
  wcrc-server-bundle.zip
  server-bundle/
```

Keep these local:

```text
certs/ca.key
certs/client.key
certs/client.crt
certs/ca.crt
wcrc-client.json
```

Upload only this file to the server:

```text
wcrc-server-bundle.zip
```

The server bundle contains only server-side material:

```text
certs/ca.crt
certs/server.crt
certs/server.key
wcrc/
wcrc-server.json
start-server.cmd
start-server.ps1
firewall-rule.example.cmd
README-SERVER.txt
```

It intentionally does not include `client.key` or `ca.key`.

### 5. Upload and Start the Server

Copy `wcrc-server-bundle.zip` to the server, extract it, then open a CMD or PowerShell in the extracted folder.

Before starting, you may inspect `wcrc-server.json`:

```json
{
  "host": "0.0.0.0",
  "port": 49606,
  "ca": "certs/ca.crt",
  "cert": "certs/server.crt",
  "key": "certs/server.key",
  "base_dir": "C:\\Users\\Administrator\\Desktop",
  "allow_shell": true,
  "timeout": 300,
  "max_output": 4194304,
  "log": "remote_exec_server.log"
}
```

Start the server:

```cmd
start-server.cmd
```

Or:

```powershell
.\start-server.ps1
```

Expected server output looks like:

```text
[2026-01-01T00:00:00+00:00] mTLS remote exec listening on 0.0.0.0:49606, base-dir=C:\Users\Administrator\Desktop
```

Keep this console open while using WCRC. Close it or press `Ctrl+C` when the maintenance window is done.

If Windows Firewall blocks the internal listen port, run this from an Administrator CMD after checking the port in the file:

```cmd
firewall-rule.example.cmd
```

### 6. Connect From Your Local Machine

On your local machine, go to the guided output directory:

```powershell
cd output\guided-setup
```

Run a basic test:

```powershell
python -m wcrc.remote_exec_client --config .\wcrc-client.json -- whoami
```

The output should be the Windows account that started `start-server.cmd` on the server.

You can also use the generated helper script:

```cmd
wcrc-command.cmd whoami
```

Run a command with arguments:

```powershell
python -m wcrc.remote_exec_client --config .\wcrc-client.json -- powershell -NoProfile -Command "$PSVersionTable.PSVersion"
```

Run inside a specific remote working directory under `base_dir`:

```powershell
python -m wcrc.remote_exec_client --config .\wcrc-client.json --cwd "C:\Users\Administrator\Desktop" -- cmd /c dir
```

Run shell mode if you enabled `Allow shell mode`:

```powershell
python -m wcrc.remote_exec_client --config .\wcrc-client.json --shell "Get-ChildItem | Select-Object Name,Length"
```

Or:

```cmd
wcrc-shell.cmd "Get-ChildItem | Select-Object Name,Length"
```

Print the raw JSON response for debugging:

```powershell
python -m wcrc.remote_exec_client --config .\wcrc-client.json --json -- whoami
```

### 7. Reconfigure or Rotate Certificates

Run the wizard again when:

- The server public IP or DNS changes.
- The public or internal port changes.
- You want a different `base_dir`.
- The certificate validity period is ending.
- You want to revoke old local client credentials by replacing the CA and all certificates.

After regenerating, upload the new `wcrc-server-bundle.zip` and replace the old local `wcrc-client.json` and `certs/` files with the newly generated ones.

### Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| `ModuleNotFoundError: No module named 'cryptography'` | Dependencies were not installed before generating certificates. | Run `python -m pip install -r requirements.txt`. |
| Setup window does not open | `tkinter` is missing from the Python install. | Use the standard Windows Python installer or install a Python build with Tk support. |
| Client times out | Public port mapping, cloud security group, firewall, or server process is not reachable. | Confirm the server console is open, confirm `Listen port`, cloud mapping, and Windows Firewall. |
| `Connection refused` | Nothing is listening on the target port. | Start `start-server.cmd` and verify the port in `wcrc-server.json`. |
| TLS hostname or certificate verification error | The client host does not match the server certificate SAN. | Regenerate with the exact `Public host` used by the client, or add the host under extra SANs. |
| Server logs `TLS handshake failed` | Client is using the wrong CA/client certificate pair. | Use the `wcrc-client.json` and `certs/` generated together with the uploaded server bundle. |
| `cwd is outside base-dir` | The requested `--cwd` is not under server `base_dir`. | Use a remote directory inside `base_dir`, or regenerate/edit server config with the intended base directory. |
| `shell mode is disabled on this server` | `Allow shell mode` was unchecked or `allow_shell` is false. | Regenerate with shell mode enabled or set `"allow_shell": true` in `wcrc-server.json` before starting the server. |
| Command exits with non-zero return code | The remote command itself failed. | Re-run with `--json` to inspect `stdout`, `stderr`, and `returncode`. |
| PowerShell execution policy blocks `.ps1` | Local policy blocks script execution. | Use the `.cmd` helpers or run the direct `python -m ...` command. |

## Config Files

The server and client can read JSON config files generated by the wizard.

Client example:

```json
{
  "host": "203.0.113.10",
  "port": 18785,
  "server_name": "203.0.113.10",
  "ca": "certs/ca.crt",
  "cert": "certs/client.crt",
  "key": "certs/client.key",
  "timeout": 300
}
```

Run it:

```powershell
python -m wcrc.remote_exec_client --config .\wcrc-client.json -- whoami
```

Server example:

```json
{
  "host": "0.0.0.0",
  "port": 49606,
  "ca": "certs/ca.crt",
  "cert": "certs/server.crt",
  "key": "certs/server.key",
  "base_dir": "C:\\Users\\Administrator\\Desktop",
  "allow_shell": true,
  "timeout": 300,
  "max_output": 4194304,
  "log": "remote_exec_server.log"
}
```

Run it:

```cmd
python -m wcrc.remote_exec_server --config wcrc-server.json
```

Relative paths inside config files are resolved relative to the config file location.

## Manual Setup

Use the manual flow when you want scriptable certificate generation instead of the guided window.

### 1. Generate Certificates Locally

Run this on your local machine, not on the server:

```powershell
python -m wcrc.make_certs --server-ip YOUR_SERVER_PUBLIC_IP
```

For a DNS name:

```powershell
python -m wcrc.make_certs --server-dns example.com
```

Generated files are written to `certs/`.

Upload to the server:

```text
wcrc/remote_exec_server.py
wcrc/__init__.py
certs/ca.crt
certs/server.crt
certs/server.key
scripts/start-server.example.cmd
```

Keep local only:

```text
certs/client.crt
certs/client.key
certs/ca.crt
wcrc/remote_exec_client.py
```

### 2. Create a Server Bundle

After generating certs, create a zip containing only the server-side files:

```powershell
.\scripts\make-server-bundle.ps1
```

This creates:

```text
wcrc-server-bundle.zip
```

Copy that zip to the server and extract it.

### 3. Start the Server

On the Windows server, edit `start-server.cmd`:

- `PORT` is the internal port the cloud provider maps from the public port.
- `BASE_DIR` is the directory where remote commands are allowed to run.

Then run:

```cmd
start-server.cmd
```

Equivalent direct command:

```cmd
python -m wcrc.remote_exec_server ^
  --host 0.0.0.0 ^
  --port 49606 ^
  --ca certs\ca.crt ^
  --cert certs\server.crt ^
  --key certs\server.key ^
  --base-dir C:\Users\Administrator\Desktop ^
  --allow-shell ^
  --timeout 300 ^
  --log remote_exec_server.log
```

If Windows Firewall blocks the internal port, run an Administrator CMD after editing the port:

```cmd
netsh advfirewall firewall add rule name="WCRC mTLS remote bridge" dir=in action=allow protocol=TCP localport=49606
```

### 4. Connect from Local

Run an argv command:

```powershell
python -m wcrc.remote_exec_client `
  --host YOUR_SERVER_PUBLIC_IP `
  --port 18785 `
  --ca certs\ca.crt `
  --cert certs\client.crt `
  --key certs\client.key `
  -- whoami
```

Run a PowerShell command through shell mode:

```powershell
python -m wcrc.remote_exec_client `
  --host YOUR_SERVER_PUBLIC_IP `
  --port 18785 `
  --ca certs\ca.crt `
  --cert certs\client.crt `
  --key certs\client.key `
  --shell "Get-ChildItem | Select-Object Name,Length"
```

Print raw JSON:

```powershell
python -m wcrc.remote_exec_client `
  --host YOUR_SERVER_PUBLIC_IP `
  --port 18785 `
  --ca certs\ca.crt `
  --cert certs\client.crt `
  --key certs\client.key `
  --json `
  -- powershell -NoProfile -Command "$PSVersionTable.PSVersion"
```

## Linux Server Example

```bash
python3 -m wcrc.remote_exec_server \
  --host 0.0.0.0 \
  --port 49606 \
  --ca certs/ca.crt \
  --cert certs/server.crt \
  --key certs/server.key \
  --base-dir /srv \
  --allow-shell \
  --timeout 180 \
  --log remote_exec_server.log
```

## Audit Log

The server writes JSON Lines records to `remote_exec_server.log`, including:

- UTC time
- client certificate common name
- remote IP
- mode
- command
- cwd
- return code
- duration

Stdout and stderr are returned to the authenticated client but are not stored in the audit log by default.

## Operational Checklist

1. Generate certificates locally with the server public IP or DNS in SAN.
2. Build and upload only the server bundle.
3. Open one mapped TCP port to the server internal port.
4. Start `start-server.cmd` in a visible console.
5. Run client commands from local.
6. Stop the server process after maintenance.

## Development

Run a quick syntax and certificate generation smoke test:

```powershell
.\scripts\smoke-test.ps1
```

## Repository Safety

The `.gitignore` excludes generated certs, private keys, logs, and bundles. Review `git status` before pushing if you generated secrets in a non-default path.
