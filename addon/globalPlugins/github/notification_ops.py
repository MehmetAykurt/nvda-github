# Copyright (C) 2026 Mehmet Aykurt <m.aykurt38@gmail.com>
# Bu eklenti Mehmet Aykurt tarafından geliştirilmiştir.
# Lisans: GNU General Public License v2 (GPL-2.0)

"""GitHub Notifications management: listing notifications, reading details in-addon, and marking as read."""

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
from .issue_ops import IssueDetailDialog, NewCommentDialog, addIssueComment, getIssueComments, setIssueState
from .pr_ops import PullRequestDetailDialog, getPullRequestFiles, mergePullRequest, setPullRequestState
from .release_ops import ReleaseDetailDialog
from .settings import SettingsError


def _check_cancelled(cancel):
    if cancel is not None:
        checkCancelled(cancel)


def _isSafeGitHubWebUrl(url):
    """Allows opening only HTTPS URLs hosted strictly on github.com."""
    if not isinstance(url, str) or not url:
        return False
    parsed = urllib.parse.urlsplit(url.strip())
    return parsed.scheme == "https" and (parsed.hostname or "").lower() == "github.com"


def _hasServiceMethod(service, name):
    return (
        getattr(type(service), name, None) is not None
        or name in getattr(service, "__dict__", {})
    )


def getReasonLabel(reason):
    reasons = {
        "mention": _("Mention"),
        "subscribed": _("Subscribed"),
        "author": _("Author"),
        "comment": _("Comment"),
        "assign": _("Assigned"),
        "state_change": _("State change"),
        "review_requested": _("Review requested"),
        "ci_activity": _("Automatic activity"),
    }
    return reasons.get(reason, reason)


def getTypeLabel(type_str):
    types = {
        "Issue": _("Issue"),
        "PullRequest": _("Pull Request"),
        "Release": _("Release"),
        "Commit": _("Commit"),
    }
    return types.get(type_str, type_str)


def apiUrlToWebUrl(subject_url, subject_type="", repo_html_url=""):
    """Converts a GitHub API subject URL into a user-facing github.com web URL."""
    if isinstance(subject_url, str) and subject_url.startswith("https://api.github.com/repos/"):
        rest = subject_url[len("https://api.github.com/repos/"):]
        parts = rest.split("/")
        if len(parts) >= 4 and re.fullmatch(r"[A-Za-z0-9_.-]+", parts[0]) and re.fullmatch(r"[A-Za-z0-9_.-]+", parts[1]):
            owner, repo, resource = parts[0], parts[1], parts[2]
            ident = "/".join(urllib.parse.quote(p, safe="") for p in parts[3:])
            base = f"https://github.com/{owner}/{repo}"
            if resource == "issues":
                return f"{base}/issues/{ident}"
            if resource == "pulls":
                return f"{base}/pull/{ident}"
            if resource == "commits":
                return f"{base}/commit/{ident}"
            if resource == "releases":
                return f"{base}/releases"
        elif len(parts) >= 2 and re.fullmatch(r"[A-Za-z0-9_.-]+", parts[0]) and re.fullmatch(r"[A-Za-z0-9_.-]+", parts[1]):
            return f"https://github.com/{parts[0]}/{parts[1]}"
    return repo_html_url.strip() if _isSafeGitHubWebUrl(repo_html_url) else ""


def listNotifications(token, all_notifications=False, cancel=None):
    """Fetches notifications for the authenticated user."""
    _check_cancelled(cancel)
    all_param = "true" if all_notifications else "false"
    url = f"https://api.github.com/notifications?all={all_param}&per_page=50"
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

    notifications = []
    for item in data:
        if not isinstance(item, dict):
            continue
        repo_obj = item.get("repository") or {}
        if not isinstance(repo_obj, dict):
            repo_obj = {}
        subj_obj = item.get("subject") or {}
        if not isinstance(subj_obj, dict):
            subj_obj = {}
        subject_type = subj_obj.get("type") or ""
        subject_url = subj_obj.get("url") or ""
        repo_html_url = repo_obj.get("html_url") or ""
        notifications.append({
            "id": str(item.get("id") or ""),
            "unread": bool(item.get("unread", False)),
            "reason": item.get("reason") or "",
            "updated_at": item.get("updated_at") or "",
            "repository": repo_obj.get("full_name") or "",
            "subject_title": subj_obj.get("title") or "",
            "subject_type": subject_type,
            "subject_url": subject_url,
            "repo_html_url": repo_html_url,
            "html_url": apiUrlToWebUrl(subject_url, subject_type, repo_html_url),
        })
    return notifications


