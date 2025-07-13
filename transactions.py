from dbconn import get_db_connection

from datetime import datetime

def get_all_transactions(username):
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT 
                invoice,
                plan_name,
                price,
                recharged_on,
                recharged_time,
                method
            FROM tbl_transactions
            WHERE username=%s AND recharged_on LIKE '2025%%'
            ORDER BY recharged_on DESC, recharged_time DESC
        """, (username,))
        transactions = cursor.fetchall()
        # Ensure all values are JSON serializable
        for txn in transactions:
            for k, v in txn.items():
                if isinstance(v, (datetime,)):
                    txn[k] = v.strftime('%Y-%m-%d %H:%M:%S')
                elif hasattr(v, 'total_seconds'):
                    txn[k] = str(v)
        cursor.close()
        conn.close()
        return transactions
    except Exception:
        return []
