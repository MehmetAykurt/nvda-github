# Copyright (C) 2026 Mehmet Aykurt <m.aykurt38@gmail.com>
# Bu eklenti Mehmet Aykurt tarafından geliştirilmiştir.
# Lisans: GNU General Public License v2 (GPL-2.0)

"""File creation, upload, update, and deletion operations for GitHub repositories."""

import addonHandler
addonHandler.initTranslation()

import base64
import json
import os
import re
import socket
import threading
import urllib.error
import urllib.parse
import urllib.request

import ui
import wx

from .auth import AuthError, checkCancelled
from .downloader import USER_AGENT, _build_opener
from .errors import errorMessage


def _check_cancelled(cancel):
    if cancel is not None:
        checkCancelled(cancel)


def getFileSha(token, full_name, file_path, cancel=None, ref=None):
    """Fetches the current blob SHA of an existing file in the repository."""
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", full_name):
        raise AuthError("invalid_response")
    _check_cancelled(cancel)

    quoted_path = urllib.parse.quote(file_path.strip("/"), safe="/")
    url = f"https://api.github.com/repos/{full_name}/contents/{quoted_path}"
    if ref:
        url += "?ref=" + urllib.parse.quote(ref, safe="")
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
            return data.get("sha")
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        if exc.code == 401:
            raise AuthError("unauthorized") from None
        if exc.code == 403:
            try:
                err_body = exc.read(4096).decode("utf-8", errors="ignore")
            except Exception:
                err_body = ""
            if "too_large" in err_body:
                raise AuthError("file_too_large") from None
            raise AuthError("limited") from None
        if exc.code == 429:
            raise AuthError("limited") from None
        raise AuthError("server_error") from None
    except (urllib.error.URLError, OSError, socket.timeout):
        raise AuthError("network") from None


