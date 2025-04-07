from pytube import YouTube
import os

def download_video(url, quality='highest'):
    try:
        yt = YouTube(url)
        
        if quality == 'highest':
            stream = yt.streams.get_highest_resolution()
        elif quality == 'audio':
            stream = yt.streams.get_audio_only()
        else:
            stream = yt.streams.filter(res=quality, file_extension='mp4').first()
        
        # Crear directorio si no existe
        os.makedirs('downloads', exist_ok=True)
        
        # Descargar el video
        filename = stream.default_filename
        stream.download('downloads')
        
        return {
            'status': 'success',
            'filename': filename,
            'title': yt.title,
            'author': yt.author,
            'length': yt.length
        }
    except Exception as e:
        return {
            'status': 'error',
            'message': str(e)
        }