# Copyright (C) 2026 Mehmet Aykurt <m.aykurt38@gmail.com>
# Bu eklenti Mehmet Aykurt tarafından geliştirilmiştir.
# Lisans: GNU General Public License v2 (GPL-2.0)

"""GitHub Issues management: listing, viewing, creating issues, comments, and state changes."""

import addonHandler
addonHandler.initTranslation()

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


def _strip_quotes(s):
    s = s.strip()
    if len(s) >= 2 and ((s[0] == '"' and s[-1] == '"') or (s[0] == "'" and s[-1] == "'")):
        return s[1:-1]
    return s


def _parse_issue_template(filename, raw_content):
    """Parses a Markdown or YAML issue template into a dict with name, title, about, and body."""
    raw_content = raw_content or ""
    lower_fn = filename.lower()

    if lower_fn.endswith((".yml", ".yaml")):
        name = ""
        about = ""
        title = ""
        sections = []

        for line in raw_content.splitlines():
            line_str = line.strip()
            if line_str.startswith("name:"):
                name = _strip_quotes(line_str.split("name:", 1)[1])
            elif line_str.startswith("description:") or line_str.startswith("about:"):
                about = _strip_quotes(line_str.split(":", 1)[1])
            elif line_str.startswith("title:"):
                title = _strip_quotes(line_str.split("title:", 1)[1])
            elif line_str.startswith("body:"):
                break

        blocks = re.split(r"\n\s*-\s+type:\s*", raw_content)
        for block in blocks[1:]:
            lines = block.splitlines()
            b_type = lines[0].strip() if lines else ""
            label = ""
            val = ""
            m_label = re.search(r"label:\s*(.*)", block)
            if m_label:
                label = _strip_quotes(m_label.group(1))
            if b_type == "markdown":
                m_val = re.search(r"value:\s*\|\s*\n(.*?)(\n\s*[a-z_]+:|\Z)", block, re.DOTALL)
                if m_val:
                    val = m_val.group(1).strip()
                else:
                    m_val_single = re.search(r"value:\s*([^\n\r]+)", block)
                    if m_val_single:
                        val = m_val_single.group(1).strip()
                    elif m_label:
                        val = label
                if val:
                    sections.append(val)
            elif label:
                if b_type == "checkboxes":
                    opts = re.findall(r"label:\s*([^\n\r]+)", block)
                    opts_text = "\n".join(f"- [ ] {opt.strip(' \'"')}" for opt in opts[1:]) if len(opts) > 1 else ""
                    sections.append(f"### {label}\n{opts_text}".rstrip())
                else:
                    sections.append(f"### {label}\n")

        if not name:
            name = filename.rsplit(".", 1)[0].replace("-", " ").replace("_", " ").title()
        return {
            "name": name,
            "about": about,
            "title": title,
            "body": "\n\n".join(sections),
            "filename": filename,
        }

    # Markdown template (.md)
    name = ""
    about = ""
    title = ""
    body = raw_content

    m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", raw_content, re.DOTALL)
    if m:
        fm, body = m.groups()
        for line in fm.splitlines():
            line_str = line.strip()
            if line_str.startswith("name:"):
                name = _strip_quotes(line_str.split("name:", 1)[1])
            elif line_str.startswith("about:") or line_str.startswith("description:"):
                about = _strip_quotes(line_str.split(":", 1)[1])
            elif line_str.startswith("title:"):
                title = _strip_quotes(line_str.split(":", 1)[1])

    if not name:
        name = filename.rsplit(".", 1)[0].replace("-", " ").replace("_", " ").title()

    return {
        "name": name,
        "about": about,
        "title": title,
        "body": body.strip(),
        "filename": filename,
    }


def getIssueTemplates(token, full_name, cancel=None):
    """Fetches and parses issue templates for a repository."""
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", full_name):
        return []
    _check_cancelled(cancel)

    opener = _build_opener()
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/vnd.github.v3+json",
        "Authorization": f"Bearer {token}",
    }

    templates = []
    dir_url = f"https://api.github.com/repos/{full_name}/contents/.github/ISSUE_TEMPLATE"
    req = urllib.request.Request(dir_url, headers=headers)
    items = None

    try:
        with opener.open(req, timeout=15) as response:
            items = json.loads(response.read().decode("utf-8"))
    except Exception:
        items = None

    _check_cancelled(cancel)

    if isinstance(items, list):
        for item in items:
            _check_cancelled(cancel)
            if not isinstance(item, dict) or item.get("type") != "file":
                continue
            fname = item.get("name", "")
            lower_fname = fname.lower()
            if not lower_fname.endswith((".md", ".yaml", ".yml")) or lower_fname.startswith("config."):
                continue
            path = item.get("path") or f".github/ISSUE_TEMPLATE/{fname}"
            file_url = f"https://api.github.com/repos/{full_name}/contents/{path}"
            raw_headers = dict(headers)
            raw_headers["Accept"] = "application/vnd.github.raw+json"
            raw_req = urllib.request.Request(file_url, headers=raw_headers)
            try:
                with opener.open(raw_req, timeout=15) as resp:
                    raw_content = resp.read().decode("utf-8", errors="replace")
                tmpl = _parse_issue_template(fname, raw_content)
                if tmpl:
                    templates.append(tmpl)
            except Exception:
                continue

    if not templates:
        for single_path in ("ISSUE_TEMPLATE.md", ".github/issue_template.md", "issue_template.md"):
            _check_cancelled(cancel)
            file_url = f"https://api.github.com/repos/{full_name}/contents/{single_path}"
            raw_headers = dict(headers)
            raw_headers["Accept"] = "application/vnd.github.raw+json"
            raw_req = urllib.request.Request(file_url, headers=raw_headers)
            try:
                with opener.open(raw_req, timeout=15) as resp:
                    raw_content = resp.read().decode("utf-8", errors="replace")
                tmpl = _parse_issue_template(single_path.split("/")[-1], raw_content)
                if tmpl:
                    templates.append(tmpl)
                    break
            except Exception:
                continue

    return templates


