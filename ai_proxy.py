import json
import os
import re
import smtplib
import tempfile
import time
from email.message import EmailMessage
from functools import lru_cache
from pathlib import Path
from typing import Any

import requests
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from openai import APIConnectionError, APITimeoutError, AuthenticationError, OpenAI, RateLimitError
from pydantic import BaseModel, EmailStr
from pypdf import PdfReader


TERMS_PDF_URL = (
    "https://raw.githubusercontent.com/davutkara1985-create/"
    "is-takip-uygulamasi3/0d5489ad4f2ef7c2478c0c742f6185cfc7564622/"
    "terimler-sozlugu-2022-09-22.pdf"
)

DEFAULT_OPENAI_MODEL = "gpt-4o-mini"
DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"
AI_PROVIDER = os.getenv("AI_PROVIDER", "openai").strip().lower()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", DEFAULT_OPENAI_MODEL)
GEMINI_MODEL = os.getenv("GEMINI_MODEL", DEFAULT_GEMINI_MODEL)
AI_TIMEOUT_SECONDS = float(os.getenv("AI_TIMEOUT_SECONDS", "45"))
AI_MAX_RETRIES = int(os.getenv("AI_MAX_RETRIES", "2"))


def selected_provider() -> str:
    """Return the configured AI provider: openai, gemini or demo."""
    provider = (os.getenv("AI_PROVIDER") or AI_PROVIDER or "openai").strip().lower()
    if provider in {"openai", "gemini", "demo"}:
        return provider
    return "openai"


def selected_model() -> str:
    """Return a safe model name according to the selected provider."""
    provider = selected_provider()

    if provider == "gemini":
        return (os.getenv("GEMINI_MODEL") or GEMINI_MODEL or DEFAULT_GEMINI_MODEL).strip()

    if provider == "demo":
        return "demo-local-template"

    model = (os.getenv("OPENAI_MODEL") or OPENAI_MODEL or DEFAULT_OPENAI_MODEL).strip()

    # Current secrets may contain this typo/non-existent model name; falling back avoids model-not-found errors.
    if model.lower() in {"gpt-5.4-mini", "gpt5.4-mini"}:
        return DEFAULT_OPENAI_MODEL

    return model or DEFAULT_OPENAI_MODEL


def load_local_secrets() -> None:
    """Load local Streamlit secrets without committing secrets to git."""
    try:
        import tomllib
    except ModuleNotFoundError:
        return

    for path in [Path(".streamlit/secrets.toml"), Path("secrets.toml")]:
        if not path.exists():
            continue

        data = tomllib.loads(path.read_text(encoding="utf-8"))
        for key in [
            "AI_PROVIDER",
            "OPENAI_API_KEY",
            "OPENAI_MODEL",
            "OPENAI_BASE_URL",
            "GEMINI_API_KEY",
            "GOOGLE_API_KEY",
            "GEMINI_MODEL",
            "SMTP_HOST",
            "SMTP_PORT",
            "SMTP_USER",
            "SMTP_PASSWORD",
            "SMTP_FROM",
            "SMTP_TLS",
        ]:
            value = data.get(key)
            if value and not os.getenv(key):
                os.environ[key] = str(value)
        break


load_local_secrets()

app = FastAPI(title="TÜRKAK Kurumsal İçerik Asistanı API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_openai_client() -> OpenAI:
    """Create an OpenAI client with explicit timeout and no implicit retries."""
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="OPENAI_API_KEY tanımlı değil.")

    base_url = os.getenv("OPENAI_BASE_URL") or None
    return OpenAI(api_key=api_key, base_url=base_url, timeout=AI_TIMEOUT_SECONDS, max_retries=0)


class ContentRequest(BaseModel):
    rawText: str
    outputs: list[str]
    provider: str = "general"
    promptKey: str = "contentAssistant"
    customPrompt: str = ""


class ResetEmailRequest(BaseModel):
    to: EmailStr
    fullName: str = ""
    resetLink: str


class NotificationEmailRequest(BaseModel):
    to: EmailStr
    subject: str
    message: str
    fullName: str = ""


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
    except Exception as exc:  # noqa: BLE001 - proxy must never fail because the PDF is unavailable
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
        "chatbot": "Uygulama bağlamına göre kısa danışman cevabı üret",
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
- Chatbot cevabı üretiliyorsa kısa, uygulanabilir ve bağlama duyarlı cevap ver.
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
  "chatbot": "Chatbot yanıtı burada",
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
        "sensitive_warnings": [text],
        "revised_text": "",
        "chatbot": text,
        "term_notes": ["Model yanıtı JSON formatında alınamadı; ham metin gösterildi."],
    }


