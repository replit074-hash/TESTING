import asyncio
import logging
import uuid
from typing import Any, Dict, List, Optional

from aiogram import types, Router, F, BaseMiddleware
from aiogram.filters import Command
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    InputMediaPhoto, InputMediaVideo, InputMediaAnimation, InputMediaDocument,
    LinkPreviewOptions,
)

# ═══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════════

# REPLACE WITH YOUR ADMIN ID
ADMIN_ID = 8760363324

# REPLACE WITH YOUR FEEDBACK CHANNEL ID
FEEDBACK_CHANNEL = -1003952934184

router = Router()

_NO_PREVIEW = LinkPreviewOptions(is_disabled=True)

# ═══════════════════════════════════════════════════════════════════════════════
# CUSTOM EMOJI IDS
# ═══════════════════════════════════════════════════════════════════════════════
FEEDBACK_EMOJI_ID = "4956719506027185156"
APPROVED_EMOJI_ID = "4958610528588008305"
REJECTED_EMOJI_ID = "4956612582816351459"
USER_EMOJI_ID = "5956561749070057536"
BUTTON_EMOJI_ID = "5465465194056525619"
BOT_EMOJI_ID = "5465465194056525619"

# ═══════════════════════════════════════════════════════════════════════════════
# SMALL CAPS HELPERS
# ═══════════════════════════════════════════════════════════════════════════════
SMALL_CAPS_MAP = {
    'a': 'ᴀ', 'b': 'ʙ', 'c': 'ᴄ', 'd': 'ᴅ', 'e': 'ᴇ',
    'f': 'ꜰ', 'g': 'ɢ', 'h': 'ʜ', 'i': 'ɪ', 'j': 'ᴊ',
    'k': 'ᴋ', 'l': 'ʟ', 'm': 'ᴍ', 'n': 'ɴ', 'o': 'ᴏ',
    'p': 'ᴘ', 'q': 'ǫ', 'r': 'ʀ', 's': 'ꜱ', 't': 'ᴛ',
    'u': 'ᴜ', 'v': 'ᴠ', 'w': 'ᴡ', 'x': 'x', 'y': 'ʏ',
    'z': 'ᴢ'
}

def to_small_caps(text: str) -> str:
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

# ═══════════════════════════════════════════════════════════════════════════════
# MEDIA GROUP COLLECTOR MIDDLEWARE
# ═══════════════════════════════════════════════════════════════════════════════
_MEDIA_GROUPS: Dict[str, List[types.Message]] = {}

class MediaGroupCollectorMiddleware(BaseMiddleware):
    async def __call__(self, handler, event: types.Message, data: Dict[str, Any]):
        gid = getattr(event, "media_group_id", None)
        if gid:
            bucket = _MEDIA_GROUPS.setdefault(gid, [])
            existing_ids = {m.message_id for m in bucket}
            if event.message_id not in existing_ids:
                bucket.append(event)
        return await handler(event, data)

router.message.middleware(MediaGroupCollectorMiddleware())

# ═══════════════════════════════════════════════════════════════════════════════
# IN-MEMORY PENDING STORE
# ═══════════════════════════════════════════════════════════════════════════════
_PENDING: dict = {}
_LAST_HIT_SOURCE: Dict[int, dict] = {}
_LAST_PROCESSED_GROUPS: set = set()

# ═══════════════════════════════════════════════════════════════════════════════
# FIX: LAST HIT CAPTURE MIDDLEWARE
# ═══════════════════════════════════════════════════════════════════════════════
# We moved the logic from a broken Handler to a proper Middleware.
# This allows it to track messages silently without crashing or blocking commands.
class LastHitSourceMiddleware(BaseMiddleware):
    async def __call__(self, handler, event: types.Message, data: Dict[str, Any]):
        if event.from_user is None:
            return await handler(event, data)

        txt = (event.text or "").lstrip()
        
        # Do not process commands, let them pass through to their handlers
        if txt.startswith("/"):
            return await handler(event, data)

        uid = event.from_user.id
        gid = getattr(event, "media_group_id", None)

        if gid is not None:
            if gid in _LAST_PROCESSED_GROUPS:
                return await handler(event, data)

            await asyncio.sleep(0.6)

            if gid in _LAST_PROCESSED_GROUPS:
                return await handler(event, data)

            items = list(_MEDIA_GROUPS.get(gid, [event]))
            items.sort(key=lambda m: m.message_id)
            items = items[:10]

            media_type = "photo_album"
            hit_text = (
                (items[0].caption or items[0].text or "").strip()
                if items else (event.caption or event.text or "").strip()
            )

            _LAST_HIT_SOURCE[uid] = {
                "messages": items,
                "media_type": media_type,
                "hit_text": hit_text,
                "user": event.from_user,
            }
            _LAST_PROCESSED_GROUPS.add(gid)

            if len(_LAST_PROCESSED_GROUPS) > 1500:
                _LAST_PROCESSED_GROUPS.clear()
        else:
            media_type = self._detect_media(event)
            hit_text = (event.caption or event.text or "").strip()

            _LAST_HIT_SOURCE[uid] = {
                "messages": [event],
                "media_type": media_type,
                "hit_text": hit_text,
                "user": event.from_user,
            }
        
        return await handler(event, data)

    def _detect_media(self, msg: types.Message) -> str:
        if msg.photo:       return "photo"
        if msg.video:       return "video"
        if msg.animation:   return "animation"
        if msg.document:    return "document"
        return "text"

