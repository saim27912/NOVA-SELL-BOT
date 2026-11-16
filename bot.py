import os
import sqlite3
import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters
)

# ===== NOVA SELL BOT CONFIG =====
TOKEN = os.environ["BOT_TOKEN"]
ADMIN = int(os.environ["ADMIN_ID"])
BKASH = os.environ.get("BKASH_NUMBER", "")
NAGAD = os.environ.get("NAGAD_NUMBER", "")
PORT = int(os.environ.get("PORT", "10000"))
BASE_URL = os.environ["RENDER_EXTERNAL_URL"].rstrip("/")
WEBHOOK_PATH = "nova-webhook"

logging.basicConfig(level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger(__name__)

DB = "nova.db"
user_state = {}
admin_state = {}


# ===== DATABASE =====
def connect():
    return sqlite3.connect(DB)


def setup():
    with connect() as con:
        con.execute("""
        CREATE TABLE IF NOT EXISTS stock (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item TEXT NOT NULL,
            price INTEGER NOT NULL,
            sold INTEGER DEFAULT 0
        )
        """)
        con.execute("""
        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            method TEXT NOT NULL,
            txid TEXT NOT NULL,
            price INTEGER NOT NULL,
            status TEXT DEFAULT 'pending'
        )
        """)


def is_admin(uid):
    return uid == ADMIN


# ===== MAIN MENU =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🌐 Proxy Stock", callback_data="stock")],
        [InlineKeyboardButton("🛒 Buy Proxy", callback_data="buy")],
        [InlineKeyboardButton("📦 My Orders", callback_data="orders")]
    ]

    await update.message.reply_text(
        "✦ NOVA SELL BOT ✦\n\n"
        "Welcome!\n"
        "বৈধ Proxy পণ্য দেখতে নিচের Menu ব্যবহার করুন।",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# ===== STOCK =====
async def show_stock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    with connect() as con:
        rows = con.execute("""
            SELECT price, COUNT(*) FROM stock
            WHERE sold=0 GROUP BY price ORDER BY price
        """).fetchall()

    if not rows:
        await q.message.reply_text("দুঃখিত! বর্তমানে Stock নেই।")
        return

    msg = "🌐 AVAILABLE PROXY STOCK\n\n"
    for price, count in rows:
        msg += f"৳{price} — {count} টি\n"

    await q.message.reply_text(msg)


# ===== BUY MENU =====
async def buy_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query

    with connect() as con:
        rows = con.execute("""
            SELECT price, COUNT(*) FROM stock
            WHERE sold=0 GROUP BY price ORDER BY price
        """).fetchall()

    if not rows:
        await q.message.reply_text("বর্তমানে Proxy Stock নেই।")
        return

    keyboard = [
        [InlineKeyboardButton(
            f"Buy — ৳{price} ({count} available)",
            callback_data=f"price:{price}"
        )]
        for price, count in rows
    ]

    await q.message.reply_text(
        "পণ্যের মূল্য নির্বাচন করুন:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# ===== SELECT PRICE =====
async def choose_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    price = int(q.data.split(":")[1])

    with connect() as con:
        count = con.execute(
            "SELECT COUNT(*) FROM stock WHERE price=? AND sold=0",
            (price,)
        ).fetchone()[0]

    if count == 0:
        await q.message.reply_text("এই পণ্যের Stock শেষ!")
        return

    user_state[q.from_user.id] = {"price": price}

    keyboard = [[
        InlineKeyboardButton("bKash", callback_data="pay:bkash"),
        InlineKeyboardButton("Nagad", callback_data="pay:nagad")
    ]]

    await q.message.reply_text(
        f"পণ্যের মূল্য: ৳{price}\n"
        "পেমেন্ট মাধ্যম নির্বাচন করুন:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# ===== PAYMENT METHOD =====
async def payment_method(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    uid = q.from_user.id
    state = user_state.get(uid)

    if not state:
        await q.message.reply_text("আবার /start দিয়ে শুরু করুন।")
        return

    method = q.data.split(":")[1]
    number = BKASH if method == "bkash" else NAGAD

    if not number:
        await q.message.reply_text("এই Payment Number Admin সেট করেননি।")
        return

    state["method"] = method
    state["stage"] = "txid"

    await q.message.reply_text(
        f"💳 {method.upper()} PAYMENT\n\n"
        f"নম্বর: {number}\n"
        f"পরিমাণ: ৳{state['price']}\n\n"
        "পেমেন্ট সম্পন্ন করে Transaction ID পাঠান।"
    )


# ===== ADMIN ADD STOCK =====
async def addstock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id

    if not is_admin(uid):
        return

    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text(
            "ব্যবহার:\n/addstock 50\n\n"
            "তারপর প্রতি লাইনে একটি করে Proxy পাঠান।"
        )
        return

    price = int(context.args[0])

    if price <= 0:
        await update.message.reply_text("সঠিক মূল্য দিন।")
        return

    admin_state[uid] = price

    await update.message.reply_text(
        f"প্রতি পণ্যের মূল্য ৳{price}\n\n"
        "এখন প্রতি লাইনে একটি করে বৈধ Proxy পাঠান।"
    )


# ===== ADMIN VIEW STOCK =====
async def adminstock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    with connect() as con:
        rows = con.execute("""
            SELECT id, price, sold FROM stock ORDER BY id DESC LIMIT 30
        """).fetchall()

    if not rows:
        await update.message.reply_text("Stock খালি।")
        return

    msg = "📦 ADMIN STOCK\n\n"
    for sid, price, sold in rows:
        status = "Sold" if sold else "Available"
        msg += f"#{sid} | ৳{price} | {status}\n"

    await update.message.reply_text(msg)


# ===== TEXT MESSAGES =====
async def messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    msg = update.message.text.strip()

    # Admin adds stock
    if uid in admin_state:
        price = admin_state.pop(uid)
        items = [x.strip() for x in msg.splitlines() if x.strip()]

        if not items:
            await update.message.reply_text("কোনো Stock যোগ হয়নি।")
            return

        with connect() as con:
            for item in items:
                con.execute(
                    "INSERT INTO stock(item,price) VALUES(?,?)",
                    (item, price)
                )

        await update.message.reply_text(
            f"✅ {len(items)} টি Stock যোগ হয়েছে।"
        )
        return

    # User submits transaction ID
    state = user_state.get(uid)

    if state and state.get("stage") == "txid":
        if len(msg) < 4 or len(msg) > 100:
            await update.message.reply_text("সঠিক Transaction ID পাঠান।")
            return

        with connect() as con:
            cur = con.execute("""
                INSERT INTO payments(user_id,method,txid,price)
                VALUES(?,?,?,?)
            """, (uid, state["method"], msg, state["price"]))
            payment_id = cur.lastrowid

        user_state.pop(uid, None)

        await update.message.reply_text(
            f"✅ Payment Request জমা হয়েছে!\n"
            f"Order ID: #{payment_id}\n"
            "Admin যাচাই করার পর পণ্য পাঠানো হবে।"
        )

        try:
            await context.bot.send_message(
                ADMIN,
                f"💳 NEW PAYMENT REQUEST\n\n"
                f"Order: #{payment_id}\n"
                f"User ID: {uid}\n"
                f"Method: {state['method'].upper()}\n"
                f"TXID: {msg}\n"
                f"Amount: ৳{state['price']}\n\n"
                f"Approve: /approve {payment_id}\n"
                f"Reject: /reject {payment_id}"
            )
        except Exception:
            log.exception("Admin notification failed")

        return

    await update.message.reply_text("Menu দেখতে /start দিন।")


# ===== APPROVE PAYMENT + DELIVERY =====
async def approve(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("ব্যবহার: /approve 1")
        return

    pid = int(context.args[0])

    with connect() as con:
        payment = con.execute("""
            SELECT user_id, price, status
            FROM payments WHERE id=?
        """, (pid,)).fetchone()

        if not payment or payment[2] != "pending":
            await update.message.reply_text(
                "Payment নেই অথবা আগেই Process হয়েছে।"
            )
            return

        item = con.execute("""
            SELECT id, item FROM stock
            WHERE price=? AND sold=0 ORDER BY id LIMIT 1
        """, (payment[1],)).fetchone()

        if not item:
            await update.message.reply_text(
                "Stock নেই। আগে Stock যোগ করুন।"
            )
            return

        # Mark item sold and payment approved together
        con.execute(
            "UPDATE stock SET sold=1 WHERE id=? AND sold=0",
            (item[0],)
        )
        con.execute(
            "UPDATE payments SET status='approved' WHERE id=?",
            (pid,)
        )

    try:
        await context.bot.send_message(
            payment[0],
            f"✅ PAYMENT APPROVED\n\n"
            f"Order ID: #{pid}\n"
            f"Your Proxy Product:\n{item[1]}"
        )
    except Exception:
        log.exception("Delivery message failed")
        await update.message.reply_text(
            "Payment Approved হয়েছে, কিন্তু User-কে Message পাঠানো যায়নি।"
        )
        return

    await update.message.reply_text(
        f"✅ Order #{pid} Approved এবং Delivery সম্পন্ন।"
    )


# ===== REJECT PAYMENT =====
async def reject(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("ব্যবহার: /reject 1")
        return

    pid = int(context.args[0])

    with connect() as con:
        payment = con.execute("""
            SELECT user_id, status FROM payments WHERE id=?
        """, (pid,)).fetchone()

        if not payment or payment[1] != "pending":
            await update.message.reply_text("Pending Payment পাওয়া যায়নি।")
            return

        con.execute(
            "UPDATE payments SET status='rejected' WHERE id=?",
            (pid,)
        )

    await context.bot.send_message(
        payment[0],
        f"❌ Payment #{pid} Rejected.\n"
        "প্রয়োজনে Admin-এর সাথে যোগাযোগ করুন।"
    )
    await update.message.reply_text("Payment Rejected.")


# ===== ORDER HISTORY =====
async def orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = q.from_user.id

    with connect() as con:
        rows = con.execute("""
            SELECT id, price, status FROM payments
            WHERE user_id=? ORDER BY id DESC LIMIT 15
        """, (uid,)).fetchall()

    if not rows:
        await q.message.reply_text("আপনার কোনো Order নেই।")
        return

    msg = "📦 YOUR ORDERS\n\n"
    for pid, price, status in rows:
        msg += f"#{pid} | ৳{price} | {status}\n"

    await q.message.reply_text(msg)


# ===== BUTTON ROUTER =====
async def buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if q.data == "stock":
        await show_stock(update, context)
    elif q.data == "buy":
        await buy_menu(update, context)
    elif q.data == "orders":
        await orders(update, context)
    elif q.data.startswith("price:"):
        await choose_price(update, context)
    elif q.data.startswith("pay:"):
        await payment_method(update, context)


# ===== START WEBHOOK =====
def main():
    setup()

    app = (
        ApplicationBuilder()
        .token(TOKEN)
        .build()
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("addstock", addstock))
    app.add_handler(CommandHandler("adminstock", adminstock))
    app.add_handler(CommandHandler("approve", approve))
    app.add_handler(CommandHandler("reject", reject))
    app.add_handler(CallbackQueryHandler(buttons))
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, messages)
    )

    log.info("NOVA SELL BOT starting in webhook mode")

    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=WEBHOOK_PATH,
        webhook_url=f"{BASE_URL}/{WEBHOOK_PATH}",
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True
    )


if __name__ == "__main__":
    main()
