import os
import requests
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackContext, ConversationHandler, filters
import logging

logging.basicConfig(level=logging.INFO)

API_URL = "http://localhost:5001/download"
# Suponemos que n8n está corriendo en un contenedor y expone un endpoint para subir archivos.
N8N_UPLOAD_URL = "http://localhost:5678/upload"  # Ajusta según tu configuración

ELEGIR_TIPO = range(1)
TELEGRAM_FILE_LIMIT = 50 * 1024 * 1024  # 50 MB en bytes

async def start(update: Update, context: CallbackContext):
    await update.message.reply_text(
        "Envía el enlace del vídeo que quieres descargar (puede ser de YouTube, Instagram, TikTok, Twitter, Facebook, etc.)."
    )

def detectar_plataforma(url):
    plataformas = {
        'youtube.com': 'YouTube 📺',
        'youtu.be': 'YouTube 📺',
        'instagram.com': 'Instagram 📸',
        'tiktok.com': 'TikTok 🎵',
        'twitter.com': 'Twitter 🐦',
        'x.com': 'Twitter 🐦',
        'facebook.com': 'Facebook 👍',
        'fb.watch': 'Facebook 👍',
        'vimeo.com': 'Vimeo 🎞️',
        'dailymotion.com': 'Dailymotion 📹',
        'reddit.com': 'Reddit 👽'
    }
    for key, nombre in plataformas.items():
        if key in url:
            return nombre
    return 'desconocida ❓'

async def recibir_url(update: Update, context: CallbackContext):
    url = update.message.text.strip()
    context.user_data['url'] = url
    plataforma = detectar_plataforma(url)

    keyboard = [["🎬 Vídeo completo", "🎵 Solo audio"]]
    await update.message.reply_text(
        f"He detectado que el enlace es de {plataforma}.\n"
        "¿Qué deseas descargar?",
        reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
    )

    return ELEGIR_TIPO

async def elegir_tipo(update: Update, context: CallbackContext):
    eleccion = update.message.text.strip()
    url = context.user_data['url']
    download_type = 'audio' if 'audio' in eleccion.lower() else 'video'

    # Solicita al API para descargar el archivo
    response = requests.post(API_URL, json={'url': url, 'type': download_type})
    data = response.json()

    if data['status'] != 'success':
        await update.message.reply_text(f"❌ Error: {data.get('message', 'Error desconocido')}")
        return ConversationHandler.END

    # El API nos devuelve la metadata y el filename
    metadata = data['metadata']
    filename = data['filename']
    file_path = os.path.join("downloads", filename)

    if not os.path.exists(file_path):
        await update.message.reply_text("❌ Error: El archivo no se encontró en el servidor.")
        return ConversationHandler.END

    file_size = os.path.getsize(file_path)
    logging.info(f"El archivo {filename} pesa {file_size} bytes.")

    # Si el archivo está dentro del límite, envíalo directamente
    if file_size <= TELEGRAM_FILE_LIMIT:
        try:
            await update.message.reply_document(document=open(file_path, 'rb'),
                                                caption=f"✅ Archivo descargado:\n"
                                                        f"📹 Título: {metadata['title']}\n"
                                                        f"👤 Autor: {metadata['author']}\n"
                                                        f"⏱ Duración: {metadata['length']} segundos")
        except Exception as e:
            await update.message.reply_text(f"❌ Error al enviar el archivo: {str(e)}")
    else:
        # Si el archivo excede el límite, usamos el endpoint de n8n para subirlo
        try:
            with open(file_path, 'rb') as f:
                files = {'file': (filename, f)}
                n8n_response = requests.post(N8N_UPLOAD_URL, files=files)
            if n8n_response.status_code == 200:
                # Se espera que n8n devuelva un JSON con la URL de descarga
                result = n8n_response.json()
                download_link = result.get("download_url")
                if download_link:
                    await update.message.reply_text(
                        f"✅ El archivo es muy grande para enviarlo directamente.\n"
                        f"Puedes descargarlo desde este enlace: {download_link}"
                    )
                else:
                    await update.message.reply_text("❌ Error al obtener el enlace de descarga desde n8n.")
            else:
                await update.message.reply_text("❌ Error al subir el archivo a n8n.")
        except Exception as e:
            await update.message.reply_text(f"❌ Error al subir el archivo a n8n: {str(e)}")

    return ConversationHandler.END

async def cancelar(update: Update, context: CallbackContext):
    await update.message.reply_text("Operación cancelada.")
    return ConversationHandler.END

def main():
    TOKEN = "8121623575:AAH798Us_OvXfiejYhURKDfxA3m4yXWe3PM"  # Sustituye por tu token real

    application = Application.builder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.TEXT & ~filters.COMMAND, recibir_url)],
        states={
            ELEGIR_TIPO: [MessageHandler(filters.TEXT & ~filters.COMMAND, elegir_tipo)]
        },
        fallbacks=[CommandHandler('cancelar', cancelar)]
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(conv_handler)

    application.run_polling()

if __name__ == '__main__':
    os.makedirs('downloads', exist_ok=True)
    main()
