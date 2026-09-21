"""Serializable coast checkpoints and conservative, side-effect-free resume checks.

Inputs may be generated ROS messages or objects with equivalent attributes. This
module never loads a save, sends commands, or restores/reuses a control lease.
"""

from dataclasses import asdict, dataclass, fields
import math


def _text(value, label, allow_empty=False):
    if not isinstance(value, str) or len(value) > 128 or (not value and not allow_empty):
        raise ValueError(f'invalid_{label}')
    return value


def _number(value, label, nonnegative=True):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f'invalid_{label}')
    if nonnegative and value < 0:
        raise ValueError(f'invalid_{label}')
    return float(value)


def _uint(value, label):
    if type(value) is not int or not 0 <= value < 2**64:
        raise ValueError(f'invalid_{label}')
    return value


def _ids(values, label, limit=256):
    if not isinstance(values, (list, tuple)) or len(values) > limit:
        raise ValueError(f'invalid_{label}')
    normalized = tuple(_text(value, label) for value in values)
    if len(set(normalized)) != len(normalized):
        raise ValueError(f'duplicate_{label}')
    return tuple(sorted(normalized))


def _identity(message):
    return (_text(message.runtime_instance, 'runtime_instance'),
            _uint(message.runtime_generation, 'runtime_generation'),
            _text(message.runtime_epoch, 'runtime_epoch'),
            _text(message.vessel_id, 'vessel_id'))


@dataclass(frozen=True)
class ResumePolicy:
    mass_tolerance_kg: float = 5.0
    fuel_tolerance: float = 0.2
    oxidizer_tolerance: float = 0.3
    electric_charge_tolerance: float = 5.0
    minimum_electric_charge: float = 0.1
    orbit_tolerance_m: float = 50.0
    maximum_thrust_n: float = 1.0
    maximum_throttle: float = 0.001
    maximum_sample_skew_sec: float = 0.5

    def __post_init__(self):
        for field in fields(self):
            _number(getattr(self, field.name), field.name)


@dataclass(frozen=True)
class ResumeValidation:
    allowed: bool
    reason: str


@dataclass(frozen=True)
class MissionCheckpoint:
    runtime_instance: str
    runtime_generation: int
    runtime_epoch: str
    vessel_id: str
    observation_sequence: int
    universal_time: float
    body_name: str
    body_radius: float
    gravitational_parameter: float
    atmosphere_depth: float
    apoapsis: float
    periapsis: float
    mass: float
    liquid_fuel: float
    oxidizer: float
    electric_charge: float
    engine_ids: tuple
    separator_ids: tuple
    pending_operation_ids: tuple
    controller_id: str
    previous_lease_id: str
    version: int = 1

    def __post_init__(self):
        if type(self.version) is not int or self.version != 1:
            raise ValueError('unsupported_checkpoint_version')
        for name in ('runtime_instance', 'runtime_epoch', 'vessel_id', 'body_name'):
            _text(getattr(self, name), name)
        for name in ('controller_id', 'previous_lease_id'):
            _text(getattr(self, name), name, allow_empty=True)
        for name in ('runtime_generation', 'observation_sequence'):
            _uint(getattr(self, name), name)
        for name in ('universal_time', 'body_radius', 'gravitational_parameter', 'atmosphere_depth',
                     'apoapsis', 'periapsis', 'mass', 'liquid_fuel', 'oxidizer', 'electric_charge'):
            _number(getattr(self, name), name)
        if min(self.mass, self.body_radius, self.gravitational_parameter) <= 0:
            raise ValueError('invalid_checkpoint_physics')
        for name in ('engine_ids', 'separator_ids', 'pending_operation_ids'):
            normalized = _ids(getattr(self, name), name, 128 if name == 'pending_operation_ids' else 256)
            object.__setattr__(self, name, normalized)

    @property
    def identity(self):
        return self.runtime_instance, self.runtime_generation, self.runtime_epoch, self.vessel_id

    @classmethod
    def capture(cls, flight, simulator, engines, separators, authority,
                pending_operation_ids=(), *, policy=ResumePolicy()):
        """Capture a known unpowered orbit, including while paused or stale.

        Capturing does not assert that resuming is currently safe. Caller must
        supply cached states from one epoch and call validate_resume on fresh
        observations before acquiring a new lease.
        """
        try:
            engines, separators = list(engines), list(separators)
            _consistent_observations(flight, simulator, engines, separators, policy)
            _safe_orbit(flight)
            _quiet_engines(engines, policy)
            if authority is None or authority.vessel_id != flight.vessel_id:
                raise ValueError('authority_vessel_mismatch')
            return cls(
                runtime_instance=flight.runtime_instance, runtime_generation=flight.runtime_generation,
                runtime_epoch=flight.runtime_epoch, vessel_id=flight.vessel_id,
                observation_sequence=flight.observation_sequence, universal_time=flight.universal_time,
                body_name=flight.body_name, body_radius=flight.body_radius,
                gravitational_parameter=flight.gravitational_parameter, atmosphere_depth=flight.atmosphere_depth,
                apoapsis=flight.apoapsis, periapsis=flight.periapsis, mass=flight.mass,
                liquid_fuel=flight.liquid_fuel, oxidizer=flight.oxidizer,
                electric_charge=flight.electric_charge,
                engine_ids=tuple(engine.id for engine in engines),
                separator_ids=tuple(separator.id for separator in separators),
                pending_operation_ids=tuple(pending_operation_ids),
                controller_id=authority.controller_id, previous_lease_id=authority.lease_id)
        except (AttributeError, TypeError) as exc:
            raise ValueError('checkpoint_observation_missing') from exc

    def to_dict(self):
        data = asdict(self)
        for name in ('engine_ids', 'separator_ids', 'pending_operation_ids'):
            data[name] = list(data[name])
        return data

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict) or set(value) != {field.name for field in fields(cls)}:
            raise ValueError('invalid_checkpoint_schema')
        return cls(**value)


