import logging
from aiogram import Router, F
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command

import database

router = Router()

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# EMOJI IDs
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

USERS_EMOJI_ID   = "5282843764451195532"
GATE_EMOJI_ID    = "5801044672658805468"
CHECKED_EMOJI_ID = "5447453226498552490"
CHARGED_EMOJI_ID = "5436143465211640305"
LIVE_EMOJI_ID    = "4958610528588008305"
DEAD_EMOJI_ID    = "4956612582816351459"
RZP_EMOJI_ID     = "5800688138833629633"
BUY_EMOJI_ID     = "5935795874251674052"
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# HELPER: Buy Now Keyboard
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
# /stats — global bot statistics (RESTRICTED)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@router.message(Command("stats"))
async def stats_command(message: Message):
    user_id = message.from_user.id

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # CHECK PLAN / PREMIUM STATUS
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    if not database.is_premium_active(user_id):
        await message.reply(
            "<b>❌ Access Denied.</b>\n"
            "<b>You must have an active plan to view global stats.</b>\n"
            "<b>Please purchase a plan to continue.</b>",
            parse_mode="HTML",
            reply_markup=buy_now_keyboard()
        )
        return

    import asyncio
    try:
        msh_stats = await asyncio.to_thread(database.get_global_stats)
        mrz_stats = await asyncio.to_thread(database.get_mrz_global_stats)
    except Exception as e:
        logging.error(f"[STATS] get_global_stats error: {e}")
        await message.reply("❌ <b>Failed to fetch stats.</b>", parse_mode="HTML")
        return

    total_users = msh_stats.get("total_users", 0)

    text = (
        f'<b><a href="https://t.me/FailureFr_07">[₪]</a> Gʟᴏʙᴀʟ Sᴛᴀᴛs</b>\n'
        f'<b>━━━━━━━━━━━━━━</b>\n'
        f'<b><tg-emoji emoji-id="{GATE_EMOJI_ID}">🛒</tg-emoji> Sʜᴏᴘɪꜰʏ | Mass</b>\n'
        f'<b><tg-emoji emoji-id="{CHECKED_EMOJI_ID}">🔍</tg-emoji> Cʜᴇᴄᴋᴇᴅ ➛ <code>{msh_stats.get("checked", 0)}</code></b>\n'
        f'<b><tg-emoji emoji-id="{CHARGED_EMOJI_ID}">💎</tg-emoji> Cʜᴀʀɢᴇᴅ ➛ <code>{msh_stats.get("charged", 0)}</code></b>\n'
        f'<b><tg-emoji emoji-id="{LIVE_EMOJI_ID}">✅</tg-emoji> Lɪᴠᴇ ➛ <code>{msh_stats.get("live", 0)}</code></b>\n'
        f'<b><tg-emoji emoji-id="{DEAD_EMOJI_ID}">❌</tg-emoji> Dᴇᴀᴅ ➛ <code>{msh_stats.get("dead", 0)}</code></b>\n'
        f'<b>━━━━━━━━━━━━━━</b>\n'
        f'<b><tg-emoji emoji-id="{RZP_EMOJI_ID}">💳</tg-emoji> Rᴀᴢᴏʀᴘᴀʏ | 1₹</b>\n'
        f'<b><tg-emoji emoji-id="{CHECKED_EMOJI_ID}">🔍</tg-emoji> Cʜᴇᴄᴋᴇᴅ ➛ <code>{mrz_stats.get("checked", 0)}</code></b>\n'
        f'<b><tg-emoji emoji-id="{CHARGED_EMOJI_ID}">💎</tg-emoji> Cʜᴀʀɢᴇᴅ ➛ <code>{mrz_stats.get("charged", 0)}</code></b>\n'
        f'<b><tg-emoji emoji-id="{LIVE_EMOJI_ID}">✅</tg-emoji> Lɪᴠᴇ ➛ <code>{mrz_stats.get("live", 0)}</code></b>\n'
        f'<b><tg-emoji emoji-id="{DEAD_EMOJI_ID}">❌</tg-emoji> Dᴇᴀᴅ ➛ <code>{mrz_stats.get("dead", 0)}</code></b>\n'
        f'<b>━━━━━━━━━━━━━━</b>'
    )

    await message.reply(text, parse_mode="HTML", disable_web_page_preview=True)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# /me — personal user statistics (RESTRICTED)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@router.message(Command("me"))
