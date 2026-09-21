"""Common identity and complete control snapshots; no implicit epoch stamping."""
import math

from .domain.session import SessionKey
from .packet_conversion import sanitize_ros_name
from .flight_packets import flight_state_from_packet
from .vehicle_packets import actuator_state_from_packet


def observation_fields(packet):
    key = SessionKey.from_packet(packet)
    sequence = packet.get('observationSequence')
    if type(sequence) is not int or not 0 <= sequence < 2**64:
        raise ValueError('invalid observation sequence')
    if not 0 <= key.generation < 2**64:
        raise ValueError('invalid runtime generation')
    if packet.get('vesselId') != key.vessel:
        raise ValueError('observation vessel mismatch')
    return dict(vessel_id=key.vessel, runtime_instance=key.instance,
                runtime_generation=key.generation, runtime_epoch=key.epoch,
                observation_sequence=sequence)


def control_snapshot_from_packet(packet):
    if packet.get('type') != 'pylon_control_snapshot' or packet.get('version') != 1:
        raise ValueError('unsupported control snapshot')
    identity = observation_fields(packet)
    envelope = SessionKey.from_packet(packet).fields()

    def member(raw, kind=None):
        if not isinstance(raw, dict):
            raise ValueError('snapshot member must be an object')
        if raw.get('vesselId') != identity['vessel_id'] or raw.get('observationSequence') != identity['observation_sequence']:
            raise ValueError('mixed observation in snapshot')
        if any(field in raw and raw[field] != value for field, value in envelope.items()):
            raise ValueError('mixed epoch in snapshot')
        value = dict(raw, **envelope)
        if kind is None:
            flight_state_from_packet(value)
        else:
            if actuator_state_from_packet(value)['actuatorType'] != kind:
                raise ValueError('wrong snapshot actuator kind')
            flags = ('enabled', 'operational', 'flameout', 'commandActive', 'gimbalAvailable', 'gimbalCommandActive') if kind == 'engine' else ('available', 'separated')
            for field in flags:
                if type(value.get(field)) is not bool:
                    raise ValueError(f'{field} must be boolean')
            scalars = ('universalTime', 'throttle', 'thrust', 'maxThrust', 'gimbalPitch', 'gimbalYaw', 'gimbalRoll') if kind == 'engine' else ('universalTime',)
            for field in scalars:
                number = value.get(field)
                if isinstance(number, bool) or not isinstance(number, (int, float)) or not math.isfinite(number):
                    raise ValueError(f'{field} must be finite')
            if not isinstance(value.get('name'), str) or not value['name'] or not isinstance(value.get('role', ''), str):
                raise ValueError('invalid actuator name or role')
        return value

    flight = member(packet.get('flight'))
    groups = []
    for field, kind in [('engines', 'engine'), ('separations', 'separation')]:
        values = packet.get(field)
        if not isinstance(values, list) or len(values) > 256:
            raise ValueError('invalid snapshot actuator list')
        parsed = [member(raw, kind) for raw in values]
        names = [sanitize_ros_name(raw['name'], kind) for raw in parsed]
        if len(set(names)) != len(names):
            raise ValueError('duplicate snapshot actuator')
        if any(raw['universalTime'] != flight['universalTime'] for raw in parsed):
            raise ValueError('mixed simulation time in snapshot')
        groups.append(parsed)
    return flight, *groups
