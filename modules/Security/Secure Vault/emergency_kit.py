"""Export an offline emergency kit — encrypted backups + restore instructions."""

from __future__ import annotations

import os
from datetime import datetime

README = """Z's Multi Tool — Secure Vault Emergency Kit
Generated: {generated}

WHAT IS IN THIS FOLDER
----------------------
  vault_backup.enc          Encrypted password vault (import via Secure Vault)
  authenticator_backup.enc  Encrypted 2FA secrets (stored separately in the app)

KEEP THIS KIT SAFE
------------------
  - Store offline (USB, printout of master password procedure, safe deposit box)
  - Anyone with this kit AND your master password can access your accounts
  - Do NOT email these files or upload them to cloud storage unencrypted

HOW TO RESTORE (same computer)
------------------------------
  1. Open Z's Multi Tool → Secure Vault
  2. Unlock with your master password
  3. Click Import (📥) and choose vault_backup.enc
  4. For 2FA codes: contact support or restore totp.json from app data if needed
     (authenticator_backup.enc is a raw encrypted copy of totp.json for disaster recovery)

HOW TO RESTORE (new computer)
-----------------------------
  1. Install Z's Multi Tool and set the SAME master password you used before
  2. Import vault_backup.enc from this folder
  3. Copy authenticator_backup.enc contents only if you manually merge TOTP data

MASTER PASSWORD
---------------
  This kit does NOT contain your master password.
  You must remember it or store it separately from this folder.

If you lose your master password, these encrypted files cannot be recovered.
"""


def export_emergency_kit(folder: str, vault_service, totp_service) -> None:
    os.makedirs(folder, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    readme_path = os.path.join(folder, "README.txt")
    with open(readme_path, "w", encoding="utf-8") as f:
        f.write(README.format(generated=stamp))

    vault_path = os.path.join(folder, "vault_backup.enc")
    vault_service.export_encrypted(vault_path)

    totp_path = os.path.join(folder, "authenticator_backup.enc")
    totp_service.export_encrypted(totp_path)
