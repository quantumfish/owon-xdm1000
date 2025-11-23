"""
Simple driver for the OWON XDM1000
(tested with firmware V4.3.0,3, should also work with 3.8.x).

Architecture:

1) Auto-discovery in constructor:
   - meter = XDM1000(serial_suffix="1543")
     -> automatically finds port and opens it

2) Class XDM1000:
   - __init__(serial_suffix=None, baudrate=115200, timeout=0.5)
       If serial_suffix is None, the first detected XDM1xxx instrument is used.
   - set_mode(mode)
       mode:
         - MeasurementMode.VDC / MeasurementMode.RES / ...
         - "VDC", "VAC", "IDC", "IAC", "RES", "CAP", "FREQ"
         - "VOLT:DC", "VOLT:AC", "CURR:DC", "CURR:AC", ...
       when changing mode:
         * sends CONF:...
         * waits MODE_SETTLE_DELAY seconds for relays/ADC to settle
         * performs 2 warm-up MEAS? calls (result is ignored)
   - set_rate(speed)
       speed:
         - MeasurementSpeed.FAST / MEDIUM / SLOW
         - "F", "FAST", "M", "MID", "MEDIUM", "L", "SLOW"
       SCPI command: RATE F / M / S
   - measure() — a single measurement in the current mode via MEAS?

No extra CONF/READ inside measure(); the screen mode does not flicker.
"""

from __future__ import annotations

import time
from enum import Enum
from typing import Optional, Union

import serial  # type: ignore[import-error]  # pylint: disable=import-error
from serial.tools import list_ports  # type: ignore[import-error]  # pylint: disable=import-error

DEFAULT_BAUDRATE = 115200
DEFAULT_TIMEOUT = 0.5
# Fixed delays used after mode/rate changes
MODE_SETTLE_DELAY = 3.0
MODE_RATE_DELAY = 0.5


class XDM1000Error(Exception):
    """Base exception type for the XDM1000 driver."""

# =============================================================
#   MEASUREMENT MODES AND SPEED
# =============================================================

class MeasurementMode(str, Enum):
    """Supported measurement functions (SCPI function mnemonics)."""
    VDC  = "VOLT:DC"
    VAC  = "VOLT:AC"
    IDC  = "CURR:DC"
    IAC  = "CURR:AC"
    RES  = "RES"
    CAP  = "CAP"
    FREQ = "FREQ"


class MeasurementSpeed(str, Enum):
    """Measurement speed settings used with the RATE command."""
    FAST   = "F"
    MEDIUM = "M"
    SLOW   = "S"


# =============================================================
#   COMMON SCPI TABLE (modes + speed)
# =============================================================

SCPI_TABLE = {
    # Mode normalization
    MeasurementMode: {
        # VDC
        "VDC":      MeasurementMode.VDC,
        "VOLT:DC":  MeasurementMode.VDC,

        # VAC
        "VAC":      MeasurementMode.VAC,
        "VOLT:AC":  MeasurementMode.VAC,

        # IDC
        "IDC":      MeasurementMode.IDC,
        "CURR:DC":  MeasurementMode.IDC,

        # IAC
        "IAC":      MeasurementMode.IAC,
        "CURR:AC":  MeasurementMode.IAC,

        # RES
        "RES":      MeasurementMode.RES,
        "OHM":      MeasurementMode.RES,

        # CAP
        "CAP":      MeasurementMode.CAP,
        "C":        MeasurementMode.CAP,

        # FREQ
        "FREQ":     MeasurementMode.FREQ,
        "F":        MeasurementMode.FREQ,
    },

    # RATE normalization
    MeasurementSpeed: {
        # FAST
        "FAST":     MeasurementSpeed.FAST,
        "F":        MeasurementSpeed.FAST,

        # MEDIUM
        "M":        MeasurementSpeed.MEDIUM,
        "MID":      MeasurementSpeed.MEDIUM,
        "MEDIUM":   MeasurementSpeed.MEDIUM,

        # SLOW
        "S":        MeasurementSpeed.SLOW,
        "SLOW":     MeasurementSpeed.SLOW,
        "L":        MeasurementSpeed.SLOW,   # alias for "slow"
    },
}


