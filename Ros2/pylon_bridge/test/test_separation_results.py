import dataclasses
from types import SimpleNamespace
import unittest

from pylon_bridge.application.runtime import BridgeRuntime
from pylon_bridge.domain.session import SessionKey
from pylon_bridge.protocol import encode_datagram
from pylon_bridge.separation_packets import (
    SeparationResultCache, separation_operation_fields,
    separation_query, separation_result_from_packet,
)


def result_packet(**changes):
    packet = dict(type="pylon_separation_result", version=1,
                  operationId="deploy-satellite", operationInstance="process", operationEpoch="before",
                  operationVesselId="launcher", originalGeneration=1, name="satellite_decoupler",
                  controllerId="mission", sequence=17, completed=True, success=True, retained=True,
                  reason="separated", resultEpoch="after", resultGeneration=2,
                  activeVesselId="launcher", resultingVesselIds=["launcher", "satellite"],
                  retentionRemainingSeconds=600.0)
    packet.update(changes)
    return packet


def heartbeat(epoch="before", generation=1):
    return dict(type="pylon_session", version=1, runtimeInstance="process", runtimeEpoch=epoch,
                runtimeGeneration=generation, runtimeVesselId="launcher", vesselId="launcher",
                vesselName="Launcher", available=True, universalTime=100.0 + generation)


class SeparationResultTests(unittest.TestCase):
    def test_result_keeps_original_identity_and_all_resulting_vessels(self):
        result = separation_result_from_packet(result_packet())
        self.assertEqual(result.key, ("process", "before", "launcher", "deploy-satellite"))
        self.assertEqual(result.result_runtime_epoch, "after")
        self.assertEqual(result.resulting_vessel_ids, ("launcher", "satellite"))
        self.assertTrue(result.success)

    def test_invalid_receipt_cannot_invent_success(self):
        for changes in (dict(completed=False), dict(resultEpoch=""), dict(sequence=True),
                        dict(success="true"), dict(retained=1), dict(resultingVesselIds=["same", "same"]),
                        dict(retentionRemainingSeconds=float("nan")), dict(operationId="x\ny")):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                separation_result_from_packet(result_packet(**changes))

    def test_terminal_result_is_not_replaced_by_reordered_pending_or_conflict(self):
        cache = SeparationResultCache()
        result = separation_result_from_packet(result_packet())
        cache.put(result, 10)
        pending = dataclasses.replace(result, completed=False, success=False, reason="pending")
        conflict = dataclasses.replace(result, retained=False, success=False, reason="operation_id_conflict")
        self.assertFalse(cache.put(pending, 11))
        self.assertFalse(cache.put(conflict, 12))
        self.assertTrue(cache.get(result.key, 13).success)
        self.assertEqual(cache.get(result.key, 13).retention_remaining_sec, 597)

    def test_cache_expiry_capacity_and_old_process_identity(self):
        cache = SeparationResultCache(capacity=2)
        result = separation_result_from_packet(result_packet())
        cache.put(result, 10)
        self.assertIsNone(cache.get(("new-process", "before", "launcher", "deploy-satellite"), 20))
        self.assertIsNone(cache.get(result.key, 610))
        for number in range(3):
            cache.put(dataclasses.replace(result, operation_id=str(number)), 700)
        self.assertEqual(len(cache.entries), 2)
        self.assertIsNone(cache.get(("process", "before", "launcher", "0"), 701))

    def test_result_retransmission_under_new_envelope_survives_epoch_transition(self):
        runtime = BridgeRuntime()
        runtime.receive(encode_datagram(heartbeat()), 1)
        result = result_packet(**SessionKey("process", 2, "after", "launcher").fields())
        # UDP result can beat the session heartbeat and is intentionally rejected.
        self.assertIsNone(runtime.receive(encode_datagram(result), 2))
        runtime.receive(encode_datagram(heartbeat("after", 2)), 3)
        event = runtime.receive(encode_datagram(result), 4)
        self.assertIsNotNone(event)
        self.assertEqual(separation_result_from_packet(event.packet).original_runtime_epoch, "before")
        query = separation_query("deploy-satellite", "process", "before", "launcher")
        encoded = runtime.encode_command(query, 3.1, 2).decode()
        self.assertIn('"runtimeEpoch":"after"', encoded)
        self.assertIn('"operationEpoch":"before"', encoded)

    def test_command_retry_retains_explicit_original_identity(self):
        message = SimpleNamespace(operation_id="deploy", original_runtime_instance="process",
                                  original_runtime_epoch="before", original_vessel_id="launcher")
        fields = separation_operation_fields(message, SessionKey("process", 2, "after", "payload"))
        self.assertEqual(fields["operationEpoch"], "before")
        self.assertEqual(fields["operationVesselId"], "launcher")

    def test_legacy_id_is_stable_and_changes_with_lease_or_actuator(self):
        message = SimpleNamespace(id="Decoupler #1", vessel_id="launcher", controller_id="mission",
                                  lease_id="lease", sequence=1)
        session = SessionKey("process", 1, "before", "launcher")
        first = separation_operation_fields(message, session)
        self.assertEqual(first, separation_operation_fields(message, session))
        message.id = "decoupler_1"
        self.assertEqual(first, separation_operation_fields(message, session))
        message.lease_id = "new-lease"
        self.assertNotEqual(first["operationId"], separation_operation_fields(message, session)["operationId"])


if __name__ == "__main__":
    unittest.main()
