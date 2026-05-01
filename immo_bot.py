import os
import re
import time
import json
import imaplib
import email
import requests
import html
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from datetime import datetime, date
from email.header import decode_header


# ============================================================
# CONFIG
# ============================================================

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
PRIVATE_CHAT_ID = os.getenv("PRIVATE_CHAT_ID")

EMAIL_CHECK_ENABLED = os.getenv("EMAIL_CHECK_ENABLED", "false").lower() == "true"
EMAIL_HOST = os.getenv("EMAIL_HOST")
EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")

INIT_MODE = os.getenv("INIT_MODE", "false").lower() == "true"

SEEN_FILE = "seen_ads.json"
TODAY_DEALS_FILE = "today_deals.json"
LAST_SUMMARY_FILE = "last_summary.txt"

SUMMARY_HOUR = 21

INTEREST_RATE = 0.045
REPAYMENT_RATE = 0.02
FINANCING_FACTOR = 1.10

GRUNDERWERBSTEUER_RATE = 0.06
NOTAR_GRUNDBUCH_RATE = 0.02

MIN_SCORE_FOR_INSTANT_MESSAGE = 55
EMAIL_MAX_TO_CHECK = 30

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0 Safari/537.36"
    )
}


SEARCH_URLS = [
    {
        "platform": "Kleinanzeigen",
        "url": "https://www.kleinanzeigen.de/s-haus-kaufen/giessen/preis::700000/c208l4678r50"
    },
    {
        "platform": "Kleinanzeigen",
        "url": "https://www.kleinanzeigen.de/s-wohnung-kaufen/giessen/preis::300000/c196l4678r50"
    },
    {
        "platform": "Kleinanzeigen",
        "url": "https://www.kleinanzeigen.de/s-immobilien/giessen/mehrfamilienhaus/k0c195l4678r50"
    },
    {
        "platform": "Kleinanzeigen",
        "url": "https://www.kleinanzeigen.de/s-immobilien/giessen/zweifamilienhaus/k0c195l4678r50"
    },
    {
        "platform": "Kleinanzeigen",
        "url": "https://www.kleinanzeigen.de/s-immobilien/giessen/dreifamilienhaus/k0c195l4678r50"
    },
    {
        "platform": "Kleinanzeigen",
        "url": "https://www.kleinanzeigen.de/s-immobilien/giessen/kapitalanlage/k0c195l4678r50"
    },
    {
        "platform": "Kleinanzeigen",
        "url": "https://www.kleinanzeigen.de/s-immobilien/giessen/rendite/k0c195l4678r50"
    },
    {
        "platform": "Kleinanzeigen",
        "url": "https://www.kleinanzeigen.de/s-immobilien/giessen/voll-vermietet/k0c195l4678r50"
    },
    {
        "platform": "Wohnungsboerse",
        "url": "https://www.wohnungsboerse.net/searches/index?estate_marketing_types=kauf%2C3&marketing_type=kauf&estate_types%5B0%5D=3&is_rendite=0&estate_id=&zipcodes%5B%5D=&cities%5B%5D=Giessen&districts%5B%5D=&term=Gie%C3%9Fen&umkreiskm=50&pricetext=&minprice=&maxprice=&sizetext=&minsize=&maxsize=&roomstext=&minrooms=&maxrooms="
    },
    {
        "platform": "Ohne-Makler",
        "url": "https://www.ohne-makler.net/immobilien/immobilie-kaufen/hessen/kreis-giessen/"
    },
]


SUPPORTED_EMAIL_DOMAINS = [
    "immobilienscout24.de",
    "immoscout24.de",
    "immowelt.de",
    "immonet.de",
    "kleinanzeigen.de",
    "meinestadt.de",
    "wohnungsboerse.net",
    "wohnungsbörse.net",
    "ohne-makler.net",
    "1a-immobilienmarkt.de",
    "immobilo.de",
    "immoweb.de",
    "ivd24immobilien.de",
    "kalaydo.de",
]


SUPPORTED_EMAIL_KEYWORDS = [
    "immobilienscout24",
    "immoscout24",
    "immowelt",
    "immonet",
    "kleinanzeigen",
    "meinestadt",
    "wohnungsboerse",
    "wohnungsbörse",
    "ohne-makler",
    "1a-immobilienmarkt",
    "immobilo",
    "immoweb",
    "ivd24",
    "kalaydo",
]


# ============================================================
# FILE HELPERS
# ============================================================

def load_seen():
    if not os.path.exists(SEEN_FILE):
        return set()

    try:
        with open(SEEN_FILE, "r", encoding="utf-8") as f:
            return set(json.load(f))
    except Exception:
        return set()


def save_seen(seen):
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(list(seen), f, ensure_ascii=False, indent=2)


