# Copyright (C) 2026 Mehmet Aykurt <m.aykurt38@gmail.com>
# Bu eklenti Mehmet Aykurt tarafından geliştirilmiştir.
# Lisans: GNU General Public License v2 (GPL-2.0)

"""Accessible file content viewer dialog and text retrieval for GitHub files."""

import addonHandler
addonHandler.initTranslation()

import os
import re
import socket
import urllib.error
import urllib.parse
import urllib.request

import ui
import wx

from .auth import AuthError, checkCancelled
from .downloader import USER_AGENT, _build_opener


def _check_cancelled(cancel):
    if cancel is not None:
        checkCancelled(cancel)


def fetchFileContent(token, full_name, file_path, cancel=None, max_size=5 * 1024 * 1024, ref=None):
    """Fetches the raw text of a file from GitHub.

    Returns dict:
      {"text": str, "is_binary": False} or {"is_binary": True, "size": int}
    """
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", full_name):
        raise AuthError("invalid_response")
    _check_cancelled(cancel)

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

    try:
        with opener.open(req, timeout=30) as response:
            data = response.read(max_size + 1)
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

    if len(data) > max_size:
        raise AuthError("file_too_large")

    # Detect binary content (null bytes in first 4KB)
    sample = data[:4096]
    if b"\x00" in sample:
        return {"is_binary": True, "size": len(data)}

    # Attempt decoding with UTF-8, then fallback to cp1254/latin-1
    for enc in ("utf-8", "utf-8-sig", "cp1254", "iso-8859-9", "latin-1"):
        try:
            text = data.decode(enc)
            return {"text": text, "is_binary": False}
        except UnicodeError:
            continue

    return {"is_binary": True, "size": len(data)}


