import logging
import random
import string
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List

import psycopg2
from psycopg2.extras import RealDictCursor

# ═══════════════════════════════════════════════════════════════════════════════
# CONNECTION
# ═══════════════════════════════════════════════════════════════════════════════

DATABASE_URL = "postgresql://postgres:JVFCZiXNnFOLwDsxiZuVYHRZZMDpruAO@postgres.railway.internal:5432/railway"


def get_connection():
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)


def get_db_connection():
    return get_connection()


# ═══════════════════════════════════════════════════════════════════════════════
# SCHEMA INIT
# ═══════════════════════════════════════════════════════════════════════════════

def init_db():
    conn   = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id        BIGINT PRIMARY KEY,
            username       TEXT,
            first_name     TEXT,
            is_banned      BOOLEAN   DEFAULT FALSE,
            is_premium     BOOLEAN   DEFAULT FALSE,
            current_plan   TEXT      DEFAULT NULL,
            premium_expiry TIMESTAMP,
            joined_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            cc_checked     INTEGER   DEFAULT 0,
            cc_charged     INTEGER   DEFAULT 0,
            cc_live        INTEGER   DEFAULT 0,
            cc_dead        INTEGER   DEFAULT 0,
            mrz_checked    INTEGER   DEFAULT 0,
            mrz_charged    INTEGER   DEFAULT 0,
            mrz_live       INTEGER   DEFAULT 0,
            mrz_dead       INTEGER   DEFAULT 0
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS redeem_codes (
            code     TEXT PRIMARY KEY,
            plan     TEXT,
            used     BOOLEAN   DEFAULT FALSE,
            used_by  BIGINT,
            used_at  TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS gate_settings (
            gate_name  TEXT PRIMARY KEY,
            enabled    BOOLEAN DEFAULT TRUE
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sites (
            url TEXT PRIMARY KEY,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.commit()

    def _migrate(sql, name):
        try:
            c = get_connection()
            cur = c.cursor()
            cur.execute(sql)
            c.commit()
            c.close()
            logging.info(f"✅ Migration OK: {name}")
        except psycopg2.errors.DuplicateColumn:
            pass
        except psycopg2.errors.UndefinedTable:
            pass
        except Exception as e:
            logging.warning(f"Migration note ({name}): {e}")

    _migrate("ALTER TABLE users ADD COLUMN IF NOT EXISTS current_plan TEXT DEFAULT NULL;",  "current_plan")
    _migrate("ALTER TABLE users DROP COLUMN IF EXISTS credits;",                            "drop credits")
    _migrate("ALTER TABLE users ADD COLUMN IF NOT EXISTS cc_checked  INTEGER DEFAULT 0;",   "cc_checked")
    _migrate("ALTER TABLE users ADD COLUMN IF NOT EXISTS cc_charged  INTEGER DEFAULT 0;",   "cc_charged")
    _migrate("ALTER TABLE users ADD COLUMN IF NOT EXISTS cc_live     INTEGER DEFAULT 0;",   "cc_live")
    _migrate("ALTER TABLE users ADD COLUMN IF NOT EXISTS cc_dead     INTEGER DEFAULT 0;",   "cc_dead")
    _migrate("ALTER TABLE users ADD COLUMN IF NOT EXISTS mrz_checked INTEGER DEFAULT 0;",   "mrz_checked")
    _migrate("ALTER TABLE users ADD COLUMN IF NOT EXISTS mrz_charged INTEGER DEFAULT 0;",   "mrz_charged")
    _migrate("ALTER TABLE users ADD COLUMN IF NOT EXISTS mrz_live    INTEGER DEFAULT 0;",   "mrz_live")
    _migrate("ALTER TABLE users ADD COLUMN IF NOT EXISTS mrz_dead    INTEGER DEFAULT 0;",   "mrz_dead")

    conn.close()
    logging.info("✅ PostgreSQL database initialized.")

# ═══════════════════════════════════════════════════════════════════════════════
# SITES MANAGEMENT
# ═══════════════════════════════════════════════════════════════════════════════

def get_all_sites() -> List[str]:
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT url FROM sites")
        rows = cursor.fetchall()
        conn.close()
        return [row['url'] for row in rows]
    except Exception as e:
        logging.error(f"[DB] get_all_sites error: {e}")
        return []

def clear_sites() -> None:
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("TRUNCATE TABLE sites")
        conn.commit()
        conn.close()
    except Exception as e:
        logging.error(f"[DB] clear_sites error: {e}")

def save_sites_list(sites_list: List[str]) -> int:
    if not sites_list:
        clear_sites()
        return 0
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("BEGIN")
        cursor.execute("TRUNCATE TABLE sites")
        cursor.executemany("INSERT INTO sites (url) VALUES (%s)", [(s,) for s in sites_list])
        conn.commit()
        count = cursor.rowcount
        conn.close()
        return count
    except Exception as e:
        logging.error(f"[DB] save_sites_list error: {e}")
        if 'conn' in locals() and conn:
            conn.rollback()
        return 0

def merge_sites_list(sites_list: List[str]) -> int:
    if not sites_list:
        return 0
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.executemany(
            "INSERT INTO sites (url) VALUES (%s) ON CONFLICT (url) DO NOTHING",
            [(s,) for s in sites_list]
        )
        conn.commit()
        count = cursor.rowcount
        conn.close()
        return count
    except Exception as e:
        logging.error(f"[DB] merge_sites_list error: {e}")
        return 0

# ═══════════════════════════════════════════════════════════════════════════════
# USER CRUD
# ═══════════════════════════════════════════════════════════════════════════════

def ensure_user(user_id: int, username: str, first_name: str):
    conn   = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO users (user_id, username, first_name) VALUES (%s, %s, %s) "
        "ON CONFLICT (user_id) DO NOTHING",
        (user_id, username, first_name),
    )
    conn.commit()
    conn.close()


def is_banned(user_id: int) -> bool:
    conn   = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT is_banned FROM users WHERE user_id = %s", (user_id,))
    row    = cursor.fetchone()
    conn.close()
    return bool(row and row['is_banned'])


def ban_user(user_id: int) -> bool:
    ensure_user(user_id, "Unknown", "User")
    conn   = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET is_banned = TRUE WHERE user_id = %s", (user_id,))
    affected = cursor.rowcount
    conn.commit()
    conn.close()
    return affected > 0


def unban_user(user_id: int) -> bool:
    conn   = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET is_banned = FALSE WHERE user_id = %s", (user_id,))
    affected = cursor.rowcount
    conn.commit()
    conn.close()
    return affected > 0


def get_full_user_info(user_id: int) -> Optional[Dict[str, Any]]:
    conn   = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE user_id = %s", (user_id,))
    row    = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def get_user_link(user_id: int) -> str:
    conn   = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT first_name, username FROM users WHERE user_id = %s", (user_id,))
    row    = cursor.fetchone()
    conn.close()
    import html as _html
    first_name = _html.escape(row['first_name'] if row and row['first_name'] else "User")
    username   = row['username'] if row else None
    if username:
        return f'<a href="https://t.me/{username}"><b>{first_name}</b></a>'
    return f'<a href="tg://user?id={user_id}"><b>{first_name}</b></a>'

# ═══════════════════════════════════════════════════════════════════════════════
# SUBSCRIPTION
# ═══════════════════════════════════════════════════════════════════════════════

def activate_subscription(user_id: int, plan: str, days: int, amount_paid: float = 0) -> bool:
    ensure_user(user_id, "Unknown", "User")
    conn   = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT premium_expiry FROM users WHERE user_id = %s", (user_id,))
    row    = cursor.fetchone()
    current_expiry = row['premium_expiry'] if row else None
    if current_expiry and current_expiry > datetime.now():
        new_expiry = current_expiry + timedelta(days=days)
    else:
        new_expiry = datetime.now() + timedelta(days=days)
    cursor.execute(
        "UPDATE users SET is_premium = TRUE, current_plan = %s, premium_expiry = %s WHERE user_id = %s",
        (plan, new_expiry, user_id),
    )
    affected = cursor.rowcount
    conn.commit()
    conn.close()
    return affected > 0


def revoke_subscription(user_id: int) -> bool:
    ensure_user(user_id, "Unknown", "User")
    conn   = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE users SET is_premium = FALSE, current_plan = NULL, premium_expiry = NULL WHERE user_id = %s",
        (user_id,),
    )
    affected = cursor.rowcount
    conn.commit()
    conn.close()
    return affected > 0


def check_and_revoke_if_expired(user_id: int) -> bool:
    conn   = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT is_premium, premium_expiry FROM users WHERE user_id = %s", (user_id,)
    )
    row = cursor.fetchone()
    if not row:
        conn.close()
        return False
    if row['is_premium'] and row['premium_expiry'] and row['premium_expiry'] <= datetime.now():
        cursor.execute(
            "UPDATE users SET is_premium = FALSE, current_plan = NULL WHERE user_id = %s",
            (user_id,),
        )
        conn.commit()
        conn.close()
        logging.info(f"🔄 User {user_id} plan expired. Access revoked.")
        return True
    conn.close()
    return False


