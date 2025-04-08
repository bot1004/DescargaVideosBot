from pytube import YouTube

def descargar_video(url):
    try:
        yt = YouTube(url)
        stream = yt.streams.filter(progressive=True, file_extension='mp4').order_by('resolution').desc().first()
        if stream:
            print(f"🔽 Baixant: {yt.title}")
            stream.download()
            print("✅ Vídeo descarregat correctament!")
        else:
            print("⚠️ No s'ha trobat cap stream compatible.")
    except Exception as e:
        print(f"❌ Error: {e}")

url = input("🔗 Introdueix la URL del vídeo de YouTube: ")
descargar_video(url)
