import os
import re
import json
import threading
import http.server
import socketserver
from datetime import datetime, date, timedelta
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import pandas as pd

# ID вашого Telegram-чату
ALLOWED_CHAT_ID = -4729811445

# Фейковий HTTP-сервер для Render
def keep_port_open():
    PORT = int(os.environ.get("PORT", "10000"))
    Handler = http.server.SimpleHTTPRequestHandler
    with socketserver.TCPServer(("", PORT), Handler) as httpd:
        httpd.serve_forever()
threading.Thread(target=keep_port_open, daemon=True).start()

# Авторизація Google Sheets
TOKEN = os.getenv("TELEGRAM_TOKEN")
SHEET_ID = os.getenv("GOOGLE_SHEET_ID")
GOOGLE_CREDS_JSON = os.getenv("GOOGLE_CREDS_JSON")
creds_dict = json.loads(GOOGLE_CREDS_JSON)
creds = ServiceAccountCredentials.from_json_keyfile_dict(
    creds_dict,
    ["https://spreadsheets.google.com/feeds","https://www.googleapis.com/auth/drive"]
)
client = gspread.authorize(creds)
sheet = client.open_by_key(SHEET_ID).sheet1

# ——— Основні команди ———
async def send_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != ALLOWED_CHAT_ID: return
    await update.message.reply_text(f"Chat ID = {update.effective_chat.id}")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != ALLOWED_CHAT_ID: return
    text = (
        "🔹 Доступні команди:\n"
        "/id — показати chat_id\n"
        "/help — ця довідка\n"
        "/day — ваші витрати за сьогодні\n"
        "/dayall — витрати всіх за сьогодні\n"
        "/week — ваші витрати від останнього понеділка\n"
        "/weekall — витрати всіх від понеділка\n"
        "/month — ваші витрати за місяць\n"
        "/monthall — витрати всіх за місяць"
    )
    await update.message.reply_text(text)

# ——— Запис витрати через текстове повідомлення ———
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != ALLOWED_CHAT_ID: return
    text = update.message.text or ''
    m = re.match(r"(?P<item>[\w\s]+?)\s+(?P<amount>\d+)", text)
    if not m:
        return await update.message.reply_text(
            "⚠️ Формат: Покупка Сума. Наприклад: Ковбаса 80"
        )
    item   = m.group('item').strip()
    amount = int(m.group('amount'))
    user   = update.message.from_user.first_name

    now       = datetime.now()
    date_str  = now.strftime("%Y-%m-%d")
    days      = {0:'Понеділок',1:'Вівторок',2:'Середа',3:'Четвер',4:"П'ятниця",5:'Субота',6:'Неділя'}
    day_name  = days[now.weekday()]
    week_num  = now.isocalendar()[1]
    months    = {1:'січень',2:'лютий',3:'березень',4:'квітень',5:'травень',6:'червень',7:'липень',8:'серпень',9:'вересень',10:'жовтень',11:'листопад',12:'грудень'}
    month_name= months[now.month]

    # Порожня категорія за замовчуванням
    sheet.append_row([
        week_num, day_name, item, amount, user, date_str, "", month_name
    ], value_input_option='USER_ENTERED')

    # Перевірка денного ліміту
    records = sheet.get_all_records()
    df = pd.DataFrame(records)
    df.rename(columns={
        'Тиждень':'week','День тижня':'day','Покупка':'item','Сума, грн':'sum',
        'Користувач':'user','Дата':'date','Категорія':'cat','Місяць':'month'
    }, inplace=True)
    df['date'] = pd.to_datetime(df['date']).dt.date
    today = date.today()
    total_today = df[(df['user']==user)&(df['date']==today)]['sum'].astype(int).sum()
    if total_today > 250:
        await update.message.reply_text(
            f"⚠️ @{user}, ви перевищили денний ліміт 250 грн! Загалом: {total_today} грн"
        )
    await update.message.reply_text(
        f"✅ Додано: {item} — {amount} грн  ({day_name}, тиждень {week_num})"
    )

# ——— Допоміжна утиліта для звітів ———
def _prepare_df():
    rec = sheet.get_all_records()
    df = pd.DataFrame(rec)
    df.rename(columns={
        'Тиждень':'week','День тижня':'day','Покупка':'item','Сума, грн':'sum',
        'Користувач':'user','Дата':'date','Категорія':'cat','Місяць':'month'
    }, inplace=True)
    df['date'] = pd.to_datetime(df['date']).dt.date
    df['sum']  = df['sum'].astype(int)
    return df

