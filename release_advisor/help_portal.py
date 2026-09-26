"""Client for help.salesforce.com: find the latest release and export its release notes PDF.

This does exactly what the site's own "PDF" button does, over plain HTTPS as an anonymous
(guest) user:

  1. Help_UserReleaseHelper.getData                   -> {"release-notes": "264.0.0", ...}   (latest release)
  2. Help_ArticleDataController.getJobTokenWithLanguage -> job token for the PDF export
  3. Help_ArticleDataController.getDownloadToken         -> polled until {"status": "JobDone", "download_token": ...}
  4. Help_ArticleDataController.getPdfDownloadEndpoint   -> URL of the generated PDF
  5. GET that URL                                        -> the official release notes PDF
     (tokens are single-use; an interrupted transfer repeats steps 3-5 for the same job)

These are the site's internal endpoints, not a published API, so failures raise HelpPortalError
with a clear message and the caller can fall back to a manually downloaded PDF.
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Callable
from urllib.parse import unquote, urlparse

import requests

log = logging.getLogger(__name__)

BASE_URL = "https://help.salesforce.com"
RN_PAGE = "/s/articleView?id=release-notes.salesforce_release_notes.htm&type=5&language=en_US"
# The PDF export is served by Salesforce's documentation delivery platform; the URL is always
# handed out by help.salesforce.com itself (step 4), never constructed by us.
TRUSTED_DOWNLOAD_HOSTS = ("salesforce.com", "zoominsoftware.io")

POLL_SECONDS = 10
JOB_TIMEOUT_SECONDS = 15 * 60
MAX_PDF_BYTES = 200 * 1024 * 1024
DOWNLOAD_ATTEMPTS = 4


class HelpPortalError(RuntimeError):
    pass


class HelpPortalClient:
    def __init__(self, session: requests.Session | None = None, sleep: Callable[[float], None] = time.sleep):
        self._session = session or requests.Session()
        self._session.headers.setdefault("User-Agent", "Mozilla/5.0 (agentforce-release-advisor)")
        self._sleep = sleep
        self._context: str | None = None
        self._req = 0

    # ---- Aura plumbing -----------------------------------------------------------------------

    def _aura_context(self) -> str:
        if self._context is None:
            try:
                html = self._session.get(BASE_URL + RN_PAGE, timeout=60).text
            except requests.RequestException as exc:
                raise HelpPortalError(f"Cannot reach help.salesforce.com: {exc}") from exc
            decoded = unquote(html)
            fwuid = re.search(r'"fwuid":"([^"]+)"', decoded)
            loaded = re.search(r'"loaded":(\{[^}]*\})', decoded)
            if not fwuid or not loaded:
                raise HelpPortalError("help.salesforce.com page layout changed; cannot initialise the site client.")
            self._context = json.dumps(
                {
                    "mode": "PROD",
                    "fwuid": fwuid.group(1),
                    "app": "siteforce:communityApp",
                    "loaded": json.loads(loaded.group(1)),
                    "dn": [],
                    "globals": {},
                    "uad": False,
                }
            )
        return self._context

    def _apex(self, classname: str, method: str, params: dict | None = None):
        self._req += 1
        message = {
            "actions": [
                {
                    "id": f"{self._req};a",
                    "descriptor": "aura://ApexActionController/ACTION$execute",
                    "callingDescriptor": "UNKNOWN",
                    "params": {
                        "namespace": "",
                        "classname": classname,
                        "method": method,
                        "params": params or {},
                        "cacheable": False,
                        "isContinuation": False,
                    },
                }
            ]
        }
        try:
            resp = self._session.post(
                f"{BASE_URL}/s/sfsites/aura?r={self._req}&aura.ApexAction.execute=1",
                data={
                    "message": json.dumps(message),
                    "aura.context": self._aura_context(),
                    "aura.pageURI": RN_PAGE,
                    "aura.token": "null",
                },
                timeout=60,
            )
        except requests.RequestException as exc:
            raise HelpPortalError(f"help.salesforce.com request failed: {exc}") from exc
        body = resp.text.removeprefix("*/")
        try:
            action = json.loads(body)["actions"][0]
        except (ValueError, KeyError, IndexError) as exc:
            if "clientOutOfSync" in body or "invalidSession" in body:
                self._context = None  # site redeployed; re-read fwuid next time
            raise HelpPortalError(f"Unexpected response from help.salesforce.com ({classname}.{method}).") from exc
        if action.get("state") != "SUCCESS":
            raise HelpPortalError(f"{classname}.{method} failed: {action.get('error')}")
        value = action.get("returnValue")
        return value.get("returnValue") if isinstance(value, dict) and "returnValue" in value else value

    # ---- public API --------------------------------------------------------------------------

    def latest_release_number(self) -> int:
        """Salesforce's current release number for release notes, e.g. 264 (= Winter '27)."""
        data = self._apex("Help_UserReleaseHelper", "getData") or {}
        version = str(data.get("release-notes", ""))
        if not re.match(r"^\d+", version):
            raise HelpPortalError(f"help.salesforce.com did not report a release-notes version (got {data!r}).")
        return int(version.split(".")[0])

    def download_release_notes_pdf(
        self, release_number: int, progress: Callable[[str], None] | None = None
    ) -> bytes:
        progress = progress or (lambda _m: None)
        bundle = f"tdta-release-notes-salesforce_release_notes-{release_number}-0-0-production"
        job = self._apex("Help_ArticleDataController", "getJobTokenWithLanguage", {"bundleId": bundle, "language": "en-US"})
        if not job:
            raise HelpPortalError(f"help.salesforce.com has no release notes PDF for release {release_number}.")

        progress("Salesforce is generating the release notes PDF (a few minutes, first time only)")
        last_error: Exception | None = None
        # Download tokens are single-use and the file server does not support resuming, so an
        # interrupted transfer is retried with a fresh token for the same (already generated) job.
        for attempt in range(DOWNLOAD_ATTEMPTS):
            token = self._wait_for_download_token(job)
            url = self._apex(
                "Help_ArticleDataController",
                "getPdfDownloadEndpoint",
                {"jobToken": job, "downloadToken": token},
            )
            _check_download_url(str(url))
            progress("Downloading the release notes PDF" + (f" (retry {attempt})" if attempt else ""))
            try:
                return self._download(str(url))
            except (requests.RequestException, HelpPortalError) as exc:
                last_error = exc
                log.warning("PDF download attempt %d failed: %s", attempt + 1, exc)
                self._sleep(3)
        raise HelpPortalError(f"PDF download kept failing ({last_error}); try again later.")

    def _wait_for_download_token(self, job: str) -> str:
        started = time.monotonic()
        while True:
            status = self._apex("Help_ArticleDataController", "getDownloadToken", {"jobToken": job}) or {}
            if status.get("status") == "JobDone" and status.get("download_token"):
                return str(status["download_token"])
            if status.get("status") not in (None, "JobInQueue", "JobInProgress", "JobDone"):
                raise HelpPortalError(f"PDF export failed: {status}")
            if time.monotonic() - started > JOB_TIMEOUT_SECONDS:
                raise HelpPortalError("Timed out waiting for help.salesforce.com to generate the PDF.")
            self._sleep(POLL_SECONDS)

    def _download(self, url: str) -> bytes:
        buf = bytearray()
        with self._session.get(url, stream=True, timeout=300) as resp:
            if resp.status_code != 200:
                raise HelpPortalError(f"PDF download failed: HTTP {resp.status_code}")
            for chunk in resp.iter_content(1 << 16):
                buf.extend(chunk)
                if len(buf) > MAX_PDF_BYTES:
                    raise HelpPortalError("PDF is unexpectedly large; aborting.")
        data = bytes(buf)
        if not data.startswith(b"%PDF"):
            raise HelpPortalError("help.salesforce.com did not return a PDF.")
        return data


def _check_download_url(url: str) -> None:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not any(host == h or host.endswith("." + h) for h in TRUSTED_DOWNLOAD_HOSTS):
        raise HelpPortalError(f"Unexpected PDF download location: {url}")
