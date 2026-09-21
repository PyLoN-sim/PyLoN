"""Validate a complete ordered batch before forwarding any of its operations."""
from copy import copy
import math
import json

from .flight_packets import flight_control_command
from .vehicle_packets import actuator_command
from .packet_conversion import sanitize_ros_name
from .separation_packets import separation_operation_fields


def control_batch_command(message, session):
    if (not all((message.vessel_id, message.controller_id, message.lease_id))
            or not 0 < message.sequence < 2**63):
        raise ValueError('batch requires identity and a positive int64 sequence')
    duration = float(message.lease_duration_sec)
    if message.renew_lease and (not math.isfinite(duration) or not .1 <= duration <= 10.):
        raise ValueError('batch lease duration must be in [0.1, 10]')
    if len(message.engines) > 16:
        raise ValueError('batch supports at most 16 engines')

    def identified(original):
        value = copy(original)
        for field in ('vessel_id', 'controller_id', 'lease_id', 'sequence'):
            setattr(value, field, getattr(message, field))
        return value

    engines = []
    names = set()
    for original in message.engines:
        engine = identified(original)
        if not engine.id or sanitize_ros_name(engine.id, 'engine') in names:
            raise ValueError('batch engine IDs must be nonempty and unique')
        names.add(sanitize_ros_name(engine.id, 'engine'))
        if not math.isfinite(engine.timeout_sec) or not .05 <= engine.timeout_sec <= 1.:
            raise ValueError('batch engine timeout must be in [0.05, 1]')
        if not math.isfinite(engine.target_thrust) or engine.target_thrust < 0:
            raise ValueError('batch engine thrust must be finite and nonnegative')
        engines.append(actuator_command('engine', engine.id, dict(
            enabled=engine.enabled, targetThrust=engine.target_thrust,
            hasGimbalCommand=engine.has_gimbal_command, gimbalPitch=engine.gimbal_pitch,
            gimbalYaw=engine.gimbal_yaw, gimbalRoll=engine.gimbal_roll,
            timeoutSeconds=engine.timeout_sec), engine.sequence, engine.vessel_id,
            engine.controller_id, engine.lease_id))
    result = dict(type='pylon_control_batch', version=1,
                  vesselId=message.vessel_id, controllerId=message.controller_id,
                  leaseId=message.lease_id, sequence=int(message.sequence),
                  renewLease=bool(message.renew_lease), leaseDurationSeconds=duration,
                  suppressSas=bool(message.suppress_sas), hasFlight=bool(message.has_flight),
                  engines=engines, hasSeparation=bool(message.has_separation))
    if message.has_flight:
        result['flight'] = flight_control_command(identified(message.flight))
    if message.has_separation:
        separation = identified(message.separation)
        if not separation.id or not separation.separate:
            raise ValueError('batch separation requires ID and separate=true')
        result['separation'] = actuator_command('separation', separation.id,
            {'separate': True}, separation.sequence, separation.vessel_id,
            separation.controller_id, separation.lease_id)
        result['separation'].update(separation_operation_fields(separation, session))
    # KSP's Unity serializer omits nested command objects. Keep one atomic UDP
    # envelope, but encode each member as JSON text for explicit decoding.
    result['engineJson'] = [json.dumps(value, separators=(',', ':'), allow_nan=False)
                            for value in result.pop('engines')]
    for field in ('flight', 'separation'):
        if field in result:
            result[field+'Json'] = json.dumps(result.pop(field), separators=(',', ':'), allow_nan=False)
    return result
