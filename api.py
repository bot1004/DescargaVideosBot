from flask import Flask, request, jsonify, send_from_directory
from download import download_video
import os
from werkzeug.utils import secure_filename

app = Flask(__name__)

@app.route('/download', methods=['POST'])
def download():
    data = request.json
    url = data.get('url')
    quality = data.get('quality', 'highest')
    
    if not url:
        return jsonify({'error': 'URL is required'}), 400
    
    result = download_video(url, quality)
    
    if result['status'] == 'success':
        return jsonify({
            'download_url': f'/downloads/{result["filename"]}',
            'metadata': {
                'title': result['title'],
                'author': result['author'],
                'length': result['length']
            }
        })
    else:
        return jsonify({'error': result['message']}), 500

@app.route('/downloads/<filename>')
def serve_file(filename):
    return send_from_directory('downloads', filename)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001)