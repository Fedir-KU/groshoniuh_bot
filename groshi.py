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
import easyocr
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

# Ініціалізація OCR (EasyOCR)
reader = easyocr.Reader(["uk", "en"], gpu=False)

# Ключові слова для rule-based категорій
CATEGORY_KEYWORDS = {
    "їжа": ["їжа", "піца", "хліб", "кава", "суп"],
    "транспорт": ["таксі", "uber", "bus", "метро", "бензин"],
    "розваги": ["кіно", "театр", "ігри", "клуб"],
    "покупки": ["купив", "магазин", "amazon", "ozon"],
    "побут": ["комунал", "інтернет", "зв'язок", "газ", "світло", "платеж"]
}

def classify_category(text: str) -> str:
    low = text.lower()
    for cat, keywords in CATEGORY_KEYWORDS.items():
        for kw in keywords:
            if kw in low:
                return cat
    return "інше"

# Команда /id — повертає chat_id
async def send_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != ALLOWED_CHAT_ID:
        return
    await update.message.reply_text(f"Chat ID = {update.effective_chat.id}")

# Команда /help — список команд
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != ALLOWED_CHAT_ID:
        return
    help_text = (
        "🔹 Доступні команди:\n"
        "/id — показати chat_id\n"
        "/help — ця довідка\n"
        "/sum <категорія> [YYYY-MM] — сума по категорії за місяць\n"
        "/report [YYYY-MM] — звіт по всіх категоріях за місяць\n"
        "Просто надішліть повідомлення або фото чеку — бот запише витрату."
    )
    await update.message.reply_text(help_text)

# Команда /sum — сума витрат по категорії
async def sum_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != ALLOWED_CHAT_ID:
        return
    args = context.args
    if not args:
        await update.message.reply_text("⚠️ Використання: /sum <категорія> [YYYY-MM]")
        return
    cat = args[0]
    month = args[1] if len(args) > 1 else datetime.now().strftime("%Y-%m")
    df = pd.DataFrame(sheet.get_all_records())
    if df.empty:
        await update.message.reply_text("Нема записів у таблиці.")
        return
    df["date"] = pd.to_datetime(df["date"])
    filtered = df[(df["cat"] == cat) & (df["date"].dt.strftime("%Y-%m") == month)]
    total = filtered["sum"].astype(int).sum()
    await update.message.reply_text(f"У {month} на {cat} витрачено {total} грн")

# Команда /report — звіт усіх категорій за місяць
async def report_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != ALLOWED_CHAT_ID:
        return
    month = context.args[0] if context.args else datetime.now().strftime("%Y-%m")
    df = pd.DataFrame(sheet.get_all_records())
    if df.empty:
        await update.message.reply_text("Нема записів у таблиці.")
        return
    df["date"] = pd.to_datetime(df["date"])
    filtered = df[df["date"].dt.strftime("%Y-%m") == month]
    sums = filtered.groupby("cat")["sum"].apply(lambda x: x.astype(int).sum())
    if sums.empty:
        await update.message.reply_text(f"Нема витрат за {month}.")
        return
    lines = [f"{cat}: {amt} грн" for cat, amt in sums.items()]
    await update.message.reply_text(f"Звіт за {month}:\n" + "\n".join(lines))

# Обробка повідомлень витрат
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != ALLOWED_CHAT_ID:
        return
    # OCR для фото
    if update.message.photo:
        file = await context.bot.get_file(update.message.photo[-1].file_id)
        path = '/tmp/receipt.jpg'
        await file.download_to_drive(path)
        text = ' '.join(reader.readtext(path, detail=0))
    else:
        text = update.message.text or ''
    # Парсимо суму
    m = re.search(r"(\d+)", text)
    if not m:
        await update.message.reply_text("⚠️ Не знайдено суму. Напишіть 'категорія сума опис'.")
        return
    amount = m.group(1)
    cat = classify_category(text)
    parts = text.split(amount, 1)
    desc = parts[1].strip() if len(parts) > 1 else ''
    date = datetime.now().strftime("%Y-%m-%d")
    user = update.message.from_user.first_name
    sheet.append_row([date, user, cat, amount, desc])
    await update.message.reply_text(f"✅ Додано: {cat} — {amount} грн — {desc}")

# Запуск бота
if __name__ == '__main__':
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("id", send_id))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("sum", sum_command))
    app.add_handler(CommandHandler("report", report_command))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    print("Бот запущено!")
    app.run_polling()
