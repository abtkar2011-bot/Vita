# -*- coding: utf-8 -*-
"""
Vita — مساعدك الدراسي الذكي 🧬
تطبيق Streamlit عربي (RTL) بتصميم داكن، مدعوم بـ Gemini API عبر REST مع بث مباشر للإجابات.

التشغيل محلياً:
    pip install -r requirements.txt
    streamlit run app.py

مفتاح الـ API اختياري ويُقرأ تلقائياً من إعدادات الخادم:
    .streamlit/secrets.toml  (أو Settings → Secrets على Streamlit Cloud)
    GEMINI_API_KEY = "..."

بدون مفتاح يعمل التطبيق بخدمة ذكاء اصطناعي مجانية (Pollinations)،
وإذا كانت مشغولة يرد Vita بإجابات محلية جاهزة حتى لا يتوقف العرض.
"""

import base64
import hashlib
import html
import inspect
import io
import json
import math
import os
import random
import re
import sys
import time
import types
import xml.etree.ElementTree as ET
import zipfile
from collections import Counter
from datetime import date, datetime, timedelta
from itertools import combinations

import pandas as pd
import requests
import streamlit as st
from PIL import Image, ImageOps

# ------------------------------------------------------------------
# توافق streamlit-drawable-canvas مع إصدارات Streamlit الحديثة
# (المكتبة تستورد streamlit.elements.image الذي نُقل في الإصدارات الجديدة)
# ------------------------------------------------------------------
try:
    import streamlit.elements.image  # noqa: F401
except ModuleNotFoundError:
    try:
        from streamlit.elements.lib import image_utils as _image_utils

        _shim = types.ModuleType("streamlit.elements.image")
        _shim.image_to_url = _image_utils.image_to_url
        sys.modules["streamlit.elements.image"] = _shim
    except Exception:
        pass

try:
    from streamlit_drawable_canvas import st_canvas

    CANVAS_ERROR = None
except Exception as exc:  # pragma: no cover
    st_canvas = None
    CANVAS_ERROR = str(exc)

try:
    from pypdf import PdfReader
except ImportError:  # pragma: no cover
    PdfReader = None

try:  # لرسم صفحات PDF المصوّرة كصور قبل قراءتها بالـ OCR
    import pypdfium2 as pdfium
except ImportError:  # pragma: no cover
    pdfium = None


# ==================================================================
# الإعدادات العامة
# ==================================================================
APP_NAME = "Vita"
DEFAULT_MODEL = "gemini-3.8-flash"
# نماذج احتياطية تُجرَّب تلقائياً إذا لم يكن النموذج الأساسي متاحاً (خطأ 404)
FALLBACK_MODELS = ["gemini-flash-latest", "gemini-2.5-flash"]
API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
MAX_DOC_CHARS = 120_000
MAX_HISTORY_TURNS = 40

# خدمة ذكاء اصطناعي مجانية بدون مفتاح (تُستخدم عند غياب مفتاح Gemini)
# حدّها المجاني: رد واحد كل 30 ثانية تقريباً لكل عنوان IP
FREE_API_URL = "https://text.pollinations.ai/openai"
FREE_MODEL = "openai"
FREE_MAX_DOC_CHARS = 20_000
FREE_MAX_WAIT = 40

SYSTEM_INSTRUCTION = (
    "أنت Vita، مساعد دراسي ذكي وودود صُمّم لمساعدة الطلاب. "
    "عرّف نفسك دائماً باسم Vita عندما تُسأل عن اسمك أو هويتك أو من أنت، ولا تقدّم نفسك باسم آخر، "
    "واكتب اسمك دائماً بالحروف اللاتينية هكذا: Vita. "
    "أجب باللغة العربية الفصحى المبسّطة ما لم يطلب المستخدم لغة أخرى. "
    "نظّم إجاباتك بعناوين ونقاط واضحة عند الحاجة، واشرح المفاهيم خطوة بخطوة مع أمثلة، "
    "وشجّع الطالب على الفهم العميق بدلاً من الحفظ. "
    "اكتب المعادلات بصيغة بسيطة مثل F = m × a أو بين علامتي $ ولا تستخدم \\( \\) أو \\[ \\]."
)

NOTEBOOK_SYSTEM = (
    "أنت Vita، مساعد مذاكرة ذكي متخصص في تحليل المستندات الدراسية. "
    "اعتمد على محتوى المستند المرفق فقط ولا تخترع معلومات غير موجودة فيه. "
    "قد يكون النص مستخرجاً بالقراءة الضوئية من صور أو شرائح عرض، فصحّح الأخطاء الإملائية البسيطة "
    "وتجاهل النصوص العشوائية مثل Lorem ipsum أو Keyword. "
    "اكتب باللغة العربية الفصحى بأسلوب منظم وواضح باستخدام تنسيق Markdown."
)

NO_KEY_MSG = (
    "لم يتم ضبط مفتاح Gemini API على الخادم. أضف السطر التالي إلى ملف "
    "`.streamlit/secrets.toml` (أو إلى Secrets في Streamlit Cloud):\n\n"
    '```toml\nGEMINI_API_KEY = "YOUR_API_KEY"\n```'
)

PAGES = {
    "chat": "💬 الدردشة الذكية",
    "board": "🎨 السبورة التفاعلية",
    "sheets": "📊 منشئ الجداول",
    "notebook": "📚 مساعد المستندات",
    "profile": "👤 الملف الشخصي والإنتاجية",
}

AVATARS = ["🎓", "🧠", "🦉", "🚀", "📚", "🌟", "🧬", "🎯", "🦊", "🐱", "🌸", "🦁"]
ASSISTANT_AVATAR = "✨"

CHAT_SUGGESTIONS = [
    ("🧠", "اشرح لي قانون نيوتن الثاني بمثال من الحياة اليومية"),
    ("📅", "ساعدني في وضع خطة مذاكرة لأسبوع الاختبارات"),
    ("✍️", "كيف أكتب مقالاً علمياً قوياً ومنظماً؟"),
    ("🔢", "حلّ معي معادلة تربيعية خطوة بخطوة"),
]

# ---------------- السبورة ----------------
BOARD_TOOLS = {
    "freedraw": "✏️ قلم",
    "eraser": "🧽 ممحاة",
    "line": "📏 خط",
    "rect": "⬜ مستطيل",
    "circle": "⭕ دائرة",
    "transform": "✋ تحريك",
}
PEN_COLORS = {
    "white": ("⚪ أبيض", "#f8fafc"),
    "black": ("⚫ أسود", "#0f172a"),
    "red": ("🔴 أحمر", "#ef4444"),
    "blue": ("🔵 أزرق", "#3b82f6"),
    "green": ("🟢 أخضر", "#22c55e"),
    "yellow": ("🟡 أصفر", "#facc15"),
    "purple": ("🟣 بنفسجي", "#a855f7"),
    "custom": ("🎨 مخصص", None),
}
BOARD_BACKGROUNDS = {
    "dark": ("🌑 سبورة داكنة", "#0b1222"),
    "white": ("⬜ سبورة بيضاء", "#ffffff"),
    "chalk": ("🟩 سبورة طباشير", "#123524"),
}
# نسبة عرض إلى ارتفاع متقاربة لكل الأحجام حتى يتحجّم الرسم بين الأحجام دون تشويه
BOARD_SIZES = {
    "s": ("صغيرة", 780, 440),
    "m": ("متوسطة", 940, 540),
    "l": ("كبيرة", 1140, 650),
}

# ---------------- الجداول ----------------
COL_SUBJECT = "المادة"
COL_TASK = "الموضوع / المهمة"
COL_DAY = "اليوم"
COL_DATE = "التاريخ"
COL_HOURS = "المدة (ساعة)"
COL_PRIORITY = "الأولوية"
COL_DONE = "تم الإنجاز"
SHEET_COLUMNS = [COL_SUBJECT, COL_TASK, COL_DAY, COL_DATE, COL_HOURS, COL_PRIORITY, COL_DONE]
WEEKDAY_AR = ["الاثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد"]
PRIORITIES = ["🔴 عالية", "🟡 متوسطة", "🟢 منخفضة"]

# ---------------- المستندات ----------------
NOTEBOOK_TASKS = {
    "summary": {
        "label": "📝 ملخص تنفيذي",
        "title": "الملخص التنفيذي",
        "desc": "نظرة عامة، أهم النقاط، والمفاهيم الأساسية",
    },
    "quiz": {
        "label": "❓ اختبار سريع",
        "title": "الاختبار السريع وأسئلة المذاكرة",
        "desc": "أسئلة اختيار من متعدد مع مفتاح الإجابات",
    },
    "mindmap": {
        "label": "🗺️ خريطة مفاهيمية",
        "title": "الخريطة المفاهيمية",
        "desc": "شجرة هرمية للأفكار والعلاقات بينها",
    },
}

# ---------------- المؤقت ----------------
POMO_MODES = {
    "focus": {"label": "🎯 تركيز", "minutes": 25, "color": "#8b5cf6"},
    "short": {"label": "☕ استراحة قصيرة", "minutes": 5, "color": "#22c55e"},
    "long": {"label": "🌿 استراحة طويلة", "minutes": 15, "color": "#06b6d4"},
}
DAILY_POMO_GOAL = 4

LEVELS = [(0, "🌱 مبتدئ"), (80, "📘 مجتهد"), (220, "🚀 متفوّق"), (450, "🏆 أسطورة المذاكرة")]


# ==================================================================
# التصميم (CSS)
# ==================================================================
CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Tajawal:wght@400;500;700;800&display=swap');

:root {
  --bg: #0f172a;
  --card: #1e293b;
  --card-soft: #172135;
  --sidebar: #0b1222;
  --border: #334155;
  --border-soft: rgba(148, 163, 184, .18);
  --text: #e2e8f0;
  --muted: #94a3b8;
  --faint: #64748b;
  --accent: #8b5cf6;
  --accent-2: #06b6d4;
  --accent-soft: rgba(139, 92, 246, .16);
}

/* ---------- الخط والاتجاه ---------- */
html, body, .stApp, .stApp button, .stApp input, .stApp textarea, .stApp select,
[data-testid="stMarkdownContainer"], [data-testid="stSidebar"], [data-testid="stToast"] {
  font-family: 'Tajawal', 'Segoe UI', Tahoma, sans-serif;
}
.stApp { background: var(--bg); color: var(--text); direction: rtl; }
[data-testid="stHeader"] { background: transparent; }
[data-testid="stAppDeployButton"], [data-testid="stDecoration"], footer { display: none !important; }
.block-container, [data-testid="stMainBlockContainer"] {
  padding-top: 2.2rem; padding-bottom: 4rem; max-width: 1240px;
}
[data-testid="stMarkdownContainer"] { text-align: right; }
[data-testid="stMarkdownContainer"] ul, [data-testid="stMarkdownContainer"] ol {
  padding-right: 1.4rem; padding-left: 0;
}
[data-testid="stMarkdownContainer"] pre, [data-testid="stMarkdownContainer"] code, .stCode {
  direction: ltr; text-align: left; unicode-bidi: isolate;
}
[data-testid="stMarkdownContainer"] table { direction: rtl; }
[data-testid="stWidgetLabel"] { text-align: right; }
[data-testid="stHeaderActionElements"] { display: none !important; }
/* عناصر تعتمد على اتجاه LTR داخلياً */
.stSlider > div, iframe, [data-testid="stDataFrame"], [data-testid="stDataFrameResizable"] { direction: ltr; }
.stSlider [data-testid="stWidgetLabel"] { direction: rtl; }

/* ---------- الشريط الجانبي ---------- */
[data-testid="stSidebar"] {
  background: var(--sidebar) !important;
  border-left: 1px solid var(--border);
  border-right: 1px solid var(--border);
  box-shadow: 0 0 40px rgba(0, 0, 0, .35);
}
[data-testid="stSidebar"] > div, [data-testid="stSidebarContent"] { background: var(--sidebar) !important; }
/* الشريط على اليمين (RTL): عند الطيّ نخفيه بدلاً من إزاحته فوق المحتوى */
[data-testid="stSidebar"][aria-expanded="false"] { transform: none !important; visibility: hidden; }
[data-testid="stSidebar"] div[role="radiogroup"] { gap: .35rem; width: 100%; }
[data-testid="stSidebar"] div[role="radiogroup"] > label {
  width: 100%; margin: 0; padding: .7rem .85rem; border-radius: 12px;
  border: 1px solid transparent; background: transparent; transition: all .15s ease; cursor: pointer;
}
[data-testid="stSidebar"] div[role="radiogroup"] > label:hover {
  background: rgba(139, 92, 246, .08); border-color: var(--border);
}
[data-testid="stSidebar"] div[role="radiogroup"] > label:has(input:checked) {
  background: linear-gradient(90deg, rgba(139, 92, 246, .26), rgba(6, 182, 212, .12));
  border-color: rgba(139, 92, 246, .6);
}
[data-testid="stSidebar"] div[role="radiogroup"] > label > div:first-child { display: none; }
[data-testid="stSidebar"] div[role="radiogroup"] > label p { font-size: 1rem; font-weight: 600; }

