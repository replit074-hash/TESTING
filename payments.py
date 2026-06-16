import requests
import json
import asyncio
import logging
import random
import string
from typing import Optional, Dict, Any
from datetime import datetime, timedelta

from aiogram.types import InlineKeyboardMarkup
import database as db

# ═══════════════════════════════════════════════════════════════════════════════
# OXAPAY CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════════

API_KEY = "Q70QZV-GSSNNC-BGXM3M-XMOAUR"
CALLBACK_URL = "https://cxchk.site/payment_callback"
API_BASE = "https://api.oxapay.com/v1"

# ═══════════════════════════════════════════════════════════════════════════════
# DIRECT NETWORK MAPPING
# ═══════════════════════════════════════════════════════════════════════════════

DIRECT_NETWORKS: Dict[str, Dict[str, str]] = {
    "BEP20": {"currency": "USDT", "network": "BSC"},
    "TRC20": {"currency": "USDT", "network": "TRC20"},
    "LTC":   {"currency": "LTC",  "network": "Litecoin"},
    "BTC":   {"currency": "BTC",  "network": "Bitcoin"},
    "SOL":   {"currency": "SOL",  "network": "Solana"},
    "POL":   {"currency": "POL",  "network": "Polygon"},
    "TON":   {"currency": "TON",  "network": "TON"},
}

# ═══════════════════════════════════════════════════════════════════════════════
# PLAN CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════════

PLANS: Dict[str, Dict[str, Any]] = {
    "LITE":  {"price": 3,  "days": 1,  "credits": "∞", "display": "Lɪᴛᴇ",  "emoji_id": "5267500801240092311"},
    "PRIME": {"price": 9,  "days": 8,  "credits": "∞", "display": "Pʀɪᴍᴇ", "emoji_id": "6100170496077204999"},
    "ELITE": {"price": 15, "days": 16, "credits": "∞", "display": "Eʟɪᴛᴇ",  "emoji_id": "6149749150410871892"},
    "APEX":  {"price": 27, "days": 32, "credits": "∞", "display": "Aᴘᴇx",   "emoji_id": "5956148757899776734"},
}

HIT_LOG_CHAT_ID = -1003838614236

# ═══════════════════════════════════════════════════════════════════════════════
# PAYMENT TRACKING (In-Memory)
# ═══════════════════════════════════════════════════════════════════════════════

active_payments: Dict[str, Dict[str, Any]] = {}
user_sessions:   Dict[int, Dict[str, str]] = {}

_bot = None

def set_bot(bot):
    global _bot
    _bot = bot

def get_bot():
    return _bot

# ═══════════════════════════════════════════════════════════════════════════════
# BUTTON HELPER
# ═══════════════════════════════════════════════════════════════════════════════

def S(text: str, callback_data: str = None, url: str = None, style: str = "primary") -> dict:
    btn = {"text": text, "style": style}
    if callback_data:
        btn["callback_data"] = callback_data
    if url:
        btn["url"] = url
    return btn

def build_kb(rows: list) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=rows)

# ═══════════════════════════════════════════════════════════════════════════════
# HIT LOG
# ═══════════════════════════════════════════════════════════════════════════════

async def send_hit_log(user_id: int, plan_key: str):
    bot = get_bot()
    if not bot:
        return
    plan_info     = PLANS.get(plan_key, {})
    plan_display  = plan_info.get("display", plan_key)
    plan_emoji_id = plan_info.get("emoji_id", "5267500801240092311")
    plan_days     = plan_info.get("days", 0)
    plan_price    = plan_info.get("price", 0)
    day_str       = "Dᴀʏ" if plan_days == 1 else "Dᴀʏꜱ"

    try:
        user_link = db.get_user_link(user_id)
    except Exception:
        user_link = f'<a href="tg://user?id={user_id}">{user_id}</a>'

    text = (
        f'<b>Nᴇᴡ Pʟᴀɴ Pᴜʀᴄʜᴀꜱᴇᴅ <tg-emoji emoji-id="4958699241137505132">💥</tg-emoji></b>\n'
        f'<b>Uꜱᴇʀ ➛ {user_link}</b>\n'
        f'<b>Aᴄᴄᴇꜱꜱ ➛ {plan_display} <tg-emoji emoji-id="{plan_emoji_id}">⭐</tg-emoji></b>\n'
        f'<b>Sᴘᴀɴ ➛ [{plan_days} {day_str}]</b>\n'
        f'<b>Pʀɪᴄᴇ ➛ {plan_price}$</b>'
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[
        {"text": "𝑪𝑨𝑹𝑫 ✘ 𝑪𝑯𝑲", "url": "https://t.me/CARDXLEFT_BOT",
         "style": "primary", "icon_custom_emoji_id": "5935795874251674052"}
    ]])
    try:
        await bot.send_message(
            chat_id=HIT_LOG_CHAT_ID, text=text, parse_mode="HTML",
            reply_markup=keyboard, link_preview_options={"is_disabled": True},
        )
    except Exception as e:
        logging.error(f"Failed to send hit log: {e}")

