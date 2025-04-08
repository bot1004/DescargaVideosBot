from yt_dlp import YoutubeDL
import logging

logging.basicConfig(level=logging.DEBUG)

# Función para validar URL de YouTube
def is_valid_youtube_url(url):
    return 'youtube.com/watch?v=' in url

# Función para descargar el video
def download_video(url):
    if not is_valid_youtube_url(url):
        return {'status': 'error', 'message': 'URL no válida de YouTube'}

    try:
        # Opciones para yt-dlp
        ydl_opts = {
            'format': 'bestvideo+bestaudio/best',  # Mejor video y audio
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