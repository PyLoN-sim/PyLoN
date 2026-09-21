import copy
import json
from types import SimpleNamespace as Message
import unittest

from pylon_vehicle_control.application.checkpoint import MissionCheckpoint, validate_resume


def observations(ut=100., sequence=10):
    identity = dict(runtime_instance='process', runtime_generation=3, runtime_epoch='epoch',
                    vessel_id='vessel', observation_sequence=sequence, universal_time=ut)
    flight = Message(**identity, body_name='Kerbin', body_radius=600000.,
                     gravitational_parameter=3.53e12, atmosphere_depth=70000.,
                     altitude_asl=80000., apoapsis=81000., periapsis=79000.,
                     mass=25000., liquid_fuel=100., oxidizer=120., electric_charge=50.,
                     landed=False, splashed=False, dynamic_pressure=0.)
    simulator = Message(**identity, state=1, communication_alive=True, simulation_advancing=True,
                        paused=False, packed=False, warp_rate=1., control_available=True)
    engine = Message(**identity, id='return_engine', thrust=0., throttle=0., flameout=False)
    separator = Message(**identity, id='payload_separator')
    authority = Message(vessel_id='vessel', state=1, controller_id='mission',
                        lease_id='old_lease', emergency_stop=False)
    return flight, simulator, [engine], [separator], authority