def is_premium_active(user_id: int) -> bool:
    check_and_revoke_if_expired(user_id)
    conn   = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT is_premium FROM users WHERE user_id = %s", (user_id,))
    row    = cursor.fetchone()
    conn.close()
    return bool(row and row['is_premium'])


def get_user_plan_status(user_id: int) -> str:
    check_and_revoke_if_expired(user_id)
    conn   = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT is_premium, current_plan FROM users WHERE user_id = %s", (user_id,))
    row    = cursor.fetchone()
    conn.close()
    if not row or not row['is_premium'] or not row['current_plan']:
        return "No Plan"
    return row['current_plan']

# ═══════════════════════════════════════════════════════════════════════════════
# GATE SETTINGS
# ═══════════════════════════════════════════════════════════════════════════════

def is_gate_enabled(gate_name: str) -> bool:
    try:
        conn   = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT enabled FROM gate_settings WHERE gate_name = %s", (gate_name,))
        row    = cursor.fetchone()
        conn.close()
        if row is None:
            return True
        return bool(row['enabled'])
    except Exception as e:
        logging.error(f"[DB] is_gate_enabled error: {e}")
        return True


def set_gate_enabled(gate_name: str, enabled: bool):
    try:
        conn   = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO gate_settings (gate_name, enabled) VALUES (%s, %s) "
            "ON CONFLICT (gate_name) DO UPDATE SET enabled = EXCLUDED.enabled",
            (gate_name, enabled),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logging.error(f"[DB] set_gate_enabled error: {e}")

