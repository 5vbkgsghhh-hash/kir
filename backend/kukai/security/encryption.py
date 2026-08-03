"""Session-level AES-256 encryption for code transport.

Encrypts C# code before sending to the client over WebSocket.
Each WebSocket session gets its own AES key, exchanged at connection time.

Security: Encrypt-then-MAC (AES-256-CBC + HMAC-SHA256).
Format: base64(HMAC[32] + IV[16] + ciphertext)

The HMAC covers IV+ciphertext to prevent tampering and padding oracle attacks.
"""

from __future__ import annotations

import base64
import hashlib
import hmac as hmac_module
import os

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import padding


class SessionEncryption:
    """AES-256-CBC encryption with HMAC-SHA256 for per-session code transport.

    Encrypt-then-MAC construction:
    - Encrypt plaintext with AES-256-CBC + PKCS7 padding
    - Compute HMAC-SHA256 over (IV + ciphertext) using the same key
    - Output: base64(HMAC[32] + IV[16] + ciphertext)

    On decrypt:
    - Extract HMAC, IV, ciphertext from payload
    - Verify HMAC (constant-time comparison)
    - Only then decrypt

    This prevents padding oracle attacks and detects any tampering.
    """

    IV_SIZE = 16     # 128 bits, standard for AES-CBC
    KEY_SIZE = 32    # 256 bits
    HMAC_SIZE = 32   # SHA-256 output

    @staticmethod
    def generate_key() -> bytes:
        """Generate a random AES-256 key (32 bytes).

        Returns:
            32-byte key suitable for AES-256-CBC + HMAC.
        """
        return os.urandom(32)

    @staticmethod
    def _derive_hmac_key(encryption_key: bytes) -> bytes:
        """Derive a separate HMAC key from the encryption key.

        Uses HKDF-like derivation: SHA-256(key + b"hmac-key") to ensure
        encryption and authentication use different keys.
        """
        return hashlib.sha256(encryption_key + b"hmac-key").digest()

    @staticmethod
    def encrypt(plaintext: str, key: bytes) -> str:
        """Encrypt a string with AES-256-CBC + HMAC-SHA256 (encrypt-then-MAC).

        Args:
            plaintext: UTF-8 string to encrypt.
            key: 32-byte AES key.

        Returns:
            Base64-encoded string: HMAC[32] + IV[16] + ciphertext.
        """
        iv = os.urandom(SessionEncryption.IV_SIZE)
        padder = padding.PKCS7(128).padder()
        data = padder.update(plaintext.encode("utf-8")) + padder.finalize()
        cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
        encryptor = cipher.encryptor()
        ciphertext = encryptor.update(data) + encryptor.finalize()

        # Compute HMAC over IV + ciphertext
        hmac_key = SessionEncryption._derive_hmac_key(key)
        mac = hmac_module.new(hmac_key, iv + ciphertext, hashlib.sha256).digest()

        # Format: HMAC[32] + IV[16] + ciphertext
        return base64.b64encode(mac + iv + ciphertext).decode("ascii")

    @staticmethod
    def decrypt(ciphertext_b64: str, key: bytes) -> str:
        """Decrypt a base64-encoded AES-256-CBC message with HMAC verification.

        Verifies HMAC-SHA256 before decrypting to prevent tampering
        and padding oracle attacks.

        Args:
            ciphertext_b64: Base64 string produced by encrypt().
            key: 32-byte AES key (same key used for encryption).

        Returns:
            Decrypted UTF-8 string.

        Raises:
            ValueError: If HMAC verification fails, input is malformed,
                       or padding is invalid.
        """
        raw = base64.b64decode(ciphertext_b64)
        min_size = SessionEncryption.HMAC_SIZE + SessionEncryption.IV_SIZE + 1
        if len(raw) < min_size:
            raise ValueError("Ciphertext too short")

        # Extract HMAC, IV, ciphertext
        received_mac = raw[:SessionEncryption.HMAC_SIZE]
        iv = raw[SessionEncryption.HMAC_SIZE:SessionEncryption.HMAC_SIZE + SessionEncryption.IV_SIZE]
        ciphertext = raw[SessionEncryption.HMAC_SIZE + SessionEncryption.IV_SIZE:]

        # Verify HMAC first (constant-time comparison)
        hmac_key = SessionEncryption._derive_hmac_key(key)
        expected_mac = hmac_module.new(hmac_key, iv + ciphertext, hashlib.sha256).digest()
        if not hmac_module.compare_digest(received_mac, expected_mac):
            raise ValueError("HMAC verification failed — data may have been tampered with")

        # HMAC verified — safe to decrypt
        cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
        decryptor = cipher.decryptor()
        padded = decryptor.update(ciphertext) + decryptor.finalize()
        unpadder = padding.PKCS7(128).unpadder()
        data = unpadder.update(padded) + unpadder.finalize()
        return data.decode("utf-8")
