# Copyright (C) 2026 Mehmet Aykurt <m.aykurt38@gmail.com>
# Bu eklenti Mehmet Aykurt tarafından geliştirilmiştir.
# Lisans: GNU General Public License v2 (GPL-2.0)

"""Localized user-facing error message formatting for GitHub operations."""

import addonHandler
addonHandler.initTranslation()

from .credentials import CredentialError
from .settings import SettingsError


def errorMessage(error):
    """Formats an exception into a safe, localized, screen-reader-friendly message."""
    if isinstance(error, CredentialError):
        return _("Windows could not read or save the account key. No key will be saved in a plain text file.")
    if isinstance(error, (OSError, SettingsError)):
        return _("GitHub settings could not be saved or read. Check access to the github configuration folder.")
    messages = {
        "not_found": _("The repository or folder was not found, or your account does not have access."),
        "not_directory": _("This item is not a folder. Refresh its parent folder."),
        "directory_limit": _("This folder reaches GitHub's 1,000-item listing limit. A complete listing is not supported in this step."),
        "file_too_large": _("This file is too large to display directly (limit is 5 MB). You can download it instead."),
        "upload_too_large": _("This file is too large to upload through the Contents API (limit is 50 MB)."),
        "release_asset_failed": _("Release was created on GitHub, but uploading the package file failed."),
        "conflict": _("A file with this name already exists or has been modified on GitHub."),
        "branch_exists": _("A branch with this name already exists or the branch name is invalid."),
        "pr_exists_or_invalid": _("A pull request may already exist between these branches, or there are no changes to merge."),
        "merge_not_allowed": _("This pull request cannot be merged. It may have conflicts or require approval."),
        "merge_conflict": _("This pull request cannot be merged due to merge conflicts."),
        "release_tag_exists": _("A release with this tag already exists or the version tag is invalid."),
        "empty_repository": _("This repository is empty."),
        "authorization_failed": _("Authorization on GitHub failed. Start the connection again."),
        "forbidden": _("Your account does not have permission for this operation. Reconnecting with the required permissions may be required."),
        "invalid_search_query": _("The search query is invalid. Check the search keywords and try again."),
        "repo_exists_or_invalid": _("A repository with this name already exists, or the name contains invalid characters."),
        "invalid_repo_name": _("The repository name is invalid."),
        "network": _("Could not reach GitHub. Check your internet connection and try again."),
        "limited": _("GitHub temporarily limited this request. Wait a while and try again."),
        "server_error": _("GitHub could not complete the request. Try again later."),
        "invalid_response": _("GitHub returned an unexpected response. The operation could not be completed."),
        "expired_token": _("The verification code expired. Start the connection again for a new code."),
        "access_denied": _("The connection was declined on GitHub. You can try again."),
        "cancelled": _("Connection cancelled."),
        "device_flow_disabled": _("Enable Device Flow in the GitHub application's settings before connecting."),
        "incorrect_client_credentials": _("GitHub did not recognize the application ID. Check the Client ID and try again."),
        "unauthorized": _("The saved session is no longer valid. Connect your account again."),
        "reauthorize": _("The saved session is missing or expired. Connect your account again."),
        "bad_refresh_token": _("The session could not be renewed. Connect your account again."),
        "account_mismatch": _("The saved session belongs to a different account. Remove the local connection and sign in again."),
    }
    return messages.get(getattr(error, "code", ""), _("The connection could not be completed. Try again."))
