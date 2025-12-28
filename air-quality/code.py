import gc
import os
import ssl
import time

import adafruit_requests
import board
import busio
import displayio
import socketpool
import terminalio
import wifi
from adafruit_display_text import label
from adafruit_pm25.i2c import PM25_I2C
from logflare import LogflareClient

# Optional NTP support for device-side timestamps
try:
    import adafruit_ntp
    NTP_AVAILABLE = True
except ImportError:
    NTP_AVAILABLE = False

# Load environment variables into globals at startup
WIFI_SSID = os.getenv("CIRCUITPY_WIFI_SSID")
WIFI_PASSWORD = os.getenv("CIRCUITPY_WIFI_PASSWORD")
LOGFLARE_API_KEY = os.getenv("LOGFLARE_API_KEY")
LOGFLARE_SOURCE_ID = os.getenv("LOGFLARE_SOURCE_ID")
DEVICE_LOCATION = os.getenv("DEVICE_LOCATION", "default")
DEVICE_ENVIRONMENT = os.getenv("DEVICE_ENVIRONMENT", "indoor")
DISPLAY_UNITS = os.getenv("DISPLAY_UNITS", "imperial")
READING_INTERVAL = int(os.getenv("READING_INTERVAL", "10"))
ENABLE_SPA06 = os.getenv("ENABLE_SPA06", "false").lower() == "true"

# Determine which sensor readings to use based on environment
USE_ENV_READINGS = DEVICE_ENVIRONMENT == "outdoor"

# Conditionally import SPA06-003 library
if ENABLE_SPA06:
    from adafruit_spa06_003 import SPA06_003


def get_air_quality(pm25_value):
    """Return status string and color based on PM2.5 value."""
    if pm25_value <= 12:
        return "Excellent", 0x00FF00
    elif pm25_value <= 35:
        return "Good", 0xFFFF00
    elif pm25_value <= 55:
        return "Moderate", 0xFF8800
    elif pm25_value <= 150:
        return "Unhealthy", 0xFF0000
    else:
        return "Hazardous", 0xFF00FF


def celsius_to_fahrenheit(celsius):
    """Convert Celsius to Fahrenheit."""
    return (celsius * 9 / 5) + 32


def get_iso_timestamp(ntp):
    """Get current time as ISO 8601 string from NTP."""
    try:
        dt = ntp.datetime
        return f"{dt.tm_year}-{dt.tm_mon:02d}-{dt.tm_mday:02d}T{dt.tm_hour:02d}:{dt.tm_min:02d}:{dt.tm_sec:02d}Z"
    except Exception:
        return None


def hpa_to_inhg(hpa):
    """Convert hectopascals to inches of mercury."""
    return hpa * 0.02953


def create_display_group():
    """Create the display group with text labels."""
    group = displayio.Group()

    # Location label (top)
    location_label = label.Label(
        terminalio.FONT,
        text=f"Location: {DEVICE_LOCATION}",
        color=0xFFFFFF,
        x=5,
        y=8,
    )
    group.append(location_label)

    # WiFi status label
    wifi_label = label.Label(
        terminalio.FONT,
        text="WiFi: ---",
        color=0xFFFFFF,
        x=5,
        y=20,
    )
    group.append(wifi_label)

    # PM2.5 value label (large)
    pm25_label = label.Label(
        terminalio.FONT,
        text="PM2.5: ---",
        color=0xFFFFFF,
        scale=2,
        x=5,
        y=38,
    )
    group.append(pm25_label)

    # Air quality status label
    status_label = label.Label(
        terminalio.FONT,
        text="---",
        color=0xFFFFFF,
        scale=2,
        x=5,
        y=60,
    )
    group.append(status_label)

    # Temperature label
    temp_label = label.Label(
        terminalio.FONT,
        text="",
        color=0x00FFFF,
        x=5,
        y=85,
    )
    group.append(temp_label)

    # Pressure label
    pressure_label = label.Label(
        terminalio.FONT,
        text="",
        color=0x00FFFF,
        x=5,
        y=97,
    )
    group.append(pressure_label)

    return group, wifi_label, pm25_label, status_label, temp_label, pressure_label


def update_wifi_status(wifi_label, connected, ssid=None):
    """Update the WiFi status label."""
    if connected and ssid:
        wifi_label.text = f"WiFi: {ssid}"
        wifi_label.color = 0x00FF00
    else:
        wifi_label.text = "WiFi: Disconnected"
        wifi_label.color = 0xFF0000


