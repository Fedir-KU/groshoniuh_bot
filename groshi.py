import os
import re
import json
import threading
import http.server
import socketserver
from datetime import datetime
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes
)
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import easyocr
import pandas as pd

ALLOWED_CHAT_ID = -4729811445  # <-- замініть на свій ID

# Фейковий HTTP‑сервер для Render
def keep_port_open():
    PORT = int(os.environ.get("PORT", "10000"))
    Handler = http.server.SimpleHTTPRequestHandler
    with socketserver.TCPServer(("", PORT), Handler) as httpd:
        httpd.serve_forever()
threading.Thread(target=keep_port_open, daemon=True).start()

# Авторизація Google Sheets
TOKEN = os.getenv("TELEGRAM_TOKEN")
SHEET_ID = os.getenv("GOOGLE_SHEET_ID")
CREDS_JSON = os.getenv("GOOGLE_CREDS_JSON")
creds_dict = json.loads(CREDS_JSON)
sheets_creds = ServiceAccountCredentials.from_json_keyfile_dict(
    creds_dict,
    ["https://spreadsheets.google.com/feeds","https://www.googleapis.com/auth/drive"]
)
client = gspread.authorize(sheets_creds)
sheet = client.open_by_key(SHEET_ID).sheet1

# OCR (EasyOCR)
reader = easyocr.Reader(["uk","en"], gpu=False)

# Rule‑based категорії
CATEGORY_KEYWORDS = {
    "їжа": ["їжа","піца","хліб","кава","суп"],
    "транспорт": ["таксі","uber","bus","метро","бензин"],
    "розваги": ["кіно","театр","ігри","клуб"],
    "покупки": ["купив","магазин","amazon","ozon"],
    "побут": ["комунал","інтернет","зв'язок","газ","світло","платеж"]
}
def classify_category(text: str) -> str:
    low = text.lower()
    for cat, kws in CATEGORY_KEYWORDS.items():
        if any(kw in low for kw in kws):
            return cat
    return "інше"

# /id
async def send_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != ALLOWED_CHAT_ID:
        return
    await update.message.reply_text(f"Chat ID = {update.effective_chat.id}")

# /help
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != ALLOWED_CHAT_ID:
        return
    await update.message.reply_text(
        "🔹 Доступні команди:\n"
        "/id — показати chat_id\n"
        "/help — ця довідка\n"
        "/sum <категорія> [YYYY-MM] — сума витрат за місяць\n"
        "/report [YYYY-MM] — звіт за місяць\n"
        "Або просто надішліть “категорія сума опис” чи фото чеку."
    )

# /sum
async def sum_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != ALLOWED_CHAT_ID:
        return
    args = context.args
    if not args:
        return await update.message.reply_text("⚠️ Використання: /sum <категорія> [YYYY-MM]")
    cat = args[0]
    month = args[1] if len(args)>1 else datetime.now().strftime("%Y-%m")
    df = pd.DataFrame(sheet.get_all_records())
    if df.empty:
        return await update.message.reply_text("Нема записів у таблиці.")
    df["date"] = pd.to_datetime(df["date"])
    filt = df[(df["cat"]==cat)&(df["date"].dt.strftime("%Y-%m")==month)]
    total = filt["sum"].astype(int).sum()
    await update.message.reply_text(f"У {month} на {cat} витрачено {total} грн")

# /report
async def report_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != ALLOWED_CHAT_ID:
        return
    month = context.args[0] if context.args else datetime.now().strftime("%Y-%m")
    df = pd.DataFrame(sheet.get_all_records())
    if df.empty:
        return await update.message.reply_text("Нема записів у таблиці.")
    df["date"] = pd.to_datetime(df["date"])
    filt = df[df["date"].dt.strftime("%Y-%m")==month]
    sums = filt.groupby("cat")["sum"].apply(lambda x: x.astype(int).sum())
    if sums.empty:
        return await update.message.reply_text(f"Нема витрат за {month}.")
    lines = [f"{c}: {a} грн" for c,a in sums.items()]
    await update.message.reply_text(f"Звіт за {month}:\n"+ "\n".join(lines))

# Обробка повідомлень/фото
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != ALLOWED_CHAT_ID:
        return
    # OCR
    if update.message.photo:
        file = await context.bot.get_file(update.message.photo[-1].file_id)
        path = "/tmp/receipt.jpg"
        await file.download_to_drive(path)
        text = " ".join(reader.readtext(path, detail=0))
    else:
        text = update.message.text or ""
    # сума
    m = re.search(r"(\d+)", text)
    if not m:
        return await update.message.reply_text("⚠️ Не знайдено суму. Напишіть 'категорія сума опис'.")
    amount = m.group(1)
    cat = classify_category(text)
    desc = text.split(amount,1)[1].strip() if text else ""
    date = datetime.now().strftime("%Y-%m-%d")
    user = update.message.from_user.first_name
    sheet.append_row([date, user, cat, amount, desc])
    await update.message.reply_text(f"✅ Додано: {cat} — {amount} грн — {desc}")

# Старт
if __name__=="__main__":
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("id", send_id))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("sum", sum_command))
    app.add_handler(CommandHandler("report", report_command))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    print("Бот запущено!")
    app.run_polling()
