"""TÜRKAK Dijital Hafıza Merkezi Streamlit sayfası."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import streamlit as st

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from database.queries import DatabaseError, SupabaseConfig, SupabaseQueries  # noqa: E402
from services.ai_analyzer import AIAnalyzer, AIAnalyzerError, AIConfig, UnsafeQueryError, validate_user_query  # noqa: E402
from services.prompt_service import PromptService  # noqa: E402
from services.suggestion_engine import SuggestionEngine  # noqa: E402
from services.theme_analyzer import ThemeAnalyzer  # noqa: E402
from services.web_collector import WebCollector, WebCollectorConfig, WebCollectorError  # noqa: E402


st.set_page_config(
    page_title="TÜRKAK Dijital Hafıza Merkezi",
    page_icon=str(ROOT_DIR / "turkak.png"),
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown(
    """
    <style>
    [data-testid="stSidebar"], [data-testid="stHeader"], footer {display:none !important;}
    .block-container {max-width: 1500px; padding-top: 1.5rem; padding-bottom: 2rem;}
    [data-testid="stDataFrame"] {width:100%;}
    </style>
    """,
    unsafe_allow_html=True,
)


def setting(name: str, default: str = "") -> str:
    try:
        value = st.secrets.get(name, "")
    except Exception:
        value = ""
    return str(value or os.getenv(name, default) or "").strip()


def positive_int_setting(name: str, default: int) -> int:
    try:
        return max(1, int(setting(name, str(default))))
    except ValueError:
        return default


def database_client() -> SupabaseQueries:
    return SupabaseQueries(
        SupabaseConfig(
            url=setting("SUPABASE_URL", "https://xhhqoacsctktvjfkgrnh.supabase.co"),
            service_role_key=setting("SUPABASE_SERVICE_ROLE_KEY") or setting("SUPABASE_SECRET_KEY"),
        )
    )


@st.cache_data(ttl=21600, show_spinner=False)
def run_analysis_cached(
    query: str,
    system_prompt: str,
    provider: str,
    model: str,
    max_results: int,
    _ai_api_key: str,
    _tavily_api_key: str,
) -> dict[str, Any]:
    analyzer = AIAnalyzer(
        AIConfig(
            provider=provider,
            api_key=_ai_api_key,
            model=model,
            timeout=positive_int_setting("AI_TIMEOUT_SECONDS", 45),
        )
    )
    intent = analyzer.analyze_query(query, system_prompt)
    contents = WebCollector(
        WebCollectorConfig(
            api_key=_tavily_api_key,
            timeout=positive_int_setting("DIGITAL_MEMORY_SEARCH_TIMEOUT", 30),
            max_results=max_results,
        )
    ).collect(intent.get("search_queries", []))
    synthesis = analyzer.synthesize(query, intent, contents, system_prompt)
    return {
        "intent": intent,
        "contents": contents,
        "theme_analysis": ThemeAnalyzer.normalize(synthesis, contents),
        "suggestions": SuggestionEngine.normalize(synthesis),
        "ai_commentary": str(synthesis.get("ai_commentary") or "Analiz yorumu oluşturulamadı."),
    }


def show_list(items: list[Any], empty_text: str) -> None:
    if not items:
        st.info(empty_text)
        return
    for item in items:
        if isinstance(item, dict):
            name = item.get("name", "Tema")
            count = item.get("count")
            evidence = item.get("evidence")
            suffix = f" ({count})" if count not in (None, "") else ""
            st.markdown(f"- **{name}{suffix}**" + (f" — {evidence}" if evidence else ""))
        else:
            st.markdown(f"- {item}")


def render_result(result: dict[str, Any]) -> None:
    contents = result.get("contents", [])
    themes = result.get("theme_analysis", {})
    suggestions = result.get("suggestions", {})
    tab_contents, tab_themes, tab_suggestions, tab_commentary = st.tabs(
        ["📚 Bulunan İçerikler", "📈 Tema Analizi", "💡 İçerik Önerileri", "📝 Yapay Zeka Yorumu"]
    )

    with tab_contents:
        if contents:
            rows = [
                {
                    "Tarih": item.get("date", ""),
                    "Başlık": item.get("title", ""),
                    "URL": item.get("url", ""),
                    "Kaynak Platform": item.get("platform", ""),
                    "Kısa Özet": item.get("summary", ""),
                }
                for item in contents
            ]
            st.dataframe(
                rows,
                use_container_width=True,
                hide_index=True,
                column_config={"URL": st.column_config.LinkColumn("URL", display_text="Kaynağı Aç")},
            )
        else:
            st.info("Resmî kanallarda sorguyla eşleşen içerik bulunamadı.")

    with tab_themes:
        left, right = st.columns(2)
        with left:
            st.subheader("En sık işlenen temalar")
            show_list(themes.get("themes", []), "Tema bulunamadı.")
            st.subheader("Ortak anahtar kelimeler")
            show_list(themes.get("keywords", []), "Anahtar kelime bulunamadı.")
        with right:
            st.subheader("İçerik kategorileri")
            show_list(themes.get("categories", []), "Kategori bulunamadı.")
            st.subheader("Eğilimler")
            show_list(themes.get("trends", []), "Eğilim bulunamadı.")

    labels = {
        "social_media": "Sosyal medya önerileri",
        "news": "Haber önerileri",
        "website": "Web sitesi önerileri",
        "video": "Video önerileri",
        "linkedin": "LinkedIn önerileri",
    }
    with tab_suggestions:
        for key, label in labels.items():
            st.subheader(label)
            show_list(suggestions.get(key, []), "Öneri oluşturulamadı.")

    with tab_commentary:
        st.markdown(result.get("ai_commentary", "Analiz yorumu oluşturulamadı."))


if st.button("← İş Yönetim Sistemine Dön"):
    st.switch_page("app.py")

st.title("🧠 TÜRKAK Dijital Hafıza Merkezi")
st.caption("TÜRKAK'ın resmî web ve sosyal medya kanallarındaki geçmiş içerikleri analiz eder.")

user_id = str(st.session_state.get("digital_memory_user_id") or "").strip()
if not user_id:
    st.warning("Bu sayfayı kullanmak için önce İş Yönetim Sistemi üzerinden giriş yapın.")
    st.stop()

queries = database_client()
active_prompt, prompt_warning = PromptService(queries).get_active_prompt()
if prompt_warning:
    st.warning("Yönetici promptu okunamadı; güvenli varsayılan prompt kullanılıyor.")

query_text = st.text_area(
    "Aramak istediğiniz konu",
    placeholder="Dünya Akreditasyon Günü",
    height=120,
)

if st.button("Analiz Et", type="primary", use_container_width=False):
    try:
        safe_query = validate_user_query(query_text)
        provider = setting("AI_PROVIDER", "gemini").lower()
        if provider == "gemini":
            ai_key = setting("GEMINI_API_KEY") or setting("GOOGLE_API_KEY")
            model = setting("GEMINI_MODEL", "gemini-2.5-flash")
        else:
            ai_key = setting("OPENAI_API_KEY")
            model = setting("OPENAI_MODEL", "gpt-4o-mini")

        with st.spinner("Resmî kaynaklar taranıyor ve içerikler analiz ediliyor..."):
            result = run_analysis_cached(
                safe_query,
                active_prompt,
                provider,
                model,
                positive_int_setting("DIGITAL_MEMORY_MAX_RESULTS", 30),
                ai_key,
                setting("TAVILY_API_KEY"),
            )
        st.session_state.digital_memory_result = result
        try:
            queries.log_ai_search(user_id, safe_query, result)
        except DatabaseError:
            st.warning("Analiz tamamlandı; ancak ai_search_logs kaydı yazılamadı. SQL kurulumunu kontrol edin.")
    except UnsafeQueryError as exc:
        st.error(str(exc))
    except (ValueError, AIAnalyzerError, WebCollectorError) as exc:
        st.error(str(exc))
    except Exception as exc:  # noqa: BLE001
        st.error(f"Analiz sırasında beklenmeyen bir hata oluştu: {exc}")

if st.session_state.get("digital_memory_result"):
    render_result(st.session_state.digital_memory_result)