def update_air_quality_display(pm25_label, status_label, pm25_value):
    """Update the air quality display labels."""
    status_text, color = get_air_quality(pm25_value)
    pm25_label.text = f"PM2.5: {pm25_value}"
    pm25_label.color = color
    status_label.text = status_text
    status_label.color = color


def update_environment_display(temp_label, pressure_label, temp_c, pressure_hpa):
    """Update the temperature and pressure display labels based on DISPLAY_UNITS."""
    if temp_c is not None:
        if DISPLAY_UNITS == "metric":
            temp_label.text = f"Temp: {temp_c:.1f} C"
        else:
            temp_f = celsius_to_fahrenheit(temp_c)
            temp_label.text = f"Temp: {temp_f:.1f} F"
    else:
        temp_label.text = ""

    if pressure_hpa is not None:
        if DISPLAY_UNITS == "metric":
            pressure_label.text = f"Pressure: {pressure_hpa:.1f} hPa"
        else:
            pressure_inhg = hpa_to_inhg(pressure_hpa)
            pressure_label.text = f"Pressure: {pressure_inhg:.2f} inHg"
    else:
        pressure_label.text = ""


def show_error(display, message):
    """Show an error message on the display."""
    group = displayio.Group()
    error_label = label.Label(
        terminalio.FONT,
        text=message,
        color=0xFF0000,
        x=5,
        y=60,
    )
    group.append(error_label)
    display.root_group = group


def connect_wifi(wifi_label=None):
    """
    Connect to WiFi with retry logic.
    Returns True if connected, False otherwise.
    """
    max_attempts = 3
    for attempt in range(max_attempts):
        try:
            if not wifi.radio.connected:
                print(f"Connecting to {WIFI_SSID} (attempt {attempt + 1})")
                wifi.radio.connect(WIFI_SSID, WIFI_PASSWORD)
            if wifi.radio.connected:
                print(f"Connected to {WIFI_SSID}")
                print(f"IP address: {wifi.radio.ipv4_address}")
                if wifi_label:
                    update_wifi_status(wifi_label, True, WIFI_SSID)
                return True
        except Exception as e:
            print(f"WiFi connection failed: {e}")
            if wifi_label:
                update_wifi_status(wifi_label, False)
            time.sleep(2 ** attempt)  # Exponential backoff
    return False


