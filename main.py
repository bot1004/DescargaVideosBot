import os
import logging
import threading
import random
import requests
import re
from datetime import datetime
from flask import Flask, request, jsonify
from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ForceReply
from telegram.constants import ParseMode
from telegram.helpers import escape_markdown
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters, ConversationHandler
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from dotenv import load_dotenv

# Cargar variables de entorno desde .env
load_dotenv()

# -------- CONFIGURACIÓN GLOBAL --------
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)
logger.info("🚀 Iniciando bot...")

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
if not TELEGRAM_TOKEN:
    logger.error("🚨 Falta TELEGRAM_TOKEN")
    exit(1)

PROXIES = [p.strip() for p in os.getenv("PROXIES", "").split(",") if p.strip()]
INVIDIOUS_API_URL = os.getenv("INVIDIOUS_API_URL")

# Verificación detallada de Google Drive
logger.info("🔍 Verificando configuración de Google Drive...")
GDRIVE_CRED_PATH = os.getenv("GOOGLE_CREDS_PATH")
GDRIVE_FOLDER_ID = os.getenv("GDRIVE_FOLDER_ID")

if not GDRIVE_CRED_PATH:
    logger.error("❌ Variable de entorno GOOGLE_CREDS_PATH no está definida")
    logger.info("ℹ️ Para configurar Google Drive, define la variable GOOGLE_CREDS_PATH con la ruta al archivo de credenciales")
    drive_service = None
elif not GDRIVE_FOLDER_ID:
    logger.error("❌ Variable de entorno GDRIVE_FOLDER_ID no está definida")
    logger.info("ℹ️ Para configurar Google Drive, define la variable GDRIVE_FOLDER_ID con el ID de la carpeta de destino")
    drive_service = None
else:
    logger.info(f"📁 Configuración de Google Drive encontrada:")
    logger.info(f"- Ruta de credenciales: {GDRIVE_CRED_PATH}")
    logger.info(f"- ID de carpeta: {GDRIVE_FOLDER_ID}")
    
    if not os.path.exists(GDRIVE_CRED_PATH):
        logger.error(f"❌ El archivo de credenciales no existe en: {GDRIVE_CRED_PATH}")
        logger.info("ℹ️ Asegúrate de que el archivo de credenciales existe y tiene los permisos correctos")
        drive_service = None
    else:
        try:
            logger.info("🔑 Cargando credenciales de Google Drive...")
            creds = service_account.Credentials.from_service_account_file(
                GDRIVE_CRED_PATH,
                scopes=["https://www.googleapis.com/auth/drive.file"]
            )
            logger.info("✅ Credenciales cargadas correctamente")
            
            logger.info("🔄 Inicializando servicio de Google Drive...")
            drive_service = build("drive", "v3", credentials=creds)
            logger.info("✅ Servicio de Google Drive inicializado")
            
            # Verificar acceso a la carpeta
            try:
                logger.info(f"🔍 Verificando acceso a la carpeta {GDRIVE_FOLDER_ID}...")
                folder = drive_service.files().get(
                    fileId=GDRIVE_FOLDER_ID,
                    fields="id,name,capabilities"
                ).execute()
                
                caps = folder.get('capabilities', {})
                logger.info(f"✅ Carpeta accesible: {folder.get('name')}")
                logger.info(f"📋 Capacidades de la carpeta:")
                logger.info(f"- Puede añadir archivos: {caps.get('canAddChildren', False)}")
                logger.info(f"- Puede editar: {caps.get('canEdit', False)}")
                logger.info(f"- Puede compartir: {caps.get('canShare', False)}")
                
                if not caps.get('canAddChildren'):
                    logger.error("❌ La cuenta de servicio no tiene permisos para añadir archivos a esta carpeta")
                    logger.info("ℹ️ Asegúrate de que la cuenta de servicio tiene permisos de editor en la carpeta")
                    drive_service = None
                
            except Exception as e:
                logger.error(f"❌ Error al acceder a la carpeta de Drive: {str(e)}")
                logger.info("ℹ️ Verifica que el ID de la carpeta es correcto y que la cuenta de servicio tiene acceso")
                drive_service = None
                
        except Exception as e:
            logger.error(f"❌ Error al inicializar Google Drive: {str(e)}")
            logger.info("ℹ️ Verifica que el archivo de credenciales es válido y tiene el formato correcto")
            drive_service = None

