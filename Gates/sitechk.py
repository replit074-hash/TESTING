import asyncio
import random
import aiohttp
import os
import re
import time
import logging
import io
from typing import Optional

from aiogram import types, Router
from aiogram.filters import Command
from aiogram.types import FSInputFile, BufferedInputFile

# Import DB functions
from database import get_all_sites, clear_sites, save_sites_list, merge_sites_list

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CONFIGURATION
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

ADMIN_IDS    = [8760363324]
TEST_CARD    = "4000223372377978|05|29|651"
API_BASE_URL = "https://captchash.up.railway.app/shopii"
API_TIMEOUT  = 120

router = Router()

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# PROXY STATE (module-level, reloaded per run)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

PROXY_LIST: list  = []
BAD_PROXIES: set  = set()


def load_proxies() -> int:
    global PROXY_LIST
    path = "px.txt"
    if not os.path.exists(path):
        logging.warning(f"[SITECHK] {path} not found — no proxies loaded")
        PROXY_LIST = []
        return 0
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            raw = [l.strip() for l in f if l.strip() and not l.startswith(("#", ";"))]
        PROXY_LIST = list(dict.fromkeys(raw))
        logging.info(f"[SITECHK] Loaded {len(PROXY_LIST)} proxies")
        return len(PROXY_LIST)
    except Exception as e:
        logging.error(f"[SITECHK] Failed to read px.txt: {e}")
        PROXY_LIST = []
        return 0


load_proxies()

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# DEAD / SUCCESS PATTERNS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# FIX: removed "generic_error" — GENERIC_ERROR is a valid bank decline response
# from a working Shopify gateway. Keeping it here caused valid sites to be
# wiped from the DB, leaving the mass checker with no good sites.
DEAD_PATTERNS = [
    "site error!", "site not supported", "connection error",
    "not shopify", "site requires login", "timeout", "http error",
    "proxy error", "curl error", "could not resolve", "connect tunnel failed",
    "step 0 failed", "step 1 failed", "step 2 failed", "step 3 failed",
    "step 4 failed", "step 5 failed", "step 6 failed", "step 7 failed",
    "step 8 failed", "step 9 failed", "step 10 failed",
    "missing stableid", "missing buildid", "missing sourcetoken",
    "could not extract private_access_token", "could not find actions js",
    "missing proposal", "missing submit id", "exceeded 30 poll",
    "could not extract queuetoken", "could not extract identification",
    "could not extract session id", "could not extract delivery handle",
    "could not extract signedhandles", "could not extract shipping amount",
    "could not extract total amount", "could not extract receiptid",
    "could not extract sessiontoken", "errstoreincompatible", "captcha_required",
    "errmissingreceiptid", "failed to get token", "failed to get checkout",
    "failed to add to cart", "no valid products", "payment method is not shopify",
    "max retries", "json", "resolve", "item", "order_paid",
]

# FIX: added GENERIC_ERROR, INCORRECT_CVC, INVALID_CVV, INCORRECT_CVV,
# TEST_MODE_LIVE_CARD — all indicate a real Shopify gateway that responded
# to the payment attempt. These sites must be KEPT, not discarded.
SUCCESS_PATTERNS = [
    "CARD_DECLINED", "INVALID_CVC", "INCORRECT_CVV", "INSUFFICIENT_FUNDS",
    "GENERIC_DECLINE", "DO NOT HONOR", "DO_NOT_HONOR", "UNKNOWN_ERROR",
    "Processing Error", "EXPIRED_CARD", "PICK_UP_CARD", "DECISION_RULE_BLOCK",
    "FRAUD_SUSPECTED", "3DS_REQUIRED", "AMOUNT_TOO_SMALL",
    "INVALID_PURCHASE_TYPE", "INVALID_PAYMENT_METHOD", "INCORRECT_NUMBER",
    "GENERIC_ERROR", "INCORRECT_CVC", "INVALID_CVV", "INCORRECT_CVV",
    "TEST_MODE_LIVE_CARD", "TRANSACTION_NOT_ALLOWED", "RESTRICTED_CARD",
    "STOLEN_CARD", "LOST_CARD", "INCORRECT_ZIP",
]

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# HELPERS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def normalize_url(url: str) -> str:
    url = url.strip().lower().rstrip("/")
    if url.startswith("www."):
        url = url[4:]
    return url


def get_random_proxy() -> Optional[str]:
    available = [p for p in PROXY_LIST if p not in BAD_PROXIES]
    if not available:
        BAD_PROXIES.clear()
        available = PROXY_LIST
    return random.choice(available) if available else None