def main():
    # Display setup
    display = board.DISPLAY
    display.rotation = 0

    # Create display elements
    group, wifi_label, pm25_label, status_label, temp_label, pressure_label = create_display_group()
    display.root_group = group

    # Check for required configuration
    if not WIFI_SSID or not WIFI_PASSWORD:
        show_error(display, "WiFi not configured")
        return

    if not LOGFLARE_API_KEY or not LOGFLARE_SOURCE_ID:
        show_error(display, "Logflare not configured")
        return

    # Initial WiFi connection
    print(f"MAC address: {[hex(i) for i in wifi.radio.mac_address]}")
    if not connect_wifi(wifi_label):
        show_error(display, "WiFi connection failed")
        return

    # Setup HTTP session and NTP
    pool = socketpool.SocketPool(wifi.radio)
    ssl_context = ssl.create_default_context()
    requests = adafruit_requests.Session(pool, ssl_context)

    # Initialize NTP for device-side timestamps (optional)
    ntp = None
    if NTP_AVAILABLE:
        try:
            ntp = adafruit_ntp.NTP(pool, tz_offset=0)
            print(f"NTP time: {get_iso_timestamp(ntp)}")
        except Exception as e:
            print(f"NTP init failed: {e}")

    # Initialize Logflare client
    logflare = LogflareClient(
        requests_session=requests,
        api_key=LOGFLARE_API_KEY,
        source_id=LOGFLARE_SOURCE_ID,
    )

    # I2C bus setup (shared by sensors)
    i2c = busio.I2C(board.SCL, board.SDA, frequency=100000)

    # PM2.5 sensor setup
    pm25_sensor = PM25_I2C(i2c, None)

    # Optional SPA06-003 temperature/pressure sensor
    spa06_sensor = None
    if ENABLE_SPA06:
        try:
            spa06_sensor = SPA06_003.over_i2c(i2c)
            print("SPA06-003 sensor initialized")
        except Exception as e:
            print(f"SPA06-003 init failed: {e}")

    # Log device startup
    startup_metadata = {
        "config": {
            "wifi_ssid": WIFI_SSID,
            "device_location": DEVICE_LOCATION,
            "device_environment": DEVICE_ENVIRONMENT,
            "reading_interval": READING_INTERVAL,
            "display_units": DISPLAY_UNITS,
            "spa06_enabled": ENABLE_SPA06,
        },
    }
    startup_time = get_iso_timestamp(ntp) if ntp else None
    if startup_time:
        startup_metadata["device_timestamp"] = startup_time
    logflare.send(f"Air quality device starting in '{DEVICE_LOCATION}'", startup_metadata, timestamp=startup_time)
    print("Starting air quality monitoring...")

    # Sequence number to track duplicate requests
    seq = 0

    while True:
        loop_start = time.monotonic()

        # Check WiFi connection and reconnect if needed
        if not wifi.radio.connected:
            update_wifi_status(wifi_label, False)
            if not connect_wifi(wifi_label):
                time.sleep(READING_INTERVAL)
                gc.collect()
                continue

        # Read air quality data
        try:
            aq_data = pm25_sensor.read()
        except RuntimeError as e:
            print(f"Sensor read failed: {e}")
            time.sleep(READING_INTERVAL)
            gc.collect()
            continue

        # Select readings based on environment setting
        suffix = " env" if USE_ENV_READINGS else " standard"
        pm10_val = aq_data["pm10" + suffix]   # PM1.0
        pm25_val = aq_data["pm25" + suffix]   # PM2.5
        pm100_val = aq_data["pm100" + suffix]  # PM10.0

        # Update display
        update_air_quality_display(pm25_label, status_label, pm25_val)

        # Get status for logging
        status_text, _ = get_air_quality(pm25_val)

        # Read temperature/pressure if SPA06 is enabled
        temperature = None
        pressure = None
        if spa06_sensor:
            try:
                if spa06_sensor.temperature_data_ready and spa06_sensor.pressure_data_ready:
                    temperature = spa06_sensor.temperature
                    pressure = spa06_sensor.pressure
            except Exception as e:
                print(f"SPA06 read failed: {e}")

        # Update environment display
        update_environment_display(temp_label, pressure_label, temperature, pressure)

        # Send to Logflare
        event_message = f"Air quality reading from '{DEVICE_LOCATION}'"
        metadata = {
            "location": DEVICE_LOCATION,
            "status": status_text,
            "pm10": pm10_val,    # PM1.0
            "pm25": pm25_val,    # PM2.5
            "pm100": pm100_val,  # PM10.0
            "particles_03um": aq_data["particles 03um"],
            "particles_05um": aq_data["particles 05um"],
            "particles_10um": aq_data["particles 10um"],
            "particles_25um": aq_data["particles 25um"],
            "particles_50um": aq_data["particles 50um"],
            "particles_100um": aq_data["particles 100um"],
            "config": {
                "wifi_ssid": WIFI_SSID,
                "device_location": DEVICE_LOCATION,
                "device_environment": DEVICE_ENVIRONMENT,
                "reading_interval": READING_INTERVAL,
                "display_units": DISPLAY_UNITS,
                "spa06_enabled": ENABLE_SPA06,
            },
        }

        # Add device timestamp if NTP available
        device_time = get_iso_timestamp(ntp) if ntp else None
        if device_time:
            metadata["device_timestamp"] = device_time

        # Add sequence number to track duplicates
        seq += 1
        metadata["http_seq_id"] = seq

        # Add temperature/pressure if available
        if temperature is not None:
            metadata["temperature_c"] = round(temperature, 1)
            metadata["temperature_f"] = round(celsius_to_fahrenheit(temperature), 1)
        if pressure is not None:
            metadata["pressure_hpa"] = round(pressure, 1)
            metadata["pressure_inhg"] = round(hpa_to_inhg(pressure), 2)

        if logflare.send(event_message, metadata, timestamp=device_time):
            print(f"Logged: PM2.5={pm25_val} ({status_text})")
        else:
            print("Failed to send to Logflare")

        # Sleep for remaining time to maintain consistent intervals
        elapsed = time.monotonic() - loop_start
        sleep_time = max(0, READING_INTERVAL - elapsed)
        print(f"Loop took {elapsed:.2f}s, sleeping {sleep_time:.2f}s")
        if sleep_time > 0:
            time.sleep(sleep_time)
        gc.collect()


main()
