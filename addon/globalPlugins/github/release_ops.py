# Copyright (C) 2026 Mehmet Aykurt <m.aykurt38@gmail.com>
# Bu eklenti Mehmet Aykurt tarafından geliştirilmiştir.
# Lisans: GNU General Public License v2 (GPL-2.0)

"""GitHub Releases management: listing releases, viewing release notes, and downloading release assets."""

import addonHandler
addonHandler.initTranslation()

import json
import os
import re
import socket
import urllib.error
import urllib.parse
import urllib.request

import ui
import wx

from .auth import AuthError, checkCancelled
from .credentials import CredentialError
from .downloader import USER_AGENT, _build_opener, computeReleaseAssetSha256, downloadFile, downloadReleaseAsset
from .errors import errorMessage
from .settings import SettingsError


def _check_cancelled(cancel):
    if cancel is not None:
        checkCancelled(cancel)


def listReleases(token, full_name, cancel=None):
    """Fetches list of releases for a repository."""
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", full_name):
        raise AuthError("invalid_response")
    _check_cancelled(cancel)

    url = f"https://api.github.com/repos/{full_name}/releases?per_page=50"
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/vnd.github.v3+json",
        "Authorization": f"Bearer {token}",
    }
    req = urllib.request.Request(url, headers=headers)
    opener = _build_opener()

    try:
        with opener.open(req, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))
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

    if not isinstance(data, list):
        raise AuthError("invalid_response")

    releases = []
    for item in data:
        if not isinstance(item, dict):
            continue
        assets = []
        for a in (item.get("assets") or []):
            if not isinstance(a, dict):
                continue
            assets.append({
                "id": a.get("id") or 0,
                "name": a.get("name") or "",
                "size": a.get("size") or 0,
                "download_count": a.get("download_count") or 0,
                "url": a.get("url") or "",
                "browser_download_url": a.get("browser_download_url") or "",
            })

        author_obj = item.get("author") or {}
        releases.append({
            "id": item.get("id") or 0,
            "name": item.get("name") or item.get("tag_name") or "",
            "tag_name": item.get("tag_name") or "",
            "author": (author_obj.get("login") or "") if isinstance(author_obj, dict) else "",
            "created_at": item.get("created_at") or "",
            "published_at": item.get("published_at") or item.get("created_at") or "",
            "body": item.get("body") or "",
            "html_url": item.get("html_url") or "",
            "draft": bool(item.get("draft", False)),
            "prerelease": bool(item.get("prerelease", False)),
            "assets": assets,
        })
    return releases