class NewIssueDialog(wx.Dialog):
    """Accessible dialog for creating a new issue, with template support."""

    def __init__(self, parent, repo_name, service=None, templates=None):
        super().__init__(
            parent,
            title=_("New issue — %s") % repo_name,
            size=(600, 500),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        self._repo_name = repo_name
        self._service = service
        self._templates = list(templates) if templates else []
        self._closing = False
        self._cancel = threading.Event()

        layout = wx.BoxSizer(wx.VERTICAL)

        # Template selection
        template_label = wx.StaticText(self, label=_("&Template:"))
        layout.Add(template_label, 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)
        self.template_choice = wx.Choice(self, choices=[_("Blank / Default form")])
        self.template_choice.SetName(_("Template"))
        self.template_choice.SetSelection(0)
        self.template_choice.Bind(wx.EVT_CHOICE, self._onTemplateChanged)
        layout.Add(self.template_choice, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)

        title_label = wx.StaticText(self, label=_("&Title:"))
        layout.Add(title_label, 0, wx.LEFT | wx.RIGHT | wx.TOP, 5)
        self.title_ctrl = wx.TextCtrl(self)
        self.title_ctrl.SetName(_("Title"))
        layout.Add(self.title_ctrl, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        body_label = wx.StaticText(self, label=_("&Description (optional):"))
        layout.Add(body_label, 0, wx.LEFT | wx.RIGHT | wx.TOP, 5)
        self.body_ctrl = wx.TextCtrl(self, style=wx.TE_MULTILINE | wx.HSCROLL)
        self.body_ctrl.SetName(_("Description (optional)"))
        layout.Add(self.body_ctrl, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        action_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.add_file_btn = wx.Button(self, label=_("&Add file…"))
        self.add_file_btn.SetName(_("Add file"))
        self.add_file_btn.Bind(wx.EVT_BUTTON, self._onAddFile)
        action_sizer.Add(self.add_file_btn, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 10)

        action_sizer.Add((0, 0), 1, wx.EXPAND)

        self.ok_btn = wx.Button(self, wx.ID_OK, _("&Submit new issue"))
        self.ok_btn.SetDefault()
        self.ok_btn.Bind(wx.EVT_BUTTON, self._onSubmit)
        action_sizer.Add(self.ok_btn, 0, wx.RIGHT, 10)

        self.cancel_btn = wx.Button(self, wx.ID_CANCEL, _("&Cancel"))
        action_sizer.Add(self.cancel_btn, 0)

        layout.Add(action_sizer, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        self.SetSizer(layout)
        self.SetMinSize((450, 400))
        self.CentreOnScreen()

        if self._templates:
            self._setTemplates(self._templates)
        elif self._service:
            self._loadTemplatesAsync()

        wx.CallAfter(self.title_ctrl.SetFocus)

    def _loadTemplatesAsync(self):
        def worker():
            try:
                tmpls = self._service.getIssueTemplates(self._repo_name, cancel=self._cancel)
                if not self._closing and tmpls:
                    wx.CallAfter(self._setTemplates, tmpls)
            except Exception:
                pass
        threading.Thread(target=worker, daemon=True).start()

    def _setTemplates(self, templates):
        if self._closing or not self or not templates:
            return
        self._templates = templates
        current_sel = self.template_choice.GetSelection()
        self.template_choice.Clear()
        self.template_choice.Append(_("Blank / Default form"))
        for tmpl in templates:
            name = tmpl.get("name") or tmpl.get("filename") or _("Unnamed template")
            self.template_choice.Append(name)
        if 0 <= current_sel < self.template_choice.GetCount():
            self.template_choice.SetSelection(current_sel)
        else:
            self.template_choice.SetSelection(0)

    def _onTemplateChanged(self, event=None):
        sel = self.template_choice.GetSelection()
        if sel <= 0 or not self._templates or sel > len(self._templates):
            return
        tmpl = self._templates[sel - 1]
        body = tmpl.get("body", "")
        if body:
            self.body_ctrl.SetValue(body)
        title_prefix = tmpl.get("title", "")
        if title_prefix:
            curr_title = self.title_ctrl.GetValue().strip()
            if not curr_title:
                self.title_ctrl.SetValue(title_prefix)

    def _onAddFile(self, event=None, filePath=None):
        if filePath is None:
            wildcard = (
                _("All supported files (*.log;*.txt;*.json;*.md;*.py;*.ini;*.diff;*.patch)")
                + "|*.log;*.txt;*.json;*.md;*.py;*.ini;*.diff;*.patch|"
                + _("Log and text files (*.log;*.txt)")
                + "|*.log;*.txt|"
                + _("All files (*.*)")
                + "|*.*"
            )
            with wx.FileDialog(
                self,
                message=_("Select file to attach"),
                wildcard=wildcard,
                style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST,
            ) as file_dlg:
                if file_dlg.ShowModal() != wx.ID_OK:
                    return
                path = file_dlg.GetPath()
        else:
            path = filePath

        if not path or not os.path.isfile(path):
            return

        try:
            size = os.path.getsize(path)
            if size > 1024 * 1024:
                wx.MessageBox(
                    _("The selected file is too large (%s MB). Maximum attachment size is 1 MB.") % round(size / (1024 * 1024), 2),
                    _("Error"),
                    wx.OK | wx.ICON_ERROR,
                    self,
                )
                return
        except Exception:
            pass

        filename = os.path.basename(path)
        content = None
        for enc in ("utf-8", "cp1254", "latin-1"):
            try:
                with open(path, "r", encoding=enc) as f:
                    content = f.read()
                break
            except (UnicodeDecodeError, OSError):
                continue

        if content is None:
            wx.MessageBox(_("Could not read file."), _("Error"), wx.OK | wx.ICON_ERROR, self)
            return

        ext = os.path.splitext(filename)[1].lower().lstrip(".")
        lang_map = {
            "log": "log",
            "txt": "text",
            "json": "json",
            "py": "python",
            "md": "markdown",
            "ini": "ini",
            "diff": "diff",
            "patch": "diff",
            "xml": "xml",
            "html": "html",
            "yaml": "yaml",
            "yml": "yaml",
        }
        lang = lang_map.get(ext, "")

        attachment_block = (
            f"<details>\n"
            f"<summary>{_('Attachment: %s') % filename}</summary>\n\n"
            f"```{lang}\n"
            f"{content.rstrip()}\n"
            f"```\n"
            f"</details>"
        )

        curr_body = self.body_ctrl.GetValue()
        if curr_body.strip():
            new_body = curr_body.rstrip() + "\n\n" + attachment_block + "\n"
        else:
            new_body = attachment_block + "\n"

        self.body_ctrl.SetValue(new_body)
        ui.message(_("File '%s' attached.") % filename)

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
        self._closing = True
        if self._cancel is not None:
            self._cancel.set()
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

    def _onAddFile(self, event=None, filePath=None):
        if filePath is None:
            wildcard = (
                _("All supported files (*.log;*.txt;*.json;*.md;*.py;*.ini;*.diff;*.patch)")
                + "|*.log;*.txt;*.json;*.md;*.py;*.ini;*.diff;*.patch|"
                + _("Log and text files (*.log;*.txt)")
                + "|*.log;*.txt|"
                + _("All files (*.*)")
                + "|*.*"
            )
            with wx.FileDialog(
                self,
                message=_("Select file to attach"),
                wildcard=wildcard,
                style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST,
            ) as file_dlg:
                if file_dlg.ShowModal() != wx.ID_OK:
                    return
                path = file_dlg.GetPath()
        else:
            path = filePath

        if not path or not os.path.isfile(path):
            return

        try:
            size = os.path.getsize(path)
            if size > 1024 * 1024:
                wx.MessageBox(
                    _("The selected file is too large (%s MB). Maximum attachment size is 1 MB.") % round(size / (1024 * 1024), 2),
                    _("Error"),
                    wx.OK | wx.ICON_ERROR,
                    self,
                )
                return
        except Exception:
            pass

        filename = os.path.basename(path)
        content = None
        for enc in ("utf-8", "cp1254", "latin-1"):
            try:
                with open(path, "r", encoding=enc) as f:
                    content = f.read()
                break
            except (UnicodeDecodeError, OSError):
                continue

        if content is None:
            wx.MessageBox(_("Could not read file."), _("Error"), wx.OK | wx.ICON_ERROR, self)
            return

        ext = os.path.splitext(filename)[1].lower().lstrip(".")
        lang_map = {
            "log": "log",
            "txt": "text",
            "json": "json",
            "py": "python",
            "md": "markdown",
            "ini": "ini",
            "diff": "diff",
            "patch": "diff",
            "xml": "xml",
            "html": "html",
            "yaml": "yaml",
            "yml": "yaml",
        }
        lang = lang_map.get(ext, "")

        attachment_block = (
            f"<details>\n"
            f"<summary>{_('Attachment: %s') % filename}</summary>\n\n"
            f"```{lang}\n"
            f"{content.rstrip()}\n"
            f"```\n"
            f"</details>"
        )

        curr_body = self.body_ctrl.GetValue()
        if curr_body.strip():
            new_body = curr_body.rstrip() + "\n\n" + attachment_block + "\n"
        else:
            new_body = attachment_block + "\n"

        self.body_ctrl.SetValue(new_body)
        ui.message(_("File '%s' attached.") % filename)

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
        if hasattr(wx, 'EVT_LIST_ITEM_SELECTED'):
            self.issues_list.Bind(wx.EVT_LIST_ITEM_SELECTED, self._onItemSelected)
        if hasattr(wx, 'EVT_LIST_ITEM_DESELECTED'):
            self.issues_list.Bind(wx.EVT_LIST_ITEM_DESELECTED, self._onItemDeselected)
        self.issues_list.Bind(wx.EVT_CONTEXT_MENU, self._onContextMenu)
        layout.Add(self.issues_list, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        # Status text
        self.status_label = wx.StaticText(self, label="")
        layout.Add(self.status_label, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)

        # Buttons
        button_sizer = wx.BoxSizer(wx.HORIZONTAL)

        self.view_btn = wx.Button(self, label=_("&View issue…"))
        self.view_btn.Bind(wx.EVT_BUTTON, self._onViewIssue)
        button_sizer.Add(self.view_btn, 0, wx.RIGHT, 10)

        self.toggle_state_btn = wx.Button(self, label=_("&Close issue"))
        self.toggle_state_btn.Bind(wx.EVT_BUTTON, self._onToggleState)
        self.toggle_state_btn.Enable(False)
        button_sizer.Add(self.toggle_state_btn, 0, wx.RIGHT, 10)

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
        if event.GetKeyCode() == ord("C") and event.ControlDown() and event.ShiftDown():
            self._onToggleState(None)
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
            self._onItemSelected()
        else:
            self._onItemSelected()
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

    def _onItemSelected(self, event=None):
        if not hasattr(self, "toggle_state_btn") or not self.toggle_state_btn:
            return
        issue = self._selectedIssue()
        if not issue:
            self.toggle_state_btn.SetLabel(_("&Close issue"))
            self.toggle_state_btn.Enable(False)
            return
        self.toggle_state_btn.Enable(True)
        if issue.get("state") == "closed":
            self.toggle_state_btn.SetLabel(_("&Reopen issue"))
        else:
            self.toggle_state_btn.SetLabel(_("&Close issue"))

    def _onItemDeselected(self, event=None):
        wx.CallAfter(self._onItemSelected)

    def _onToggleState(self, event=None):
        if self._closing or not self or self._child_dlg is not None:
            return
        issue = self._selectedIssue()
        if not issue:
            ui.message(_("Please select an issue first."))
            return

        new_state = "open" if issue.get("state") == "closed" else "closed"
        progress_msg = _("Closing issue…") if new_state == "closed" else _("Reopening issue…")
        self._setStatus(progress_msg)
        ui.message(progress_msg)
        self.toggle_state_btn.Enable(False)

        def worker():
            try:
                self.service.setIssueState(self.full_name, issue["number"], state=new_state)
                issue["state"] = new_state

                def on_ok():
                    action_msg = _("Issue closed.") if new_state == "closed" else _("Issue reopened.")
                    ui.message(action_msg)
                    if not self._closing and self:
                        self.loadIssues()

                wx.CallAfter(on_ok)
            except Exception as err:
                def on_err():
                    if not self._closing and self:
                        self.toggle_state_btn.Enable(True)
                    if isinstance(err, (AuthError, CredentialError, SettingsError, OSError)):
                        ui.message(errorMessage(err))
                    else:
                        ui.message(_("Failed to change issue state."))

                wx.CallAfter(on_err)

        threading.Thread(target=worker, daemon=True).start()

    def _onContextMenu(self, event):
        issue = self._selectedIssue()
        if not issue:
            return
        menu = wx.Menu()

        view_item = menu.Append(wx.ID_ANY, _("&View issue…") + "\tEnter")
        menu.Bind(wx.EVT_MENU, self._onViewIssue, id=view_item.GetId())

        state_label = _("&Reopen issue") if issue.get("state") == "closed" else _("&Close issue")
        state_item = menu.Append(wx.ID_ANY, state_label + "\tCtrl+Shift+C")
        menu.Bind(wx.EVT_MENU, self._onToggleState, id=state_item.GetId())

        new_item = menu.Append(wx.ID_ANY, _("&New issue…") + "\tCtrl+N")
        menu.Bind(wx.EVT_MENU, self._onNewIssue, id=new_item.GetId())

        menu.AppendSeparator()

        copy_item = menu.Append(wx.ID_ANY, _("&Copy issue link"))
        menu.Bind(wx.EVT_MENU, lambda e: self._copyIssueLink(issue), id=copy_item.GetId())

        web_item = menu.Append(wx.ID_ANY, _("&Open on web"))
        menu.Bind(wx.EVT_MENU, lambda e: self._openIssueOnWeb(issue), id=web_item.GetId())

        point = wx.DefaultPosition
        idx = self.issues_list.GetFirstSelected()
        if idx >= 0:
            rect = self.issues_list.GetItemRect(idx)
            if hasattr(rect, "x"):
                point = wx.Point(rect.x, rect.y + rect.height)
            elif hasattr(rect, "GetBottomLeft"):
                point = rect.GetBottomLeft()
        self.PopupMenu(menu, point)
        menu.Destroy()

    def _copyIssueLink(self, issue):
        url = issue.get("html_url") or f"https://github.com/{self.full_name}/issues/{issue['number']}"
        if wx.TheClipboard.Open():
            try:
                wx.TheClipboard.SetData(wx.TextDataObject(url))
                ui.message(_("Issue link copied to clipboard."))
            finally:
                wx.TheClipboard.Close()
        else:
            ui.message(_("Clipboard could not be opened."))

    def _openIssueOnWeb(self, issue):
        import webbrowser
        url = issue.get("html_url") or f"https://github.com/{self.full_name}/issues/{issue['number']}"
        webbrowser.open(url)
        ui.message(_("Opening issue on web…"))


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
        dlg = NewIssueDialog(self, self.full_name, service=self.service)
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

