from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes
import re
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime

# 🔐 Google Sheets
SHEET_ID = 'тут_ID_твоєї_таблиці'
GOOGLE_CREDENTIALS_FILE = 'credentials.json'  # твій json з Google Cloud

# Підключення до таблиці
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_name(GOOGLE_CREDENTIALS_FILE, scope)
client = gspread.authorize(creds)
sheet = client.open_by_key(SHEET_ID).sheet1

# 📥 Обробка повідомлень
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message.text
    user = update.message.from_user.first_name
    date = datetime.now().strftime("%Y-%m-%d")

    # 🔍 Парсимо повідомлення (категорія сума опис)
    match = re.match(r"(?P<cat>\w+)\s+(?P<sum>\d+)[^\d]*(?P<desc>.*)", message)
    if match:
        cat = match.group("cat")
        summ = match.group("sum")
        desc = match.group("desc").strip()

        # Додаємо в таблицю
        sheet.append_row([date, user, cat, summ, desc])
        await update.message.reply_text(f"✅ Додано: {cat} — {summ} грн — {desc}")
    else:
        await update.message.reply_text("⚠️ Не зміг розпізнати витрату. Формат: \"їжа 150 піца\"")

# 🚀 Запуск бота
if __name__ == '__main__':
    TOKEN = "тут_твій_бот_токен"
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    print("Бот працює!")
    app.run_polling()