def markNotificationRead(token, thread_id, cancel=None):
    """Marks a single notification thread as read."""
    clean_id = str(thread_id or "").strip()
    if not clean_id or not re.fullmatch(r"[A-Za-z0-9_-]+", clean_id):
        raise AuthError("invalid_response")
    _check_cancelled(cancel)
    url = f"https://api.github.com/notifications/threads/{clean_id}"
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/vnd.github.v3+json",
        "Authorization": f"Bearer {token}",
    }
    req = urllib.request.Request(url, headers=headers, method="PATCH")
    opener = _build_opener()

    try:
        with opener.open(req, timeout=30) as response:
            pass
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            raise AuthError("unauthorized") from None
        if exc.code in (403, 429):
            raise AuthError("limited") from None
        raise AuthError("server_error") from None
    except (urllib.error.URLError, OSError, socket.timeout):
        raise AuthError("network") from None

    _check_cancelled(cancel)
    return True


def markAllNotificationsRead(token, cancel=None):
    """Marks all notifications as read."""
    _check_cancelled(cancel)
    url = "https://api.github.com/notifications"
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/vnd.github.v3+json",
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    payload = json.dumps({}).encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers=headers, method="PUT")
    opener = _build_opener()

    try:
        with opener.open(req, timeout=30) as response:
            pass
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            raise AuthError("unauthorized") from None
        if exc.code in (403, 429):
            raise AuthError("limited") from None
        raise AuthError("server_error") from None
    except (urllib.error.URLError, OSError, socket.timeout):
        raise AuthError("network") from None

    _check_cancelled(cancel)
    return True


