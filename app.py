from flask import Flask, render_template, request, redirect, url_for, session, flash
from datetime import datetime
import os
import sqlite3
import json

app = Flask(__name__)
app.secret_key = "ilikeheadphones"

PROMO_CODES = {
    'AUDIO26': 0.20,
    'SAVE07':  0.10,
}

def load_data():
    try:
        with open('data/headphones.json') as file:
            headphones = json.load(file)
    except FileNotFoundError:
        headphones = {}
    try:
        with open('data/addons.json') as file:
            addons = json.load(file)
    except FileNotFoundError:
        addons = {}
    return headphones, addons

def calculate_total(cart):
    total = sum(item['price'] * item['quantity'] for item in cart.values())
    return total

def initialize_data_base():
    try:
        with sqlite3.connect('headphones.db') as conn:
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS orders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    invoice_number TEXT NOT NULL,
                    customer_name TEXT NOT NULL,
                    items TEXT NOT NULL,
                    total REAL NOT NULL,
                    date timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            ''')
    except sqlite3.Error as e:
        print(f"Error initializing database: {e}")

@app.route('/')
@app.route('/home')
def home():
    headphones, addons = load_data()
    cart           = session.get('cart', {})
    total          = calculate_total(cart)
    promo_code     = session.get('promo_code', '')
    promo_discount = PROMO_CODES.get(promo_code, 0)
    return render_template('index.html', headphones=headphones, addons=addons, cart=cart, total=total, promo_code=promo_code, promo_discount=promo_discount)

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
        cart[item] = {
            'price':    price,
            'quantity': quantity,
            'color':    color
        }

    session['cart'] = cart
    session.modified = True
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
        session['cart'] = cart
        session.modified = True
        flash(f"Removed {item.capitalize()} from the cart.", 'removed')
    return redirect(url_for('home'))

@app.route('/checkout', methods=['POST'])
def checkout():
    # Validate customer name
    customer_name = request.form['customer_name_checkout'].strip().title()
    if not customer_name:
        flash("Customer name is required.")
        return redirect(url_for('home'))

    # Get cart
    cart = session.get('cart', {})
    if not cart:
        flash("Your cart is empty.")
        return redirect(url_for('home'))

    headphones_cart = {k: v for k, v in cart.items() if v['color'] is not None}
    addons_cart     = {k: v for k, v in cart.items() if v['color'] is None}

    subtotal = calculate_total(cart)

    # Discount 1 — promo code
    promo_code     = session.get('promo_code', '')
    promo_discount = PROMO_CODES.get(promo_code, 0)

    # Discount 2 — order over $500
    order_discount = 0.10 if subtotal >= 500 else 0

    # Discount 3 — AirPods 3 in cart
    headphone26_discount = 0.10 if 'AirPods 3' in headphones_cart else 0

    # Apply the best discount
    discount = max(promo_discount, order_discount, headphone26_discount)
    savings  = round(subtotal * discount, 2)
    total    = round(subtotal - savings, 2)

    # Discount label for invoice
    if discount == 0:
        discount_label = None
    elif promo_code and promo_discount == discount:
        discount_label = f"Promo Code ({promo_code})"
    elif order_discount == discount:
        discount_label = "Order Over $500"
    else:
        discount_label = "AirPods 3 Discount"

    invoice_date   = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    invoice_number = f"INV_{customer_name.replace(' ', '_')}_{invoice_date}"

    # Save to database
    try:
        with sqlite3.connect('headphones.db') as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO orders (invoice_number, customer_name, items, total)
                VALUES (?, ?, ?, ?)
            ''', (invoice_number, customer_name, json.dumps(cart), total))
            conn.commit()
    except sqlite3.Error as e:
        flash("Database error occurred.")
        print(f"SQLite error: {e}")
        return redirect(url_for('home'))

    # Write invoice file
    try:
        os.makedirs('invoices', exist_ok=True)
        invoice_filename = f"invoices/{invoice_number}.txt"
        with open(invoice_filename, 'w') as file:
            file.write(f"Invoice Number: {invoice_number}\n")
            file.write(f"Customer Name: {customer_name}\n")
            file.write(f"Date: {invoice_date}\n")
            file.write("\nItems:\n")
            for item, details in cart.items():
                color_info = f" ({details['color']})" if details['color'] else ""
                file.write(f"  - {item.capitalize()}{color_info}: ${details['price']} x {details['quantity']} = ${details['price'] * details['quantity']}\n")
            file.write(f"\nSubtotal: ${subtotal}\n")
            if discount_label:
                file.write(f"Discount — {discount_label} ({int(discount * 100)}%): -${savings}\n")
            file.write(f"Total: ${total}\n")
    except OSError as e:
        flash("Could not generate invoice file.")
        print(f"Error writing invoice: {e}")

    # Update stock — headphones
    try:
        with open('data/headphones.json', 'r') as file:
            headphones = json.load(file)
        for item, details in headphones_cart.items():
            if item in headphones:
                headphones[item]['stock'] = max(0, headphones[item]['stock'] - details['quantity'])
        with open('data/headphones.json', 'w') as file:
            json.dump(headphones, file, indent=4)
    except OSError as e:
        flash("Could not update stock file.")
        print(f"Error updating headphones stock: {e}")

    # Update stock — addons
    try:
        with open('data/addons.json', 'r') as file:
            addons = json.load(file)
        for item, details in addons_cart.items():
            if item in addons:
                addons[item]['stock'] = max(0, addons[item]['stock'] - details['quantity'])
        with open('data/addons.json', 'w') as file:
            json.dump(addons, file, indent=4)
    except OSError as e:
        flash("Could not update stock file.")
        print(f"Error updating addons stock: {e}")

    # Clear cart and promo code after checkout
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
    with sqlite3.connect('headphones.db') as conn:
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
    with sqlite3.connect('headphones.db') as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT invoice_number, customer_name, items, total, date
            FROM orders WHERE invoice_number = ?
        ''', (invoice_number,))
        row = cursor.fetchone()

    if not row:
        flash("Invoice not found.")
        return redirect(url_for('orders'))

    cart            = json.loads(row[2])
    headphones_cart = {k: v for k, v in cart.items() if v['color'] is not None}
    addons_cart     = {k: v for k, v in cart.items() if v['color'] is None}

    return render_template(
        'invoice.html',
        customer_name   = row[1],
        headphones_cart = headphones_cart,
        addons_cart     = addons_cart,
        subtotal        = row[3],
        savings         = 0,
        total           = row[3],
        discount        = 0,
        discount_label  = None,
        invoice_date    = row[4],
        invoice_number  = row[0],
    )

@app.route('/orders')
def orders():
    with sqlite3.connect('headphones.db') as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT invoice_number, customer_name, items, total, date FROM orders ORDER BY date DESC')
        rows = cursor.fetchall()
    orders_list = []
    for row in rows:
        orders_list.append({
            'invoice_number': row[0],
            'customer_name':  row[1],
            'items':          json.loads(row[2]),
            'total':          row[3],
            'date':           row[4]
        })
    return render_template('orders.html', orders=orders_list)

if __name__ == '__main__':
    initialize_data_base()
    app.run(debug=True)