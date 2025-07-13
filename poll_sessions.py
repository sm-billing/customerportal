#!/usr/bin/env python3

import os
import datetime
import logging
from librouteros import connect
import mysql.connector
from dotenv import load_dotenv

# Load environment
load_dotenv(dotenv_path="./.env")

# Setup logging
log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "poll_sessions.log")
logging.basicConfig(
    filename=log_path,
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s: %(message)s'
)

def get_db_conn():
    return mysql.connector.connect(
        host=os.getenv("DB_HOST"),
        port=int(os.getenv("DB_PORT")),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASS"),
        database=os.getenv("DB_NAME")
    )

def connect_router():
    return connect(
        host=os.getenv("ROUTER_IP"),
        username=os.getenv("ROUTER_USERNAME"),
        password=os.getenv("ROUTER_PASSWORD"),
        port=int(os.getenv("ROUTER_PORT"))
    )

def main():
    now = datetime.datetime.now()

    try:
        api = connect_router()
        interfaces = api.path("interface")

        conn = get_db_conn()
        cursor = conn.cursor(dictionary=True)

        for iface in interfaces:
            try:
                name = iface.get("name", "")
                if not name.startswith("<pppoe-") or iface.get("rx-byte") is None:
                    continue

                username = name.replace("<pppoe-", "").replace(">", "")
                rx = int(iface.get("rx-byte", 0))
                tx = int(iface.get("tx-byte", 0))
                link_time = iface.get("last-link-up-time")

                if not link_time:
                    continue

                if isinstance(link_time, str):
                    try:
                        link_time = datetime.datetime.fromisoformat(link_time)
                    except Exception as e:
                        logging.warning(f"⚠️ Invalid time for {username}: {e}")
                        continue

                duration_min = int((now - link_time).total_seconds() / 60)
                if duration_min < 0:
                    duration_min = 0

                # Check for existing session
                cursor.execute("""
                    SELECT id FROM ppp_usage_session
                    WHERE name = %s AND start_time = %s
                """, (username, link_time))
                session = cursor.fetchone()

                if session:
                    cursor.execute("""
                        UPDATE ppp_usage_session
                        SET end_time = %s,
                            rx_byte = %s,
                            tx_byte = %s,
                            duration_min = %s
                        WHERE id = %s
                    """, (now, rx, tx, duration_min, session['id']))
                else:
                    cursor.execute("""
                        INSERT INTO ppp_usage_session
                        (name, start_time, end_time, rx_byte, tx_byte, duration_min)
                        VALUES (%s, %s, %s, %s, %s, %s)
                    """, (username, link_time, now, rx, tx, duration_min))

                # Keep last 24 sessions per user
                cursor.execute("""
                    DELETE FROM ppp_usage_session
                    WHERE id NOT IN (
                        SELECT id FROM (
                            SELECT id FROM ppp_usage_session
                            WHERE name = %s
                            ORDER BY end_time DESC
                            LIMIT 24
                        ) AS recent
                    ) AND name = %s
                """, (username, username))

                # Update raw snapshot
                cursor.execute("""
                    REPLACE INTO ppp_usage_raw
                    (name, rx_byte, tx_byte, last_link_up_time, last_polled_at)
                    VALUES (%s, %s, %s, %s, %s)
                """, (username, rx, tx, link_time, now))

            except Exception as user_error:
                logging.error(f"❌ Error processing {iface.get('name')}: {user_error}")

        conn.commit()
        cursor.close()
        conn.close()
        logging.info("✅ Session poll complete.")

    except Exception as e:
        logging.error(f"❌ Fatal error: {e}")

    try:
        api._conn.close()
    except:
        pass

if __name__ == "__main__":
    main()
