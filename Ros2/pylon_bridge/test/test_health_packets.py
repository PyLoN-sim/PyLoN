import unittest

from pylon_bridge.health_packets import ChargeRateEstimator, part_thermal_state_from_packet


def power(sequence=1, ut=10., amount=50., **updates):
    packet = dict(type='pylon_vehicle_health', version=1, vesselId='v', runtimeVesselId='v',
                  runtimeInstance='process', runtimeGeneration=1, runtimeEpoch='epoch',
                  observationSequence=sequence, universalTime=ut,
                  electricCharge=amount, electricCapacity=100.)
    packet.update(updates)
    return packet


def thermal(**updates):
    packet = power(type='pylon_part_thermal_state', partFlightId=12, partPersistentId=34,
                   partName='RTG', temperature=350., maxTemperature=1200.,
                   skinTemperature=800., maxSkinTemperature=2000., shieldedFromAirstream=True)
    packet.update(updates)
    return packet


class VehicleHealthTests(unittest.TestCase):
    def test_temperature_limits_shielding_and_resource_units_are_preserved(self):
        state = part_thermal_state_from_packet(thermal())
        self.assertEqual(state['part_flight_id'], 12)
        self.assertEqual(state['part_persistent_id'], 34)
        self.assertEqual(state['skin_temperature'], 800.)
        self.assertEqual(state['max_temperature'], 1200.)
        self.assertTrue(state['shielded_from_airstream'])
        self.assertEqual(state['electric_capacity'], 100.)

    def test_storage_slope_is_an_estimate_and_never_an_individual_flow_measurement(self):
        estimator = ChargeRateEstimator()
        self.assertFalse(estimator.observe(power())['net_charge_rate_valid'])
        draining = estimator.observe(power(2, 12., 42.))
        self.assertTrue(draining['net_charge_rate_valid'])
        self.assertEqual(draining['net_charge_rate_estimate'], -4.)
        self.assertEqual(draining['rate_sample_interval_sec'], 2.)
        charging = estimator.observe(power(3, 13., 47.))
        self.assertEqual(charging['net_charge_rate_estimate'], 5.)
        self.assertFalse(charging['generation_rate_valid'])
        self.assertFalse(charging['consumption_rate_valid'])

    def test_pause_capacity_changes_and_epoch_changes_do_not_produce_spurious_rates(self):
        estimator = ChargeRateEstimator()
        estimator.observe(power())
        for packet in [power(2, 10., 50.), power(3, 11., 60., electricCapacity=200.),
                       power(4, 12., 80., runtimeEpoch='separated', runtimeGeneration=2)]:
            self.assertFalse(estimator.observe(packet)['net_charge_rate_valid'])
        resumed = estimator.observe(power(5, 13., 77., runtimeEpoch='separated', runtimeGeneration=2))
        self.assertEqual(resumed['net_charge_rate_estimate'], -3.)

    def test_old_or_duplicate_samples_cannot_corrupt_charge_baseline(self):
        estimator = ChargeRateEstimator()
        estimator.observe(power(10, 10., 50.))
        for packet in [power(9, 11., 0.), power(10, 10., 0.), power(11, 9., 0.)]:
            self.assertIsNone(estimator.observe(packet))
        self.assertEqual(estimator.observe(power(11, 11., 48.))['net_charge_rate_estimate'], -2.)

    def test_invalid_identity_temperature_resources_and_flags_are_rejected(self):
        for key, value in [('version', True), ('runtimeGeneration', 2**64),
                           ('observationSequence', -1), ('partFlightId', 2**32),
                           ('partPersistentId', True), ('temperature', -1.),
                           ('skinTemperature', float('nan')), ('shieldedFromAirstream', 1),
                           ('electricCharge', float('inf')), ('electricCapacity', -1.),
                           ('vesselId', 'wrong')]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                part_thermal_state_from_packet(thermal(**{key: value}))
