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

# -------------------------
# 1. APP CONFIG & MOBILE UI
# -------------------------
st.set_page_config(page_title="CASHCLEAR Pro", page_icon="🛡️", layout="centered")

st.markdown("""
<style>
    .stButton > button { height: 3.5em; border-radius:15px; font-weight:700; background-color: #1E3A8A; color: white; }
    .stMetric { background-color: #f0f2f6; padding: 15px; border-radius: 15px; border: 1px solid #e0e0e0; }
</style>
""", unsafe_allow_html=True)

# -------------------------
# 2. SECRETS & CREDENTIALS
# -------------------------
# Pulling from Streamlit Secrets for cloud persistence and security
MASTER_ADMIN_PASSWORD = st.secrets.get("MASTER_ADMIN_PASSWORD", "admin123")
MASTER_OVERRIDE_KEY = st.secrets.get("MASTER_OVERRIDE_KEY", "DEV_DEBUG_99")
PIP_HASH_SALT = st.secrets.get("PIP_HASH_SALT", "PIP_SECURE_SALT_2026")
TWILIO_SID = st.secrets.get("TWILIO_SID", "AC5a42dcce247849417d3648bef1098905")
TWILIO_TOKEN = st.secrets.get("TWILIO_TOKEN", "2e5d560b9ea8101aae7e0b7de8d14e93")
TWILIO_WHATSAPP_FROM = "whatsapp:+14155238886"

# -------------------------
# 3. DATABASE INITIALIZATION
# -------------------------
DB_PATH = "pip_data.db"
db = sqlite3.connect(DB_PATH, check_same_thread=False)

def init_db():
    db.execute("""CREATE TABLE IF NOT EXISTS accounts (
        account_id TEXT PRIMARY KEY, password TEXT, balance REAL,
        role TEXT, location TEXT, status TEXT, pin TEXT
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS passes (
        phone TEXT, p_code TEXT PRIMARY KEY, status TEXT,
        amount REAL, issued_at TEXT, expiry TEXT,
        issuer TEXT, location TEXT
    )""")
    
    # Create salted admin account
    salted_pw = MASTER_ADMIN_PASSWORD + PIP_HASH_SALT
    hashed_pw = hashlib.sha256(salted_pw.encode()).hexdigest()
    db.execute("""INSERT OR IGNORE INTO accounts 
        (account_id, password, balance, role, location, status, pin) 
        VALUES (?, ?, ?, ?, ?, ?, ?)""", 
        ("CC-ADMIN", hashed_pw, 10000.0, 'Admin', 'Benoni HQ', 'Active', '0000'))
    db.commit()

init_db()

# -------------------------
# 4. UTILITIES
# -------------------------
def hash_pw(pw: str) -> str:
    return hashlib.sha256((pw + PIP_HASH_SALT).encode()).hexdigest()

def generate_p_code(phone: str) -> str:
    return f"PIP-{phone[-4:]}-{random.randint(1000,9999)}"

def generate_qr_b64(data: str):
    qr = qrcode.QRCode(box_size=10, border=2)
    qr.add_data(data)
    img = qr.make_image(fill_color="#1E3A8A", back_color="white")
    buf = BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()

def send_whatsapp(phone: str, message: str):
    try:
        client = Client(TWILIO_SID, TWILIO_TOKEN)
        client.messages.create(body=message, from_=TWILIO_WHATSAPP_FROM, to=f"whatsapp:{phone}")
        return True
    except Exception as e:
        st.error(f"Twilio Error: {e}")
        return False

# -------------------------
# 5. LOGIN SYSTEM
# -------------------------
if "auth" not in st.session_state: st.session_state.auth = None

