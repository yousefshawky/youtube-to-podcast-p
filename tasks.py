import os
import time
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

app = Celery('tasks', broker='redis://localhost:6379/0', backend='redis://localhost:6379/0')

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
    return s3_url


def delete_from_s3(bucket_name, s3_key):
    s3.delete_object(Bucket=bucket_name, Key=s3_key)
    print(f"Deleted {s3_key} from S3 bucket {bucket_name}")


def is_url_accessible(url):
    try:
        response = requests.head(url)
        return response.status_code == 200
    except requests.RequestException:
        return False


def upload_to_buzzsprout(title, description, file_url):
    if not is_url_accessible(file_url):
        print(f"Failed to upload episode '{title}' to Buzzsprout: URL not accessible")
        return None

    api_key = os.getenv('BUZZSPROUT_API_KEY')
    podcast_id = os.getenv('BUZZSPROUT_PODCAST_ID')
    url = f'https://www.buzzsprout.com/api/{podcast_id}/episodes'
    headers = {
        'Authorization': f'Token token={api_key}',
        'Content-Type': 'application/json',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    description_with_br = description.replace('\n', '<br>')
    data = {
        'title': title,
        'description': description_with_br,
        'audio_url': file_url
    }
    response = requests.post(url, headers=headers, json=data)
    if response.status_code == 201:
        episode_id = response.json()['id']
        print(f"Episode '{title}' uploaded successfully to Buzzsprout with ID {episode_id}.")
        return episode_id
    else:
        print(f"Failed to upload episode '{title}' to Buzzsprout: {response.content}")
        print(f"Audio URL: {file_url}")
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


def get_video_details(video_id, api_key):
    youtube = build('youtube', 'v3', developerKey=api_key)
    request = youtube.videos().list(
        part="snippet,contentDetails",
        id=video_id
    )
    response = request.execute()
    items = response.get('items')
    if not items:
        return None, None
    return items[0]['snippet'], items[0]['contentDetails']




def download_video(url, download_path):
    yt = YouTube(url)
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


def check_episode_processed(episode_id):
    api_key = os.getenv('BUZZSPROUT_API_KEY')
    podcast_id = os.getenv('BUZZSPROUT_PODCAST_ID')
    url = f'https://www.buzzsprout.com/api/{podcast_id}/episodes/{episode_id}'
    headers = {
        'Authorization': f'Token token={api_key}',
        'Content-Type': 'application/json',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        episode_status = response.json().get('status', 'processing')
        return episode_status == 'processing'
    else:
        print(f"Failed to get status for episode {episode_id}: {response.content}")
        return False


@app.task
def download_channel_podcast(channel_url, min_duration):
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

        uploaded_episodes = []

        for video in video_urls:
            try:
                yt = YouTube(video["url"])
                video_duration = yt.length  # in seconds
                if video_duration < min_duration:
                    print(f"Skipping video '{yt.title}' as it is shorter than the minimum duration.")
                    continue

                snippet, content_details = get_video_details(yt.video_id, api_key)
                if snippet is None or content_details is None:
                    print(f"Skipping video {video['url']} due to missing details.")
                    continue

                mp3_file = download_video(video["url"], download_path)
                file_metadata = get_mp3_metadata(mp3_file)
                s3_url = upload_to_s3(mp3_file, os.getenv('AWS_BUCKET_NAME'),
                                      f"{channel_id}/{os.path.basename(mp3_file)}")
                episode_id = upload_to_buzzsprout(file_metadata['title'], snippet['description'], s3_url)

                if episode_id:
                    while not check_episode_processed(episode_id):
                        print(f"Waiting for episode {episode_id} to be processed...")
                        time.sleep(10)  # Delay to avoid hitting the server too frequently

                    uploaded_episodes.append({'title': file_metadata['title'], 'episode_id': episode_id})
                    print(f"Deleting local file: {mp3_file}")
                    os.remove(mp3_file)  # Delete local file
                    delete_from_s3(os.getenv('AWS_BUCKET_NAME'),
                                   f"{channel_id}/{os.path.basename(mp3_file)}")  # Delete from S3
                else:
                    print(f"Failed to upload episode '{file_metadata['title']}' to Buzzsprout.")
            except Exception as e:
                print(f"Failed to download video {video['url']}: {e}")

        print(f"Podcast for channel {channel_name} created successfully.")
        return uploaded_episodes
    except Exception as e:
        print(f"Failed to create podcast: {e}")
        return []


@app.task
def publish_buzzsprout_episode(episode_id):
    api_key = os.getenv('BUZZSPROUT_API_KEY')
    podcast_id = os.getenv('BUZZSPROUT_PODCAST_ID')
    url = f'https://www.buzzsprout.com/api/{podcast_id}/episodes/{episode_id}/publish'
    headers = {
        'Authorization': f'Token token={api_key}',
        'Content-Type': 'application/json',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    response = requests.patch(url, headers=headers)
    if response.status_code == 200:
        print(f"Episode with ID {episode_id} published successfully.")
    else:
        print(f"Failed to publish episode with ID {episode_id}: {response.content}")
