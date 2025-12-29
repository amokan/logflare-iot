"""
A simple module for sending log events to Logflare's HTTP API.
Uses raw sockets to avoid adafruit_requests retry behavior.
"""

import json

# Default Logflare API endpoint
LOGFLARE_HOST = "api.logflare.app"
LOGFLARE_PATH = "/logs"


class LogflareClient:
    """A client for sending log events to Logflare."""

    def __init__(self, socket_pool, ssl_context, api_key, source_id, host=None):
        """
        Initialize the Logflare client.

        Args:
            socket_pool: A socketpool.SocketPool object
            ssl_context: An ssl.SSLContext object
            api_key: Your Logflare API key
            source_id: The Logflare source UUID
            host: Optional custom host for self-hosted Logflare
        """
        self._pool = socket_pool
        self._ssl_context = ssl_context
        self._api_key = api_key
        self._host = host if host else LOGFLARE_HOST
        self._path = f"{LOGFLARE_PATH}?source={source_id}"

    def send(self, event_message, metadata=None, timeout=10):
        """
        Send a log event to Logflare.

        Args:
            event_message: A string describing the event
            metadata: Optional dict of key-value pairs for additional context
            timeout: Socket timeout in seconds (default: 10)

        Returns:
            True if the event was sent successfully, False otherwise
        """
        payload = {
            "event_message": event_message,
        }
        if metadata:
            payload["metadata"] = metadata

        body = json.dumps(payload)
        body_bytes = body.encode("utf-8")

        # Build HTTP request
        request = (
            f"POST {self._path} HTTP/1.1\r\n"
            f"Host: {self._host}\r\n"
            f"X-API-KEY: {self._api_key}\r\n"
            f"Content-Type: application/json\r\n"
            f"Content-Length: {len(body_bytes)}\r\n"
            f"Connection: close\r\n"
            f"\r\n"
        )

        sock = None
        try:
            # Create socket and wrap with SSL
            sock = self._pool.socket(self._pool.AF_INET, self._pool.SOCK_STREAM)
            sock.settimeout(timeout)
            sock = self._ssl_context.wrap_socket(sock, server_hostname=self._host)

            # Connect and send
            sock.connect((self._host, 443))
            sock.send(request.encode("utf-8"))
            sock.send(body_bytes)

            # Read response (just need status line)
            response = b""
            while b"\r\n" not in response:
                chunk = sock.recv(64)
                if not chunk:
                    break
                response += chunk

            # Parse status code from "HTTP/1.1 200 OK\r\n..."
            status_line = response.split(b"\r\n")[0].decode("utf-8")
            parts = status_line.split(" ", 2)
            if len(parts) >= 2:
                status = int(parts[1])
                if status == 200 or status == 201:
                    return True
                else:
                    print(f"Logflare API error: {status}")
                    return False
            else:
                print(f"Logflare invalid response: {status_line}")
                return False

        except Exception as e:
            print(f"Logflare send failed: {e}")
            return False
        finally:
            if sock:
                try:
                    sock.close()
                except:
                    pass
