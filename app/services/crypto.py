"""Encrypt OAuth tokens before they go into Firestore (Fernet = AES-128-CBC + HMAC-SHA256)."""
import json

from cryptography.fernet import Fernet, InvalidToken

HOW_TO_MAKE_KEY = (
    "FERNET_KEY is not set. Make one with:  "
    "python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\"  "
    "and put it in your .env file (keep it secret; losing it means reconnecting every channel)."
)


class CipherNotConfigured(RuntimeError):
    pass


class TokenDecryptError(Exception):
    pass


class TokenCipher:
    def __init__(self, key: str):
        if not key:
            raise CipherNotConfigured(HOW_TO_MAKE_KEY)
        try:
            self._f = Fernet(key.encode())
        except ValueError as e:
            raise CipherNotConfigured("FERNET_KEY is not a valid key. " + HOW_TO_MAKE_KEY) from e

    def encrypt(self, data: dict) -> str:
        return self._f.encrypt(json.dumps(data).encode()).decode()

    def decrypt(self, blob: str) -> dict:
        try:
            return json.loads(self._f.decrypt(blob.encode()))
        except (InvalidToken, ValueError) as e:
            raise TokenDecryptError("Stored token can't be decrypted (was FERNET_KEY changed?)") from e
