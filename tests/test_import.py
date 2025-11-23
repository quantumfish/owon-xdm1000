def test_import():
    from xdm1000 import XDM1000, MeasurementMode, MeasurementSpeed

    # Just ensure the symbols exist
    assert XDM1000 is not None
    assert MeasurementMode.VDC.value == "VOLT:DC"
    assert MeasurementSpeed.FAST.value == "F"