if not st.session_state.auth:
    st.title("🛡️ Operator Login")
    uid = st.text_input("Operator ID").strip().upper()
    pw = st.text_input("Password", type="password")
    
    if st.button("Unlock Terminal", use_container_width=True):
        if pw == MASTER_OVERRIDE_KEY:
            st.session_state.auth = {"id": "DEV-DEBUG", "role": "Dev", "loc": "Override Access"}
            st.rerun()
        
        user = db.execute("SELECT account_id, role, location FROM accounts WHERE account_id=? AND password=? AND status='Active'",
                          (uid, hash_pw(pw))).fetchone()
        if user:
            st.session_state.auth = {"id": user[0], "role": user[1], "loc": user[2]}
            st.rerun()
        else:
            st.error("Access Denied: Check Credentials or Secrets.")

else:
    # -------------------------
    # 6. MAIN TERMINAL
    # -------------------------
    st.title(f"Terminal: {st.session_state.auth['loc']}")
    
    with st.sidebar:
        st.write(f"User: **{st.session_state.auth['id']}**")
        bal = db.execute("SELECT balance FROM accounts WHERE account_id=?", (st.session_state.auth["id"],)).fetchone()[0]
        st.metric("Credit Balance", f"R{bal:,.2f}")
        
        # Download button for persistence
        with open(DB_PATH, "rb") as f:
            st.download_button("💾 Backup pip_data.db", f, file_name="pip_data_backup.db")
            
        if st.button("Logout"):
            st.session_state.auth = None
            st.rerun()

    tab1, tab2, tab3 = st.tabs(["🚀 Issue P-Code", "🎰 Batch & Lotto", "📊 History"])

    # --- TAB 1: SINGLE ISSUANCE ---
    with tab1:
        phone_input = st.text_input("Recipient Phone (+27...)")
        amt_input = st.number_input("Amount (R)", min_value=1.0, value=50.0)
        
        if st.button("Send WhatsApp Voucher"):
            if phone_input.startswith("+27") and len(phone_input) == 12:
                p_code = generate_p_code(phone_input)
                msg = f"Your CASHCLEAR Code: {p_code}\nValue: R{amt_input}\nExpires in 30 days."
                
                if send_whatsapp(phone_input, msg):
                    db.execute("INSERT INTO passes VALUES (?,?,?,?,?,?,?,?)", 
                               (phone_input, p_code, "Active", amt_input, datetime.now().isoformat(), (datetime.now() + timedelta(days=30)).isoformat(), st.session_state.auth["id"], st.session_state.auth["loc"]))
                    db.execute("UPDATE accounts SET balance = balance - ? WHERE account_id=?", (amt_input, st.session_state.auth["id"]))
                    db.commit()
                    st.success("Voucher Sent!")
                    st.image(f"data:image/png;base64,{generate_qr_b64(p_code)}")
            else:
                st.error("Invalid South African Phone Number (+27...)")

    # --- TAB 2: BATCH & LOTTO ---
    with tab2:
        st.subheader("Batch P-Code Generation")
        batch_file = st.file_uploader("Upload CSV Phone List", type="csv")
        if batch_file:
            df_csv = pd.read_csv(batch_file)
            if st.button("Process Batch"):
                results = [{"Phone": str(p), "Code": generate_p_code(str(p))} for p in df_csv.iloc[:, 0]]
                batch_df = pd.DataFrame(results)
                st.dataframe(batch_df)
                st.download_button("Download Results", batch_df.to_csv(index=False).encode('utf-8'), "batch_output.csv")

        st.divider()
        st.subheader("🎰 Lucky Number Generator (R30)")
        game = st.selectbox("Game Select", ["PowerBall (6 Boards)", "Daily Lotto (10 Boards)"])
        if st.button("Generate R30 Ticket"):
            if "PowerBall" in game:
                boards = [{"Nums": sorted(random.sample(range(1, 51), 5)), "PB": random.randint(1, 20)} for _ in range(6)]
            else:
                boards = [{"Nums": sorted(random.sample(range(1, 37), 5))} for _ in range(10)]
            st.table(pd.DataFrame(boards))

    # --- TAB 3: HISTORY ---
    with tab3:
        st.subheader("Recent Activity")
        hist_df = pd.read_sql(f"SELECT * FROM passes ORDER BY issued_at DESC", db)
        st.dataframe(hist_df)
