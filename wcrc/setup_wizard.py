#!/usr/bin/env python3
"""Small Tk setup wizard for WCRC certificates and connection config."""

from __future__ import annotations

import ipaddress
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from wcrc.make_certs import generate_certificates


DEFAULT_OUTPUT_DIR = Path("output") / "guided-setup"
DEFAULT_PORT = 49606
DEFAULT_TIMEOUT = 300
DEFAULT_BASE_DIR = r"C:\Users\Administrator\Desktop"
MAX_OUTPUT_CHARS = 4 * 1024 * 1024


@dataclass(frozen=True)
class SetupSettings:
    public_host: str
    public_port: int = DEFAULT_PORT
    bind_host: str = "0.0.0.0"
    bind_port: int = DEFAULT_PORT
    base_dir: str = DEFAULT_BASE_DIR
    allow_shell: bool = True
    timeout: int = DEFAULT_TIMEOUT
    days: int = 30
    server_ips: tuple[str, ...] = ()
    server_dns: tuple[str, ...] = ()
    output_dir: Path = field(default_factory=lambda: DEFAULT_OUTPUT_DIR)


@dataclass(frozen=True)
class SetupResult:
    output_dir: Path
    cert_dir: Path
    client_config: Path
    server_config: Path
    server_bundle_dir: Path
    server_bundle_zip: Path


def split_values(raw: str) -> list[str]:
    return [value for value in re.split(r"[\s,;]+", raw.strip()) if value]


def parse_public_host(raw: str) -> tuple[str, int | None]:
    raw = raw.strip()
    if not raw:
        raise ValueError("Public host is required.")

    try:
        ipaddress.ip_address(raw)
        return raw, None
    except ValueError:
        pass

    candidate = raw if "://" in raw else f"//{raw}"
    parsed = urlparse(candidate)
    host = parsed.hostname
    if not host:
        return raw, None
    try:
        return host, parsed.port
    except ValueError as exc:
        raise ValueError("Public host contains an invalid port.") from exc


def classify_host_for_san(host: str) -> tuple[list[str], list[str]]:
    try:
        ipaddress.ip_address(host)
        return [host], []
    except ValueError:
        return [], [host]


def unique(values: list[str] | tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value.strip() for value in values if value.strip()))


def checked_port(value: str | int, label: str) -> int:
    try:
        port = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a number.") from exc
    if port < 1 or port > 65535:
        raise ValueError(f"{label} must be between 1 and 65535.")
    return port


def checked_positive_int(value: str | int, label: str) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a number.") from exc
    if number < 1:
        raise ValueError(f"{label} must be at least 1.")
    return number


def effective_sans(settings: SetupSettings) -> tuple[tuple[str, ...], tuple[str, ...]]:
    host_ips, host_dns = classify_host_for_san(settings.public_host)
    return unique([*settings.server_ips, *host_ips]), unique([*settings.server_dns, *host_dns])


def write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def copy_package_files(target_package_dir: Path, module_names: tuple[str, ...]) -> None:
    source_package_dir = Path(__file__).resolve().parent
    target_package_dir.mkdir(parents=True, exist_ok=True)
    for module_name in module_names:
        shutil.copy2(source_package_dir / module_name, target_package_dir / module_name)


def assert_safe_generated_package_path(output_dir: Path) -> None:
    source_package_dir = Path(__file__).resolve().parent
    generated_package_dir = (output_dir / "wcrc").resolve()
    if generated_package_dir == source_package_dir:
        raise ValueError("Output directory cannot be the project root; choose a subdirectory such as output\\guided-setup.")


def write_text(path: Path, value: str) -> None:
    path.write_text(value, encoding="utf-8", newline="\n")


def write_client_files(output_dir: Path, settings: SetupSettings) -> Path:
    client_config = output_dir / "wcrc-client.json"
    write_json(
        client_config,
        {
            "host": settings.public_host,
            "port": settings.public_port,
            "server_name": settings.public_host,
            "ca": "certs/ca.crt",
            "cert": "certs/client.crt",
            "key": "certs/client.key",
            "timeout": settings.timeout,
        },
    )

    write_text(
        output_dir / "run-whoami.ps1",
        """$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
python -m wcrc.remote_exec_client --config (Join-Path $PSScriptRoot "wcrc-client.json") -- whoami
exit $LASTEXITCODE
""",
    )
    write_text(
        output_dir / "wcrc-command.cmd",
        """@echo off
setlocal
cd /d "%~dp0"
if "%~1"=="" (
  echo Usage: wcrc-command.cmd whoami
  exit /b 2
)
python -m wcrc.remote_exec_client --config "%~dp0wcrc-client.json" -- %*
""",
    )
    if settings.allow_shell:
        write_text(
            output_dir / "wcrc-shell.cmd",
            """@echo off
setlocal
cd /d "%~dp0"
if "%~1"=="" (
  echo Usage: wcrc-shell.cmd "Get-ChildItem"
  exit /b 2
)
python -m wcrc.remote_exec_client --config "%~dp0wcrc-client.json" --shell "%*"
""",
        )
    else:
        (output_dir / "wcrc-shell.cmd").unlink(missing_ok=True)
    return client_config


