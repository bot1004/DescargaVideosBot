import os
import requests
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackContext, ConversationHandler, filters
import logging

logging.basicConfig(level=logging.INFO)

API_URL = "http://localhost:5001/download"
ELEGIR_TIPO = range(1)

async def start(update: Update, context: CallbackContext):
    await update.message.reply_text("Envía el enlace del vídeo que quieres descargar (YouTube, Instagram, TikTok, Twitter, Facebook, etc.).")

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

    response = requests.post(API_URL, json={'url': url, 'type': download_type})
    data = response.json()

    if data['status'] == 'success':
        metadata = data['metadata']
        file_path = os.path.join("downloads", data['filename'])

        await update.message.reply_text(
            f"✅ Archivo descargado:\n"
            f"📹 Título: {metadata['title']}\n"
            f"👤 Autor: {metadata['author']}\n"
            f"⏱ Duración: {metadata['length']} segundos\n"
            f"📂 Archivo: {file_path}"
        )
    else:
        await update.message.reply_text(f"❌ Error: {data['message']}")

    return ConversationHandler.END

async def cancelar(update: Update, context: CallbackContext):
    await update.message.reply_text("Operación cancelada.")
    return ConversationHandler.END

def main():
    TOKEN = "8121623575:AAH798Us_OvXfiejYhURKDfxA3m4yXWe3PM"

    application = Application.builder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.TEXT & ~filters.COMMAND, recibir_url)],
        states={ ELEGIR_TIPO: [MessageHandler(filters.TEXT & ~filters.COMMAND, elegir_tipo)] },
        fallbacks=[CommandHandler('cancelar', cancelar)]
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(conv_handler)

    application.run_polling()

if __name__ == '__main__':
    os.makedirs('downloads', exist_ok=True)
    main()
