import os
import logging
import threading
import random
import requests

from flask import Flask, request, jsonify
from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ForceReply
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters
)

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# --- Logging ---
logging.basicConfig(level=logging.INFO)

# --- Entorno ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
if not TELEGRAM_TOKEN:
    logging.error("🚨 Debes exportar TELEGRAM_TOKEN con tu token de BotFather.")
    exit(1)

PROXIES = [
    p.strip()
    for p in os.getenv("PROXIES", "").split(",")
    if p.strip()
]
INVIDIOUS_API_URL = os.getenv("INVIDIOUS_API_URL")  # ej: https://yewtu.be

# --- Google Drive (Service Account) ---
GDRIVE_CRED_PATH = os.getenv("GOOGLE_CREDS_PATH")
GDRIVE_FOLDER_ID = os.getenv("GDRIVE_FOLDER_ID")
if GDRIVE_CRED_PATH and GDRIVE_FOLDER_ID:
    creds = service_account.Credentials.from_service_account_file(
        GDRIVE_CRED_PATH,
        scopes=["https://www.googleapis.com/auth/drive.file"]
    )
    drive_service = build("drive", "v3", credentials=creds)
else:
    logging.warning("Google Drive no configurado; se omitirá subida.")

# --- Configuración de descarga & Flask ---
DOWNLOAD_DIR = "downloads"
API_PORT = int(os.getenv("PORT", 5001))
TELEGRAM_FILE_LIMIT = 50 * 1024 * 1024  # 50 MB
SUPPORTED_SITES = [
    "youtube.com/watch?v=", "youtu.be/",
    "instagram.com/reel/", "instagram.com/p/",
    "tiktok.com/", "twitter.com/", "x.com/",
    "facebook.com/", "fb.watch/",
    "vimeo.com/", "dailymotion.com/", "reddit.com/"
]
ELEGIR_TIPO = range(1)

# --- Helpers ---
def get_proxy_dict():
    """Devuelve un dict de proxy aleatorio o None."""
    if PROXIES:
        p = random.choice(PROXIES)
        return {"http": p, "https": p}
    return None

def is_supported_url(url: str) -> bool:
    return any(site in url for site in SUPPORTED_SITES)

def choose_format(info: dict, download_type: str) -> str:
    """Elige mejor formato progresivo (vídeo) o de audio."""
    formats = info.get("formats", [])
    if download_type == "video":
        prog = [f for f in formats
                if f.get("vcodec") != "none" and f.get("acodec") != "none"]
        if prog:
            return max(prog, key=lambda f: (f.get("tbr") or 0))["format_id"]
    audio = [f for f in formats
             if f.get("acodec") != "none"
             and f.get("vcodec") in (None, "none")]
    if audio:
        return max(audio, key=lambda f: (f.get("abr") or 0))["format_id"]
    return "best"

def invidious_download(video_id: str, download_type: str):
    """Descarga vía Invidious si YouTube bloquea la petición."""
    if not INVIDIOUS_API_URL:
        raise Exception("Invidious no configurado")
    # 1) Info JSON
    resp = requests.get(
        f"{INVIDIOUS_API_URL}/api/v1/videos/{video_id}",
        proxies=get_proxy_dict(),
        timeout=15
    )
    resp.raise_for_status()
    info = resp.json()
    # 2) Elegir formato y obtener URL
    fmt = choose_format(info, download_type)
    stream_url = next(
        (f["url"] for f in info.get("formats", [])
         if f["format_id"] == fmt),
        None
    )
    if not stream_url:
        raise Exception("Formato no encontrado en Invidious")
    # 3) Descargar stream
    title = info.get("title", video_id)
    ext = ".mp4" if download_type == "video" else ".mp3"
    safe_name = title.replace("/", "_").replace(" ", "_") + ext
    path = os.path.join(DOWNLOAD_DIR, safe_name)
    with requests.get(
        stream_url,
        stream=True,
        proxies=get_proxy_dict(),
        timeout=60
    ) as r:
        r.raise_for_status()
        with open(path, "wb") as f:
            for chunk in r.iter_content(chunk_size=1024*1024):
                if chunk:
                    f.write(chunk)
    meta = {
        "title": title,
        "author": info.get("uploader"),
        "length": info.get("duration"),
        "type": download_type
    }
    return meta, path

