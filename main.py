from fastapi import FastAPI, Request, Header, Response
import os
import requests
from fastapi.middleware.cors import CORSMiddleware
from telegram import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardRemove
from datetime import datetime, timedelta
from fastapi.responses import HTMLResponse
from typing import Dict, List
import time
import telegram
from telegram import constants
import stripe
from pymongo import MongoClient
import random
import string
import traceback
import json



# API Keys: ___________________________________________________________________________________________________________
TOKEN = "5918110016:AAF8wtmTHc7imMUYVdC_bwyccHlmySsvVbc"
stripe.api_key = "sk_test_51KrCOaLTObQHYLJ1PmfqCSsYuDxmqDV9sqTEaxNF0dLh7YZqBrA1J49rR7NnZnd7xIeRGPqmkuiuSqXFpDdYLUlY00bilidgOR"
webhook_secret = "whsec_rSxDn6C2pMp1ALQK8wA4RiOVcS09glK2"
mongodb_key = 'flower.cer'
app_script_url = "https://script.google.com/macros/s/AKfycbysMeo-7JIvUiYMSsKoOlCp3ACrToACjYN3yEiCbldGpsM4ZV_B-v2ntVA8sGTI-Wiw/exec"
admin_id = -941570588
crm_id = -908442773
# Client: ____________________________________________________________________________________________________________
bot = telegram.Bot(TOKEN)
app = FastAPI()
mongo = MongoClient("mongodb+srv://cluster0.wdlo0j7.mongodb.net/?authSource=%24external&authMechanism=MONGODB-X509&retryWrites=true&w=majority",
                     tls=True,
                     tlsCertificateKeyFile=mongodb_key)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# Text: ______________________________________________________________________________________________________________
msg1 = '''
Hello! Welcome to Flower Mommies.
We are a flower delivery service that delivers flowers to your doorstep.
'''
msg7 = '''
We have a wide variety of flowers to choose from. Please note the ID of the flower you want to orderl and use /purchase to buy it.
'''
# Functions: _________________________________________________________________________________________________________
users = mongo['Users']
clients = users['clients']
admin = users['admin']
product = users['product']
order = users['order']

def send_appscript_request(data):
    try:
        print(data)
        output = requests.get(app_script_url, params=data)
    except:
        traceback.print_exc()


def delete_stripe_link(payment_intent_id):
    return stripe.checkout.Session.expire(payment_intent_id)



async def payment_received_script(payment_intent_id, time):
    order_id_payload = order.find_one({"stripe_payment_id": payment_intent_id})
    if len(order_id_payload) == 0:
        print('big ooof', payment_intent_id)
        return {"status": "ok"}
    else:
        order_id = order_id_payload['_id']
        order.update_one({"_id": order_id}, {"$set": {"paid": True}})
        random_id = order_id_payload['user_id']
        chat_id = clients.find_one({"random_id": random_id})['_id']
        await send_text(chat_id, "Your payment has been received. Your order has been pushed to the delivery queue. For any queries, please contact @ojasx.")
        order_products = order_id_payload['products']
        order_address = order_id_payload['address']
        order_comment = order_id_payload['comment']
        order_amount = order_id_payload['amount']
        order_customer_id = order_id_payload['user_id']
        order_text = f'''
<b>Order ID:</b> {order_id}
<b>Customer ID:</b> {order_customer_id}
<b>Order Amount:</b> {order_amount}
<b>Products:</b> {order_products}
<b>Order Address:</b> {order_address}
<b>Order Comment:</b> {order_comment}
<b>Payment ID:</b> {payment_intent_id}
        '''
        await send_text(admin_id, order_text)
        clients.update_one({"random_id": order_id_payload['user_id']}, {"$set": {"state.major": 0, "state.minor": 0}})
        to_send = {"method": "payment_received", "time": time}
        for key in order_id_payload:
            if key != "time":
                to_send[key] = order_id_payload[key]
        products = order_id_payload['products']
        formatted_products = ",".join(["[" + str(d['id']) + "," + str(d['quantity']) + "]" for d in products])
        to_send['products'] = formatted_products
        print(to_send)
        send_appscript_request(to_send)