# Register the middleware
router.message.middleware(LastHitSourceMiddleware())

# ═══════════════════════════════════════════════════════════════════════════════
# MEDIA DETECTION (Helper functions)
# ═══════════════════════════════════════════════════════════════════════════════
def _detect_media(msg: types.Message) -> str:
    if msg.photo:       return "photo"
    if msg.video:       return "video"
    if msg.animation:   return "animation"
    if msg.document:    return "document"
    return "text"

def _get_file_id(msg: types.Message) -> Optional[str]:
    if msg.photo:       return msg.photo[-1].file_id
    if msg.video:       return msg.video.file_id
    if msg.animation:   return msg.animation.file_id
    if msg.document:    return msg.document.file_id
    return None

# ═══════════════════════════════════════════════════════════════════════════════
# HELPERS (NEW UI - SMALL CAPS STYLE)
# ═══════════════════════════════════════════════════════════════════════════════
def _admin_info_text(user: types.User, media_type: str, count: int) -> str:
    username_part = f"@{user.username}" if user.username else "N/A"
    user_link     = f'<a href="tg://user?id={user.id}">{user.first_name}</a>'
    media_label   = f"{count}× {media_type}" if count > 1 else media_type
    media_styled  = to_small_caps_title(media_label)
    return (
        "━━━━━━━━━━━━━━━━\n"
        f"<b>Uꜱᴇʀ ➛ {user_link}</b> <tg-emoji emoji-id=\"{USER_EMOJI_ID}\">👤</tg-emoji>\n"
        f"<b>Uɪᴅ ➛ {user.id}</b>\n"
        f"<b>Usᴇʀɴᴀᴍᴇ ➛ {username_part}</b>\n"
        f"<b>Mᴇᴅɪᴀ ➛ {media_styled}</b>\n"
        "━━━━━━━━━━━━━━━━"
    )

def _approve_keyboard(pid: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text=f"Aᴘᴘʀᴏᴠᴇ",
            callback_data=f"fb_approve_{pid}",
            style="success",
            icon_custom_emoji_id=APPROVED_EMOJI_ID
        ),
        InlineKeyboardButton(
            text=f"Rᴇᴊᴇᴄᴛ",
            callback_data=f"fb_reject_{pid}",
            style="danger",
            icon_custom_emoji_id=REJECTED_EMOJI_ID
        ),
    ]])

def _channel_caption(user: types.User, hit_text: str) -> str:
    user_link = f'<a href="tg://user?id={user.id}">{user.first_name}</a>'
    note_part = hit_text if hit_text else "—"
    note_styled = to_small_caps_title(str(note_part))
    return (
        f'<b>Fᴇᴇᴅʙᴀᴄᴋ</b> <tg-emoji emoji-id="{FEEDBACK_EMOJI_ID}">💎</tg-emoji>\n'
        f"<b>Uꜱᴇʀ ➛</b> {user_link} <tg-emoji emoji-id=\"{USER_EMOJI_ID}\">👤</tg-emoji>\n"
        f"<b>Uɪᴅ ➛</b> {user.id}\n"
        "━━━━━━━━━━━━━━\n"
        f" {note_styled} "
    )

def _channel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text="Bᴜʏ Nᴏᴡ",
            url="https://t.me/CARDXLEFT_BOT?start=buy",
            style="primary",
            icon_custom_emoji_id=BOT_EMOJI_ID
        )
    ]])

def _build_input_media(msg: types.Message, caption: str = "", parse_mode: str = "HTML") -> Optional[Any]:
    fid = _get_file_id(msg)
    if not fid:
        return None
    mtype = _detect_media(msg)
    if mtype == "photo":
        return InputMediaPhoto(media=fid, caption=caption or None, parse_mode=parse_mode if caption else None)
    if mtype == "video":
        return InputMediaVideo(media=fid, caption=caption or None, parse_mode=parse_mode if caption else None)
    if mtype == "animation":
        return InputMediaDocument(media=fid, caption=caption or None, parse_mode=parse_mode if caption else None)
    if mtype == "document":
        return InputMediaDocument(media=fid, caption=caption or None, parse_mode=parse_mode if caption else None)
    return None