class FileViewerDialog(wx.Dialog):
    """Accessible modal/modeless dialog for reviewing text files."""

    def __init__(self, parent, file_name, repo_name, content_text, on_edit=None):
        title = _("GitHub — %s (%s)") % (file_name, repo_name)
        super().__init__(
            parent,
            title=title,
            size=(800, 600),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        self.file_name = file_name
        self.repo_name = repo_name
        self.content_text = content_text
        self.on_edit = on_edit

        layout = wx.BoxSizer(wx.VERTICAL)

        info_label = wx.StaticText(self, label=_("Content of file: %s") % file_name)
        layout.Add(info_label, 0, wx.ALL, 10)

        self.text_ctrl = wx.TextCtrl(
            self,
            value=content_text,
            style=wx.TE_MULTILINE | wx.TE_READONLY | wx.HSCROLL,
        )
        self.text_ctrl.SetName(_("File content"))
        layout.Add(self.text_ctrl, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        button_sizer = wx.BoxSizer(wx.HORIZONTAL)

        if self.on_edit is not None:
            self.edit_btn = wx.Button(self, label=_("&Edit file…"))
            self.edit_btn.Bind(wx.EVT_BUTTON, self._onEditClicked)
            button_sizer.Add(self.edit_btn, 0, wx.RIGHT, 10)

        self.copy_btn = wx.Button(self, label=_("&Copy all content"))
        self.copy_btn.Bind(wx.EVT_BUTTON, self._onCopy)
        button_sizer.Add(self.copy_btn, 0, wx.RIGHT, 10)

        self.close_btn = wx.Button(self, wx.ID_CANCEL, _("&Close"))
        self.close_btn.Bind(wx.EVT_BUTTON, self._onClose)
        button_sizer.Add(self.close_btn, 0)

        layout.Add(button_sizer, 0, wx.ALIGN_RIGHT | wx.RIGHT | wx.BOTTOM, 10)

        self.SetSizer(layout)
        self.SetMinSize((500, 400))
        self.CentreOnScreen()

        self.Bind(wx.EVT_CHAR_HOOK, self._onCharHook)
        wx.CallAfter(self.text_ctrl.SetFocus)

    def _onEditClicked(self, event):
        if callable(self.on_edit):
            self.on_edit(self)

    def setContent(self, new_text):
        self.content_text = new_text
        self.text_ctrl.SetValue(new_text)

    def _onCharHook(self, event):
        if event.GetKeyCode() == wx.WXK_ESCAPE:
            self._onClose()
            return
        event.Skip()

    def _onCopy(self, event):
        if wx.TheClipboard.Open():
            try:
                wx.TheClipboard.SetData(wx.TextDataObject(self.content_text))
                ui.message(_("All content copied to clipboard."))
            finally:
                wx.TheClipboard.Close()
        else:
            ui.message(_("Clipboard could not be opened."))

    def cancelAndClose(self):
        if self.IsModal():
            self.EndModal(wx.ID_CANCEL)

    def _onClose(self, event=None):
        if self.IsModal():
            self.EndModal(wx.ID_CANCEL)
        else:
            self.Destroy()


class FileEditorDialog(wx.Dialog):
    """Accessible dialog for directly editing and saving file text on GitHub."""

    def __init__(self, parent, file_name, repo_name, content_text):
        title = _("Edit File — %s (%s)") % (file_name, repo_name)
        super().__init__(
            parent,
            title=title,
            size=(850, 620),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        self.file_name = file_name
        self.repo_name = repo_name
        self._saved_data = None

        layout = wx.BoxSizer(wx.VERTICAL)

        info_label = wx.StaticText(self, label=_("&File content (%s):") % file_name)
        layout.Add(info_label, 0, wx.ALL, 8)

        self.text_ctrl = wx.TextCtrl(
            self,
            value=content_text,
            style=wx.TE_MULTILINE | wx.HSCROLL,
        )
        self.text_ctrl.SetName(_("File content"))
        layout.Add(self.text_ctrl, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        msg_label = wx.StaticText(self, label=_("&Commit message:"))
        layout.Add(msg_label, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 4)

        default_commit = _("Update %s") % file_name
        self.commit_ctrl = wx.TextCtrl(self, value=default_commit)
        self.commit_ctrl.SetName(_("Commit message"))
        layout.Add(self.commit_ctrl, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        button_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.save_btn = wx.Button(self, wx.ID_OK, _("&Save"))
        self.save_btn.SetDefault()
        self.save_btn.Bind(wx.EVT_BUTTON, self._onSave)
        button_sizer.Add(self.save_btn, 0, wx.RIGHT, 10)

        self.cancel_btn = wx.Button(self, wx.ID_CANCEL, _("&Cancel"))
        self.cancel_btn.Bind(wx.EVT_BUTTON, self._onCancel)
        button_sizer.Add(self.cancel_btn, 0)

        layout.Add(button_sizer, 0, wx.ALIGN_RIGHT | wx.RIGHT | wx.BOTTOM, 10)
        self.SetSizer(layout)
        self.SetMinSize((550, 450))
        self.CentreOnScreen()

        self.Bind(wx.EVT_CHAR_HOOK, self._onCharHook)
        wx.CallAfter(self.text_ctrl.SetFocus)

    def _onCharHook(self, event):
        if event.GetKeyCode() == wx.WXK_ESCAPE:
            self._onCancel()
            return
        if event.GetKeyCode() == ord("S") and event.ControlDown() and not event.ShiftDown() and not event.AltDown():
            self._onSave(None)
            return
        event.Skip()

    def _onSave(self, event):
        msg = self.commit_ctrl.GetValue().strip()
        if not msg:
            wx.MessageBox(_("Please enter a commit message."), _("Error"), wx.OK | wx.ICON_ERROR, self)
            self.commit_ctrl.SetFocus()
            return
        text = self.text_ctrl.GetValue()
        self._saved_data = (text.encode("utf-8"), msg, text)
        if self.IsModal():
            self.EndModal(wx.ID_OK)
        else:
            self.Close()

    def _onCancel(self, event=None):
        if self.IsModal():
            self.EndModal(wx.ID_CANCEL)
        else:
            self.Close()
            self.Destroy()

    def cancelAndClose(self):
        if self.IsModal():
            self.EndModal(wx.ID_CANCEL)

    def getData(self):
        return self._saved_data