def stripe_payment_link_generator(order_id, total_price):
    try:
        session = stripe.checkout.Session.create(
            payment_method_types=['paynow'], # You need to replace 'card' with the identifier for PayNow
            line_items=[{
                'price_data': {
                    'currency': 'sgd',
                    'product_data': {
                        'name': 'Flower Mommies Bot',
                    },
                    'unit_amount': int(total_price),
                },
                'quantity': 1,
            }],
            mode='payment',
            success_url='https://www.google.com',
            cancel_url='https://www.google.com',
            client_reference_id=order_id,
        )
        payment_intent_id = session.payment_intent
        return [payment_intent_id, session.url, session.id]
    except Exception as e:
        print("Error: ", e)



async def send_options_buttons(chat_id, text, options):
    buttons = []
    for option in options:
        buttons.append(InlineKeyboardButton(text=option, callback_data=option))
    keyboard = [buttons]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await bot.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup)


def cart_summary(product_id_quantity_pairs):
    # extract the price, name and quantity of each product
    total_price = 0
    total_text = ""
    for pair in product_id_quantity_pairs:
        product_id = pair[0]
        quantity = pair[1]
        product_details = product.find_one({"_id": product_id})
        product_name = product_details['name']
        product_price = product_details['price']
        total_price += product_price * quantity
        product_text = f"{product_name} x {quantity} = {product_price * quantity}"
        total_text += product_text + "\n"
    total_text += f"Total Checkout Price: {total_price}" + "\n"
    return total_text


def add_product(id, name, description, price, dimensions, status):
    new_product = {
        "_id": id,
        "name": name,
        "description": description,
        "price": price,
        "dimensions": dimensions,
        "status": status
    }
    product.insert_one(new_product)


async def update_state_admin(chat_id, major, minor):
    admin.update_one({"_id": chat_id}, {"$set": {"state.major": major, "state.minor": minor}})


async def update_state_client(chat_id, major, minor):
    clients.update_one({"_id": chat_id}, {"$set": {"state.major": major, "state.minor": minor}})

async def send_text(chat_id, message_text):
    await bot.send_message(chat_id, message_text, parse_mode=telegram.constants.ParseMode.HTML, disable_web_page_preview=True)


async def update_info_payload_client(chat_id, key, pair):
    clients.update_one({"_id": chat_id}, {"$set": {str("info_payload."+key): pair}})


async def update_info_payload_admin(chat_id, key, pair):
    admin.update_one({"_id": chat_id}, {"$set": {str("info_payload."+key): pair}})


async def info_payload_reset_client(chat_id):
    clients.update_one({"_id": chat_id}, {"$set": {"info_payload": {}}})


async def info_payload_reset_admin(chat_id):
    admin.update_one({"_id": chat_id}, {"$set": {"info_payload": {}}})


async def update_client_info_from_payload(chat_id, info_payload):
    for key in info_payload:
        clients.update_one({"_id": chat_id}, {"$set": {str(key): info_payload[key]}})


async def update_admin_info_from_payload(chat_id, info_payload):
    for key in info_payload:
        admin.update_one({"_id": chat_id}, {"$set": {str(key): info_payload[key]}})


async def send_options_buttons(chat_id, text, options):
    buttons = []
    for option in options:
        buttons.append(InlineKeyboardButton(text=option, callback_data=option))
    keyboard = [buttons]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await bot.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup)


