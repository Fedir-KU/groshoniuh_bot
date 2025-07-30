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
    ContextTypes,
    CallbackContext
)
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import openai
from google.cloud import vision
from google.oauth2 import service_account

# Дозволений chat_id вашої групи/чату
ALLOWED_CHAT_ID = -4729811445  # <-- замініть на свій ID

# 🛠 Запуск фейкового HTTP-сервера (Render використовує порт із $PORT)
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
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Ініціалізація OpenAI
openai.api_key = OPENAI_API_KEY
print("DEBUG: OPENAI_API_KEY=", OPENAI_API_KEY)

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

# 🖼 OCR: витяг тексту з фото
def ocr_extract_text(path: str) -> str:
    with open(path, 'rb') as f:
        content = f.read()
    image = vision.Image(content=content)
    result = vision_client.text_detection(image=image)
    return result.text_annotations[0].description if result.text_annotations else ''

# 🧠 GPT-парсинг витрати
def parse_expense(text: str) -> dict:
    prompt = (
        f"Видобери з цього тексту категорію, суму (цілим числом) та короткий опис:\n"
        f"\"{text}\"\n"
        "Відповідай JSON-об'єктом з полями category, amount, description."
    )
    # Використовуємо новий інтерфейс openai>=1.0.0
    resp = openai.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[{"role":"user","content":prompt}],
        temperature=0
    )
    return json.loads(resp.choices[0].message.content)

# ▶️ /id — показати chat_id
async def send_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != ALLOWED_CHAT_ID:
        return
    await update.message.reply_text(f"Chat ID = {update.effective_chat.id}")

# ▶️ /help — список команд
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

# ▶️ /query — обробка запитів до таблиці через GPT
async def query_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != ALLOWED_CHAT_ID:
        return
    # debug
    print(">>> query_handler called with args:", context.args)
    await update.message.reply_text(f"Отримав args: {context.args}")
    try:
        q = " ".join(context.args)
        if not q:
            await update.message.reply_text(
                "⚠️ Використання: /query <запит>\n"
                "Наприклад: /query скільки я витратив на їжу цього місяця?"
            )
            return
        records = sheet.get_all_records()
        records = records[-50:] if len(records) > 50 else records
        records_json = json.dumps(records, ensure_ascii=False)
        prompt = (
            f"У мене є дані витрат у форматі JSON:\n{records_json}\n"
            f"Запит: {q}\nОтвіт українською, коротко:"
        )
        # Новий інтерфейс OpenAI
        resp = openai.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role":"user","content":prompt}],
            temperature=0
        )
        answer = resp.choices[0].message.content
        await update.message.reply_text(answer)
    except Exception as e:
        print("Error in query_handler:", e)
        import traceback; traceback.print_exc()
        await update.message.reply_text(f"⚠️ Помилка виконання /query: {e}")

# ▶️ Обробка текстових повідомлень та фото чеків
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
        desc = exp.get('description', '').strip()
    except Exception as e:
        print("Error in parse_expense:", e)
        await update.message.reply_text(
            "⚠️ Не вдалося розпізнати витрату. Спробуйте інший формат або фото."
        )
        return
    date = datetime.now().strftime("%Y-%m-%d")
    user = update.message.from_user.first_name
    sheet.append_row([date, user, cat, amount, desc])
    await update.message.reply_text(f"✅ Додано: {cat} — {amount} грн — {desc}")

# ▶️ Global error handler
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    print("❗️ Exception in handler:", context.error)
    if hasattr(update, 'effective_message') and update.effective_message:
        await update.effective_message.reply_text("⚠️ Виникла помилка. Перевір логи.")

# ▶️ Запуск бота
if __name__ == '__main__':
    import asyncio
    app = ApplicationBuilder().token(TOKEN).build()
    # видаляємо webhook та старі апдейти
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(app.bot.delete_webhook(drop_pending_updates=True))
    # реєстрація хендлерів
    app.add_handler(CommandHandler("id", send_id))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("query", query_handler))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    app.add_error_handler(error_handler)

    print("Бот запущено!")
    # polling з відкиданням старих апдейтів
    app.run_polling(drop_pending_updates=True)
