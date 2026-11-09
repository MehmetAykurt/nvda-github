# Copyright (C) 2026 Mehmet Aykurt <m.aykurt38@gmail.com>
# Bu eklenti Mehmet Aykurt tarafından geliştirilmiştir.
# Lisans: GNU General Public License v2 (GPL-2.0)

"""Global repository search, starring, and forking for GitHub."""

import addonHandler
addonHandler.initTranslation()

import json
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
import webbrowser

import ui
import wx

from .auth import AuthError, checkCancelled
from .credentials import CredentialError
from .downloader import USER_AGENT, _build_opener
from .errors import errorMessage
from .notification_ops import _isSafeGitHubWebUrl
from .settings import SettingsError


def _check_cancelled(cancel):
    if cancel is not None:
        checkCancelled(cancel)


def searchRepositories(token, query, sort="stars", order="desc", cancel=None):
    """Searches public repositories on GitHub matching query."""
    clean_query = query.strip()
    if not clean_query:
        return []
    _check_cancelled(cancel)

    quoted_query = urllib.parse.quote(clean_query)
    url = f"https://api.github.com/search/repositories?q={quoted_query}&sort={sort}&order={order}&per_page=30"
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/vnd.github.v3+json",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    req = urllib.request.Request(url, headers=headers)
    opener = _build_opener()

    try:
        with opener.open(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 422:
            raise AuthError("invalid_search_query") from None
        if exc.code == 401:
            raise AuthError("unauthorized") from None
        if exc.code in (403, 429):
            raise AuthError("limited") from None
        raise AuthError("server_error") from None
    except (urllib.error.URLError, OSError, socket.timeout):
        raise AuthError("network") from None

    _check_cancelled(cancel)
    items = data.get("items") or []
    if not isinstance(items, list):
        raise AuthError("invalid_response")

    results = []
    for r in items:
        if not isinstance(r, dict):
            continue
        results.append({
            "id": r.get("id") or 0,
            "full_name": r.get("full_name") or "",
            "name": r.get("name") or "",
            "description": (r.get("description") or "").strip(),
            "stars": r.get("stargazers_count") or 0,
            "forks": r.get("forks_count") or 0,
            "language": r.get("language") or "",
            "html_url": r.get("html_url") or "",
            "default_branch": r.get("default_branch") or "main",
        })
    return results


def isRepoStarred(token, full_name, cancel=None):
    """Checks if the authenticated user has starred full_name."""
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", full_name):
        raise AuthError("invalid_response")
    _check_cancelled(cancel)

    url = f"https://api.github.com/user/starred/{full_name}"
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/vnd.github.v3+json",
        "Authorization": f"Bearer {token}",
    }
    req = urllib.request.Request(url, headers=headers)
    opener = _build_opener()

    try:
        with opener.open(req, timeout=20):
            return True
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return False
        if exc.code == 401:
            raise AuthError("unauthorized") from None
        if exc.code in (403, 429):
            raise AuthError("limited") from None
        raise AuthError("server_error") from None
    except (urllib.error.URLError, OSError, socket.timeout):
        raise AuthError("network") from None


def starRepository(token, full_name, star=True, cancel=None):
    """Stars or unstars a repository for the authenticated user."""
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", full_name):
        raise AuthError("invalid_response")
    _check_cancelled(cancel)

    url = f"https://api.github.com/user/starred/{full_name}"
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/vnd.github.v3+json",
        "Authorization": f"Bearer {token}",
        "Content-Length": "0",
    }
    method = "PUT" if star else "DELETE"
    req = urllib.request.Request(url, data=b"", headers=headers, method=method)
    opener = _build_opener()

    try:
        with opener.open(req, timeout=20):
            return True
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            raise AuthError("unauthorized") from None
        if exc.code in (403, 429):
            raise AuthError("limited") from None
        raise AuthError("server_error") from None
    except (urllib.error.URLError, OSError, socket.timeout):
        raise AuthError("network") from None


