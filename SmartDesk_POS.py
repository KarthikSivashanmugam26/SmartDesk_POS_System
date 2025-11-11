# SmartDesk_POS.py
# Single-file SmartDesk POS (finalized)
# - Category-first inventory (items grouped by category)
# - Multi-select Add Selected -> Billing
# - Chocolate category auto-generated (500 items ₹1..₹500)
# - Billing columns: HSN | Category | Item name | Qty | MRP | GST | Total
# - UPI QR (UPI field empty by default)
# - Invoice PDF + DB save + local JSON backup + optional GitHub upload
# - Twilio SMS optional (configure in Settings)
# - Admin: myadmin / 1234 ; Staff: employee / 1111
# - Theme chooser (Light / Dark)
#
# Usage:
#   pip install PyQt5 qrcode reportlab twilio requests python-dotenv
#   python SmartDesk_POS.py

import sys
import os
import io
import json
import random
import base64
import sqlite3
from pathlib import Path
from datetime import datetime, timezone

# optional .env
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

# PyQt
from PyQt5 import QtWidgets, QtGui, QtCore

# QR & PDF
import qrcode
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

# Twilio optional
try:
    from twilio.rest import Client as TwilioClient
except Exception:
    TwilioClient = None

# HTTP
import requests

# ---------------- Config & Paths ----------------
DB_FILE = "smartdesk_pos.db"
INVOICES_DIR = Path("invoices"); INVOICES_DIR.mkdir(exist_ok=True)
BACKUP_DIR = Path("backups"); BACKUP_DIR.mkdir(exist_ok=True)

# Use your GitHub username as default owner (from your reply)
DEFAULT_GH_OWNER = "KarthikSivashanmugam26"
DEFAULT_GH_REPO = "SmartDesk_POS_System" 
DEFAULT_GH_PATH = ""  # repo root by default

# Twilio env fallback (settings UI will show / let user edit)
ENV_TW_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
ENV_TW_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
ENV_TW_FROM = os.getenv("TWILIO_FROM_NUMBER", "")

# UPI id left empty by default; user can set in Settings
DEFAULT_UPI = ""

# ---------------- Categories & GST ----------------
CATEGORIES = [
    "Fresh Produce", "Dairy & Eggs", "Breads & Buns", "Pastries, Cakes & Desserts", "Beverages",
    "Snacks & Packaged Foods", "Frozen Foods", "Pulses, Rice & Grains", "Oils & Masalas",
    "Personal Care", "Household Essentials", "Stationery & Office Supplies", "Baby Care",
    "Pet Supplies", "Electronics & Accessories", "Home Appliances", "Furniture & Home Décor",
    "Gardening & Outdoor", "Automotive & Tools", "Health & Wellness",
    "Sports & Fitness", "Home Safety & Security Systems", "Chocolate"
]

GST_RATES = {
    "Fresh Produce": 0, "Dairy & Eggs": 5, "Breads & Buns": 5, "Pastries, Cakes & Desserts": 18,
    "Beverages": 12, "Snacks & Packaged Foods": 12, "Frozen Foods": 12, "Pulses, Rice & Grains": 0,
    "Oils & Masalas": 5, "Personal Care": 18, "Household Essentials": 18,
    "Stationery & Office Supplies": 12, "Baby Care": 12, "Pet Supplies": 12,
    "Electronics & Accessories": 18, "Home Appliances": 18, "Furniture & Home Décor": 18,
    "Gardening & Outdoor": 12, "Automotive & Tools": 18, "Health & Wellness": 12,
    "Sports & Fitness": 18, "Home Safety & Security Systems": 18, "Chocolate": 18
}

# ---------------- UI Styles ----------------
STYLE_LIGHT = """
QWidget { background: #ffffff; color: #0b1a2b; font-family: "Segoe UI", Arial, sans-serif; }
QPushButton { background:#f0f6ff; border:1px solid #d9e9ff; padding:8px; border-radius:8px }
QPushButton#accent { background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #2563eb, stop:1 #3b82f6); color:white; font-weight:700; }
QLabel#title { font-size:20px; font-weight:700; color:#072146; }
QTableWidget, QLineEdit, QComboBox, QSpinBox, QTextEdit { border:1px solid #e6f0fb; background:white; padding:6px; border-radius:6px }
QListWidget { border:1px solid #e6f0fb; background: #fbfdff; }
"""

STYLE_DARK = """
QWidget { background: #0b1220; color: #e8eef6; font-family: "Segoe UI", Arial, sans-serif; }
QPushButton { background:#111827; border:1px solid #1f2937; padding:8px; border-radius:8px; color:#e8eef6 }
QPushButton#accent { background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #b8860b, stop:1 #d4af37); color:#071018; font-weight:700; }
QLabel#title { font-size:20px; font-weight:700; color:#f3e9d2; }
QTableWidget, QLineEdit, QComboBox, QSpinBox, QTextEdit { border:1px solid #22303a; background:#071018; padding:6px; border-radius:6px; color:#e8eef6 }
QListWidget { border:1px solid #22303a; background:#071018; }
"""

# category color hints (for list background)
CATEGORY_COLORS = ["#e6f2ff","#fff7ed","#f0f9ff","#fff1f2","#f7fee9","#fef3f2","#f0f4f8","#f3f4f6","#fff8f1","#f8fafc","#f6f7fb","#f2f8ee"]

