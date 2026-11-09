# Copyright (C) 2026 Mehmet Aykurt <m.aykurt38@gmail.com>
# Bu eklenti Mehmet Aykurt tarafından geliştirilmiştir.
# Lisans: GNU General Public License v2 (GPL-2.0)

"""Keyboard-accessible account dialogs. Network operations run off the GUI thread."""

import os
import threading
import webbrowser
from urllib.parse import quote

import addonHandler
addonHandler.initTranslation()

import ui
import wx
from logHandler import log

from .auth import AuthError, VERIFY_URL
from .credentials import CredentialError
from .commit_ops import CommitsDialog
from .errors import errorMessage
from .file_ops import (
    CopyDialog,
    DeleteConfirmDialog,
    NewFileDialog,
    RenameMoveDialog,
    UploadConfirmDialog,
    UploadFolderConfirmDialog,
)
from .issue_ops import IssuesDialog, NewIssueDialog, createIssue
from .notification_ops import NotificationsDialog
from .pr_ops import PullRequestsDialog
from .release_ops import NewReleaseDialog, ReleasesDialog
from .repo_ops import (
    DeleteRepoConfirmDialog,
    NewBranchDialog,
    NewRepositoryDialog,
    RepoSettingsDialog,
    filterRepositories,
)
from .search_ops import GlobalSearchDialog
from .settings import SettingsError
from .viewer import FileEditorDialog, FileViewerDialog


def runTask(owner, operation, onSuccess, onFailure, onCode=None, slot="_cancel"):
    """Ignore queued results after cancellation, window closure or a newer task."""
    cancel = threading.Event()
    previous = getattr(owner, slot, None)
    if previous is not None:
        previous.set()
    setattr(owner, slot, cancel)

    def deliver(callback, *args):
        if not owner._closing and getattr(owner, slot) is cancel and not cancel.is_set():
            callback(*args)

    def reportCode(code, lifetime=None):
        if lifetime is not None and onCode is not None:
            wx.CallAfter(deliver, onCode, code, lifetime)
        elif isinstance(code, str) and hasattr(owner, "_setStatus"):
            wx.CallAfter(deliver, owner._setStatus, code, True)

    def work():
        try:
            result = operation(cancel, reportCode)
        except Exception as error:
            # Never log response bodies, exception text, tokens or device codes.
            if not isinstance(error, AuthError):
                log.error("GitHub account operation failed: %s", type(error).__name__)
            wx.CallAfter(deliver, onFailure, errorMessage(error))
        else:
            wx.CallAfter(deliver, onSuccess, result)

    worker = threading.Thread(target=work, name="GitHubAccount", daemon=True)
    worker.start()
    return worker


def openPage(url, parent):
    try:
        if webbrowser.open(url, new=2):
            return
    except OSError:
        pass
    parent.showMessage(_("The browser could not be opened. Open this address manually: ") + url, wx.OK | wx.ICON_ERROR)


class MessageMixin:
    def showMessage(self, message, style):
        prompt = wx.MessageDialog(self, message, "GitHub", style)
        if style & wx.YES_NO:
            prompt.SetYesNoLabels(_("&Yes"), _("&No"))
        else:
            prompt.SetOKLabel(_("&OK"))
        self._prompt = prompt
        try:
            return prompt.ShowModal()
        finally:
            self._prompt = None
            prompt.Destroy()


