"""At-rest encryption for per-agent WhatsApp business tokens. Fails closed off local."""

import base64
import hashlib
import logging

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

logger = logging.getLogger(__name__)
_warned_local_key = False


class TokenEncryptionUnavailable(RuntimeError):
    """No usable key, or a stored value this key set cannot read. Never carries secrets."""


def _cipher(config) -> MultiFernet:
    raw = config.WHATSAPP_TOKEN_ENCRYPTION_KEY
    if not raw:
        if config.ENVIRONMENT != "local":
            raise TokenEncryptionUnavailable("WHATSAPP_TOKEN_ENCRYPTION_KEY is not configured")
        global _warned_local_key
        if not _warned_local_key:
            _warned_local_key = True
            logger.warning("WHATSAPP_TOKEN_ENCRYPTION_KEY is unset; using a local development key")
        digest = hashlib.sha256(("vv-local-whatsapp:" + config.SESSION_SECRET).encode()).digest()
        return MultiFernet([Fernet(base64.urlsafe_b64encode(digest))])
    try:
        return MultiFernet([Fernet(key.strip().encode()) for key in raw.split(",") if key.strip()])
    except (ValueError, TypeError):
        raise TokenEncryptionUnavailable("WHATSAPP_TOKEN_ENCRYPTION_KEY is invalid") from None


def available(config) -> bool:
    try:
        _cipher(config)
    except TokenEncryptionUnavailable:
        return False
    return True


def encrypt_token(token: str, config) -> str:
    return _cipher(config).encrypt(token.encode()).decode()


def decrypt_token(stored: str, config) -> str:
    cipher = _cipher(config)
    try:
        return cipher.decrypt(stored.encode()).decode()
    except (InvalidToken, ValueError, TypeError):
        raise TokenEncryptionUnavailable("Stored WhatsApp token cannot be decrypted") from None