def write_server_files(server_dir: Path, settings: SetupSettings) -> Path:
    server_config = server_dir / "wcrc-server.json"
    write_json(
        server_config,
        {
            "host": settings.bind_host,
            "port": settings.bind_port,
            "ca": "certs/ca.crt",
            "cert": "certs/server.crt",
            "key": "certs/server.key",
            "base_dir": settings.base_dir,
            "allow_shell": settings.allow_shell,
            "timeout": settings.timeout,
            "max_output": MAX_OUTPUT_CHARS,
            "log": "remote_exec_server.log",
        },
    )
    write_text(
        server_dir / "start-server.cmd",
        """@echo off
setlocal
cd /d "%~dp0"
python -m wcrc.remote_exec_server --config "%~dp0wcrc-server.json"
pause
""",
    )
    write_text(
        server_dir / "start-server.ps1",
        """$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
python -m wcrc.remote_exec_server --config (Join-Path $PSScriptRoot "wcrc-server.json")
""",
    )
    write_text(
        server_dir / "firewall-rule.example.cmd",
        f"""@echo off
REM Run as Administrator if Windows Firewall blocks the WCRC listen port.
netsh advfirewall firewall add rule name="WCRC mTLS remote bridge" dir=in action=allow protocol=TCP localport={settings.bind_port}
""",
    )
    write_text(
        server_dir / "README-SERVER.txt",
        f"""WCRC server bundle

1. Extract this folder or wcrc-server-bundle.zip on the target server.
2. Confirm wcrc-server.json:
   - host: {settings.bind_host}
   - port: {settings.bind_port}
   - base_dir: {settings.base_dir}
3. If Windows Firewall blocks the port, run firewall-rule.example.cmd as Administrator.
4. Run start-server.cmd and keep the console open while using WCRC.

This bundle intentionally excludes client.key and ca.key.
""",
    )
    return server_config


def write_local_readme(output_dir: Path, settings: SetupSettings, result: SetupResult) -> None:
    shell_example = ""
    if settings.allow_shell:
        shell_example = (
            "\nRun a remote PowerShell command through shell mode:\n\n"
            "  python -m wcrc.remote_exec_client --config .\\wcrc-client.json --shell \"Get-ChildItem\"\n"
        )
    write_text(
        output_dir / "README-WCRC-SETUP.txt",
        f"""WCRC guided setup output

Connection:
  public host: {settings.public_host}
  public port: {settings.public_port}
  server listen: {settings.bind_host}:{settings.bind_port}

Upload this file to the server:
  {result.server_bundle_zip.name}

On the server:
  1. Extract {result.server_bundle_zip.name}.
  2. Run start-server.cmd.
  3. If the port is blocked, run firewall-rule.example.cmd as Administrator.

On this local machine, run from this output directory:
  python -m wcrc.remote_exec_client --config .\\wcrc-client.json -- whoami

Or use:
  .\\wcrc-command.cmd whoami
{shell_example}
Keep certs\\client.key and certs\\ca.key private. Do not upload them to the server.
""",
    )


def create_zip(source_dir: Path, zip_path: Path) -> None:
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as handle:
        for path in sorted(source_dir.rglob("*")):
            if path.is_file():
                handle.write(path, path.relative_to(source_dir).as_posix())


