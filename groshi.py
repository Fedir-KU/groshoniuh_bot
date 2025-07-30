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

# 📥 Змінні оточення та налаштування API ключів
TOKEN = os.getenv("TELEGRAM_TOKEN")
SHEET_ID = os.getenv("GOOGLE_SHEET_ID")
GOOGLE_CREDS_JSON = os.getenv("GOOGLE_CREDS_JSON")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# 🔐 Авторизація OpenAI
openai.api_key = OPENAI_API_KEY

# 🔐 Авторизація Google Sheets і Vision API
ecreds_dict = json.loads(GOOGLE_CREDS_JSON)
sheets_scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
sheets_creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, sheets_scope)

gspread_client = gspread.authorize(sheets_creds)
sheet = gspread_client.open_by_key(SHEET_ID).sheet1

vision_creds = service_account.Credentials.from_service_account_info(creds_dict)
vision_client = vision.ImageAnnotatorClient(credentials=vision_creds)

# 🔎 OCR: витягуємо текст з фотографії
def ocr_extract_text(image_path: str) -> str:
    with open(image_path, 'rb') as img_file:
        content = img_file.read()
    image = vision.Image(content=content)
    result = vision_client.text_detection(image=image)
    annotations = result.text_annotations
    return annotations[0].description if annotations else ''

# 🧠 Парсинг витрат через OpenAI GPT
def parse_expense(text: str) -> dict:
    prompt = f"""
    Видобери з цього тексту категорію, суму (цілим числом) та короткий опис:
    "{text}"
    Відповідай JSON-об'єктом з полями: category, amount, description.
    """
    resp = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
    )
    return json.loads(resp.choices[0].message.content)

# Команда /id: повертає chat_id
async def send_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"Chat ID = {update.effective_chat.id}")

# 📝 Команда /query: простий запит до таблиці через GPT
async def query_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id != ALLOWED_CHAT_ID:
        return
    query = " ".join(context.args)
    records = sheet.get_all_records()
    prompt = f"У мене є дані витрат: {records}\nЗапит: {query}\nВідповідь українською:" 
    resp = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
    )
    await update.message.reply_text(resp.choices[0].message.content)

# 📩 Обробка повідомлень витрат\async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id != ALLOWED_CHAT_ID:
        return

    # якщо є фото — спочатку OCR
    if update.message.photo:
        file = await context.bot.get_file(update.message.photo[-1].file_id)
        image_path = "/tmp/receipt.jpg"
        await file.download_to_drive(image_path)
        text = ocr_extract_text(image_path)
    else:
        text = update.message.text

    try:
        expense = parse_expense(text)
        cat = expense['category']
        amount = expense['amount']
        desc = expense.get('description', '').strip()
    except Exception as e:
        await update.message.reply_text("⚠️ Не вдалося розпізнати витрату. Спробуйте інший формат або фото.")
        return

    date = datetime.now().strftime("%Y-%m-%d")
    user = update.message.from_user.first_name
    sheet.append_row([date, user, cat, amount, desc])
    await update.message.reply_text(f"✅ Додано: {cat} — {amount} грн — {desc}")

# ▶️ Запуск бота
if __name__ == '__main__':
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("id", send_id))
    app.add_handler(CommandHandler("query", query_handler))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    print("Бот запущено!")
    app.run_polling()
