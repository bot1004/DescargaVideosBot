import os
import logging
import threading
import requests
from flask import Flask, request, jsonify
from yt_dlp import YoutubeDL
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    ConversationHandler, ContextTypes, filters
)

# --- Configuración ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
if not TELEGRAM_TOKEN:
    logging.error("🚨 Debes exportar TELEGRAM_TOKEN con tu token de BotFather.")
    exit(1)

N8N_UPLOAD_URL = os.getenv("N8N_UPLOAD_URL", "http://localhost:5678/upload")
DOWNLOAD_DIR = "downloads"
API_PORT = int(os.getenv("PORT", 5001))
TELEGRAM_FILE_LIMIT = 50 * 1024 * 1024  # 50 MB
SUPPORTED_SITES = [
    'youtube.com/watch?v=', 'youtu.be/', 'instagram.com/reel/', 'instagram.com/p/',
    'tiktok.com/', 'twitter.com/', 'x.com/', 'facebook.com/', 'fb.watch/',
    'vimeo.com/', 'dailymotion.com/', 'reddit.com/'
]
ELEGIR_TIPO = range(1)

logging.basicConfig(level=logging.INFO)

# --- Funciones de descarga ---
def is_supported_url(url: str) -> bool:
    return any(site in url for site in SUPPORTED_SITES)


def choose_format(info: dict, download_type: str) -> str:
    """Elige el mejor formato disponible evitando None en tbr/abr."""
    formats = info.get("formats", [])

    if download_type == "video":
        # Formatos progresivos (tienen audio y vídeo en el mismo file)
        prog = [f for f in formats if f.get("vcodec") != "none" and f.get("acodec") != "none"]
        if prog:
            best = max(prog, key=lambda f: (f.get("tbr") or 0))
            return best["format_id"]

    # Solo audio o fallback
    audio = [f for f in formats if f.get("acodec") != "none" and (f.get("vcodec") in (None, "none"))]
    if audio:
        best_a = max(audio, key=lambda f: (f.get("abr") or 0))
        return best_a["format_id"]

    # Último recurso
    return "best"


def download_video(url: str, download_type: str = 'video') -> dict:
    if not is_supported_url(url):
        return {'status': 'error', 'message': 'URL no válida o plataforma no soportada'}

    # Opciones iniciales
    base_opts = {
        'noplaylist': True,
        'outtmpl': os.path.join(DOWNLOAD_DIR, '%(title)s.%(ext)s'),
        'windowsfilenames': True,
    }

    try:
        # 1) Obtener info de los formatos (sin descargar)
        ydl_probe = YoutubeDL({**base_opts, 'format': 'best'})
        info = ydl_probe.extract_info(url, download=False)

        # 2) Elegir formato
        chosen_fmt = choose_format(info, download_type)

        # 3) Descargar con el formato elegido
        opts = {**base_opts, 'format': chosen_fmt}
        if download_type == 'video':
            opts['merge_output_format'] = 'mp4'
        else:
            # convierte a mp3
            opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }]

        with YoutubeDL(opts) as ydl:
            result = ydl.extract_info(url, download=True)
            path = ydl.prepare_filename(result)
            if download_type == 'audio':
                base, _ = os.path.splitext(path)
                path = base + '.mp3'

        filename = os.path.basename(path)
        return {
            'status': 'success',
            'filename': filename,
            'metadata': {
                'title': result.get('title'),
                'author': result.get('uploader'),
                'length': result.get('duration'),
                'type': download_type
            }
        }

    except Exception as e:
        logging.error("Error al descargar:", exc_info=True)
        return {'status': 'error', 'message': f"Error al descargar: {e}"}

# --- Servicio Flask ---
app = Flask(__name__)

@app.route('/download', methods=['POST'])
def download_endpoint():
    try:
        payload = request.get_json() or {}
        url = payload.get('url')
        dtype = payload.get('type', 'video')
        result = download_video(url, dtype)
        return jsonify(result)
    except Exception as e:
        logging.error("Error en la API:", exc_info=True)
        return jsonify({'status': 'error', 'message': str(e)}), 500


def run_flask():
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    app.run(host='0.0.0.0', port=API_PORT, use_reloader=False)

# --- Handlers del bot ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Envía el enlace del vídeo que quieres descargar (YouTube, Instagram, TikTok, etc.)."
    )

async def recibir_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text.strip()
    context.user_data['url'] = url
    keyboard = [["🎬 Vídeo completo", "🎵 Solo audio"]]
    await update.message.reply_text(
        "¿Qué deseas descargar?",
        reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
    )
    return ELEGIR_TIPO

async def elegir_tipo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    choice = update.message.text.strip().lower()
    url = context.user_data['url']
    dtype = 'audio' if 'audio' in choice else 'video'

    result = download_video(url, dtype)
    if result['status'] != 'success':
        await update.message.reply_text(f"❌ {result.get('message')}")
        return ConversationHandler.END

    fn = result['filename']
    path = os.path.join(DOWNLOAD_DIR, fn)
    if not os.path.exists(path):
        await update.message.reply_text("❌ Archivo no encontrado tras descargar.")
        return ConversationHandler.END

    size = os.path.getsize(path)
    logging.info(f"Archivo {fn} pesa {size} bytes.")

    if size <= TELEGRAM_FILE_LIMIT:
        await update.message.reply_document(
            document=open(path, 'rb'),
            caption=(f"✅ Descargado:\n📹 {result['metadata']['title']}\n"
                     f"👤 {result['metadata']['author']}\n"
                     f"⏱ {result['metadata']['length']}s")
        )
    else:
        try:
            with open(path, 'rb') as f:
                r = requests.post(N8N_UPLOAD_URL, files={'file': (fn, f)})
            link = r.json().get('download_url') if r.ok else None
            if link:
                await update.message.reply_text(f"✅ Archivo grande. Descarga en: {link}")
            else:
                await update.message.reply_text("❌ Falló subida a n8n.")
        except Exception as e:
            await update.message.reply_text(f"❌ Error subiendo a n8n: {e}")

    return ConversationHandler.END

async def cancelar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Operación cancelada.")
    return ConversationHandler.END

# --- Arranque de servicios ---
if __name__ == '__main__':
    threading.Thread(target=run_flask, daemon=True).start()
    app_bot = Application.builder().token(TELEGRAM_TOKEN).build()
    conv = ConversationHandler(
        entry_points=[MessageHandler(filters.TEXT & ~filters.COMMAND, recibir_url)],
        states={ELEGIR_TIPO: [MessageHandler(filters.TEXT & ~filters.COMMAND, elegir_tipo)]},
        fallbacks=[CommandHandler('cancelar', cancelar)]
    )
    app_bot.add_handler(CommandHandler("start", start))
    app_bot.add_handler(conv)
    app_bot.run_polling()