# ═══════════════════════════════════════════════════════════════════════════════
# STATS — Shopify / MSH (cc_*)
# ═══════════════════════════════════════════════════════════════════════════════

def update_user_stats(user_id: int, result_type: str):
    """
    Increment Shopify/MSH stats.
    result_type: "charged" | "live" | "dead" | "error"
    Always increments cc_checked.
    """
    col_map = {
        "charged": "cc_charged",
        "live":    "cc_live",
        "dead":    "cc_dead",
    }
    extra_col = col_map.get(result_type)
    try:
        conn   = get_connection()
        cursor = conn.cursor()
        ensure_user(user_id, "Unknown", "User")
        if extra_col:
            cursor.execute(
                f"UPDATE users SET cc_checked = cc_checked + 1, {extra_col} = {extra_col} + 1 "
                f"WHERE user_id = %s",
                (user_id,),
            )
        else:
            cursor.execute(
                "UPDATE users SET cc_checked = cc_checked + 1 WHERE user_id = %s",
                (user_id,),
            )
        conn.commit()
        conn.close()
    except Exception as e:
        logging.error(f"[DB] update_user_stats error: {e}")


def get_user_stats(user_id: int) -> Dict[str, int]:
    """Returns this user's Shopify/MSH checked/charged/live/dead counts."""
    try:
        conn   = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT cc_checked, cc_charged, cc_live, cc_dead FROM users WHERE user_id = %s",
            (user_id,),
        )
        row  = cursor.fetchone()
        conn.close()
        if not row:
            return {"checked": 0, "charged": 0, "live": 0, "dead": 0}
        return {
            "checked": row.get("cc_checked", 0) or 0,
            "charged": row.get("cc_charged", 0) or 0,
            "live":    row.get("cc_live",    0) or 0,
            "dead":    row.get("cc_dead",    0) or 0,
        }
    except Exception as e:
        logging.error(f"[DB] get_user_stats error: {e}")
        return {"checked": 0, "charged": 0, "live": 0, "dead": 0}


def get_global_stats() -> Dict[str, int]:
    """Returns summed Shopify/MSH stats across ALL users."""
    try:
        conn   = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COALESCE(SUM(cc_checked), 0) AS checked, "
            "       COALESCE(SUM(cc_charged), 0) AS charged, "
            "       COALESCE(SUM(cc_live),    0) AS live, "
            "       COALESCE(SUM(cc_dead),    0) AS dead, "
            "       COUNT(*) AS total_users "
            "FROM users"
        )
        row  = cursor.fetchone()
        conn.close()
        if not row:
            return {"checked": 0, "charged": 0, "live": 0, "dead": 0, "total_users": 0}
        return {
            "checked":     int(row.get("checked",     0) or 0),
            "charged":     int(row.get("charged",     0) or 0),
            "live":        int(row.get("live",        0) or 0),
            "dead":        int(row.get("dead",        0) or 0),
            "total_users": int(row.get("total_users", 0) or 0),
        }
    except Exception as e:
        logging.error(f"[DB] get_global_stats error: {e}")
        return {"checked": 0, "charged": 0, "live": 0, "dead": 0, "total_users": 0}

