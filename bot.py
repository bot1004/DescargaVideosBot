from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackContext, filters
import requests
import os

API_URL = "http://localhost:5001/download"

async def start(update: Update, context: CallbackContext):
    await update.message.reply_text(
        "¡Bienvenido al bot de descarga de YouTube!\n"
        "Envía el enlace de un video de YouTube para descargarlo."
    )

async def handle_message(update: Update, context: CallbackContext):
    url = update.message.text.strip()

    try:
        response = requests.post(API_URL, json={'url': url})
        data = response.json()

        if response.status_code == 200:
            filename = data['filename']
            metadata = data['metadata']
            file_path = os.path.join("downloads", filename)

            if os.path.exists(file_path):
                with open(file_path, 'rb') as f:
                    await update.message.reply_video(
                        video=f,
                        caption=( 
                            f"✅ Video descargado:\n"
                            f"📹 Título: {metadata['title']}\n"
                            f"👤 Autor: {metadata['author']}\n"
                            f"⏱ Duración: {metadata['length']} segundos"
                        )
                    )
            else:
                await update.message.reply_text("❌ El archivo no se encontró en el servidor.")
        else:
            await update.message.reply_text(f"❌ Error: {data.get('error', 'Error desconocido')}")
    except Exception as e:
        await update.message.reply_text(f"❌ Error de conexión con el servidor: {str(e)}")

def main():
    TOKEN = "8121623575:AAH798Us_OvXfiejYhURKDfxA3m4yXWe3PM"  # 👈 Sustituye por el token real

    # Inicialización de la aplicación (con los cambios de la nueva versión)
    application = Application.builder().token(TOKEN).build()

    # Agregar manejadores
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Correr el bot
    application.run_polling()

if __name__ == '__main__':
    main()
