#!/usr/bin/env python3
"""Client for the mTLS remote command runner."""

from __future__ import annotations

import argparse
import json
import socket
import ssl
import sys


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="mTLS remote command client")
    parser.add_argument("--host", required=True, help="Public server IP or DNS")
    parser.add_argument("--port", type=int, required=True, help="Public mapped port")
    parser.add_argument("--server-name", default=None, help="TLS server name; defaults to --host")
    parser.add_argument("--ca", required=True, help="CA certificate PEM")
    parser.add_argument("--cert", required=True, help="Client certificate PEM")
    parser.add_argument("--key", required=True, help="Client private key PEM")
    parser.add_argument("--cwd", default=None, help="Remote working directory")
    parser.add_argument("--timeout", type=int, default=120, help="Remote command timeout")
    parser.add_argument("--shell", default=None, help="Run this command through the remote shell")
    parser.add_argument("--json", action="store_true", help="Print raw JSON response")
    parser.add_argument("argv", nargs=argparse.REMAINDER, help="Command argv after --")
    args = parser.parse_args()
    if args.port < 1 or args.port > 65535:
        parser.error("--port must be between 1 and 65535")
    if args.timeout < 1:
        parser.error("--timeout must be at least 1")
    return args


def make_payload(args: argparse.Namespace) -> dict:
    payload = {"cwd": args.cwd, "timeout": args.timeout}
    if args.shell is not None:
        payload.update({"mode": "shell", "command": args.shell})
    else:
        argv = args.argv
        if argv and argv[0] == "--":
            argv = argv[1:]
        if not argv:
            raise SystemExit("Provide a command after --, or use --shell \"...\"")
        payload.update({"mode": "argv", "argv": argv})
    return payload


def request(args: argparse.Namespace, payload: dict) -> dict:
    context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH, cafile=args.ca)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    if hasattr(ssl, "VERIFY_X509_STRICT"):
        context.verify_flags &= ~ssl.VERIFY_X509_STRICT
    context.load_cert_chain(certfile=args.cert, keyfile=args.key)
    server_name = args.server_name or args.host

    with socket.create_connection((args.host, args.port), timeout=15) as raw_sock:
        with context.wrap_socket(raw_sock, server_hostname=server_name) as conn:
            conn.settimeout(max(args.timeout + 30, 60))
            conn.sendall((json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"))
            chunks: list[bytes] = []
            while True:
                chunk = conn.recv(65536)
                if not chunk:
                    break
                chunks.append(chunk)
    if not chunks:
        raise RuntimeError("empty response")
    return json.loads(b"".join(chunks).decode("utf-8"))


def main() -> None:
    args = parse_args()
    payload = make_payload(args)
    response = request(args, payload)

    if args.json:
        print(json.dumps(response, ensure_ascii=False, indent=2))
    else:
        if response.get("stdout"):
            print(response["stdout"], end="" if response["stdout"].endswith("\n") else "\n")
        if response.get("stderr"):
            print(response["stderr"], end="" if response["stderr"].endswith("\n") else "\n", file=sys.stderr)
        if not response.get("ok"):
            print(f"remote error: {response.get('error', 'unknown error')}", file=sys.stderr)

    code = int(response.get("returncode", 1))
    raise SystemExit(code if 0 <= code <= 255 else 1)


if __name__ == "__main__":
    main()
