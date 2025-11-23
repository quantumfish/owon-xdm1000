# xdm1000

Simple Python driver for OWON XDM1000 / XDM1xxx multimeters over serial (SCPI).

## Features

- Auto-discovery of the first available OWON XDM1xxx using `*IDN?`
- High-level `XDM1000` class:
  - `set_mode()` — selects measurement function (VDC, VAC, IDC, IAC, RES, CAP, FREQ)
  - `set_rate()` — sets measurement speed (`RATE F/M/S`)
  - `measure()` — single measurement using `MEAS?` in the current mode
- Works with:
  - XDM1000 (firmware V4.3.0,3 tested)
  - Other XDM1xxx models should also be compatible (e.g. XDM1241)

## Installation

```bash
pip install xdm1000

(Or clone this repo and install in editable mode:)

git clone https://github.com/yourname/xdm1000.git
cd xdm1000
pip install -e .

## Usage

from xdm1000 import XDM1000, MeasurementMode, MeasurementSpeed
import time

# Auto-discover first XDM1xxx
with XDM1000() as meter:
    print("Connected to:", meter.idn)

    # Set DC voltage mode and FAST rate
    meter.set_mode(MeasurementMode.VDC)
    meter.set_rate(MeasurementSpeed.FAST)

    for i in range(5):
        value = meter.measure()
        print(f"V = {value}")
        time.sleep(1.0)

You can also select a specific instrument by serial suffix:

with XDM1000(serial_suffix="1543") as meter:
    ...

This matches any device whose serial number (3rd field in *IDN?) contains "1543".