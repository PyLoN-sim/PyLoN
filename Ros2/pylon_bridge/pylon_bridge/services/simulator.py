"""Publish simulator heartbeats without treating paused simulation time as packet loss."""

from dataclasses import fields
import time

from pylon_interfaces.msg import SimulatorState
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy

from ..simulator_packets import SimulatorObservation, SimulatorTracker


class SimulatorService:
    def __init__(self, bridge):
        self.bridge = bridge
        self.tracker = SimulatorTracker()
        qos = QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE,
                         durability=DurabilityPolicy.TRANSIENT_LOCAL)
        self.publisher = bridge.create_publisher(
            SimulatorState, f'{bridge.topic_prefix}/simulator/state', qos)

    def observe(self, packet):
        # Older v1 plugins still establish a flight session; they do not claim
        # the new explicit simulator-state contract.
        if 'observationSequence' not in packet:
            return
        try:
            state = self.tracker.observe(packet, time.monotonic())
        except ValueError as exc:
            self.bridge.get_logger().warning(f'Invalid simulator heartbeat: {exc}')
            return
        if state is not None:
            self.publish(state)

    def expire(self):
        state = self.tracker.expire(time.monotonic(), self.bridge.args.topic_timeout_sec)
        if state is not None:
            self.publish(state)

    def publish(self, state):
        message = SimulatorState()
        message.header.stamp = self.bridge.get_clock().now().to_msg()
        for field in fields(SimulatorObservation):
            setattr(message, field.name, getattr(state, field.name))
        self.publisher.publish(message)
