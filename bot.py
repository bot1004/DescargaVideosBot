import os
import requests
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackContext, filters
import logging

# Configuración de logging
logging.basicConfig(level=logging.INFO)

API_URL = "http://localhost:5001/download"

# Función para manejar el mensaje
async def handle_message(update: Update, context: CallbackContext):
    url = update.message.text.strip()

    try:
        response = requests.post(API_URL, json={'url': url})
        data = response.json()

        # Imprimir la respuesta para depurar
        logging.info(f"Respuesta de la API: {data}")

        if response.status_code == 200:
            metadata = data.get('metadata', None)  # Usamos get para evitar KeyError

            if metadata is not None:
                filename = data.get('filename', 'No disponible')  # Usamos get para evitar KeyError
                file_path = os.path.join("downloads", filename)

                # Mensaje con los detalles del video
                await update.message.reply_text(
                    f"✅ Video descargado:\n"
                    f"📹 Título: {metadata['title']}\n"
                    f"👤 Autor: {metadata['author']}\n"
                    f"⏱ Duración: {metadata['length']} segundos\n"
                    f"📂 Ruta del archivo: {file_path}"
                )
            else:
                await update.message.reply_text("❌ Error: La respuesta no contiene metadata.")
        else:
            await update.message.reply_text(f"❌ Error: {data.get('error', 'Error desconocido')}")
    
    except Exception as e:
        await update.message.reply_text(f"❌ Error de conexión con el servidor: {str(e)}")

# Función para iniciar el bot
async def start(update: Update, context: CallbackContext):
    await update.message.reply_text(
        "¡Bienvenido al bot de descarga de YouTube!\n"
        "Envía el enlace de un video de YouTube para descargarlo."
    )

# Función principal para ejecutar el bot
def main():
    TOKEN = "8121623575:AAH798Us_OvXfiejYhURKDfxA3m4yXWe3PM"  # Sustituye por tu token real de Telegram

    # Inicialización de la aplicación
    application = Application.builder().token(TOKEN).build()

    # Agregar manejadores
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Ejecutar el bot
    application.run_polling()

if __name__ == '__main__':
    main()
