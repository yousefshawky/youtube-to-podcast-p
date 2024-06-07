from flask import Flask, request, render_template
from tasks import download_channel_podcast, download_playlist_podcast

app = Flask(__name__)


@app.route('/')
def index():
    channel_url = request.args.get('channel_url')
    playlist_url = request.args.get('playlist_url')
    min_duration_minutes = int(request.args.get('min_duration_minutes', 0))
    min_duration_seconds = int(request.args.get('min_duration_seconds', 0))
    min_duration = min_duration_minutes * 60 + min_duration_seconds

    if channel_url:
        download_channel_podcast.delay(channel_url, min_duration)
    elif playlist_url:
        download_playlist_podcast.delay(playlist_url, min_duration)

    return render_template('index.html')


if __name__ == "__main__":
    app.run(debug=True)
