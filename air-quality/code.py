import gc
import os
import ssl
import time

import board
import busio
import displayio
import socketpool
import terminalio
import wifi
from adafruit_display_text import label
from adafruit_pm25.i2c import PM25_I2C
from logflare import LogflareClient

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

# Display colors
COLOR_WHITE = 0xFFFFFF
COLOR_GRAY = 0x888888
COLOR_GRAY_LIGHT = 0xAAAAAA
COLOR_CYAN = 0x00FFFF
COLOR_GREEN = 0x00FF00
COLOR_YELLOW = 0xFFFF00
COLOR_ORANGE = 0xFF8800
COLOR_RED = 0xFF0000
COLOR_MAGENTA = 0xFF00FF


def get_air_quality(pm25_value):
    """Return status string and color based on PM2.5 value."""
    if pm25_value <= 12:
        return "Excellent", COLOR_GREEN
    elif pm25_value <= 35:
        return "Good", COLOR_YELLOW
    elif pm25_value <= 55:
        return "Moderate", COLOR_ORANGE
    elif pm25_value <= 150:
        return "Unhealthy", COLOR_RED
    else:
        return "Hazardous", COLOR_MAGENTA


def celsius_to_fahrenheit(celsius):
    """Convert Celsius to Fahrenheit."""
    return (celsius * 9 / 5) + 32


def hpa_to_inhg(hpa):
    """Convert hectopascals to inches of mercury."""
    return hpa * 0.02953


def pressure_to_altitude(hpa, sea_level_hpa=1013.25):
    """Estimate altitude in meters from pressure using barometric formula."""
    return 44330 * (1 - (hpa / sea_level_hpa) ** 0.1903)


def truncate_text(text, max_length):
    """Truncate text to max_length, adding ellipsis if needed."""
    if len(text) <= max_length:
        return text
    return text[: max_length - 1] + "."


def create_display_group():
    """Create the display group with text labels."""
    main_group = displayio.Group()

    # Location label (top left, truncated)
    location_text = truncate_text(DEVICE_LOCATION, 18)
    location_label = label.Label(
        terminalio.FONT,
        text=f"Loc: {location_text}",
        color=COLOR_WHITE,
        x=5,
        y=8,
    )
    main_group.append(location_label)

    # Environment label (top right)
    # "outdoor" is 7 chars * 6px = 42px, position so it ends near right edge
    env_label = label.Label(
        terminalio.FONT,
        text=DEVICE_ENVIRONMENT,
        color=COLOR_GRAY,
        x=195,
        y=8,
    )
    main_group.append(env_label)

    # WiFi status label
    wifi_label = label.Label(
        terminalio.FONT,
        text="WiFi: ---",
        color=COLOR_WHITE,
        x=5,
        y=20,
    )
    main_group.append(wifi_label)

    # Air quality status label (moved above PM2.5)
    status_label = label.Label(
        terminalio.FONT,
        text="---",
        color=COLOR_WHITE,
        scale=2,
        x=5,
        y=36,
    )
    main_group.append(status_label)

    # PM2.5 label (static)
    pm25_text_label = label.Label(
        terminalio.FONT,
        text="PM2.5:",
        color=COLOR_WHITE,
        scale=2,
        x=5,
        y=62,
    )
    main_group.append(pm25_text_label)

    # PM2.5 value (dynamic, colored by status)
    pm25_label = label.Label(
        terminalio.FONT,
        text="----",
        color=COLOR_WHITE,
        scale=2,
        x=77,  # After "PM2.5:" (6 chars * 12px at scale=2)
        y=62,
    )
    main_group.append(pm25_label)

    # PM1.0 and PM10 labels - same x position, values right-aligned with 1um
    # Both 11 chars total (66px) to end at x=227, start at x=161
    pm10_label = label.Label(
        terminalio.FONT,
        text="PM1.0:-----",
        color=COLOR_WHITE,
        x=161,
        y=56,
    )
    main_group.append(pm10_label)

    pm100_label = label.Label(
        terminalio.FONT,
        text=" PM10:-----",  # Leading space to match PM1.0 width
        color=COLOR_WHITE,
        x=161,
        y=68,
    )
    main_group.append(pm100_label)

    # Particle counts label (y=92 adds breathing room above)
    particles_label = label.Label(
        terminalio.FONT,
        text="",
        color=COLOR_WHITE,
        x=5,
        y=92,
    )
    main_group.append(particles_label)

    # Temperature and pressure labels (only if SPA06 enabled)
    temp_value_label = None
    pressure_value_label = None
    if ENABLE_SPA06:
        temp_text_label = label.Label(
            terminalio.FONT,
            text="Temp:",
            color=COLOR_GRAY,
            x=5,
            y=120,
        )
        main_group.append(temp_text_label)

        temp_value_label = label.Label(
            terminalio.FONT,
            text="",
            color=COLOR_WHITE,
            x=35,  # After "Temp:" (5 chars * 6px)
            y=120,
        )
        main_group.append(temp_value_label)

        pressure_text_label = label.Label(
            terminalio.FONT,
            text="| Pres:",
            color=COLOR_GRAY,
            x=100,
            y=120,
        )
        main_group.append(pressure_text_label)

        pressure_value_label = label.Label(
            terminalio.FONT,
            text="",
            color=COLOR_WHITE,
            x=142,  # After "| Pres:" (7 chars * 6px)
            y=120,
        )
        main_group.append(pressure_value_label)

    return (
        main_group,
        wifi_label,
        pm25_label,
        pm10_label,
        pm100_label,
        status_label,
        particles_label,
        temp_value_label,
        pressure_value_label,
    )


