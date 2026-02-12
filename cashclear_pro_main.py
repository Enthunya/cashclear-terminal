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

# 1. APP CONFIG
st.set_page_config(page_title="CashClear", page_icon="🛡️", layout="centered")

# 2. SECRETS (SECURE FETCHING)
# These values will now be pulled from your Streamlit "Secrets" dashboard
MASTER_ADMIN_PASSWORD = st.secrets["MASTER_ADMIN_PASSWORD"]
MASTER_OVERRIDE_KEY = st.secrets["MASTER_OVERRIDE_KEY"]
PIP_HASH_SALT = st.secrets["PIP_HASH_SALT"]
TWILIO_SID = st.secrets["TWILIO_SID"]
TWILIO_TOKEN = st.secrets["TWILIO_TOKEN"]

TWILIO_WHATSAPP_FROM = "whatsapp:+14155238886"
DB_PATH = "pip_data.db"

# 3. DATABASE & SECURITY
db = sqlite3.connect(DB_PATH, check_same_thread=False)

def hash_pw(pw):
    return hashlib.sha256((pw + PIP_HASH_SALT).encode()).hexdigest()

def init_db():
    db.execute("""CREATE TABLE IF NOT EXISTS accounts (
        account_id TEXT PRIMARY KEY, password TEXT, balance REAL, 
        role TEXT, location TEXT, status TEXT, pin TEXT)""")
    db.execute("""CREATE TABLE IF NOT EXISTS passes (
        phone TEXT, p_code TEXT PRIMARY KEY, status TEXT, 
        amount REAL, issued_at TEXT, expiry TEXT, 
        issuer TEXT, location TEXT)""")
    
    # FORCED ADMIN RESET: Ensures password always matches your Secrets
    admin_pw_hashed = hash_pw(MASTER_ADMIN_PASSWORD)
    db.execute("DELETE FROM accounts WHERE account_id = 'CC-ADMIN'")
    db.execute("""INSERT INTO accounts 
               (account_id, password, balance, role, location, status, pin) 
               VALUES (?, ?, ?, ?, ?, ?, ?)""", 
               ("CC-ADMIN", admin_pw_hashed, 10000.0, 'Admin', 'Benoni HQ', 'Active', '0000'))
    db.commit()

init_db()

# 4. UTILITIES
def generate_qr_b64(data):
    qr = qrcode.QRCode(box_size=10, border=2)
    qr.add_data(data)
    img = qr.make_image(fill_color="#1E3A8A", back_color="white")
    buf = BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()

def send_whatsapp(to_phone, message_body):
    try:
        client = Client(TWILIO_SID, TWILIO_TOKEN)
        client.messages.create(from_=TWILIO_WHATSAPP_FROM, body=message_body, to=f"whatsapp:{to_phone}")
        return True
    except Exception as e:
        st.error(f"WhatsApp Error: {e}")
        return False

# 5. LOGIN SYSTEM
if "auth" not in st.session_state:
    st.session_state.auth = None

if not st.session_state.auth:
    st.title("🛡️ CashClear")
    st.subheader("Secure Operator Terminal")
    
    uid = st.text_input("Operator ID").strip().upper()
    pw = st.text_input("Password", type="password")
    
    if st.button("Unlock Terminal", use_container_width=True):
        if pw == MASTER_OVERRIDE_KEY:
            st.session_state.auth = {"id": "DEV-DEBUG", "role": "Dev", "loc": "Override Access"}
            st.rerun()
        
        user = db.execute("SELECT account_id, role, location FROM accounts WHERE account_id=? AND password=?",
                          (uid, hash_pw(pw))).fetchone()
        if user:
            st.session_state.auth = {"id": user[0], "role": user[1], "loc": user[2]}
            st.rerun()
        else:
            st.error("Access Denied: Check credentials or Streamlit Secrets.")

else:
    # 6. MAIN TERMINAL
    st.title(f"Terminal: {st.session_state.auth['loc']}")
    
    with st.sidebar:
        st.write(f"Operator: **{st.session_state.auth['id']}**")
        bal_res = db.execute("SELECT balance FROM accounts WHERE account_id=?", 
                             (st.session_state.auth["id"],)).fetchone()
        display_bal = bal_res[0] if bal_res else 0.0
        st.metric("Credit Balance", f"R{display_bal:,.2f}")
        
        if st.button("Logout"):
            st.session_state.auth = None
            st.rerun()

    tab1, tab2, tab3 = st.tabs(["🚀 Issue P-Code", "📊 Batch & Lotto", "📜 History"])

    with tab1:
        st.subheader("Send Single Voucher")
        phone = st.text_input("Customer Phone (+27...)")
        amt = st.number_input("Amount (R)", min_value=1.0, value=50.0)
        
        if st.button("Send Voucher via WhatsApp"):
            p_code = f"PIP-{phone[-4:]}-{random.randint(1000,9999)}"
            msg = f"CashClear P-Code: {p_code}\nValue: R{amt}\nLocation: {st.session_state.auth['loc']}"
            
            if send_whatsapp(phone, msg):
                db.execute("INSERT INTO passes VALUES (?,?,?,?,?,?,?,?)", 
                           (phone, p_code, "Active", amt, datetime.now().isoformat(), 
                            (datetime.now() + timedelta(days=30)).isoformat(), 
                            st.session_state.auth["id"], st.session_state.auth["loc"]))
                db.execute("UPDATE accounts SET balance = balance - ? WHERE account_id=?", 
                           (amt, st.session_state.auth["id"]))
                db.commit()
                st.success("Dispatched!")
                st.image(f"data:image/png;base64,{generate_qr_b64(p_code)}")

    with tab2:
        st.subheader("Batch Generation")
        csv_file = st.file_uploader("Upload Phone List", type="csv")
        
        st.divider()
        st.subheader("🎰 Lucky Numbers")
        if st.button("Generate 10 Lotto Boards"):
            boards = [sorted(random.sample(range(1, 37), 5)) for _ in range(10)]
            st.table(pd.DataFrame(boards, columns=["#1", "#2", "#3", "#4", "#5"]))

    with tab3:
        st.subheader("History")
        hist_df = pd.read_sql("SELECT * FROM passes ORDER BY issued_at DESC", db)
        st.dataframe(hist_df)
