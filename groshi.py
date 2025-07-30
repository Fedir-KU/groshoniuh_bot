import os
import re
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes
from datetime import datetime
import json
import gspread
from oauth2client.service_account import ServiceAccountCredentials

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

# 📩 Обробка повідомлень
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message.text
    user = update.message.from_user.first_name
    date = datetime.now().strftime("%Y-%m-%d")

    match = re.match(r"(?P<cat>\w+)\s+(?P<sum>\d+)[^\d]*(?P<desc>.*)", message)
    if match:
        cat = match.group("cat")
        summ = match.group("sum")
        desc = match.group("desc").strip()
        sheet.append_row([date, user, cat, summ, desc])
        await update.message.reply_text(f"✅ Додано: {cat} — {summ} грн — {desc}")
    else:
        await update.message.reply_text("⚠️ Формат: 'категорія сума опис'. Наприклад: їжа 200 піца")

# ▶️ Запуск бота
if __name__ == '__main__':
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    print("Бот запущено!")
    app.run_polling()
