#!/usr/bin/env python3
"""Generate a VAPID (ES256) keypair for Web Push. Needs `openssl` only.

Prints export lines — add them to your env / .env, then restart AURA:
  AURA_VAPID_PUBLIC_KEY=...
  AURA_VAPID_PRIVATE_KEY=...
"""
import base64
import re
import subprocess
import sys


def b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def main() -> int:
    try:
        key_pem = subprocess.run(
            ["openssl", "ecparam", "-genkey", "-name", "prime256v1", "-noout"],
            capture_output=True, check=True).stdout
        text = subprocess.run(
            ["openssl", "ec", "-in", "/dev/stdin", "-text", "-noout"],
            input=key_pem, capture_output=True, check=True).stdout.decode()
    except (FileNotFoundError, subprocess.CalledProcessError) as e:
        print(f"openssl failed: {e}", file=sys.stderr)
        return 1
    priv_m = re.search(r"priv:\n((?:\s+[0-9a-f:]+\n)+)", text)
    pub_m = re.search(r"pub:\n((?:\s+[0-9a-f:]+\n)+)", text)
    if not priv_m or not pub_m:
        print("could not parse openssl output", file=sys.stderr)
        return 1
    priv = bytes(int(x, 16) for x in re.findall(r"[0-9a-f]{2}", priv_m.group(1)))
    pub = bytes(int(x, 16) for x in re.findall(r"[0-9a-f]{2}", pub_m.group(1)))
    assert len(priv) == 32 and len(pub) == 65 and pub[0] == 0x04, "unexpected key sizes"
    print(f"AURA_VAPID_PUBLIC_KEY={b64(pub)}")
    print(f"AURA_VAPID_PRIVATE_KEY={b64(priv)}")
    print("AURA_VAPID_SUBJECT=mailto:you@example.com   # change me", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
