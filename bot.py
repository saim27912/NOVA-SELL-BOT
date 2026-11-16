import os
import sqlite3
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters
)

# NOVA SELL BOT
BOT_TOKEN = os.environ["BOT_TOKEN"]
ADMIN_ID = int(os.environ["ADMIN_ID"])
BKASH = os.environ.get("BKASH_NUMBER", "")
NAGAD = os.environ.get("NAGAD_NUMBER", "")

logging.basicConfig(level=logging.INFO)
db = sqlite3.connect("nova.db", check_same_thread=False)
db.execute("""CREATE TABLE IF NOT EXISTS stock (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item TEXT, price INTEGER, sold INTEGER DEFAULT 0
)""")
db.execute("""CREATE TABLE IF NOT EXISTS payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER, method TEXT, txid TEXT,
    price INTEGER, status TEXT DEFAULT 'pending'
)""")
db.commit()

user_state = {}
admin_state = {}

def is_admin(uid):
    return uid == ADMIN_ID

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🌐 Proxy Stock", callback_data="stock")],
        [InlineKeyboardButton("🛒 Buy Proxy", callback_data="buy")],
        [InlineKeyboardButton("📦 My Orders", callback_data="orders")]
    ]
    await update.message.reply_text(
        "✦ WELCOME TO NOVA SELL BOT ✦\n\n"
        "নিরাপদ ও বৈধ Proxy পণ্য কিনতে নিচের মেনু ব্যবহার করুন।",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def stock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = db.execute("""
        SELECT price, COUNT(*) FROM stock
        WHERE sold=0 GROUP BY price ORDER BY price
    """).fetchall()

    if not rows:
        return await update.callback_query.message.reply_text(
            "দুঃখিত! বর্তমানে Stock নেই।"
        )

    msg = "🌐 AVAILABLE PROXY STOCK\n\n"
    for price, count in rows:
        msg += f"৳{price} — {count} টি\n"

    await update.callback_query.message.reply_text(msg)

async def buy_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = db.execute("""
        SELECT price, COUNT(*) FROM stock
        WHERE sold=0 GROUP BY price ORDER BY price
    """).fetchall()

    if not rows:
        return await update.callback_query.message.reply_text(
            "বর্তমানে কোনো Proxy Stock নেই।"
        )

    buttons = [
        [InlineKeyboardButton(
            f"Buy — ৳{price}",
            callback_data=f"price:{price}"
        )]
        for price, count in rows
    ]

    await update.callback_query.message.reply_text(
        "কোন দামের Proxy কিনতে চান?",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

async def choose_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    price = int(q.data.split(":")[1])

    count = db.execute(
        "SELECT COUNT(*) FROM stock WHERE price=? AND sold=0",
        (price,)
    ).fetchone()[0]

    if count < 1:
        return await q.message.reply_text("এই পণ্যের Stock শেষ!")

    user_state[q.from_user.id] = {"price": price}

    keyboard = [[
        InlineKeyboardButton("bKash", callback_data="pay:bkash"),
        InlineKeyboardButton("Nagad", callback_data="pay:nagad")
    ]]

    await q.message.reply_text(
        f"পণ্যের মূল্য: ৳{price}\n\nপেমেন্ট মাধ্যম নির্বাচন করুন:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def payment_method(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    uid = q.from_user.id
    if uid not in user_state:
        return await q.message.reply_text("আবার /buy দিয়ে শুরু করুন।")

    method = q.data.split(":")[1]
    number = BKASH if method == "bkash" else NAGAD

    if not number:
        return await q.message.reply_text(
            "এই পেমেন্ট মাধ্যমটি এখনো Admin সেট করেননি।"
        )

    user_state[uid]["method"] = method
    user_state[uid]["stage"] = "txid"

    await q.message.reply_text(
        f"পেমেন্ট মাধ্যম: {method.upper()}\n"
        f"নম্বর: {number}\n"
        f"পরিমাণ: ৳{user_state[uid]['price']}\n\n"
        "পেমেন্ট সম্পন্ন করে Transaction ID পাঠান।"
    )

async def messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    msg = update.message.text.strip()

    # Admin stock addition
    if uid in admin_state:
        price = admin_state.pop(uid)
        items = [x.strip() for x in msg.splitlines() if x.strip()]
        for item in items:
            db.execute(
                "INSERT INTO stock(item,price) VALUES(?,?)",
                (item, price)
            )
        db.commit()
        return await update.message.reply_text(
            f"✅ {len(items)} টি Proxy Stock যোগ হয়েছে।"
        )

    # User payment transaction ID
    state = user_state.get(uid)
    if state and state.get("stage") == "txid":
        cur = db.execute(
            """INSERT INTO payments(user_id,method,txid,price)
               VALUES(?,?,?,?)""",
            (uid, state["method"], msg, state["price"])
        )
        db.commit()
        payment_id = cur.lastrowid
        user_state.pop(uid, None)

        await update.message.reply_text(
            f"✅ Payment Request জমা হয়েছে!\n"
            f"Order ID: #{payment_id}\n"
            "Admin যাচাই করার পর পণ্য পাঠানো হবে।"
        )

        try:
            await context.bot.send_message(
                ADMIN_ID,
                f"💳 NEW PAYMENT REQUEST\n"
                f"Order: #{payment_id}\n"
                f"User: {uid}\n"
                f"Method: {state['method'].upper()}\n"
                f"TXID: {msg}\n"
                f"Amount: ৳{state['price']}\n\n"
                f"/approve {payment_id} অথবা /reject {payment_id}"
            )
        except Exception:
            logging.exception("Could not notify admin")
        return

    await update.message.reply_text("মেনু দেখতে /start দিন।")

async def addstock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if not context.args or not context.args[0].isdigit():
        return await update.message.reply_text(
            "ব্যবহার: /addstock 50"
        )

    admin_state[update.effective_user.id] = int(context.args[0])
    await update.message.reply_text(
        "এখন প্রতি লাইনে একটি করে বৈধ Proxy পণ্য পাঠান।"
    )

async def approve(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if not context.args or not context.args[0].isdigit():
        return await update.message.reply_text("ব্যবহার: /approve 1")

    pid = int(context.args[0])
    payment = db.execute(
        "SELECT user_id,price,status FROM payments WHERE id=?",
        (pid,)
    ).fetchone()

    if not payment or payment[2] != "pending":
        return await update.message.reply_text(
            "Payment পাওয়া যায়নি অথবা আগেই প্রসেস হয়েছে।"
        )

    item = db.execute(
        "SELECT id,item FROM stock WHERE price=? AND sold=0 LIMIT 1",
        (payment[1],)
    ).fetchone()

    if not item:
        return await update.message.reply_text(
            "Stock নেই! আগে Stock যোগ করুন।"
        )

    db.execute("UPDATE stock SET sold=1 WHERE id=?", (item[0],))
    db.execute(
        "UPDATE payments SET status='approved' WHERE id=?", (pid,)
    )
    db.commit()

    await context.bot.send_message(
        payment[0],
        f"✅ PAYMENT APPROVED\n\n"
        f"Your Proxy Product:\n{item[1]}\n\n"
        f"Order ID: #{pid}"
    )
    await update.message.reply_text(
        f"✅ Order #{pid} Approved এবং Delivery সম্পন্ন।"
    )

async def reject(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if not context.args or not context.args[0].isdigit():
        return await update.message.reply_text("ব্যবহার: /reject 1")

    pid = int(context.args[0])
    cur = db.execute(
        """UPDATE payments SET status='rejected'
           WHERE id=? AND status='pending'""", (pid,)
    )
    db.commit()

    if cur.rowcount == 0:
        return await update.message.reply_text(
            "Pending Payment পাওয়া যায়নি।"
        )

    payment = db.execute(
        "SELECT user_id FROM payments WHERE id=?", (pid,)
    ).fetchone()

    await context.bot.send_message(
        payment[0], f"❌ Payment #{pid} Rejected. Admin-এর সাথে যোগাযোগ করুন।"
    )
    await update.message.reply_text("Payment Rejected.")

async def orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = q.from_user.id
    rows = db.execute(
        "SELECT id,price,status FROM payments WHERE user_id=? ORDER BY id DESC LIMIT 15",
        (uid,)
    ).fetchall()

    if not rows:
        return await q.message.reply_text("আপনার কোনো Order নেই।")

    msg = "📦 YOUR ORDERS\n\n"
    for pid, price, status in rows:
        msg += f"#{pid} | ৳{price} | {status}\n"

    await q.message.reply_text(msg)

async def buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if q.data == "stock":
        await q.answer()
        await stock(update, context)
    elif q.data == "buy":
        await q.answer()
        await buy_menu(update, context)
    elif q.data == "orders":
        await q.answer()
        await orders(update, context)
    elif q.data.startswith("price:"):
        await choose_price(update, context)
    elif q.data.startswith("pay:"):
        await payment_method(update, context)

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("addstock", addstock))
    app.add_handler(CommandHandler("approve", approve))
    app.add_handler(CommandHandler("reject", reject))
    app.add_handler(CallbackQueryHandler(buttons))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, messages))

    print("NOVA SELL BOT is running...")
    app.run_polling()

if __name__ == "__main__":
    main()

import os
import sqlite3
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters
)

# NOVA SELL BOT
BOT_TOKEN = os.environ["BOT_TOKEN"]
ADMIN_ID = int(os.environ["ADMIN_ID"])
BKASH = os.environ.get("BKASH_NUMBER", "")
NAGAD = os.environ.get("NAGAD_NUMBER", "")

logging.basicConfig(level=logging.INFO)
db = sqlite3.connect("nova.db", check_same_thread=False)
db.execute("""CREATE TABLE IF NOT EXISTS stock (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item TEXT, price INTEGER, sold INTEGER DEFAULT 0
)""")
db.execute("""CREATE TABLE IF NOT EXISTS payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER, method TEXT, txid TEXT,
    price INTEGER, status TEXT DEFAULT 'pending'
)""")
db.commit()

user_state = {}
admin_state = {}

def is_admin(uid):
    return uid == ADMIN_ID

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🌐 Proxy Stock", callback_data="stock")],
        [InlineKeyboardButton("🛒 Buy Proxy", callback_data="buy")],
        [InlineKeyboardButton("📦 My Orders", callback_data="orders")]
    ]
    await update.message.reply_text(
        "✦ WELCOME TO NOVA SELL BOT ✦\n\n"
        "নিরাপদ ও বৈধ Proxy পণ্য কিনতে নিচের মেনু ব্যবহার করুন।",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def stock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = db.execute("""
        SELECT price, COUNT(*) FROM stock
        WHERE sold=0 GROUP BY price ORDER BY price
    """).fetchall()

    if not rows:
        return await update.callback_query.message.reply_text(
            "দুঃখিত! বর্তমানে Stock নেই।"
        )

    msg = "🌐 AVAILABLE PROXY STOCK\n\n"
    for price, count in rows:
        msg += f"৳{price} — {count} টি\n"

    await update.callback_query.message.reply_text(msg)

async def buy_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = db.execute("""
        SELECT price, COUNT(*) FROM stock
        WHERE sold=0 GROUP BY price ORDER BY price
    """).fetchall()

    if not rows:
        return await update.callback_query.message.reply_text(
            "বর্তমানে কোনো Proxy Stock নেই।"
        )

    buttons = [
        [InlineKeyboardButton(
            f"Buy — ৳{price}",
            callback_data=f"price:{price}"
        )]
        for price, count in rows
    ]

    await update.callback_query.message.reply_text(
        "কোন দামের Proxy কিনতে চান?",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

async def choose_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    price = int(q.data.split(":")[1])

    count = db.execute(
        "SELECT COUNT(*) FROM stock WHERE price=? AND sold=0",
        (price,)
    ).fetchone()[0]

    if count < 1:
        return await q.message.reply_text("এই পণ্যের Stock শেষ!")

    user_state[q.from_user.id] = {"price": price}

    keyboard = [[
        InlineKeyboardButton("bKash", callback_data="pay:bkash"),
        InlineKeyboardButton("Nagad", callback_data="pay:nagad")
    ]]

    await q.message.reply_text(
        f"পণ্যের মূল্য: ৳{price}\n\nপেমেন্ট মাধ্যম নির্বাচন করুন:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def payment_method(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    uid = q.from_user.id
    if uid not in user_state:
        return await q.message.reply_text("আবার /buy দিয়ে শুরু করুন।")

    method = q.data.split(":")[1]
    number = BKASH if method == "bkash" else NAGAD

    if not number:
        return await q.message.reply_text(
            "এই পেমেন্ট মাধ্যমটি এখনো Admin সেট করেননি।"
        )

    user_state[uid]["method"] = method
    user_state[uid]["stage"] = "txid"

    await q.message.reply_text(
        f"পেমেন্ট মাধ্যম: {method.upper()}\n"
        f"নম্বর: {number}\n"
        f"পরিমাণ: ৳{user_state[uid]['price']}\n\n"
        "পেমেন্ট সম্পন্ন করে Transaction ID পাঠান।"
    )

async def messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    msg = update.message.text.strip()

    # Admin stock addition
    if uid in admin_state:
        price = admin_state.pop(uid)
        items = [x.strip() for x in msg.splitlines() if x.strip()]
        for item in items:
            db.execute(
                "INSERT INTO stock(item,price) VALUES(?,?)",
                (item, price)
            )
        db.commit()
        return await update.message.reply_text(
            f"✅ {len(items)} টি Proxy Stock যোগ হয়েছে।"
        )

    # User payment transaction ID
    state = user_state.get(uid)
    if state and state.get("stage") == "txid":
        cur = db.execute(
            """INSERT INTO payments(user_id,method,txid,price)
               VALUES(?,?,?,?)""",
            (uid, state["method"], msg, state["price"])
        )
        db.commit()
        payment_id = cur.lastrowid
        user_state.pop(uid, None)

        await update.message.reply_text(
            f"✅ Payment Request জমা হয়েছে!\n"
            f"Order ID: #{payment_id}\n"
            "Admin যাচাই করার পর পণ্য পাঠানো হবে।"
        )

        try:
            await context.bot.send_message(
                ADMIN_ID,
                f"💳 NEW PAYMENT REQUEST\n"
                f"Order: #{payment_id}\n"
                f"User: {uid}\n"
                f"Method: {state['method'].upper()}\n"
                f"TXID: {msg}\n"
                f"Amount: ৳{state['price']}\n\n"
                f"/approve {payment_id} অথবা /reject {payment_id}"
            )
        except Exception:
            logging.exception("Could not notify admin")
        return

    await update.message.reply_text("মেনু দেখতে /start দিন।")

async def addstock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if not context.args or not context.args[0].isdigit():
        return await update.message.reply_text(
            "ব্যবহার: /addstock 50"
        )

    admin_state[update.effective_user.id] = int(context.args[0])
    await update.message.reply_text(
        "এখন প্রতি লাইনে একটি করে বৈধ Proxy পণ্য পাঠান।"
    )

async def approve(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if not context.args or not context.args[0].isdigit():
        return await update.message.reply_text("ব্যবহার: /approve 1")

    pid = int(context.args[0])
    payment = db.execute(
        "SELECT user_id,price,status FROM payments WHERE id=?",
        (pid,)
    ).fetchone()

    if not payment or payment[2] != "pending":
        return await update.message.reply_text(
            "Payment পাওয়া যায়নি অথবা আগেই প্রসেস হয়েছে।"
        )

    item = db.execute(
        "SELECT id,item FROM stock WHERE price=? AND sold=0 LIMIT 1",
        (payment[1],)
    ).fetchone()

    if not item:
        return await update.message.reply_text(
            "Stock নেই! আগে Stock যোগ করুন।"
        )

    db.execute("UPDATE stock SET sold=1 WHERE id=?", (item[0],))
    db.execute(
        "UPDATE payments SET status='approved' WHERE id=?", (pid,)
    )
    db.commit()

    await context.bot.send_message(
        payment[0],
        f"✅ PAYMENT APPROVED\n\n"
        f"Your Proxy Product:\n{item[1]}\n\n"
        f"Order ID: #{pid}"
    )
    await update.message.reply_text(
        f"✅ Order #{pid} Approved এবং Delivery সম্পন্ন।"
    )

async def reject(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if not context.args or not context.args[0].isdigit():
        return await update.message.reply_text("ব্যবহার: /reject 1")

    pid = int(context.args[0])
    cur = db.execute(
        """UPDATE payments SET status='rejected'
           WHERE id=? AND status='pending'""", (pid,)
    )
    db.commit()

    if cur.rowcount == 0:
        return await update.message.reply_text(
            "Pending Payment পাওয়া যায়নি।"
        )

    payment = db.execute(
        "SELECT user_id FROM payments WHERE id=?", (pid,)
    ).fetchone()

    await context.bot.send_message(
        payment[0], f"❌ Payment #{pid} Rejected. Admin-এর সাথে যোগাযোগ করুন।"
    )
    await update.message.reply_text("Payment Rejected.")

async def orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = q.from_user.id
    rows = db.execute(
        "SELECT id,price,status FROM payments WHERE user_id=? ORDER BY id DESC LIMIT 15",
        (uid,)
    ).fetchall()

    if not rows:
        return await q.message.reply_text("আপনার কোনো Order নেই।")

    msg = "📦 YOUR ORDERS\n\n"
    for pid, price, status in rows:
        msg += f"#{pid} | ৳{price} | {status}\n"

    await q.message.reply_text(msg)

async def buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if q.data == "stock":
        await q.answer()
        await stock(update, context)
    elif q.data == "buy":
        await q.answer()
        await buy_menu(update, context)
    elif q.data == "orders":
        await q.answer()
        await orders(update, context)
    elif q.data.startswith("price:"):
        await choose_price(update, context)
    elif q.data.startswith("pay:"):
        await payment_method(update, context)

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("addstock", addstock))
    app.add_handler(CommandHandler("approve", approve))
    app.add_handler(CommandHandler("reject", reject))
    app.add_handler(CallbackQueryHandler(buttons))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, messages))

    print("NOVA SELL BOT is running...")
    app.run_polling()

if __name__ == "__main__":
    main()