def download_video(url: str, download_type: str = "video") -> dict:
    """
    Intento principal con yt-dlp (+ proxy), y fallback a Invidious si
    detecta bloqueo de YouTube.
    """
    if not is_supported_url(url):
        return {"status":"error","message":"URL no soportada"}
    # extraer video_id de YouTube
    video_id = None
    if "youtube" in url:
        parts = url.split("v=")
        video_id = parts[1] if len(parts) > 1 else url.rsplit("/", 1)[-1]
    # opts básicos
    base_opts = {
        "format": "bestvideo+bestaudio/best",
        "noplaylist": True,
        "outtmpl": os.path.join(DOWNLOAD_DIR, "%(title)s.%(ext)s"),
        "windowsfilenames": True
    }
    proxy = get_proxy_dict()
    if proxy:
        base_opts["proxy"] = proxy.get("http")
    # 1) Prueba yt-dlp
    try:
        with YoutubeDL(base_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            path = ydl.prepare_filename(info)
    except DownloadError as e:
        msg = str(e)
        logging.warning("yt-dlp fallo: %s", msg)
        # 2) Fallback a Invidious
        if video_id and (
            "Sign in to confirm" in msg or "Requested format" in msg
        ):
            try:
                meta, path = invidious_download(video_id, download_type)
            except Exception as ie:
                logging.error("Invidious fallo: %s", ie, exc_info=True)
                return {"status":"error","message":f"Error Invidious: {ie}"}
        else:
            return {"status":"error","message":msg}
        # Cuando Invidious devuelve meta y path:
        return {"status":"success","metadata":meta,"path":path}

    # 3) Éxito con yt-dlp: construye metadata
    meta = {
        "title": info.get("title"),
        "author": info.get("uploader"),
        "length": info.get("duration"),
        "type": download_type
    }
    return {"status":"success","metadata":meta,"path":path}

def upload_to_drive(path: str) -> str:
    """Sube un fichero a Google Drive y devuelve el webViewLink."""
    if not (GDRIVE_CRED_PATH and GDRIVE_FOLDER_ID):
        return None
    file_metadata = {
        "name": os.path.basename(path),
        "parents": [GDRIVE_FOLDER_ID]
    }
    media = MediaFileUpload(path, resumable=False)
    file = drive_service.files().create(
        body=file_metadata,
        media_body=media,
        fields="webViewLink"
    ).execute()
    return file.get("webViewLink")

# --- API Flask ---
app = Flask(__name__)

@app.route("/download", methods=["POST"])
def download_endpoint():
    data = request.get_json() or {}
    res = download_video(data.get("url"), data.get("type","video"))
    if res["status"] != "success":
        return jsonify(res), 400
    return jsonify({
        "status":"success",
        "metadata":res["metadata"],
        "path":res["path"]
    })

def run_flask():
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    app.run(host="0.0.0.0", port=API_PORT, use_reloader=False)

# --- Bot de Telegram ---
async def show_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [
        [InlineKeyboardButton("🔽 Descargar", callback_data="download")],
        [InlineKeyboardButton("❓ Ayuda",     callback_data="help")]
    ]
    await update.message.reply_text("Selecciona una opción:", reply_markup=InlineKeyboardMarkup(kb))

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    text = (
        "1) Pulsar 'Descargar' → envía URL\n"
        "2) Elige formato: Vídeo o Audio\n\n"
        "Se usan proxies rotativos y fallback a Invidious para YouTube."
    )
    await update.callback_query.message.reply_text(text)

async def download_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await update.callback_query.message.reply_text(
        "Envía la URL que quieres descargar:",
        reply_markup=ForceReply(selective=True)
    )

def is_reply_to_bot(update: Update) -> bool:
    """Check if the message is a reply to our bot's message."""
    return update.message and update.message.reply_to_message and update.message.reply_to_message.from_user.is_bot

async def handle_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text.strip()
    context.user_data["url"] = url
    kb = [
        [InlineKeyboardButton("🎬 Vídeo", callback_data="fmt_video")],
        [InlineKeyboardButton("🎵 Audio", callback_data="fmt_audio")]
    ]
    await update.message.reply_text("¿Qué formato deseas?", reply_markup=InlineKeyboardMarkup(kb))

async def handle_format(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    dtype = "audio" if update.callback_query.data == "fmt_audio" else "video"
    url   = context.user_data.get("url")
    res   = download_video(url, dtype)
    if res["status"] != "success":
        await update.callback_query.message.reply_text(f"❌ {res['message']}")
        return
    path = res["path"]
    meta = res["metadata"]
    # Envía el archivo
    await update.callback_query.message.reply_document(
        open(path, "rb"),
        caption=f"✅ {meta['title']} by {meta['author']} ({meta['length']}s)"
    )
    # Opcional: sube a Drive
    link = upload_to_drive(path)
    if link:
        await update.callback_query.message.reply_text(f"📁 Google Drive: {link}")

if __name__ == "__main__":
    # Lanza Flask en hilo
    threading.Thread(target=run_flask, daemon=True).start()
    # Lanza el bot
    app_bot = Application.builder().token(TELEGRAM_TOKEN).build()
    app_bot.add_handler(CommandHandler("start", show_menu))
    app_bot.add_handler(CallbackQueryHandler(help_cmd,    pattern="^help$"))
    app_bot.add_handler(CallbackQueryHandler(download_start, pattern="^download$"))
    app_bot.add_handler(MessageHandler(filters.TEXT & filters.create(is_reply_to_bot), handle_url))
    app_bot.add_handler(CallbackQueryHandler(handle_format, pattern="^fmt_"))
    app_bot.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, show_menu))
    app_bot.run_polling()
