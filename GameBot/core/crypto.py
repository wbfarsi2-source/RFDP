from __future__ import annotations

import base64
import hashlib
import json
import os
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from core.config import settings


class CredentialVault:
    VERSION = 1

    def __init__(self, master_key: str | None = None) -> None:
        source = (master_key if master_key is not None else settings.master_key).strip()
        if not source:
            raise RuntimeError("MASTER_KEY is empty. Generate it before storing credentials.")
        self._key = hashlib.sha256(source.encode("utf-8")).digest()

    def encrypt(self, data: dict[str, Any]) -> str:
        nonce = os.urandom(12)
        plaintext = json.dumps(data, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        encrypted = AESGCM(self._key).encrypt(nonce, plaintext, b"gamebot-platform")
        envelope = {
            "v": self.VERSION,
            "n": base64.urlsafe_b64encode(nonce).decode("ascii"),
            "c": base64.urlsafe_b64encode(encrypted).decode("ascii"),
        }
        return json.dumps(envelope, separators=(",", ":"))

    def decrypt(self, token: str) -> dict[str, Any]:
        envelope = json.loads(token)
        nonce = base64.urlsafe_b64decode(envelope["n"])
        ciphertext = base64.urlsafe_b64decode(envelope["c"])
        plaintext = AESGCM(self._key).decrypt(nonce, ciphertext, b"gamebot-platform")
        value = json.loads(plaintext.decode("utf-8"))
        if not isinstance(value, dict):
            raise ValueError("Credential payload must be an object.")
        return value
