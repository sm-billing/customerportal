from flask import Flask, request, render_template, session, redirect, url_for, flash, send_file, abort
from dotenv import load_dotenv
import os
import mysql.connector
import login as login_module
import dbconn
from transactions import get_all_transactions
from datetime import datetime
from librouteros import connect
from datetime import datetime

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "fallback_secret_key")  # Secure secret key









########## Unified DB Connection ##########
def get_db_conn():
    return mysql.connector.connect(
        host=os.getenv("DB_HOST"),
        port=int(os.getenv("DB_PORT")),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASS"),
        database=os.getenv("DB_NAME")
    )

########## Router Connection (MikroTik) ##########
def connect_to_router():
    return connect(
        username=os.getenv("ROUTER_USER"),
        password=os.getenv("ROUTER_PASS"),
        host=os.getenv("ROUTER_HOST"),
        port=int(os.getenv("ROUTER_PORT", 8728)),
        plaintext_login=True
    )










########## Session History ##########
@app.route('/usage')
def usage_history():
    if 'username' not in session:
        return redirect(url_for('login'))

    username = session['username']
    try:
        conn = get_db_conn()
        cur = conn.cursor(dictionary=True)
        cur.execute("""
            SELECT day, rx_mb, tx_mb, total_mb
            FROM ppp_usage_daily
            WHERE name = %s
            ORDER BY day DESC
            LIMIT 30
        """, (username,))
        usage_days = cur.fetchall()
        cur.close()

        return render_template("usage.html", usage_days=usage_days, username=username)

    except Exception as e:
        return f"❌ Error: {str(e)}", 500










########## Router Status Page (optional) ##########
@app.route('/router-status')
def router_status():
    if 'username' not in session:
        return redirect(url_for('login'))

    try:
        api = connect_to_router()
        active_ppp = api.path("ppp", "active").get()
        return render_template("router_status.html", ppp_sessions=active_ppp)

    except Exception as e:
        return f"❌ Router Connection Error: {str(e)}", 500









########## Authentication ##########
@app.route('/', methods=['GET', 'POST'])
def login():
    if 'username' in session:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        success, error = login_module.login_function(request, render_template)
        if success:
            session['username'] = username
            return redirect(url_for('dashboard'))
        else:
            flash(error or 'Invalid username or password', 'danger')
    return render_template('login.html')

from datetime import datetime

@app.route('/dashboard')
def dashboard():
    if 'username' not in session:
        return redirect(url_for('login'))
    username = session['username']
    customer = get_customer_info(username)
    package_info = get_package_info(username)
    recharged_on, recharged_time = get_last_recharge(username)
    valid_till, valid_till_status = get_valid_till(username)
    monthly_usage, latest_duration = get_monthly_usage(username)

    current_month = datetime.now().strftime('%B')  # e.g. "July"

    return render_template(
        'dashboard.html',
        customer=customer,
        package_info=package_info,
        recharged_on=recharged_on,
        recharged_time=recharged_time,
        valid_till=valid_till,
        valid_till_status=valid_till_status,
        monthly_usage=monthly_usage,
        latest_duration=latest_duration,
        current_month=current_month  # ✅ pass it to template
    )







@app.route('/transactions')
def transactions():
    if 'username' not in session:
        return redirect(url_for('login'))
    username = session['username']
    customer = get_customer_info(username)
    package_info = get_package_info(username)
    txns = get_all_transactions(username)
    valid_till = get_valid_till(username)
    return render_template(
        'transactions.html',
        transactions=txns,
        customer=customer,
        package_info=package_info,
        valid_till=valid_till
    )

@app.route('/about')
def about():
    return render_template('about.html')

@app.route('/logout')
def logout():
    session.pop('username', None)
    flash('You have been logged out.', 'success')
    return redirect(url_for('login'))







########## Supporting Functions ##########
def get_customer_info(username):
    conn = dbconn.get_db_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT fullname, username, balance, email, address, phonenumber FROM tbl_customers WHERE username=%s", (username,))
    customer = cur.fetchone()
    cur.close()
    return customer

def get_package_info(username):
    conn = dbconn.get_db_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute("""
        SELECT namebp, status, routers, method
        FROM tbl_user_recharges
        WHERE username = %s AND status IN ('on', 'off')
        ORDER BY recharged_on DESC, recharged_time DESC
        LIMIT 1
    """, (username,))
    package = cur.fetchone()
    cur.close()
    return package

def get_last_recharge(username):
    conn = dbconn.get_db_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute("""
        SELECT recharged_on, recharged_time
        FROM tbl_user_recharges
        WHERE username=%s
        ORDER BY recharged_on DESC, recharged_time DESC LIMIT 1
    """, (username,))
    row = cur.fetchone()
    cur.close()
    if row:
        return row['recharged_on'], row['recharged_time']
    return None, None

def get_valid_till(username):
    conn = dbconn.get_db_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute("""
        SELECT expiration, time
        FROM tbl_user_recharges
        WHERE username=%s AND status='on'
        ORDER BY expiration DESC, time DESC LIMIT 1
    """, (username,))
    row = cur.fetchone()
    cur.close()
    if row and row['expiration'] and row['time']:
        valid_till_str = f"{row['expiration']} {row['time']}"
        try:
            valid_till = datetime.strptime(valid_till_str, '%Y-%m-%d %H:%M:%S')
        except ValueError:
            valid_till = datetime.strptime(valid_till_str, '%Y-%m-%d %H:%M')
        now = datetime.now()
        status = 'active' if valid_till >= now else 'expired'
        return valid_till_str, status
    return None, 'expired'


def get_monthly_usage(username):
    conn = get_db_conn()
    cur = conn.cursor(dictionary=True)

    # 1. Get monthly total from daily summary table
    cur.execute("""
        SELECT SUM(rx_mb) AS total_rx, SUM(tx_mb) AS total_tx
        FROM ppp_usage_daily
        WHERE name = %s AND MONTH(day) = MONTH(CURDATE()) AND YEAR(day) = YEAR(CURDATE())
    """, (username,))
    row = cur.fetchone()
    total_mb = (row['total_rx'] or 0) + (row['total_tx'] or 0)
    formatted_usage = f"{total_mb / 1024:.2f} GB" if total_mb >= 1024 else f"{total_mb:.2f} MB"

    # 2. Get latest session's duration
    cur.execute("""
        SELECT duration_min
        FROM ppp_usage_session
        WHERE name = %s
        ORDER BY end_time DESC
        LIMIT 1
    """, (username,))
    row2 = cur.fetchone()
    latest_duration = row2['duration_min'] if row2 else 0

    cur.close()
    return formatted_usage, latest_duration












if __name__ == '__main__':
    app.run(host='0.0.0.0', port=3000, debug=True)
