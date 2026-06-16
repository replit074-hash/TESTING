import asyncio
import logging
import os
import sys
from aiogram import Bot, Dispatcher, F, BaseMiddleware
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.filters import CommandStart
from fb import router as fb_router
from payments import (
    set_bot, get_bot, get_plan_selection_keyboard, get_network_selection_keyboard,
    get_paid_button_keyboard, create_payment, start_payment_monitor,
    register_payment, set_user_session, get_user_session,
    format_payment_caption, check_payment_status, activate_plan,
    send_hit_log, format_congrats_message, DIRECT_NETWORKS,
    PLANS, cancel_user_active_payment, active_payments, _cleanup_payment,
    build_kb, S,
)

import database
from broad import router as broad_router
from sub import router as admin_router
from Gates.b3 import router as b3_router
from Gates.sh import router as sh_router
from Gates.chk import router as chk_router
from Gates.rz import router as rz_router
from Gates.msh import router as msh_router
from Gates.mrz import router as mrz_router
from stats import router as stats_router
from Gates.sitechk import router as sitechk_router

# ═══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION & LOGGING
# ═══════════════════════════════════════════════════════════════════════════════

BOT_TOKEN = os.getenv("BOT_TOKEN", "8873449307:AAGhIFzl2EgJtI2BgIAwM_KAcMiIF47Vhag")

logging.basicConfig(level=logging.INFO, stream=sys.stdout)
log = logging.getLogger(__name__)

USER_ID_EMOJI_ID      = "5282843764451195532"
USERNAME_EMOJI_ID     = "5271604874419647061"
PLAN_LABEL_EMOJI_ID   = "5251203410396458957"
PLAN_STAR_EMOJI_ID    = "5267500801240092311"
MASS_GATES_EMOJI_ID   = "5801044672658805468"
CATEGORY_EMOJI_ID     = "6102731950148029376"
SINGLE_GATES_EMOJI_ID = "6100570056884752399"
HEALTH_EMOJI_ID       = "5244837092042750681"
CHANNEL_EMOJI_ID      = "5926783847453692661"
GROUP_EMOJI_ID        = "5884510167986343350"
BUY_EMOJI_ID          = "5935795874251674052"
BACK_EMOJI_ID         = "5875082500023258804"
PROCEED_EMOJI_ID      = "5877468380125990242"
# Using a valid existing ID for the Commands button to prevent crashes
COMMANDS_EMOJI_ID     = "5267500801240092311" 

bot = Bot(token=BOT_TOKEN)
dp  = Dispatcher()

# ═══════════════════════════════════════════════════════════════════════════════
# DATABASE & ROUTER INITIALIZATION
# ═══════════════════════════════════════════════════════════════════════════════

database.init_db()

dp.include_router(admin_router)
dp.include_router(b3_router)
dp.include_router(sh_router)
dp.include_router(chk_router)
dp.include_router(rz_router)
dp.include_router(msh_router)
dp.include_router(mrz_router)
dp.include_router(stats_router)
dp.include_router(sitechk_router)
dp.include_router(broad_router)
dp.include_router(fb_router) 
set_bot(bot)

# ═══════════════════════════════════════════════════════════════════════════════
# BAN MIDDLEWARE
# ═══════════════════════════════════════════════════════════════════════════════

class BanMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        user = event.from_user
        if user and database.is_banned(user.id):
            if isinstance(event, Message):
                await event.reply("<b>You are banned from using this bot.</b>", parse_mode="HTML")
            elif isinstance(event, CallbackQuery):
                await event.answer("You are banned from using this bot.", show_alert=True)
            return
        return await handler(event, data)

dp.message.middleware(BanMiddleware())
dp.callback_query.middleware(BanMiddleware())

# ═══════════════════════════════════════════════════════════════════════════════
# SAFE CALLBACK ANSWER  (never raises — mirrors old bot's _safe_answer)
# ═══════════════════════════════════════════════════════════════════════════════

