"""Operation-correlated separation receipts, independent of ROS and sockets."""

from collections import OrderedDict
from dataclasses import dataclass, replace
import hashlib
import math

from .packet_conversion import sanitize_ros_name


def _token(value, field):
    if (not isinstance(value, str) or not 1 <= len(value) <= 128
            or any(not 33 <= ord(char) <= 126 for char in value)):
        raise ValueError(f"invalid {field}")
    return value


def separation_operation_fields(message, session):
    if session is None:
        raise ValueError("no current session for separation operation")
    operation = getattr(message, "operation_id", "")
    if not operation:
        # Identical to the C# legacy adapter. Explicit IDs plus the original
        # identity are required for retries across epochs or replacement leases.
        text = "\n".join((message.controller_id, message.lease_id,
                          sanitize_ros_name(message.id, "actuator"), str(message.sequence)))
        operation = "legacy-" + hashlib.sha256(text.encode("utf-8")).hexdigest()
    return dict(
        operationId=_token(operation, "operation_id"),
        operationInstance=_token(getattr(message, "original_runtime_instance", "") or session.instance, "original_runtime_instance"),
        operationEpoch=_token(getattr(message, "original_runtime_epoch", "") or session.epoch, "original_runtime_epoch"),
        operationVesselId=_token(getattr(message, "original_vessel_id", "") or message.vessel_id, "original_vessel_id"),
    )


def separation_query(operation, instance, epoch, vessel):
    return dict(type="pylon_separation_query", version=1,
                operationId=_token(operation, "operation_id"),
                operationInstance=_token(instance, "original_runtime_instance"),
                operationEpoch=_token(epoch, "original_runtime_epoch"),
                operationVesselId=_token(vessel, "original_vessel_id"))


@dataclass(frozen=True)
class SeparationResultData:
    operation_id: str
    original_runtime_instance: str
    original_runtime_epoch: str
    original_vessel_id: str
    original_runtime_generation: int
    id: str
    controller_id: str
    sequence: int
    completed: bool
    success: bool
    retained: bool
    reason: str
    result_runtime_epoch: str
    result_runtime_generation: int
    active_vessel_id: str
    resulting_vessel_ids: tuple
    retention_remaining_sec: float

    @property
    def key(self):
        return (self.original_runtime_instance, self.original_runtime_epoch,
                self.original_vessel_id, self.operation_id)


def separation_result_from_packet(packet):
    if packet.get("type") != "pylon_separation_result" or type(packet.get("version")) is not int or packet["version"] != 1:
        raise ValueError("unsupported separation result")
    identity = [_token(packet.get(field), field) for field in
                ("operationId", "operationInstance", "operationEpoch", "operationVesselId")]
    for field in ("sequence", "originalGeneration", "resultGeneration"):
        if type(packet.get(field)) is not int or not 0 <= packet[field] < 2**64:
            raise ValueError(f"invalid {field}")
    for field in ("completed", "success", "retained"):
        if type(packet.get(field)) is not bool:
            raise ValueError(f"invalid {field}")
    for field in ("name", "controllerId", "reason", "resultEpoch", "activeVesselId"):
        if not isinstance(packet.get(field), str):
            raise ValueError(f"invalid {field}")
    remaining = packet.get("retentionRemainingSeconds")
    if (isinstance(remaining, bool) or not isinstance(remaining, (int, float))
            or not math.isfinite(remaining) or not 0 <= remaining <= 600):
        raise ValueError("invalid retentionRemainingSeconds")
    ids = packet.get("resultingVesselIds")
    if (not isinstance(ids, list) or len(ids) > 4096
            or any(not isinstance(value, str) or not value for value in ids)
            or len(ids) != len(set(ids))):
        raise ValueError("invalid resultingVesselIds")
    if packet["success"] and (not packet["completed"] or not packet["resultEpoch"]):
        raise ValueError("inconsistent successful separation result")
    return SeparationResultData(*identity, packet["originalGeneration"], packet["name"], packet["controllerId"],
                                packet["sequence"], packet["completed"], packet["success"], packet["retained"],
                                packet["reason"], packet["resultEpoch"], packet["resultGeneration"],
                                packet["activeVesselId"], tuple(ids), float(remaining))


class SeparationResultCache:
    """Bounded cache that survives epoch transitions and never regresses a receipt."""

    def __init__(self, capacity=128):
        if capacity < 1:
            raise ValueError("capacity must be positive")
        self.capacity = capacity
        self.entries = OrderedDict()

    def put(self, result, now):
        previous = self.get(result.key, now)
        if previous and previous.retained:
            if not result.retained or (previous.completed and not result.completed):
                return False
            if previous.completed and previous != result:
                # Remaining retention decreases on repeats; all outcome fields
                # must remain identical once an operation has completed.
                if replace(previous, retention_remaining_sec=result.retention_remaining_sec) != result:
                    return False
        self.entries[result.key] = (result, now + (result.retention_remaining_sec if result.retained else 1.0))
        self.entries.move_to_end(result.key)
        while len(self.entries) > self.capacity:
            self.entries.popitem(last=False)
        return True

    def get(self, key, now):
        entry = self.entries.get(key)
        if entry is None:
            return None
        result, expires = entry
        if now >= expires:
            del self.entries[key]
            return None
        return replace(result, retention_remaining_sec=max(0.0, expires - now)) if result.retained else result
