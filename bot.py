from telegram import Update
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext
import requests
import os

API_URL = "http://localhost:5000/download"  # Cambiar en producción

def start(update: Update, context: CallbackContext):
    update.message.reply_text(
        "¡Bienvenido al bot de descarga de YouTube!\n"
        "Envía el enlace de un video de YouTube para descargarlo."
    )

def handle_message(update: Update, context: CallbackContext):
    url = update.message.text
    
    try:
        response = requests.post(API_URL, json={'url': url})
        data = response.json()
        
        if response.status_code == 200:
            download_url = data['download_url']
            metadata = data['metadata']
            
            message = (
                f"✅ Video descargado:\n"
                f"📹 Título: {metadata['title']}\n"
                f"👤 Autor: {metadata['author']}\n"
                f"⏱ Duración: {metadata['length']} segundos\n"
                f"🔗 Enlace: {download_url}"
            )
            
            update.message.reply_text(message)
        else:
            update.message.reply_text(f"❌ Error: {data.get('error', 'Error desconocido')}")
    except Exception as e:
        update.message.reply_text(f"❌ Error de conexión con el servidor: {str(e)}")

def main():
    TOKEN = "TU_TOKEN_DE_TELEGRAM"  # Obtener de @BotFather
    updater = Updater(TOKEN)
    dispatcher = updater.dispatcher
    
    dispatcher.add_handler(CommandHandler("start", start))
    dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_message))
    
    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()