async def _safe_answer(cb: CallbackQuery, text: str = "", **kw):
    try:
        await cb.answer(text, **kw)
    except Exception:
        pass

# ═══════════════════════════════════════════════════════════════════════════════
# KEYBOARDS
# ═══════════════════════════════════════════════════════════════════════════════

def main_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                {"text": "Channel", "url": "https://t.me/+v37hxupsIXdmZmEx",
                 "style": "primary", "icon_custom_emoji_id": CHANNEL_EMOJI_ID},
                {"text": "Group",   "url": "https://t.me/+bCNmQ2fzMK1kOTM0",
                 "style": "primary", "icon_custom_emoji_id": GROUP_EMOJI_ID},
            ],
            [
                {"text": "Buy Now", "callback_data": "buy_now",
                 "style": "primary", "icon_custom_emoji_id": BUY_EMOJI_ID},
            ],
            [
                {"text": "Commands", "callback_data": "show_commands",
                 "style": "primary", "icon_custom_emoji_id": COMMANDS_EMOJI_ID},
            ],
        ]
    )

def back_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[[
            {"text": "Back", "callback_data": "back_home",
             "style": "primary", "icon_custom_emoji_id": BACK_EMOJI_ID},
        ]]
    )

def buy_now_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [{"text": "Proceed", "callback_data": "proceed_to_payment",
              "style": "primary", "icon_custom_emoji_id": PROCEED_EMOJI_ID}],
            [{"text": "Back",    "callback_data": "back_home",
              "style": "primary", "icon_custom_emoji_id": BACK_EMOJI_ID}],
        ]
    )

# ═══════════════════════════════════════════════════════════════════════════════
# TEXT FORMATTERS
# ═══════════════════════════════════════════════════════════════════════════════

def build_user_info_text(user):
    username = f"@{user.username}" if user.username else "No Username"
    plan_key = database.get_user_plan_status(user.id)
    if plan_key == "No Plan":
        plan_text = "No Plan"
    else:
        plan_info    = PLANS.get(plan_key, {})
        plan_display = plan_info.get("display", plan_key)
        plan_emoji   = plan_info.get("emoji_id", PLAN_STAR_EMOJI_ID)
        plan_text    = f'{plan_display} <tg-emoji emoji-id="{plan_emoji}">⭐</tg-emoji>'

    return (
        f"<b>╭──〔 𝗨𝗦𝗘𝗥 𝗜𝗡𝗙𝗢 〕──╮</b>\n"
        f'<b>◈ User ID ➛ <code>{user.id}</code></b>\n'
        f'<b>◈ Username ➛ {username}</b>\n'
        f'<b>◈ Plan ➛ {plan_text}</b>\n'
        f'<b><tg-emoji emoji-id="{MASS_GATES_EMOJI_ID}">⚡</tg-emoji> Mass Gates ⤵︎</b>\n'
        f'<b>           ◈ Razorpay <tg-emoji emoji-id="{CATEGORY_EMOJI_ID}">📂</tg-emoji></b>\n'
        f'<b>           ◈ Shopify <tg-emoji emoji-id="{CATEGORY_EMOJI_ID}">📂</tg-emoji></b>\n'
        f'<b><tg-emoji emoji-id="{SINGLE_GATES_EMOJI_ID}">🔓</tg-emoji> Single Gates ➛ 4</b>\n'
        f'<b>\n</b>'
        f'<b><tg-emoji emoji-id="{HEALTH_EMOJI_ID}">📊</tg-emoji> Gates Health ➛ 100%</b>\n'
        f'<b>╰──────────╯</b>'
    )

