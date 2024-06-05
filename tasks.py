import os
import requests
import certifi
import ssl
import urllib.request
from pytube import YouTube, Channel, request
import ffmpeg
import boto3
from datetime import datetime
import pytz
from googleapiclient.discovery import build
from celery import Celery
from dotenv import load_dotenv

load_dotenv()

app = Celery('tasks', broker='redis://localhost:6379/0')

# SSL context for requests
ssl_context = ssl.create_default_context(cafile=certifi.where())


# Custom get function for pytube
def custom_get(url, headers=None, timeout=None):
    if headers is None:
        headers = {}
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, context=ssl_context, timeout=timeout) as response:
        return response.read().decode('utf-8')


# Patch pytube's request handling
request.get = custom_get

# AWS S3 setup
s3 = boto3.client(
    's3',
    aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
    aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY')
)


def upload_to_s3(file_path, bucket_name, s3_key):
    s3.upload_file(file_path, bucket_name, s3_key)
    s3_url = f'https://{bucket_name}.s3.amazonaws.com/{s3_key}'
    print(f"Uploaded to S3: {s3_url}")  # Debug statement
    return s3_url


def is_url_accessible(url):
    try:
        response = requests.head(url)
        accessible = response.status_code == 200
        print(f"URL accessible: {url}, Status: {response.status_code}, Accessible: {accessible}")  # Debug statement
        return accessible
    except requests.RequestException as e:
        print(f"URL check failed for {url}: {e}")  # Debug statement
        return False


def upload_to_buzzsprout(title, description, file_url):
    if not is_url_accessible(file_url):
        print(f"Failed to upload episode '{title}' to Buzzsprout: URL not accessible")
        return

    api_key = os.getenv('BUZZSPROUT_API_KEY')
    podcast_id = os.getenv('BUZZSPROUT_PODCAST_ID')
    url = f'https://www.buzzsprout.com/api/{podcast_id}/episodes'
    headers = {
        'Authorization': f'Token token={api_key}',
        'Content-Type': 'application/json',
        'User-Agent': 'YT-Podcast 1.0 (Contact: yousef.shawky22@gmail..com)'
    }
    data = {
        'title': title,
        'description': description,
        'audio_url': file_url
    }

    print(f"Uploading to Buzzsprout: {data}")  # Debug statement

    for attempt in range(3):  # Retry mechanism
        response = requests.post(url, headers=headers, json=data)
        print(f"Buzzsprout response: {response.status_code}, {response.content}")  # Debug statement
        if response.status_code == 201:
            print(f"Episode '{title}' uploaded successfully to Buzzsprout.")
            return
        elif response.status_code == 403:
            print("Cloudflare block encountered. Retrying...")
        else:
            print(f"Failed to upload episode '{title}' to Buzzsprout: {response.content}")
            print(f"Audio URL: {file_url}")
            return

    print(f"Failed to upload episode '{title}' to Buzzsprout after multiple attempts.")


def get_channel_videos(channel_id, api_key):
    youtube = build('youtube', 'v3', developerKey=api_key)
    request = youtube.search().list(
        part="snippet",
        channelId=channel_id,
        maxResults=50,
        order="date"
    )
    response = request.execute()
    video_urls = ["https://www.youtube.com/watch?v=" + item['id']['videoId'] for item in response['items'] if
                  item['id']['kind'] == 'youtube#video']
    return video_urls


def download_video(url, download_path):
    yt = YouTube(url)
    stream = yt.streams.filter(progressive=True, file_extension='mp4').first()
    output_file = stream.download(output_path=download_path)
    output_mp3 = output_file.replace('.mp4', '.mp3')
    ffmpeg.input(output_file).output(output_mp3).run()
    os.remove(output_file)
    return output_mp3


def get_mp3_files_metadata(download_path):
    episodes = []
    for file in os.listdir(download_path):
        if file.endswith(".mp3"):
            file_path = os.path.join(download_path, file)
            file_size = os.path.getsize(file_path)
            pub_date = datetime.now(pytz.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")
            episodes.append({
                'title': file.replace('.mp3', ''),
                'description': f"Episode from {file.replace('.mp3', '')}",
                'pubDate': pub_date,
                'url': upload_to_s3(file_path, os.getenv('AWS_BUCKET_NAME'), f"podcast/{file}"),
                'length': file_size
            })
    return episodes


def generate_rss_feed(channel_name, episodes, output_path):
    rss_feed = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>{channel_name} Podcast</title>
    <description>{channel_name} YouTube Channel converted to Podcast</description>
    <link>http://yourwebsite.com/podcast</link>"""

    for episode in episodes:
        rss_feed += f"""
    <item>
      <title>{episode['title']}</title>
      <description>{episode['description']}</description>
      <pubDate>{episode['pubDate']}</pubDate>
      <enclosure url="{episode['url']}" length="{episode['length']}" type="audio/mpeg"/>
      <guid>{episode['url']}</guid>
    </item>"""

    rss_feed += """
  </channel>
</rss>"""

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(rss_feed)


@app.task
def download_channel_podcast(channel_url):
    try:
        channel = Channel(channel_url)
        channel_name = channel.channel_name
        channel_id = channel.channel_id
        download_path = os.path.join("downloaded", channel_id)
        os.makedirs(download_path, exist_ok=True)

        api_key = os.getenv('API_KEY')
        if not api_key:
            raise ValueError("No API key provided. Please set the API_KEY environment variable.")

        video_urls = get_channel_videos(channel_id, api_key)

        for video_url in video_urls:
            try:
                print(f"Downloading video: {video_url}")  # Debug statement
                mp3_file = download_video(video_url, download_path)
                file_metadata = get_mp3_files_metadata(download_path)[0]  # Get metadata for the newly downloaded file
                print(f"File metadata: {file_metadata}")  # Debug statement
                s3_url = upload_to_s3(mp3_file, os.getenv('AWS_BUCKET_NAME'),
                                      f"{channel_id}/{os.path.basename(mp3_file)}")
                print(f"Uploaded MP3 URL: {s3_url}")  # Debug statement
                upload_to_buzzsprout(file_metadata['title'], file_metadata['description'], s3_url)
            except Exception as e:
                print(f"Failed to download video {video_url}: {e}")

        episodes = get_mp3_files_metadata(download_path)
        rss_output_path = os.path.join(download_path, "rss_feed.xml")
        generate_rss_feed(channel_name, episodes, rss_output_path)

        # Upload RSS feed to S3
        upload_to_s3(rss_output_path, os.getenv('AWS_BUCKET_NAME'), f"podcast/{channel_id}/rss_feed.xml")

        print(f"Podcast for channel {channel_name} created successfully.")
    except Exception as e:
        print(f"Failed to create podcast: {e}")