def forkRepository(token, full_name, cancel=None):
    """Forks a repository to the authenticated user's GitHub account."""
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", full_name):
        raise AuthError("invalid_response")
    _check_cancelled(cancel)

    url = f"https://api.github.com/repos/{full_name}/forks"
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/vnd.github.v3+json",
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    req = urllib.request.Request(url, data=b"{}", headers=headers, method="POST")
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
        if exc.code == 422:
            raise AuthError("conflict") from None
        raise AuthError("server_error") from None
    except (urllib.error.URLError, OSError, socket.timeout):
        raise AuthError("network") from None


class GlobalRepoDetailDialog(wx.Dialog):
    """Accessible dialog for reviewing details of a repository found in global search."""

    def __init__(self, parent, repo_dict):
        super().__init__(
            parent,
            title=_("Repository Details — %s") % repo_dict["full_name"],
            size=(700, 480),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        self.repo = repo_dict

        layout = wx.BoxSizer(wx.VERTICAL)

        info_label = wx.StaticText(self, label=_("&Repository information:"))
        layout.Add(info_label, 0, wx.ALL, 6)

        self.text_ctrl = wx.TextCtrl(
            self,
            value=self._formatText(repo_dict),
            style=wx.TE_MULTILINE | wx.TE_READONLY | wx.HSCROLL,
        )
        self.text_ctrl.SetName(_("Repository information"))
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
        self.SetMinSize((480, 360))
        self.CentreOnScreen()

        self.Bind(wx.EVT_CHAR_HOOK, self._onCharHook)
        wx.CallAfter(self.text_ctrl.SetFocus)

    def _formatText(self, r):
        lines = [
            f"{_('Repository:')} {r.get('full_name')}",
            f"{_('Stars:')} {r.get('stars', 0)} | {_('Forks:')} {r.get('forks', 0)} | {_('Language:')} {r.get('language') or _('(Not specified)')}",
            f"{_('Web Address:')} {r.get('html_url')}",
            f"{_('Default branch:')} {r.get('default_branch', 'main')}",
            "-" * 45,
            _("Description:"),
            r.get("description") or _("(No description provided.)"),
        ]
        return "\n".join(lines)

    def _onCopy(self, event):
        text = self.text_ctrl.GetValue()
        if wx.TheClipboard.Open():
            try:
                wx.TheClipboard.SetData(wx.TextDataObject(text))
                ui.message(_("Repository details copied to clipboard."))
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


class GlobalSearchDialog(wx.Dialog):
    """Accessible dialog for searching all public repositories on GitHub."""

    def __init__(self, parent, service):
        super().__init__(
            parent,
            title=_("Explore GitHub Repositories"),
            size=(880, 560),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        self.service = service
        self.results = []
        self._closing = False
        self._child_dlg = None
        self._searching = False

        layout = wx.BoxSizer(wx.VERTICAL)

        # Search row
        search_row = wx.BoxSizer(wx.HORIZONTAL)
        search_label = wx.StaticText(self, label=_("&Search keywords:"))
        search_row.Add(search_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)

        self.query_ctrl = wx.TextCtrl(self, style=wx.TE_PROCESS_ENTER)
        self.query_ctrl.SetName(_("Search keywords"))
        self.query_ctrl.Bind(wx.EVT_TEXT_ENTER, self._onSearch)
        search_row.Add(self.query_ctrl, 1, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)

        self.search_btn = wx.Button(self, label=_("&Search"))
        self.search_btn.SetDefault()
        self.search_btn.Bind(wx.EVT_BUTTON, self._onSearch)
        search_row.Add(self.search_btn, 0, wx.ALIGN_CENTER_VERTICAL)

        layout.Add(search_row, 0, wx.EXPAND | wx.ALL, 10)

        # Results list
        self.results_list = wx.ListCtrl(self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        self.results_list.SetName(_("Search results"))
        self.results_list.InsertColumn(0, _("Repository"), width=240)
        self.results_list.InsertColumn(1, _("Stars"), width=75)
        self.results_list.InsertColumn(2, _("Forks"), width=75)
        self.results_list.InsertColumn(3, _("Language"), width=110)
        self.results_list.InsertColumn(4, _("Description"), width=320)

        self.results_list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self._onViewDetail)
        self.results_list.Bind(wx.EVT_KEY_DOWN, self._onListKey)
        self.results_list.Bind(wx.EVT_CONTEXT_MENU, self._onContextMenu)
        layout.Add(self.results_list, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        # Status text
        self.status_label = wx.StaticText(self, label="")
        layout.Add(self.status_label, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)

        # Buttons
        button_sizer = wx.BoxSizer(wx.HORIZONTAL)

        self.view_btn = wx.Button(self, label=_("&Repository details…"))
        self.view_btn.Bind(wx.EVT_BUTTON, self._onViewDetail)
        button_sizer.Add(self.view_btn, 0, wx.RIGHT, 8)

        self.issues_btn = wx.Button(self, label=_("&Issues…"))
        self.issues_btn.Bind(wx.EVT_BUTTON, self._onOpenIssues)
        button_sizer.Add(self.issues_btn, 0, wx.RIGHT, 8)

        self.new_issue_btn = wx.Button(self, label=_("&New issue…"))
        self.new_issue_btn.Bind(wx.EVT_BUTTON, self._onNewIssue)
        button_sizer.Add(self.new_issue_btn, 0, wx.RIGHT, 8)

        self.star_btn = wx.Button(self, label=_("&Star / Unstar"))
        self.star_btn.Bind(wx.EVT_BUTTON, self._onStarClick)
        button_sizer.Add(self.star_btn, 0, wx.RIGHT, 8)

        self.fork_btn = wx.Button(self, label=_("&Fork to my account…"))
        self.fork_btn.Bind(wx.EVT_BUTTON, self._onForkClick)
        button_sizer.Add(self.fork_btn, 0, wx.RIGHT, 8)

        self.web_btn = wx.Button(self, label=_("&Open on web"))
        self.web_btn.Bind(wx.EVT_BUTTON, self._onOpenWeb)
        button_sizer.Add(self.web_btn, 0, wx.RIGHT, 8)

        self.close_btn = wx.Button(self, wx.ID_CANCEL, _("&Close"))
        self.close_btn.Bind(wx.EVT_BUTTON, self._onClose)
        button_sizer.Add(self.close_btn, 0)

        layout.Add(button_sizer, 0, wx.ALIGN_RIGHT | wx.RIGHT | wx.BOTTOM, 10)
        self.SetSizer(layout)
        self.SetMinSize((700, 450))
        self.CentreOnScreen()

        self.Bind(wx.EVT_CLOSE, self._onClose)
        self.Bind(wx.EVT_CHAR_HOOK, self._onCharHook)
        wx.CallAfter(self.query_ctrl.SetFocus)

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
        if event.GetKeyCode() == wx.WXK_ESCAPE:
            self._onClose()
            return
        event.Skip()

    def _onListKey(self, event):
        kc = event.GetKeyCode()
        if kc == wx.WXK_RETURN:
            self._onViewDetail(None)
            return
        elif kc == ord('I') and event.ControlDown():
            self._onOpenIssues(None)
            return
        elif kc == ord('N') and event.ControlDown():
            self._onNewIssue(None)
            return
        event.Skip()

    def _onSearch(self, event=None):
        if self._closing or self._searching:
            return
        query = self.query_ctrl.GetValue().strip()
        if not query:
            wx.MessageBox(_("Please enter a search keyword."), _("Search"), wx.OK | wx.ICON_INFORMATION, self)
            self.query_ctrl.SetFocus()
            return

        self._searching = True
        self.search_btn.Enable(False)
        start_msg = _("Searching repositories: %s…") % query
        self._setStatus(start_msg)
        ui.message(start_msg)
        self.results_list.DeleteAllItems()

        import threading

        def thread_target():
            try:
                if hasattr(self.service, "searchGlobalRepositories"):
                    res = self.service.searchGlobalRepositories(query)
                else:
                    token = self.service.getAccessToken() if hasattr(self.service, "getAccessToken") else ""
                    res = searchRepositories(token, query)
                wx.CallAfter(self._onSearchLoaded, res, query)
            except Exception as e:
                wx.CallAfter(self._onSearchError, e)

        threading.Thread(target=thread_target, daemon=True).start()

    def _onSearchLoaded(self, results, query):
        self._searching = False
        self.search_btn.Enable(True)
        if self._closing or not self:
            return
        self.results = results
        self.results_list.DeleteAllItems()
        for idx, item in enumerate(results):
            pos = self.results_list.InsertItem(idx, item.get("full_name") or "")
            self.results_list.SetItem(pos, 1, str(item.get("stars") or 0))
            self.results_list.SetItem(pos, 2, str(item.get("forks") or 0))
            self.results_list.SetItem(pos, 3, item.get("language") or "")
            self.results_list.SetItem(pos, 4, item.get("description") or "")

        if results:
            msg = _("%s repositories found.") % len(results)
            self._setStatus(msg)
            ui.message(msg)
            self.results_list.Select(0)
            self.results_list.Focus(0)
            self.results_list.SetFocus()
        else:
            msg = _("No repositories match '%s'.") % query
            self._setStatus(msg)
            ui.message(msg)
            self.query_ctrl.SetFocus()

    def _onSearchError(self, err):
        self._searching = False
        self.search_btn.Enable(True)
        if self._closing or not self:
            return
        if isinstance(err, (AuthError, CredentialError, SettingsError, OSError)):
            msg = errorMessage(err)
        else:
            msg = _("Search failed.")
        self._setStatus(msg)
        ui.message(msg)

    def _selectedRepo(self):
        idx = self.results_list.GetFirstSelected()
        if 0 <= idx < len(self.results):
            return self.results[idx]
        return None

    def _onViewDetail(self, event=None):
        if self._closing or self._child_dlg is not None:
            return
        repo = self._selectedRepo()
        if not repo:
            return
        self._runNestedModal(GlobalRepoDetailDialog(self, repo))

    def _onOpenIssues(self, event=None):
        if self._closing or self._child_dlg is not None:
            return
        repo = self._selectedRepo()
        if not repo:
            ui.message(_("No repository selected."))
            return
        full_name = repo.get("full_name")
        if not full_name:
            return
        from .issue_ops import IssuesDialog
        self._runNestedModal(IssuesDialog(self, full_name, self.service))

    def _onNewIssue(self, event=None):
        if self._closing or self._child_dlg is not None:
            return
        repo = self._selectedRepo()
        if not repo:
            ui.message(_("No repository selected."))
            return
        full_name = repo.get("full_name")
        if not full_name:
            return

        from .issue_ops import NewIssueDialog, createIssue

        dlg = NewIssueDialog(self, full_name, service=self.service)
        data = None
        self._child_dlg = dlg
        try:
            if dlg.ShowModal() == wx.ID_OK:
                data = dlg.getData()
        finally:
            if hasattr(dlg, "cancelAndClose"):
                dlg.cancelAndClose()
            self._child_dlg = None
            if dlg:
                dlg.Destroy()

        if not data or self._closing:
            return

        start_msg = _("Creating issue…")
        self._setStatus(start_msg)
        ui.message(start_msg)

        import threading

        def thread_target():
            try:
                if hasattr(self.service, "createIssue"):
                    self.service.createIssue(full_name, data["title"], data.get("body", ""))
                else:
                    token = self.service.getAccessToken() if hasattr(self.service, "getAccessToken") else ""
                    createIssue(token, full_name, data["title"], data.get("body", ""))

                def on_ok():
                    msg = _("Issue created successfully.")
                    ui.message(msg)
                    self._setStatus(msg)

                wx.CallAfter(on_ok)
            except Exception as e:
                def on_err():
                    if self._closing or not self:
                        return
                    if isinstance(e, (AuthError, CredentialError, SettingsError, OSError)):
                        msg = errorMessage(e)
                    else:
                        msg = _("Failed to create issue.")
                    ui.message(msg)
                    self._setStatus(msg)

                wx.CallAfter(on_err)

        threading.Thread(target=thread_target, daemon=True).start()

    def _onContextMenu(self, event=None):
        if self._closing or self._child_dlg is not None:
            return
        repo = self._selectedRepo()
        if not repo:
            return

        menu = wx.Menu()
        view_item = menu.Append(wx.ID_ANY, _("&Repository details…"))
        issues_item = menu.Append(wx.ID_ANY, _("&Issues…") + "	Ctrl+I")
        new_issue_item = menu.Append(wx.ID_ANY, _("&New issue…") + "	Ctrl+N")
        menu.AppendSeparator()
        star_item = menu.Append(wx.ID_ANY, _("&Star / Unstar"))
        fork_item = menu.Append(wx.ID_ANY, _("&Fork to my account…"))
        web_item = menu.Append(wx.ID_ANY, _("&Open on web"))

        menu.Bind(wx.EVT_MENU, self._onViewDetail, view_item)
        menu.Bind(wx.EVT_MENU, self._onOpenIssues, issues_item)
        menu.Bind(wx.EVT_MENU, self._onNewIssue, new_issue_item)
        menu.Bind(wx.EVT_MENU, self._onStarClick, star_item)
        menu.Bind(wx.EVT_MENU, self._onForkClick, fork_item)
        menu.Bind(wx.EVT_MENU, self._onOpenWeb, web_item)

        self.PopupMenu(menu)
        menu.Destroy()

    def _onOpenWeb(self, event=None):
        repo = self._selectedRepo()
        if not repo:
            return
        url = repo.get("html_url") or f"https://github.com/{repo.get('full_name')}"
        if _isSafeGitHubWebUrl(url):
            try:
                webbrowser.open(url, new=2)
                return
            except OSError:
                pass
        ui.message(_("Could not open repository address."))

    def _onStarClick(self, event=None):
        if self._closing or self._child_dlg is not None:
            return
        repo = self._selectedRepo()
        if not repo:
            return

        full_name = repo["full_name"]
        import threading

        def thread_target():
            try:
                if hasattr(self.service, "isRepoStarred"):
                    starred = self.service.isRepoStarred(full_name)
                    new_state = not starred
                    self.service.starRepository(full_name, star=new_state)
                else:
                    token = self.service.getAccessToken() if hasattr(self.service, "getAccessToken") else ""
                    starred = isRepoStarred(token, full_name)
                    new_state = not starred
                    starRepository(token, full_name, star=new_state)

                def on_ok():
                    action_msg = _("Repository starred: %s") % full_name if new_state else _("Star removed: %s") % full_name
                    ui.message(action_msg)
                    self._setStatus(action_msg)

                wx.CallAfter(on_ok)
            except Exception as e:
                def on_err():
                    if isinstance(e, (AuthError, CredentialError, SettingsError, OSError)):
                        ui.message(errorMessage(e))
                    else:
                        ui.message(_("Star operation failed."))

                wx.CallAfter(on_err)

        threading.Thread(target=thread_target, daemon=True).start()

    def _onForkClick(self, event=None):
        if self._closing or self._child_dlg is not None:
            return
        repo = self._selectedRepo()
        if not repo:
            return

        full_name = repo["full_name"]
        answer = wx.MessageBox(
            _("Do you want to fork '%s' to your GitHub account?") % full_name,
            _("Fork Repository"),
            wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION,
            self,
        )
        if answer != wx.YES or self._closing:
            return

        start_msg = _("Forking repository: %s…") % full_name
        self._setStatus(start_msg)
        ui.message(start_msg)

        import threading

        def thread_target():
            try:
                if hasattr(self.service, "forkRepository"):
                    forked_data = self.service.forkRepository(full_name)
                else:
                    token = self.service.getAccessToken() if hasattr(self.service, "getAccessToken") else ""
                    forked_data = forkRepository(token, full_name)

                def on_ok():
                    my_repo = forked_data.get("full_name") or full_name
                    msg = _("Repository successfully forked: %s") % my_repo
                    ui.message(msg)
                    self._setStatus(msg)

                wx.CallAfter(on_ok)
            except Exception as e:
                def on_err():
                    if isinstance(e, (AuthError, CredentialError, SettingsError, OSError)):
                        ui.message(errorMessage(e))
                    else:
                        ui.message(_("Failed to fork repository."))

                wx.CallAfter(on_err)

        threading.Thread(target=thread_target, daemon=True).start()
