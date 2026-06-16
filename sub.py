import logging
from datetime import datetime, timedelta
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from payments import PLANS, format_congrats_message
import database

router = Router()

# ⚠️ PUT YOUR TELEGRAM USER ID HERE SO ONLY YOU CAN USE ADMIN COMMANDS
ADMIN_IDS = [8760363324] 
HIT_LOG_CHAT_ID = -1003838614236

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CUSTOM EMOJI IDs
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Used in /info and other displays
USERS_EMOJI_ID   = "5282843764451195532"
PLAN_STAR_ID    = "5267500801240092311" # Star used for plans
LIVE_EMOJI_ID   = "4958610528588008305" # Diamond
USER_EMOJI_ID   = "5956561749070057536"
PRO_EMOJI_ID    = "6298678524379137990"
BAN_EMOJI_ID    = "5304357779199061662"
BUY_EMOJI_ID    = "5935795874251674052"
# ═══════════════════════════════════════════════════════════════════════════════
# HELPER: Buy Now Keyboard
# ═══════════════════════════════════════════════════════════════════════════════

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

# ═══════════════════════════════════════════════════════════════════════════════
# HIT LOG HELPER
# ═══════════════════════════════════════════════════════════════════════════════

async def send_hit_log(bot, user_id: int, plan_key: str):
    """Sends a stylish hit log to the specified Telegram group."""
    plan_info = PLANS.get(plan_key, {})
    plan_display = plan_info.get("display", plan_key)
    plan_emoji_id = plan_info.get("emoji_id", PLAN_STAR_ID)
    plan_days = plan_info.get("days", 0)
    plan_price = plan_info.get("price", 0)
    day_str = "Dᴀʏ" if plan_days == 1 else "Dᴀʏꜱ"
    
    user_link = database.get_user_link(user_id)
    
    text = (
        f'<b>Nᴇᴡ Pʟᴀɴ Pᴜʀᴄʜᴀꜱᴇᴅ <tg-emoji emoji-id="4958699241137505132">💥</tg-emoji></b>\n'
        f'<b>Uꜱᴇʀ ➛ {user_link}</b>\n'
        f'<b>Aᴄᴄᴇꜱꜱ ➛ {plan_display} <tg-emoji emoji-id="{plan_emoji_id}">⭐</tg-emoji></b>\n'
        f'<b>Sᴘᴀɴ ➛ [{plan_days} {day_str}]</b>\n'
        f'<b>Pʀɪᴄᴇ ➛ {plan_price}$</b>'
    )
    
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[
            {
                "text": "𝑪𝑨𝑹𝑫 ✘ 𝑪𝑯𝑲",
                "url": "https://t.me/CARDXLEFT_BOT",
                "style": "primary",
                "icon_custom_emoji_id": "5935795874251674052"
            }
        ]]
    )

    try:
        await bot.send_message(
            chat_id=HIT_LOG_CHAT_ID,
            text=text,
            parse_mode="HTML",
            reply_markup=keyboard,
            link_preview_options={"is_disabled": True}
        )
    except Exception as e:
        logging.error(f"Failed to send hit log: {e}")


# ═══════════════════════════════════════════════════════════════════════════════
# ADMIN COMMANDS
# ═══════════════════════════════════════════════════════════════════════════════

