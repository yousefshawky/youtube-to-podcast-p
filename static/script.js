document.getElementById('download-form').addEventListener('submit', function (event) {
    event.preventDefault();

    const channelUrl = document.getElementById('channel-url').value;
    const minDurationMinutes = parseInt(document.getElementById('min-duration-minutes').value, 10) || 0;
    const minDurationSeconds = parseInt(document.getElementById('min-duration-seconds').value, 10) || 0;
    const minDuration = (minDurationMinutes * 60) + minDurationSeconds;

    fetch('/download', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({
            channel_url: channelUrl,
            min_duration: minDuration,
        }),
    })
    .then(response => response.json())
    .then(data => {
        const statusDiv = document.getElementById('status');
        statusDiv.innerHTML = `Task ID: ${data.task_id}<br>Status: ${data.status}`;
    })
    .catch((error) => {
        console.error('Error:', error);
    });
});