# ---------------- Database Helper ----------------
class DB:
    def __init__(self, filename=DB_FILE):
        self.conn = sqlite3.connect(filename, check_same_thread=False)
        self._init_tables()

    def _init_tables(self):
        cur = self.conn.cursor()
        cur.execute('''CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY, sku TEXT UNIQUE, name TEXT, category TEXT, unit TEXT, hsn TEXT, gst INTEGER, mrp REAL, stock INTEGER
        )''')
        cur.execute('''CREATE TABLE IF NOT EXISTS invoices (
            id INTEGER PRIMARY KEY, invoice_no TEXT, customer_phone TEXT, data TEXT, file_path TEXT, created_at TEXT
        )''')
        cur.execute('''CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY, username TEXT UNIQUE, password TEXT, role TEXT
        )''')
        cur.execute('''CREATE TABLE IF NOT EXISTS settings (k TEXT PRIMARY KEY, v TEXT)''')
        self.conn.commit()
        self._seed_defaults()

    def _seed_defaults(self):
        cur = self.conn.cursor()
        cur.execute('SELECT COUNT(*) FROM users')
        if cur.fetchone()[0] == 0:
            cur.execute('INSERT INTO users (username,password,role) VALUES (?,?,?)', ('myadmin','1234','admin'))
            cur.execute('INSERT INTO users (username,password,role) VALUES (?,?,?)', ('employee','1111','staff'))
        cur.execute('INSERT OR IGNORE INTO settings (k,v) VALUES (?,?)', ('store_name','Smart Desk Mart'))
        cur.execute('INSERT OR IGNORE INTO settings (k,v) VALUES (?,?)', ('theme','light'))
        cur.execute('INSERT OR IGNORE INTO settings (k,v) VALUES (?,?)', ('gh_owner', DEFAULT_GH_OWNER))
        cur.execute('INSERT OR IGNORE INTO settings (k,v) VALUES (?,?)', ('gh_repo', DEFAULT_GH_REPO))
        cur.execute('INSERT OR IGNORE INTO settings (k,v) VALUES (?,?)', ('gh_path', DEFAULT_GH_PATH))
        cur.execute('INSERT OR IGNORE INTO settings (k,v) VALUES (?,?)', ('tw_sid', ENV_TW_SID))
        cur.execute('INSERT OR IGNORE INTO settings (k,v) VALUES (?,?)', ('tw_token', ENV_TW_TOKEN))
        cur.execute('INSERT OR IGNORE INTO settings (k,v) VALUES (?,?)', ('tw_from', ENV_TW_FROM))
        cur.execute('INSERT OR IGNORE INTO settings (k,v) VALUES (?,?)', ('upi_id', DEFAULT_UPI))
        self.conn.commit()

    # products
    def insert_product(self, sku, name, category, unit, hsn, gst, mrp, stock):
        cur = self.conn.cursor()
        try:
            cur.execute('INSERT INTO products (sku,name,category,unit,hsn,gst,mrp,stock) VALUES (?,?,?,?,?,?,?,?)',
                        (sku, name, category, unit, hsn, gst, mrp, stock))
            self.conn.commit()
            return cur.lastrowid
        except sqlite3.IntegrityError:
            return None

    def products_by_category(self, category):
        cur = self.conn.cursor()
        cur.execute('SELECT id,sku,name,category,unit,hsn,gst,mrp,stock FROM products WHERE category=?', (category,))
        return cur.fetchall()

    def list_products(self):
        cur = self.conn.cursor()
        cur.execute('SELECT id,sku,name,category,unit,hsn,gst,mrp,stock FROM products')
        return cur.fetchall()

    def get_product_by_sku(self, sku):
        cur = self.conn.cursor()
        cur.execute('SELECT id,sku,name,category,unit,hsn,gst,mrp,stock FROM products WHERE sku=?', (sku,))
        return cur.fetchone()

    def update_stock(self, sku, delta):
        cur = self.conn.cursor()
        cur.execute('UPDATE products SET stock=stock+? WHERE sku=?', (delta, sku))
        self.conn.commit()

    def save_invoice(self, invoice_no, phone, data_dict, file_path):
        cur = self.conn.cursor()
        cur.execute('INSERT INTO invoices (invoice_no,customer_phone,data,file_path,created_at) VALUES (?,?,?,?,?)',
                    (invoice_no, phone, json.dumps(data_dict), file_path, datetime.now(timezone.utc).isoformat()))
        self.conn.commit()

    def validate_user(self, username, password, role):
        cur = self.conn.cursor()
        cur.execute('SELECT role FROM users WHERE username=? AND password=?', (username, password))
        r = cur.fetchone()
        if not r:
            return False
        db_role = r[0]
        if role == 'Admin':
            return db_role == 'admin'
        else:
            return db_role in ('staff', 'admin')

    def set_user(self, username, password, role):
        cur = self.conn.cursor()
        cur.execute('INSERT OR REPLACE INTO users (username,password,role) VALUES (?,?,?)', (username, password, role))
        self.conn.commit()

    def set_setting(self, k, v):
        cur = self.conn.cursor()
        cur.execute('INSERT OR REPLACE INTO settings (k,v) VALUES (?,?)', (k, v))
        self.conn.commit()

    def get_setting(self, k, default=None):
        cur = self.conn.cursor()
        cur.execute('SELECT v FROM settings WHERE k=?', (k,))
        r = cur.fetchone()
        return r[0] if r else default

    def export_all(self):
        data = {"products": [], "invoices": []}
        for r in self.list_products():
            data["products"].append({
                "id": r[0], "sku": r[1], "name": r[2], "category": r[3], "unit": r[4], "hsn": r[5], "gst": r[6], "mrp": r[7], "stock": r[8]
            })
        cur = self.conn.cursor()
        cur.execute('SELECT id,invoice_no,customer_phone,file_path,data,created_at FROM invoices')
        data["invoices"] = []
        for r in cur.fetchall():
            data["invoices"].append({"id": r[0], "invoice_no": r[1], "customer_phone": r[2], "file_path": r[3], "data": json.loads(r[4]), "created_at": r[5]})
        return data

# ---------------- Data generator ----------------
UNITS = ["piece","kg","litre","gram"]
GRAM_VARIANTS = [50,100,200,500]

