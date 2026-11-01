# Copyright (C) 2026 Mehmet Aykurt <m.aykurt38@gmail.com>
# Bu eklenti Mehmet Aykurt tarafından geliştirilmiştir.
# Lisans: GNU General Public License v2 (GPL-2.0)

"""Commit history and diff inspection operations for GitHub repositories."""

import addonHandler
addonHandler.initTranslation()

import json
import re
import socket
import urllib.error
import urllib.parse
import urllib.request

import ui
import wx

from .auth import AuthError, checkCancelled
from .credentials import CredentialError
from .downloader import USER_AGENT, _build_opener
from .errors import errorMessage
from .settings import SettingsError


def _check_cancelled(cancel):
    if cancel is not None:
        checkCancelled(cancel)


def listCommits(token, full_name, sha=None, page=1, cancel=None):
    """Fetches list of commits for a repository branch or default branch."""
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", full_name):
        raise AuthError("invalid_response")
    _check_cancelled(cancel)

    url = f"https://api.github.com/repos/{full_name}/commits?page={int(page)}&per_page=50"
    if sha:
        url += "&sha=" + urllib.parse.quote(sha, safe="")

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

    commits = []
    for item in data:
        if not isinstance(item, dict):
            continue
        c_obj = item.get("commit") or {}
        author_obj = c_obj.get("author") or {}
        author_name = author_obj.get("name") or ""
        author_date = (author_obj.get("date") or "")[:10]
        sha_str = item.get("sha") or ""
        message = (c_obj.get("message") or "").strip()
        first_line = message.splitlines()[0] if message else ""

        commits.append({
            "sha": sha_str,
            "short_sha": sha_str[:7],
            "message": first_line,
            "full_message": message,
            "author": author_name,
            "date": author_date,
        })
    return commits


def getCommitDetail(token, full_name, commit_sha, cancel=None):
    """Fetches full commit details, changed files and unified diff patches."""
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", full_name):
        raise AuthError("invalid_response")
    if not re.fullmatch(r"[0-9a-fA-F]{7,40}", commit_sha):
        raise AuthError("invalid_response")
    _check_cancelled(cancel)

    url = f"https://api.github.com/repos/{full_name}/commits/{commit_sha}"
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
            raise AuthError("not_found") from None
        if exc.code == 401:
            raise AuthError("unauthorized") from None
        if exc.code in (403, 429):
            raise AuthError("limited") from None
        raise AuthError("server_error") from None
    except (urllib.error.URLError, OSError, socket.timeout):
        raise AuthError("network") from None

    _check_cancelled(cancel)
    if not isinstance(data, dict):
        raise AuthError("invalid_response")

    c_obj = data.get("commit") or {}
    author_obj = c_obj.get("author") or {}
    stats_obj = data.get("stats") or {}

    files = []
    for f in (data.get("files") or []):
        if not isinstance(f, dict):
            continue
        files.append({
            "filename": f.get("filename") or "",
            "status": f.get("status") or "",
            "additions": f.get("additions") or 0,
            "deletions": f.get("deletions") or 0,
            "patch": f.get("patch") or "",
        })

    return {
        "sha": data.get("sha") or commit_sha,
        "message": (c_obj.get("message") or "").strip(),
        "author": author_obj.get("name") or "",
        "date": (author_obj.get("date") or "")[:19].replace("T", " "),
        "additions": stats_obj.get("additions") or 0,
        "deletions": stats_obj.get("deletions") or 0,
        "files": files,
    }


