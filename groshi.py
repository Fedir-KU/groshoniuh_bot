import os
import re
import json
import threading
import http.server
import socketserver
from datetime import datetime
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import pandas as pd

# Дозволений chat_id вашої групи/чату
ALLOWED_CHAT_ID = -4729811445  # <-- замініть на свій ID

# Запуск фейкового HTTP-сервера для Render

def keep_port_open():
    PORT = int(os.environ.get("PORT", "10000"))
    Handler = http.server.SimpleHTTPRequestHandler
    with socketserver.TCPServer(("", PORT), Handler) as httpd:
        httpd.serve_forever()

threading.Thread(target=keep_port_open, daemon=True).start()

# Змінні оточення та авторизація Google Sheets
TOKEN = os.getenv("TELEGRAM_TOKEN")
SHEET_ID = os.getenv("GOOGLE_SHEET_ID")
GOOGLE_CREDS_JSON = os.getenv("GOOGLE_CREDS_JSON")

creds_dict = json.loads(GOOGLE_CREDS_JSON)
sheets_creds = ServiceAccountCredentials.from_json_keyfile_dict(
    creds_dict,
    ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
)
gspread_client = gspread.authorize(sheets_creds)
sheet = gspread_client.open_by_key(SHEET_ID).sheet1

# Ініціалізація rule-based категорій
CATEGORY_KEYWORDS = {
    "їжа": ["їжа", "піца", "хліб", "кава", "суп"],
    "транспорт": ["таксі", "uber", "bus", "метро", "бензин"],
    "розваги": ["кіно", "театр", "ігри", "клуб"],
    "покупки": ["купив", "магазин", "amazon", "ozon"],
    "побут": ["комунал", "інтернет", "зв'язок", "газ", "світло", "платеж"]
}

def classify_category(text: str) -> str:
    low = text.lower()
    for cat, kws in CATEGORY_KEYWORDS.items():
        if any(kw in low for kw in kws):
            return cat
    return "інше"

# /id — повертає chat_id
async def send_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != ALLOWED_CHAT_ID:
        return
    await update.message.reply_text(f"Chat ID = {update.effective_chat.id}")

# /help — список команд
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != ALLOWED_CHAT_ID:
        return
    help_text = (
        "🔹 Доступні команди:\n"
        "/id — показати chat_id\n"
        "/help — ця довідка\n"
        "Просто надсилайте “Покупка Сума” або фото чеку."
    )
    await update.message.reply_text(help_text)

# Обробка повідомлень витрат
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != ALLOWED_CHAT_ID:
        return
    # текст повідомлення
    text = update.message.text or ''
    # формат "Покупка Сума"
    m = re.match(r'(?P<item>[\w\s]+?)\s+(?P<amount>\d+)', text)
    if not m:
        return await update.message.reply_text(
            "⚠️ Формат: Покупка Сума. Наприклад: Ковбаса 80"
        )
    item   = m.group('item').strip()
    amount = m.group('amount')
    user   = update.message.from_user.first_name

    now      = datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    # дні тижня UA
    days = {0:'Понеділок',1:'Вівторок',2:'Середа',3:'Четвер',4:"П'ятниця",5:'Субота',6:'Неділя'}
    day_name  = days[now.weekday()]
    week_num  = now.isocalendar()[1]
    # місяці UA
    months = {1:'січень',2:'лютий',3:'березень',4:'квітень',5:'травень',6:'червень',7:'липень',8:'серпень',9:'вересень',10:'жовтень',11:'листопад',12:'грудень'}
    month_name = months[now.month]

    # підрахунок витрат за сьогодні
    records = sheet.get_all_records()
    daily_total = sum(
        int(r.get('Сума, грн', r.get('sum',0)))
        for r in records
        if r.get('Дата') == date_str
    )

    # Створюємо рядок: Тиждень, День тижня, Покупка, Сума, Користувач, Дата, Місяць, Витрати за день
    row = [week_num, day_name, item, amount, user, date_str, month_name, daily_total]
    sheet.append_row(row, value_input_option='USER_ENTERED')

    await update.message.reply_text(
        f"✅ Додано: {item} — {amount} грн  ({day_name}, тиждень {week_num})"
    )

# Старт бота
if __name__ == '__main__':
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("id", send_id))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    print("Бот запущено!")
    app.run_polling()