if drive_service:
    logger.info("✅ Google Drive configurado y listo para usar")
else:
    logger.warning("⚠️ Google Drive no está disponible - las subidas a Drive estarán deshabilitadas")

DOWNLOAD_DIR = "downloads"
API_PORT = int(os.getenv("PORT", 5001))
TELEGRAM_FILE_LIMIT = 50 * 1024 * 1024  # 50 MB

# Lista de sitios soportados con ejemplos de URLs
SUPPORTED_SITES = {
    "YouTube": ["youtube.com/watch?v=", "youtu.be/"],
    "Instagram": ["instagram.com/reel/", "instagram.com/p/"],
    "TikTok": ["tiktok.com/"],
    "Twitter/X": ["twitter.com/", "x.com/"],
    "Facebook": ["facebook.com/", "fb.watch/"],
    "Vimeo": ["vimeo.com/"],
    "Dailymotion": ["dailymotion.com/"],
    "Reddit": ["reddit.com/r/"]
}

# Estados para el ConversationHandler
WAITING_URL, CHOOSING_FORMAT, DOWNLOADING = range(3)

# -------- UTILIDADES --------
def get_proxy_dict():
    if PROXIES:
        p = random.choice(PROXIES)
        return {"http": p, "https": p}
    return None

def choose_format(info: dict, kind: str) -> str:
    fmts = info.get("formats", [])
    if kind == "video":
        prog = [f for f in fmts if f.get("vcodec") != "none" and f.get("acodec") != "none"]
        if prog:
            return max(prog, key=lambda f: (f.get("tbr") or 0))["format_id"]
    audio = [f for f in fmts if f.get("acodec") != "none" and f.get("vcodec") in (None, "none")]
    if audio:
        return max(audio, key=lambda f: (f.get("abr") or 0))["format_id"]
    return "best"

def invidious_download(video_id: str, kind: str):
    if not INVIDIOUS_API_URL:
        raise Exception("Invidious no configurado")
    resp = requests.get(f"{INVIDIOUS_API_URL}/api/v1/videos/{video_id}", proxies=get_proxy_dict(), timeout=15)
    resp.raise_for_status()
    info = resp.json()
    fmt = choose_format(info, kind)
    stream_url = next((f["url"] for f in info.get("formats", []) if f["format_id"] == fmt), None)
    if not stream_url:
        raise Exception("Formato no encontrado en Invidious")
    title = info.get("title", video_id)
    ext = ".mp4" if kind == "video" else ".mp3"
    fname = title.replace("/", "_").replace(" ", "_") + ext
    path = os.path.join(DOWNLOAD_DIR, fname)
    with requests.get(stream_url, stream=True, proxies=get_proxy_dict(), timeout=60) as r:
        r.raise_for_status()
        with open(path, "wb") as f:
            for chunk in r.iter_content(chunk_size=1024*1024):
                if chunk:
                    f.write(chunk)
    meta = {"title": title, "author": info.get("uploader"), "length": info.get("duration"), "type": kind}
    return meta, path

def format_duration(seconds):
    """Convierte segundos a formato HH:MM:SS"""
    if not seconds:
        return "Desconocida"
    hours, remainder = divmod(int(seconds), 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    else:
        return f"{minutes:02d}:{seconds:02d}"

def format_file_size(size_bytes):
    """Convierte bytes a formato legible (KB, MB, GB)"""
    if size_bytes < 1024:
        return f"{size_bytes} bytes"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes/1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes/(1024*1024):.1f} MB"
    else:
        return f"{size_bytes/(1024*1024*1024):.2f} GB"

def is_supported_url(url):
    """Verifica si la URL es de un sitio soportado"""
    for site_urls in SUPPORTED_SITES.values():
        if any(site_url in url.lower() for site_url in site_urls):
            return True
    return False

def get_site_name(url):
    """Obtiene el nombre del sitio de la URL"""
    for site_name, site_urls in SUPPORTED_SITES.items():
        if any(site_url in url.lower() for site_url in site_urls):
            return site_name
    return "Desconocido"

