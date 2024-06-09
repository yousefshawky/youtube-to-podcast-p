document.addEventListener('DOMContentLoaded', function() {
    const form = document.getElementById('converter-form');
    const logsContainer = document.getElementById('logs');

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
            body: JSON.stringify({ url: url, min_duration_minutes: minDurationMinutes, min_duration_seconds: minDurationSeconds })
        })
        .then(response => response.json())
        .then(data => {
            console.log(data.status);
            logsContainer.innerHTML = 'Processing...';
            startEventSource();
        })
        .catch(error => console.error('Error:', error));
    });

    function startEventSource() {
        const eventSource = new EventSource('/status-updates');
        eventSource.onmessage = function(event) {
            logsContainer.innerHTML += `<div>${event.data}</div>`;
        };
        eventSource.onerror = function(event) {
            console.error('EventSource failed:', event);
            eventSource.close();
        };
    }
});
