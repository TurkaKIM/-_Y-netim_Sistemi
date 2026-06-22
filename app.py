import json
import os
import re
import tempfile
import time
from functools import lru_cache
from pathlib import Path
from typing import Any

import requests
import streamlit as st
import streamlit.components.v1 as components
from openai import APIConnectionError, APITimeoutError, AuthenticationError, OpenAI, RateLimitError
from pypdf import PdfReader

TERMS_PDF_URL = (
    "https://raw.githubusercontent.com/davutkara1985-create/"
    "is-takip-uygulamasi3/0d5489ad4f2ef7c2478c0c742f6185cfc7564622/"
    "terimler-sozlugu-2022-09-22.pdf"
)

DEFAULT_OPENAI_MODEL = "gpt-4o-mini"
DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"

# Streamlit sayfasını geniş ekran yap
st.set_page_config(
    page_title="TÜRKAK İş Yönetim Sistemi",
    page_icon="turkak.png",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Streamlit'in kendi boşluklarını ve üst/alt alanlarını kaldır
st.markdown("""
<style>
/* Sayfanın genel boşluklarını sıfırla */
html, body, .stApp, [data-testid="stAppViewContainer"] {
    width: 100vw !important;
    height: 100vh !important;
    min-height: 100dvh !important;
    margin: 0 !important;
    padding: 0 !important;
    overflow: hidden !important;
}

/* Streamlit ana içerik kapsayıcısının boşluklarını kaldır */
.block-container {
    padding-top: 0rem !important;
    padding-bottom: 0rem !important;
    padding-left: 0rem !important;
    padding-right: 0rem !important;
    margin: 0 !important;
    max-width: 100% !important;
}

/* Streamlit üst barını gizle */
[data-testid="stHeader"] {
    display: none !important;
}

/* Streamlit toolbar alanını gizle */
[data-testid="stToolbar"] {
    display: none !important;
}

/* Streamlit footer alanını gizle */
footer {
    display: none !important;
}

/* iframe çevresindeki boşlukları kaldır */
[data-testid="stIFrame"],
iframe {
    display: block !important;
    width: 100vw !important;
    min-width: 100vw !important;
    height: 100vh !important;
    height: 100dvh !important;
    min-height: 100vh !important;
    min-height: 100dvh !important;
    border: none !important;
    margin: 0 !important;
    padding: 0 !important;
}
</style>
""", unsafe_allow_html=True)


def get_secret_or_env(name: str, default: str = "") -> str:
    """Read a value from Streamlit secrets first, then environment variables."""
    try:
        value = st.secrets.get(name, "")
    except Exception:
        value = ""

    return str(value or os.getenv(name, default) or "").strip()


def selected_openai_model() -> str:
    """Return a safe OpenAI model name for direct Streamlit AI calls."""
    model = get_secret_or_env("OPENAI_MODEL", DEFAULT_OPENAI_MODEL).strip() or DEFAULT_OPENAI_MODEL
    model_lower = model.lower()

    # Eski/yanlış secrets değerleri uygulamayı kırmasın.
    if model_lower.startswith("gemini") or model_lower in {"gpt-5.4-mini", "gpt5.4-mini"}:
        return DEFAULT_OPENAI_MODEL

    return model


def selected_provider() -> str:
    """Return selected AI provider."""
    provider = get_secret_or_env("AI_PROVIDER", "openai").strip().lower()
    if provider in {"openai", "gemini"}:
        return provider
    return "openai"


def selected_gemini_model() -> str:
    """Return Gemini model name."""
    return get_secret_or_env("GEMINI_MODEL", DEFAULT_GEMINI_MODEL).strip() or DEFAULT_GEMINI_MODEL


def selected_ai_model() -> str:
    """Return selected model according to AI provider."""
    if selected_provider() == "gemini":
        return selected_gemini_model()
    return selected_openai_model()


def ai_timeout_seconds() -> float:
    value = get_secret_or_env("AI_TIMEOUT_SECONDS") or get_secret_or_env("OPENAI_TIMEOUT", "45")
    try:
        return float(value)
    except ValueError:
        return 45.0


def ai_max_retries() -> int:
    value = get_secret_or_env("AI_MAX_RETRIES") or get_secret_or_env("OPENAI_MAX_RETRIES", "2")
    try:
        return int(value)
    except ValueError:
        return 2


@lru_cache(maxsize=1)
def load_terms_text() -> str:
    """Read TÜRKAK terms PDF and cache the extracted text."""
    try:
        response = requests.get(TERMS_PDF_URL, timeout=30)
        response.raise_for_status()

        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            tmp.write(response.content)
            tmp_path = tmp.name

        reader = PdfReader(tmp_path)
        pages = []
        for page in reader.pages[:30]:
            pages.append(page.extract_text() or "")

        text = re.sub(r"\s+", " ", "\n".join(pages)).strip()
        return text[:18000]
    except Exception as exc:  # noqa: BLE001 - AI üretimi terimler PDF'i okunamazsa da devam etmeli
        print("Terimler sözlüğü okunamadı:", exc)
        return ""


def build_prompt(raw_text: str, outputs: list[str], terms_text: str, custom_prompt: str = "") -> str:
    """Build a JSON-only corporate content prompt."""
    output_labels = {
        "corporate_news": "Kurumsal haber metni oluştur",
        "social_media": "Sosyal medya metni oluştur",
        "title": "Başlık öner",
        "spot": "Spot metin öner",
        "web_news": "Kurumsal web sitesi haberi oluştur",
        "linkedin_post": "LinkedIn paylaşımı oluştur",
        "x_post": "X paylaşımı oluştur",
        "instagram_post": "Instagram paylaşımı oluştur",
        "bulletin_text": "Bülten metni oluştur",
        "english_news": "İngilizce haber versiyonu oluştur",
        "press_note": "Basın notu oluştur",
        "image_prompt": "Kurumsal görsel üretim promptu oluştur",
        "daily_summary": "Günlük iş ve iletişim öncelikleri özeti oluştur",
        "sensitive_check": "Hassas içerik uyarı sistemi kontrolü yap",
    }
    selected_outputs = [output_labels.get(x, x) for x in outputs]
    admin_prompt_block = custom_prompt.strip() or "Bu alan için admin tarafından özel prompt tanımlanmamış; varsayılan TÜRKAK kurumsal iletişim kurallarını uygula."

    return f"""
Sen TÜRKAK Kurumsal İletişim Müdürlüğü için çalışan kurumsal içerik ve iş yönetimi asistanısın.

Admin tarafından bu AI alanı için tanımlanan özel talimat:
{admin_prompt_block}

Kullanıcının istediği çıktı türleri:
{json.dumps(selected_outputs, ensure_ascii=False, indent=2)}

Kurumsal dil kuralları:
- Metinler resmi, sade, açıklayıcı ve kurumsal olmalı.
- Gereksiz abartılı ifadeler kullanılmamalı.
- TÜRKAK adı doğru ve tutarlı kullanılmalı.
- İngilizce ülke adında Turkey yerine Türkiye tercih edilmeli.
- Türkçe “denetim” karşılığı İngilizce kullanımda assessment olarak düşünülmeli.
- Türkçe “değerlendirme” karşılığı İngilizce kullanımda evaluation olarak düşünülmeli.
- “Local Accreditation, Global Acceptance” yerine “Accredited once, accepted everywhere” tercih edilmeli.
- Kurumsal haber metninde ziyaretin/toplantının amacı, teknik bilgi paylaşımı, iş birliği ve kurumsal katkı vurgusu bulunmalı.
- Sosyal medya metni kısa, etkili, kurumsal ve paylaşılabilir olmalı.
- Günlük özet üretiliyorsa öncelik, risk ve önerilen aksiyonlara odaklan.
- Görsel prompt üretiliyorsa TÜRKAK kurumsal kimliği, kırmızı-beyaz tonlar, sade ve resmî görsel dil vurgulansın.
- Hassas içerik kontrolü isteniyorsa şu başlıkları özellikle denetle: fazla iddialı ifade, resmî dile uygun olmayan ifade, yanlış kurum adı kullanımı, eksik unvan, yanlış tarih, politik açıdan hassas ifade, akreditasyon terminolojisine uygun olmayan kullanım.
- Platforma özel metinlerde aynı içeriği tekrar etme; LinkedIn, X ve Instagram dilini ayrı ayrı uyarlayıp üret.

Terimler sözlüğünden çıkarılan referans metin:
{terms_text}

Ham metin / uygulama bağlamı:
{raw_text}

Cevabı sadece geçerli JSON olarak ver. Markdown kullanma.

JSON şeması:
{{
  "corporate_news": "Kurumsal haber metni burada",
  "social_media": "Sosyal medya metni burada",
  "title_suggestions": ["Başlık 1", "Başlık 2", "Başlık 3"],
  "spot_text": "Spot metin burada",
  "web_news": "Kurumsal web sitesi haberi burada",
  "linkedin_post": "LinkedIn paylaşımı burada",
  "x_post": "X paylaşımı burada",
  "instagram_post": "Instagram paylaşımı burada",
  "bulletin_text": "Bülten metni burada",
  "english_news": "English news version here",
  "press_note": "Basın notu burada",
  "image_prompt": "Kurumsal görsel promptu burada",
  "daily_summary": "Günlük AI özeti burada",
  "sensitive_warnings": ["Uyarı 1", "Uyarı 2"],
  "revised_text": "Varsa düzeltilmiş metin burada",
  "term_notes": ["Terim uyarısı 1", "Terim uyarısı 2"]
}}
"""


def safe_json_parse(text: str) -> dict[str, Any]:
    """Parse model output as JSON with a safe fallback."""
    try:
        return json.loads(text)
    except Exception:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except Exception:
                pass

    return {
        "corporate_news": text,
        "social_media": "",
        "title_suggestions": [],
        "spot_text": "",
        "web_news": text,
        "linkedin_post": "",
        "x_post": "",
        "instagram_post": "",
        "bulletin_text": "",
        "english_news": "",
        "press_note": "",
        "image_prompt": "",
        "daily_summary": text,
        "sensitive_warnings": [text] if text else [],
        "revised_text": "",
        "term_notes": ["Model yanıtı JSON formatında alınamadı; ham metin gösterildi."],
    }


def call_openai_with_retry(prompt: str) -> str:
    """Call OpenAI directly from Streamlit backend."""
    api_key = get_secret_or_env("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY Streamlit Secrets alanında tanımlı değil.")

    if not api_key.startswith("sk-"):
        raise RuntimeError("OPENAI_API_KEY değeri OpenAI API anahtarı formatında görünmüyor. Yeni OpenAI API key'i sk- veya sk-proj- ile başlamalıdır.")

    client = OpenAI(
        api_key=api_key,
        base_url=get_secret_or_env("OPENAI_BASE_URL") or None,
        timeout=ai_timeout_seconds(),
        max_retries=0,
    )
    last_error: Exception | None = None

    for attempt in range(ai_max_retries() + 1):
        try:
            response = client.responses.create(
                model=selected_openai_model(),
                input=prompt,
            )
            return response.output_text
        except AuthenticationError as exc:
            raise RuntimeError("OPENAI_API_KEY geçersiz veya yetkisiz.") from exc
        except (APITimeoutError, APIConnectionError, RateLimitError) as exc:
            last_error = exc
            if attempt >= ai_max_retries():
                break
            time.sleep(min(2**attempt, 4))
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            break

    raise RuntimeError(f"OpenAI servisi geçici olarak kullanılamıyor: {last_error}")
def call_gemini_with_retry(prompt: str) -> str:
    """Call Gemini Developer API directly from Streamlit backend."""
    api_key = get_secret_or_env("GEMINI_API_KEY") or get_secret_or_env("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY Streamlit Secrets alanında tanımlı değil.")

    model = selected_gemini_model()
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [{"text": prompt}],
            }
        ],
        "generationConfig": {
            "responseMimeType": "application/json",
        },
    }

    last_error: Exception | None = None

    for attempt in range(ai_max_retries() + 1):
        try:
            response = requests.post(
                url,
                params={"key": api_key},
                json=payload,
                timeout=ai_timeout_seconds(),
            )

            if response.status_code in {408, 429, 500, 502, 503, 504} and attempt < ai_max_retries():
                last_error = RuntimeError(response.text[:500])
                time.sleep(min(2**attempt, 4))
                continue

            if response.status_code in {400, 401, 403}:
                raise RuntimeError(f"Gemini API anahtarı veya model erişimi hatası: {response.text[:500]}")

            response.raise_for_status()

            data = response.json()
            candidates = data.get("candidates") or []
            parts = (((candidates[0] or {}).get("content") or {}).get("parts") or []) if candidates else []
            text = "".join(part.get("text", "") for part in parts)

            if not text.strip():
                raise RuntimeError("Gemini boş yanıt döndürdü.")

            return text

        except Exception as exc:
            last_error = exc
            if attempt >= ai_max_retries():
                break
            time.sleep(min(2**attempt, 4))

    raise RuntimeError(f"Gemini servisi geçici olarak kullanılamıyor: {last_error}")