def formatFileSize(size_bytes):
    """Formats file size into human-readable Turkish/English format."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    else:
        return f"{size_bytes / (1024 * 1024):.1f} MB"


def createRelease(token, full_name, tag, name="", body="", target_commitish=None, prerelease=False, cancel=None):
    """Creates a new release on GitHub."""
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", full_name):
        raise AuthError("invalid_response")
    tag = tag.strip()
    if not tag:
        raise AuthError("invalid_response")
    _check_cancelled(cancel)

    url = f"https://api.github.com/repos/{full_name}/releases"
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/vnd.github.v3+json",
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    payload = {
        "tag_name": tag,
        "name": name.strip() if name else tag,
        "body": body,
        "prerelease": bool(prerelease),
    }
    if target_commitish:
        payload["target_commitish"] = target_commitish

    body_bytes = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body_bytes, headers=headers, method="POST")
    opener = _build_opener()

    try:
        with opener.open(req, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise AuthError("not_found") from None
        if exc.code == 401:
            raise AuthError("unauthorized") from None
        if exc.code == 422:
            raise AuthError("release_tag_exists") from None
        if exc.code in (403, 429):
            raise AuthError("limited") from None
        raise AuthError("server_error") from None
    except (urllib.error.URLError, OSError, socket.timeout):
        raise AuthError("network") from None

    _check_cancelled(cancel)
    return data


def uploadReleaseAsset(token, full_name, release_id, file_path, cancel=None):
    """Uploads a binary asset file to a GitHub release."""
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", full_name):
        raise AuthError("invalid_response")
    if not os.path.isfile(file_path):
        raise AuthError("invalid_response")
    _check_cancelled(cancel)

    file_name = os.path.basename(file_path)
    file_size = os.path.getsize(file_path)
    if file_size > 100 * 1024 * 1024:
        raise AuthError("file_too_large")

    with open(file_path, "rb") as f:
        content_bytes = f.read()

    _check_cancelled(cancel)

    quoted_name = urllib.parse.quote(file_name)
    url = f"https://uploads.github.com/repos/{full_name}/releases/{int(release_id)}/assets?name={quoted_name}"
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/vnd.github.v3+json",
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/octet-stream",
        "Content-Length": str(len(content_bytes)),
    }
    req = urllib.request.Request(url, data=content_bytes, headers=headers, method="POST")
    opener = _build_opener()

    try:
        with opener.open(req, timeout=120) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise AuthError("not_found") from None
        if exc.code == 401:
            raise AuthError("unauthorized") from None
        if exc.code == 422:
            raise AuthError("release_asset_failed") from None
        if exc.code in (403, 429):
            raise AuthError("limited") from None
        raise AuthError("server_error") from None
    except (urllib.error.URLError, OSError, socket.timeout):
        raise AuthError("network") from None

    _check_cancelled(cancel)
    return data


def updateRelease(token, full_name, release_id, tag_name=None, name=None, body=None, draft=None, prerelease=None, cancel=None):
    """Updates release details (title, notes, tag, draft/prerelease state)."""
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", full_name):
        raise AuthError("invalid_response")
    _check_cancelled(cancel)

    url = f"https://api.github.com/repos/{full_name}/releases/{int(release_id)}"
    payload_dict = {}
    if tag_name is not None:
        payload_dict["tag_name"] = tag_name
    if name is not None:
        payload_dict["name"] = name
    if body is not None:
        payload_dict["body"] = body
    if draft is not None:
        payload_dict["draft"] = bool(draft)
    if prerelease is not None:
        payload_dict["prerelease"] = bool(prerelease)

    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/vnd.github.v3+json",
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    req = urllib.request.Request(url, data=json.dumps(payload_dict).encode("utf-8"), headers=headers, method="PATCH")
    opener = _build_opener()

    try:
        with opener.open(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise AuthError("not_found") from None
        if exc.code == 401:
            raise AuthError("unauthorized") from None
        if exc.code == 422:
            raise AuthError("release_tag_exists") from None
        if exc.code in (403, 429):
            raise AuthError("limited") from None
        raise AuthError("server_error") from None
    except (urllib.error.URLError, OSError, socket.timeout):
        raise AuthError("network") from None


def deleteRelease(token, full_name, release_id, cancel=None):
    """Deletes a release from GitHub."""
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", full_name):
        raise AuthError("invalid_response")
    _check_cancelled(cancel)

    url = f"https://api.github.com/repos/{full_name}/releases/{int(release_id)}"
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/vnd.github.v3+json",
        "Authorization": f"Bearer {token}",
    }
    req = urllib.request.Request(url, headers=headers, method="DELETE")
    opener = _build_opener()

    try:
        with opener.open(req, timeout=30):
            return True
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


class EditReleaseDialog(wx.Dialog):
    """Accessible dialog for editing an existing GitHub release."""

    def __init__(self, parent, release_dict):
        rel_name = release_dict.get("name") or release_dict.get("tag_name") or _("Release")
        super().__init__(
            parent,
            title=_("Edit Release — %s") % rel_name,
            size=(580, 500),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        self.release = release_dict

        layout = wx.BoxSizer(wx.VERTICAL)

        # Version tag
        tag_label = wx.StaticText(self, label=_("&Version tag:"))
        layout.Add(tag_label, 0, wx.ALL, 6)
        self.tag_ctrl = wx.TextCtrl(self, value=release_dict.get("tag_name") or "")
        self.tag_ctrl.SetName(_("Version tag"))
        layout.Add(self.tag_ctrl, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        # Release title
        title_label = wx.StaticText(self, label=_("&Release title:"))
        layout.Add(title_label, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)
        self.title_ctrl = wx.TextCtrl(self, value=release_dict.get("name") or "")
        self.title_ctrl.SetName(_("Release title"))
        layout.Add(self.title_ctrl, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        # Pre-release checkbox
        self.prerelease_cb = wx.CheckBox(self, label=_("&Mark as pre-release"))
        self.prerelease_cb.SetValue(bool(release_dict.get("prerelease", False)))
        self.prerelease_cb.SetName(_("Mark as pre-release"))
        layout.Add(self.prerelease_cb, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        # Release notes (body)
        body_label = wx.StaticText(self, label=_("&Release notes:"))
        layout.Add(body_label, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)
        self.body_ctrl = wx.TextCtrl(self, value=release_dict.get("body") or "", style=wx.TE_MULTILINE)
        self.body_ctrl.SetName(_("Release notes"))
        layout.Add(self.body_ctrl, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        # Buttons
        button_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.ok_btn = wx.Button(self, wx.ID_OK, _("&Save changes"))
        self.ok_btn.SetDefault()
        self.ok_btn.Bind(wx.EVT_BUTTON, self._onSubmit)
        button_sizer.Add(self.ok_btn, 0, wx.RIGHT, 10)

        self.cancel_btn = wx.Button(self, wx.ID_CANCEL, _("&Cancel"))
        button_sizer.Add(self.cancel_btn, 0)

        layout.Add(button_sizer, 0, wx.ALIGN_RIGHT | wx.RIGHT | wx.BOTTOM, 10)
        self.SetSizer(layout)
        self.SetMinSize((480, 420))
        self.CentreOnScreen()

        wx.CallAfter(self.tag_ctrl.SetFocus)

    def _onSubmit(self, event):
        tag = self.tag_ctrl.GetValue().strip()
        if not tag:
            wx.MessageBox(_("Please enter a version tag."), _("Error"), wx.OK | wx.ICON_ERROR, self)
            self.tag_ctrl.SetFocus()
            return
        self.EndModal(wx.ID_OK)

    def getData(self):
        return {
            "tag_name": self.tag_ctrl.GetValue().strip(),
            "name": self.title_ctrl.GetValue().strip(),
            "body": self.body_ctrl.GetValue(),
            "prerelease": self.prerelease_cb.IsChecked(),
        }

    def cancelAndClose(self):
        if self.IsModal():
            self.EndModal(wx.ID_CANCEL)


class ReleaseDetailDialog(wx.Dialog):
    """Accessible dialog for reading release notes and downloading release assets."""

    def __init__(self, parent, release, full_name, service):
        rel_name = release.get("name") or release.get("tag_name") or _("Release")
        super().__init__(
            parent,
            title=_("Release Details — %s") % rel_name,
            size=(750, 550),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        self.release = release
        self.full_name = full_name
        self.service = service
        self._closing = False

        layout = wx.BoxSizer(wx.VERTICAL)

        # Release description box
        notes_label = wx.StaticText(self, label=_("&Release notes:"))
        layout.Add(notes_label, 0, wx.ALL, 6)

        self.text_ctrl = wx.TextCtrl(
            self,
            value=self._buildFullText(release),
            style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_DONTWRAP | wx.HSCROLL,
        )
        self.text_ctrl.SetName(_("Release notes"))
        layout.Add(self.text_ctrl, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        # Assets list (if any)
        self.assets = release.get("assets", [])
        assets_label = wx.StaticText(self, label=_("&Downloadable files (%s):") % len(self.assets))
        layout.Add(assets_label, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)

        self.assets_list = wx.ListCtrl(self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        self.assets_list.SetName(_("Downloadable files"))
        self.assets_list.InsertColumn(0, _("File name"), width=320)
        self.assets_list.InsertColumn(1, _("Size"), width=110)
        self.assets_list.InsertColumn(2, _("Downloads"), width=110)

        for idx, a in enumerate(self.assets):
            pos = self.assets_list.InsertItem(idx, a.get("name", ""))
            self.assets_list.SetItem(pos, 1, formatFileSize(a.get("size", 0)))
            self.assets_list.SetItem(pos, 2, str(a.get("download_count", 0)))

        if self.assets:
            self.assets_list.Select(0)
            self.assets_list.Focus(0)

        self.assets_list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self._onDownloadAsset)
        self.assets_list.Bind(wx.EVT_KEY_DOWN, self._onAssetKey)
        self.assets_list.Bind(wx.EVT_CONTEXT_MENU, self._onAssetContextMenu)
        layout.Add(self.assets_list, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        # Buttons
        button_sizer = wx.BoxSizer(wx.HORIZONTAL)

        self.download_btn = wx.Button(self, label=_("&Download file…"))
        self.download_btn.Bind(wx.EVT_BUTTON, self._onDownloadAsset)
        self.download_btn.Enable(bool(self.assets))
        button_sizer.Add(self.download_btn, 0, wx.RIGHT, 10)

        self.copy_link_btn = wx.Button(self, label=_("Copy download &link"))
        self.copy_link_btn.Bind(wx.EVT_BUTTON, self._onCopyAssetLink)
        self.copy_link_btn.Enable(bool(self.assets))
        button_sizer.Add(self.copy_link_btn, 0, wx.RIGHT, 10)

        self.copy_sha_btn = wx.Button(self, label=_("Copy &SHA256 hash"))
        self.copy_sha_btn.Bind(wx.EVT_BUTTON, self._onCopyAssetSha)
        self.copy_sha_btn.Enable(bool(self.assets))
        button_sizer.Add(self.copy_sha_btn, 0, wx.RIGHT, 10)

        self.copy_btn = wx.Button(self, label=_("&Copy text"))
        self.copy_btn.Bind(wx.EVT_BUTTON, self._onCopyClicked)
        button_sizer.Add(self.copy_btn, 0, wx.RIGHT, 10)

        self.close_btn = wx.Button(self, wx.ID_CANCEL, _("&Close"))
        self.close_btn.Bind(wx.EVT_BUTTON, self._onClose)
        button_sizer.Add(self.close_btn, 0)

        layout.Add(button_sizer, 0, wx.ALIGN_RIGHT | wx.RIGHT | wx.BOTTOM, 10)
        self.SetSizer(layout)
        self.SetMinSize((550, 420))
        self.CentreOnScreen()

        self.Bind(wx.EVT_CLOSE, self._onClose)
        self.Bind(wx.EVT_CHAR_HOOK, self._onCharHook)
        wx.CallAfter(self.text_ctrl.SetFocus)

    def _buildFullText(self, release):
        lines = []
        name = release.get("name") or release.get("tag_name") or ""
        tag = release.get("tag_name") or ""
        pub_date = (release.get("published_at") or release.get("created_at") or "")[:10]
        lines.append(f"{_('Version:')} {name} ({tag})")
        lines.append(f"{_('Author:')} {release.get('author') or ''} | {_('Date:')} {pub_date}")
        if release.get("draft"):
            lines.append(f"[{_('Draft')}]")
        if release.get("prerelease"):
            lines.append(f"[{_('Pre-release')}]")
        lines.append("-" * 40)
        body = (release.get("body") or "").strip()
        lines.append(body if body else _("(No release notes provided.)"))
        return "\n".join(lines)

    def cancelAndClose(self):
        self._closing = True
        if self.IsModal():
            self.EndModal(wx.ID_CANCEL)

    def _onClose(self, event=None):
        self._closing = True
        if self.IsModal():
            self.EndModal(wx.ID_CANCEL)
        else:
            self.Close()
            self.Destroy()

    def _onCharHook(self, event):
        if event.GetKeyCode() == wx.WXK_ESCAPE:
            self._onClose()
            return
        event.Skip()

    def _onAssetKey(self, event):
        if event.GetKeyCode() == wx.WXK_RETURN and not event.HasAnyModifiers():
            self._onDownloadAsset(None)
            return
        if event.GetKeyCode() == ord("C") and event.ControlDown() and not event.ShiftDown() and not event.AltDown():
            self._onCopyAssetLink(None)
            return
        if event.GetKeyCode() == ord("H") and event.ControlDown() and not event.ShiftDown() and not event.AltDown():
            self._onCopyAssetSha(None)
            return
        if event.GetKeyCode() == ord("S") and event.ControlDown() and event.ShiftDown() and not event.AltDown():
            self._onCopyAssetSha(None)
            return
        if event.GetKeyCode() == wx.WXK_F10 and event.ShiftDown():
            self._onAssetContextMenu(None)
            return
        event.Skip()

    def _onAssetContextMenu(self, event=None):
        if self._closing or not self.assets:
            return
        idx = self.assets_list.GetFirstSelected()
        if idx < 0:
            idx = 0
            self.assets_list.Select(0)
            self.assets_list.Focus(0)
        menu = wx.Menu()
        dl_item = menu.Append(wx.ID_ANY, _("&Download file…"))
        menu.Bind(wx.EVT_MENU, self._onDownloadAsset, id=dl_item.GetId())
        link_item = menu.Append(wx.ID_ANY, _("Copy download &link") + "\tCtrl+C")
        menu.Bind(wx.EVT_MENU, self._onCopyAssetLink, id=link_item.GetId())
        sha_item = menu.Append(wx.ID_ANY, _("Copy &SHA256 hash") + "\tCtrl+Shift+S")
        menu.Bind(wx.EVT_MENU, self._onCopyAssetSha, id=sha_item.GetId())
        self.PopupMenu(menu)
        menu.Destroy()

    def _onCopyAssetLink(self, event=None):
        if self._closing:
            return
        idx = self.assets_list.GetFirstSelected()
        if idx < 0 and self.assets:
            idx = 0
            self.assets_list.Select(0)
            self.assets_list.Focus(0)
        if idx < 0 or idx >= len(self.assets):
            ui.message(_("No downloadable files available."))
            return
        asset = self.assets[idx]
        download_url = asset.get("browser_download_url") or ""
        if not download_url:
            ui.message(_("No download link available for this file."))
            return
        if wx.TheClipboard.Open():
            try:
                wx.TheClipboard.SetData(wx.TextDataObject(download_url))
                ui.message(_("Download link copied to clipboard."))
            finally:
                wx.TheClipboard.Close()
        else:
            ui.message(_("Clipboard could not be opened."))

    def _onCopyAssetSha(self, event=None):
        if self._closing:
            return
        idx = self.assets_list.GetFirstSelected()
        if idx < 0 and self.assets:
            idx = 0
            self.assets_list.Select(0)
            self.assets_list.Focus(0)
        if idx < 0 or idx >= len(self.assets):
            ui.message(_("No downloadable files available."))
            return
        asset = self.assets[idx]
        cached_sha = asset.get("_sha256")
        if cached_sha:
            if wx.TheClipboard.Open():
                try:
                    wx.TheClipboard.SetData(wx.TextDataObject(cached_sha))
                    ui.message(_("SHA256 hash copied to clipboard."))
                finally:
                    wx.TheClipboard.Close()
            else:
                ui.message(_("Clipboard could not be opened."))
            return

        asset_id = asset.get("id") or 0
        download_url = asset.get("browser_download_url") or ""
        filename = asset.get("name") or _("File")
        if not asset_id and not download_url:
            ui.message(_("No download link available for this file."))
            return

        ui.message(_("Calculating SHA256: %s…") % filename)

        def worker():
            try:
                if hasattr(self.service, "computeReleaseAssetSha256"):
                    sha256_hash = self.service.computeReleaseAssetSha256(
                        self.full_name,
                        asset_id,
                        downloadUrl=download_url,
                    )
                else:
                    sha256_hash = computeReleaseAssetSha256(
                        "",
                        self.full_name,
                        asset_id,
                        download_url=download_url,
                    )
                asset["_sha256"] = sha256_hash

                def on_success():
                    if self._closing or not self:
                        return
                    if wx.TheClipboard.Open():
                        try:
                            wx.TheClipboard.SetData(wx.TextDataObject(sha256_hash))
                            ui.message(_("SHA256 hash copied to clipboard."))
                        finally:
                            wx.TheClipboard.Close()
                    else:
                        ui.message(_("Clipboard could not be opened."))

                wx.CallAfter(on_success)
            except Exception as err:
                def on_error():
                    if self._closing or not self:
                        return
                    if isinstance(err, (AuthError, CredentialError, SettingsError, OSError)):
                        ui.message(errorMessage(err))
                    else:
                        ui.message(_("Could not calculate SHA256."))

                wx.CallAfter(on_error)

        import threading
        self._sha_worker = threading.Thread(target=worker, daemon=True)
        self._sha_worker.start()

    def _onCopyClicked(self, event):
        text = self.text_ctrl.GetValue()
        if wx.TheClipboard.Open():
            try:
                wx.TheClipboard.SetData(wx.TextDataObject(text))
                ui.message(_("Release details copied to clipboard."))
            finally:
                wx.TheClipboard.Close()
        else:
            ui.message(_("Clipboard could not be opened."))

    def _onDownloadAsset(self, event):
        if self._closing:
            return
        idx = self.assets_list.GetFirstSelected()
        if idx < 0 and self.assets:
            idx = 0
            self.assets_list.Select(0)
            self.assets_list.Focus(0)
        if idx < 0 or idx >= len(self.assets):
            ui.message(_("No downloadable files available."))
            return
        asset = self.assets[idx]
        asset_id = asset.get("id") or 0
        download_url = asset.get("browser_download_url") or ""
        filename = asset.get("name")
        if (not asset_id and not download_url) or not filename:
            return

        with wx.FileDialog(
            self,
            message=_("Save file"),
            defaultFile=filename,
            style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT,
        ) as file_dlg:
            if file_dlg.ShowModal() != wx.ID_OK:
                return
            target_path = file_dlg.GetPath()

        ui.message(_("Downloading: %s…") % filename)

        def worker():
            try:
                if hasattr(self.service, "downloadReleaseAsset"):
                    self.service.downloadReleaseAsset(
                        self.full_name,
                        asset_id,
                        target_path,
                        downloadUrl=download_url,
                    )
                else:
                    downloadReleaseAsset(
                        "",
                        self.full_name,
                        asset_id,
                        target_path,
                        download_url=download_url,
                    )
                try:
                    import hashlib
                    hasher = hashlib.sha256()
                    with open(target_path, "rb") as f_in:
                        while True:
                            chunk = f_in.read(64 * 1024)
                            if not chunk:
                                break
                            hasher.update(chunk)
                    asset["_sha256"] = hasher.hexdigest()
                except Exception:
                    pass
                wx.CallAfter(ui.message, _("File successfully downloaded: %s") % filename)
            except Exception as err:
                if isinstance(err, (AuthError, CredentialError, SettingsError, OSError)):
                    wx.CallAfter(ui.message, errorMessage(err))
                else:
                    wx.CallAfter(ui.message, _("Download failed."))

        import threading
        self._download_worker = threading.Thread(target=worker, daemon=True)
        self._download_worker.start()


class NewReleaseDialog(wx.Dialog):
    """Accessible dialog for creating a new release and optionally attaching an asset file."""

    def __init__(self, parent, full_name, default_branch="main"):
        super().__init__(
            parent,
            title=_("Create New Release — %s") % full_name,
            size=(600, 560),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        self.full_name = full_name
        self.default_branch = default_branch

        layout = wx.BoxSizer(wx.VERTICAL)

        # Tag name
        tag_label = wx.StaticText(self, label=_("&Version tag (e.g. v1.0):"))
        layout.Add(tag_label, 0, wx.ALL, 6)
        self.tag_ctrl = wx.TextCtrl(self)
        self.tag_ctrl.SetName(_("Version tag"))
        layout.Add(self.tag_ctrl, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        # Release title
        title_label = wx.StaticText(self, label=_("&Release title (optional):"))
        layout.Add(title_label, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)
        self.title_ctrl = wx.TextCtrl(self)
        self.title_ctrl.SetName(_("Release title"))
        layout.Add(self.title_ctrl, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        # Target branch
        branch_label = wx.StaticText(self, label=_("&Target branch:"))
        layout.Add(branch_label, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)
        self.branch_ctrl = wx.TextCtrl(self, value=default_branch or "main")
        self.branch_ctrl.SetName(_("Target branch"))
        layout.Add(self.branch_ctrl, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        # Pre-release checkbox
        self.prerelease_cb = wx.CheckBox(self, label=_("&Mark as pre-release"))
        self.prerelease_cb.SetName(_("Mark as pre-release"))
        layout.Add(self.prerelease_cb, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        # Release notes (body)
        body_label = wx.StaticText(self, label=_("&Release notes (optional):"))
        layout.Add(body_label, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)
        self.body_ctrl = wx.TextCtrl(self, style=wx.TE_MULTILINE)
        self.body_ctrl.SetName(_("Release notes"))
        layout.Add(self.body_ctrl, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        # Asset package file row
        asset_label = wx.StaticText(self, label=_("&Attach package file (optional):"))
        layout.Add(asset_label, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 4)

        asset_row = wx.BoxSizer(wx.HORIZONTAL)
        self.file_ctrl = wx.TextCtrl(self)
        self.file_ctrl.SetName(_("Package file path"))
        asset_row.Add(self.file_ctrl, 1, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)

        self.browse_btn = wx.Button(self, label=_("&Browse…"))
        self.browse_btn.Bind(wx.EVT_BUTTON, self._onBrowseFile)
        asset_row.Add(self.browse_btn, 0, wx.ALIGN_CENTER_VERTICAL)
        layout.Add(asset_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        # Buttons
        button_sizer = wx.BoxSizer(wx.HORIZONTAL)

        self.ok_btn = wx.Button(self, wx.ID_OK, _("&Publish release"))
        self.ok_btn.SetDefault()
        self.ok_btn.Bind(wx.EVT_BUTTON, self._onSubmit)
        button_sizer.Add(self.ok_btn, 0, wx.RIGHT, 10)

        self.cancel_btn = wx.Button(self, wx.ID_CANCEL, _("&Cancel"))
        self.cancel_btn.Bind(wx.EVT_BUTTON, self._onClose)
        button_sizer.Add(self.cancel_btn, 0)

        layout.Add(button_sizer, 0, wx.ALIGN_RIGHT | wx.RIGHT | wx.BOTTOM, 10)
        self.SetSizer(layout)
        self.SetMinSize((500, 480))
        self.CentreOnScreen()

        self.Bind(wx.EVT_CLOSE, self._onClose)
        self.Bind(wx.EVT_CHAR_HOOK, self._onCharHook)
        wx.CallAfter(self.tag_ctrl.SetFocus)

    def _onBrowseFile(self, event):
        with wx.FileDialog(
            self,
            message=_("Select package file"),
            wildcard=_("All files (*.*)|*.*|NVDA Add-on (*.nvda-addon)|*.nvda-addon|ZIP files (*.zip)|*.zip"),
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST,
        ) as dlg:
            if dlg.ShowModal() == wx.ID_OK:
                self.file_ctrl.SetValue(dlg.GetPath())

    def _onSubmit(self, event):
        tag = self.tag_ctrl.GetValue().strip()
        if not tag:
            wx.MessageBox(_("Please enter a version tag."), _("Error"), wx.OK | wx.ICON_ERROR, self)
            self.tag_ctrl.SetFocus()
            return

        file_path = self.file_ctrl.GetValue().strip()
        if file_path and not os.path.isfile(file_path):
            wx.MessageBox(_("Selected package file does not exist."), _("Error"), wx.OK | wx.ICON_ERROR, self)
            self.file_ctrl.SetFocus()
            return

        self.EndModal(wx.ID_OK)

    def cancelAndClose(self):
        if self.IsModal():
            self.EndModal(wx.ID_CANCEL)

    def _onClose(self, event=None):
        if self.IsModal():
            self.EndModal(wx.ID_CANCEL)
        else:
            self.Close()
            self.Destroy()

    def _onCharHook(self, event):
        if event.GetKeyCode() == wx.WXK_ESCAPE:
            self._onClose()
            return
        event.Skip()

    def getData(self):
        return {
            "tag": self.tag_ctrl.GetValue().strip(),
            "name": self.title_ctrl.GetValue().strip(),
            "branch": self.branch_ctrl.GetValue().strip() or "main",
            "prerelease": self.prerelease_cb.IsChecked(),
            "body": self.body_ctrl.GetValue(),
            "file_path": self.file_ctrl.GetValue().strip(),
        }


class ReleasesDialog(wx.Dialog):
    """Accessible dialog for browsing and managing repository releases."""

    def __init__(self, parent, full_name, service, default_branch="main"):
        super().__init__(
            parent,
            title=_("Releases — %s") % full_name,
            size=(850, 520),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        self.full_name = full_name
        self.service = service
        self.default_branch = default_branch or "main"
        self.releases = []
        self._closing = False
        self._child_dlg = None

        layout = wx.BoxSizer(wx.VERTICAL)

        # Releases list
        self.releases_list = wx.ListCtrl(self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        self.releases_list.SetName(_("Releases"))
        self.releases_list.InsertColumn(0, _("Version"), width=220)
        self.releases_list.InsertColumn(1, _("Tag"), width=120)
        self.releases_list.InsertColumn(2, _("Date"), width=130)
        self.releases_list.InsertColumn(3, _("Author"), width=130)
        self.releases_list.InsertColumn(4, _("Files"), width=90)

        self.releases_list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self._onViewRelease)
        self.releases_list.Bind(wx.EVT_KEY_DOWN, self._onListKey)
        layout.Add(self.releases_list, 1, wx.EXPAND | wx.ALL, 10)

        # Status text
        self.status_label = wx.StaticText(self, label="")
        layout.Add(self.status_label, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)

        # Buttons
        button_sizer = wx.BoxSizer(wx.HORIZONTAL)

        self.view_btn = wx.Button(self, label=_("&Release details…"))
        self.view_btn.Bind(wx.EVT_BUTTON, self._onViewRelease)
        button_sizer.Add(self.view_btn, 0, wx.RIGHT, 10)

        self.edit_btn = wx.Button(self, label=_("&Edit release…"))
        self.edit_btn.Bind(wx.EVT_BUTTON, self._onEditRelease)
        button_sizer.Add(self.edit_btn, 0, wx.RIGHT, 10)

        self.delete_btn = wx.Button(self, label=_("&Delete release…"))
        self.delete_btn.Bind(wx.EVT_BUTTON, self._onDeleteRelease)
        button_sizer.Add(self.delete_btn, 0, wx.RIGHT, 10)

        self.new_btn = wx.Button(self, label=_("&New release…"))
        self.new_btn.Bind(wx.EVT_BUTTON, self._onNewRelease)
        button_sizer.Add(self.new_btn, 0, wx.RIGHT, 10)

        self.close_btn = wx.Button(self, wx.ID_CANCEL, _("&Close"))
        self.close_btn.Bind(wx.EVT_BUTTON, self._onClose)
        button_sizer.Add(self.close_btn, 0)

        layout.Add(button_sizer, 0, wx.ALIGN_RIGHT | wx.RIGHT | wx.BOTTOM, 10)
        self.SetSizer(layout)
        self.SetMinSize((650, 400))
        self.CentreOnScreen()

        self.Bind(wx.EVT_CLOSE, self._onClose)
        self.Bind(wx.EVT_CHAR_HOOK, self._onCharHook)
        wx.CallAfter(self.loadReleases)

    def _setStatus(self, msg):
        if not self._closing and self:
            self.status_label.SetLabel(msg)

    def _runNestedModal(self, dlg):
        if self._closing or not self:
            if dlg:
                dlg.Destroy()
            return wx.ID_CANCEL
        self._child_dlg = dlg
        try:
            return dlg.ShowModal()
        finally:
            if hasattr(dlg, "cancelAndClose"):
                dlg.cancelAndClose()
            self._child_dlg = None
            if dlg:
                dlg.Destroy()

    def cancelAndClose(self):
        self._closing = True
        if self._child_dlg is not None:
            if hasattr(self._child_dlg, "cancelAndClose"):
                self._child_dlg.cancelAndClose()
            elif self._child_dlg.IsModal():
                self._child_dlg.EndModal(wx.ID_CANCEL)
        if self.IsModal():
            self.EndModal(wx.ID_CANCEL)

    def _onClose(self, event=None):
        self._closing = True
        if self._child_dlg is not None:
            if hasattr(self._child_dlg, "cancelAndClose"):
                self._child_dlg.cancelAndClose()
            elif self._child_dlg.IsModal():
                self._child_dlg.EndModal(wx.ID_CANCEL)
        if self.IsModal():
            self.EndModal(wx.ID_CANCEL)
        else:
            self.Close()
            self.Destroy()

    def _onCharHook(self, event):
        if event.GetKeyCode() == wx.WXK_ESCAPE and not event.HasAnyModifiers():
            self._onClose()
            return
        if event.GetKeyCode() == wx.WXK_F5 and not event.HasAnyModifiers():
            self.loadReleases()
            return
        if event.GetKeyCode() == ord("N") and event.ControlDown() and not event.ShiftDown() and not event.AltDown():
            self._onNewRelease(None)
            return
        event.Skip()

    def _onListKey(self, event):
        if event.GetKeyCode() == wx.WXK_RETURN:
            self._onViewRelease(None)
            return
        if event.GetKeyCode() == ord("N") and event.ControlDown() and not event.ShiftDown():
            self._onNewRelease(None)
            return
        if event.GetKeyCode() == wx.WXK_F5:
            self.loadReleases()
            return
        event.Skip()

    def loadReleases(self):
        if self._closing or not self:
            return
        self._setStatus(_("Loading releases…"))
        self.releases_list.DeleteAllItems()

        def background_task():
            if hasattr(self.service, "loadReleases"):
                return self.service.loadReleases(self.full_name)
            return []

        import threading

        def thread_target():
            try:
                result = background_task()
                wx.CallAfter(self._onReleasesLoaded, result)
            except Exception as e:
                wx.CallAfter(self._onReleasesError, e)

        self._worker = threading.Thread(target=thread_target, daemon=True)
        self._worker.start()

    def _onReleasesLoaded(self, releases):
        if self._closing or not self:
            return
        self.releases = releases
        self.releases_list.DeleteAllItems()
        for idx, item in enumerate(releases):
            name = item.get("name") or item.get("tag_name") or ""
            badges = []
            if item.get("draft"):
                badges.append(_("Draft"))
            if item.get("prerelease"):
                badges.append(_("Pre-release"))
            if badges:
                badge_text = f"[{' / '.join(badges)}]"
                name = f"{name} {badge_text}" if name else badge_text
            pos = self.releases_list.InsertItem(idx, name)
            self.releases_list.SetItem(pos, 1, item.get("tag_name") or "")
            date_str = (item.get("published_at") or item.get("created_at") or "")[:10]
            self.releases_list.SetItem(pos, 2, date_str)
            self.releases_list.SetItem(pos, 3, item.get("author") or "")
            self.releases_list.SetItem(pos, 4, str(len(item.get("assets") or [])))

        if releases:
            msg = _("%s releases listed.") % len(releases)
            self._setStatus(msg)
            ui.message(msg)
            self.releases_list.Select(0)
            self.releases_list.Focus(0)
            self.releases_list.SetFocus()
        else:
            msg = _("No releases found.")
            self._setStatus(msg)
            ui.message(msg)
            self.new_btn.SetFocus()

    def _onReleasesError(self, err):
        if self._closing or not self:
            return
        if isinstance(err, (AuthError, CredentialError, SettingsError, OSError)):
            msg = errorMessage(err)
        else:
            msg = _("Could not load releases.")
        self._setStatus(msg)
        ui.message(msg)

    def _selectedRelease(self):
        index = self.releases_list.GetFirstSelected()
        if 0 <= index < len(self.releases):
            return self.releases[index]
        return None

    def _onViewRelease(self, event):
        if self._closing or not self or self._child_dlg is not None:
            return
        release = self._selectedRelease()
        if not release:
            return
        self._runNestedModal(ReleaseDetailDialog(self, release, self.full_name, self.service))

    def _onEditRelease(self, event=None):
        if self._closing or not self or self._child_dlg is not None:
            return
        release = self._selectedRelease()
        if not release:
            return
        dlg = EditReleaseDialog(self, release)
        data = None
        self._child_dlg = dlg
        try:
            if dlg.ShowModal() == wx.ID_OK:
                data = dlg.getData()
        finally:
            dlg.cancelAndClose()
            self._child_dlg = None
            dlg.Destroy()
        if not data or self._closing or not self:
            return

        def worker():
            try:
                self.service.updateRelease(
                    self.full_name,
                    release["id"],
                    tag_name=data["tag_name"],
                    name=data["name"],
                    body=data["body"],
                    prerelease=data["prerelease"],
                )

                def on_ok():
                    ui.message(_("Release updated successfully."))
                    if not self._closing and self:
                        self.loadReleases()

                wx.CallAfter(on_ok)
            except Exception as err:
                def on_err():
                    if isinstance(err, (AuthError, CredentialError, SettingsError, OSError)):
                        ui.message(errorMessage(err))
                    else:
                        ui.message(_("Failed to update release."))

                wx.CallAfter(on_err)

        import threading
        threading.Thread(target=worker, daemon=True).start()

    def _onDeleteRelease(self, event=None):
        if self._closing or not self or self._child_dlg is not None:
            return
        release = self._selectedRelease()
        if not release:
            return
        rel_name = release.get("name") or release.get("tag_name") or _("Release")
        answer = wx.MessageBox(
            _("Are you sure you want to delete the release '%s'? This action cannot be undone.") % rel_name,
            _("Delete Release"),
            wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION,
            self,
        )
        if answer != wx.YES or self._closing:
            return

        def worker():
            try:
                self.service.deleteRelease(self.full_name, release["id"])

                def on_ok():
                    ui.message(_("Release deleted successfully."))
                    if not self._closing and self:
                        self.loadReleases()

                wx.CallAfter(on_ok)
            except Exception as err:
                def on_err():
                    if isinstance(err, (AuthError, CredentialError, SettingsError, OSError)):
                        ui.message(errorMessage(err))
                    else:
                        ui.message(_("Failed to delete release."))

                wx.CallAfter(on_err)

        import threading
        threading.Thread(target=worker, daemon=True).start()

    def _onNewRelease(self, event=None):
        if self._closing or not self or self._child_dlg is not None:
            return
        dlg = NewReleaseDialog(self, self.full_name, default_branch=self.default_branch)
        data = None
        self._child_dlg = dlg
        try:
            if dlg.ShowModal() == wx.ID_OK:
                data = dlg.getData()
        finally:
            dlg.cancelAndClose()
            self._child_dlg = None
            dlg.Destroy()
        if not data or self._closing or not self:
            return

        start_msg = _("Publishing release: %s…") % data["tag"]
        self._setStatus(start_msg)
        ui.message(start_msg)

        def worker():
            try:
                self.service.createRelease(
                    self.full_name,
                    data["tag"],
                    name=data["name"],
                    body=data["body"],
                    target_commitish=data["branch"],
                    prerelease=data["prerelease"],
                    asset_path=data["file_path"],
                )

                def on_created():
                    ui.message(_("Release published successfully."))
                    if not self._closing and self:
                        self.loadReleases()

                wx.CallAfter(on_created)
            except AuthError as err:
                def on_auth_err(e=err):
                    ui.message(errorMessage(e))
                    if getattr(e, "code", "") == "release_asset_failed" and not self._closing and self:
                        self.loadReleases()

                wx.CallAfter(on_auth_err)
            except Exception as err:
                def on_generic_err(e=err):
                    if isinstance(e, (CredentialError, SettingsError, OSError)):
                        ui.message(errorMessage(e))
                    else:
                        ui.message(_("Failed to publish release."))

                wx.CallAfter(on_generic_err)

        import threading
        threading.Thread(target=worker, daemon=True).start()
