# Copyright (C) 2026 Mehmet Aykurt <m.aykurt38@gmail.com>
# Bu eklenti Mehmet Aykurt tarafından geliştirilmiştir.
# Lisans: GNU General Public License v2 (GPL-2.0)

"""Account persistence and serialized background session operations."""

import threading
import time
import uuid

from .auth import AuthError, DeviceFlow, checkCancelled
from .commit_ops import getCommitDetail, listCommits
from .downloader import (
    computeReleaseAssetSha256,
    downloadFile,
    downloadFolderAsZip,
    downloadReleaseAsset,
    downloadRepositoryZip,
)
from .file_ops import createOrUpdateFile, deleteFile, getFileSha, getRawFileContent
from .issue_ops import addIssueComment, createIssue, getIssueComments, listIssues, setIssueState
from .notification_ops import fetchResource, listNotifications, markAllNotificationsRead, markNotificationRead
from .pr_ops import createPullRequest, getPullRequest, getPullRequestFiles, listPullRequests, mergePullRequest, setPullRequestState
from .release_ops import createRelease, deleteRelease, listReleases, updateRelease, uploadReleaseAsset
from .repo_ops import createBranch, createRepository, deleteBranch, deleteRepository, listBranches, updateRepository
from .search_ops import forkRepository, isRepoStarred, searchRepositories, starRepository
from .viewer import fetchFileContent