def mark_proxy_bad(proxy: str):
    if proxy:
        BAD_PROXIES.add(proxy)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# API CALL
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def call_api(site: str, proxy: str) -> dict:
    if not proxy:
        return {"success": False, "response": "No Proxies Available", "price": -1.0,
                "proxy_status": "Dead", "error": "NO_PROXIES"}
    api_url = f"{API_BASE_URL}?site={site}&cc={TEST_CARD}&proxy={proxy}"
    try:
        timeout = aiohttp.ClientTimeout(total=API_TIMEOUT)
        async with aiohttp.ClientSession() as sess:
            async with sess.get(api_url, timeout=timeout, ssl=False) as resp:
                if resp.status != 200:
                    return {"success": False, "response": f"HTTP Error {resp.status}",
                            "price": -1.0, "proxy_status": "Dead", "error": f"HTTP_{resp.status}"}
                try:
                    data = await resp.json(content_type=None)
                except Exception:
                    return {"success": False, "response": "Invalid JSON",
                            "price": -1.0, "proxy_status": "Dead", "error": "JSON_PARSE_ERROR"}
                proxy_raw    = data.get("Proxy", "Dead")
                proxy_status = "Live" if "live" in str(proxy_raw).lower() else "Dead"
                try:
                    price = float(re.sub(r"[^\d.]", "", str(data.get("Price", "-1.0"))) or -1)
                except ValueError:
                    price = -1.0
                return {"success": True, "response": data.get("Response", "Unknown"),
                        "price": price, "proxy_status": proxy_status, "error": None}
    except asyncio.TimeoutError:
        return {"success": False, "response": "Timeout", "price": -1.0,
                "proxy_status": "Dead", "error": "TIMEOUT"}
    except Exception as e:
        return {"success": False, "response": f"Error: {str(e)[:60]}", "price": -1.0,
                "proxy_status": "Dead", "error": "ERROR"}

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SITE CHECKER LOGIC
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def check_site(site: str) -> tuple:
    """Returns (site, status, price, response_msg) — status: KEEP | REMOVE | ERROR"""
    MAX_RETRIES = 3
    for attempt in range(MAX_RETRIES):
        proxy = get_random_proxy()
        if not proxy:
            return site, "REMOVE", -1.0, "No Proxies Available"

        result       = await call_api(site, proxy)
        response     = result.get("response", "Unknown")
        price        = result.get("price", -1.0)
        proxy_status = result.get("proxy_status", "Dead")
        error        = result.get("error")

        if proxy_status.lower() != "live":
            mark_proxy_bad(proxy)
            if error in ("PROXY_ERROR", "TIMEOUT", "ERROR") and attempt < MAX_RETRIES - 1:
                await asyncio.sleep(0.5)
                continue

        response_upper = response.upper()

        # ORDER_PAID treated as dead (site actually charged the test card)
        if "ORDER_PAID" in response_upper or response_upper.strip() == "PAID":
            return site, "REMOVE", price, f"ORDER_PAID - Blocked"

        # Dead patterns — site infrastructure error, not a real gateway response
        response_lower = response.lower()
        if any(p in response_lower for p in DEAD_PATTERNS):
            return site, "REMOVE", price, response

        # Valid gateway response — site is working, keep if price is in range
        if any(s.upper() in response_upper for s in SUCCESS_PATTERNS):
            if 0.0 < price <= 20.0:
                return site, "KEEP", price, f"${price:.2f} | {response}"
            else:
                return site, "REMOVE", price, f"Price ${price:.2f} out of range | {response}"

        # Unknown response with valid price — keep it
        if result.get("success") and 0.0 < price <= 20.0:
            return site, "KEEP", price, f"${price:.2f} | {response}"

        return site, "REMOVE", price, response

    return site, "ERROR", -1.0, "Max Retries Reached"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# BACKGROUND RUNNER
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def run_checker(bot, chat_id: int, sites: list, mode: str, status_msg_id: int):
    """
    mode: "audit" → replaces DB with only kept sites
          "add"   → merges kept sites into existing DB sites
    """
    global BAD_PROXIES
    BAD_PROXIES.clear()

    total         = len(sites)
    kept          = []
    kept_content  = []
    dead_count    = 0
    checked       = 0
    dupes_skipped = 0
    last_edit     = 0.0
    EDIT_INTERVAL = 2.0

    # For "add" mode, we need to know existing sites to count duplicates correctly
    existing_norm = set()
    if mode == "add":
        db_sites = await asyncio.to_thread(get_all_sites)
        existing_norm = {normalize_url(s) for s in db_sites}

    sem   = asyncio.Semaphore(200)

    async def worker(site):
        async with sem:
            return await check_site(site)

    tasks = [worker(s) for s in sites]

    for fut in asyncio.as_completed(tasks):
        try:
            site, status, price, resp = await fut
        except Exception as e:
            checked   += 1
            dead_count += 1
            logging.error(f"[SITECHK] Worker exception: {e}")
            continue

        checked += 1
        logging.info(f"[SITECHK] {site} | {status} | {resp}")

        if status == "KEEP":
            norm = normalize_url(site)
            if mode == "add" and norm in existing_norm:
                dupes_skipped += 1
                continue
            # Also check within the current batch to avoid self-dupes
            norm_kept = {normalize_url(s) for s in kept}
            if norm in norm_kept:
                dupes_skipped += 1
                continue

            kept.append(site)
            existing_norm.add(norm)
            price_str = f"${price:.2f}" if price > 0 else "N/A"
            kept_content.append(f"{site} | {price_str} | {resp}")
        else:
            dead_count += 1

        now = time.time()
        if now - last_edit >= EDIT_INTERVAL or checked % 10 == 0:
            try:
                dupe_line = f"\n🔄 <b>Duplicates Skipped:</b> <code>{dupes_skipped}</code>" if dupes_skipped else ""
                await bot.edit_message_text(
                    chat_id=chat_id, message_id=status_msg_id,
                    text=(
                        f"🔄 <b>{'Auditing' if mode == 'audit' else 'Adding'} {total} Sites...</b>\n"
                        f"<b>━━━━━━━━━━━━━━━━━━━━━━</b>\n"
                        f"✅ <b>Kept:</b> <code>{len(kept)}</code>\n"
                        f"❌ <b>Rejected:</b> <code>{dead_count}</code>\n"
                        f"🔄 <b>Checked:</b> <code>{checked}/{total}</code>\n"
                        f"🌐 <b>Proxies:</b> <code>{len(PROXY_LIST) - len(BAD_PROXIES)}/{len(PROXY_LIST)}</code>"
                        f"{dupe_line}"
                    ),
                    parse_mode="HTML",
                )
                last_edit = now
            except Exception:
                pass

    # Save to DB
    if mode == "audit":
        saved = await asyncio.to_thread(save_sites_list, kept)
    else:
        # "add" mode: merge only the new valid sites
        # kept list contains valid normalized sites
        saved = await asyncio.to_thread(merge_sites_list, kept)

    # Report file
    ts       = int(time.time())
    filename = f"sitechk_{'audit' if mode == 'audit' else 'add'}_{ts}.txt"
    content  = (
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"MODE: {'AUDIT' if mode == 'audit' else 'ADD'}\n"
        f"TOTAL CHECKED: {total}\n"
        f"KEPT (working): {len(kept)}\n"
        f"REJECTED: {dead_count}\n"
        f"DUPLICATES SKIPPED: {dupes_skipped}\n"
        f"PROXIES: {len(PROXY_LIST)} total | {len(BAD_PROXIES)} bad\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        + ("\n".join(kept_content) if kept_content else "No valid sites found.")
    )

    def _write():
        with open(filename, "w", encoding="utf-8") as f:
            f.write(content)
    await asyncio.to_thread(_write)

    try:
        dupe_final = f"\n🚫 <b>Duplicates Blocked:</b> <code>{dupes_skipped}</code>" if dupes_skipped else ""
        await bot.edit_message_text(
            chat_id=chat_id, message_id=status_msg_id,
            text=(
                f"✅ <b>{'Audit' if mode == 'audit' else 'Add'} Complete!</b>\n\n"
                f"<b>Total Checked:</b> {total}\n"
                f"<b>Valid (>$0-$20):</b> <code>{len(kept)}</code> ✅\n"
                f"<b>Rejected:</b> <code>{dead_count}</code> ❌\n"
                f"<b>━━━━━━━━━━━━━━━━━━━━━━</b>\n"
                f"🌐 <b>Proxies:</b> <code>{len(PROXY_LIST)}</code> | "
                f"<b>Bad:</b> <code>{len(BAD_PROXIES)}</code>"
                f"{dupe_final}"
            ),
            parse_mode="HTML",
        )
    except Exception:
        pass

    try:
        doc = BufferedInputFile(content.encode("utf-8"), filename=filename)
        await bot.send_document(
            chat_id=chat_id, document=doc,
            caption=f"📜 <b>{'Audit' if mode == 'audit' else 'Add'} Report</b>",
            parse_mode="HTML",
        )
    except Exception as e:
        await bot.send_message(chat_id=chat_id, text=f"❌ Error sending report: {e}")

    try:
        os.remove(filename)
    except Exception:
        pass

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# COMMAND HANDLERS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@router.message(Command("sitechk"))
async def cmd_sitechk(message: types.Message):
    """Audit existing sites — remove dead ones and deduplicate."""
    if not is_admin(message.from_user.id):
        await message.answer("⛔ <b>Unauthorized.</b>", parse_mode="HTML"); return

    load_proxies()
    # Fetch from DB
    sites = await asyncio.to_thread(get_all_sites)
    if not sites:
        await message.answer("📭 <b>No sites in Database</b>", parse_mode="HTML"); return

    status = await message.answer(
        f"🔄 <b>Starting Audit on {len(sites)} Sites...</b>\n"
        f"<b>━━━━━━━━━━━━━━━━━━━━━━</b>\n"
        f"🔄 <b>Checked:</b> <code>0/{len(sites)}</code>\n"
        f"✅ <b>Kept:</b> <code>0</code>\n"
        f"❌ <b>Rejected:</b> <code>0</code>\n"
        f"🌐 <b>Proxies:</b> <code>{len(PROXY_LIST)}</code>",
        parse_mode="HTML",
    )
    asyncio.create_task(run_checker(message.bot, message.chat.id, sites, "audit", status.message_id))