async def register_handler(chat_id, client_status, update):
    if client_status['state']['minor'] == 1 and update.message.contact != None:
        await update_info_payload_client(chat_id, "phone_number", update.message.contact.phone_number)
        await update_state_client(chat_id, 3, 2)
        await bot.send_message(chat_id=update.message.chat_id, text="Please enter your name?", reply_markup=ReplyKeyboardRemove())
    elif client_status['state']['minor'] == 2 and update.message and update.message.text:
        await update_info_payload_client(chat_id, "name", update.message.text)
        await update_state_client(chat_id, 3, 3)
        await send_text(chat_id, "Please enter your email address?")
    elif client_status['state']['minor'] == 3 and update.message and update.message.text:
        text = update.message.text
        await update_info_payload_client(chat_id, "email", text)
        info_payload = clients.find_one({'_id': chat_id})['info_payload']
        await update_client_info_from_payload(chat_id, info_payload)
        await info_payload_reset_client(chat_id)
        await update_state_client(client_status['_id'], 0, 0)
        await send_text(chat_id, "You have been registered successfully. You can now use /purchase to make your order ;)\nYou may use /register again if any of the details you entered are incorrect.")
        send_appscript_request({"method": "register", "random_id": client_status["random_id"], "phone_number": info_payload['phone_number'], "email": text, "name": info_payload['name'], "chat_id": chat_id})
    else:
        await send_text(chat_id, "Please enter a valid input. If you want to restart, use /cancel and then press /register again.")


