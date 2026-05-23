from flask import Flask, render_template, request, redirect, url_for, session, flash, Response
from werkzeug.security import generate_password_hash, check_password_hash
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from functools import wraps
import os
import sqlite3
import json
import shutil
from io import BytesIO

app = Flask(__name__)
app.secret_key = "ilikeheadphones"
ADMIN_SECRET_KEY = os.environ.get('ADMIN_SECRET_KEY', 'headphonesforlife')

app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///users.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# user model
class User(db.Model):
    id            = db.Column(db.Integer, primary_key=True)
    name          = db.Column(db.String(150), nullable=False)
    email         = db.Column(db.String(150), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    is_admin      = db.Column(db.Boolean, nullable=False, default=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


PROMO_CODES = {
    'AUDIO26': 0.20,
    'SAVE07':  0.10,
}


# db paths
def orders_db_path():
    os.makedirs(app.instance_path, exist_ok=True)
    return os.path.join(app.instance_path, 'orders.db')

def reviews_db_path():
    os.makedirs(app.instance_path, exist_ok=True)
    return os.path.join(app.instance_path, 'community_reviews.db')

def votes_db_path():
    os.makedirs(app.instance_path, exist_ok=True)
    return os.path.join(app.instance_path, 'product_votes.db')

def feedback_db_path():
    os.makedirs(app.instance_path, exist_ok=True)
    return os.path.join(app.instance_path, 'feedback.db')

def invoice_folder_path():
    path = os.path.join(app.instance_path, 'invoices')
    os.makedirs(path, exist_ok=True)
    return path


# load json data
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

def save_headphones(headphones):
    with open('data/headphones.json', 'w') as f:
        json.dump(headphones, f, indent=4)


# parse and validate product form
def parse_product_form():
    name        = request.form.get('name', '').strip()
    description = request.form.get('description', '').strip()
    image       = request.form.get('image', '').strip()
    colors      = [c.strip() for c in request.form.get('colors', '').split(',') if c.strip()]

    try:
        price = float(request.form.get('price', ''))
        stock = int(request.form.get('stock', ''))
    except (TypeError, ValueError):
        return None, "Price and stock must be valid numbers."

    if not name:             return None, "Product name is required."
    if price < 0 or stock < 0: return None, "Price and stock cannot be negative."
    if not description:      return None, "Description is required."
    if not image:            return None, "Image URL is required."
    if not colors:           return None, "Add at least one color."

    if price.is_integer():
        price = int(price)

    return {
        'name': name,
        'details': {
            'price': price, 'stock': stock,
            'description': description, 'image': image, 'colors': colors,
        }
    }, None


# cart helpers
def calculate_total(cart):
    return sum(item['price'] * item['quantity'] for item in cart.values())

def cart_redirect():
    target = request.form.get('next') or request.referrer or url_for('home')
    return redirect(target)

def load_featured_products(headphones, limit=4):
    return dict(list(headphones.items())[:limit])


# fallback testimonials
def default_testimonials():
    return [
        {'name': 'Maya Chen',    'product': 'Sony WH-1000XM5',     'rating': 5, 'quote': 'The noise cancellation made my commute feel calm for the first time in years.'},
        {'name': 'Noah Patel',   'product': 'AirPods Pro',          'rating': 5, 'quote': 'Crisp sound, fast delivery, and the fit is perfect for long work sessions.'},
        {'name': 'Ava Thompson', 'product': 'Bose QuietComfort 45', 'rating': 4, 'quote': 'Lightweight, comfortable, and exactly the upgrade I wanted for travel.'},
    ]


# pull public reviews
def get_public_testimonials(limit=None):
    testimonials = []
    try:
        with sqlite3.connect(reviews_db_path()) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            query = '''
                SELECT customer_name, product_name, rating, review_text, created_at
                FROM community_reviews
                WHERE rating >= 4 AND review_text != ''
                ORDER BY created_at DESC
            '''
            if limit:
                query += ' LIMIT ?'
                rows = cursor.execute(query, (limit,)).fetchall()
            else:
                rows = cursor.execute(query).fetchall()
            testimonials = [
                {'name': row['customer_name'], 'product': row['product_name'],
                 'rating': row['rating'], 'quote': row['review_text']}
                for row in rows
            ]
    except sqlite3.Error:
        testimonials = []

    if not testimonials:
        testimonials = default_testimonials()
    return testimonials[:limit] if limit else testimonials


# votes and ratings per product
def get_product_feedback(headphones):
    feedback = {name: {'votes': 0, 'average_rating': 0, 'rating_count': 0} for name in headphones}

    try:
        with sqlite3.connect(votes_db_path()) as conn:
            cursor = conn.cursor()
            for product, votes in cursor.execute('SELECT product_name, votes FROM product_votes'):
                if product in feedback:
                    feedback[product]['votes'] = votes
    except sqlite3.Error:
        pass

    try:
        with sqlite3.connect(reviews_db_path()) as conn:
            cursor = conn.cursor()
            for product, rating_total, rating_count in cursor.execute('''
                SELECT product_name, SUM(rating), COUNT(*)
                FROM community_reviews
                GROUP BY product_name
            '''):
                if product in feedback and rating_count:
                    feedback[product]['average_rating'] = round(rating_total / rating_count, 1)
                    feedback[product]['rating_count'] = rating_count
    except sqlite3.Error:
        pass

    return feedback


# fetch single order for current user
def get_order_for_user(invoice_number):
    with sqlite3.connect(orders_db_path()) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT invoice_number, customer_name, items, total, savings, discount_label, date
            FROM orders WHERE invoice_number = ? AND user_id = ?
        ''', (invoice_number, session['user_id']))
        return cursor.fetchone()


# format invoice as plain text
def invoice_text(row):
    cart     = json.loads(row[2])
    savings  = row[4] or 0
    subtotal = round(row[3] + savings, 2)
    lines    = [
        f"Invoice Number: {row[0]}", f"Customer Name: {row[1]}", f"Date: {row[6]}", "", "Items:",
    ]
    for item, details in cart.items():
        color_info = f" ({details['color']})" if details.get('color') else ""
        lines.append(f"  - {item}{color_info}: ${details['price']} x {details['quantity']} = ${details['price'] * details['quantity']}")
    lines.extend(["", f"Subtotal: ${subtotal}"])
    if row[5]:
        lines.append(f"Discount - {row[5]}: -${savings}")
    lines.append(f"Total: ${row[3]}")
    return "\n".join(lines) + "\n"


# build a minimal pdf in memory
def simple_pdf_bytes(title, body):
    text  = body.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')
    lines = text.splitlines()
    content_lines = ["BT", "/F1 11 Tf", "50 770 Td", f"({title}) Tj", "0 -24 Td"]
    for line in lines[:45]:
        content_lines.append(f"({line[:95]}) Tj")
        content_lines.append("0 -16 Td")
    content_lines.append("ET")
    stream  = "\n".join(content_lines)
    objects = [
        "1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n",
        "2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n",
        "3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >> endobj\n",
        "4 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj\n",
        f"5 0 obj << /Length {len(stream.encode('utf-8'))} >> stream\n{stream}\nendstream endobj\n",
    ]
    output = BytesIO()
    output.write(b"%PDF-1.4\n")
    offsets = []
    for obj in objects:
        offsets.append(output.tell())
        output.write(obj.encode('utf-8'))
    xref = output.tell()
    output.write(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode('utf-8'))
    for offset in offsets:
        output.write(f"{offset:010d} 00000 n \n".encode('utf-8'))
    output.write(f"trailer << /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode('utf-8'))
    return output.getvalue()


# migrate old invoices.db and folder to instance/
def migrate_invoice_storage():
    os.makedirs(app.instance_path, exist_ok=True)
    old_db = 'invoices.db'
    new_db = orders_db_path()
    if os.path.exists(old_db) and not os.path.exists(new_db):
        shutil.copy2(old_db, new_db)
    old_folder = 'invoices'
    new_folder = invoice_folder_path()
    if os.path.isdir(old_folder):
        for filename in os.listdir(old_folder):
            old_file = os.path.join(old_folder, filename)
            new_file = os.path.join(new_folder, filename)
            if os.path.isfile(old_file) and not os.path.exists(new_file):
                shutil.copy2(old_file, new_file)


# db init
def init_orders_db():
    with sqlite3.connect(orders_db_path()) as conn:
        cursor = conn.cursor()
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
        for col in ('savings REAL NOT NULL DEFAULT 0', 'discount_label TEXT', 'user_id INTEGER'):
            try:
                cursor.execute(f'ALTER TABLE orders ADD COLUMN {col}')
            except sqlite3.OperationalError:
                pass

def init_reviews_db():
    with sqlite3.connect(reviews_db_path()) as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS community_reviews (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                product_name  TEXT NOT NULL,
                customer_name TEXT NOT NULL,
                rating        INTEGER NOT NULL,
                review_text   TEXT NOT NULL,
                created_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        ''')

def init_votes_db():
    with sqlite3.connect(votes_db_path()) as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS product_votes (
                product_name TEXT PRIMARY KEY,
                votes        INTEGER NOT NULL DEFAULT 0
            )
        ''')

def init_feedback_db():
    with sqlite3.connect(feedback_db_path()) as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS feedback_messages (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                name       TEXT NOT NULL,
                email      TEXT NOT NULL,
                message    TEXT NOT NULL,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        ''')