# ═══════════════════════════════════════════════════════════════════════════════
# RESOLVE HIT SOURCE
# ═══════════════════════════════════════════════════════════════════════════════
async def _resolve_hit_source(replied: Optional[types.Message], issuer: types.User) -> Optional[dict]:
    if replied:
        gid = getattr(replied, "media_group_id", None)
        if gid:
            await asyncio.sleep(0.5)
            group_msgs = list(_MEDIA_GROUPS.get(gid, [replied]))
            group_msgs.sort(key=lambda m: m.message_id)
            group_msgs = group_msgs[:10]
            media_type = "photo_album"
            hit_text = (replied.caption or replied.text or "").strip()
        else:
            group_msgs = [replied]
            media_type = _detect_media(replied)
            hit_text = (replied.caption or replied.text or "").strip()

        return {
            "messages": group_msgs,
            "media_type": media_type,
            "hit_text": hit_text,
            "user": issuer,
        }

    src = _LAST_HIT_SOURCE.pop(issuer.id, None)
    if not src:
        return None

    return {
        "messages": src["messages"],
        "media_type": src["media_type"],
        "hit_text": src["hit_text"],
        "user": issuer,
    }

# ═══════════════════════════════════════════════════════════════════════════════
# /fb COMMAND HANDLER
# ═══════════════════════════════════════════════════════════════════════════════
@router.message(Command("fb"))
async def feedback_cmd(message: types.Message):
    user = message.from_user
    replied = message.reply_to_message

    source = await _resolve_hit_source(replied, user)
    if not source:
        await message.reply(
            f"<b>Usᴀɢᴇ ➺</b> Rᴇᴘʟʏ ᴛᴏ ʏᴏᴜʀ ʜɪᴛ ᴡɪᴛʜ /ꜰʙ (ᴀʟʙᴜᴍs sᴜᴘᴘᴏʀᴛᴇᴅ), ᴏʀ ꜰᴏʀᴡᴀʀᴅ/ᴜᴘʟᴏᴀᴅ ᴘʜᴏᴛᴏ(s) ᴛʜᴇɴ sᴇɴᴅ /ꜰʙ",
            parse_mode="HTML"
        )
        return

    await message.reply(
        "━━━━━━━━━━━━━━━━\n"
        f"<b>Fᴇᴇᴅʙᴀᴄᴋ Sᴜʙᴍɪᴛᴛᴇᴅ <tg-emoji emoji-id=\"{APPROVED_EMOJI_ID}\">✅</tg-emoji></b>\n"
        "━━━━━━━━━━━━━━━━",
        parse_mode="HTML"
    )

    group_msgs = source["messages"]
    media_type = source["media_type"]
    hit_text   = source["hit_text"]

    pid = uuid.uuid4().hex[:10]
    _PENDING[pid] = {
        "messages":   group_msgs,
        "media_type": media_type,
        "hit_text":   hit_text,
        "user":       user,
    }

    admin_text = _admin_info_text(user, media_type, len(group_msgs))

    async def _forward_all():
        for m in group_msgs:
            try:
                await message.bot.forward_message(
                    chat_id=ADMIN_ID,
                    from_chat_id=m.chat.id,
                    message_id=m.message_id
                )
            except Exception as e:
                logging.warning(f"[fb] Could not forward message {m.message_id}: {e}")
                try:
                    await message.bot.copy_message(
                        chat_id=ADMIN_ID,
                        from_chat_id=m.chat.id,
                        message_id=m.message_id
                    )
                except Exception as e2:
                    logging.warning(f"[fb] Could not copy message {m.message_id} either: {e2}")

    async def _send_admin_info():
        try:
            await message.bot.send_message(
                chat_id=ADMIN_ID,
                text=admin_text,
                parse_mode="HTML",
                reply_markup=_approve_keyboard(pid),
                link_preview_options=_NO_PREVIEW,
            )
            logging.info(f"[fb] Pending {pid} stored for user {user.id} ({media_type}, {len(group_msgs)} item(s))")
        except Exception as e:
            logging.error(f"[fb] Admin notify error: {e}")

    await asyncio.gather(_forward_all(), _send_admin_info())