def extract_video_id(url):
    """Extrae el ID del video de diferentes plataformas"""
    # YouTube
    if "youtube.com" in url or "youtu.be" in url:
        if "youtube.com/watch" in url:
            return re.search(r"v=([^&]+)", url).group(1)
        elif "youtu.be/" in url:
            return url.split("youtu.be/")[1].split("?")[0]
    # Otros formatos se pueden agregar según sea necesario
    return None

def download_video(url: str, kind: str = "video") -> dict:
    """Descarga un video o audio de una URL"""
    if not is_supported_url(url):
        return {"status": "error", "message": "⚠️ URL no soportada. Usa /plataformas para ver los sitios disponibles."}
    
    video_id = extract_video_id(url)
    opts = {
        "format": "bestvideo+bestaudio/best" if kind == "video" else "bestaudio/best",
        "noplaylist": True,
        "outtmpl": os.path.join(DOWNLOAD_DIR, "%(title)s.%(ext)s"),
        "windowsfilenames": True,
        "quiet": True,
        "no_warnings": True
    }
    
    if kind == "audio":
        opts["postprocessors"] = [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }]
    
    if (p := get_proxy_dict()):
        opts["proxy"] = p["http"]
    
    try:
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            path = ydl.prepare_filename(info)
            if kind == "audio" and not path.endswith(".mp3"):
                path = os.path.splitext(path)[0] + ".mp3"
            
            meta = {
                "title": info.get("title", "Desconocido"),
                "author": info.get("uploader", "Desconocido"),
                "length": info.get("duration", 0),
                "thumbnail": info.get("thumbnail"),
                "type": kind,
                "site": get_site_name(url)
            }
    except DownloadError as e:
        msg = str(e)
        logging.warning("yt-dlp fallo: %s", msg)
        if video_id and "youtube" in url.lower() and any(x in msg for x in ["Sign in to confirm", "Requested format"]):
            try:
                meta, path = invidious_download(video_id, kind)
            except Exception as e2:
                return {"status": "error", "message": f"❌ Error: {str(e2)}"}
        else:
            return {"status": "error", "message": f"❌ Error: {msg}"}
    
    return {"status": "success", "metadata": meta, "path": path}

def upload_to_drive(path: str) -> str | None:
    """Sube un archivo a Google Drive y devuelve el enlace"""
    if not drive_service:
        logging.error("❌ Google Drive no está configurado (drive_service es None)")
        return None
    
    if not os.path.exists(path):
        logging.error(f"❌ El archivo no existe: {path}")
        return None
    
    try:
        file_size = os.path.getsize(path)
        logging.info(f"📤 Iniciando subida a Drive:")
        logging.info(f"- Archivo: {path}")
        logging.info(f"- Tamaño: {format_file_size(file_size)}")
        logging.info(f"- Carpeta destino: {GDRIVE_FOLDER_ID}")
        
        # Verificar permisos de la carpeta antes de subir
        try:
            folder = drive_service.files().get(
                fileId=GDRIVE_FOLDER_ID,
                fields="id,name,capabilities"
            ).execute()
            caps = folder.get('capabilities', {})
            if not caps.get('canAddChildren'):
                logging.error("❌ No hay permisos para subir archivos a esta carpeta")
                return None
            logging.info(f"✅ Permisos de carpeta verificados: {caps}")
        except Exception as e:
            logging.error(f"❌ Error al verificar permisos de carpeta: {str(e)}")
            return None
        
        file_metadata = {
            "name": os.path.basename(path),
            "parents": [GDRIVE_FOLDER_ID],
            "description": f"Subido por DownloaderBot el {datetime.now().strftime('%d/%m/%Y %H:%M')}"
        }
        
        logging.info(f"📝 Metadata del archivo: {file_metadata}")
        
        # Configurar la subida con chunks más pequeños para mejor manejo de errores
        media = MediaFileUpload(
            path,
            resumable=True,
            chunksize=512*1024,  # 512KB chunks
            mimetype='video/mp4' if path.endswith('.mp4') else 'audio/mpeg'
        )
        
        logging.info("🚀 Iniciando subida a Drive...")
        request = drive_service.files().create(
            body=file_metadata,
            media_body=media,
            fields="id,webViewLink,size"
        )
        
        # Monitorear el progreso de la subida
        response = None
        while response is None:
            try:
                status, response = request.next_chunk()
                if status:
                    logging.info(f"📊 Progreso: {int(status.progress() * 100)}%")
            except Exception as e:
                logging.error(f"❌ Error durante la subida: {str(e)}")
                return None
        
        logging.info(f"✅ Archivo subido exitosamente:")
        logging.info(f"- ID: {response.get('id')}")
        logging.info(f"- Tamaño: {format_file_size(int(response.get('size', 0)))}")
        
        # Configurar permisos públicos
        logging.info("🔒 Configurando permisos públicos...")
        try:
            drive_service.permissions().create(
                fileId=response.get("id"),
                body={"type": "anyone", "role": "reader"},
                fields="id"
            ).execute()
            logging.info("✅ Permisos públicos configurados")
        except Exception as e:
            logging.error(f"❌ Error al configurar permisos: {str(e)}")
            # Continuamos aunque falle la configuración de permisos
        
        web_link = response.get("webViewLink")
        logging.info(f"🔗 Enlace generado: {web_link}")
        return web_link
        
    except Exception as e:
        logging.error(f"❌ Error al subir a Drive: {str(e)}", exc_info=True)
        return None

