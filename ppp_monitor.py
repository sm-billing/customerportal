#!/usr/bin/env python3
"""
ppp_monitor.py

Objective:
1. Overwrite ppp_raw with latest RouterOS interface data (no math).
2. Insert or update ppp_session based on last-link-up-time.
   - If same as existing session start_time: update rx/tx and end_time.
   - Else: insert new session.
   - Store uptime = (end_time - start_time).seconds
   - Keep only last 24 sessions per user.
3. Update ppp_daily by summing rx+tx for sessions ending today.
"""

import os
import datetime
import logging

from dotenv import load_dotenv
from librouteros import connect
import mysql.connector

# ─── SETUP ─────────────────────────────────────────────────────────────────────
HERE = os.path.dirname(__file__)
load_dotenv(os.path.join(HERE, ".env"))

logging.basicConfig(
    filename=os.path.join(HERE, "ppp_monitor.log"),
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s: %(message)s'
)

def get_db_conn():
    return mysql.connector.connect(
        host=os.getenv("DB_HOST"),
        port=int(os.getenv("DB_PORT", 3306)),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASS"),
        database=os.getenv("DB_NAME")
    )

def connect_router():
    return connect(
        host=os.getenv("ROUTER_IP"),
        username=os.getenv("ROUTER_USERNAME"),
        password=os.getenv("ROUTER_PASSWORD"),
        port=int(os.getenv("ROUTER_PORT", 8728))
    )

def human_readable_mb(bytes_val):
    mb = bytes_val / 1024**2
    return f"{round(mb / 1024, 2)} GB" if mb >= 1024 else f"{round(mb, 2)} MB"

def update_daily_usage(cur):
    today = datetime.date.today()
    now = datetime.datetime.now()

    cur.execute("""
        SELECT name, DATE(end_time) AS day,
               SUM(rx_bytes + tx_bytes) AS total_bytes
        FROM ppp_session
        WHERE DATE(end_time) = %s
        GROUP BY name, day
    """, (today,))

    rows = cur.fetchall()

    for row in rows:
        readable_total = human_readable_mb(row["total_bytes"])
        cur.execute("""
            INSERT INTO ppp_daily (name, date, total, updated_at)
            VALUES (%s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
              total = VALUES(total),
              updated_at = VALUES(updated_at)
        """, (row["name"], row["day"], readable_total, now))

def main():
    now = datetime.datetime.now()
    api  = connect_router()
    conn = get_db_conn()
    cur  = conn.cursor(dictionary=True)

    raws = api.path("interface").select("name", "rx-byte", "tx-byte", "last-link-up-time")

    for iface in raws:
        name = iface.get("name", "")
        if not name.startswith("<pppoe-") or iface.get("rx-byte") is None:
            continue

        user   = name.replace("<pppoe-", "").rstrip(">")
        rx     = int(iface.get("rx-byte", 0))
        tx     = int(iface.get("tx-byte", 0))
        linkup = iface.get("last-link-up-time")
        if not linkup:
            continue

        # Parse RouterOS link-up time
        try:
            if isinstance(linkup, str):
                linkup = datetime.datetime.fromisoformat(linkup)
        except ValueError:
            logging.warning(f"Invalid link-up time for {user}: {linkup}")
            continue

        uptime = int((now - linkup).total_seconds())

        # ─── Step 1: Update ppp_raw ─────────────────────────────────────────────
        cur.execute("""
            REPLACE INTO ppp_raw (name, rx_bytes, tx_bytes, last_link_up_time, measured_at)
            VALUES (%s, %s, %s, %s, %s)
        """, (user, rx, tx, linkup, now))

        # ─── Step 2: Manage ppp_session ─────────────────────────────────────────
        cur.execute("""
            SELECT id FROM ppp_session
            WHERE name = %s AND start_time = %s
            ORDER BY id DESC LIMIT 1
        """, (user, linkup))
        session = cur.fetchone()

        if session:
            # Update existing session
            cur.execute("""
                UPDATE ppp_session
                SET rx_bytes = %s,
                    tx_bytes = %s,
                    end_time = %s,
                    uptime = %s
                WHERE id = %s
            """, (rx, tx, now, uptime, session['id']))
        else:
            # Insert new session
            cur.execute("""
                INSERT INTO ppp_session (name, rx_bytes, tx_bytes, start_time, end_time, uptime)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (user, rx, tx, linkup, now, uptime))

        # ─── Step 3: Keep only last 24 sessions per user ────────────────────────
        cur.execute("""
            DELETE FROM ppp_session
            WHERE name = %s AND id NOT IN (
                SELECT id FROM (
                    SELECT id FROM ppp_session
                    WHERE name = %s
                    ORDER BY start_time DESC
                    LIMIT 24
                ) AS keep_ids
            )
        """, (user, user))

    # ─── Step 4: Update Daily Usage Summary ────────────────────────────────────
    update_daily_usage(cur)

    conn.commit()
    conn.close()
    logging.info("✅ Completed ppp_raw, ppp_session, and ppp_daily updates.")

if __name__ == "__main__":
    main()
