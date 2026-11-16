import ast
import unittest
from pathlib import Path
from unittest.mock import patch

from discrete_event_simulation import carbon_components

ROOT = Path(__file__).resolve().parents[1]
PEAK_TIME_WEIGHT = 1.8537915984724496
LIGHT_LOAD_TIME_WEIGHT = 0.6492089470812875
SECONDS_PER_HOUR = 3600.0
SECONDS_PER_HALF_HOUR = 1800.0
SECONDS_PER_DAY = 86400.0
PEAK_START_SEC = 63000.0
PEAK_END_SEC = 81000.0
LIGHT_LOAD_START_SEC = 0.0
LIGHT_LOAD_END_SEC = 21600.0
ELECTRICITY_TIME_BAND_WEIGHTS = [
    {'start_sec': PEAK_START_SEC, 'end_sec': PEAK_END_SEC, 'weight': PEAK_TIME_WEIGHT},
    {'start_sec': LIGHT_LOAD_START_SEC, 'end_sec': LIGHT_LOAD_END_SEC,
     'weight': LIGHT_LOAD_TIME_WEIGHT},
]
POWER_KW = 2.0
ENERGY_OF_ONE_HOUR_KWH = 2.0
ENERGY_OF_HALF_HOUR_KWH = 1.0
ONE_HOUR_AFTER_PEAK_START_SEC = PEAK_START_SEC + SECONDS_PER_HOUR
HALF_HOUR_BEFORE_PEAK_START_SEC = PEAK_START_SEC - SECONDS_PER_HALF_HOUR
HALF_HOUR_AFTER_PEAK_START_SEC = PEAK_START_SEC + SECONDS_PER_HALF_HOUR
HALF_HOUR_BEFORE_MIDNIGHT_SEC = SECONDS_PER_DAY - SECONDS_PER_HALF_HOUR
HALF_HOUR_AFTER_MIDNIGHT_SEC = SECONDS_PER_DAY + SECONDS_PER_HALF_HOUR
START_SEC_WITHOUT_TIME_BAND = 10.0
END_SEC_BEFORE_START = 5.0
ONE_HOUR_AFTER_START_SEC_WITHOUT_TIME_BAND = START_SEC_WITHOUT_TIME_BAND + SECONDS_PER_HOUR
EMISSION_FACTOR_FOR_TEST = 0.5
PEAK_HOURS_PER_DAY = 5.0
LIGHT_LOAD_HOURS_PER_DAY = 6.0
OTHER_HOURS_PER_DAY = 13.0
DAY_COUNT = 3.0
WEIGHTED_ENERGY_OF_ONE_DAY_KWH = POWER_KW * (
    OTHER_HOURS_PER_DAY + PEAK_HOURS_PER_DAY * PEAK_TIME_WEIGHT
    + LIGHT_LOAD_HOURS_PER_DAY * LIGHT_LOAD_TIME_WEIGHT)
SEC_AFTER_POWER_OFF = 70000.0
OLD_WEIGHTED_SECOND_NAMES = {
    'tariff_weighted_sec', '_tariff_weighted_sec', 'weighted_seconds', 'WeightedActiveSec'}
FILES_WITHOUT_WEIGHTED_SECOND_NAMES = [
    'discrete_event_simulation/carbon_components.py',
    'discrete_event_simulation/simulation_model.py',
    'discrete_event_simulation/simulation_generator.py',
]


