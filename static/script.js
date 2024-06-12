document.addEventListener('DOMContentLoaded', function() {
    const form = document.getElementById('converter-form');
    const statusDiv = document.getElementById('status');

    const socket = io.connect('http://' + document.domain + ':' + location.port);

    socket.on('connect', function() {
        console.log('WebSocket connected');
    });

    socket.on('disconnect', function() {
        console.log('WebSocket disconnected');
    });

    socket.on('status', function(data) {
        console.log('Status update received:', data);
        const newMessage = document.createElement('p');
        newMessage.innerText = data.message;
        statusDiv.appendChild(newMessage);
    });

    form.addEventListener('submit', function(event) {
        event.preventDefault();

        const url = document.getElementById('url').value;
        const minDurationMinutes = document.getElementById('min-duration-minutes').value;
        const minDurationSeconds = document.getElementById('min-duration-seconds').value;

        fetch('/start-conversion', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                url: url,
                min_duration_minutes: minDurationMinutes,
                min_duration_seconds: minDurationSeconds
            })
        })
        .then(response => response.json())
        .then(data => {
            if (data.status === 'started') {
                const newMessage = document.createElement('p');
                newMessage.innerText = 'Conversion started';
                statusDiv.appendChild(newMessage);
            } else {
                const newMessage = document.createElement('p');
                newMessage.innerText = 'Error: ' + data.message;
                statusDiv.appendChild(newMessage);
            }
        })
        .catch(error => console.error('Error:', error));
    });
});
