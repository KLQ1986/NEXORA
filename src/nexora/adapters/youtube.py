"""Publishing to YouTube and reading a video's figures, through the YouTube Data API v3 with the operator's own OAuth client.

A video is uploaded as private unless the settings say otherwise: making it public stays a deliberate act. Every upload
carries its publication key as a tag, so that when an upload ends without a clear answer the channel can be asked
whether a video with that key exists before anything is sent again.
"""
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from nexora.core.adapter import Adapter, AdapterError, Capability, ErrorCode, Request, Result

FIGURES = {"viewCount": "views", "likeCount": "likes", "commentCount": "comments"}


class YouTubePublisher(Adapter):
    def __init__(self, client_id: str, client_secret: str, refresh_token: str, *, privacy: str = "private", api: str = "https://www.googleapis.com",
                 token_url: str = "https://oauth2.googleapis.com/token"):
        self._client, self._secret, self._refresh = client_id, client_secret, refresh_token
        self._privacy = privacy if privacy in ("private", "unlisted", "public") else "private"
        self._api, self._token_url, self._token, self._expires = api.rstrip("/"), token_url, None, 0.0

    def describe(self) -> Capability:
        return Capability(name="publish.youtube", operations=("publish", "stats"), runs="cloud", supports_reconcile=True)

    def environment(self) -> dict:
        return {"configured": bool(self._client and self._secret and self._refresh), "privacy": self._privacy}

    def _open(self, req: urllib.request.Request, timeout: float):
        try:
            return urllib.request.urlopen(req, timeout=timeout)
        except urllib.error.HTTPError as err:
            detail = err.read().decode(errors="replace")[:200]
            code = (ErrorCode.QUOTA_EXHAUSTED if err.code == 403 and "quota" in detail.lower() else
                    {400: ErrorCode.INVALID_REQUEST, 401: ErrorCode.AUTH, 403: ErrorCode.AUTH, 404: ErrorCode.INVALID_REQUEST, 429: ErrorCode.RATE_LIMITED}.get(err.code, ErrorCode.UNAVAILABLE))
            raise AdapterError(code, f"YouTube answered {err.code}: {detail}") from None
        except TimeoutError:
            raise AdapterError(ErrorCode.TIMEOUT, "YouTube did not answer in time") from None
        except (urllib.error.URLError, ConnectionError) as err:
            raise AdapterError(ErrorCode.UNAVAILABLE, f"YouTube is not reachable: {err}") from None

    def _auth(self) -> dict:
        if not self._token or time.time() >= self._expires - 60:
            body = urllib.parse.urlencode({"client_id": self._client, "client_secret": self._secret, "refresh_token": self._refresh, "grant_type": "refresh_token"}).encode()
            with self._open(urllib.request.Request(self._token_url, data=body), 30) as r:
                answer = json.load(r)
            if not answer.get("access_token"):
                raise AdapterError(ErrorCode.AUTH, "Google gave no access token: the refresh token may have been revoked", retryable=False)
            self._token, self._expires = answer["access_token"], time.time() + float(answer.get("expires_in", 3000))
        return {"authorization": f"Bearer {self._token}"}

    def _get(self, path: str, **query) -> dict:
        with self._open(urllib.request.Request(f"{self._api}{path}?{urllib.parse.urlencode(query)}", headers=self._auth()), 60) as r:
            return json.load(r)

    def _result(self, video_id: str) -> Result:
        return Result(outputs={"url": f"https://youtu.be/{video_id}", "video_id": video_id, "privacy": self._privacy}, external_ref=video_id)

    def reconcile(self, request: Request) -> Result | None:
        """Whether the channel already holds a video uploaded under this publication key."""
        if not request.idempotency_key:
            return None
        found = self._get("/youtube/v3/search", part="id", forMine="true", type="video", q=f'"{request.idempotency_key}"', maxResults=5).get("items", [])
        for item in found:
            video_id = item.get("id", {}).get("videoId")
            tags = (self._get("/youtube/v3/videos", part="snippet", id=video_id).get("items") or [{}])[0].get("snippet", {}).get("tags", []) if video_id else []
            if request.idempotency_key in tags:
                return self._result(video_id)
        return None

    def _stats(self, request: Request) -> Result:
        items = self._get("/youtube/v3/videos", part="statistics", id=request.inputs["external_ref"]).get("items", [])
        if not items:
            raise AdapterError(ErrorCode.INVALID_REQUEST, "this video is no longer on the channel", retryable=False)
        return Result(outputs={"figures": {ours: float(items[0]["statistics"][theirs]) for theirs, ours in FIGURES.items() if theirs in items[0].get("statistics", {})}})

    def submit(self, request: Request) -> Result:
        if request.operation == "stats":
            return self._stats(request)
        if not request.idempotency_key:
            raise AdapterError(ErrorCode.INVALID_REQUEST, "a publication needs an idempotency key")
        folder = Path(request.inputs["folder"])
        video = next((folder / f for f in request.inputs["files"] if f.lower().endswith((".mp4", ".mov"))), None)
        if video is None or not video.is_file():
            raise AdapterError(ErrorCode.MISSING_INPUT, "the package has no video file")
        meta = {"snippet": {"title": request.inputs.get("title", "")[:100], "description": request.inputs.get("description", "")[:4900], "tags": [request.idempotency_key]},
                "status": {"privacyStatus": self._privacy, "selfDeclaredMadeForKids": False, "containsSyntheticMedia": bool(request.inputs.get("synthetic_content"))}}
        start = urllib.request.Request(f"{self._api}/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status", data=json.dumps(meta).encode(),
                                       headers={**self._auth(), "content-type": "application/json; charset=UTF-8", "x-upload-content-type": "video/mp4", "x-upload-content-length": str(video.stat().st_size)})
        with self._open(start, 60) as r:
            session = r.headers.get("location")
        if not session:
            raise AdapterError(ErrorCode.OUTPUT_INVALID, "YouTube opened no upload session")
        put = urllib.request.Request(session, data=video.read_bytes(), method="PUT", headers={**self._auth(), "content-type": "video/mp4"})
        with self._open(put, request.deadline_seconds or 1800) as r:
            made = json.load(r)
        if not made.get("id"):
            raise AdapterError(ErrorCode.OUTPUT_INVALID, "YouTube took the file but returned no video id")
        return self._result(made["id"])
