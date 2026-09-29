from __future__ import annotations

import json
import os
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


LINKEDIN_UGC_POSTS_URL = "https://api.linkedin.com/v2/ugcPosts"


@dataclass(frozen=True)
class LinkedInPublishResult:
    ok: bool
    status_code: int | None
    post_urn: str
    response_body: str
    error: str


class LinkedInClient:
    """Small official-API client for member text posts."""

    def __init__(self, access_token: str | None = None, author_urn: str | None = None) -> None:
        self.access_token = access_token or os.getenv("LINKEDIN_ACCESS_TOKEN", "")
        self.author_urn = author_urn or os.getenv("LINKEDIN_AUTHOR_URN", "")

    def validate_config(self) -> list[str]:
        errors: list[str] = []
        if not self.access_token:
            errors.append("LINKEDIN_ACCESS_TOKEN is missing.")
        if not self.author_urn:
            errors.append("LINKEDIN_AUTHOR_URN is missing.")
        if self.author_urn and not self.author_urn.startswith("urn:li:person:"):
            errors.append("LINKEDIN_AUTHOR_URN must look like urn:li:person:{id} for personal profile posting.")
        return errors

    def create_text_share(self, text: str) -> LinkedInPublishResult:
        config_errors = self.validate_config()
        if config_errors:
            return LinkedInPublishResult(
                ok=False,
                status_code=None,
                post_urn="",
                response_body="",
                error=" ".join(config_errors),
            )

        payload = {
            "author": self.author_urn,
            "lifecycleState": "PUBLISHED",
            "specificContent": {
                "com.linkedin.ugc.ShareContent": {
                    "shareCommentary": {"text": text},
                    "shareMediaCategory": "NONE",
                }
            },
            "visibility": {
                "com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC",
            },
        }

        request = Request(
            LINKEDIN_UGC_POSTS_URL,
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={
                "Authorization": f"Bearer {self.access_token}",
                "Content-Type": "application/json",
                "X-Restli-Protocol-Version": "2.0.0",
            },
        )

        try:
            with urlopen(request, timeout=30) as response:
                body = response.read().decode("utf-8")
                post_urn = response.headers.get("x-restli-id", "")
                return LinkedInPublishResult(
                    ok=200 <= response.status < 300,
                    status_code=response.status,
                    post_urn=post_urn,
                    response_body=body,
                    error="",
                )
        except HTTPError as exc:
            return LinkedInPublishResult(
                ok=False,
                status_code=exc.code,
                post_urn="",
                response_body=exc.read().decode("utf-8", errors="replace"),
                error=str(exc),
            )
        except URLError as exc:
            return LinkedInPublishResult(
                ok=False,
                status_code=None,
                post_urn="",
                response_body="",
                error=str(exc.reason),
            )

