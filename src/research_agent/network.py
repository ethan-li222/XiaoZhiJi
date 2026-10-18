import asyncio
import base64
import hashlib
import json
import time
from urllib.parse import urlparse

import httpx


def public_url(url):
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("需要有效的 HTTP(S) URL")
    if parsed.username or parsed.password:
        raise ValueError("URL 中不能包含凭据")
    return url


class Network:
    def __init__(self, settings, store, client=None):
        self.settings, self.store = settings, store
        self.client = client
        self.last = {}
        self.requests = 0
        self.warnings = []

    async def get(
        self, url, params=None, headers=None, *, json_response=True, binary=False, interval=0.2
    ):
        public_url(url)
        params = params or {}
        key = hashlib.sha256(
            json.dumps([url, params, headers or {}, json_response, binary], sort_keys=True).encode()
        ).hexdigest()
        with self.store.connect() as db:
            cached = db.execute("SELECT body,expires FROM cache WHERE key=?", (key,)).fetchone()
        if cached and cached["expires"] > time.time():
            value = json.loads(cached["body"])
            return base64.b64decode(value) if binary else value
        host = urlparse(url).netloc
        if self.requests >= self.settings.source_requests_per_run:
            if cached:
                self.warnings.append("本次请求预算已用尽，使用过期缓存")
                value = json.loads(cached["body"])
                return base64.b64decode(value) if binary else value
            raise ValueError("本次请求预算已用尽，请缩小检索数量")
        last_error = None
        async with httpx.AsyncClient(
            timeout=self.settings.http_timeout, follow_redirects=True
        ) as default:
            client = self.client or default
            for attempt in range(3):
                if self.requests >= self.settings.source_requests_per_run:
                    last_error = ValueError("请求预算用尽")
                    break
                await asyncio.sleep(max(0, interval - (time.monotonic() - self.last.get(host, 0))))
                self.last[host] = time.monotonic()
                self.requests += 1
                try:
                    response = await client.get(url, params=params, headers=headers)
                    if response.status_code == 429 or response.status_code >= 500:
                        retry = response.headers.get("Retry-After", "")
                        delay = min(10, float(retry)) if retry.isdigit() else 2**attempt
                        await asyncio.sleep(delay)
                        response.raise_for_status()
                    response.raise_for_status()
                    body = (
                        base64.b64encode(response.content).decode()
                        if binary
                        else response.json()
                        if json_response
                        else response.text
                    )
                    with self.store.connect() as db:
                        db.execute(
                            "INSERT OR REPLACE INTO cache VALUES(?,?,?)",
                            (key, json.dumps(body), time.time() + self.settings.cache_ttl),
                        )
                    return response.content if binary else body
                except (httpx.HTTPError, ValueError) as exc:
                    last_error = exc
                    if (
                        isinstance(exc, httpx.HTTPStatusError)
                        and exc.response.status_code < 500
                        and exc.response.status_code != 429
                    ):
                        break
        if cached:
            self.warnings.append(f"{host} 请求失败，使用过期缓存")
            value = json.loads(cached["body"])
            return base64.b64decode(value) if binary else value
        # Do not include request URLs in errors: OpenAlex keys appear in query parameters.
        detail = type(last_error).__name__
        if isinstance(last_error, httpx.HTTPStatusError):
            code = last_error.response.status_code
            detail = f"HTTP {code}"
            if code in {401, 403}:
                detail += "，请检查该数据源的访问权限和 API Key"
            elif code == 429:
                detail += "，数据源限流或额度不足，请稍后重试"
        raise ValueError(f"{host} 请求失败（{detail}）")