# ═══════════════════════════════════════════════════════════════════════════════
# APPROVE CALLBACK
# ═══════════════════════════════════════════════════════════════════════════════
@router.callback_query(F.data.startswith("fb_approve_"))
async def fb_approve(callback: types.CallbackQuery):
    pid   = callback.data.replace("fb_approve_", "")
    entry = _PENDING.pop(pid, None)

    await callback.answer()

    if not entry:
        try:
            await callback.message.edit_text(
                "<b>Eхᴘɪʀᴇᴅ — ꜰᴇᴇᴅʙᴀᴄᴋ ᴀʟʀᴇᴀᴅʏ ʜᴀɴᴅʟᴇᴅ ᴏʀ ʙᴏᴛ ʀᴇsᴛᴀʀᴛᴇᴅ.</b>",
                parse_mode="HTML"
            )
        except Exception:
            pass
        return

    try:
        await callback.message.edit_text(
            f"<b>Aᴘᴘʀᴏᴠᴇᴅ <tg-emoji emoji-id=\"{APPROVED_EMOJI_ID}\">✅</tg-emoji> — Pᴏsᴛɪɴɢ ᴛᴏ ᴄʜᴀɴɴᴇʟ...</b>",
            parse_mode="HTML"
        )
    except Exception as e:
        logging.warning(f"[fb] Could not edit admin message: {e}")

    user       = entry["user"]
    msgs       = entry["messages"]
    media_type = entry["media_type"]
    hit_text   = entry["hit_text"]
    caption    = _channel_caption(user, hit_text)
    ch_kb      = _channel_keyboard()

    try:
        if media_type == "photo_album" and len(msgs) > 1:
            media_items = []
            for i, m in enumerate(msgs):
                inp = _build_input_media(m, caption=caption if i == 0 else "")
                if inp:
                    media_items.append(inp)
            if media_items:
                await callback.bot.send_media_group(
                    chat_id=FEEDBACK_CHANNEL,
                    media=media_items
                )
                await callback.bot.send_message(
                    chat_id=FEEDBACK_CHANNEL,
                    text="⬆️",
                    reply_markup=ch_kb,
                    link_preview_options=_NO_PREVIEW,
                )
            else:
                await callback.bot.copy_message(
                    chat_id=FEEDBACK_CHANNEL,
                    from_chat_id=msgs[0].chat.id,
                    message_id=msgs[0].message_id,
                    caption=caption,
                    parse_mode="HTML",
                    reply_markup=ch_kb
                )

        elif media_type == "photo":
            await callback.bot.send_photo(
                chat_id=FEEDBACK_CHANNEL,
                photo=_get_file_id(msgs[0]),
                caption=caption,
                parse_mode="HTML",
                reply_markup=ch_kb
            )

        elif media_type == "video":
            await callback.bot.send_video(
                chat_id=FEEDBACK_CHANNEL,
                video=_get_file_id(msgs[0]),
                caption=caption,
                parse_mode="HTML",
                reply_markup=ch_kb
            )

        elif media_type == "animation":
            await callback.bot.send_animation(
                chat_id=FEEDBACK_CHANNEL,
                animation=_get_file_id(msgs[0]),
                caption=caption,
                parse_mode="HTML",
                reply_markup=ch_kb
            )

        elif media_type == "document":
            await callback.bot.send_document(
                chat_id=FEEDBACK_CHANNEL,
                document=_get_file_id(msgs[0]),
                caption=caption,
                parse_mode="HTML",
                reply_markup=ch_kb
            )

        else:
            await callback.bot.send_message(
                chat_id=FEEDBACK_CHANNEL,
                text=caption,
                parse_mode="HTML",
                link_preview_options=_NO_PREVIEW,
                reply_markup=ch_kb
            )

        try:
            await callback.message.edit_text(
                f"<b>Aᴘᴘʀᴏᴠᴇᴅ <tg-emoji emoji-id=\"{APPROVED_EMOJI_ID}\">✅</tg-emoji> — Pᴏsᴛᴇᴅ ᴛᴏ ᴄʜᴀɴɴᴇʟ</b>",
                parse_mode="HTML"
            )
        except Exception:
            pass
        logging.info(f"[fb] Approved and posted for user {user.id} ({media_type}, {len(msgs)} item(s))")

    except Exception as e:
        logging.error(f"[fb] Approve post error: {e}")
        try:
            await callback.message.edit_text(
                f"<b>Aᴘᴘʀᴏᴠᴇ Fᴀɪʟᴇᴅ ➺</b> <code>{str(e)[:40]}</code>",
                parse_mode="HTML"
            )
        except Exception:
            pass

# ═══════════════════════════════════════════════════════════════════════════════
# REJECT CALLBACK
# ═══════════════════════════════════════════════════════════════════════════════
@router.callback_query(F.data.startswith("fb_reject_"))
async def fb_reject(callback: types.CallbackQuery):
    await callback.answer()
    pid = callback.data.replace("fb_reject_", "")
    _PENDING.pop(pid, None)
    try:
        await callback.message.edit_text(
            f'<b>Rᴇᴊᴇᴄᴛᴇᴅ <tg-emoji emoji-id="{REJECTED_EMOJI_ID}">❌</tg-emoji></b>',
            parse_mode="HTML"
        )
    except Exception as e:
        logging.warning(f"[fb] Could not edit reject message: {e}")
    logging.info(f"[fb] Rejected feedback {pid}")