ADJ = ["Fresh","Premium","Organic","Pure","Classic","Deluxe","New","Tasty","Crunchy","Smooth"]
WORDS = [
    "Milk", "Paneer", "White Bread", "Chocolate Cake", "Orange Juice", "Potato Chips",
    "Frozen Peas", "Basmati Rice", "Mustard Oil", "Shampoo", "Dishwash Liquid", "A4 Paper",
    "Baby Diapers", "Dog Food", "USB Cable", "Blender", "Cushion Cover", "Gardening Soil",
    "Car Wax", "Vitamin C", "Yoga Mat", "Door Sensor", "LED Bulb"
]

def gen_hsn_for_category(cat):
    idx = CATEGORIES.index(cat) + 1
    return f"{1000 + idx:04d}"

def seed_products(db: DB, target=1100):
    cur = db.conn.cursor()
    cur.execute('SELECT COUNT(*) FROM products')
    if cur.fetchone()[0] >= target:
        return
    sku = 10000
    created = 0
    # generate non-chocolate items until target-500
    while created < (target - 500):
        for cat in CATEGORIES:
            if cat == "Chocolate": continue
            if created >= (target - 500): break
            name = f"{random.choice(ADJ)} {random.choice(WORDS)}"
            unit = random.choice(UNITS)
            if unit == "gram":
                g = random.choice(GRAM_VARIANTS)
                name = f"{name} {g}g"
            gst = GST_RATES.get(cat, 18)
            hsn = gen_hsn_for_category(cat)
            mrp = round(random.uniform(30, 2000), 2)
            stock = random.randint(0,200)
            sku_code = f"SKU{sku}"
            db.insert_product(sku_code, name, cat, unit, hsn, gst, mrp, stock)
            sku += 1
            created += 1
            if created >= (target - 500):
                break
    # chocolate: 500 items from ₹1 to ₹500
    for i in range(1,501):
        price = float(i)
        unit = "piece" if i % 7 else "gram"
        name = f"ChocolateVar {i}"
        if unit == "gram":
            g = random.choice(GRAM_VARIANTS)
            name = f"{name} {g}g"
        hsn = gen_hsn_for_category("Chocolate")
        gst = GST_RATES.get("Chocolate", 18)
        sku_code = f"CHC{i:04d}"
        stock = random.randint(10,300)
        db.insert_product(sku_code, name, "Chocolate", unit, hsn, gst, price, stock)

# ---------------- GitHub uploader ----------------
class GitHubUploader:
    def __init__(self, token, owner, repo):
        self.token = token
        self.owner = owner
        self.repo = repo
        self.api = f"https://api.github.com/repos/{owner}/{repo}"

    def upload(self, path_in_repo, file_bytes, commit_msg='SmartDesk backup'):
        url = f"{self.api}/contents/{path_in_repo.lstrip('/')}"
        content = base64.b64encode(file_bytes).decode()
        headers = {"Authorization": f"token {self.token}", "User-Agent": "SmartDeskPOS"}
        r = requests.get(url, headers=headers)
        sha = None
        try:
            if r.status_code == 200:
                data = r.json()
                if isinstance(data, dict) and 'sha' in data:
                    sha = data['sha']
        except Exception:
            sha = None
        payload = {"message": commit_msg, "content": content}
        if sha:
            payload['sha'] = sha
        resp = requests.put(url, headers=headers, data=json.dumps(payload))
        return resp.status_code in (200,201)

# ---------------- Twilio sender ----------------
class TwilioSender:
    def __init__(self, sid, token, from_no):
        if TwilioClient is None:
            raise RuntimeError("Twilio library not installed")
        self.client = TwilioClient(sid, token)
        self.from_no = from_no

    def send(self, to, body):
        msg = self.client.messages.create(body=body, from_=self.from_no, to=to)
        return msg.sid

# ---------------- Invoice / PDF / Backup ----------------
def generate_invoice_pdf(invoice_no, invoice_data, out_path: Path):
    c = canvas.Canvas(str(out_path), pagesize=A4)
    w, h = A4
    c.setFont("Helvetica-Bold", 16)
    c.drawString(40, h-60, invoice_data.get('store', 'Smart Desk Mart'))
    c.setFont("Helvetica", 10)
    c.drawString(40, h-80, f"Invoice: {invoice_no}")
    c.drawString(40, h-95, f"Date: {datetime.now(timezone.utc).isoformat()}")
    c.drawString(40, h-110, f"Customer: {invoice_data.get('customer_name','-')} Phone: {invoice_data.get('customer_phone','-')}")
    y = h-140
    c.drawString(40, y, "HSN | Category | Item | Qty | MRP | GST% | Total")
    y -= 16
    for it in invoice_data.get('items', []):
        line = f"{it.get('hsn','-')} | {it.get('category','-')} | {it.get('name','-')} | {it.get('qty',0)} | {it.get('mrp')} | {it.get('gst')} | {it.get('total')}"
        c.drawString(40, y, line)
        y -= 14
        if y < 80:
            c.showPage(); y = h-60
    y -= 8
    c.drawString(40, y, f"Total Amount: ₹{invoice_data.get('total')}")
    c.save()

def backup_json(db: DB):
    data = db.export_all()
    fname = BACKUP_DIR / f"backup_{int(datetime.now(timezone.utc).timestamp())}.json"
    with open(fname, "w", encoding="utf8") as f:
        json.dump(data, f, indent=2)
    return fname

