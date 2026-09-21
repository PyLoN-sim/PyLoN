import copy
import json
import unittest
from types import SimpleNamespace as NS

from pylon_bridge.control_batch import control_batch_command
from pylon_bridge.domain.session import SessionKey
from pylon_bridge.flight_packets import SCALARS, VECTORS
from pylon_bridge.observations import control_snapshot_from_packet


class ControlBatchTests(unittest.TestCase):
    def batch(self):
        identity = dict(vessel_id='v', controller_id='c', lease_id='l', sequence=4)
        return NS(**identity, renew_lease=True, lease_duration_sec=1., suppress_sas=True,
                  has_flight=True, flight=NS(**identity, pitch=.2, yaw=-.3, roll=.1,
                                            landing_gear=False, timeout_sec=.3),
                  engines=[NS(**identity, id='main', enabled=True, target_thrust=100.,
                              has_gimbal_command=False, gimbal_pitch=0., gimbal_yaw=0.,
                              gimbal_roll=0., timeout_sec=.3)],
                  has_separation=True, separation=NS(**identity, id='payload', separate=True,
                      operation_id='operation', original_runtime_instance='',
                      original_runtime_epoch='', original_vessel_id=''))

    def convert(self, batch):
        return control_batch_command(batch, SessionKey('instance', 1, 'epoch', 'v'))

    def test_outer_identity_and_sequence_own_every_member(self):
        batch = self.batch()
        batch.flight.sequence = 100
        batch.engines[0].vessel_id = 'wrong'
        packet = self.convert(batch)
        self.assertNotIn('engines', packet)
        members = [json.loads(packet['flightJson']), json.loads(packet['engineJson'][0]),
                   json.loads(packet['separationJson'])]
        for value in members:
            self.assertEqual(value['sequence'], 4)
            self.assertEqual(value['vesselId'], 'v')
        self.assertEqual(members[2]['operationEpoch'], 'epoch')
        self.assertEqual(batch.flight.sequence, 100)

    def test_rejects_whole_batch_for_bad_member(self):
        for field, value in [('target_thrust', float('nan')), ('timeout_sec', 2.),
                              ('id', ''), ('gimbal_pitch', 2.)]:
            batch = self.batch()
            setattr(batch.engines[0], field, value)
            with self.assertRaises(ValueError):
                self.convert(batch)

    def test_rejects_duplicate_engines(self):
        batch = self.batch()
        batch.engines.append(copy.copy(batch.engines[0]))
        with self.assertRaises(ValueError):
            self.convert(batch)

    def test_rejects_out_of_range_sequence_and_lease(self):
        for field, value in [('sequence', 2**63), ('sequence', 0), ('lease_duration_sec', .01)]:
            batch = self.batch()
            setattr(batch, field, value)
            with self.assertRaises(ValueError):
                self.convert(batch)


class SnapshotTests(unittest.TestCase):
    def packet(self):
        flight = dict(type='pylon_flight_state', version=1, vesselId='v', observationSequence=1,
                      bodyName='Kerbin', landed=False, splashed=False,
                      **{key: 1. for key in SCALARS.values()},
                      **{key: [1., 0., 0.] for key in VECTORS.values()})
        engine = dict(type='pylon_actuator_state', version=1, vesselId='v', observationSequence=1,
                      universalTime=1., actuatorType='engine', name='main',
                      enabled=True, operational=True, flameout=False, commandActive=False,
                      gimbalAvailable=False, gimbalCommandActive=False, throttle=0.,
                      thrust=0., maxThrust=10., gimbalPitch=0., gimbalYaw=0., gimbalRoll=0.)
        return dict(type='pylon_control_snapshot', version=1, vesselId='v', observationSequence=1,
                    **SessionKey('instance', 2, 'epoch', 'v').fields(),
                    flight=flight, engines=[engine], separations=[])

    def test_members_inherit_exact_envelope(self):
        flight, engines, separators = control_snapshot_from_packet(self.packet())
        self.assertEqual(flight['runtimeEpoch'], 'epoch')
        self.assertEqual(engines[0]['runtimeGeneration'], 2)
        self.assertEqual(separators, [])

    def test_rejects_mixed_epoch_frame_time_and_vessel(self):
        for field, value in [('runtimeEpoch', 'old'), ('observationSequence', 2),
                             ('universalTime', .5), ('vesselId', 'other')]:
            packet = self.packet()
            packet['engines'][0][field] = value
            with self.assertRaises(ValueError):
                control_snapshot_from_packet(packet)

    def test_rejects_incomplete_or_duplicate_snapshot(self):
        for field in ('flight', 'engines', 'separations'):
            packet = self.packet(); packet.pop(field)
            with self.assertRaises(ValueError):
                control_snapshot_from_packet(packet)
        packet = self.packet(); packet['engines'] *= 2
        with self.assertRaises(ValueError):
            control_snapshot_from_packet(packet)

    def test_rejects_malformed_ros_scalar_types(self):
        for field, value in [('enabled', 'false'), ('thrust', True), ('role', []), ('name', 3)]:
            packet = self.packet(); packet['engines'][0][field] = value
            with self.assertRaises(ValueError):
                control_snapshot_from_packet(packet)
        packet = self.packet(); packet['runtimeGeneration'] = 2**64
        with self.assertRaises(ValueError):
            control_snapshot_from_packet(packet)