def call_ai_with_retry(prompt: str) -> str:
    """Call selected AI provider."""
    if selected_provider() == "gemini":
        return call_gemini_with_retry(prompt)
    return call_openai_with_retry(prompt)

def process_ai_request(request_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Process one AI request coming from the Streamlit component iframe."""
    try:
        raw_text = str(payload.get("rawText") or "").strip()
        outputs = payload.get("outputs") or []
        custom_prompt = str(payload.get("customPrompt") or "")

        if not raw_text:
            raise RuntimeError("Ham metin boş olamaz.")
        if not isinstance(outputs, list) or not outputs:
            raise RuntimeError("En az bir çıktı türü seçilmelidir.")

        prompt = build_prompt(raw_text, outputs, load_terms_text(), custom_prompt)
        model_text = call_ai_with_retry(prompt)

        return {
            "ok": True,
            "requestId": request_id,
            "provider": selected_provider(),
            "model": selected_ai_model(),
            "result": safe_json_parse(model_text),
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "requestId": request_id,
            "provider": selected_provider(),
            "model": selected_ai_model(),
            "detail": str(exc),
            "result": {},
        }


if "turkak_ai_response" not in st.session_state:
    st.session_state.turkak_ai_response = None
if "turkak_last_ai_request_id" not in st.session_state:
    st.session_state.turkak_last_ai_request_id = ""

component_dir = Path(__file__).parent.resolve()
turkak_component = components.declare_component(
    "turkak_is_yonetim_sistemi",
    path=str(component_dir),
)

component_value = turkak_component(
    ai_response=st.session_state.turkak_ai_response,
    key="turkak_is_yonetim_sistemi",
    default=None,
)

if isinstance(component_value, dict) and component_value.get("type") == "ai_request":
    request_id = str(component_value.get("requestId") or "")
    payload = component_value.get("payload") or {}

    if request_id and request_id != st.session_state.turkak_last_ai_request_id:
        st.session_state.turkak_last_ai_request_id = request_id
        st.session_state.turkak_ai_response = process_ai_request(request_id, payload)
        st.rerun()