class CarbonEnergyTest(unittest.TestCase):
    bands = ELECTRICITY_TIME_BAND_WEIGHTS

    def test_weight_applies_to_energy_not_elapsed_seconds(self):
        weighted = carbon_components.weighted_energy_kwh(
            PEAK_START_SEC, ONE_HOUR_AFTER_PEAK_START_SEC, POWER_KW, self.bands)
        self.assertAlmostEqual(weighted, ENERGY_OF_ONE_HOUR_KWH * PEAK_TIME_WEIGHT)
        with patch.dict(carbon_components.EMISSION_FACTORS,
                        {'electricity': EMISSION_FACTOR_FOR_TEST}):
            self.assertAlmostEqual(
                carbon_components.convert_to_carbon_emission(weighted),
                ENERGY_OF_ONE_HOUR_KWH * PEAK_TIME_WEIGHT * EMISSION_FACTOR_FOR_TEST)
        self.assertEqual(
            carbon_components.time_band_weight(PEAK_START_SEC, self.bands), PEAK_TIME_WEIGHT)
        self.assertEqual(carbon_components.weighted_energy_kwh(
            START_SEC_WITHOUT_TIME_BAND, END_SEC_BEFORE_START, POWER_KW, self.bands), 0.0)
        self.assertEqual(carbon_components.weighted_energy_kwh(
            START_SEC_WITHOUT_TIME_BAND, ONE_HOUR_AFTER_START_SEC_WITHOUT_TIME_BAND, POWER_KW, []),
            ENERGY_OF_ONE_HOUR_KWH)

    def test_crossing_band_boundary_and_multiple_days(self):
        self.assertAlmostEqual(
            carbon_components.weighted_energy_kwh(
                HALF_HOUR_BEFORE_PEAK_START_SEC, HALF_HOUR_AFTER_PEAK_START_SEC, POWER_KW,
                self.bands),
            ENERGY_OF_HALF_HOUR_KWH + PEAK_TIME_WEIGHT)
        self.assertAlmostEqual(
            carbon_components.weighted_energy_kwh(
                HALF_HOUR_BEFORE_MIDNIGHT_SEC, HALF_HOUR_AFTER_MIDNIGHT_SEC, POWER_KW,
                self.bands),
            ENERGY_OF_HALF_HOUR_KWH + LIGHT_LOAD_TIME_WEIGHT)
        self.assertAlmostEqual(
            carbon_components.weighted_energy_kwh(
                0.0, DAY_COUNT * SECONDS_PER_DAY, POWER_KW, self.bands),
            DAY_COUNT * WEIGHTED_ENERGY_OF_ONE_DAY_KWH)

    def test_power_integral_retains_physical_energy_and_actual_time(self):
        result = carbon_components.energy_by_time_band(
            PEAK_START_SEC, ONE_HOUR_AFTER_PEAK_START_SEC, POWER_KW, self.bands)
        self.assertEqual(result['kwh'], ENERGY_OF_ONE_HOUR_KWH)
        self.assertAlmostEqual(result['weighted_kwh'], ENERGY_OF_ONE_HOUR_KWH * PEAK_TIME_WEIGHT)
        integral = carbon_components.PowerIntegral(self.bands)
        integral.change_power(PEAK_START_SEC, POWER_KW)
        self.assertAlmostEqual(
            integral.weighted_energy_kwh_until(ONE_HOUR_AFTER_PEAK_START_SEC),
            result['weighted_kwh'])
        integral.change_power(ONE_HOUR_AFTER_PEAK_START_SEC, -POWER_KW)
        self.assertEqual(integral.recorded_sec, ONE_HOUR_AFTER_PEAK_START_SEC)
        self.assertAlmostEqual(
            integral.weighted_energy_kwh_until(SEC_AFTER_POWER_OFF), result['weighted_kwh'])

    def test_no_weighted_second_interface(self):
        for file_name in FILES_WITHOUT_WEIGHTED_SECOND_NAMES:
            tree = ast.parse((ROOT / file_name).read_text(encoding='utf-8'))
            names = [node.id for node in ast.walk(tree) if isinstance(node, ast.Name)]
            attributes = [node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)]
            functions = [node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)]
            used_names = set(names + attributes + functions)
            self.assertFalse(used_names & OLD_WEIGHTED_SECOND_NAMES, file_name)


if __name__ == '__main__':
    unittest.main()
