import os
import logging
import threading
import random
import requests
from flask import Flask, request, jsonify
from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError
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

# --- Configuración de logging ---
logging.basicConfig(level=logging.INFO)

# --- Variables de entorno ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
if not TELEGRAM_TOKEN:
    logging.error("🚨 Debes exportar TELEGRAM_TOKEN con tu token de BotFather.")
    exit(1)

# Proxies rotativos (ej: "http://ip1:port,http://ip2:port")
PROXIES = [p.strip() for p in os.getenv("PROXIES", "").split(",") if p.strip()]
INVIDIOUS_API_URL = os.getenv("INVIDIOUS_API_URL")  # ej: https://yewtu.be

# Google Drive
GDRIVE_CRED_PATH = os.getenv("GOOGLE_CREDS_PATH")
GDRIVE_FOLDER_ID = os.getenv("GDRIVE_FOLDER_ID")
if GDRIVE_CRED_PATH and GDRIVE_FOLDER_ID:
    creds = service_account.Credentials.from_service_account_file(
        GDRIVE_CRED_PATH,
        scopes=["https://www.googleapis.com/auth/drive.file"]
    )
    drive_service = build('drive', 'v3', credentials=creds)
else:
    logging.warning("Google Drive no configurado; se omitirá subida.")

# Variables de descarga y Flask
DOWNLOAD_DIR = "downloads"
API_PORT = int(os.getenv("PORT", 5001))
TELEGRAM_FILE_LIMIT = 50 * 1024 * 1024  # 50 MB
SUPPORTED_SITES = [
    'youtube.com/watch?v=', 'youtu.be/', 'instagram.com/reel/', 'instagram.com/p/',
    'tiktok.com/', 'twitter.com/', 'x.com/', 'facebook.com/', 'fb.watch/',
    'vimeo.com/', 'dailymotion.com/', 'reddit.com/'
]
ELEGIR_TIPO = range(1)

# --- Helpers ---

def get_proxy_dict():
    if PROXIES:
        proxy = random.choice(PROXIES)
        return {"http": proxy, "https": proxy}
    return None


def is_supported_url(url: str) -> bool:
    return any(site in url for site in SUPPORTED_SITES)


def choose_format(info: dict, download_type: str) -> str:
    formats = info.get("formats", [])
    # video progresivo
    if download_type == "video":
        prog = [f for f in formats if f.get("vcodec") != "none" and f.get("acodec") != "none"]
        if prog:
            return max(prog, key=lambda f: (f.get("tbr") or 0))["format_id"]
    # solo audio
    audio = [f for f in formats if f.get("acodec") != "none" and f.get("vcodec") in (None, "none")]
    if audio:
        return max(audio, key=lambda f: (f.get("abr") or 0))["format_id"]
    return "best"


def invidious_download(video_id: str, download_type: str):
    if not INVIDIOUS_API_URL:
        raise Exception("Invidious no configurado")
    # 1) Obtener info JSON de invidious
    url = f"{INVIDIOUS_API_URL}/api/v1/videos/{video_id}"
    resp = requests.get(url, proxies=get_proxy_dict(), timeout=15)
    resp.raise_for_status()
    info = resp.json()
    fmt = choose_format(info, download_type)
    # 2) URL directa
    stream_url = next((f["url"] for f in info.get("formats", []) if f["format_id"] == fmt), None)
    if not stream_url:
        raise Exception("Formato no encontrado en Invidious")
    # 3) Descarga por streaming
    title = info.get("title", video_id)
    ext = '.mp4' if download_type=='video' else '.mp3'
    safe_name = title.replace('/', '_').replace(' ', '_') + ext
    path = os.path.join(DOWNLOAD_DIR, safe_name)
    with requests.get(stream_url, stream=True, proxies=get_proxy_dict(), timeout=60) as r:
        r.raise_for_status()
        with open(path, 'wb') as f:
            for chunk in r.iter_content(chunk_size=1024*1024):
                if chunk:
                    f.write(chunk)
    meta = {
        'title': title,
        'author': info.get('uploader'),
        'length': info.get('duration'),
        'type': download_type
    }
    return meta, path


