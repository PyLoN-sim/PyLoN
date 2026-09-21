"""ROS adapter for separation receipts and read-only result queries."""

from dataclasses import fields
import time

from pylon_interfaces.msg import SeparationResult
from pylon_interfaces.srv import GetSeparationResult
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy

from ..separation_packets import SeparationResultCache, separation_query, separation_result_from_packet


class SeparationResultsService:
    def __init__(self, bridge):
        self.bridge = bridge
        self.cache = SeparationResultCache()
        qos = QoSProfile(depth=128)
        qos.reliability = ReliabilityPolicy.RELIABLE
        qos.durability = DurabilityPolicy.TRANSIENT_LOCAL
        prefix = f"{bridge.actuators_prefix}/separation"
        self.publisher = bridge.create_publisher(SeparationResult, f"{prefix}/result", qos)
        self.service = bridge.create_service(GetSeparationResult, f"{prefix}/get_result", self.get_result)

    def message(self, result):
        message = SeparationResult()
        message.header.stamp = self.bridge.get_clock().now().to_msg()
        for field in fields(result):
            value = getattr(result, field.name)
            setattr(message, field.name, list(value) if isinstance(value, tuple) else value)
        return message

    def publish_result(self, packet):
        try:
            result = separation_result_from_packet(packet)
        except ValueError as exc:
            self.bridge.get_logger().warning(f"Dropped invalid separation result: {exc}")
            return
        if self.cache.put(result, time.monotonic()):
            self.publisher.publish(self.message(result))

    def get_result(self, request, response):
        try:
            command = separation_query(request.operation_id, request.original_runtime_instance,
                                       request.original_runtime_epoch, request.original_vessel_id)
            key = (request.original_runtime_instance, request.original_runtime_epoch,
                   request.original_vessel_id, request.operation_id)
            result = self.cache.get(key, time.monotonic())
            if result is not None:
                response.found = result.retained
                response.reason = result.reason
                response.result = self.message(result)
                if result.completed:
                    return response
                # A final UDP receipt may have been lost after the pending one.
                # Query again instead of returning a cached pending state forever.
            self.bridge.connection.send_command(command)
            response.query_sent = True
            response.reason = "query_sent"
        except (OSError, ValueError) as exc:
            response.reason = str(exc)
        return response
