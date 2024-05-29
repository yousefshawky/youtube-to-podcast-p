import os
import certifi
import ssl
import urllib.request
from pytube import Channel, YouTube
import ffmpeg

# Create an SSL context using certifi
ssl_context = ssl.create_default_context(cafile=certifi.where())

# Custom get function to use the SSL context and decode the response
def custom_get(url, headers=None, timeout=None):
    if headers is None:
        headers = {}
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, context=ssl_context, timeout=timeout) as response:
        return response.read().decode('utf-8')

# Patch pytube's request handling to use the custom_get function
from pytube import request
request.get = custom_get

def download_video(url, download_path):
    yt = YouTube(url)
    stream = yt.streams.filter(progressive=True, file_extension='mp4').first()
    output_file = stream.download(output_path=download_path)
    output_mp3 = output_file.replace('.mp4', '.mp3')
    ffmpeg.input(output_file).output(output_mp3).run()
    os.remove(output_file)
    return output_mp3

def download_channel_videos(channel_url, download_path):
    os.makedirs(download_path, exist_ok=True)

    print(f"Channel URL: {channel_url}")
    print(f"Fetching videos from channel...")

    try:
        channel = Channel(channel_url)
        # Fetch and print channel details
        channel_name = channel.channel_name
        channel_id = channel.channel_id
        channel_url = channel.channel_url

        print(f"Channel Name: {channel_name}")
        print(f"Channel ID: {channel_id}")
        print(f"Channel URL: {channel_url}")

        # Fetch video URLs
        video_urls = [video.watch_url for video in channel.videos]
        print(f"Number of videos found: {len(video_urls)}")
        print(f"Video URLs: {video_urls}")

        for video_url in video_urls:
            print(f'Downloading: {video_url}')
            try:
                download_video(video_url, download_path)
            except Exception as e:
                print(f"Failed to download video {video_url}: {e}")

    except Exception as e:
        print(f"Failed to create Channel object: {e}")
        return

def list_downloaded_mp3s(download_path):
    print("Downloaded MP3 files:")
    if not os.path.exists(download_path):
        print(f"The directory {download_path} does not exist.")
        return
    for file in os.listdir(download_path):
        if file.endswith(".mp3"):
            print(file)

if __name__ == "__main__":
    channel_url = "https://www.youtube.com/channel/UCE6xj743OtZ1OiqCYdRbJzQ"  # Use the channel URL without "/videos"
    download_path = "/Users/yousefshawky/Desktop/downloaded-videos"
    download_channel_videos(channel_url, download_path)
    list_downloaded_mp3s(download_path)