def create_setup_files(settings: SetupSettings) -> SetupResult:
    output_dir = settings.output_dir.expanduser().resolve()
    assert_safe_generated_package_path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    cert_dir = output_dir / "certs"
    server_dir = output_dir / "server-bundle"
    local_package_dir = output_dir / "wcrc"
    server_zip = output_dir / "wcrc-server-bundle.zip"

    server_ips, server_dns = effective_sans(settings)
    generate_certificates(cert_dir, server_ips=server_ips, server_dns=server_dns, days=settings.days)

    if local_package_dir.exists():
        shutil.rmtree(local_package_dir)
    copy_package_files(local_package_dir, ("__init__.py", "config.py", "remote_exec_client.py"))
    client_config = write_client_files(output_dir, settings)

    if server_dir.exists():
        shutil.rmtree(server_dir)
    (server_dir / "certs").mkdir(parents=True, exist_ok=True)
    copy_package_files(server_dir / "wcrc", ("__init__.py", "config.py", "remote_exec_server.py"))
    for name in ("ca.crt", "server.crt", "server.key"):
        shutil.copy2(cert_dir / name, server_dir / "certs" / name)
    server_config = write_server_files(server_dir, settings)

    result = SetupResult(
        output_dir=output_dir,
        cert_dir=cert_dir,
        client_config=client_config,
        server_config=server_config,
        server_bundle_dir=server_dir,
        server_bundle_zip=server_zip,
    )
    write_local_readme(output_dir, settings, result)
    create_zip(server_dir, server_zip)
    return result