@router.message(Command("sub"))
async def sub_command(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    
    args = message.text.split()
    if len(args) != 3:
        await message.reply(
            "<b>Usage:</b> <code>/sub {plan} {user_id}</code>\n\n<b>Plans:</b> LITE, PRIME, ELITE, APEX", 
            parse_mode="HTML", 
            link_preview_options={"is_disabled": True}
        )
        return
    
    plan_key = args[1].upper()
    try:
        user_id = int(args[2])
    except ValueError:
        await message.reply(
            "<b>Error:</b> User ID must be a number.", 
            parse_mode="HTML", 
            link_preview_options={"is_disabled": True}
        )
        return

    if plan_key not in PLANS:
        await message.reply(
            "<b>Error:</b> Invalid plan. Use LITE, PRIME, ELITE, or APEX.", 
            parse_mode="HTML", 
            link_preview_options={"is_disabled": True}
        )
        return

    plan_info = PLANS[plan_key]
    database.ensure_user(user_id, "Unknown", "User")
    success = database.activate_subscription(user_id, plan_key, plan_info["days"], amount_paid=0)

    if success:
        await message.reply(
            f"✅ <b>Successfully activated {plan_info['display']} for user <code>{user_id}</code></b>", 
            parse_mode="HTML", 
            link_preview_options={"is_disabled": True}
        )
        
        # Send Hit Log
        await send_hit_log(message.bot, user_id, plan_key)
        
        # Send Congratulations DM to User
        try:
            dm_text = format_congrats_message(user_id, plan_key)
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Sᴜᴘᴘᴏʀᴛ", url="https://t.me/FailureFr_07")]
            ])
            
            await message.bot.send_message(
                chat_id=user_id,
                text=dm_text,
                parse_mode="HTML",
                reply_markup=keyboard,
                link_preview_options={"is_disabled": True}
            )
        except Exception as e:
            logging.error(f"Could not send DM to user {user_id} via /sub: {e}")
    else:
        await message.reply(
            f"❌ <b>Failed to activate plan for user <code>{user_id}</code></b>", 
            parse_mode="HTML", 
            link_preview_options={"is_disabled": True}
        )