# ═══════════════════════════════════════════════════════════════════════════════
# PAYMENT CREATION
# ═══════════════════════════════════════════════════════════════════════════════

def create_payment(user_id: int, plan: str, currency: str, network: str) -> Optional[Dict]:
    if plan not in PLANS:
        return None

    plan_info = PLANS[plan]
    url = f"{API_BASE}/payment/white-label"
    headers = {
        "merchant_api_key": API_KEY,
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0",
    }
    order_id = f"{user_id}_{plan}_{int(datetime.now().timestamp())}"
    payload = {
        "amount": plan_info["price"],
        "currency": "USD",
        "pay_currency": currency,
        "network": network,
        "lifetime": 1440,
        "fee_paid_by_payer": 0,
        "under_paid_coverage": 2,
        "to_currency": "USDT",
        "order_id": order_id,
        "description": f"{plan_info['display']} Pʟᴀɴ Aᴄᴛɪᴠᴀᴛɪᴏɴ - Uꜱᴇʀ {user_id}",
        "callback_url": CALLBACK_URL,
    }

    try:
        r = requests.post(url, data=json.dumps(payload), headers=headers, timeout=30)
        res = r.json()
        if res.get("status") == 200:
            d = res["data"]
            return {
                "track_id": d["track_id"],
                "address":  d["address"],
                "amount":   d["pay_amount"],
                "currency": d["pay_currency"],
                "network":  d["network"],
                "qr":       d["qr_code"],
                "expires":  d["expired_at"],
                "order_id": order_id,
            }
        logging.error(f"OxaPay API Error: {res}")
        return None
    except Exception as e:
        logging.error(f"Payment creation error: {e}")
        return None

# ═══════════════════════════════════════════════════════════════════════════════
# PAYMENT STATUS CHECK
# ═══════════════════════════════════════════════════════════════════════════════

def check_payment_status(track_id: str) -> Optional[str]:
    """
    Returns the raw status string from OxaPay (e.g. 'Paid', 'Waiting',
    'Confirming', 'Expired') or None on error.
    Logs the full response so you can verify the exact shape OxaPay returns.
    """
    url = f"{API_BASE}/payment/{track_id}"
    headers = {
        "merchant_api_key": API_KEY,
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0",
    }
    try:
        r = requests.get(url, headers=headers, timeout=15)
        res = r.json()
        logging.info(f"[OxaPay] track={track_id} HTTP={r.status_code} body={res}")

        # Shape: {"status": 200, "data": {"status": "Paid", ...}}
        data = res.get("data")
        if isinstance(data, dict):
            status = data.get("status")
            if isinstance(status, str) and status:
                if track_id in active_payments:
                    active_payments[track_id]["status"] = status
                return status

        # Fallback: some variants put status at root as a string
        root_status = res.get("status")
        if isinstance(root_status, str) and root_status:
            if track_id in active_payments:
                active_payments[track_id]["status"] = root_status
            return root_status

        logging.warning(f"[OxaPay] Could not extract status from response: {res}")
        return None
    except Exception as e:
        logging.error(f"[OxaPay] Status check error for {track_id}: {e}")
        return None

