from pytube import YouTube

def descargar_video(url):
    yt = YouTube(url)
    stream = yt.streams.get_highest_resolution()
    print(f"Descargando: {yt.title}")
    stream.download()
    print("¡Descarga completada!")

if __name__ == "__main__":
    url = input("Introduce la URL del video de YouTube: ")
    descargar_video(url)