# -------- SERVICIO FLASK --------
app = Flask(__name__)

@app.route("/download", methods=["POST"])
def api_download():
    data = request.json or {}
    return jsonify(download_video(data.get("url"), data.get("type", "video")))

def run_flask():
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    app.run(host="0.0.0.0", port=API_PORT, use_reloader=False)

# -------- BOT DE TELEGRAM --------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /start - Muestra el menú principal"""
    await show_welcome_message(update, context)
    return ConversationHandler.END

async def show_welcome_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Muestra el mensaje de bienvenida con el menú principal"""
    # Verificar estado del bot
    bot_status = "🟢 Bot Activo" if context.bot else "🔴 Bot Inactivo"
    
    kb = [
        [InlineKeyboardButton("🚀 Empezar a descargar", callback_data="start_download")],
        [InlineKeyboardButton("📱 Plataformas soportadas", callback_data="platforms")],
        [InlineKeyboardButton("❓ Ayuda & Comandos", callback_data="help")],
        [InlineKeyboardButton(bot_status, callback_data="bot_status")]
    ]
    
    message = (
        "🎬 *¡Bienvenido al Descargador de Videos!* 🎬\n\n"
        f"*Estado:* {bot_status}\n\n"
        "Puedo descargar videos y audio de varias plataformas populares.\n"
        "¿Qué quieres hacer hoy?"
    )
    
    # Si el mensaje viene de un callback, editamos el mensaje existente
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.message.edit_text(
            message, reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.MARKDOWN
        )
    # Si no, enviamos un nuevo mensaje
    else:
        await update.message.reply_markdown(
            message, reply_markup=InlineKeyboardMarkup(kb)
        )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Muestra la ayuda directamente"""
    await show_help(update, context)
    return ConversationHandler.END

async def show_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Muestra información de ayuda"""
    if update.callback_query:
        await update.callback_query.answer()
        message = update.callback_query.message
    else:
        message = update.message
    
    text = (
        "📖 *Guía de uso del Descargador* 📖\n\n"
        "*Comandos disponibles:*\n"
        "• /start - Inicia el bot y muestra el menú principal\n"
        "• /descargar - Comienza el proceso de descarga\n"
        "• /plataformas - Muestra las plataformas soportadas\n"
        "• /ayuda - Muestra este mensaje de ayuda\n"
        "• /cancelar - Cancela la operación actual\n\n"
        
        "*¿Cómo descargar un video?*\n"
        "1️⃣ Selecciona 'Empezar a descargar' o usa /descargar\n"
        "2️⃣ Envía la URL del video o audio que quieres descargar\n"
        "3️⃣ Selecciona si quieres descargar video o solo audio\n"
        "4️⃣ Espera mientras descargo y proceso tu archivo\n"
        "5️⃣ ¡Recibe tu descarga directamente en Telegram o por Google Drive!\n\n"
        
        "*Consejos:*\n"
        "• Asegúrate de enviar URLs completas y válidas\n"
        "• Los archivos mayores de 50MB se comparten por Google Drive\n"
        "• Si tienes problemas, intenta con otro formato\n\n"
        
        "🔄 *¿Volver al menú principal?*"
    )
    
    kb = [[InlineKeyboardButton("🏠 Volver al Menú", callback_data="back_to_menu")]]
    
    if hasattr(message, 'reply_markdown'):
        await message.reply_markdown(text, reply_markup=InlineKeyboardMarkup(kb))
    else:
        await message.edit_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.MARKDOWN)

async def platforms_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Muestra las plataformas directamente"""
    await show_platforms(update, context)
    return ConversationHandler.END