@router.message(Command("addsite"))
async def cmd_addsite(message: types.Message):
    """Add new sites from an uploaded file (auto-validates, deduplicates)."""
    if not is_admin(message.from_user.id):
        await message.answer("⛔ <b>Unauthorized.</b>", parse_mode="HTML"); return

    doc = message.document
    if not doc and message.reply_to_message:
        doc = message.reply_to_message.document

    if not doc:
        await message.answer(
            "⚠️ <b>Upload a .txt file containing sites with /addsite or reply to one.</b>",
            parse_mode="HTML",
        ); return

    try:
        file_info = await message.bot.get_file(doc.file_id)
        buf = io.BytesIO()
        await message.bot.download_file(file_info.file_path, buf)
        buf.seek(0)
        text = buf.read().decode("utf-8", errors="ignore")
    except Exception as e:
        await message.answer(f"❌ <b>Error reading file:</b> {e}", parse_mode="HTML"); return

    url_re    = re.compile(r"(https?://\S+)")
    new_sites = []
    seen      = set()
    for line in text.splitlines():
        m = url_re.search(line)
        if m:
            url = m.group(1).rstrip(".,;:!?)'\"")
            if url not in seen:
                seen.add(url); new_sites.append(url)

    if not new_sites:
        await message.answer("❌ <b>No valid URLs found in file.</b>", parse_mode="HTML"); return

    load_proxies()
    status = await message.answer(
        f"🔄 <b>Checking {len(new_sites)} New Sites...</b>\n"
        f"<b>━━━━━━━━━━━━━━━━━━━━━━</b>\n"
        f"🔄 <b>Checked:</b> <code>0/{len(new_sites)}</code>\n"
        f"✅ <b>Added:</b> <code>0</code>\n"
        f"❌ <b>Rejected:</b> <code>0</code>\n"
        f"🚫 <b>Duplicates:</b> <code>0</code>\n"
        f"🌐 <b>Proxies:</b> <code>{len(PROXY_LIST)}</code>",
        parse_mode="HTML",
    )
    asyncio.create_task(run_checker(message.bot, message.chat.id, new_sites, "add", status.message_id))