class CommitDetailDialog(wx.Dialog):
    """Accessible dialog for reviewing a commit's metadata and file diffs."""

    def __init__(self, parent, commit_detail):
        short_sha = (commit_detail.get("sha") or "")[:7]
        super().__init__(
            parent,
            title=_("Commit Details — %s") % short_sha,
            size=(800, 600),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        self.detail = commit_detail

        layout = wx.BoxSizer(wx.VERTICAL)

        info_label = wx.StaticText(self, label=_("&Commit information:"))
        layout.Add(info_label, 0, wx.ALL, 6)

        self.text_ctrl = wx.TextCtrl(
            self,
            value=self._formatText(commit_detail),
            style=wx.TE_MULTILINE | wx.TE_READONLY | wx.HSCROLL,
        )
        self.text_ctrl.SetName(_("Commit information"))
        layout.Add(self.text_ctrl, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        button_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.copy_btn = wx.Button(self, label=_("&Copy details"))
        self.copy_btn.Bind(wx.EVT_BUTTON, self._onCopy)
        button_sizer.Add(self.copy_btn, 0, wx.RIGHT, 10)

        self.close_btn = wx.Button(self, wx.ID_CANCEL, _("&Close"))
        self.close_btn.Bind(wx.EVT_BUTTON, self._onClose)
        button_sizer.Add(self.close_btn, 0)

        layout.Add(button_sizer, 0, wx.ALIGN_RIGHT | wx.RIGHT | wx.BOTTOM, 10)
        self.SetSizer(layout)
        self.SetMinSize((550, 420))
        self.CentreOnScreen()

        self.Bind(wx.EVT_CHAR_HOOK, self._onCharHook)
        wx.CallAfter(self.text_ctrl.SetFocus)

    def _formatText(self, d):
        lines = [
            f"{_('Commit:')} {d.get('sha') or ''}",
            f"{_('Author:')} {d.get('author') or ''} | {_('Date:')} {d.get('date') or ''}",
            f"{_('Changes:')} +{d.get('additions', 0)} / -{d.get('deletions', 0)}",
            "-" * 50,
            d.get("message") or "",
            "=" * 50,
            _("Changed Files:"),
        ]
        files = d.get("files") or []
        if not files:
            lines.append(_("(No file changes recorded.)"))
        for f in files:
            status = f.get("status", "")
            lines.append(f"\n[{status.upper()}] {f.get('filename', '')} (+{f.get('additions', 0)}, -{f.get('deletions', 0)})")
            patch = f.get("patch") or ""
            if patch:
                lines.append(patch)
        return "\n".join(lines)

    def _onCopy(self, event):
        text = self.text_ctrl.GetValue()
        if wx.TheClipboard.Open():
            try:
                wx.TheClipboard.SetData(wx.TextDataObject(text))
                ui.message(_("Commit details copied to clipboard."))
            finally:
                wx.TheClipboard.Close()
        else:
            ui.message(_("Clipboard could not be opened."))

    def _onCharHook(self, event):
        if event.GetKeyCode() == wx.WXK_ESCAPE:
            self._onClose()
            return
        event.Skip()

    def _onClose(self, event=None):
        if self.IsModal():
            self.EndModal(wx.ID_CANCEL)
        else:
            self.Close()
            self.Destroy()

    def cancelAndClose(self):
        if self.IsModal():
            self.EndModal(wx.ID_CANCEL)


class CommitsDialog(wx.Dialog):
    """Accessible dialog for browsing commits history on a repository branch."""

    def __init__(self, parent, full_name, service, branch=None):
        branch_label = f" ({branch})" if branch else ""
        super().__init__(
            parent,
            title=_("Commit History — %s%s") % (full_name, branch_label),
            size=(850, 520),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        self.full_name = full_name
        self.service = service
        self.branch = branch
        self.commits = []
        self._closing = False
        self._child_dlg = None

        layout = wx.BoxSizer(wx.VERTICAL)

        self.commits_list = wx.ListCtrl(self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        self.commits_list.SetName(_("Commits"))
        self.commits_list.InsertColumn(0, _("Commit"), width=90)
        self.commits_list.InsertColumn(1, _("Message"), width=340)
        self.commits_list.InsertColumn(2, _("Author"), width=150)
        self.commits_list.InsertColumn(3, _("Date"), width=110)

        self.commits_list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self._onViewCommit)
        self.commits_list.Bind(wx.EVT_KEY_DOWN, self._onListKey)
        layout.Add(self.commits_list, 1, wx.EXPAND | wx.ALL, 10)

        self.status_label = wx.StaticText(self, label="")
        layout.Add(self.status_label, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)

        button_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.view_btn = wx.Button(self, label=_("&Commit details…"))
        self.view_btn.Bind(wx.EVT_BUTTON, self._onViewCommit)
        button_sizer.Add(self.view_btn, 0, wx.RIGHT, 10)

        self.close_btn = wx.Button(self, wx.ID_CANCEL, _("&Close"))
        self.close_btn.Bind(wx.EVT_BUTTON, self._onClose)
        button_sizer.Add(self.close_btn, 0)

        layout.Add(button_sizer, 0, wx.ALIGN_RIGHT | wx.RIGHT | wx.BOTTOM, 10)
        self.SetSizer(layout)
        self.SetMinSize((650, 400))
        self.CentreOnScreen()

        self.Bind(wx.EVT_CLOSE, self._onClose)
        self.Bind(wx.EVT_CHAR_HOOK, self._onCharHook)
        wx.CallAfter(self.loadCommits)

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
            self.loadCommits()
            return
        event.Skip()

    def _onListKey(self, event):
        if event.GetKeyCode() == wx.WXK_RETURN:
            self._onViewCommit(None)
            return
        if event.GetKeyCode() == wx.WXK_F5:
            self.loadCommits()
            return
        event.Skip()

    def loadCommits(self):
        if self._closing or not self:
            return
        self._setStatus(_("Loading commits…"))
        self.commits_list.DeleteAllItems()

        import threading

        def thread_target():
            try:
                if hasattr(self.service, "loadCommits"):
                    result = self.service.loadCommits(self.full_name, branch=self.branch)
                else:
                    token = self.service.getAccessToken() if hasattr(self.service, "getAccessToken") else ""
                    result = listCommits(token, self.full_name, sha=self.branch)
                wx.CallAfter(self._onCommitsLoaded, result)
            except Exception as e:
                wx.CallAfter(self._onCommitsError, e)

        threading.Thread(target=thread_target, daemon=True).start()

    def _onCommitsLoaded(self, commits):
        if self._closing or not self:
            return
        self.commits = commits
        self.commits_list.DeleteAllItems()
        for idx, item in enumerate(commits):
            pos = self.commits_list.InsertItem(idx, item.get("short_sha") or "")
            self.commits_list.SetItem(pos, 1, item.get("message") or "")
            self.commits_list.SetItem(pos, 2, item.get("author") or "")
            self.commits_list.SetItem(pos, 3, item.get("date") or "")

        if commits:
            msg = _("%s commits listed.") % len(commits)
            self._setStatus(msg)
            ui.message(msg)
            self.commits_list.Select(0)
            self.commits_list.Focus(0)
            self.commits_list.SetFocus()
        else:
            msg = _("No commits found.")
            self._setStatus(msg)
            ui.message(msg)
            self.close_btn.SetFocus()

    def _onCommitsError(self, err):
        if self._closing or not self:
            return
        if isinstance(err, (AuthError, CredentialError, SettingsError, OSError)):
            msg = errorMessage(err)
        else:
            msg = _("Could not load commits.")
        self._setStatus(msg)
        ui.message(msg)

    def _selectedCommit(self):
        index = self.commits_list.GetFirstSelected()
        if 0 <= index < len(self.commits):
            return self.commits[index]
        return None

    def _onViewCommit(self, event):
        if self._closing or not self or self._child_dlg is not None:
            return
        commit = self._selectedCommit()
        if not commit:
            return

        sha = commit["sha"]
        load_msg = _("Loading commit details…")
        self._setStatus(load_msg)
        ui.message(load_msg)

        import threading

        def thread_target():
            try:
                if hasattr(self.service, "loadCommitDetail"):
                    detail = self.service.loadCommitDetail(self.full_name, sha)
                else:
                    token = self.service.getAccessToken() if hasattr(self.service, "getAccessToken") else ""
                    detail = getCommitDetail(token, self.full_name, sha)

                def show_detail():
                    if self._closing or not self or self._child_dlg is not None:
                        return
                    self._setStatus("")
                    self._runNestedModal(CommitDetailDialog(self, detail))

                wx.CallAfter(show_detail)
            except Exception as e:
                def on_err():
                    if self._closing or not self:
                        return
                    if isinstance(e, (AuthError, CredentialError, SettingsError, OSError)):
                        self._setStatus(errorMessage(e))
                    else:
                        self._setStatus(_("Could not load commit details."))

                wx.CallAfter(on_err)

        threading.Thread(target=thread_target, daemon=True).start()
