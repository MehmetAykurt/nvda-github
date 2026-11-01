# Copyright (C) 2026 Mehmet Aykurt <m.aykurt38@gmail.com>
# Bu eklenti Mehmet Aykurt tarafından geliştirilmiştir.
# Lisans: GNU General Public License v2 (GPL-2.0)

"""Keep all add-on settings below <NVDA configuration>/github.

Only application identifiers and account metadata belong here. Credentials
are stored separately in Windows Credential Manager.
"""

import json
import os
from pathlib import Path
import re
import tempfile

from .application import CLIENT_ID


class SettingsError(ValueError):
    pass


class SettingsStore:
    def __init__(self, configPath):
        self.directory = Path(configPath) / "github"
        self.path = self.directory / "settings.json"

    def load(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        try:
            with self.path.open("x", encoding="utf-8") as stream:
                json.dump({"schemaVersion": 1, "accounts": []}, stream, indent=2)
                stream.write("\n")
        except FileExistsError:
            pass
        try:
            with self.path.open(encoding="utf-8") as stream:
                settings = json.load(stream)
        except (ValueError, UnicodeError) as error:
            raise SettingsError("Invalid GitHub settings") from error
        if not isinstance(settings, dict) or type(settings.get("schemaVersion")) is not int:
            raise SettingsError("Invalid settings schema")
        if settings["schemaVersion"] != 1 or not isinstance(settings.get("accounts"), list):
            raise SettingsError("Unsupported settings schema")
        if any(not isinstance(account, dict) or not account.get("login")
               or not isinstance(account["login"], str) for account in settings["accounts"]):
            raise SettingsError("Invalid account metadata")
        if not isinstance(settings.get("clientId", ""), str):
            raise SettingsError("Invalid application identifier")
        for account in settings["accounts"]:
            reference = account.get("credentialId")
            if reference is not None and (not isinstance(reference, str)
                                         or not re.fullmatch(r"[0-9a-f]{32}", reference)):
                raise SettingsError("Invalid credential reference")
        return settings

    def hasAccounts(self):
        return bool(self.load()["accounts"])

    def getAccount(self):
        accounts = self.load()["accounts"]
        return accounts[0] if accounts else None

    def getClientId(self):
        settings = self.load()
        return settings.get("clientId") or CLIENT_ID

    def setClientId(self, clientId):
        if (not re.fullmatch(r"[A-Za-z0-9_.-]{6,100}", clientId)
                or clientId.startswith(("ghp_", "gho_", "ghu_", "ghs_", "ghr_", "github_pat_"))
                or re.fullmatch(r"[0-9a-fA-F]{40}", clientId)):
            raise SettingsError("Invalid application identifier")
        settings = self.load()
        settings["clientId"] = clientId
        self._write(settings)

    def setAccount(self, account):
        settings = self.load()
        # Keep the file free of secrets even if a caller passes extra fields.
        settings["accounts"] = [] if account is None else [{
            "login": account["login"],
            "id": account["id"],
            "credentialId": account["credentialId"],
        }]
        self._write(settings)

    def _write(self, settings):
        path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=self.directory,
                prefix="settings-", suffix=".tmp", delete=False,
            ) as stream:
                path = Path(stream.name)
                json.dump(settings, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(path, self.path)
        finally:
            if path is not None:
                path.unlink(missing_ok=True)
