"""Generated ROS messages and bridge adapters, without a running simulator."""
from types import SimpleNamespace as NS
import unittest
import json
from unittest.mock import Mock

from builtin_interfaces.msg import Time
from pylon_interfaces.msg import ControlBatch, EngineCommand
from rclpy.serialization import serialize_message
from pylon_bridge.application.runtime import BridgeRuntime
from pylon_bridge.control_batch import control_batch_command
from pylon_bridge.domain.session import SessionKey
from pylon_bridge.flight_packets import SCALARS, VECTORS
from pylon_bridge.protocol import decode_datagram
from pylon_bridge.services.snapshot import SnapshotService


class ControlApiRosTests(unittest.TestCase):
    def test_batch_is_one_session_bound_datagram_with_shared_identity(self):
        message = ControlBatch(vessel_id='v', controller_id='controller', lease_id='lease', sequence=7,
                               renew_lease=True, lease_duration_sec=1., suppress_sas=True, has_flight=True)
        message.flight.pitch, message.flight.timeout_sec = .4, .3
        message.engines = [EngineCommand(id='main', enabled=True, target_thrust=100., timeout_sec=.3)]
        serialize_message(message)
        runtime = BridgeRuntime()
        key = SessionKey('instance', 1, 'epoch', 'v')
        runtime.observe_session(dict(type='pylon_session', version=1, **key.fields(),
            vesselId='v', available=True, universalTime=1.), 10.)
        packet = decode_datagram(runtime.encode_command(control_batch_command(message, key), 10.1, 1.))
        self.assertEqual(packet['runtimeEpoch'], 'epoch')
        self.assertEqual(json.loads(packet['engineJson'][0])['sequence'], 7)
        self.assertEqual(json.loads(packet['flightJson'])['sequence'], 7)
        self.assertEqual(json.loads(packet['engineJson'][0])['leaseId'], 'lease')

    def test_coherent_snapshot_serializes_and_reordered_frame_is_dropped(self):
        publisher = Mock()
        bridge = NS(ground_truth_enabled=True, topic_prefix='/test',
                    create_publisher=lambda *args: publisher,
                    flight=NS(stamp_for_universal_time=lambda value: Time()),
                    get_logger=lambda: NS(warning=Mock()))
        service = SnapshotService(bridge)
        flight = dict(type='pylon_flight_state', version=1, vesselId='v', observationSequence=2,
                      bodyName='Kerbin', landed=False, splashed=False,
                      **{key: 1. for key in SCALARS.values()},
                      **{key: [1., 0., 0.] for key in VECTORS.values()})
        flight.update(appliedInputValid=True, flightCommandActive=True, appliedInputSequence=7,
                      appliedInputAge=.01, appliedPitch=.4, appliedYaw=0., appliedRoll=0., inputAtLimit=False)
        engine = dict(type='pylon_actuator_state', version=1, actuatorType='engine',
                      vesselId='v', observationSequence=2, universalTime=1., name='main', role='return_engine',
                      enabled=True, operational=True, flameout=False, throttle=.2, thrust=10., maxThrust=50.,
                      commandActive=True, gimbalAvailable=False, gimbalCommandActive=False,
                      gimbalPitch=0., gimbalYaw=0., gimbalRoll=0.)
        packet = dict(type='pylon_control_snapshot', version=1, **SessionKey('i', 1, 'e', 'v').fields(),
                      vesselId='v', observationSequence=2, flight=flight, engines=[engine], separations=[])
        service.publish(packet)
        result = publisher.publish.call_args.args[0]
        serialize_message(result)
        self.assertEqual(result.flight.applied_input_sequence, 7)
        self.assertEqual(result.engines[0].role, 'return_engine')
        self.assertEqual(result.engines[0].runtime_epoch, result.flight.runtime_epoch)
        service.publish(packet)
        self.assertEqual(publisher.publish.call_count, 1)
        packet['engines'][0]['enabled'] = 'false'
        service.latest = None
        service.publish(packet)
        self.assertEqual(publisher.publish.call_count, 1)