def load_today_deals():
    if not os.path.exists(TODAY_DEALS_FILE):
        return []

    try:
        with open(TODAY_DEALS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def save_today_deals(deals):
    with open(TODAY_DEALS_FILE, "w", encoding="utf-8") as f:
        json.dump(deals, f, ensure_ascii=False, indent=2)


def add_deal_to_today(ad, result):
    deals = load_today_deals()
    today = date.today().isoformat()
    deal_id = ad.get("id")

    for d in deals:
        if d.get("id") == deal_id and d.get("date") == today:
            return

    deals.append({
        "id": deal_id,
        "date": today,
        "platform": ad.get("platform", "Unbekannt"),
        "title": ad.get("title"),
        "link": ad.get("link"),
        "price": ad.get("price"),
        "area": ad.get("area"),
        "rooms": ad.get("rooms"),
        "location": ad.get("location"),
        "seller_type": ad.get("seller_type", "Unklar"),
        "commission_percent": result.get("commission_percent"),
        "commission_euro": result.get("commission_euro"),
        "grunderwerbsteuer": result.get("grunderwerbsteuer"),
        "notar_grundbuch": result.get("notar_grundbuch"),
        "extra_costs_total": result.get("extra_costs_total"),
        "total_purchase_costs": result.get("total_purchase_costs"),
        "equity_needed_after_110": result.get("equity_needed_after_110"),
        "score": result.get("score"),
        "category": result.get("category"),
        "status": result.get("status"),
        "monthly_rent": result.get("monthly_rent"),
        "yearly_rent": result.get("yearly_rent"),
        "gross_yield": result.get("gross_yield"),
        "gross_yield_on_price": result.get("gross_yield_on_price"),
        "gross_yield_on_total": result.get("gross_yield_on_total"),
        "factor": result.get("factor"),
        "factor_on_price": result.get("factor_on_price"),
        "factor_on_total": result.get("factor_on_total"),
        "loan_amount": result.get("loan_amount"),
        "loan_amount_110": result.get("loan_amount_110"),
        "loan_amount_total": result.get("loan_amount_total"),
        "monthly_rate": result.get("monthly_rate"),
        "monthly_rate_110": result.get("monthly_rate_110"),
        "monthly_rate_total": result.get("monthly_rate_total"),
        "cashflow": result.get("cashflow"),
        "cashflow_110": result.get("cashflow_110"),
        "cashflow_total": result.get("cashflow_total"),
    })

    save_today_deals(deals)


def was_summary_sent_today():
    if not os.path.exists(LAST_SUMMARY_FILE):
        return False

    try:
        with open(LAST_SUMMARY_FILE, "r", encoding="utf-8") as f:
            return f.read().strip() == date.today().isoformat()
    except Exception:
        return False


def mark_summary_sent_today():
    with open(LAST_SUMMARY_FILE, "w", encoding="utf-8") as f:
        f.write(date.today().isoformat())


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram(message, chat_id=None):
    if not TELEGRAM_BOT_TOKEN:
        raise ValueError("TELEGRAM_BOT_TOKEN fehlt. Prüfe deine .env Datei oder GitHub Secrets.")

    target_chat_id = chat_id or TELEGRAM_CHAT_ID

    if not target_chat_id:
        raise ValueError("TELEGRAM_CHAT_ID fehlt. Prüfe deine .env Datei oder GitHub Secrets.")

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    payload = {
        "chat_id": target_chat_id,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": False
    }

    response = requests.post(url, data=payload, timeout=20)
    response.raise_for_status()


# ============================================================
# HELPERS
# ============================================================

def clean_text(value):
    if not value:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def tg(value):
    if value is None:
        return ""
    return html.escape(str(value))


def clean_location(value):
    text = clean_text(value)

    if " - " in text:
        text = text.split(" - ")[-1].strip()

    text = re.sub(r"^\d{5}\s+", "", text).strip()

    return text


def make_soup(html_text):
    try:
        return BeautifulSoup(html_text, "html5lib")
    except Exception as e:
        print(f"Parser-Fehler mit html5lib: {e}")
        return None


def decode_email_text(value):
    if not value:
        return ""

    decoded_parts = decode_header(value)
    result = ""

    for part, encoding in decoded_parts:
        if isinstance(part, bytes):
            result += part.decode(encoding or "utf-8", errors="ignore")
        else:
            result += part

    return clean_text(result)


def get_email_body(msg):
    parts = []
    links = []

    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            disposition = str(part.get("Content-Disposition") or "")

            if "attachment" in disposition.lower():
                continue

            payload = part.get_payload(decode=True)
            if not payload:
                continue

            charset = part.get_content_charset() or "utf-8"

            try:
                text = payload.decode(charset, errors="ignore")
            except Exception:
                text = payload.decode("utf-8", errors="ignore")

            if content_type == "text/plain":
                parts.append(text)

            elif content_type == "text/html":
                soup = make_soup(text)

                if soup:
                    for a in soup.find_all("a", href=True):
                        links.append(a["href"])

                    parts.append(soup.get_text(" ", strip=True))
                else:
                    parts.append(text)

    else:
        payload = msg.get_payload(decode=True)

        if payload:
            charset = msg.get_content_charset() or "utf-8"
            text = payload.decode(charset, errors="ignore")

            if msg.get_content_type() == "text/html":
                soup = make_soup(text)

                if soup:
                    for a in soup.find_all("a", href=True):
                        links.append(a["href"])

                    parts.append(soup.get_text(" ", strip=True))
                else:
                    parts.append(text)
            else:
                parts.append(text)

    return clean_text("\n".join(parts + links))


def normalize_url_for_id(url):
    if not url:
        return ""

    url = url.replace("&amp;", "&")
    url = url.split("#")[0]

    if "?" in url:
        base, query = url.split("?", 1)
        useful_params = []

        for part in query.split("&"):
            lower = part.lower()

            if lower.startswith((
                "utm_",
                "tracking",
                "ref",
                "referrer",
                "newsletter",
                "email",
                "cid",
                "mc_",
                "sc_",
                "cmp",
                "campaign"
            )):
                continue

            useful_params.append(part)

        if useful_params:
            url = base + "?" + "&".join(useful_params)
        else:
            url = base

    url = url.rstrip("/")

    return url


def is_bad_link(link):
    if not link:
        return True

    lower = link.lower()

    bad_parts = [
        "savedsearch",
        "delete",
        "unsubscribe",
        "abmelden",
        "datenschutz",
        "privacy",
        "agb",
        "impressum",
        "hilfe",
        "help",
        "kontakt",
        "email",
        "utm_",
        "tracking",
        "newsletter",
        "notification",
        "preferences",
        "settings",
        "static-immobilienscout24.de",
        "static.",
        "/static/",
        ".css",
        ".js",
        ".woff",
        ".woff2",
        ".ttf",
        ".svg",
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        "font",
        "makeitsans",
    ]

    return any(part in lower for part in bad_parts)


def is_likely_property_link(link):
    lower = link.lower()

    if "immobilienscout24.de" in lower or "immoscout24.de" in lower:
        return "/expose/" in lower or "/expose-" in lower or "expose/" in lower

    if "kleinanzeigen.de" in lower:
        return "/s-anzeige/" in lower

    good_parts = [
        "/expose/",
        "expose",
        "/angebot/",
        "/immobilien/",
        "/immobilie/",
        "/haus-kaufen/",
        "/wohnung-kaufen/",
        "/kaufen/",
        "/details/",
        "/objekt/",
    ]

    return any(part in lower for part in good_parts)


def extract_links_from_text(text):
    if not text:
        return []

    raw_links = re.findall(r"https?://[^\s<>\"']+", text)
    clean_links = []

    for link in raw_links:
        link = link.strip().rstrip(").,;]")
        link = link.replace("&amp;", "&")

        if is_bad_link(link):
            continue

        lower = link.lower()

        if any(domain in lower for domain in SUPPORTED_EMAIL_DOMAINS):
            if is_likely_property_link(link):
                clean_links.append(link)

    seen = set()
    unique = []

    for link in clean_links:
        key = normalize_url_for_id(link)

        if key not in seen:
            seen.add(key)
            unique.append(link)

    return unique


def detect_platform_from_link_or_sender(link, sender=""):
    text = f"{link} {sender}".lower()

    if "kleinanzeigen.de" in text:
        return "Kleinanzeigen"
    if "immobilienscout24.de" in text or "immoscout24.de" in text:
        return "ImmoScout"
    if "immowelt.de" in text:
        return "Immowelt"
    if "immonet.de" in text:
        return "Immonet"
    if "meinestadt.de" in text:
        return "Meinestadt"
    if "wohnungsboerse.net" in text or "wohnungsbörse.net" in text:
        return "Wohnungsboerse"
    if "ohne-makler.net" in text:
        return "Ohne-Makler"
    if "1a-immobilienmarkt.de" in text:
        return "1A-Immobilien"
    if "immobilo.de" in text:
        return "Immobilo"
    if "immoweb.de" in text:
        return "Immoweb"
    if "ivd24immobilien.de" in text:
        return "IVD24"
    if "kalaydo.de" in text:
        return "Kalaydo"

    return "E-Mail"


def extract_ad_id_from_url(url):
    if not url:
        return None

    clean_url = normalize_url_for_id(url)
    lower = clean_url.lower()

    patterns = [
        r"/expose/(\d+)",
        r"expose-(\d+)",
        r"/s-anzeige/.*?/(\d+)-",
        r"/s-anzeige/.*?/(\d+)$",
        r"/immobilie/(\d+)",
        r"/objekt/(\d+)",
        r"/angebot/(\d+)",
        r"id=(\d+)",
        r"objectid=(\d+)",
        r"estate_id=(\d+)",
    ]

    for pattern in patterns:
        match = re.search(pattern, lower)

        if match:
            return match.group(1)

    last_part = clean_url.split("/")[-1]
    match = re.search(r"(\d+)$", last_part)

    if match:
        return match.group(1)

    slug = re.sub(r"[^a-zA-Z0-9]+", "_", lower)

    return slug[-120:]


def parse_price(text):
    if not text:
        return None

    clean = text.replace(".", "").replace(",", ".")

    patterns = [
        r"(\d{2,})\s*€",
        r"€\s*(\d{2,})",
        r"kaufpreis\s*(\d{2,})",
        r"preis\s*(\d{2,})",
    ]

    for pattern in patterns:
        match = re.search(pattern, clean, re.IGNORECASE)

        if match:
            try:
                return int(float(match.group(1)))
            except ValueError:
                return None

    return None


def parse_area(text):
    if not text:
        return None

    clean = text.replace(",", ".")

    patterns = [
        r"(\d+(\.\d+)?)\s*m²",
        r"wohnfläche\s*(\d+(\.\d+)?)",
        r"fläche\s*(\d+(\.\d+)?)",
    ]

    for pattern in patterns:
        match = re.search(pattern, clean, re.IGNORECASE)

        if match:
            try:
                return float(match.group(1))
            except ValueError:
                return None

    return None


def parse_rooms(text):
    if not text:
        return None

    clean = text.replace(",", ".").lower()

    patterns = [
        r"(\d+(\.\d+)?)\s*zimmer",
        r"zimmer\s*(\d+(\.\d+)?)",
        r"(\d+(\.\d+)?)\s*zkb",
        r"(\d+(\.\d+)?)\s*zi\.",
    ]

    for pattern in patterns:
        match = re.search(pattern, clean)

        if match:
            try:
                return float(match.group(1))
            except ValueError:
                return None

    return None


def detect_seller_type(title, description):
    text = f"{title} {description}".lower()

    if "ohne-makler.net" in text or "ohne makler" in text:
        return "Privat/ohne Makler"

    private_words = [
        "privatverkauf",
        "von privat",
        "privat angeboten",
        "private anzeige",
        "provisionsfrei",
        "keine provision",
        "ohne provision",
        "ohne makler",
        "keine käuferprovision",
        "keine zusätzliche käuferprovision",
        "keine maklerprovision",
    ]

    broker_words = [
        "makler",
        "immobilienmakler",
        "maklercourtage",
        "maklerprovision",
        "käuferprovision",
        "courtage",
        "provision",
        "immobilien gmbh",
        "real estate",
        "immobilienservice",
        "immobilienvermittlung",
        "objektbetreuer",
        "exposé",
        "expose",
    ]

    company_words = [
        "gmbh",
        "ug ",
        "ohg",
        "kg ",
        "ag ",
        "immobilien",
        "real estate",
        "verwaltung",
        "hausverwaltung",
    ]

    if any(word in text for word in private_words):
        return "Privat/provisionsfrei"

    if any(word in text for word in broker_words):
        return "Makler/gewerblich"

    if any(word in text for word in company_words):
        return "Gewerblich wahrscheinlich"

    return "Unklar"


def parse_commission_percent(title, description):
    text = f"{title} {description}".lower()
    text = text.replace(",", ".")

    if "ohne-makler.net" in text or "ohne makler" in text:
        return 0.0

    free_words = [
        "provisionsfrei",
        "keine provision",
        "ohne provision",
        "ohne makler",
        "keine käuferprovision",
        "keine zusätzliche käuferprovision",
        "keine maklerprovision",
    ]

    if any(word in text for word in free_words):
        return 0.0

    patterns = [
        r"(\d+(\.\d+)?)\s*%\s*käuferprovision",
        r"käuferprovision\s*(\d+(\.\d+)?)\s*%",
        r"(\d+(\.\d+)?)\s*%\s*maklerprovision",
        r"maklerprovision\s*(\d+(\.\d+)?)\s*%",
        r"(\d+(\.\d+)?)\s*%\s*courtage",
        r"courtage\s*(\d+(\.\d+)?)\s*%",
        r"provision\s*(\d+(\.\d+)?)\s*%",
        r"(\d+(\.\d+)?)\s*%\s*provision",
    ]

    for pattern in patterns:
        match = re.search(pattern, text)

        if match:
            try:
                return float(match.group(1))
            except ValueError:
                return None

    if (
        "käuferprovision" in text
        or "maklercourtage" in text
        or "courtage" in text
        or "maklerprovision" in text
    ):
        return 3.57

    return None


def calculate_purchase_costs(price, commission_percent):
    if not price:
        return {
            "purchase_price": 0,
            "commission_percent": commission_percent,
            "commission_euro": 0,
            "grunderwerbsteuer": 0,
            "notar_grundbuch": 0,
            "extra_costs_total": 0,
            "total_purchase_costs": 0,
        }

    commission_euro = 0

    if commission_percent:
        commission_euro = price * commission_percent / 100

    grunderwerbsteuer = price * GRUNDERWERBSTEUER_RATE
    notar_grundbuch = price * NOTAR_GRUNDBUCH_RATE
    extra_costs_total = commission_euro + grunderwerbsteuer + notar_grundbuch
    total_purchase_costs = price + extra_costs_total

    return {
        "purchase_price": price,
        "commission_percent": commission_percent,
        "commission_euro": commission_euro,
        "grunderwerbsteuer": grunderwerbsteuer,
        "notar_grundbuch": notar_grundbuch,
        "extra_costs_total": extra_costs_total,
        "total_purchase_costs": total_purchase_costs,
    }


# ============================================================
# RENT ESTIMATION
# ============================================================

def estimate_rent_per_m2(location_text):
    text = location_text.lower()

    if "gießen" in text or "giessen" in text:
        return 12.0
    if "marburg" in text:
        return 12.0
    if "wetzlar" in text:
        return 10.5
    if "kirchhain" in text:
        return 9.5
    if "butzbach" in text:
        return 10.0
    if "lich" in text:
        return 9.5
    if "grünberg" in text or "gruenberg" in text:
        return 9.0
    if "laubach" in text:
        return 8.5
    if "hungen" in text:
        return 9.0
    if "reiskirchen" in text:
        return 9.5
    if "pohlheim" in text:
        return 10.0
    if "buseck" in text:
        return 9.5
    if "wetter" in text:
        return 9.0
    if "gladenbach" in text:
        return 8.5
    if "alsfeld" in text:
        return 8.0
    if "friedberg" in text:
        return 11.0
    if "bad nauheim" in text:
        return 11.5
    if "herborn" in text:
        return 9.0
    if "dillenburg" in text:
        return 8.5
    if "friedrichsdorf" in text:
        return 12.0
    if "bad homburg" in text:
        return 14.0
    if "kelkheim" in text:
        return 13.0

    return 10.0


# ============================================================
# FILTER UND BEWERTUNG
# ============================================================

def should_skip_ad(ad):
    title = ad.get("title", "").lower()
    location = ad.get("location", "").lower()
    description = ad.get("description", "").lower()
    full_text = ad.get("full_text", "").lower()

    text = f"{title} {location} {description} {full_text}"

    search_words_in_title = [
        "suche",
        "gesucht",
        "suchen",
        "wohnung gesucht",
        "haus gesucht",
        "grundstück gesucht",
        "immobilie gesucht",
    ]

    if any(word in title for word in search_words_in_title):
        print(f"Filter: Suchanzeige | {ad.get('title')}")
        return True

    land_words_title = [
        "grundstück",
        "baugrundstück",
        "bauland",
        "ackerland",
        "wiese",
        "gartengrundstück",
    ]

    building_words_title = [
        "haus",
        "wohnhaus",
        "mehrfamilienhaus",
        "zweifamilienhaus",
        "dreifamilienhaus",
        "familienhaus",
        "immobilie",
        "kapitalanlage",
        "wohnung",
        "parteienhaus",
        "sechsparteienhaus",
        "renditeobjekt",
        "anlageobjekt",
    ]

    title_has_land = any(word in title for word in land_words_title)
    title_has_building = any(word in title for word in building_words_title)

    if title_has_land and not title_has_building:
        print(f"Filter: Grundstück im Titel | {ad.get('title')}")
        return True

    hard_bad_keywords = [
        "erbpacht",
        "wohnrecht",
        "nießbrauch",
        "niessbrauch",
        "tausch",
        "ferienwohnung",
        "luxus",
        "penthouse",
        "zwangsversteigerung",
        "versteigerung",
    ]

    for word in hard_bad_keywords:
        if word in text:
            print(f"Filter: BAD_KEYWORD '{word}' | {ad.get('title')}")
            return True

    price = ad.get("price")
    area = ad.get("area")

    if price and area:
        price_per_m2 = price / area

        if price_per_m2 > 4000:
            print(f"Filter: Preis/m² zu hoch {price_per_m2:.0f} €/m² | {ad.get('title')}")
            return True

        if area < 30:
            print(f"Filter: Fläche zu klein {area:.1f} m² | {ad.get('title')}")
            return True

    return False


def evaluate_deal(price, area, location, title="", description="", commission_percent=None):
    if not price or not area:
        return {
            "status": "⚠️ Daten fehlen",
            "category": "unknown",
            "score": 0,
            "message": "Preis oder Wohnfläche konnte nicht sicher erkannt werden.",
            "commission_percent": commission_percent,
            "commission_euro": 0,
        }

    purchase_costs = calculate_purchase_costs(price, commission_percent)

    rent_per_m2 = estimate_rent_per_m2(location)
    monthly_rent = area * rent_per_m2
    yearly_rent = monthly_rent * 12

    total_purchase_costs = purchase_costs["total_purchase_costs"]

    gross_yield_on_price = yearly_rent / price * 100
    gross_yield_on_total = yearly_rent / total_purchase_costs * 100 if total_purchase_costs else 0

    factor_on_price = price / yearly_rent if yearly_rent else 0
    factor_on_total = total_purchase_costs / yearly_rent if yearly_rent else 0

    loan_amount_110 = price * FINANCING_FACTOR
    monthly_rate_110 = loan_amount_110 * (INTEREST_RATE + REPAYMENT_RATE) / 12

    loan_amount_total = total_purchase_costs
    monthly_rate_total = loan_amount_total * (INTEREST_RATE + REPAYMENT_RATE) / 12

    equity_needed_after_110 = max(0, total_purchase_costs - loan_amount_110)

    non_recoverable_costs = monthly_rent * 0.10

    cashflow_110 = monthly_rent - monthly_rate_110 - non_recoverable_costs
    cashflow_total = monthly_rent - monthly_rate_total - non_recoverable_costs

    text = f"{title} {description}".lower()

    score = 0

    if gross_yield_on_total >= 8:
        score += 40
    elif gross_yield_on_total >= 7:
        score += 30
    elif gross_yield_on_total >= 6:
        score += 20
    elif gross_yield_on_total >= 5.5:
        score += 10
    else:
        score += 3

    if factor_on_total <= 13:
        score += 25
    elif factor_on_total <= 15:
        score += 15
    elif factor_on_total <= 17:
        score += 5

    if cashflow_total >= 0:
        score += 25
    elif cashflow_total >= -200:
        score += 15
    elif cashflow_total >= -400:
        score += 5

    if any(word in text for word in [
        "mehrfamilienhaus",
        "3-familienhaus",
        "dreifamilienhaus",
        "zweifamilienhaus",
        "anlageobjekt",
        "kapitalanlage",
        "voll vermietet",
        "rendite",
    ]):
        score += 10

    if any(word in text for word in ["wg", "studenten", "monteur", "zimmervermietung"]):
        score += 5

    if any(word in text for word in ["souterrain", "erbpacht", "nießbrauch", "niessbrauch", "wohnrecht"]):
        score -= 15

    if commission_percent and commission_percent > 0:
        score -= 5

    if score >= 75:
        status = "✅ Gut"
        category = "good"
    elif score >= 55:
        status = "🟡 Knapp"
        category = "maybe"
    else:
        status = "❌ Schwach"
        category = "bad"

    return {
        "status": status,
        "category": category,
        "score": score,
        "rent_per_m2": rent_per_m2,
        "monthly_rent": monthly_rent,
        "yearly_rent": yearly_rent,
        "gross_yield": gross_yield_on_total,
        "gross_yield_on_price": gross_yield_on_price,
        "gross_yield_on_total": gross_yield_on_total,
        "factor": factor_on_total,
        "factor_on_price": factor_on_price,
        "factor_on_total": factor_on_total,
        "loan_amount": loan_amount_total,
        "loan_amount_110": loan_amount_110,
        "loan_amount_total": loan_amount_total,
        "monthly_rate": monthly_rate_total,
        "monthly_rate_110": monthly_rate_110,
        "monthly_rate_total": monthly_rate_total,
        "cashflow": cashflow_total,
        "cashflow_110": cashflow_110,
        "cashflow_total": cashflow_total,
        "equity_needed_after_110": equity_needed_after_110,
        **purchase_costs,
    }


# ============================================================
# SCRAPER
# ============================================================

def scrape_kleinanzeigen_search_page(url):
    response = requests.get(url, headers=HEADERS, timeout=30)

    print("Kleinanzeigen HTTP:", response.status_code, response.url)
    print("HTML Länge:", len(response.text))

    if "captcha" in response.text.lower() or "g-recaptcha" in response.text.lower():
        print("WARNUNG: Kleinanzeigen blockt evtl. mit Captcha.")
        return []

    response.raise_for_status()

    soup = make_soup(response.text)

    if soup is None:
        return []

    ads = []

    articles = soup.select("article.aditem")
    print("article.aditem gefunden:", len(articles))

    for article in articles:
        link_tag = (
            article.select_one("a.ellipsis")
            or article.select_one("a[href*='/s-anzeige/']")
            or article.select_one("a[href*='/s-']")
        )

        if not link_tag:
            continue

        href = link_tag.get("href")

        if not href:
            continue

        full_link = urljoin("https://www.kleinanzeigen.de", href.split("?")[0])

        if "/s-anzeige/" not in full_link:
            continue

        title = clean_text(link_tag.get_text(" ", strip=True))

        if not title:
            title_tag = article.select_one("h2, h3")
            title = clean_text(title_tag.get_text(" ", strip=True)) if title_tag else "Kleinanzeigen Angebot"

        raw_ad_id = extract_ad_id_from_url(full_link)
        ad_id = f"kleinanzeigen_{raw_ad_id}"

        article_text = clean_text(article.get_text(" ", strip=True))

        price = parse_price(article_text)
        area = parse_area(article_text)
        rooms = parse_rooms(article_text)

        location_tag = (
            article.select_one(".aditem-main--top--left")
            or article.select_one("[class*='location']")
        )

        location = clean_location(location_tag.get_text(" ", strip=True)) if location_tag else ""

        desc_tag = article.select_one(".aditem-main--middle--description")
        description = clean_text(desc_tag.get_text(" ", strip=True)) if desc_tag else article_text

        ads.append({
            "id": ad_id,
            "platform": "Kleinanzeigen",
            "title": title,
            "link": full_link,
            "price": price,
            "area": area,
            "rooms": rooms,
            "location": location,
            "description": description,
            "full_text": description,
        })

    return ads


def enrich_kleinanzeigen_detail(ad):
    try:
        response = requests.get(ad["link"], headers=HEADERS, timeout=30)
        response.raise_for_status()
    except Exception as e:
        print(f"Detailseite konnte nicht gelesen werden: {ad.get('link')} | {e}")
        return ad

    soup = make_soup(response.text)

    if soup is None:
        return ad

    page_text = clean_text(soup.get_text(" ", strip=True))

    description = ""

    desc_candidates = [
        "#viewad-description-text",
        ".viewad-description",
        "[data-testid='ad-description']",
    ]

    for selector in desc_candidates:
        tag = soup.select_one(selector)

        if tag:
            description = clean_text(tag.get_text(" ", strip=True))
            break

    if not description:
        description = page_text

    ad["description"] = description
    ad["full_text"] = page_text

    if not ad.get("price"):
        ad["price"] = parse_price(page_text)

    if not ad.get("area"):
        ad["area"] = parse_area(page_text)

    if not ad.get("rooms"):
        ad["rooms"] = parse_rooms(page_text)

    return ad


def scrape_wohnungsboerse_search_page(url):
    response = None

    for attempt in range(3):
        try:
            response = requests.get(url, headers=HEADERS, timeout=60)
            response.raise_for_status()
            break
        except Exception as e:
            print(f"Wohnungsboerse Versuch {attempt + 1}/3 fehlgeschlagen: {e}")
            time.sleep(5)

    if response is None:
        return []

    soup = make_soup(response.text)

    if soup is None:
        return []

    ads = []
    seen_links = set()

    for a in soup.find_all("a"):
        href = a.get("href")
        text = clean_text(a.get_text(" ", strip=True))

        if not href or not text:
            continue

        lower = text.lower()

        if "€" not in text and "kaufpreis" not in lower:
            continue

        if "m²" not in text and "fläche" not in lower:
            continue

        full_link = urljoin("https://www.wohnungsboerse.net", href)
        clean_link = normalize_url_for_id(full_link)

        if clean_link in seen_links:
            continue

        seen_links.add(clean_link)

        raw_id = extract_ad_id_from_url(full_link)
        ad_id = f"wohnungsboerse_{raw_id}"

        price = parse_price(text)
        area = parse_area(text)
        rooms = parse_rooms(text)
        location = extract_location_from_email_text(text)

        title = text

        if "Kaufpreis" in title:
            title = title.split("Kaufpreis")[0].strip()

        if len(title) > 120:
            title = title[:120].strip() + "..."

        ads.append({
            "id": ad_id,
            "platform": "Wohnungsboerse",
            "title": title,
            "link": full_link,
            "price": price,
            "area": area,
            "rooms": rooms,
            "location": location,
            "description": text,
            "full_text": text,
        })

    return ads


def scrape_ohne_makler_search_page(url):
    response = requests.get(url, headers=HEADERS, timeout=30)
    response.raise_for_status()

    soup = make_soup(response.text)

    if soup is None:
        return []

    ads = []
    seen_links = set()

    for a in soup.find_all("a"):
        href = a.get("href")
        text = clean_text(a.get_text(" ", strip=True))

        if not href or not text:
            continue

        lower = text.lower()

        if "€" not in text:
            continue

        if "m²" not in text:
            continue

        if "monatsrate" not in lower and "zimmer" not in lower and "m²" not in lower:
            continue

        full_link = urljoin("https://www.ohne-makler.net", href)
        clean_link = normalize_url_for_id(full_link)

        if clean_link in seen_links:
            continue

        seen_links.add(clean_link)

        raw_id = extract_ad_id_from_url(full_link)
        ad_id = f"ohne_makler_{raw_id}"

        price = parse_price(text)
        area = parse_area(text)
        rooms = parse_rooms(text)
        location = extract_location_from_email_text(text)

        title = text

        if len(title) > 120:
            title = title[:120].strip() + "..."

        ads.append({
            "id": ad_id,
            "platform": "Ohne-Makler",
            "title": title,
            "link": full_link,
            "price": price,
            "area": area,
            "rooms": rooms,
            "location": location,
            "description": text + " ohne-makler.net provisionsfrei ohne Makler",
            "full_text": text + " ohne-makler.net provisionsfrei ohne Makler",
        })

    return ads


# ============================================================
# EMAIL
# ============================================================

def extract_location_from_email_text(text):
    text = clean_text(text)

    known_locations = [
        "Gießen", "Giessen", "Marburg", "Wetzlar", "Kirchhain", "Butzbach",
        "Lich", "Grünberg", "Gruenberg", "Laubach", "Hungen", "Reiskirchen",
        "Pohlheim", "Buseck", "Wetter", "Gladenbach", "Alsfeld", "Friedberg",
        "Bad Nauheim", "Herborn", "Dillenburg", "Friedrichsdorf", "Bad Homburg",
        "Kelkheim"
    ]

    lower = text.lower()

    for loc in known_locations:
        if loc.lower() in lower:
            return "Gießen" if loc.lower() == "giessen" else loc

    match = re.search(r"\b\d{5}\s+([A-ZÄÖÜ][a-zäöüß\-]+)", text)

    if match:
        return clean_location(match.group(0))

    return ""


def fetch_email_ads():
    ads = []

    if not EMAIL_CHECK_ENABLED:
        return ads

    if not EMAIL_HOST or not EMAIL_USER or not EMAIL_PASSWORD:
        print("E-Mail Prüfung aktiv, aber EMAIL_HOST/EMAIL_USER/EMAIL_PASSWORD fehlt.")
        return ads

    try:
        mail = imaplib.IMAP4_SSL(EMAIL_HOST)
        mail.login(EMAIL_USER, EMAIL_PASSWORD)
        mail.select("inbox")

        status, data = mail.search(None, "UNSEEN")

        if status != "OK":
            mail.logout()
            return ads

        email_ids = data[0].split()

        if not email_ids:
            mail.logout()
            return ads

        latest_ids = email_ids[-EMAIL_MAX_TO_CHECK:]

        print(f"Gmail: {len(latest_ids)} ungelesene Mails werden geprüft")

        for mail_id in latest_ids:
            try:
                status, msg_data = mail.fetch(mail_id, "(RFC822)")

                if status != "OK":
                    continue

                msg = email.message_from_bytes(msg_data[0][1])

                sender = decode_email_text(msg.get("From"))
                subject = decode_email_text(msg.get("Subject"))
                body = get_email_body(msg)

                combined_text = clean_text(f"{subject} {sender} {body}")
                lower_text = combined_text.lower()

                if not any(x in lower_text for x in SUPPORTED_EMAIL_KEYWORDS):
                    continue

                links = extract_links_from_text(combined_text)

                for link in links:
                    platform = detect_platform_from_link_or_sender(link, sender)
                    raw_id = extract_ad_id_from_url(link)
                    ad_id = f"{platform.lower()}_{raw_id}"

                    title = subject or f"Neues Angebot von {platform}"

                    price = parse_price(combined_text)
                    area = parse_area(combined_text)
                    rooms = parse_rooms(combined_text)
                    location = extract_location_from_email_text(combined_text)

                    ads.append({
                        "id": ad_id,
                        "platform": platform,
                        "title": title,
                        "link": link,
                        "price": price,
                        "area": area,
                        "rooms": rooms,
                        "location": location,
                        "description": combined_text,
                        "full_text": combined_text,
                        "source": "email",
                    })

            except Exception as e:
                print(f"E-Mail konnte nicht verarbeitet werden: {e}")

        mail.logout()

    except Exception as e:
        print(f"Gmail Fehler: {e}")

    return ads


def enrich_external_detail(ad):
    platform = ad.get("platform")

    if platform == "Kleinanzeigen":
        return enrich_kleinanzeigen_detail(ad)

    try:
        response = requests.get(ad["link"], headers=HEADERS, timeout=30, allow_redirects=True)
        response.raise_for_status()
    except Exception as e:
        print(f"Externe Detailseite konnte nicht gelesen werden: {ad.get('link')} | {e}")
        return ad

    soup = make_soup(response.text)

    if soup is None:
        return ad

    page_text = clean_text(soup.get_text(" ", strip=True))

    if page_text:
        ad["full_text"] = clean_text(ad.get("full_text", "") + " " + page_text)
        ad["description"] = ad["full_text"]

    if not ad.get("price"):
        ad["price"] = parse_price(page_text)

    if not ad.get("area"):
        ad["area"] = parse_area(page_text)

    if not ad.get("rooms"):
        ad["rooms"] = parse_rooms(page_text)

    if not ad.get("location"):
        ad["location"] = extract_location_from_email_text(page_text)

    return ad


def scrape_platform(platform, url):
    if platform == "Kleinanzeigen":
        return scrape_kleinanzeigen_search_page(url)

    if platform == "Wohnungsboerse":
        return scrape_wohnungsboerse_search_page(url)

    if platform == "Ohne-Makler":
        return scrape_ohne_makler_search_page(url)

    return []


# ============================================================
# FORMAT
# ============================================================

def euro(value):
    if value is None:
        return "?"
    return f"{value:,.0f} €".replace(",", ".")


def format_commission_text(result):
    commission_percent = result.get("commission_percent")
    commission_euro = result.get("commission_euro", 0)

    if commission_percent is None:
        return "Provision: unklar"

    if commission_percent == 0:
        return "Provision: 0%"

    return f"Provision: {commission_percent:.2f}% ≈ {commission_euro:.0f} €"


def format_message(ad, result):
    title = tg(ad.get("title", "Unbekanntes Angebot"))
    platform = tg(ad.get("platform", "Unbekannt"))
    location = tg(ad.get("location", ""))
    link = tg(ad.get("link", ""))

    price_text = tg(euro(ad.get("price")))
    area_text = f"{ad['area']:.0f} m²" if ad.get("area") else "? m²"
    rooms_text = f"{ad['rooms']:.1f} Zimmer" if ad.get("rooms") else "? Zimmer"

    seller_type = tg(ad.get("seller_type", "Unklar"))
    commission_text = tg(format_commission_text(result))

    status = tg(result.get("status", ""))
    score = result.get("score", 0)

    if "monthly_rent" not in result:
        return (
            f"🏠 <b>{title}</b>\n\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📍 <b>Objekt</b>\n"
            f"<b>Plattform:</b> {platform}\n"
            f"<b>Ort:</b> {location}\n"
            f"<b>Kaufpreis:</b> {price_text}\n"
            f"<b>Wohnfläche:</b> {area_text}\n"
            f"<b>Zimmer:</b> {rooms_text}\n\n"

            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 <b>Anbieter & Provision</b>\n"
            f"<b>Anbieter:</b> {seller_type}\n"
            f"<b>{commission_text}</b>\n\n"

            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"✅ <b>Bewertung</b>\n"
            f"<b>Status:</b> {status}\n"
            f"<b>Score:</b> {score}\n\n"

            f"🔗 {link}"
        )

    return (
        f"🏠 <b>{title}</b>\n\n"

        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📍 <b>Objekt</b>\n"
        f"<b>Plattform:</b> {platform}\n"
        f"<b>Ort:</b> {location}\n"
        f"<b>Kaufpreis:</b> {price_text}\n"
        f"<b>Wohnfläche:</b> {area_text}\n"
        f"<b>Zimmer:</b> {rooms_text}\n\n"

        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 <b>Anbieter & Provision</b>\n"
        f"<b>Anbieter:</b> {seller_type}\n"
        f"<b>{commission_text}</b>\n\n"

        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 <b>Kaufnebenkosten</b>\n"
        f"<b>Grunderwerbsteuer:</b> {result['grunderwerbsteuer']:.0f} €\n"
        f"<b>Notar & Grundbuch:</b> {result['notar_grundbuch']:.0f} €\n"
        f"<b>Gesamtkosten:</b> {result['total_purchase_costs']:.0f} €\n"
        f"<b>Benötigtes Eigenkapital nach 110%-Finanzierung:</b> {result['equity_needed_after_110']:.0f} €\n\n"

        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🏦 <b>Finanzierung</b>\n"
        f"<b>Monatliche Rate bei 110%-Finanzierung:</b> {result['monthly_rate_110']:.0f} €\n"
        f"<b>Monatliche Rate bei Finanzierung der Gesamtkosten:</b> {result['monthly_rate_total']:.0f} €\n\n"

        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🏘️ <b>Miete & Rendite</b>\n"
        f"<b>Geschätzte Monatsmiete:</b> {result['monthly_rent']:.0f} €\n"
        f"<b>Geschätzte Jahresmiete:</b> {result['yearly_rent']:.0f} €\n"
        f"<b>Bruttorendite auf Kaufpreis:</b> {result['gross_yield_on_price']:.2f}%\n"
        f"<b>Bruttorendite auf Gesamtkosten:</b> {result['gross_yield_on_total']:.2f}%\n"
        f"<b>Kaufpreisfaktor auf Kaufpreis:</b> {result['factor_on_price']:.1f}\n"
        f"<b>Kaufpreisfaktor auf Gesamtkosten:</b> {result['factor_on_total']:.1f}\n\n"

        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📈 <b>Monatliches Ergebnis</b>\n"
        f"<b>Überschuss bei 110%-Finanzierung:</b> {result['cashflow_110']:.0f} €\n"
        f"<b>Überschuss bei Finanzierung der Gesamtkosten:</b> {result['cashflow_total']:.0f} €\n\n"

        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"✅ <b>Bewertung</b>\n"
        f"<b>Status:</b> {status}\n"
        f"<b>Score:</b> {score}\n\n"

        f"🔗 {link}"
    )


def format_summary_deal(d):
    title = tg(d.get("title", ""))
    platform = tg(d.get("platform", ""))
    location = tg(d.get("location", ""))
    link = tg(d.get("link", ""))

    price = d.get("price") or 0
    area = d.get("area") or 0
    rooms = d.get("rooms")

    commission_percent = d.get("commission_percent")
    commission_euro = d.get("commission_euro") or 0

    if commission_percent is None:
        commission_text = "Provision: unklar"
    elif commission_percent == 0:
        commission_text = "Provision: 0%"
    else:
        commission_text = f"Provision: {commission_percent:.2f}% ≈ {commission_euro:.0f} €"

    rooms_text = f"{rooms:.1f} Zimmer" if isinstance(rooms, (int, float)) else "? Zimmer"

    return (
        f"<b>{tg(d.get('status'))} | Score {d.get('score')}</b>\n"
        f"<b>{title}</b>\n"
        f"<b>Plattform:</b> {platform}\n"
        f"<b>Ort:</b> {location}\n"
        f"<b>Kaufpreis:</b> {price:.0f} €\n"
        f"<b>Wohnfläche:</b> {area:.0f} m²\n"
        f"<b>Zimmer:</b> {rooms_text}\n"
        f"<b>Anbieter:</b> {tg(d.get('seller_type'))}\n"
        f"<b>{tg(commission_text)}</b>\n"
        f"<b>Gesamtkosten:</b> {d.get('total_purchase_costs', 0):.0f} €\n"
        f"<b>Eigenkapital nach 110%-Finanzierung:</b> {d.get('equity_needed_after_110', 0):.0f} €\n"
        f"<b>Monatsmiete:</b> {d.get('monthly_rent', 0):.0f} €\n"
        f"<b>Bruttorendite:</b> {d.get('gross_yield_on_total', 0):.2f}%\n"
        f"<b>Kaufpreisfaktor:</b> {d.get('factor_on_total', 0):.1f}\n"
        f"<b>Überschuss 110%-Finanzierung:</b> {d.get('cashflow_110', 0):.0f} €\n"
        f"<b>Überschuss Gesamtkosten-Finanzierung:</b> {d.get('cashflow_total', 0):.0f} €\n"
        f"{link}\n\n"
    )


# ============================================================
# SUMMARY
# ============================================================

def send_daily_summary_if_needed():
    now = datetime.now()

    if now.hour != SUMMARY_HOUR:
        return

    if was_summary_sent_today():
        return

    deals = load_today_deals()
    today = date.today().isoformat()

    today_deals = [d for d in deals if d.get("date") == today]

    good_deals = [d for d in today_deals if d.get("category") == "good"]
    maybe_deals = [d for d in today_deals if d.get("category") == "maybe"]

    if not good_deals and not maybe_deals:
        send_telegram("📊 <b>Tageszusammenfassung</b>\n\nHeute keine guten oder knappen Angebote gefunden.")
        mark_summary_sent_today()
        return

    good_deals = sorted(good_deals, key=lambda x: x.get("score", 0), reverse=True)
    maybe_deals = sorted(maybe_deals, key=lambda x: x.get("score", 0), reverse=True)

    message = f"📊 <b>Tageszusammenfassung {today}</b>\n\n"

    if good_deals:
        message += "✅ <b>Gute Angebote</b>\n\n"

        for d in good_deals[:5]:
            message += format_summary_deal(d)

    if maybe_deals:
        message += "🟡 <b>Knappe Angebote</b>\n\n"

        for d in maybe_deals[:5]:
            message += format_summary_deal(d)

    if len(message) > 3900:
        message = message[:3900] + "\n\n... gekürzt"

    send_telegram(message)
    mark_summary_sent_today()


# ============================================================
# MAIN PROCESSING
# ============================================================

def process_ads(ads, seen, new_seen):
    for ad in ads:
        if not ad.get("id"):
            continue

        if ad["id"] in seen or ad["id"] in new_seen:
            print(f"Schon gesehen: {ad.get('platform')} | {ad.get('title')}")
            continue

        try:
            if ad.get("platform") == "Kleinanzeigen":
                ad = enrich_kleinanzeigen_detail(ad)
                time.sleep(1)

            elif ad.get("platform") in ["Wohnungsboerse", "Ohne-Makler"]:
                ad = enrich_external_detail(ad)
                time.sleep(1)

            elif ad.get("source") == "email":
                ad = enrich_external_detail(ad)
                time.sleep(1)

            title = ad.get("title", "")
            description = ad.get("description", "")
            full_text = ad.get("full_text", description)

            ad["seller_type"] = detect_seller_type(title, full_text)
            commission_percent = parse_commission_percent(title, full_text)

            if should_skip_ad(ad):
                new_seen.add(ad["id"])
                save_seen(new_seen)
                continue

            result = evaluate_deal(
                ad.get("price"),
                ad.get("area"),
                ad.get("location", ""),
                title=title,
                description=full_text,
                commission_percent=commission_percent
            )

            if result.get("category") in ["good", "maybe"]:
                add_deal_to_today(ad, result)

            if INIT_MODE:
                print(f"INIT gespeichert, nicht gesendet: {ad.get('platform')} | {ad.get('title')}")
                new_seen.add(ad["id"])
                save_seen(new_seen)
                continue

            if result.get("score", 0) < MIN_SCORE_FOR_INSTANT_MESSAGE:
                print(f"Nicht gesendet, Score zu niedrig: {result.get('score')} | {ad.get('title')}")
                new_seen.add(ad["id"])
                save_seen(new_seen)
                continue

            message = format_message(ad, result)

            # Wichtig:
            # Die ID wird VOR Telegram gespeichert.
            # Falls der Prozess nach dem Senden abbricht, wird das Angebot nicht erneut gesendet.
            new_seen.add(ad["id"])
            save_seen(new_seen)

            try:
                send_telegram(message)

                if PRIVATE_CHAT_ID:
                    send_telegram("🔔 <b>Neues Angebot:</b>\n\n" + message, chat_id=PRIVATE_CHAT_ID)

                print(f"Gesendet und gespeichert: {ad.get('title')}")
                time.sleep(2)

            except Exception as e:
                print(f"Telegram Fehler, aber ID wurde bereits gespeichert: {e}")

        except Exception as e:
            print(f"Anzeige übersprungen wegen Fehler: {ad.get('title')} | {e}")
            new_seen.add(ad["id"])
            save_seen(new_seen)
            continue


def run_once():
    print("\n" + "=" * 70)
    print("Neue Suche gestartet:", datetime.now().strftime("%d.%m.%Y %H:%M:%S"))
    print("Arbeitsordner:", os.getcwd())
    print("=" * 70)

    seen = load_seen()
    new_seen = set(seen)

    print("Gesehene Anzeigen beim Start:", len(seen))

    for search in SEARCH_URLS:
        platform = search["platform"]
        search_url = search["url"]

        try:
            ads = scrape_platform(platform, search_url)
        except Exception as e:
            print(f"Fehler bei Suche {platform} | {search_url}: {e}")
            continue

        print(f"\n{platform}: {len(ads)} Anzeigen gefunden")

        for ad in ads[:20]:
            status = "ALT" if ad.get("id") in seen else "NEU"
            print(
                f"  {status} | {ad.get('platform')} | "
                f"{ad.get('title')} | {ad.get('price')} | "
                f"{ad.get('area')} | {ad.get('link')}"
            )

        process_ads(ads, seen, new_seen)

    try:
        email_ads = fetch_email_ads()

        if email_ads:
            print(f"\nGmail: {len(email_ads)} Immobilien-Links gefunden")

            for ad in email_ads[:20]:
                status = "ALT" if ad.get("id") in seen else "NEU"
                print(
                    f"  {status} | {ad.get('platform')} | "
                    f"{ad.get('title')} | {ad.get('price')} | "
                    f"{ad.get('area')} | {ad.get('link')}"
                )

            process_ads(email_ads, seen, new_seen)

    except Exception as e:
        print(f"Gmail Verarbeitung Fehler: {e}")

    save_seen(new_seen)

    print("\n" + "-" * 70)
    print("Lauf beendet.")
    print("Gesehene Anzeigen beim Start:", len(seen))
    print("Neue gespeicherte Anzeigen:", len(new_seen) - len(seen))
    print("Gesamt gespeicherte Anzeigen:", len(new_seen))
    print("-" * 70)

    try:
        send_daily_summary_if_needed()
    except Exception as e:
        print(f"Fehler Tageszusammenfassung: {e}")


if __name__ == "__main__":
    print("Immo Bot gestartet.")
    print("Telegram Chat:", TELEGRAM_CHAT_ID)
    print("Private Chat:", PRIVATE_CHAT_ID)
    print("E-Mail Check:", EMAIL_CHECK_ENABLED)
    print("E-Mail User:", EMAIL_USER)
    print("INIT_MODE:", INIT_MODE)
    print("GitHub-Actions-Modus: einmaliger Lauf.")

    run_once()

    print("Lauf beendet.")