def initialize_data_base():
    try:
        migrate_invoice_storage()
        init_orders_db()
        init_reviews_db()
        init_votes_db()
        init_feedback_db()
    except sqlite3.Error as e:
        print(f"Error initializing databases: {e}")

def migrate_user_database():
    db.create_all()
    try:
        with sqlite3.connect(os.path.join(app.instance_path, 'users.db')) as conn:
            cursor = conn.cursor()
            try:
                cursor.execute('ALTER TABLE user ADD COLUMN is_admin BOOLEAN NOT NULL DEFAULT 0')
                conn.commit()
            except sqlite3.OperationalError:
                pass
    except sqlite3.Error as e:
        print(f"Error updating users database: {e}")


# session helpers
def sign_in_user(user):
    session['user_id']    = user.id
    session['username']   = user.name
    session['user_email'] = user.email
    session['is_admin']   = bool(user.is_admin)

def current_user():
    user_id = session.get('user_id')
    if not user_id:
        return None
    return db.session.get(User, user_id)

@app.before_request
def sync_session_user_details():
    if session.get('user_id') and (not session.get('user_email') or 'is_admin' not in session):
        user = current_user()
        if user:
            session['username']   = user.name
            session['user_email'] = user.email
            session['is_admin']   = bool(user.is_admin)

