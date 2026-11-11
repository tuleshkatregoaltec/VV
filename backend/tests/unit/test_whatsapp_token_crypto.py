import pytest
from cryptography.fernet import Fernet

from app.config import settings
from app.whatsapp import token_crypto


def config(**update):
    return settings.model_copy(update=update)


def test_token_is_stored_encrypted_and_decrypts_with_the_configured_key():
    key = Fernet.generate_key().decode()
    c = config(ENVIRONMENT="staging", WHATSAPP_TOKEN_ENCRYPTION_KEY=key)
    stored = token_crypto.encrypt_token("EAAG-business-token", c)
    assert stored != "EAAG-business-token"
    assert "EAAG-business-token" not in stored
    assert token_crypto.decrypt_token(stored, c) == "EAAG-business-token"
    other = config(
        ENVIRONMENT="staging", WHATSAPP_TOKEN_ENCRYPTION_KEY=Fernet.generate_key().decode()
    )
    with pytest.raises(token_crypto.TokenEncryptionUnavailable):
        token_crypto.decrypt_token(stored, other)


@pytest.mark.parametrize("environment", ["staging", "production"])
def test_missing_key_fails_closed_outside_local(environment):
    c = config(ENVIRONMENT=environment, WHATSAPP_TOKEN_ENCRYPTION_KEY=None)
    assert not token_crypto.available(c)
    with pytest.raises(token_crypto.TokenEncryptionUnavailable):
        token_crypto.encrypt_token("token", c)
    with pytest.raises(token_crypto.TokenEncryptionUnavailable):
        token_crypto.decrypt_token("anything", c)


def test_invalid_key_fails_closed():
    c = config(ENVIRONMENT="staging", WHATSAPP_TOKEN_ENCRYPTION_KEY="not-a-fernet-key")
    assert not token_crypto.available(c)
    with pytest.raises(token_crypto.TokenEncryptionUnavailable):
        token_crypto.encrypt_token("token", c)


def test_local_development_derives_a_key_without_configuration():
    c = config(ENVIRONMENT="local", WHATSAPP_TOKEN_ENCRYPTION_KEY=None)
    stored = token_crypto.encrypt_token("token", c)
    assert stored != "token"
    assert token_crypto.decrypt_token(stored, c) == "token"


def test_key_rotation_keeps_old_tokens_readable():
    old, new = Fernet.generate_key().decode(), Fernet.generate_key().decode()
    stored = token_crypto.encrypt_token(
        "token", config(ENVIRONMENT="staging", WHATSAPP_TOKEN_ENCRYPTION_KEY=old)
    )
    rotated = config(ENVIRONMENT="staging", WHATSAPP_TOKEN_ENCRYPTION_KEY=f"{new},{old}")
    assert token_crypto.decrypt_token(stored, rotated) == "token"
    fresh = token_crypto.encrypt_token("token", rotated)
    assert (
        token_crypto.decrypt_token(
            fresh, config(ENVIRONMENT="staging", WHATSAPP_TOKEN_ENCRYPTION_KEY=new)
        )
        == "token"
    )
