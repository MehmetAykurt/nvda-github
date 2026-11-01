# Copyright (C) 2026 Mehmet Aykurt <m.aykurt38@gmail.com>
# Bu eklenti Mehmet Aykurt tarafından geliştirilmiştir.
# Lisans: GNU General Public License v2 (GPL-2.0)

"""Repository creation and management operations for GitHub."""

import addonHandler
addonHandler.initTranslation()

import json
import re
import socket
import urllib.error
import urllib.parse
import urllib.request

import wx

from .auth import AuthError, checkCancelled
from .downloader import USER_AGENT, _build_opener


def _check_cancelled(cancel):
    if cancel is not None:
        checkCancelled(cancel)


def _normalizeSearch(text):
    if not text:
        return ""
    # Normalize Turkish dotted/dotless variations and common Turkish characters to ASCII for flexible searching.
    t = text.replace("İ", "i").replace("I", "i").replace("ı", "i")
    t = t.replace("\u0307", "")
    t = t.casefold()
    tr_map = str.maketrans("çğöşü", "cgosu")
    return t.translate(tr_map)


def filterRepositories(repositories, query):
    """Filters repositories by matching query case-insensitively against name or full_name."""
    if not query or not repositories:
        return list(repositories or [])
    clean_query = _normalizeSearch(query.strip())
    if not clean_query:
        return list(repositories)
    return [
        repo for repo in repositories
        if clean_query in _normalizeSearch(repo.get("full_name", ""))
        or clean_query in _normalizeSearch(repo.get("name", ""))
    ]


def listBranches(token, full_name, cancel=None):
    """Fetches list of branches for a repository."""
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", full_name):
        raise AuthError("invalid_response")
    _check_cancelled(cancel)

    url = f"https://api.github.com/repos/{full_name}/branches?per_page=100"
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/vnd.github.v3+json",
        "Authorization": f"Bearer {token}",
    }
    req = urllib.request.Request(url, headers=headers)
    opener = _build_opener()

    try:
        with opener.open(req, timeout=30) as response:
            rows = json.loads(response.read().decode("utf-8"))
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
    if not isinstance(rows, list):
        raise AuthError("invalid_response")

    branches = []
    for row in rows:
        if isinstance(row, dict) and isinstance(row.get("name"), str):
            branches.append(row["name"])
    return branches



def createRepository(token, name, description="", private=False, auto_init=True, license_template="", cancel=None):
    """Creates a new repository on GitHub for the authenticated user."""
    clean_name = name.strip()
    if not clean_name or clean_name in (".", "..") or not re.fullmatch(r"[A-Za-z0-9_.-]+", clean_name):
        raise AuthError("invalid_repo_name")
    _check_cancelled(cancel)

    url = "https://api.github.com/user/repos"
    lic = str(license_template).strip() if license_template else ""
    payload = {
        "name": clean_name,
        "description": description.strip(),
        "private": bool(private),
        "auto_init": bool(auto_init) or bool(lic),
    }
    if lic:
        payload["license_template"] = lic

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
        if exc.code == 422:
            raise AuthError("repo_exists_or_invalid") from None
        if exc.code == 401:
            raise AuthError("unauthorized") from None
        if exc.code in (403, 429):
            raise AuthError("limited") from None
        raise AuthError("server_error") from None
    except (urllib.error.URLError, OSError, socket.timeout):
        raise AuthError("network") from None


