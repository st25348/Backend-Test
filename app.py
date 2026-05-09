from flask import Flask, render_template, request, redirect, url_for, session, flash, redirect, url_for
import json

app = Flask(__name__)
app.secret_key = "ilikeheadphones"

def load_data():
    with open('data/headphones.json') as file:
        headphones = json.load(file)
    with open('data/addons.json') as file:
        addons = json.load(file)
    return headphones, addons

@app.route('/home')
def index():
    headphones, addons = load_data()
    cart = session.get('cart', {})
    return render_template('index.html', headphones=headphones, addons=addons, cart=cart)  

@app.route('/add_to_cart', methods=['POST'])
def add_to_cart():
    headphones, addons = load_data()
    cart = session.get('cart', {})               # get cart from session or start fresh
    quantity = int(request.form['quantity'])      # convert quantity to a number

    if 'headphone' in request.form:              # headphone form was submitted
        item = request.form['headphone']         # get selected headphone name
        if item not in headphones:
            flash("Invalid headphone selected.", 'item')
            return redirect(url_for('index'))
        price = headphones[item]['price']

    elif 'addon' in request.form:               # addon form was submitted
        item = request.form['addon']            # get selected addon name
        if item not in addons:
            flash("Invalid addon selected.", 'item')
            return redirect(url_for('index'))
        price = addons[item]['price']

    if item in cart:
        cart[item]['quantity'] += quantity       # add to existing quantity
    else:
        cart[item] = {
            'price': price,
            'quantity': quantity
        }

    session['cart'] = cart                       # update session
    session.modified = True                      # force Flask to save it
    flash(f"{quantity} x {item} added to cart.", item)
    return redirect(url_for('index'))

@app.route('/remove_from_cart/<item>')
def remove_from_cart(item):
    cart = session.get('cart', {})
    if item in cart:
        del cart[item]
        session['cart'] = cart
        session.modified = True
    return redirect(url_for('index'))

@app.route('/checkout')
def checkout():
    return render_template('checkout.html')

@app.route('/about')
def about():
    return render_template('about.html')

@app.route('/orders')
def order_history():
    return render_template('orders.html')

if __name__ == '__main__':
    app.run(debug=True)