def update_wifi_status(wifi_label, connected, ssid=None):
    """Update the WiFi status label."""
    if connected and ssid:
        wifi_label.text = f"WiFi: {ssid}"
        wifi_label.color = COLOR_WHITE
    else:
        wifi_label.text = "WiFi: Disconnected"
        wifi_label.color = COLOR_RED


def update_air_quality_display(
    pm25_label, pm10_label, pm100_label, status_label, particles_label, aq_data
):
    """Update all air quality display labels."""
    pm25_val = aq_data["pm25"]
    pm10_val = aq_data["pm10"]
    pm100_val = aq_data["pm100"]

    status_text, color = get_air_quality(pm25_val)

    # Main PM2.5 value (fixed width)
    pm25_label.text = f"{pm25_val:>4}"
    pm25_label.color = color

    # Status text (fixed width)
    status_label.text = f"{status_text:<9}"
    status_label.color = color

    # PM1.0 and PM10 (5-digit values, right-aligned with 1um)
    pm10_label.text = f"PM1.0:{pm10_val:>5}"
    pm100_label.text = f" PM10:{pm100_val:>5}"

    # Particle counts (left-aligned values, spaced out)
    p03 = aq_data["particles_03um"]
    p05 = aq_data["particles_05um"]
    p10 = aq_data["particles_10um"]
    particles_label.text = f"0.3um: {p03:<5}  0.5um: {p05:<5}  1um: {p10:<5}"

    return status_text


def show_aq_read_error(pm25_label, pm10_label, pm100_label, status_label, particles_label):
    """Update display to show air quality sensor read error."""
    pm25_label.text = " ERR"
    pm25_label.color = COLOR_RED

    status_label.text = "Read Fail"
    status_label.color = COLOR_RED

    pm10_label.text = "PM1.0:-----"
    pm100_label.text = " PM10:-----"

    particles_label.text = "0.3um: -----  0.5um: -----  1um: -----"


def update_environment_display(temp_value_label, pressure_value_label, temp_c, pressure_hpa):
    """Update the temperature and pressure value labels (if labels exist)."""
    if temp_value_label is None or pressure_value_label is None:
        return

    if temp_c is not None:
        if DISPLAY_UNITS == "metric":
            temp_value_label.text = f"{temp_c:>5.1f}C"
        else:
            temp_f = celsius_to_fahrenheit(temp_c)
            temp_value_label.text = f"{temp_f:>5.1f}F"
    else:
        temp_value_label.text = "-----"

    if pressure_hpa is not None:
        if DISPLAY_UNITS == "metric":
            pressure_value_label.text = f"{pressure_hpa:>6.0f}hPa"
        else:
            pressure_inhg = hpa_to_inhg(pressure_hpa)
            pressure_value_label.text = f"{pressure_inhg:>5.2f}inHg"
    else:
        pressure_value_label.text = "-----"


