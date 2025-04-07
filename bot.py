from telegram import Update
from telegram.ext import (
    Application,  # Reemplaza Updater
    CommandHandler,
    MessageHandler,
    CallbackContext,
    filters
)
import requests

API_URL = "http://localhost:5001/download"

async def start(update: Update, context: CallbackContext):
    await update.message.reply_text(
        "¡Bienvenido al bot de descarga de YouTube!\n"
        "Envía el enlace de un video de YouTube para descargarlo."
    )

async def handle_message(update: Update, context: CallbackContext):
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
            
            await update.message.reply_text(message)
        else:
            await update.message.reply_text(f"❌ Error: {data.get('error', 'Error desconocido')}")
    except Exception as e:
        await update.message.reply_text(f"❌ Error de conexión con el servidor: {str(e)}")

def main():
    TOKEN = "8121623575:AAH798Us_OvXfiejYhURKDfxA3m4yXWe3PM"
    
    # Nueva forma de inicializar (v21.0+)
    application = Application.builder().token(TOKEN).build()
    
    # Handlers (ahora usan async/await)
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # Inicia el bot
    application.run_polling()

if __name__ == '__main__':
    main()