# ═══════════════════════════════════════════════════════════════════════════════
# PLAN ACTIVATION
# ═══════════════════════════════════════════════════════════════════════════════

def activate_plan(user_id: int, plan: str) -> bool:
    if plan not in PLANS:
        return False
    plan_info = PLANS[plan]
    try:
        db.ensure_user(user_id, "Unknown", "User")
        success = db.activate_subscription(
            user_id, plan, plan_info["days"], amount_paid=plan_info["price"]
        )
        if success:
            logging.info(f"✅ Activated {plan} for user {user_id}")
        else:
            logging.error(f"❌ activate_subscription returned False for user {user_id} plan {plan}")
        return bool(success)
    except Exception as e:
        logging.error(f"Plan activation error for {user_id}: {e}")
        return False

# ═══════════════════════════════════════════════════════════════════════════════
# TEXT FORMATTERS
# ═══════════════════════════════════════════════════════════════════════════════

def format_congrats_message(user_id: int, plan: str) -> str:
    plan_info = PLANS.get(plan, {})
    return (
        f"<b>Cᴏɴɢʀᴀᴛᴜʟᴀᴛɪᴏɴꜱ! 🎉 Yᴏᴜʀ ᴀᴄᴄᴇꜱꜱ ʜᴀꜱ ʙᴇᴇɴ ᴀᴄᴛɪᴠᴀᴛᴇᴅ.</b>\n"
        f"<b>Aᴄᴄᴇꜱꜱ ➛ {plan_info.get('display', plan)}</b>\n"
        f"<b>Dᴜʀᴀᴛɪᴏɴ ➛ {plan_info.get('days', 0)} Dᴀʏꜱ</b>\n"
        f"<b>Cʀᴇᴅɪᴛꜱ Aᴅᴅᴇᴅ ➛ ∞</b>\n"
        f"<b>Yᴏᴜʀ ᴘʟᴀɴ ʜᴀꜱ ʙᴇᴇɴ ᴀᴄᴛɪᴠᴀᴛᴇᴅ!</b>"
    )

def format_payment_caption(payment_data: Dict, plan: str) -> str:
    plan_info = PLANS.get(plan, {})
    try:
        expires_dt = datetime.fromisoformat(payment_data["expires"].replace("Z", "+00:00"))
        diff    = expires_dt - datetime.now(expires_dt.tzinfo)
        minutes = max(0, int(diff.total_seconds() / 60))
    except Exception:
        minutes = 30

    return (
        f"<b>Pʟᴀɴ ➛ {plan_info.get('display', plan)}</b>\n"
        f"<b>Pʀɪᴄᴇ ➛ ${plan_info.get('price', 0):.2f} Uꜱᴅ</b>\n"
        f"<b>Pᴀʏ ➛ {payment_data['amount']} {payment_data['currency']}</b>\n"
        f"<b>Nᴇᴛᴡᴏʀᴋ ➛ {payment_data['network']}</b>\n\n"
        f"<b>Dᴇᴘᴏꜱɪᴛ Aᴅᴅʀᴇꜱꜱ ➛</b>\n"
        f"<code>{payment_data['address']}</code>\n\n"
        f"<b>Exᴘɪʀᴇꜱ ɪɴ ➺ {minutes} Mɪɴᴜᴛᴇꜱ</b>\n"
        f"<b>Dᴇᴘᴏꜱɪᴛꜱ ᴛᴀᴋᴇ 3 ᴍɪɴꜱ ᴛᴏ ᴄᴏɴꜰɪʀᴍ ᴀꜰᴛᴇʀ ᴄᴏᴍᴘʟᴇᴛᴇᴅ</b>"
    )

# ═══════════════════════════════════════════════════════════════════════════════
# BACKGROUND PAYMENT MONITOR (auto-confirms without user clicking "Paid")
# ═══════════════════════════════════════════════════════════════════════════════

async def start_payment_monitor(
    track_id: str, chat_id: int, message_id: int, is_photo: bool, original_text: str
):
    if track_id not in active_payments:
        active_payments[track_id] = {}

    existing = active_payments[track_id].get("task")
    if existing and not existing.done():
        existing.cancel()

    active_payments[track_id].update({
        "chat_id":       chat_id,
        "message_id":    message_id,
        "is_photo":      is_photo,
        "original_text": original_text,
    })
    task = asyncio.create_task(_monitor_payment_loop(track_id))
    active_payments[track_id]["task"] = task


