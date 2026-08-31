"""İçerik önerisi alanlarını tutarlı biçime getirir."""

from __future__ import annotations


class SuggestionEngine:
    KEYS = ("social_media", "news", "website", "video", "linkedin")

    @classmethod
    def normalize(cls, ai_output: dict) -> dict[str, list[str]]:
        raw = ai_output.get("suggestions") if isinstance(ai_output.get("suggestions"), dict) else {}
        result: dict[str, list[str]] = {}
        for key in cls.KEYS:
            values = raw.get(key, [])
            if isinstance(values, str):
                values = [values]
            result[key] = [str(value).strip() for value in values if str(value).strip()][:8]
        return result