async def me_command(message: Message):
    import asyncio
    user    = message.from_user
    user_id = user.id

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # CHECK PLAN / PREMIUM STATUS
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    if not database.is_premium_active(user_id):
        await message.reply(
            "<b>❌ Access Denied.</b>\n"
            "<b>You must have an active plan to view your stats.</b>\n"
            "<b>Please purchase a plan to continue.</b>",
            parse_mode="HTML",
            reply_markup=buy_now_keyboard()
        )
        return

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # FETCH STATS
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    try:
        database.ensure_user(user_id, user.username, user.first_name)
        msh_stats = await asyncio.to_thread(database.get_user_stats,     user_id)
        mrz_stats = await asyncio.to_thread(database.get_mrz_user_stats, user_id)
    except Exception as e:
        logging.error(f"[STATS] get_user_stats error: {e}")
        await message.reply("❌ <b>Failed to fetch your stats.</b>", parse_mode="HTML")
        return

    name = user.first_name or "User"
    if user.username:
        user_link = f'<a href="https://t.me/{user.username}">{name}</a>'
    else:
        user_link = f'<a href="tg://user?id={user_id}">{name}</a>'

    text = (
        f'<b><a href="https://t.me/FailureFr_07">[₪]</a> Mʏ Sᴛᴀᴛs ➛ {user_link}</b>\n'
        f'<b>━━━━━━━━━━━━━━</b>\n'
        f'<b><tg-emoji emoji-id="{GATE_EMOJI_ID}">🛒</tg-emoji> Sʜᴏᴘɪꜰʏ | Mass</b>\n'
        f'<b><tg-emoji emoji-id="{CHECKED_EMOJI_ID}">🔍</tg-emoji> Cʜᴇᴄᴋᴇᴅ ➛ <code>{msh_stats.get("checked", 0)}</code></b>\n'
        f'<b><tg-emoji emoji-id="{CHARGED_EMOJI_ID}">💎</tg-emoji> Cʜᴀʀɢᴇᴅ ➛ <code>{msh_stats.get("charged", 0)}</code></b>\n'
        f'<b><tg-emoji emoji-id="{LIVE_EMOJI_ID}">✅</tg-emoji> Lɪᴠᴇ ➛ <code>{msh_stats.get("live", 0)}</code></b>\n'
        f'<b><tg-emoji emoji-id="{DEAD_EMOJI_ID}">❌</tg-emoji> Dᴇᴀᴅ ➛ <code>{msh_stats.get("dead", 0)}</code></b>\n'
        f'<b>━━━━━━━━━━━━━━</b>\n'
        f'<b><tg-emoji emoji-id="{RZP_EMOJI_ID}">💳</tg-emoji> Rᴀᴢᴏʀᴘᴀʏ | 1₹</b>\n'
        f'<b><tg-emoji emoji-id="{CHECKED_EMOJI_ID}">🔍</tg-emoji> Cʜᴇᴄᴋᴇᴅ ➛ <code>{mrz_stats.get("checked", 0)}</code></b>\n'
        f'<b><tg-emoji emoji-id="{CHARGED_EMOJI_ID}">💎</tg-emoji> Cʜᴀʀɢᴇᴅ ➛ <code>{mrz_stats.get("charged", 0)}</code></b>\n'
        f'<b><tg-emoji emoji-id="{LIVE_EMOJI_ID}">✅</tg-emoji> Lɪᴠᴇ ➛ <code>{mrz_stats.get("live", 0)}</code></b>\n'
        f'<b><tg-emoji emoji-id="{DEAD_EMOJI_ID}">❌</tg-emoji> Dᴇᴀᴅ ➛ <code>{mrz_stats.get("dead", 0)}</code></b>\n'
        f'<b>━━━━━━━━━━━━━━</b>'
    )

    await message.reply(text, parse_mode="HTML", disable_web_page_preview=True)