def download_video(url: str, download_type: str = 'video') -> dict:
    """Intenta yt-dlp, con proxies, y fallback a Invidious si es necesario"""
    if not is_supported_url(url):
        return {'status':'error','message':'URL no soportada'}
    # extraer videoId de YouTube
    video_id = None
    if 'youtube' in url:
        # formato estándar youtu.be/
        parts = url.split('v=')
        video_id = parts[1] if len(parts)>1 else url.rsplit('/',1)[-1]
    base_opts = {
        'format': 'bestvideo+bestaudio/best',
        'noplaylist': True,
        'outtmpl': os.path.join(DOWNLOAD_DIR, '%(title)s.%(ext)s'),
        'windowsfilenames': True,
    }
    # agregar proxy a yt-dlp
    proxy_dict = get_proxy_dict()
    if proxy_dict:
        base_opts['proxy'] = proxy_dict.get('http')
    # intenta con yt-dlp
    try:
        with YoutubeDL(base_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            path = ydl.prepare_filename(info)
    except DownloadError as e:
        msg = str(e)
        logging.warning("yt-dlp fallo: %s", msg)
        # fallback YouTube bloqueado?
        if video_id and ("Sign in to confirm" in msg or "Requested format" in msg):
            try:
                meta, path = invidious_download(video_id, download_type)
            except Exception as ie:
                logging.error("Invidious fallo: %s", ie, exc_info=True)
                return {'status':'error','message':f"Error Invidious: {ie}"}
        else:
            return {'status':'error','message':msg}
    # metadata
    meta = {
        'title': info.get('title'),
        'author': info.get('uploader'),
        'length': info.get('duration'),
        'type': download_type
    }
    return {'status':'success','metadata':meta,'path':path}


def upload_to_drive(path: str) -> str:
    if not (GDRIVE_CRED_PATH and GDRIVE_FOLDER_ID):
        return None
    file_metadata = {'name': os.path.basename(path), 'parents':[GDRIVE_FOLDER_ID]}
    media = MediaFileUpload(path, resumable=False)
    file = drive_service.files().create(body=file_metadata, media_body=media, fields='webViewLink').execute()
    return file.get('webViewLink')

# --- Servicio Flask ---
app = Flask(__name__)
@app.route('/download', methods=['POST'])
def download_endpoint():
    data = request.get_json() or {}
    res = download_video(data.get('url'), data.get('type','video'))
    if res['status']!='success':
        return jsonify(res), 400
    return jsonify({'status':'success','metadata':res['metadata'],'path':res['path']})

def run_flask():
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    app.run(host='0.0.0.0', port=API_PORT, use_reloader=False)

# --- Bot de Telegram ---
async def show_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb=[[InlineKeyboardButton("🔽 Descargar",callback_data='download')], [InlineKeyboardButton("❓ Ayuda",callback_data='help')]]
    await update.message.reply_text("Selecciona:", reply_markup=InlineKeyboardMarkup(kb))

async def help_cmd(update,ctx):
    await update.callback_query.answer()
    text = "1) Descargar → envía URL\n2) Elige formato\nLos vídeos bloqueados usan Invidious y proxies rotativos"
    await update.callback_query.message.reply_text(text)

async def download_start(update,ctx):
    await update.callback_query.answer()
    await update.callback_query.message.reply_text("Envía la URL:", reply_markup=ForceReply(selective=True))

async def handle_url(update,ctx):
    url=update.message.text.strip()
    ctx.user_data['url']=url
    kb=[[InlineKeyboardButton("🎬 Vídeo",callback_data='fmt_video')],[InlineKeyboardButton("🎵 Audio",callback_data='fmt_audio')]]
    await update.message.reply_text("Elige formato:",reply_markup=InlineKeyboardMarkup(kb))

async def handle_format(update,ctx):
    await update.callback_query.answer()
    dtype='audio' if update.callback_query.data=='fmt_audio' else 'video'
    url=ctx.user_data.get('url')
    res=download_video(url,dtype)
    if res['status']!='success':
        await update.callback_query.message.reply_text(f"❌ {res['message']}")
        return
    path=res['path']; meta=res['metadata']
    await update.callback_query.message.reply_document(open(path,'rb'),caption=f"✅ {meta['title']} by {meta['author']} ({meta['length']}s)")
    drv=upload_to_drive(path)
    if drv: await update.callback_query.message.reply_text(f"📁 Drive: {drv}")

if __name__=='__main__':
    threading.Thread(target=run_flask,daemon=True).start()
    app_bot=Application.builder().token(TELEGRAM_TOKEN).build()
    app_bot.add_handler(CommandHandler('start',show_menu))
    app_bot.add_handler(CallbackQueryHandler(help_cmd,pattern='^help$'))
    app_bot.add_handler(CallbackQueryHandler(download_start,pattern='^download$'))
    app_bot.add_handler(MessageHandler(filters.TEXT & filters.FORCE_REPLY,handle_url))
    app_bot.add_handler(CallbackQueryHandler(handle_format,pattern='^fmt_'))
    app_bot.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,show_menu))
    app_bot.run_polling()
