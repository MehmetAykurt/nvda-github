# Copyright (C) 2026 Mehmet Aykurt <m.aykurt38@gmail.com>
# Bu eklenti Mehmet Aykurt tarafından geliştirilmiştir.
# Lisans: GNU General Public License v2 (GPL-2.0)

"""NVDA entry point for the GitHub add-on."""

import addonHandler
import globalPluginHandler
import globalVars
import gui
import wx
from logHandler import log
from scriptHandler import script

addonHandler.initTranslation()

from .dialogs import GitHubDialog
from .accounts import AccountService
from .credentials import CredentialStore
from .settings import SettingsError, SettingsStore


class GlobalPlugin(globalPluginHandler.GlobalPlugin):
    scriptCategory = "GitHub"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._dialog = None
        self._service = None
        self._terminated = False
        self._menuItem = None
        if globalVars.appArgs.secure:
            return
        self._menuItem = gui.mainFrame.sysTrayIcon.toolsMenu.Append(wx.ID_ANY, "GitHub…")
        gui.mainFrame.sysTrayIcon.Bind(wx.EVT_MENU, self._onMenu, self._menuItem)

    @script(
        description=_("Open GitHub"),
        gesture="kb:NVDA+g",
        speakOnDemand=True,
    )
    def script_openGitHub(self, gesture):
        self._requestOpen()

    def _onMenu(self, event):
        self._requestOpen()

    def _requestOpen(self):
        if not self._terminated and not globalVars.appArgs.secure:
            wx.CallAfter(self._openWindow)

    def _openWindow(self):
        if self._terminated or globalVars.appArgs.secure:
            return
        if self._dialog is not None:
            self._dialog.activate()
            return
        try:
            settings = SettingsStore(globalVars.appArgs.configPath)
            hasAccounts = settings.hasAccounts()
            if self._service is None:
                self._service = AccountService(settings, CredentialStore(globalVars.appArgs.configPath))
            else:
                self._service.settings = settings
        except (OSError, SettingsError):
            log.error("GitHub: could not read settings", exc_info=True)
            gui.messageBox(
                _("GitHub settings could not be read. Check the github folder in your NVDA user configuration. Existing settings have not been changed."),
                "GitHub",
                wx.OK | wx.ICON_ERROR,
            )
            return
        gui.mainFrame.prePopup()
        try:
            self._dialog = GitHubDialog(gui.mainFrame, self._onDialogClosed, self._service)
            self._dialog.Show()
        finally:
            gui.mainFrame.postPopup()
        # The modeless dialog must be activated after hidden-owner cleanup.
        log.info("GitHub main window shown")
        wx.CallAfter(self._finishOpening, self._dialog, hasAccounts)

    def _finishOpening(self, dialog, hasAccounts):
        if self._terminated or self._dialog is not dialog or dialog._closing:
            return
        dialog.activate()
        if not hasAccounts:
            wx.CallAfter(dialog.offerAccountSetup)
        else:
            wx.CallAfter(dialog.restoreAccount)

    def _onDialogClosed(self):
        self._dialog = None

    def terminate(self):
        self._terminated = True
        if self._menuItem is not None:
            try:
                tray = getattr(gui.mainFrame, "sysTrayIcon", None)
                if tray is not None and hasattr(tray, "toolsMenu") and tray.toolsMenu is not None:
                    tray.Unbind(wx.EVT_MENU, handler=self._onMenu, source=self._menuItem)
                    tray.toolsMenu.DestroyItem(self._menuItem)
            except Exception:
                pass
            self._menuItem = None
        if self._dialog is not None:
            try:
                self._dialog.shutdown()
            except Exception:
                pass
            self._dialog = None
        super().terminate()