# ═══════════════════════════════════════════════════════════════════════════════
# STATS — Razorpay / MRZ (mrz_*)
# ═══════════════════════════════════════════════════════════════════════════════

def update_mrz_stats(user_id: int, result_type: str):
    """
    Increment Razorpay/MRZ stats.
    result_type: "charged" | "live" | "dead" | "error"
    Always increments mrz_checked.
    """
    col_map = {
        "charged": "mrz_charged",
        "live":    "mrz_live",
        "dead":    "mrz_dead",
    }
    extra_col = col_map.get(result_type)
    try:
        conn   = get_connection()
        cursor = conn.cursor()
        ensure_user(user_id, "Unknown", "User")
        if extra_col:
            cursor.execute(
                f"UPDATE users SET mrz_checked = mrz_checked + 1, {extra_col} = {extra_col} + 1 "
                f"WHERE user_id = %s",
                (user_id,),
            )
        else:
            cursor.execute(
                "UPDATE users SET mrz_checked = mrz_checked + 1 WHERE user_id = %s",
                (user_id,),
            )
        conn.commit()
        conn.close()
    except Exception as e:
        logging.error(f"[DB] update_mrz_stats error: {e}")


def get_mrz_user_stats(user_id: int) -> Dict[str, int]:
    """Returns this user's Razorpay/MRZ checked/charged/live/dead counts."""
    try:
        conn   = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT mrz_checked, mrz_charged, mrz_live, mrz_dead FROM users WHERE user_id = %s",
            (user_id,),
        )
        row  = cursor.fetchone()
        conn.close()
        if not row:
            return {"checked": 0, "charged": 0, "live": 0, "dead": 0}
        return {
            "checked": row.get("mrz_checked", 0) or 0,
            "charged": row.get("mrz_charged", 0) or 0,
            "live":    row.get("mrz_live",    0) or 0,
            "dead":    row.get("mrz_dead",    0) or 0,
        }
    except Exception as e:
        logging.error(f"[DB] get_mrz_user_stats error: {e}")
        return {"checked": 0, "charged": 0, "live": 0, "dead": 0}


def get_mrz_global_stats() -> Dict[str, int]:
    """Returns summed Razorpay/MRZ stats across ALL users."""
    try:
        conn   = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COALESCE(SUM(mrz_checked), 0) AS checked, "
            "       COALESCE(SUM(mrz_charged), 0) AS charged, "
            "       COALESCE(SUM(mrz_live),    0) AS live, "
            "       COALESCE(SUM(mrz_dead),    0) AS dead "
            "FROM users"
        )
        row  = cursor.fetchone()
        conn.close()
        if not row:
            return {"checked": 0, "charged": 0, "live": 0, "dead": 0}
        return {
            "checked": int(row.get("checked", 0) or 0),
            "charged": int(row.get("charged", 0) or 0),
            "live":    int(row.get("live",    0) or 0),
            "dead":    int(row.get("dead",    0) or 0),
        }
    except Exception as e:
        logging.error(f"[DB] get_mrz_global_stats error: {e}")
        return {"checked": 0, "charged": 0, "live": 0, "dead": 0}

# ═══════════════════════════════════════════════════════════════════════════════
# REDEEM CODES
# ═══════════════════════════════════════════════════════════════════════════════

def generate_code_string() -> str:
    p1 = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
    p2 = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
    return f"CX-{p1}-{p2}"


def create_redeem_codes(plan: str, count: int) -> List[str]:
    conn   = get_connection()
    cursor = conn.cursor()
    codes  = []
    for _ in range(count):
        code = generate_code_string()
        cursor.execute("INSERT INTO redeem_codes (code, plan) VALUES (%s, %s)", (code, plan))
        codes.append(code)
    conn.commit()
    conn.close()
    return codes


def claim_redeem_code(user_id: int, code: str) -> Optional[str]:
    conn   = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT plan, used FROM redeem_codes WHERE code = %s", (code,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return "invalid"
    if row['used']:
        conn.close()
        return "already_used"
    plan = row['plan']
    cursor.execute(
        "UPDATE redeem_codes SET used = TRUE, used_by = %s, used_at = %s WHERE code = %s",
        (user_id, datetime.now(), code),
    )
    conn.commit()
    conn.close()
    return plan
