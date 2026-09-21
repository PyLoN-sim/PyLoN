import unittest

from pylon_bridge.simulator_packets import (
    ADVANCING, INITIALIZING, PAUSED, STALLED, STALE, UNAVAILABLE,
    SimulatorTracker, simulator_state_from_packet,
)


def heartbeat(sequence=1, ut=100., realtime=10., **updates):
    packet = dict(type='pylon_session', version=1, runtimeInstance='runtime',
                  runtimeGeneration=2, runtimeEpoch='epoch', runtimeVesselId='vessel',
                  vesselId='vessel', observationSequence=sequence, universalTime=ut,
                  realtimeSinceStartup=realtime, available=True, paused=False,
                  packed=False, warpRate=1., physicsWarp=False)
    packet.update(updates)
    return packet


class SimulatorTests(unittest.TestCase):
    def test_pause_heartbeats_remain_alive_without_simulation_progress(self):
        tracker = SimulatorTracker()
        tracker.observe(heartbeat(), 1.)
        active = tracker.observe(heartbeat(2, 100.1, 10.1), 1.1)
        self.assertEqual(active.state, ADVANCING)
        self.assertTrue(active.simulation_advancing)
        for sequence, realtime in [(3, 10.2), (4, 15.), (5, 25.)]:
            state = tracker.observe(heartbeat(sequence, 100.1, realtime, paused=True), realtime)
            self.assertEqual(state.state, PAUSED)
            self.assertFalse(state.simulation_advancing)
            self.assertTrue(state.communication_alive)
            self.assertEqual(state.seconds_since_progress, 0.)
            self.assertIsNone(tracker.expire(realtime + .2, .5))
        resumed = tracker.observe(heartbeat(6, 100.1, 25.1), 25.1)
        self.assertEqual(resumed.state, INITIALIZING)
        self.assertEqual(resumed.seconds_since_progress, 0.)
        self.assertEqual(tracker.observe(heartbeat(7, 100.2, 25.2), 25.2).state, ADVANCING)

    def test_fresh_heartbeats_with_stopped_ut_are_distinct_from_no_heartbeat(self):
        tracker = SimulatorTracker()
        tracker.observe(heartbeat(), 1.)
        stalled = tracker.observe(heartbeat(2, 100., 11.), 2.)
        self.assertEqual(stalled.state, STALLED)
        self.assertEqual(stalled.seconds_since_progress, 1.)
        self.assertTrue(stalled.communication_alive)
        self.assertFalse(stalled.paused)
        stale = tracker.expire(2.6, .5)
        self.assertEqual(stale.state, STALE)
        self.assertFalse(stale.communication_alive)
        self.assertAlmostEqual(stale.heartbeat_age_sec, .6)
        self.assertIsNone(tracker.expire(3., .5))
        # A long gap cannot count as continuously observed lack of progress.
        recovered = tracker.observe(heartbeat(3, 100., 30.), 21.)
        self.assertEqual(recovered.state, INITIALIZING)

    def test_packed_rails_warp_has_progress_without_control_availability(self):
        tracker = SimulatorTracker()
        settings = dict(packed=True, available=False, warpRate=100.)
        tracker.observe(heartbeat(**settings), 1.)
        state = tracker.observe(heartbeat(2, 110., 10.1, **settings), 1.1)
        self.assertEqual(state.state, ADVANCING)
        self.assertFalse(state.control_available)
        self.assertTrue(state.packed)
        self.assertFalse(state.physics_warp)
        self.assertEqual(state.warp_rate, 100.)

    def test_identity_change_resets_progress_and_unavailable_has_no_vessel(self):
        tracker = SimulatorTracker()
        tracker.observe(heartbeat(), 1.)
        changed = heartbeat(2, 50., 15., runtimeGeneration=3, runtimeEpoch='new')
        self.assertEqual(tracker.observe(changed, 2.).state, INITIALIZING)
        empty = heartbeat(3, 50., 16., runtimeGeneration=4, runtimeEpoch='empty',
                          vesselId='', runtimeVesselId='', available=False)
        self.assertEqual(tracker.observe(empty, 3.).state, UNAVAILABLE)

    def test_receipt_delay_does_not_change_producer_progress_clock(self):
        tracker = SimulatorTracker()
        tracker.observe(heartbeat(), 1.)
        state = tracker.observe(heartbeat(2, 100., 10.1), 100.)
        self.assertEqual(state.state, INITIALIZING)
        self.assertAlmostEqual(state.seconds_since_progress, .1)

    def test_reordered_duplicate_or_backwards_samples_do_not_refresh_heartbeat(self):
        tracker = SimulatorTracker()
        tracker.observe(heartbeat(4, 100., 10., paused=True), 1.)
        for packet in [heartbeat(3), heartbeat(4), heartbeat(5, 99., 11.), heartbeat(5, 101., 9.)]:
            self.assertIsNone(tracker.observe(packet, 2.))
        self.assertEqual(tracker.latest.observation_sequence, 4)
        self.assertEqual(tracker.last_seen, 1.)
        self.assertEqual(tracker.expire(2., .5).state, STALE)

    def test_malformed_state_is_rejected(self):
        for key, value in [('version', True), ('observationSequence', True),
                           ('observationSequence', -1), ('observationSequence', 2**64),
                           ('runtimeGeneration', 2**64), ('universalTime', float('nan')),
                           ('realtimeSinceStartup', -1.), ('warpRate', float('inf')),
                           ('warpRate', -1.), ('paused', 'true'), ('packed', True),
                           ('vesselId', 'different')]:
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                simulator_state_from_packet(heartbeat(**{key: value}))
