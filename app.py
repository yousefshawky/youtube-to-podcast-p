import eventlet
eventlet.monkey_patch()

import os
from flask import Flask, request, jsonify, render_template
from flask_socketio import SocketIO, emit
from celery import Celery
from tasks import download_channel_podcast, download_playlist_podcast, resolve_channel_url

app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret!'
socketio = SocketIO(app, message_queue='redis://localhost:6379/0', async_mode='eventlet')

def make_celery(app):
    celery = Celery(app.import_name, broker=app.config['CELERY_BROKER_URL'])
    celery.conf.update(app.config)
    TaskBase = celery.Task

    class ContextTask(TaskBase):
        abstract = True

        def __call__(self, *args, **kwargs):
            with app.app_context():
                return TaskBase.__call__(self, *args, **kwargs)

    celery.Task = ContextTask
    return celery

app.config.update(
    CELERY_BROKER_URL='redis://localhost:6379/0',
    CELERY_RESULT_BACKEND='redis://localhost:6379/0'
)

celery = make_celery(app)

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/start-conversion', methods=['POST'])
def start_conversion():
    data = request.json
    url = data['url']
    min_duration = data.get('min_duration_minutes', 0) * 60 + data.get('min_duration_seconds', 0) if 'min_duration_minutes' in data and 'min_duration_seconds' in data else None
    max_duration = data.get('max_duration_minutes', 0) * 60 + data.get('max_duration_seconds', 0) if 'max_duration_minutes' in data and 'max_duration_seconds' in data else None
    title_filter = data.get('title_filter', None)

    # Resolve the correct URL format
    api_key = os.getenv('API_KEY')
    resolved_url = resolve_channel_url(url, api_key)
    if not resolved_url:
        return jsonify({"status": "error", "message": "Invalid URL format"})

    if "playlist?list=" in resolved_url:
        task = download_playlist_podcast.apply_async(args=[resolved_url, min_duration, max_duration, title_filter])
    elif "channel/" in resolved_url or "/@" in resolved_url:
        task = download_channel_podcast.apply_async(args=[resolved_url, min_duration, max_duration, title_filter])
    else:
        return jsonify({"status": "error", "message": "Invalid URL format"})

    return jsonify({"status": "started", "task_id": task.id})

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5001)
