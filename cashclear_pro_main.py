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
# 1. APP CONFIG & SECURITY
# -------------------------
st.set_page_config(page_title="CASHCLEAR Pro", page_icon="🛡️", layout="centered")

# Pulling security keys from Streamlit Cloud Secrets
MASTER_ADMIN_PASSWORD = st.secrets.get("MASTER_ADMIN_PASSWORD", "admin123")
MASTER_OVERRIDE_KEY = st.secrets.get("MASTER_OVERRIDE_KEY", "DEV_DEBUG_99")
PIP_HASH_SALT = st.secrets.get("PIP_HASH_SALT", "PIP_SECURE_SALT_2026")

# Twilio Configuration
TWILIO_SID = st.secrets.get("TWILIO_SID", "AC5a42dcce247849417d3648bef1098905")
TWILIO_TOKEN = st.secrets.get("TWILIO_TOKEN", "2e5d560b9ea8101aae7e0b7de8d14e93")
TWILIO_WHATSAPP_FROM = "whatsapp:+14155238886"

# -------------------------
# 2. DATABASE INITIALIZATION
# -------------------------
DB_PATH = "pip_data.db" 
db = sqlite3.connect(DB_PATH, check_same_thread=False)

def init_db():
    db.execute("""CREATE TABLE IF NOT EXISTS accounts (
        account_id TEXT PRIMARY KEY, password TEXT, balance REAL, 
        role TEXT, location TEXT, status TEXT, pin TEXT)""")
    db.execute("""CREATE TABLE IF NOT EXISTS passes (
        phone TEXT, p_code TEXT PRIMARY KEY, status TEXT, 
        amount REAL, issued_at TEXT, expiry TEXT, 
        issuer TEXT, location TEXT)""")
    
    # Create the Admin account with Salted Hashing
    salted_pw = MASTER_ADMIN_PASSWORD + PIP_HASH_SALT
    hashed_pw = hashlib.sha256(salted_pw.encode()).hexdigest()
    
    db.execute("""INSERT OR IGNORE INTO accounts 
               (account_id, password, balance, role, location, status, pin) 
               VALUES (?, ?, ?, ?, ?, ?, ?)""", 
               ("CC-ADMIN", hashed_pw, 10000.0, 'Admin', 'Benoni HQ', 'Active', '0000'))
    db.commit()

init_db()

# -------------------------
# 3. UTILITIES
# -------------------------
def hash_pw(pw: str): 
    return hashlib.sha256((pw + PIP_HASH_SALT).encode()).hexdigest()

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
# 4. LOGIN SYSTEM
# -------------------------
if "auth" not in st.session_state: st.session_state.auth = None

if not st.session_state.auth:
    st.title("🛡️ Operator Login")
    uid = st.text_input("Operator ID").strip().upper()
    pw = st.text_input("Password", type="password")
    
    if st.button("Unlock Terminal", use_container_width=True):
        # 1. Check Master Override first
        if pw == MASTER_OVERRIDE_KEY:
            st.session_state.auth = {"id": "DEV-OVERRIDE", "role": "Dev", "loc": "Override Access"}
            st.rerun()
        
        # 2. Check Database
        user = db.execute("SELECT account_id, role, location FROM accounts WHERE account_id=? AND password=? AND status='Active'",
                          (uid, hash_pw(pw))).fetchone()
        if user:
            st.session_state.auth = {"id": user[0], "role": user[1], "loc": user[2]}
            st.rerun()
        else:
            st.error("Invalid Login. Check Credentials or Streamlit Secrets.")

else:
    # -------------------------
    # 5. MAIN TERMINAL INTERFACE
    # -------------------------
    st.title(f"Terminal: {st.session_state.auth['loc']}")
    
    with st.sidebar:
        st.write(f"Logged in: **{st.session_state.auth['id']}**")
        
        # FIXED: Check if balance exists to prevent TypeError
        bal_res = db.execute("SELECT balance FROM accounts WHERE account_id=?", 
                             (st.session_state.auth["id"],)).fetchone()
        display_bal = bal_res[0] if bal_res else 0.0
        
        st.metric("Credit Balance", f"R{display_bal:,.2f}")
        
        # Backup button for persistence
        try:
            with open(DB_PATH, "rb") as f:
                st.download_button("💾 Backup pip_data.db", f, file_name="pip_data_backup.db")
        except:
            st.warning("Database file not found yet.")
            
        if st.button("Logout"):
            st.session_state.auth = None
            st.rerun()

    tab1, tab2, tab3 = st.tabs(["🚀 Issue P-Code", "📊 Batch & Lotto", "📜 History"])

    with tab1:
        phone = st.text_input("Customer Phone (+27...)")
        amt = st.number_input("Amount (R)", min_value=1.0, value=50.0)
        if st.button("Send Voucher via WhatsApp"):
            p_code = f"PIP-{phone[-4:]}-{random.randint(1000,9999)}"
            msg = f"CASHCLEAR PRO\nYour P-Code: {p_code}\nValue: R{amt}\nValid for 30 Days."
            if send_whatsapp(phone, msg):
                db.execute("INSERT INTO passes VALUES (?,?,?,?,?,?,?,?)", 
                           (phone, p_code, "Active", amt, datetime.now().isoformat(), 
                            (datetime.now() + timedelta(days=30)).isoformat(), 
                            st.session_state.auth["id"], st.session_state.auth["loc"]))
                db.execute("UPDATE accounts SET balance = balance - ? WHERE account_id=?", 
                           (amt, st.session_state.auth["id"]))
                db.commit()
                st.success("Sent Successfully!")
                st.image(f"data:image/png;base64,{generate_qr_b64(p_code)}")

    with tab2:
        st.subheader("Batch P-Code Generation") # [cite: 2026-02-04]
        csv_file = st.file_uploader("Upload CSV Phone List", type="csv")
        if csv_file:
            df = pd.read_csv(csv_file)
            if st.button("Generate All P-Codes"):
                results = [{"Phone": str(p), "Code": f"PIP-{str(p)[-4:]}-{random.randint(1000,9999)}"} for p in df.iloc[:,0]]
                batch_df = pd.DataFrame(results)
                st.dataframe(batch_df)
                st.download_button("Download CSV", batch_df.to_csv(index=False).encode('utf-8'), "batch_results.csv")
        
        st.divider()
        st.subheader("🎰 Lucky Numbers (R30)")
        game = st.radio("Select Game", ["Daily Lotto (10 Boards)", "PowerBall (6 Boards)"])
        if st.button("Generate Numbers"):
            if "Daily" in game:
                boards = [{"Num": sorted(random.sample(range(1, 37), 5))} for _ in range(10)]
            else:
                boards = [{"Num": sorted(random.sample(range(1, 51), 5)), "PB": random.randint(1, 20)} for _ in range(6)]
            st.table(pd.DataFrame(boards))

    with tab3:
        st.subheader("Recent History")
        hist_df = pd.read_sql(f"SELECT * FROM passes ORDER BY issued_at DESC", db)
        st.dataframe(hist_df)