# ---------------- Small icon helper (safe painter init) ----------------
def create_icon_pixmap(name, size=44):
    pix = QtGui.QPixmap(size, size)
    pix.fill(QtCore.Qt.transparent)
    p = None
    try:
        p = QtGui.QPainter(pix)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        pen = QtGui.QPen(QtGui.QColor('#2563eb'))
        pen.setWidthF(2.0)
        p.setPen(pen)
        if name == 'billing':
            p.drawRect(8, 10, size-16, size-20)
            p.drawLine(12, 22, size-12, 22)
            p.drawLine(12, 32, size-12, 32)
        elif name == 'inventory':
            p.drawRect(8, 10, size-16, size-20)
            p.drawLine(8, 16, size/2, 4)
            p.drawLine(size-8, 16, size/2, 4)
        elif name == 'reports':
            w = (size - 20) / 6
            for i, hfactor in enumerate([0.35,0.55,0.85,0.6]):
                ph = (size - 20) * hfactor
                p.drawRect(10 + i*(w+4), size-10-ph, w, ph)
        elif name == 'stock':
            p.drawRect(8, 10, size-16, size-30)
            p.drawEllipse(12, size-16, 8, 8)
            p.drawEllipse(size-20, size-16, 8, 8)
        else:
            p.drawEllipse(8, 8, size-16, size-16)
    except Exception:
        pass
    finally:
        if p is not None:
            p.end()
    return pix

# ---------------- GUI Widgets ----------------
class LoginWindow(QtWidgets.QWidget):
    def __init__(self, db, main_win):
        super().__init__()
        self.db = db
        self.main_win = main_win
        self.setWindowTitle("SmartDesk - Login")
        self.resize(760, 480)
        # theme set in main window; set application stylesheet from db
        layout = QtWidgets.QVBoxLayout(self)
        lbl = QtWidgets.QLabel(self.db.get_setting('store_name','Smart Desk Mart'))
        lbl.setObjectName('title')
        lbl.setAlignment(QtCore.Qt.AlignCenter)
        font = lbl.font(); font.setPointSize(18); font.setBold(True); lbl.setFont(font)
        layout.addWidget(lbl)
        form = QtWidgets.QFormLayout()
        self.role = QtWidgets.QComboBox(); self.role.addItems(['Admin','Staff'])
        self.user = QtWidgets.QLineEdit(); self.pwd = QtWidgets.QLineEdit(); self.pwd.setEchoMode(QtWidgets.QLineEdit.Password)
        form.addRow('Role', self.role); form.addRow('Username', self.user); form.addRow('Password', self.pwd)
        layout.addLayout(form)
        btn = QtWidgets.QPushButton("Login"); btn.setObjectName('accent'); btn.clicked.connect(self.try_login)
        layout.addWidget(btn)
        layout.addStretch(1)

    def try_login(self):
        role = self.role.currentText(); u = self.user.text().strip(); p = self.pwd.text().strip()
        if self.db.validate_user(u, p, role):
            self.hide()
            # show main window (preserve the full screen behavior optional)
            self.main_win.show()
            return
        QtWidgets.QMessageBox.warning(self, "Login failed", "Invalid credentials")

class DashboardWidget(QtWidgets.QWidget):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        layout = QtWidgets.QVBoxLayout(self)
        title = QtWidgets.QLabel(self.parent.db.get_setting('store_name','Smart Desk Mart'))
        title.setObjectName('title'); title.setAlignment(QtCore.Qt.AlignCenter)
        layout.addWidget(title)
        # center cards grid
        gridwrap = QtWidgets.QWidget(); grid = QtWidgets.QGridLayout(); grid.setSpacing(18); gridwrap.setLayout(grid)
        layout.addWidget(gridwrap, alignment=QtCore.Qt.AlignCenter)
        def card(text, icon, handler):
            btn = QtWidgets.QPushButton()
            btn.setFixedSize(220,120)
            btn.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
            v = QtWidgets.QVBoxLayout(btn)
            ic = QtWidgets.QLabel(); ic.setPixmap(create_icon_pixmap(icon,44)); ic.setAlignment(QtCore.Qt.AlignCenter)
            v.addWidget(ic)
            lbl = QtWidgets.QLabel(text); lbl.setAlignment(QtCore.Qt.AlignCenter); lbl.setStyleSheet("font-weight:700")
            v.addWidget(lbl)
            btn.clicked.connect(handler)
            return btn
        grid.addWidget(card('Billing','billing', lambda: parent.open_billing()), 0, 0)
        grid.addWidget(card('Inventory','inventory', lambda: parent.show_inventory()), 0, 1)
        grid.addWidget(card('Reports','reports', lambda: parent.show_reports()), 1, 0)
        grid.addWidget(card('Stock Inwards','stock', lambda: parent.show_stock()), 1, 1)
        grid.addWidget(card('Settings','settings', lambda: parent.show_settings()), 2, 0)
        grid.addWidget(card('Logout','logout', lambda: QtWidgets.qApp.quit()), 2, 1)

