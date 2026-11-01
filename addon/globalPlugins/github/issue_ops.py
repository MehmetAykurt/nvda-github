# Copyright (C) 2026 Mehmet Aykurt <m.aykurt38@gmail.com>
# Bu eklenti Mehmet Aykurt tarafından geliştirilmiştir.
# Lisans: GNU General Public License v2 (GPL-2.0)

"""GitHub Issues management: listing, viewing, creating issues, comments, and state changes."""

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


def listIssues(token, full_name, state="open", cancel=None):
    """Fetches list of issues for a repository (excluding pull requests)."""
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", full_name):
        raise AuthError("invalid_response")
    _check_cancelled(cancel)

    valid_states = {"open", "closed", "all"}
    clean_state = state if state in valid_states else "open"

    opener = _build_opener()
    issues = []

    for page in range(1, 4):
        _check_cancelled(cancel)
        page_suffix = f"&page={page}" if page > 1 else ""
        url = (
            f"https://api.github.com/repos/{full_name}/issues"
            f"?state={clean_state}&per_page=100&sort=updated&direction=desc{page_suffix}"
        )
        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "application/vnd.github.v3+json",
            "Authorization": f"Bearer {token}",
        }
        req = urllib.request.Request(url, headers=headers)

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

        for item in data:
            if not isinstance(item, dict):
                continue
            # Exclude Pull Requests returned by the Issues API
            if "pull_request" in item:
                continue
            user_obj = item.get("user") or {}
            issues.append({
                "number": item.get("number") or 0,
                "title": item.get("title") or "",
                "state": item.get("state") or "open",
                "user": (user_obj.get("login") or "") if isinstance(user_obj, dict) else "",
                "comments": item.get("comments") or 0,
                "created_at": item.get("created_at") or "",
                "updated_at": item.get("updated_at") or "",
                "body": item.get("body") or "",
                "html_url": item.get("html_url") or "",
            })

        if len(data) < 100 or len(issues) >= 50:
            break

    return issues


def getIssueComments(token, full_name, issue_number, cancel=None):
    """Fetches comments for an issue."""
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", full_name):
        raise AuthError("invalid_response")
    _check_cancelled(cancel)

    url = f"https://api.github.com/repos/{full_name}/issues/{int(issue_number)}/comments?per_page=100"
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

    comments = []
    for c in data:
        if not isinstance(c, dict):
            continue
        user_obj = c.get("user") or {}
        comments.append({
            "id": c.get("id") or 0,
            "user": (user_obj.get("login") or "") if isinstance(user_obj, dict) else "",
            "created_at": c.get("created_at") or "",
            "body": c.get("body") or "",
        })
    return comments


