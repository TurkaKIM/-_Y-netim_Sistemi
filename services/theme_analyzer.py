"""LLM tema çıktısını doğrular ve eksik alanlar için güvenli yedek üretir."""

from __future__ import annotations

import re
from collections import Counter


STOP_WORDS = {
    "acaba", "ancak", "bunun", "daha", "için", "ile", "olan", "olarak", "sonra",
    "türkak", "veya", "üzerine", "www", "https", "com", "org", "tr",
}


class ThemeAnalyzer:
    @staticmethod
    def normalize(ai_output: dict, contents: list[dict[str, str]]) -> dict:
        themes = ai_output.get("themes") if isinstance(ai_output.get("themes"), list) else []
        keywords = ai_output.get("keywords") if isinstance(ai_output.get("keywords"), list) else []
        categories = ai_output.get("categories") if isinstance(ai_output.get("categories"), list) else []
        trends = ai_output.get("trends") if isinstance(ai_output.get("trends"), list) else []

        if not keywords:
            text = " ".join(f"{item.get('title', '')} {item.get('summary', '')}" for item in contents).lower()
            words = re.findall(r"[a-zçğıöşü]{4,}", text, flags=re.IGNORECASE)
            keywords = [word for word, _ in Counter(word for word in words if word not in STOP_WORDS).most_common(12)]
        if not categories:
            counts = Counter(item.get("platform", "Diğer") for item in contents)
            categories = [{"name": name, "count": count} for name, count in counts.most_common()]
        if not themes and keywords:
            themes = [{"name": word.title(), "count": 1, "evidence": "Kaynak metinlerde sık geçti."} for word in keywords[:5]]
        if not trends:
            trends = ["Eğilim analizi için yeterli tarihli içerik bulunamadı."] if contents else []
        return {"themes": themes, "keywords": keywords, "categories": categories, "trends": trends}
