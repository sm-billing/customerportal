
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





######################################################## Authentication ###############################################################
#######################################################################################################################################

# ------------------------------------------- @app.route('/') ------------------------------------------------ #

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
            flash("Login successful!", "success")
            return redirect(url_for('dashboard'))
        else:
            flash(error or 'Login failed. Invalid username or password.', 'danger')
            return redirect(url_for('login'))
    return render_template('login.html')

    


# ------------------------------------------- @app.route('/router-status') ------------------------------------------------ #

@app.route('/router-status')
def router_status():
    if 'username' not in session:
        return redirect(url_for('login'))

    try:
        api = connect_to_router()
        active_ppp = api.path("ppp", "active").get()
        return render_template("router_status.html", ppp_sessions=active_ppp)

    except Exception as e:
        return f"Router Connection Error: {str(e)}", 500


# ------------------------------------------- @app.route('/session') ------------------------------------------------ #

@app.route('/session')
def session_history():
    if 'username' not in session:
        return redirect(url_for('login'))

    username = session['username']
    customer = get_customer_info(username)
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

        return render_template("session_history.html", usage_days=sessions, username=username, customer=customer)

    except Exception as e:
        return f"Error: {str(e)}", 500




# ------------------------------------------- @app.route('/dashboard') ------------------------------------------------ #

@app.route('/dashboard')
def dashboard():
    if 'username' not in session:
        return redirect(url_for('login'))
    username = session['username']
    customer = get_customer_info(username)
    package_info = get_package_info(username)
    recharged_on, recharged_time = get_last_recharge(username)
    valid_till, valid_till_status = get_valid_till(username)

    # FIXED HERE: only unpack one value
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


# ------------------------------------------- @app.route('/profile') ------------------------------------------------ #

@app.route('/profile', methods=['GET', 'POST'])
def profile():
    if 'username' not in session:
        return redirect(url_for('login'))

    username = session['username']
    conn = get_db_conn()
    cur = conn.cursor(dictionary=True)

    if request.method == 'POST':
        fullname = request.form.get('fullname')
        email = request.form.get('email')
        address = request.form.get('address')
        file = request.files.get('profile_image')

        # Basic validation
        if not fullname or not email:
            flash("Full name and email are required.", "danger")
            return redirect(url_for('profile'))

        # Update customer info
        cur.execute("""
            UPDATE tbl_customers
            SET fullname=%s, email=%s, address=%s
            WHERE username=%s
        """, (fullname, email, address, username))

        # Handle image upload and update ppp_image
        if file and file.filename:
            ext = os.path.splitext(file.filename)[1].lower()
            profile_image = f"{username}{ext}"
            filepath = os.path.join('static/profile_pics', profile_image)
            file.save(filepath)

            cur.execute("""
                INSERT INTO ppp_image (username, filename, uploaded_at)
                VALUES (%s, %s, NOW())
                ON DUPLICATE KEY UPDATE
                    filename = VALUES(filename),
                    uploaded_at = VALUES(uploaded_at)
            """, (username, profile_image))

        conn.commit()
        flash("Profile updated successfully!", "success")
        return redirect(url_for('profile'))

    # GET method: fetch user data + image
    cur.execute("""
        SELECT c.*, i.filename AS profile_image
        FROM tbl_customers c
        LEFT JOIN ppp_image i ON c.username = i.username
        WHERE c.username = %s
    """, (username,))
    customer = cur.fetchone()
    cur.close()
    return render_template('profile.html', customer=customer)




# ------------------------------------------- @app.route('/transactions') ------------------------------------------------ #

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


# ------------------------------------------- @app.route('/about') ------------------------------------------------ #

@app.route('/about')
def about():
    if 'username' not in session:
        return redirect(url_for('login'))
    username = session['username']
    customer = get_customer_info(username)
    return render_template('about.html', username=username, customer=customer)


# ------------------------------------------- @app.route('/logout') ------------------------------------------------ #

@app.route('/logout')
def logout():
    session.pop('username', None)
    flash('You have been logged out.', 'success')
    return redirect(url_for('login'))







############################################################# Supporting Functions ###########################################################
##############################################################################################################################################

# ---------------------------------------------------------------- get_customer_info(username) ----------------------------------------------------- #

def get_customer_info(username):
    conn = dbconn.get_db_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute("""
        SELECT c.fullname, c.username, c.balance, c.email, c.address, c.phonenumber,
               i.filename AS profile_image
        FROM tbl_customers c
        LEFT JOIN ppp_image i ON c.username = i.username
        WHERE c.username = %s
    """, (username,))
    customer = cur.fetchone()
    cur.close()
    return customer


# ---------------------------------------------------------------- get_package_info(username) ----------------------------------------------------- #

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


# ---------------------------------------------------------------- get_last_recharge(username) ----------------------------------------------------- #

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


# ---------------------------------------------------------------- get_valid_till(username) ----------------------------------------------------- #

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



# ------------------------------------------------------------------ get_monthly_usage(username) ----------------------------------------------------- #

def get_monthly_usage(name):
    from datetime import datetime
    conn = get_db_conn()
    cur = conn.cursor(dictionary=True)
    month_str = datetime.now().strftime('%Y-%m')  # e.g. '2024-08'

    cur.execute("""
        SELECT total_bytes FROM ppp_monthly
        WHERE name = %s AND month = %s
    """, (name, month_str))

    row = cur.fetchone()
    cur.close()

    if row and row['total_bytes'] is not None:
        total_gb = row['total_bytes'] / 1024 / 1024 / 1024
        return f"{total_gb:.2f} GB"
    return "0.00 GB"



# ------------------------------------------- Run Flask App ------------------------------------------------ #

if __name__ == '__main__':
    app.run(host='0.0.0.0', port= 3000, debug=False)