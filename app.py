import eventlet
eventlet.monkey_patch()

import os
from flask import Flask, request, jsonify, render_template, redirect
from flask_socketio import SocketIO, emit
from celery import Celery
from tasks import download_channel_podcast, download_playlist_podcast, resolve_channel_url
from dotenv import load_dotenv
import logging


# Initialize logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

app = Flask(__name__, static_folder='static', template_folder='templates')
app.config['SECRET_KEY'] = 'secret!'

# Configure Redis as the message queue for SocketIO
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
    logging.info("Accessed index route")
    return render_template('index.html')

@app.route('/start-conversion', methods=['POST'])
def start_conversion():
    try:
        data = request.json
        logging.info(f"Received data: {data}")

        url = data['url']
        min_duration = int(data.get('min_duration_minutes', 0)) * 60 + int(data.get('min_duration_seconds',
                                                                                    0)) if 'min_duration_minutes' in data and 'min_duration_seconds' in data else None
        max_duration = int(data.get('max_duration_minutes', 0)) * 60 + int(data.get('max_duration_seconds',
                                                                                    0)) if 'max_duration_minutes' in data and 'max_duration_seconds' in data else None
        title_filter = data.get('title_filter', None)
        buzzsprout_api_key = data['buzzsprout_api_key']
        buzzsprout_podcast_id = data['buzzsprout_podcast_id']

        logging.info(
            f"Received start-conversion request: URL={url}, min_duration={min_duration}, max_duration={max_duration}, title_filter={title_filter}, buzzsprout_api_key={buzzsprout_api_key}, buzzsprout_podcast_id={buzzsprout_podcast_id}")

        resolved_url = resolve_channel_url(url, os.getenv('API_KEY'))
        logging.info(f"Resolved URL: {resolved_url}")

        if not resolved_url:
            logging.error("Invalid URL format")
            return jsonify({"status": "error", "message": "Invalid URL format"}), 400

        env_content = f"""
API_KEY={os.getenv('API_KEY')}
AWS_ACCESS_KEY_ID={os.getenv('AWS_ACCESS_KEY_ID')}
AWS_SECRET_ACCESS_KEY={os.getenv('AWS_SECRET_ACCESS_KEY')}
BUZZSPROUT_API_KEY={buzzsprout_api_key}
BUZZSPROUT_PODCAST_ID={buzzsprout_podcast_id}
AWS_BUCKET_NAME={os.getenv('AWS_BUCKET_NAME')}
        """

        user_env_path = f"user_envs/{buzzsprout_podcast_id}.env"
        os.makedirs(os.path.dirname(user_env_path), exist_ok=True)
        with open(user_env_path, 'w') as env_file:
            env_file.write(env_content.strip())

        logging.info(f"Created .env file at: {user_env_path}")

        if "playlist?list=" in resolved_url:
            task = download_playlist_podcast.apply_async(
                args=[resolved_url, min_duration, max_duration, title_filter, user_env_path])
        elif "channel/" in resolved_url or "/@" in resolved_url:
            task = download_channel_podcast.apply_async(
                args=[resolved_url, min_duration, max_duration, title_filter, user_env_path])
        else:
            logging.error("Invalid URL format")
            return jsonify({"status": "error", "message": "Invalid URL format"}), 400

        logging.info(f"Task {task.id} started")
        return jsonify({"status": "started", "task_id": task.id})
    except KeyError as e:
        logging.error(f"KeyError: {e}")
        return jsonify({"status": "error", "message": f"Missing key: {str(e)}"}), 400
    except Exception as e:
        logging.error(f"Error in start-conversion: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/stop-conversion', methods=['POST'])
def stop_conversion():
    try:
        # Revoke all tasks
        i = celery.control.inspect()
        active_tasks = i.active()

        if active_tasks:
            for worker, tasks in active_tasks.items():
                for task in tasks:
                    celery.control.revoke(task['id'], terminate=True)
            logging.info("All active tasks have been terminated.")
            return jsonify({"status": "stopped"})
        else:
            logging.info("No active tasks to terminate.")
            return jsonify({"status": "error", "message": "No active tasks to terminate"}), 400

    except Exception as e:
        logging.error(f"Error stopping conversion: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == '__main__':
    logging.info("Starting Flask app")
    print("Starting Flask app")
    socketio.run(app, host='0.0.0.0', port=5001)
    logging.info("Flask app running")
    print("Flask app running")