async def _monitor_payment_loop(track_id: str):
    max_checks  = 360   # 360 × 5 s = 30 minutes
    check_count = 0
    while check_count < max_checks:
        try:
            status = await asyncio.to_thread(check_payment_status, track_id)
            if status and status.lower() == "paid":
                logging.info(f"💰 Monitor confirmed payment: {track_id}")
                await _handle_payment_success(track_id)
                return
            if status and status.lower() == "expired":
                logging.info(f"⏰ Monitor: payment expired: {track_id}")
                await _handle_payment_expired(track_id)
                return
            await asyncio.sleep(5)
            check_count += 1
        except asyncio.CancelledError:
            return
        except Exception as e:
            logging.error(f"Monitor error for {track_id}: {e}")
            await asyncio.sleep(5)
            check_count += 1

    # Timed out
    await _handle_payment_expired(track_id)


async def _handle_payment_success(track_id: str):
    bot = get_bot()
    if not bot:
        return

    payment    = active_payments.get(track_id, {})
    user_id    = payment.get("user_id")
    plan       = payment.get("plan")
    chat_id    = payment.get("chat_id")
    message_id = payment.get("message_id")

    if not user_id or not plan or not chat_id or not message_id:
        logging.error(f"_handle_payment_success: incomplete data for {track_id}")
        return

    activated = await asyncio.to_thread(activate_plan, user_id, plan)
    if not activated:
        logging.error(f"Activation failed in monitor for user {user_id} plan {plan}")
        return

    plan_info    = PLANS.get(plan, {})
    success_text = (
        f"<b>✅ Tʀᴀɴꜱᴀᴄᴛɪᴏɴ Sᴜᴄᴄᴇꜱꜱ!</b>\n\n"
        f"<b>Pʟᴀɴ ➛ {plan_info.get('display', plan)}</b>\n"
        f"<b>Dᴜʀᴀᴛɪᴏɴ ➛ {plan_info.get('days', 0)} Dᴀʏꜱ</b>\n"
        f"<b>Cʀᴇᴅɪᴛꜱ Aᴅᴅᴇᴅ ➛ {plan_info.get('credits', '∞')}</b>\n\n"
        f"<b>Yᴏᴜʀ ᴘʟᴀɴ ʜᴀꜱ ʙᴇᴇɴ ᴀᴄᴛɪᴠᴀᴛᴇᴅ!</b>"
    )
    dm_text  = format_congrats_message(user_id, plan)
    dm_kb    = build_kb([[S("Sᴜᴘᴘᴏʀᴛ", url="https://t.me/FailureFr_07")]])

    await asyncio.gather(
        _safe_edit(bot, chat_id, message_id, success_text),
        _safe_send(bot, user_id, dm_text, dm_kb),
        send_hit_log(user_id, plan),
        return_exceptions=True,
    )
    _cleanup_payment(track_id, user_id)


async def _handle_payment_expired(track_id: str):
    bot = get_bot()
    if not bot:
        return

    payment    = active_payments.get(track_id, {})
    chat_id    = payment.get("chat_id")
    message_id = payment.get("message_id")
    user_id    = payment.get("user_id")

    if chat_id and message_id:
        expired_text = (
            "<b>⏰ Pᴀʏᴍᴇɴᴛ Exᴘɪʀᴇᴅ</b>\n\n"
            "<b>Tʜᴇ ᴘᴀʏᴍᴇɴᴛ ᴡɪɴᴅᴏᴡ ʜᴀꜱ ᴄʟᴏꜱᴇᴅ.</b>\n"
            "<b>Pʟᴇᴀꜱᴇ ꜱᴛᴀʀᴛ ᴀ ɴᴇᴡ ᴘᴀʏᴍᴇɴᴛ.</b>"
        )
        try:
            await bot.edit_message_text(
                chat_id=chat_id, message_id=message_id,
                text=expired_text, parse_mode="HTML",
            )
        except Exception as e:
            logging.error(f"Error editing expired message: {e}")

    _cleanup_payment(track_id, user_id)


