"""ROS adaptation of complete flight observations."""
from pylon_interfaces.msg import ControlSnapshot, FlightState, EngineState, SeparationState
from ..observations import observation_fields, control_snapshot_from_packet
from ..flight_packets import flight_state_from_packet, VECTORS
from ..vehicle_packets import actuator_state_from_packet


def fill_identity(message, packet):
    for field, value in observation_fields(packet).items():
        setattr(message, field, value)


def flight_message(packet, stamp):
    message = FlightState()
    message.header.stamp, message.header.frame_id = stamp, 'base_link'
    fill_identity(message, packet)
    for field, value in flight_state_from_packet(packet).items():
        if field in VECTORS:
            getattr(message, field).x, getattr(message, field).y, getattr(message, field).z = value
        else:
            setattr(message, field, value)
    return message


def actuator_message(packet, stamp, kind):
    values = actuator_state_from_packet(packet)
    message = EngineState() if kind == 'engine' else SeparationState()
    message.header.stamp, message.header.frame_id = stamp, 'base_link'
    fill_identity(message, packet)
    message.id = message.name = values['name']
    message.universal_time = float(packet['universalTime'])
    message.role = str(packet.get('role', ''))
    if kind == 'engine':
        fields = {'enabled':'enabled', 'operational':'operational', 'flameout':'flameout',
                  'throttle':'throttle', 'thrust':'thrust', 'max_thrust':'maxThrust',
                  'command_active':'commandActive', 'gimbal_available':'gimbalAvailable',
                  'gimbal_command_active':'gimbalCommandActive', 'gimbal_pitch':'gimbalPitch',
                  'gimbal_yaw':'gimbalYaw', 'gimbal_roll':'gimbalRoll'}
    else:
        fields = {'mechanism':'mechanism', 'available':'available', 'separated':'separated'}
    for field, key in fields.items():
        setattr(message, field, values[key])
    return message


class SnapshotService:
    def __init__(self, bridge):
        self.bridge = bridge
        self.latest = None
        self.publisher = bridge.create_publisher(ControlSnapshot, f'{bridge.topic_prefix}/control/snapshot', 10) if bridge.ground_truth_enabled else None

    def publish(self, packet):
        if self.publisher is None:
            return
        try:
            flight, engines, separations = control_snapshot_from_packet(packet)
            key = (packet['runtimeInstance'], packet['runtimeEpoch'])
            sequence = packet['observationSequence']
            if self.latest is not None and self.latest[0] == key and sequence <= self.latest[1]:
                return
            stamp = self.bridge.flight.stamp_for_universal_time(flight['universalTime'])
            message = ControlSnapshot(flight=flight_message(flight, stamp),
                engines=[actuator_message(value, stamp, 'engine') for value in engines],
                separations=[actuator_message(value, stamp, 'separation') for value in separations])
            message.header = message.flight.header
        except (ValueError, KeyError) as exc:
            self.bridge.get_logger().warning(f'Invalid control snapshot: {exc}')
            return
        self.latest = key, sequence
        self.publisher.publish(message)
