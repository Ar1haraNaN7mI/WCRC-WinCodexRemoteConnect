#!/usr/bin/env python3
"""Small mTLS-protected remote command runner for an explicitly managed server.

This is intentionally not a daemon installer. Run it in a visible terminal or
inside your normal process supervisor, and stop it when deployment work is done.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import ssl
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path


MAX_REQUEST_BYTES = 256 * 1024
DEFAULT_TIMEOUT_SECONDS = 120


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="mTLS remote command server")
    parser.add_argument("--host", default="0.0.0.0", help="Bind address")
    parser.add_argument("--port", type=int, required=True, help="Bind port on the server")
    parser.add_argument("--cert", required=True, help="Server certificate PEM")
    parser.add_argument("--key", required=True, help="Server private key PEM")
    parser.add_argument("--ca", required=True, help="CA certificate that signed allowed client certs")
    parser.add_argument("--base-dir", default=str(Path.cwd()), help="Allowed working directory root")
    parser.add_argument("--allow-shell", action="store_true", help="Allow shell-mode commands")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_SECONDS, help="Default command timeout")
    parser.add_argument("--max-output", type=int, default=4 * 1024 * 1024, help="Max stdout/stderr chars returned")
    parser.add_argument("--log", default="remote_exec_server.log", help="Audit log path")
    parser.add_argument("--strict-x509", action="store_true", help="Enable Python's strict X509 verification flags")
    args = parser.parse_args()
    if args.port < 1 or args.port > 65535:
        parser.error("--port must be between 1 and 65535")
    if args.timeout < 1:
        parser.error("--timeout must be at least 1")
    if args.max_output < 1024:
        parser.error("--max-output must be at least 1024")
    return args


def peer_name(conn: ssl.SSLSocket) -> str:
    cert = conn.getpeercert() or {}
    subject = cert.get("subject", [])
    for group in subject:
        for key, value in group:
            if key == "commonName":
                return value
    return "unknown-client"


def write_log(log_path: Path, record: dict) -> None:
    record = {"time": utc_now(), **record}
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def print_event(message: str) -> None:
    print(f"[{utc_now()}] {message}", flush=True)


def safe_cwd(base_dir: Path, requested: str | None) -> Path:
    base = base_dir.resolve()
    cwd = base if not requested else Path(requested).expanduser().resolve()
    if cwd != base and base not in cwd.parents:
        raise ValueError(f"cwd is outside base-dir: {cwd}")
    return cwd


def truncate(value: str, max_chars: int) -> tuple[str, bool]:
    if len(value) <= max_chars:
        return value, False
    return value[:max_chars], True


def run_command(request: dict, args: argparse.Namespace) -> dict:
    mode = request.get("mode", "argv")
    timeout = int(request.get("timeout") or args.timeout)
    timeout = max(1, min(timeout, args.timeout))
    cwd = safe_cwd(Path(args.base_dir), request.get("cwd"))

    started = time.monotonic()
    if mode == "argv":
        argv = request.get("argv")
        if not isinstance(argv, list) or not argv or not all(isinstance(item, str) for item in argv):
            raise ValueError("argv mode requires a non-empty string argv array")
        completed = subprocess.run(
            argv,
            cwd=str(cwd),
            shell=False,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
        )
        command_for_log = argv
    elif mode == "shell":
        if not args.allow_shell:
            raise ValueError("shell mode is disabled on this server")
        command = request.get("command")
        if not isinstance(command, str) or not command.strip():
            raise ValueError("shell mode requires a non-empty command string")
        completed = subprocess.run(
            command,
            cwd=str(cwd),
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
        )
        command_for_log = command
    else:
        raise ValueError(f"unknown command mode: {mode}")

    stdout, stdout_truncated = truncate(completed.stdout or "", args.max_output)
    stderr, stderr_truncated = truncate(completed.stderr or "", args.max_output)
    return {
        "ok": True,
        "mode": mode,
        "command": command_for_log,
        "cwd": str(cwd),
        "returncode": completed.returncode,
        "duration_ms": int((time.monotonic() - started) * 1000),
        "stdout": stdout,
        "stderr": stderr,
        "stdout_truncated": stdout_truncated,
        "stderr_truncated": stderr_truncated,
    }


def read_json_line(conn: ssl.SSLSocket) -> dict:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = conn.recv(4096)
        if not chunk:
            break
        total += len(chunk)
        if total > MAX_REQUEST_BYTES:
            raise ValueError("request too large")
        chunks.append(chunk)
        if b"\n" in chunk:
            break
    raw = b"".join(chunks).split(b"\n", 1)[0]
    if not raw:
        raise ValueError("empty request")
    return json.loads(raw.decode("utf-8"))


def handle_client(conn: ssl.SSLSocket, address: tuple, args: argparse.Namespace, log_path: Path) -> None:
    client = peer_name(conn)
    try:
        request = read_json_line(conn)
        result = run_command(request, args)
        write_log(log_path, {
            "client": client,
            "remote": address[0],
            "mode": result["mode"],
            "command": result["command"],
            "cwd": result["cwd"],
            "returncode": result["returncode"],
            "duration_ms": result["duration_ms"],
        })
    except subprocess.TimeoutExpired as exc:
        result = {"ok": False, "error": f"command timed out after {exc.timeout}s", "returncode": 124}
        write_log(log_path, {"client": client, "remote": address[0], "error": result["error"]})
    except Exception as exc:  # Return explicit errors to the authenticated client.
        result = {"ok": False, "error": str(exc), "returncode": 1}
        write_log(log_path, {"client": client, "remote": address[0], "error": result["error"]})
    finally:
        try:
            conn.sendall((json.dumps(result, ensure_ascii=False) + "\n").encode("utf-8"))
        except Exception:
            pass
        conn.close()


def main() -> None:
    args = parse_args()
    base_dir = Path(args.base_dir).expanduser().resolve()
    if not base_dir.exists():
        raise SystemExit(f"base-dir does not exist: {base_dir}")
    args.base_dir = str(base_dir)
    log_path = Path(args.log).expanduser().resolve()

    context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    if not args.strict_x509 and hasattr(ssl, "VERIFY_X509_STRICT"):
        context.verify_flags &= ~ssl.VERIFY_X509_STRICT
    context.verify_mode = ssl.CERT_REQUIRED
    context.load_cert_chain(certfile=args.cert, keyfile=args.key)
    context.load_verify_locations(cafile=args.ca)

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((args.host, args.port))
        server.listen(20)
        print_event(f"mTLS remote exec listening on {args.host}:{args.port}, base-dir={args.base_dir}")
        while True:
            raw_conn, address = server.accept()
            try:
                conn = context.wrap_socket(raw_conn, server_side=True)
            except ssl.SSLError as exc:
                write_log(log_path, {"remote": address[0], "error": f"TLS handshake failed: {exc}"})
                print_event(f"TLS handshake failed from {address[0]}:{address[1]}: {exc}")
                raw_conn.close()
                continue
            thread = threading.Thread(target=handle_client, args=(conn, address, args, log_path), daemon=True)
            thread.start()


if __name__ == "__main__":
    main()
