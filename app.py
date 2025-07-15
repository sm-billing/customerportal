from flask import Flask, request, render_template, session, redirect, url_for, flash, send_file, abort
from dotenv import load_dotenv
import os
import mysql.connector
import login as login_module
import dbconn
from transactions import get_all_transactions
from datetime import datetime, timedelta
from librouteros import connect


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

@app.route('/session')
def session_history():
    if 'username' not in session:
        return redirect(url_for('login'))

    username = session['username']
    try:
        conn = get_db_conn()
        cur = conn.cursor(dictionary=True)
        cur.execute("""
            SELECT start_time, end_time, rx_bytes, tx_bytes
            FROM ppp_session
            WHERE name = %s
            ORDER BY end_time DESC
            LIMIT 30
        """, (username,))
        sessions = cur.fetchall()
        cur.close()

        for row in sessions:
            row['rx_mb'] = round(row['rx_bytes'] / 1024**2, 2)
            row['tx_mb'] = round(row['tx_bytes'] / 1024**2, 2)
            row['total_mb'] = round(row['rx_mb'] + row['tx_mb'], 2)
            uptime_seconds = int((row['end_time'] - row['start_time']).total_seconds())
            row['uptime_str'] = str(timedelta(seconds=uptime_seconds))

        return render_template("session_history.html", usage_days=sessions, username=username)

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

    # ✅ FIXED HERE: only unpack one value
    monthly_usage = get_monthly_usage(username)

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
        current_month=current_month
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




def get_monthly_usage(name):
    conn = get_db_conn()
    cur = conn.cursor(dictionary=True)

    # Sum usage from ppp_daily (this month's entries)
    cur.execute("""
        SELECT total
        FROM ppp_daily
        WHERE name = %s
          AND date >= DATE_FORMAT(CURDATE(), '%%Y-%%m-01')
          AND date <= CURDATE()
    """, (name,))
    rows = cur.fetchall()
    cur.close()

    total_mb = 0

    for row in rows:
        if not row['total']:
            continue
        value, unit = row['total'].split()
        mb = float(value) * 1024 if unit.upper() == 'GB' else float(value)
        total_mb += mb

    return f"{total_mb / 1024:.2f} GB" if total_mb >= 1024 else f"{total_mb:.2f} MB"













if __name__ == '__main__':
    app.run(host='0.0.0.0', port=3000, debug=True)