def build_pricing_text():
    return (
        f'<b>Aᴄᴄᴇꜱꜱ ➛ Lɪᴛᴇ <tg-emoji emoji-id="5267500801240092311">⭐</tg-emoji></b>\n'
        f'<b>Sᴘᴀɴ ➛ [1 Dᴀʏ]</b>\n'
        f'<b>Pʀɪᴄᴇ ➛ 3$</b>\n'
        f'<b>━━━━━━━</b>\n'
        f'<b>Aᴄᴄᴇꜱꜱ ➛ Pʀɪᴍᴇ <tg-emoji emoji-id="6100170496077204999">💎</tg-emoji></b>\n'
        f'<b>Sᴘᴀɴ ➛ [8 Dᴀʏꜱ]</b>\n'
        f'<b>Pʀɪᴄᴇ ➛ 9$</b>\n'
        f'<b>━━━━━━━</b>\n'
        f'<b>Aᴄᴄᴇꜱꜱ ➛ Eʟɪᴛᴇ <tg-emoji emoji-id="6149749150410871892">⚡</tg-emoji></b>\n'
        f'<b>Sᴘᴀɴ ➛ [16 Dᴀʏꜱ]</b>\n'
        f'<b>Pʀɪᴄᴇ ➛ 15$</b>\n'
        f'<b>━━━━━━━</b>\n'
        f'<b>Aᴄᴄᴇꜱꜱ ➛ Aᴘᴇx <tg-emoji emoji-id="5956148757899776734">👑</tg-emoji></b>\n'
        f'<b>Sᴘᴀɴ ➛ [32 Dᴀʏꜱ]</b>\n'
        f'<b>Pʀɪᴄᴇ ➛ 27$</b>\n'
        f'<b>━━━━━━━</b>'
    )

def build_commands_text():
    return (
        f"<b>╭──〔 𝗖𝗢𝗠𝗠𝗔𝗡𝗗𝗦 〕──╮</b>\n"
        f'⚡ <b>Aᴠᴀɪʟᴀʙʟᴇ Cᴏᴍᴍᴀɴᴅs:</b>\n\n'  # Removed custom tg-emoji tag to fix DOCUMENT_INVALID error
        f'<b>◈</b> <code>/msh</code> ➛ <b>Mᴀss Sʜᴏᴘɪꜰʏ</b>\n'
        f'<b>◈</b> <code>/mrz</code> ➛ <b>Mᴀss RᴀzorPᴀʏ</b>\n'
        f'<b>◈</b> <code>/sh</code> ➛ <b>Sʜᴏᴘɪꜰʏ 0.5$</b>\n'
        f'<b>◈</b> <code>/rz</code> ➛ <b>Rᴀzorpay 1₹</b>\n'
        f'<b>◈</b> <code>/chk</code> ➛ <b>Sᴛʀɪᴘᴇ Aᴜᴛʜ</b>\n'
        f'<b>◈</b> <code>/b3</code> ➛ <b>B3 Aᴜᴛʜ</b>\n'
        f'<b>╰──────────╯</b>'
    )

# ═══════════════════════════════════════════════════════════════════════════════
# HOME & PRICING HANDLERS
# ═══════════════════════════════════════════════════════════════════════════════

@dp.message(CommandStart())
async def start_cmd(message: Message):
    database.ensure_user(
        message.from_user.id,
        message.from_user.username or "Unknown",
        message.from_user.first_name or "User",
    )
    text = build_user_info_text(message.from_user)
    await message.reply(text=text, parse_mode="HTML", reply_markup=main_keyboard())


@dp.callback_query(F.data == "buy_now")
async def buy_now(callback: CallbackQuery):
    text = build_pricing_text()
    await callback.message.edit_text(text=text, parse_mode="HTML", reply_markup=buy_now_keyboard())
    await _safe_answer(callback)


@dp.callback_query(F.data == "back_home")
async def back_home(callback: CallbackQuery):
    text = build_user_info_text(callback.from_user)
    await callback.message.edit_text(text=text, parse_mode="HTML", reply_markup=main_keyboard())
    await _safe_answer(callback)

# ═══════════════════════════════════════════════════════════════════════════════
# COMMANDS MENU HANDLERS
# ═══════════════════════════════════════════════════════════════════════════════

@dp.callback_query(F.data == "show_commands")
async def show_commands(callback: CallbackQuery):
    text = build_commands_text()
    await callback.message.edit_text(text=text, parse_mode="HTML", reply_markup=back_keyboard())
    await _safe_answer(callback)

