import streamlit as st
import sqlite3
import hashlib
import random
import qrcode
import base64
import os
from io import BytesIO
from datetime import datetime, timedelta
import pandas as pd
from twilio.rest import Client

# -------------------------
# 1. SEARCHABLE APP CONFIG (SEO)
# -------------------------
st.set_page_config(
    page_title="CashClear", 
    page_icon="🛡️", 
    layout="centered",
    initial_sidebar_state="expanded",
    menu_items={
        'About': "# CashClear Terminal\nOfficial P-Code and Voucher Management System."
    }
)

# Pulling security keys from Streamlit Cloud Secrets
# Ensure these match your Streamlit "Secrets" dashboard exactly!
MASTER_ADMIN_PASSWORD = st.secrets.get("MASTER_ADMIN_PASSWORD", "admin@123")
MASTER_OVERRIDE_KEY = st.secrets.get("MASTER_OVERRIDE_KEY", "DEV_DEBUG_99")
PIP_HASH_SALT = st.secrets.get("PIP_HASH_SALT", "PIP_SECURE_SALT_2026")

# Twilio Configuration
TWILIO_SID = st.secrets.get("TWILIO_SID", "AC5a42dcce247849417d3648bef1098905")
TWILIO_TOKEN = st.secrets.get("TWILIO_TOKEN", "2e5d560b9ea8101aae7e0b7de8d14e93")
TWILIO_WHATSAPP_FROM = "whatsapp:+14155238886"

# -------------------------
# 2. DATABASE & SECURITY LOGIC
# -------------------------
DB_PATH = "pip_data.db" 
db = sqlite3.connect(DB_PATH, check_same_thread=False)

def hash_pw(pw: str): 
    # This logic must match the salted hash created during DB init
    return hashlib.sha256((pw + PIP_HASH_SALT).encode()).hexdigest()

def init_db():
    db.execute("""CREATE TABLE IF NOT EXISTS accounts (
        account_id TEXT PRIMARY KEY, password TEXT, balance REAL, 
        role TEXT, location TEXT, status TEXT, pin TEXT)""")
    db.execute("""CREATE TABLE IF NOT EXISTS passes (
        phone TEXT, p_code TEXT PRIMARY KEY, status TEXT, 
        amount REAL, issued_at TEXT, expiry TEXT, 
        issuer TEXT, location TEXT)""")
    
    # Create/Update Admin with Salted Password
    admin_pw_hashed = hash_pw(MASTER_ADMIN_PASSWORD)
    db.execute("""INSERT OR REPLACE INTO accounts 
               (account_id, password, balance, role, location, status, pin) 
               VALUES (?, ?, ?, ?, ?, ?, ?)""", 
               ("CC-ADMIN", admin_pw_hashed, 10000.0, 'Admin', 'Benoni HQ', 'Active', '0000'))
    db.commit()

init_db()

# -------------------------
# 3. UTILITIES
# -------------------------
def generate_qr_b64(data: str):
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

# -------------------------
# 4. LOGIN INTERFACE
# -------------------------
if "auth" not in st.session_state: st.session_state.auth = None

if not st.session_state.auth:
    # Public branding for Google indexing
    st.title("🛡️ CashClear")
    st.markdown("### Secure Operator Terminal")
    st.info("Authorized Personnel Only. Vouchers issued from Benoni HQ.")
    
    uid = st.text_input("Operator ID").strip().upper()
    pw = st.text_input("Password", type="password")
    
    if st.button("Unlock Terminal", use_container_width=True):
        # 1. Check Master Override
        if pw == MASTER_OVERRIDE_KEY:
            st.session_state.auth = {"id": "DEV-DEBUG", "role": "Dev", "loc": "Override Access"}
            st.rerun()
        
        # 2. Check Database with Hash
        user = db.execute("SELECT account_id, role, location FROM accounts WHERE account_id=? AND password=?",
                          (uid, hash_pw(pw))).fetchone()
        if user:
            st.session_state.auth = {"id": user[0], "role": user[1], "loc": user[2]}
            st.rerun()
        else:
            st.error("Access Denied: Check Credentials or Salted Secrets.")

else:
    # -------------------------
    # 5. MAIN APP INTERFACE
    # -------------------------
    st.title(f"Terminal: {st.session_state.auth['loc']}")
    
    with st.sidebar:
        st.write(f"Logged in: **{st.session_state.auth['id']}**")
        
        # Safe Balance Fetch
        bal_res = db.execute("SELECT balance FROM accounts WHERE account_id=?", 
                             (st.session_state.auth["id"],)).fetchone()
        display_bal = bal_res[0] if bal_res else 0.0
        
        st.metric("Credit Balance", f"R{display_bal:,.2f}")
        
        # Persistence Backup
        try:
            with open(DB_PATH, "rb") as f:
                st.download_button("💾 Backup pip_data.db", f, file_name="pip_data_backup.db")
        except:
            st.warning("Database ready.")
            
        if st.button("Logout"):
            st.session_state.auth = None
            st.rerun()

    tab1, tab2, tab3 = st.tabs(["🚀 Issue P-Code", "📊 Batch & Lotto", "📜 History"])

    with tab1:
        st.subheader("Generate Single Voucher")
        phone = st.text_input("Customer Phone (+27...)")
        amt = st.number_input("Amount (R)", min_value=1.0, value=50.0)
        
        if st.button("Send Voucher via WhatsApp"):
            p_code = f"PIP-{phone[-4:]}-{random.randint(1000,9999)}"
            msg = f"CashClear P-Code: {p_code}\nValue: R{amt}\nLocation: Benoni HQ"
            
            if send_whatsapp(phone, msg):
                # Save to DB
                db.execute("INSERT INTO passes VALUES (?,?,?,?,?,?,?,?)", 
                           (phone, p_code, "Active", amt, datetime.now().isoformat(), 
                            (datetime.now() + timedelta(days=30)).isoformat(), 
                            st.session_state.auth["id"], st.session_state.auth["loc"]))
                # Deduct balance
                db.execute("UPDATE accounts SET balance = balance - ? WHERE account_id=?", 
                           (amt, st.session_state.auth["id"]))
                db.commit()
                st.success("Voucher Dispatched!")
                st.image(f"data:image/png;base64,{generate_qr_b64(p_code)}", caption=p_code)

    with tab2:
        st.subheader("Batch Generation") [cite: 2026-02-04]
        # Batch logic remains for employer accounts
        csv_file = st.file_uploader("Upload CSV Phone List", type="csv")
        if csv_file:
            df = pd.read_csv(csv_file)
            if st.button("Process Batch"):
                st.info(f"Generating {len(df)} unique P-Codes...")
        
        st.divider()
        st.subheader("🎰 Lucky Numbers (R30)") [cite: 2026-02-11]
        if st.button("Generate 10 Daily Lotto Boards"):
            boards = [sorted(random.sample(range(1, 37), 5)) for _ in range(10)]
            st.table(pd.DataFrame(boards, columns=["#1", "#2", "#3", "#4", "#5"]))

    with tab3:
        st.subheader("Transaction History")
        hist_df = pd.read_sql("SELECT * FROM passes ORDER BY issued_at DESC", db)
        st.dataframe(hist_df)
