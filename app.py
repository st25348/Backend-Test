from flask import Flask, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from functools import wraps
import os
import sqlite3
import json
import shutil

app = Flask(__name__)
app.secret_key = "ilikeheadphones"

# Configure SQLAlchemy
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///users.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# User model
class User(db.Model):
    id            = db.Column(db.Integer, primary_key=True)
    name          = db.Column(db.String(150), nullable=False)
    email         = db.Column(db.String(150), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

PROMO_CODES = {
    'AUDIO26': 0.20,
    'SAVE07':  0.10,
}

def load_data():
    try:
        with open('data/headphones.json') as f:
            headphones = json.load(f)
    except FileNotFoundError:
        headphones = {}
    try:
        with open('data/addons.json') as f:
            addons = json.load(f)
    except FileNotFoundError:
        addons = {}
    return headphones, addons

def calculate_total(cart):
    return sum(item['price'] * item['quantity'] for item in cart.values())

def invoice_db_path():
    os.makedirs(app.instance_path, exist_ok=True)
    return os.path.join(app.instance_path, 'invoices.db')

def invoice_folder_path():
    path = os.path.join(app.instance_path, 'invoices')
    os.makedirs(path, exist_ok=True)
    return path

def migrate_invoice_storage():
    os.makedirs(app.instance_path, exist_ok=True)

    old_db_path = 'invoices.db'
    new_db_path = invoice_db_path()
    if os.path.exists(old_db_path) and not os.path.exists(new_db_path):
        shutil.copy2(old_db_path, new_db_path)

    old_invoice_folder = 'invoices'
    new_invoice_folder = invoice_folder_path()
    if os.path.isdir(old_invoice_folder):
        for filename in os.listdir(old_invoice_folder):
            old_file_path = os.path.join(old_invoice_folder, filename)
            new_file_path = os.path.join(new_invoice_folder, filename)
            if os.path.isfile(old_file_path) and not os.path.exists(new_file_path):
                shutil.copy2(old_file_path, new_file_path)

def sign_in_user(user):
    session['user_id'] = user.id
    session['username'] = user.name

def current_user():
    user_id = session.get('user_id')
    if not user_id:
        return None
    return db.session.get(User, user_id)

def login_required(view_func):
    @wraps(view_func)
    def wrapped_view(*args, **kwargs):
        if not current_user():
            session.pop('user_id', None)
            session.pop('username', None)
            session['reopen_auth'] = 'login'
            flash("Please log in to continue.", 'login_error')
            return redirect(url_for('home'))
        return view_func(*args, **kwargs)
    return wrapped_view

def parse_quantity():
    try:
        quantity = int(request.form.get('quantity', ''))
    except (TypeError, ValueError):
        return None
    return quantity if quantity >= 1 else None

def validate_cart_stock(cart, headphones, addons):
    checked_cart = {}
    for item, details in cart.items():
        try:
            quantity = int(details.get('quantity', 0))
        except (TypeError, ValueError):
            return f"Please remove {item} and add it again with a valid quantity.", None

        if quantity < 1:
            return f"Please remove {item} and add it again with a valid quantity.", None

        color = details.get('color')
        if color is not None:
            product = headphones.get(item)
            if not product:
                return f"{item} is no longer available.", None
            if color not in product.get('colors', []):
                return f"{color} is not available for {item}.", None
            stock = product.get('stock', 0)
            if quantity > stock:
                return f"Only {stock} {item} available. Please update your cart.", None
            checked_cart[item] = {
                'price': product['price'],
                'quantity': quantity,
                'color': color,
            }
        else:
            addon = addons.get(item)
            if not addon:
                return f"{item} is no longer available.", None
            stock = addon.get('stock', 0)
            if quantity > stock:
                return f"Only {stock} {item} available. Please update your cart.", None
            checked_cart[item] = {
                'price': addon['price'],
                'quantity': quantity,
                'color': None,
            }

    return None, checked_cart

def initialize_data_base():
    try:
        migrate_invoice_storage()
        with sqlite3.connect(invoice_db_path()) as conn:
            cursor = conn.cursor()
            # Create table with savings + discount_label columns
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS orders (
                    id             INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id        INTEGER,
                    invoice_number TEXT NOT NULL,
                    customer_name  TEXT NOT NULL,
                    items          TEXT NOT NULL,
                    total          REAL NOT NULL,
                    savings        REAL NOT NULL DEFAULT 0,
                    discount_label TEXT,
                    date           TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            # Add columns to existing DB if upgrading from old schema
            try:
                cursor.execute('ALTER TABLE orders ADD COLUMN savings REAL NOT NULL DEFAULT 0')
            except sqlite3.OperationalError:
                pass
            try:
                cursor.execute('ALTER TABLE orders ADD COLUMN discount_label TEXT')
            except sqlite3.OperationalError:
                pass
            try:
                cursor.execute('ALTER TABLE orders ADD COLUMN user_id INTEGER')
            except sqlite3.OperationalError:
                pass
    except sqlite3.Error as e:
        print(f"Error initializing database: {e}")

# ── Routes ──────────────────────────────────────────────────────────

@app.route('/login', methods=['POST'])
def login():
    email    = request.form['email'].strip().lower()
    password = request.form['password']
    user     = User.query.filter_by(email=email).first()
    if user and user.check_password(password):
        sign_in_user(user)
        flash(f"Welcome back, {user.name}!", 'login_success')
        return redirect(url_for('home'))
    else:
        flash("Invalid email or password.", 'login_error')
        session['reopen_auth'] = 'login'
        return redirect(url_for('home'))

@app.route('/register', methods=['POST'])
def register():
    name     = request.form['name'].strip()
    email    = request.form['email'].strip().lower()
    password = request.form['password']
    confirm  = request.form['confirm_password']

    if password != confirm:
        flash("Passwords do not match.", 'register_error')
        session['reopen_auth'] = 'register'
        return redirect(url_for('home'))

    if User.query.filter_by(email=email).first():
        flash("Email already registered.", 'register_error')
        session['reopen_auth'] = 'register'
        return redirect(url_for('home'))

    new_user = User(name=name, email=email)
    new_user.set_password(password)
    db.session.add(new_user)
    db.session.commit()

    sign_in_user(new_user)
    flash(f"Account created for {new_user.name}!", 'register_success')
    return redirect(url_for('home'))

@app.route('/logout')
def logout():
    session.clear()
    flash("You've been logged out.", 'logout')
    return redirect(url_for('home'))

@app.route('/')
@app.route('/home')
def home():
    username       = session.get('username')
    headphones, addons = load_data()
    cart           = session.get('cart', {})
    total          = calculate_total(cart)
    promo_code     = session.get('promo_code', '')
    promo_discount = PROMO_CODES.get(promo_code, 0)
    reopen_auth    = session.pop('reopen_auth', None)   # consume once
    return render_template(
        'index.html',
        headphones     = headphones,
        addons         = addons,
        cart           = cart,
        total          = total,
        promo_code     = promo_code,
        promo_discount = promo_discount,
        username       = username,
        reopen_auth    = reopen_auth,
    )

@app.route('/add_to_cart', methods=['POST'])
def add_to_cart():
    headphones, addons = load_data()
    cart     = session.get('cart', {})
    quantity = parse_quantity()
    if quantity is None:
        flash("Please enter a valid quantity.", 'cart_error')
        return redirect(url_for('home'))

    if 'headphone' in request.form:
        item  = request.form['headphone']
        color = request.form.get('color', 'Default')
        if item not in headphones:
            flash("Invalid headphone selected.", 'cart_error')
            return redirect(url_for('home'))
        if color not in headphones[item].get('colors', []):
            flash("Invalid color selected.", 'cart_error')
            return redirect(url_for('home'))
        price = headphones[item]['price']
        stock = headphones[item].get('stock', 0)
    elif 'addon' in request.form:
        item = request.form['addon']
        if item not in addons:
            flash("Invalid addon selected.", 'cart_error')
            return redirect(url_for('home'))
        price = addons[item]['price']
        color = None
        stock = addons[item].get('stock', 0)
    else:
        flash("Invalid item selected.", 'cart_error')
        return redirect(url_for('home'))

    try:
        current_quantity = int(cart.get(item, {}).get('quantity', 0))
    except (AttributeError, TypeError, ValueError):
        current_quantity = 0
    if current_quantity + quantity > stock:
        stock_error_category = f"{item}_error"
        if current_quantity:
            flash(f"Only {stock} {item} available; you already have {current_quantity} in your cart.", stock_error_category)
        elif stock == 0:
            flash(f"{item} is out of stock.", stock_error_category)
        else:
            flash(f"Only {stock} {item} available.", stock_error_category)
        return redirect(url_for('home'))

    if item in cart:
        cart[item]['quantity'] += quantity
    else:
        cart[item] = {'price': price, 'quantity': quantity, 'color': color}

    session['cart']     = cart
    session.modified    = True
    flash(f"{quantity} x {item} added to cart.", item)
    return redirect(url_for('home'))

@app.route('/apply_promo', methods=['POST'])
def apply_promo():
    promo_code = request.form.get('promo_code', '').strip().upper()
    if promo_code in PROMO_CODES:
        session['promo_code'] = promo_code
        flash(f"Promo code {promo_code} applied — {int(PROMO_CODES[promo_code] * 100)}% off!", 'promo')
    else:
        session.pop('promo_code', None)
        flash("Invalid promo code.", 'promo_error')
    return redirect(url_for('home'))

@app.route('/remove_from_cart/<item>')
def remove_from_cart(item):
    cart = session.get('cart', {})
    if item in cart:
        del cart[item]
        session['cart']  = cart
        session.modified = True
        flash(f"Removed {item.capitalize()} from the cart.", 'removed')
    return redirect(url_for('home'))

@app.route('/checkout', methods=['POST'])
@login_required
def checkout():
    user = current_user()
    customer_name = request.form['customer_name_checkout'].strip().title()
    if not customer_name:
        flash("Customer name is required.", 'cart_error')
        return redirect(url_for('home'))

    cart = session.get('cart', {})
    if not cart:
        flash("Your cart is empty.", 'cart_error')
        return redirect(url_for('home'))

    headphones, addons = load_data()
    stock_error, checked_cart = validate_cart_stock(cart, headphones, addons)
    if stock_error:
        flash(stock_error, 'cart_error')
        return redirect(url_for('home'))

    cart = checked_cart
    session['cart'] = cart
    session.modified = True

    headphones_cart = {k: v for k, v in cart.items() if v['color'] is not None}
    addons_cart     = {k: v for k, v in cart.items() if v['color'] is None}
    subtotal        = calculate_total(cart)

    promo_code       = session.get('promo_code', '')
    promo_discount   = PROMO_CODES.get(promo_code, 0)
    order_discount   = 0.10 if subtotal >= 500 else 0
    airpods_discount = 0.10 if 'AirPods 3' in headphones_cart else 0

    discount = min(promo_discount + order_discount + airpods_discount, 0.40)
    savings  = round(subtotal * discount, 2)
    total    = round(subtotal - savings, 2)

    active_discounts = []
    if promo_discount:   active_discounts.append(f"Promo ({promo_code} -{int(promo_discount*100)}%)")
    if order_discount:   active_discounts.append("Order Over $500 -10%")
    if airpods_discount: active_discounts.append("AirPods 3 -10%")
    discount_label = " + ".join(active_discounts) if active_discounts else None

    invoice_date   = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    invoice_number = f"INV_{customer_name.replace(' ', '_')}_{invoice_date}"

    # Save to DB — now includes savings + discount_label
    try:
        with sqlite3.connect(invoice_db_path()) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO orders (user_id, invoice_number, customer_name, items, total, savings, discount_label)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (user.id, invoice_number, customer_name, json.dumps(cart), total, savings, discount_label))
            conn.commit()
    except sqlite3.Error as e:
        flash("Database error occurred.")
        print(f"SQLite error: {e}")
        return redirect(url_for('home'))

    # Write invoice file
    try:
        invoice_file_path = os.path.join(invoice_folder_path(), f"{invoice_number}.txt")
        with open(invoice_file_path, 'w') as f:
            f.write(f"Invoice Number: {invoice_number}\n")
            f.write(f"Customer Name: {customer_name}\n")
            f.write(f"Date: {invoice_date}\n\nItems:\n")
            for item, details in cart.items():
                color_info = f" ({details['color']})" if details['color'] else ""
                f.write(f"  - {item.capitalize()}{color_info}: ${details['price']} x {details['quantity']} = ${details['price'] * details['quantity']}\n")
            f.write(f"\nSubtotal: ${subtotal}\n")
            if discount_label:
                f.write(f"Discount — {discount_label} ({int(discount * 100)}%): -${savings}\n")
            f.write(f"Total: ${total}\n")
    except OSError as e:
        flash("Could not generate invoice file.")
        print(f"Error writing invoice: {e}")

    # Update headphone stock
    try:
        for item, details in headphones_cart.items():
            if item in headphones:
                headphones[item]['stock'] = max(0, headphones[item]['stock'] - details['quantity'])
        with open('data/headphones.json', 'w') as f:
            json.dump(headphones, f, indent=4)
    except OSError as e:
        print(f"Error updating headphones stock: {e}")

    # Update addon stock
    try:
        for item, details in addons_cart.items():
            if item in addons:
                addons[item]['stock'] = max(0, addons[item]['stock'] - details['quantity'])
        with open('data/addons.json', 'w') as f:
            json.dump(addons, f, indent=4)
    except OSError as e:
        print(f"Error updating addons stock: {e}")

    session['cart'] = {}
    session.pop('promo_code', None)
    session.modified = True

    return render_template(
        'invoice.html',
        customer_name   = customer_name,
        headphones_cart = headphones_cart,
        addons_cart     = addons_cart,
        subtotal        = subtotal,
        savings         = savings,
        total           = total,
        discount        = discount,
        discount_label  = discount_label,
        invoice_date    = invoice_date,
        invoice_number  = invoice_number,
    )

@app.route('/delete_order/<invoice_number>', methods=['POST'])
@login_required
def delete_order(invoice_number):
    with sqlite3.connect(invoice_db_path()) as conn:
        cursor = conn.cursor()
        cursor.execute(
            'DELETE FROM orders WHERE invoice_number = ? AND user_id = ?',
            (invoice_number, session['user_id'])
        )
        conn.commit()
        if cursor.rowcount:
            flash(f"Order {invoice_number} has been canceled.", 'canceled')
        else:
            flash("Order not found.", 'canceled')
    return redirect(url_for('orders'))

@app.route('/about')
def about():
    return render_template('about.html')

@app.route('/invoice/<invoice_number>')
@login_required
def view_invoice(invoice_number):
    with sqlite3.connect(invoice_db_path()) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT invoice_number, customer_name, items, total, savings, discount_label, date
            FROM orders WHERE invoice_number = ? AND user_id = ?
        ''', (invoice_number, session['user_id']))
        row = cursor.fetchone()

    if not row:
        flash("Invoice not found.")
        return redirect(url_for('orders'))

    cart            = json.loads(row[2])
    headphones_cart = {k: v for k, v in cart.items() if v['color'] is not None}
    addons_cart     = {k: v for k, v in cart.items() if v['color'] is None}
    savings         = row[4]
    discount_label  = row[5]
    subtotal        = round(row[3] + savings, 2)

    return render_template(
        'invoice.html',
        customer_name   = row[1],
        headphones_cart = headphones_cart,
        addons_cart     = addons_cart,
        subtotal        = subtotal,
        savings         = savings,
        total           = row[3],
        discount        = round(savings / subtotal, 2) if subtotal else 0,
        discount_label  = discount_label,
        invoice_date    = row[6],
        invoice_number  = row[0],
    )

@app.route('/orders')
@login_required
def orders():
    with sqlite3.connect(invoice_db_path()) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT invoice_number, customer_name, items, total, date
            FROM orders
            WHERE user_id = ?
            ORDER BY date DESC
        ''', (session['user_id'],))
        rows = cursor.fetchall()
    orders_list = [
        {
            'invoice_number': row[0],
            'customer_name':  row[1],
            'items':          json.loads(row[2]),
            'total':          row[3],
            'date':           row[4],
        }
        for row in rows
    ]
    return render_template('orders.html', orders=orders_list)

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    initialize_data_base()
    app.run(debug=True)
