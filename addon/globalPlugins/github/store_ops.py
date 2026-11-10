# Copyright (C) 2026 Mehmet Aykurt <m.aykurt38@gmail.com>
# Bu eklenti Mehmet Aykurt tarafından geliştirilmiştir.
# Lisans: GNU General Public License v2 (GPL-2.0)

"""NVDA Add-on Store submission operations.

Fetches latest release metadata, validates store fields according to the official
nvaccess/addon-datastore schema, builds issue templates/URLs, and provides an
accessible dialog for submitting add-ons.
"""

try:
    import addonHandler
    addonHandler.initTranslation()
except Exception:
    def _(s):
        return s

import json
import os
import re
import socket
import threading
import urllib.error
import urllib.parse
import urllib.request
import webbrowser

import ui
import wx

from .auth import AuthError, checkCancelled
from .downloader import USER_AGENT, _build_opener

STORE_REPO = "nvaccess/addon-datastore"
DEFAULT_LICENSE_NAME = "GPL v2"
DEFAULT_LICENSE_URL = "https://www.gnu.org/licenses/gpl-2.0.html"
VALID_CHANNELS = ("stable", "beta", "dev")


def _check_cancelled(cancel):
    if cancel is not None:
        checkCancelled(cancel)


def getLatestAddonRelease(token, full_name, cancel=None):
    """Fetches the latest release of a repository and discovers the .nvda-addon asset.

    Returns a dict with release details and detected add-on fields, or None if no release.
    Raises AuthError on network/auth failures.
    """
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", full_name):
        raise AuthError("invalid_response")
    _check_cancelled(cancel)

    url = f"https://api.github.com/repos/{full_name}/releases/latest"
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/vnd.github.v3+json",
        "Authorization": f"Bearer {token}",
    }
    req = urllib.request.Request(url, headers=headers)
    opener = _build_opener()

    try:
        with opener.open(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        if exc.code == 401:
            raise AuthError("unauthorized") from None
        if exc.code in (403, 429):
            raise AuthError("limited") from None
        raise AuthError("server_error") from None
    except (urllib.error.URLError, OSError, socket.timeout):
        raise AuthError("network") from None

    tag_name = data.get("tag_name", "").strip()
    raw_release_name = data.get("name", "").strip()
    release_name = raw_release_name or tag_name
    assets = data.get("assets", [])

    addon_asset = None
    for asset in assets:
        name = asset.get("name", "")
        if name.lower().endswith(".nvda-addon"):
            addon_asset = asset
            break

    download_url = addon_asset.get("browser_download_url", "") if addon_asset else ""
    asset_name = addon_asset.get("name", "") if addon_asset else ""
    source_url = f"https://github.com/{full_name}"

    version = tag_name.lstrip("vV") if tag_name else ""
    repo_short_name = full_name.split("/")[-1]

    # Başlık (Title) oluşturma mantığı:
    # 1. Öncelik: Sürümün (Release) kendi adı (Örn: "GitHub İçin NVDA Entegrasyonu 2026.11.11")
    if raw_release_name and raw_release_name.lower().strip("v. ") != tag_name.lower().strip("v. "):
        subject = raw_release_name
        if version and version not in subject:
            subject = f"{subject} {version}"
        display_name = subject
    else:
        # 2. Öncelik: Dosya adından temizlenmiş eklenti adı veya depo adı + sürüm
        display_name = repo_short_name
        if asset_name:
            clean_asset = re.sub(r"\.nvda-addon$", "", asset_name, flags=re.IGNORECASE)
            if version and clean_asset.endswith(version):
                clean_asset = clean_asset[:-len(version)].rstrip("-_.")
            elif "-" in clean_asset:
                clean_asset = clean_asset.rsplit("-", 1)[0]
            if clean_asset:
                display_name = clean_asset.replace("-", " ").replace("_", " ").strip()
        subject = f"{display_name} {version}".strip() if version else display_name

    title = f"[Submit add-on]: {subject}".strip()

    return {
        "tag_name": tag_name,
        "release_name": release_name,
        "version": version,
        "asset_name": asset_name,
        "download_url": download_url,
        "source_url": source_url,
        "display_name": display_name,
        "title": title,
    }


def buildStoreMarkdown(download_url, source_url, publisher, channel="stable",
                       license_name=DEFAULT_LICENSE_NAME, license_url=DEFAULT_LICENSE_URL):
    """Builds the exact Markdown issue body conforming to nvaccess/addon-datastore registerAddon.yml."""
    clean_channel = channel.strip().lower() if channel.strip().lower() in VALID_CHANNELS else "stable"
    clean_lic_name = license_name.strip() or DEFAULT_LICENSE_NAME
    clean_lic_url = license_url.strip() or DEFAULT_LICENSE_URL

    return (
        f"### Download URL\n\n"
        f"{download_url.strip()}\n\n"
        f"### Source URL\n\n"
        f"{source_url.strip()}\n\n"
        f"### Publisher\n\n"
        f"{publisher.strip()}\n\n"
        f"### Channel\n\n"
        f"{clean_channel}\n\n"
        f"### License Name\n\n"
        f"{clean_lic_name}\n\n"
        f"### License URL\n\n"
        f"{clean_lic_url}"
    )


def buildStoreWebUrl(title, download_url, source_url, publisher, channel="stable",
                     license_name=DEFAULT_LICENSE_NAME, license_url=DEFAULT_LICENSE_URL):
    """Builds the direct web issue template URL with all query parameters prefilled."""
    clean_channel = channel.strip().lower() if channel.strip().lower() in VALID_CHANNELS else "stable"
    clean_lic_name = license_name.strip() or DEFAULT_LICENSE_NAME
    clean_lic_url = license_url.strip() or DEFAULT_LICENSE_URL

    params = {
        "template": "registerAddon.yml",
        "title": title.strip(),
        "download-url": download_url.strip(),
        "source-url": source_url.strip(),
        "publisher": publisher.strip(),
        "channel": clean_channel,
        "license-name": clean_lic_name,
        "license-url": clean_lic_url,
    }
    query_string = urllib.parse.urlencode(params)
    return f"https://github.com/{STORE_REPO}/issues/new?{query_string}"


def validateStoreSubmission(download_url, source_url, publisher):
    """Validates the submission fields. Returns (True, None) or (False, error_reason)."""
    d = (download_url or "").strip()
    s = (source_url or "").strip()
    p = (publisher or "").strip()

    if not d:
        return False, "missing_download_url"
    if not (d.startswith("https://") and d.lower().endswith(".nvda-addon")):
        return False, "invalid_download_url"
    if not s:
        return False, "missing_source_url"
    if not s.startswith("https://"):
        return False, "invalid_source_url"
    if not p:
        return False, "missing_publisher"
    return True, None


def submitAddonViaApi(token, title, download_url, source_url, publisher, channel="stable",
                      license_name=DEFAULT_LICENSE_NAME, license_url=DEFAULT_LICENSE_URL,
                      cancel=None):
    """Submits the add-on issue directly to nvaccess/addon-datastore via GitHub API."""
    ok, err = validateStoreSubmission(download_url, source_url, publisher)
    if not ok:
        raise ValueError(err)

    _check_cancelled(cancel)

    body = buildStoreMarkdown(
        download_url=download_url,
        source_url=source_url,
        publisher=publisher,
        channel=channel,
        license_name=license_name,
        license_url=license_url,
    )

    clean_title = title.strip()
    if not clean_title.startswith("[Submit add-on]:"):
        clean_title = f"[Submit add-on]: {clean_title}"

    url = f"https://api.github.com/repos/{STORE_REPO}/issues"
    payload = {
        "title": clean_title,
        "body": body,
        "labels": ["autoSubmissionFromIssue"],
        "assignees": ["nvaccess"],
    }
    data_bytes = json.dumps(payload).encode("utf-8")
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/vnd.github.v3+json",
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }

    req = urllib.request.Request(url, data=data_bytes, headers=headers, method="POST")
    opener = _build_opener()

    try:
        with opener.open(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
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


class SubmitAddonDialog(wx.Dialog):
    """Accessible dialog for submitting an add-on to the NVDA Add-on Store."""

    def __init__(self, parent, full_name="", token="", publisher="", initial_data=None):
        dlg_title = _("Submit Add-on to NVDA Store — %s") % full_name if full_name else _("Submit Add-on to NVDA Store")
        super().__init__(
            parent,
            title=dlg_title,
            size=(640, 580),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        self.full_name = full_name
        self.token = token
        self._closing = False
        self._cancel = threading.Event()

        layout = wx.BoxSizer(wx.VERTICAL)

        # 1. Title
        title_label = wx.StaticText(self, label=_("&Title:"))
        layout.Add(title_label, 0, wx.LEFT | wx.RIGHT | wx.TOP, 8)
        self.title_ctrl = wx.TextCtrl(self)
        self.title_ctrl.SetName(_("Title"))
        layout.Add(self.title_ctrl, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)

        # 2. Download URL
        download_label = wx.StaticText(self, label=_("&Download URL (.nvda-addon):"))
        layout.Add(download_label, 0, wx.LEFT | wx.RIGHT | wx.TOP, 4)
        self.download_url_ctrl = wx.TextCtrl(self)
        self.download_url_ctrl.SetName(_("Download URL (.nvda-addon)"))
        layout.Add(self.download_url_ctrl, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)

        # 3. Source repository URL
        default_source_url = f"https://github.com/{full_name}" if full_name else ""
        source_label = wx.StaticText(self, label=_("&Source repository URL:"))
        layout.Add(source_label, 0, wx.LEFT | wx.RIGHT | wx.TOP, 4)
        self.source_url_ctrl = wx.TextCtrl(self, value=default_source_url)
        self.source_url_ctrl.SetName(_("Source repository URL"))
        layout.Add(self.source_url_ctrl, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)

        # 4. Publisher / Author
        pub_label = wx.StaticText(self, label=_("&Publisher / Author:"))
        layout.Add(pub_label, 0, wx.LEFT | wx.RIGHT | wx.TOP, 4)
        self.publisher_ctrl = wx.TextCtrl(self, value=publisher or "")
        self.publisher_ctrl.SetName(_("Publisher / Author"))
        layout.Add(self.publisher_ctrl, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)

        # 5. Channel (stable, beta, dev)
        channel_label = wx.StaticText(self, label=_("&Channel:"))
        layout.Add(channel_label, 0, wx.LEFT | wx.RIGHT | wx.TOP, 4)
        self.channel_choice = wx.Choice(
            self,
            choices=[
                _("stable (recommended)"),
                _("beta"),
                _("dev"),
            ],
        )
        self.channel_choice.SetName(_("Channel"))
        self.channel_choice.SetSelection(0)
        layout.Add(self.channel_choice, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)

        # 6. License Name
        lic_name_label = wx.StaticText(self, label=_("&License name:"))
        layout.Add(lic_name_label, 0, wx.LEFT | wx.RIGHT | wx.TOP, 4)
        self.license_name_ctrl = wx.TextCtrl(self, value=DEFAULT_LICENSE_NAME)
        self.license_name_ctrl.SetName(_("License name"))
        layout.Add(self.license_name_ctrl, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)

        # 7. License URL
        lic_url_label = wx.StaticText(self, label=_("&License URL:"))
        layout.Add(lic_url_label, 0, wx.LEFT | wx.RIGHT | wx.TOP, 4)
        self.license_url_ctrl = wx.TextCtrl(self, value=DEFAULT_LICENSE_URL)
        self.license_url_ctrl.SetName(_("License URL"))
        layout.Add(self.license_url_ctrl, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        # Buttons
        button_sizer = wx.BoxSizer(wx.HORIZONTAL)

        self.web_btn = wx.Button(self, wx.ID_OK, _("&Submit in browser (recommended)"))
        self.web_btn.SetDefault()
        self.web_btn.Bind(wx.EVT_BUTTON, self._onSubmitWeb)
        button_sizer.Add(self.web_btn, 0, wx.RIGHT, 8)

        self.copy_btn = wx.Button(self, wx.ID_ANY, _("&Copy template"))
        self.copy_btn.Bind(wx.EVT_BUTTON, self._onCopyTemplate)
        button_sizer.Add(self.copy_btn, 0, wx.RIGHT, 8)

        self.cancel_btn = wx.Button(self, wx.ID_CANCEL, _("&Cancel"))
        self.cancel_btn.Bind(wx.EVT_BUTTON, self._onClose)
        button_sizer.Add(self.cancel_btn, 0)

        layout.Add(button_sizer, 0, wx.ALIGN_RIGHT | wx.RIGHT | wx.BOTTOM, 10)
        self.SetSizer(layout)
        self.SetMinSize((520, 500))
        self.CentreOnScreen()

        self.Bind(wx.EVT_CLOSE, self._onClose)
        self.Bind(wx.EVT_CHAR_HOOK, self._onCharHook)

        if initial_data:
            self._applyData(initial_data)
        elif self.full_name and self.token:
            self._fetchReleaseAsync()

        wx.CallAfter(self.title_ctrl.SetFocus)

    def _getSelectedChannel(self):
        sel = self.channel_choice.GetSelection()
        if 0 <= sel < len(VALID_CHANNELS):
            return VALID_CHANNELS[sel]
        return "stable"

    def getData(self):
        return {
            "title": self.title_ctrl.GetValue().strip(),
            "download_url": self.download_url_ctrl.GetValue().strip(),
            "source_url": self.source_url_ctrl.GetValue().strip(),
            "publisher": self.publisher_ctrl.GetValue().strip(),
            "channel": self._getSelectedChannel(),
            "license_name": self.license_name_ctrl.GetValue().strip(),
            "license_url": self.license_url_ctrl.GetValue().strip(),
        }

    def _applyData(self, data):
        if self._closing or not data:
            return
        if data.get("title"):
            self.title_ctrl.SetValue(data["title"])
        if data.get("download_url"):
            self.download_url_ctrl.SetValue(data["download_url"])
        if data.get("source_url"):
            self.source_url_ctrl.SetValue(data["source_url"])
        if data.get("publisher"):
            self.publisher_ctrl.SetValue(data["publisher"])
        if data.get("channel") in VALID_CHANNELS:
            idx = VALID_CHANNELS.index(data["channel"])
            self.channel_choice.SetSelection(idx)
        if data.get("license_name"):
            self.license_name_ctrl.SetValue(data["license_name"])
        if data.get("license_url"):
            self.license_url_ctrl.SetValue(data["license_url"])

    def _fetchReleaseAsync(self):
        def worker():
            try:
                info = getLatestAddonRelease(self.token, self.full_name, cancel=self._cancel)
                if not self._closing and info:
                    wx.CallAfter(self._applyData, info)
            except Exception:
                pass
        threading.Thread(target=worker, daemon=True).start()

    def _validate(self):
        data = self.getData()
        if not data["title"]:
            wx.MessageBox(_("Please enter an issue title."), _("Error"), wx.OK | wx.ICON_ERROR, self)
            self.title_ctrl.SetFocus()
            return False, None

        ok, err = validateStoreSubmission(data["download_url"], data["source_url"], data["publisher"])
        if not ok:
            if err == "missing_download_url":
                msg = _("Download URL must start with 'https://' and end with '.nvda-addon'.")
                self.download_url_ctrl.SetFocus()
            elif err == "invalid_download_url":
                msg = _("Download URL must start with 'https://' and end with '.nvda-addon'.")
                self.download_url_ctrl.SetFocus()
            elif err in ("missing_source_url", "invalid_source_url"):
                msg = _("Source URL must start with 'https://'.")
                self.source_url_ctrl.SetFocus()
            elif err == "missing_publisher":
                msg = _("Please enter a publisher name.")
                self.publisher_ctrl.SetFocus()
            else:
                msg = _("Please check required fields.")
            wx.MessageBox(msg, _("Error"), wx.OK | wx.ICON_ERROR, self)
            return False, None

        return True, data

    def _copyToClipboard(self, text):
        if wx.TheClipboard.Open():
            wx.TheClipboard.SetData(wx.TextDataObject(text))
            wx.TheClipboard.Close()
            return True
        return False

    def _onSubmitWeb(self, event=None):
        valid, data = self._validate()
        if not valid:
            return

        markdown_body = buildStoreMarkdown(
            download_url=data["download_url"],
            source_url=data["source_url"],
            publisher=data["publisher"],
            channel=data["channel"],
            license_name=data["license_name"],
            license_url=data["license_url"],
        )
        self._copyToClipboard(markdown_body)

        web_url = buildStoreWebUrl(
            title=data["title"],
            download_url=data["download_url"],
            source_url=data["source_url"],
            publisher=data["publisher"],
            channel=data["channel"],
            license_name=data["license_name"],
            license_url=data["license_url"],
        )

        try:
            webbrowser.open(web_url)
            ui.message(_("Submission form opened in browser with prefilled data."))
        except Exception:
            pass

        self._closing = True
        self.EndModal(wx.ID_OK)

    def _onCopyTemplate(self, event=None):
        data = self.getData()
        markdown_body = buildStoreMarkdown(
            download_url=data["download_url"],
            source_url=data["source_url"],
            publisher=data["publisher"],
            channel=data["channel"],
            license_name=data["license_name"],
            license_url=data["license_url"],
        )
        if self._copyToClipboard(markdown_body):
            ui.message(_("Form data copied to clipboard."))
        else:
            ui.message(_("Clipboard could not be opened."))

    def cancelAndClose(self):
        self._closing = True
        self._cancel.set()

    def _onClose(self, event=None):
        self.cancelAndClose()
        self.EndModal(wx.ID_CANCEL)

    def _onCharHook(self, event):
        key = event.GetKeyCode()
        if key == wx.WXK_ESCAPE:
            self._onClose()
            return
        event.Skip()