class CheckpointTests(unittest.TestCase):
    def setUp(self):
        self.original = observations()
        self.checkpoint = MissionCheckpoint.capture(*self.original)
        self.current = observations(ut=110., sequence=30)
        self.current[-1].state = 0
        self.current[-1].lease_id = ''
        self.current[-1].controller_id = ''

    def validate(self, current=None, checkpoint=None, **kwargs):
        args = dict(now_monotonic=20., received_at=19.9)
        args.update(kwargs)
        return validate_resume(checkpoint or self.checkpoint, *(current or self.current), **args)

    def test_json_roundtrip_is_bounded_and_rejects_unknown_schema(self):
        encoded = json.loads(json.dumps(self.checkpoint.to_dict()))
        self.assertEqual(MissionCheckpoint.from_dict(encoded), self.checkpoint)
        for updates in [dict(version=2), dict(mass=float('nan')), dict(runtime_generation=True),
                        dict(engine_ids=['e'] * 257), dict(vessel_id='x' * 129), dict(secret='extra')]:
            with self.subTest(updates=updates), self.assertRaises(ValueError):
                MissionCheckpoint.from_dict(dict(encoded, **updates))

    def test_capture_can_preserve_a_paused_or_stale_unpowered_baseline(self):
        flight, simulator, engines, separators, authority = self.original
        simulator.paused = True
        simulator.state = 5
        simulator.communication_alive = False
        self.assertEqual(MissionCheckpoint.capture(*self.original).identity, self.checkpoint.identity)
        engines[0].thrust = 500.
        with self.assertRaisesRegex(ValueError, 'engine_not_quiescent'):
            MissionCheckpoint.capture(*self.original)

    def test_orbital_phase_and_time_can_advance_with_safe_configuration(self):
        self.current[0].altitude_asl = 80500.
        self.assertTrue(self.validate().allowed)
        self.assertEqual(self.validate().reason, 'ready_for_new_lease')

    def test_missing_or_stale_telemetry_cannot_resume(self):
        for receipt in (19., 21.):
            self.assertEqual(self.validate(received_at=receipt).reason, 'telemetry_stale')
        self.assertEqual(self.validate(current=(None, *self.current[1:])).reason, 'checkpoint_observation_missing')

    def test_pause_pack_warp_stall_and_communication_loss_each_reject_resume(self):
        for field, value, reason in [
            ('paused', True, 'simulator_paused'), ('packed', True, 'simulator_packed'),
            ('warp_rate', 10., 'simulator_warping'), ('state', 3, 'simulator_not_advancing'),
            ('simulation_advancing', False, 'simulator_not_advancing'),
            ('communication_alive', False, 'simulator_unavailable'),
            ('control_available', False, 'simulator_unavailable'),
        ]:
            current = copy.deepcopy(self.current)
            setattr(current[1], field, value)
            self.assertEqual(self.validate(current).reason, reason)

    def test_changed_identity_and_mixed_epoch_observations_reject_resume(self):
        for field, value in [('runtime_instance', 'restart'), ('runtime_generation', 4),
                             ('runtime_epoch', 'other'), ('vessel_id', 'other')]:
            current = copy.deepcopy(self.current)
            setattr(current[0], field, value)
            self.assertEqual(self.validate(current).reason, 'checkpoint_identity_changed')
        current = copy.deepcopy(self.current)
        current[2][0].runtime_epoch = 'old'
        self.assertEqual(self.validate(current).reason, 'observation_identity_mismatch')

    def test_replayed_or_incoherent_observations_reject_resume(self):
        self.assertEqual(self.validate(current=self.original).reason, 'fresh_post_checkpoint_observation_required')
        current = copy.deepcopy(self.current)
        current[2][0].universal_time -= 1.
        self.assertEqual(self.validate(current).reason, 'observation_time_mismatch')

    def test_actuators_must_share_the_flight_snapshot_frame(self):
        current = copy.deepcopy(self.current)
        current[2][0].observation_sequence -= 1
        self.assertEqual(self.validate(current).reason, 'observation_frame_mismatch')

    def test_configuration_resources_mass_body_and_orbit_must_match(self):
        for field, value, reason in [('body_name', 'Mun', 'body_changed'), ('mass', 24900., 'mass_changed'),
                                     ('liquid_fuel', 90., 'liquid_fuel_changed'),
                                     ('oxidizer', 110., 'oxidizer_changed'),
                                     ('electric_charge', 0., 'electric_charge_changed'),
                                     ('apoapsis', 82000., 'apoapsis_changed'),
                                     ('periapsis', 78500., 'periapsis_changed')]:
            current = copy.deepcopy(self.current)
            setattr(current[0], field, value)
            self.assertEqual(self.validate(current).reason, reason)
        current = copy.deepcopy(self.current)
        current[2][0].id = 'different_engine'
        self.assertEqual(self.validate(current).reason, 'actuator_configuration_changed')

    def test_nonzero_thrust_flameout_and_unsafe_orbit_are_rejected(self):
        for field, value in [('thrust', 20.), ('throttle', .1), ('flameout', True)]:
            current = copy.deepcopy(self.current)
            setattr(current[2][0], field, value)
            self.assertEqual(self.validate(current).reason, 'engine_not_quiescent')
        self.current[0].periapsis = 65000.
        self.assertEqual(self.validate().reason, 'requires_unpowered_vacuum_orbit')

    def test_pending_operations_require_explicit_resolution(self):
        checkpoint = MissionCheckpoint.capture(*self.original, pending_operation_ids=['separation_1'])
        self.assertEqual(self.validate(checkpoint=checkpoint).reason, 'pending_operations_unresolved')
        self.assertTrue(self.validate(checkpoint=checkpoint, resolved_operation_ids=['separation_1']).allowed)

    def test_new_explicit_lease_allowed_but_checkpoint_lease_never_reused(self):
        authority = self.current[-1]
        authority.state, authority.controller_id, authority.lease_id = 1, 'mission', 'old_lease'
        self.assertEqual(self.validate(allowed_controller_id='mission', allowed_lease_id='old_lease').reason,
                         'authority_not_released')
        authority.lease_id = 'fresh_lease'
        self.assertEqual(self.validate().reason, 'authority_conflict')
        self.assertTrue(self.validate(allowed_controller_id='mission', allowed_lease_id='fresh_lease').allowed)
        authority.emergency_stop = True
        self.assertEqual(self.validate().reason, 'emergency_stop_active')

    def test_nonboolean_simulator_flags_do_not_accidentally_authorize_resume(self):
        self.current[1].communication_alive = 'false'
        self.assertEqual(self.validate().reason, 'invalid_simulator_state')
