# Air Quality Sensor Integration With Logflare

DIY home air quality sensor using [Logflare](https://logflare.app) as a backend for data storage and visualization using commodity hardware from Adafruit for simplicity.

## Hardware

- [Adafruit ESP32-S2 Reverse TFT Feather](https://www.adafruit.com/product/5345)
  - [Overview](https://learn.adafruit.com/esp32-s2-reverse-tft-feather)
- [Adafruit PMSA003I Air Quality Breakout](https://www.adafruit.com/product/4632)
- [STEMMA QT / Qwiic JST SH 4-Pin Cable](https://www.adafruit.com/product/4399)
- [Adafruit SPA06-003 Temperature + Pressure Sensor](https://www.adafruit.com/product/6420) (Optional)

## CircuitPython

- [CircuitPython 10.0.3 for the Adafruit ESP32-S2 Reverse TFT Feather](https://circuitpython.org/board/adafruit_feather_esp32s2_reverse_tft/)

### Documentation

- [CircuitPython v10.0.3 Docs](https://docs.circuitpython.org/en/10.0.3/README.html)
  - [Core Modules](https://docs.circuitpython.org/en/10.0.3/shared-bindings/index.html)
  - [Standard Libraries](https://docs.circuitpython.org/en/10.0.3/docs/library/index.html)

## Setup

### CircuitPython Libraries

Download and extract the latest 10.x bundle of CircuitPython libraries from [https://circuitpython.org/libraries](https://circuitpython.org/libraries).

Copy the following library files/directories to the `/lib` directory on the board:
  - `adafruit_display_text/`
  - `adafruit_displayio_layout/`
  - `adafruit_pm25/`
  - `adafruit_register/`
  - `adafruit_connection_manager.mpy`
  - `adafruit_ntp.mpy`
  - `adafruit_requests.mpy`
  - `adafruit_spa06_003.mpy` (_Optional, if using the SPA06-003 temperature / pressure sensor_)

### Code

Copy the `code.py` and `logflare.py` files to the root directory of the board.

### Configuration

Copy the `settings.toml` file to the root directory of the board and update with your settings for wifi and Logflare.