# ═══════════════════════════════════════════════════════════════════════════════
# PAYMENT FLOW HANDLERS
# ═══════════════════════════════════════════════════════════════════════════════

@dp.callback_query(F.data == "proceed_to_payment")
async def proceed_to_payment(callback: CallbackQuery):
    text = "<b>Sᴇʟᴇᴄᴛ ᴀ Pʟᴀɴ ᴛᴏ Pᴜʀᴄʜᴀꜱᴇ:</b>"
    await callback.message.edit_text(text=text, parse_mode="HTML",
                                     reply_markup=get_plan_selection_keyboard())
    await _safe_answer(callback)


@dp.callback_query(F.data == "menu_pricing")
async def menu_pricing(callback: CallbackQuery):
    await buy_now(callback)


@dp.callback_query(F.data.startswith("pay_plan_"))
async def pay_plan(callback: CallbackQuery):
    plan    = callback.data.split("pay_plan_")[1]
    user_id = callback.from_user.id
    set_user_session(user_id, plan)
    plan_display = PLANS.get(plan, {}).get("display", plan)
    text = f"<b>Sᴇʟᴇᴄᴛ Pᴀʏᴍᴇɴᴛ Nᴇᴛᴡᴏʀᴋ ꜰᴏʀ {plan_display}:</b>"
    await callback.message.edit_text(text=text, parse_mode="HTML",
                                     reply_markup=get_network_selection_keyboard(user_id))
    await _safe_answer(callback)


@dp.callback_query(F.data.startswith("pay_back_plans_"))
async def pay_back_plans(callback: CallbackQuery):
    await proceed_to_payment(callback)


@dp.callback_query(F.data.startswith("pay_direct_"))
async def pay_direct(callback: CallbackQuery):
    network_key = callback.data.split("pay_direct_")[1]
    user_id     = callback.from_user.id
    session     = get_user_session(user_id)

    if not session or not session.get("plan"):
        await _safe_answer(callback, "Sᴇssɪᴏɴ exᴘɪʀᴇᴅ. Pʟᴇᴀꜱᴇ ꜱᴛᴀʀᴛ ᴀɢᴀɪɴ.", show_alert=True)
        return

    plan         = session["plan"]
    network_info = DIRECT_NETWORKS.get(network_key)

    if not network_info:
        await _safe_answer(callback, "Iɴᴠᴀʟɪᴅ ɴᴇᴛᴡᴏʀᴋ.", show_alert=True)
        return

    cancel_user_active_payment(user_id)
    await _safe_answer(callback)

    payment_data = await asyncio.to_thread(
        create_payment, user_id, plan, network_info["currency"], network_info["network"]
    )

    if not payment_data:
        await callback.message.edit_text(
            "<b>❌ Fᴀɪʟᴇᴅ ᴛᴏ ᴄʀᴇᴀᴛᴇ ᴘᴀʏᴍᴇɴᴛ. Pʟᴇᴀꜱᴇ ᴛʀʏ ᴀɢᴀɪɴ ʟᴀᴛᴇʀ.</b>",
            parse_mode="HTML",
            reply_markup=get_plan_selection_keyboard(),
        )
        return

    track_id = payment_data["track_id"]
    register_payment(track_id, user_id, plan)
    set_user_session(user_id, plan, network_key)

    caption = format_payment_caption(payment_data, plan)
    kb      = get_paid_button_keyboard(track_id, user_id)

    # Send as NEW message (like old bot) so message_id is fresh and reliable
    try:
        sent_msg = await callback.message.answer(
            text=caption, parse_mode="HTML", reply_markup=kb,
        )
    except Exception as e:
        log.error(f"pay_direct send error: {e}")
        return

    # Delete the previous menu message cleanly
    try:
        await callback.message.delete()
    except Exception:
        pass

    # Store exact chat_id + message_id from the NEW message — then start monitor
    if sent_msg:
        active_payments[track_id].update({
            "chat_id":       sent_msg.chat.id,
            "message_id":    sent_msg.message_id,
            "original_text": caption,
        })
        await start_payment_monitor(
            track_id,
            sent_msg.chat.id,
            sent_msg.message_id,
            False,
            caption,
        )


