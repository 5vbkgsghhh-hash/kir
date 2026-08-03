"""RSA signing for the desktop auto-update package — closes the unsigned-ZIP RCE.

The C# updater verifies an RSASSA-PKCS1-v1_5/SHA-256 detached signature before
extracting: the BUILD signs the zip with a private key held outside the repo,
and UpdateChecker verifies it against a PINNED public key.

RSA (not Ed25519) because .NET verifies RSA with the BUILT-IN System.Security.Cryptography
(RSACryptoServiceProvider, net48 + net8-windows) — no extra NuGet dependency in the plugin.

The client pins the public half (RSA .NET XML), downloads `latest.zip.sig`, and
calls rsa.VerifyData(zipBytes, "SHA256", sig). Fetching the key from the server
would defeat the purpose because an attacker could replace both.

Key lifecycle:
  - One-time: `python -m kukai.security.update_signing generate` → writes the private PEM
    (0600) and prints the public key (XML to embed in the client + base64 SPKI).
  - Build: `sign_file(zip_path)` writes `<zip>.sig` (base64 PKCS1v15-SHA256 signature).
"""
from __future__ import annotations

import base64
import os
from pathlib import Path
from typing import Optional

_KEY_SIZE = 2048

# Public half of the fleet trust anchor pinned in
# src/Kukai.Revit.Bridge/Config/UpdateChecker.cs. Verification code must use
# this value, not derive a public key by opening the signing private key on a
# production web host. The private key is needed only by release signing.
_FLEET_PUBLIC_KEY_B64 = (
    "MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAj97oZ8lkdPuOD7nFEQ/k"
    "HnJXmlCMqOQZduQJeAKnUKeGbncpZY+l8gLbdJAbsNcVYY5ogyhCwjZYd5rlRWzN"
    "1g0Q5Q+VCGUjluEyU8wAaRwU6sxX6l3Pspu2h9gL5WOHjgS1D3hqxiDpAWPgEyr"
    "hS2eTRtEkNMqE2YG+ZLtjr894/5BsOJPetktGaVUprLO1/v/I9MWKGwYmh85grz"
    "FSwWAmCkhjqlAawPTdC3JvP59PcyI+U6UEBxfI8Lac6ayHXPD2HVVKtUzRscq88"
    "MVHH0nPTzuX3tFHTuGXTIFE6B6KvrnnHe3ooTM4gbFCFuKhaArwYAm0qYA23B0q"
    "JYjnSQIDAQAB"
)


def _key_path() -> Path:
    p = os.environ.get("KUKAI_UPDATE_SIGNING_KEY_PATH", "")
    if p:
        return Path(p)
    return Path(__file__).resolve().parents[2] / "data" / "update_signing_key.pem"


def _load_private_key():
    """Load the RSA private key from the PEM path, or None if absent/unreadable."""
    path = _key_path()
    if not path.is_file():
        return None
    try:
        from cryptography.hazmat.primitives.serialization import load_pem_private_key
        return load_pem_private_key(path.read_bytes(), password=None)
    except Exception:
        return None


def generate_keypair(path: Optional[Path] = None) -> str:
    """Create an RSA-2048 private key PEM (0600) and return the public key (base64 SPKI).
    One-time operator action; the private key NEVER goes in the repo."""
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives import serialization

    path = path or _key_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    priv = rsa.generate_private_key(public_exponent=65537, key_size=_KEY_SIZE)
    pem = priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    path.write_bytes(pem)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return _public_b64(priv)


def _public_b64(priv) -> str:
    from cryptography.hazmat.primitives import serialization
    der = priv.public_key().public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return base64.b64encode(der).decode("ascii")


def _public_xml(priv) -> str:
    """The public key as .NET RSA XML (<RSAKeyValue><Modulus/><Exponent/></RSAKeyValue>) —
    what the C# client pins and loads via RSACryptoServiceProvider.FromXmlString."""
    nums = priv.public_key().public_numbers()
    n_len = (nums.n.bit_length() + 7) // 8
    e_len = (nums.e.bit_length() + 7) // 8
    mod = base64.b64encode(nums.n.to_bytes(n_len, "big")).decode("ascii")
    exp = base64.b64encode(nums.e.to_bytes(e_len, "big")).decode("ascii")
    return f"<RSAKeyValue><Modulus>{mod}</Modulus><Exponent>{exp}</Exponent></RSAKeyValue>"


def public_key_b64() -> Optional[str]:
    priv = _load_private_key()
    return _public_b64(priv) if priv is not None else None


def fleet_public_key_b64() -> str:
    """Return the client-pinned public verification key without reading secrets."""
    return _FLEET_PUBLIC_KEY_B64


def public_key_xml() -> Optional[str]:
    priv = _load_private_key()
    return _public_xml(priv) if priv is not None else None


def sign_file(data_path: Path) -> Optional[str]:
    """Sign ``data_path`` (RSASSA-PKCS1-v1_5 over SHA256) → write ``<data_path>.sig``
    (base64). Returns the public key (b64) on success, or None if no key is configured."""
    priv = _load_private_key()
    if priv is None:
        return None
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding
    sig = priv.sign(Path(data_path).read_bytes(), padding.PKCS1v15(), hashes.SHA256())
    Path(str(data_path) + ".sig").write_text(base64.b64encode(sig).decode("ascii"), encoding="utf-8")
    return _public_b64(priv)


def verify(data: bytes, sig_b64: str, pub_b64: str) -> bool:
    """Verify a detached base64 RSA-PKCS1v15-SHA256 signature against a base64 SPKI public
    key. Mirrors what the C# client does (RSACryptoServiceProvider.VerifyData ... "SHA256")."""
    try:
        from cryptography.hazmat.primitives.serialization import load_der_public_key
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import padding
        pub = load_der_public_key(base64.b64decode(pub_b64))
        pub.verify(base64.b64decode(sig_b64), data, padding.PKCS1v15(), hashes.SHA256())
        return True
    except Exception:
        return False


if __name__ == "__main__":  # `python -m kukai.security.update_signing generate`
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "generate":
        pub = generate_keypair()
        print("RSA signing key written to:", _key_path())
        print("PUBLIC KEY (base64 SPKI):", pub)
        print("PUBLIC KEY XML (pin this in the C# UpdateChecker):")
        print(public_key_xml())
    else:
        print("usage: python -m kukai.security.update_signing generate")