def call_openai_with_retry(prompt: str) -> str:
    """Call OpenAI with explicit retry handling for transient failures."""
    client = get_openai_client()
    last_error: Exception | None = None

    for attempt in range(AI_MAX_RETRIES + 1):
        try:
            response = client.responses.create(
                model=selected_model(),
                input=prompt,
            )
            return response.output_text
        except AuthenticationError as exc:
            raise HTTPException(status_code=401, detail="OPENAI_API_KEY geçersiz veya yetkisiz.") from exc
        except (APITimeoutError, APIConnectionError, RateLimitError) as exc:
            last_error = exc
            if attempt >= AI_MAX_RETRIES:
                break
            time.sleep(min(2**attempt, 4))
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            break

    raise HTTPException(status_code=503, detail=f"OpenAI servisi geçici olarak kullanılamıyor: {last_error}")


def call_gemini_with_retry(prompt: str) -> str:
    """Call Gemini Developer API via REST without adding a new dependency."""
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="GEMINI_API_KEY veya GOOGLE_API_KEY tanımlı değil.")

    model = selected_model()
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

    for attempt in range(AI_MAX_RETRIES + 1):
        try:
            response = requests.post(
                url,
                params={"key": api_key},
                json=payload,
                timeout=AI_TIMEOUT_SECONDS,
            )
            if response.status_code in {408, 429, 500, 502, 503, 504} and attempt < AI_MAX_RETRIES:
                last_error = RuntimeError(response.text[:500])
                time.sleep(min(2**attempt, 4))
                continue
            if response.status_code == 401:
                raise HTTPException(status_code=401, detail="Gemini API anahtarı geçersiz veya yetkisiz.")
            response.raise_for_status()
            data = response.json()
            candidates = data.get("candidates") or []
            parts = (((candidates[0] or {}).get("content") or {}).get("parts") or []) if candidates else []
            text = "".join(part.get("text", "") for part in parts)
            if not text.strip():
                raise RuntimeError("Gemini boş yanıt döndürdü.")
            return text
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if attempt >= AI_MAX_RETRIES:
                break
            time.sleep(min(2**attempt, 4))

    raise HTTPException(status_code=503, detail=f"Gemini servisi geçici olarak kullanılamıyor: {last_error}")


def demo_response(outputs: list[str], raw_text: str) -> dict[str, Any]:
    """Return a deterministic template response for testing without an external AI account."""
    text = raw_text.strip()[:700]
    result: dict[str, Any] = {
        "corporate_news": "Demo mod: Kurumsal haber taslağı oluşturmak için gerçek AI sağlayıcısı bağlayın. Girdi özeti: " + text,
        "social_media": "Demo mod: Sosyal medya metni için gerçek AI sağlayıcısı bağlayın.",
        "title_suggestions": ["Demo Başlık Önerisi 1", "Demo Başlık Önerisi 2", "Demo Başlık Önerisi 3"],
        "spot_text": "Demo mod: Bu alan gerçek AI bağlantısı kurulduğunda otomatik üretilecektir.",
        "web_news": "Demo mod: Web sitesi haberi için gerçek AI sağlayıcısı bağlayın. Girdi özeti: " + text,
        "linkedin_post": "Demo mod: LinkedIn paylaşımı gerçek AI sağlayıcısı bağlandığında üretilecektir.",
        "x_post": "Demo mod: X paylaşımı gerçek AI sağlayıcısı bağlandığında üretilecektir.",
        "instagram_post": "Demo mod: Instagram paylaşımı gerçek AI sağlayıcısı bağlandığında üretilecektir.",
        "bulletin_text": "Demo mod: Bülten metni gerçek AI sağlayıcısı bağlandığında üretilecektir.",
        "english_news": "Demo mode: English version will be generated after a real AI provider is connected.",
        "press_note": "Demo mod: Basın notu gerçek AI sağlayıcısı bağlandığında üretilecektir.",
        "image_prompt": "Demo mod: Kurumsal kırmızı-beyaz sade görsel yaklaşım.",
        "daily_summary": "Demo mod: Bugünün öncelikleri gerçek AI bağlantısı kurulduğunda verilerden özetlenecektir.",
        "sensitive_warnings": ["Demo mod: Hassas içerik kontrolü için gerçek AI sağlayıcısı bağlayın."],
        "revised_text": text,
        "chatbot": "Demo mod açık. Gerçek cevaplar için AI_PROVIDER=openai veya AI_PROVIDER=gemini olarak ayarlayın.",
        "term_notes": ["Demo mod gerçek terminoloji analizi yapmaz."],
    }
    return result