class InventoryWidget(QtWidgets.QWidget):
    def __init__(self, db, main_win):
        super().__init__()
        self.db = db
        self.main_win = main_win
        self._selected = set()
        layout = QtWidgets.QVBoxLayout(self)
        # top controls
        top = QtWidgets.QHBoxLayout()
        self.search = QtWidgets.QLineEdit(); self.search.setPlaceholderText("Search SKU or name (filters within selected category)")
        self.reload_btn = QtWidgets.QPushButton("Reload")
        top.addWidget(self.search); top.addWidget(self.reload_btn)
        layout.addLayout(top)
        # body: categories list left, items table right
        body = QtWidgets.QHBoxLayout()
        self.cat_list = QtWidgets.QListWidget(); self.cat_list.setMaximumWidth(260)
        body.addWidget(self.cat_list)
        self.table = QtWidgets.QTableWidget(0,7)
        self.table.setHorizontalHeaderLabels(["Select","SKU","Name","Unit","MRP","GST%","Stock"])
        self.table.horizontalHeader().setSectionResizeMode(2, QtWidgets.QHeaderView.Stretch)
        body.addWidget(self.table)
        layout.addLayout(body)
        # bottom
        bottom = QtWidgets.QHBoxLayout()
        self.selected_label = QtWidgets.QLabel("Selected: 0")
        bottom.addWidget(self.selected_label); bottom.addStretch()
        self.add_selected_btn = QtWidgets.QPushButton("Add Selected to Billing"); self.add_selected_btn.setEnabled(False)
        bottom.addWidget(self.add_selected_btn)
        layout.addLayout(bottom)
        # signals
        self.reload_btn.clicked.connect(self.load_categories)
        self.cat_list.currentItemChanged.connect(self.on_category_changed)
        self.search.textChanged.connect(self.populate_items)
        self.add_selected_btn.clicked.connect(self.add_selected_to_billing)
        # initial load
        self.load_categories()

    def load_categories(self):
        self.cat_list.clear()
        for i, c in enumerate(CATEGORIES):
            it = QtWidgets.QListWidgetItem(c)
            color = CATEGORY_COLORS[i % len(CATEGORY_COLORS)]
            it.setBackground(QtGui.QColor(color))
            self.cat_list.addItem(it)
        if self.cat_list.count() > 0:
            self.cat_list.setCurrentRow(0)

    def on_category_changed(self, cur, prev):
        if cur:
            self.current_category = cur.text()
            self.populate_items()

    def populate_items(self):
        # avoid itemChanged recursion
        try:
            self.table.itemChanged.disconnect(self.on_item_changed)
        except Exception:
            pass
        self.table.setRowCount(0)
        if not hasattr(self, 'current_category'):
            return
        q = self.search.text().strip().lower()
        rows = self.db.products_by_category(self.current_category)
        for rec in rows:
            _id, sku, name, cat, unit, hsn, gst, mrp, stock = rec
            display = f"{sku} {name}".lower()
            if q and q not in display:
                continue
            r = self.table.rowCount(); self.table.insertRow(r)
            # checkbox item
            chk = QtWidgets.QTableWidgetItem()
            chk.setFlags(QtCore.Qt.ItemIsUserCheckable | QtCore.Qt.ItemIsEnabled)
            chk.setCheckState(QtCore.Qt.Unchecked)
            self.table.setItem(r, 0, chk)
            self.table.setItem(r, 1, QtWidgets.QTableWidgetItem(sku))
            self.table.setItem(r, 2, QtWidgets.QTableWidgetItem(name))
            self.table.setItem(r, 3, QtWidgets.QTableWidgetItem(unit))
            self.table.setItem(r, 4, QtWidgets.QTableWidgetItem(str(mrp)))
            self.table.setItem(r, 5, QtWidgets.QTableWidgetItem(str(gst)))
            self.table.setItem(r, 6, QtWidgets.QTableWidgetItem(str(stock)))
        # reconnect
        self.table.itemChanged.connect(self.on_item_changed)
        self.update_selection_status()

    def on_item_changed(self, item):
        # watch only checkbox column 0
        if item.column() != 0:
            return
        row = item.row()
        sku_item = self.table.item(row, 1)
        if not sku_item:
            return
        sku = sku_item.text()
        if item.checkState() == QtCore.Qt.Checked:
            self._selected.add(sku)
        else:
            self._selected.discard(sku)
        self.update_selection_status()

    def update_selection_status(self):
        cnt = len(self._selected)
        self.selected_label.setText(f"Selected: {cnt}")
        self.add_selected_btn.setEnabled(cnt > 0)

    def add_selected_to_billing(self):
        if not self._selected:
            return
        bw = self.main_win.open_billing()
        for sku in list(self._selected):
            rec = self.db.get_product_by_sku(sku)
            if not rec: continue
            _, sku, name, category, unit, hsn, gst, mrp, stock = rec
            bw.add_row_from_inventory({"hsn": hsn, "category": category, "name": name, "qty": 1, "mrp": mrp, "gst": gst, "sku": sku})
        # clear selection & refresh view
        self._selected.clear()
        self.populate_items()
        bw.show(); bw.raise_(); bw.activateWindow()

