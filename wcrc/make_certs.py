#!/usr/bin/env python3
"""Generate a private CA plus server/client certificates for WCRC mTLS."""

from __future__ import annotations

import argparse
import ipaddress
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID


def key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=3072)


def write_private_key(path: Path, private_key: rsa.RSAPrivateKey) -> None:
    path.write_bytes(
        private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )


def write_cert(path: Path, cert: x509.Certificate) -> None:
    path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))


def name(common_name: str) -> x509.Name:
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])


def sign_cert(
    subject_name: x509.Name,
    public_key,
    issuer_name: x509.Name,
    issuer_key,
    days: int,
    extensions: list[tuple[x509.ExtensionType, bool]],
) -> x509.Certificate:
    now = datetime.now(timezone.utc)
    builder = (
        x509.CertificateBuilder()
        .subject_name(subject_name)
        .issuer_name(issuer_name)
        .public_key(public_key)
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=days))
    )
    for extension, critical in extensions:
        builder = builder.add_extension(extension, critical=critical)
    return builder.sign(private_key=issuer_key, algorithm=hashes.SHA256())


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate mTLS certificates")
    parser.add_argument("--out", default="certs", help="Output directory")
    parser.add_argument("--server-ip", action="append", default=[], help="Server IP SAN; can be repeated")
    parser.add_argument("--server-dns", action="append", default=[], help="Server DNS SAN")
    parser.add_argument("--days", type=int, default=30, help="Certificate validity days")
    args = parser.parse_args()
    if not args.server_ip and not args.server_dns:
        parser.error("provide at least one --server-ip or --server-dns for the server certificate SAN")
    if args.days < 1:
        parser.error("--days must be at least 1")
    return args


def main() -> None:
    args = parse_args()
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)

    ca_key = key()
    ca_name = name("WCRC Remote Connect Local CA")
    ca_cert = sign_cert(
        ca_name,
        ca_key.public_key(),
        ca_name,
        ca_key,
        args.days,
        [
            (x509.BasicConstraints(ca=True, path_length=0), True),
            (x509.KeyUsage(True, False, False, False, False, True, True, False, False), True),
            (x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), False),
        ],
    )

    server_key = key()
    alt_names: list[x509.GeneralName] = []
    for value in dict.fromkeys(args.server_ip):
        alt_names.append(x509.IPAddress(ipaddress.ip_address(value)))
    for value in dict.fromkeys(args.server_dns):
        alt_names.append(x509.DNSName(value))
    server_cert = sign_cert(
        name("wcrc-remote-server"),
        server_key.public_key(),
        ca_cert.subject,
        ca_key,
        args.days,
        [
            (x509.BasicConstraints(ca=False, path_length=None), True),
            (x509.SubjectAlternativeName(alt_names), False),
            (x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), False),
            (x509.SubjectKeyIdentifier.from_public_key(server_key.public_key()), False),
            (x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), False),
            (x509.KeyUsage(True, False, True, False, False, False, False, False, False), True),
        ],
    )

    client_key = key()
    client_cert = sign_cert(
        name("wcrc-codex-client"),
        client_key.public_key(),
        ca_cert.subject,
        ca_key,
        args.days,
        [
            (x509.BasicConstraints(ca=False, path_length=None), True),
            (x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), False),
            (x509.SubjectKeyIdentifier.from_public_key(client_key.public_key()), False),
            (x509.ExtendedKeyUsage([ExtendedKeyUsageOID.CLIENT_AUTH]), False),
            (x509.KeyUsage(True, False, True, False, False, False, False, False, False), True),
        ],
    )

    write_private_key(out / "ca.key", ca_key)
    write_cert(out / "ca.crt", ca_cert)
    write_private_key(out / "server.key", server_key)
    write_cert(out / "server.crt", server_cert)
    write_private_key(out / "client.key", client_key)
    write_cert(out / "client.crt", client_cert)

    (out / "FILES.txt").write_text(
        "Upload to server: ca.crt, server.crt, server.key, wcrc/remote_exec_server.py, wcrc/__init__.py\n"
        "Keep on local machine only: ca.crt, client.crt, client.key, wcrc/remote_exec_client.py\n"
        "Never upload client.key to the server.\n",
        encoding="utf-8",
    )
    print(f"Generated certificates in {out}")


if __name__ == "__main__":
    main()
