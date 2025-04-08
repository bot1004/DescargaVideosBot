import yt_dlp

def descarregar_video(url):
    ydl_opts = {
        'outtmpl': '%(title)s.%(ext)s',  # Nom del fitxer de sortida
        'format': 'bestvideo+bestaudio/best',  # Millor qualitat disponible
        'merge_output_format': 'mp4',  # Format de sortida
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])

# Exemple d'ús
url = input("Introdueix la URL del vídeo de YouTube: ")
descarregar_video(url)
