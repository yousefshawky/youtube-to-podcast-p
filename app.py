from flask import Flask, request, render_template
from tasks import download_channel_podcast

app = Flask(__name__)

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        channel_url = request.form['channel_url']
        download_channel_podcast.delay(channel_url)
        return 'Processing... Check your logs for updates.'

    return render_template('index.html')

if __name__ == '__main__':
    app.run(debug=True)
