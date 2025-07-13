import mysql.connector
from dotenv import load_dotenv
import os
from datetime import datetime

load_dotenv()

def get_db_conn():
    return mysql.connector.connect(
        host=os.getenv("DB_HOST"),
        port=int(os.getenv("DB_PORT")),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASS"),
        database=os.getenv("DB_NAME")
    )

def log(message):
    log_path = os.path.join(os.path.dirname(__file__), "update_daily_usage.log")
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(log_path, "a") as f:
        f.write(f"[{timestamp}] {message}\n")

def update_daily_usage():
    try:
        conn = get_db_conn()
        cur = conn.cursor()

        cur.execute("""
            SELECT 
                name,
                DATE(start_time) AS day,
                SUM(rx_byte) / (1024 * 1024) AS rx_mb,
                SUM(tx_byte) / (1024 * 1024) AS tx_mb,
                (SUM(rx_byte) + SUM(tx_byte)) / (1024 * 1024) AS total_mb
            FROM ppp_usage_session
            GROUP BY name, day
        """)

        usage_rows = cur.fetchall()

        updated = 0
        for name, day, rx_mb, tx_mb, total_mb in usage_rows:
            cur.execute("""
                INSERT INTO ppp_usage_daily (name, day, rx_mb, tx_mb, total_mb)
                VALUES (%s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    rx_mb = VALUES(rx_mb),
                    tx_mb = VALUES(tx_mb),
                    total_mb = VALUES(total_mb)
            """, (name, day, rx_mb, tx_mb, total_mb))
            updated += 1

        conn.commit()
        cur.close()
        conn.close()
        log(f"✅ Updated {updated} row(s) in ppp_usage_daily.")
    except Exception as e:
        log(f"❌ Error: {str(e)}")

if __name__ == '__main__':
    update_daily_usage()