class NewRepositoryDialog(wx.Dialog):
    """Accessible dialog for creating a new repository."""

    def __init__(self, parent):
        super().__init__(
            parent,
            title=_("GitHub — Create New Repository"),
            size=(550, 420),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )

        layout = wx.BoxSizer(wx.VERTICAL)

        # Repository Name
        name_label = wx.StaticText(self, label=_("&Repository name:"))
        layout.Add(name_label, 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)
        self.name_ctrl = wx.TextCtrl(self)
        self.name_ctrl.SetName(_("Repository name"))
        layout.Add(self.name_ctrl, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        # Description
        desc_label = wx.StaticText(self, label=_("&Description (optional):"))
        layout.Add(desc_label, 0, wx.LEFT | wx.RIGHT | wx.TOP, 5)
        self.desc_ctrl = wx.TextCtrl(self)
        self.desc_ctrl.SetName(_("Description (optional)"))
        layout.Add(self.desc_ctrl, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        # Visibility
        vis_choices = [_("Public"), _("Private")]
        self.vis_box = wx.RadioBox(
            self,
            label=_("Visibility:"),
            choices=vis_choices,
            majorDimension=1,
            style=wx.RA_SPECIFY_ROWS,
        )
        self.vis_box.SetName(_("Visibility"))
        layout.Add(self.vis_box, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        # Initialize with README
        self.readme_cb = wx.CheckBox(self, label=_("&Initialize this repository with a README.md"))
        self.readme_cb.SetValue(True)
        self.readme_cb.SetName(_("Initialize with README"))
        layout.Add(self.readme_cb, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        # License (optional)
        license_label = wx.StaticText(self, label=_("&License (optional):"))
        layout.Add(license_label, 0, wx.LEFT | wx.RIGHT | wx.TOP, 4)
        self.license_choices = [
            (_("None"), ""),
            ("GNU General Public License v2.0 (GPL-2.0)", "gpl-2.0"),
            ("GNU General Public License v3.0 (GPL-3.0)", "gpl-3.0"),
            ("MIT License", "mit"),
            ("Apache License 2.0", "apache-2.0"),
            ("BSD 2-Clause License", "bsd-2-clause"),
            ("BSD 3-Clause License", "bsd-3-clause"),
            ("The Unlicense", "unlicense"),
        ]
        self.license_choice = wx.Choice(
            self,
            choices=[label for label, _key in self.license_choices],
        )
        self.license_choice.SetName(_("License (optional)"))
        self.license_choice.SetSelection(0)
        layout.Add(self.license_choice, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)

        # Buttons
        button_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.ok_btn = wx.Button(self, wx.ID_OK, _("&Create repository"))
        self.ok_btn.SetDefault()
        self.ok_btn.Bind(wx.EVT_BUTTON, self._onCreate)
        button_sizer.Add(self.ok_btn, 0, wx.RIGHT, 10)

        self.cancel_btn = wx.Button(self, wx.ID_CANCEL, _("&Cancel"))
        button_sizer.Add(self.cancel_btn, 0)

        layout.Add(button_sizer, 0, wx.ALIGN_RIGHT | wx.RIGHT | wx.BOTTOM, 10)
        self.SetSizer(layout)
        self.SetMinSize((400, 350))
        self.CentreOnScreen()

        wx.CallAfter(self.name_ctrl.SetFocus)

    def _onCreate(self, event):
        name = self.name_ctrl.GetValue().strip()
        if not name:
            wx.MessageBox(_("Please enter a repository name."), _("Error"), wx.OK | wx.ICON_ERROR, self)
            self.name_ctrl.SetFocus()
            return
        if name in (".", ".."):
            wx.MessageBox(_("The repository name is invalid."), _("Error"), wx.OK | wx.ICON_ERROR, self)
            self.name_ctrl.SetFocus()
            return
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", name):
            wx.MessageBox(
                _("Repository name can only contain letters, numbers, hyphens, underscores, and dots."),
                _("Error"),
                wx.OK | wx.ICON_ERROR,
                self,
            )
            self.name_ctrl.SetFocus()
            return
        self.EndModal(wx.ID_OK)

    def getData(self):
        lic_idx = self.license_choice.GetSelection()
        lic_val = self.license_choices[lic_idx][1] if lic_idx >= 0 else ""
        return {
            "name": self.name_ctrl.GetValue().strip(),
            "description": self.desc_ctrl.GetValue().strip(),
            "private": self.vis_box.GetSelection() == 1,
            "auto_init": self.readme_cb.IsChecked() or bool(lic_val),
            "license_template": lic_val,
        }

    def cancelAndClose(self):
        if self.IsModal():
            self.EndModal(wx.ID_CANCEL)


def isValidBranchName(name):
    """Validates git branch naming according to git-check-ref-format rules."""
    if not isinstance(name, str) or not name:
        return False
    clean = name.strip()
    if not clean or clean != name:
        return False
    if clean.startswith(("/", ".")) or clean.endswith(("/", ".")):
        return False
    if ".." in clean or "//" in clean or clean.endswith(".lock"):
        return False
    segments = clean.split("/")
    for seg in segments:
        if not seg or seg in (".", "..") or seg.endswith(".lock") or seg.startswith("."):
            return False
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", seg):
            return False
    return True


def createBranch(token, full_name, new_branch_name, source_branch, cancel=None):
    """Creates a new branch referencing the tip commit of source_branch."""
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", full_name):
        raise AuthError("invalid_response")
    if not isValidBranchName(new_branch_name):
        raise AuthError("invalid_response")
    _check_cancelled(cancel)

    # 1. Fetch source branch ref SHA
    quoted_source = urllib.parse.quote(source_branch, safe="/")
    url = f"https://api.github.com/repos/{full_name}/git/ref/heads/{quoted_source}"
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
            sha = data.get("object", {}).get("sha")
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

    if not sha:
        raise AuthError("not_found")

    _check_cancelled(cancel)

    # 2. Create new git ref
    create_url = f"https://api.github.com/repos/{full_name}/git/refs"
    payload = json.dumps({
        "ref": f"refs/heads/{new_branch_name}",
        "sha": sha,
    }).encode("utf-8")
    req_create = urllib.request.Request(
        create_url,
        data=payload,
        headers={**headers, "Content-Type": "application/json"},
    )

    try:
        with opener.open(req_create, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 422:
            raise AuthError("branch_exists") from None
        if exc.code == 401:
            raise AuthError("unauthorized") from None
        if exc.code in (403, 429):
            raise AuthError("limited") from None
        raise AuthError("server_error") from None
    except (urllib.error.URLError, OSError, socket.timeout):
        raise AuthError("network") from None


def deleteBranch(token, full_name, branch_name, cancel=None):
    """Deletes a git branch from repository."""
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", full_name):
        raise AuthError("invalid_response")
    _check_cancelled(cancel)

    quoted_branch = urllib.parse.quote(branch_name, safe="/")
    url = f"https://api.github.com/repos/{full_name}/git/refs/heads/{quoted_branch}"
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


def updateRepository(token, full_name, description=None, private=None, archived=None, cancel=None):
    """Updates repository description, visibility or archived status."""
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", full_name):
        raise AuthError("invalid_response")
    _check_cancelled(cancel)

    url = f"https://api.github.com/repos/{full_name}"
    payload_dict = {}
    if description is not None:
        payload_dict["description"] = description
    if private is not None:
        payload_dict["private"] = bool(private)
    if archived is not None:
        payload_dict["archived"] = bool(archived)

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
        if exc.code == 403:
            body = ""
            try:
                body = exc.read().decode("utf-8", errors="ignore").casefold()
            except Exception:
                pass
            if "rate limit" in body or exc.headers.get("X-RateLimit-Remaining") == "0":
                raise AuthError("limited") from None
            raise AuthError("forbidden") from None
        if exc.code == 429:
            raise AuthError("limited") from None
        raise AuthError("server_error") from None
    except (urllib.error.URLError, OSError, socket.timeout):
        raise AuthError("network") from None


def deleteRepository(token, full_name, cancel=None):
    """Permanently deletes a repository from GitHub."""
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", full_name):
        raise AuthError("invalid_response")
    _check_cancelled(cancel)

    url = f"https://api.github.com/repos/{full_name}"
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
        if exc.code == 403:
            body = ""
            try:
                body = exc.read().decode("utf-8", errors="ignore").casefold()
            except Exception:
                pass
            if "rate limit" in body or exc.headers.get("X-RateLimit-Remaining") == "0":
                raise AuthError("limited") from None
            raise AuthError("forbidden") from None
        if exc.code == 429:
            raise AuthError("limited") from None
        raise AuthError("server_error") from None
    except (urllib.error.URLError, OSError, socket.timeout):
        raise AuthError("network") from None


class NewBranchDialog(wx.Dialog):
    """Accessible dialog for creating a new git branch."""

    def __init__(self, parent, full_name, branches, current_branch):
        super().__init__(
            parent,
            title=_("Create New Branch — %s") % full_name,
            size=(480, 320),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        self.full_name = full_name
        self.branches = branches or []

        layout = wx.BoxSizer(wx.VERTICAL)

        # Source branch
        source_label = wx.StaticText(self, label=_("&Source branch:"))
        layout.Add(source_label, 0, wx.ALL, 6)
        self.source_choice = wx.Choice(self, choices=self.branches)
        if current_branch in self.branches:
            self.source_choice.SetSelection(self.branches.index(current_branch))
        elif self.branches:
            self.source_choice.SetSelection(0)
        self.source_choice.SetName(_("Source branch"))
        layout.Add(self.source_choice, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        # New branch name
        name_label = wx.StaticText(self, label=_("&New branch name:"))
        layout.Add(name_label, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)
        self.name_ctrl = wx.TextCtrl(self)
        self.name_ctrl.SetName(_("New branch name"))
        layout.Add(self.name_ctrl, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)

        # Buttons
        button_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.ok_btn = wx.Button(self, wx.ID_OK, _("&Create branch"))
        self.ok_btn.SetDefault()
        self.ok_btn.Bind(wx.EVT_BUTTON, self._onCreate)
        button_sizer.Add(self.ok_btn, 0, wx.RIGHT, 10)

        self.cancel_btn = wx.Button(self, wx.ID_CANCEL, _("&Cancel"))
        button_sizer.Add(self.cancel_btn, 0)

        layout.Add(button_sizer, 0, wx.ALIGN_RIGHT | wx.RIGHT | wx.BOTTOM, 10)
        self.SetSizer(layout)
        self.SetMinSize((400, 260))
        self.CentreOnScreen()

        wx.CallAfter(self.name_ctrl.SetFocus)

    def _onCreate(self, event):
        name = self.name_ctrl.GetValue().strip()
        if not name:
            wx.MessageBox(_("Please enter a branch name."), _("Error"), wx.OK | wx.ICON_ERROR, self)
            self.name_ctrl.SetFocus()
            return
        if not isValidBranchName(name):
            wx.MessageBox(
                _("Branch name contains invalid characters. Use letters, numbers, hyphens, and slashes."),
                _("Error"),
                wx.OK | wx.ICON_ERROR,
                self,
            )
            self.name_ctrl.SetFocus()
            return
        if name in self.branches:
            wx.MessageBox(_("A branch with this name already exists."), _("Error"), wx.OK | wx.ICON_ERROR, self)
            self.name_ctrl.SetFocus()
            return
        self.EndModal(wx.ID_OK)

    def getData(self):
        return {
            "name": self.name_ctrl.GetValue().strip(),
            "source": self.source_choice.GetStringSelection(),
        }

    def cancelAndClose(self):
        if self.IsModal():
            self.EndModal(wx.ID_CANCEL)


class RepoSettingsDialog(wx.Dialog):
    """Accessible dialog for editing repository description, visibility, and archiving/deleting."""

    def __init__(self, parent, repo_dict):
        super().__init__(
            parent,
            title=_("Repository Settings — %s") % repo_dict["full_name"],
            size=(560, 480),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        self.repo = repo_dict
        self._action = "save"

        layout = wx.BoxSizer(wx.VERTICAL)

        # Name display
        layout.Add(wx.StaticText(self, label=_("Repository: %s") % repo_dict["full_name"]), 0, wx.ALL, 8)

        # Description
        desc_label = wx.StaticText(self, label=_("&Description (optional):"))
        layout.Add(desc_label, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 4)
        self.desc_ctrl = wx.TextCtrl(self, value=repo_dict.get("description") or "")
        self.desc_ctrl.SetName(_("Description"))
        layout.Add(self.desc_ctrl, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        # Visibility
        vis_choices = [_("Public"), _("Private")]
        self.vis_box = wx.RadioBox(
            self,
            label=_("Visibility:"),
            choices=vis_choices,
            majorDimension=1,
            style=wx.RA_SPECIFY_ROWS,
        )
        self.vis_box.SetSelection(1 if repo_dict.get("private") else 0)
        self.vis_box.SetName(_("Visibility"))
        layout.Add(self.vis_box, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        # Archived checkbox
        self.archive_cb = wx.CheckBox(self, label=_("&Archive this repository (make it read-only)"))
        self.archive_cb.SetValue(bool(repo_dict.get("archived", False)))
        self.archive_cb.SetName(_("Archive repository"))
        layout.Add(self.archive_cb, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)

        # Danger zone: Delete repo button
        danger_box = wx.StaticBoxSizer(wx.VERTICAL, self, label=_("Danger Zone"))
        self.delete_btn = wx.Button(self, label=_("&Delete repository…"))
        self.delete_btn.Bind(wx.EVT_BUTTON, self._onDeleteClick)
        danger_box.Add(self.delete_btn, 0, wx.ALL, 6)
        layout.Add(danger_box, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)

        # Dialog Buttons
        button_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.save_btn = wx.Button(self, wx.ID_OK, _("&Save changes"))
        self.save_btn.SetDefault()
        self.save_btn.Bind(wx.EVT_BUTTON, self._onSave)
        button_sizer.Add(self.save_btn, 0, wx.RIGHT, 10)

        self.cancel_btn = wx.Button(self, wx.ID_CANCEL, _("&Cancel"))
        button_sizer.Add(self.cancel_btn, 0)

        layout.Add(button_sizer, 0, wx.ALIGN_RIGHT | wx.RIGHT | wx.BOTTOM, 10)
        self.SetSizer(layout)
        self.SetMinSize((480, 420))
        self.CentreOnScreen()

        wx.CallAfter(self.desc_ctrl.SetFocus)

    def _onSave(self, event):
        self._action = "save"
        self.EndModal(wx.ID_OK)

    def _onDeleteClick(self, event):
        self._action = "delete"
        self.EndModal(wx.ID_OK)

    def getAction(self):
        return self._action

    def getData(self):
        return {
            "description": self.desc_ctrl.GetValue().strip(),
            "private": self.vis_box.GetSelection() == 1,
            "archived": self.archive_cb.IsChecked(),
        }

    def cancelAndClose(self):
        if self.IsModal():
            self.EndModal(wx.ID_CANCEL)


class DeleteRepoConfirmDialog(wx.Dialog):
    """Accessible security confirmation dialog requiring exact repo name entry to delete."""

    def __init__(self, parent, full_name):
        super().__init__(
            parent,
            title=_("Delete Repository — Confirmation"),
            size=(500, 320),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        self.full_name = full_name
        repo_short = full_name.split("/")[-1]
        self.repo_short = repo_short

        layout = wx.BoxSizer(wx.VERTICAL)

        warning_label = wx.StaticText(
            self,
            label=_("Warning: This action cannot be undone. This will permanently delete the repository '%s', its code, branches, issues, and releases.") % full_name,
        )
        warning_label.Wrap(460)
        layout.Add(warning_label, 0, wx.EXPAND | wx.ALL, 10)

        prompt_label = wx.StaticText(
            self,
            label=_("To confirm deletion, please type the repository name (%s) below:") % repo_short,
        )
        layout.Add(prompt_label, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)

        self.confirm_ctrl = wx.TextCtrl(self, style=wx.TE_PROCESS_ENTER)
        self.confirm_ctrl.SetName(_("Repository confirmation name"))
        self.confirm_ctrl.Bind(wx.EVT_TEXT, self._onTextChanged)
        if hasattr(wx, "EVT_TEXT_ENTER"):
            self.confirm_ctrl.Bind(wx.EVT_TEXT_ENTER, self._onEnter)
        layout.Add(self.confirm_ctrl, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)

        button_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.delete_btn = wx.Button(self, wx.ID_OK, _("I understand, &delete this repository"))
        self.delete_btn.Disable()
        self.delete_btn.Bind(wx.EVT_BUTTON, self._onDelete)
        button_sizer.Add(self.delete_btn, 0, wx.RIGHT, 10)

        self.cancel_btn = wx.Button(self, wx.ID_CANCEL, _("&Cancel"))
        button_sizer.Add(self.cancel_btn, 0)

        layout.Add(button_sizer, 0, wx.ALIGN_RIGHT | wx.RIGHT | wx.BOTTOM, 10)
        self.SetSizer(layout)
        self.SetMinSize((450, 280))
        self.CentreOnScreen()

        wx.CallAfter(self.confirm_ctrl.SetFocus)

    def _isMatch(self, val):
        v = val.strip().casefold()
        return bool(v and (v == self.repo_short.casefold() or v == self.full_name.casefold()))

    def _onTextChanged(self, event):
        matched = self._isMatch(self.confirm_ctrl.GetValue())
        self.delete_btn.Enable(matched)
        if matched:
            self.delete_btn.SetDefault()

    def _onEnter(self, event):
        val = self.confirm_ctrl.GetValue().strip()
        if self._isMatch(val):
            self.EndModal(wx.ID_OK)
        else:
            icon = getattr(wx, "ICON_WARNING", getattr(wx, "ICON_ERROR", 0))
            wx.MessageBox(
                _("To confirm deletion, please type the repository name '%s' exactly.") % self.repo_short,
                _("Confirmation Required"),
                wx.OK | icon,
                self,
            )
            self.confirm_ctrl.SetFocus()

    def _onDelete(self, event):
        val = self.confirm_ctrl.GetValue().strip()
        if not self._isMatch(val):
            icon = getattr(wx, "ICON_WARNING", getattr(wx, "ICON_ERROR", 0))
            wx.MessageBox(
                _("To confirm deletion, please type the repository name '%s' exactly.") % self.repo_short,
                _("Confirmation Required"),
                wx.OK | icon,
                self,
            )
            self.confirm_ctrl.SetFocus()
            return
        self.EndModal(wx.ID_OK)

    def cancelAndClose(self):
        if self.IsModal():
            self.EndModal(wx.ID_CANCEL)
