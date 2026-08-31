"""Resmî TÜRKAK kanallarındaki sonuçları Tavily üzerinden toplar."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

import requests


class WebCollectorError(RuntimeError):
    """Web araması tamamlanamadığında oluşur."""


@dataclass(frozen=True)
class WebCollectorConfig:
    api_key: str
    timeout: int = 30
    max_results: int = 30


class WebCollector:
    SEARCH_URL = "https://api.tavily.com/search"
    ALLOWED_DOMAINS = (
        "turkak.org.tr",
        "linkedin.com",
        "x.com",
        "twitter.com",
        "instagram.com",
        "youtube.com",
        "youtu.be",
    )

    def __init__(self, config: WebCollectorConfig) -> None:
        self.config = config

    def collect(self, search_queries: list[str]) -> list[dict[str, str]]:
        if not self.config.api_key:
            raise WebCollectorError("TAVILY_API_KEY tanımlı değil.")

        normalized: list[dict[str, str]] = []
        seen_urls: set[str] = set()
        errors: list[str] = []
        for query in search_queries[:8]:
            try:
                response = requests.post(
                    self.SEARCH_URL,
                    json={
                        "api_key": self.config.api_key,
                        "query": query,
                        "search_depth": "advanced",
                        "max_results": 6,
                        "include_answer": False,
                        "include_raw_content": False,
                    },
                    timeout=self.config.timeout,
                )
                if not response.ok:
                    errors.append(f"HTTP {response.status_code}")
                    continue
                for item in response.json().get("results", []):
                    result = self._normalize(item)
                    if not result or result["url"] in seen_urls:
                        continue
                    seen_urls.add(result["url"])
                    normalized.append(result)
                    if len(normalized) >= self.config.max_results:
                        return normalized
            except requests.RequestException as exc:
                errors.append(str(exc))

        if not normalized and errors:
            raise WebCollectorError("Web araması tamamlanamadı: " + "; ".join(errors[:3]))
        return normalized

    def _normalize(self, item: dict) -> dict[str, str] | None:
        url = str(item.get("url") or "").strip()
        host = urlparse(url).netloc.lower().removeprefix("www.")
        if not url or not any(host == domain or host.endswith(f".{domain}") for domain in self.ALLOWED_DOMAINS):
            return None
        content = re.sub(r"\s+", " ", str(item.get("content") or "")).strip()
        published = str(item.get("published_date") or item.get("publishedDate") or "").strip()
        if not published:
            date_match = re.search(r"\b(20\d{2})[-/.](0?[1-9]|1[0-2])[-/.]([0-2]?\d|3[01])\b", content)
            published = date_match.group(0) if date_match else "Belirtilmemiş"
        return {
            "date": published,
            "title": str(item.get("title") or "Başlıksız içerik").strip(),
            "url": url,
            "platform": self.platform_from_url(url),
            "summary": content[:700] or "Arama sonucunda özet metin bulunamadı.",
        }

    @staticmethod
    def platform_from_url(url: str) -> str:
        host = urlparse(url).netloc.lower()
        if "linkedin.com" in host:
            return "LinkedIn"
        if "twitter.com" in host or host.endswith("x.com"):
            return "X"
        if "instagram.com" in host:
            return "Instagram"
        if "youtube.com" in host or "youtu.be" in host:
            return "YouTube"
        return "TÜRKAK Web Sitesi"
