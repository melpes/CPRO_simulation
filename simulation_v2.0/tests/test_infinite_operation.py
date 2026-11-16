import unittest

import episode_procedure
import scenario_conditions
from discrete_event_simulation.simulation_model import (
    TARGET_PERIOD_END_REASONS, SimulationModel, quantity_by_product_ratio)
from discrete_event_simulation.smt_line import planned_item_with_least_pcb_stock
from reinforcement_learning import reward

SCENARIO = 'S1'
SIMULATION_SEED = 98102105
SECONDS_PER_DAY = 86400
SIMULATION_PERIOD_DAY = 4
PRODUCTION_QUANTITY_PER_PRODUCT = 6
MAINTAINED_UNFINISHED_QUANTITY_PER_RATIO_UNIT = 12
FINITE_PRODUCTION_QUANTITY_PER_PRODUCT = 6
UNREACHABLE_PRODUCTION_QUANTITY_PER_PRODUCT = 600
SHORT_DUE_DAY = 1
SIMULATION_PERIOD_DAY_FOR_SHORT_DUE = 2
PCB_PRODUCTION_PLAN_FOR_SELECTION = [
    {'item_code': 'PCB_WITHOUT_ARRAY', 'array_count': 0},
    {'item_code': 'PCB_FIRST', 'array_count': 1},
    {'item_code': 'PCB_SECOND', 'array_count': 1},
    {'item_code': 'PCB_THIRD', 'array_count': 1},
]
PCB_PRODUCTION_PLAN_WITHOUT_ARRAY = [{'item_code': 'PCB_WITHOUT_ARRAY', 'array_count': 0}]
PCB_STOCK_WITH_ONE_LEAST_ITEM = {
    'PCB_WITHOUT_ARRAY': 0, 'PCB_FIRST': 5, 'PCB_SECOND': 3, 'PCB_THIRD': 4}
PCB_STOCK_WITH_TWO_LEAST_ITEMS = {
    'PCB_WITHOUT_ARRAY': 0, 'PCB_FIRST': 5, 'PCB_SECOND': 3, 'PCB_THIRD': 3}
DECISIONS_FOR_INTERVAL_REWARDS = [
    {'cumulative_reward': -1.0}, {'cumulative_reward': -3.0}, {'cumulative_reward': -0.5}]
TARGET_PERIOD_NUMBERS_OF_DECISIONS = [1, 1, 2]
FINAL_REWARD_ITEMS = {'production_time': -2.0}
REWARD_ITEMS_OF_ENDED_TARGET_PERIODS = {1: {'production_time': -4.0}}
EXPECTED_INTERVAL_REWARDS = [-2.0, -1.0, -1.5]


def infinite_operation_conditions_for_short_run():
    conditions = scenario_conditions.conditions_of_scenario(SCENARIO)
    conditions['infinite_operation'] = True
    conditions['simulation_period_day'] = SIMULATION_PERIOD_DAY
    conditions['production_quantity_per_product'] = PRODUCTION_QUANTITY_PER_PRODUCT
    infinite_operation_conditions = conditions['infinite_operation_conditions']
    infinite_operation_conditions['maintained_unfinished_quantity_per_ratio_unit'] = (
        MAINTAINED_UNFINISHED_QUANTITY_PER_RATIO_UNIT)
    return conditions


def run_as_is(conditions):
    episode = episode_procedure.EpisodeProcedure(conditions, SIMULATION_SEED, SimulationModel)
    episode.prepare_simulation_model()
    episode.run_production()
    episode.calculate_energy_at_end()
    episode.calculate_interval_rewards()
    return episode


class InfiniteOperationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.conditions = infinite_operation_conditions_for_short_run()
        cls.episode = run_as_is(cls.conditions)
        cls.simulation_model = cls.episode.simulation_model

    def test_runs_until_simulation_period_and_keeps_producing(self):
        simulation_model = self.simulation_model
        self.assertEqual(
            simulation_model.simpy_environment.now, SIMULATION_PERIOD_DAY * SECONDS_PER_DAY)
        self.assertIsNone(self.episode.completion_sec)
        for product, target_quantity in simulation_model.target_quantity_by_product.items():
            self.assertEqual(target_quantity, PRODUCTION_QUANTITY_PER_PRODUCT)
            self.assertGreater(
                simulation_model.production_quantity_by_product[product], target_quantity)

    def test_target_periods_end_when_every_target_quantity_is_reached(self):
        simulation_model = self.simulation_model
        target_period_records = simulation_model.target_period_records
        due_sec = self.conditions['due_day'] * SECONDS_PER_DAY
        self.assertGreater(len(target_period_records), 0)
        for record in target_period_records:
            self.assertEqual(
                record['end_reason'], TARGET_PERIOD_END_REASONS['target_quantity_reached'])
            self.assertLessEqual(record['end_sec'] - record['start_sec'], due_sec)
            for product, production_quantity in record['production_quantity_by_product'].items():
                self.assertGreaterEqual(production_quantity, PRODUCTION_QUANTITY_PER_PRODUCT)
                self.assertEqual(
                    record['due_sec_by_product'][product], record['start_sec'] + due_sec)
        self.assertEqual(simulation_model.target_period_number, len(target_period_records) + 1)
        self.assertEqual(
            simulation_model.target_period_start_sec, target_period_records[-1]['end_sec'])
        for product_due_sec in simulation_model.target_period_due_sec_by_product.values():
            self.assertEqual(product_due_sec, simulation_model.target_period_start_sec + due_sec)

    def test_target_period_ends_when_due_passes(self):
        conditions = infinite_operation_conditions_for_short_run()
        conditions['production_quantity_per_product'] = UNREACHABLE_PRODUCTION_QUANTITY_PER_PRODUCT
        conditions['due_day'] = SHORT_DUE_DAY
        conditions['simulation_period_day'] = SIMULATION_PERIOD_DAY_FOR_SHORT_DUE
        simulation_model = run_as_is(conditions).simulation_model
        due_sec = SHORT_DUE_DAY * SECONDS_PER_DAY
        end_secs = [record['end_sec'] for record in simulation_model.target_period_records]
        end_reasons = [record['end_reason'] for record in simulation_model.target_period_records]
        self.assertEqual(end_secs[0], due_sec)
        self.assertEqual(end_reasons[0], TARGET_PERIOD_END_REASONS['due_passed'])
        for record in simulation_model.target_period_records:
            self.assertEqual(record['end_sec'] - record['start_sec'], due_sec)

    def test_smt_keeps_producing_within_pcb_stock_limit(self):
        simulation_model = self.simulation_model
        planned_item_count = 0
        for pcb_production_plan in simulation_model.smt_production_plan.values():
            planned_item_count += len(pcb_production_plan)
            for planned_item in pcb_production_plan:
                item_code = planned_item['item_code']
                quantity_per_smt_production = (
                    planned_item['array_count'] * planned_item['quantity_per_array'])
                pcb_stock_limit = (
                    simulation_model.required_pcb_quantity_by_item_code[item_code]
                    + quantity_per_smt_production)
                self.assertLess(simulation_model.pcb_stock[item_code], pcb_stock_limit)
        self.assertGreater(len(simulation_model.smt_production_records), planned_item_count)

    def test_smt_selects_pcb_item_with_least_stock(self):
        plan = PCB_PRODUCTION_PLAN_FOR_SELECTION
        least_stock_item = planned_item_with_least_pcb_stock(plan, PCB_STOCK_WITH_ONE_LEAST_ITEM)
        self.assertEqual(least_stock_item['item_code'], 'PCB_SECOND')
        first_item_of_same_stock = planned_item_with_least_pcb_stock(
            plan, PCB_STOCK_WITH_TWO_LEAST_ITEMS)
        self.assertEqual(first_item_of_same_stock['item_code'], 'PCB_SECOND')
        self.assertIsNone(planned_item_with_least_pcb_stock(
            PCB_PRODUCTION_PLAN_WITHOUT_ARRAY, PCB_STOCK_WITH_ONE_LEAST_ITEM))

    def test_reward_restarts_at_every_target_period(self):
        simulation_model = self.simulation_model
        cumulative_reward = reward.CumulativeReward(simulation_model)
        reward_items_at_start = cumulative_reward.reward_items(
            simulation_model.target_period_start_sec)
        self.assertEqual(set(reward_items_at_start.values()), {0.0})
        reward_items_of_ended_target_periods = self.episode.reward_items_of_ended_target_periods
        self.assertEqual(
            list(reward_items_of_ended_target_periods),
            [record['target_period_number'] for record in simulation_model.target_period_records])
        for record in simulation_model.target_period_records:
            reward_items = reward_items_of_ended_target_periods[record['target_period_number']]
            work_time_sec = (
                simulation_model.elapsed_work_time_sec(record['end_sec'])
                - simulation_model.elapsed_work_time_sec(record['start_sec']))
            self.assertEqual(
                reward_items['production_time'],
                reward.production_time_reward(
                    reward.REWARD_WEIGHTS['production_time'], work_time_sec,
                    cumulative_reward.denominator_work_time_sec))
            self.assertLessEqual(reward_items['carbon_emission'], 0.0)
            self.assertEqual(reward_items['delivery_delay'], 0.0)

    def test_interval_reward_stays_within_target_period(self):
        decisions = [dict(decision) for decision in DECISIONS_FOR_INTERVAL_REWARDS]
        reward.interval_rewards(
            decisions, TARGET_PERIOD_NUMBERS_OF_DECISIONS, FINAL_REWARD_ITEMS,
            REWARD_ITEMS_OF_ENDED_TARGET_PERIODS)
        self.assertEqual(
            [decision['reward'] for decision in decisions], EXPECTED_INTERVAL_REWARDS)

    def test_product_without_ratio_stops(self):
        with self.assertRaises(ValueError):
            quantity_by_product_ratio(['MODEL_A', 'MODEL_B'], {'MODEL_A': 1}, 1)

    def test_target_quantity_run_has_one_target_period(self):
        conditions = scenario_conditions.conditions_of_scenario(SCENARIO)
        conditions['production_quantity_per_product'] = FINITE_PRODUCTION_QUANTITY_PER_PRODUCT
        episode = episode_procedure.EpisodeProcedure(conditions, SIMULATION_SEED, SimulationModel)
        episode.prepare_simulation_model()
        episode.run_production()
        simulation_model = episode.simulation_model
        self.assertIsNotNone(simulation_model.production_completion_sec())
        self.assertEqual(simulation_model.target_period_records, [])
        self.assertEqual(simulation_model.target_period_start_sec, 0.0)
        self.assertEqual(
            simulation_model.target_period_due_sec_by_product,
            simulation_model.due_sec_by_product)
        self.assertEqual(
            simulation_model.production_quantity_in_target_period_by_product,
            simulation_model.production_quantity_by_product)


if __name__ == '__main__':
    unittest.main()