# ═══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

async def _safe_edit(bot, chat_id, message_id, text, reply_markup=None):
    try:
        await bot.edit_message_text(
            chat_id=chat_id, message_id=message_id,
            text=text, parse_mode="HTML", reply_markup=reply_markup,
        )
    except Exception as e:
        logging.error(f"_safe_edit error: {e}")

async def _safe_send(bot, chat_id, text, reply_markup=None):
    try:
        await bot.send_message(
            chat_id=chat_id, text=text,
            parse_mode="HTML", reply_markup=reply_markup,
        )
    except Exception as e:
        logging.error(f"_safe_send error: {e}")

# ═══════════════════════════════════════════════════════════════════════════════
# SESSION & CLEANUP MANAGEMENT
# ═══════════════════════════════════════════════════════════════════════════════

def set_user_session(user_id: int, plan: str, currency: str = None):
    user_sessions[user_id] = {"plan": plan, "currency": currency}

def get_user_session(user_id: int) -> Optional[Dict]:
    return user_sessions.get(user_id)

def clear_user_session(user_id: int):
    user_sessions.pop(user_id, None)

def _cleanup_payment(track_id: str, user_id: int = None):
    payment = active_payments.pop(track_id, None)
    if payment:
        task = payment.get("task")
        if task and not task.done():
            task.cancel()
    if user_id:
        clear_user_session(user_id)

def cancel_user_active_payment(user_id: int):
    for track_id, payment in list(active_payments.items()):
        if payment.get("user_id") == user_id:
            task = payment.get("task")
            if task and not task.done():
                task.cancel()
            active_payments.pop(track_id, None)
    clear_user_session(user_id)

def register_payment(track_id: str, user_id: int, plan: str):
    active_payments[track_id] = {
        "user_id":    user_id,
        "plan":       plan,
        "created_at": datetime.now(),
        "status":     "Pending",
    }

# ═══════════════════════════════════════════════════════════════════════════════
# KEYBOARD BUILDERS
# ═══════════════════════════════════════════════════════════════════════════════

def get_plan_selection_keyboard():
    return build_kb([
        [S("Lɪᴛᴇ — $3",   callback_data="pay_plan_LITE")],
        [S("Pʀɪᴍᴇ — $9",  callback_data="pay_plan_PRIME")],
        [S("Eʟɪᴛᴇ — $15", callback_data="pay_plan_ELITE")],
        [S("Aᴘᴇx — $27",  callback_data="pay_plan_APEX")],
        [S("« Bᴀᴄᴋ", callback_data="menu_pricing", style="danger")],
    ])

def get_network_selection_keyboard(user_id: int):
    return build_kb([
        [S("Uꜱᴅᴛ (Bᴇᴘ20)", callback_data="pay_direct_BEP20"),
         S("Uꜱᴅᴛ (Tʀᴄ20)", callback_data="pay_direct_TRC20")],
        [S("Lɪᴛᴇᴄᴏɪɴ",      callback_data="pay_direct_LTC"),
         S("Bɪᴛᴄᴏɪɴ",       callback_data="pay_direct_BTC")],
        [S("Sᴏʟᴀɴᴀ",        callback_data="pay_direct_SOL"),
         S("Pᴏʟʏɢᴏɴ",       callback_data="pay_direct_POL")],
        [S("Tᴏɴ",            callback_data="pay_direct_TON")],
        [S("« Bᴀᴄᴋ", callback_data=f"pay_back_plans_{user_id}", style="danger")],
    ])

def get_paid_button_keyboard(track_id: str, user_id: int):
    return build_kb([
        [S("✅ Iᴠᴇ Pᴀɪᴅ", callback_data=f"pay_check_{track_id}")],
        [S("Sᴜᴘᴘᴏʀᴛ", url="https://t.me/FailureFr_07")],
        [S("« Bᴀᴄᴋ", callback_data=f"pay_back_plans_{user_id}", style="danger")],
    ])