def _consistent_observations(flight, simulator, engines, separators, policy):
    if flight is None or simulator is None:
        raise ValueError('checkpoint_observation_missing')
    identity = _identity(flight)
    ut = _number(flight.universal_time, 'universal_time')
    if not engines or len(engines) > 256 or len(separators) > 256:
        raise ValueError('invalid_actuator_configuration')
    for message in [simulator, *engines, *separators]:
        if _identity(message) != identity:
            raise ValueError('observation_identity_mismatch')
        _uint(message.observation_sequence, 'observation_sequence')
        timestamp = _number(message.universal_time, 'observation_time')
        if abs(timestamp - ut) > policy.maximum_sample_skew_sec:
            raise ValueError('observation_time_mismatch')
    _uint(flight.observation_sequence, 'observation_sequence')
    if any(item.observation_sequence != flight.observation_sequence for item in [*engines, *separators]):
        raise ValueError('observation_frame_mismatch')
    _ids(tuple(engine.id for engine in engines), 'engine_ids')
    _ids(tuple(separator.id for separator in separators), 'separator_ids')


def _safe_orbit(flight):
    atmosphere = _number(flight.atmosphere_depth, 'atmosphere_depth')
    altitude = _number(flight.altitude_asl, 'altitude_asl')
    periapsis = _number(flight.periapsis, 'periapsis')
    pressure = _number(flight.dynamic_pressure, 'dynamic_pressure')
    if type(flight.landed) is not bool or type(flight.splashed) is not bool:
        raise ValueError('invalid_surface_state')
    if flight.landed or flight.splashed or min(altitude, periapsis) <= atmosphere or pressure != 0:
        raise ValueError('requires_unpowered_vacuum_orbit')


def _quiet_engines(engines, policy):
    for engine in engines:
        if (type(engine.flameout) is not bool or engine.flameout
                or _number(engine.thrust, 'engine_thrust') > policy.maximum_thrust_n
                or _number(engine.throttle, 'engine_throttle') > policy.maximum_throttle):
            raise ValueError('engine_not_quiescent')


