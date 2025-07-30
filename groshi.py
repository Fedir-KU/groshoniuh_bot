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
import openai
from google.cloud import vision
from google.oauth2 import service_account

# Дозволений chat_id вашої групи/чату
ALLOWED_CHAT_ID = -4729811445  # <-- замініть на свій ID

# Фейковий HTTP‑сервер для Render (слухає порт з $PORT)
def keep_port_open():
    PORT = int(os.environ.get("PORT", "10000"))
    Handler = http.server.SimpleHTTPRequestHandler
    with socketserver.TCPServer(("", PORT), Handler) as httpd:
        print(f"Serving fake HTTP on port {PORT}")
        httpd.serve_forever()
threading.Thread(target=keep_port_open, daemon=True).start()

# Змінні оточення
TOKEN = os.getenv("TELEGRAM_TOKEN")
SHEET_ID = os.getenv("GOOGLE_SHEET_ID")
GOOGLE_CREDS_JSON = os.getenv("GOOGLE_CREDS_JSON")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Ініціалізація OpenAI
openai.api_key = OPENAI_API_KEY

# Авторизація Google Sheets та Vision API
creds_dict = json.loads(GOOGLE_CREDS_JSON)
sheets_scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive"
]
sheets_creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, sheets_scope)
gspread_client = gspread.authorize(sheets_creds)
sheet = gspread_client.open_by_key(SHEET_ID).sheet1

vision_creds = service_account.Credentials.from_service_account_info(creds_dict)
vision_client = vision.ImageAnnotatorClient(credentials=vision_creds)

# OCR: витяг тексту з фото
def ocr_extract_text(path: str) -> str:
    with open(path, 'rb') as f:
        img = f.read()
    image = vision.Image(content=img)
    result = vision_client.text_detection(image=image)
    annotations = result.text_annotations
    return annotations[0].description if annotations else ''

# GPT-парсинг витрати
def parse_expense(text: str) -> dict:
    prompt = (
        f"Видобери з цього тексту категорію, суму (цілим числом) та короткий опис:\n"
        f"\"{text}\"\n"
        "Відповідай JSON-об'єктом з полями category, amount, description."
    )
    resp = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        messages=[{"role":"user","content":prompt}],
        temperature=0
    )
    return json.loads(resp.choices[0].message.content)

# /id
async def send_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != ALLOWED_CHAT_ID:
        return
    await update.message.reply_text(f"Chat ID = {update.effective_chat.id}")

# /help
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != ALLOWED_CHAT_ID:
        return
    help_text = (
        "🔹 Доступні команди:\n"
        "/id — показати chat_id чату\n"
        "/help — цей довідник\n"
        "/query <запит> — запит до таблиці витрат\n"
        "Просто надішліть повідомлення або фото чеку — бот автоматично розпізнає витрату."
    )
    await update.message.reply_text(help_text)

# /query
async def query_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != ALLOWED_CHAT_ID:
        return
    q = " ".join(context.args)
    if not q:
        await update.message.reply_text(
            "⚠️ Використання: /query <запит>\n"
            "Наприклад: /query скільки я витратив на їжу цього місяця?"
        )
        return
    records = sheet.get_all_records()
    prompt = (
        f"У мене є дані витрат у форматі JSON: {records}\n"
        f"Запит: {q}\nВідповідь українською:"
    )
    resp = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        messages=[{"role":"user","content":prompt}],
        temperature=0
    )
    await update.message.reply_text(resp.choices[0].message.content)

# обробка витрат
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != ALLOWED_CHAT_ID:
        return
    if update.message.photo:
        file = await context.bot.get_file(update.message.photo[-1].file_id)
        path = "/tmp/receipt.jpg"
        await file.download_to_drive(path)
        text = ocr_extract_text(path)
    else:
        text = update.message.text or ''
    try:
        exp = parse_expense(text)
        cat = exp['category']
        amount = exp['amount']
        desc = exp.get('description', '')
    except Exception:
        await update.message.reply_text(
            "⚠️ Не вдалося розпізнати витрату. Спробуйте інший формат або фото."
        )
        return
    date = datetime.now().strftime("%Y-%m-%d")
    user = update.message.from_user.first_name
    sheet.append_row([date, user, cat, amount, desc])
    await update.message.reply_text(f"✅ Додано: {cat} — {amount} грн — {desc}")

# запуск бота
if __name__ == '__main__':
    app = ApplicationBuilder().token(TOKEN).build()
    # скидаємо webhook і чергу оновлень перед polling
    app.bot.delete_webhook(drop_pending_updates=True)
    app.add_handler(CommandHandler("id", send_id))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("query", query_handler))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    print("Бот запущено!")
    # запускаємо polling і відкидаємо старі апдейти
    app.run_polling(drop_pending_updates=True)
