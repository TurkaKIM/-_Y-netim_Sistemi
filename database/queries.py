"""Dijital Hafıza Merkezi için sunucu taraflı Supabase sorguları."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import requests


class DatabaseError(RuntimeError):
    """Supabase işlemi tamamlanamadığında oluşur."""


@dataclass(frozen=True)
class SupabaseConfig:
    url: str
    service_role_key: str
    table: str = "app_store"
    row_id: str = "turkak_its_data"
    timeout: int = 20


class SupabaseQueries:
    """Service-role anahtarını yalnızca Python sunucusunda kullanan veri katmanı."""

    def __init__(self, config: SupabaseConfig) -> None:
        self.config = config

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "apikey": self.config.service_role_key,
            "Authorization": f"Bearer {self.config.service_role_key}",
            "Content-Type": "application/json",
        }

    def _ensure_configured(self) -> None:
        if not self.config.url or not self.config.service_role_key:
            raise DatabaseError("Supabase URL veya service role anahtarı tanımlı değil.")

    def get_digital_memory_prompt(self) -> str:
        self._ensure_configured()
        endpoint = f"{self.config.url.rstrip('/')}/rest/v1/{self.config.table}"
        try:
            response = requests.get(
                endpoint,
                headers=self._headers,
                params={"id": f"eq.{self.config.row_id}", "select": "data", "limit": "1"},
                timeout=self.config.timeout,
            )
        except requests.RequestException as exc:
            raise DatabaseError(f"Aktif prompt okunamadı: {exc}") from exc
        if not response.ok:
            raise DatabaseError(self._response_error(response, "Aktif prompt okunamadı"))
        rows = response.json()
        if not rows:
            return ""
        data = rows[0].get("data") or {}
        prompts = data.get("aiPrompts") if isinstance(data, dict) else {}
        return str((prompts or {}).get("digitalMemory") or "").strip()

    def log_ai_search(self, user_id: str, query: str, response_data: dict[str, Any]) -> None:
        self._ensure_configured()
        endpoint = f"{self.config.url.rstrip('/')}/rest/v1/ai_search_logs"
        try:
            response = requests.post(
                endpoint,
                headers={**self._headers, "Prefer": "return=minimal"},
                json={
                    "user_id": str(user_id or "unknown"),
                    "query": query,
                    "response": response_data,
                },
                timeout=self.config.timeout,
            )
        except requests.RequestException as exc:
            raise DatabaseError(f"Arama kaydı yazılamadı: {exc}") from exc
        if not response.ok:
            raise DatabaseError(self._response_error(response, "Arama kaydı yazılamadı"))

    @staticmethod
    def _response_error(response: requests.Response, prefix: str) -> str:
        detail = ""
        try:
            payload = response.json()
            detail = payload.get("message") or payload.get("details") or json.dumps(payload, ensure_ascii=False)
        except (ValueError, AttributeError):
            detail = response.text[:500]
        return f"{prefix} (HTTP {response.status_code}): {detail or 'Bilinmeyen hata'}"
