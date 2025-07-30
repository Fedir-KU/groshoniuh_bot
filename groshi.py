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

# Вкажіть тут ваш chat_id (отриманий через команду /id)
ALLOWED_CHAT_ID = -1001234567890  # Заміни на свій chat_id

# 🛠 Фейковий HTTP-сервер для Render (слухає порт із $PORT)
def keep_port_open():
    PORT = int(os.environ.get("PORT", "10000"))
    Handler = http.server.SimpleHTTPRequestHandler
    with socketserver.TCPServer(("", PORT), Handler) as httpd:
        print(f"Serving fake HTTP on port {PORT}")
        httpd.serve_forever()

threading.Thread(target=keep_port_open, daemon=True).start()

# 📥 Змінні оточення
TOKEN = os.getenv("TELEGRAM_TOKEN")
SHEET_ID = os.getenv("GOOGLE_SHEET_ID")
GOOGLE_CREDS_JSON = os.getenv("GOOGLE_CREDS_JSON")

# 🔐 Авторизація Google Sheets
creds_dict = json.loads(GOOGLE_CREDS_JSON)
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
client = gspread.authorize(creds)
sheet = client.open_by_key(SHEET_ID).sheet1

# Команда /id
def send_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Відправляє chat_id поточного чату"""
    update.message.reply_text(f"Chat ID = {update.effective_chat.id}")

# 📩 Обробка повідомлень
def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    # Ігноруємо повідомлення з інших чатів
    if chat_id != ALLOWED_CHAT_ID:
        return

    message = update.message.text
    user = update.message.from_user.first_name
    date = datetime.now().strftime("%Y-%m-%d")

    match = re.match(r"(?P<cat>\w+)\s+(?P<sum>\d+)[^\d]*(?P<desc>.*)", message)
    if match:
        cat = match.group("cat")
        summ = match.group("sum")
        desc = match.group("desc").strip()
        sheet.append_row([date, user, cat, summ, desc])
        update.message.reply_text(f"✅ Додано: {cat} — {summ} грн — {desc}")
    else:
        update.message.reply_text("⚠️ Формат: 'категорія сума опис'. Наприклад: їжа 200 піца")

# ▶️ Запуск бота
if __name__ == '__main__':
    app = ApplicationBuilder().token(TOKEN).build()
    # Регіструємо команду /id
    app.add_handler(CommandHandler("id", send_id))
    # Регіструємо обробник повідомлень витрат
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    print("Бот запущено!")
    app.run_polling()
