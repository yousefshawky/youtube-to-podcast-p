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
import redis
from flask_socketio import SocketIO

load_dotenv()

celery_app = Celery('tasks', broker='redis://localhost:6379/0', backend='redis://localhost:6379/0')

# Redis client
redis_client = redis.StrictRedis(host='localhost', port=6379, db=0)

# SSL context for requests
ssl_context = ssl.create_default_context(cafile=certifi.where())

# Setup logging
logging.basicConfig(filename='logfile.log', level=logging.INFO, format='%(message)s')

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
    return description.replace('\n', '<br>\n')

def upload_to_buzzsprout(title, description, file_url):
    if not is_url_accessible(file_url):
        logging.info(f"Failed to upload episode '{title}' to Buzzsprout: URL not accessible")
        emit_status(f"Failed to upload episode '{title}' to Buzzsprout: URL not accessible")
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
        logging.info(f"Episode '{title}' uploaded successfully to Buzzsprout.")
        emit_status(f"Episode '{title}' uploaded successfully to Buzzsprout.")
        return response.json().get('id')
    else:
        logging.info(f"Failed to upload episode '{title}' to Buzzsprout: {response.content}")
        emit_status(f"Failed to upload episode '{title}' to Buzzsprout: {response.content}")
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
        part="snippet",
        playlistId=playlist_id,
        maxResults=50
    )
    response = request.execute()
    video_urls = [{"url": "https://www.youtube.com/watch?v=" + item['snippet']['resourceId']['videoId'],
                   "description": item['snippet']['description']} for item in response['items']]
    return video_urls

def emit_status(message):
    logging.info(f"Emitting status: {message}")
    redis_client.publish('status_updates', message)

@celery_app.task(bind=True)
def download_channel_podcast(self, url, min_duration):
    try:
        channel = Channel(url)
        channel_name = channel.channel_name
        channel_id = channel.channel_id
        download_path = os.path.join("downloaded", channel_id)
        os.makedirs(download_path, exist_ok=True)

        api_key = os.getenv('API_KEY')
        if not api_key:
            raise ValueError("No API key provided. Please set the API_KEY environment variable.")

        video_urls = get_channel_videos(channel_id, api_key)
        emit_status('Download started for channel')
        logging.info("Processing started...")
        uploaded_episodes = []

        for video in video_urls:
            try:
                yt = YouTube(video["url"])
                video_duration = yt.length
                if video_duration is None or video_duration < min_duration:
                    logging.info(f"Skipping video '{yt.title}' as it is shorter than the minimum duration or duration is not available.")
                    emit_status(f"Skipping video '{yt.title}' as it is shorter than the minimum duration or duration is not available.")
                    continue

                logging.info(f"Downloading video: {yt.title}")
                emit_status(f"Downloading video: {yt.title}")
                yt.streams.filter(only_audio=True).first().download(output_path=download_path, filename=f'{yt.title}.mp3')
                file_path = os.path.join(download_path, f'{yt.title}.mp3')

                logging.info(f"Uploading video: {yt.title}")
                emit_status(f"Uploading video: {yt.title}")
                s3_url = upload_to_s3(file_path, os.getenv('AWS_BUCKET_NAME'), f'podcasts/{yt.title}.mp3')
                buzzsprout_id = upload_to_buzzsprout(yt.title, yt.description, s3_url)
                logging.info(f"Video {yt.title} uploaded with ID {buzzsprout_id}")
                emit_status(f"Video {yt.title} uploaded with ID {buzzsprout_id}")
                uploaded_episodes.append({'title': yt.title, 'episode_id': buzzsprout_id})
                os.remove(file_path)
            except Exception as e:
                logging.info(f"Failed to download video {video['url']} due to error: {e}")
                emit_status(f"Failed to download video {video['url']} due to error: {e}")

        logging.info(f"Upload complete, {len(uploaded_episodes)} episodes have been uploaded to your Buzzsprout dashboard.")
        emit_status(f"Upload complete, {len(uploaded_episodes)} episodes have been uploaded to your Buzzsprout dashboard.")
        return uploaded_episodes
    except Exception as e:
        logging.info(f"Error processing channel: {e}")
        emit_status(f"Error processing channel: {e}")
        return []

@celery_app.task(bind=True)
def download_playlist_podcast(self, url, min_duration):
    try:
        playlist = Playlist(url)
        playlist_id = playlist.playlist_id
        playlist_title = playlist.title
        download_path = os.path.join("downloaded", playlist_id)
        os.makedirs(download_path, exist_ok=True)

        api_key = os.getenv('API_KEY')
        if not api_key:
            raise ValueError("No API key provided. Please set the API_KEY environment variable.")

        video_urls = get_playlist_videos(playlist_id, api_key)
        emit_status('Download started for playlist')
        logging.info("Processing started...")
        uploaded_episodes = []

        for video in video_urls:
            try:
                yt = YouTube(video["url"])
                video_duration = yt.length
                if video_duration is None or video_duration < min_duration:
                    logging.info(f"Skipping video '{yt.title}' as it is shorter than the minimum duration or duration is not available.")
                    emit_status(f"Skipping video '{yt.title}' as it is shorter than the minimum duration or duration is not available.")
                    continue

                logging.info(f"Downloading video: {yt.title}")
                emit_status(f"Downloading video: {yt.title}")
                yt.streams.filter(only_audio=True).first().download(output_path=download_path, filename=f'{yt.title}.mp3')
                file_path = os.path.join(download_path, f'{yt.title}.mp3')

                logging.info(f"Uploading video: {yt.title}")
                emit_status(f"Uploading video: {yt.title}")
                s3_url = upload_to_s3(file_path, os.getenv('AWS_BUCKET_NAME'), f'podcasts/{yt.title}.mp3')
                buzzsprout_id = upload_to_buzzsprout(yt.title, yt.description, s3_url)
                logging.info(f"Video {yt.title} uploaded with ID {buzzsprout_id}")
                emit_status(f"Video {yt.title} uploaded with ID {buzzsprout_id}")
                uploaded_episodes.append({'title': yt.title, 'episode_id': buzzsprout_id})
                os.remove(file_path)
            except Exception as e:
                logging.info(f"Failed to download video {video['url']} due to error: {e}")
                emit_status(f"Failed to download video {video['url']} due to error: {e}")

        logging.info(f"Upload complete, {len(uploaded_episodes)} episodes have been uploaded to your Buzzsprout dashboard.")
        emit_status(f"Upload complete, {len(uploaded_episodes)} episodes have been uploaded to your Buzzsprout dashboard.")
        return uploaded_episodes
    except Exception as e:
        logging.info(f"Error processing playlist: {e}")
        emit_status(f"Error processing playlist: {e}")
        return []
