import os
import logging
import threading
import requests
from flask import Flask, request, jsonify
from yt_dlp import YoutubeDL
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ForceReply
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# --- Configuración ---
logging.basicConfig(level=logging.INFO)
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
if not TELEGRAM_TOKEN:
    logging.error("🚨 Debes exportar TELEGRAM_TOKEN con tu token de BotFather.")
    exit(1)

# Google Drive
GDRIVE_CRED_PATH = os.getenv("GOOGLE_CREDS_PATH")
GDRIVE_FOLDER_ID = os.getenv("GDRIVE_FOLDER_ID")
if not (GDRIVE_CRED_PATH and GDRIVE_FOLDER_ID):
    logging.warning("No se ha configurado Google Drive. Los archivos no se subirán.")
else:
    creds = service_account.Credentials.from_service_account_file(
        GDRIVE_CRED_PATH,
        scopes=["https://www.googleapis.com/auth/drive.file"]
    )
    drive_service = build('drive', 'v3', credentials=creds)

# Download bot
N8N_UPLOAD_URL = os.getenv("N8N_UPLOAD_URL", "http://localhost:5678/upload")
DOWNLOAD_DIR = "downloads"
API_PORT = int(os.getenv("PORT", 5001))
TELEGRAM_FILE_LIMIT = 50 * 1024 * 1024  # 50 MB
SUPPORTED_SITES = [
    'youtube.com/watch?v=', 'youtu.be/', 'instagram.com/reel/', 'instagram.com/p/',
    'tiktok.com/', 'twitter.com/', 'x.com/', 'facebook.com/', 'fb.watch/',
    'vimeo.com/', 'dailymotion.com/', 'reddit.com/'
]

# --- Funciones auxiliares ---
def is_supported_url(url: str) -> bool:
    return any(site in url for site in SUPPORTED_SITES)


def choose_format(info: dict, download_type: str) -> str:
    formats = info.get("formats", [])
    if download_type == "video":
        prog = [f for f in formats if f.get("vcodec") != "none" and f.get("acodec") != "none"]
        if prog:
            return max(prog, key=lambda f: (f.get("tbr") or 0))["format_id"]
    audio = [f for f in formats if f.get("acodec") != "none" and f.get("vcodec") in (None, "none")]
    if audio:
        return max(audio, key=lambda f: (f.get("abr") or 0))["format_id"]
    return "best"


def download_video(url: str, download_type: str) -> (str, dict, str):
    # devuelve (status, metadata_dict, path_or_error)
    if not is_supported_url(url):
        return 'error', {'message': 'URL no válida o plataforma no soportada'}, None

    base_opts = {
        'noplaylist': True,
        'outtmpl': os.path.join(DOWNLOAD_DIR, '%(title)s.%(ext)s'),
        'windowsfilenames': True,
    }
    try:
        probe = YoutubeDL({**base_opts, 'format': 'best'})
        info = probe.extract_info(url, download=False)
        fmt = choose_format(info, download_type)
        opts = {**base_opts, 'format': fmt}
        if download_type == 'video':
            opts['merge_output_format'] = 'mp4'
        else:
            opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }]
        ydl = YoutubeDL(opts)
        result = ydl.extract_info(url, download=True)
        path = ydl.prepare_filename(result)
        if download_type == 'audio':
            path = os.path.splitext(path)[0] + '.mp3'
        meta = {
            'title': result.get('title'),
            'author': result.get('uploader'),
            'length': result.get('duration'),
            'type': download_type
        }
        return 'success', meta, path
    except Exception as e:
        logging.error("Error descargando:", exc_info=True)
        return 'error', {'message': str(e)}, None


def upload_to_drive(path: str) -> str:
    if not (GDRIVE_CRED_PATH and GDRIVE_FOLDER_ID):
        return None
    file_metadata = {'name': os.path.basename(path), 'parents': [GDRIVE_FOLDER_ID]}
    media = MediaFileUpload(path, resumable=False)
    file = drive_service.files().create(
        body=file_metadata, media_body=media, fields='webViewLink'
    ).execute()
    return file.get('webViewLink')

# --- API Flask ---
app = Flask(__name__)
@app.route('/download', methods=['POST'])
def download_endpoint():
    data = request.get_json() or {}
    status, meta, path_or_error = download_video(data.get('url'), data.get('type', 'video'))
    if status != 'success':
        return jsonify({'status': 'error', 'message': meta.get('message')}), 400
    return jsonify({'status': 'success', 'metadata': meta, 'path': path_or_error})

def run_flask():
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    app.run(host='0.0.0.0', port=API_PORT, use_reloader=False)

# --- Bot de Telegram ---
async def show_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🔽 Descargar", callback_data='download')],
        [InlineKeyboardButton("❓ Ayuda", callback_data='help')]
    ]
    await update.message.reply_text("¡Bienvenido! Selecciona una opción:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "Usa el menú para seleccionar 'Descargar'. Luego envía la URL y elige formato: video o audio.\n"
        "Los vídeos se subirán también a Google Drive si está configurado."
    )
    await update.callback_query.answer()
    await update.callback_query.message.reply_text(text)

async def download_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await update.callback_query.message.reply_text(
        "Envía el enlace del contenido:", reply_markup=ForceReply(selective=True)
    )

async def handle_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text.strip()
    context.user_data['url'] = url
    keyboard = [
        [InlineKeyboardButton("🎬 Vídeo completo", callback_data='format_video')],
        [InlineKeyboardButton("🎵 Solo audio", callback_data='format_audio')]
    ]
    await update.message.reply_text("¿Qué formato deseas?",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def handle_format(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    dtype = 'audio' if update.callback_query.data == 'format_audio' else 'video'
    url = context.user_data.get('url')
    status, meta, path = download_video(url, dtype)
    if status != 'success':
        await update.callback_query.message.reply_text(f"❌ {meta.get('message')}")
        return
    # Enviar al chat
    await update.callback_query.message.reply_document(
        document=open(path, 'rb'),
        caption=(f"✅ Descargado: {meta['title']}\n👤 {meta['author']}\n⏱ {meta['length']}s")
    )
    # Subir a Drive
    drive_link = upload_to_drive(path)
    if drive_link:
        await update.callback_query.message.reply_text(f"📁 Google Drive: {drive_link}")

# --- Inicialización ---
if __name__ == '__main__':
    threading.Thread(target=run_flask, daemon=True).start()
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    # Handlers
    app.add_handler(CommandHandler('start', show_menu))
    app.add_handler(CallbackQueryHandler(help_command, pattern='^help$'))
    app.add_handler(CallbackQueryHandler(download_start, pattern='^download$'))
    app.add_handler(MessageHandler(filters.TEXT & filters.FORCE_REPLY, handle_url))
    app.add_handler(CallbackQueryHandler(handle_format, pattern='^format_'))
    # Mostrar menú por defecto si no es comando
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, show_menu))
    app.run_polling()
