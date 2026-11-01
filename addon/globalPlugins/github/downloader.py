# Copyright (C) 2026 Mehmet Aykurt <m.aykurt38@gmail.com>
# Bu eklenti Mehmet Aykurt tarafından geliştirilmiştir.
# Lisans: GNU General Public License v2 (GPL-2.0)

"""Secure download operations for GitHub repositories, directories, and files."""

import hashlib
import json
import os
import re
import socket
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile

from .application import USER_AGENT
from .auth import AuthError, checkCancelled


def _check_cancelled(cancel):
    if cancel is not None:
        checkCancelled(cancel)

ALLOWED_REDIRECT_DOMAINS = (
    "api.github.com",
    "codeload.github.com",
    "github.com",
    "raw.githubusercontent.com",
    "objects.githubusercontent.com",
    "release-assets.githubusercontent.com",
)

CHUNK_SIZE = 64 * 1024


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Allows redirects only to trusted GitHub CDN and storage domains."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parsed = urllib.parse.urlsplit(newurl)
        if parsed.scheme != "https":
            return None
        hostname = (parsed.hostname or "").lower()
        if not any(hostname == domain or hostname.endswith("." + domain) for domain in ALLOWED_REDIRECT_DOMAINS):
            return None
        new_req = urllib.request.Request(
            newurl,
            headers=dict(req.headers),
            origin_req_host=req.origin_req_host,
            unverifiable=req.unverifiable,
        )
        # Drop bearer token when redirecting away from api.github.com
        if hostname != "api.github.com":
            new_req.headers.pop("Authorization", None)
            new_req.headers.pop("authorization", None)
            if hasattr(new_req, "unredirected_hdrs"):
                new_req.unredirected_hdrs.pop("Authorization", None)
                new_req.unredirected_hdrs.pop("authorization", None)
        return new_req


def _build_opener():
    return urllib.request.build_opener(_SafeRedirectHandler())


def _stream_to_file(opener, req, target_path, cancel=None):
    _check_cancelled(cancel)
    target_dir = os.path.dirname(os.path.abspath(target_path))
    os.makedirs(target_dir, exist_ok=True)

    fd, temp_path = tempfile.mkstemp(dir=target_dir, prefix="nvda_gh_dl_")
    try:
        try:
            max_total_bytes = 500 * 1024 * 1024
            total_written = 0
            with opener.open(req, timeout=30) as response:
                with os.fdopen(fd, "wb") as f_out:
                    fd = None  # file descriptor is now owned by f_out
                    while True:
                        _check_cancelled(cancel)
                        chunk = response.read(CHUNK_SIZE)
                        if not chunk:
                            break
                        total_written += len(chunk)
                        if total_written > max_total_bytes:
                            raise AuthError("file_too_large")
                        f_out.write(chunk)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raise AuthError("not_found") from None
            if exc.code == 401:
                raise AuthError("unauthorized") from None
            if exc.code in (403, 429):
                raise AuthError("limited") from None
            raise AuthError("server_error") from None
        except (urllib.error.URLError, OSError, socket.timeout):
            raise AuthError("network") from None

        _check_cancelled(cancel)
        if os.path.exists(target_path):
            os.replace(temp_path, target_path)
        else:
            os.rename(temp_path, target_path)
        return target_path
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass



def downloadRepositoryZip(token, full_name, target_path, cancel=None, ref=None):
    """Downloads the entire repository archive (default branch or specified ref) as a ZIP file."""
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", full_name):
        raise AuthError("invalid_response")
    url = f"https://api.github.com/repos/{full_name}/zipball"
    if ref:
        url += "/" + urllib.parse.quote(ref, safe="/")
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/vnd.github.v3+json",
        "Authorization": f"Bearer {token}",
    }
    req = urllib.request.Request(url, headers=headers)
    opener = _build_opener()
    return _stream_to_file(opener, req, target_path, cancel=cancel)


def downloadFile(token, full_name, file_path, target_path, cancel=None, ref=None):
    """Downloads a single file from the repository to the local path."""
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", full_name):
        raise AuthError("invalid_response")
    quoted_path = urllib.parse.quote(file_path.strip("/"), safe="/")
    url = f"https://api.github.com/repos/{full_name}/contents/{quoted_path}"
    if ref:
        url += "?ref=" + urllib.parse.quote(ref, safe="")
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/vnd.github.raw+json",
        "Authorization": f"Bearer {token}",
    }
    req = urllib.request.Request(url, headers=headers)
    opener = _build_opener()
    return _stream_to_file(opener, req, target_path, cancel=cancel)


def downloadReleaseAsset(token, full_name, asset_id, target_path, download_url="", cancel=None):
    """Downloads a release binary asset (works for both public and private repositories) atomically."""
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", full_name):
        raise AuthError("invalid_response")
    _check_cancelled(cancel)

    if asset_id and int(asset_id) > 0:
        url = f"https://api.github.com/repos/{full_name}/releases/assets/{int(asset_id)}"
        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "application/octet-stream",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
    elif download_url:
        parsed = urllib.parse.urlsplit(download_url)
        hostname = (parsed.hostname or "").lower()
        if parsed.scheme != "https" or not any(
            hostname == domain or hostname.endswith("." + domain)
            for domain in ALLOWED_REDIRECT_DOMAINS
        ):
            raise AuthError("invalid_response")
        url = download_url
        headers = {"User-Agent": USER_AGENT}
        if token and hostname == "api.github.com":
            headers["Authorization"] = f"Bearer {token}"
    else:
        raise AuthError("invalid_response")

    req = urllib.request.Request(url, headers=headers)
    opener = _build_opener()
    return _stream_to_file(opener, req, target_path, cancel=cancel)