def fetchResource(token, api_url, cancel=None):
    """Fetches a resource by its GitHub API URL (strictly https://api.github.com)."""
    _check_cancelled(cancel)
    if not isinstance(api_url, str) or not api_url:
        raise AuthError("invalid_response")
    parsed = urllib.parse.urlsplit(api_url)
    if parsed.scheme != "https" or (parsed.hostname or "").lower() != "api.github.com":
        raise AuthError("invalid_response")
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/vnd.github.v3+json",
        "Authorization": f"Bearer {token}",
    }
    req = urllib.request.Request(api_url, headers=headers)
    opener = _build_opener()
    try:
        with opener.open(req, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            raise AuthError("unauthorized") from None
        return None
    except Exception:
        return None


class NotificationsDialog(wx.Dialog):
    """Accessible dialog for browsing, opening, and managing GitHub notifications."""

    def __init__(self, parent, service):
        super().__init__(
            parent,
            title=_("GitHub Notifications"),
            size=(850, 550),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        self.service = service
        self.notifications = []
        self._closing = False
        self._child_dlg = None
        self._opening_detail = False

        layout = wx.BoxSizer(wx.VERTICAL)

        # Filter row
        filter_row = wx.BoxSizer(wx.HORIZONTAL)
        filter_label = wx.StaticText(self, label=_("&Filter:"))
        filter_row.Add(filter_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)

        self.filter_choice = wx.Choice(self, choices=[_("Only unread"), _("All")])
        self.filter_choice.SetSelection(0)
        self.filter_choice.SetName(_("Filter"))
        self.filter_choice.Bind(wx.EVT_CHOICE, self._onFilterChanged)
        filter_row.Add(self.filter_choice, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 15)

        layout.Add(filter_row, 0, wx.ALL, 10)

        # Notifications list
        self.notif_list = wx.ListCtrl(self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        self.notif_list.SetName(_("Notifications"))
        self.notif_list.InsertColumn(0, _("Repository"), width=170)
        self.notif_list.InsertColumn(1, _("State"), width=95)
        self.notif_list.InsertColumn(2, _("Type"), width=100)
        self.notif_list.InsertColumn(3, _("Title"), width=260)
        self.notif_list.InsertColumn(4, _("Reason"), width=110)
        self.notif_list.InsertColumn(5, _("Date"), width=95)

        self.notif_list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self._onOpenNotification)
        self.notif_list.Bind(wx.EVT_KEY_DOWN, self._onListKey)
        layout.Add(self.notif_list, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        # Status text
        self.status_label = wx.StaticText(self, label="")
        layout.Add(self.status_label, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)

        # Buttons
        button_sizer = wx.BoxSizer(wx.HORIZONTAL)

        self.open_btn = wx.Button(self, label=_("&View notification…"))
        self.open_btn.Bind(wx.EVT_BUTTON, self._onOpenNotification)
        button_sizer.Add(self.open_btn, 0, wx.RIGHT, 8)

        self.mark_read_btn = wx.Button(self, label=_("&Mark as read"))
        self.mark_read_btn.Bind(wx.EVT_BUTTON, self._onMarkRead)
        button_sizer.Add(self.mark_read_btn, 0, wx.RIGHT, 8)

        self.mark_all_btn = wx.Button(self, label=_("Mark &all as read"))
        self.mark_all_btn.Bind(wx.EVT_BUTTON, self._onMarkAllRead)
        button_sizer.Add(self.mark_all_btn, 0, wx.RIGHT, 8)

        self.web_btn = wx.Button(self, label=_("&Open on web"))
        self.web_btn.Bind(wx.EVT_BUTTON, self._onOpenWeb)
        button_sizer.Add(self.web_btn, 0, wx.RIGHT, 8)

        self.close_btn = wx.Button(self, wx.ID_CANCEL, _("&Close"))
        self.close_btn.Bind(wx.EVT_BUTTON, self._onClose)
        button_sizer.Add(self.close_btn, 0)

        layout.Add(button_sizer, 0, wx.ALIGN_RIGHT | wx.RIGHT | wx.BOTTOM, 10)
        self.SetSizer(layout)
        self.SetMinSize((650, 420))
        self.CentreOnScreen()

        self.Bind(wx.EVT_CLOSE, self._onClose)
        self.Bind(wx.EVT_CHAR_HOOK, self._onCharHook)
        wx.CallAfter(self.loadNotifications)

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

    def _onFilterChanged(self, event):
        self.loadNotifications()

    def _onListKey(self, event):
        code = event.GetKeyCode()
        if code == wx.WXK_RETURN:
            self._onOpenNotification(None)
            return
        if code == wx.WXK_SPACE:
            self._onMarkRead(None)
            return
        if code == wx.WXK_F5:
            self.loadNotifications()
            return
        event.Skip()

    def loadNotifications(self):
        if self._closing or not self:
            return
        self._setStatus(_("Loading notifications…"))
        self.notif_list.DeleteAllItems()
        all_notifs = (self.filter_choice.GetSelection() == 1)

        def background_task():
            if hasattr(self.service, "loadNotifications"):
                return self.service.loadNotifications(all_notifications=all_notifs)
            return []

        import threading

        def thread_target():
            try:
                result = background_task()
                wx.CallAfter(self._onNotificationsLoaded, result)
            except Exception as e:
                wx.CallAfter(self._onNotificationsError, e)

        self._worker = threading.Thread(target=thread_target, daemon=True)
        self._worker.start()

    def _onNotificationsLoaded(self, notifications):
        if self._closing or not self:
            return
        self.notifications = notifications
        self.notif_list.DeleteAllItems()
        for idx, item in enumerate(notifications):
            repo = item.get("repository") or ""
            pos = self.notif_list.InsertItem(idx, repo)
            read_label = _("Unread") if item.get("unread") else _("Read")
            self.notif_list.SetItem(pos, 1, read_label)
            self.notif_list.SetItem(pos, 2, getTypeLabel(item.get("subject_type") or ""))
            self.notif_list.SetItem(pos, 3, item.get("subject_title") or "")
            self.notif_list.SetItem(pos, 4, getReasonLabel(item.get("reason") or ""))
            date_str = (item.get("updated_at") or "")[:10]
            self.notif_list.SetItem(pos, 5, date_str)

        if notifications:
            msg = _("%s notifications listed.") % len(notifications)
            self._setStatus(msg)
            ui.message(msg)
            self.notif_list.Select(0)
            self.notif_list.Focus(0)
            self.notif_list.SetFocus()
        else:
            msg = _("No notifications found.")
            self._setStatus(msg)
            ui.message(msg)
            self.filter_choice.SetFocus()

    def _onNotificationsError(self, err):
        if self._closing or not self:
            return
        if isinstance(err, (AuthError, CredentialError, SettingsError, OSError)):
            msg = errorMessage(err)
        else:
            msg = _("Could not load notifications.")
        self._setStatus(msg)
        ui.message(msg)

    def _selectedNotification(self):
        index = self.notif_list.GetFirstSelected()
        if 0 <= index < len(self.notifications):
            return self.notifications[index]
        return None

    def _onMarkRead(self, event):
        if self._closing or not self:
            return
        item = self._selectedNotification()
        if not item:
            return

        def worker():
            try:
                if hasattr(self.service, "markNotificationRead"):
                    self.service.markNotificationRead(item["id"])
                item["unread"] = False

                def on_ok():
                    ui.message(_("Notification marked as read."))
                    if not self._closing and self:
                        self.loadNotifications()

                wx.CallAfter(on_ok)
            except Exception as err:
                def on_err():
                    if isinstance(err, (AuthError, CredentialError, SettingsError, OSError)):
                        ui.message(errorMessage(err))
                    else:
                        ui.message(_("Failed to mark notification as read."))

                wx.CallAfter(on_err)

        import threading
        threading.Thread(target=worker, daemon=True).start()


    def _onMarkAllRead(self, event):
        if self._closing or not self:
            return

        def worker():
            try:
                if hasattr(self.service, "markAllNotificationsRead"):
                    self.service.markAllNotificationsRead()

                def on_ok():
                    ui.message(_("All notifications marked as read."))
                    if not self._closing and self:
                        self.loadNotifications()

                wx.CallAfter(on_ok)
            except Exception as err:
                def on_err():
                    if isinstance(err, (AuthError, CredentialError, SettingsError, OSError)):
                        ui.message(errorMessage(err))
                    else:
                        ui.message(_("Failed to mark all notifications as read."))

                wx.CallAfter(on_err)

        import threading
        threading.Thread(target=worker, daemon=True).start()


    def _onOpenWeb(self, event=None, item=None):
        if self._closing or not self:
            return
        target = item if item is not None else self._selectedNotification()
        if not target:
            return
        url = target.get("html_url") or target.get("repo_html_url") or ""
        if _isSafeGitHubWebUrl(url):
            try:
                webbrowser.open(url.strip(), new=2)
                return
            except OSError:
                pass
        ui.message(_("Could not open notification address."))

    def _onOpenNotification(self, event):
        if self._closing or not self or self._opening_detail or self._child_dlg is not None:
            return
        index = self.notif_list.GetFirstSelected()
        if not (0 <= index < len(self.notifications)):
            return
        item = self.notifications[index]

        subject_type = item.get("subject_type")
        subject_url = item.get("subject_url")
        full_name = item.get("repository")

        # Mark as read in background and update list status immediately
        if item.get("unread") and hasattr(self.service, "markNotificationRead"):
            item["unread"] = False
            self.notif_list.SetItem(index, 1, _("Read"))
            import threading

            def _mark_bg():
                try:
                    self.service.markNotificationRead(item["id"])
                except Exception:
                    pass

            threading.Thread(target=_mark_bg, daemon=True).start()

        if subject_type == "Issue" and subject_url:
            self._openIssueInAddon(full_name, subject_url, item=item)
        elif subject_type == "Release" and subject_url:
            self._openReleaseInAddon(full_name, subject_url, item=item)
        elif subject_type in ("PullRequest", "Pull Request") and subject_url:
            self._openPullRequestInAddon(full_name, subject_url, item=item)
        else:
            self._onOpenWeb(None, item=item)

    def _openIssueInAddon(self, full_name, subject_url, item=None):
        if self._closing or not self or self._opening_detail or self._child_dlg is not None:
            return
        self._opening_detail = True
        target_item = item if item is not None else self._selectedNotification()
        load_msg = _("Loading issue…")
        self._setStatus(load_msg)
        ui.message(load_msg)
        import threading

        def worker():
            try:
                if _hasServiceMethod(self.service, "fetchNotificationResource"):
                    issue_data = self.service.fetchNotificationResource(subject_url)
                else:
                    token = self.service.getAccessToken() if hasattr(self.service, "getAccessToken") else ""
                    issue_data = fetchResource(token, subject_url)
                if not issue_data or not isinstance(issue_data, dict):
                    def fallback_web():
                        self._opening_detail = False
                        if self._closing or not self:
                            return
                        self._setStatus("")
                        self._onOpenWeb(None, item=target_item)
                    wx.CallAfter(fallback_web)
                    return

                issue_num = issue_data.get("number") or 0
                comments = []
                if issue_num and full_name:
                    try:
                        if _hasServiceMethod(self.service, "loadIssueComments"):
                            comments = self.service.loadIssueComments(full_name, issue_num)
                        else:
                            token = self.service.getAccessToken() if hasattr(self.service, "getAccessToken") else ""
                            if token:
                                comments = getIssueComments(token, full_name, issue_num)
                    except Exception:
                        comments = None

                def show_issue():
                    self._opening_detail = False
                    if self._closing or not self or self._child_dlg is not None:
                        return
                    self._setStatus("")
                    user_obj = issue_data.get("user") or {}
                    issue_dict = {
                        "number": issue_num,
                        "title": issue_data.get("title") or "",
                        "state": issue_data.get("state") or "open",
                        "user": (user_obj.get("login") or "") if isinstance(user_obj, dict) else "",
                        "created_at": issue_data.get("created_at") or "",
                        "body": issue_data.get("body") or "",
                    }

                    def on_add_comment(parent_dlg):
                        c_dlg = NewCommentDialog(parent_dlg, issue_dict["title"])
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
                                self.service.addIssueComment(full_name, issue_dict["number"], text)

                                def on_ok():
                                    ui.message(_("Comment added successfully."))
                                    if parent_dlg and not parent_dlg._closing:
                                        parent_dlg._onClose()

                                wx.CallAfter(on_ok)
                            except Exception as err:
                                def on_err():
                                    if parent_dlg and not parent_dlg._closing:
                                        parent_dlg.comment_btn.Enable(True)
                                    if isinstance(err, (AuthError, CredentialError, SettingsError, OSError)):
                                        ui.message(errorMessage(err))
                                    else:
                                        ui.message(_("Failed to add comment."))

                                wx.CallAfter(on_err)

                        threading.Thread(target=comment_worker, daemon=True).start()

                    def on_toggle_state(parent_dlg):
                        new_state = "open" if issue_dict["state"] == "closed" else "closed"
                        parent_dlg.toggle_state_btn.Enable(False)

                        def state_worker():
                            try:
                                self.service.setIssueState(full_name, issue_dict["number"], state=new_state)
                                issue_dict["state"] = new_state

                                def on_ok():
                                    action_msg = _("Issue closed.") if new_state == "closed" else _("Issue reopened.")
                                    ui.message(action_msg)
                                    if parent_dlg and not parent_dlg._closing:
                                        parent_dlg._onClose()

                                wx.CallAfter(on_ok)
                            except Exception as err:
                                def on_err():
                                    if parent_dlg and not parent_dlg._closing:
                                        parent_dlg.toggle_state_btn.Enable(True)
                                    if isinstance(err, (AuthError, CredentialError, SettingsError, OSError)):
                                        ui.message(errorMessage(err))
                                    else:
                                        ui.message(_("Failed to change issue state."))

                                wx.CallAfter(on_err)

                        threading.Thread(target=state_worker, daemon=True).start()

                    self._runNestedModal(IssueDetailDialog(self, issue_dict, comments, on_add_comment, on_toggle_state))

                wx.CallAfter(show_issue)
            except Exception:
                def fallback_err():
                    self._opening_detail = False
                    if self._closing or not self:
                        return
                    self._setStatus("")
                    self._onOpenWeb(None, item=target_item)
                wx.CallAfter(fallback_err)

        threading.Thread(target=worker, daemon=True).start()


    def _openReleaseInAddon(self, full_name, subject_url, item=None):
        if self._closing or not self or self._opening_detail or self._child_dlg is not None:
            return
        self._opening_detail = True
        target_item = item if item is not None else self._selectedNotification()
        load_msg = _("Loading release…")
        self._setStatus(load_msg)
        ui.message(load_msg)
        import threading

        def worker():
            try:
                if _hasServiceMethod(self.service, "fetchNotificationResource"):
                    rel_data = self.service.fetchNotificationResource(subject_url)
                else:
                    token = self.service.getAccessToken() if hasattr(self.service, "getAccessToken") else ""
                    rel_data = fetchResource(token, subject_url)
                if not rel_data or not isinstance(rel_data, dict):
                    def fallback_web():
                        self._opening_detail = False
                        if self._closing or not self:
                            return
                        self._setStatus("")
                        self._onOpenWeb(None, item=target_item)
                    wx.CallAfter(fallback_web)
                    return

                assets = []
                for a in (rel_data.get("assets") or []):
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

                author_obj = rel_data.get("author") or {}
                release_dict = {
                    "id": rel_data.get("id") or 0,
                    "name": rel_data.get("name") or rel_data.get("tag_name") or "",
                    "tag_name": rel_data.get("tag_name") or "",
                    "author": (author_obj.get("login") or "") if isinstance(author_obj, dict) else "",
                    "created_at": rel_data.get("created_at") or "",
                    "published_at": rel_data.get("published_at") or rel_data.get("created_at") or "",
                    "body": rel_data.get("body") or "",
                    "html_url": rel_data.get("html_url") or "",
                    "draft": bool(rel_data.get("draft", False)),
                    "prerelease": bool(rel_data.get("prerelease", False)),
                    "assets": assets,
                }

                def show_release():
                    self._opening_detail = False
                    if self._closing or not self or self._child_dlg is not None:
                        return
                    self._setStatus("")
                    self._runNestedModal(ReleaseDetailDialog(self, release_dict, full_name, self.service))

                wx.CallAfter(show_release)
            except Exception:
                def fallback_err():
                    self._opening_detail = False
                    if self._closing or not self:
                        return
                    self._setStatus("")
                    self._onOpenWeb(None, item=target_item)
                wx.CallAfter(fallback_err)

        threading.Thread(target=worker, daemon=True).start()

    def _openPullRequestInAddon(self, full_name, subject_url, item=None):
        if self._closing or not self or self._opening_detail or self._child_dlg is not None:
            return
        self._opening_detail = True
        target_item = item if item is not None else self._selectedNotification()
        load_msg = _("Loading pull request…")
        self._setStatus(load_msg)
        ui.message(load_msg)
        import threading

        def worker():
            try:
                if _hasServiceMethod(self.service, "fetchNotificationResource"):
                    pr_data = self.service.fetchNotificationResource(subject_url)
                else:
                    token = self.service.getAccessToken() if hasattr(self.service, "getAccessToken") else ""
                    pr_data = fetchResource(token, subject_url)
                if not pr_data or not isinstance(pr_data, dict):
                    def fallback_web():
                        self._opening_detail = False
                        if self._closing or not self:
                            return
                        self._setStatus("")
                        self._onOpenWeb(None, item=target_item)
                    wx.CallAfter(fallback_web)
                    return

                pr_num = pr_data.get("number") or 0
                files = []
                comments = []
                if pr_num and full_name:
                    try:
                        if _hasServiceMethod(self.service, "loadPullRequestFiles"):
                            files = self.service.loadPullRequestFiles(full_name, pr_num)
                        else:
                            token = self.service.getAccessToken() if hasattr(self.service, "getAccessToken") else ""
                            files = getPullRequestFiles(token, full_name, pr_num)
                    except Exception:
                        files = None

                    try:
                        if _hasServiceMethod(self.service, "loadIssueComments"):
                            comments = self.service.loadIssueComments(full_name, pr_num)
                        else:
                            token = self.service.getAccessToken() if hasattr(self.service, "getAccessToken") else ""
                            if token:
                                comments = getIssueComments(token, full_name, pr_num)
                    except Exception:
                        comments = None

                user_obj = pr_data.get("user") or {}
                head_obj = pr_data.get("head") or {}
                base_obj = pr_data.get("base") or {}
                pr_dict = {
                    "number": pr_num,
                    "title": pr_data.get("title") or "",
                    "state": pr_data.get("state") or "open",
                    "user": user_obj.get("login") or "" if isinstance(user_obj, dict) else "",
                    "head": head_obj.get("ref") or "" if isinstance(head_obj, dict) else "",
                    "base": base_obj.get("ref") or "" if isinstance(base_obj, dict) else "",
                    "comments": pr_data.get("comments") or 0,
                    "created_at": pr_data.get("created_at") or "",
                    "body": pr_data.get("body") or "",
                    "html_url": pr_data.get("html_url") or "",
                    "merged": bool(pr_data.get("merged_at")),
                }

                def show_pr():
                    self._opening_detail = False
                    if self._closing or not self or self._child_dlg is not None:
                        return
                    self._setStatus("")

                    def on_add_comment(parent_dlg):
                        c_dlg = NewCommentDialog(parent_dlg, pr_dict["title"])
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
                                self.service.addIssueComment(full_name, pr_dict["number"], text)
                                def on_ok():
                                    ui.message(_("Comment added successfully."))
                                    if parent_dlg and not parent_dlg._closing:
                                        parent_dlg._onClose()
                                wx.CallAfter(on_ok)
                            except Exception as err:
                                def on_err():
                                    if parent_dlg and not parent_dlg._closing:
                                        parent_dlg.comment_btn.Enable(True)
                                    if isinstance(err, (AuthError, CredentialError, SettingsError, OSError)):
                                        ui.message(errorMessage(err))
                                    else:
                                        ui.message(_("Failed to add comment."))
                                wx.CallAfter(on_err)

                        threading.Thread(target=comment_worker, daemon=True).start()

                    def on_merge(parent_dlg):
                        answer = wx.MessageBox(
                            _("Are you sure you want to merge pull request #%s into '%s'?") % (pr_dict["number"], pr_dict.get("base")),
                            _("Merge Pull Request"),
                            wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION,
                            parent_dlg,
                        )
                        if answer != wx.YES or parent_dlg._closing or self._closing:
                            return
                        parent_dlg.merge_btn.Enable(False)

                        def merge_worker():
                            try:
                                if _hasServiceMethod(self.service, "mergePullRequest"):
                                    self.service.mergePullRequest(full_name, pr_dict["number"])
                                else:
                                    token = self.service.getAccessToken() if hasattr(self.service, "getAccessToken") else ""
                                    mergePullRequest(token, full_name, pr_dict["number"])

                                def on_merge_ok():
                                    ui.message(_("Pull request merged successfully."))
                                    if parent_dlg and not parent_dlg._closing:
                                        parent_dlg._onClose()
                                    if not self._closing and self:
                                        self.loadNotifications()

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
                        new_state = "open" if pr_dict["state"] == "closed" else "closed"
                        parent_dlg.toggle_state_btn.Enable(False)

                        def state_worker():
                            try:
                                if _hasServiceMethod(self.service, "setPullRequestState"):
                                    self.service.setPullRequestState(full_name, pr_dict["number"], state=new_state)
                                else:
                                    token = self.service.getAccessToken() if hasattr(self.service, "getAccessToken") else ""
                                    setPullRequestState(token, full_name, pr_dict["number"], state=new_state)
                                pr_dict["state"] = new_state

                                def on_ok():
                                    action_msg = _("Pull request closed.") if new_state == "closed" else _("Pull request reopened.")
                                    ui.message(action_msg)
                                    if parent_dlg and not parent_dlg._closing:
                                        parent_dlg._onClose()

                                wx.CallAfter(on_ok)
                            except Exception as err:
                                def on_err():
                                    if parent_dlg and not parent_dlg._closing:
                                        parent_dlg.toggle_state_btn.Enable(True)
                                    if isinstance(err, (AuthError, CredentialError, SettingsError, OSError)):
                                        ui.message(errorMessage(err))
                                    else:
                                        ui.message(_("Failed to change pull request state."))

                                wx.CallAfter(on_err)

                        threading.Thread(target=state_worker, daemon=True).start()

                    self._runNestedModal(PullRequestDetailDialog(self, pr_dict, files, comments, on_add_comment, on_merge, on_toggle_state))

                wx.CallAfter(show_pr)
            except Exception:
                def fallback_err():
                    self._opening_detail = False
                    if self._closing or not self:
                        return
                    self._setStatus("")
                    self._onOpenWeb(None, item=target_item)
                wx.CallAfter(fallback_err)

        threading.Thread(target=worker, daemon=True).start()