class AccountService:
    def __init__(self, settings, vault, flow=None):
        self.settings = settings
        self.vault = vault
        self.flow = flow or DeviceFlow()
        self._lock = threading.Lock()

    def connect(self, clientId, cancel, onCode):
        bundle = self.flow.authorize(clientId, cancel, onCode)
        profile = self.flow.profile(bundle, cancel)
        with self._lock:
            checkCancelled(cancel)
            previous = self.settings.getAccount()
            reference = uuid.uuid4().hex
            self.vault.write(reference, bundle)
            try:
                self.settings.setAccount({**profile, "credentialId": reference})
            except Exception:
                self.vault.delete(reference)
                raise
            if previous and previous.get("credentialId"):
                try:
                    self.vault.delete(previous["credentialId"])
                except OSError:
                    # The new session is committed. Cleanup can be retried by a maintainer;
                    # do not report a successful sign-in as failed or expose credentials.
                    pass
        return profile

    def restore(self, cancel):
        with self._lock:
            checkCancelled(cancel)
            account = self.settings.getAccount()
            if not account or not account.get("credentialId"):
                raise AuthError("reauthorize")
            reference = account["credentialId"]
            bundle = self.vault.read(reference)
            if not bundle:
                raise AuthError("reauthorize")
            if not bundle.get("clientId") and hasattr(self.settings, "getClientId"):
                cfg_client_id = self.settings.getClientId()
                if cfg_client_id:
                    bundle = {**bundle, "clientId": cfg_client_id}
            refreshed = False
            if bundle.get("expiresAt", time.time() + 120) <= time.time() + 60:
                bundle = self.flow.refresh(bundle)
                # A refresh rotates tokens. Persist it even if the window was closed
                # during the request, before checking cancellation again.
                self.vault.write(reference, bundle)
                refreshed = True
            try:
                profile = self.flow.profile(bundle, cancel)
            except AuthError as error:
                if error.code != "unauthorized" or refreshed or not bundle.get("refresh_token"):
                    raise
                bundle = self.flow.refresh(bundle)
                self.vault.write(reference, bundle)
                profile = self.flow.profile(bundle, cancel)
            if account.get("id") is not None and profile["id"] != account["id"]:
                raise AuthError("account_mismatch")
            checkCancelled(cancel)
            self.settings.setAccount({**profile, "credentialId": reference})
            return profile

    def _getValidBundle(self, cancel=None, forceRefresh=False):
        """Reads and refreshes the token bundle under lock without holding lock during long network I/O."""
        with self._lock:
            checkCancelled(cancel)
            account = self.settings.getAccount()
            if not account or not account.get("credentialId"):
                raise AuthError("reauthorize")
            reference = account["credentialId"]
            bundle = self.vault.read(reference)
            if not bundle or not bundle.get("access_token"):
                raise AuthError("reauthorize")
            if not bundle.get("clientId") and hasattr(self.settings, "getClientId"):
                cfg_client_id = self.settings.getClientId()
                if cfg_client_id:
                    bundle = {**bundle, "clientId": cfg_client_id}
            needs_refresh = forceRefresh or (
                bundle.get("expiresAt", time.time() + 120) <= time.time() + 60
            )
            if needs_refresh:
                bundle = self.flow.refresh(bundle)
                self.vault.write(reference, bundle)
            return dict(bundle)

    def _runWithToken(self, cancel, func):
        bundle = self._getValidBundle(cancel=cancel)
        try:
            return func(bundle)
        except AuthError as error:
            if error.code != "unauthorized" or not bundle.get("refresh_token"):
                raise
            refreshed = self._getValidBundle(cancel=cancel, forceRefresh=True)
            return func(refreshed)

    def loadRepositories(self, cancel):
        profile = self.restore(cancel)
        bundle = self._getValidBundle(cancel=cancel)
        repositories = self.flow.repositories(bundle, cancel)
        checkCancelled(cancel)
        return {"profile": profile, "repositories": repositories}

    def loadContents(self, fullName, path, cancel, ref=None):
        return self._runWithToken(
            cancel,
            lambda bundle: self.flow.directoryContents(bundle, fullName, path, cancel, ref=ref),
        )

    def disconnect(self, cancel):
        with self._lock:
            checkCancelled(cancel)
            account = self.settings.getAccount()
            if account and account.get("credentialId"):
                self.vault.delete(account["credentialId"])
            self.settings.setAccount(None)

    def downloadRepository(self, fullName, targetPath, cancel, ref=None):
        return self._runWithToken(
            cancel,
            lambda bundle: downloadRepositoryZip(bundle["access_token"], fullName, targetPath, cancel, ref=ref),
        )

    def downloadContentFile(self, fullName, filePath, targetPath, cancel, ref=None):
        return self._runWithToken(
            cancel,
            lambda bundle: downloadFile(bundle["access_token"], fullName, filePath, targetPath, cancel, ref=ref),
        )

    def downloadReleaseAsset(self, fullName, assetId, targetPath, downloadUrl="", cancel=None):
        return self._runWithToken(
            cancel,
            lambda bundle: downloadReleaseAsset(
                bundle["access_token"],
                fullName,
                assetId,
                targetPath,
                download_url=downloadUrl,
                cancel=cancel,
            ),
        )

    def computeReleaseAssetSha256(self, fullName, assetId, downloadUrl="", cancel=None):
        return self._runWithToken(
            cancel,
            lambda bundle: computeReleaseAssetSha256(
                bundle["access_token"],
                fullName,
                assetId,
                download_url=downloadUrl,
                cancel=cancel,
            ),
        )

    def downloadContentFolder(self, fullName, folderPath, targetZipPath, cancel, ref=None):
        return self._runWithToken(
            cancel,
            lambda bundle: downloadFolderAsZip(self.flow, bundle, fullName, folderPath, targetZipPath, cancel, ref=ref),
        )

    def fetchFileText(self, fullName, filePath, cancel, ref=None):
        return self._runWithToken(
            cancel,
            lambda bundle: fetchFileContent(bundle["access_token"], fullName, filePath, cancel, ref=ref),
        )

    def createOrUpdateFile(self, fullName, filePath, contentBytes, commitMessage, sha=None, cancel=None, branch=None):
        return self._runWithToken(
            cancel,
            lambda bundle: createOrUpdateFile(
                bundle["access_token"],
                fullName,
                filePath,
                contentBytes,
                commitMessage,
                sha=sha,
                cancel=cancel,
                branch=branch,
            ),
        )

    def deleteFile(self, fullName, filePath, sha, commitMessage, cancel=None, branch=None):
        return self._runWithToken(
            cancel,
            lambda bundle: deleteFile(
                bundle["access_token"],
                fullName,
                filePath,
                sha,
                commitMessage,
                cancel=cancel,
                branch=branch,
            ),
        )

    def getRawFileContent(self, fullName, filePath, cancel=None, ref=None):
        return self._runWithToken(
            cancel,
            lambda bundle: getRawFileContent(bundle["access_token"], fullName, filePath, cancel=cancel, ref=ref),
        )

    def getFileSha(self, fullName, filePath, cancel=None, ref=None):
        return self._runWithToken(
            cancel,
            lambda bundle: getFileSha(bundle["access_token"], fullName, filePath, cancel=cancel, ref=ref),
        )

    def loadBranches(self, fullName, cancel=None):
        return self._runWithToken(
            cancel,
            lambda bundle: listBranches(bundle["access_token"], fullName, cancel=cancel),
        )

    def createRepository(self, name, description="", private=False, auto_init=True, license_template="", cancel=None):
        return self._runWithToken(
            cancel,
            lambda bundle: createRepository(
                bundle["access_token"],
                name,
                description=description,
                private=private,
                auto_init=auto_init,
                license_template=license_template,
                cancel=cancel,
            ),
        )

    def loadIssues(self, fullName, state="open", cancel=None):
        return self._runWithToken(
            cancel,
            lambda bundle: listIssues(bundle["access_token"], fullName, state=state, cancel=cancel),
        )

    def loadIssueComments(self, fullName, issueNumber, cancel=None):
        return self._runWithToken(
            cancel,
            lambda bundle: getIssueComments(bundle["access_token"], fullName, issueNumber, cancel=cancel),
        )

    def createIssue(self, fullName, title, body="", cancel=None):
        return self._runWithToken(
            cancel,
            lambda bundle: createIssue(bundle["access_token"], fullName, title, body=body, cancel=cancel),
        )

    def addIssueComment(self, fullName, issueNumber, body, cancel=None):
        return self._runWithToken(
            cancel,
            lambda bundle: addIssueComment(bundle["access_token"], fullName, issueNumber, body, cancel=cancel),
        )

    def setIssueState(self, fullName, issueNumber, state="closed", cancel=None):
        return self._runWithToken(
            cancel,
            lambda bundle: setIssueState(bundle["access_token"], fullName, issueNumber, state=state, cancel=cancel),
        )

    def loadReleases(self, fullName, cancel=None):
        return self._runWithToken(
            cancel,
            lambda bundle: listReleases(bundle["access_token"], fullName, cancel=cancel),
        )

    def createRelease(self, fullName, tag, name="", body="", target_commitish=None, prerelease=False, asset_path=None, cancel=None):
        import os

        def _do_create(bundle):
            rel = createRelease(
                bundle["access_token"],
                fullName,
                tag,
                name=name,
                body=body,
                target_commitish=target_commitish,
                prerelease=prerelease,
                cancel=cancel,
            )
            if asset_path and os.path.isfile(asset_path):
                try:
                    uploadReleaseAsset(
                        bundle["access_token"],
                        fullName,
                        rel["id"],
                        asset_path,
                        cancel=cancel,
                    )
                except Exception as exc:
                    err = AuthError("release_asset_failed")
                    err.release = rel
                    raise err from exc
            return rel

        return self._runWithToken(cancel, _do_create)

    def getAccessToken(self, cancel=None):
        try:
            bundle = self._getValidBundle(cancel=cancel)
            return bundle.get("access_token")
        except Exception:
            return None

    def fetchNotificationResource(self, api_url, cancel=None):
        return self._runWithToken(
            cancel,
            lambda bundle: fetchResource(bundle["access_token"], api_url, cancel=cancel),
        )

    def loadNotifications(self, all_notifications=False, cancel=None):
        return self._runWithToken(
            cancel,
            lambda bundle: listNotifications(bundle["access_token"], all_notifications=all_notifications, cancel=cancel),
        )

    def markNotificationRead(self, thread_id, cancel=None):
        return self._runWithToken(
            cancel,
            lambda bundle: markNotificationRead(bundle["access_token"], thread_id, cancel=cancel),
        )

    def markAllNotificationsRead(self, cancel=None):
        return self._runWithToken(
            cancel,
            lambda bundle: markAllNotificationsRead(bundle["access_token"], cancel=cancel),
        )

    # Branch operations (Stage 1)
    def createBranch(self, fullName, newBranch, sourceBranch=None, cancel=None, **kwargs):
        effective_source = sourceBranch if sourceBranch is not None else kwargs.get("source_branch")
        return self._runWithToken(
            cancel,
            lambda bundle: createBranch(bundle["access_token"], fullName, newBranch, effective_source, cancel=cancel),
        )

    def deleteBranch(self, fullName, branchName, cancel=None):
        return self._runWithToken(
            cancel,
            lambda bundle: deleteBranch(bundle["access_token"], fullName, branchName, cancel=cancel),
        )

    # Repository management (Stage 2)
    def updateRepository(self, fullName, description=None, private=None, archived=None, cancel=None):
        return self._runWithToken(
            cancel,
            lambda bundle: updateRepository(
                bundle["access_token"], fullName, description=description, private=private, archived=archived, cancel=cancel
            ),
        )

    def deleteRepository(self, fullName, cancel=None):
        return self._runWithToken(
            cancel,
            lambda bundle: deleteRepository(bundle["access_token"], fullName, cancel=cancel),
        )

    # Commits (Stage 2)
    def loadCommits(self, fullName, branch=None, page=1, cancel=None):
        return self._runWithToken(
            cancel,
            lambda bundle: listCommits(bundle["access_token"], fullName, sha=branch, page=page, cancel=cancel),
        )

    def loadCommitDetail(self, fullName, commitSha, cancel=None):
        return self._runWithToken(
            cancel,
            lambda bundle: getCommitDetail(bundle["access_token"], fullName, commitSha, cancel=cancel),
        )

    # Release editing and deleting (Stage 2)
    def updateRelease(self, fullName, releaseId, tag_name=None, name=None, body=None, draft=None, prerelease=None, cancel=None):
        return self._runWithToken(
            cancel,
            lambda bundle: updateRelease(
                bundle["access_token"],
                fullName,
                releaseId,
                tag_name=tag_name,
                name=name,
                body=body,
                draft=draft,
                prerelease=prerelease,
                cancel=cancel,
            ),
        )

    def deleteRelease(self, fullName, releaseId, cancel=None):
        return self._runWithToken(
            cancel,
            lambda bundle: deleteRelease(bundle["access_token"], fullName, releaseId, cancel=cancel),
        )

    # Pull Requests (Stage 3)
    def loadPullRequests(self, fullName, state="open", cancel=None):
        return self._runWithToken(
            cancel,
            lambda bundle: listPullRequests(bundle["access_token"], fullName, state=state, cancel=cancel),
        )

    def getPullRequest(self, fullName, number, cancel=None):
        return self._runWithToken(
            cancel,
            lambda bundle: getPullRequest(bundle["access_token"], fullName, number, cancel=cancel),
        )

    def loadPullRequestFiles(self, fullName, number, cancel=None):
        return self._runWithToken(
            cancel,
            lambda bundle: getPullRequestFiles(bundle["access_token"], fullName, number, cancel=cancel),
        )

    def createPullRequest(self, fullName, title, head, base, body="", cancel=None):
        return self._runWithToken(
            cancel,
            lambda bundle: createPullRequest(bundle["access_token"], fullName, title, head, base, body=body, cancel=cancel),
        )

    def mergePullRequest(self, fullName, number, commit_title="", commit_message="", merge_method="merge", cancel=None):
        return self._runWithToken(
            cancel,
            lambda bundle: mergePullRequest(
                bundle["access_token"], fullName, number, commit_title=commit_title, commit_message=commit_message, merge_method=merge_method, cancel=cancel
            ),
        )

    def setPullRequestState(self, fullName, number, state="closed", cancel=None):
        return self._runWithToken(
            cancel,
            lambda bundle: setPullRequestState(bundle["access_token"], fullName, number, state=state, cancel=cancel),
        )

    # Global search, star, and fork (Stage 4)
    def searchGlobalRepositories(self, query, sort="stars", order="desc", cancel=None):
        return self._runWithToken(
            cancel,
            lambda bundle: searchRepositories(bundle["access_token"], query, sort=sort, order=order, cancel=cancel),
        )

    def isRepoStarred(self, fullName, cancel=None):
        return self._runWithToken(
            cancel,
            lambda bundle: isRepoStarred(bundle["access_token"], fullName, cancel=cancel),
        )

    def starRepository(self, fullName, star=True, cancel=None):
        return self._runWithToken(
            cancel,
            lambda bundle: starRepository(bundle["access_token"], fullName, star=star, cancel=cancel),
        )

    def forkRepository(self, fullName, cancel=None):
        return self._runWithToken(
            cancel,
            lambda bundle: forkRepository(bundle["access_token"], fullName, cancel=cancel),
        )