@app.context_processor
def inject_global_cart():
    cart       = session.get('cart', {})
    promo_code = session.get('promo_code', '')
    return {
        'cart':            cart,
        'cart_item_count': sum(int(item.get('quantity', 0)) for item in cart.values()),
        'total':           calculate_total(cart),
        'promo_code':      promo_code,
        'promo_discount':  PROMO_CODES.get(promo_code, 0),
        'reopen_auth':     session.get('reopen_auth', ''),
    }


# auth decorators
def login_required(view_func):
    @wraps(view_func)
    def wrapped_view(*args, **kwargs):
        if not current_user():
            session.pop('user_id', None)
            session.pop('username', None)
            session.pop('user_email', None)
            session.pop('is_admin', None)
            session['reopen_auth'] = 'login'
            flash("Please log in to continue.", 'login_error')
            return redirect(url_for('home'))
        return view_func(*args, **kwargs)
    return wrapped_view

def admin_required(view_func):
    @wraps(view_func)
    @login_required
    def wrapped_view(*args, **kwargs):
        user = current_user()
        if not user or not user.is_admin:
            flash("Admin access is required.", 'profile_admin_error')
            return redirect(url_for('home'))
        return view_func(*args, **kwargs)
    return wrapped_view


# cart validation
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
            checked_cart[item] = {'price': product['price'], 'quantity': quantity, 'color': color}
        else:
            addon = addons.get(item)
            if not addon:
                return f"{item} is no longer available.", None
            stock = addon.get('stock', 0)
            if quantity > stock:
                return f"Only {stock} {item} available. Please update your cart.", None
            checked_cart[item] = {'price': addon['price'], 'quantity': quantity, 'color': None}

    return None, checked_cart