class BillingWindow(QtWidgets.QWidget):
    def __init__(self, db):
        super().__init__()
        self.db = db
        self.setWindowTitle("Billing - SmartDesk")
        self.resize(980,720)
        layout = QtWidgets.QVBoxLayout(self)
        # header: customer + search
        header = QtWidgets.QHBoxLayout()
        self.cust_name = QtWidgets.QLineEdit(); self.cust_name.setPlaceholderText("Customer name")
        self.cust_phone = QtWidgets.QLineEdit(); self.cust_phone.setPlaceholderText("Customer phone")
        header.addWidget(self.cust_name); header.addWidget(self.cust_phone)
        layout.addLayout(header)
        # table with billing columns: HSN | Category | Item name | Qty | MRP | GST | Total
        self.table = QtWidgets.QTableWidget(0,7)
        self.table.setHorizontalHeaderLabels(["HSN","Category","Item name","Qty","MRP","GST%","Total"])
        self.table.horizontalHeader().setSectionResizeMode(2, QtWidgets.QHeaderView.Stretch)
        layout.addWidget(self.table)
        # controls
        ctrl = QtWidgets.QHBoxLayout()
        self.remove_btn = QtWidgets.QPushButton("Remove Selected")
        ctrl.addWidget(self.remove_btn)
        ctrl.addStretch()
        self.total_label = QtWidgets.QLabel("Total: ₹0.00")
        ctrl.addWidget(self.total_label)
        layout.addLayout(ctrl)
        self.remove_btn.clicked.connect(self.remove_selected)
        # payment area
        payrow = QtWidgets.QHBoxLayout()
        self.pay_combo = QtWidgets.QComboBox(); self.pay_combo.addItems(["QR","Credit Card","Debit Card","Cash on hand","UPI"])
        self.pay_btn = QtWidgets.QPushButton("Pay & Generate Invoice"); self.pay_btn.setObjectName("accent")
        payrow.addWidget(self.pay_combo); payrow.addWidget(self.pay_btn)
        layout.addLayout(payrow)
        self.pay_btn.clicked.connect(self.pay)
        # track edits to quantity
        self.table.itemChanged.connect(self.on_item_changed)

    def add_row_from_inventory(self, item):
        r = self.table.rowCount(); self.table.insertRow(r)
        self.table.setItem(r,0, QtWidgets.QTableWidgetItem(str(item.get("hsn",""))))
        self.table.setItem(r,1, QtWidgets.QTableWidgetItem(str(item.get("category",""))))
        self.table.setItem(r,2, QtWidgets.QTableWidgetItem(str(item.get("name",""))))
        qty_item = QtWidgets.QTableWidgetItem(str(item.get("qty",1)))
        qty_item.setFlags(qty_item.flags() | QtCore.Qt.ItemIsEditable)
        self.table.setItem(r,3, qty_item)
        self.table.setItem(r,4, QtWidgets.QTableWidgetItem(str(item.get("mrp",0.0))))
        self.table.setItem(r,5, QtWidgets.QTableWidgetItem(str(item.get("gst",0))))
        total = round(float(item.get("mrp",0.0)) * float(item.get("qty",1)),2)
        self.table.setItem(r,6, QtWidgets.QTableWidgetItem(str(total)))
        self.recalculate_total()

    def on_item_changed(self, it):
        if it.column() == 3:
            try:
                row = it.row()
                qty = float(it.text())
                mrp = float(self.table.item(row,4).text())
                self.table.item(row,6).setText(str(round(qty*mrp,2)))
            except Exception:
                pass
            self.recalculate_total()

    def recalculate_total(self):
        total = 0.0
        for r in range(self.table.rowCount()):
            try:
                total += float(self.table.item(r,6).text())
            except Exception:
                pass
        self.total_label.setText(f"Total: ₹{round(total,2)}")

    def remove_selected(self):
        r = self.table.currentRow()
        if r >= 0:
            self.table.removeRow(r); self.recalculate_total()

    def pay(self):
        method = self.pay_combo.currentText()
        cname = self.cust_name.text().strip(); phone = self.cust_phone.text().strip()
        items = []; total = 0.0
        for r in range(self.table.rowCount()):
            try:
                hsn = self.table.item(r,0).text()
                cat = self.table.item(r,1).text()
                name = self.table.item(r,2).text()
                qty = float(self.table.item(r,3).text())
                mrp = float(self.table.item(r,4).text())
                gst = float(self.table.item(r,5).text())
                line = float(self.table.item(r,6).text())
                items.append({"hsn":hsn,"category":cat,"name":name,"qty":qty,"mrp":mrp,"gst":gst,"total":line})
                total += line
            except Exception:
                pass
        if not items:
            QtWidgets.QMessageBox.warning(self, "Empty", "Add items before paying"); return
        invoice_no = f"INV{int(datetime.now(timezone.utc).timestamp())}"
        invoice_data = {"invoice_no": invoice_no, "customer_name": cname, "customer_phone": phone, "items": items, "total": round(total,2), "payment_method": method, "store": self.db.get_setting('store_name','Smart Desk Mart')}
        # UPI/QR flow
        if method in ("QR","UPI"):
            upi_id = self.db.get_setting('upi_id','')
            buf = qrcode.make(f"upi://pay?pa={upi_id}&pn=Merchant&am={round(total,2)}")
            b = io.BytesIO(); buf.save(b, format='PNG'); b.seek(0)
            pix = QtGui.QPixmap(); pix.loadFromData(b.read())
            dlg = QtWidgets.QDialog(self); dlg.setWindowTitle("Scan to Pay"); lay = QtWidgets.QVBoxLayout(dlg)
            lb = QtWidgets.QLabel(); lb.setPixmap(pix); lb.setAlignment(QtCore.Qt.AlignCenter); lay.addWidget(lb)
            lay.addWidget(QtWidgets.QLabel(f"UPI ID: {upi_id}\nAmount: ₹{round(total,2)}"))
            ok = QtWidgets.QPushButton("Done (simulate)"); lay.addWidget(ok); ok.clicked.connect(dlg.accept)
            dlg.exec_()
        else:
            QtWidgets.QMessageBox.information(self, "Payment", f"{method} selected (simulated)")
        # Deduct stock best-effort (match by SKU first, else by name)
        for it in items:
            # try by SKU search in products (we don't store sku in table rows for billing)
            # Attempt match by name (best-effort)
            cur = self.db.conn.cursor()
            cur.execute('SELECT sku,stock FROM products WHERE name=? LIMIT 1', (it['name'],))
            r = cur.fetchone()
            if r:
                sku, stock = r
                try:
                    self.db.update_stock(sku, -int(round(it['qty'])))
                except Exception:
                    pass
        # save invoice pdf and db, backup and optional git push
        out = INVOICES_DIR / f"{invoice_no}.pdf"
        generate_invoice_pdf(invoice_no, invoice_data, out)
        self.db.save_invoice(invoice_no, phone, invoice_data, str(out))
        backup = backup_json(self.db)
        # Twilio send if configured
        sent = False
        tw_sid = self.db.get_setting('tw_sid','') or ENV_TW_SID
        tw_token = self.db.get_setting('tw_token','') or ENV_TW_TOKEN
        tw_from = self.db.get_setting('tw_from','') or ENV_TW_FROM
        if tw_sid and tw_token and tw_from and TwilioClient is not None and phone:
            try:
                ts = TwilioSender(tw_sid, tw_token, tw_from)
                body = f"{invoice_data.get('store')} Invoice {invoice_no} Total ₹{invoice_data.get('total')}"
                ts.send(phone, body)
                sent = True
            except Exception as e:
                print("SMS failed:", e)
        # GitHub optional push of JSON backup
        pushed = False
        gh_token = self.db.get_setting('gh_token','')
        gh_owner = self.db.get_setting('gh_owner','') or DEFAULT_GH_OWNER
        gh_repo = self.db.get_setting('gh_repo','') or DEFAULT_GH_REPO
        gh_path = self.db.get_setting('gh_path','') or DEFAULT_GH_PATH
        try:
            if gh_token and gh_owner and gh_repo:
                uploader = GitHubUploader(gh_token, gh_owner, gh_repo)
                with open(backup, 'rb') as f:
                    jbytes = f.read()
                dest = gh_path.strip('/') if gh_path else f"backups/{backup.name}"
                if not dest:
                    dest = backup.name
                pushed = uploader.upload(dest, jbytes, commit_msg=f"SmartDesk backup {invoice_no}")
        except Exception as ex:
            print("GitHub upload failed:", ex)
        QtWidgets.QMessageBox.information(self, "Done", f"Invoice saved: {out}\nBackup: {backup}\nSMS sent: {sent}\nGitHub pushed: {pushed}")
        self.close()

