from flask import Flask, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import os
import sqlite3
import json

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

def initialize_data_base():
    try:
        with sqlite3.connect('invoices.db') as conn:
            cursor = conn.cursor()
            # Create table with savings + discount_label columns
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS orders (
                    id             INTEGER PRIMARY KEY AUTOINCREMENT,
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
    except sqlite3.Error as e:
        print(f"Error initializing database: {e}")

# ── Routes ──────────────────────────────────────────────────────────

@app.route('/login', methods=['POST'])
def login():
    email    = request.form['email'].strip().lower()
    password = request.form['password']
    user     = User.query.filter_by(email=email).first()
    if user and user.check_password(password):
        session['username'] = user.name
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

    session['username'] = new_user.name
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
    quantity = int(request.form['quantity'])

    if 'headphone' in request.form:
        item  = request.form['headphone']
        color = request.form.get('color', 'Default')
        if item not in headphones:
            flash("Invalid headphone selected.", item)
            return redirect(url_for('home'))
        price = headphones[item]['price']
    elif 'addon' in request.form:
        item = request.form['addon']
        if item not in addons:
            flash("Invalid addon selected.", item)
            return redirect(url_for('home'))
        price = addons[item]['price']
        color = None

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
def checkout():
    customer_name = request.form['customer_name_checkout'].strip().title()
    if not customer_name:
        flash("Customer name is required.")
        return redirect(url_for('home'))

    cart = session.get('cart', {})
    if not cart:
        flash("Your cart is empty.")
        return redirect(url_for('home'))

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
        with sqlite3.connect('invoices.db') as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO orders (invoice_number, customer_name, items, total, savings, discount_label)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (invoice_number, customer_name, json.dumps(cart), total, savings, discount_label))
            conn.commit()
    except sqlite3.Error as e:
        flash("Database error occurred.")
        print(f"SQLite error: {e}")
        return redirect(url_for('home'))

    # Write invoice file
    try:
        os.makedirs('invoices', exist_ok=True)
        with open(f"invoices/{invoice_number}.txt", 'w') as f:
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
        with open('data/headphones.json', 'r') as f:
            headphones = json.load(f)
        for item, details in headphones_cart.items():
            if item in headphones:
                headphones[item]['stock'] = max(0, headphones[item]['stock'] - details['quantity'])
        with open('data/headphones.json', 'w') as f:
            json.dump(headphones, f, indent=4)
    except OSError as e:
        print(f"Error updating headphones stock: {e}")

    # Update addon stock
    try:
        with open('data/addons.json', 'r') as f:
            addons = json.load(f)
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
def delete_order(invoice_number):
    with sqlite3.connect('invoices.db') as conn:
        cursor = conn.cursor()
        cursor.execute('DELETE FROM orders WHERE invoice_number = ?', (invoice_number,))
        conn.commit()
        flash(f"Order {invoice_number} has been canceled.", 'canceled')
    return redirect(url_for('orders'))

@app.route('/about')
def about():
    return render_template('about.html')

@app.route('/invoice/<invoice_number>')
def view_invoice(invoice_number):
    with sqlite3.connect('invoices.db') as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT invoice_number, customer_name, items, total, savings, discount_label, date
            FROM orders WHERE invoice_number = ?
        ''', (invoice_number,))
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
def orders():
    with sqlite3.connect('invoices.db') as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT invoice_number, customer_name, items, total, date FROM orders ORDER BY date DESC')
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