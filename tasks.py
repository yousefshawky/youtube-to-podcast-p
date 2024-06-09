import os
import requests
import certifi
import ssl
import urllib.request
from pytube import YouTube, Channel, Playlist, request
import ffmpeg
import boto3
from datetime import datetime
import pytz
from googleapiclient.discovery import build
from celery import Celery
from dotenv import load_dotenv
import logging
from flask import current_app, Flask

load_dotenv()

flask_app = Flask(__name__)

celery_app = Celery('tasks', broker='redis://localhost:6379/0', backend='redis://localhost:6379/0')

# SSL context for requests
ssl_context = ssl.create_default_context(cafile=certifi.where())

# Setup logging
logging.basicConfig(filename='logfile.log', level=logging.INFO, format='%(message)s')

# Store the status updates
status_updates = []

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
    return s3_url

def is_url_accessible(url):
    try:
        response = requests.head(url)
        return response.status_code == 200
    except requests.RequestException:
        return False

def format_description(description):
    # Replace new lines with HTML line breaks to preserve formatting
    return description.replace('\n', '<br>\n')

def upload_to_buzzsprout(title, description, file_url):
    if not is_url_accessible(file_url):
        status_updates.append(f"Failed to upload episode '{title}' to Buzzsprout: URL not accessible")
        logging.info(f"Failed to upload episode '{title}' to Buzzsprout: URL not accessible")
        return False

    api_key = os.getenv('BUZZSPROUT_API_KEY')
    podcast_id = os.getenv('BUZZSPROUT_PODCAST_ID')
    url = f'https://www.buzzsprout.com/api/{podcast_id}/episodes'
    headers = {
        'Authorization': f'Token token={api_key}',
        'Content-Type': 'application/json',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    data = {
        'title': title,
        'description': format_description(description),
        'audio_url': file_url
    }
    response = requests.post(url, headers=headers, json=data)
    if response.status_code == 201:
        status_updates.append(f"Episode '{title}' uploaded successfully to Buzzsprout.")
        logging.info(f"Episode '{title}' uploaded successfully to Buzzsprout.")
        return response.json().get('id')  # Return the episode ID
    else:
        status_updates.append(f"Failed to upload episode '{title}' to Buzzsprout: {response.content}")
        logging.info(f"Failed to upload episode '{title}' to Buzzsprout: {response.content}")
        status_updates.append(f"Audio URL: {file_url}")
        return None

def get_channel_videos(channel_id, api_key):
    youtube = build('youtube', 'v3', developerKey=api_key)
    request = youtube.search().list(
        part="snippet",
        channelId=channel_id,
        maxResults=50,
        order="date"
    )
    response = request.execute()
    video_urls = [{"url": "https://www.youtube.com/watch?v=" + item['id']['videoId'],
                   "description": item['snippet']['description']} for item in response['items'] if
                  item['id']['kind'] == 'youtube#video']
    return video_urls

def get_playlist_videos(playlist_id, api_key):
    youtube = build('youtube', 'v3', developerKey=api_key)
    request = youtube.playlistItems().list(
        part="snippet,contentDetails",
        playlistId=playlist_id,
        maxResults=50
    )
    response = request.execute()
    video_urls = [{"url": "https://www.youtube.com/watch?v=" + item['contentDetails']['videoId'],
                   "description": item['snippet']['description']} for item in response['items']]
    return video_urls

def get_video_details(video_id, api_key):
    youtube = build('youtube', 'v3', developerKey=api_key)
    request = youtube.videos().list(
        part="snippet,contentDetails",
        id=video_id
    )
    response = request.execute()
    if 'items' in response and len(response['items']) > 0:
        return response['items'][0]['snippet'], response['items'][0]['contentDetails']
    return None, None

def download_video(url, download_path):
    yt = YouTube(url)
    status_updates.append(f"Starting download: {yt.title}")
    logging.info(f"Starting download: {yt.title}")
    stream = yt.streams.filter(progressive=True, file_extension='mp4').first()
    output_file = stream.download(output_path=download_path)
    output_mp3 = output_file.replace('.mp4', '.mp3')
    ffmpeg.input(output_file).output(output_mp3).run()
    os.remove(output_file)
    return output_mp3

def get_mp3_metadata(file_path):
    file_size = os.path.getsize(file_path)
    pub_date = datetime.now(pytz.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")
    title = os.path.basename(file_path).replace('.mp3', '')
    return {
        'title': title,
        'description': f"Episode from {title}",
        'pubDate': pub_date,
        'url': upload_to_s3(file_path, os.getenv('AWS_BUCKET_NAME'), f"podcast/{os.path.basename(file_path)}"),
        'length': file_size
    }

def download_podcast(video_urls, min_duration, download_path, bucket_name, channel_or_playlist_id):
    uploaded_episodes = []
    for video in video_urls:
        try:
            yt = YouTube(video["url"])
            video_duration = yt.length  # in seconds
            if video_duration is None or video_duration < min_duration:
                status_updates.append(f"Skipping video '{yt.title}' as it is shorter than the minimum duration or duration is not available.")
                continue

            snippet, content_details = get_video_details(yt.video_id, os.getenv('API_KEY'))
            if snippet is None or content_details is None:
                status_updates.append(f"Skipping video {video['url']} due to missing details.")
                continue

            mp3_file = download_video(video["url"], download_path)
            file_metadata = get_mp3_metadata(mp3_file)
            status_updates.append(f"Starting upload: {file_metadata['title']}")
            s3_url = upload_to_s3(mp3_file, bucket_name, f"{channel_or_playlist_id}/{os.path.basename(mp3_file)}")
            episode_id = upload_to_buzzsprout(file_metadata['title'], snippet['description'], s3_url)
            if episode_id:
                uploaded_episodes.append({'title': file_metadata['title'], 'episode_id': episode_id})
                status_updates.append(f"Deleting local file: {mp3_file}")
                os.remove(mp3_file)  # Delete local file
            else:
                status_updates.append(f"Failed to upload episode '{file_metadata['title']}' to Buzzsprout.")
        except Exception as e:
            status_updates.append(f"Failed to download video {video['url']} due to error: {e}")

    return uploaded_episodes

@celery_app.task
def download_channel_podcast(channel_url, min_duration):
    with flask_app.app_context():
        global status_updates
        status_updates = []
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
            status_updates.append("Processing started...")
            logging.info("Processing started...")
            uploaded_episodes = download_podcast(video_urls, min_duration, download_path, os.getenv('AWS_BUCKET_NAME'), channel_id)
            status_updates.append(f"Upload complete, {len(uploaded_episodes)} episodes have been uploaded to your Buzzsprout dashboard.")
            logging.info(f"Upload complete, {len(uploaded_episodes)} episodes have been uploaded to your Buzzsprout dashboard.")
            return uploaded_episodes
        except Exception as e:
            status_updates.append(f"Failed to create podcast: {e}")
            logging.error(f"Failed to create podcast: {e}")
            return []

@celery_app.task
def download_playlist_podcast(playlist_url, min_duration):
    with flask_app.app_context():
        global status_updates
        status_updates = []
        try:
            playlist = Playlist(playlist_url)
            playlist_title = playlist.title
            playlist_id = playlist.playlist_id
            download_path = os.path.join("downloaded", playlist_id)
            os.makedirs(download_path, exist_ok=True)

            api_key = os.getenv('API_KEY')
            if not api_key:
                raise ValueError("No API key provided. Please set the API_KEY environment variable.")

            video_urls = get_playlist_videos(playlist_id, api_key)
            status_updates.append("Processing started...")
            logging.info("Processing started...")
            uploaded_episodes = download_podcast(video_urls, min_duration, download_path, os.getenv('AWS_BUCKET_NAME'), playlist_id)
            status_updates.append(f"Upload complete, {len(uploaded_episodes)} episodes have been uploaded to your Buzzsprout dashboard.")
            logging.info(f"Upload complete, {len(uploaded_episodes)} episodes have been uploaded to your Buzzsprout dashboard.")
            return uploaded_episodes
        except Exception as e:
            status_updates.append(f"Failed to create podcast: {e}")
            logging.error(f"Failed to create podcast: {e}")
            return []
