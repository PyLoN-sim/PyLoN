import unittest
from pylon_vehicle_control.application.flight_axes import stock_inputs_for_body_axes


class FlightAxesTests(unittest.TestCase):
    def test_positive_and_negative_body_axes(self):
        for axis, expected in [(0, (0, 0, 1)), (1, (-1, 0, 0)), (2, (0, -1, 0))]:
            for sign in (-1, 1):
                value = [0., 0., 0.]; value[axis] = float(sign)
                self.assertEqual(stock_inputs_for_body_axes(value), tuple(sign*v for v in expected))

    def test_rejects_unbounded_or_nonfinite_input(self):
        for value in [(0, 1), (0, 0, 1.1), (float('nan'), 0, 0), (True, 0, 0)]:
            with self.assertRaises(ValueError):
                stock_inputs_for_body_axes(value)