def createOrUpdateFile(token, full_name, file_path, content_bytes, commit_message, sha=None, cancel=None, branch=None):
    """Creates a new file or updates an existing file on GitHub via the Contents API."""
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", full_name):
        raise AuthError("invalid_response")
    _check_cancelled(cancel)

    clean_path = file_path.strip("/")
    if not clean_path or any(part in ("", ".", "..") for part in clean_path.split("/")):
        raise AuthError("invalid_response")

    quoted_path = urllib.parse.quote(clean_path, safe="/")
    url = f"https://api.github.com/repos/{full_name}/contents/{quoted_path}"

    payload = {
        "message": commit_message or (_("Update %s") % os.path.basename(clean_path)),
        "content": base64.b64encode(content_bytes).decode("ascii"),
    }
    if sha:
        payload["sha"] = sha
    if branch:
        payload["branch"] = branch

    data_bytes = json.dumps(payload).encode("utf-8")
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/vnd.github.v3+json",
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }
    req = urllib.request.Request(url, data=data_bytes, headers=headers, method="PUT")
    opener = _build_opener()

    try:
        with opener.open(req, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            raise AuthError("unauthorized") from None
        if exc.code in (403, 429):
            raise AuthError("limited") from None
        if exc.code in (409, 422):
            raise AuthError("conflict") from None
        raise AuthError("server_error") from None
    except (urllib.error.URLError, OSError, socket.timeout):
        raise AuthError("network") from None


def deleteFile(token, full_name, file_path, sha, commit_message, cancel=None, branch=None):
    """Deletes an existing file on GitHub via the Contents API."""
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", full_name):
        raise AuthError("invalid_response")
    _check_cancelled(cancel)

    clean_path = file_path.strip("/")
    quoted_path = urllib.parse.quote(clean_path, safe="/")
    url = f"https://api.github.com/repos/{full_name}/contents/{quoted_path}"

    payload = {
        "message": commit_message or (_("Delete %s") % clean_path.split("/")[-1]),
        "sha": sha,
    }
    if branch:
        payload["branch"] = branch
    data_bytes = json.dumps(payload).encode("utf-8")
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/vnd.github.v3+json",
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }
    req = urllib.request.Request(url, data=data_bytes, headers=headers, method="DELETE")
    opener = _build_opener()

    try:
        with opener.open(req, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            raise AuthError("unauthorized") from None
        if exc.code in (403, 429):
            raise AuthError("limited") from None
        if exc.code == 404:
            raise AuthError("not_found") from None
        if exc.code in (409, 422):
            raise AuthError("conflict") from None
        raise AuthError("server_error") from None
    except (urllib.error.URLError, OSError, socket.timeout):
        raise AuthError("network") from None

def getRawFileContent(token, full_name, file_path, cancel=None, ref=None):
    """Fetches the raw bytes of a file from GitHub."""
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", full_name):
        raise AuthError("invalid_response")
    _check_cancelled(cancel)

    clean_path = file_path.strip("/")
    quoted_path = urllib.parse.quote(clean_path, safe="/")
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
            return response.read()
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


class NewFileDialog(wx.Dialog):
    """Accessible dialog for creating a new file in a repository directory."""

    def __init__(self, parent, repo_name, current_dir="", existing_names=None):
        title = _("Create new file — %s") % repo_name
        super().__init__(
            parent,
            title=title,
            size=(700, 500),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        self.current_dir = current_dir
        self.existing_names = set(existing_names or ())

        layout = wx.BoxSizer(wx.VERTICAL)

        # File name
        name_label = wx.StaticText(self, label=_("&File name:"))
        layout.Add(name_label, 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)
        self.name_ctrl = wx.TextCtrl(self)
        self.name_ctrl.SetName(_("File name"))
        layout.Add(self.name_ctrl, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        # Commit message
        msg_label = wx.StaticText(self, label=_("&Commit message:"))
        layout.Add(msg_label, 0, wx.LEFT | wx.RIGHT | wx.TOP, 5)
        self.msg_ctrl = wx.TextCtrl(self, value=_("Create new file"))
        self.msg_ctrl.SetName(_("Commit message"))
        layout.Add(self.msg_ctrl, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        # Content
        content_label = wx.StaticText(self, label=_("&File content:"))
        layout.Add(content_label, 0, wx.LEFT | wx.RIGHT | wx.TOP, 5)
        self.content_ctrl = wx.TextCtrl(self, style=wx.TE_MULTILINE | wx.HSCROLL)
        self.content_ctrl.SetName(_("File content"))
        layout.Add(self.content_ctrl, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        # Buttons
        button_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.ok_btn = wx.Button(self, wx.ID_OK, _("&Save"))
        self.ok_btn.SetDefault()
        self.ok_btn.Bind(wx.EVT_BUTTON, self._onSave)
        button_sizer.Add(self.ok_btn, 0, wx.RIGHT, 10)

        self.cancel_btn = wx.Button(self, wx.ID_CANCEL, _("&Cancel"))
        button_sizer.Add(self.cancel_btn, 0)

        layout.Add(button_sizer, 0, wx.ALIGN_RIGHT | wx.RIGHT | wx.BOTTOM, 10)
        self.SetSizer(layout)
        self.SetMinSize((450, 350))
        self.CentreOnScreen()

        wx.CallAfter(self.name_ctrl.SetFocus)

    def _onSave(self, event):
        filename = self.name_ctrl.GetValue().strip()
        if not filename or filename in (".", ".."):
            wx.MessageBox(_("Please enter a file name."), _("Error"), wx.OK | wx.ICON_ERROR, self)
            self.name_ctrl.SetFocus()
            return
        if "/" in filename or "\\" in filename:
            wx.MessageBox(_("File name cannot contain slashes."), _("Error"), wx.OK | wx.ICON_ERROR, self)
            self.name_ctrl.SetFocus()
            return
        if filename in self.existing_names:
            wx.MessageBox(
                _("A file with this name already exists or has been modified on GitHub."),
                _("Error"),
                wx.OK | wx.ICON_ERROR,
                self,
            )
            self.name_ctrl.SetFocus()
            return
        self.EndModal(wx.ID_OK)

    def getResult(self):
        filename = self.name_ctrl.GetValue().strip()
        path = f"{self.current_dir}/{filename}" if self.current_dir else filename
        commit_msg = self.msg_ctrl.GetValue().strip() or (_("Create %s") % filename)
        content_bytes = self.content_ctrl.GetValue().encode("utf-8")
        return path, content_bytes, commit_msg

    def cancelAndClose(self):
        if self.IsModal():
            self.EndModal(wx.ID_CANCEL)


class UploadConfirmDialog(wx.Dialog):
    """Accessible dialog for confirming file upload, monitoring progress, cancelling, and reviewing results."""

    def __init__(
        self,
        parent,
        filename,
        repo_name,
        current_dir="",
        file_count=1,
        local_paths=None,
        service=None,
        branch=None,
        known_sha=None,
    ):
        self.filename = filename
        self.repo_name = repo_name
        self.current_dir = current_dir
        self.file_count = file_count
        self.local_paths = local_paths or []
        self.service = service
        self.branch = branch
        self.known_sha = known_sha

        self._is_uploading = False
        self._is_completed = False
        self._is_cancelled = False
        self.cancel_event = threading.Event()
        self.uploaded_count = 0

        if file_count > 1:
            title = _("Upload files — %s") % repo_name
            label_text = _("Uploading %d files to folder: /%s") % (file_count, current_dir)
            default_msg = _("Upload %d files") % file_count
        else:
            title = _("Upload file — %s") % repo_name
            label_text = _("Uploading '%s' to folder: /%s") % (filename, current_dir)
            default_msg = _("Upload %s") % filename

        super().__init__(
            parent,
            title=title,
            size=(540, 320),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )

        layout = wx.BoxSizer(wx.VERTICAL)

        self.info = wx.StaticText(self, label=label_text)
        layout.Add(self.info, 0, wx.ALL, 10)

        msg_label = wx.StaticText(self, label=_("&Commit message:"))
        layout.Add(msg_label, 0, wx.LEFT | wx.RIGHT | wx.TOP, 5)
        self.msg_ctrl = wx.TextCtrl(self, value=default_msg)
        self.msg_ctrl.SetName(_("Commit message"))
        layout.Add(self.msg_ctrl, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        self.status_label = wx.StaticText(self, label="")
        self.status_label.SetName(_("Upload status"))
        layout.Add(self.status_label, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)

        self.gauge = wx.Gauge(self, range=max(1, file_count), style=wx.GA_HORIZONTAL | getattr(wx, "GA_SMOOTH", 0))
        self.gauge.SetName(_("Upload progress"))
        self.gauge.SetValue(0)
        layout.Add(self.gauge, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        button_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.ok_btn = wx.Button(self, wx.ID_OK, _("&Upload"))
        self.ok_btn.SetDefault()
        self.ok_btn.Bind(wx.EVT_BUTTON, self._onUpload)
        button_sizer.Add(self.ok_btn, 0, wx.RIGHT, 10)

        self.cancel_btn = wx.Button(self, wx.ID_CANCEL, _("&Cancel"))
        self.cancel_btn.Bind(wx.EVT_BUTTON, self._onCancel)
        button_sizer.Add(self.cancel_btn, 0)

        layout.Add(button_sizer, 0, wx.ALIGN_RIGHT | wx.RIGHT | wx.BOTTOM, 10)
        self.SetSizer(layout)
        self.CentreOnScreen()
        self.Bind(wx.EVT_CLOSE, self._onCloseWindow)
        wx.CallAfter(self.msg_ctrl.SetFocus)

    def getCommitMessage(self):
        if self.file_count > 1:
            fallback = _("Upload %d files") % self.file_count
        else:
            fallback = _("Upload %s") % self.filename
        return self.msg_ctrl.GetValue().strip() or fallback

    def _onUpload(self, event):
        if not self.service or not self.local_paths:
            self.EndModal(wx.ID_OK)
            return

        commit_msg = self.getCommitMessage()
        self._is_uploading = True
        self.msg_ctrl.Disable()
        self.ok_btn.Disable()
        self.ok_btn.Hide()
        self.Layout()

        initial_status = _("Uploading files…")
        self.status_label.SetLabel(initial_status)
        ui.message(initial_status)
        self.cancel_btn.SetFocus()

        worker = threading.Thread(
            target=self._uploadWorker,
            args=(commit_msg,),
            name="FileUploadWorker",
            daemon=True,
        )
        worker.start()

    def _uploadWorker(self, commit_msg):
        total = len(self.local_paths)
        try:
            for idx, path in enumerate(self.local_paths, start=1):
                if self.cancel_event.is_set():
                    raise AuthError("cancelled")

                fname = os.path.basename(path)
                if total > 1:
                    progress_msg = _("Uploading file (%d of %d): %s…") % (idx, total, fname)
                else:
                    progress_msg = _("Uploading file: %s…") % fname

                wx.CallAfter(self._onWorkerProgress, idx - 1, total, progress_msg)

                target = f"{self.current_dir}/{fname}" if self.current_dir else fname
                with open(path, "rb") as f:
                    data = f.read()

                sha = self.known_sha if (total == 1 and self.known_sha) else self.service.getFileSha(
                    self.repo_name, target, cancel=self.cancel_event, ref=self.branch
                )
                self.service.createOrUpdateFile(
                    self.repo_name, target, data, commit_msg, sha=sha, cancel=self.cancel_event, branch=self.branch
                )
                self.uploaded_count += 1
                wx.CallAfter(self._onWorkerProgress, idx, total, progress_msg)

            wx.CallAfter(self._onWorkerSuccess)
        except Exception as error:
            if isinstance(error, AuthError) and getattr(error, "code", "") == "cancelled":
                wx.CallAfter(self._onWorkerCancelled)
            else:
                wx.CallAfter(self._onWorkerFailure, error)

    def _onWorkerProgress(self, current, total, msg):
        if self._is_completed or self._is_cancelled:
            return
        self.gauge.SetValue(current)
        self.status_label.SetLabel(msg)
        ui.message(msg)

    def _onWorkerSuccess(self):
        self._is_uploading = False
        self._is_completed = True
        self.gauge.SetValue(self.file_count)

        target_display = f"/{self.current_dir.strip('/')}" if self.current_dir.strip("/") else "/"
        if self.file_count > 1:
            msg = _("Upload complete. %d files have been uploaded to: %s.") % (self.file_count, target_display)
        else:
            msg = _("Upload complete. File '%s' has been uploaded to: %s.") % (self.filename, target_display)

        self.status_label.SetLabel(msg)
        self.cancel_btn.Enable()
        self.cancel_btn.SetLabel(_("&Close"))
        self.cancel_btn.SetId(wx.ID_OK)
        self.cancel_btn.SetDefault()
        self.cancel_btn.SetFocus()
        ui.message(msg)

    def _onWorkerCancelled(self):
        self._is_uploading = False
        self._is_cancelled = True
        msg = _("Upload cancelled by user.")
        self.status_label.SetLabel(msg)
        self.cancel_btn.Enable()
        self.cancel_btn.SetLabel(_("&Close"))
        self.cancel_btn.SetId(wx.ID_CANCEL)
        self.cancel_btn.SetDefault()
        self.cancel_btn.SetFocus()
        ui.message(msg)

    def _onWorkerFailure(self, error):
        self._is_uploading = False
        err_text = errorMessage(error)
        msg = _("Upload failed: %s") % err_text
        self.status_label.SetLabel(msg)
        self.cancel_btn.Enable()
        self.cancel_btn.SetLabel(_("&Close"))
        self.cancel_btn.SetId(wx.ID_CANCEL)
        self.cancel_btn.SetDefault()
        self.cancel_btn.SetFocus()
        ui.message(msg)

    def _onCancel(self, event):
        if self._is_uploading:
            self.cancel_event.set()
            self.cancel_btn.Disable()
            msg = _("Cancelling upload…")
            self.status_label.SetLabel(msg)
            ui.message(msg)
            return

        self.EndModal(wx.ID_OK if self._is_completed else wx.ID_CANCEL)

    def _onCloseWindow(self, event):
        self.cancelAndClose()

    def cancelAndClose(self):
        if self._is_uploading:
            self.cancel_event.set()
        if self.IsModal():
            self.EndModal(wx.ID_OK if self._is_completed else wx.ID_CANCEL)


class UploadFolderConfirmDialog(wx.Dialog):
    """Accessible dialog for confirming folder upload, monitoring progress, cancelling, and reviewing results."""

    def __init__(
        self,
        parent,
        folder_name,
        file_count,
        repo_name,
        current_dir="",
        files_to_upload=None,
        service=None,
        branch=None,
    ):
        title = _("Upload folder — %s") % repo_name
        super().__init__(
            parent,
            title=title,
            size=(540, 320),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        self.folder_name = folder_name
        self.file_count = file_count
        self.repo_name = repo_name
        self.current_dir = current_dir
        self.files_to_upload = files_to_upload or []
        self.service = service
        self.branch = branch

        self._is_uploading = False
        self._is_completed = False
        self._is_cancelled = False
        self.cancel_event = threading.Event()
        self.uploaded_count = 0

        layout = wx.BoxSizer(wx.VERTICAL)

        self.info = wx.StaticText(
            self,
            label=_("Uploading folder '%s' (%d files) to: /%s") % (folder_name, file_count, current_dir),
        )
        layout.Add(self.info, 0, wx.ALL, 10)

        msg_label = wx.StaticText(self, label=_("&Commit message:"))
        layout.Add(msg_label, 0, wx.LEFT | wx.RIGHT | wx.TOP, 5)
        self.msg_ctrl = wx.TextCtrl(self, value=_("Upload folder %s") % folder_name)
        self.msg_ctrl.SetName(_("Commit message"))
        layout.Add(self.msg_ctrl, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        self.status_label = wx.StaticText(self, label="")
        self.status_label.SetName(_("Upload status"))
        layout.Add(self.status_label, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)

        self.gauge = wx.Gauge(self, range=max(1, file_count), style=wx.GA_HORIZONTAL | getattr(wx, "GA_SMOOTH", 0))
        self.gauge.SetName(_("Upload progress"))
        self.gauge.SetValue(0)
        layout.Add(self.gauge, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        button_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.ok_btn = wx.Button(self, wx.ID_OK, _("&Upload"))
        self.ok_btn.SetDefault()
        self.ok_btn.Bind(wx.EVT_BUTTON, self._onUpload)
        button_sizer.Add(self.ok_btn, 0, wx.RIGHT, 10)

        self.cancel_btn = wx.Button(self, wx.ID_CANCEL, _("&Cancel"))
        self.cancel_btn.Bind(wx.EVT_BUTTON, self._onCancel)
        button_sizer.Add(self.cancel_btn, 0)

        layout.Add(button_sizer, 0, wx.ALIGN_RIGHT | wx.RIGHT | wx.BOTTOM, 10)
        self.SetSizer(layout)
        self.CentreOnScreen()
        self.Bind(wx.EVT_CLOSE, self._onCloseWindow)
        wx.CallAfter(self.msg_ctrl.SetFocus)

    def getCommitMessage(self):
        fallback = _("Upload folder %s") % self.folder_name
        return self.msg_ctrl.GetValue().strip() or fallback

    def _onUpload(self, event):
        if not self.service or not self.files_to_upload:
            self.EndModal(wx.ID_OK)
            return

        commit_msg = self.getCommitMessage()
        self._is_uploading = True
        self.msg_ctrl.Disable()
        self.ok_btn.Disable()
        self.ok_btn.Hide()
        self.Layout()

        initial_status = _("Uploading files…")
        self.status_label.SetLabel(initial_status)
        ui.message(initial_status)
        self.cancel_btn.SetFocus()

        target_dir = f"{self.current_dir}/{self.folder_name}" if self.current_dir else self.folder_name
        worker = threading.Thread(
            target=self._uploadWorker,
            args=(commit_msg, target_dir),
            name="FolderUploadWorker",
            daemon=True,
        )
        worker.start()

    def _uploadWorker(self, commit_msg, target_dir):
        total = len(self.files_to_upload)
        try:
            for idx, (abs_path, rel_path) in enumerate(self.files_to_upload, start=1):
                if self.cancel_event.is_set():
                    raise AuthError("cancelled")

                progress_msg = _("Uploading folder '%s' (%d of %d): %s…") % (
                    self.folder_name,
                    idx,
                    total,
                    rel_path,
                )
                wx.CallAfter(self._onWorkerProgress, idx - 1, total, progress_msg)

                target_file_path = f"{target_dir}/{rel_path}"
                with open(abs_path, "rb") as f:
                    data = f.read()

                sha = self.service.getFileSha(
                    self.repo_name, target_file_path, cancel=self.cancel_event, ref=self.branch
                )
                self.service.createOrUpdateFile(
                    self.repo_name,
                    target_file_path,
                    data,
                    commit_msg,
                    sha=sha,
                    cancel=self.cancel_event,
                    branch=self.branch,
                )
                self.uploaded_count += 1
                wx.CallAfter(self._onWorkerProgress, idx, total, progress_msg)

            wx.CallAfter(self._onWorkerSuccess, target_dir)
        except Exception as error:
            if isinstance(error, AuthError) and getattr(error, "code", "") == "cancelled":
                wx.CallAfter(self._onWorkerCancelled)
            else:
                wx.CallAfter(self._onWorkerFailure, error)

    def _onWorkerProgress(self, current, total, msg):
        if self._is_completed or self._is_cancelled:
            return
        self.gauge.SetValue(current)
        self.status_label.SetLabel(msg)
        ui.message(msg)

    def _onWorkerSuccess(self, target_dir):
        self._is_uploading = False
        self._is_completed = True
        self.gauge.SetValue(self.file_count)

        target_display = f"/{target_dir.strip('/')}" if target_dir.strip("/") else "/"
        msg = _("Upload complete. Folder '%s' (%d files) has been uploaded to: %s.") % (
            self.folder_name,
            self.file_count,
            target_display,
        )
        self.status_label.SetLabel(msg)
        self.cancel_btn.Enable()
        self.cancel_btn.SetLabel(_("&Close"))
        self.cancel_btn.SetId(wx.ID_OK)
        self.cancel_btn.SetDefault()
        self.cancel_btn.SetFocus()
        ui.message(msg)

    def _onWorkerCancelled(self):
        self._is_uploading = False
        self._is_cancelled = True
        msg = _("Upload cancelled by user.")
        self.status_label.SetLabel(msg)
        self.cancel_btn.Enable()
        self.cancel_btn.SetLabel(_("&Close"))
        self.cancel_btn.SetId(wx.ID_CANCEL)
        self.cancel_btn.SetDefault()
        self.cancel_btn.SetFocus()
        ui.message(msg)

    def _onWorkerFailure(self, error):
        self._is_uploading = False
        err_text = errorMessage(error)
        msg = _("Upload failed: %s") % err_text
        self.status_label.SetLabel(msg)
        self.cancel_btn.Enable()
        self.cancel_btn.SetLabel(_("&Close"))
        self.cancel_btn.SetId(wx.ID_CANCEL)
        self.cancel_btn.SetDefault()
        self.cancel_btn.SetFocus()
        ui.message(msg)

    def _onCancel(self, event):
        if self._is_uploading:
            self.cancel_event.set()
            self.cancel_btn.Disable()
            msg = _("Cancelling upload…")
            self.status_label.SetLabel(msg)
            ui.message(msg)
            return

        self.EndModal(wx.ID_OK if self._is_completed else wx.ID_CANCEL)

    def _onCloseWindow(self, event):
        self.cancelAndClose()

    def cancelAndClose(self):
        if self._is_uploading:
            self.cancel_event.set()
        if self.IsModal():
            self.EndModal(wx.ID_OK if self._is_completed else wx.ID_CANCEL)


class DeleteConfirmDialog(wx.Dialog):
    """Accessible dialog for confirming file deletion and entering commit message."""

    def __init__(self, parent, filename, repo_name):
        title = _("Delete file — %s") % repo_name
        super().__init__(
            parent,
            title=title,
            size=(500, 250),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        self.filename = filename

        layout = wx.BoxSizer(wx.VERTICAL)

        prompt = wx.StaticText(self, label=_("Are you sure you want to delete '%s'?") % filename)
        layout.Add(prompt, 0, wx.ALL, 10)

        msg_label = wx.StaticText(self, label=_("&Commit message:"))
        layout.Add(msg_label, 0, wx.LEFT | wx.RIGHT | wx.TOP, 5)
        self.msg_ctrl = wx.TextCtrl(self, value=_("Delete %s") % filename)
        self.msg_ctrl.SetName(_("Commit message"))
        layout.Add(self.msg_ctrl, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        button_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.ok_btn = wx.Button(self, wx.ID_OK, _("&Delete"))
        self.ok_btn.SetDefault()
        button_sizer.Add(self.ok_btn, 0, wx.RIGHT, 10)

        self.cancel_btn = wx.Button(self, wx.ID_CANCEL, _("&Cancel"))
        button_sizer.Add(self.cancel_btn, 0)

        layout.Add(button_sizer, 0, wx.ALIGN_RIGHT | wx.RIGHT | wx.BOTTOM, 10)
        self.SetSizer(layout)
        self.CentreOnScreen()
        wx.CallAfter(self.ok_btn.SetFocus)

    def getCommitMessage(self):
        return self.msg_ctrl.GetValue().strip() or (_("Delete %s") % self.filename)

    def cancelAndClose(self):
        if self.IsModal():
            self.EndModal(wx.ID_CANCEL)


class RenameMoveDialog(wx.Dialog):
    """Accessible dialog for renaming or moving a file or folder in a repository."""

    def __init__(self, parent, old_path, repo_name, is_folder=False):
        self.old_path = old_path.strip("/")
        self.repo_name = repo_name
        self.is_folder = is_folder

        if is_folder:
            title = _("Rename / Move Folder — %s") % repo_name
            info_label = _("Current path: /%s (folder)") % self.old_path
            path_label_text = _("&New folder name or path:")
            path_name_text = _("New folder name or path")
            hint_text = _("Hint: Enter a new folder name to rename, or change the directory path to move.")
            default_commit = _("Rename / move folder %s") % self.old_path
        else:
            title = _("Rename / Move File — %s") % repo_name
            info_label = _("Current path: /%s") % self.old_path
            path_label_text = _("&New file name or path:")
            path_name_text = _("New file name or path")
            hint_text = _("Hint: Enter a new file name to rename, or include folders (e.g. 'folder/file.txt') to move.")
            default_commit = _("Rename / move %s") % self.old_path

        super().__init__(
            parent,
            title=title,
            size=(560, 310),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )

        layout = wx.BoxSizer(wx.VERTICAL)

        info = wx.StaticText(self, label=info_label)
        layout.Add(info, 0, wx.ALL, 10)

        path_label = wx.StaticText(self, label=path_label_text)
        layout.Add(path_label, 0, wx.LEFT | wx.RIGHT | wx.TOP, 5)

        self.path_ctrl = wx.TextCtrl(self, value=self.old_path)
        self.path_ctrl.SetName(path_name_text)
        layout.Add(self.path_ctrl, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)

        hint = wx.StaticText(self, label=hint_text)
        layout.Add(hint, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        msg_label = wx.StaticText(self, label=_("&Commit message:"))
        layout.Add(msg_label, 0, wx.LEFT | wx.RIGHT | wx.TOP, 5)

        self.msg_ctrl = wx.TextCtrl(self, value=default_commit)
        self.msg_ctrl.SetName(_("Commit message"))
        layout.Add(self.msg_ctrl, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        self.path_ctrl.Bind(wx.EVT_TEXT, self._onPathChanged)

        button_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.ok_btn = wx.Button(self, wx.ID_OK, _("&Rename / Move"))
        self.ok_btn.SetDefault()
        self.ok_btn.Bind(wx.EVT_BUTTON, self._onOk)
        button_sizer.Add(self.ok_btn, 0, wx.RIGHT, 10)

        self.cancel_btn = wx.Button(self, wx.ID_CANCEL, _("&Cancel"))
        button_sizer.Add(self.cancel_btn, 0)

        layout.Add(button_sizer, 0, wx.ALIGN_RIGHT | wx.RIGHT | wx.BOTTOM, 10)
        self.SetSizer(layout)
        self.CentreOnScreen()
        wx.CallAfter(self.path_ctrl.SetFocus)

    def _cleanPath(self):
        raw = self.path_ctrl.GetValue().strip().replace("\\", "/")
        had_slash = raw.endswith("/")
        clean = raw.strip("/")
        if not self.is_folder and had_slash and clean:
            clean = f"{clean}/{self.old_path.split('/')[-1]}"
        return clean

    def _onPathChanged(self, event):
        new_path = self._cleanPath()
        old_dir = self.old_path.rsplit("/", 1)[0] if "/" in self.old_path else ""
        new_dir = new_path.rsplit("/", 1)[0] if "/" in new_path else ""
        old_name = self.old_path.split("/")[-1]
        new_name = new_path.split("/")[-1] if new_path else ""
        if new_dir != old_dir:
            self.msg_ctrl.SetValue(_("Move %s to %s") % (self.old_path, new_path))
        elif new_name and new_name != old_name:
            self.msg_ctrl.SetValue(_("Rename %s to %s") % (old_name, new_name))
        event.Skip()

    def _onOk(self, event):
        new_path = self._cleanPath()
        if not new_path:
            err_msg = (
                _("Please enter a new folder name or path.")
                if self.is_folder
                else _("Please enter a new file name or path.")
            )
            wx.MessageBox(err_msg, _("Error"), wx.OK | wx.ICON_ERROR, self)
            self.path_ctrl.SetFocus()
            return
        if new_path == self.old_path:
            wx.MessageBox(
                _("The new path is identical to the current path."),
                _("Error"),
                wx.OK | wx.ICON_ERROR,
                self,
            )
            self.path_ctrl.SetFocus()
            return
        if self.is_folder and new_path.startswith(self.old_path + "/"):
            wx.MessageBox(
                _("Cannot move a folder into itself or its subfolder."),
                _("Error"),
                wx.OK | wx.ICON_ERROR,
                self,
            )
            self.path_ctrl.SetFocus()
            return
        parts = new_path.split("/")
        for part in parts:
            if not part or part in (".", ".."):
                err_msg = (
                    _("Please enter a valid folder path.")
                    if self.is_folder
                    else _("Please enter a valid file path.")
                )
                wx.MessageBox(err_msg, _("Error"), wx.OK | wx.ICON_ERROR, self)
                self.path_ctrl.SetFocus()
                return
        self.EndModal(wx.ID_OK)

    def getResult(self):
        new_path = self._cleanPath()
        msg = self.msg_ctrl.GetValue().strip()
        if not msg:
            msg = _("Move %s to %s") % (self.old_path, new_path)
        return new_path, msg

    def cancelAndClose(self):
        if self.IsModal():
            self.EndModal(wx.ID_CANCEL)


class CopyDialog(wx.Dialog):
    """Accessible dialog for copying a file or folder to a new path in a repository."""

    def __init__(self, parent, old_path, repo_name, is_folder=False):
        self.old_path = old_path.strip("/")
        self.repo_name = repo_name
        self.is_folder = is_folder

        if is_folder:
            title = _("Copy Folder — %s") % repo_name
            info_label = _("Current path: /%s (folder)") % self.old_path
            path_label_text = _("&Destination folder path:")
            path_name_text = _("Destination folder path")
            hint_text = _("Hint: Enter a destination folder path (e.g. 'addon/doc').")
            default_commit = _("Copy folder %s to %s") % (self.old_path, self.old_path + "-copy")
        else:
            title = _("Copy File — %s") % repo_name
            info_label = _("Current path: /%s") % self.old_path
            path_label_text = _("&Destination file path:")
            path_name_text = _("Destination file path")
            hint_text = _("Hint: Enter a destination file path (e.g. 'addon/file.txt').")
            default_commit = _("Copy %s") % self.old_path

        super().__init__(
            parent,
            title=title,
            size=(560, 310),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )

        layout = wx.BoxSizer(wx.VERTICAL)

        info = wx.StaticText(self, label=info_label)
        layout.Add(info, 0, wx.ALL, 10)

        path_label = wx.StaticText(self, label=path_label_text)
        layout.Add(path_label, 0, wx.LEFT | wx.RIGHT | wx.TOP, 5)

        self.path_ctrl = wx.TextCtrl(self, value=self.old_path)
        self.path_ctrl.SetName(path_name_text)
        layout.Add(self.path_ctrl, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)

        hint = wx.StaticText(self, label=hint_text)
        layout.Add(hint, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        msg_label = wx.StaticText(self, label=_("&Commit message:"))
        layout.Add(msg_label, 0, wx.LEFT | wx.RIGHT | wx.TOP, 5)

        self.msg_ctrl = wx.TextCtrl(self, value=default_commit)
        self.msg_ctrl.SetName(_("Commit message"))
        layout.Add(self.msg_ctrl, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        self.path_ctrl.Bind(wx.EVT_TEXT, self._onPathChanged)

        button_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.ok_btn = wx.Button(self, wx.ID_OK, _("&Copy"))
        self.ok_btn.SetDefault()
        self.ok_btn.Bind(wx.EVT_BUTTON, self._onOk)
        button_sizer.Add(self.ok_btn, 0, wx.RIGHT, 10)

        self.cancel_btn = wx.Button(self, wx.ID_CANCEL, _("&Cancel"))
        button_sizer.Add(self.cancel_btn, 0)

        layout.Add(button_sizer, 0, wx.ALIGN_RIGHT | wx.RIGHT | wx.BOTTOM, 10)
        self.SetSizer(layout)
        self.CentreOnScreen()
        wx.CallAfter(self.path_ctrl.SetFocus)

    def _cleanPath(self):
        raw = self.path_ctrl.GetValue().strip().replace("\\", "/")
        had_slash = raw.endswith("/")
        clean = raw.strip("/")
        if not self.is_folder and had_slash and clean:
            clean = f"{clean}/{self.old_path.split('/')[-1]}"
        return clean

    def _onPathChanged(self, event):
        new_path = self._cleanPath()
        if self.is_folder:
            self.msg_ctrl.SetValue(_("Copy folder %s to %s") % (self.old_path, new_path or "..."))
        else:
            self.msg_ctrl.SetValue(_("Copy %s to %s") % (self.old_path, new_path or "..."))
        event.Skip()

    def _onOk(self, event):
        new_path = self._cleanPath()
        if not new_path:
            err_msg = (
                _("Please enter a destination folder path.")
                if self.is_folder
                else _("Please enter a destination file path.")
            )
            wx.MessageBox(err_msg, _("Error"), wx.OK | wx.ICON_ERROR, self)
            self.path_ctrl.SetFocus()
            return
        if new_path == self.old_path:
            wx.MessageBox(
                _("The destination path is identical to the current path."),
                _("Error"),
                wx.OK | wx.ICON_ERROR,
                self,
            )
            self.path_ctrl.SetFocus()
            return
        if self.is_folder and new_path.startswith(self.old_path + "/"):
            wx.MessageBox(
                _("Cannot copy a folder into itself or its subfolder."),
                _("Error"),
                wx.OK | wx.ICON_ERROR,
                self,
            )
            self.path_ctrl.SetFocus()
            return
        parts = new_path.split("/")
        for part in parts:
            if not part or part in (".", ".."):
                err_msg = (
                    _("Please enter a valid folder path.")
                    if self.is_folder
                    else _("Please enter a valid file path.")
                )
                wx.MessageBox(err_msg, _("Error"), wx.OK | wx.ICON_ERROR, self)
                self.path_ctrl.SetFocus()
                return
        self.EndModal(wx.ID_OK)

    def getResult(self):
        new_path = self._cleanPath()
        msg = self.msg_ctrl.GetValue().strip()
        if not msg:
            if self.is_folder:
                msg = _("Copy folder %s to %s") % (self.old_path, new_path)
            else:
                msg = _("Copy %s to %s") % (self.old_path, new_path)
        return new_path, msg

    def cancelAndClose(self):
        if self.IsModal():
            self.EndModal(wx.ID_CANCEL)
