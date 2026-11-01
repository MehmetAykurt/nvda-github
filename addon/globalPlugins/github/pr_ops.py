# Copyright (C) 2026 Mehmet Aykurt <m.aykurt38@gmail.com>
# Bu eklenti Mehmet Aykurt tarafından geliştirilmiştir.
# Lisans: GNU General Public License v2 (GPL-2.0)

"""Pull Requests operations, diff review, and merging for GitHub repositories."""

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
from .issue_ops import NewCommentDialog
from .settings import SettingsError


def formatTime(timestamp):
    if not timestamp:
        return ""
    return str(timestamp).replace("T", " ").replace("Z", "")[:16]


def _check_cancelled(cancel):
    if cancel is not None:
        checkCancelled(cancel)


def listPullRequests(token, full_name, state="open", cancel=None):
    """Fetches list of pull requests for a repository."""
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", full_name):
        raise AuthError("invalid_response")
    _check_cancelled(cancel)

    state_param = state if state in ("open", "closed", "all") else "open"
    url = f"https://api.github.com/repos/{full_name}/pulls?state={state_param}&per_page=100"
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

    prs = []
    for item in data:
        if not isinstance(item, dict):
            continue
        user_obj = item.get("user") or {}
        head_obj = item.get("head") or {}
        base_obj = item.get("base") or {}
        prs.append({
            "number": item.get("number") or 0,
            "title": item.get("title") or "",
            "state": item.get("state") or "open",
            "user": user_obj.get("login") or "" if isinstance(user_obj, dict) else "",
            "head": head_obj.get("ref") or "" if isinstance(head_obj, dict) else "",
            "base": base_obj.get("ref") or "" if isinstance(base_obj, dict) else "",
            "comments": item.get("comments") or 0,
            "created_at": item.get("created_at") or "",
            "body": item.get("body") or "",
            "html_url": item.get("html_url") or "",
            "merged": bool(item.get("merged_at")),
        })
    return prs


def getPullRequest(token, full_name, number, cancel=None):
    """Fetches full details of a single pull request."""
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", full_name):
        raise AuthError("invalid_response")
    _check_cancelled(cancel)

    url = f"https://api.github.com/repos/{full_name}/pulls/{int(number)}"
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/vnd.github.v3+json",
        "Authorization": f"Bearer {token}",
    }
    req = urllib.request.Request(url, headers=headers)
    opener = _build_opener()

    try:
        with opener.open(req, timeout=30) as resp:
            item = json.loads(resp.read().decode("utf-8"))
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
    if not isinstance(item, dict):
        raise AuthError("invalid_response")

    user_obj = item.get("user") or {}
    head_obj = item.get("head") or {}
    base_obj = item.get("base") or {}
    return {
        "number": item.get("number") or 0,
        "title": item.get("title") or "",
        "state": item.get("state") or "open",
        "user": user_obj.get("login") or "" if isinstance(user_obj, dict) else "",
        "head": head_obj.get("ref") or "" if isinstance(head_obj, dict) else "",
        "base": base_obj.get("ref") or "" if isinstance(base_obj, dict) else "",
        "comments": item.get("comments") or 0,
        "created_at": item.get("created_at") or "",
        "body": item.get("body") or "",
        "html_url": item.get("html_url") or "",
        "mergeable": item.get("mergeable"),
        "merged": bool(item.get("merged_at")),
    }


def getPullRequestFiles(token, full_name, number, cancel=None):
    """Fetches list of changed files and diffs for a pull request."""
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", full_name):
        raise AuthError("invalid_response")
    _check_cancelled(cancel)

    url = f"https://api.github.com/repos/{full_name}/pulls/{int(number)}/files?per_page=100"
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

    files = []
    for f in data:
        if not isinstance(f, dict):
            continue
        files.append({
            "filename": f.get("filename") or "",
            "status": f.get("status") or "",
            "additions": f.get("additions") or 0,
            "deletions": f.get("deletions") or 0,
            "patch": f.get("patch") or "",
        })
    return files