def show_error(display, message):
    """Show an error message on the display."""
    group = displayio.Group()
    error_label = label.Label(
        terminalio.FONT,
        text=message,
        color=COLOR_RED,
        x=5,
        y=60,
    )
    group.append(error_label)
    display.root_group = group


def validate_source_id(source_id):
    """Basic validation that source_id looks like a UUID (hex characters, proper length)."""
    if not source_id:
        return False
    # Remove hyphens for length check
    clean_id = source_id.replace("-", "")
    # UUID should be 32 hex chars (without hyphens) or 36 with hyphens
    if len(clean_id) != 32:
        return False
    # Check all characters are valid hex
    try:
        int(clean_id, 16)
        return True
    except ValueError:
        return False


def aq_sensor_warmup(display, seconds=30):
    """Display warm-up message and wait for air quality sensor to stabilize."""
    group = displayio.Group()

    title_label = label.Label(
        terminalio.FONT,
        text="AQ Sensor",
        color=COLOR_YELLOW,
        scale=2,
        x=5,
        y=25,
    )
    group.append(title_label)

    subtitle_label = label.Label(
        terminalio.FONT,
        text="Warm-up",
        color=COLOR_YELLOW,
        scale=2,
        x=5,
        y=50,
    )
    group.append(subtitle_label)

    status_label = label.Label(
        terminalio.FONT,
        text="Please wait...",
        color=COLOR_WHITE,
        x=5,
        y=75,
    )
    group.append(status_label)

    countdown_label = label.Label(
        terminalio.FONT,
        text="",
        color=COLOR_CYAN,
        scale=2,
        x=5,
        y=105,
    )
    group.append(countdown_label)

    display.root_group = group

    print(f"Air quality sensor warm-up: waiting {seconds} seconds...")
    for remaining in range(seconds, 0, -1):
        countdown_label.text = f"{remaining}s"
        time.sleep(1)
    print("Air quality sensor warm-up complete")


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
    (
        main_group,
        wifi_label,
        pm25_label,
        pm10_label,
        pm100_label,
        status_label,
        particles_label,
        temp_value_label,
        pressure_value_label,
    ) = create_display_group()
    display.root_group = main_group

    # Check for required configuration
    if not WIFI_SSID or not WIFI_PASSWORD:
        show_error(display, "WiFi not configured")
        return

    if not LOGFLARE_API_KEY:
        show_error(display, "Logflare API key\nnot configured")
        return

    if not validate_source_id(LOGFLARE_SOURCE_ID):
        show_error(display, "Invalid Logflare\nSource ID")
        return

    # Initial WiFi connection
    device_mac = ":".join(f"{b:02x}" for b in wifi.radio.mac_address)
    print(f"MAC address: {device_mac}")
    if not connect_wifi(wifi_label):
        show_error(display, "WiFi connection failed")
        return

    # Setup socket pool and SSL context
    pool = socketpool.SocketPool(wifi.radio)
    ssl_context = ssl.create_default_context()

    # Initialize Logflare client
    logflare = LogflareClient(
        socket_pool=pool,
        ssl_context=ssl_context,
        api_key=LOGFLARE_API_KEY,
        source_id=LOGFLARE_SOURCE_ID,
    )

    # I2C bus setup (shared by sensors)
    i2c = busio.I2C(board.SCL, board.SDA, frequency=100000)

    # PM2.5 sensor setup
    pm25_sensor = PM25_I2C(i2c, None)

    # Optional SPA06-003 temperature/pressure sensor (init before warmup so it's ready)
    spa06_sensor = None
    if ENABLE_SPA06:
        try:
            spa06_sensor = SPA06_003.over_i2c(i2c)
            print("SPA06-003 sensor initialized")
        except Exception as e:
            print(f"SPA06-003 init failed: {e}")

    # Log device startup before warmup so we know the device came online
    startup_metadata = {
        "level": "debug",
        "mac_address": device_mac,
        "location": DEVICE_LOCATION,
        "config": {
            "wifi_ssid": WIFI_SSID,
            "device_location": DEVICE_LOCATION,
            "device_environment": DEVICE_ENVIRONMENT,
            "reading_interval": READING_INTERVAL,
            "display_units": DISPLAY_UNITS,
            "spa06_enabled": ENABLE_SPA06,
        },
    }
    logflare.send(f"Air quality device starting in '{DEVICE_LOCATION}'", startup_metadata)
    print("Starting air quality monitoring...")

    # Air quality sensor warm-up period for accurate readings
    aq_sensor_warmup(display, seconds=30)

    # Restore main display group after warmup
    display.root_group = main_group

    while True:
        loop_start = time.monotonic()

        # Check WiFi connection and reconnect if needed
        if not wifi.radio.connected:
            update_wifi_status(wifi_label, False)
            if not connect_wifi(wifi_label):
                time.sleep(READING_INTERVAL)
                gc.collect()
                continue

        # Read air quality data (with one retry for transient errors)
        aq_data = None
        last_error = None
        for attempt in range(2):
            try:
                aq_data = pm25_sensor.read()
                break
            except RuntimeError as e:
                last_error = e
                if attempt == 0:
                    print(f"Sensor read failed (retrying): {e}")
                    time.sleep(0.5)

        if aq_data is None:
            print(f"Sensor read failed after retry: {last_error}")
            show_aq_read_error(
                pm25_label, pm10_label, pm100_label, status_label, particles_label
            )
            # Log read failure to Logflare
            error_metadata = {
                "level": "error",
                "mac_address": device_mac,
                "location": DEVICE_LOCATION,
                "error": str(last_error),
                "config": {
                    "wifi_ssid": WIFI_SSID,
                    "device_location": DEVICE_LOCATION,
                    "device_environment": DEVICE_ENVIRONMENT,
                    "reading_interval": READING_INTERVAL,
                    "display_units": DISPLAY_UNITS,
                    "spa06_enabled": ENABLE_SPA06,
                },
            }
            logflare.send(f"AQ sensor read failed in '{DEVICE_LOCATION}'", error_metadata)
            time.sleep(READING_INTERVAL)
            gc.collect()
            continue

        # Select readings based on environment setting
        suffix = " env" if USE_ENV_READINGS else " standard"
        pm10_val = aq_data["pm10" + suffix]   # PM1.0
        pm25_val = aq_data["pm25" + suffix]   # PM2.5
        pm100_val = aq_data["pm100" + suffix]  # PM10.0

        # Build display data dict
        display_data = {
            "pm10": pm10_val,
            "pm25": pm25_val,
            "pm100": pm100_val,
            "particles_03um": aq_data["particles 03um"],
            "particles_05um": aq_data["particles 05um"],
            "particles_10um": aq_data["particles 10um"],
        }

        # Update display
        status_text = update_air_quality_display(
            pm25_label, pm10_label, pm100_label, status_label, particles_label, display_data
        )

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
        update_environment_display(temp_value_label, pressure_value_label, temperature, pressure)

        # Send to Logflare
        event_message = f"Air quality reading from '{DEVICE_LOCATION}'"
        metadata = {
            "level": "info",
            "mac_address": device_mac,
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

        # Add temperature/pressure if available
        if temperature is not None:
            metadata["temperature_c"] = round(temperature, 1)
            metadata["temperature_f"] = round(celsius_to_fahrenheit(temperature), 1)
        if pressure is not None:
            metadata["pressure_hpa"] = round(pressure, 1)
            metadata["pressure_inhg"] = round(hpa_to_inhg(pressure), 2)
            metadata["estimated_altitude_m"] = round(pressure_to_altitude(pressure), 1)

        if logflare.send(event_message, metadata):
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
