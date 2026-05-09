from datetime import datetime

from flask import Flask, render_template, request, redirect, url_for, session, flash
import json

app = Flask(__name__)
app.secret_key = "ilikeheadphones"

def load_data():
    with open('data/headphones.json') as file:
        headphones = json.load(file)
    with open('data/addons.json') as file:
        addons = json.load(file)
    return headphones, addons

def calculate_total(cart):
    total = sum(item['price'] * item['quantity'] for item in cart.values())
    return total

@app.route('/')
@app.route('/home')
def home():
    headphones, addons = load_data()
    cart = session.get('cart', {})
    total = calculate_total(cart)
    return render_template('index.html', headphones=headphones, addons=addons, cart=cart, total=total)

@app.route('/add_to_cart', methods=['POST'])
def add_to_cart():
    headphones, addons = load_data()
    cart = session.get('cart', {})
    quantity = int(request.form['quantity'])

    if 'headphone' in request.form:
        item = request.form['headphone']
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
            'price': price,
            'quantity': quantity,
            'color': color
        }

    session['cart'] = cart
    session.modified = True
    flash(f"{quantity} x {item} added to cart.", item)
    return redirect(url_for('home'))

@app.route('/remove_from_cart/<item>')
def remove_from_cart(item):
    cart = session.get('cart', {})
    if item in cart:
        del cart[item]
        session['cart'] = cart
        session.modified = True
        flash(f"Removed all {item.capitalize()} from the cart.", 'removed')
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

    total = calculate_total(cart)
    invoice_date   = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    invoice_number = f"INV_{customer_name.replace(' ', '_')}_{invoice_date}"

    return render_template(
        'invoice.html',
        customer_name  = customer_name,
        headphones_cart = headphones_cart,
        addons_cart    = addons_cart,
        total          = total,
        invoice_date   = invoice_date,
        invoice_number = invoice_number,
    )

@app.route('/about')
def about():
    return render_template('about.html')

@app.route('/orders')
def order_history():
    return render_template('orders.html')

if __name__ == '__main__':
    app.run(debug=True)