class ReportsWidget(QtWidgets.QWidget):
    def __init__(self, db):
        super().__init__(); self.db = db
        v = QtWidgets.QVBoxLayout(self)
        h = QtWidgets.QHBoxLayout()
        self.daily = QtWidgets.QPushButton("Daily"); self.weekly = QtWidgets.QPushButton("Weekly")
        self.monthly = QtWidgets.QPushButton("Monthly"); self.yearly = QtWidgets.QPushButton("Yearly")
        for b in (self.daily,self.weekly,self.monthly,self.yearly):
            h.addWidget(b)
        v.addLayout(h)
        self.cal = QtWidgets.QCalendarWidget(); v.addWidget(self.cal)
        self.out = QtWidgets.QTextEdit(); self.out.setReadOnly(True); v.addWidget(self.out)
        self.daily.clicked.connect(lambda: self.gen('daily')); self.weekly.clicked.connect(lambda: self.gen('weekly'))
        self.monthly.clicked.connect(lambda: self.gen('monthly')); self.yearly.clicked.connect(lambda: self.gen('yearly'))

    def gen(self, period):
        cur = self.db.conn.cursor()
        cur.execute('SELECT COUNT(*) FROM products'); pcount = cur.fetchone()[0]
        cur.execute('SELECT COUNT(*) FROM invoices'); inv = cur.fetchone()[0]
        cur.execute('SELECT COUNT(*) FROM products WHERE stock<=5'); low = cur.fetchone()[0]
        now = datetime.now(timezone.utc)
        report = (f"Report: {period} at {now.isoformat()}\nProducts total: {pcount}\nInvoices total: {inv}\nLow stock items (<=5): {low}")
        self.out.setPlainText(report)

class StockInwardWidget(QtWidgets.QWidget):
    def __init__(self, db):
        super().__init__(); self.db = db
        v = QtWidgets.QVBoxLayout(self)
        h = QtWidgets.QHBoxLayout()
        self.product_combo = QtWidgets.QComboBox(); self.refresh_products()
        self.qty_spin = QtWidgets.QSpinBox(); self.qty_spin.setMaximum(100000)
        add_btn = QtWidgets.QPushButton("Add Stock")
        h.addWidget(self.product_combo); h.addWidget(self.qty_spin); h.addWidget(add_btn)
        v.addLayout(h)
        self.log = QtWidgets.QTextEdit(); self.log.setReadOnly(True); v.addWidget(self.log)
        add_btn.clicked.connect(self.add_stock)

    def refresh_products(self):
        self.product_combo.clear()
        for r in self.db.list_products():
            self.product_combo.addItem(f"{r[1]} - {r[2]}", userData=r[1])

    def add_stock(self):
        sku = self.product_combo.currentData()
        qty = self.qty_spin.value()
        if not sku or qty <= 0:
            return
        self.db.update_stock(sku, qty)
        self.log.append(f"Added {qty} to {sku} at {datetime.now(timezone.utc).isoformat()}")
        backup_json(self.db)
        self.refresh_products()

class SettingsWidget(QtWidgets.QWidget):
    def __init__(self, db, main_win):
        super().__init__(); self.db = db; self.main_win = main_win
        v = QtWidgets.QVBoxLayout(self)
        form = QtWidgets.QFormLayout()
        self.store_name = QtWidgets.QLineEdit(self.db.get_setting('store_name','Smart Desk Mart'))
        self.theme_combo = QtWidgets.QComboBox(); self.theme_combo.addItems(['light','dark'])
        self.theme_combo.setCurrentText(self.db.get_setting('theme','light'))
        # Users
        self.admin_user = QtWidgets.QLineEdit('myadmin'); self.admin_pass = QtWidgets.QLineEdit('1234')
        self.staff_user = QtWidgets.QLineEdit('employee'); self.staff_pass = QtWidgets.QLineEdit('1111')
        # Twilio / GitHub / UPI
        self.tw_sid = QtWidgets.QLineEdit(self.db.get_setting('tw_sid',''))
        self.tw_token = QtWidgets.QLineEdit(self.db.get_setting('tw_token',''))
        self.tw_from = QtWidgets.QLineEdit(self.db.get_setting('tw_from',''))
        self.gh_token = QtWidgets.QLineEdit(self.db.get_setting('gh_token',''))
        self.gh_owner = QtWidgets.QLineEdit(self.db.get_setting('gh_owner', DEFAULT_GH_OWNER))
        self.gh_repo = QtWidgets.QLineEdit(self.db.get_setting('gh_repo',''))
        self.gh_path = QtWidgets.QLineEdit(self.db.get_setting('gh_path',''))
        self.upi = QtWidgets.QLineEdit(self.db.get_setting('upi_id',''))
        form.addRow('Store name', self.store_name)
        form.addRow('Theme', self.theme_combo)
        form.addRow('Admin user', self.admin_user); form.addRow('Admin pass', self.admin_pass)
        form.addRow('Staff user', self.staff_user); form.addRow('Staff pass', self.staff_pass)
        form.addRow('Twilio SID', self.tw_sid); form.addRow('Twilio Token', self.tw_token); form.addRow('Twilio From', self.tw_from)
        form.addRow('GitHub token', self.gh_token); form.addRow('GitHub owner', self.gh_owner); form.addRow('GitHub repo', self.gh_repo); form.addRow('GitHub path', self.gh_path)
        form.addRow('UPI ID', self.upi)
        v.addLayout(form)
        btn_save = QtWidgets.QPushButton("Save Settings"); v.addWidget(btn_save)
        btn_save.clicked.connect(self.save)

    def save(self):
        self.db.set_setting('store_name', self.store_name.text().strip())
        self.db.set_setting('theme', self.theme_combo.currentText())
        self.db.set_user(self.admin_user.text().strip(), self.admin_pass.text().strip(), 'admin')
        self.db.set_user(self.staff_user.text().strip(), self.staff_pass.text().strip(), 'staff')
        self.db.set_setting('tw_sid', self.tw_sid.text().strip())
        self.db.set_setting('tw_token', self.tw_token.text().strip())
        self.db.set_setting('tw_from', self.tw_from.text().strip())
        self.db.set_setting('gh_token', self.gh_token.text().strip())
        self.db.set_setting('gh_owner', self.gh_owner.text().strip())
        self.db.set_setting('gh_repo', self.gh_repo.text().strip())
        self.db.set_setting('gh_path', self.gh_path.text().strip())
        self.db.set_setting('upi_id', self.upi.text().strip())
        QtWidgets.QMessageBox.information(self, "Saved", "Settings saved. Theme will apply on next restart.")
        # apply theme immediately if possible
        theme = self.theme_combo.currentText()
        if theme == 'dark':
            self.main_win.apply_theme('dark')
        else:
            self.main_win.apply_theme('light')

