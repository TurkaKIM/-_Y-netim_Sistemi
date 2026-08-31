"""Aktif Dijital Hafıza promptunu yönetir."""

from database.queries import DatabaseError, SupabaseQueries


DEFAULT_DIGITAL_MEMORY_PROMPT = (
    "TÜRKAK'ın geçmiş web ve sosyal medya içeriklerini kurumsal iletişim bakış açısıyla "
    "incele. Yalnızca sunulan kaynaklara dayan; tarih, başlık veya içerik uydurma. "
    "Bulguları Türkçe, açık, tarafsız ve uygulanabilir biçimde raporla."
)


class PromptService:
    def __init__(self, queries: SupabaseQueries) -> None:
        self.queries = queries

    def get_active_prompt(self) -> tuple[str, str | None]:
        """Aktif promptu döndürür; erişim hatasında güvenli varsayılanı kullanır."""
        try:
            prompt = self.queries.get_digital_memory_prompt()
            return prompt or DEFAULT_DIGITAL_MEMORY_PROMPT, None
        except DatabaseError as exc:
            return DEFAULT_DIGITAL_MEMORY_PROMPT, str(exc)
