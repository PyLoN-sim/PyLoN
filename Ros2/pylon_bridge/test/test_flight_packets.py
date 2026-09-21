from types import SimpleNamespace
import unittest
from pylon_bridge.flight_packets import SCALARS, VECTORS, flight_state_from_packet, flight_control_command


class FlightPacketsTest(unittest.TestCase):
    def packet(self):
        return dict(type='pylon_flight_state', version=1, vesselId='vessel', bodyName='Kerbin',
                    landed=True, splashed=False, **{k: 1. for k in SCALARS.values()},
                    **{k: [1., 0., 0.] for k in VECTORS.values()})

    def test_state_units_and_frame_values_preserved(self):
        p = self.packet(); p['mass'] = 80000.; p['altitudeAsl'] = 90000.
        state = flight_state_from_packet(p)
        self.assertEqual(state['mass'], 80000.)
        self.assertEqual(state['altitude_asl'], 90000.)
        self.assertEqual(state['up_body'], (1., 0., 0.))

    def test_state_rejects_invalid_telemetry(self):
        for field, value in [('mass', 0.), ('gravity', float('nan')), ('upBody', [0, 1]),
                             ('landed', 'true'), ('vesselId', ''), ('liquidFuel', True)]:
            p = self.packet(); p[field] = value
            with self.assertRaises(ValueError):
                flight_state_from_packet(p)

    def test_command_requires_bounded_inputs_and_identity(self):
        m = SimpleNamespace(vessel_id='v', controller_id='c', lease_id='l', sequence=1,
                            pitch=.2, yaw=-.3, roll=.1, landing_gear=True, timeout_sec=.3)
        p = flight_control_command(m)
        self.assertEqual(p['pitch'], .2)
        self.assertEqual(p['timeoutSeconds'], .3)
        for field, value in [('pitch', 1.1), ('yaw', float('nan')), ('lease_id', ''),
                             ('sequence', 0), ('timeout_sec', 10.)]:
            bad = SimpleNamespace(**vars(m)); setattr(bad, field, value)
            with self.assertRaises(ValueError):
                flight_control_command(bad)
