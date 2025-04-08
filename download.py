from yt_dlp import YoutubeDL
import os
import logging
import re

logging.basicConfig(level=logging.DEBUG)

# Función para validar URLs de YouTube
def is_valid_youtube_url(url):
    pattern = r'(https?://)?(www\.)?(youtube\.com|youtu\.be)/.+'  # Validación básica
    return re.match(pattern, url) is not None

def download_video(url, quality='highest'):
    if not is_valid_youtube_url(url):
        return {'status': 'error', 'message': 'URL no válida de YouTube'}

    try:
        # Opciones de configuración para yt-dlp
        ydl_opts = {
            'format': quality,  # 'best', 'highest', 'audio', o el que sea solicitado
            'noplaylist': True,  # Evita descargar listas de reproducción
            'outtmpl': 'downloads/%(title)s.%(ext)s',  # Define el nombre del archivo
            'merge_output_format': 'mp4',  # Asegura que se convierta a MP4
            'postprocessors': [{
                'key': 'FFmpegVideoConvertor',  # Correcto: Conversión de video
                'preferedformat': 'mp4',  # Asegura que se convierta a MP4
            }],
        }

        # Usar yt-dlp con las opciones definidas
        with YoutubeDL(ydl_opts) as ydl:
            result = ydl.extract_info(url, download=True)

        # Devolver la información del archivo descargado
        return {
            'status': 'success',
            'filename': result['title'] + '.mp4',  # Asignar extensión .mp4
            'title': result['title'],
            'author': result['uploader'],
            'length': result['duration']
        }

    except Exception as e:
        logging.error("Error al descargar:", exc_info=True)
        return {'status': 'error', 'message': f"Error al descargar: {str(e)}"}