class GitHubDialog(MessageMixin, wx.Dialog):
    def __init__(self, parent, onClosed, service):
        super().__init__(parent, title="GitHub", style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.service = service
        self._onClosed = onClosed
        self._closing = False
        self._prompt = None
        self._child = None
        self._cancel = threading.Event()
        self._busy = False
        self._repositoryRows = []
        self._hasRepositoryData = False
        self._contentCancel = threading.Event()
        self._contentTimer = None
        self._contentLoading = False
        self._contentFocusQueued = False
        self._populatingRepositories = False
        self._currentPath = ""
        self._contentRows = []
        self._contentRepositoryId = None
        self._branches = []
        self._currentBranch = ""
        self._branchesCancel = threading.Event()
        self._downloadCancel = threading.Event()
        self._viewCancel = threading.Event()
        self._mutationCancel = threading.Event()
        self._mutating = False

        self._menu = wx.Menu()
        self._repositoryItems = []
        self._repositoryActionIds = []

        # 1. Account Menu
        self._accountMenu = wx.Menu()
        self._connectItem = self._accountMenu.Append(wx.ID_ANY, _("&Connect account"))
        self._disconnectItem = self._accountMenu.Append(wx.ID_ANY, _("&Remove local connection"))
        self.Bind(wx.EVT_MENU, self._onConnect, id=self._connectItem.GetId())
        self.Bind(wx.EVT_MENU, self._onDisconnect, id=self._disconnectItem.GetId())
        self._menu.AppendSubMenu(self._accountMenu, _("&Account"))

        # 2. Repository Menu
        self._repositoryMenu = wx.Menu()
        self._repositoryContextMenu = wx.Menu()
        self._newRepoItem = self._repositoryMenu.Append(wx.ID_ANY, _("&New repository…") + "\tCtrl+Shift+N")
        self.Bind(wx.EVT_MENU, self._onCreateRepository, id=self._newRepoItem.GetId())
        self._searchRepoItem = self._repositoryMenu.Append(wx.ID_ANY, _("&Search repositories…") + "\tCtrl+F")
        self.Bind(wx.EVT_MENU, self._onFocusSearch, id=self._searchRepoItem.GetId())
        self._repositoryMenu.AppendSeparator()
        self._refreshItem = self._repositoryMenu.Append(wx.ID_ANY, _("&Refresh repositories") + "\tF5")
        self.Bind(wx.EVT_MENU, self._onRefresh, id=self._refreshItem.GetId())
        self._repositoryMenu.AppendSeparator()

        for label, handler in (
            (_("&Download repository (ZIP)…"), self._onDownloadRepository),
            (_("&Repository settings…"), self._onRepoSettings),
            (_("&Delete repository…"), self._onDeleteRepository),
            (_("&Copy repository address"), self._copyRepository),
            (_("&Open repository on GitHub"), self._openRepository),
        ):
            identifier = wx.NewIdRef()
            self._repositoryActionIds.append(identifier)
            item = self._repositoryMenu.Append(int(identifier), label)
            self._repositoryItems.append(item)
            self.Bind(wx.EVT_MENU, handler, id=int(identifier))

        # Context menu on repositories tree
        for label, handler in (
            (_("&Go to branch") + "\tCtrl+B", self._onFocusBranch),
            (_("&Go to contents"), self._focusContents),
            (_("&Download repository (ZIP)…"), self._onDownloadRepository),
            (_("&Repository settings…"), self._onRepoSettings),
            (_("&Delete repository…"), self._onDeleteRepository),
            (_("&Copy repository address"), self._copyRepository),
            (_("&Open repository on GitHub"), self._openRepository),
        ):
            c_ident = wx.NewIdRef()
            c_item = self._repositoryContextMenu.Append(int(c_ident), label)
            self._repositoryItems.append(c_item)
            self.Bind(wx.EVT_MENU, handler, id=int(c_ident))

        self._repositoryContextMenu.AppendSeparator()
        self._contextNewRepoItem = self._repositoryContextMenu.Append(wx.ID_ANY, _("&New repository…") + "\tCtrl+Shift+N")
        self.Bind(wx.EVT_MENU, self._onCreateRepository, id=self._contextNewRepoItem.GetId())
        self._contextSearchRepoItem = self._repositoryContextMenu.Append(wx.ID_ANY, _("&Search repositories…") + "\tCtrl+F")
        self.Bind(wx.EVT_MENU, self._onFocusSearch, id=self._contextSearchRepoItem.GetId())
        self._menu.AppendSubMenu(self._repositoryMenu, _("&Repository"))

        # 3. Branch Menu
        self._branchMenu = wx.Menu()
        for label, handler in (
            (_("&Go to branch") + "\tCtrl+B", self._onFocusBranch),
            (_("&New branch…"), self._onCreateBranch),
            (_("&Delete current branch…"), self._onDeleteBranch),
        ):
            b_ident = wx.NewIdRef()
            self._repositoryActionIds.append(b_ident)
            b_item = self._branchMenu.Append(int(b_ident), label)
            self._repositoryItems.append(b_item)
            self.Bind(wx.EVT_MENU, handler, id=int(b_ident))
        self._branchMenu.AppendSeparator()
        self._refreshBranchMenuItem = self._branchMenu.Append(wx.ID_ANY, _("&Refresh branches"))
        self._repositoryItems.append(self._refreshBranchMenuItem)
        self.Bind(wx.EVT_MENU, self._onRefreshBranches, id=self._refreshBranchMenuItem.GetId())
        self._menu.AppendSubMenu(self._branchMenu, _("&Branch"))

        # 4. File Menu
        self._fileMenu = wx.Menu()
        for label, handler in (
            (_("&Go to contents"), self._focusContents),
            (_("&New file…") + "\tCtrl+N", self._onCreateFile),
            (_("&Upload file(s) from computer…") + "\tCtrl+U", self._onUploadFile),
            (_("Upload &folder from computer…") + "\tCtrl+Shift+U", self._onUploadFolder),
            (_("&Edit file…") + "\tCtrl+E", self._onEditContent),
            (_("&Rename or move…") + "\tF2", self._onRenameContent),
            (_("&Copy file or folder…") + "\tCtrl+Shift+C", self._onCopyContent),
            (_("&Refresh contents"), self._refreshContents),
        ):
            f_ident = wx.NewIdRef()
            self._repositoryActionIds.append(f_ident)
            f_item = self._fileMenu.Append(int(f_ident), label)
            self._repositoryItems.append(f_item)
            self.Bind(wx.EVT_MENU, handler, id=int(f_ident))
        self._menu.AppendSubMenu(self._fileMenu, _("&File"))

        # 5. Tools Menu
        self._toolsMenu = wx.Menu()
        for label, handler in (
            (_("&Issues…") + "\tCtrl+I", self._onOpenIssues),
            (_("&New issue…") + "\tCtrl+Shift+I", self._onOpenNewIssue),
            (_("&Pull requests…") + "\tCtrl+P", self._onOpenPullRequests),
            (_("&Releases…") + "\tCtrl+R", self._onOpenReleases),
            (_("&New release…") + "\tCtrl+Shift+R", self._onOpenNewRelease),
            (_("&Commit history…") + "\tCtrl+H", self._onOpenCommits),
        ):
            t_ident = wx.NewIdRef()
            self._repositoryActionIds.append(t_ident)
            t_item = self._toolsMenu.Append(int(t_ident), label)
            self._repositoryItems.append(t_item)
            self.Bind(wx.EVT_MENU, handler, id=int(t_ident))
        self._toolsMenu.AppendSeparator()
        self._notifItem = self._toolsMenu.Append(wx.ID_ANY, _("&Notifications…") + "\tCtrl+Shift+B")
        self.Bind(wx.EVT_MENU, self._onOpenNotifications, id=self._notifItem.GetId())
        self._exploreItem = self._toolsMenu.Append(wx.ID_ANY, _("&Explore GitHub repositories…") + "\tCtrl+Shift+F")
        self.Bind(wx.EVT_MENU, self._onExploreRepositories, id=self._exploreItem.GetId())
        self._menu.AppendSubMenu(self._toolsMenu, _("&Tools"))
        self._openMenuId = wx.NewIdRef()
        self.Bind(wx.EVT_MENU, self._onMenu, id=int(self._openMenuId))
        self._refreshFocusedId = wx.NewIdRef()
        self.Bind(wx.EVT_MENU, self._refreshFocused, id=int(self._refreshFocusedId))
        self._notifAccId = wx.NewIdRef()
        self.Bind(wx.EVT_MENU, self._onOpenNotifications, id=int(self._notifAccId))
        self._exploreAccId = wx.NewIdRef()
        self.Bind(wx.EVT_MENU, self._onExploreRepositories, id=int(self._exploreAccId))
        self._commitsAccId = wx.NewIdRef()
        self.Bind(wx.EVT_MENU, self._onOpenCommits, id=int(self._commitsAccId))
        self._prsAccId = wx.NewIdRef()
        self.Bind(wx.EVT_MENU, self._onOpenPullRequests, id=int(self._prsAccId))
        self._newRepoAccId = wx.NewIdRef()
        self.Bind(wx.EVT_MENU, self._onCreateRepository, id=int(self._newRepoAccId))
        self._searchAccId = wx.NewIdRef()
        self.Bind(wx.EVT_MENU, self._onFocusSearch, id=int(self._searchAccId))
        self._branchAccId = wx.NewIdRef()
        self.Bind(wx.EVT_MENU, self._onFocusBranch, id=int(self._branchAccId))
        self._issuesAccId = wx.NewIdRef()
        self.Bind(wx.EVT_MENU, self._onOpenIssues, id=int(self._issuesAccId))
        self._newIssueAccId = wx.NewIdRef()
        self.Bind(wx.EVT_MENU, self._onOpenNewIssue, id=int(self._newIssueAccId))
        self._releasesAccId = wx.NewIdRef()
        self.Bind(wx.EVT_MENU, self._onOpenReleases, id=int(self._releasesAccId))
        self._newReleaseAccId = wx.NewIdRef()
        self.Bind(wx.EVT_MENU, self._onOpenNewRelease, id=int(self._newReleaseAccId))
        self._newFileAccId = wx.NewIdRef()
        self.Bind(wx.EVT_MENU, self._onCreateFile, id=int(self._newFileAccId))
        self._uploadFileAccId = wx.NewIdRef()
        self.Bind(wx.EVT_MENU, self._onUploadFile, id=int(self._uploadFileAccId))
        self._uploadFolderAccId = wx.NewIdRef()
        self.Bind(wx.EVT_MENU, self._onUploadFolder, id=int(self._uploadFolderAccId))
        self._renameAccId = wx.NewIdRef()
        self.Bind(wx.EVT_MENU, self._onRenameContent, id=int(self._renameAccId))
        self._copyAccId = wx.NewIdRef()
        self.Bind(wx.EVT_MENU, self._onCopyContent, id=int(self._copyAccId))
        self._closeAccId = wx.NewIdRef()
        self.Bind(wx.EVT_MENU, self._onClose, id=int(self._closeAccId))
        self.SetAcceleratorTable(wx.AcceleratorTable([
            (wx.ACCEL_ALT, ord("M"), int(self._openMenuId)),
            (wx.ACCEL_ALT, ord("K"), int(self._closeAccId)),
            (wx.ACCEL_ALT, ord("C"), int(self._closeAccId)),
            (wx.ACCEL_NORMAL, wx.WXK_F5, int(self._refreshFocusedId)),
            (wx.ACCEL_CTRL | wx.ACCEL_SHIFT, ord("B"), int(self._notifAccId)),
            (wx.ACCEL_CTRL | wx.ACCEL_SHIFT, ord("F"), int(self._exploreAccId)),
            (wx.ACCEL_CTRL | wx.ACCEL_SHIFT, ord("N"), int(self._newRepoAccId)),
            (wx.ACCEL_CTRL | wx.ACCEL_SHIFT, ord("I"), int(self._newIssueAccId)),
            (wx.ACCEL_CTRL | wx.ACCEL_SHIFT, ord("R"), int(self._newReleaseAccId)),
            (wx.ACCEL_CTRL | wx.ACCEL_SHIFT, ord("C"), int(self._copyAccId)),
            (wx.ACCEL_CTRL, ord("N"), int(self._newFileAccId)),
            (wx.ACCEL_CTRL, ord("U"), int(self._uploadFileAccId)),
            (wx.ACCEL_CTRL | wx.ACCEL_SHIFT, ord("U"), int(self._uploadFolderAccId)),
            (wx.ACCEL_NORMAL, getattr(wx, "WXK_F2", 341), int(self._renameAccId)),
            (wx.ACCEL_CTRL, ord("H"), int(self._commitsAccId)),
            (wx.ACCEL_CTRL, ord("P"), int(self._prsAccId)),
            (wx.ACCEL_CTRL, ord("I"), int(self._issuesAccId)),
            (wx.ACCEL_CTRL, ord("R"), int(self._releasesAccId)),
            (wx.ACCEL_CTRL, ord("F"), int(self._searchAccId)),
            (wx.ACCEL_CTRL, ord("B"), int(self._branchAccId)),
        ]))

        layout = wx.BoxSizer(wx.VERTICAL)
        panes = wx.BoxSizer(wx.HORIZONTAL)
        treePane = wx.BoxSizer(wx.VERTICAL)
        treePane.Add(wx.StaticText(self, label=_("Search &repositories:")), 0, wx.BOTTOM, 4)
        self._repoSearchCtrl = wx.TextCtrl(self, style=wx.TE_PROCESS_ENTER)
        self._repoSearchCtrl.SetName(_("Search repositories"))
        self._repoSearchCtrl.Bind(wx.EVT_TEXT, self._onSearchChanged)
        self._repoSearchCtrl.Bind(wx.EVT_KEY_DOWN, self._onSearchKey)
        treePane.Add(self._repoSearchCtrl, 0, wx.EXPAND | wx.BOTTOM, 8)
        self._repoTreeLabel = wx.StaticText(self, label=_("Repositories"))
        treePane.Add(self._repoTreeLabel, 0, wx.BOTTOM, 4)
        self._repositories = wx.TreeCtrl(self, style=(
            wx.TR_HIDE_ROOT | wx.TR_HAS_BUTTONS | wx.TR_LINES_AT_ROOT | wx.TR_SINGLE
        ))
        self._repositories.SetName(_("Repositories"))
        images = wx.ImageList(16, 16)
        self._folderImage = images.Add(wx.ArtProvider.GetBitmap(wx.ART_FOLDER, wx.ART_OTHER, (16, 16)))
        self._repositories.AssignImageList(images)
        self._root = self._repositories.AddRoot(_("Repositories"))
        self._repositories.Bind(wx.EVT_TREE_SEL_CHANGED, self._onRepositorySelected)
        self._repositories.Bind(wx.EVT_KEY_DOWN, self._onRepositoryKey)
        self._repositories.Bind(wx.EVT_CONTEXT_MENU, self._onRepositoryContext)
        treePane.Add(self._repositories, 1, wx.EXPAND)
        panes.Add(treePane, 1, wx.EXPAND | wx.RIGHT, 12)
        contentPane = wx.BoxSizer(wx.VERTICAL)

        # Branch selector row
        branchRow = wx.BoxSizer(wx.HORIZONTAL)
        branchLabel = wx.StaticText(self, label=_("&Branch:"))
        branchRow.Add(branchLabel, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        self._branchChoice = wx.Choice(self)
        self._branchChoice.SetName(_("Branch"))
        self._branchChoice.Bind(wx.EVT_CHOICE, self._onBranchSelected)
        self._branchChoice.Bind(wx.EVT_KEY_DOWN, self._onBranchKey)
        self._branchChoice.Bind(wx.EVT_SET_FOCUS, self._onBranchFocus)
        self._branchChoice.Bind(wx.EVT_CONTEXT_MENU, self._onBranchContext)
        branchRow.Add(self._branchChoice, 1, wx.EXPAND)
        contentPane.Add(branchRow, 0, wx.EXPAND | wx.BOTTOM, 8)

        self._contentLabel = wx.StaticText(self, label=_("Contents"))
        contentPane.Add(self._contentLabel, 0, wx.BOTTOM, 6)
        self._contents = wx.ListCtrl(self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        self._contents.SetName(_("Contents"))
        self._contents.InsertColumn(0, _("Name"), width=300)
        self._contents.InsertColumn(1, _("Type"), width=120)
        self._contents.Bind(wx.EVT_KEY_DOWN, self._onContentKey)
        self._contents.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self._onContentActivate)
        self._contents.Bind(wx.EVT_SET_FOCUS, self._onContentFocus)
        self._contents.Bind(wx.EVT_CONTEXT_MENU, self._onContentContext)
        contentPane.Add(self._contents, 1, wx.EXPAND)
        panes.Add(contentPane, 2, wx.EXPAND)
        layout.Add(panes, 1, wx.EXPAND | wx.ALL, 12)
        self._status = wx.StaticText(self, label="")
        layout.Add(self._status, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)

        buttonRow = wx.BoxSizer(wx.HORIZONTAL)
        self._menuButton = wx.Button(self, label=_("&Menu"))
        self._menuButton.Bind(wx.EVT_BUTTON, self._onMenu)
        buttonRow.Add(self._menuButton, 0, wx.RIGHT, 10)

        self._closeButton = wx.Button(self, wx.ID_ANY, _("&Close"))
        self._closeButton.Bind(wx.EVT_BUTTON, self._onClose)
        buttonRow.Add(self._closeButton, 0)

        layout.Add(buttonRow, 0, wx.ALIGN_RIGHT | wx.RIGHT | wx.BOTTOM, 12)
        self.SetSizer(layout)
        self.SetMinSize((700, 360))
        self.SetSize((1000, 550))
        self.CentreOnScreen()
        self.Bind(wx.EVT_CLOSE, self._onClose)
        self.Bind(wx.EVT_CHAR_HOOK, self._onCharHook)
        self._updateAccount()

    def _updateAccount(self, verified=True):
        account = self.service.settings.getAccount()
        self._connectItem.SetItemLabel(_("&Reconnect account") if account else _("&Connect account"))
        self._setBusy(self._busy)
        if account:
            label = _("Connected account: %s") if verified else _("Saved account: %s")
            self.SetTitle("GitHub — " + label % account["login"])
        else:
            self.SetTitle("GitHub")
            self._setStatus(_("No account is connected."), False)

    def _setStatus(self, message, announce=True):
        self._status.SetLabel(message)
        self._status.Wrap(max(300, self.GetClientSize().GetWidth() - 24))
        self.Layout()
        if announce:
            ui.message(message)

    def activate(self):
        if self._closing:
            return
        target = self._prompt or self._child
        if target is not None:
            target.Raise()
            return
        if not self.IsShown():
            self.Show()
        if self.IsIconized():
            self.Iconize(False)
        self.Raise()
        wx.CallAfter(self._finishActivation)

    def _finishActivation(self):
        if self._closing or not self.IsShown() or not self.IsActive():
            return
        if self._prompt is not None or self._child is not None:
            return
        current = wx.Window.FindFocus()
        if current is self._contents:
            self._repairContentFocus(forceEvent=True)
        elif current is not self._repositories:
            self._repositories.SetFocus()

    def _onCharHook(self, event):
        if event.GetKeyCode() == wx.WXK_ESCAPE:
            focused = wx.Window.FindFocus()
            if focused is self._repoSearchCtrl:
                event.Skip()
                return
            return
        event.Skip()

    def _onMenu(self, event):
        if self._closing or self._child is not None or self._prompt is not None:
            return
        position = self._menuButton.GetPosition() + wx.Point(0, self._menuButton.GetSize().GetHeight())
        self.PopupMenu(self._menu, position)

    def offerAccountSetup(self):
        if self._closing or self._prompt is not None or self._child is not None:
            return
        result = self.showMessage(
            _("No GitHub account has been added. Would you like to add an account now?"),
            wx.YES_NO | wx.ICON_QUESTION,
        )
        if self._closing:
            return
        if result == wx.ID_YES:
            self._onConnect(None)
        self.activate()

    def _onConnect(self, event):
        if self._closing or self._child is not None or self._busy:
            return
        self._cancelContents()
        dialog = ConnectDialog(self, self.service)
        self._child = dialog
        try:
            result = dialog.ShowModal()
        finally:
            dialog.cancelAndClose()
            self._child = None
            dialog.Destroy()
        if self._closing:
            return
        if result == wx.ID_OK:
            self._repositories.DeleteChildren(self._root)
            self._repositoryRows = []
            self._hasRepositoryData = False
            self._updateAccount(verified=True)
            self.restoreAccount()
        self.activate()

    def _setBusy(self, busy):
        self._busy = busy
        account = self.service.settings.getAccount()
        self._connectItem.Enable(not busy)
        self._disconnectItem.Enable(not busy and bool(account))
        self._refreshItem.Enable(not busy and bool(account))
        self._notifItem.Enable(not busy and bool(account))
        self._exploreItem.Enable(not busy and bool(account))
        self._newRepoItem.Enable(not busy and bool(account))
        self._contextNewRepoItem.Enable(not busy and bool(account))
        self._searchRepoItem.Enable(not busy and bool(account))
        self._contextSearchRepoItem.Enable(not busy and bool(account))
        self._repoSearchCtrl.Enable(not busy and bool(account))
        self._branchChoice.Enable(not busy and bool(account) and bool(self._selectedRepository()))
        self._updateRepositoryMenus()

    def _onRefresh(self, event):
        if not self._closing and not self._busy and self.service.settings.hasAccounts():
            self._reloadRepositories()

    def restoreAccount(self):
        self._reloadRepositories()

    def _reloadRepositories(self, selectRepoId=None, announceLoad=True):
        if self._closing or self._busy:
            return
        self._setBusy(True)
        self._setStatus(_("Loading repositories…"), announce=announceLoad)

        def success(result):
            self._setBusy(False)
            self._updateAccount(verified=True)
            self._showRepositories(result["repositories"], selectRepoId=selectRepoId)

        def failure(message):
            self._setBusy(False)
            suffix = _("The previously loaded list is still shown.") if self._hasRepositoryData else ""
            self._setStatus(message + (" " + suffix if suffix else ""))

        runTask(self, lambda cancel, report: self.service.loadRepositories(cancel), success, failure)

    def _onFocusSearch(self, event=None):
        if self._closing:
            return
        if not self._repoSearchCtrl.IsEnabled():
            if not self.service.settings.hasAccounts():
                ui.message(_("No account is connected."))
            elif self._busy:
                ui.message(_("Loading repositories…"))
            return
        self._repoSearchCtrl.SetFocus()
        self._repoSearchCtrl.SelectAll()

    def _onSearchKey(self, event):
        code = event.GetKeyCode()
        if code in (wx.WXK_DOWN, wx.WXK_RETURN) and not event.HasAnyModifiers():
            self._repositories.SetFocus()
            return
        if code == wx.WXK_ESCAPE and not event.HasAnyModifiers():
            if self._repoSearchCtrl.GetValue():
                self._repoSearchCtrl.Clear()
                ui.message(_("Search cleared."))
                return
        event.Skip()

    def _onSearchChanged(self, event):
        if self._populatingRepositories or self._closing:
            return
        query = self._repoSearchCtrl.GetValue().strip()
        filtered = filterRepositories(self._repositoryRows, query)
        self._populateTree(filtered, query=query)

    def _showRepositories(self, repositories, selectRepoId=None):
        self._repositoryRows = repositories
        self._hasRepositoryData = True
        query = self._repoSearchCtrl.GetValue().strip() if hasattr(self, "_repoSearchCtrl") else ""
        filtered = filterRepositories(repositories, query)
        self._populateTree(filtered, selectRepoId=selectRepoId, query=query)

    def _populateTree(self, repositories, selectRepoId=None, query=""):
        self._populatingRepositories = True
        selection = self._repositories.GetSelection()
        selectedId = selectRepoId if selectRepoId is not None else (self._repositories.GetItemData(selection) if selection.IsOk() else None)
        treeHasFocus = wx.Window.FindFocus() is self._repositories
        selectedItem = None
        firstItem = None
        self._repositories.Freeze()
        try:
            self._repositories.DeleteChildren(self._root)
            for repository in repositories:
                item = self._repositories.AppendItem(self._root, repository["full_name"], image=self._folderImage)
                self._repositories.SetItemData(item, repository["id"])
                if firstItem is None:
                    firstItem = item
                if repository["id"] == selectedId:
                    selectedItem = item
            selectedItem = selectedItem if selectedItem is not None else firstItem
            if selectedItem is not None:
                self._repositories.SelectItem(selectedItem)
                if treeHasFocus:
                    self._repositories.SetFocusedItem(selectedItem)
                    self._repositories.EnsureVisible(selectedItem)
        finally:
            self._repositories.Thaw()
            self._populatingRepositories = False
        if query:
            if repositories:
                msg = _("%s repositories found.") % len(repositories)
            else:
                msg = _("No repositories match '%s'.") % query
        else:
            msg = (_("%s repositories listed.") % len(repositories)) if repositories else _("No repositories are visible with the current account permissions.")
        self._setStatus(msg)
        self._onRepositorySelected(None)

    def _selectedRepository(self):
        item = self._repositories.GetSelection()
        if not item.IsOk():
            return None
        identifier = self._repositories.GetItemData(item)
        return next((row for row in self._repositoryRows if row["id"] == identifier), None)

    def _updateRepositoryMenus(self):
        available = not self._busy and self._selectedRepository() is not None
        for item in self._repositoryItems:
            item.Enable(available)

    def _cancelContents(self):
        self._contentCancel.set()
        if self._contentTimer is not None:
            self._contentTimer.Stop()
            self._contentTimer = None
        self._contentLoading = False

    def _onFocusBranch(self, event=None):
        if self._closing:
            return
        if not self._branchChoice.IsEnabled():
            if not self.service.settings.hasAccounts():
                ui.message(_("No account is connected."))
            elif self._busy:
                ui.message(_("Loading repositories…"))
            elif not self._selectedRepository():
                ui.message(_("No repository selected."))
            else:
                ui.message(_("No branches found."))
            return
        self._branchChoice.SetFocus()
        count = self._branchChoice.GetCount()
        if count > 0:
            cur = self._branchChoice.GetSelection()
            idx = cur if cur >= 0 else 0
            branch = self._branchChoice.GetString(idx)
            ui.message(f"{branch} ({idx + 1} / {count})")
        else:
            ui.message(_("Loading branches…"))

    def _onBranchFocus(self, event):
        count = self._branchChoice.GetCount()
        if count > 0:
            cur = self._branchChoice.GetSelection()
            idx = cur if cur >= 0 else 0
            branch = self._branchChoice.GetString(idx)
            ui.message(f"{branch} ({idx + 1} / {count})")
        event.Skip()

    def _onBranchKey(self, event):
        code = event.GetKeyCode()
        if (code == wx.WXK_F10 and event.ShiftDown()) or code == getattr(wx, "WXK_WINDOWS_MENU", None):
            self._onBranchContext()
            return
        if code == wx.WXK_TAB and not event.ShiftDown() and not event.ControlDown() and not event.AltDown():
            self._focusContents(None)
            return
        if code == wx.WXK_TAB and event.ShiftDown() and not event.ControlDown() and not event.AltDown():
            self._repositories.SetFocus()
            return
        if code == wx.WXK_RETURN and not event.HasAnyModifiers():
            self._focusContents(None)
            return

        if not event.HasAnyModifiers():
            count = self._branchChoice.GetCount()
            if count == 0:
                if code in (wx.WXK_UP, wx.WXK_DOWN):
                    ui.message(_("Loading branches…") if self._selectedRepository() else _("No repository selected."))
                    return
                event.Skip()
                return

            cur = self._branchChoice.GetSelection()
            if cur < 0:
                cur = 0

            if code == wx.WXK_DOWN:
                if cur < count - 1:
                    new_idx = cur + 1
                    self._branchChoice.SetSelection(new_idx)
                    self._onBranchSelected(None)
                else:
                    branch = self._branchChoice.GetString(cur)
                    ui.message(f"{branch} ({count} / {count})")
                return

            if code == wx.WXK_UP:
                if cur > 0:
                    new_idx = cur - 1
                    self._branchChoice.SetSelection(new_idx)
                    self._onBranchSelected(None)
                else:
                    branch = self._branchChoice.GetString(cur)
                    ui.message(f"{branch} (1 / {count})")
                return

            if code == wx.WXK_HOME:
                if cur != 0:
                    self._branchChoice.SetSelection(0)
                    self._onBranchSelected(None)
                else:
                    branch = self._branchChoice.GetString(0)
                    ui.message(f"{branch} (1 / {count})")
                return

            if code == wx.WXK_END:
                last = count - 1
                if cur != last:
                    self._branchChoice.SetSelection(last)
                    self._onBranchSelected(None)
                else:
                    branch = self._branchChoice.GetString(last)
                    ui.message(f"{branch} ({count} / {count})")
                return

        event.Skip()

    def _onRefreshBranches(self, event=None):
        if self._closing or self._busy:
            return
        repo = self._selectedRepository()
        if repo:
            self._loadBranches(repo)

    def _onBranchContext(self, event=None):
        if self._closing or self._busy or self._child is not None or self._prompt is not None:
            return
        repo = self._selectedRepository()
        if not repo:
            return
        menu = wx.Menu()
        newBranchItem = menu.Append(wx.ID_ANY, _("&New branch…"))
        menu.Bind(wx.EVT_MENU, self._onCreateBranch, id=newBranchItem.GetId())
        if self._currentBranch:
            delBranchItem = menu.Append(wx.ID_ANY, _("&Delete current branch…"))
            menu.Bind(wx.EVT_MENU, self._onDeleteBranch, id=delBranchItem.GetId())
        menu.AppendSeparator()
        refreshBranchItem = menu.Append(wx.ID_ANY, _("&Refresh branches"))
        menu.Bind(wx.EVT_MENU, self._onRefreshBranches, id=refreshBranchItem.GetId())

        self._branchChoice.PopupMenu(menu, wx.DefaultPosition)
        menu.Destroy()

    def _onBranchSelected(self, event):
        if self._closing or self._busy:
            return
        branch = self._branchChoice.GetStringSelection()
        if branch == self._currentBranch:
            return
        self._currentBranch = branch
        repository = self._selectedRepository()
        if repository:
            cur = self._branchChoice.GetSelection()
            count = self._branchChoice.GetCount()
            if count > 1 and cur >= 0:
                ui.message(_("Branch switched: %s") % f"{branch} ({cur + 1} / {count})")
            else:
                ui.message(_("Branch switched: %s") % branch)
            self._loadDirectory(repository, "")

    def _cancelBranches(self):
        self._branchesCancel.set()

    def _loadBranches(self, repository):
        self._cancelBranches()
        default_branch = repository.get("default_branch") or ""

        def success(branches):
            if self._closing or self._selectedRepository() != repository:
                return
            self._branches = branches
            self._branchChoice.Clear()
            for b in branches:
                self._branchChoice.Append(b)
            if branches:
                if self._currentBranch in branches:
                    target_branch = self._currentBranch
                elif default_branch and default_branch in branches:
                    target_branch = default_branch
                else:
                    target_branch = branches[0]
                previous_branch = self._currentBranch
                self._currentBranch = target_branch
                self._branchChoice.SetStringSelection(target_branch)
                if previous_branch != target_branch and self._contentRepositoryId == repository["id"]:
                    label = _("Contents: %s") % (repository["full_name"] + "/" + self._currentPath) + f" [{target_branch}]"
                    self._contentLabel.SetLabel(label)
                    self._contents.SetName(label)
                if wx.Window.FindFocus() is self._branchChoice:
                    cur = self._branchChoice.GetSelection()
                    idx = cur if cur >= 0 else 0
                    ui.message(f"{self._currentBranch} ({idx + 1} / {len(branches)})")
            else:
                self._currentBranch = ""
                if wx.Window.FindFocus() is self._branchChoice:
                    ui.message(_("No branches found."))
            self._branchChoice.Enable(bool(branches))

        def failure(msg):
            pass

        runTask(self, lambda cancel, report: self.service.loadBranches(repository["full_name"], cancel=cancel), success, failure, slot="_branchesCancel")

    def _clearContents(self):
        self._cancelContents()
        self._cancelBranches()
        self._contents.DeleteAllItems()
        self._contentRows = []
        self._currentPath = ""
        self._contentRepositoryId = None
        self._branches = []
        self._currentBranch = ""
        self._branchChoice.Clear()
        self._branchChoice.Enable(False)
        self._contentLabel.SetLabel(_("Contents"))
        self._contents.SetName(_("Contents"))

    def _onRepositorySelected(self, event):
        if self._closing or self._populatingRepositories:
            return
        self._updateRepositoryMenus()
        repository = self._selectedRepository()
        self._clearContents()
        if repository is not None:
            self._currentBranch = repository.get("default_branch") or ""
            self._branchChoice.Enable(True)
            self._loadBranches(repository)
            self._contentLabel.SetLabel(_("Contents: %s") % (repository["full_name"] + "/"))
            self._contentTimer = wx.CallLater(180, self._loadDirectory, repository, "")
        self.Layout()

    def _loadDirectory(self, repository, path, selectPath=None, announceLoad=True):
        if self._closing:
            return
        selected = self._selectedRepository()
        if not selected or selected["id"] != repository["id"]:
            return
        self._cancelContents()
        self._contentLoading = True
        branch = self._currentBranch or None
        branchSuffix = f" ({branch})" if branch else ""
        self._setStatus(_("Loading contents: %s") % (repository["full_name"] + "/" + path + branchSuffix), announce=announceLoad)

        def success(rows):
            self._contentLoading = False
            self._currentPath = path
            self._contentRepositoryId = repository["id"]
            self._contentRows = rows
            branch = self._currentBranch or None
            branchSuffix = f" [{branch}]" if branch else ""
            label = _("Contents: %s") % (repository["full_name"] + "/" + path) + branchSuffix
            self._contentLabel.SetLabel(label)
            self._contents.SetName(label)
            kinds = {"dir": _("Folder"), "file": _("File"), "symlink": _("Symbolic link"), "submodule": _("Submodule")}
            self._contents.Freeze()
            try:
                self._contents.DeleteAllItems()
                selectedIndex = 0
                for index, row in enumerate(rows):
                    self._contents.InsertItem(index, row["name"])
                    self._contents.SetItem(index, 1, kinds[row["type"]])
                    if row["path"] == selectPath:
                        selectedIndex = index
                if rows:
                    self._contents.Select(selectedIndex)
            finally:
                self._contents.Thaw()
            self._setStatus((_("%s items listed.") % len(rows)) if rows else _("This folder is empty."))
            # Emit item focus after rebuilding, without taking focus from the tree.
            self._queueContentFocus()

        def failure(message):
            self._contentLoading = False
            self._setStatus(message)

        runTask(self, lambda cancel, report: self.service.loadContents(repository["full_name"], path, cancel, ref=branch), success, failure, slot="_contentCancel")

    def _onRepositoryKey(self, event):
        if event.GetKeyCode() == ord("F") and event.ControlDown() and not event.ShiftDown() and not event.AltDown():
            self._onFocusSearch()
            return
        if event.GetKeyCode() == ord("B") and event.ControlDown() and not event.ShiftDown() and not event.AltDown():
            self._onFocusBranch()
            return
        if event.GetKeyCode() == wx.WXK_TAB and not event.ShiftDown() and not event.ControlDown() and not event.AltDown():
            if self._branchChoice.IsEnabled():
                self._onFocusBranch()
            else:
                self._focusContents(None)
            return
        if event.GetKeyCode() == wx.WXK_TAB and event.ShiftDown() and not event.ControlDown() and not event.AltDown():
            if self._repoSearchCtrl.IsEnabled():
                self._onFocusSearch()
            else:
                self._closeButton.SetFocus()
            return
        if event.GetKeyCode() == wx.WXK_F10 and event.ShiftDown():
            self._onRepositoryContext(None)
            return
        event.Skip()

    def _onContentKey(self, event):
        if event.GetKeyCode() == ord("B") and event.ControlDown() and not event.ShiftDown() and not event.AltDown():
            self._onFocusBranch()
            return
        if event.GetKeyCode() == wx.WXK_TAB and event.ShiftDown() and not event.ControlDown() and not event.AltDown():
            if self._branchChoice.IsEnabled():
                self._branchChoice.SetFocus()
            else:
                self._repositories.SetFocus()
            return
        if event.GetKeyCode() == ord("S") and event.ControlDown() and not event.ShiftDown() and not event.AltDown():
            self._onDownloadContent(None)
            return
        if event.GetKeyCode() == ord("N") and event.ControlDown() and not event.ShiftDown() and not event.AltDown():
            self._onCreateFile(None)
            return
        if event.GetKeyCode() == ord("E") and event.ControlDown() and not event.ShiftDown() and not event.AltDown():
            self._onEditContent(None)
            return
        if event.GetKeyCode() == ord("U") and event.ControlDown() and not event.ShiftDown() and not event.AltDown():
            self._onUploadFile(None)
            return
        if event.GetKeyCode() == ord("U") and event.ControlDown() and event.ShiftDown() and not event.AltDown():
            self._onUploadFolder(None)
            return
        if event.GetKeyCode() == getattr(wx, "WXK_F2", 341) and not event.HasAnyModifiers():
            self._onRenameContent(None)
            return
        if event.GetKeyCode() == ord("C") and event.ControlDown() and event.ShiftDown() and not event.AltDown():
            self._onCopyContent(None)
            return
        if event.GetKeyCode() == wx.WXK_DELETE and not event.HasAnyModifiers():
            self._onDeleteContent(None)
            return
        if event.GetKeyCode() == wx.WXK_F10 and event.ShiftDown():
            self._onContentContext(None)
            return
        if event.GetKeyCode() == wx.WXK_BACK and not event.HasAnyModifiers():
            repository = self._selectedRepository()
            if self._contentLoading:
                return
            if repository and self._currentPath:
                self._loadDirectory(repository, self._currentPath.rpartition("/")[0], selectPath=self._currentPath)
            else:
                ui.message(_("You are already at the repository root."))
            return
        event.Skip()

    def _onContentActivate(self, event):
        if self._contentLoading or self._contentTimer is not None:
            ui.message(_("Please wait until folder contents finish loading."))
            return
        index = event.GetIndex()
        repository = self._selectedRepository()
        if not repository or not 0 <= index < len(self._contentRows):
            return
        row = self._contentRows[index]
        if row["type"] == "dir":
            self._loadDirectory(repository, row["path"])
        elif row["type"] == "submodule":
            ui.message(_("Submodules cannot be viewed or downloaded directly as files."))
        else:
            self._viewFile(row)

    def _focusContents(self, event):
        self._contents.SetFocus()
        self._queueContentFocus()

    def _onContentFocus(self, event):
        event.Skip()
        self._queueContentFocus()

    def _queueContentFocus(self):
        if self._closing or self._contentFocusQueued:
            return
        self._contentFocusQueued = True
        wx.CallAfter(self._finishContentFocus)

    def _finishContentFocus(self):
        self._contentFocusQueued = False
        self._repairContentFocus(forceEvent=True)

    def _repairContentFocus(self, forceEvent=False):
        if self._closing or wx.Window.FindFocus() is not self._contents:
            return
        count = self._contents.GetItemCount()
        if not count:
            return
        selected = self._contents.GetFirstSelected()
        focused = self._contents.GetFocusedItem()
        if not 0 <= selected < count:
            selected = focused if 0 <= focused < count else 0
            self._contents.Select(selected)
        if forceEvent:
            # Keep selection while regenerating the native item-focus event.
            self._contents.SetItemState(-1, 0, wx.LIST_STATE_FOCUSED)
        if forceEvent or focused != selected:
            self._contents.Focus(selected)
        self._contents.EnsureVisible(selected)

    def _refreshContents(self, event, announceLoad=True):
        repository = self._selectedRepository()
        if not repository or self._busy:
            return
        index = self._contents.GetFirstSelected()
        selectPath = self._contentRows[index]["path"] if 0 <= index < len(self._contentRows) else None
        self._loadDirectory(repository, self._currentPath, selectPath=selectPath, announceLoad=announceLoad)

    def _refreshFocused(self, event):
        if wx.Window.FindFocus() is self._contents:
            self._refreshContents(event)
        else:
            self._onRefresh(event)

    def _onRepositoryContext(self, event):
        if self._closing or self._child is not None or self._prompt is not None:
            return
        self._updateRepositoryMenus()
        item = self._repositories.GetSelection()
        if not item.IsOk():
            return
        rectangle = self._repositories.GetBoundingRect(item)
        point = rectangle.GetBottomLeft() if rectangle is not None else wx.Point(5, 5)
        self._repositories.PopupMenu(self._repositoryContextMenu, point)

    def _repositoryUrl(self):
        repository = self._selectedRepository()
        return "https://github.com/" + quote(repository["full_name"], safe="/") if repository else None

    def _openRepository(self, event):
        url = self._repositoryUrl()
        if url:
            openPage(url, self)

    def _cancelDownloads(self):
        if self._downloadCancel is not None:
            self._downloadCancel.set()
        if self._viewCancel is not None:
            self._viewCancel.set()
        if self._mutationCancel is not None:
            self._mutationCancel.set()
        self._mutating = False

    def _runChildModal(self, dialog):
        if self._closing or self._child is not None:
            if dialog:
                dialog.Destroy()
            return wx.ID_CANCEL
        self._child = dialog
        try:
            return dialog.ShowModal()
        finally:
            if hasattr(dialog, "cancelAndClose"):
                dialog.cancelAndClose()
            self._child = None
            if dialog:
                dialog.Destroy()

    def _onCreateRepository(self, event=None):
        if self._closing or self._busy or self._child is not None or not self.service.settings.hasAccounts():
            return
        if self._mutating:
            ui.message(_("Another repository modification is already in progress. Please wait."))
            return
        dlg = NewRepositoryDialog(self)
        data = None
        self._child = dlg
        try:
            if dlg.ShowModal() == wx.ID_OK:
                data = dlg.getData()
        finally:
            dlg.cancelAndClose()
            self._child = None
            if dlg:
                dlg.Destroy()
        if not data or self._closing:
            return

        repoName = data["name"]
        self._mutating = True
        self._setStatus(_("Creating repository: %s…") % repoName)

        def success(result):
            self._mutating = False
            fullName = result.get("full_name", repoName)
            self._setStatus(_("Repository created successfully: %s") % fullName)
            newId = result.get("id")
            self._reloadRepositories(selectRepoId=newId, announceLoad=False)

        def failure(message):
            self._mutating = False
            self._setStatus(message)

        runTask(
            self,
            lambda cancel, report: self.service.createRepository(
                data["name"],
                description=data["description"],
                private=data["private"],
                auto_init=data["auto_init"],
                license_template=data.get("license_template", ""),
                cancel=cancel,
            ),
            success,
            failure,
            slot="_mutationCancel",
        )

    def _onOpenIssues(self, event=None):
        if self._closing or self._busy or self._child is not None:
            return
        repo = self._selectedRepository()
        if not repo:
            return
        self._runChildModal(IssuesDialog(self, repo["full_name"], self.service))

    def _onOpenNewIssue(self, event=None):
        if self._closing or self._busy or self._child is not None:
            return
        repo = self._selectedRepository()
        if not repo:
            return
        dlg = NewIssueDialog(self, repo["full_name"], service=self.service)
        data = None
        self._child = dlg
        try:
            if dlg.ShowModal() == wx.ID_OK:
                data = dlg.getData()
        finally:
            dlg.cancelAndClose()
            self._child = None
            if dlg:
                dlg.Destroy()
        if not data or self._closing:
            return

        self._setStatus(_("Creating issue…"))

        def create_target():
            try:
                self.service.createIssue(repo["full_name"], data["title"], data.get("body", ""))

                def on_ok():
                    if not self._closing:
                        self._setStatus(_("Issue created successfully."))

                wx.CallAfter(on_ok)
            except Exception as err:
                def on_err():
                    if self._closing:
                        return
                    if isinstance(err, (AuthError, CredentialError, SettingsError, OSError)):
                        self._setStatus(errorMessage(err))
                    else:
                        self._setStatus(_("Failed to create issue."))

                wx.CallAfter(on_err)

        threading.Thread(target=create_target, daemon=True).start()

    def _onOpenReleases(self, event=None):
        if self._closing or self._busy or self._child is not None:
            return
        repo = self._selectedRepository()
        if not repo:
            return
        default_branch = self._currentBranch or repo.get("default_branch") or "main"
        self._runChildModal(ReleasesDialog(self, repo["full_name"], self.service, default_branch=default_branch))

    def _onOpenNewRelease(self, event=None):
        if self._closing or self._busy or self._child is not None:
            return
        if self._mutating:
            ui.message(_("Another repository modification is already in progress. Please wait."))
            return
        repo = self._selectedRepository()
        if not repo:
            return
        default_branch = self._currentBranch or repo.get("default_branch") or "main"
        dlg = NewReleaseDialog(self, repo["full_name"], default_branch=default_branch)
        data = None
        self._child = dlg
        try:
            if dlg.ShowModal() == wx.ID_OK:
                data = dlg.getData()
        finally:
            dlg.cancelAndClose()
            self._child = None
            if dlg:
                dlg.Destroy()
        if not data or self._closing:
            return

        self._mutating = True
        self._setStatus(_("Publishing release: %s…") % data["tag"])

        def worker():
            try:
                self.service.createRelease(
                    repo["full_name"],
                    data["tag"],
                    name=data["name"],
                    body=data["body"],
                    target_commitish=data["branch"],
                    prerelease=data["prerelease"],
                    asset_path=data["file_path"],
                )

                def on_ok():
                    self._mutating = False
                    if not self._closing:
                        self._setStatus(_("Release published successfully."))

                wx.CallAfter(on_ok)
            except Exception as err:
                def on_err():
                    self._mutating = False
                    if self._closing:
                        return
                    if isinstance(err, (AuthError, CredentialError, SettingsError, OSError)):
                        self._setStatus(errorMessage(err))
                    else:
                        self._setStatus(_("Failed to publish release."))

                wx.CallAfter(on_err)

        threading.Thread(target=worker, daemon=True).start()

    def _onOpenNotifications(self, event=None):
        if self._closing or self._busy or self._child is not None:
            return
        account = self.service.settings.getAccount()
        if not account:
            return
        self._runChildModal(NotificationsDialog(self, self.service))

    def _onCreateBranch(self, event=None):
        if self._closing or self._busy or self._child is not None:
            return
        if self._mutating:
            ui.message(_("Another repository modification is already in progress. Please wait."))
            return
        repo = self._selectedRepository()
        if not repo:
            return
        if not self._branches:
            ui.message(_("Loading branches…"))
            return
        dlg = NewBranchDialog(self, repo["full_name"], self._branches, current_branch=self._currentBranch)
        data = None
        self._child = dlg
        try:
            if dlg.ShowModal() == wx.ID_OK:
                data = dlg.getData()
        finally:
            dlg.cancelAndClose()
            self._child = None
            if dlg:
                dlg.Destroy()
        if not data or self._closing:
            return

        new_branch_name = data["name"]
        source_branch = data["source"]
        self._mutating = True
        self._setStatus(_("Creating branch: %s…") % new_branch_name)

        def success(result):
            self._mutating = False
            self._setStatus(_("Branch created successfully: %s") % new_branch_name)
            self._currentBranch = new_branch_name
            self._loadBranches(repo)
            self._loadDirectory(repo, "")

        def failure(message):
            self._mutating = False
            self._setStatus(message)

        runTask(
            self,
            lambda cancel, report: self.service.createBranch(
                repo["full_name"], new_branch_name, sourceBranch=source_branch, cancel=cancel
            ),
            success,
            failure,
            slot="_mutationCancel",
        )

    def _onDeleteBranch(self, event=None):
        if self._closing or self._busy or self._child is not None:
            return
        if self._mutating:
            ui.message(_("Another repository modification is already in progress. Please wait."))
            return
        repo = self._selectedRepository()
        if not repo:
            return
        if not self._currentBranch:
            ui.message(_("No branch selected."))
            return
        default_branch = repo.get("default_branch") or ""
        if self._currentBranch == default_branch:
            self.showMessage(
                _("The default branch '%s' cannot be deleted.") % default_branch,
                wx.OK | wx.ICON_WARNING,
            )
            return

        ans = self.showMessage(
            _("Are you sure you want to delete branch '%s' from repository '%s'?") % (self._currentBranch, repo["full_name"]),
            wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION,
        )
        if ans != wx.ID_YES or self._closing:
            return

        target_branch = self._currentBranch
        self._mutating = True
        self._setStatus(_("Deleting branch: %s…") % target_branch)

        def success(result):
            self._mutating = False
            self._setStatus(_("Branch deleted successfully: %s") % target_branch)
            self._currentBranch = default_branch
            self._loadBranches(repo)
            self._loadDirectory(repo, "")

        def failure(message):
            self._mutating = False
            self._setStatus(message)

        runTask(
            self,
            lambda cancel, report: self.service.deleteBranch(repo["full_name"], target_branch, cancel=cancel),
            success,
            failure,
            slot="_mutationCancel",
        )

    def _onOpenCommits(self, event=None):
        if self._closing or self._busy or self._child is not None:
            return
        repo = self._selectedRepository()
        if not repo:
            return
        self._runChildModal(CommitsDialog(self, repo["full_name"], self.service, branch=self._currentBranch or None))

    def _onOpenPullRequests(self, event=None):
        if self._closing or self._busy or self._child is not None:
            return
        repo = self._selectedRepository()
        if not repo:
            return
        self._runChildModal(PullRequestsDialog(self, repo["full_name"], self.service))

    def _onRepoSettings(self, event=None):
        if self._closing or self._busy or self._child is not None:
            return
        if self._mutating:
            ui.message(_("Another repository modification is already in progress. Please wait."))
            return
        repo = self._selectedRepository()
        if not repo:
            return

        dlg = RepoSettingsDialog(self, repo)
        action = None
        data = None
        self._child = dlg
        try:
            if dlg.ShowModal() == wx.ID_OK:
                action = dlg.getAction()
                data = dlg.getData()
        finally:
            dlg.cancelAndClose()
            self._child = None
            if dlg:
                dlg.Destroy()
        if not action or self._closing:
            return

        if action == "save" and data:
            self._mutating = True
            self._setStatus(_("Updating repository settings…"))

            def success(updated_repo):
                self._mutating = False
                self._setStatus(_("Repository settings updated successfully."))
                if isinstance(updated_repo, dict):
                    repo["description"] = updated_repo.get("description") or ""
                    repo["private"] = bool(updated_repo.get("private", False))
                    repo["archived"] = bool(updated_repo.get("archived", False))
                self._reloadRepositories(selectRepoId=repo["id"], announceLoad=False)

            def failure(message):
                self._mutating = False
                self._setStatus(message)

            runTask(
                self,
                lambda cancel, report: self.service.updateRepository(
                    repo["full_name"],
                    description=data.get("description"),
                    private=data.get("private"),
                    archived=data.get("archived"),
                    cancel=cancel,
                ),
                success,
                failure,
                slot="_mutationCancel",
            )
        elif action == "delete":
            wx.CallAfter(self._onDeleteRepository)

    def _onDeleteRepository(self, event=None):
        if self._closing or self._busy or self._child is not None:
            return
        if self._mutating:
            ui.message(_("Another repository modification is already in progress. Please wait."))
            return
        repo = self._selectedRepository()
        if not repo:
            return

        delDlg = DeleteRepoConfirmDialog(self, repo["full_name"])
        confirmed = False
        self._child = delDlg
        try:
            if delDlg.ShowModal() == wx.ID_OK:
                confirmed = True
        finally:
            delDlg.cancelAndClose()
            self._child = None
            if delDlg:
                delDlg.Destroy()
        if not confirmed or self._closing:
            return

        self._mutating = True
        self._setStatus(_("Deleting repository: %s…") % repo["full_name"])

        def del_success(result):
            self._mutating = False
            self._setStatus(_("Repository deleted successfully: %s") % repo["full_name"])
            self._reloadRepositories(announceLoad=False)

        def del_failure(message):
            self._mutating = False
            self._setStatus(message)
            self.showMessage(message, wx.OK | wx.ICON_ERROR)

        runTask(
            self,
            lambda cancel, report: self.service.deleteRepository(repo["full_name"], cancel=cancel),
            del_success,
            del_failure,
            slot="_mutationCancel",
        )

    def _onExploreRepositories(self, event=None):
        if self._closing or self._busy or self._child is not None:
            return
        account = self.service.settings.getAccount()
        if not account:
            ui.message(_("No account is connected."))
            return
        self._runChildModal(GlobalSearchDialog(self, self.service))

    def _onDownloadRepository(self, event):
        if self._closing or self._busy or self._child is not None:
            return
        repository = self._selectedRepository()
        if not repository:
            return
        repoName = repository["full_name"].split("/")[-1]
        with wx.FileDialog(
            self,
            message=_("Save repository as ZIP"),
            defaultFile=f"{repoName}.zip",
            wildcard=_("ZIP files (*.zip)|*.zip|All files (*.*)|*.*"),
            style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT,
        ) as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return
            targetPath = dlg.GetPath()
        if self._closing:
            return

        self._setStatus(_("Downloading repository: %s…") % repository["full_name"])

        def success(path):
            fileName = os.path.basename(path)
            self._setStatus(_("Repository successfully saved: %s") % fileName)

        def failure(message):
            self._setStatus(message)

        runTask(
            self,
            lambda cancel, report: self.service.downloadRepository(repository["full_name"], targetPath, cancel, ref=self._currentBranch or None),
            success,
            failure,
            slot="_downloadCancel",
        )

    def _selectedContent(self):
        index = self._contents.GetFirstSelected()
        if 0 <= index < len(self._contentRows):
            return self._contentRows[index]
        return None

    def _onDownloadContent(self, event=None, targetItem=None):
        if self._closing or self._busy or self._child is not None:
            return
        if self._contentLoading or self._contentTimer is not None:
            ui.message(_("Please wait until folder contents finish loading."))
            return
        repository = self._selectedRepository()
        item = targetItem if targetItem is not None else self._selectedContent()
        if not repository or not item:
            return
        if item.get("type") == "submodule":
            ui.message(_("Submodules cannot be viewed or downloaded directly as files."))
            return

        isFolder = item["type"] == "dir"
        if isFolder:
            defaultFile = f"{item['name']}.zip"
            wildcard = _("ZIP files (*.zip)|*.zip|All files (*.*)|*.*")
            dialogTitle = _("Save folder as ZIP")
            startMessage = _("Packaging and downloading folder %s…") % item["name"]
            successTemplate = _("Folder successfully saved: %s")
        else:
            defaultFile = item["name"]
            wildcard = _("All files (*.*)|*.*")
            dialogTitle = _("Save file")
            startMessage = _("Downloading file %s…") % item["name"]
            successTemplate = _("File successfully saved: %s")

        with wx.FileDialog(
            self,
            message=dialogTitle,
            defaultFile=defaultFile,
            wildcard=wildcard,
            style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT,
        ) as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return
            targetPath = dlg.GetPath()
        if self._closing:
            return

        self._setStatus(startMessage)

        def success(path):
            fileName = os.path.basename(path)
            self._setStatus(successTemplate % fileName)

        def failure(message):
            self._setStatus(message)

        branch = self._currentBranch or None
        if isFolder:
            task = lambda cancel, report: self.service.downloadContentFolder(repository["full_name"], item["path"], targetPath, cancel, ref=branch)
        else:
            task = lambda cancel, report: self.service.downloadContentFile(repository["full_name"], item["path"], targetPath, cancel, ref=branch)

        runTask(self, task, success, failure, slot="_downloadCancel")

    def _viewFile(self, item):
        if self._closing or self._busy or self._child is not None:
            return
        if self._contentLoading or self._contentTimer is not None:
            ui.message(_("Please wait until folder contents finish loading."))
            return
        repository = self._selectedRepository()
        if not repository or not item:
            return
        if item.get("type") == "submodule":
            ui.message(_("Submodules cannot be viewed or downloaded directly as files."))
            return
        fileName = item["name"]
        size = item.get("size")
        if isinstance(size, int) and size > 5 * 1024 * 1024:
            answer = self.showMessage(
                _("'%s' is too large to display directly (over 5 MB). Would you like to download it instead?") % fileName,
                wx.YES_NO | wx.ICON_QUESTION,
            )
            if not self._closing and answer == wx.ID_YES:
                self._onDownloadContent(targetItem=item)
            return

        self._setStatus(_("Loading file content: %s…") % fileName)

        def success(result):
            self._setStatus("", announce=False)
            if result.get("is_binary"):
                answer = self.showMessage(
                    _("'%s' is a binary file and cannot be viewed as text. Would you like to download it?") % fileName,
                    wx.YES_NO | wx.ICON_QUESTION,
                )
                if not self._closing and answer == wx.ID_YES:
                    self._onDownloadContent(targetItem=item)
                return

            text = result.get("text", "")

            def on_viewer_edit(viewer_dlg):
                self._onEditContent(targetItem=item, initialText=viewer_dlg.content_text, viewerDlg=viewer_dlg)

            self._runChildModal(FileViewerDialog(self, fileName, repository["full_name"], text, on_edit=on_viewer_edit))

        def failure(message):
            self._setStatus(message)

        runTask(
            self,
            lambda cancel, report: self.service.fetchFileText(repository["full_name"], item["path"], cancel, ref=self._currentBranch or None),
            success,
            failure,
            slot="_viewCancel",
        )

    def _onContentContext(self, event):
        if self._closing or self._child is not None or self._prompt is not None:
            return
        if not self._selectedRepository():
            return
        item = self._selectedContent()
        menu = wx.Menu()
        if item:
            if item["type"] == "dir":
                openItem = menu.Append(wx.ID_ANY, _("&Open folder"))
                menu.Bind(wx.EVT_MENU, lambda e: self._loadDirectory(self._selectedRepository(), item["path"]), id=openItem.GetId())
                dlItem = menu.Append(wx.ID_ANY, _("&Download folder as ZIP…") + "\tCtrl+S")
                menu.Bind(wx.EVT_MENU, self._onDownloadContent, id=dlItem.GetId())
                menu.AppendSeparator()
            elif item["type"] != "submodule":
                viewItem = menu.Append(wx.ID_ANY, _("&View file") + "\tEnter")
                menu.Bind(wx.EVT_MENU, lambda e: self._viewFile(item), id=viewItem.GetId())
                editItem = menu.Append(wx.ID_ANY, _("&Edit file…") + "\tCtrl+E")
                menu.Bind(wx.EVT_MENU, lambda e: self._onEditContent(targetItem=item), id=editItem.GetId())
                dlItem = menu.Append(wx.ID_ANY, _("&Download file…") + "\tCtrl+S")
                menu.Bind(wx.EVT_MENU, self._onDownloadContent, id=dlItem.GetId())
                menu.AppendSeparator()

        newFileItem = menu.Append(wx.ID_ANY, _("&New file…") + "\tCtrl+N")
        menu.Bind(wx.EVT_MENU, self._onCreateFile, id=newFileItem.GetId())
        uploadItem = menu.Append(wx.ID_ANY, _("&Upload file(s) from computer…") + "\tCtrl+U")
        menu.Bind(wx.EVT_MENU, self._onUploadFile, id=uploadItem.GetId())
        uploadFolderItem = menu.Append(wx.ID_ANY, _("Upload &folder from computer…") + "\tCtrl+Shift+U")
        menu.Bind(wx.EVT_MENU, self._onUploadFolder, id=uploadFolderItem.GetId())
        if item and item["type"] in ("file", "dir"):
            renameItem = menu.Append(wx.ID_ANY, _("&Rename or move…") + "\tF2")
            menu.Bind(wx.EVT_MENU, self._onRenameContent, id=renameItem.GetId())
            copyItem = menu.Append(wx.ID_ANY, _("&Copy file or folder…") + "\tCtrl+Shift+C")
            menu.Bind(wx.EVT_MENU, self._onCopyContent, id=copyItem.GetId())
        if item and item["type"] == "file":
            delItem = menu.Append(wx.ID_ANY, _("&Delete file…") + "\tDelete")
            menu.Bind(wx.EVT_MENU, self._onDeleteContent, id=delItem.GetId())

        if item:
            menu.AppendSeparator()
            copyItem = menu.Append(wx.ID_ANY, _("&Copy item path"))
            menu.Bind(wx.EVT_MENU, lambda e: self._copyContentPath(item["path"]), id=copyItem.GetId())

        index = self._contents.GetFirstSelected()
        point = wx.DefaultPosition
        if index >= 0:
            rect = self._contents.GetItemRect(index)
            if hasattr(rect, "x"):
                point = wx.Point(rect.x, rect.y + rect.height)
            elif hasattr(rect, "GetBottomLeft"):
                point = rect.GetBottomLeft()
        self._contents.PopupMenu(menu, point)
        menu.Destroy()

    def _copyContentPath(self, path):
        if wx.TheClipboard.Open():
            try:
                copied = wx.TheClipboard.SetData(wx.TextDataObject(path))
            finally:
                wx.TheClipboard.Close()
            if copied:
                ui.message(_("Path copied: %s") % path)
                return
        self._setStatus(_("The path could not be copied."))

    def _onCreateFile(self, event=None):
        if self._closing or self._busy or self._child is not None:
            return
        if self._contentLoading or self._contentTimer is not None:
            ui.message(_("Please wait until folder contents finish loading."))
            return
        if self._mutating:
            ui.message(_("Another repository modification is already in progress. Please wait."))
            return
        repository = self._selectedRepository()
        if not repository:
            return
        existing_names = {r["name"] for r in self._contentRows}
        dlg = NewFileDialog(
            self,
            repository["full_name"],
            current_dir=self._currentPath,
            existing_names=existing_names,
        )
        result_tuple = None
        self._child = dlg
        try:
            if dlg.ShowModal() == wx.ID_OK:
                result_tuple = dlg.getResult()
        finally:
            dlg.cancelAndClose()
            self._child = None
            if dlg:
                dlg.Destroy()
        if not result_tuple or self._closing:
            return
        path, content_bytes, commit_msg = result_tuple

        filename = os.path.basename(path)
        self._mutating = True
        self._setStatus(_("Creating file: %s…") % filename)

        def success(result):
            self._mutating = False
            self._setStatus(_("File created successfully: %s") % filename)
            self._refreshContents(None, announceLoad=False)

        def failure(message):
            self._mutating = False
            self._setStatus(message)

        branch = self._currentBranch or None
        runTask(
            self,
            lambda cancel, report: self.service.createOrUpdateFile(
                repository["full_name"], path, content_bytes, commit_msg, cancel=cancel, branch=branch
            ),
            success,
            failure,
            slot="_mutationCancel",
        )

    def _onUploadFile(self, event=None):
        if self._closing or self._busy or self._child is not None:
            return
        if self._contentLoading or self._contentTimer is not None:
            ui.message(_("Please wait until folder contents finish loading."))
            return
        if self._mutating:
            ui.message(_("Another repository modification is already in progress. Please wait."))
            return
        repository = self._selectedRepository()
        if not repository:
            return
        with wx.FileDialog(
            self,
            message=_("Select file(s) to upload"),
            wildcard=_("All files (*.*)|*.*"),
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST | wx.FD_MULTIPLE,
        ) as fileDlg:
            if fileDlg.ShowModal() != wx.ID_OK:
                return
            local_paths = fileDlg.GetPaths()
        if self._closing or not local_paths:
            return

        for path in local_paths:
            try:
                if os.path.getsize(path) > 50 * 1024 * 1024:
                    fname = os.path.basename(path)
                    ui.message(_("File '%s' exceeds 50 MB limit.") % fname)
                    return
            except OSError:
                self._setStatus(_("Could not read local file."))
                return

        file_count = len(local_paths)
        first_name = os.path.basename(local_paths[0])
        existing = next(
            (r for r in self._contentRows if r.get("name") == first_name and r.get("type") == "file"),
            None,
        )
        known_sha = existing.get("sha") if (file_count == 1 and existing) else None

        confDlg = UploadConfirmDialog(
            self,
            first_name,
            repository["full_name"],
            current_dir=self._currentPath,
            file_count=file_count,
            local_paths=local_paths,
            service=self.service,
            branch=self._currentBranch or None,
            known_sha=known_sha,
        )
        self._child = confDlg
        self._mutating = True
        try:
            result = confDlg.ShowModal()
        finally:
            confDlg.cancelAndClose()
            self._child = None
            self._mutating = False
            confDlg.Destroy()

        if self._closing:
            return

        if result == wx.ID_OK or getattr(confDlg, "uploaded_count", 0) > 0:
            self._refreshContents(None, announceLoad=False)

    def _onUploadFolder(self, event=None):
        if self._closing or self._busy or self._child is not None:
            return
        if self._contentLoading or self._contentTimer is not None:
            ui.message(_("Please wait until folder contents finish loading."))
            return
        if self._mutating:
            ui.message(_("Another repository modification is already in progress. Please wait."))
            return
        repository = self._selectedRepository()
        if not repository:
            return
        with wx.DirDialog(
            self,
            message=_("Select folder to upload"),
            style=wx.DD_DEFAULT_STYLE | wx.DD_DIR_MUST_EXIST,
        ) as dirDlg:
            if dirDlg.ShowModal() != wx.ID_OK:
                return
            local_dir = dirDlg.GetPath()
        if self._closing or not local_dir:
            return

        folder_name = os.path.basename(local_dir.rstrip("\\/"))
        if not folder_name:
            folder_name = "folder"

        files_to_upload = []
        for root, dirs, files in os.walk(local_dir):
            dirs[:] = [d for d in dirs if d != ".git"]
            for f in files:
                abs_path = os.path.join(root, f)
                rel_path = os.path.relpath(abs_path, local_dir).replace("\\", "/")
                try:
                    if os.path.getsize(abs_path) > 50 * 1024 * 1024:
                        ui.message(_("File '%s' exceeds 50 MB limit.") % f)
                        return
                except OSError:
                    continue
                files_to_upload.append((abs_path, rel_path))

        if not files_to_upload:
            ui.message(_("The selected folder contains no files."))
            return

        total_files = len(files_to_upload)
        confDlg = UploadFolderConfirmDialog(
            self,
            folder_name,
            total_files,
            repository["full_name"],
            current_dir=self._currentPath,
            files_to_upload=files_to_upload,
            service=self.service,
            branch=self._currentBranch or None,
        )
        self._child = confDlg
        self._mutating = True
        try:
            result = confDlg.ShowModal()
        finally:
            confDlg.cancelAndClose()
            self._child = None
            self._mutating = False
            confDlg.Destroy()

        if self._closing:
            return

        if result == wx.ID_OK or getattr(confDlg, "uploaded_count", 0) > 0:
            self._refreshContents(None, announceLoad=False)

    def _onRenameContent(self, event=None):
        if self._closing or self._busy or self._child is not None:
            return
        if self._contentLoading or self._contentTimer is not None:
            ui.message(_("Please wait until folder contents finish loading."))
            return
        if self._mutating:
            ui.message(_("Another repository modification is already in progress. Please wait."))
            return
        repository = self._selectedRepository()
        item = self._selectedContent()
        if not repository or not item:
            ui.message(_("Please select a file or folder to rename or move."))
            return
        if item.get("type") not in ("file", "dir"):
            ui.message(_("Only files and folders can be renamed or moved."))
            return

        is_folder = (item.get("type") == "dir")
        old_path = item["path"]
        confDlg = RenameMoveDialog(self, old_path, repository["full_name"], is_folder=is_folder)
        new_path = None
        commit_msg = None
        self._child = confDlg
        try:
            if confDlg.ShowModal() == wx.ID_OK:
                new_path, commit_msg = confDlg.getResult()
        finally:
            confDlg.cancelAndClose()
            self._child = None
            if confDlg:
                confDlg.Destroy()

        if not new_path or self._closing:
            return

        self._mutating = True
        branch = self._currentBranch or None

        if not is_folder:
            self._setStatus(_("Renaming / moving file: %s…") % old_path)

            def file_task(cancel, report):
                report(_("Fetching file content: %s…") % old_path)
                content_bytes = self.service.getRawFileContent(
                    repository["full_name"], old_path, cancel=cancel, ref=branch
                )
                known_sha = item.get("sha")
                old_sha = known_sha or self.service.getFileSha(
                    repository["full_name"], old_path, cancel=cancel, ref=branch
                )
                target_sha = self.service.getFileSha(
                    repository["full_name"], new_path, cancel=cancel, ref=branch
                )
                report(_("Creating file at new path: %s…") % new_path)
                self.service.createOrUpdateFile(
                    repository["full_name"],
                    new_path,
                    content_bytes,
                    commit_msg,
                    sha=target_sha,
                    cancel=cancel,
                    branch=branch,
                )
                report(_("Removing file from old path: %s…") % old_path)
                source_sha = self.service.getFileSha(
                    repository["full_name"], old_path, cancel=cancel, ref=branch
                ) or old_sha
                self.service.deleteFile(
                    repository["full_name"],
                    old_path,
                    source_sha,
                    commit_msg,
                    cancel=cancel,
                    branch=branch,
                )
                return new_path

            def file_success(result):
                self._mutating = False
                self._setStatus(_("File moved successfully: %s -> %s") % (old_path, new_path))
                self._refreshContents(None, announceLoad=False)

            def file_failure(message):
                self._mutating = False
                self._setStatus(message)

            runTask(self, file_task, file_success, file_failure, slot="_mutationCancel")
        else:
            self._setStatus(_("Renaming / moving folder: %s…") % old_path)

            def folder_task(cancel, report):
                report(_("Scanning folder contents: %s…") % old_path)
                base_folder = old_path.strip("/")
                queue = [base_folder]
                files_to_move = []

                while queue:
                    if cancel and cancel.is_set():
                        raise AuthError("cancelled")
                    cur_dir = queue.pop(0)
                    contents = self.service.loadContents(repository["full_name"], cur_dir, cancel, ref=branch)
                    for entry in contents:
                        if cancel and cancel.is_set():
                            raise AuthError("cancelled")
                        if entry.get("type") == "dir":
                            queue.append(entry["path"])
                        elif entry.get("type") == "file":
                            rel = os.path.relpath(entry["path"], base_folder).replace("\\", "/")
                            files_to_move.append((entry["path"], rel, entry.get("sha")))

                if not files_to_move:
                    return 0

                total_files = len(files_to_move)
                clean_new_path = new_path.strip("/")
                for idx, (old_fpath, rel, old_sha) in enumerate(files_to_move, start=1):
                    if cancel and cancel.is_set():
                        raise AuthError("cancelled")
                    target_fpath = f"{clean_new_path}/{rel}"
                    report(_("Moving file (%d of %d): %s…") % (idx, total_files, rel))
                    data = self.service.getRawFileContent(
                        repository["full_name"], old_fpath, cancel=cancel, ref=branch
                    )
                    sha = old_sha or self.service.getFileSha(
                        repository["full_name"], old_fpath, cancel=cancel, ref=branch
                    )
                    target_sha = self.service.getFileSha(
                        repository["full_name"], target_fpath, cancel=cancel, ref=branch
                    )
                    self.service.createOrUpdateFile(
                        repository["full_name"], target_fpath, data, commit_msg, sha=target_sha, cancel=cancel, branch=branch
                    )
                    source_sha = self.service.getFileSha(
                        repository["full_name"], old_fpath, cancel=cancel, ref=branch
                    ) or sha
                    self.service.deleteFile(
                        repository["full_name"], old_fpath, source_sha, commit_msg, cancel=cancel, branch=branch
                    )

                return total_files

            def folder_success(total_files):
                self._mutating = False
                self._setStatus(_("Folder moved successfully: %s -> %s (%d files)") % (old_path, new_path, total_files))
                self._refreshContents(None, announceLoad=False)

            def folder_failure(message):
                self._mutating = False
                self._setStatus(message)

            runTask(self, folder_task, folder_success, folder_failure, slot="_mutationCancel")

    def _onCopyContent(self, event=None):
        if self._closing or self._busy or self._child is not None:
            return
        if self._contentLoading or self._contentTimer is not None:
            ui.message(_("Please wait until folder contents finish loading."))
            return
        if self._mutating:
            ui.message(_("Another repository modification is already in progress. Please wait."))
            return
        repository = self._selectedRepository()
        item = self._selectedContent()
        if not repository or not item:
            ui.message(_("Please select a file or folder to copy."))
            return
        if item.get("type") not in ("file", "dir"):
            ui.message(_("Only files and folders can be copied."))
            return

        is_folder = (item.get("type") == "dir")
        old_path = item["path"]
        confDlg = CopyDialog(self, old_path, repository["full_name"], is_folder=is_folder)
        new_path = None
        commit_msg = None
        self._child = confDlg
        try:
            if confDlg.ShowModal() == wx.ID_OK:
                new_path, commit_msg = confDlg.getResult()
        finally:
            confDlg.cancelAndClose()
            self._child = None
            if confDlg:
                confDlg.Destroy()

        if not new_path or self._closing:
            return

        self._mutating = True
        branch = self._currentBranch or None

        if not is_folder:
            self._setStatus(_("Copying file: %s…") % old_path)

            def file_task(cancel, report):
                report(_("Fetching file content: %s…") % old_path)
                content_bytes = self.service.getRawFileContent(
                    repository["full_name"], old_path, cancel=cancel, ref=branch
                )
                target_sha = self.service.getFileSha(
                    repository["full_name"], new_path, cancel=cancel, ref=branch
                )
                report(_("Creating copy at: %s…") % new_path)
                self.service.createOrUpdateFile(
                    repository["full_name"],
                    new_path,
                    content_bytes,
                    commit_msg,
                    sha=target_sha,
                    cancel=cancel,
                    branch=branch,
                )
                return new_path

            def file_success(result):
                self._mutating = False
                self._setStatus(_("File copied successfully: %s -> %s") % (old_path, new_path))
                self._refreshContents(None, announceLoad=False)

            def file_failure(message):
                self._mutating = False
                self._setStatus(message)

            runTask(self, file_task, file_success, file_failure, slot="_mutationCancel")
        else:
            self._setStatus(_("Copying folder: %s…") % old_path)

            def folder_task(cancel, report):
                report(_("Scanning folder contents: %s…") % old_path)
                base_folder = old_path.strip("/")
                queue = [base_folder]
                files_to_copy = []

                while queue:
                    if cancel and cancel.is_set():
                        raise AuthError("cancelled")
                    cur_dir = queue.pop(0)
                    contents = self.service.loadContents(repository["full_name"], cur_dir, cancel, ref=branch)
                    for entry in contents:
                        if cancel and cancel.is_set():
                            raise AuthError("cancelled")
                        if entry.get("type") == "dir":
                            queue.append(entry["path"])
                        elif entry.get("type") == "file":
                            rel = os.path.relpath(entry["path"], base_folder).replace("\\", "/")
                            files_to_copy.append((entry["path"], rel))

                if not files_to_copy:
                    return 0

                total_files = len(files_to_copy)
                clean_new_path = new_path.strip("/")
                for idx, (old_fpath, rel) in enumerate(files_to_copy, start=1):
                    if cancel and cancel.is_set():
                        raise AuthError("cancelled")
                    target_fpath = f"{clean_new_path}/{rel}"
                    report(_("Copying file (%d of %d): %s…") % (idx, total_files, rel))
                    data = self.service.getRawFileContent(
                        repository["full_name"], old_fpath, cancel=cancel, ref=branch
                    )
                    target_sha = self.service.getFileSha(
                        repository["full_name"], target_fpath, cancel=cancel, ref=branch
                    )
                    self.service.createOrUpdateFile(
                        repository["full_name"], target_fpath, data, commit_msg, sha=target_sha, cancel=cancel, branch=branch
                    )

                return total_files

            def folder_success(total_files):
                self._mutating = False
                self._setStatus(_("Folder copied successfully: %s -> %s (%d files)") % (old_path, new_path, total_files))
                self._refreshContents(None, announceLoad=False)

            def folder_failure(message):
                self._mutating = False
                self._setStatus(message)

            runTask(self, folder_task, folder_success, folder_failure, slot="_mutationCancel")

    def _onDeleteContent(self, event=None):
        if self._closing or self._busy or self._child is not None:
            return
        if self._contentLoading or self._contentTimer is not None:
            ui.message(_("Please wait until folder contents finish loading."))
            return
        if self._mutating:
            ui.message(_("Another repository modification is already in progress. Please wait."))
            return
        repository = self._selectedRepository()
        item = self._selectedContent()
        if not repository or not item:
            return
        if item["type"] != "file":
            ui.message(_("Only files can be deleted in this step."))
            return

        filename = item["name"]
        dlg = DeleteConfirmDialog(self, filename, repository["full_name"])
        commit_msg = None
        self._child = dlg
        try:
            if dlg.ShowModal() == wx.ID_OK:
                commit_msg = dlg.getCommitMessage()
        finally:
            dlg.cancelAndClose()
            self._child = None
            if dlg:
                dlg.Destroy()
        if commit_msg is None or self._closing:
            return

        known_sha = item.get("sha")
        self._mutating = True
        self._setStatus(_("Deleting file: %s…") % filename)
        branch = self._currentBranch or None

        def task(cancel, report):
            sha = known_sha or self.service.getFileSha(repository["full_name"], item["path"], cancel=cancel, ref=branch)
            if not sha:
                raise AuthError("not_found")
            return self.service.deleteFile(
                repository["full_name"], item["path"], sha, commit_msg, cancel=cancel, branch=branch
            )

        def success(result):
            self._mutating = False
            self._setStatus(_("File deleted successfully: %s") % filename)
            self._refreshContents(None, announceLoad=False)

        def failure(message):
            self._mutating = False
            self._setStatus(message)

        runTask(self, task, success, failure, slot="_mutationCancel")

    def _onEditContent(self, event=None, targetItem=None, initialText=None, viewerDlg=None):
        if self._closing or self._busy or (self._child is not None and self._child is not viewerDlg):
            return
        if self._contentLoading or self._contentTimer is not None:
            ui.message(_("Please wait until folder contents finish loading."))
            return
        if self._mutating:
            ui.message(_("Another repository modification is already in progress. Please wait."))
            return
        repo = self._selectedRepository()
        if not repo:
            return
        item = targetItem or self._selectedContent()
        if not item or item.get("type") != "file":
            ui.message(_("Please select a file to edit."))
            return
        fileName = item["name"]
        size = item.get("size")
        if isinstance(size, int) and size > 5 * 1024 * 1024:
            self.showMessage(
                _("This file is too large to display directly (limit is 5 MB). You can download it instead."),
                wx.OK | wx.ICON_WARNING,
            )
            return

        def openEditor(text):
            editorDlg = FileEditorDialog(self, fileName, repo["full_name"], text)
            saved_tuple = None
            parent_child = self._child
            self._child = editorDlg
            try:
                if editorDlg.ShowModal() == wx.ID_OK:
                    saved_tuple = editorDlg.getData()
            finally:
                editorDlg.cancelAndClose()
                self._child = parent_child
                editorDlg.Destroy()

            if not saved_tuple or self._closing:
                return
            content_bytes, commit_msg, updated_text = saved_tuple
            known_sha = item.get("sha")
            branch = self._currentBranch or None
            self._mutating = True
            self._setStatus(_("Saving file: %s…") % fileName)

            def task(cancel, report):
                sha = known_sha or self.service.getFileSha(repo["full_name"], item["path"], cancel=cancel, ref=branch)
                return self.service.createOrUpdateFile(
                    repo["full_name"], item["path"], content_bytes, commit_msg, sha=sha, cancel=cancel, branch=branch
                )

            def success(result):
                self._mutating = False
                self._setStatus(_("File updated successfully: %s") % fileName)
                new_sha = (result.get("content") or {}).get("sha") if isinstance(result, dict) else None
                if isinstance(new_sha, str) and new_sha:
                    item["sha"] = new_sha
                if viewerDlg and hasattr(viewerDlg, "setContent"):
                    viewerDlg.setContent(updated_text)
                self._refreshContents(None, announceLoad=False)

            def failure(message):
                self._mutating = False
                self._setStatus(message)

            runTask(self, task, success, failure, slot="_mutationCancel")

        if initialText is not None:
            openEditor(initialText)
        else:
            self._setStatus(_("Loading file content: %s…") % fileName)

            def fetch_success(res):
                self._setStatus("", announce=False)
                if res.get("is_binary"):
                    self.showMessage(_("'%s' is a binary file and cannot be edited as text.") % fileName, wx.OK | wx.ICON_WARNING)
                    return
                openEditor(res.get("text", ""))

            def fetch_failure(msg):
                self._setStatus(msg)

            runTask(
                self,
                lambda cancel, report: self.service.fetchFileText(repo["full_name"], item["path"], cancel, ref=self._currentBranch or None),
                fetch_success,
                fetch_failure,
                slot="_viewCancel",
            )

    def _copyRepository(self, event):
        url = self._repositoryUrl()
        if url and wx.TheClipboard.Open():
            try:
                copied = wx.TheClipboard.SetData(wx.TextDataObject(url))
            finally:
                wx.TheClipboard.Close()
            if copied:
                ui.message(_("Repository address copied."))
                return
        self._setStatus(_("The repository address could not be copied."))

    def _onDisconnect(self, event):
        if self._busy or self._closing:
            return
        result = self.showMessage(
            _("Remove this account and its saved key from this computer? This does not delete the GitHub account or revoke the application's authorization on GitHub."),
            wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION,
        )
        if result != wx.ID_YES or self._closing:
            return
        self._setBusy(True)

        def success(result):
            self._setBusy(False)
            self._clearContents()
            self._repositories.DeleteChildren(self._root)
            self._repositoryRows = []
            self._hasRepositoryData = False
            self._updateAccount()
            self._setStatus(_("The local account connection was removed."))
            self._repositories.SetFocus()

        def failure(message):
            self._setBusy(False)
            self._setStatus(message)

        runTask(self, lambda cancel, report: self.service.disconnect(cancel), success, failure)

    def _onClose(self, event):
        self.shutdown()

    def shutdown(self):
        if self._closing:
            return
        log.info("GitHub main window closed")
        self._closing = True
        self._cancel.set()
        self._cancelContents()
        self._cancelBranches()
        self._cancelDownloads()
        if self._child is not None:
            if hasattr(self._child, "cancelAndClose"):
                self._child.cancelAndClose()
            elif self._child.IsModal():
                self._child.EndModal(wx.ID_CANCEL)
        if self._prompt is not None:
            self._prompt.EndModal(wx.ID_CANCEL)
        self._onClosed()
        self._menu.Destroy()
        self._repositoryContextMenu.Destroy()
        self.Destroy()


class ConnectDialog(MessageMixin, wx.Dialog):
    def __init__(self, parent, service):
        super().__init__(parent, title=_("Connect GitHub account"), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.service = service
        self._closing = False
        self._prompt = None
        self._cancel = threading.Event()
        self.profile = None
        self._userCode = ""
        clientId = service.settings.getClientId()
        self._configuredClientId = clientId
        self._clientId = None
        layout = wx.BoxSizer(wx.VERTICAL)
        explanation = wx.StaticText(self, label=_(
            "Your password stays on GitHub. You will authorize repository access on GitHub's official verification page using a one-time device code."
        ))
        explanation.Wrap(560)
        layout.Add(explanation, 0, wx.EXPAND | wx.ALL, 12)
        if not clientId:
            note = wx.StaticText(self, label=_(
                "One-time setup: register this add-on as an OAuth application on GitHub and enable Device Flow. Enter its public Client ID below, not a client secret or access token."
            ))
            note.Wrap(560)
            layout.Add(note, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
            register = wx.Button(self, label=_("Open application &registration page"))
            register.Bind(wx.EVT_BUTTON, lambda event: openPage("https://github.com/settings/applications/new", self))
            layout.Add(register, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
            layout.Add(wx.StaticText(self, label=_("Client ID (public application identifier)")), 0, wx.LEFT | wx.RIGHT, 12)
            self._clientId = wx.TextCtrl(self)
            self._clientId.SetName(_("Client ID (public application identifier)"))
            layout.Add(self._clientId, 0, wx.EXPAND | wx.ALL, 12)
        self._start = wx.Button(self, label=_("&Start connection"))
        self._start.Bind(wx.EVT_BUTTON, self._onStart)
        layout.Add(self._start, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
        layout.Add(wx.StaticText(self, label=_("Verification code")), 0, wx.LEFT | wx.RIGHT, 12)
        self._code = wx.TextCtrl(self, style=wx.TE_READONLY)
        self._code.SetName(_("Verification code"))
        layout.Add(self._code, 0, wx.EXPAND | wx.ALL, 12)
        row = wx.BoxSizer(wx.HORIZONTAL)
        self._copy = wx.Button(self, label=_("&Copy code"))
        self._browser = wx.Button(self, label=_("&Open GitHub approval page"))
        self._copy.Bind(wx.EVT_BUTTON, self._onCopy)
        self._browser.Bind(wx.EVT_BUTTON, lambda event: openPage(VERIFY_URL, self))
        for button in (self._copy, self._browser):
            button.Disable()
            row.Add(button, 0, wx.RIGHT, 8)
        layout.Add(row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
        layout.Add(wx.StaticText(self, label=_("Connection status")), 0, wx.LEFT | wx.RIGHT, 12)
        self._status = wx.TextCtrl(self, value=_("Ready to connect."), style=wx.TE_READONLY | wx.TE_MULTILINE)
        self._status.SetName(_("Connection status"))
        layout.Add(self._status, 1, wx.EXPAND | wx.ALL, 12)
        cancel = wx.Button(self, wx.ID_CANCEL, _("&Cancel"))
        layout.Add(cancel, 0, wx.ALIGN_RIGHT | wx.RIGHT | wx.BOTTOM, 12)
        self.SetSizer(layout)
        self.SetMinSize((600, 450))
        self.SetSize((680, 700) if not clientId else (640, 480))
        self.CentreOnParent()
        self.Bind(wx.EVT_BUTTON, self._onCancel, id=wx.ID_CANCEL)
        self.Bind(wx.EVT_CLOSE, self._onCancel)
        self._start.SetFocus() if clientId else self._clientId.SetFocus()

    def _setStatus(self, message):
        self._status.ChangeValue(message)
        ui.message(message)

    def _onStart(self, event):
        clientId = self._configuredClientId if self._clientId is None else self._clientId.GetValue().strip()
        try:
            self.service.settings.setClientId(clientId)
        except SettingsError:
            self.showMessage(_("Enter the public Client ID from the GitHub application registration. Do not enter a client secret or access token."), wx.OK | wx.ICON_ERROR)
            if self._clientId is not None:
                self._clientId.SetFocus()
            return
        except OSError as error:
            self._setStatus(errorMessage(error))
            return
        self._start.Disable()
        if self._clientId is not None:
            self._clientId.Disable()
        self._userCode = ""
        self._code.ChangeValue("")
        self._copy.Disable()
        self._browser.Disable()
        self._setStatus(_("Requesting a verification code from GitHub…"))

        def codeReady(code, lifetime):
            self._userCode = code
            self._code.ChangeValue(code)
            self._copy.Enable()
            self._browser.Enable()
            self._code.SetFocus()
            self._code.SelectAll()
            self._setStatus(_("Copy the code and enter it on the GitHub approval page. Waiting for your approval. The code is valid for %s minutes.") % max(1, int(lifetime // 60)))

        def success(profile):
            self.profile = profile
            self._closing = True
            self._cancel.set()
            self.EndModal(wx.ID_OK)

        def failure(message):
            self._start.Enable()
            if self._clientId is not None:
                self._clientId.Enable()
            self._copy.Disable()
            self._browser.Disable()
            self._userCode = ""
            self._code.ChangeValue("")
            self._setStatus(message)
            self._start.SetFocus()

        runTask(self, lambda cancel, report: self.service.connect(clientId, cancel, report), success, failure, codeReady)

    def _onCopy(self, event):
        if not self._userCode:
            return
        if wx.TheClipboard.Open():
            try:
                copied = wx.TheClipboard.SetData(wx.TextDataObject(self._userCode))
            finally:
                wx.TheClipboard.Close()
            if copied:
                ui.message(_("Verification code copied."))
                return
        self.showMessage(_("The code could not be copied. Select the verification code field and press Control+C."), wx.OK | wx.ICON_ERROR)

    def _onCancel(self, event):
        self.cancelAndClose()

    def cancelAndClose(self):
        self._cancel.set()
        if self._closing:
            return
        self._closing = True
        if self._prompt is not None:
            self._prompt.EndModal(wx.ID_CANCEL)
        if self.IsModal():
            self.EndModal(wx.ID_CANCEL)
