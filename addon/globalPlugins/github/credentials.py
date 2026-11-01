# Copyright (C) 2026 Mehmet Aykurt <m.aykurt38@gmail.com>
# Bu eklenti Mehmet Aykurt tarafından geliştirilmiştir.
# Lisans: GNU General Public License v2 (GPL-2.0)

"""Windows-only generic credentials. No secret is written to add-on files."""

import ctypes
from ctypes import wintypes
import hashlib
import json
from pathlib import Path
import re


class CredentialError(OSError):
    pass


class _Credential(ctypes.Structure):
    _fields_ = [
        ("Flags", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR),
        ("Comment", wintypes.LPWSTR),
        ("LastWritten", wintypes.FILETIME),
        ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.POINTER(wintypes.BYTE)),
        ("Persist", wintypes.DWORD),
        ("AttributeCount", wintypes.DWORD),
        ("Attributes", ctypes.c_void_p),
        ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    ]


class CredentialStore:
    def __init__(self, configPath):
        identity = str(Path(configPath).resolve()).casefold().encode("utf-8")
        self._prefix = "NVDA/GitHub/" + hashlib.sha256(identity).hexdigest()[:24] + "/"
        self._api = ctypes.WinDLL("Advapi32.dll", use_last_error=True)
        pointer = ctypes.POINTER(_Credential)
        self._api.CredWriteW.argtypes = [pointer, wintypes.DWORD]
        self._api.CredWriteW.restype = wintypes.BOOL
        self._api.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(pointer)]
        self._api.CredReadW.restype = wintypes.BOOL
        self._api.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
        self._api.CredDeleteW.restype = wintypes.BOOL
        self._api.CredFree.argtypes = [ctypes.c_void_p]
        self._api.CredFree.restype = None

    def _target(self, reference):
        if not re.fullmatch(r"[0-9a-f]{32}", reference):
            raise CredentialError("Invalid credential reference")
        return self._prefix + reference

    def write(self, reference, bundle):
        data = json.dumps(bundle, separators=(",", ":")).encode("utf-8")
        if len(data) > 2560:
            raise CredentialError("Credential exceeds Windows storage limit")
        buffer = (wintypes.BYTE * len(data)).from_buffer_copy(data)
        credential = _Credential()
        credential.Type = 1  # CRED_TYPE_GENERIC
        credential.TargetName = self._target(reference)
        credential.CredentialBlobSize = len(data)
        credential.CredentialBlob = ctypes.cast(buffer, ctypes.POINTER(wintypes.BYTE))
        credential.Persist = 2  # CRED_PERSIST_LOCAL_MACHINE: same Windows user, later logons.
        credential.UserName = "GitHub"
        try:
            if not self._api.CredWriteW(ctypes.byref(credential), 0):
                raise CredentialError(ctypes.get_last_error(), "Windows credential write failed")
        finally:
            ctypes.memset(buffer, 0, len(data))

    def read(self, reference):
        pointer = ctypes.POINTER(_Credential)()
        if not self._api.CredReadW(self._target(reference), 1, 0, ctypes.byref(pointer)):
            code = ctypes.get_last_error()
            if code == 1168:  # ERROR_NOT_FOUND
                return None
            raise CredentialError(code, "Windows credential read failed")
        try:
            data = ctypes.string_at(pointer.contents.CredentialBlob, pointer.contents.CredentialBlobSize)
            bundle = json.loads(data.decode("utf-8"))
            if not isinstance(bundle, dict) or not isinstance(bundle.get("access_token"), str):
                raise ValueError("Invalid credential")
            return bundle
        except (ValueError, UnicodeError) as error:
            raise CredentialError("Invalid saved credential") from error
        finally:
            ctypes.memset(pointer.contents.CredentialBlob, 0, pointer.contents.CredentialBlobSize)
            self._api.CredFree(pointer)

    def delete(self, reference):
        if not self._api.CredDeleteW(self._target(reference), 1, 0):
            code = ctypes.get_last_error()
            if code != 1168:
                raise CredentialError(code, "Windows credential delete failed")