def _normalize_scpi(value, enum_type):
    """
    Normalize a SCPI-like token into the given Enum type.

    Parameters
    ----------
    value : Enum or str
        Either a MeasurementMode/MeasurementSpeed value, or a string alias.
        For strings, case and surrounding whitespace are ignored.
    enum_type : Type[Enum]
        Target enum class: MeasurementMode or MeasurementSpeed.

    Returns
    -------
    enum_type
        Normalized enum value.

    Raises
    ------
    XDM1000Error
        If the token is not recognized for the given enum type.
    """
    if isinstance(value, enum_type):
        return value

    s = str(value).strip().upper()
    table = SCPI_TABLE.get(enum_type, {})

    try:
        return table[s]
    except KeyError as exc:  # pylint: disable=raise-missing-from
        raise XDM1000Error(
            f"Unknown {enum_type.__name__} token: {value!r}"
        ) from exc


# =============================================================
#   DRIVER CLASS
# =============================================================

class XDM1000:
    """
    Simple high-level driver for the OWON XDM1000.

    The constructor performs auto-discovery using the *IDN? query and opens
    a serial connection to the first matching XDM1xxx instrument.

    The class implements the context manager protocol, so it can be used as:

    >>> from xdm1000 import XDM1000
    >>> with XDM1000("1543") as meter:
    ...     meter.set_mode("VDC")
    ...     print(meter.measure())

    Typical usage without context manager
    -------------------------------------

    >>> from xdm1000 import XDM1000, MeasurementMode, MeasurementSpeed
    >>> import time
    >>>
    >>> meter = XDM1000(serial_suffix="1543")
    >>> meter.set_mode(MeasurementMode.VDC)
    >>> meter.set_rate(MeasurementSpeed.FAST)
    >>>
    >>> while True:
    ...     print("V =", meter.measure())
    ...     time.sleep(1)
    """
    # pylint: disable=too-many-instance-attributes

    def __init__(
        self,
        serial_suffix: Optional[str] = None,
        baudrate: int = DEFAULT_BAUDRATE,
        timeout: float = DEFAULT_TIMEOUT,
    ):
        """
        Auto-discover and open a connection to an OWON XDM1xxx instrument.

        Discovery is done by scanning available serial ports, sending *IDN?
        to each, and selecting the first device whose IDN string contains
        both "OWON" and "XDM1". If `serial_suffix` is given, the third field
        of the IDN (serial number) must contain that substring.

        Parameters
        ----------
        serial_suffix : str or None
            Substring of the instrument serial number (e.g. "1543").
            If None, the first detected XDM1xxx is used.
        baudrate : int
            Serial port speed (default: 115200).
        timeout : float
            Read timeout in seconds (default: 0.5).

        Raises
        ------
        XDM1000Error
            If no matching instrument is found.
        """
        self.baudrate = baudrate
        self.timeout = timeout

        # -------- Auto-discovery --------
        ports = list(list_ports.comports())
        chosen_port: Optional[str] = None
        chosen_idn: Optional[str] = None

        for p in ports:
            try:
                ser = serial.Serial(
                    p.device,
                    baudrate=baudrate,
                    timeout=timeout,
                    write_timeout=timeout,
                )

                # Let the instrument wake up after opening the port
                time.sleep(0.3)
                ser.reset_input_buffer()

                # *IDN? query
                ser.write(b"*IDN?\r\n")
                ser.flush()
                time.sleep(0.3)
                idn = ser.readline().decode("ascii", errors="ignore").strip()
                ser.close()

                if not idn:
                    continue

                idn_upper = idn.upper()

                # Require OWON and an XDM1xxx model
                if "OWON" not in idn_upper or "XDM1" not in idn_upper:
                    continue

                parts = [x.strip() for x in idn.split(",")]
                if len(parts) < 3:
                    continue

                serial_number = parts[2]

                if serial_suffix is None or serial_suffix in serial_number:
                    chosen_port = p.device
                    chosen_idn = idn
                    break
            except Exception:  # pylint: disable=broad-exception-caught
                # Any error on this port: skip to the next one
                continue

        if chosen_port is None or chosen_idn is None:
            raise XDM1000Error(
                f"Failed to find XDM1000 with serial suffix {serial_suffix}."
            )

        # Save basic info
        self.port_name = chosen_port
        self.idn = chosen_idn.strip()

        parts = self.idn.split(",")
        self.serial_number = parts[2] if len(parts) >= 3 else ""
        self.firmware = parts[3] if len(parts) >= 4 else ""

        # Open the serial port for further communication
        self.ser = serial.Serial(
            self.port_name,
            baudrate=self.baudrate,
            timeout=self.timeout,
            write_timeout=self.timeout,
        )

        # Allow to wake up
        time.sleep(0.3)
        self.ser.reset_input_buffer()

        self._current_mode: Optional[MeasurementMode] = None

    # -------- Context manager protocol --------

    def __enter__(self) -> "XDM1000":
        """Enter the runtime context related to this object."""
        return self

    def __exit__(self, exc_type, exc, tb):
        """
        Exit the runtime context and close the serial port.

        Any exception raised inside the block is propagated (no suppression).
        """
        self.close()

    # ---------------- Low-level I/O ----------------

    def write(self, cmd: str):
        """
        Send a SCPI command terminated with CRLF.

        Parameters
        ----------
        cmd : str
            Command string without line ending, e.g. "CONF:VOLT:DC".
        """
        self.ser.write((cmd + "\r\n").encode("ascii"))
        self.ser.flush()
        time.sleep(0.05)

    def read(self) -> str:
        """
        Read a single line of response from the instrument.

        Returns
        -------
        str
            Response line decoded as ASCII and stripped of trailing whitespace.
        """
        return self.ser.readline().decode("ascii", errors="ignore").strip()

    def query(self, cmd: str) -> str:
        """
        Send a SCPI command and read back a single-line response.

        This is equivalent to calling `write(cmd)` followed by `read()`.

        Parameters
        ----------
        cmd : str
            Command string without line ending.

        Returns
        -------
        str
            Response from the instrument.
        """
        self.write(cmd)
        return self.read()

    # ---------------- Mode setting ----------------

    def set_mode(self, mode: Union[MeasurementMode, str]):
        """
        Set the measurement function/mode.

        The driver sends a `CONF:<MODE>` command, waits for
        `MODE_SETTLE_DELAY` seconds to allow relays/ADC to settle,
        then performs two dummy `MEAS?` queries (ignored) to warm up
        the measurement path.

        Parameters
        ----------
        mode : MeasurementMode or str
            Desired measurement mode, e.g.:
            - MeasurementMode.VDC
            - "VDC", "VOLT:DC"
            - "RES", "OHM"
            - "FREQ", "F"
        """
        mode_enum = _normalize_scpi(mode, MeasurementMode)

        # (1) send CONF:...
        conf_cmd = f"CONF:{mode_enum.value}"
        self.write(conf_cmd)

        # (2) settling delay
        time.sleep(MODE_SETTLE_DELAY)

        # (3) warm-up dummy measurements
        for _ in range(2):
            try:
                _ = self.query("MEAS?")
            except Exception:  # pylint: disable=broad-exception-caught
                # warm-up failures are ignored
                pass
            time.sleep(0.1)

        self._current_mode = mode_enum

    # ---------------- RATE setting ----------------

    def set_rate(self, speed):
        """
        Set the measurement speed using the SCPI `RATE` command.

        The RATE affects integration time / averaging inside the instrument.
        After the command is sent, the driver waits `MODE_RATE_DELAY`
        seconds to allow the new settings to take effect.

        Parameters
        ----------
        speed : MeasurementSpeed or str
            May be:
                - MeasurementSpeed.FAST / MEDIUM / SLOW
                - "F", "FAST"
                - "M", "MID", "MEDIUM"
                - "L", "S", "SLOW"
        """
        speed_enum = _normalize_scpi(speed, MeasurementSpeed)
        self.write(f"RATE {speed_enum.value}")
        time.sleep(MODE_RATE_DELAY)

    # ---------------- Measurements (MEAS? only, no mode changes) ----------------

    @staticmethod
    def _is_number(s: str) -> bool:
        """
        Check if a string can be safely converted to float.

        Parameters
        ----------
        s : str
            Input string.

        Returns
        -------
        bool
            True if `float(s)` succeeds, False otherwise.
        """
        try:
            float(s)
            return True
        except Exception:  # pylint: disable=broad-exception-caught
            return False

    def measure(self) -> float:
        """
        Perform a single measurement in the current mode using `MEAS?`.

        This method does not change the instrument mode. It assumes that
        the desired mode has been previously selected via `set_mode()`.

        Returns
        -------
        float
            Numeric value returned by the instrument.

        Raises
        ------
        XDM1000Error
            If the response is empty or cannot be parsed as a float.
        """
        resp = self.query("MEAS?")
        if not resp:
            raise XDM1000Error("Empty response during measurement (MEAS?).")

        if not self._is_number(resp):
            raise XDM1000Error(f"Non-numeric MEAS? response: {resp!r}")

        return float(resp)

    # ---------------- Resource cleanup ----------------

    def close(self):
        """
        Close the underlying serial port.

        After calling this method (or after leaving a `with` block),
        the instance should not be used for further communication.
        """
        self.ser.close()