async def show_platforms(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Muestra las plataformas soportadas de forma visual"""
    if update.callback_query:
        await update.callback_query.answer()
        message = update.callback_query.message
    else:
        message = update.message
    
    platforms_text = "*📱 Plataformas soportadas:*\n\n"
    for platform, urls in SUPPORTED_SITES.items():
        platforms_text += f"• *{platform}* {get_platform_emoji(platform)}\n"
        platforms_text += f"  `{urls[0]}`\n\n"
    
    platforms_text += (
        "\n*¿Cómo usar?*\n"
        "1. Copia la URL del video\n"
        "2. Pégala en el chat\n"
        "3. Selecciona el formato\n"
        "4. ¡Listo! Recibe tu descarga\n\n"
        "*¿Qué quieres hacer ahora?*"
    )
    
    kb = [
        [InlineKeyboardButton("🚀 Descargar ahora", callback_data="start_download")],
        [InlineKeyboardButton("🏠 Volver al Menú", callback_data="back_to_menu")]
    ]
    
    if hasattr(message, 'reply_markdown'):
        await message.reply_markdown(platforms_text, reply_markup=InlineKeyboardMarkup(kb))
    else:
        await message.edit_text(platforms_text, reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.MARKDOWN)

def get_platform_emoji(platform: str) -> str:
    """Retorna el emoji correspondiente a la plataforma"""
    emojis = {
        "YouTube": "📺",
        "Instagram": "📸",
        "TikTok": "🎵",
        "Twitter/X": "🐦",
        "Facebook": "👥",
        "Vimeo": "🎥",
        "Dailymotion": "🎬",
        "Reddit": "📱"
    }
    return emojis.get(platform, "🌐")

async def start_download(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Inicia el proceso de descarga con un menú más guiado"""
    if update.callback_query:
        await update.callback_query.answer()
        message = update.callback_query.message
    else:
        message = update.message
    
    # Crear botones para plataformas populares
    platform_buttons = []
    for platform in ["YouTube", "Instagram", "TikTok", "Twitter/X"]:
        platform_buttons.append([InlineKeyboardButton(
            f"{get_platform_emoji(platform)} {platform}",
            callback_data=f"platform_{platform}"
        )])
    
    # Añadir botones de acción
    platform_buttons.extend([
        [InlineKeyboardButton("📋 Ver todas las plataformas", callback_data="platforms")],
        [InlineKeyboardButton("❌ Cancelar", callback_data="cancel")]
    ])
    
    text = (
        "🔗 *¿De qué plataforma quieres descargar?*\n\n"
        "Selecciona una plataforma o envía directamente la URL del video.\n\n"
        "_También puedes usar /cancelar para volver al menú principal_"
    )
    
    if hasattr(message, 'reply_markdown'):
        await message.reply_markdown(text, reply_markup=InlineKeyboardMarkup(platform_buttons))
    else:
        await message.edit_text(text, reply_markup=InlineKeyboardMarkup(platform_buttons), parse_mode=ParseMode.MARKDOWN)
    
    return WAITING_URL

async def download_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /descargar - Inicia el proceso de descarga"""
    return await start_download(update, context)

async def process_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Procesa la URL enviada por el usuario"""
    url = update.message.text.strip()
    
    # Verificar si la URL es válida y de un sitio soportado
    if not is_supported_url(url):
        kb = [
            [InlineKeyboardButton("📱 Ver plataformas soportadas", callback_data="platforms")],
            [InlineKeyboardButton("🔄 Intentar otra URL", callback_data="start_download")],
            [InlineKeyboardButton("🏠 Volver al Menú", callback_data="back_to_menu")]
        ]
        
        await update.message.reply_markdown(
            "⚠️ *URL no soportada*\n\n"
            "La URL que enviaste no parece ser de una plataforma soportada.\n"
            "Por favor, verifica la URL e intenta nuevamente.",
            reply_markup=InlineKeyboardMarkup(kb)
        )
        return ConversationHandler.END
    
    # Guardar la URL en el contexto
    context.user_data["url"] = url
    context.user_data["site"] = get_site_name(url)
    
    # Mostrar opciones de formato
    kb = [
        [InlineKeyboardButton("🎬 Descargar VIDEO", callback_data="fmt_video")],
        [InlineKeyboardButton("🎵 Descargar AUDIO", callback_data="fmt_audio")],
        [InlineKeyboardButton("❌ Cancelar", callback_data="cancel")]
    ]
    
    await update.message.reply_markdown(
        f"✅ *URL recibida de {context.user_data['site']}*\n\n"
        "¿Qué formato quieres descargar?",
        reply_markup=InlineKeyboardMarkup(kb)
    )
    
    return CHOOSING_FORMAT

async def process_format(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Procesa la selección de formato y comienza la descarga con mejor feedback"""
    await update.callback_query.answer()
    
    callback_data = update.callback_query.data
    if callback_data == "cancel":
        await update.callback_query.message.reply_markdown(
            "❌ *Operación cancelada*\n\n¿Qué quieres hacer ahora?",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Intentar otra descarga", callback_data="start_download")],
                [InlineKeyboardButton("🏠 Volver al Menú", callback_data="back_to_menu")]
            ])
        )
        return ConversationHandler.END
    
    kind = "audio" if callback_data == "fmt_audio" else "video"
    url = context.user_data.get("url")
    
    # Mostrar mensaje de descarga con progreso
    status_message = await update.callback_query.message.reply_markdown(
        f"⌛ *Iniciando descarga...*\n\n"
        f"📥 Descargando {kind} de {context.user_data.get('site', 'sitio web')}\n"
        f"⏳ Esto puede tomar unos momentos...\n\n"
        f"_Te avisaré cuando esté listo_"
    )
    
    # Proceso de descarga
    context.user_data["status_message"] = status_message
    
    # Actualizar mensaje de estado durante la descarga
    await status_message.edit_text(
        f"⌛ *Descargando...*\n\n"
        f"📥 Descargando {kind} de {context.user_data.get('site', 'sitio web')}\n"
        f"⏳ Procesando archivo...\n\n"
        f"_Por favor, espera un momento..._"
    )
    
    # Iniciar descarga
    result = download_video(url, kind)
    
    if result["status"] != "success":
        await status_message.edit_text(
            f"❌ *Error en la descarga*\n\n"
            f"{result.get('message')}\n\n"
            f"¿Quieres intentar de nuevo?",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Intentar otra URL", callback_data="start_download")],
                [InlineKeyboardButton("🏠 Volver al Menú", callback_data="back_to_menu")]
            ]),
            parse_mode=ParseMode.MARKDOWN
        )
        return ConversationHandler.END
    
    # La descarga fue exitosa
    meta = result["metadata"]
    path = result["path"]
    file_size = os.path.getsize(path)
    
    logging.info(f"Archivo descargado: {path} ({format_file_size(file_size)})")
    
    # Actualizar mensaje de estado
    await status_message.edit_text(
        "✅ *¡Descarga completada!*\n\n"
        "🔄 Procesando archivo para envío...\n"
        "_Un momento por favor..._"
    )
    
    # Intentar subir a Google Drive
    drive_link = None
    if drive_service:
        logging.info("Iniciando subida a Drive...")
        await status_message.edit_text(
            "🔄 *Subiendo a Google Drive...*\n\n"
            "📤 Preparando archivo para compartir...\n"
            "_Esto puede tomar unos momentos..._"
        )
        
        drive_link = upload_to_drive(path)
        
        if not drive_link:
            logging.error("No se pudo obtener el enlace de Drive")
            await status_message.edit_text(
                "❌ *Error al subir a Google Drive*\n\n"
                "No se pudo subir el archivo a Drive. Por favor, intenta de nuevo o usa otro formato.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔄 Intentar otra URL", callback_data="start_download")],
                    [InlineKeyboardButton("🏠 Volver al Menú", callback_data="back_to_menu")]
                ]),
                parse_mode=ParseMode.MARKDOWN
            )
            return ConversationHandler.END
    else:
        logging.warning("Google Drive no está configurado - no se intentará subir el archivo")
    
    # Preparar mensaje de éxito con más detalles
    emoji_type = "🎵" if kind == "audio" else "🎬"
    title = escape_markdown(meta["title"], version=2)
    author = escape_markdown(meta["author"], version=2)
    info_text = (
        f"✨ *¡Descarga exitosa!*\n\n"
        f"{emoji_type} *{title}*\n"
        f"👤 Autor: {author}\n"
        f"⏱ Duración: {format_duration(meta['length'])}\n"
        f"📦 Tamaño: {format_file_size(file_size)}\n"
        f"🌐 Plataforma: {meta.get('site', context.user_data.get('site', 'Desconocida'))}\n"
    )
    
    if drive_link:
        info_text += f"\n📁 *Enlace de Google Drive:*\n`{drive_link}`\n"
        logging.info(f"Enlace de Drive generado: {drive_link}")
    
    # Botones de acción rápida
    action_buttons = [
        [InlineKeyboardButton("⬇️ Descargar otro", callback_data="start_download")],
        [InlineKeyboardButton("📱 Ver plataformas", callback_data="platforms")],
        [InlineKeyboardButton("🏠 Menú Principal", callback_data="back_to_menu")]
    ]
    
    # Actualizar mensaje final
    await status_message.edit_text(
        info_text,
        reply_markup=InlineKeyboardMarkup(action_buttons),
        parse_mode=ParseMode.MARKDOWN
    )
    
    # Enviar archivo por Telegram si es posible y Drive falló
    if not drive_link and file_size <= TELEGRAM_FILE_LIMIT:
        try:
            with open(path, 'rb') as file:
                if kind == "video":
                    await update.callback_query.message.reply_video(
                        file,
                        caption=f"📹 {meta['title']}\n\n"
                               f"✅ ¡Descarga completada!\n"
                               f"¿Quieres descargar otro video?",
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("⬇️ Descargar otro", callback_data="start_download")]
                        ])
                    )
                else:
                    await update.callback_query.message.reply_audio(
                        file,
                        caption=f"🎵 {meta['title']}\n\n"
                               f"✅ ¡Descarga completada!\n"
                               f"¿Quieres descargar otro audio?",
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("⬇️ Descargar otro", callback_data="start_download")]
                        ]),
                        title=meta['title'],
                        performer=meta['author']
                    )
        except Exception as e:
            await update.callback_query.message.reply_markdown(
                f"⚠️ *Error al enviar el archivo:* {str(e)}\n\n"
                f"Puedes descargarlo desde el enlace de Drive si está disponible.",
                reply_markup=InlineKeyboardMarkup(action_buttons)
            )
    elif not drive_link:
        await update.callback_query.message.reply_markdown(
            f"⚠️ *Archivo demasiado grande*\n\n"
            f"El archivo excede el límite de Telegram ({format_file_size(TELEGRAM_FILE_LIMIT)})\n"
            f"Por favor, usa el enlace de Google Drive para descargar.",
            reply_markup=InlineKeyboardMarkup(action_buttons)
        )
    
    # Limpiar archivo
    try:
        os.remove(path)
        logging.info(f"Archivo eliminado: {path}")
    except:
        logging.warning(f"No se pudo eliminar: {path}")
    
    return ConversationHandler.END

async def handle_platform_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Maneja la selección de plataforma desde el menú"""
    await update.callback_query.answer()
    platform = update.callback_query.data.replace("platform_", "")
    
    text = (
        f"🔗 *Descarga de {platform} {get_platform_emoji(platform)}*\n\n"
        f"Por favor, envía la URL del video que quieres descargar.\n\n"
        f"_Ejemplo de URL válida:_\n"
        f"`{SUPPORTED_SITES[platform][0]}`"
    )
    
    kb = [[InlineKeyboardButton("❌ Cancelar", callback_data="cancel")]]
    
    await update.callback_query.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode=ParseMode.MARKDOWN
    )
    
    return WAITING_URL

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancela la operación actual y vuelve al menú principal"""
    user = update.message.from_user
    logging.info("Usuario %s canceló la conversación.", user.first_name)
    
    await update.message.reply_markdown(
        "❌ *Operación cancelada*\n\n¿Qué quieres hacer ahora?",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🏠 Volver al Menú", callback_data="back_to_menu")]
        ])
    )
    
    return ConversationHandler.END

async def cancel_from_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancela la operación desde un callback"""
    await update.callback_query.answer()
    
    await update.callback_query.message.reply_markdown(
        "❌ *Operación cancelada*\n\n¿Qué quieres hacer ahora?",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🏠 Volver al Menú", callback_data="back_to_menu")]
        ])
    )
    
    return ConversationHandler.END