async def purchase_handler(chat_id, client_status, update):
    if client_status['state']['minor'] == 0 and update.message and update.message.text:
        id = update.message.text
        if product.count_documents({"_id": id}) == 0:
            await send_text(chat_id, "Your product ID doesn't exist. Kindly re-enter another product ID.")
            return {"status": "ok"}
        if product.find_one({"_id": id})['status'] == False:
            await send_text(chat_id, "The product you have chosen is currently out of stock. Please choose another product ID instead.")
            return {"status": "ok"}
        info_payload = client_status['info_payload']
        for key in info_payload:
            if key == id:
                await send_text(chat_id, "You have already added this product to your cart. Please add another product ID instead")
                await send_text(chat_id, "If you wish to cancel the current order, use /cancel.")
                return {"status": "ok"}
        await update_info_payload_client(chat_id, id, 0)
        await update_state_client(chat_id, 1, 1)
        product_details = product.find_one({"_id": id})
        product_name = product_details['name']
        product_description = product_details['description']
        product_price = product_details['price']
        product_dimensions = product_details['dimensions']
        await send_text(chat_id, f'''
        You have chosen this flower 🌻
        <b>Product ID:</b> {id}
        <b>Name:</b> {product_name}
        <b>Description:</b> {product_description}
        <b>Price:</b> {product_price}
        <b>Dimensions:</b> {product_dimensions}

        Please enter the quantity of the product you want to purchase. (e.g. 2)
        ''')
        await send_text(chat_id, "If you wish to cancel the current order, use /cancel.")
    elif client_status['state']['minor'] == 1 and update.message and update.message.text:
        quantity = update.message.text
        if not quantity.isdigit() or int(quantity) < 1 or int(quantity) > 1000:
            await send_text(chat_id, "Please enter a valid number between 1-1000 for your quantity instead.")
            await send_text(chat_id, "If you wish to cancel the current order, use /cancel.")
            return {"status": "ok"}
        info_payload = client_status['info_payload']
        for key in info_payload:
            if info_payload[key] == 0:
                await update_info_payload_client(chat_id, key, int(quantity))
                break
        info_payload = clients.find_one({'_id': chat_id})['info_payload']
        product_id_quantity_pairs = []
        for key in info_payload:
            if info_payload[key] != 0:
                product_id_quantity_pairs.append([key, info_payload[key]])
        cart_text = cart_summary(product_id_quantity_pairs)
        await send_text(chat_id, cart_text)
        await send_options_buttons(client_status['_id'], "Do you wish to add more items in your cart or checkout?",["Checkout 🛒", "Add more 🏵"])
        await update_state_client(chat_id, 1, 2)
        await send_text(chat_id, "If you wish to cancel the current order, use /cancel.")
    elif client_status['state']['minor'] == 2 and update.callback_query and update.callback_query.data:
        text = update.callback_query.data
        if text == "Checkout 🛒":
            info_payload = client_status['info_payload']
            for key in info_payload:
                if info_payload[key] == 0:
                    await update_info_payload_client(chat_id, key, quantity)
                    break
            product_id_quantity_pairs = []
            for key in info_payload:
                if info_payload[key] != 0:
                    product_id_quantity_pairs.append([key, info_payload[key]])
            cart_text = cart_summary(product_id_quantity_pairs)
            await send_text(chat_id, cart_text)
            await send_options_buttons(client_status['_id'], "Do you wish to checkout your order summary?",["Yes ✅", "No ❌"])
            await update_state_client(chat_id, 1, 3)
        elif text == "Add more 🏵":
            await send_text(chat_id, "Look at the catalog again :) Please enter the ID of the product you want to purchase.")
            await update_state_client(chat_id, 1, 0)
        else:
            await send_text(chat_id, "Please enter a valid input. If you want to restart the purchase, use /cancel and then press /purchase again.")
    elif client_status['state']['minor'] == 3 and update.callback_query and update.callback_query.data:
        text = update.callback_query.data
        if text == "Yes ✅":
            await send_text(chat_id, "Please enter your order delivery address.")
            await update_state_client(chat_id, 1, 4)
        elif text == "No ❌":
            await info_payload_reset_client(chat_id)
            await update_state_client(chat_id, 0, 0)
            await send_text(chat_id, "Your current order has been cancelled. Use /purchase to make any new orders.")
    elif client_status['state']['minor'] == 4 and update.message and update.message.text:
        address = update.message.text
        await update_info_payload_client(chat_id, "address", address)
        await send_text(chat_id, "Please enter any comments you have for your order.")
        await update_state_client(chat_id, 1, 5)
    elif client_status['state']['minor'] == 5 and update.message and update.message.text:
        comment = update.message.text
        await update_info_payload_client(chat_id, "comment", comment)
        # Print the order summary
        info_payload = client_status['info_payload']
        product_id_quantity_pairs = []
        for key in info_payload:
            if key not in ["address", "comment"]:
                product_id_quantity_pairs.append([key, info_payload[key]])
        cart_text = cart_summary(product_id_quantity_pairs)
        await send_text(chat_id, cart_text)
        await send_text(chat_id, f"Your order will be delivered to: {info_payload['address']}")
        await send_text(chat_id, f"Your comment for the order is: {comment}")
        await send_options_buttons(client_status['_id'], "Do you wish to confirm your order?",["Yes ✅", "No ❌"])
        await update_state_client(chat_id, 1, 6)
    elif client_status['state']['minor'] == 6 and update.callback_query and update.callback_query.data:
        text = update.callback_query.data
        if text == "Yes ✅":
            order_payload = {}
            order_id = ""
            first_char = str(random.randint(0, 9))
            second_char = random.choice(string.ascii_uppercase)
            third_char = str(random.randint(0, 9))
            fourth_char = random.choice(string.ascii_uppercase)
            fifth_char = str(random.randint(0, 9))
            sixth_char = random.choice(string.ascii_uppercase)
            order_id = f"{first_char}{second_char}{third_char}{fourth_char}{fifth_char}{sixth_char}"
            while order.count_documents({"_id": order_id}) > 0:
                first_char = str(random.randint(0, 9))
                second_char = random.choice(string.ascii_uppercase)
                third_char = str(random.randint(0, 9))
                fourth_char = random.choice(string.ascii_uppercase)
                fifth_char = str(random.randint(0, 9))
                sixth_char = random.choice(string.ascii_uppercase)
                order_id = f"{first_char}{second_char}{third_char}{fourth_char}{fifth_char}{sixth_char}"
            order_payload['_id'] = order_id
            order_payload['user_id'] = client_status['random_id']
            order_payload['products'] = []
            info_payload = client_status['info_payload']
            for key in info_payload:
                if key not in ["address", "comment"]:
                    order_payload['products'].append({"id": key, "quantity": info_payload[key]})
            total_price = 0
            for pair in order_payload['products']:
                product_details = product.find_one({"_id": pair['id']})
                total_price += product_details['price'] * pair['quantity']
            order_payload['amount'] = total_price 
            order_payload['time'] = datetime.now()
            order_payload['address'] = info_payload['address']
            order_payload['status'] = False
            order_payload['comment'] = info_payload['comment']
            order_payload['refunded'] = False
            order_payload['paid'] = False 
            stripe_data = stripe_payment_link_generator(order_id, total_price*100)
            stripe_payment_id, stripe_payment_url, checkout_id = stripe_data[0], stripe_data[1], stripe_data[2]
            order_payload['stripe_payment_link'] = stripe_payment_url
            order_payload['stripe_payment_id'] = stripe_payment_id
            order_payload['checkout_id'] = checkout_id
            await send_text(chat_id, f"Your order has been placed successfully. Please pay ${total_price} at the following url: <a href='"+stripe_payment_url+"'>Click Here</a>")
            order.insert_one(order_payload)
            await info_payload_reset_client(chat_id)
            clients.update_one({"_id": chat_id}, {"$push": {"order_history": order_id}})
            await update_state_client(chat_id, 2, 0)
        elif text == "No ❌":
            await info_payload_reset_client(chat_id)
            await update_state_client(chat_id, 0, 0)
            await send_text(chat_id, "Your current order has been cancelled. Use /purchase to make any new orders.")
    else:
        await send_text(chat_id, "Please enter a valid input. If you want to restart the purchase, use /cancel and then press /purchase again.")