/* ---------- الأزرار ---------- */
[data-testid="stElementContainer"]:has(> .stButton),
[data-testid="stElementContainer"]:has(> .stDownloadButton),
[data-testid="stElementContainer"]:has(> .stFormSubmitButton),
.stButton, .stDownloadButton, .stFormSubmitButton { width: 100% !important; }
.stButton > button, .stDownloadButton > button, .stFormSubmitButton > button {
  width: 100%; min-height: 2.65rem; border-radius: 12px; font-weight: 700;
  padding-left: .6rem; padding-right: .6rem; line-height: 1.5; height: auto;
  border: 1px solid var(--border); background: var(--card); color: var(--text);
  transition: all .15s ease;
}
.stButton > button:hover, .stDownloadButton > button:hover, .stFormSubmitButton > button:hover {
  border-color: var(--accent); color: #fff; transform: translateY(-1px);
}
.stButton > button[kind="primary"], .stDownloadButton > button[kind="primary"],
.stFormSubmitButton > button[kind="primaryFormSubmit"],
button[data-testid="stBaseButton-primary"], button[data-testid="stBaseButton-primaryFormSubmit"] {
  background: linear-gradient(135deg, #8b5cf6, #6366f1); border: none; color: #fff;
  box-shadow: 0 6px 18px rgba(99, 102, 241, .28);
}

/* ---------- الحقول والعناصر ---------- */
[data-baseweb="input"], [data-baseweb="textarea"], [data-baseweb="select"] > div, [data-baseweb="base-input"] {
  border-radius: 12px !important;
}
[data-baseweb="input"], [data-baseweb="textarea"], [data-baseweb="select"] > div {
  background: var(--bg) !important; border: 1px solid var(--border) !important;
}
[data-baseweb="input"]:focus-within, [data-baseweb="textarea"]:focus-within { border-color: var(--accent) !important; }
[data-testid="stForm"] {
  background: var(--card); border: 1px solid var(--border-soft); border-radius: 20px; padding: 1.4rem;
}
[data-testid="stExpander"] details {
  background: var(--card); border: 1px solid var(--border-soft); border-radius: 16px;
}
[data-testid="stExpander"] summary:hover { color: #c4b5fd; }
[data-testid="stFileUploaderDropzone"] {
  background: var(--card-soft); border: 2px dashed #475569; border-radius: 16px;
}
/* أسماء الملفات العربية تُعرض بترتيبها الصحيح (الاسم ثم .pdf) */
[data-testid="stFileUploaderFileName"] { direction: ltr; unicode-bidi: isolate; text-align: right; }
[data-testid="stFileUploaderFile"] small { margin-inline-start: .5rem; }
/* تعريب نصوص أداة رفع الملفات */
[data-testid="stFileUploaderDropzoneInstructions"] > div > span { display: none; }
[data-testid="stFileUploaderDropzoneInstructions"] > div::before {
  content: "اسحب الملف وأفلته هنا"; display: block; font-weight: 700; color: var(--text);
}
[data-testid="stFileUploaderDropzoneInstructions"] > div::after {
  content: "أو اضغط زر التصفّح لاختيار ملف من جهازك"; display: block; font-size: .82rem; color: var(--muted);
}
[data-testid="stFileUploaderDropzone"] button { font-size: 0 !important; }
[data-testid="stFileUploaderDropzone"] button::after { content: "تصفّح الملفات"; font-size: .9rem; }
[data-testid="stVerticalBlockBorderWrapper"]:has(> div > [data-testid="stVerticalBlock"]) { border-radius: 18px; }
.stTabs [data-baseweb="tab-list"] { gap: .4rem; }
.stTabs [data-baseweb="tab"] { border-radius: 10px 10px 0 0; padding: .4rem 1rem; }
[data-testid="stAlert"] { border-radius: 14px; }
div[role="radiogroup"] { gap: .3rem .6rem; }
[data-testid="stProgress"] > div > div > div > div { background: linear-gradient(90deg, #8b5cf6, #06b6d4); }

/* ---------- الدردشة ---------- */
[data-testid="stChatMessage"] {
  background: var(--card); border: 1px solid var(--border-soft); border-radius: 18px;
  padding: 1rem 1.15rem; margin-bottom: .7rem;
}
[data-testid="stChatMessage"] [data-testid="stMarkdownContainer"] { line-height: 1.9; }
[data-testid="stBottom"] > div, [data-testid="stBottomBlockContainer"] { background: var(--bg); }
[data-testid="stChatInput"] { border-radius: 16px; }
[data-testid="stChatInput"] textarea { direction: rtl; text-align: right; }

/* ---------- مكونات Vita ---------- */
.vita-hero {
  display: flex; align-items: center; gap: 1.1rem; padding: 1.3rem 1.5rem; margin-bottom: 1.4rem;
  background: linear-gradient(135deg, rgba(139, 92, 246, .20), rgba(6, 182, 212, .08)), var(--card);
  border: 1px solid var(--border-soft); border-radius: 22px;
}
.vita-hero-icon {
  width: 60px; height: 60px; flex-shrink: 0; border-radius: 18px; display: grid; place-items: center;
  font-size: 1.9rem; background: rgba(15, 23, 42, .6); border: 1px solid var(--border-soft);
}
.vita-hero-tag {
  display: inline-block; direction: ltr; font-size: .74rem; font-weight: 700; letter-spacing: .04em;
  color: #c4b5fd; background: var(--accent-soft); padding: .12rem .65rem; border-radius: 999px; margin-bottom: .3rem;
}
.vita-hero-title { font-size: 1.75rem; font-weight: 800; color: #f8fafc; line-height: 1.35; }
.vita-hero-sub { color: var(--muted); font-size: .98rem; margin-top: .1rem; }

.vita-card {
  background: var(--card); border: 1px solid var(--border-soft); border-radius: 18px;
  padding: 1.1rem 1.25rem; margin-bottom: 1rem;
}
.vita-section {
  display: flex; align-items: center; gap: .5rem; font-size: 1.12rem; font-weight: 800;
  color: #f1f5f9; margin: .3rem 0 .8rem;
}
.vita-muted { color: var(--muted); }
.vita-chips { display: flex; flex-wrap: wrap; gap: .45rem; align-items: center; }
.vita-chip {
  display: inline-flex; align-items: center; gap: .4rem; background: var(--card);
  border: 1px solid var(--border-soft); border-radius: 999px; padding: .28rem .8rem;
  font-size: .85rem; color: #cbd5e1;
}
.vita-dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; }
.vita-ltr { direction: ltr; unicode-bidi: isolate; }

/* إحصائيات */
.vita-stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(165px, 1fr)); gap: .8rem; margin: .2rem 0 1.3rem; }
.vita-stat { background: var(--card); border: 1px solid var(--border-soft); border-radius: 16px; padding: 1rem 1.1rem; }
.vita-stat-icon {
  width: 40px; height: 40px; border-radius: 12px; display: grid; place-items: center; font-size: 1.25rem;
  background: rgba(148, 163, 184, .10);
}
.vita-stat-value { font-size: 1.85rem; font-weight: 800; color: #f8fafc; margin-top: .6rem; line-height: 1.1; }
.vita-stat-label { color: var(--muted); font-size: .9rem; margin-top: .25rem; }

/* الشريط الجانبي */
.vita-brand { display: flex; align-items: center; gap: .75rem; padding: .1rem .1rem 1rem; margin-bottom: 1rem; border-bottom: 1px solid var(--border); }
.vita-logo {
  width: 46px; height: 46px; border-radius: 14px; display: grid; place-items: center; flex-shrink: 0;
  background: linear-gradient(135deg, #8b5cf6, #06b6d4); color: #fff; font-weight: 800; font-size: 1.45rem;
  box-shadow: 0 8px 24px rgba(139, 92, 246, .35);
}
.vita-brand-name { font-size: 1.5rem; font-weight: 800; color: #f8fafc; line-height: 1.1; }
.vita-brand-sub { font-size: .8rem; color: var(--muted); }
.vita-user {
  display: flex; align-items: center; gap: .7rem; padding: .7rem; margin-bottom: 1rem;
  background: var(--card); border: 1px solid var(--border-soft); border-radius: 14px;
}
.vita-avatar {
  border-radius: 50%; display: grid; place-items: center; flex-shrink: 0; object-fit: cover;
  background: linear-gradient(135deg, #312e81, #0e7490); border: 2px solid rgba(255, 255, 255, .14);
}
.vita-user-name { font-weight: 700; color: #f1f5f9; line-height: 1.3; }
.vita-user-handle { font-size: .8rem; color: var(--muted); }
.vita-side-label { font-size: .76rem; color: var(--faint); font-weight: 700; margin: .2rem .3rem .5rem; }
.vita-mini-stats { display: grid; grid-template-columns: repeat(3, 1fr); gap: .45rem; margin: 1.1rem 0 .8rem; }
.vita-mini { background: var(--card); border: 1px solid var(--border-soft); border-radius: 12px; padding: .55rem .3rem; text-align: center; }
.vita-mini b { display: block; font-size: 1.15rem; color: #f8fafc; }
.vita-mini span { font-size: .72rem; color: var(--muted); }
.vita-status {
  font-size: .83rem; color: #cbd5e1; background: var(--card); border: 1px solid var(--border-soft);
  border-radius: 12px; padding: .55rem .75rem; margin-bottom: .8rem; line-height: 1.7;
}
.vita-side-footer { text-align: center; font-size: .75rem; color: var(--faint); margin-top: 1rem; }

/* صفحة الدخول */
.vita-login-brand { text-align: center; margin: 2vh 0 1.3rem; }
.vita-login-logo {
  width: 78px; height: 78px; margin: 0 auto .8rem; border-radius: 24px; display: grid; place-items: center;
  background: linear-gradient(135deg, #8b5cf6, #06b6d4); color: #fff; font-size: 2.3rem; font-weight: 800;
  box-shadow: 0 14px 40px rgba(139, 92, 246, .4);
}
.vita-login-title {
  font-size: 2.6rem; font-weight: 800; line-height: 1.2;
  background: linear-gradient(135deg, #c4b5fd, #67e8f9); -webkit-background-clip: text; background-clip: text; color: transparent;
}
.vita-login-sub { color: var(--muted); font-size: 1.02rem; }
.vita-or { display: flex; align-items: center; gap: .8rem; color: var(--faint); margin: 1rem 0; font-size: .85rem; }
.vita-or::before, .vita-or::after { content: ""; flex: 1; height: 1px; background: var(--border); }
.vita-features { display: grid; grid-template-columns: repeat(auto-fit, minmax(92px, 1fr)); gap: .5rem; margin-top: 1.4rem; }
.vita-feature {
  background: var(--card); border: 1px solid var(--border-soft); border-radius: 14px;
  padding: .75rem .35rem; text-align: center; font-size: .78rem; color: var(--muted);
}
.vita-feature div { font-size: 1.45rem; margin-bottom: .25rem; }
.vita-note { text-align: center; color: var(--faint); font-size: .8rem; margin-top: 1rem; }

/* الدردشة - ترحيب */
.vita-welcome { text-align: center; padding: 1.6rem 1rem .6rem; }
.vita-welcome .vita-login-logo { width: 64px; height: 64px; font-size: 1.9rem; border-radius: 20px; }
.vita-welcome-title { font-size: 1.5rem; font-weight: 800; color: #f8fafc; }
.vita-welcome-sub { color: var(--muted); margin-top: .3rem; }

/* الملف الشخصي */
.vita-profile { background: var(--card); border: 1px solid var(--border-soft); border-radius: 22px; overflow: hidden; margin-bottom: 1.2rem; }
.vita-cover {
  height: 140px;
  background:
    radial-gradient(circle at 15% 30%, rgba(6, 182, 212, .55), transparent 45%),
    radial-gradient(circle at 85% 10%, rgba(139, 92, 246, .75), transparent 50%),
    linear-gradient(135deg, #1e1b4b, #0f172a);
}
.vita-profile-body { display: flex; gap: 1.3rem; padding: 0 1.6rem 1.5rem; flex-wrap: wrap; align-items: flex-start; }
.vita-profile-avatar { margin-top: -54px; }
.vita-profile-avatar .vita-avatar { border: 4px solid var(--card); box-shadow: 0 10px 30px rgba(0, 0, 0, .4); }
.vita-profile-info { flex: 1; min-width: 240px; padding-top: .9rem; }
.vita-profile-name { font-size: 1.65rem; font-weight: 800; color: #f8fafc; line-height: 1.3; }
.vita-profile-handle { color: var(--muted); font-size: .92rem; }
.vita-bio { color: #cbd5e1; margin-top: .6rem; line-height: 1.85; white-space: pre-wrap; }
.vita-profile-meta { display: flex; gap: .45rem; flex-wrap: wrap; margin-top: .8rem; }
.vita-level { min-width: 220px; padding-top: 1rem; }
.vita-badge {
  display: inline-block; padding: .35rem .9rem; border-radius: 999px; font-weight: 700; color: #fff;
  background: linear-gradient(135deg, #8b5cf6, #06b6d4);
}
.vita-bar { height: 8px; background: #0f172a; border-radius: 999px; overflow: hidden; margin-top: .55rem; }
.vita-bar span { display: block; height: 100%; border-radius: 999px; background: linear-gradient(90deg, #8b5cf6, #06b6d4); }
.vita-level small { color: var(--muted); display: block; margin-top: .35rem; }

/* سجل النشاط */
.vita-tl-item { display: flex; gap: .7rem; align-items: flex-start; padding: .55rem .1rem; border-bottom: 1px dashed rgba(148, 163, 184, .15); }
.vita-tl-item:last-child { border-bottom: none; }
.vita-tl-icon { width: 34px; height: 34px; border-radius: 10px; flex-shrink: 0; display: grid; place-items: center; background: rgba(148, 163, 184, .10); }
.vita-tl-text { color: #e2e8f0; font-size: .93rem; line-height: 1.5; }
.vita-tl-time { color: var(--faint); font-size: .78rem; }

/* المؤقت */
.vita-timer { position: relative; width: 240px; height: 240px; margin: .4rem auto 1rem; }
.vita-timer svg { width: 100%; height: 100%; }
.vita-timer-center { position: absolute; inset: 0; display: flex; flex-direction: column; align-items: center; justify-content: center; }
.vita-timer-time { direction: ltr; font-size: 3.1rem; font-weight: 800; color: #f8fafc; font-variant-numeric: tabular-nums; line-height: 1.1; }
.vita-timer-mode { color: var(--muted); font-size: .95rem; margin-top: .25rem; }

/* المستندات */
.vita-doc { display: flex; gap: 1rem; align-items: center; flex-wrap: wrap; }
.vita-doc-icon {
  width: 54px; height: 54px; border-radius: 16px; display: grid; place-items: center; font-size: 1.7rem; flex-shrink: 0;
  background: linear-gradient(135deg, rgba(139, 92, 246, .3), rgba(6, 182, 212, .2));
}
.vita-doc-name { font-weight: 800; color: #f8fafc; font-size: 1.05rem; word-break: break-all; }
.vita-preview {
  max-height: 260px; overflow-y: auto; white-space: pre-wrap; color: #cbd5e1; font-size: .9rem;
  line-height: 1.8; background: var(--card-soft); border-radius: 12px; padding: .9rem 1rem;
}
.vita-empty { text-align: center; padding: 1.8rem 1rem; }
.vita-empty-icon { font-size: 2.6rem; }
.vita-feature-row { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: .8rem; margin-top: 1rem; }
.vita-feature-row .vita-card { margin-bottom: 0; }
.vita-feature-row b { color: #f1f5f9; }

/* الاختبار التفاعلي */
.vita-q-title { font-weight: 700; color: #f1f5f9; line-height: 1.9; font-size: 1.02rem; margin: .2rem 0 .3rem; }
.vita-score {
  display: flex; align-items: center; gap: 1.3rem; padding: 1.1rem 1.3rem; margin-bottom: 1rem; border-radius: 18px;
  background: linear-gradient(135deg, rgba(139, 92, 246, .22), rgba(6, 182, 212, .10)), var(--card);
  border: 1px solid var(--border-soft);
}
.vita-score-num { font-size: 2.4rem; font-weight: 800; color: #f8fafc; white-space: nowrap; }
.vita-score-verdict { font-size: 1.1rem; font-weight: 800; color: #f1f5f9; }
.vita-q { background: var(--card-soft); border: 1px solid var(--border-soft); border-radius: 16px; padding: .9rem 1.1rem; margin-bottom: .8rem; }
.vita-q.ok { border-color: rgba(34, 197, 94, .55); }
.vita-q.bad { border-color: rgba(239, 68, 68, .55); }
.vita-q.skip { border-color: rgba(245, 158, 11, .5); }
.vita-q-head { display: flex; justify-content: space-between; align-items: flex-start; gap: .8rem; margin-bottom: .4rem; }
.vita-q-badge { font-size: .82rem; font-weight: 700; white-space: nowrap; color: #e2e8f0; }
.vita-opt {
  display: flex; justify-content: space-between; gap: .6rem; padding: .45rem .8rem; margin: .3rem 0;
  border-radius: 10px; border: 1px solid rgba(148, 163, 184, .14); color: #cbd5e1;
}
.vita-opt.correct { background: rgba(34, 197, 94, .14); border-color: rgba(34, 197, 94, .6); color: #dcfce7; }
.vita-opt.wrong { background: rgba(239, 68, 68, .14); border-color: rgba(239, 68, 68, .6); color: #fee2e2; }
.vita-opt small { font-weight: 700; opacity: .9; white-space: nowrap; }
.vita-explain { margin-top: .55rem; color: var(--muted); font-size: .9rem; line-height: 1.8; }

@media (max-width: 760px) {
  .vita-hero { padding: 1rem; }
  .vita-hero-title { font-size: 1.35rem; }
}
</style>
"""


# ==================================================================
# أدوات مساعدة عامة
# ==================================================================
def esc(value):
    return html.escape("" if value is None else str(value))


def stretch_kwargs(func):
    """يعيد وسيط ملء العرض المناسب لإصدار Streamlit المثبّت."""
    try:
        params = inspect.signature(func).parameters
    except (TypeError, ValueError):
        return {}
    width = params.get("width")
    if width is not None and isinstance(width.default, str):
        return {"width": "stretch"}
    if "use_container_width" in params:
        return {"use_container_width": True}
    return {}


def html_block(markup):
    st.markdown(markup, unsafe_allow_html=True)


def hash_password(username, password):
    return hashlib.sha256(f"vita::{username}::{password}".encode("utf-8")).hexdigest()


def time_ago(moment):
    seconds = int((datetime.now() - moment).total_seconds())
    if seconds < 60:
        return "الآن"
    if seconds < 3600:
        return f"منذ {seconds // 60} دقيقة"
    if seconds < 86400:
        return f"منذ {seconds // 3600} ساعة"
    return moment.strftime("%Y/%m/%d")


def format_duration(seconds):
    minutes = int(seconds) // 60
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}س {minutes}د"
    return f"{minutes}د"


def avatar_html(profile, size=48):
    if profile.get("avatar_img"):
        return (
            f'<img class="vita-avatar" src="{profile["avatar_img"]}" '
            f'style="width:{size}px;height:{size}px" alt="avatar"/>'
        )
    return (
        f'<div class="vita-avatar" style="width:{size}px;height:{size}px;'
        f'font-size:{int(size * 0.52)}px">{esc(profile.get("avatar", "🎓"))}</div>'
    )


def page_header(icon, title, tag, subtitle):
    html_block(
        f'<div class="vita-hero"><div class="vita-hero-icon">{icon}</div><div>'
        f'<div class="vita-hero-tag">{esc(tag)}</div>'
        f'<div class="vita-hero-title">{esc(title)}</div>'
        f'<div class="vita-hero-sub">{esc(subtitle)}</div></div></div>'
    )


def section_title(text):
    html_block(f'<div class="vita-section">{esc(text)}</div>')


def stat_tiles(items):
    """items: [(icon, value, label, tint)]"""
    tiles = "".join(
        f'<div class="vita-stat"><div class="vita-stat-icon" style="background:{tint}">{icon}</div>'
        f'<div class="vita-stat-value">{esc(value)}</div><div class="vita-stat-label">{esc(label)}</div></div>'
        for icon, value, label, tint in items
    )
    html_block(f'<div class="vita-stats">{tiles}</div>')


# ==================================================================
# الحالة والجلسة (Session State) + نظام الدخول التجريبي
# ==================================================================
def day_name(d):
    return WEEKDAY_AR[d.weekday()]


def to_iso_date(value):
    """يحوّل أي قيمة تاريخ (date/Timestamp/نص) إلى نص YYYY-MM-DD، أو None إن كانت فارغة."""
    if value is None or (isinstance(value, float) and math.isnan(value)) or value is pd.NaT:
        return None
    if isinstance(value, (datetime, pd.Timestamp)):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    try:
        return date.fromisoformat(str(value).strip()[:10]).isoformat()
    except ValueError:
        return None


def date_label(iso):
    """طريقة عرض التاريخ في قائمة الاختيار: «الأربعاء 21/10/2026»."""
    d = date.fromisoformat(iso)
    return f"{day_name(d)} {d:%d/%m/%Y}"


def tidy_sheet(df):
    """يوحّد أنواع أعمدة الجدول، ويملأ اليوم تلقائياً من التاريخ."""
    df = df.reindex(columns=SHEET_COLUMNS).reset_index(drop=True)

    def blank(value):
        return value is None or (isinstance(value, float) and math.isnan(value))

    df[COL_DATE] = df[COL_DATE].map(to_iso_date).astype(object)
    df[COL_DAY] = df[COL_DATE].map(lambda iso: day_name(date.fromisoformat(iso)) if iso else None).astype(object)
    df[COL_HOURS] = pd.to_numeric(df[COL_HOURS], errors="coerce")
    df[COL_DONE] = df[COL_DONE].map(lambda v: False if blank(v) else bool(v)).astype(bool)
    for col in (COL_SUBJECT, COL_TASK):  # خلايا فارغة بدلاً من كلمة None
        df[col] = df[col].map(lambda v: "" if blank(v) else str(v)).astype(object)
    df[COL_PRIORITY] = df[COL_PRIORITY].map(lambda v: PRIORITIES[1] if blank(v) else str(v)).astype(object)
    return df


def sample_sheet():
    today = date.today()
    rows = [
        ("الرياضيات", "مراجعة التفاضل والتكامل", 0, 2.0, PRIORITIES[0], True),
        ("الفيزياء", "حل مسائل قوانين نيوتن", 1, 1.5, PRIORITIES[0], False),
        ("الكيمياء", "تلخيص الجدول الدوري", 2, 1.0, PRIORITIES[1], False),
        ("اللغة الإنجليزية", "قراءة نص وحفظ مفردات جديدة", 3, 1.0, PRIORITIES[2], False),
        ("الأحياء", "خريطة ذهنية لانقسام الخلية", 4, 1.5, PRIORITIES[1], False),
    ]
    data = [
        {
            COL_SUBJECT: subject,
            COL_TASK: task,
            COL_DATE: (today + timedelta(days=offset)).isoformat(),
            COL_HOURS: hours,
            COL_PRIORITY: priority,
            COL_DONE: done,
        }
        for subject, task, offset, hours, priority, done in rows
    ]
    return tidy_sheet(pd.DataFrame(data))


def empty_sheet():
    return tidy_sheet(pd.DataFrame(columns=SHEET_COLUMNS))


def new_user_data(username, password, display_name=None):
    return {
        "username": username,
        "password": hash_password(username.lower(), password),
        "profile": {
            "name": display_name or username,
            "bio": "طالب طموح يستخدم Vita لتنظيم مذاكرته وتحقيق أهدافه الدراسية 🚀",
            "major": "",
            "avatar": "🎓",
            "avatar_img": None,
            "avatar_bytes": None,
            "joined": datetime.now(),
        },
        "stats": {
            "chats": 0,
            "messages": 0,
            "files": 0,
            "pomodoros": 0,
            "focus_seconds": 0,
            "boards": 0,
            "sheets": 0,
            "logins": 0,
        },
        "activity": [],
        "messages": [],
        "sheet": sample_sheet(),
        "sheet_v": 0,
        "board_saved": None,
        "board_live": None,
        "board_v": 0,
        "notebook": {},
        "processed_files": [],
        "pomo": {
            "mode": "focus",
            "minutes": {k: v["minutes"] for k, v in POMO_MODES.items()},
            "duration": POMO_MODES["focus"]["minutes"] * 60,
            "remaining": POMO_MODES["focus"]["minutes"] * 60,
            "running": False,
            "end_time": None,
            "history": [],
        },
    }


def init_state():
    ss = st.session_state
    ss.setdefault("users", {})
    ss.setdefault("current_user", None)
    ss.setdefault("page", "chat")
    ss.setdefault("flash", [])


def U():
    return st.session_state.users[st.session_state.current_user]


def flash(message, icon="✅", balloons=False):
    st.session_state.flash.append((message, icon, balloons))


def show_flash():
    pending = st.session_state.get("flash", [])
    st.session_state.flash = []
    for message, icon, balloons in pending:
        st.toast(message, icon=icon)
        if balloons:
            st.balloons()


def log_activity(icon, text):
    activity = U()["activity"]
    activity.insert(0, {"icon": icon, "text": text, "time": datetime.now()})
    del activity[60:]


def start_session(key, message):
    st.session_state.current_user = key
    st.session_state.page = "chat"
    U()["stats"]["logins"] += 1
    log_activity("🔐", "تسجيل الدخول إلى Vita")
    flash(message, icon="👋")
    st.rerun()


def do_login(username, password):
    username = (username or "").strip()
    if not username or not password:
        st.error("الرجاء إدخال اسم المستخدم وكلمة المرور.", icon="⚠️")
        return
    if len(username) < 3:
        st.error("اسم المستخدم يجب أن يتكوّن من 3 أحرف على الأقل.", icon="⚠️")
        return
    key = username.lower()
    users = st.session_state.users
    if key in users:
        if users[key]["password"] != hash_password(key, password):
            st.error("كلمة المرور غير صحيحة لهذا الحساب.", icon="🔒")
            return
        start_session(key, f"أهلاً بعودتك يا {users[key]['profile']['name']}!")
    else:
        users[key] = new_user_data(username, password)
        start_session(key, f"تم إنشاء حسابك بنجاح، مرحباً بك يا {username}!")


def demo_login():
    key = "demo"
    users = st.session_state.users
    if key not in users:
        data = new_user_data("demo", "demo", display_name="طالب Vita التجريبي")
        data["profile"].update(
            {
                "avatar": "🦉",
                "major": "طالب ثانوي – المسار العلمي",
                "bio": "أحب الفيزياء والبرمجة 💡 أستخدم Vita لتلخيص دروسي وتنظيم جدول مذاكرتي والتركيز بتقنية بومودورو.",
            }
        )
        users[key] = data
    start_session(key, "مرحباً بك في الحساب التجريبي لـ Vita ✨")


def snapshot_workspace():
    """يحفظ رسم السبورة قبل مغادرة الصفحة (تعديلات الجدول تُحفظ فور حدوثها)."""
    if not st.session_state.get("current_user"):
        return
    u = U()
    if u.get("board_live") is not None:
        u["board_saved"] = u["board_live"]


def on_nav_change():
    snapshot_workspace()


def logout():
    snapshot_workspace()
    log_activity("🚪", "تسجيل الخروج")
    st.session_state.current_user = None
    st.session_state.pop("pending_prompt", None)
    flash("تم تسجيل الخروج بنجاح. نراك قريباً!", icon="👋")


# ==================================================================
# Gemini REST API مع البث المباشر (Streaming)
# ==================================================================
class VitaError(Exception):
    pass


def read_secret(name, default=""):
    try:
        value = st.secrets[name]
    except Exception:
        value = os.environ.get(name, default)
    return str(value or "").strip()


def get_api_key():
    return read_secret("GEMINI_API_KEY")


def configured_model():
    return read_secret("GEMINI_MODEL") or DEFAULT_MODEL


def model_candidates():
    ordered = [st.session_state.get("active_model"), configured_model()] + FALLBACK_MODELS
    seen, result = set(), []
    for model in ordered:
        if model and model not in seen:
            seen.add(model)
            result.append(model)
    return result


def api_error_message(resp):
    message = ""
    try:
        message = resp.json().get("error", {}).get("message", "")
    except ValueError:
        message = resp.text[:300]
    if resp.status_code in (401, 403) or "API key" in message:
        return "مفتاح Gemini API غير صالح أو لا يملك الصلاحية. تحقق من قيمة GEMINI_API_KEY في إعدادات الخادم."
    if resp.status_code == 429:
        return "تم تجاوز حد الاستخدام المسموح لمفتاح الـ API مؤقتاً. انتظر قليلاً ثم أعد المحاولة."
    if resp.status_code >= 500:
        return "خادم Gemini مشغول حالياً، حاول مرة أخرى بعد لحظات."
    return f"خطأ من Gemini ({resp.status_code}): {message}"


def iter_sse_text(lines):
    """يحلل أسطر Server-Sent Events القادمة من Gemini ويعيد النصوص فقط."""
    for raw in lines:
        if not raw:
            continue
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="replace")
        line = raw.strip()
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if not payload or payload == "[DONE]":
            continue
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            continue
        if "error" in data:
            raise VitaError(data["error"].get("message", "حدث خطأ غير معروف من Gemini."))
        if (data.get("promptFeedback") or {}).get("blockReason"):
            raise VitaError("تم حجب الطلب بواسطة فلاتر الأمان. حاول إعادة صياغة سؤالك.")
        for candidate in data.get("candidates") or []:
            for part in (candidate.get("content") or {}).get("parts") or []:
                if part.get("thought"):
                    continue
                text = part.get("text")
                if text:
                    yield text


def gemini_stream(contents, system_instruction=SYSTEM_INSTRUCTION, temperature=0.7):
    api_key = get_api_key()
    if not api_key:
        raise VitaError(NO_KEY_MSG)

    payload = {
        "contents": contents,
        "systemInstruction": {"parts": [{"text": system_instruction}]},
        "generationConfig": {"temperature": temperature},
    }
    headers = {"x-goog-api-key": api_key, "Content-Type": "application/json"}
    missing = []
    for model in model_candidates():
        try:
            resp = requests.post(
                f"{API_BASE}/{model}:streamGenerateContent",
                params={"alt": "sse"},
                headers=headers,
                json=payload,
                stream=True,
                timeout=(10, 180),
            )
        except requests.exceptions.RequestException:
            raise VitaError("تعذّر الاتصال بخادم Gemini. تحقق من اتصال الإنترنت ثم أعد المحاولة.")

        if resp.status_code == 404:
            missing.append(model)
            resp.close()
            continue
        if resp.status_code != 200:
            message = api_error_message(resp)
            resp.close()
            raise VitaError(message)

        st.session_state.active_model = model
        try:
            yield from iter_sse_text(resp.iter_lines())
        except requests.exceptions.RequestException:
            raise VitaError("انقطع الاتصال أثناء استقبال الإجابة. حاول مرة أخرى.")
        finally:
            resp.close()
        return

    raise VitaError("لم يتم العثور على نموذج متاح من Gemini. النماذج التي جُرّبت: " + "، ".join(missing))


# ---------------- خدمة مجانية بدون مفتاح (Pollinations) ----------------
def to_openai_messages(contents, system_instruction):
    messages = [{"role": "system", "content": system_instruction}]
    for item in contents:
        text = "".join(part.get("text", "") for part in item["parts"])
        messages.append({"role": "assistant" if item["role"] == "model" else "user", "content": text})
    return messages


def iter_openai_sse(lines):
    """يحلل بث الخدمة المجانية (صيغة OpenAI) ويعيد نص الإجابة فقط دون خطوات التفكير."""
    for raw in lines:
        if not raw:
            continue
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="replace")
        line = raw.strip()
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if payload == "[DONE]":
            return
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            continue
        if data.get("error"):
            err = data["error"]
            raise VitaError(err.get("message", "حدث خطأ أثناء تجهيز الإجابة.") if isinstance(err, dict) else str(err))
        for choice in data.get("choices") or []:
            text = (choice.get("delta") or {}).get("content")
            if text:
                yield text


def retry_after_seconds(resp):
    match = re.search(r"(?:after|wait)\s+(\d+)", resp.text or "", re.IGNORECASE)
    return int(match.group(1)) + 1 if match else 31


def free_stream(contents, system_instruction, status):
    payload = {
        "model": FREE_MODEL,
        "messages": to_openai_messages(contents, system_instruction),
        "stream": True,
        # النموذج المجاني «يفكّر» طويلاً قبل الإجابة وقد يُقطع رده؛ تفكير أقل وحدّ أعلى للإجابة = رد أسرع وكامل
        "reasoning_effort": "low",
        "max_tokens": 4000,
    }
    for attempt in range(2):
        try:
            resp = requests.post(FREE_API_URL, json=payload, stream=True, timeout=(10, 60))
        except requests.exceptions.RequestException:
            raise VitaError("تعذّر الاتصال، تحقق من الإنترنت ثم أعد المحاولة.")

        # الحد المجاني: رد واحد كل 30 ثانية تقريباً → ننتظر مرة واحدة ثم نعيد المحاولة
        if resp.status_code in (402, 429) and attempt == 0:
            wait = retry_after_seconds(resp)
            resp.close()
            if wait > FREE_MAX_WAIT:
                raise VitaError("Vita مشغول حالياً، أعد المحاولة بعد قليل.")
            for left in range(wait, 0, -1):
                status.info(f"Vita مشغول قليلاً — سيُرسل سؤالك خلال {left} ثانية...", icon="⏳")
                time.sleep(1)
            status.markdown("💭 *Vita يفكر...*")
            continue
        if resp.status_code != 200:
            resp.close()
            raise VitaError("Vita غير متاح الآن، أعد المحاولة بعد قليل.")

        try:
            yield from iter_openai_sse(resp.iter_lines())
        except requests.exceptions.RequestException:
            raise VitaError("انقطع الاتصال أثناء الإجابة، أعد المحاولة.")
        finally:
            resp.close()
        return
    raise VitaError("Vita مشغول حالياً، أعد المحاولة بعد قليل.")


def ai_stream(contents, system_instruction, temperature, status, fallback=None):
    """Gemini (إن وُجد مفتاح) ← الخدمة المجانية ← الرد المحلي، حتى لا يتوقف العرض أبداً."""
    providers = []
    if get_api_key():
        providers.append(("gemini", lambda: gemini_stream(contents, system_instruction, temperature)))
    providers.append(("free", lambda: free_stream(contents, system_instruction, status)))

    last_error = None
    for name, start in providers:
        produced = False
        try:
            for chunk in start():
                if not produced:
                    produced = True
                    status.empty()
                    st.session_state.active_provider = name
                yield chunk
        except VitaError as err:
            if produced:
                raise
            last_error = str(err)
            continue
        if produced:
            return

    status.empty()
    if fallback is None:
        raise VitaError(last_error or "خدمة الذكاء الاصطناعي غير متاحة حالياً.")
    st.session_state.active_provider = "local"
    text = fallback()
    for i in range(0, len(text), 12):
        yield text[i : i + 12]


def typewriter(chunks, state):
    """يحوّل أجزاء البث إلى تدفق حرفاً بحرف مع التقاط الأخطاء."""
    try:
        for chunk in chunks:
            state["text"] += chunk
            if len(chunk) <= 6:  # أجزاء البث الصغيرة تظهر حرفاً بحرف أصلاً
                yield chunk
                continue
            step = math.ceil(len(chunk) / min(30, len(chunk) // 4))
            for i in range(0, len(chunk), step):
                yield chunk[i : i + step]
                time.sleep(0.01)
    except VitaError as err:
        state["error"] = str(err)


def stream_answer(contents, system_instruction=SYSTEM_INSTRUCTION, temperature=0.7, fallback=None):
    state = {"text": "", "error": None}
    status = st.empty()
    status.markdown("💭 *Vita يفكر...*")
    st.write_stream(
        typewriter(ai_stream(contents, system_instruction, temperature, status, fallback), state)
    )
    status.empty()
    if state["error"]:
        st.error(state["error"], icon="⚠️")
    return state["text"], state["error"]


def tidy_math(text):
    r"""يحوّل صيغ LaTeX من نوع \[ \] و \( \) إلى $$ $$ و $ $ التي يعرضها Streamlit."""
    text = re.sub(r"\\\[(.+?)\\\]", lambda m: "$$" + m.group(1).strip() + "$$", text, flags=re.S)
    return re.sub(r"\\\((.+?)\\\)", lambda m: "$" + m.group(1).strip() + "$", text, flags=re.S)


def build_contents(messages):
    contents = []
    for msg in messages:
        if msg.get("error"):
            continue
        role = "model" if msg["role"] == "assistant" else "user"
        if contents and contents[-1]["role"] == role:
            contents[-1]["parts"][0]["text"] += "\n\n" + msg["content"]
        else:
            contents.append({"role": role, "parts": [{"text": msg["content"]}]})
    contents = contents[-MAX_HISTORY_TURNS:]
    while contents and contents[0]["role"] != "user":
        contents.pop(0)
    return contents


# ==================================================================
# الوضع المحلي الاحتياطي (يعمل بدون إنترنت ولا مفتاح)
# ==================================================================
LOCAL_NOTE = (
    "\n\n---\n*⚡ رد من وضع العرض المحلي لأن خدمة الذكاء الاصطناعي غير متاحة الآن — "
    "أعد المحاولة بعد قليل للحصول على إجابة ذكية.*"
)
DOC_LOCAL_NOTE = (
    "> ⚡ أُنشئ هذا المحتوى محلياً (بدون ذكاء اصطناعي) لأن الخدمة الذكية غير متاحة الآن — "
    "أعد المحاولة بعد قليل للحصول على نتيجة أدق.\n\n"
)

NEWTON_ANSWER = """### ⚖️ قانون نيوتن الثاني
**الفكرة:** تسارع الجسم يتناسب طردياً مع القوة المؤثرة عليه، وعكسياً مع كتلته.

**الصيغة:** `F = m × a`
- **F** القوة (نيوتن)
- **m** الكتلة (كجم)
- **a** التسارع (م/ث²)

**🛒 مثال من الحياة اليومية:**
عندما تدفع عربة تسوّق فارغة تتحرك بسهولة وبسرعة، لكن إذا امتلأت بالأغراض تحتاج إلى قوة أكبر لتحصل على نفس التسارع، لأن الكتلة زادت.

**🧮 مثال حسابي:** دفعت صندوقاً كتلته 10 كجم بقوة 20 نيوتن، إذن التسارع = 20 ÷ 10 = **2 م/ث²**.

💡 **للمذاكرة:** احفظ العلاقة على شكل مثلث (F في الأعلى، و m و a في الأسفل) لتستخرج أي متغير بسهولة."""

PLAN_ANSWER = """### 📅 خطة مذاكرة لأسبوع الاختبارات

| اليوم | الصباح (ساعتان) | المساء (ساعة ونصف) |
|---|---|---|
| السبت | المادة الأصعب: قراءة وتلخيص | حل أسئلة سابقة |
| الأحد | المادة الثانية: فهم المفاهيم | مراجعة ملخص السبت |
| الاثنين | المادة الثالثة | اختبار ذاتي سريع |
| الثلاثاء | تمارين وحل مسائل | مراجعة الأخطاء |
| الأربعاء | مراجعة شاملة للمادة الأصعب | خرائط ذهنية |
| الخميس | اختبار تجريبي كامل | راحة خفيفة |
| الجمعة | مراجعة سريعة للملخصات | نوم مبكر 😴 |

**✅ قواعد ذهبية:**
1. ذاكر بنظام **بومودورو**: 25 دقيقة تركيز ثم 5 دقائق راحة.
2. ابدأ بالمادة **الأصعب** عندما يكون ذهنك صافياً.
3. حوّل كل درس إلى **أسئلة** واختبر نفسك بدلاً من إعادة القراءة.
4. نَم **7–8 ساعات**، فالنوم يثبّت المعلومات في الذاكرة.

💡 يمكنك نقل هذه الخطة إلى صفحة **📊 منشئ الجداول** وتعديلها حسب موادك."""

ESSAY_ANSWER = """### ✍️ كيف تكتب مقالاً علمياً قوياً؟

**1. المقدمة (10%)**
- ابدأ بجملة جاذبة أو حقيقة مدهشة.
- عرّف بالموضوع واذكر **الفكرة الرئيسية** بوضوح.

**2. العرض (80%)**
- خصّص **فقرة لكل فكرة**، وابدأها بجملة مفتاحية.
- ادعم كل فكرة **بدليل**: إحصائية أو تجربة أو مرجع موثوق.
- استخدم أدوات الربط: *علاوة على ذلك، في المقابل، نتيجة لذلك*.

**3. الخاتمة (10%)**
- لخّص الأفكار الرئيسية دون تكرار حرفي.
- اختم بتوصية أو سؤال يفتح آفاقاً جديدة.

**🔍 قبل التسليم:**
- راجع الإملاء وعلامات الترقيم.
- تأكد من توثيق المراجع.
- اقرأ المقال بصوت عالٍ لتكتشف الجمل الطويلة أو الغامضة."""

QUADRATIC_ANSWER = """### 🔢 حل معادلة تربيعية خطوة بخطوة

**المثال:** `x² − 5x + 6 = 0`

**الخطوة 1: حدّد المعاملات:** `a = 1` ، `b = −5` ، `c = 6`

**الخطوة 2: احسب المميز:** `Δ = b² − 4ac = 25 − 24 = 1`

بما أن **Δ أكبر من صفر**، فللمعادلة حلّان حقيقيان مختلفان.

**الخطوة 3: طبّق القانون العام:** `x = (−b ± √Δ) / 2a = (5 ± 1) / 2`

**الخطوة 4: استخرج الحلّين:**
- `x₁ = (5 + 1) / 2 = 3`
- `x₂ = (5 − 1) / 2 = 2`

**✅ التحقق:** عند التعويض بـ `x = 3` نحصل على `9 − 15 + 6 = 0` ✓

💡 **طريقة أسرع (التحليل):** ابحث عن عددين حاصل ضربهما 6 ومجموعهما −5، وهما −2 و −3، إذن `(x − 2)(x − 3) = 0`."""

POMODORO_ANSWER = """### 🍅 تقنية بومودورو للتركيز
1. اختر مهمة واحدة فقط.
2. اضبط المؤقت على **25 دقيقة** وركّز دون مقاطعة.
3. خذ استراحة قصيرة مدتها **5 دقائق**.
4. بعد 4 جلسات خذ استراحة طويلة **15–30 دقيقة**.

💡 جرّبها الآن من صفحة **👤 الملف الشخصي والإنتاجية**، فالمؤقت جاهز ويحسب جلساتك تلقائياً!"""

IDENTITY_ANSWER = """أنا **Vita** 👋، مساعدك الدراسي الذكي!

أستطيع مساعدتك في:
- 💬 شرح الدروس والإجابة عن أسئلتك.
- 📚 تلخيص ملفاتك وتحويلها إلى اختبارات وخرائط مفاهيم.
- 📊 تنظيم جدول مذاكرتك.
- ⏱️ التركيز بتقنية بومودورو."""

GREETING_ANSWER = (
    "أهلاً وسهلاً بك! 😊 أنا **Vita**، مساعدك الدراسي. اسألني عن أي درس، أو جرّب أحد الاقتراحات: "
    "قانون نيوتن، خطة مذاكرة، كتابة مقال، أو حل معادلة تربيعية."
)
THANKS_ANSWER = "العفو! 🌟 سعيد بمساعدتك. بالتوفيق في مذاكرتك، وأنا هنا متى احتجت أي شيء."

DEFAULT_ANSWER = """سؤال جميل! 🤔 لا أستطيع الإجابة بدقة عن «{q}» في هذه اللحظة لأن خدمة الذكاء الاصطناعي مشغولة، فأعد إرسال سؤالك بعد نصف دقيقة.

وفي هذه الأثناء، إليك طريقة فعّالة لمذاكرة أي موضوع:
1. **اقرأ الفكرة العامة** أولاً قبل التفاصيل.
2. **لخّص بكلماتك** في 3–5 نقاط.
3. **اختبر نفسك** بأسئلة قصيرة (جرّب صفحة 📚 مساعد المستندات).
4. **راجع بعد يوم ثم بعد أسبوع** (التكرار المتباعد).
5. **ركّز 25 دقيقة** باستخدام مؤقت بومودورو في صفحة 👤 الملف الشخصي."""

# (الكلمات المفتاحية، الرد، مطابقة الكلمة كاملة؟)
LOCAL_CHAT_RULES = [
    (("نيوتن", "newton"), NEWTON_ANSWER, False),
    (("خطة مذاكرة", "خطة للمذاكرة", "جدول مذاكرة", "أسبوع الاختبارات", "خطة دراسية"), PLAN_ANSWER, False),
    (("مقال",), ESSAY_ANSWER, False),
    (("تربيعية", "معادلة"), QUADRATIC_ANSWER, False),
    (("بومودورو", "pomodoro", "التركيز", "أركز"), POMODORO_ANSWER, False),
    (
        ("من أنت", "ما اسمك", "عرف بنفسك", "عرفني بنفسك", "مين انت", "وش اسمك", "ايش اسمك", "who are you", "your name"),
        IDENTITY_ANSWER,
        True,
    ),
    (("شكرا", "مشكور", "يعطيك العافية", "thanks", "thank you"), THANKS_ANSWER, True),
]
GREETING_WORDS = ("مرحبا", "السلام عليكم", "أهلا", "هلا", "hello", "hi", "صباح الخير", "مساء الخير")

AR_DIACRITICS = re.compile(r"[ً-ْٰـ]")
WORD_RE = re.compile(r"[A-Za-zء-يً-ْ]{3,}")
AR_STOPWORDS = """
من في على الى إلى عن ان أن إن كان كانت يكون تكون هذا هذه ذلك تلك هؤلاء التي الذي الذين او أو ثم ما ماذا
لا لم لن قد كل بعض هو هي هم هن نحن انت أنت انا أنا مع عند بين حتى اذا إذا كما اي أي به بها له لها لهم
فيه فيها منه منها عليه عليها عنه عنها وهو وهي يتم تم اكثر أكثر ايضا أيضا غير بعد قبل حيث لكن ولكن ذات مثل
هناك هنا خلال كيف متى لماذا هل عندما بينما ضمن نحو لدى منذ سوف اما أما وقد فقد لقد كذلك بسبب جدا يمكن
عدة احد أحد دون وفي ومن وعلى والتي والذي وهذا وهذه فهو فهي ليس ليست كانوا تكون يكونون الى عليهم
جميع داخل خارج لأن لأنها لأنه أنها أنه عليهما تحتوي يحتوي تتكون يتكون تقوم يقوم تعد يعد تعتبر يعتبر
تنتج ينتج اللازمة اللازم مسؤولة مسؤول باستخدام استخدام أيضاً بشكل خاصة عام عامة كبير كبيرة
the and for are with that this from into was were have has had not but you your they their its can will
also more than which about been when what how
""".split()


def normalize_ar(text):
    text = AR_DIACRITICS.sub("", text)
    for src, dst in (("أ", "ا"), ("إ", "ا"), ("آ", "ا"), ("ة", "ه"), ("ى", "ي")):
        text = text.replace(src, dst)
    return text.lower()


def strip_prefix(word):
    """يزيل حروف العطف والجر الملتصقة: والخلية / بالخلية / للخلية ← الخلية."""
    word = AR_DIACRITICS.sub("", word)
    for prefix in ("وال", "بال", "كال", "فال"):
        if word.startswith(prefix) and len(word) > 5:
            return word[1:]
    if word.startswith("لل") and len(word) > 4:
        return "ال" + word[2:]
    return word


def word_key(word):
    key = normalize_ar(strip_prefix(word))
    if key.startswith("ال") and len(key) > 4:
        key = key[2:]
    return key


STOP_KEYS = {word_key(w) for w in AR_STOPWORDS}


def shorten(text, max_words):
    words = text.split()
    return " ".join(words[:max_words]) + ("…" if len(words) > max_words else "")


def count_ar(n, one, two, few, many):
    """صياغة العدد بالعربية: مرة واحدة / مرتين / 3 مرات / 11 مرة."""
    if n == 1:
        return one
    if n == 2:
        return two
    if 3 <= n % 100 <= 10:
        return f"{n} {few}"
    return f"{n} {many}"


def attached_prefix(token):
    """حرف الجر أو العطف الملتصق بالكلمة ليبقى قبل الفراغ في الأسئلة: بالخلية ← بـ_____"""
    if token[:3] in ("وال", "بال", "كال", "فال"):
        return token[0] + "ـ"
    if token.startswith("لل"):
        return "لـ"
    return ""


def local_chat_answer(prompt):
    question = " " + " ".join(re.sub(r"[^\w\s]", " ", normalize_ar(prompt)).split()) + " "

    def mentions(keys, whole):
        if whole:
            return any(f" {normalize_ar(k)} " in question for k in keys)
        return any(normalize_ar(k) in question for k in keys)

    for keys, answer, whole in LOCAL_CHAT_RULES:
        if mentions(keys, whole):
            return answer + LOCAL_NOTE
    if len(prompt.split()) <= 5 and mentions(GREETING_WORDS, True):
        return GREETING_ANSWER + LOCAL_NOTE
    return DEFAULT_ANSWER.format(q=shorten(prompt, 12)) + LOCAL_NOTE


def split_sentences(text):
    parts = re.split(r"(?<=[.!؟?؛])\s+|\n+", text)
    sentences = [re.sub(r"\s+", " ", p).strip(" -•*\t") for p in parts]
    sentences = [s for s in sentences if len(s.split()) >= 4]
    words = text.split()
    if len(sentences) < 3 and len(words) > 60:  # نص بلا علامات ترقيم: نقسمه إلى مقاطع
        sentences = [" ".join(words[i : i + 20]) for i in range(0, len(words), 20)]
    return sentences


def analyze_document(text):
    sentences = split_sentences(text)
    counts, forms, sent_keys = Counter(), {}, []
    for sentence in sentences:
        keys = []
        for word in WORD_RE.findall(sentence):
            key = word_key(word)
            if len(key) < 3 or key in STOP_KEYS:
                continue
            counts[key] += 1
            forms.setdefault(key, Counter())[strip_prefix(word)] += 1
            keys.append(key)
        sent_keys.append(keys)
    best_forms = {k: v.most_common(1)[0][0] for k, v in forms.items()}

    def concept_score(key):
        # الأسماء المعرّفة (الخلية، النواة) والمصطلحات اللاتينية غالباً هي المفاهيم الأهم
        form = best_forms[key]
        return counts[key] * (1.5 if form.startswith("ال") or form.isascii() else 1.0)

    return {
        "sentences": sentences,
        "sent_keys": sent_keys,
        "counts": counts,
        "forms": best_forms,
        "keywords": sorted(counts, key=concept_score, reverse=True)[:40],
    }


def top_sentences(info, n):
    scored = []
    for i, (sentence, keys) in enumerate(zip(info["sentences"], info["sent_keys"])):
        if keys:
            score = sum(info["counts"][k] for k in set(keys)) / math.sqrt(len(sentence.split()))
            scored.append((score, i))
    best = sorted(sorted(scored, reverse=True)[:n], key=lambda item: item[1])
    return [info["sentences"][i] for _, i in best]


def local_summary(info):
    sentences, forms, counts = info["sentences"], info["forms"], info["counts"]
    if not sentences or not info["keywords"]:
        return None
    keywords = info["keywords"][:8]
    words = sum(len(s.split()) for s in sentences)
    lines = [
        "### 📝 الملخص التنفيذي",
        DOC_LOCAL_NOTE,
        "**🔎 نظرة عامة**",
        " ".join(shorten(s, 40) for s in sentences[:2]),
        "",
        "**📌 أهم النقاط**",
    ]
    lines += [f"- {shorten(s, 35)}" for s in top_sentences(info, 6)]
    lines += ["", "**🔑 المفاهيم الأساسية**"]
    lines += [
        f"- **{forms[k]}**: ورد {count_ar(counts[k], 'مرة واحدة', 'مرتين', 'مرات', 'مرة')} في المستند"
        for k in keywords
    ]
    lines += [
        "",
        "**📊 عن المستند**",
        f"- عدد الجمل: {len(sentences)}",
        f"- عدد الكلمات: {words:,}",
        f"- وقت القراءة التقديري: {max(1, round(words / 200))} دقيقة",
        "",
        "**💡 نصائح للمذاكرة**",
        f"- ابدأ بالمفاهيم الأكثر تكراراً: {'، '.join(forms[k] for k in keywords[:3])}.",
        "- حوّل كل نقطة من النقاط أعلاه إلى سؤال واختبر نفسك.",
        "- استخدم زر «❓ اختبار سريع» لتوليد أسئلة تدريبية من نفس الملف.",
    ]
    return "\n".join(lines)


QUIZ_LETTERS = ["أ", "ب", "ج", "د"]


def local_quiz_data(info, n_questions, difficulty, seed):
    """اختبار محلي (بدون ذكاء اصطناعي) بنفس صيغة أسئلة الاختبار التفاعلي."""
    rng = random.Random(seed)
    forms, counts = info["forms"], info["counts"]
    pool = info["keywords"][:20]
    if len(pool) < 4:
        return None
    candidates = [
        (s, keys) for s, keys in zip(info["sentences"], info["sent_keys"]) if 5 <= len(s.split()) <= 45
    ]
    rng.shuffle(candidates)
    candidates.sort(key=lambda item: -max([counts[k] for k in item[1] if k in pool] or [0]))

    questions, used = [], set()
    for sentence, keys in candidates:
        if len(questions) >= n_questions:
            break
        targets = [k for k in keys if k in pool and k not in used]
        if not targets:
            continue
        key = max(targets, key=lambda k: counts[k])
        token = next((w for w in WORD_RE.findall(sentence) if word_key(w) == key), None)
        if not token:
            continue
        used.add(key)
        others = [k for k in pool if k != key and forms[k] != forms[key]]
        source_line = f"ورد في المستند: «{shorten(sentence, 30)}»"
        if (len(questions) + 1) % 3 == 0:
            if rng.random() < 0.5:
                statement, answer = sentence, 0
            else:
                statement, answer = sentence.replace(token, forms[rng.choice(others)], 1), 1
            questions.append(
                {"question": f"صح أم خطأ: {shorten(statement, 50)}", "options": ["صح", "خطأ"],
                 "answer": answer, "explanation": source_line}
            )
            continue
        if difficulty == "صعب":
            others = others[:6]
        elif difficulty == "سهل":
            others = others[-8:]
        options = [forms[key]] + [forms[k] for k in rng.sample(others, min(3, len(others)))]
        rng.shuffle(options)
        blank = sentence.replace(token, attached_prefix(token) + "_____", 1)
        questions.append(
            {"question": f"أكمل الفراغ: {shorten(blank, 50)}", "options": options,
             "answer": options.index(forms[key]), "explanation": source_line}
        )
    return questions or None


def quiz_markdown(questions, difficulty, local=False):
    """نسخة نصية من الاختبار مع مفتاح الإجابات (للتنزيل وسجل المستندات)."""
    lines = [f"### ❓ اختبار سريع: {len(questions)} أسئلة (مستوى {difficulty})"]
    if local:
        lines.append(DOC_LOCAL_NOTE)
    for number, q in enumerate(questions, 1):
        lines.append(f"\n**{number}. {q['question']}**")
        lines += [f"- {QUIZ_LETTERS[i]}) {opt}" for i, opt in enumerate(q["options"])]
    lines += ["", "---", "### ✅ مفتاح الإجابات"]
    for number, q in enumerate(questions, 1):
        correct = q["options"][q["answer"]]
        explanation = f" — {q['explanation']}" if q.get("explanation") else ""
        lines.append(f"{number}. **{QUIZ_LETTERS[q['answer']]}) {correct}**{explanation}")
    return "\n".join(lines)


def local_quiz(info, n_questions, difficulty, seed):
    questions = local_quiz_data(info, n_questions, difficulty, seed)
    return quiz_markdown(questions, difficulty, local=True) if questions else None


def local_mindmap(info):
    forms, keywords = info["forms"], info["keywords"]
    if len(keywords) < 2:
        return None
    root, branches = keywords[0], keywords[1:6]
    linked = Counter()
    for keys in info["sent_keys"]:
        present = sorted({k for k in keys if k in keywords[:12]})
        for a, b in combinations(present, 2):
            linked[(a, b)] += 1

    lines = [f"### 🎯 {forms[root]}", DOC_LOCAL_NOTE]
    for key in branches:
        lines.append(f"- **🔷 {forms[key]}**")
        examples = [s for s, keys in zip(info["sentences"], info["sent_keys"]) if key in keys][:2]
        lines += [f"  - 🔹 {shorten(s, 14)}" for s in examples]
        related = [b if a == key else a for (a, b), _ in linked.most_common() if key in (a, b)][:3]
        if related:
            lines.append(f"  - ▫️ يرتبط بـ: {'، '.join(forms[r] for r in related)}")
    lines += ["", "**🔗 العلاقات بين المفاهيم**"]
    pairs = linked.most_common(5)
    if pairs:
        lines += [
            f"- «{forms[a]}» و«{forms[b]}» يظهران معاً في {count_ar(n, 'جملة واحدة', 'جملتين', 'جمل', 'جملة')}"
            for (a, b), n in pairs
        ]
    else:
        lines.append(f"- جميع الفروع تتفرع من الفكرة الرئيسية «{forms[root]}».")
    return "\n".join(lines)


def local_notebook(kind, text, n_questions, difficulty):
    info = analyze_document(text)
    if kind == "summary":
        result = local_summary(info)
    elif kind == "quiz":
        result = local_quiz(info, n_questions, difficulty, hashlib.md5(text[:5000].encode("utf-8")).hexdigest())
    else:
        result = local_mindmap(info)
    return result or (DOC_LOCAL_NOTE + "المستند قصير جداً لاستخراج نتيجة مفيدة محلياً. جرّب ملفاً أطول.")


# ==================================================================
# صفحة تسجيل الدخول
# ==================================================================
def render_login():
    _, center, _ = st.columns([1, 1.6, 1])
    with center:
        html_block(
            '<div class="vita-login-brand"><div class="vita-login-logo">V</div>'
            '<div class="vita-login-title">Vita</div>'
            '<div class="vita-login-sub">مساعدك الدراسي الذكي — ذكاء اصطناعي، تنظيم، وتركيز في مكان واحد</div></div>'
        )
        with st.form("login_form", clear_on_submit=False):
            html_block('<div class="vita-section">🔐 تسجيل الدخول أو إنشاء حساب</div>')
            username = st.text_input("اسم المستخدم", placeholder="مثال: sara_2026", max_chars=30)
            password = st.text_input("كلمة المرور", type="password", placeholder="اختر أي كلمة مرور")
            st.caption("إذا لم يكن الحساب موجوداً سيتم إنشاؤه تلقائياً بنفس البيانات.")
            submitted = st.form_submit_button("دخول إلى Vita", type="primary")
        if submitted:
            do_login(username, password)

        html_block('<div class="vita-or">أو</div>')
        if st.button("⚡ تسجيل الدخول للتجربة", key="demo_login_btn"):
            demo_login()

        features = "".join(
            f"<div class='vita-feature'><div>{label.split(' ', 1)[0]}</div>{esc(label.split(' ', 1)[1])}</div>"
            for label in PAGES.values()
        )
        html_block(f'<div class="vita-features">{features}</div>')
        html_block(
            '<div class="vita-note">نسخة تجريبية للعرض: الحسابات والبيانات تُحفظ مؤقتاً في جلسة المتصفح الحالية فقط.</div>'
        )


# ==================================================================
# الشريط الجانبي
# ==================================================================
def render_sidebar():
    u = U()
    profile, stats, pomo = u["profile"], u["stats"], u["pomo"]
    with st.sidebar:
        html_block(
            '<div class="vita-brand"><div class="vita-logo">V</div><div>'
            '<div class="vita-brand-name">Vita</div>'
            '<div class="vita-brand-sub">مساعدك الدراسي الذكي</div></div></div>'
        )
        html_block(
            f'<div class="vita-user">{avatar_html(profile, 44)}<div>'
            f'<div class="vita-user-name">{esc(profile["name"])}</div>'
            f'<div class="vita-user-handle"><span class="vita-ltr">@{esc(u["username"])}</span></div></div></div>'
        )
        html_block('<div class="vita-side-label">القائمة الرئيسية</div>')
        st.radio(
            "القائمة الرئيسية",
            list(PAGES),
            format_func=PAGES.get,
            key="page",
            label_visibility="collapsed",
            on_change=on_nav_change,
        )
        html_block(
            '<div class="vita-mini-stats">'
            f'<div class="vita-mini"><b>{stats["chats"]}</b><span>محادثات</span></div>'
            f'<div class="vita-mini"><b>{stats["files"]}</b><span>ملفات</span></div>'
            f'<div class="vita-mini"><b>{stats["pomodoros"]}</b><span>بومودورو</span></div>'
            "</div>"
        )
        if pomo["running"]:
            left = max(0, int(pomo["end_time"] - time.time()))
            html_block(
                f'<div class="vita-status">⏱️ {POMO_MODES[pomo["mode"]]["label"]} جارية — '
                f"متبقٍ {math.ceil(left / 60)} د</div>"
            )
        st.button("🚪 تسجيل الخروج", key="logout_btn", on_click=logout)
        html_block('<div class="vita-side-footer">Vita v1.0 · مشروع طلابي 🎓</div>')


# ==================================================================
# 1) الدردشة الذكية
# ==================================================================
def reset_chat():
    u = U()
    if u["messages"]:
        log_activity("🧹", "بدأت محادثة جديدة مع Vita")
    u["messages"] = []
    flash("تم تصفير المحادثة — ابدأ محادثة جديدة!", icon="🧹")


def queue_prompt(text):
    st.session_state.pending_prompt = text


def page_chat():
    u = U()
    page_header(
        "💬",
        "الدردشة الذكية",
        "Vita Chat",
        "اسأل Vita أي سؤال دراسي واحصل على إجابة منظمة تُكتب أمامك مباشرة.",
    )

    info_col, btn_col = st.columns([3, 1])
    with info_col:
        html_block(
            '<div class="vita-chips">'
            f'<span class="vita-chip">💬 المحادثات: {u["stats"]["chats"]}</span>'
            f'<span class="vita-chip">✉️ الرسائل في هذه المحادثة: {len(u["messages"])}</span>'
            "</div>"
        )
    with btn_col:
        st.button("🧹 محادثة جديدة", key="reset_chat_btn", on_click=reset_chat)

    user_avatar = u["profile"].get("avatar_bytes") or u["profile"].get("avatar", "🎓")

    if not u["messages"]:
        html_block(
            '<div class="vita-welcome"><div class="vita-login-logo">V</div>'
            f'<div class="vita-welcome-title">أهلاً {esc(u["profile"]["name"])}، أنا Vita 👋</div>'
            '<div class="vita-welcome-sub">مساعدك الدراسي الذكي. اختر اقتراحاً أو اكتب سؤالك بالأسفل.</div></div>'
        )
        cols = st.columns(2)
        for i, (icon, text) in enumerate(CHAT_SUGGESTIONS):
            cols[i % 2].button(
                f"{icon} {text}", key=f"suggest_{i}", on_click=queue_prompt, args=(text,)
            )

    for msg in u["messages"]:
        avatar = ASSISTANT_AVATAR if msg["role"] == "assistant" else user_avatar
        with st.chat_message(msg["role"], avatar=avatar):
            st.markdown(tidy_math(msg["content"]))

    prompt = st.chat_input("اكتب سؤالك لـ Vita هنا...")
    if not prompt:
        prompt = st.session_state.pop("pending_prompt", None)
    if not prompt:
        return

    if not u["messages"]:
        u["stats"]["chats"] += 1
        log_activity("💬", f"بدأت محادثة جديدة: «{prompt[:40]}»")
    u["messages"].append({"role": "user", "content": prompt})
    u["stats"]["messages"] += 1

    with st.chat_message("user", avatar=user_avatar):
        st.markdown(prompt)
    with st.chat_message("assistant", avatar=ASSISTANT_AVATAR):
        text, error = stream_answer(
            build_contents(u["messages"]), fallback=lambda: local_chat_answer(prompt)
        )

    if error:
        content = (text + "\n\n" if text else "") + f"⚠️ {error}"
        u["messages"].append({"role": "assistant", "content": content, "error": True})
    else:
        u["messages"].append({"role": "assistant", "content": text or "…"})
    st.rerun()


# ==================================================================
# 2) السبورة التفاعلية
# ==================================================================
def save_board_snapshot():
    u = U()
    if u.get("board_live") is not None:
        u["board_saved"] = u["board_live"]


def scale_drawing(drawing, factor):
    """يكبّر/يصغّر كل عناصر الرسم بنفس النسبة لتبقى في مكانها النسبي عند تغيير حجم اللوحة."""
    if not drawing or factor == 1:
        return drawing
    scaled = json.loads(json.dumps(drawing))
    for obj in scaled.get("objects", []):
        obj["left"] = obj.get("left", 0) * factor
        obj["top"] = obj.get("top", 0) * factor
        obj["scaleX"] = obj.get("scaleX", 1) * factor
        obj["scaleY"] = obj.get("scaleY", 1) * factor
    return scaled


def on_board_resize():
    """عند تغيير حجم اللوحة: نحفظ الرسم الحالي ونحجّمه للمقاس الجديد."""
    u = U()
    old = BOARD_SIZES[u.get("board_dims", "m")]
    new = BOARD_SIZES[st.session_state.board_dims]
    drawing = u.get("board_live") or u.get("board_saved")
    u["board_saved"] = scale_drawing(drawing, min(new[1] / old[1], new[2] / old[2]))
    u["board_live"] = None
    u["board_dims"] = st.session_state.board_dims


def clear_board():
    u = U()
    u["board_saved"] = None
    u["board_live"] = None
    u["board_v"] += 1
    flash("تم مسح السبورة", icon="🗑️")


def on_board_download():
    U()["stats"]["boards"] += 1
    log_activity("🎨", "نزّلت لوحة من السبورة التفاعلية")


def hex_to_rgba(hex_color):
    hex_color = hex_color.lstrip("#")
    return tuple(int(hex_color[i : i + 2], 16) for i in (0, 2, 4)) + (255,)


def page_board():
    u = U()
    page_header(
        "🎨",
        "السبورة التفاعلية",
        "Interactive Whiteboard",
        "ارسم واشرح وخطّط أفكارك بحرية، ثم نزّل لوحتك كصورة بضغطة زر.",
    )
    if st_canvas is None:
        st.error(f"تعذّر تحميل مكتبة السبورة (streamlit-drawable-canvas): {CANVAS_ERROR}", icon="⚠️")
        return

    with st.container(border=True):
        left, right = st.columns([1.55, 1])
        with left:
            tool = st.radio(
                "🛠️ الأداة", list(BOARD_TOOLS), format_func=BOARD_TOOLS.get, horizontal=True, key="board_tool"
            )
            color_key = st.radio(
                "🎨 لون القلم",
                list(PEN_COLORS),
                format_func=lambda k: PEN_COLORS[k][0],
                horizontal=True,
                key="board_color",
            )
        with right:
            if color_key == "custom":
                stroke_color = st.color_picker("لون مخصص", "#f472b6", key="board_custom_color")
            else:
                stroke_color = PEN_COLORS[color_key][1]
            size = st.slider("✒️ حجم الفرشاة / الممحاة", 1, 60, 6, key="board_size")
            c1, c2 = st.columns(2)
            bg_key = c1.selectbox(
                "🖼️ نوع السبورة",
                list(BOARD_BACKGROUNDS),
                format_func=lambda k: BOARD_BACKGROUNDS[k][0],
                key="board_bg",
                on_change=save_board_snapshot,
            )
            size_key = c2.selectbox(
                "📐 حجم اللوحة",
                list(BOARD_SIZES),
                index=1,
                format_func=lambda k: BOARD_SIZES[k][0],
                key="board_dims",
                on_change=on_board_resize,
            )
    u["board_dims"] = size_key

    bg_color = BOARD_BACKGROUNDS[bg_key][1]
    _, width, height = BOARD_SIZES[size_key]
    is_eraser = tool == "eraser"
    if is_eraser:
        st.caption("🧽 الممحاة تمسح بلون خلفية السبورة — يمكنك أيضاً استخدام أزرار التراجع أسفل اللوحة.")
    if size_key == "l":
        st.caption("💡 إذا لم تظهر اللوحة الكبيرة كاملة، أغلق الشريط الجانبي من زر « في أعلاه لتتسع الصفحة.")

    canvas = st_canvas(
        fill_color="rgba(0, 0, 0, 0)",
        stroke_width=size,
        stroke_color=bg_color if is_eraser else stroke_color,
        background_color=bg_color,
        initial_drawing=u["board_saved"],
        update_streamlit=True,
        height=height,
        width=width,
        drawing_mode="freedraw" if is_eraser else tool,
        display_toolbar=True,
        # المكتبة لا تعيد ضبط طبقة الخلفية عند تغيير المقاس، فيظهر الخط في غير مكانه؛
        # لذلك نعيد إنشاء اللوحة (مع الرسم المحفوظ) كلما تغيّر الحجم أو نوع السبورة
        key=f"board_canvas_{u['board_v']}_{size_key}_{bg_key}",
    )

    objects = []
    if canvas is not None and canvas.json_data is not None:
        u["board_live"] = canvas.json_data
        objects = canvas.json_data.get("objects", [])

    a, b, c = st.columns([1, 1, 1.2])
    with a:
        st.button("🗑️ مسح السبورة", key="board_clear", on_click=clear_board)
    with b:
        png = None
        if canvas is not None and canvas.image_data is not None and objects:
            drawing = Image.fromarray(canvas.image_data.astype("uint8"), "RGBA")
            background = Image.new("RGBA", drawing.size, hex_to_rgba(bg_color))
            buffer = io.BytesIO()
            Image.alpha_composite(background, drawing).convert("RGB").save(buffer, format="PNG")
            png = buffer.getvalue()
        st.download_button(
            "⬇️ تنزيل اللوحة كصورة",
            data=png or b"",
            file_name=f"vita_board_{datetime.now():%Y%m%d_%H%M}.png",
            mime="image/png",
            disabled=png is None,
            key="board_download",
            on_click=on_board_download,
            type="primary",
        )
    with c:
        html_block(
            '<div class="vita-chips" style="justify-content:center;min-height:2.65rem">'
            f'<span class="vita-chip">✍️ عناصر مرسومة: {len(objects)}</span>'
            f'<span class="vita-chip">🖼️ <span class="vita-ltr">{width}×{height}</span></span></div>'
        )


# ==================================================================
# 3) منشئ الجداول
# ==================================================================
def set_sheet(df, message, icon="📊"):
    u = U()
    u["sheet"] = df
    u["sheet_v"] += 1
    flash(message, icon=icon)


def apply_sheet_edits():
    """يطبّق تعديلات الجدول فور حدوثها، فيُكتب اليوم تلقائياً بعد اختيار التاريخ."""
    u = U()
    state = st.session_state.get(f"sheet_editor_{u['sheet_v']}") or {}
    df = u["sheet"].copy().reset_index(drop=True)
    for row, changes in (state.get("edited_rows") or {}).items():
        for column, value in changes.items():
            if column in df.columns:
                df.at[int(row), column] = value
    deleted = [int(i) for i in state.get("deleted_rows") or []]
    if deleted:
        df = df.drop(index=deleted)
    added = [{k: v for k, v in row.items() if k in SHEET_COLUMNS} for row in state.get("added_rows") or []]
    if added:
        df = pd.concat([df, pd.DataFrame(added)], ignore_index=True)
    u["sheet"] = tidy_sheet(df)
    u["sheet_v"] += 1


def save_sheet():
    u = U()
    u["stats"]["sheets"] += 1
    log_activity("💾", "حفظت جدول المذاكرة")
    flash("تم حفظ الجدول في جلستك", icon="💾")


def on_sheet_export():
    log_activity("⬇️", "صدّرت جدول المذاكرة بصيغة CSV")


def page_sheets():
    u = U()
    page_header(
        "📊",
        "منشئ الجداول",
        "Data Sheets",
        "أنشئ جدول مذاكرتك، عدّل الخلايا مباشرة، أضف صفوفاً أو احذفها، ثم صدّره بصيغة CSV.",
    )

    u["sheet"] = tidy_sheet(u["sheet"])  # يحوّل الجداول القديمة إلى الصيغة الجديدة للتاريخ
    # قائمة تواريخ للاختيار (أسبوعان مضيا + ستة أشهر قادمة) بدلاً من كتابة التاريخ يدوياً
    today = date.today()
    date_options = [(today + timedelta(days=offset)).isoformat() for offset in range(-14, 181)]
    date_options = sorted(set(date_options) | set(u["sheet"][COL_DATE].dropna()))

    # القيم الافتراضية للصف الجديد: تاريخ اليوم (ويُكتب اليوم تلقائياً)، ساعة واحدة، أولوية متوسطة
    column_config = {
        COL_SUBJECT: st.column_config.TextColumn(COL_SUBJECT, help="اسم المادة الدراسية", default=""),
        COL_TASK: st.column_config.TextColumn(COL_TASK, help="ما الذي ستذاكره؟", width="medium", default=""),
        COL_DATE: st.column_config.SelectboxColumn(
            COL_DATE, options=date_options, format_func=date_label, help="اختر التاريخ من القائمة",
            width="medium", default=today.isoformat(),
        ),
        COL_DAY: st.column_config.TextColumn(COL_DAY, help="يُكتب تلقائياً حسب التاريخ", disabled=True),
        COL_HOURS: st.column_config.NumberColumn(
            COL_HOURS, min_value=0.0, max_value=24.0, step=0.5, format="%.1f", default=1.0
        ),
        COL_PRIORITY: st.column_config.SelectboxColumn(COL_PRIORITY, options=PRIORITIES, default=PRIORITIES[1]),
        COL_DONE: st.column_config.CheckboxColumn(COL_DONE, default=False),
    }

    section_title("🗓️ جدول المذاكرة")
    st.caption(
        "💡 انقر على أي خلية لتعديلها، واختر التاريخ من القائمة فيُكتب اليوم تلقائياً. "
        "استخدم الصف الأخير (+) لإضافة مهمة، وحدّد صفاً ثم اضغط Delete لحذفه."
    )
    html_block('<div style="height:1.1rem"></div>')
    edited = st.data_editor(
        u["sheet"],
        key=f"sheet_editor_{u['sheet_v']}",
        num_rows="dynamic",
        hide_index=True,
        column_config=column_config,
        # الجدول يُرسم من اليسار لليمين، لذا نعكس ترتيب الأعمدة ليُقرأ من اليمين كالعربية
        column_order=list(reversed(SHEET_COLUMNS)),
        on_change=apply_sheet_edits,
        **stretch_kwargs(st.data_editor),
    )

    total = len(edited)
    if COL_HOURS in edited.columns:
        hours = float(pd.to_numeric(edited[COL_HOURS], errors="coerce").fillna(0).sum())
    else:
        hours = 0.0
    done = int(edited[COL_DONE].eq(True).sum()) if COL_DONE in edited.columns else 0
    percent = int(round(done / total * 100)) if total else 0

    stat_tiles(
        [
            ("📋", total, "إجمالي المهام", "rgba(139,92,246,.18)"),
            ("⏳", f"{hours:g}", "ساعات المذاكرة المخططة", "rgba(6,182,212,.18)"),
            ("✅", done, "مهام مُنجزة", "rgba(34,197,94,.18)"),
            ("📈", f"{percent}%", "نسبة الإنجاز", "rgba(245,158,11,.18)"),
        ]
    )
    st.progress(percent / 100)

    csv_bytes = edited.to_csv(index=False).encode("utf-8-sig")
    b1, b2, b3, b4 = st.columns(4)
    b1.button("💾 حفظ الجدول", key="sheet_save", on_click=save_sheet, type="primary")
    b2.download_button(
        "⬇️ تصدير CSV",
        data=csv_bytes,
        file_name=f"vita_study_plan_{date.today():%Y%m%d}.csv",
        mime="text/csv",
        key="sheet_export",
        on_click=on_sheet_export,
    )
    b3.button(
        "🔄 استعادة النموذج",
        key="sheet_sample",
        on_click=set_sheet,
        args=(sample_sheet(), "تمت استعادة جدول المذاكرة النموذجي", "🔄"),
    )
    b4.button(
        "🧾 جدول فارغ",
        key="sheet_empty",
        on_click=set_sheet,
        args=(empty_sheet(), "تم إنشاء جدول فارغ جديد", "🧾"),
    )


# ==================================================================
# 4) مساعد المستندات
# ==================================================================
# ---------------- قراءة الملفات بكل أنواعها ----------------
# كل ملف يتحول إلى «مقاطع»: ("text", نص) أو ("image", صورة JPEG, وصف) تُقرأ لاحقاً بالتعرف الضوئي (OCR)
TEXT_EXTS = {
    "txt", "md", "markdown", "csv", "tsv", "log", "xml", "yaml", "yml", "ini", "cfg", "tex", "srt", "vtt",
    "py", "js", "ts", "java", "c", "cpp", "h", "cs", "go", "rb", "php", "swift", "kt", "sql", "css", "sh", "bat",
}
IMAGE_EXTS = {"png", "jpg", "jpeg", "webp", "bmp", "gif", "tif", "tiff", "jfif"}
MEDIA_EXTS = {"mp3", "wav", "m4a", "aac", "ogg", "flac", "mp4", "mov", "avi", "mkv", "webm", "wmv"}
ARCHIVE_EXTS = {"zip", "rar", "7z", "tar", "gz", "exe", "msi", "dll", "apk", "iso"}
MAX_OCR_PAGES = 40
OCR_MAX_SIDE = 1600
MIN_PAGE_TEXT = 25  # صفحة PDF بنص أقل من هذا تُعامل كصورة وتُقرأ بالـ OCR

W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
A_NS = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
ODF_TEXT_NS = "{urn:oasis:names:tc:opendocument:xmlns:text:1.0}"

FILE_KINDS = {
    "pdf": ("📕", "PDF", "صفحة"),
    "word": ("📘", "Word", "صفحة"),
    "slides": ("📙", "عرض تقديمي", "شريحة"),
    "sheet": ("📗", "جدول بيانات", "ورقة"),
    "image": ("🖼️", "صورة", "صورة"),
    "text": ("📄", "ملف نصي", "صفحة"),
}


class UnsupportedFile(Exception):
    pass


def decode_text_bytes(data):
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return data.decode("utf-16", errors="replace")
    for encoding in ("utf-8-sig", "cp1256"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1")


def looks_binary(data):
    sample = data[:4000]
    if not sample:
        return False
    if b"\x00" in sample:
        return True
    control = sum(1 for b in sample if b < 9 or 13 < b < 32)
    return control / len(sample) > 0.05


def image_to_jpeg(image):
    """يجهّز الصورة للقراءة: تدوير صحيح، خلفية بيضاء للشفافية، وتصغير لسرعة الـ OCR."""
    image = ImageOps.exif_transpose(image)
    if image.mode in ("RGBA", "LA", "P"):
        image = image.convert("RGBA")
        background = Image.new("RGB", image.size, "white")
        background.paste(image, mask=image.split()[-1])
        image = background
    image = image.convert("RGB")
    image.thumbnail((OCR_MAX_SIDE, OCR_MAX_SIDE))
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=90)
    return buffer.getvalue()


def xml_lines(xml_bytes, para_tag, text_tag):
    root = ET.fromstring(xml_bytes)
    lines = []
    for para in root.iter(para_tag):
        line = "".join(node.text or "" for node in para.iter(text_tag)).strip()
        if line:
            lines.append(line)
    return lines


def zip_media_images(archive, prefix, limit=MAX_OCR_PAGES):
    names = sorted(
        n for n in archive.namelist()
        if n.startswith(prefix) and n.rsplit(".", 1)[-1].lower() in IMAGE_EXTS
    )
    segments = []
    for n, name in enumerate(names[:limit], 1):
        try:
            image = Image.open(io.BytesIO(archive.read(name)))
            if min(image.size) >= 200:  # نتجاهل الأيقونات الصغيرة
                segments.append(("image", image_to_jpeg(image), f"صورة {n}"))
        except Exception:
            continue
    return segments


def render_pdf_page(data, index, pdf_cache):
    """يرسم صفحة PDF كصورة (pypdfium2)، أو يأخذ أكبر صورة مضمّنة فيها كحل بديل."""
    if pdfium is not None:
        try:
            if "doc" not in pdf_cache:
                pdf_cache["doc"] = pdfium.PdfDocument(data)
            page = pdf_cache["doc"][index]
            width, height = page.get_size()
            scale = min(3.0, OCR_MAX_SIDE / max(width, height, 1))
            return image_to_jpeg(page.render(scale=scale).to_pil())
        except Exception:
            pass
    try:
        page = pdf_cache["reader"].pages[index]
        images = [img.image for img in page.images if img.image is not None]
        if images:
            return image_to_jpeg(max(images, key=lambda im: im.size[0] * im.size[1]))
    except Exception:
        pass
    return None


def parse_pdf(data):
    if PdfReader is None:
        raise UnsupportedFile("مكتبة pypdf غير مثبتة.")
    reader = PdfReader(io.BytesIO(data))
    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception:
            raise UnsupportedFile("الملف محمي بكلمة مرور. أزل الحماية ثم ارفعه مرة أخرى.")
    segments, cache, ocr_pages = [], {"reader": reader}, 0
    for index, page in enumerate(reader.pages):
        try:
            text = (page.extract_text() or "").strip()
        except Exception:
            text = ""
        if len(text) >= MIN_PAGE_TEXT or ocr_pages >= MAX_OCR_PAGES:
            if text:
                segments.append(("text", text))
            continue
        image = render_pdf_page(data, index, cache)
        if image:
            ocr_pages += 1
            segments.append(("image", image, f"صفحة {index + 1}"))
        elif text:
            segments.append(("text", text))
    return {"kind": "pdf", "count": len(reader.pages), "segments": segments}


def parse_word(data):
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        lines = xml_lines(archive.read("word/document.xml"), W_NS + "p", W_NS + "t")
        segments = [("text", "\n".join(lines))] if lines else []
        if len(" ".join(lines)) < 50:  # مستند Word عبارة عن صور ممسوحة
            segments += zip_media_images(archive, "word/media/")
    return {"kind": "word", "count": None, "segments": segments}


def parse_slides(data):
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        slides = sorted(
            (n for n in archive.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)),
            key=lambda n: int(re.findall(r"\d+", n)[-1]),
        )
        segments, total = [], 0
        for number, name in enumerate(slides, 1):
            lines = xml_lines(archive.read(name), A_NS + "p", A_NS + "t")
            total += len(" ".join(lines))
            if lines:
                segments.append(("text", f"[الشريحة {number}]\n" + "\n".join(lines)))
        if total < 50 * max(1, len(slides)) // 2:  # شرائح معظمها صور
            segments += zip_media_images(archive, "ppt/media/")
    return {"kind": "slides", "count": len(slides), "segments": segments}


def parse_odf(data, ext):
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        root = ET.fromstring(archive.read("content.xml"))
        lines = [
            "".join(el.itertext()).strip()
            for el in root.iter()
            if el.tag in (ODF_TEXT_NS + "p", ODF_TEXT_NS + "h")
        ]
        segments = [("text", "\n".join(line for line in lines if line))]
        if len(" ".join(lines)) < 50:
            segments += zip_media_images(archive, "Pictures/")
    kind = {"odt": "word", "odp": "slides", "ods": "sheet"}[ext]
    return {"kind": kind, "count": None, "segments": segments}


def parse_spreadsheet(data):
    try:
        sheets = pd.read_excel(io.BytesIO(data), sheet_name=None)
    except ImportError:
        raise UnsupportedFile("صيغة Excel القديمة (xls) تحتاج مكتبة إضافية؛ احفظ الملف بصيغة xlsx ثم ارفعه.")
    parts = []
    for name, frame in sheets.items():
        frame = frame.dropna(how="all").dropna(axis=1, how="all")
        if not frame.empty:
            parts.append(f"[ورقة: {name}] ({len(frame)} صفاً)\n" + frame.head(300).to_csv(index=False))
    return {"kind": "sheet", "count": len(sheets), "segments": [("text", "\n\n".join(parts))]}


def legacy_office_text(data):
    """استخراج تقريبي للنص من ملفات Word/PowerPoint القديمة (doc/ppt)."""
    runs = []
    for offset in (0, 1):
        decoded = data[offset:].decode("utf-16-le", errors="ignore")
        runs += re.findall(r"[\u0600-\u06FFA-Za-z0-9 .,،؛:!?؟()\-«»\"'\n]{25,}", decoded)
    lines = [re.sub(r"\s+", " ", r).strip() for r in runs]
    lines = [line for line in lines if len(line.split()) >= 4]
    if not lines:
        lines = [r.decode("ascii").strip() for r in re.findall(rb"[\x20-\x7E\r\n\t]{40,}", data)]
    return "\n".join(dict.fromkeys(lines))


def rtf_to_text(raw):
    match = re.search(r"\\ansicpg(\d+)", raw)
    codepage = f"cp{match.group(1)}" if match else "cp1252"
    text = re.sub(r"\{\\\*[^{}]*\}", "", raw)
    text = re.sub(r"\\u(-?\d+)\??", lambda m: chr(int(m.group(1)) % 65536), text)
    text = re.sub(
        r"\\'([0-9a-fA-F]{2})", lambda m: bytes([int(m.group(1), 16)]).decode(codepage, "ignore"), text
    )
    text = re.sub(r"\\(par|line)\b ?", "\n", text)
    text = re.sub(r"\\[a-zA-Z]+-?\d* ?", "", text)
    return text.replace("{", "").replace("}", "")


def html_to_text(raw):
    raw = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", raw)
    raw = re.sub(r"(?i)<br\s*/?>|</(p|div|li|h[1-6]|tr)>", "\n", raw)
    text = html.unescape(re.sub(r"<[^>]+>", " ", raw))
    return "\n".join(line.strip() for line in text.splitlines() if line.strip())


def as_image(data):
    try:
        image = Image.open(io.BytesIO(data))
        image.load()
        return image
    except Exception:
        return None


@st.cache_data(show_spinner=False, max_entries=24)
def parse_document(data, filename):
    """يقرأ أي ملف ويعيده كمقاطع نصية أو صور تحتاج OCR."""
    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    if ext in MEDIA_EXTS:
        raise UnsupportedFile("ملفات الصوت والفيديو غير مدعومة حالياً. ارفع ملفاً نصياً أو PDF أو صورة.")
    if ext in ARCHIVE_EXTS:
        raise UnsupportedFile("الملفات المضغوطة والبرامج غير مدعومة. فك الضغط وارفع الملف نفسه.")
    try:
        if ext == "pdf" or data[:5] == b"%PDF-":
            return parse_pdf(data)
        if ext in ("docx", "docm", "dotx"):
            return parse_word(data)
        if ext in ("pptx", "ppsx", "potx", "pptm"):
            return parse_slides(data)
        if ext in ("xlsx", "xlsm", "xls"):
            return parse_spreadsheet(data)
        if ext in ("odt", "odp", "ods"):
            return parse_odf(data, ext)
        if ext in ("doc", "ppt"):
            kind = "word" if ext == "doc" else "slides"
            return {"kind": kind, "count": None, "segments": [("text", legacy_office_text(data))]}
    except UnsupportedFile:
        raise
    except (zipfile.BadZipFile, KeyError, ET.ParseError):
        raise UnsupportedFile("الملف تالف أو امتداده لا يطابق محتواه.")

    if ext in IMAGE_EXTS or ext in ("heic", "svg"):
        image = as_image(data)
        if image is None:
            raise UnsupportedFile("تعذّر فتح الصورة. جرّب حفظها بصيغة PNG أو JPG.")
        return {"kind": "image", "count": 1, "segments": [("image", image_to_jpeg(image), "الصورة")]}

    text = decode_text_bytes(data) if not looks_binary(data) else None
    if text is None:
        image = as_image(data)  # ملف بلا امتداد معروف لكنه صورة
        if image is not None:
            return {"kind": "image", "count": 1, "segments": [("image", image_to_jpeg(image), "الصورة")]}
        raise UnsupportedFile("نوع هذا الملف غير مدعوم. جرّب PDF أو Word أو PowerPoint أو Excel أو صورة أو ملفاً نصياً.")
    if ext == "rtf" or text.startswith("{\\rtf"):
        text = rtf_to_text(text)
    elif ext in ("html", "htm", "xhtml"):
        text = html_to_text(text)
    elif ext == "json":
        try:
            text = json.dumps(json.loads(text), ensure_ascii=False, indent=2)
        except ValueError:
            pass
    return {"kind": "text", "count": None, "segments": [("text", text)]}


# ---------------- التعرف الضوئي على النصوص (OCR) بدون إنترنت ----------------
@st.cache_resource(show_spinner=False)
def get_ocr_engine():
    from rapidocr import LangRec, ModelType, OCRVersion, RapidOCR

    # نموذج PP-OCRv5 العربي يقرأ العربية والإنجليزية معاً
    return RapidOCR(
        params={
            "Global.log_level": "error",
            "Rec.lang_type": LangRec.ARABIC,
            "Rec.model_type": ModelType.MOBILE,
            "Rec.ocr_version": OCRVersion.PPOCRV5,
        }
    )


# نصوص القوالب الجاهزة (Canva وغيرها) التي لا فائدة منها في التحليل
OCR_JUNK = re.compile(
    r"(?i)lorem|ipsum|dummy text|typesett|keyword\s*\d|type specimen|scrambled|letraset|pagemaker"
    r"|survived not only|leap into electronic|essentially unchanged|printer took|product descriptions"
    r"|^[\W\d_]{0,3}$|^[\W_]*[A-Za-z]{1,3}[\W_]*$"
)


@st.cache_data(show_spinner=False, max_entries=400)
def ocr_image(jpeg_bytes):
    result = get_ocr_engine()(jpeg_bytes)
    pairs = zip(result.txts or (), result.scores or ())
    return "\n".join(
        text.strip() for text, score in pairs if text and score >= 0.5 and not OCR_JUNK.search(text.strip())
    )


def ocr_available():
    try:
        import rapidocr  # noqa: F401

        return True
    except Exception:
        return False


def document_text(parsed, file_id):
    """يجمع نص الملف، ويقرأ الصفحات المصوّرة بالـ OCR مع شريط تقدم (مرة واحدة لكل ملف)."""
    cache = st.session_state.setdefault("doc_text_cache", {})
    if file_id in cache:
        return cache[file_id]

    images = [i for i, seg in enumerate(parsed["segments"]) if seg[0] == "image"]
    ocr_results, ocr_note = {}, None
    if images and not ocr_available():
        ocr_note = "هذا الملف يحتوي صوراً، ومكتبة القراءة الضوئية غير مثبتة. شغّل: python -m pip install -r requirements.txt"
    elif images:
        bar = st.progress(0.0)
        for done, index in enumerate(images):
            label = parsed["segments"][index][2]
            hint = " (أول مرة قد تستغرق دقيقة لتحميل نموذج القراءة)" if done == 0 else ""
            bar.progress(done / len(images), text=f"🔍 جارٍ قراءة {label} بالتعرف الضوئي ({done + 1}/{len(images)}){hint}")
            try:
                ocr_results[index] = ocr_image(parsed["segments"][index][1])
            except Exception as err:
                ocr_note = f"تعذّرت قراءة بعض الصور بالتعرف الضوئي: {err}"
        bar.empty()

    parts = []
    for index, seg in enumerate(parsed["segments"]):
        if seg[0] == "text":
            parts.append(seg[1].strip())
        elif ocr_results.get(index):
            parts.append(f"[{seg[2]}]\n{ocr_results[index]}")
    text = "\n\n".join(p for p in parts if p).strip()
    result = (text, len(images), ocr_note)
    if not ocr_note:
        cache[file_id] = result
    return result


def notebook_prompt(kind, text, filename, n_questions, difficulty):
    if kind == "summary":
        instruction = (
            "اقرأ المستند التالي ثم اكتب **ملخصاً تنفيذياً** احترافياً يتضمن:\n"
            "1. **نظرة عامة**: فقرة قصيرة توضح موضوع المستند وهدفه.\n"
            "2. **أهم النقاط**: من 5 إلى 8 نقاط مركّزة.\n"
            "3. **المفاهيم والمصطلحات الأساسية**: كل مصطلح مع شرح موجز.\n"
            "4. **الخلاصة ونصائح المذاكرة**: كيف يذاكر الطالب هذا المحتوى بفعالية.\n"
            "استخدم عناوين Markdown ونقاطاً واضحة."
        )
    elif kind == "quiz":
        instruction = (
            f"أنشئ **اختباراً سريعاً** من {n_questions} أسئلة بمستوى صعوبة «{difficulty}» مبنياً على المستند فقط:\n"
            "- اجعل معظم الأسئلة اختيار من متعدد بأربعة خيارات (أ، ب، ج، د)، وبعضها صح أو خطأ.\n"
            "- رقّم الأسئلة واكتب كل خيار في سطر مستقل.\n"
            "- بعد الأسئلة أضف قسماً بعنوان **✅ مفتاح الإجابات** مع شرح مختصر لسبب صحة كل إجابة.\n"
            "- ثم أضف قسماً بعنوان **📝 أسئلة مذاكرة مقالية** يحتوي 3 أسئلة للمراجعة العميقة."
        )
    else:
        instruction = (
            "أنشئ **خريطة مفاهيمية نصية** للمستند على شكل قائمة Markdown متداخلة (هرمية):\n"
            "- ابدأ بعنوان من المستوى الثالث يحتوي 🎯 والفكرة الرئيسية للمستند.\n"
            "- المستوى الأول من القائمة: الفروع الرئيسية بخط عريض مع الرمز 🔷.\n"
            "- المستوى الثاني: الأفكار الفرعية مع الرمز 🔹.\n"
            "- المستوى الثالث: التفاصيل والأمثلة مع الرمز ▫️.\n"
            "- بعد الخريطة اكتب قسماً بعنوان **🔗 العلاقات بين المفاهيم** يشرح في 3–5 نقاط كيف ترتبط الفروع ببعضها."
        )
    return (
        f"{instruction}\n\n---\nاسم الملف: {filename}\n"
        f"محتوى المستند:\n<<<\n{text}\n>>>"
    )


# ---------------- الاختبار التفاعلي ----------------
QUIZ_SYSTEM = (
    "أنت Vita، مساعد مذاكرة يصنع اختبارات دقيقة من المستندات الدراسية. "
    "اعتمد على محتوى المستند فقط، وتجاهل نصوص القوالب العشوائية مثل Lorem ipsum. "
    "أعد دائماً JSON صالحاً فقط دون أي نص أو تنسيق إضافي."
)
OPTION_PREFIX = re.compile(r"^\s*(?:[أابجده]|[A-Da-d]|\d)\s*[\)\.\-:]\s+")
LETTER_INDEX = {"أ": 0, "ا": 0, "ب": 1, "ج": 2, "د": 3, "a": 0, "b": 1, "c": 2, "d": 3}


def quiz_prompt(text, filename, n_questions, difficulty):
    return (
        f"أنشئ اختباراً من {n_questions} أسئلة بمستوى صعوبة «{difficulty}» مبنياً على محتوى المستند التالي فقط.\n"
        "- اجعل معظم الأسئلة اختيار من متعدد بأربعة خيارات، وسؤالاً أو سؤالين من نوع صح أو خطأ بخيارين: «صح» و«خطأ».\n"
        "- لكل سؤال إجابة صحيحة واحدة فقط تجدها في المستند، والخيارات الخاطئة معقولة وليست سخيفة.\n"
        "- في explanation اكتب جملة قصيرة توضح سبب صحة الإجابة مستشهداً بما ورد في المستند.\n"
        "أعد النتيجة بصيغة JSON فقط بهذا الشكل بالضبط:\n"
        '{"questions": [{"question": "نص السؤال", "options": ["الخيار الأول", "الخيار الثاني", "الخيار الثالث", '
        '"الخيار الرابع"], "answer": 0, "explanation": "سبب صحة الإجابة من المستند"}]}\n'
        "حيث answer هو رقم الخيار الصحيح في القائمة بدءاً من 0.\n\n"
        f"---\nاسم الملف: {filename}\nمحتوى المستند:\n<<<\n{text}\n>>>"
    )


def parse_quiz_json(raw):
    """يستخرج الأسئلة من رد الذكاء الاصطناعي ويتحقق من صحتها (يتحمل الأخطاء الشائعة في التنسيق)."""
    raw = re.sub(r"```(?:json)?", "", raw or "")
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end <= start:
        return None
    data = None
    for blob in (raw[start : end + 1], re.sub(r",\s*([}\]])", r"\1", raw[start : end + 1])):
        try:
            data = json.loads(blob)
            break
        except ValueError:
            continue
    items = data.get("questions") if isinstance(data, dict) else None
    questions = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        question = re.sub(r"\\n|\s+", " ", str(item.get("question") or "")).replace("--", " ")
        question = re.sub(r"\s+", " ", question).strip()
        options = [OPTION_PREFIX.sub("", str(o)).strip() for o in item.get("options") or []]
        options = [o for o in options if o][:4]
        answer = item.get("answer")
        if isinstance(answer, str):
            text = answer.strip()
            if text.isdigit():
                answer = int(text)
            elif text.lower() in LETTER_INDEX:
                answer = LETTER_INDEX[text.lower()]
            else:
                answer = next((i for i, o in enumerate(options) if o == OPTION_PREFIX.sub("", text).strip()), None)
        if isinstance(answer, bool) or not isinstance(answer, int):
            continue
        explanation = str(item.get("explanation") or "").strip()
        # تصحيح احتياطي: إن ذكر الشرح خياراً واحداً بعينه غير المعلَّم عليه، نعتمد ما في الشرح
        mentioned = [i for i, o in enumerate(options) if len(o) >= 3 and o in explanation]
        if len(mentioned) == 1 and mentioned[0] != answer:
            answer = mentioned[0]
        if len(question) < 3 or len(options) < 2 or not 0 <= answer < len(options):
            continue
        questions.append({"question": question, "options": options, "answer": answer, "explanation": explanation})
    return questions or None


def shuffle_quiz(questions, seed):
    """نخلط خيارات أسئلة الاختيار من متعدد حتى لا تكون الإجابة الصحيحة في نفس المكان دائماً."""
    rng = random.Random(seed)
    for q in questions:
        if set(q["options"]) <= {"صح", "خطأ", "صحيح", "خاطئ"}:
            continue
        correct = q["options"][q["answer"]]
        rng.shuffle(q["options"])
        q["answer"] = q["options"].index(correct)
    return questions


def generate_quiz(doc_text, filename, n_questions, difficulty):
    """يطلب الأسئلة من الذكاء الاصطناعي، وإن تعذّر ذلك يصنعها محلياً. يعيد (الأسئلة، المصدر)."""
    seed = hashlib.md5(f"{doc_text[:2000]}{time.time()}".encode("utf-8")).hexdigest()
    contents = [{"role": "user", "parts": [{"text": quiz_prompt(doc_text, filename, n_questions, difficulty)}]}]
    status = st.empty()
    status.markdown("💭 *Vita يجهّز أسئلة الاختبار من المستند...*")
    raw = ""
    try:
        for chunk in ai_stream(contents, QUIZ_SYSTEM, 0.3, status, fallback=None):
            raw += chunk
            written = raw.count('"question"')
            if written:
                status.markdown(f"✍️ *Vita يكتب السؤال {min(written, n_questions)} من {n_questions}...*")
    except VitaError:
        pass
    status.empty()
    questions = parse_quiz_json(raw)
    if questions:
        return shuffle_quiz(questions[:n_questions], seed), "ai"
    return local_quiz_data(analyze_document(doc_text), n_questions, difficulty, seed), "local"


def submit_quiz(result, doc_name):
    count = len(result["questions"])
    answers = {i: st.session_state.get(f"quiz_{result['id']}_{i}") for i in range(count)}
    score = sum(1 for i, q in enumerate(result["questions"]) if answers[i] == q["answer"])
    result.update(answers=answers, score=score, submitted=True)
    log_activity("📝", f"أنهيت اختباراً عن «{doc_name}»: {score} من {count}")
    if score == count:
        flash("علامة كاملة! أحسنت 🎉", icon="🏆", balloons=True)


def retry_quiz(result):
    result.update(id=hashlib.md5(str(time.time()).encode()).hexdigest()[:8], answers={}, score=None, submitted=False)


def render_quiz(result, doc_name):
    questions = result["questions"]
    if result.get("source") == "local":
        st.caption("⚡ أُنشئ هذا الاختبار محلياً لأن خدمة الذكاء الاصطناعي كانت غير متاحة؛ أعد إنشاءه بعد قليل لأسئلة أدق.")

    if not result.get("submitted"):
        st.caption("اختر إجابة لكل سؤال، ثم اضغط «تقديم الإجابات» في الأسفل لترى نتيجتك.")
        with st.form(f"quiz_form_{result['id']}", border=False):
            for i, q in enumerate(questions):
                html_block(f'<div class="vita-q-title">{i + 1}. {esc(q["question"])}</div>')
                st.radio(
                    f"السؤال {i + 1}",
                    list(range(len(q["options"]))),
                    format_func=lambda j, q=q: f"{QUIZ_LETTERS[j]}) {q['options'][j]}",
                    index=None,
                    key=f"quiz_{result['id']}_{i}",
                    label_visibility="collapsed",
                )
                if i < len(questions) - 1:
                    st.divider()
            submitted = st.form_submit_button("📤 تقديم الإجابات", type="primary")
        if submitted:
            submit_quiz(result, doc_name)
            st.rerun()
        return

    total, score = len(questions), result["score"]
    percent = round(score / total * 100) if total else 0
    if percent >= 90:
        verdict = "🏆 ممتاز! فهمك للمستند رائع"
    elif percent >= 70:
        verdict = "👏 أحسنت، نتيجة جيدة جداً"
    elif percent >= 50:
        verdict = "📘 جيد، راجع الأسئلة الخاطئة"
    else:
        verdict = "💪 تحتاج إلى مراجعة المستند مرة أخرى"
    unanswered = sum(1 for v in result["answers"].values() if v is None)
    html_block(
        '<div class="vita-score">'
        f'<div class="vita-score-num"><span class="vita-ltr">{score} / {total}</span></div>'
        f'<div style="flex:1"><div class="vita-score-verdict">{verdict}</div>'
        f'<div class="vita-muted">نسبة الإجابات الصحيحة {percent}%'
        f'{f" · لم تُجب عن {unanswered}" if unanswered else ""}</div>'
        f'<div class="vita-bar"><span style="width:{percent}%"></span></div></div></div>'
    )
    for i, q in enumerate(questions):
        chosen = result["answers"].get(i)
        state = "skip" if chosen is None else ("ok" if chosen == q["answer"] else "bad")
        badge = {"ok": "✅ إجابة صحيحة", "bad": "❌ إجابة خاطئة", "skip": "⚪ لم تُجب"}[state]
        options = ""
        for j, option in enumerate(q["options"]):
            css, tag = "", ""
            if j == q["answer"]:
                css, tag = "correct", "الإجابة الصحيحة"
            if j == chosen and chosen != q["answer"]:
                css, tag = "wrong", "إجابتك"
            elif j == chosen:
                tag = "إجابتك ✓"
            tag_html = f"<small>{tag}</small>" if tag else ""
            options += f'<div class="vita-opt {css}">{QUIZ_LETTERS[j]}) {esc(option)}{tag_html}</div>'
        explanation = (
            f'<div class="vita-explain">💡 {esc(q["explanation"])}</div>' if q.get("explanation") else ""
        )
        html_block(
            f'<div class="vita-q {state}"><div class="vita-q-head"><span class="vita-q-title">'
            f'{i + 1}. {esc(q["question"])}</span><span class="vita-q-badge">{badge}</span></div>'
            f"{options}{explanation}</div>"
        )
    st.button("🔁 إعادة المحاولة", key=f"quiz_retry_{result['id']}", on_click=retry_quiz, args=(result,))


def page_notebook():
    u = U()
    page_header(
        "📚",
        "مساعد المستندات",
        "Vita Notebook",
        "ارفع أي ملف دراسي، ودع Vita يقرأه ويلخّصه ويحوّله إلى اختبار سريع وخريطة مفاهيمية.",
    )

    uploaded = st.file_uploader(
        "ارفع أي ملف دراسي (PDF أو Word أو PowerPoint أو Excel أو صورة أو ملف نصي)",
        type=None,
        key=f"nb_upload_{u['username']}",
        help="الحد الأقصى 25 ميجابايت. الصور وملفات PDF المصوّرة (مثل Canva والمسح الضوئي) تُقرأ بالتعرف الضوئي على النصوص.",
    )

    if uploaded is None:
        html_block(
            '<div class="vita-card vita-empty"><div class="vita-empty-icon">📄</div>'
            '<div class="vita-section" style="justify-content:center">ابدأ برفع ملف دراسي</div>'
            '<div class="vita-muted">يقبل Vita ملفات PDF (حتى المصوّرة منها)، Word، PowerPoint، Excel، الصور، '
            "والملفات النصية، ويقرأ النصوص العربية والإنجليزية من الصور تلقائياً.</div>"
            '<div class="vita-feature-row">'
            + "".join(
                f'<div class="vita-card"><b>{esc(t["label"])}</b><div class="vita-muted">{esc(t["desc"])}</div></div>'
                for t in NOTEBOOK_TASKS.values()
            )
            + "</div></div>"
        )
        render_notebook_history(u)
        return

    data = uploaded.getvalue()
    file_id = hashlib.sha1(data).hexdigest()[:16]
    try:
        parsed = parse_document(data, uploaded.name)
    except UnsupportedFile as err:
        st.warning(str(err), icon="📄")
        return
    except Exception as err:
        st.error(f"تعذّر قراءة الملف: {err}", icon="⚠️")
        return
    text, ocr_count, ocr_note = document_text(parsed, file_id)
    if ocr_note:
        st.warning(ocr_note, icon="🔍")
    if not text:
        st.warning(
            "لم نجد أي نص في هذا الملف، حتى بعد القراءة الضوئية. تأكد أن الملف يحتوي كتابة واضحة.", icon="📄"
        )
        return

    doc = u["notebook"].setdefault(
        file_id, {"name": uploaded.name, "results": {}, "uploaded": datetime.now()}
    )
    words = len(text.split())
    doc_limit = MAX_DOC_CHARS if get_api_key() else FREE_MAX_DOC_CHARS
    truncated = len(text) > doc_limit
    icon, kind_label, unit = FILE_KINDS[parsed["kind"]]
    count = parsed["count"]
    count_chip = f'<span class="vita-chip">📑 {count} {unit}</span>' if count and parsed["kind"] != "image" else ""
    ocr_chip = (
        f'<span class="vita-chip">🔍 قراءة ضوئية لـ {ocr_count} {"صورة" if parsed["kind"] != "pdf" else "صفحة"}</span>'
        if ocr_count
        else ""
    )
    html_block(
        '<div class="vita-card"><div class="vita-doc">'
        f'<div class="vita-doc-icon">{icon}</div><div style="flex:1">'
        f'<div class="vita-doc-name"><span class="vita-ltr">{esc(uploaded.name)}</span></div>'
        '<div class="vita-chips" style="margin-top:.4rem">'
        f'<span class="vita-chip">{esc(kind_label)}</span>'
        f"{count_chip}{ocr_chip}"
        f'<span class="vita-chip">🔤 {words:,} كلمة</span>'
        f'<span class="vita-chip">✍️ {len(text):,} حرف</span>'
        f'<span class="vita-chip">{"🟢 تمت معالجته" if file_id in u["processed_files"] else "⚪ جديد"}</span>'
        "</div></div></div></div>"
    )
    if truncated:
        st.info(f"المستند طويل، سيتم تحليل أول {doc_limit:,} حرف منه.", icon="✂️")

    with st.expander("👁️ معاينة النص المستخرج"):
        html_block(f'<div class="vita-preview">{esc(text[:4000])}{"…" if len(text) > 4000 else ""}</div>')

    section_title("🤖 أدوات Vita الذكية")
    o1, o2 = st.columns(2)
    n_questions = o1.slider("عدد أسئلة الاختبار", 3, 15, 5, key="nb_questions")
    difficulty = o2.radio(
        "مستوى الصعوبة", ["سهل", "متوسط", "صعب"], index=1, horizontal=True, key="nb_difficulty"
    )

    clicked = None
    for col, (kind, task) in zip(st.columns(3), NOTEBOOK_TASKS.items()):
        with col:
            done_mark = " ✓" if kind in doc["results"] else ""
            if st.button(task["label"] + done_mark, key=f"nb_{kind}", type="primary"):
                clicked = kind
            st.caption(task["desc"])

    view_key = f"nb_view_{file_id}"
    if clicked:
        section_title(f"⏳ Vita يعمل على: {NOTEBOOK_TASKS[clicked]['title']}")
        doc_text = text[:doc_limit]
        if clicked == "quiz":  # اختبار تفاعلي: أسئلة يجيب عنها الطالب ثم يُصحَّح
            with st.container(border=True):
                questions, source = generate_quiz(doc_text, uploaded.name, n_questions, difficulty)
            if not questions:
                st.warning("المستند قصير جداً لصنع اختبار منه. جرّب ملفاً أطول.", icon="📄")
                result, error = None, True
            else:
                result, error = quiz_markdown(questions, difficulty, source == "local"), None
        else:
            prompt = notebook_prompt(clicked, doc_text, uploaded.name, n_questions, difficulty)
            with st.container(border=True):
                result, error = stream_answer(
                    [{"role": "user", "parts": [{"text": prompt}]}],
                    NOTEBOOK_SYSTEM,
                    temperature=0.4,
                    fallback=lambda: local_notebook(clicked, doc_text, n_questions, difficulty),
                )
        if result and not error:
            doc["results"][clicked] = {"text": result, "time": datetime.now()}
            if clicked == "quiz":
                doc["results"]["quiz"].update(questions=questions, source=source, difficulty=difficulty)
                retry_quiz(doc["results"]["quiz"])
            if file_id not in u["processed_files"]:
                u["processed_files"].append(file_id)
                u["stats"]["files"] += 1
                flash("📄 أُضيف الملف إلى عداد الملفات الملخصة في ملفك الشخصي", icon="📄")
            log_activity("📚", f"{NOTEBOOK_TASKS[clicked]['title']} للملف «{uploaded.name}»")
            st.session_state[view_key] = clicked
            st.rerun()

    if doc["results"]:
        section_title("📌 نتائج المستند")
        kinds = [k for k in NOTEBOOK_TASKS if k in doc["results"]]
        if st.session_state.get(view_key) not in kinds:
            st.session_state[view_key] = kinds[-1]
        view = st.radio(
            "عرض النتيجة",
            kinds,
            format_func=lambda k: NOTEBOOK_TASKS[k]["label"],
            horizontal=True,
            key=view_key,
            label_visibility="collapsed",
        )
        result = doc["results"][view]
        with st.container(border=True):
            if view == "quiz" and result.get("questions"):
                render_quiz(result, uploaded.name)
            else:
                st.markdown(tidy_math(result["text"]))
        base_name = uploaded.name.rsplit(".", 1)[0]
        st.download_button(
            "⬇️ تنزيل النتيجة مع مفتاح الإجابات (Markdown)" if view == "quiz" else "⬇️ تنزيل النتيجة (Markdown)",
            data=result["text"].encode("utf-8"),
            file_name=f"{base_name}_{view}.md",
            mime="text/markdown",
            key=f"nb_download_{view}",
        )


def render_notebook_history(u):
    docs = [d for d in u["notebook"].values() if d["results"]]
    if not docs:
        return
    section_title("🗂️ مستنداتك المعالجة")
    for doc in reversed(docs):
        with st.expander(f"📄 {doc['name']} — {len(doc['results'])} نتيجة"):
            kinds = [k for k in NOTEBOOK_TASKS if k in doc["results"]]
            for tab, kind in zip(st.tabs([NOTEBOOK_TASKS[k]["label"] for k in kinds]), kinds):
                with tab:
                    st.markdown(tidy_math(doc["results"][kind]["text"]))


# ==================================================================
# 5) الملف الشخصي والإنتاجية
# ==================================================================
def level_info(stats):
    points = (
        stats["chats"] * 10
        + stats["messages"] * 2
        + stats["files"] * 25
        + stats["pomodoros"] * 20
        + stats["boards"] * 5
        + stats["sheets"] * 5
    )
    current, nxt = LEVELS[0], None
    for i, (threshold, name) in enumerate(LEVELS):
        if points >= threshold:
            current = (threshold, name)
            nxt = LEVELS[i + 1] if i + 1 < len(LEVELS) else None
    if nxt:
        progress = (points - current[0]) / (nxt[0] - current[0])
        hint = f"{nxt[0] - points} نقطة للوصول إلى {nxt[1]}"
    else:
        progress, hint = 1.0, "وصلت لأعلى مستوى! 🎉"
    return points, current[1], progress, hint


def pomo_widget_keys():
    name = st.session_state.current_user
    return f"pomo_mode_{name}", f"pomo_minutes_{name}"


def pomo_apply_mode(mode):
    p = U()["pomo"]
    p["mode"] = mode
    p["duration"] = int(p["minutes"][mode]) * 60
    p["remaining"] = p["duration"]
    p["running"] = False
    p["end_time"] = None


def pomo_remaining(p):
    if p["running"] and p["end_time"]:
        return max(0.0, p["end_time"] - time.time())
    return float(p["remaining"])


def pomo_tick():
    """يعالج انتهاء جلسة البومودورو (يُستدعى في بداية كل تشغيل كامل للتطبيق)."""
    u = U()
    p = u["pomo"]
    if not (p["running"] and p["end_time"] and time.time() >= p["end_time"]):
        return
    finished = p["mode"]
    if finished == "focus":
        u["stats"]["pomodoros"] += 1
        u["stats"]["focus_seconds"] += p["duration"]
        p["history"].append(date.today().isoformat())
        log_activity("🍅", f"أنهيت جلسة تركيز مدتها {p['duration'] // 60} دقيقة")
        flash("أحسنت! أنهيت جلسة تركيز كاملة — خذ استراحة قصيرة.", icon="🎉", balloons=True)
        next_mode = "long" if u["stats"]["pomodoros"] % 4 == 0 else "short"
    else:
        log_activity("☕", "أنهيت استراحة")
        flash("انتهت الاستراحة! جاهز لجلسة تركيز جديدة؟", icon="⏰")
        next_mode = "focus"
    pomo_apply_mode(next_mode)
    mode_key, minutes_key = pomo_widget_keys()
    st.session_state[mode_key] = next_mode
    st.session_state[minutes_key] = int(p["minutes"][next_mode])


def on_pomo_mode_change():
    mode_key, minutes_key = pomo_widget_keys()
    mode = st.session_state[mode_key]
    pomo_apply_mode(mode)
    st.session_state[minutes_key] = int(U()["pomo"]["minutes"][mode])


def on_pomo_minutes_change():
    _, minutes_key = pomo_widget_keys()
    p = U()["pomo"]
    p["minutes"][p["mode"]] = int(st.session_state[minutes_key])
    pomo_apply_mode(p["mode"])


def timer_ring(fraction, color, time_text, label):
    radius = 92
    circumference = 2 * math.pi * radius
    offset = circumference * (1 - max(0.0, min(1.0, fraction)))
    return (
        '<div class="vita-timer"><svg viewBox="0 0 220 220">'
        f'<circle cx="110" cy="110" r="{radius}" stroke="#334155" stroke-width="12" fill="none"/>'
        f'<circle cx="110" cy="110" r="{radius}" stroke="{color}" stroke-width="12" fill="none" '
        f'stroke-linecap="round" stroke-dasharray="{circumference:.2f}" stroke-dashoffset="{offset:.2f}" '
        'transform="rotate(-90 110 110)" style="transition:stroke-dashoffset .9s linear"/></svg>'
        f'<div class="vita-timer-center"><div class="vita-timer-time">{time_text}</div>'
        f'<div class="vita-timer-mode">{esc(label)}</div></div></div>'
    )


def render_pomodoro():
    u = U()
    p = u["pomo"]
    mode_key, minutes_key = pomo_widget_keys()
    st.session_state.setdefault(mode_key, p["mode"])
    st.session_state.setdefault(minutes_key, int(p["minutes"][p["mode"]]))

    section_title("⏱️ مؤقت المذاكرة (Pomodoro)")
    st.radio(
        "نوع الجلسة",
        list(POMO_MODES),
        format_func=lambda k: POMO_MODES[k]["label"],
        horizontal=True,
        key=mode_key,
        on_change=on_pomo_mode_change,
        disabled=p["running"],
        label_visibility="collapsed",
    )
    st.number_input(
        "مدة الجلسة (بالدقائق)",
        min_value=1,
        max_value=120,
        step=1,
        key=minutes_key,
        on_change=on_pomo_minutes_change,
        disabled=p["running"],
    )

    @st.fragment(run_every=1 if p["running"] else None)
    def timer_fragment():
        pomo = U()["pomo"]
        remaining = pomo_remaining(pomo)
        if pomo["running"] and remaining <= 0:
            st.rerun()
        seconds = int(math.ceil(remaining))
        mode = POMO_MODES[pomo["mode"]]
        status = "جارٍ الآن" if pomo["running"] else ("متوقف مؤقتاً" if seconds < pomo["duration"] else "جاهز للبدء")
        html_block(
            timer_ring(
                remaining / pomo["duration"] if pomo["duration"] else 0,
                mode["color"],
                f"{seconds // 60:02d}:{seconds % 60:02d}",
                f"{mode['label']} · {status}",
            )
        )
        c1, c2, c3 = st.columns(3)
        with c1:
            if st.button("▶️ بدء", key="pomo_start", type="primary", disabled=pomo["running"]):
                pomo["running"] = True
                pomo["end_time"] = time.time() + pomo_remaining(pomo)
                if pomo["remaining"] == pomo["duration"]:
                    log_activity("▶️", f"بدأت {mode['label']} لمدة {pomo['duration'] // 60} دقيقة")
                st.rerun()
        with c2:
            if st.button("⏸️ إيقاف", key="pomo_pause", disabled=not pomo["running"]):
                pomo["remaining"] = int(math.ceil(pomo_remaining(pomo)))
                pomo["running"] = False
                pomo["end_time"] = None
                st.rerun()
        with c3:
            if st.button("🔄 إعادة ضبط", key="pomo_reset"):
                pomo_apply_mode(pomo["mode"])
                st.rerun()

    timer_fragment()

    today_count = p["history"].count(date.today().isoformat())
    goal = min(1.0, today_count / DAILY_POMO_GOAL)
    html_block(
        '<div class="vita-card" style="margin-top:.6rem">'
        f'<div style="display:flex;justify-content:space-between"><b>🎯 هدف اليوم</b>'
        f'<span class="vita-muted">{today_count} / {DAILY_POMO_GOAL} جلسات</span></div>'
        f'<div class="vita-bar"><span style="width:{goal * 100:.0f}%"></span></div>'
        f'<small class="vita-muted">إجمالي وقت التركيز: {format_duration(u["stats"]["focus_seconds"])}</small></div>'
    )


def process_avatar(uploaded):
    image = Image.open(uploaded).convert("RGB")
    image = ImageOps.fit(image, (256, 256))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    data = buffer.getvalue()
    return data, "data:image/png;base64," + base64.b64encode(data).decode("ascii")


def render_profile_editor(u):
    profile = u["profile"]
    with st.expander("✏️ تعديل الملف الشخصي"):
        with st.form("profile_form", border=False):
            name = st.text_input("الاسم", value=profile["name"], max_chars=40)
            major = st.text_input("التخصص / المرحلة الدراسية", value=profile["major"], max_chars=60)
            bio = st.text_area("النبذة الشخصية", value=profile["bio"], max_chars=280, height=110)
            avatar = st.radio(
                "اختر صورتك الرمزية",
                AVATARS,
                index=AVATARS.index(profile["avatar"]) if profile["avatar"] in AVATARS else 0,
                horizontal=True,
            )
            image = st.file_uploader("أو ارفع صورة شخصية", type=["png", "jpg", "jpeg", "webp"])
            remove_image = False
            if profile.get("avatar_img"):
                remove_image = st.checkbox("إزالة الصورة المرفوعة واستخدام الرمز")
            submitted = st.form_submit_button("💾 حفظ التغييرات", type="primary")
        if submitted:
            if not name.strip():
                st.error("الاسم لا يمكن أن يكون فارغاً.", icon="⚠️")
                return
            profile.update({"name": name.strip(), "major": major.strip(), "bio": bio.strip(), "avatar": avatar})
            if remove_image:
                profile["avatar_img"], profile["avatar_bytes"] = None, None
            if image is not None:
                try:
                    profile["avatar_bytes"], profile["avatar_img"] = process_avatar(image)
                except Exception:
                    st.error("تعذّر قراءة الصورة المرفوعة.", icon="⚠️")
                    return
            log_activity("✏️", "حدّثت الملف الشخصي")
            flash("تم حفظ ملفك الشخصي", icon="✨")
            st.rerun()


def render_activity(u):
    section_title("🕒 سجل النشاط")
    items = u["activity"][:12]
    if not items:
        html_block('<div class="vita-card vita-muted">لا يوجد نشاط بعد.</div>')
        return
    rows = "".join(
        f'<div class="vita-tl-item"><div class="vita-tl-icon">{esc(a["icon"])}</div><div>'
        f'<div class="vita-tl-text">{esc(a["text"])}</div>'
        f'<div class="vita-tl-time">{time_ago(a["time"])}</div></div></div>'
        for a in items
    )
    html_block(f'<div class="vita-card">{rows}</div>')


def page_profile():
    u = U()
    profile, stats = u["profile"], u["stats"]
    page_header(
        "👤",
        "الملف الشخصي والإنتاجية",
        "Profile & Productivity",
        "تابع إنجازاتك، عدّل ملفك الشخصي، وركّز في مذاكرتك بمؤقت بومودورو.",
    )

    points, level, progress, hint = level_info(stats)
    major = f'<span class="vita-chip">🎓 {esc(profile["major"])}</span>' if profile["major"] else ""
    html_block(
        '<div class="vita-profile"><div class="vita-cover"></div><div class="vita-profile-body">'
        f'<div class="vita-profile-avatar">{avatar_html(profile, 112)}</div>'
        '<div class="vita-profile-info">'
        f'<div class="vita-profile-name">{esc(profile["name"])}</div>'
        f'<div class="vita-profile-handle"><span class="vita-ltr">@{esc(u["username"])}</span></div>'
        f'<div class="vita-bio">{esc(profile["bio"])}</div>'
        f'<div class="vita-profile-meta">{major}'
        f'<span class="vita-chip">📅 انضم {profile["joined"]:%Y/%m/%d}</span>'
        f'<span class="vita-chip">🔐 {stats["logins"]} تسجيل دخول</span></div></div>'
        '<div class="vita-level">'
        f'<span class="vita-badge">{esc(level)}</span>'
        f'<div class="vita-bar"><span style="width:{progress * 100:.0f}%"></span></div>'
        f"<small>⭐ {points} نقطة · {esc(hint)}</small></div>"
        "</div></div>"
    )

    section_title("📊 لوحة الإحصائيات")
    stat_tiles(
        [
            ("💬", stats["chats"], "المحادثات الجارية", "rgba(139,92,246,.18)"),
            ("📄", stats["files"], "الملفات الملخصة", "rgba(6,182,212,.18)"),
            ("🍅", stats["pomodoros"], "جلسات التركيز", "rgba(239,68,68,.16)"),
            ("⏳", format_duration(stats["focus_seconds"]), "وقت التركيز", "rgba(34,197,94,.16)"),
            ("✉️", stats["messages"], "الرسائل المرسلة", "rgba(245,158,11,.16)"),
        ]
    )

    timer_col, side_col = st.columns([1.15, 1], gap="large")
    with timer_col:
        with st.container(border=True):
            render_pomodoro()
    with side_col:
        render_profile_editor(u)
        render_activity(u)


# ==================================================================
# التشغيل الرئيسي
# ==================================================================
def main():
    st.set_page_config(
        page_title="Vita | مساعدك الدراسي الذكي",
        page_icon="🧬",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    st.markdown(CSS, unsafe_allow_html=True)
    init_state()

    current = st.session_state.current_user
    if not current or current not in st.session_state.users:
        st.session_state.current_user = None
        render_login()
        show_flash()
        return

    pomo_tick()
    render_sidebar()
    show_flash()

    pages = {
        "chat": page_chat,
        "board": page_board,
        "sheets": page_sheets,
        "notebook": page_notebook,
        "profile": page_profile,
    }
    pages.get(st.session_state.page, page_chat)()


if __name__ == "__main__":  # Streamlit يشغّل الملف بالاسم __main__
    main()