# routes
@app.route('/login', methods=['POST'])
def login():
    email    = request.form['email'].strip().lower()
    password = request.form['password']
    user     = User.query.filter_by(email=email).first()
    if user and user.check_password(password):
        sign_in_user(user)
        flash(f"Welcome back, {user.name}!", 'login_success')
        return redirect(url_for('home'))
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

@app.route('/become_admin', methods=['POST'])
@login_required
def become_admin():
    secret_key = request.form.get('admin_secret', '').strip()
    if secret_key != ADMIN_SECRET_KEY:
        flash("That admin key is not correct.", 'profile_admin_error')
        return redirect(url_for('home'))
    user = current_user()
    user.is_admin = True
    db.session.commit()
    session['is_admin'] = True
    flash("Admin access unlocked.", 'admin_access')
    return redirect(url_for('admin'))

@app.route('/admin')
@admin_required
def admin():
    headphones, _ = load_data()
    return render_template('admin.html', headphones=headphones)

@app.route('/admin/products/add', methods=['POST'])
@admin_required
def add_product():
    product, error = parse_product_form()
    if error:
        flash(error, 'admin_error')
        return redirect(url_for('admin'))
    headphones, _ = load_data()
    if product['name'] in headphones:
        flash("A product with that name already exists.", 'admin_error')
        return redirect(url_for('admin'))
    headphones[product['name']] = product['details']
    try:
        save_headphones(headphones)
        flash(f"{product['name']} was added.", 'admin_success')
    except OSError:
        flash("Could not save the new product.", 'admin_error')
    return redirect(url_for('admin'))

@app.route('/admin/products/<path:product_name>/update', methods=['POST'])
@admin_required
def update_product(product_name):
    product, error = parse_product_form()
    if error:
        flash(error, 'admin_error')
        return redirect(url_for('admin'))
    headphones, _ = load_data()
    if product_name not in headphones:
        flash("Product not found.", 'admin_error')
        return redirect(url_for('admin'))
    if product['name'] != product_name and product['name'] in headphones:
        flash("Another product already uses that name.", 'admin_error')
        return redirect(url_for('admin'))
    if product['name'] != product_name:
        headphones.pop(product_name)
    headphones[product['name']] = product['details']
    try:
        save_headphones(headphones)
        flash(f"{product['name']} was updated.", 'admin_success')
    except OSError:
        flash("Could not save product changes.", 'admin_error')
    return redirect(url_for('admin'))

@app.route('/')
@app.route('/home')
def home():
    username           = session.get('username')
    headphones, addons = load_data()
    reopen_auth        = session.pop('reopen_auth', None)
    return render_template(
        'index.html',
        headphones   = headphones,
        featured     = load_featured_products(headphones),
        testimonials = get_public_testimonials(6),
        username     = username,
        reopen_auth  = reopen_auth,
    )

@app.route('/catalog')
def catalog():
    headphones, addons = load_data()
    reopen_auth = session.pop('reopen_auth', None)
    brands = sorted({name.split()[0] for name in headphones})
    colors = sorted({color for details in headphones.values() for color in details.get('colors', [])})
    return render_template(
        'catalog.html',
        headphones  = headphones,
        addons      = addons,
        brands      = brands,
        colors      = colors,
        reopen_auth = reopen_auth,
    )

@app.route('/community')
def community():
    headphones, _ = load_data()
    reopen_auth   = session.pop('reopen_auth', None)
    return render_template(
        'community.html',
        headphones   = headphones,
        feedback     = get_product_feedback(headphones),
        testimonials = get_public_testimonials(),
        reopen_auth  = reopen_auth,
    )

