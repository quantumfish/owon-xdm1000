#!/usr/bin/env python3
"""
Example: sweep all modes and speeds on the first available XDM1xxx.

- Finds the first available XDM1xxx instrument.
- Iterates through all MeasurementMode values.
- For each mode iterates through all MeasurementSpeed values.
- In each (mode, speed) combination performs 3 measurements.
"""

import time

from xdm1000 import (
    XDM1000,
    XDM1000Error,
    MeasurementMode,
    MeasurementSpeed,
)


def main():
    """Sweep all modes and speeds, printing measurement values."""
    print("Searching for first OWON XDM1xxx instrument...\n")

    try:
        # No serial_suffix -> first matching instrument
        with XDM1000() as meter:
            print(f"Connected to: {meter.idn}")
            print(f"Port: {meter.port_name}")
            print(f"Serial: {meter.serial_number}, FW: {meter.firmware}\n")

            modes = list(MeasurementMode)
            speeds = list(MeasurementSpeed)

            for mode in modes:
                print(f"=== MODE: {mode.name} ({mode.value}) ===")
                meter.set_mode(mode)

                for speed in speeds:
                    print(f"  RATE: {speed.name} ({speed.value})")
                    meter.set_rate(speed)

                    for i in range(3):
                        try:
                            value = meter.measure()
                            print(f"    Measurement {i + 1}: {value}")
                        except XDM1000Error as e:
                            print(f"    Measurement {i + 1} FAILED: {e}")
                        time.sleep(0.2)

                print()

    except XDM1000Error as e:
        print(f"ERROR: {e}")


if __name__ == "__main__":
    main()
