"""Strict flight truth and normalized stock-control wire contracts."""
import math

SCALARS = {
    'universal_time': 'universalTime', 'altitude_asl': 'altitudeAsl',
    'altitude_agl': 'altitudeAgl', 'latitude': 'latitude', 'longitude': 'longitude',
    'mass': 'mass', 'liquid_fuel': 'liquidFuel', 'oxidizer': 'oxidizer',
    'electric_charge': 'electricCharge', 'gravity': 'gravity',
    'body_radius': 'bodyRadius', 'gravitational_parameter': 'gravitationalParameter',
    'atmosphere_depth': 'atmosphereDepth', 'apoapsis': 'apoapsis',
    'periapsis': 'periapsis', 'time_to_apoapsis': 'timeToApoapsis',
    'vertical_speed': 'verticalSpeed', 'horizontal_speed': 'horizontalSpeed',
    'dynamic_pressure': 'dynamicPressure',
}
VECTORS = {
    'up_body': 'upBody', 'east_body': 'eastBody', 'north_body': 'northBody',
    'surface_velocity_body': 'surfaceVelocityBody',
    'orbital_velocity_body': 'orbitalVelocityBody',
    'angular_velocity_body': 'angularVelocityBody',
}


def finite(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError('flight values must be finite numbers')
    return float(value)


def flight_state_from_packet(packet):
    if packet.get('type') != 'pylon_flight_state' or packet.get('version') != 1:
        raise ValueError('unsupported flight state')
    state = {field: finite(packet.get(key)) for field, key in SCALARS.items()}
    for field, key in VECTORS.items():
        value = packet.get(key)
        if not isinstance(value, (tuple, list)) or len(value) != 3:
            raise ValueError(f'{key} requires three values')
        state[field] = tuple(finite(v) for v in value)
    for field, key in [('vessel_id', 'vesselId'), ('body_name', 'bodyName')]:
        value = packet.get(key)
        if not isinstance(value, str) or not value:
            raise ValueError(f'{key} is required')
        state[field] = value
    for field in ('landed', 'splashed'):
        if not isinstance(packet.get(field), bool):
            raise ValueError(f'{field} must be boolean')
        state[field] = packet[field]
    if state['mass'] <= 0 or state['gravity'] <= 0 or state['body_radius'] <= 0:
        raise ValueError('invalid physical flight state')
    if 'appliedInputValid' in packet:
        for field, key in [('applied_input_valid', 'appliedInputValid'),
                           ('flight_command_active', 'flightCommandActive'), ('input_at_limit', 'inputAtLimit')]:
            if type(packet.get(key)) is not bool:
                raise ValueError(f'{key} must be boolean')
            state[field] = packet[key]
        for field, key in [('applied_pitch', 'appliedPitch'), ('applied_yaw', 'appliedYaw'),
                           ('applied_roll', 'appliedRoll'), ('applied_input_age', 'appliedInputAge')]:
            state[field] = finite(packet.get(key))
        sequence = packet.get('appliedInputSequence')
        if type(sequence) is not int or not 0 <= sequence < 2**63:
            raise ValueError('invalid applied input sequence')
        if state['applied_input_age'] < 0 or any(abs(state[k]) > 1 for k in ('applied_pitch', 'applied_yaw', 'applied_roll')):
            raise ValueError('invalid applied input feedback')
        state['applied_input_sequence'] = sequence
    return state


def flight_control_command(message):
    values = {key: finite(getattr(message, key)) for key in ('pitch', 'yaw', 'roll')}
    if any(abs(value) > 1 for value in values.values()):
        raise ValueError('flight inputs must be in [-1, 1]')
    timeout = finite(message.timeout_sec)
    if not 0.05 <= timeout <= 1.0:
        raise ValueError('flight timeout must be in [0.05, 1.0]')
    if not all((message.vessel_id, message.controller_id, message.lease_id)) or message.sequence <= 0:
        raise ValueError('flight control requires a lease and positive sequence')
    return dict(type='pylon_flight_control_command', version=1,
                vesselId=message.vessel_id, controllerId=message.controller_id,
                leaseId=message.lease_id, sequence=int(message.sequence),
                landingGear=bool(message.landing_gear), timeoutSeconds=timeout, **values)