# ---------------- Main Window ----------------
class MainWindow(QtWidgets.QMainWindow):
    def __init__(self, db):
        super().__init__(); self.db = db
        self.setWindowTitle("SmartDesk POS")
        self.resize(1300,820)
        # apply theme from DB
        theme = self.db.get_setting('theme','light')
        self.apply_theme(theme)
        central = QtWidgets.QWidget(); self.setCentralWidget(central)
        h = QtWidgets.QHBoxLayout(central)
        # sidebar
        sidebar = QtWidgets.QVBoxLayout()
        # center title
        title = QtWidgets.QLabel(self.db.get_setting('store_name','Smart Desk Mart')); title.setObjectName('title'); title.setAlignment(QtCore.Qt.AlignCenter)
        sidebar.addWidget(title)
        sidebar.addSpacing(8)
        # sidebar buttons
        btns = {}
        for name in [('Dashboard','billing'),('Billing','billing'),('Inventory','inventory'),('Reports','reports'),('Stock Inwards','stock'),('Settings','settings'),('Logout','logout')]:
            b = QtWidgets.QPushButton(name[0]); b.setMinimumHeight(44)
            b.setIcon(QtGui.QIcon(create_icon_pixmap(name[1],26)))
            btns[name[0]] = b; sidebar.addWidget(b)
        sidebar.addStretch()
        h.addLayout(sidebar,1)
        # stack
        self.stack = QtWidgets.QStackedWidget(); h.addWidget(self.stack,6)
        self.dashboard_widget = DashboardWidget(self)
        self.inventory_widget = InventoryWidget(self.db, self)
        self.reports_widget = ReportsWidget(self.db)
        self.stock_widget = StockInwardWidget(self.db)
        self.settings_widget = SettingsWidget(self.db, self)
        self.stack.addWidget(self.dashboard_widget)
        self.stack.addWidget(self.inventory_widget)
        self.stack.addWidget(self.reports_widget)
        self.stack.addWidget(self.stock_widget)
        self.stack.addWidget(self.settings_widget)
        # connect
        btns['Dashboard'].clicked.connect(lambda: self.stack.setCurrentWidget(self.dashboard_widget))
        btns['Billing'].clicked.connect(self.open_billing)
        btns['Inventory'].clicked.connect(lambda: self.stack.setCurrentWidget(self.inventory_widget))
        btns['Reports'].clicked.connect(lambda: self.stack.setCurrentWidget(self.reports_widget))
        btns['Stock Inwards'].clicked.connect(lambda: self.stack.setCurrentWidget(self.stock_widget))
        btns['Settings'].clicked.connect(lambda: self.stack.setCurrentWidget(self.settings_widget))
        btns['Logout'].clicked.connect(QtWidgets.qApp.quit)
        self.billing_win = None

    def apply_theme(self, theme):
        if theme == 'dark':
            QtWidgets.QApplication.instance().setStyleSheet(STYLE_DARK)
        else:
            QtWidgets.QApplication.instance().setStyleSheet(STYLE_LIGHT)

    def open_billing(self):
        if self.billing_win is None or not self.billing_win.isVisible():
            self.billing_win = BillingWindow(self.db)
        self.billing_win.show(); self.billing_win.raise_(); self.billing_win.activateWindow()
        return self.billing_win

    def show_inventory(self):
        self.stack.setCurrentWidget(self.inventory_widget)

    def show_reports(self):
        self.stack.setCurrentWidget(self.reports_widget)

    def show_stock(self):
        self.stack.setCurrentWidget(self.stock_widget)

    def show_settings(self):
        self.stack.setCurrentWidget(self.settings_widget)

# ---------------- App bootstrap ----------------
def main():
    db = DB()
    seed_products(db, target=1100)
    app = QtWidgets.QApplication(sys.argv)
    # apply initial theme
    theme = db.get_setting('theme','light')
    if theme == 'dark':
        app.setStyleSheet(STYLE_DARK)
    else:
        app.setStyleSheet(STYLE_LIGHT)
    main_win = MainWindow(db)
    login = LoginWindow(db, main_win)
    login.show()
    main_win.hide()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
