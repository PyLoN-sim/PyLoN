"""Explicit simulator health, independent of ROS and the sensor sample clocks."""

from dataclasses import dataclass, replace
import math

from .domain.session import SessionKey
from .protocol import SESSION_PACKET_TYPE

INITIALIZING, ADVANCING, PAUSED, STALLED, UNAVAILABLE, STALE = range(6)


def simulator_state_from_packet(packet):
    if packet.get('type') != SESSION_PACKET_TYPE or type(packet.get('version')) is not int or packet['version'] != 1:
        raise ValueError('unsupported simulator heartbeat')
    identity = SessionKey.from_packet(packet)
    if identity.generation >= 2**64:
        raise ValueError('simulator generation exceeds uint64')
    if packet.get('vesselId') != identity.vessel:
        raise ValueError('simulator vessel identity mismatch')
    observation = packet.get('observationSequence')
    if type(observation) is not int or not 0 <= observation < 2**64:
        raise ValueError('invalid simulator observation sequence')
    fields = dict(vessel_id=identity.vessel, runtime_instance=identity.instance,
                  runtime_epoch=identity.epoch, runtime_generation=identity.generation,
                  observation_sequence=observation)
    for field, key in [('universal_time', 'universalTime'),
                       ('realtime_since_startup', 'realtimeSinceStartup'),
                       ('warp_rate', 'warpRate')]:
        value = packet.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(f'{key} must be finite')
        if field != 'universal_time' and value < 0:
            raise ValueError(f'{key} must be nonnegative')
        fields[field] = float(value)
    for field, key in [('paused', 'paused'), ('packed', 'packed'),
                       ('physics_warp', 'physicsWarp'), ('control_available', 'available')]:
        if type(packet.get(key)) is not bool:
            raise ValueError(f'{key} must be boolean')
        fields[field] = packet[key]
    if fields['control_available'] and (not identity.vessel or fields['packed']):
        raise ValueError('inconsistent simulator control availability')
    return SimulatorObservation(**fields)


@dataclass(frozen=True)
class SimulatorObservation:
    vessel_id: str
    runtime_instance: str
    runtime_epoch: str
    runtime_generation: int
    observation_sequence: int
    universal_time: float
    realtime_since_startup: float
    warp_rate: float
    paused: bool
    packed: bool
    physics_warp: bool
    control_available: bool
    state: int = INITIALIZING
    communication_alive: bool = True
    simulation_advancing: bool = False
    seconds_since_progress: float = 0.0
    heartbeat_age_sec: float = 0.0

    @property
    def identity(self):
        return (self.runtime_instance, self.runtime_generation, self.runtime_epoch, self.vessel_id)


class SimulatorTracker:
    """Compare producer-clock observations; never infer pause from missing packets."""

    def __init__(self, stall_timeout=0.5):
        if not math.isfinite(stall_timeout) or stall_timeout <= 0:
            raise ValueError('stall timeout must be positive')
        self.stall_timeout = stall_timeout
        self.latest = None
        self.last_progress = 0.0
        self.last_seen = None

    def observe(self, packet, received_at):
        current = simulator_state_from_packet(packet)
        previous = self.latest
        same_session = previous is not None and current.identity == previous.identity
        if same_session and (current.observation_sequence <= previous.observation_sequence
                             or current.realtime_since_startup < previous.realtime_since_startup
                             or current.universal_time < previous.universal_time):
            return None
        reset = (not same_session or not previous.communication_alive
                 or current.paused != previous.paused)
        progressing = (not reset and not current.paused
                       and current.universal_time > previous.universal_time)
        if reset or progressing or current.paused:
            self.last_progress = current.realtime_since_startup
        age = max(0.0, current.realtime_since_startup - self.last_progress)
        if not current.vessel_id:
            state = UNAVAILABLE
        elif current.paused:
            state = PAUSED
        elif progressing:
            state = ADVANCING
        elif age >= self.stall_timeout:
            state = STALLED
        else:
            state = INITIALIZING
        self.latest = replace(current, state=state, simulation_advancing=progressing,
                              seconds_since_progress=age)
        self.last_seen = received_at
        return self.latest

    def expire(self, now, timeout):
        if self.latest is None or not self.latest.communication_alive:
            return None
        age = max(0.0, now - self.last_seen)
        if age < timeout:
            return None
        self.latest = replace(self.latest, communication_alive=False, state=STALE,
                              simulation_advancing=False, heartbeat_age_sec=age)
        return self.latest
