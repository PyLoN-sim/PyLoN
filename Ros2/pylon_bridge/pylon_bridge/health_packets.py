"""Part thermals and explicit-quality electrical storage observations."""

import math

from .domain.session import SessionKey


def _number(packet, key, nonnegative=True):
    value = packet.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f'{key} must be finite')
    if nonnegative and value < 0:
        raise ValueError(f'{key} must be nonnegative')
    return float(value)


def _uint(packet, key, bits):
    value = packet.get(key)
    if type(value) is not int or not 0 <= value < 2**bits:
        raise ValueError(f'{key} must be uint{bits}')
    return value


def _base(packet, kind):
    if packet.get('type') != kind or type(packet.get('version')) is not int or packet['version'] != 1:
        raise ValueError('unsupported vehicle health packet')
    session = SessionKey.from_packet(packet)
    if not session.vessel or packet.get('vesselId') != session.vessel:
        raise ValueError('invalid health vessel identity')
    return dict(vessel_id=session.vessel, runtime_instance=session.instance,
                runtime_epoch=session.epoch,
                runtime_generation=_uint(packet, 'runtimeGeneration', 64),
                observation_sequence=_uint(packet, 'observationSequence', 64),
                universal_time=_number(packet, 'universalTime', nonnegative=False),
                electric_charge=_number(packet, 'electricCharge'),
                electric_capacity=_number(packet, 'electricCapacity'))


def vehicle_health_from_packet(packet):
    return _base(packet, 'pylon_vehicle_health')


def part_thermal_state_from_packet(packet):
    state = _base(packet, 'pylon_part_thermal_state')
    state.update(part_flight_id=_uint(packet, 'partFlightId', 32),
                 part_persistent_id=_uint(packet, 'partPersistentId', 32))
    name = packet.get('partName')
    if not isinstance(name, str) or not name:
        raise ValueError('partName is required')
    state['part_name'] = name
    for field, key in [('temperature', 'temperature'), ('max_temperature', 'maxTemperature'),
                       ('skin_temperature', 'skinTemperature'), ('max_skin_temperature', 'maxSkinTemperature')]:
        state[field] = _number(packet, key)
    if type(packet.get('shieldedFromAirstream')) is not bool:
        raise ValueError('shieldedFromAirstream must be boolean')
    state['shielded_from_airstream'] = packet['shieldedFromAirstream']
    return state


def health_identity(state):
    return tuple(state[key] for key in ('runtime_instance', 'runtime_generation', 'runtime_epoch', 'vessel_id'))


class ChargeRateEstimator:
    """Storage slope only; never reports separate generator/load measurements."""

    def __init__(self):
        self.previous = None

    def observe(self, packet):
        state = vehicle_health_from_packet(packet)
        previous = self.previous
        same = previous is not None and health_identity(previous) == health_identity(state)
        if same and (state['observation_sequence'] <= previous['observation_sequence']
                     or state['universal_time'] < previous['universal_time']):
            return None
        estimate, valid, interval = 0., False, 0.
        if same and state['electric_capacity'] == previous['electric_capacity']:
            delta = state['universal_time'] - previous['universal_time']
            if delta > 1e-6:
                estimate = (state['electric_charge'] - previous['electric_charge']) / delta
                valid = math.isfinite(estimate)
                interval = delta
        self.previous = state
        return dict(state, net_charge_rate_estimate=estimate if valid else 0.,
                    net_charge_rate_valid=valid, rate_sample_interval_sec=interval,
                    generation_rate=0., generation_rate_valid=False,
                    consumption_rate=0., consumption_rate_valid=False)