@app.route('/community/vote', methods=['POST'])
def community_vote():
    product_name  = request.form.get('product_name', '').strip()
    headphones, _ = load_data()
    if product_name not in headphones:
        flash("Product not found.", 'community_error')
        return redirect(url_for('community'))
    with sqlite3.connect(votes_db_path()) as conn:
        conn.execute('''
            INSERT INTO product_votes (product_name, votes)
            VALUES (?, 1)
            ON CONFLICT(product_name) DO UPDATE SET votes = votes + 1
        ''', (product_name,))
        conn.commit()
    flash(f"Vote counted for {product_name}.", 'community_success')
    return redirect(url_for('community'))

@app.route('/community/review', methods=['POST'])
def community_review():
    product_name  = request.form.get('product_name', '').strip()
    customer_name = request.form.get('customer_name', '').strip()
    review_text   = request.form.get('review_text', '').strip()
    try:
        rating = int(request.form.get('rating', '5'))
    except ValueError:
        rating = 5
    headphones, _ = load_data()
    if product_name not in headphones or rating < 1 or rating > 5 or not customer_name:
        flash("Please choose a product, name, and rating.", 'community_error')
        return redirect(url_for('community'))
    with sqlite3.connect(reviews_db_path()) as conn:
        conn.execute('''
            INSERT INTO community_reviews (product_name, customer_name, rating, review_text)
            VALUES (?, ?, ?, ?)
        ''', (product_name, customer_name, rating, review_text))
        conn.commit()
    flash("Thanks for sharing your rating.", 'community_success')
    return redirect(url_for('community'))

@app.route('/community/feedback', methods=['POST'])
def community_feedback():
    name    = request.form.get('name', '').strip()
    email   = request.form.get('email', '').strip()
    message = request.form.get('message', '').strip()
    if not name or not email or not message:
        flash("Please complete every feedback field.", 'community_error')
        return redirect(url_for('community'))
    with sqlite3.connect(feedback_db_path()) as conn:
        conn.execute('''
            INSERT INTO feedback_messages (name, email, message)
            VALUES (?, ?, ?)
        ''', (name, email, message))
        conn.commit()
    flash("Feedback submitted. Thank you.", 'community_success')
    return redirect(url_for('community'))

@app.route('/add_to_cart', methods=['POST'])
def add_to_cart():
    headphones, addons = load_data()
    cart     = session.get('cart', {})
    quantity = parse_quantity()
    if quantity is None:
        flash("Please enter a valid quantity.", 'cart_error')
        return cart_redirect()

    if 'headphone' in request.form:
        item  = request.form['headphone']
        color = request.form.get('color', 'Default')
        if item not in headphones:
            flash("Invalid headphone selected.", 'cart_error')
            return cart_redirect()
        if color not in headphones[item].get('colors', []):
            flash("Invalid color selected.", 'cart_error')
            return cart_redirect()
        price = headphones[item]['price']
        stock = headphones[item].get('stock', 0)
    elif 'addon' in request.form:
        item  = request.form['addon']
        if item not in addons:
            flash("Invalid addon selected.", 'cart_error')
            return cart_redirect()
        price = addons[item]['price']
        color = None
        stock = addons[item].get('stock', 0)
    else:
        flash("Invalid item selected.", 'cart_error')
        return cart_redirect()

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
        return cart_redirect()

    if item in cart:
        cart[item]['quantity'] += quantity
    else:
        cart[item] = {'price': price, 'quantity': quantity, 'color': color}

    session['cart']  = cart
    session.modified = True
    flash(f"{quantity} x {item} added to cart.", item)
    return cart_redirect()

@app.route('/apply_promo', methods=['POST'])
def apply_promo():
    promo_code = request.form.get('promo_code', '').strip().upper()
    if promo_code in PROMO_CODES:
        session['promo_code'] = promo_code
        flash(f"Promo code {promo_code} applied — {int(PROMO_CODES[promo_code] * 100)}% off!", 'promo')
    else:
        session.pop('promo_code', None)
        flash("Invalid promo code.", 'promo_error')
    return cart_redirect()

