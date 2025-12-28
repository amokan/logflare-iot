"""
A simple module for sending log events to Logflare's HTTP API.
Designed to work with CircuitPython's `adafruit_requests` library.
"""

# Default Logflare API endpoint
LOGFLARE_API_URL = "https://api.logflare.app/logs"


class LogflareClient:
    """A client for sending log events to Logflare."""

    def __init__(self, requests_session, api_key, source_id, api_url=None):
        """
        Initialize the Logflare client.

        Args:
            requests_session: An adafruit_requests.Session object
            api_key: Your Logflare API key
            source_id: The Logflare source UUID
            api_url: Optional custom API URL for self-hosted Logflare
        """
        self._session = requests_session
        base_url = api_url if api_url else LOGFLARE_API_URL
        self._url = f"{base_url}?source={source_id}"
        self._headers = {
            "X-API-KEY": api_key,
            "Content-Type": "application/json",
        }

    def send(self, event_message, metadata=None, timestamp=None):
        """
        Send a log event to Logflare.

        Args:
            event_message: A string describing the event
            metadata: Optional dict of key-value pairs for additional context
            timestamp: Optional ISO 8601 timestamp string (UTC) for the event

        Returns:
            True if the event was sent successfully, False otherwise
        """
        payload = {
            "event_message": event_message,
        }
        if timestamp:
            payload["timestamp"] = timestamp
        if metadata:
            payload["metadata"] = metadata

        response = None
        try:
            response = self._session.post(
                self._url,
                json=payload,
                headers=self._headers,
                timeout=5,
            )
            status = response.status_code
            response.close()
            if status == 200 or status == 201:
                return True
            else:
                print(f"Logflare API error: {status}")
                return False
        except Exception as e:
            print(f"Logflare send failed: {e}")
            if response:
                try:
                    response.close()
                except:
                    pass
            return False
