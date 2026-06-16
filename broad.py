import asyncio
import logging
import database  # Import your local database module
from aiogram import Router, types
from aiogram.filters import Command
from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest

# ═══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════════

# REPLACE THIS WITH YOUR ACTUAL TELEGRAM ADMIN ID
ADMIN_ID = 8760363324 

# Update progress every N users
UPDATE_EVERY_N_USERS = 100

# Max concurrent sends (higher = faster broadcast, but respect Telegram rate limits)
MAX_CONCURRENT_BROADCASTS = 200

router = Router()

# Async lock - prevents concurrent/duplicate broadcasts
_broadcast_lock = asyncio.Lock()

# ═══════════════════════════════════════════════════════════════════════════════
# DB HELPER
# ═══════════════════════════════════════════════════════════════════════════════

def _get_all_user_ids() -> list:
    """Fetch all user IDs from database using the helper from database.py."""
    try:
        conn = database.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT user_id FROM users")
        rows = cursor.fetchall()
        cursor.close()
        conn.close()
        # RealDictCursor returns dicts, so we access by key
        return [row['user_id'] for row in rows]
    except Exception as e:
        logging.error(f"[broad] DB Error fetching users: {e}")
        return []

# ═══════════════════════════════════════════════════════════════════════════════
# LIVE STATUS BUILDER
# ═══════════════════════════════════════════════════════════════════════════════

def _status_text(total: int, done: int, sent: int, blocked: int, failed: int, finished: bool = False) -> str:
    """Generate formatted status text for broadcast progress."""
    header = "✅ <b>Broadcast Complete</b>" if finished else "📡 <b>Broadcasting…</b>"
    bar_filled = int((done / total) * 20) if total else 20
    bar = "█" * bar_filled + "░" * (20 - bar_filled)
    return (
        f"{header}\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"👥 <b>Total</b>   ➛ <b>{total}</b>\n"
        f"📨 <b>Sent</b>    ➛ <b>{sent}</b>\n"
        f"🚫 <b>Blocked</b> ➛ <b>{blocked}</b>\n"
        f"❌ <b>Failed</b>  ➛ <b>{failed}</b>\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"<code>[{bar}]</code> {done}/{total}"
    )

# ═══════════════════════════════════════════════════════════════════════════════
# BROADCAST WORKER (runs in background)
# ═══════════════════════════════════════════════════════════════════════════════

async def _broadcast_worker(target: types.Message, status_msg: types.Message, user_ids: list):
    """
    Core broadcast logic - runs as background task.
    Sends to *all* users concurrently (rate-limited for safety) so broadcasts finish fast.
    Progress is updated every UPDATE_EVERY_N_USERS users.
    """
    total = len(user_ids)
    sent = blocked = failed = 0
    done = 0

    sem = asyncio.Semaphore(MAX_CONCURRENT_BROADCASTS)
    lock = asyncio.Lock()

    async def send_to_one(uid: int):
        nonlocal sent, blocked, failed, done
        async with sem:
            try:
                await target.copy_to(chat_id=uid)
                async with lock:
                    sent += 1
            except TelegramForbiddenError:
                async with lock:
                    blocked += 1
                    logging.debug(f"[broad] blocked by {uid}")
            except TelegramBadRequest as e:
                async with lock:
                    failed += 1
                    logging.debug(f"[broad] bad request for {uid}: {e}")
            except Exception as e:
                async with lock:
                    failed += 1
                    logging.debug(f"[broad] error for {uid}: {e}")
            finally:
                async with lock:
                    done += 1

    # Fire off *all* sends at once (capped by the semaphore for safe concurrency)
    tasks = [asyncio.create_task(send_to_one(uid)) for uid in user_ids]

    # Live progress updater
    last_reported = 0
    try:
        while True:
            await asyncio.sleep(0.3)
            async with lock:
                current_done = done
                current_sent = sent
                current_blocked = blocked
                current_failed = failed
            if current_done >= total:
                break
            if current_done - last_reported >= UPDATE_EVERY_N_USERS:
                try:
                    await status_msg.edit_text(
                        _status_text(total, current_done, current_sent, current_blocked, current_failed),
                        parse_mode="HTML"
                    )
                except Exception:
                    pass
                last_reported = current_done
    except Exception:
        pass

    # Wait for every task to settle (they're already rate-limited)
    await asyncio.gather(*tasks, return_exceptions=True)

    # Final status
    async with lock:
        final_sent, final_blocked, final_failed = sent, blocked, failed

    try:
        await status_msg.edit_text(
            _status_text(total, total, final_sent, final_blocked, final_failed, finished=True),
            parse_mode="HTML"
        )
    except Exception:
        pass

    if _broadcast_lock.locked():
        _broadcast_lock.release()

    logging.info(
        f"[broad] Finished: {total} total | "
        f"{final_sent} sent | {final_blocked} blocked | {final_failed} failed"
    )