@router.message(Command("siteall"))
async def cmd_siteall(message: types.Message):
    """Download the full deduplicated list of sites."""
    if not is_admin(message.from_user.id):
        await message.answer("⛔ <b>Unauthorized.</b>", parse_mode="HTML"); return

    # Fetch from DB
    sites = await asyncio.to_thread(get_all_sites)
    if not sites:
        await message.answer("📭 <b>Database is empty.</b>", parse_mode="HTML"); return

    content = f"Total Sites: {len(sites)} (Deduplicated)\n\n" + "\n".join(sites)
    doc     = BufferedInputFile(content.encode("utf-8"), filename=f"sites_{int(time.time())}.txt")
    await message.answer_document(
        document=doc,
        caption=f"📜 <b>Total Sites:</b> <code>{len(sites)}</code>",
        parse_mode="HTML",
    )


@router.message(Command("removeall"))
async def cmd_removeall(message: types.Message):
    """Clear all sites from the database."""
    if not is_admin(message.from_user.id):
        await message.answer("⛔ <b>Unauthorized.</b>", parse_mode="HTML"); return

    # Fetch from DB for count
    sites = await asyncio.to_thread(get_all_sites)
    if not sites:
        await message.answer("📭 <b>Database is already empty.</b>", parse_mode="HTML"); return

    await asyncio.to_thread(clear_sites)
    await message.answer(
        f"✅ <b>Cleared!</b> Removed <code>{len(sites)}</code> sites.",
        parse_mode="HTML",
    )


