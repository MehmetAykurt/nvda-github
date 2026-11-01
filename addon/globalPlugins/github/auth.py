# Copyright (C) 2026 Mehmet Aykurt <m.aykurt38@gmail.com>
# Bu eklenti Mehmet Aykurt tarafından geliştirilmiştir.
# Lisans: GNU General Public License v2 (GPL-2.0)

"""GitHub device authorization, with bounded requests and cancellable polling.

HTTP payloads and credentials must never be included in exceptions or logs.
All URLs are fixed to GitHub; redirects are rejected to protect bearer tokens.
"""

import json
import math
import re
import socket
import time
from urllib import error, parse, request

from .application import USER_AGENT

DEVICE_URL = "https://github.com/login/device/code"
TOKEN_URL = "https://github.com/login/oauth/access_token"
VERIFY_URL = "https://github.com/login/device"
USER_URL = "https://api.github.com/user"
REPOS_URL = "https://api.github.com/user/repos"
CONTENT_URL = re.compile(r"https://api\.github\.com/repos/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/contents(?:/[A-Za-z0-9%._~/-]*)?")


class AuthError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


class _NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Transport:
    def __init__(self):
        self._opener = request.build_opener(_NoRedirect())

    def __call__(self, url, form=None, token=None, query=None):
        isContents = CONTENT_URL.fullmatch(url) is not None
        if url not in (DEVICE_URL, TOKEN_URL, USER_URL, REPOS_URL) and not isContents:
            raise AuthError("invalid_response")
        headers = {"Accept": "application/json", "User-Agent": USER_AGENT}
        data = None
        if form is not None:
            data = parse.urlencode(form).encode("ascii")
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        if token is not None:
            headers["Authorization"] = "Bearer " + token
        requestUrl = url + "?" + parse.urlencode(query) if query else url
        req = request.Request(requestUrl, data=data, headers=headers)
        try:
            limit = 4 * 1024 * 1024 if isContents else 1024 * 1024
            with self._opener.open(req, timeout=20) as response:
                data = response.read(limit + 1)
        except error.HTTPError as exc:
            if isContents and exc.code == 404:
                try:
                    empty = json.loads(exc.read(4096)).get("message") == "This repository is empty."
                except (ValueError, AttributeError):
                    empty = False
                raise AuthError("empty_repository" if empty else "not_found") from None
            if exc.code == 401:
                raise AuthError("unauthorized") from None
            if exc.code in (403, 429):
                raise AuthError("limited") from None
            raise AuthError("server_error") from None
        except (error.URLError, OSError, socket.timeout):
            raise AuthError("network") from None
        if len(data) > limit:
            raise AuthError("invalid_response")
        try:
            decoded = json.loads(data.decode("utf-8"))
        except (ValueError, UnicodeError):
            raise AuthError("invalid_response") from None
        if not isinstance(decoded, (dict, list) if isContents else (list if url == REPOS_URL else dict)):
            raise AuthError("invalid_response")
        return decoded


def checkCancelled(cancel):
    if cancel is not None and cancel.is_set():
        raise AuthError("cancelled")


def positiveNumber(value, maximum):
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 < value <= maximum:
        raise AuthError("invalid_response")
    return float(value)


def tokenBundle(response, clientId, now):
    token = response.get("access_token")
    if not isinstance(token, str) or not token or not token.isascii() or len(token) > 1024 or any(c.isspace() for c in token):
        raise AuthError("invalid_response")
    if not isinstance(response.get("token_type", "bearer"), str) or response.get("token_type", "bearer").lower() != "bearer":
        raise AuthError("invalid_response")
    result = {"access_token": token, "clientId": clientId}
    if "expires_in" in response:
        result["expiresAt"] = now + positiveNumber(response["expires_in"], 366 * 86400)
    if "refresh_token" in response:
        refresh = response["refresh_token"]
        if not isinstance(refresh, str) or not refresh or len(refresh) > 1024:
            raise AuthError("invalid_response")
        result["refresh_token"] = refresh
    if "refresh_token_expires_in" in response:
        result["refreshExpiresAt"] = now + positiveNumber(response["refresh_token_expires_in"], 10 * 366 * 86400)
    return result


