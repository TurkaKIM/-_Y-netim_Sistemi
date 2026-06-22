import os

import streamlit as st
import streamlit.components.v1 as components

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
html, body, [data-testid="stAppViewContainer"] {
    margin: 14 !important;
    padding: 14 !important;
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
iframe {
    display: block !important;
    width: 100vw !important;
    min-width: 100vw !important;
    height: 100vh !important;
    min-height: 100vh !important;
    border: none !important;
    margin: 0 !important;
    padding: 0 !important;
}
</style>
""", unsafe_allow_html=True)

# HTML dosyasını oku
with open("index.html", "r", encoding="utf-8") as f:
    html_kodu = f.read()

DEFAULT_AI_PROXY_URL = "https://script.google.com/macros/s/AKfycbxKa4-i3lZDy4tjJ716YrSuJDk6iih6oj8gTnx4resvQkQXbB4hV6_atYeqmPkLxlVopw/exec"


def get_secret_or_env(name: str, default: str = "") -> str:
    """Read a value from Streamlit secrets first, then environment variables."""
    try:
        value = st.secrets.get(name, "")
    except Exception:
        value = ""

    return str(value or os.getenv(name, default) or "").strip()


def normalize_ai_proxy_url(value: str) -> str:
    """Return the browser-side AI endpoint URL without breaking Apps Script URLs."""
    value = (value or "").strip()

    if not value:
        return DEFAULT_AI_PROXY_URL

    value = value.rstrip("/")

    if "script.google.com/macros/s/" in value:
        return value

    if value.endswith("/ai-content"):
        return value

    return f"{value}/ai-content"

ai_proxy_url = normalize_ai_proxy_url(
    get_secret_or_env("AI_PROXY_URL") or get_secret_or_env("AI_PROXY_BASE_URL")
)
html_kodu = html_kodu.replace("__AI_PROXY_URL__", ai_proxy_url)

# HTML'i Streamlit bileşeni olarak tam ekrana yakın göster
components.html(
    html_kodu,
    height=1100,
    scrolling=False
)