def validate_resume(checkpoint, flight, simulator, engines, separators, authority, *,
                    now_monotonic, received_at, max_sample_age_sec=0.6,
                    allowed_controller_id='', allowed_lease_id='', resolved_operation_ids=(),
                    policy=ResumePolicy()):
    """Validate last-known checkpoint against fresh observations; never acquire.

    received_at must be the oldest monotonic receipt among ALL supplied flight,
    simulator, authority, engine and separator observations. Callers can approve
    an explicitly acquired new lease, but cannot reuse the checkpoint's lease.
    """
    try:
        if not isinstance(checkpoint, MissionCheckpoint):
            raise ValueError('invalid_checkpoint')
        now = _number(now_monotonic, 'monotonic_time')
        receipt = _number(received_at, 'receipt_time')
        maximum_age = _number(max_sample_age_sec, 'sample_timeout')
        if maximum_age <= 0 or receipt > now or now - receipt >= maximum_age:
            raise ValueError('telemetry_stale')
        resolved = _ids(tuple(resolved_operation_ids), 'resolved_operation_ids', 128)
        if set(checkpoint.pending_operation_ids) - set(resolved):
            raise ValueError('pending_operations_unresolved')
        if simulator is None:
            raise ValueError('simulator_unavailable')
        for name in ('communication_alive', 'paused', 'packed', 'control_available', 'simulation_advancing'):
            if type(getattr(simulator, name)) is not bool:
                raise ValueError('invalid_simulator_state')
        if type(simulator.state) is not int or not 0 <= simulator.state <= 5:
            raise ValueError('invalid_simulator_state')
        if not simulator.communication_alive:
            raise ValueError('simulator_unavailable')
        if simulator.paused:
            raise ValueError('simulator_paused')
        if simulator.packed:
            raise ValueError('simulator_packed')
        if not simulator.control_available:
            raise ValueError('simulator_unavailable')
        if abs(_number(simulator.warp_rate, 'warp_rate') - 1.) > 1e-6:
            raise ValueError('simulator_warping')
        if simulator.state != 1 or not simulator.simulation_advancing:
            raise ValueError('simulator_not_advancing')
        if _identity(flight) != checkpoint.identity:
            raise ValueError('checkpoint_identity_changed')
        if flight.observation_sequence <= checkpoint.observation_sequence or flight.universal_time <= checkpoint.universal_time:
            raise ValueError('fresh_post_checkpoint_observation_required')
        engines, separators = list(engines), list(separators)
        _consistent_observations(flight, simulator, engines, separators, policy)
        if (tuple(sorted(engine.id for engine in engines)) != checkpoint.engine_ids
                or tuple(sorted(separator.id for separator in separators)) != checkpoint.separator_ids):
            raise ValueError('actuator_configuration_changed')
        _safe_orbit(flight)
        _quiet_engines(engines, policy)
        if (flight.body_name != checkpoint.body_name or flight.body_radius != checkpoint.body_radius
                or flight.gravitational_parameter != checkpoint.gravitational_parameter
                or flight.atmosphere_depth != checkpoint.atmosphere_depth):
            raise ValueError('body_changed')
        for name, tolerance in [('mass', policy.mass_tolerance_kg), ('liquid_fuel', policy.fuel_tolerance),
                                ('oxidizer', policy.oxidizer_tolerance),
                                ('electric_charge', policy.electric_charge_tolerance),
                                ('apoapsis', policy.orbit_tolerance_m), ('periapsis', policy.orbit_tolerance_m)]:
            if abs(_number(getattr(flight, name), name) - getattr(checkpoint, name)) > tolerance:
                raise ValueError(f'{name}_changed')
        if flight.electric_charge <= policy.minimum_electric_charge:
            raise ValueError('power_unavailable')
        if authority is None or authority.vessel_id != checkpoint.vessel_id:
            raise ValueError('authority_vessel_mismatch')
        if type(authority.state) is not int or type(authority.emergency_stop) is not bool:
            raise ValueError('invalid_authority_state')
        if authority.emergency_stop or authority.state == 2:
            raise ValueError('emergency_stop_active')
        if authority.state != 0:
            if authority.lease_id == checkpoint.previous_lease_id:
                raise ValueError('authority_not_released')
            if (authority.state != 1 or not allowed_controller_id or not allowed_lease_id
                    or authority.controller_id != allowed_controller_id or authority.lease_id != allowed_lease_id):
                raise ValueError('authority_conflict')
        return ResumeValidation(True, 'ready_for_new_lease')
    except ValueError as exc:
        return ResumeValidation(False, str(exc))
    except (AttributeError, TypeError):
        return ResumeValidation(False, 'checkpoint_observation_missing')
