import streamlit as st
import sqlite3
import hashlib
import random
import qrcode
import base64
from io import BytesIO
from datetime import datetime, timedelta
import pandas as pd
from twilio.rest import Client

# 1. APP CONFIGURATION (Makes it searchable in the browser)
st.set_page_config(
    page_title="CashClear Terminal", 
    page_icon="🛡️", 
    layout="centered"
)

# 2. SECURE CREDENTIALS (Fetched from your Streamlit "Vault")
try:
    ADMIN_PW = st.secrets["MASTER_ADMIN_PASSWORD"]
    DEBUG_KEY = st.secrets["MASTER_OVERRIDE_KEY"]
    SALT = st.secrets["PIP_HASH_SALT"]
    T_SID = st.secrets["TWILIO_SID"]
    T_TOKEN = st.secrets["TWILIO_TOKEN"]
except Exception as e:
    st.error("Configuration Missing: Please ensure Streamlit Secrets are set.")
    st.stop()

TWILIO_WHATSAPP_FROM = "whatsapp:+14155238886"
DB_PATH = "pip_data.db"

# 3. DATABASE ENGINE & SECURITY
db = sqlite3.connect(DB_PATH, check_same_thread=False)

def secure_hash(text):
    return hashlib.sha256((text + SALT).encode()).hexdigest()

def init_db():
    # Create tables
    db.execute("""CREATE TABLE IF NOT EXISTS accounts (
        account_id TEXT PRIMARY KEY, password TEXT, balance REAL, 
        role TEXT, location TEXT, status TEXT)""")
    db.execute("""CREATE TABLE IF NOT EXISTS passes (
        phone TEXT, p_code TEXT PRIMARY KEY, status TEXT, 
        amount REAL, issued_at TEXT, expiry TEXT, 
        issuer TEXT, location TEXT)""")
    
    # GLOBAL FIX: Always refresh Admin to match Secrets
    admin_hashed = secure_hash(ADMIN_PW)
    db.execute("DELETE FROM accounts WHERE account_id = 'CC-ADMIN'")
    db.execute("""INSERT INTO accounts 
               (account_id, password, balance, role, location, status) 
               VALUES (?, ?, ?, ?, ?, ?)""", 
               ("CC-ADMIN", admin_hashed, 10000.0, 'Admin', 'Benoni HQ', 'Active'))
    db.commit()

init_db()

# 4. CORE UTILITIES
def generate_qr(data):
    qr = qrcode.QRCode(box_size=10, border=2)
    qr.add_data(data)
    img = qr.make_image(fill_color="#1E3A8A", back_color="white")
    buf = BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()

def send_pcode_whatsapp(phone, p_code, amount, location):
    try:
        client = Client(T_SID, T_TOKEN)
        body = f"🛡️ *CashClear Voucher*\n\nCode: {p_code}\nValue: R{amount}\nLocation: {location}\nValid for 30 days."
        client.messages.create(from_=TWILIO_WHATSAPP_FROM, body=body, to=f"whatsapp:{phone}")
        return True
    except Exception as e:
        st.error(f"Twilio Error: {e}")
        return False

# 5. AUTHENTICATION INTERFACE
if "auth" not in st.session_state:
    st.session_state.auth = None

if not st.session_state.auth:
    st.title("🛡️ CashClear")
    st.markdown("### Secure Terminal Login")
    
    user_id = st.text_input("Operator ID").strip().upper()
    password = st.text_input("Password", type="password")
    
    if st.button("Unlock System", use_container_width=True):
        # Check Master Debug Override
        if password == DEBUG_KEY:
            st.session_state.auth = {"id": "DEV-DEBUG", "role": "Dev", "loc": "Remote"}
            st.rerun()
        
        # Check Database Credentials
        user = db.execute("SELECT account_id, role, location FROM accounts WHERE account_id=? AND password=?",
                          (user_id, secure_hash(password))).fetchone()
        if user:
            st.session_state.auth = {"id": user[0], "role": user[1], "loc": user[2]}
            st.rerun()
        else:
            st.error("Invalid Credentials. Please check your ID and Password.")

else:
    # 6. MAIN OPERATOR DASHBOARD
    st.title(f"📍 {st.session_state.auth['loc']}")
    
    with st.sidebar:
        st.header("Account Info")
        st.write(f"User: **{st.session_state.auth['id']}**")
        bal = db.execute("SELECT balance FROM accounts WHERE account_id=?", (st.session_state.auth["id"],)).fetchone()
        st.metric("Available Credit", f"R{bal[0] if bal else 0:,.2f}")
        
        if st.button("Logout"):
            st.session_state.auth = None
            st.rerun()

    tab1, tab2, tab3 = st.tabs(["💎 Single Issue", "📦 Batch Generation", "📋 Logs"])

    with tab1:
        st.subheader("Issue Individual P-Code")
        c_phone = st.text_input("Customer Phone (e.g., +27123456789)")
        c_amount = st.number_input("Voucher Amount (R)", min_value=10.0, step=10.0)
        
        if st.button("Generate & Send"):
            if c_phone:
                new_pcode = f"CC-{random.randint(100,999)}-{random.randint(1000,9999)}"
                if send_pcode_whatsapp(c_phone, new_pcode, c_amount, st.session_state.auth['loc']):
                    db.execute("INSERT INTO passes VALUES (?,?,?,?,?,?,?,?)", 
                               (c_phone, new_pcode, "Active", c_amount, datetime.now().isoformat(), 
                                (datetime.now() + timedelta(days=30)).isoformat(), 
                                st.session_state.auth["id"], st.session_state.auth["loc"]))
                    db.execute("UPDATE accounts SET balance = balance - ? WHERE account_id=?", 
                               (c_amount, st.session_state.auth["id"]))
                    db.commit()
                    st.success(f"Voucher {new_pcode} sent to {c_phone}")
                    st.image(f"data:image/png;base64,{generate_qr(new_pcode)}", caption="Scan to Redeem")
            else:
                st.warning("Please enter a phone number.")

    with tab2:
        st.subheader("Employer Batch Tools")
        st.info("Upload a CSV file with a 'phone' column to issue multiple P-Codes.")
        uploaded_file = st.file_uploader("Choose CSV", type="csv")
        batch_amt = st.number_input("Amount per P-Code (R)", min_value=10.0, key="batch_val")
        
        if uploaded_file and st.button("Run Batch Process"):
            df = pd.read_csv(uploaded_file)
            if 'phone' in df.columns:
                count = 0
                for phone in df['phone']:
                    pcode = f"CC-B-{random.randint(1000,9999)}"
                    # In a real batch, you might skip WhatsApp to avoid Twilio rate limits, 
                    # but here we log it to the DB.
                    db.execute("INSERT INTO passes VALUES (?,?,?,?,?,?,?,?)", 
                               (str(phone), pcode, "Active", batch_amt, datetime.now().isoformat(), 
                                (datetime.now() + timedelta(days=30)).isoformat(), 
                                st.session_state.auth["id"], st.session_state.auth["loc"]))
                    count += 1
                db.execute("UPDATE accounts SET balance = balance - ? WHERE account_id=?", 
                           (batch_amt * count, st.session_state.auth["id"]))
                db.commit()
                st.success(f"Processed {count} unique P-Codes successfully.")
            else:
                st.error("CSV must contain a column named 'phone'.")

    with tab3:
        st.subheader("Transaction History")
        history = pd.read_sql("SELECT phone, p_code, amount, status, issued_at FROM passes", db)
        st.dataframe(history, use_container_width=True)