@dp.callback_query(F.data.startswith("pay_check_"))
async def pay_check(callback: CallbackQuery):
    """
    Triggered when the user clicks '✅ Iᴠᴇ Pᴀɪᴅ'.

    Logic ported from the working old bot:
    • Check ownership of the payment first.
    • Call check_payment_status() directly via asyncio.to_thread.
    • Compare case-insensitively (OxaPay may return 'Paid' or 'paid').
    • Call activate_plan() directly in the handler.
    • Use asyncio.gather() so the callback answer, message edit, and DM
      all fire simultaneously — no second callback.answer() call.
    """
    track_id = callback.data.split("pay_check_")[1]
    user_id  = callback.from_user.id

    payment = active_payments.get(track_id)
    if not payment or payment.get("user_id") != user_id:
        await _safe_answer(callback, "❌ Pᴀʏᴍᴇɴᴛ ɴᴏᴛ ꜰᴏᴜɴᴅ ᴏʀ ɴᴏ ᴘᴇʀᴍɪꜱꜱɪᴏɴ.", show_alert=True)
        return

    bot_i = get_bot()
    if not bot_i:
        await _safe_answer(callback, "❌ Bᴏᴛ ᴇʀʀᴏʀ. Tʀʏ ᴀɢᴀɪɴ.", show_alert=True)
        return

    try:
        # ── Ask OxaPay for the current status ─────────────────────────────
        status = await asyncio.to_thread(check_payment_status, track_id)

        # ── PAID ──────────────────────────────────────────────────────────
        if status and status.lower() == "paid":
            plan     = payment["plan"]
            chat_id  = payment.get("chat_id")
            msg_id   = payment.get("message_id")
            plan_info = PLANS.get(plan, {})

            activated = await asyncio.to_thread(activate_plan, user_id, plan)

            if not activated:
                await _safe_answer(
                    callback,
                    "⚠️ Pᴀʏᴍᴇɴᴛ ʀᴇᴄᴇɪᴠᴇᴅ ʙᴜᴛ ᴀᴄᴛɪᴠᴀᴛɪᴏɴ ꜰᴀɪʟᴇᴅ. Cᴏɴᴛᴀᴄᴛ ꜱᴜᴘᴘᴏʀᴛ.",
                    show_alert=True,
                )
                return

            success_text = (
                f"<b>✅ Tʀᴀɴꜱᴀᴄᴛɪᴏɴ Sᴜᴄᴄᴇꜱꜱ!</b>\n\n"
                f"<b>Pʟᴀɴ ➺ {plan_info.get('display', plan)}</b>\n"
                f"<b>Dᴜʀᴀᴛɪᴏɴ ➺ {plan_info.get('days', 0)} Dᴀʏꜱ</b>\n"
                f"<b>Cʀᴇᴅɪᴛꜱ Aᴅᴅᴇᴅ ➺ {plan_info.get('credits', '∞')}</b>\n\n"
                f"<b>Yᴏᴜʀ Pʟᴀɴ ʜᴀꜱ ʙᴇᴇɴ Aᴄᴛɪᴠᴀᴛᴇᴅ!</b>"
            )
            dm_text = format_congrats_message(user_id, plan)
            dm_kb   = build_kb([[S("Sᴜᴘᴘᴏʀᴛ", url="https://t.me/FailureFr_07")]])

            # Fire answer + edit + DM + hit log all at once
            tasks = [
                _safe_answer(callback, "✅ Pᴀʏᴍᴇɴᴛ Cᴏɴꜰɪʀᴍᴇᴅ! Pʟᴀɴ ᴀᴄᴛɪᴠᴀᴛᴇᴅ.", show_alert=True),
                bot_i.send_message(chat_id=user_id, text=dm_text,
                                   parse_mode="HTML", reply_markup=dm_kb),
                send_hit_log(user_id, plan),
            ]
            if chat_id and msg_id:
                tasks.append(
                    bot_i.edit_message_text(
                        chat_id=chat_id, message_id=msg_id,
                        text=success_text, parse_mode="HTML",
                    )
                )
            await asyncio.gather(*tasks, return_exceptions=True)
            _cleanup_payment(track_id, user_id)

        # ── EXPIRED ───────────────────────────────────────────────────────
        elif status and status.lower() == "expired":
            chat_id = payment.get("chat_id")
            msg_id  = payment.get("message_id")
            expired_text = (
                "<b>⏰ Pᴀʏᴍᴇɴᴛ Exᴘɪʀᴇᴅ</b>\n\n"
                "<b>Tʜᴇ ᴘᴀʏᴍᴇɴᴛ ᴡɪɴᴅᴏᴡ ʜᴀꜱ ᴄʟᴏꜱᴇᴅ.</b>\n"
                "<b>Pʟᴇᴀꜱᴇ ꜱᴛᴀʀᴛ ᴀ ɴᴇᴡ ᴘᴀʏᴍᴇɴᴛ.</b>"
            )
            tasks = [
                _safe_answer(callback, "⏰ Pᴀʏᴍᴇɴᴛ ʜᴀꜱ exᴘɪʀᴇᴅ.", show_alert=True),
            ]
            if chat_id and msg_id:
                tasks.append(
                    bot_i.edit_message_text(
                        chat_id=chat_id, message_id=msg_id,
                        text=expired_text, parse_mode="HTML",
                    )
                )
            await asyncio.gather(*tasks, return_exceptions=True)
            _cleanup_payment(track_id, user_id)

        # ── STILL PENDING ─────────────────────────────────────────────────
        else:
            # Append a note to the payment message so user knows we checked
            cur_text = payment.get("original_text", "")
            await _safe_answer(
                callback,
                "⏳ Pᴀʏᴍᴇɴᴛ ɴᴏᴛ ᴅᴇᴛᴇᴄᴛᴇᴅ ʏᴇᴛ.\nEɴꜱᴜʀᴇ ᴇxᴀᴄᴛ ᴀᴍᴏᴜɴᴛ ɪꜱ ꜱᴇɴᴛ.",
                show_alert=True,
            )
            # Only append the notice once
            if "ɴᴏᴛ ᴅᴇᴛᴇᴄᴛᴇᴅ" not in cur_text:
                pending_text = (
                    f"{cur_text}\n\n"
                    f"<b>⏳ Pᴀʏᴍᴇɴᴛ ɴᴏᴛ ᴅᴇᴛᴇᴄᴛᴇᴅ ʏᴇᴛ.</b>\n"
                    f"<b>Eɴꜱᴜʀᴇ ᴇxᴀᴄᴛ ᴀᴍᴏᴜɴᴛ ɪꜱ ꜱᴇɴᴛ. Cʟɪᴄᴋ ᴛʜᴇ ʙᴜᴛᴛᴏɴ ᴀɢᴀɪɴ ᴛᴏ ʀᴇᴄʜᴇᴄᴋ.</b>"
                )
                chat_id = payment.get("chat_id")
                msg_id  = payment.get("message_id")
                if chat_id and msg_id:
                    try:
                        await bot_i.edit_message_text(
                            chat_id=chat_id, message_id=msg_id,
                            text=pending_text, parse_mode="HTML",
                            reply_markup=get_paid_button_keyboard(track_id, user_id),
                        )
                        payment["original_text"] = pending_text
                    except Exception as e:
                        if "not modified" not in str(e).lower():
                            log.error(f"pending edit error: {e}")

    except Exception as e:
        log.error(f"pay_check error: {e}")
        await _safe_answer(callback, "⚠️ Nᴇᴛᴡᴏʀᴋ ᴇʀʀᴏʀ. Tʀʏ ᴀɢᴀɪɴ.", show_alert=True)

# ═══════════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════════

async def main():
    log.info("Bot Started...")
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
