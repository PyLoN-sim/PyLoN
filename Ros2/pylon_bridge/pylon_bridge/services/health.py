"""Read-only diagnostic telemetry, independent of optional navigation truth."""

from pylon_interfaces.msg import PartThermalState, VehicleHealth
from rclpy.qos import QoSProfile, ReliabilityPolicy

from ..health_packets import ChargeRateEstimator, health_identity, part_thermal_state_from_packet


class HealthService:
    def __init__(self, bridge):
        self.bridge = bridge
        self.charge = ChargeRateEstimator()
        self.part_observations = {}
        self.part_identity = None
        qos = QoSProfile(depth=100, reliability=ReliabilityPolicy.BEST_EFFORT)
        self.power_publisher = bridge.create_publisher(
            VehicleHealth, f'{bridge.topic_prefix}/health/power', qos)
        self.thermal_publisher = bridge.create_publisher(
            PartThermalState, f'{bridge.topic_prefix}/health/thermal', qos)

    def publish_power(self, packet):
        try:
            state = self.charge.observe(packet)
        except ValueError as exc:
            self.bridge.get_logger().warning(f'Invalid vehicle health: {exc}')
            return
        if state is not None:
            self.publish(VehicleHealth, self.power_publisher, state)

    def publish_thermal(self, packet):
        try:
            state = part_thermal_state_from_packet(packet)
        except ValueError as exc:
            self.bridge.get_logger().warning(f'Invalid part thermals: {exc}')
            return
        identity = health_identity(state)
        if identity != self.part_identity:
            self.part_observations.clear()
            self.part_identity = identity
        part = state['part_flight_id']
        sequence = state['observation_sequence']
        if sequence <= self.part_observations.get(part, -1):
            return
        self.part_observations[part] = sequence
        self.publish(PartThermalState, self.thermal_publisher, state)

    def publish(self, message_type, publisher, state):
        message = message_type()
        message.header.stamp = self.bridge.flight.stamp_for_universal_time(state['universal_time'])
        for key, value in state.items():
            setattr(message, key, value)
        publisher.publish(message)