# ——— Команди звітів ———
async def day_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != ALLOWED_CHAT_ID: return
    df = _prepare_df()
    me = update.message.from_user.first_name
    today = date.today()
    d = df[(df['user']==me)&(df['date']==today)]
    total = d['sum'].sum()
    text = f"🔸 Сьогодні ({today}) ви витратили {total} грн"
    if not d.empty:
        stats = d.groupby('cat')['sum'].sum()
        text += "\nПо категоріям:" + "\n".join(f"{c}: {s} грн" for c,s in stats.items())
    await update.message.reply_text(text)

async def dayall_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != ALLOWED_CHAT_ID: return
    df = _prepare_df()
    today = date.today()
    d = df[df['date']==today]
    total = d['sum'].sum()
    text = f"🔹 Сьогодні ({today}) всього витрачено {total} грн"
    if not d.empty:
        stats = d.groupby('cat')['sum'].sum()
        text += "\nПо категоріям:" + "\n".join(f"{c}: {s} грн" for c,s in stats.items())
    await update.message.reply_text(text)

async def week_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != ALLOWED_CHAT_ID: return
    df = _prepare_df()
    me = update.message.from_user.first_name
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    d = df[(df['user']==me)&(df['date']>=monday)&(df['date']<=today)]
    total = d['sum'].sum()
    text = f"🔸 З {monday} до {today} ви витратили {total} грн"
    if not d.empty:
        stats = d.groupby('cat')['sum'].sum()
        text += "\nПо категоріям:" + "\n".join(f"{c}: {s} грн" for c,s in stats.items())
    await update.message.reply_text(text)

async def weekall_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != ALLOWED_CHAT_ID: return
    df = _prepare_df()
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    d = df[(df['date']>=monday)&(df['date']<=today)]
    total = d['sum'].sum()
    text = f"🔹 З {monday} до {today} всього витрачено {total} грн"
    if not d.empty:
        stats = d.groupby('cat')['sum'].sum()
        text += "\nПо категоріям:" + "\n".join(f"{c}: {s} грн" for c,s in stats.items())
    await update.message.reply_text(text)

async def month_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != ALLOWED_CHAT_ID: return
    df = _prepare_df()
    me = update.message.from_user.first_name
    today = date.today()
    first = today.replace(day=1)
    d = df[(df['user']==me)&(df['date']>=first)&(df['date']<=today)]
    total = d['sum'].sum()
    text = f"🔸 З початку місяця ви витратили {total} грн"
    if not d.empty:
        stats = d.groupby('cat')['sum'].sum()
        text += "\nПо категоріям:" + "\n".join(f"{c}: {s} грн" for c,s in stats.items())
    await update.message.reply_text(text)

async def monthall_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != ALLOWED_CHAT_ID: return
    df = _prepare_df()
    today = date.today()
    first = today.replace(day=1)
    d = df[(df['date']>=first)&(df['date']<=today)]
    total = d['sum'].sum()
    text = f"🔹 З початку місяця всього витрачено {total} грн"
    if not d.empty:
        stats = d.groupby('cat')['sum'].sum()
        text += "\nПо категоріям:" + "\n".join(f"{c}: {s} грн" for c,s in stats.items())
    await update.message.reply_text(text)

# ——— Автозапуск звітів через automations — не забудь запланувати:
# /dayall щодня о 23:30 київського часу
# /weekall щонеділі о 23:30
# /monthall в останній день місяця о 23:30

# ——— Регістрація хендлерів і запуск бота ———
if __name__ == '__main__':
    app = ApplicationBuilder().token(TOKEN).build()
    # базові
    app.add_handler(CommandHandler("id", send_id))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    # звіти
    app.add_handler(CommandHandler("day", day_command))
    app.add_handler(CommandHandler("dayall", dayall_command))
    app.add_handler(CommandHandler("week", week_command))
    app.add_handler(CommandHandler("weekall", weekall_command))
    app.add_handler(CommandHandler("month", month_command))
    app.add_handler(CommandHandler("monthall", monthall_command))
    print("Бот запущено!")
    app.run_polling()