def createPullRequest(token, full_name, title, head, base, body="", cancel=None):
    """Creates a new pull request on GitHub."""
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", full_name):
        raise AuthError("invalid_response")
    if not title or not head or not base:
        raise AuthError("invalid_response")
    _check_cancelled(cancel)

    url = f"https://api.github.com/repos/{full_name}/pulls"
    payload = json.dumps({
        "title": title,
        "head": head,
        "base": base,
        "body": body,
    }).encode("utf-8")

    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/vnd.github.v3+json",
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
    opener = _build_opener()

    try:
        with opener.open(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 422:
            raise AuthError("pr_exists_or_invalid") from None
        if exc.code == 401:
            raise AuthError("unauthorized") from None
        if exc.code in (403, 429):
            raise AuthError("limited") from None
        raise AuthError("server_error") from None
    except (urllib.error.URLError, OSError, socket.timeout):
        raise AuthError("network") from None


def mergePullRequest(token, full_name, number, commit_title="", commit_message="", merge_method="merge", cancel=None):
    """Merges a pull request on GitHub."""
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", full_name):
        raise AuthError("invalid_response")
    _check_cancelled(cancel)

    url = f"https://api.github.com/repos/{full_name}/pulls/{int(number)}/merge"
    payload_dict = {"merge_method": merge_method}
    if commit_title:
        payload_dict["commit_title"] = commit_title
    if commit_message:
        payload_dict["commit_message"] = commit_message

    payload = json.dumps(payload_dict).encode("utf-8")
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/vnd.github.v3+json",
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    req = urllib.request.Request(url, data=payload, headers=headers, method="PUT")
    opener = _build_opener()

    try:
        with opener.open(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 405:
            raise AuthError("merge_not_allowed") from None
        if exc.code == 409:
            raise AuthError("merge_conflict") from None
        if exc.code == 401:
            raise AuthError("unauthorized") from None
        if exc.code in (403, 429):
            raise AuthError("limited") from None
        raise AuthError("server_error") from None
    except (urllib.error.URLError, OSError, socket.timeout):
        raise AuthError("network") from None


def setPullRequestState(token, full_name, number, state="closed", cancel=None):
    """Opens or closes a pull request."""
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", full_name):
        raise AuthError("invalid_response")
    _check_cancelled(cancel)

    url = f"https://api.github.com/repos/{full_name}/pulls/{int(number)}"
    payload = json.dumps({"state": state}).encode("utf-8")
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/vnd.github.v3+json",
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    req = urllib.request.Request(url, data=payload, headers=headers, method="PATCH")
    opener = _build_opener()

    try:
        with opener.open(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            raise AuthError("unauthorized") from None
        if exc.code in (403, 429):
            raise AuthError("limited") from None
        raise AuthError("server_error") from None
    except (urllib.error.URLError, OSError, socket.timeout):
        raise AuthError("network") from None


class NewPullRequestDialog(wx.Dialog):
    """Accessible dialog for opening a new pull request between branches."""

    def __init__(self, parent, full_name, branches, current_branch):
        super().__init__(
            parent,
            title=_("Open New Pull Request — %s") % full_name,
            size=(580, 520),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        self.branches = branches or []

        layout = wx.BoxSizer(wx.VERTICAL)

        # Title
        title_label = wx.StaticText(self, label=_("&Title:"))
        layout.Add(title_label, 0, wx.ALL, 6)
        self.title_ctrl = wx.TextCtrl(self)
        self.title_ctrl.SetName(_("Title"))
        layout.Add(self.title_ctrl, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        # Head branch (source / compare)
        head_label = wx.StaticText(self, label=_("&Source branch (Head):"))
        layout.Add(head_label, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 4)
        self.head_choice = wx.Choice(self, choices=self.branches)
        if current_branch in self.branches:
            self.head_choice.SetSelection(self.branches.index(current_branch))
        elif self.branches:
            self.head_choice.SetSelection(0)
        self.head_choice.SetName(_("Source branch"))
        layout.Add(self.head_choice, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        # Base branch (target)
        base_label = wx.StaticText(self, label=_("&Target branch (Base):"))
        layout.Add(base_label, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 4)
        self.base_choice = wx.Choice(self, choices=self.branches)
        # Default target: main or master or second branch
        target_idx = 0
        for b_name in ("main", "master"):
            if b_name in self.branches:
                target_idx = self.branches.index(b_name)
                break
        if self.branches:
            self.base_choice.SetSelection(target_idx)
        self.base_choice.SetName(_("Target branch"))
        layout.Add(self.base_choice, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        # Description (body)
        body_label = wx.StaticText(self, label=_("&Description (optional):"))
        layout.Add(body_label, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 4)
        self.body_ctrl = wx.TextCtrl(self, style=wx.TE_MULTILINE)
        self.body_ctrl.SetName(_("Description"))
        layout.Add(self.body_ctrl, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        # Buttons
        button_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.ok_btn = wx.Button(self, wx.ID_OK, _("&Create pull request"))
        self.ok_btn.SetDefault()
        self.ok_btn.Bind(wx.EVT_BUTTON, self._onSubmit)
        button_sizer.Add(self.ok_btn, 0, wx.RIGHT, 10)

        self.cancel_btn = wx.Button(self, wx.ID_CANCEL, _("&Cancel"))
        button_sizer.Add(self.cancel_btn, 0)

        layout.Add(button_sizer, 0, wx.ALIGN_RIGHT | wx.RIGHT | wx.BOTTOM, 10)
        self.SetSizer(layout)
        self.SetMinSize((480, 440))
        self.CentreOnScreen()

        wx.CallAfter(self.title_ctrl.SetFocus)

    def _onSubmit(self, event):
        title = self.title_ctrl.GetValue().strip()
        if not title:
            wx.MessageBox(_("Please enter a title for the pull request."), _("Error"), wx.OK | wx.ICON_ERROR, self)
            self.title_ctrl.SetFocus()
            return
        head = self.head_choice.GetStringSelection()
        base = self.base_choice.GetStringSelection()
        if head == base:
            wx.MessageBox(_("Source and target branches cannot be the same."), _("Error"), wx.OK | wx.ICON_ERROR, self)
            self.head_choice.SetFocus()
            return
        self.EndModal(wx.ID_OK)

    def getData(self):
        return {
            "title": self.title_ctrl.GetValue().strip(),
            "head": self.head_choice.GetStringSelection(),
            "base": self.base_choice.GetStringSelection(),
            "body": self.body_ctrl.GetValue(),
        }

    def cancelAndClose(self):
        if self.IsModal():
            self.EndModal(wx.ID_CANCEL)


class PullRequestDetailDialog(wx.Dialog):
    """Accessible dialog for reviewing pull request metadata, diffs, comments, and merging."""

    def __init__(self, parent, pr_dict, files, comments, on_add_comment=None, on_merge=None, on_toggle_state=None):
        num = pr_dict.get("number") or 0
        super().__init__(
            parent,
            title=_("Pull Request #%s — %s") % (num, pr_dict.get("title") or ""),
            size=(850, 620),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        self.pr = pr_dict
        self.files = files or []
        self.comments = comments or []
        self.on_add_comment = on_add_comment
        self.on_merge = on_merge
        self.on_toggle_state = on_toggle_state
        self._closing = False
        self._child_dlg = None

        layout = wx.BoxSizer(wx.VERTICAL)

        info_label = wx.StaticText(self, label=_("&Pull request details and changes:"))
        layout.Add(info_label, 0, wx.ALL, 6)

        self.text_ctrl = wx.TextCtrl(
            self,
            value=self._formatFullText(pr_dict, files, comments),
            style=wx.TE_MULTILINE | wx.TE_READONLY | wx.HSCROLL,
        )
        self.text_ctrl.SetName(_("Pull request details"))
        layout.Add(self.text_ctrl, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        button_sizer = wx.BoxSizer(wx.HORIZONTAL)

        is_open = pr_dict.get("state") == "open"
        if on_merge is not None and is_open and not pr_dict.get("merged"):
            self.merge_btn = wx.Button(self, label=_("&Merge pull request…"))
            self.merge_btn.Bind(wx.EVT_BUTTON, lambda e: self.on_merge(self))
            button_sizer.Add(self.merge_btn, 0, wx.RIGHT, 10)

        if on_add_comment is not None:
            self.comment_btn = wx.Button(self, label=_("&Add comment…"))
            self.comment_btn.Bind(wx.EVT_BUTTON, lambda e: self.on_add_comment(self))
            button_sizer.Add(self.comment_btn, 0, wx.RIGHT, 10)

        if on_toggle_state is not None and not pr_dict.get("merged"):
            state_label = _("&Close pull request") if is_open else _("&Reopen pull request")
            self.toggle_state_btn = wx.Button(self, label=state_label)
            self.toggle_state_btn.Bind(wx.EVT_BUTTON, lambda e: self.on_toggle_state(self))
            button_sizer.Add(self.toggle_state_btn, 0, wx.RIGHT, 10)

        self.copy_btn = wx.Button(self, label=_("&Copy details"))
        self.copy_btn.Bind(wx.EVT_BUTTON, self._onCopy)
        button_sizer.Add(self.copy_btn, 0, wx.RIGHT, 10)

        self.close_btn = wx.Button(self, wx.ID_CANCEL, _("&Close"))
        self.close_btn.Bind(wx.EVT_BUTTON, self._onClose)
        button_sizer.Add(self.close_btn, 0)

        layout.Add(button_sizer, 0, wx.ALIGN_RIGHT | wx.RIGHT | wx.BOTTOM, 10)
        self.SetSizer(layout)
        self.SetMinSize((600, 450))
        self.CentreOnScreen()

        self.Bind(wx.EVT_CHAR_HOOK, self._onCharHook)
        wx.CallAfter(self.text_ctrl.SetFocus)

    def _formatFullText(self, pr, files, comments):
        state_label = _("Closed") if pr.get("state") == "closed" else _("Open")
        if pr.get("merged"):
            state_label = _("Merged")
        lines = [
            f"{_('Pull Request:')} #{pr.get('number')} - {pr.get('title')}",
            f"{_('State:')} {state_label} | {_('Author:')} {pr.get('user')} | {_('Date:')} {formatTime(pr.get('created_at'))}",
            f"{_('Branches:')} {pr.get('head')} -> {pr.get('base')}",
            "=" * 50,
            _("Description:"),
            (pr.get("body") or "").strip() or _("(No description provided.)"),
            "=" * 50,
            _("Changed Files (%s):") % (len(files) if files is not None else 0),
        ]
        if files is None:
            lines.append(_("(Could not load file changes.)"))
        elif not files:
            lines.append(_("(No files changed.)"))
        else:
            for f in files:
                lines.append(f"\n[{f.get('status', '').upper()}] {f.get('filename', '')} (+{f.get('additions', 0)}, -{f.get('deletions', 0)})")
                patch = f.get("patch") or ""
                if patch:
                    lines.append(patch)

        lines.append("\n" + "=" * 50)
        lines.append(_("Comments (%s):") % (len(comments) if comments is not None else 0))
        if comments is None:
            lines.append(_("(Could not load comments.)"))
        elif not comments:
            lines.append(_("(No comments yet.)"))
        else:
            for c in comments:
                author = c.get("user") or ""
                created = formatTime(c.get("created_at"))
                body = (c.get("body") or "").strip()
                lines.append(f"\n--- {author} ({created}) ---\n{body}")

        return "\n".join(lines)

    def _onCopy(self, event):
        text = self.text_ctrl.GetValue()
        if wx.TheClipboard.Open():
            try:
                wx.TheClipboard.SetData(wx.TextDataObject(text))
                ui.message(_("Pull request details copied to clipboard."))
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

    def cancelAndClose(self):
        self._closing = True
        if self._child_dlg is not None:
            if hasattr(self._child_dlg, "cancelAndClose"):
                self._child_dlg.cancelAndClose()
            elif self._child_dlg.IsModal():
                self._child_dlg.EndModal(wx.ID_CANCEL)
        if self.IsModal():
            self.EndModal(wx.ID_CANCEL)


class PullRequestsDialog(wx.Dialog):
    """Accessible dialog for listing and managing repository pull requests."""

    def __init__(self, parent, full_name, service):
        super().__init__(
            parent,
            title=_("Pull Requests — %s") % full_name,
            size=(850, 550),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        self.full_name = full_name
        self.service = service
        self.prs = []
        self._closing = False
        self._child_dlg = None
        self._loading_detail = False

        layout = wx.BoxSizer(wx.VERTICAL)

        # Filter row
        filter_row = wx.BoxSizer(wx.HORIZONTAL)
        filter_label = wx.StaticText(self, label=_("&Filter:"))
        filter_row.Add(filter_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)

        self.filter_choice = wx.Choice(self, choices=[_("Open"), _("Closed"), _("All")])
        self.filter_choice.SetSelection(0)
        self.filter_choice.SetName(_("Filter"))
        self.filter_choice.Bind(wx.EVT_CHOICE, self._onFilterChanged)
        filter_row.Add(self.filter_choice, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 15)
        layout.Add(filter_row, 0, wx.ALL, 10)

        # PRs list
        self.prs_list = wx.ListCtrl(self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        self.prs_list.SetName(_("Pull Requests"))
        self.prs_list.InsertColumn(0, _("Number"), width=75)
        self.prs_list.InsertColumn(1, _("State"), width=90)
        self.prs_list.InsertColumn(2, _("Title"), width=280)
        self.prs_list.InsertColumn(3, _("Author"), width=120)
        self.prs_list.InsertColumn(4, _("Branches"), width=150)
        self.prs_list.InsertColumn(5, _("Date"), width=110)

        self.prs_list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self._onViewPR)
        self.prs_list.Bind(wx.EVT_KEY_DOWN, self._onListKey)
        layout.Add(self.prs_list, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        # Status text
        self.status_label = wx.StaticText(self, label="")
        layout.Add(self.status_label, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)

        # Buttons
        button_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.view_btn = wx.Button(self, label=_("&View pull request…"))
        self.view_btn.Bind(wx.EVT_BUTTON, self._onViewPR)
        button_sizer.Add(self.view_btn, 0, wx.RIGHT, 10)

        self.new_btn = wx.Button(self, label=_("&New pull request…"))
        self.new_btn.Bind(wx.EVT_BUTTON, self._onNewPR)
        button_sizer.Add(self.new_btn, 0, wx.RIGHT, 10)

        self.close_btn = wx.Button(self, wx.ID_CANCEL, _("&Close"))
        self.close_btn.Bind(wx.EVT_BUTTON, self._onClose)
        button_sizer.Add(self.close_btn, 0)

        layout.Add(button_sizer, 0, wx.ALIGN_RIGHT | wx.RIGHT | wx.BOTTOM, 10)
        self.SetSizer(layout)
        self.SetMinSize((650, 420))
        self.CentreOnScreen()

        self.Bind(wx.EVT_CLOSE, self._onClose)
        self.Bind(wx.EVT_CHAR_HOOK, self._onCharHook)
        wx.CallAfter(self.loadPRs)

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
            self.loadPRs()
            return
        if event.GetKeyCode() == ord("N") and event.ControlDown() and not event.ShiftDown() and not event.AltDown():
            self._onNewPR(None)
            return
        event.Skip()

    def _onListKey(self, event):
        if event.GetKeyCode() == wx.WXK_RETURN:
            self._onViewPR(None)
            return
        if event.GetKeyCode() == ord("N") and event.ControlDown() and not event.ShiftDown():
            self._onNewPR(None)
            return
        if event.GetKeyCode() == wx.WXK_F5:
            self.loadPRs()
            return
        event.Skip()

    def _onFilterChanged(self, event):
        self.loadPRs()

    def loadPRs(self):
        if self._closing or not self:
            return
        self._setStatus(_("Loading pull requests…"))
        self.prs_list.DeleteAllItems()
        sel = self.filter_choice.GetSelection()
        state = "open" if sel == 0 else ("closed" if sel == 1 else "all")

        import threading

        def thread_target():
            try:
                if hasattr(self.service, "loadPullRequests"):
                    result = self.service.loadPullRequests(self.full_name, state=state)
                else:
                    token = self.service.getAccessToken() if hasattr(self.service, "getAccessToken") else ""
                    result = listPullRequests(token, self.full_name, state=state)
                wx.CallAfter(self._onPRsLoaded, result)
            except Exception as e:
                wx.CallAfter(self._onPRsError, e)

        threading.Thread(target=thread_target, daemon=True).start()

    def _onPRsLoaded(self, prs):
        if self._closing or not self:
            return
        self.prs = prs
        self.prs_list.DeleteAllItems()
        for idx, item in enumerate(prs):
            pos = self.prs_list.InsertItem(idx, f"#{item['number']}")
            state_label = _("Merged") if item.get("merged") else (_("Closed") if item.get("state") == "closed" else _("Open"))
            self.prs_list.SetItem(pos, 1, state_label)
            self.prs_list.SetItem(pos, 2, item.get("title") or "")
            self.prs_list.SetItem(pos, 3, item.get("user") or "")
            branches_str = f"{item.get('head')} -> {item.get('base')}"
            self.prs_list.SetItem(pos, 4, branches_str)
            date_str = (item.get("created_at") or "")[:10]
            self.prs_list.SetItem(pos, 5, date_str)

        if prs:
            msg = _("%s pull requests listed.") % len(prs)
            self._setStatus(msg)
            ui.message(msg)
            self.prs_list.Select(0)
            self.prs_list.Focus(0)
            self.prs_list.SetFocus()
        else:
            msg = _("No pull requests found.")
            self._setStatus(msg)
            ui.message(msg)
            self.filter_choice.SetFocus()

    def _onPRsError(self, err):
        if self._closing or not self:
            return
        if isinstance(err, (AuthError, CredentialError, SettingsError, OSError)):
            msg = errorMessage(err)
        else:
            msg = _("Could not load pull requests.")
        self._setStatus(msg)
        ui.message(msg)

    def _selectedPR(self):
        index = self.prs_list.GetFirstSelected()
        if 0 <= index < len(self.prs):
            return self.prs[index]
        return None

    def _onViewPR(self, event, target_pr=None):
        if self._closing or not self or self._loading_detail or self._child_dlg is not None:
            return
        pr = target_pr if target_pr is not None else self._selectedPR()
        if not pr:
            return

        self._loading_detail = True
        load_msg = _("Loading pull request…")
        self._setStatus(load_msg)
        ui.message(load_msg)

        import threading

        def thread_target():
            comments = None
            files = None
            try:
                if hasattr(self.service, "loadPullRequestFiles"):
                    files = self.service.loadPullRequestFiles(self.full_name, pr["number"])
                else:
                    token = self.service.getAccessToken() if hasattr(self.service, "getAccessToken") else ""
                    files = getPullRequestFiles(token, self.full_name, pr["number"])
            except Exception:
                files = None

            try:
                if hasattr(self.service, "loadIssueComments"):
                    comments = self.service.loadIssueComments(self.full_name, pr["number"])
            except Exception:
                comments = None

            def show_dlg():
                self._loading_detail = False
                if self._closing or not self or self._child_dlg is not None:
                    return
                self._setStatus("")

                def on_add_comment(parent_dlg):
                    c_dlg = NewCommentDialog(parent_dlg, pr.get("title") or "")
                    text = ""
                    parent_dlg._child_dlg = c_dlg
                    try:
                        if c_dlg.ShowModal() == wx.ID_OK:
                            text = c_dlg.getCommentText()
                    finally:
                        c_dlg.cancelAndClose()
                        parent_dlg._child_dlg = None
                        c_dlg.Destroy()
                    if not text or parent_dlg._closing or self._closing:
                        return
                    parent_dlg.comment_btn.Enable(False)

                    def comment_worker():
                        try:
                            self.service.addIssueComment(self.full_name, pr["number"], text)

                            def on_comment_ok():
                                ui.message(_("Comment added successfully."))
                                if parent_dlg and not parent_dlg._closing:
                                    parent_dlg._onClose()
                                if not self._closing and self:
                                    wx.CallAfter(self._onViewPR, None, pr)

                            wx.CallAfter(on_comment_ok)
                        except Exception as err:
                            def on_comment_err():
                                if parent_dlg and not parent_dlg._closing:
                                    parent_dlg.comment_btn.Enable(True)
                                if isinstance(err, (AuthError, CredentialError, SettingsError, OSError)):
                                    ui.message(errorMessage(err))
                                else:
                                    ui.message(_("Failed to add comment."))

                            wx.CallAfter(on_comment_err)

                    threading.Thread(target=comment_worker, daemon=True).start()

                def on_merge(parent_dlg):
                    answer = wx.MessageBox(
                        _("Are you sure you want to merge pull request #%s into '%s'?") % (pr["number"], pr.get("base")),
                        _("Merge Pull Request"),
                        wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION,
                        parent_dlg,
                    )
                    if answer != wx.YES or parent_dlg._closing or self._closing:
                        return
                    parent_dlg.merge_btn.Enable(False)

                    def merge_worker():
                        try:
                            if hasattr(self.service, "mergePullRequest"):
                                self.service.mergePullRequest(self.full_name, pr["number"])
                            else:
                                token = self.service.getAccessToken() if hasattr(self.service, "getAccessToken") else ""
                                mergePullRequest(token, self.full_name, pr["number"])

                            def on_merge_ok():
                                ui.message(_("Pull request merged successfully."))
                                if parent_dlg and not parent_dlg._closing:
                                    parent_dlg._onClose()
                                if not self._closing and self:
                                    self.loadPRs()

                            wx.CallAfter(on_merge_ok)
                        except Exception as err:
                            def on_merge_err():
                                if parent_dlg and not parent_dlg._closing:
                                    parent_dlg.merge_btn.Enable(True)
                                if isinstance(err, (AuthError, CredentialError, SettingsError, OSError)):
                                    ui.message(errorMessage(err))
                                else:
                                    ui.message(_("Failed to merge pull request."))

                            wx.CallAfter(on_merge_err)

                    threading.Thread(target=merge_worker, daemon=True).start()

                def on_toggle_state(parent_dlg):
                    new_state = "open" if pr.get("state") == "closed" else "closed"
                    parent_dlg.toggle_state_btn.Enable(False)

                    def state_worker():
                        try:
                            if hasattr(self.service, "setPullRequestState"):
                                self.service.setPullRequestState(self.full_name, pr["number"], state=new_state)
                            else:
                                token = self.service.getAccessToken() if hasattr(self.service, "getAccessToken") else ""
                                setPullRequestState(token, self.full_name, pr["number"], state=new_state)
                            pr["state"] = new_state

                            def on_state_ok():
                                action_msg = _("Pull request closed.") if new_state == "closed" else _("Pull request reopened.")
                                ui.message(action_msg)
                                if parent_dlg and not parent_dlg._closing:
                                    parent_dlg._onClose()
                                if not self._closing and self:
                                    self.loadPRs()

                            wx.CallAfter(on_state_ok)
                        except Exception as err:
                            def on_state_err():
                                if parent_dlg and not parent_dlg._closing:
                                    parent_dlg.toggle_state_btn.Enable(True)
                                if isinstance(err, (AuthError, CredentialError, SettingsError, OSError)):
                                    ui.message(errorMessage(err))
                                else:
                                    ui.message(_("Failed to change pull request state."))

                            wx.CallAfter(on_state_err)

                    threading.Thread(target=state_worker, daemon=True).start()

                self._runNestedModal(PullRequestDetailDialog(self, pr, files, comments, on_add_comment, on_merge, on_toggle_state))

            wx.CallAfter(show_dlg)

        threading.Thread(target=thread_target, daemon=True).start()

    def _onNewPR(self, event=None):
        if self._closing or not self or self._child_dlg is not None or getattr(self, "_opening_new_pr", False):
            return

        self._opening_new_pr = True
        self._setStatus(_("Loading branches…"))
        ui.message(_("Loading branches…"))

        import threading

        def thread_target():
            branches = []
            try:
                if hasattr(self.service, "loadBranches"):
                    branches = self.service.loadBranches(self.full_name)
            except Exception:
                branches = []

            def show_dlg():
                self._opening_new_pr = False
                if self._closing or not self or self._child_dlg is not None:
                    return
                self._setStatus("")

                if not branches or len(branches) < 2:
                    ui.message(_("At least two branches are required to create a pull request."))
                    return

                dlg = NewPullRequestDialog(self, self.full_name, branches, branches[0])
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

                start_msg = _("Creating pull request…")
                self._setStatus(start_msg)
                ui.message(start_msg)

                def create_target():
                    try:
                        if hasattr(self.service, "createPullRequest"):
                            self.service.createPullRequest(
                                self.full_name,
                                data["title"],
                                data["head"],
                                data["base"],
                                body=data.get("body", ""),
                            )
                        else:
                            token = self.service.getAccessToken() if hasattr(self.service, "getAccessToken") else ""
                            createPullRequest(
                                token,
                                self.full_name,
                                data["title"],
                                data["head"],
                                data["base"],
                                body=data.get("body", ""),
                            )

                        def on_created():
                            ui.message(_("Pull request created successfully."))
                            if not self._closing and self:
                                self.loadPRs()

                        wx.CallAfter(on_created)
                    except Exception as err:
                        def on_create_err():
                            if isinstance(err, (AuthError, CredentialError, SettingsError, OSError)):
                                self._setStatus(errorMessage(err))
                                ui.message(errorMessage(err))
                            else:
                                err_msg = _("Failed to create pull request.")
                                self._setStatus(err_msg)
                                ui.message(err_msg)

                        wx.CallAfter(on_create_err)

                threading.Thread(target=create_target, daemon=True).start()

            wx.CallAfter(show_dlg)

        threading.Thread(target=thread_target, daemon=True).start()