async def unknown_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Responde a comandos desconocidos"""
    kb = [[InlineKeyboardButton("🏠 Menú Principal", callback_data="back_to_menu")]]
    
    await update.message.reply_markdown(
        "⚠️ *Comando desconocido*\n\n"
        "No reconozco ese comando. Por favor, usa /ayuda para ver la lista de comandos disponibles.",
        reply_markup=InlineKeyboardMarkup(kb)
    )

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Maneja texto que no es parte de una conversación"""
    text = update.message.text.strip()
    
    # Detectar si es una URL válida
    if text.startswith(("http://", "https://")) and is_supported_url(text):
        context.user_data["url"] = text
        context.user_data["site"] = get_site_name(text)
        
        kb = [
            [InlineKeyboardButton("🎬 Descargar VIDEO", callback_data="fmt_video")],
            [InlineKeyboardButton("🎵 Descargar AUDIO", callback_data="fmt_audio")]
        ]
        
        await update.message.reply_markdown(
            f"✅ *URL detectada de {context.user_data['site']}*\n\n"
            "¿Qué formato quieres descargar?",
            reply_markup=InlineKeyboardMarkup(kb)
        )
        
        return CHOOSING_FORMAT
    else:
        # Si no es una URL, mostrar el menú principal
        await show_welcome_message(update, context)
        return ConversationHandler.END

