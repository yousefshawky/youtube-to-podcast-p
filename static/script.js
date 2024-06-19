document.addEventListener('DOMContentLoaded', function() {
    const form = document.getElementById('converter-form');
    const startButton = document.getElementById('start-conversion-btn');
    const stopButton = document.getElementById('stop-conversion-btn');
    const statusUpdatesDiv = document.getElementById('status-updates');

    // Socket.IO connection
    const socket = io();

    socket.on('connect', function() {
        console.log('Connected to server');
    });

    socket.on('status_update', function(msg) {
        console.log('Status update:', msg);
        const statusMessage = document.createElement('p');
        statusMessage.textContent = msg.status;
        statusUpdatesDiv.appendChild(statusMessage);
    });

    form.addEventListener('submit', function(event) {
        event.preventDefault();

        const url = document.getElementById('url').value;
        const buzzsproutApiKey = document.getElementById('buzzsprout-api-key').value;
        const buzzsproutPodcastId = document.getElementById('buzzsprout-podcast-id').value;
        const minDurationMinutes = document.getElementById('min-duration-minutes').value;
        const minDurationSeconds = document.getElementById('min-duration-seconds').value;
        const maxDurationMinutes = document.getElementById('max-duration-minutes').value;
        const maxDurationSeconds = document.getElementById('max-duration-seconds').value;
        const titleFilter = document.getElementById('title-filter').value;

        const requestBody = {
            url: url,
            buzzsprout_api_key: buzzsproutApiKey,
            buzzsprout_podcast_id: buzzsproutPodcastId,
            min_duration_minutes: minDurationMinutes || 0,
            min_duration_seconds: minDurationSeconds || 0,
            max_duration_minutes: maxDurationMinutes || 0,
            max_duration_seconds: maxDurationSeconds || 0,
            title_filter: titleFilter || ''
        };

        fetch('/start-conversion', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(requestBody)
        })
        .then(response => {
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            return response.json();
        })
        .then(data => {
            if (data.status === 'started') {
                alert('Conversion started');
                stopButton.style.display = 'block';
            } else {
                alert('Error: ' + data.message);
            }
        })
        .catch(error => {
            console.error('Error:', error);
            alert(`Error: ${error.message}`);
        });
    });

    stopButton.addEventListener('click', function() {
        fetch('/stop-conversion', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            }
        })
        .then(response => {
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            return response.json();
        })
        .then(data => {
            if (data.status === 'stopped') {
                alert('Conversion stopped');
                stopButton.style.display = 'none';
            } else {
                alert('Error: ' + data.message);
            }
        })
        .catch(error => {
            console.error('Error:', error);
            alert(`Error: ${error.message}`);
        });
    });

    const filterMinDurationCheckbox = document.getElementById('filter-min-duration');
    const filterMaxDurationCheckbox = document.getElementById('filter-max-duration');
    const filterTitleCheckbox = document.getElementById('filter-title');

    filterMinDurationCheckbox.addEventListener('change', function() {
        const minDurationInputs = document.getElementById('min-duration-inputs');
        if (this.checked) {
            minDurationInputs.style.display = 'flex';
        } else {
            minDurationInputs.style.display = 'none';
        }
    });

    filterMaxDurationCheckbox.addEventListener('change', function() {
        const maxDurationInputs = document.getElementById('max-duration-inputs');
        if (this.checked) {
            maxDurationInputs.style.display = 'flex';
        } else {
            maxDurationInputs.style.display = 'none';
        }
    });

    filterTitleCheckbox.addEventListener('change', function() {
        const titleFilterInput = document.getElementById('title-filter');
        if (this.checked) {
            titleFilterInput.style.display = 'block';
        } else {
            titleFilterInput.style.display = 'none';
        }
    });
});
