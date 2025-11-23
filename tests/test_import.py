"""Basic smoke-test for xdm1000 package import."""

from xdm1000 import XDM1000, MeasurementMode, MeasurementSpeed


def test_import():
    """Check that package symbols import correctly."""
    assert XDM1000
    assert MeasurementMode
    assert MeasurementSpeed
