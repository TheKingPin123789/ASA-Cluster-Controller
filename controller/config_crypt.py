"""
config_crypt.py — Encrypt/decrypt sensitive config.ini values.

Sensitive fields (rcon_password, secret_key, webhook_url, bot_token) are stored
as  ENC:<fernet-token>  so they cannot be read by opening config.ini in a text editor.

The encryption key is derived from the Windows Machine GUID, which is unique per
machine and stored in the registry. This means the encrypted values only work on
the machine that wrote them — copying config.ini to another PC won't expose secrets.

All four files that read config.ini (asa_cluster_controller.py, dashboard.py,
setup_wizard.py, launch_map.py) import decrypt_cfg_value() from here.
setup_wizard.py also imports encrypt_cfg_value() when writing sensitive fields.
"""

import base64
import hashlib
import logging

# Fields that should be encrypted when written and decrypted when read
SENSITIVE_KEYS = {"rcon_password", "secret_key", "webhook_url", "bot_token"}

_log = logging.getLogger(__name__)

_ENC_PREFIX = "ENC:"


def _get_fernet():
    """Return a Fernet instance keyed to this machine's GUID."""
    from cryptography.fernet import Fernet
    try:
        import winreg
        reg = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                             r"SOFTWARE\Microsoft\Cryptography")
        machine_guid, _ = winreg.QueryValueEx(reg, "MachineGuid")
        winreg.CloseKey(reg)
    except OSError as exc:
        # Registry unavailable (non-Windows or restricted permissions) — fall back
        # to hostname. Less unique, but still better than plaintext.
        _log.debug("Could not read MachineGuid from registry (%s); falling back to hostname.", exc)
        import socket
        machine_guid = socket.gethostname()
    raw_key = hashlib.sha256(machine_guid.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(raw_key))


def encrypt_cfg_value(plaintext: str) -> str:
    """Return ENC:<token> for a plaintext config value."""
    if not plaintext or plaintext.startswith(_ENC_PREFIX):
        return plaintext  # already encrypted or empty
    token = _get_fernet().encrypt(plaintext.encode()).decode()
    return _ENC_PREFIX + token


def decrypt_cfg_value(value: str) -> str:
    """Return the plaintext for an ENC:<token> value, or the value unchanged."""
    if not value or not value.startswith(_ENC_PREFIX):
        return value  # plaintext or empty — pass through
    try:
        return _get_fernet().decrypt(value[len(_ENC_PREFIX):].encode()).decode()
    except Exception as exc:
        # Decryption failed — likely config.ini was copied from another machine.
        # Return empty string so the caller gets a clear auth failure rather than
        # silently using the "ENC:..." string as a literal password.
        _log.warning(
            "Failed to decrypt a config value (%s). "
            "If you copied config.ini from another machine, re-run setup_wizard.py.",
            exc,
        )
        return ""


def decrypt_config(cfg) -> None:
    """Decrypt all sensitive fields in a ConfigParser object in-place.
    Call this once after cfg.read() before using any values."""
    for section in cfg.sections():
        for key in cfg.options(section):
            if key in SENSITIVE_KEYS:
                raw = cfg.get(section, key, fallback="")
                if raw.startswith(_ENC_PREFIX):
                    cfg.set(section, key, decrypt_cfg_value(raw))