def main():
    """Función principal para iniciar el bot"""
    # Crear el directorio de descargas si no existe
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    
    # Iniciar el servidor Flask en un hilo separado
    threading.Thread(target=run_flask, daemon=True).start()
    
    # Crear la aplicación del bot
    app_bot = Application.builder().token(TELEGRAM_TOKEN).build()
    
    # Manejador de conversación para el proceso de descarga
    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("descargar", download_command),
            CallbackQueryHandler(start_download, pattern="^start_download$"),
            CallbackQueryHandler(handle_platform_selection, pattern="^platform_"),
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text)
        ],
        states={
            WAITING_URL: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, process_url),
                CallbackQueryHandler(cancel_from_callback, pattern="^cancel$")
            ],
            CHOOSING_FORMAT: [
                CallbackQueryHandler(process_format, pattern="^fmt_(video|audio)$"),
                CallbackQueryHandler(cancel_from_callback, pattern="^cancel$")
            ]
        },
        fallbacks=[CommandHandler("cancelar", cancel)]
    )
    
    # Agregar manejadores
    app_bot.add_handler(CommandHandler("start", start))
    app_bot.add_handler(CommandHandler("ayuda", help_command))
    app_bot.add_handler(CommandHandler("plataformas", platforms_command))
    app_bot.add_handler(conv_handler)
    
    # Manejador para el botón de estado
    app_bot.add_handler(CallbackQueryHandler(
        lambda u, c: u.callback_query.answer("🟢 Bot activo y funcionando", show_alert=True),
        pattern="^bot_status$"
    ))
    
    # Manejador para volver al menú
    app_bot.add_handler(CallbackQueryHandler(show_welcome_message, pattern="^back_to_menu$"))
    
    # Manejador para comandos desconocidos
    app_bot.add_handler(MessageHandler(filters.COMMAND, unknown_command))
    
    # Iniciar el bot
    app_bot.run_polling()

if __name__ == "__main__":
    main()