@app.post("/telegram")
async def echo(request: Request):
    try:
        update_data = await request.json()
        update = telegram.Update.de_json(update_data, bot)
        if update.message:
            chat_id = update.message.chat_id
        elif update.callback_query:
            chat_id = update.callback_query.message.chat_id
        else:
            await send_text(chat_id, "Your message type isn't supported.")
            return {"status": "ok"}
        if chat_id==crm_id or chat_id==admin_id:
            admin_status = admin.find_one({'_id': chat_id})
            if admin_status['state']['major'] == 0:
                if update.message:
                    if "/get_user_info" in update.message.text:
                        text = update.message.text
                        if " " not in text:
                            await send_text(chat_id, "Please enter a valid input. The format is /get_user_info [user_id]")
                            return {"status": "ok"}
                        random_id = text.split(" ")[1]
                        if clients.find_one({"random_id": random_id}) == None:
                            await send_text(chat_id, "The user ID you entered doesn't exist. Please enter a valid user ID.")
                            return {"status": "ok"}
                        else:
                            client_status = clients.find_one({"random_id": random_id})
                            client_name = client_status['name']
                            client_phone_number = client_status['phone_number']
                            client_email = client_status['email']
                            client_free_credits = client_status['free_credits']
                            client_order_history = client_status['order_history']
                            client_text = f'''
<b>User ID:</b> {random_id} 
<b>Name:</b> {client_name}
<b>Phone Number:</b> {client_phone_number}
<b>Email:</b> {client_email}
<b>Order History:</b> {client_order_history}
                            '''
                            await send_text(chat_id, client_text)
                    elif "/get_order_info" in update.message.text:
                        text = update.message.text
                        if " " not in text:
                            await send_text(chat_id, "Please enter a valid input. The format is /get_order_info [order_id]")
                            return {"status": "ok"}
                        order_id = text.split(" ")[1]
                        order = users['order']
                        if order.find_one({"_id": order_id}) == None:
                            await send_text(chat_id, "The order ID you entered doesn't exist. Please enter a valid order ID.")
                            return {"status": "ok"}
                        else:
                            order_status = order.find_one({"_id": order_id})
                            customer_id = order_status['user_id']
                            order_amount = order_status['amount']
                            order_products = order_status['products']
                            order_time = order_status['time']
                            order_address = order_status['address']
                            delivery_status = order_status['status']
                            order_comment = order_status['comment']
                            order_refunded = order_status['refunded']
                            payment_intent_id = order_status['stripe_payment_id']
                            order_text =  f'''
<b>Order ID:</b> {order_id}
<b>Customer ID:</b> {customer_id}
<b>Order Amount:</b> {order_amount}
<b>Products:</b> {order_products}
<b>Order Time:</b> {order_time}
<b>Order Address:</b> {order_address}
<b>Delivery Status:</b> {delivery_status}
<b>Order Comment:</b> {order_comment}
<b>Order Refunded:</b> {order_refunded}
<b>Payment ID:</b> {payment_intent_id}
                            '''
                            await send_text(chat_id, order_text)
                    elif "/delivered" in update.message.text: # The order has been delivered
                        text = update.message.text
                        if " " not in text:
                            await send_text(chat_id, "Please enter a valid input. The format is /delivered [order_id]")
                            return {"status": "ok"}
                        order_id = text.split(" ")[1]
                        order = users['order']
                        if order.find_one({"_id": order_id}) == None:
                            await send_text(chat_id, "The order ID you entered doesn't exist. Please enter a valid order ID.")
                            return {"status": "ok"}
                        else:
                            order.update_one({"_id": order_id}, {"$set": {"status": True}})
                            await send_text(chat_id, "The order has been marked as delivered.")
                            send_appscript_request({"method": "delivered", "order_id": order_id, "status": True})
                    elif "/cancel_delivered" in update.message.text: # The order has been delivered
                        text = update.message.text
                        if " " not in text:
                            await send_text(chat_id, "Please enter a valid input. The format is /cancel_delivered [order_id]")
                            return {"status": "ok"}
                        order_id = text.split(" ")[1]
                        order = users['order']
                        if order.find_one({"_id": order_id}) == None:
                            await send_text(chat_id, "The order ID you entered doesn't exist. Please enter a valid order ID.")
                            return {"status": "ok"}
                        else:
                            order.update_one({"_id": order_id}, {"$set": {"status": False}})
                            await send_text(chat_id, "The order has been marked as not delivered.")
                            send_appscript_request({"method": "delivered", "order_id": order_id, "status": False})
                    elif "/refund" in update.message.text: # The order has been refunded
                        text = update.message.text
                        if " " not in text:
                            await send_text(chat_id, "Please enter a valid input. The format is /refund [order_id]")
                            return {"status": "ok"}
                        order_id = text.split(" ")[1]
                        order = users['order']
                        if order.find_one({"_id": order_id}) == None:
                            await send_text(chat_id, "The order ID you entered doesn't exist. Please enter a valid order ID.")
                            return {"status": "ok"}
                        else:
                            order.update_one({"_id": order_id}, {"$set": {"refunded": True}})
                            await send_text(chat_id, "The order has been marked as refunded.")
                            send_appscript_request({"method": "refund", "order_id": order_id, "status": True})
                    elif "/cancel_refund" in update.message.text: # The order has been refunded
                        text = update.message.text
                        if " " not in text:
                            await send_text(chat_id, "Please enter a valid input. The format is /cancel_refund [order_id]")
                            return {"status": "ok"}
                        order_id = text.split(" ")[1]
                        order = users['order']
                        if order.find_one({"_id": order_id}) == None:
                            await send_text(chat_id, "The order ID you entered doesn't exist. Please enter a valid order ID.")
                            return {"status": "ok"}
                        else:
                            order.update_one({"_id": order_id}, {"$set": {"refunded": True}})
                            await send_text(chat_id, "The order has been marked as refunded.")
                            send_appscript_request({"method": "refund", "order_id": order_id, "status": False})
                    elif "/in_stock" in update.message.text: # The product is in stock
                        text = update.message.text
                        if " " not in text:
                            await send_text(chat_id, "Please enter a valid input. The format is /in_stock [product_id]")
                            return {"status": "ok"}
                        product_id = text.split(" ")[1]
                        product = users['product']
                        if product.find_one({"_id": product_id}) == None:
                            await send_text(chat_id, "The product ID you entered doesn't exist. Please enter a valid product ID.")
                            return {"status": "ok"}
                        else:
                            product.update_one({"_id": product_id}, {"$set": {"status": True}})
                            await send_text(chat_id, "The product has been marked as in stock.")
                    elif "/outof_stock" in update.message.text: # The product is in stock
                        text = update.message.text
                        if " " not in text:
                            await send_text(chat_id, "Please enter a valid input. The format is /in_stock [product_id]")
                            return {"status": "ok"}
                        product_id = text.split(" ")[1]
                        product = users['product']
                        if product.find_one({"_id": product_id}) == None:
                            await send_text(chat_id, "The product ID you entered doesn't exist. Please enter a valid product ID.")
                            return {"status": "ok"}
                        else:
                            product.update_one({"_id": product_id}, {"$set": {"status": False}})
                            await send_text(chat_id, "The product has been marked as out of stock.")
        elif not clients.find_one({'_id': chat_id}):
            first_char = str(random.randint(0, 9))
            second_char = random.choice(string.ascii_uppercase)
            third_char = str(random.randint(0, 9))
            fourth_char = random.choice(string.ascii_uppercase)
            random_id = f"{first_char}{second_char}{third_char}{fourth_char}"
            while clients.count_documents({"random_id": random_id}) > 0:
                first_char = str(random.randint(0, 9))
                second_char = random.choice(string.ascii_uppercase)
                third_char = str(random.randint(0, 9))
                fourth_char = random.choice(string.ascii_uppercase)
                random_id = f"{first_char}{second_char}{third_char}{fourth_char}"
            new_user = {
                "_id": int(chat_id),  # Telegram ID (INT)
                "name": "",  # Name of the individual (STR)
                "random_id": random_id,  # Random User ID (INT)
                "phone_number": "",  # Phone number of the particular user (STR)
                "email": "",  # Email ID of the individual (STR)
                "free_credits": 0.0,  # Amount of free credits (FLOAT)
                "state": {"major": 0, "minor": 0},  # State of each user in the document flow (Document)
                "info_payload": {},  # Contain all the information relevant to the current procedure (Document)
                "order_history": [],  # Contains the history of all the orders by the particular user (ARRAY)
                "meta_data": {}  # Essentially extra data or data which we feel might be necessary to issue discounts and stuff (Document)
            }
            clients.insert_one(new_user)
            await send_text(chat_id, msg1)
        else:
            client_status = clients.find_one({'_id': chat_id})
            if client_status['state']['major'] == 0:
                if update.message:
                    if "/start" == update.message.text :
                        await send_text(chat_id, msg1)
                    elif "/cancel" == update.message.text:
                        await send_text(chat_id, "Your current procedure has been cancelled.")
                        await update_state_client(chat_id, 0, 0)
                        await info_payload_reset_client(chat_id)
                        return {"status": "ok"}
                    elif "/contact" == update.message.text:
                        help_msg = "Please contact @ojasx for customer support/suggestions."
                        await send_text(chat_id, help_msg)
                    elif "/referral" == update.message.text:
                        referal_message = f"Your referal code is: {client_status['random_id']}."
                        await send_text(chat_id, referal_message)
                    elif "/catalog" == update.message.text:
                        await bot.send_photo(chat_id=chat_id, photo="https://cdn.discordapp.com/attachments/628770208319930398/1124613491047792670/IMG_20230701_155627_608.jpg", caption=msg7)
                        await send_text(chat_id, referal_message)
                    elif "/order_history" == update.message.text:
                        # check if order history is empty
                        if len(client_status['order_history']) == 0:
                            await send_text(chat_id, "You haven't placed any orders yet. Kindly use /purchase to make your first order.")
                        else:
                            total_text = ""
                            for order in client_status['order_history']:
                                order_id = order['_id']
                                order_products = order['products']
                                order_time = order['time']
                                order_address = order['address']
                                order_status = order['status']
                                order_comment = order['comment']
                                order_refunded = order['refunded']
                                order_text =  f'''
                                Order ID: {order_id}
                                Products: {order_products}
                                Order Time: {order_time}
                                Order Address: {order_address}
                                Order Status: {order_status}
                                Order Comment: {order_comment}
                                Order Refunded: {order_refunded}
                                '''
                            total_text += order_text + "----------------------------------------"+ "\n"
                            await send_text(chat_id, total_text)
                    elif "/purchase" == update.message.text:
                        if client_status['phone_number'] == "":
                            await send_text(chat_id, "Please register first by using /register command before making a purchase. 😀")
                        else:
                            await bot.send_photo(chat_id=chat_id, photo="https://cdn.discordapp.com/attachments/628770208319930398/1124613491047792670/IMG_20230701_155627_608.jpg", caption="")
                            await send_text(chat_id, "Look at the catalog. Please enter the ID of the product you want to purchase.")
                            await update_state_client(chat_id, 1, 0)
                            
                    elif "/register" == update.message.text:
                        await update_state_client(chat_id, 3, 1)
                        reply_keyboard = [[KeyboardButton("Share Phone Number 📞", request_contact=True)]]
                        markup = ReplyKeyboardMarkup(reply_keyboard, resize_keyboard=True, one_time_keyboard=True)
                        await bot.send_message(chat_id, text="Click the button below to share your 📞 contact details\nThis is so that we can contact you if there are any issues.", reply_markup=markup)
                    else:
                        await send_text(chat_id, "I am not sure what you mean 😅. Please use the availible command in the menu section to interact with me. Or /contact support for help.")
                else:
                    await send_text(chat_id, "Please enter a valid input.")
            elif client_status['state']['major'] == 3:
                if update.message and update.message.text == "/cancel":
                    await send_text(chat_id, "Your current procedure has been cancelled.")
                    await update_state_client(chat_id, 0, 0)
                    await info_payload_reset_client(chat_id)
                    return {"status": "ok"}
                await register_handler(chat_id, client_status, update)
            elif client_status['state']['major'] == 1:
                if update.message and update.message.text == "/cancel":
                    await send_text(chat_id, "Your current procedure has been cancelled.")
                    await update_state_client(chat_id, 0, 0)
                    await info_payload_reset_client(chat_id)
                    return {"status": "ok"}
                await purchase_handler(chat_id, client_status, update)
            elif client_status['state']['major'] == 2:
                if update.message and update.message.text == "/cancel":
                    await send_text(chat_id, "If you wish to cancel your current order, please press /delete_order.")
                    return {"status": "ok"}
                elif update.message and update.message.text == "/delete_order":
                    order_history = client_status['order_history']
                    order = users['order']
                    for order_id in order_history:
                        order_payload = order.find_one({"_id": order_id})
                        if order_payload['paid'] == False:
                            order.delete_one({"_id": order_id})
                            try:
                                delete_stripe_link(order_payload['checkout_id'])
                            except:
                                print('Fuck it')
                            clients.update_one({"_id": chat_id}, {"$pull": {"order_history": order_id}})
                            await send_text(chat_id, "Your order has been deleted successfully.")
                            await update_state_client(chat_id, 0, 0)
                            return {"status": "ok"}
                elif update.message and update.message.text:
                    order = users['order']
                    order_history = client_status['order_history']
                    for order_id in order_history:
                        order_payload = order.find_one({"_id": order_id})
                        if order_payload['paid'] == False:
                            stripe_payment_link = order_payload['stripe_payment_link']
                            await send_text(chat_id, f"Please pay for your order at the following url: <a href='"+stripe_payment_link+"'>Click Here</a>")
                            await send_text(chat_id, "If you wish to cancel your current order, please contact, please press the command /delete_order.")
                            return {"status": "ok"}
        return {"status": "ok"}
    except Exception as e:
        print(e)
        print("Exception occurred on line:", e.__traceback__.tb_lineno)
        traceback.print_exc()
        return {"status": "ok"}
    


@app.post("/stripe")
async def webhook_received(request: Request, stripe_signature: str = Header(None)):
    data = await request.body()
    try:
        event = stripe.Webhook.construct_event(
            payload=data,
            sig_header=stripe_signature,
            secret=webhook_secret
        )
        event_data = event['data']
    except Exception as e:
        print(e)
        return {"error": str(e)}
    time = event_data["object"]["created"]
    status = event_data['object']['status']
    if status == 'complete':
        payment_intent_id = event_data['object']['payment_intent']
        await payment_received_script(payment_intent_id, time)
    elif status == 'expired':
        return {"status": "success"}
    else:
        return {"status": "success"}
    