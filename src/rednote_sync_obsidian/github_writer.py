from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import httpx

from .config import Settings


@dataclass(frozen=True)
class GitHubWriter:
    token: str
    repo: str
    branch: str = "main"
    api_base: str = "https://api.github.com"
    timeout_seconds: float = 20.0

    @classmethod
    def from_settings(cls, settings: Settings) -> "GitHubWriter":
        return cls(
            token=settings.github_token,
            repo=settings.github_repo,
            branch=settings.github_branch,
            api_base=settings.github_api_base.rstrip("/"),
        )

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "rednote-sync-obsidian",
        }

    def _contents_url(self, path: str) -> str:
        safe_path = quote(path.lstrip("/"), safe="/")
        return f"{self.api_base}/repos/{self.repo}/contents/{safe_path}"

    def _raise_github_error(self, action: str, path: str, response: httpx.Response) -> None:
        hint = ""
        if response.status_code == 403 and "Resource not accessible by personal access token" in response.text:
            hint = (
                " Hint: the token cannot access this repository contents endpoint. "
                "For a fine-grained PAT, select the exact GITHUB_REPO and set Repository permissions -> "
                "Contents -> Read and write. If the repository belongs to an organization, approve/authorize "
                "the token for that organization."
            )
        elif response.status_code == 404:
            hint = " Hint: verify GITHUB_REPO owner/name and GITHUB_BRANCH. Private repos also need an authorized token."
        elif response.status_code == 409:
            hint = " Hint: verify the target branch exists and is not blocked by branch protection for this token."
        raise RuntimeError(f"GitHub {action} failed for {path}: {response.status_code} {response.text}{hint}")

    def get_file_sha(self, path: str) -> str | None:
        with httpx.Client(timeout=self.timeout_seconds) as client:
            response = client.get(
                self._contents_url(path),
                headers=self._headers,
                params={"ref": self.branch},
            )
        if response.status_code == 404:
            return None
        if response.status_code >= 400:
            self._raise_github_error("read", path, response)
        data = response.json()
        if isinstance(data, dict) and data.get("type") == "file":
            return str(data.get("sha"))
        raise RuntimeError(f"GitHub path exists but is not a file: {path}")

    def _put_file_once(self, *, path: str, payload: dict[str, Any]) -> httpx.Response:
        with httpx.Client(timeout=self.timeout_seconds) as client:
            return client.put(self._contents_url(path), json=payload, headers=self._headers)

    def put_file(self, *, path: str, content_bytes: bytes, message: str, overwrite: bool = True) -> dict[str, Any]:
        encoded = base64.b64encode(content_bytes).decode("utf-8")
        payload: dict[str, Any] = {
            "message": message,
            "content": encoded,
            "branch": self.branch,
        }

        # Optimistic create first. This avoids a pre-write GET for new notes/assets.
        # If the file already exists, GitHub returns a validation error and we retry
        # with the current SHA when overwrite=True.
        response = self._put_file_once(path=path, payload=payload)
        if response.status_code in (200, 201):
            return response.json()

        if overwrite and response.status_code == 422 and "sha" in response.text.lower():
            sha = self.get_file_sha(path)
            if sha:
                retry_payload = dict(payload)
                retry_payload["sha"] = sha
                retry = self._put_file_once(path=path, payload=retry_payload)
                if retry.status_code in (200, 201):
                    return retry.json()
                self._raise_github_error("write", path, retry)

        self._raise_github_error("write", path, response)