def createIssue(token, full_name, title, body="", cancel=None):
    """Creates a new issue in the specified repository."""
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", full_name):
        raise AuthError("invalid_response")
    clean_title = title.strip()
    if not clean_title:
        raise AuthError("invalid_response")
    _check_cancelled(cancel)

    url = f"https://api.github.com/repos/{full_name}/issues"
    payload = {
        "title": clean_title,
        "body": body.strip(),
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
        with opener.open(req, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
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


def addIssueComment(token, full_name, issue_number, body, cancel=None):
    """Adds a new comment to an existing issue."""
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", full_name):
        raise AuthError("invalid_response")
    clean_body = body.strip()
    if not clean_body:
        raise AuthError("invalid_response")
    _check_cancelled(cancel)

    url = f"https://api.github.com/repos/{full_name}/issues/{int(issue_number)}/comments"
    payload = {"body": clean_body}
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
        with opener.open(req, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
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


def setIssueState(token, full_name, issue_number, state="closed", cancel=None):
    """Closes or reopens an issue."""
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", full_name):
        raise AuthError("invalid_response")
    target_state = "closed" if state == "closed" else "open"
    _check_cancelled(cancel)

    url = f"https://api.github.com/repos/{full_name}/issues/{int(issue_number)}"
    payload = {"state": target_state}
    data_bytes = json.dumps(payload).encode("utf-8")
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/vnd.github.v3+json",
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }
    req = urllib.request.Request(url, data=data_bytes, headers=headers, method="PATCH")
    opener = _build_opener()

    try:
        with opener.open(req, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
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


class NewIssueDialog(wx.Dialog):
    """Accessible dialog for creating a new issue."""

    def __init__(self, parent, repo_name):
        super().__init__(
            parent,
            title=_("New issue — %s") % repo_name,
            size=(600, 450),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )

        layout = wx.BoxSizer(wx.VERTICAL)

        title_label = wx.StaticText(self, label=_("&Title:"))
        layout.Add(title_label, 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)
        self.title_ctrl = wx.TextCtrl(self)
        self.title_ctrl.SetName(_("Title"))
        layout.Add(self.title_ctrl, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        body_label = wx.StaticText(self, label=_("&Description (optional):"))
        layout.Add(body_label, 0, wx.LEFT | wx.RIGHT | wx.TOP, 5)
        self.body_ctrl = wx.TextCtrl(self, style=wx.TE_MULTILINE | wx.HSCROLL)
        self.body_ctrl.SetName(_("Description (optional)"))
        layout.Add(self.body_ctrl, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        button_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.ok_btn = wx.Button(self, wx.ID_OK, _("&Submit new issue"))
        self.ok_btn.SetDefault()
        self.ok_btn.Bind(wx.EVT_BUTTON, self._onSubmit)
        button_sizer.Add(self.ok_btn, 0, wx.RIGHT, 10)

        self.cancel_btn = wx.Button(self, wx.ID_CANCEL, _("&Cancel"))
        button_sizer.Add(self.cancel_btn, 0)

        layout.Add(button_sizer, 0, wx.ALIGN_RIGHT | wx.RIGHT | wx.BOTTOM, 10)
        self.SetSizer(layout)
        self.SetMinSize((450, 350))
        self.CentreOnScreen()
        wx.CallAfter(self.title_ctrl.SetFocus)

    def _onSubmit(self, event):
        title = self.title_ctrl.GetValue().strip()
        if not title:
            wx.MessageBox(_("Please enter an issue title."), _("Error"), wx.OK | wx.ICON_ERROR, self)
            self.title_ctrl.SetFocus()
            return
        self.EndModal(wx.ID_OK)

    def getData(self):
        return {
            "title": self.title_ctrl.GetValue().strip(),
            "body": self.body_ctrl.GetValue().strip(),
        }

    def cancelAndClose(self):
        if self.IsModal():
            self.EndModal(wx.ID_CANCEL)


class NewCommentDialog(wx.Dialog):
    """Accessible dialog for writing a comment on an issue."""

    def __init__(self, parent, issue_title):
        super().__init__(
            parent,
            title=_("Add comment — %s") % issue_title,
            size=(550, 350),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )

        layout = wx.BoxSizer(wx.VERTICAL)

        label = wx.StaticText(self, label=_("&Comment:"))
        layout.Add(label, 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)
        self.comment_ctrl = wx.TextCtrl(self, style=wx.TE_MULTILINE | wx.HSCROLL)
        self.comment_ctrl.SetName(_("Comment"))
        layout.Add(self.comment_ctrl, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        button_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.ok_btn = wx.Button(self, wx.ID_OK, _("&Add comment"))
        self.ok_btn.SetDefault()
        self.ok_btn.Bind(wx.EVT_BUTTON, self._onSubmit)
        button_sizer.Add(self.ok_btn, 0, wx.RIGHT, 10)

        self.cancel_btn = wx.Button(self, wx.ID_CANCEL, _("&Cancel"))
        button_sizer.Add(self.cancel_btn, 0)

        layout.Add(button_sizer, 0, wx.ALIGN_RIGHT | wx.RIGHT | wx.BOTTOM, 10)
        self.SetSizer(layout)
        self.SetMinSize((400, 250))
        self.CentreOnScreen()
        wx.CallAfter(self.comment_ctrl.SetFocus)

    def _onSubmit(self, event):
        body = self.comment_ctrl.GetValue().strip()
        if not body:
            wx.MessageBox(_("Please enter comment text."), _("Error"), wx.OK | wx.ICON_ERROR, self)
            self.comment_ctrl.SetFocus()
            return
        self.EndModal(wx.ID_OK)

    def getCommentText(self):
        return self.comment_ctrl.GetValue().strip()

    def cancelAndClose(self):
        if self.IsModal():
            self.EndModal(wx.ID_CANCEL)


class IssueDetailDialog(wx.Dialog):
    """Accessible dialog displaying full details of an issue and its comments."""

    def __init__(self, parent, issue, comments, onAddComment, onToggleState):
        super().__init__(
            parent,
            title=_("Issue #%s: %s") % (issue.get("number", 0), issue.get("title", "")),
            size=(750, 550),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        self.issue = issue
        self.comments = comments
        self.onAddComment = onAddComment
        self.onToggleState = onToggleState
        self._closing = False
        self._child_dlg = None

        layout = wx.BoxSizer(wx.VERTICAL)

        state_str = _("Closed") if issue.get("state") == "closed" else _("Open")
        info_text = _("State: %s | Author: %s | Comments: %s") % (
            state_str,
            issue.get("user", ""),
            len(comments),
        )
        self.info_label = wx.StaticText(self, label=info_text)
        layout.Add(self.info_label, 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)

        # Build readable full text content
        full_text = self._buildFullText(issue, comments)
        self.text_ctrl = wx.TextCtrl(
            self,
            value=full_text,
            style=wx.TE_MULTILINE | wx.TE_READONLY | wx.HSCROLL,
        )
        self.text_ctrl.SetName(_("Issue details and comments"))
        layout.Add(self.text_ctrl, 1, wx.EXPAND | wx.ALL, 10)

        button_sizer = wx.BoxSizer(wx.HORIZONTAL)

        self.comment_btn = wx.Button(self, label=_("&Add comment…"))
        self.comment_btn.Bind(wx.EVT_BUTTON, self._onCommentClicked)
        button_sizer.Add(self.comment_btn, 0, wx.RIGHT, 10)

        state_label = _("&Reopen issue") if issue.get("state") == "closed" else _("&Close issue")
        self.toggle_state_btn = wx.Button(self, label=state_label)
        self.toggle_state_btn.Bind(wx.EVT_BUTTON, self._onToggleStateClicked)
        button_sizer.Add(self.toggle_state_btn, 0, wx.RIGHT, 10)

        self.copy_btn = wx.Button(self, label=_("&Copy text"))
        self.copy_btn.Bind(wx.EVT_BUTTON, self._onCopyClicked)
        button_sizer.Add(self.copy_btn, 0, wx.RIGHT, 10)

        self.close_btn = wx.Button(self, wx.ID_CANCEL, _("&Close"))
        self.close_btn.Bind(wx.EVT_BUTTON, self._onClose)
        button_sizer.Add(self.close_btn, 0)

        layout.Add(button_sizer, 0, wx.ALIGN_RIGHT | wx.RIGHT | wx.BOTTOM, 10)
        self.SetSizer(layout)
        self.SetMinSize((500, 380))
        self.CentreOnScreen()

        self.Bind(wx.EVT_CLOSE, self._onClose)
        self.Bind(wx.EVT_CHAR_HOOK, self._onCharHook)
        wx.CallAfter(self.text_ctrl.SetFocus)

    def _buildFullText(self, issue, comments):
        lines = []
        lines.append(f"#{issue.get('number', 0)}: {issue.get('title', '')}")
        lines.append(f"{_('Author:')} {issue.get('user', '')} ({issue.get('created_at', '')})")
        lines.append("-" * 40)
        lines.append(issue.get("body", "") or _("(No description provided.)"))
        lines.append("")

        if comments:
            lines.append(f"=== {_('Comments')} ({len(comments)}) ===")
            for idx, c in enumerate(comments, 1):
                lines.append(f"\n--- {_('Comment #%s') % idx} — {c.get('user', '')} ({c.get('created_at', '')}) ---")
                lines.append(c.get("body", ""))
        else:
            lines.append(f"=== {_('No comments yet.')} ===")
        return "\n".join(lines)

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
        if event.GetKeyCode() == wx.WXK_ESCAPE:
            self._onClose()
            return
        event.Skip()

    def _onCommentClicked(self, event):
        if self.onAddComment:
            self.onAddComment(self)

    def _onToggleStateClicked(self, event):
        if self.onToggleState:
            self.onToggleState(self)

    def _onCopyClicked(self, event):
        text = self.text_ctrl.GetValue()
        if wx.TheClipboard.Open():
            try:
                wx.TheClipboard.SetData(wx.TextDataObject(text))
                ui.message(_("Issue details copied to clipboard."))
            finally:
                wx.TheClipboard.Close()
        else:
            ui.message(_("Clipboard could not be opened."))


class IssuesDialog(wx.Dialog):
    """Accessible dialog for browsing and managing repository issues."""

    def __init__(self, parent, full_name, service):
        super().__init__(
            parent,
            title=_("Issues — %s") % full_name,
            size=(850, 550),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        self.full_name = full_name
        self.service = service
        self.issues = []
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

        # Issues list
        self.issues_list = wx.ListCtrl(self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        self.issues_list.SetName(_("Issues"))
        self.issues_list.InsertColumn(0, _("Number"), width=75)
        self.issues_list.InsertColumn(1, _("State"), width=90)
        self.issues_list.InsertColumn(2, _("Title"), width=310)
        self.issues_list.InsertColumn(3, _("Author"), width=120)
        self.issues_list.InsertColumn(4, _("Comments"), width=85)
        self.issues_list.InsertColumn(5, _("Date"), width=110)

        self.issues_list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self._onViewIssue)
        self.issues_list.Bind(wx.EVT_KEY_DOWN, self._onListKey)
        layout.Add(self.issues_list, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        # Status text
        self.status_label = wx.StaticText(self, label="")
        layout.Add(self.status_label, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)

        # Buttons
        button_sizer = wx.BoxSizer(wx.HORIZONTAL)

        self.view_btn = wx.Button(self, label=_("&View issue…"))
        self.view_btn.Bind(wx.EVT_BUTTON, self._onViewIssue)
        button_sizer.Add(self.view_btn, 0, wx.RIGHT, 10)

        self.new_btn = wx.Button(self, label=_("&New issue…"))
        self.new_btn.Bind(wx.EVT_BUTTON, self._onNewIssue)
        button_sizer.Add(self.new_btn, 0, wx.RIGHT, 10)

        self.close_btn = wx.Button(self, wx.ID_CANCEL, _("&Close"))
        self.close_btn.Bind(wx.EVT_BUTTON, self._onClose)
        button_sizer.Add(self.close_btn, 0)

        layout.Add(button_sizer, 0, wx.ALIGN_RIGHT | wx.RIGHT | wx.BOTTOM, 10)
        self.SetSizer(layout)
        self.SetMinSize((600, 400))
        self.CentreOnScreen()

        self.Bind(wx.EVT_CLOSE, self._onClose)
        self.Bind(wx.EVT_CHAR_HOOK, self._onCharHook)
        wx.CallAfter(self.loadIssues)

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
            self.loadIssues()
            return
        if event.GetKeyCode() == ord("N") and event.ControlDown() and not event.ShiftDown() and not event.AltDown():
            self._onNewIssue(None)
            return
        event.Skip()

    def _onListKey(self, event):
        if event.GetKeyCode() == wx.WXK_RETURN:
            self._onViewIssue(None)
            return
        if event.GetKeyCode() == ord("N") and event.ControlDown() and not event.ShiftDown():
            self._onNewIssue(None)
            return
        if event.GetKeyCode() == wx.WXK_F5:
            self.loadIssues()
            return
        event.Skip()

    def _onFilterChanged(self, event):
        self.loadIssues()

    def loadIssues(self):
        if self._closing or not self:
            return
        sel = self.filter_choice.GetSelection()
        state_map = {0: "open", 1: "closed", 2: "all"}
        state = state_map.get(sel, "open")

        self._setStatus(_("Loading issues…"))
        self.issues_list.DeleteAllItems()

        def background_task():
            if hasattr(self.service, "loadIssues"):
                return self.service.loadIssues(self.full_name, state=state)
            return []

        import threading

        def thread_target():
            try:
                result = background_task()
                wx.CallAfter(self._onIssuesLoaded, result)
            except Exception as e:
                wx.CallAfter(self._onIssuesError, e)

        self._worker = threading.Thread(target=thread_target, daemon=True)
        self._worker.start()

    def _onIssuesLoaded(self, issues):
        if self._closing or not self:
            return
        self.issues = issues
        self.issues_list.DeleteAllItems()
        for idx, item in enumerate(issues):
            pos = self.issues_list.InsertItem(idx, f"#{item['number']}")
            state_label = _("Closed") if item.get("state") == "closed" else _("Open")
            self.issues_list.SetItem(pos, 1, state_label)
            self.issues_list.SetItem(pos, 2, item.get("title") or "")
            self.issues_list.SetItem(pos, 3, item.get("user") or "")
            self.issues_list.SetItem(pos, 4, str(item.get("comments") or 0))
            date_str = (item.get("created_at") or "")[:10]
            self.issues_list.SetItem(pos, 5, date_str)

        if issues:
            msg = _("%s issues listed.") % len(issues)
            self._setStatus(msg)
            ui.message(msg)
            self.issues_list.Select(0)
            self.issues_list.Focus(0)
            self.issues_list.SetFocus()
        else:
            msg = _("No issues found.")
            self._setStatus(msg)
            ui.message(msg)
            self.filter_choice.SetFocus()

    def _onIssuesError(self, err):
        if self._closing or not self:
            return
        if isinstance(err, (AuthError, CredentialError, SettingsError, OSError)):
            msg = errorMessage(err)
        else:
            msg = _("Could not load issues.")
        self._setStatus(msg)
        ui.message(msg)

    def _selectedIssue(self):
        index = self.issues_list.GetFirstSelected()
        if 0 <= index < len(self.issues):
            return self.issues[index]
        return None

    def _onViewIssue(self, event, target_issue=None):
        if self._closing or not self or self._loading_detail or self._child_dlg is not None:
            return
        issue = target_issue if target_issue is not None else self._selectedIssue()
        if not issue:
            return

        self._loading_detail = True
        load_msg = _("Loading issue…")
        self._setStatus(load_msg)
        ui.message(load_msg)

        import threading

        def fetch_comments_and_show():
            comments = []
            if hasattr(self.service, "loadIssueComments"):
                try:
                    comments = self.service.loadIssueComments(self.full_name, issue["number"])
                except Exception:
                    comments = []

            def show_dlg():
                self._loading_detail = False
                if self._closing or not self or self._child_dlg is not None:
                    return
                self._setStatus("")

                def on_add_comment(parent_dlg):
                    c_dlg = NewCommentDialog(parent_dlg, issue.get("title") or "")
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
                            self.service.addIssueComment(self.full_name, issue["number"], text)

                            def on_comment_ok():
                                issue["comments"] = int(issue.get("comments") or 0) + 1
                                if not self._closing and self and issue in self.issues:
                                    row_idx = self.issues.index(issue)
                                    self.issues_list.SetItem(row_idx, 4, str(issue["comments"]))
                                ui.message(_("Comment added successfully."))
                                if parent_dlg and not parent_dlg._closing:
                                    parent_dlg._onClose()
                                if not self._closing and self:
                                    wx.CallAfter(self._onViewIssue, None, issue)

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

                def on_toggle_state(parent_dlg):
                    new_state = "open" if issue.get("state") == "closed" else "closed"
                    parent_dlg.toggle_state_btn.Enable(False)

                    def state_worker():
                        try:
                            self.service.setIssueState(self.full_name, issue["number"], state=new_state)
                            issue["state"] = new_state

                            def on_state_ok():
                                action_msg = _("Issue closed.") if new_state == "closed" else _("Issue reopened.")
                                ui.message(action_msg)
                                if parent_dlg and not parent_dlg._closing:
                                    parent_dlg._onClose()
                                if not self._closing and self:
                                    self.loadIssues()

                            wx.CallAfter(on_state_ok)
                        except Exception as err:
                            def on_state_err():
                                if parent_dlg and not parent_dlg._closing:
                                    parent_dlg.toggle_state_btn.Enable(True)
                                if isinstance(err, (AuthError, CredentialError, SettingsError, OSError)):
                                    ui.message(errorMessage(err))
                                else:
                                    ui.message(_("Failed to change issue state."))

                            wx.CallAfter(on_state_err)

                    threading.Thread(target=state_worker, daemon=True).start()

                self._runNestedModal(IssueDetailDialog(self, issue, comments, on_add_comment, on_toggle_state))

            wx.CallAfter(show_dlg)

        threading.Thread(target=fetch_comments_and_show, daemon=True).start()

    def _onNewIssue(self, event):
        if self._closing or not self or self._child_dlg is not None:
            return
        dlg = NewIssueDialog(self, self.full_name)
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

        start_msg = _("Creating issue…")
        self._setStatus(start_msg)
        ui.message(start_msg)

        def create_target():
            try:
                self.service.createIssue(self.full_name, data["title"], data.get("body", ""))

                def on_created():
                    ui.message(_("Issue created successfully."))
                    if not self._closing and self:
                        self.loadIssues()

                wx.CallAfter(on_created)
            except Exception as err:
                def on_create_err():
                    if isinstance(err, (AuthError, CredentialError, SettingsError, OSError)):
                        ui.message(errorMessage(err))
                    else:
                        ui.message(_("Failed to create issue."))

                wx.CallAfter(on_create_err)

        import threading
        threading.Thread(target=create_target, daemon=True).start()