class DeviceFlow:
    def __init__(self, transport=None, monotonic=time.monotonic, clock=time.time, wait=None):
        self.transport = transport or Transport()
        self.monotonic = monotonic
        self.clock = clock
        self.wait = wait or (lambda cancel, seconds: cancel.wait(seconds))

    def authorize(self, clientId, cancel, onCode):
        checkCancelled(cancel)
        # Request repo and delete_repo scopes to allow repository browsing, file modifications, and repository management.
        response = self.transport(DEVICE_URL, form={"client_id": clientId, "scope": "repo delete_repo"})
        self._checkError(response)
        deviceCode = response.get("device_code")
        userCode = response.get("user_code")
        if (not isinstance(deviceCode, str) or not deviceCode
                or not isinstance(userCode, str) or not userCode or len(userCode) > 32
                or response.get("verification_uri") != VERIFY_URL):
            raise AuthError("invalid_response")
        lifetime = positiveNumber(response.get("expires_in"), 3600)
        interval = positiveNumber(response.get("interval", 5), 3600)
        deadline = self.monotonic() + lifetime
        checkCancelled(cancel)
        onCode(userCode, lifetime)
        while True:
            remaining = deadline - self.monotonic()
            if remaining <= 0:
                raise AuthError("expired_token")
            if self.wait(cancel, min(interval, remaining)):
                raise AuthError("cancelled")
            checkCancelled(cancel)
            if self.monotonic() >= deadline:
                raise AuthError("expired_token")
            response = self.transport(TOKEN_URL, form={
                "client_id": clientId,
                "device_code": deviceCode,
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            })
            checkCancelled(cancel)
            if self.monotonic() >= deadline:
                raise AuthError("expired_token")
            errorCode = response.get("error")
            if errorCode == "authorization_pending":
                continue
            if errorCode == "slow_down":
                interval += 5
                continue
            self._checkError(response)
            return tokenBundle(response, clientId, self.clock())

    def profile(self, bundle, cancel):
        checkCancelled(cancel)
        profile = self.transport(USER_URL, token=bundle["access_token"])
        checkCancelled(cancel)
        login, userId = profile.get("login"), profile.get("id")
        if not isinstance(login, str) or not login or len(login) > 100 or type(userId) is not int or userId <= 0:
            raise AuthError("invalid_response")
        return {"login": login, "id": userId}

    def directoryContents(self, bundle, fullName, path, cancel, ref=None):
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", fullName):
            raise AuthError("invalid_response")
        if not isinstance(path, str) or (path and any(part in ("", ".", "..") for part in path.split("/"))):
            raise AuthError("invalid_response")
        url = "https://api.github.com/repos/" + fullName + "/contents"
        if path:
            url += "/" + parse.quote(path, safe="/")
        checkCancelled(cancel)
        try:
            query = {"ref": ref} if ref else None
            rows = self.transport(url, token=bundle["access_token"], query=query)
        except AuthError as exc:
            if exc.code == "empty_repository" and not path:
                return []
            raise
        checkCancelled(cancel)
        if not isinstance(rows, list):
            raise AuthError("not_directory")
        if len(rows) >= 1000:
            raise AuthError("directory_limit")
        result = []
        seen = set()
        for row in rows:
            if not isinstance(row, dict):
                raise AuthError("invalid_response")
            name, itemPath, kind = row.get("name"), row.get("path"), row.get("type")
            expected = path + "/" + name if path and isinstance(name, str) else name
            if (not isinstance(name, str) or not name or "/" in name or name in (".", "..")
                    or itemPath != expected or itemPath in seen
                    or kind not in ("dir", "file", "symlink", "submodule")):
                raise AuthError("invalid_response")
            seen.add(itemPath)
            # GitHub may label a submodule as a file for backward compatibility.
            if row.get("submodule_git_url"):
                kind = "submodule"
            entry = {"name": name, "path": itemPath, "type": kind}
            if isinstance(row.get("sha"), str) and row["sha"]:
                entry["sha"] = row["sha"]
            if type(row.get("size")) is int and row["size"] >= 0:
                entry["size"] = row["size"]
            result.append(entry)
        return sorted(result, key=lambda row: (row["type"] != "dir", row["name"].casefold()))

    def repositories(self, bundle, cancel):
        repositories = {}
        page = 1
        while True:
            checkCancelled(cancel)
            rows = self.transport(REPOS_URL, token=bundle["access_token"], query={
                "per_page": 100, "page": page, "sort": "full_name", "direction": "asc",
            })
            checkCancelled(cancel)
            if not isinstance(rows, list) or len(rows) > 100:
                raise AuthError("invalid_response")
            previousCount = len(repositories)
            for row in rows:
                if (not isinstance(row, dict) or type(row.get("id")) is not int
                        or row["id"] <= 0 or not isinstance(row.get("full_name"), str)
                        or not row["full_name"] or len(row["full_name"]) > 300):
                    raise AuthError("invalid_response")
                repo_entry = {
                    "id": row["id"],
                    "full_name": row["full_name"],
                    "private": bool(row.get("private", False)),
                    "archived": bool(row.get("archived", False)),
                    "description": row.get("description") if isinstance(row.get("description"), str) else "",
                }
                if isinstance(row.get("default_branch"), str) and row["default_branch"]:
                    repo_entry["default_branch"] = row["default_branch"]
                repositories[row["id"]] = repo_entry
            if len(rows) < 100:
                break
            if len(repositories) == previousCount:
                raise AuthError("invalid_response")
            page += 1
        return sorted(repositories.values(), key=lambda row: row["full_name"].casefold())

    def refresh(self, bundle):
        client_id = bundle.get("clientId")
        if (not isinstance(client_id, str) or not client_id.strip()
                or not bundle.get("refresh_token")
                or bundle.get("refreshExpiresAt", self.clock() + 1) <= self.clock()):
            raise AuthError("reauthorize")
        response = self.transport(TOKEN_URL, form={
            "client_id": client_id,
            "refresh_token": bundle["refresh_token"],
            "grant_type": "refresh_token",
        })
        self._checkError(response)
        return tokenBundle(response, client_id, self.clock())

    @staticmethod
    def _checkError(response):
        code = response.get("error")
        if code:
            known = {"access_denied", "expired_token", "device_flow_disabled",
                     "incorrect_client_credentials", "bad_refresh_token"}
            raise AuthError(code if code in known else "authorization_failed")
