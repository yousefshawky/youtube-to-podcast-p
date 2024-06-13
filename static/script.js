document.addEventListener('DOMContentLoaded', function() {
    const form = document.getElementById('converter-form');
    const statusDiv = document.getElementById('status');

    var socket = io.connect('http://' + document.domain + ':' + location.port);

    socket.on('connect', function() {
        console.log('WebSocket connected');
    });

    socket.on('disconnect', function() {
        console.log('WebSocket disconnected');
    });

    socket.on('reconnect', function() {
        console.log('WebSocket reconnected');
    });

    socket.on('status', function(data) {
        console.log('Status update received:', data); // Log the entire data object
        if (data && data.message) {
            var newMessage = document.createElement('p');
            newMessage.innerText = data.message;
            statusDiv.appendChild(newMessage);
        } else {
            console.error('Invalid status data received:', data);
        }
    });

    form.addEventListener('submit', function(event) {
        event.preventDefault();

        const url = document.getElementById('url').value;
        const filterMinDuration = document.getElementById('filter-min-duration').checked;
        const filterMaxDuration = document.getElementById('filter-max-duration').checked;
        const filterTitle = document.getElementById('filter-title').checked;
        const minDurationMinutes = document.getElementById('min-duration-minutes').value;
        const minDurationSeconds = document.getElementById('min-duration-seconds').value;
        const maxDurationMinutes = document.getElementById('max-duration-minutes').value;
        const maxDurationSeconds = document.getElementById('max-duration-seconds').value;
        const titleFilter = document.getElementById('title-filter').value;

        let requestBody = { url: url };

        if (filterMinDuration) {
            requestBody.min_duration_minutes = parseInt(minDurationMinutes) || 0;
            requestBody.min_duration_seconds = parseInt(minDurationSeconds) || 0;
        }

        if (filterMaxDuration) {
            requestBody.max_duration_minutes = parseInt(maxDurationMinutes) || 0;
            requestBody.max_duration_seconds = parseInt(maxDurationSeconds) || 0;
        }

        if (filterTitle) {
            requestBody.title_filter = titleFilter.toLowerCase();
        }

        fetch('/start-conversion', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(requestBody)
        })
        .then(response => response.json())
        .then(data => {
            if (data.status === 'started') {
                alert('Conversion started');
            } else {
                alert('Error: ' + data.message);
            }
        })
        .catch(error => console.error('Error:', error));
    });

    const filterMinDurationCheckbox = document.getElementById('filter-min-duration');
    filterMinDurationCheckbox.addEventListener('change', function() {
        const minDurationInputs = document.getElementById('min-duration-inputs');
        minDurationInputs.style.display = this.checked ? 'flex' : 'none';
    });

    const filterMaxDurationCheckbox = document.getElementById('filter-max-duration');
    filterMaxDurationCheckbox.addEventListener('change', function() {
        const maxDurationInputs = document.getElementById('max-duration-inputs');
        maxDurationInputs.style.display = this.checked ? 'flex' : 'none';
    });

    const filterTitleCheckbox = document.getElementById('filter-title');
    filterTitleCheckbox.addEventListener('change', function() {
        const titleFilterInput = document.getElementById('title-filter');
        titleFilterInput.style.display = this.checked ? 'block' : 'none';
    });
});