class SetupWizard:
    def __init__(self, root) -> None:
        import tkinter as tk
        from tkinter import ttk

        self.root = root
        self.tk = tk
        self.ttk = ttk
        self.last_output_dir: Path | None = None

        root.title("WCRC guided setup")
        root.minsize(760, 620)

        frame = ttk.Frame(root, padding=16)
        frame.grid(row=0, column=0, sticky="nsew")
        root.columnconfigure(0, weight=1)
        root.rowconfigure(0, weight=1)
        frame.columnconfigure(1, weight=1)

        self.public_host = tk.StringVar()
        self.public_port = tk.StringVar(value=str(DEFAULT_PORT))
        self.server_ips = tk.StringVar()
        self.server_dns = tk.StringVar()
        self.bind_host = tk.StringVar(value="0.0.0.0")
        self.bind_port = tk.StringVar(value=str(DEFAULT_PORT))
        self.base_dir = tk.StringVar(value=DEFAULT_BASE_DIR)
        self.allow_shell = tk.BooleanVar(value=True)
        self.timeout = tk.StringVar(value=str(DEFAULT_TIMEOUT))
        self.days = tk.StringVar(value="30")
        self.output_dir = tk.StringVar(value=str(DEFAULT_OUTPUT_DIR))

        row = 0
        row = self.add_heading(frame, row, "Connection")
        row = self.add_entry(frame, row, "Public host", self.public_host, "Server public IP or DNS used by the client.")
        row = self.add_entry(frame, row, "Public port", self.public_port, "Cloud/public mapped port used by the client.")
        row = self.add_entry(frame, row, "Extra IP SANs", self.server_ips, "Optional, comma or space separated.")
        row = self.add_entry(frame, row, "Extra DNS SANs", self.server_dns, "Optional, comma or space separated.")

        row = self.add_heading(frame, row, "Server")
        row = self.add_entry(frame, row, "Bind host", self.bind_host, "Usually 0.0.0.0.")
        row = self.add_entry(frame, row, "Listen port", self.bind_port, "Internal port on the server.")
        row = self.add_entry(frame, row, "Base directory", self.base_dir, "Remote commands are limited to this server path.")
        row = self.add_check(frame, row, "Allow shell mode", self.allow_shell)
        row = self.add_entry(frame, row, "Timeout seconds", self.timeout, "Maximum remote command runtime.")
        row = self.add_entry(frame, row, "Certificate days", self.days, "Certificate validity period.")

        row = self.add_heading(frame, row, "Output")
        row = self.add_output_entry(frame, row)

        actions = ttk.Frame(frame)
        actions.grid(row=row, column=0, columnspan=3, sticky="ew", pady=(16, 8))
        actions.columnconfigure(2, weight=1)
        ttk.Button(actions, text="Generate setup", command=self.generate).grid(row=0, column=0, sticky="w")
        self.open_button = ttk.Button(actions, text="Open output folder", command=self.open_output, state="disabled")
        self.open_button.grid(row=0, column=1, sticky="w", padx=(8, 0))
        row += 1

        self.status = tk.Text(frame, height=9, wrap="word")
        self.status.grid(row=row, column=0, columnspan=3, sticky="nsew", pady=(8, 0))
        frame.rowconfigure(row, weight=1)
        self.log("Fill in the public host and ports, then generate the setup files.")

    def add_heading(self, frame, row: int, text: str) -> int:
        label = self.ttk.Label(frame, text=text, font=("", 10, "bold"))
        label.grid(row=row, column=0, columnspan=3, sticky="w", pady=(12, 4))
        return row + 1

    def add_entry(self, frame, row: int, label: str, variable, hint: str) -> int:
        self.ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", pady=3)
        self.ttk.Entry(frame, textvariable=variable).grid(row=row, column=1, sticky="ew", pady=3)
        self.ttk.Label(frame, text=hint).grid(row=row, column=2, sticky="w", padx=(8, 0), pady=3)
        return row + 1

    def add_check(self, frame, row: int, label: str, variable) -> int:
        self.ttk.Checkbutton(frame, text=label, variable=variable).grid(row=row, column=1, sticky="w", pady=3)
        return row + 1

    def add_output_entry(self, frame, row: int) -> int:
        from tkinter import filedialog

        def browse() -> None:
            selected = filedialog.askdirectory(initialdir=str(Path.cwd()))
            if selected:
                self.output_dir.set(selected)

        self.ttk.Label(frame, text="Output directory").grid(row=row, column=0, sticky="w", pady=3)
        self.ttk.Entry(frame, textvariable=self.output_dir).grid(row=row, column=1, sticky="ew", pady=3)
        self.ttk.Button(frame, text="Browse", command=browse).grid(row=row, column=2, sticky="w", padx=(8, 0), pady=3)
        return row + 1

    def log(self, message: str) -> None:
        self.status.insert("end", message.rstrip() + "\n")
        self.status.see("end")

    def gather_settings(self) -> SetupSettings:
        public_host, parsed_port = parse_public_host(self.public_host.get())
        public_port_raw = self.public_port.get().strip()
        if parsed_port is not None and public_port_raw in {"", str(DEFAULT_PORT)}:
            public_port = parsed_port
        else:
            public_port = checked_port(public_port_raw or DEFAULT_PORT, "Public port")
        bind_port = checked_port(self.bind_port.get(), "Listen port")
        timeout = checked_positive_int(self.timeout.get(), "Timeout seconds")
        days = checked_positive_int(self.days.get(), "Certificate days")
        bind_host = self.bind_host.get().strip() or "0.0.0.0"
        base_dir = self.base_dir.get().strip()
        if not base_dir:
            raise ValueError("Base directory is required.")
        return SetupSettings(
            public_host=public_host,
            public_port=public_port,
            bind_host=bind_host,
            bind_port=bind_port,
            base_dir=base_dir,
            allow_shell=bool(self.allow_shell.get()),
            timeout=timeout,
            days=days,
            server_ips=tuple(split_values(self.server_ips.get())),
            server_dns=tuple(split_values(self.server_dns.get())),
            output_dir=Path(self.output_dir.get().strip() or DEFAULT_OUTPUT_DIR),
        )

    def generate(self) -> None:
        from tkinter import messagebox

        try:
            settings = self.gather_settings()
            output_dir = settings.output_dir.expanduser().resolve()
            if output_dir.exists() and any(output_dir.iterdir()):
                ok = messagebox.askyesno(
                    "Overwrite generated files",
                    f"WCRC files in this directory may be overwritten:\n\n{output_dir}\n\nContinue?",
                )
                if not ok:
                    return
            result = create_setup_files(settings)
        except Exception as exc:
            messagebox.showerror("WCRC setup failed", str(exc))
            self.log(f"Error: {exc}")
            return

        self.last_output_dir = result.output_dir
        self.open_button.configure(state="normal")
        self.log(f"Generated setup in: {result.output_dir}")
        self.log(f"Server bundle zip: {result.server_bundle_zip}")
        self.log(f"Client config: {result.client_config}")
        self.log("Next: upload wcrc-server-bundle.zip to the server, extract it, then run start-server.cmd.")
        messagebox.showinfo("WCRC setup complete", f"Generated setup in:\n{result.output_dir}")

    def open_output(self) -> None:
        if not self.last_output_dir:
            return
        if sys.platform.startswith("win"):
            os.startfile(self.last_output_dir)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.run(["open", str(self.last_output_dir)], check=False)
        else:
            subprocess.run(["xdg-open", str(self.last_output_dir)], check=False)


def main() -> None:
    try:
        import tkinter as tk
    except ImportError as exc:
        raise SystemExit("tkinter is required for the setup wizard. On Windows, use the standard python.org build.") from exc

    root = tk.Tk()
    SetupWizard(root)
    root.mainloop()


if __name__ == "__main__":
    main()