# ═══════════════════════════════════════════════════════════════════════════════
# /broad COMMAND
# ═══════════════════════════════════════════════════════════════════════════════

@router.message(Command("broad"))
async def broad_command(message: types.Message):
    """Handle /broad command - starts instant background broadcast."""
    
    # Admin check
    if message.from_user.id != ADMIN_ID:
        await message.reply("⛔ Admin only.")
        return

    # Must reply to a message
    if not message.reply_to_message:
        await message.reply(
            "↩️ Reply to a message with <b>/broad</b> to broadcast it to all users.\n\n"
            "<i>The message is sent as a native bot message — no 'Forwarded from' header.</i>",
            parse_mode="HTML"
        )
        return

    # 🔒 Prevent duplicate broadcasts using async lock
    if _broadcast_lock.locked():
        await message.reply("⚠️ A broadcast is already in progress. Please wait for it to finish.")
        return

    # Acquire the lock (prevents any other broadcast from starting)
    await _broadcast_lock.acquire()

    try:
        # Fetch all user IDs (runs in thread pool to not block)
        user_ids = await asyncio.to_thread(_get_all_user_ids)
        total = len(user_ids)
        target = message.reply_to_message

        if total == 0:
            await message.reply("⚠️ No users found in database.")
            _broadcast_lock.release()
            return

        # Send initial status message
        status_msg = await message.reply(
            _status_text(total, 0, 0, 0, 0),
            parse_mode="HTML"
        )

        # 🚀 Launch broadcast in BACKGROUND - returns immediately!
        # Other commands will work while broadcast runs
        asyncio.create_task(
            _broadcast_worker(target, status_msg, user_ids)
        )

        # Optional: Confirm to admin that broadcast started
        await message.answer(
            f"🚀 Broadcast started!\n"
            f"Sending to <b>{total}</b> users in background...\n\n"
            f"<i>Progress updates every {UPDATE_EVERY_N_USERS} users.</i>",
            parse_mode="HTML"
        )

    except Exception as e:
        # If anything fails before launching, release lock
        if _broadcast_lock.locked():
            _broadcast_lock.release()
        logging.error(f"[broad] Failed to start broadcast: {e}")
        await message.reply(f"❌ Error starting broadcast: {e}")

# ═══════════════════════════════════════════════════════════════════════════════
# OPTIONAL: Command to check broadcast status
# ═══════════════════════════════════════════════════════════════════════════════

@router.message(Command("bstatus"))
async def bstatus_command(message: types.Message):
    """Check if a broadcast is currently running."""
    if message.from_user.id != ADMIN_ID:
        await message.reply("⛔ Admin only.")
        return

    if _broadcast_lock.locked():
        await message.reply("📡 <b>Status:</b> Broadcast is currently running...")
    else:
        await message.reply("✅ <b>Status:</b> No broadcast in progress.", parse_mode="HTML")