@app.route('/remove_from_cart/<item>')
def remove_from_cart(item):
    cart = session.get('cart', {})
    if item in cart:
        del cart[item]
        session['cart']  = cart
        session.modified = True
        flash(f"Removed {item.capitalize()} from the cart.", 'removed')
    return redirect(request.referrer or url_for('home'))

@app.route('/checkout', methods=['POST'])
@login_required
def checkout():
    user          = current_user()
    customer_name = request.form['customer_name_checkout'].strip().title()
    if not customer_name:
        flash("Customer name is required.", 'cart_error')
        return redirect(request.referrer or url_for('home'))

    cart = session.get('cart', {})
    if not cart:
        flash("Your cart is empty.", 'cart_error')
        return redirect(request.referrer or url_for('home'))

    headphones, addons = load_data()
    stock_error, checked_cart = validate_cart_stock(cart, headphones, addons)
    if stock_error:
        flash(stock_error, 'cart_error')
        return redirect(request.referrer or url_for('home'))

    cart             = checked_cart
    session['cart']  = cart
    session.modified = True

    headphones_cart  = {k: v for k, v in cart.items() if v['color'] is not None}
    addons_cart      = {k: v for k, v in cart.items() if v['color'] is None}
    subtotal         = calculate_total(cart)

    # discounts
    promo_code       = session.get('promo_code', '')
    promo_discount   = PROMO_CODES.get(promo_code, 0)
    order_discount   = 0.10 if subtotal >= 500 else 0
    airpods_discount = 0.10 if 'AirPods 3' in headphones_cart else 0
    discount         = min(promo_discount + order_discount + airpods_discount, 0.40)
    savings          = round(subtotal * discount, 2)
    total            = round(subtotal - savings, 2)

    active_discounts = []
    if promo_discount:   active_discounts.append(f"Promo ({promo_code} -{int(promo_discount*100)}%)")
    if order_discount:   active_discounts.append("Order Over $500 -10%")
    if airpods_discount: active_discounts.append("AirPods 3 -10%")
    discount_label = " + ".join(active_discounts) if active_discounts else None

    invoice_date   = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    invoice_number = f"INV_{customer_name.replace(' ', '_')}_{invoice_date}"

    # save order
    try:
        with sqlite3.connect(orders_db_path()) as conn:
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

    # write invoice file
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

    # update stock
    try:
        for item, details in headphones_cart.items():
            if item in headphones:
                headphones[item]['stock'] = max(0, headphones[item]['stock'] - details['quantity'])
        with open('data/headphones.json', 'w') as f:
            json.dump(headphones, f, indent=4)
    except OSError as e:
        print(f"Error updating headphones stock: {e}")

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
    with sqlite3.connect(orders_db_path()) as conn:
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

@app.route('/invoice/<invoice_number>')
@login_required
def view_invoice(invoice_number):
    row = get_order_for_user(invoice_number)
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
    with sqlite3.connect(orders_db_path()) as conn:
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

@app.route('/orders/<invoice_number>/download/<file_type>')
@login_required
def download_invoice(invoice_number, file_type):
    row = get_order_for_user(invoice_number)
    if not row:
        flash("Invoice not found.", 'orders_error')
        return redirect(url_for('orders'))

    text         = invoice_text(row)
    safe_invoice = invoice_number.replace('/', '_')

    if file_type == 'txt':
        return Response(
            text,
            mimetype='text/plain',
            headers={'Content-Disposition': f'attachment; filename="{safe_invoice}.txt"'},
        )
    if file_type == 'pdf':
        return Response(
            simple_pdf_bytes('AudioZone Invoice', text),
            mimetype='application/pdf',
            headers={'Content-Disposition': f'attachment; filename="{safe_invoice}.pdf"'},
        )

    flash("Unsupported download type.", 'orders_error')
    return redirect(url_for('orders'))


# startup
with app.app_context():
    migrate_user_database()
initialize_data_base()

if __name__ == '__main__':
    app.run(debug=True)