def _stream_to_sha256(opener, req, cancel=None):
    _check_cancelled(cancel)
    hasher = hashlib.sha256()
    max_total_bytes = 500 * 1024 * 1024
    total_read = 0
    try:
        with opener.open(req, timeout=30) as response:
            while True:
                _check_cancelled(cancel)
                chunk = response.read(CHUNK_SIZE)
                if not chunk:
                    break
                total_read += len(chunk)
                if total_read > max_total_bytes:
                    raise AuthError("file_too_large")
                hasher.update(chunk)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise AuthError("not_found") from None
        if exc.code == 401:
            raise AuthError("unauthorized") from None
        if exc.code in (403, 429):
            raise AuthError("limited") from None
        raise AuthError("server_error") from None
    except (urllib.error.URLError, OSError, socket.timeout):
        raise AuthError("network") from None

    _check_cancelled(cancel)
    return hasher.hexdigest()


def computeReleaseAssetSha256(token, full_name, asset_id, download_url="", cancel=None):
    """Streams a release binary asset directly into hashlib.sha256 and returns the hex digest."""
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", full_name):
        raise AuthError("invalid_response")
    _check_cancelled(cancel)

    if asset_id and int(asset_id) > 0:
        url = f"https://api.github.com/repos/{full_name}/releases/assets/{int(asset_id)}"
        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "application/octet-stream",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
    elif download_url:
        parsed = urllib.parse.urlsplit(download_url)
        hostname = (parsed.hostname or "").lower()
        if parsed.scheme != "https" or not any(
            hostname == domain or hostname.endswith("." + domain)
            for domain in ALLOWED_REDIRECT_DOMAINS
        ):
            raise AuthError("invalid_response")
        url = download_url
        headers = {"User-Agent": USER_AGENT}
        if token and hostname == "api.github.com":
            headers["Authorization"] = f"Bearer {token}"
    else:
        raise AuthError("invalid_response")

    req = urllib.request.Request(url, headers=headers)
    opener = _build_opener()
    return _stream_to_sha256(opener, req, cancel=cancel)


def downloadFolderAsZip(flow, bundle, full_name, folder_path, target_zip_path, cancel=None, ref=None):
    """Recursively lists all files in folder_path and packages them into a local ZIP archive."""
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", full_name):
        raise AuthError("invalid_response")
    _check_cancelled(cancel)

    target_dir = os.path.dirname(os.path.abspath(target_zip_path))
    os.makedirs(target_dir, exist_ok=True)

    files_to_download = []
    base_folder = folder_path.strip("/")
    queue = [base_folder]

    while queue:
        _check_cancelled(cancel)
        current_dir = queue.pop(0)
        items = flow.directoryContents(bundle, full_name, current_dir, cancel, ref=ref)
        for item in items:
            _check_cancelled(cancel)
            if item["type"] == "dir":
                queue.append(item["path"])
            elif item["type"] == "file":
                rel = os.path.relpath(item["path"], base_folder) if base_folder else item["path"]
                rel = rel.replace("\\", "/")
                files_to_download.append((item["path"], rel))

    _check_cancelled(cancel)
    fd, temp_zip = tempfile.mkstemp(dir=target_dir, prefix="nvda_gh_zip_")
    os.close(fd)

    max_total_bytes = 500 * 1024 * 1024
    total_written = 0
    opener = _build_opener()
    try:
        with zipfile.ZipFile(temp_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for repo_path, rel_in_zip in files_to_download:
                _check_cancelled(cancel)
                quoted_path = urllib.parse.quote(repo_path, safe="/")
                url = f"https://api.github.com/repos/{full_name}/contents/{quoted_path}"
                if ref:
                    url += "?ref=" + urllib.parse.quote(ref, safe="")
                headers = {
                    "User-Agent": USER_AGENT,
                    "Accept": "application/vnd.github.raw+json",
                    "Authorization": f"Bearer {bundle['access_token']}",
                }
                req = urllib.request.Request(url, headers=headers)
                try:
                    with opener.open(req, timeout=30) as resp:
                        with zf.open(rel_in_zip, "w") as member:
                            while True:
                                _check_cancelled(cancel)
                                chunk = resp.read(CHUNK_SIZE)
                                if not chunk:
                                    break
                                total_written += len(chunk)
                                if total_written > max_total_bytes:
                                    raise AuthError("file_too_large")
                                member.write(chunk)
                except urllib.error.HTTPError as exc:
                    if exc.code == 404:
                        raise AuthError("not_found") from None
                    if exc.code == 401:
                        raise AuthError("unauthorized") from None
                    if exc.code in (403, 429):
                        raise AuthError("limited") from None
                    raise AuthError("server_error") from None
                except (urllib.error.URLError, OSError, socket.timeout):
                    raise AuthError("network") from None

        _check_cancelled(cancel)
        if os.path.exists(target_zip_path):
            os.replace(temp_zip, target_zip_path)
        else:
            os.rename(temp_zip, target_zip_path)
        return target_zip_path
    finally:
        if os.path.exists(temp_zip):
            try:
                os.remove(temp_zip)
            except OSError:
                pass

