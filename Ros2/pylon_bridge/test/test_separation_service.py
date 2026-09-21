"""Exercise generated message/service adapters without sockets or a ROS executor."""
import unittest
from unittest.mock import Mock

try:
    from pylon_interfaces.srv import GetSeparationResult
    from pylon_bridge.services.separation_results import SeparationResultsService
except ImportError:
    SeparationResultsService = None

try:
    from .test_separation_results import result_packet
except ImportError:
    from test_separation_results import result_packet


@unittest.skipIf(SeparationResultsService is None, "generated ROS interfaces unavailable")
class SeparationServiceTests(unittest.TestCase):
    def setUp(self):
        self.bridge = Mock(actuators_prefix='/ksp_vessel/actuators')
        from builtin_interfaces.msg import Time
        self.bridge.get_clock.return_value.now.return_value.to_msg.return_value = Time()
        self.service = SeparationResultsService(self.bridge)
        self.request = GetSeparationResult.Request(operation_id='deploy-satellite',
            original_runtime_instance='process', original_runtime_epoch='before', original_vessel_id='launcher')

    def test_cache_miss_queries_and_pending_cache_keeps_querying_until_completion(self):
        response = self.service.get_result(self.request, GetSeparationResult.Response())
        self.assertFalse(response.found)
        self.assertTrue(response.query_sent)
        command = self.bridge.connection.send_command.call_args[0][0]
        self.assertEqual(command['type'], 'pylon_separation_query')
        self.assertEqual(command['operationEpoch'], 'before')
        pending = result_packet(completed=False, success=False, reason='pending', resultEpoch='',
                                resultGeneration=0, activeVesselId='', resultingVesselIds=[])
        self.service.publish_result(pending)
        self.bridge.connection.send_command.reset_mock()
        response = self.service.get_result(self.request, GetSeparationResult.Response())
        self.assertTrue(response.found)
        self.assertFalse(response.result.completed)
        self.assertTrue(response.query_sent)
        self.bridge.connection.send_command.assert_called_once()
        self.service.publish_result(result_packet())
        self.bridge.connection.send_command.reset_mock()
        response = self.service.get_result(self.request, GetSeparationResult.Response())
        self.assertTrue(response.result.completed)
        self.assertTrue(response.result.success)
        self.assertFalse(response.query_sent)
        self.bridge.connection.send_command.assert_not_called()

    def test_cached_completion_can_be_queried_without_active_control_connection(self):
        self.service.publish_result(result_packet())
        self.bridge.connection.send_command.side_effect = ValueError('session unavailable')
        response = self.service.get_result(self.request, GetSeparationResult.Response())
        self.assertTrue(response.found)
        self.assertTrue(response.result.success)

    def test_unknown_result_reports_missing_without_inventing_success(self):
        self.service.publish_result(result_packet(retained=False, success=False, reason='result_not_retained',
            name='', controllerId='', resultEpoch='', resultingVesselIds=[], retentionRemainingSeconds=0.))
        response = self.service.get_result(self.request, GetSeparationResult.Response())
        self.assertFalse(response.found)
        self.assertFalse(response.result.success)
        self.assertEqual(response.reason, 'result_not_retained')


if __name__ == '__main__':
    unittest.main()
