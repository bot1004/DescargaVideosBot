from flask import Flask, request, jsonify
from yt_dlp import YoutubeDL
import logging

app = Flask(__name__)

logging.basicConfig(level=logging.DEBUG)

# Función para validar URL de YouTube
def is_valid_youtube_url(url):
    return 'youtube.com/watch?v=' in url

# Función para descargar el video
def download_video(url, quality='bestvideo+bestaudio'):
    if not is_valid_youtube_url(url):
        return {'status': 'error', 'message': 'URL no válida de YouTube'}

    try:
        # Opciones para yt-dlp
        ydl_opts = {
            'format': quality,  # Usa la calidad proporcionada
            'noplaylist': True,  # Desactivar descarga de listas de reproducción
            'outtmpl': 'downloads/%(title)s.%(ext)s',  # Ruta de descarga
            'merge_output_format': 'mp4',  # Formato de salida
        }

        # Descargar video
        with YoutubeDL(ydl_opts) as ydl:
            result = ydl.extract_info(url, download=True)

        return {
            'status': 'success',
            'filename': result['title'] + '.mp4',  # Asignar extensión mp4
            'title': result['title'],
            'author': result['uploader'],
            'length': result['duration']
        }

    except Exception as e:
        logging.error("Error al descargar:", exc_info=True)
        return {'status': 'error', 'message': f"Error al descargar: {str(e)}"}

@app.route('/download', methods=['POST'])
def download():
    try:
        # Recibir la URL desde el cuerpo del POST
        data = request.get_json()
        url = data.get('url')
        quality = data.get('quality', 'bestvideo+bestaudio')  # Default quality if not provided

        # Llamar a la función para descargar el video
        result = download_video(url, quality)

        return jsonify(result)
    except Exception as e:
        logging.error("Error en la API:", exc_info=True)
        return jsonify({'status': 'error', 'message': 'Error en la API: ' + str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5001)