@router.message(Command("rsub"))
async def rsub_command(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    
    args = message.text.split()
    if len(args) != 2:
        await message.reply(
            "<b>Usage:</b> <code>/rsub {user_id}</code>", 
            parse_mode="HTML", 
            link_preview_options={"is_disabled": True}
        )
        return
    
    try:
        user_id = int(args[1])
    except ValueError:
        await message.reply(
            "<b>Error:</b> User ID must be a number.", 
            parse_mode="HTML", 
            link_preview_options={"is_disabled": True}
        )
        return

    if database.revoke_subscription(user_id):
        await message.reply(
            f"⛔ <b>Subscription revoked for user <code>{user_id}</code></b>", 
            parse_mode="HTML", 
            link_preview_options={"is_disabled": True}
        )
    else:
        await message.reply(
            f"❌ <b>Failed to revoke subscription for user <code>{user_id}</code> (Maybe no active plan?).</b>", 
            parse_mode="HTML", 
            link_preview_options={"is_disabled": True}
        )


@router.message(Command("ban"))
async def ban_command(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    
    args = message.text.split()
    if len(args) != 2:
        await message.reply(
            "<b>Usage:</b> <code>/ban {user_id}</code>", 
            parse_mode="HTML", 
            link_preview_options={"is_disabled": True}
        )
        return
    
    try:
        user_id = int(args[1])
    except ValueError:
        await message.reply(
            "<b>Error:</b> User ID must be a number.", 
            parse_mode="HTML", 
            link_preview_options={"is_disabled": True}
        )
        return

    if database.ban_user(user_id):
        await message.reply(
            f"🚫 <b>User <code>{user_id}</code> has been banned.</b>", 
            parse_mode="HTML", 
            link_preview_options={"is_disabled": True}
        )
    else:
        await message.reply(
            f"❌ <b>Failed to ban user <code>{user_id}</code> (Maybe they don't exist?).</b>", 
            parse_mode="HTML", 
            link_preview_options={"is_disabled": True}
        )


@router.message(Command("unban"))
async def unban_command(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    
    args = message.text.split()
    if len(args) != 2:
        await message.reply(
            "<b>Usage:</b> <code>/unban {user_id}</code>", 
            parse_mode="HTML", 
            link_preview_options={"is_disabled": True}
        )
        return
    
    try:
        user_id = int(args[1])
    except ValueError:
        await message.reply(
            "<b>Error:</b> User ID must be a number.", 
            parse_mode="HTML", 
            link_preview_options={"is_disabled": True}
        )
        return

    if database.unban_user(user_id):
        await message.reply(
            f"✅ <b>User <code>{user_id}</code> has been unbanned.</b>", 
            parse_mode="HTML", 
            link_preview_options={"is_disabled": True}
        )
    else:
        await message.reply(
            f"❌ <b>Failed to unban user <code>{user_id}</code>.</b>", 
            parse_mode="HTML", 
            link_preview_options={"is_disabled": True}
        )


@router.message(Command("code"))
async def code_command(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    
    args = message.text.split()
    if len(args) != 3:
        await message.reply(
            "<b>Usage:</b> <code>/code {plan} {number_of_codes}</code>\n\n<b>Plans:</b> LITE, PRIME, ELITE, APEX", 
            parse_mode="HTML", 
            link_preview_options={"is_disabled": True}
        )
        return
    
    plan_key = args[1].upper()
    try:
        count = int(args[2])
    except ValueError:
        await message.reply(
            "<b>Error:</b> Number of codes must be a number.", 
            parse_mode="HTML", 
            link_preview_options={"is_disabled": True}
        )
        return

    if plan_key not in PLANS:
        await message.reply(
            "<b>Error:</b> Invalid plan. Use LITE, PRIME, ELITE, or APEX.", 
            parse_mode="HTML", 
            link_preview_options={"is_disabled": True}
        )
        return

    codes = database.create_redeem_codes(plan_key, count)
    plan_info = PLANS[plan_key]
    
    codes_text = "\n".join([f"<code>{c}</code>" for c in codes])
    
    await message.reply(
        f"🎟 <b>Generated {count} codes for {plan_info['display']}:</b>\n\n"
        f"{codes_text}",
        parse_mode="HTML",
        link_preview_options={"is_disabled": True}
    )


# ═══════════════════════════════════════════════════════════════════════════════
# USER COMMANDS
# ═══════════════════════════════════════════════════════════════════════════════

@router.message(Command("claim"))
async def claim_command(message: Message):
    # This command is FREE for users to redeem codes
    user_id = message.from_user.id
    
    if database.is_banned(user_id):
        await message.reply(
            "<b>You are banned from using this bot.</b>", 
            parse_mode="HTML", 
            link_preview_options={"is_disabled": True}
        )
        return

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # CHECK: Active Subscription
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # Prevent users from claiming codes if they already have an active plan
    if database.is_premium_active(user_id):
        await message.reply(
            "<b>⚠️ You already have an active subscription.</b>\n"
            "<b>Please wait until your current plan expires before claiming a new code.</b>",
            parse_mode="HTML",
            link_preview_options={"is_disabled": True}
        )
        return

    args = message.text.split()
    if len(args) != 2:
        await message.reply(
            "<b>Usage:</b> <code>/claim {code}</code>", 
            parse_mode="HTML", 
            link_preview_options={"is_disabled": True}
        )
        return
    
    code = args[1].upper()
    result_plan = database.claim_redeem_code(user_id, code)
    
    if result_plan == "invalid":
        await message.reply(
            "<b>Invalid code. Please check and try again.</b>", 
            parse_mode="HTML", 
            link_preview_options={"is_disabled": True}
        )
    elif result_plan == "already_used":
        await message.reply(
            "<b>This code has already been claimed.</b>", 
            parse_mode="HTML", 
            link_preview_options={"is_disabled": True}
        )
    else:
        plan_info = PLANS.get(result_plan, {})
        success = database.activate_subscription(user_id, result_plan, plan_info.get("days", 0), amount_paid=0)
        
        if success:
            # Send Congrats Message to User
            text = format_congrats_message(user_id, result_plan)
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Sᴜᴘᴘᴏʀᴛ", url="https://t.me/FailureFr_07")]
            ])
            
            await message.reply(
                text, 
                parse_mode="HTML", 
                reply_markup=keyboard, 
                link_preview_options={"is_disabled": True}
            )
            
            # Send Hit Log to Group
            await send_hit_log(message.bot, user_id, result_plan)
        else:
            await message.reply(
                "<b>Failed to activate plan. Contact support.</b>", 
                parse_mode="HTML", 
                link_preview_options={"is_disabled": True}
            )

@router.message(Command("info"))
async def info_command(message: Message):
    user_id = message.from_user.id
    
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # RESTRICTION: Premium Only
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    if not database.is_premium_active(user_id):
        await message.reply(
            "<b>❌ Access Denied.</b>\n"
            "<b>You must have an active plan to view your profile info.</b>\n"
            "<b>Please purchase a plan to continue.</b>",
            parse_mode="HTML",
            reply_markup=buy_now_keyboard()
        )
        return

    # Ensure user exists in DB
    database.ensure_user(user_id, message.from_user.username or "Unknown", message.from_user.first_name or "User")
    
    user_data = database.get_full_user_info(user_id)
    
    if not user_data:
        await message.reply("❌ <b>Error fetching user data.</b>", parse_mode="HTML")
        return

    # Extract data
    u_id = user_data.get('user_id')
    u_name = user_data.get('first_name', 'User')
    u_username = user_data.get('username')
    u_joined = user_data.get('joined_at')
    is_banned = user_data.get('is_banned', False)
    
    # Subscription Logic
    is_premium = user_data.get('is_premium', False)
    plan_key = user_data.get('current_plan')
    expiry_raw = user_data.get('premium_expiry')
    
    # Default Values
    access_str = "Nᴏ Pʟᴀɴ"
    span_str = "N/A"
    expiry_str = "N/A"
    left_str = "N/A"
    
    if is_premium and plan_key and expiry_raw:
        # Check if strictly active
        if expiry_raw > datetime.now():
            plan_info = PLANS.get(plan_key, {})
            plan_display = plan_info.get("display", plan_key)
            plan_days = plan_info.get("days", 0)
            
            # Formatting Span (e.g., [1 Day] or [8 Days])
            day_word = "Dᴀʏ" if plan_days == 1 else "Dᴀʏꜱ"
            span_str = f"[{plan_days} {day_word}]"
            
            # Formatting Access Line with Custom Emoji
            access_str = f"{plan_display} <tg-emoji emoji-id='{PLAN_STAR_ID}'>⭐</tg-emoji>"
            
            # Formatting Expiry Date
            expiry_str = expiry_raw.strftime("%Y-%m-%d %H:%M:%S")
            
            # Formatting Time Left (Days only, rounding up)
            delta = expiry_raw - datetime.now()
            days_left = (delta.total_seconds() + 86399) // 86400 # Round up to next day if > 0 seconds
            
            if days_left > 0:
                left_str = f"{int(days_left)} Dᴀʏꜱ"
            else:
                left_str = "< 1 Dᴀʏ"
                
        else:
            # Expired but DB hasn't caught up yet
            database.check_and_revoke_if_expired(user_id)
            access_str = "Exᴘɪʀᴇᴅ ❌"
            span_str = "N/A"
            expiry_str = expiry_raw.strftime("%Y-%m-%d %H:%M:%S")
            left_str = "0 Dᴀʏꜱ"

    # Format Username/Link
    username_display = f"@{u_username}" if u_username else "Nᴏ Uꜱᴇʀɴᴀᴍᴇ"
    
    # Format Ban Status with Custom Emoji
    if is_banned:
        ban_status = f'<b>Bᴀɴɴᴇᴅ <tg-emoji emoji-id="{BAN_EMOJI_ID}">🚫</tg-emoji></b>'
    else:
        ban_status = f'<b>Cʟᴇᴀɴ <tg-emoji emoji-id="{LIVE_EMOJI_ID}">✅</tg-emoji></b>'
    
    # Format Joined Date
    joined_str = u_joined.strftime("%Y-%m-%d") if u_joined else "Unknown"

    # Construct Message with Custom Emojis
    text = (
        f'<b><tg-emoji emoji-id="{USER_EMOJI_ID}">👤</tg-emoji> Uꜱᴇʀ Pʀᴏꜰɪʟᴇ</b>\n\n'
        f'━━━━━━━━━━━━━━━━━━\n'
        f'<b><tg-emoji emoji-id="{USERS_EMOJI_ID}">🆔</tg-emoji> ID ➛</b> <code>{u_id}</code>\n'
        f'<b>Nᴀᴍᴇ ➛</b> {u_name}\n'
        f'<b>Uꜱᴇʀ ➛</b> {username_display}\n'
        f'━━━━━━━━━━━━━━━━━━\n'
        f'<b>Sᴛᴀᴛᴜꜱ ➛</b> {ban_status}\n'
        f'━━━━━━━━━━━━━━━━━━\n'
        f'<b>Aᴄᴄᴇꜱꜱ ➛</b> {access_str}\n'
        f'<b>Sᴘᴀɴ ➛</b> {span_str}\n'
        f'<b>Exᴘɪʀᴇꜱ ➛</b> <code>{expiry_str}</code>\n'
        f'<b>Lᴇꜰᴛ ➛</b> {left_str}\n'
        f'━━━━━━━━━━━━━━━━━━\n'
        f'<b>Jᴏɪɴᴇᴅ ➛</b> {joined_str}\n'
    )
    
    await message.reply(text, parse_mode="HTML", link_preview_options={"is_disabled": True})
