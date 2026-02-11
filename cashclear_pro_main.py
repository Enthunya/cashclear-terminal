import streamlit as st
import sqlite3
import hashlib
import random
import qrcode
import base64
import cv2
import numpy as np
import os
from io import BytesIO
from datetime import datetime, timedelta
import pandas as pd

# -------------------------
# 0. PWA INJECTION (Critical for Option B)
# -------------------------
st.markdown("""
<link rel="manifest" href="/static/manifest.json">
<meta name="theme-color" content="#1E3A8A">
<script>
if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('/static/service-worker.js');
}
</script>
""", unsafe_allow_html=True)

# -------------------------
# 1. PAGE CONFIG
# -------------------------
st.set_page_config(
    page_title="CASHCLEAR Terminal", 
    page_icon="🛡️", 
    layout="centered",  # Optimized for Mobile
    initial_sidebar_state="collapsed"
)

# Custom Mobile-First CSS
st.markdown("""
<style>
    .stButton > button { height: 3.5em; border-radius:15px; font-weight:700; background-color: #1E3A8A; color: white; }
    div[data-baseweb="tab-list"] { gap: 10px; }
    div[data-baseweb="tab"] { background-color: #f0f2f6; border-radius: 10px 10px 0 0; padding: 10px 20px; }
    .stMetric { background-color: #ffffff; padding: 15px; border-radius: 15px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); }
</style>
""", unsafe_allow_html=True)

# -------------------------
# 2. DATABASE PATH & INIT
# -------------------------
# Ensure directory exists for cloud deploy
if not os.path.exists("database"):
    os.makedirs("database")

DB_PATH = "database/cashclear.db"
db = sqlite3.connect(DB_PATH, check_same_thread=False)

# Re-run table creations just in case
db.execute("""CREATE TABLE IF NOT EXISTS accounts (account_id TEXT PRIMARY KEY, password TEXT, balance REAL, role TEXT, location TEXT, status TEXT, pin TEXT)""")
db.execute("""CREATE TABLE IF NOT EXISTS passes (phone TEXT, p_code TEXT PRIMARY KEY, status TEXT, amount REAL, issued_at TEXT, expiry TEXT, issuer TEXT, location TEXT)""")
db.commit()

# -------------------------
# 3. UTILITIES
# -------------------------
def hash_pw(pw: str): return hashlib.sha256(pw.encode()).hexdigest()

def generate_qr_b64(data: str):
    qr = qrcode.QRCode(box_size=8, border=2)
    qr.add_data(data)
    img = qr.make_image(fill_color="#1E3A8A", back_color="white")
    buf = BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()

# -------------------------
# 4. SESSION STATE
# -------------------------
if "auth" not in st.session_state: st.session_state.auth = None
if "mode" not in st.session_state: st.session_state.mode = "Simple"

# -------------------------
# 5. SIDEBAR (Fragmented)
# -------------------------
with st.sidebar:
    st.title("🛡️ CASHCLEAR")
    st.radio("Mode", ["Simple", "Advanced"], key="mode")
    if st.session_state.auth:
        res = db.execute("SELECT balance FROM accounts WHERE account_id=?", (st.session_state.auth["id"],)).fetchone()
        st.metric("Wallet", f"R{res[0]:,.2f}")
        if st.button("Logout"):
            st.session_state.auth = None
            st.rerun()

# -------------------------
# 6. AUTHENTICATION FLOW
# -------------------------
if not st.session_state.auth:
    st.title("Operator Login")
    uid = st.text_input("Operator ID").upper()
    pw = st.text_input("Password", type="password")
    if st.button("Unlock Terminal", use_container_width=True):
        user = db.execute("SELECT account_id, role, location FROM accounts WHERE account_id=? AND password=? AND status='Active'",
                          (uid, hash_pw(pw))).fetchone()
        if user:
            st.session_state.auth = {"id":user[0], "role":user[1], "loc":user[2]}
            st.rerun()
        else: st.error("Access Denied")

else:
    # MAIN MENU
    tabs = st.tabs(["🚀 Issue", "✅ Redeem"]) if st.session_state.mode == "Simple" else \
           st.tabs(["🚀 Issue", "📦 Batch", "✅ Redeem", "📊 Audit", "⚙️ Admin"])

    # --- TAB: ISSUE ---
    with tabs[0]:
        st.subheader("Issue Voucher")
        phone = st.text_input("Customer Phone")
        amount = st.number_input("Amount (R)", min_value=10.0, step=10.0)
        
        if st.button("Create Voucher", use_container_width=True):
            bal = db.execute("SELECT balance FROM accounts WHERE account_id=?", (st.session_state.auth["id"],)).fetchone()[0]
            if bal >= amount and phone:
                p_code = f"CC-{random.randint(1000,9999)}-{random.randint(1000,9999)}"
                expiry = (datetime.now() + timedelta(days=7)).isoformat()
                with db:
                    db.execute("INSERT INTO passes VALUES (?,?,?,?,?,?,?,?)", (phone, p_code, "Active", amount, datetime.now().isoformat(), expiry, st.session_state.auth["id"], st.session_state.auth["loc"]))
                    db.execute("UPDATE accounts SET balance = balance - ? WHERE account_id=?", (amount, st.session_state.auth["id"]))
                st.success("Voucher Created!")
                st.image(f"data:image/png;base64,{generate_qr_b64(p_code)}")
                st.code(p_code)
            else: st.error("Check balance or phone number")

    # --- TAB: REDEEM ---
    r_idx = 1 if st.session_state.mode == "Simple" else 2
    with tabs[r_idx]:
        st.subheader("Redeem System")
        cam_img = st.camera_input("Scan QR")
        scanned = None
        if cam_img:
            bytes_data = cam_img.getvalue()
            img = cv2.imdecode(np.frombuffer(bytes_data, np.uint8), cv2.IMREAD_COLOR)
            detector = cv2.QRCodeDetector()
            val, _, _ = detector.detectAndDecode(img)
            if val: scanned = val
        
        code = st.text_input("Voucher Code", value=scanned if scanned else "").upper()
        
        if st.button("Process Payment", use_container_width=True):
            v = db.execute("SELECT status, amount, expiry FROM passes WHERE p_code=?", (code,)).fetchone()
            if v and v[0] == "Active" and datetime.fromisoformat(v[2]) > datetime.now():
                with db:
                    db.execute("UPDATE passes SET status='Redeemed' WHERE p_code=?", (code,))
                st.balloons()
                st.success(f"Redeemed R{v[1]}")
            else: st.error("Invalid or Expired")

    # --- TAB: AUDIT ---
    if st.session_state.mode == "Advanced":
        with tabs[3]:
            st.subheader("Recent Activity")
            df = pd.read_sql("SELECT * FROM passes ORDER BY issued_at DESC LIMIT 20", db)
            st.dataframe(df)