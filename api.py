from flask import Flask, request, jsonify
from yt_dlp import YoutubeDL
import logging
import os

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

def is_valid_youtube_url(url):
    return 'youtube.com/watch?v=' in url or 'youtu.be/' in url

def download_video(url, quality, download_type='video'):
    if not is_valid_youtube_url(url):
        return {'status': 'error', 'message': 'URL no válida de YouTube'}

    try:
        ydl_opts = {
            'format': quality,
            'noplaylist': True,
            'outtmpl': 'downloads/%(title)s.%(ext)s',
            'windowsfilenames': True,
        }

        if download_type == 'audio':
            ydl_opts.update({
                'format': 'bestaudio/best',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }],
            })
        else:
            ydl_opts['merge_output_format'] = 'mp4'

        with YoutubeDL(ydl_opts) as ydl:
            result = ydl.extract_info(url, download=True)
            real_path = ydl.prepare_filename(result)

            if download_type == 'audio':
                real_path = os.path.splitext(real_path)[0] + ".mp3"

        basename = os.path.basename(real_path)

        return {
            'status': 'success',
            'filename': basename,
            'metadata': {
                'title': result.get('title'),
                'author': result.get('uploader'),
                'length': result.get('duration'),
                'type': download_type
            }
        }

    except Exception as e:
        logging.error("Error al descargar:", exc_info=True)
        return {'status': 'error', 'message': f"Error al descargar: {str(e)}"}

@app.route('/download', methods=['POST'])
def download():
    try:
        data = request.get_json()
        url = data.get('url')
        download_type = data.get('type', 'video')

        quality = 'bestvideo+bestaudio' if download_type == 'video' else 'bestaudio/best'

        result = download_video(url, quality, download_type)
        return jsonify(result)

    except Exception as e:
        logging.error("Error en la API:", exc_info=True)
        return jsonify({'status': 'error', 'message': 'Error en la API: ' + str(e)}), 500

if __name__ == '__main__':
    os.makedirs('downloads', exist_ok=True)
    app.run(debug=True, host='0.0.0.0', port=5001)
