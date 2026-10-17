#!/usr/bin/env python3
"""Create a separate local Quest certificate without replacing shared certificates."""

import argparse
import ipaddress
import subprocess
import tempfile
from pathlib import Path

from benchmark.paths import ROOT, writable_output


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host-ip", required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "results/phase3_tls")
    args = parser.parse_args(argv)
    address = ipaddress.ip_address(args.host_ip)
    destination = writable_output(args.output)
    if destination.exists():
        raise FileExistsError(
            f"Choose a new directory; existing TLS files are preserved: {destination}"
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".quest-tls-", dir=destination.parent) as temporary:
        folder = Path(temporary)
        subprocess.run(
            [
                "openssl",
                "req",
                "-x509",
                "-newkey",
                "rsa:2048",
                "-nodes",
                "-days",
                "365",
                "-keyout",
                str(folder / "key.pem"),
                "-out",
                str(folder / "cert.pem"),
                "-subj",
                "/CN=Quest Hand Local Receiver",
                "-addext",
                f"subjectAltName=IP:{address},IP:127.0.0.1,DNS:localhost",
            ],
            check=True,
            capture_output=True,
        )
        (folder / "key.pem").chmod(0o600)
        folder.chmod(0o700)
        folder.rename(destination)
    print(f"Certificate: {destination / 'cert.pem'}")
    print(f"Private key saved with mode 0600 in {destination}")
    print("Shared certificates and system/browser trust stores were not modified.")


if __name__ == "__main__":
    main()