def call_ai_with_retry(prompt: str) -> str | dict[str, Any]:
    provider = selected_provider()
    if provider == "gemini":
        return call_gemini_with_retry(prompt)
    if provider == "demo":
        # The caller has the output list and raw text, so demo is handled in /ai-content.
        return "{}"
    return call_openai_with_retry(prompt)


@app.post("/ai-content")
def ai_content(req: ContentRequest):
    if not req.rawText.strip():
        raise HTTPException(status_code=400, detail="Ham metin boş olamaz.")

    if not req.outputs:
        raise HTTPException(status_code=400, detail="En az bir çıktı türü seçilmelidir.")

    if selected_provider() == "demo":
        result_json = demo_response(req.outputs, req.rawText)
    else:
        prompt = build_prompt(req.rawText, req.outputs, load_terms_text(), req.customPrompt)
        result_text = call_ai_with_retry(prompt)
        result_json = safe_json_parse(str(result_text))

    return {
        "ok": True,
        "provider": selected_provider(),
        "model": selected_model(),
        "result": result_json,
    }


@app.post("/send-reset-email")
def send_reset_email(req: ResetEmailRequest):
    """Send password reset link via SMTP if SMTP settings are defined."""
    host = os.getenv("SMTP_HOST")
    user = os.getenv("SMTP_USER")
    password = os.getenv("SMTP_PASSWORD")
    sender = os.getenv("SMTP_FROM") or user
    port = int(os.getenv("SMTP_PORT", "587"))
    use_tls = os.getenv("SMTP_TLS", "true").lower() != "false"

    if not host or not sender:
        raise HTTPException(status_code=503, detail="SMTP ayarları tanımlı değil.")

    msg = EmailMessage()
    msg["Subject"] = "TÜRKAK İş Yönetim Sistemi Şifre Sıfırlama"
    msg["From"] = sender
    msg["To"] = str(req.to)
    greeting = f"Sayın {req.fullName}," if req.fullName else "Merhaba,"
    msg.set_content(
        f"{greeting}\n\n"
        "TÜRKAK İş Yönetim Sistemi için şifre sıfırlama bağlantınız aşağıdadır. "
        "Bağlantı 30 dakika geçerlidir.\n\n"
        f"{req.resetLink}\n\n"
        "Bu işlemi siz talep etmediyseniz bu e-postayı dikkate almayınız."
    )

    try:
        with smtplib.SMTP(host, port, timeout=20) as smtp:
            if use_tls:
                smtp.starttls()
            if user and password:
                smtp.login(user, password)
            smtp.send_message(msg)
        return {"ok": True}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"E-posta gönderilemedi: {exc}") from exc


@app.post("/send-notification-email")
def send_notification_email(req: NotificationEmailRequest):
    """Send an admin notification email via SMTP if SMTP settings are defined."""
    host = os.getenv("SMTP_HOST")
    user = os.getenv("SMTP_USER")
    password = os.getenv("SMTP_PASSWORD")
    sender = os.getenv("SMTP_FROM") or user
    port = int(os.getenv("SMTP_PORT", "587"))
    use_tls = os.getenv("SMTP_TLS", "true").lower() != "false"

    if not host or not sender:
        raise HTTPException(status_code=503, detail="SMTP ayarları tanımlı değil.")

    msg = EmailMessage()
    msg["Subject"] = req.subject or "TÜRKAK İş Yönetim Sistemi Bildirimi"
    msg["From"] = sender
    msg["To"] = str(req.to)
    greeting = f"Sayın {req.fullName}," if req.fullName else "Merhaba,"
    msg.set_content(
        f"{greeting}\n\n"
        f"{req.message}\n\n"
        "Bu bildirim TÜRKAK İş Yönetim Sistemi üzerinden gönderilmiştir."
    )

    try:
        with smtplib.SMTP(host, port, timeout=20) as smtp:
            if use_tls:
                smtp.starttls()
            if user and password:
                smtp.login(user, password)
            smtp.send_message(msg)
        return {"ok": True}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"E-posta gönderilemedi: {exc}") from exc


@app.get("/health")
def health():
    return {"ok": True, "provider": selected_provider(), "model": selected_model()}
    
