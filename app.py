import os
from flask import Flask, render_template, request, jsonify, Response
from tasks import download_channel_podcast, download_playlist_podcast
import logging

app = Flask(__name__)

# Ensure the 'static' folder is correctly configured
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0

status_updates = []  # Global list to hold status updates

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/start-conversion', methods=['POST'])
def start_conversion():
    data = request.json
    url = data['url']
    min_duration_minutes = data.get('min_duration_minutes', 0)
    min_duration_seconds = data.get('min_duration_seconds', 0)
    min_duration = int(min_duration_minutes) * 60 + int(min_duration_seconds)

    if 'channel' in url:
        task = download_channel_podcast.delay(url, min_duration)
    elif 'playlist' in url:
        task = download_playlist_podcast.delay(url, min_duration)
    else:
        return jsonify({'status': 'error', 'message': 'Invalid URL'}), 400

    return jsonify({'status': 'started', 'task_id': task.id}), 202

@app.route('/status-updates')
def status_updates_view():
    def generate():
        while True:
            if status_updates:
                update = status_updates.pop(0)
                yield f'data: {update}\n\n'
    return Response(generate(), mimetype='text/event-stream')

if __name__ == '__main__':
    logging.basicConfig(filename='logfile.log', level=logging.INFO)
    app.run(debug=True)