@router.message(Command("dedupe"))
async def cmd_dedupe(message: types.Message):
    """Force-deduplicate sites in database."""
    if not is_admin(message.from_user.id):
        await message.answer("⛔ <b>Unauthorized.</b>", parse_mode="HTML"); return

    sites = await asyncio.to_thread(get_all_sites)
    if not sites:
        await message.answer("📭 <b>Database is empty.</b>", parse_mode="HTML"); return

    original = len(sites)
    unique_sites = list(dict.fromkeys(sites))
    final = await asyncio.to_thread(save_sites_list, unique_sites)
    removed  = original - final

    if removed > 0:
        await message.answer(
            f"✨ <b>Done!</b>\n\n"
            f"<b>Original:</b> <code>{original}</code>\n"
            f"<b>Removed:</b> <code>{removed}</code> duplicates\n"
            f"<b>Final:</b> <code>{final}</code> unique sites",
            parse_mode="HTML",
        )
    else:
        await message.answer(
            f"✅ <b>No duplicates found.</b>\n<b>Total:</b> <code>{final}</code>",
            parse_mode="HTML",
        )


@router.message(Command("proxyinfo"))
async def cmd_proxyinfo(message: types.Message):
    """Show proxy stats."""
    if not is_admin(message.from_user.id):
        await message.answer("⛔ <b>Unauthorized.</b>", parse_mode="HTML"); return

    available = len(PROXY_LIST) - len(BAD_PROXIES)
    lines = [
        "🌐 <b>Proxy Information</b>",
        "<b>━━━━━━━━━━━━━━━━━━━━━━</b>",
        f"📊 <b>Total:</b> <code>{len(PROXY_LIST)}</code>",
        f"✅ <b>Available:</b> <code>{available}</code>",
        f"❌ <b>Bad/Dead:</b> <code>{len(BAD_PROXIES)}</code>",
        "<b>━━━━━━━━━━━━━━━━━━━━━━</b>",
    ]
    for i, proxy in enumerate(PROXY_LIST[:20], 1):
        status = "❌ Dead" if proxy in BAD_PROXIES else "✅ Live"
        display = f"***@{proxy.split('@')[1]}" if "@" in proxy else proxy[:30]
        lines.append(f"<code>{i}.</code> {display} — {status}")
    if len(PROXY_LIST) > 20:
        lines.append(f"... and {len(PROXY_LIST) - 20} more")
    await message.answer("\n".join(lines), parse_mode="HTML")


@router.message(Command("resetproxy"))
async def cmd_resetproxy(message: types.Message):
    """Reset bad proxy list."""
    if not is_admin(message.from_user.id):
        await message.answer("⛔ <b>Unauthorized.</b>", parse_mode="HTML"); return

    cleared = len(BAD_PROXIES)
    BAD_PROXIES.clear()
    await message.answer(
        f"✅ <b>Proxy List Reset!</b>\n\n"
        f"<b>Cleared:</b> <code>{cleared}</code> bad proxies\n"
        f"<b>Available Now:</b> <code>{len(PROXY_LIST)}</code>",
        parse_mode="HTML",
    )


@router.message(Command("reloadproxy"))
async def cmd_reloadproxy(message: types.Message):
    """Reload px.txt from disk."""
    if not is_admin(message.from_user.id):
        await message.answer("⛔ <b>Unauthorized.</b>", parse_mode="HTML"); return

    BAD_PROXIES.clear()
    count = load_proxies()
    await message.answer(
        f"✅ <b>Proxies Reloaded!</b>\n\n"
        f"<b>Loaded:</b> <code>{count}</code> proxies from px.txt",
        parse_mode="HTML",
    )
