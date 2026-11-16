import ast
import unittest
from operator import attrgetter
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from discrete_event_simulation import carbon_components
from reinforcement_learning import action, reward

ROOT = Path(__file__).resolve().parents[1]
PEAK_TIME_WEIGHT = 1.8537915984724496
LIGHT_LOAD_TIME_WEIGHT = 0.6492089470812875
ELECTRICITY_TIME_BAND_WEIGHTS = [
    {'start_sec': 63000, 'end_sec': 81000, 'weight': PEAK_TIME_WEIGHT},
    {'start_sec': 0, 'end_sec': 21600, 'weight': LIGHT_LOAD_TIME_WEIGHT},
]
PEAK_START_SEC = 63000.0
ONE_HOUR_AFTER_PEAK_START_SEC = 66600.0
POWER_KW = 2.0
ENERGY_OF_ONE_HOUR_KWH = 2.0
START_SEC_WITHOUT_TIME_BAND = 10.0
END_SEC_BEFORE_START = 5.0
WEIGHTED_ENERGY_KWH = 5.0
DUE_SEC = 100.0
COMPLETION_SEC = 10.0
TARGET_PERIOD_NUMBER = 1
TARGET_PERIOD_START_SEC = 0.0
REWARD_WEIGHTS_FOR_TEST = {
    'production_time': 1.0, 'carbon_emission': 2.0, 'delivery_delay': 1.0}
REWARD_NORMALIZATION_DENOMINATORS_FOR_TEST = {'production_time': 100.0, 'carbon_emission': 10.0}
DOUBLED_EMISSION_FACTOR = 2.0
CARBON_REWARD_WITH_DOUBLED_EMISSION_FACTOR = -2.0
CARBON_EMISSION_WITH_DOUBLED_EMISSION_FACTOR = 10.0
EMISSION_CONVERSION_CALL_COUNT = 2
MAX_LINE_LENGTH = 100
MAX_EPISODE_FUNCTION_LINES = 25
SEPARATOR_COMMENT_START = '# ================================================ '
SEPARATOR_COMMENT_END = ' ================================================'
FOLDERS_NOT_CHECKED_FOR_EXPRESSION_RULES = ['api', 'tests']
EPISODE_STAGES = {
    'run_episode': [
        'EpisodeProcedure', 'episode.prepare_simulation_model',
        'episode.prepare_reinforcement_learning_model', 'episode.run_production',
        'episode.calculate_energy_at_end', 'episode.calculate_interval_rewards',
        'episode.collect_result'],
    'run_as_is_episode': [
        'EpisodeProcedure', 'episode.prepare_simulation_model', 'episode.run_production',
        'episode.calculate_energy_at_end', 'episode.calculate_interval_rewards',
        'episode.collect_as_is_result'],
}
TRAINING_STAGES = {
    'train_scenario_model': [
        'training.check_output_folder', 'training.prepare_reinforcement_learning_model',
        'training.resume_from_saved_model', 'training.save_training_settings',
        'training.evaluate_before_training', 'training.run_training_episodes',
        'training.update_with_ppo', 'training.save_last_model_and_progress',
        'training.evaluate_at_interval_or_end'],
    'integrate_scenario_models': [
        'integration.select_scenario_models',
        'integration.load_scenario_models_and_initial_integrated_model',
        'integration.collect_states_with_scenario_models',
        'integration.label_states_with_scenario_model_outputs',
        'integration.fit_integrated_model', 'integration.save_integrated_model',
        'integration.collect_states_with_integrated_model', 'integration.test_integrated_model',
        'integration.run_as_is_episodes', 'integration.save_test_verdict_and_log'],
}
DEFINITION_ORDER_BY_FILE = {
    'reinforcement_learning/state.py': ['generate_gnn_input', 'StateBuilder'],
    'reinforcement_learning/model.py': [
        'RelationalGraphConvolution', 'ReinforcementLearningModel', 'create_model', 'load_model'],
    'reinforcement_learning/action.py': [
        'priority_scores', 'select_candidate_index', 'StartTimingEmissionRecord',
        'ActionSelector', 'create_action_selector'],
    'reinforcement_learning/reward.py': ['CumulativeReward', 'interval_rewards'],
    'reinforcement_learning/ppo.py': ['advantages_and_value_targets', 'ppo_update'],
}
SIMULATION_MODEL_METHOD_ORDER = [
    'start', 'advance', 'ready_queue', 'jobs_fitting_remaining_work_time',
    'select_and_start_jobs']


def syntax_tree(file_name):
    return ast.parse((ROOT / file_name).read_text(encoding='utf-8-sig'))


def top_level_function(file_name, function_name):
    for node in syntax_tree(file_name).body:
        if isinstance(node, ast.FunctionDef) and node.name == function_name:
            return node
    raise AssertionError(f'{file_name}에 {function_name} 함수가 없음')


def called_names(function_node):
    calls = [node for node in ast.walk(function_node) if isinstance(node, ast.Call)]
    calls.sort(key=attrgetter('lineno', 'col_offset'))
    return [ast.unparse(call.func) for call in calls]


def code_files_checked_for_expression_rules():
    code_files = []
    for code_file in sorted(ROOT.rglob('*.py')):
        top_folder = code_file.relative_to(ROOT).parts[0]
        if top_folder not in FOLDERS_NOT_CHECKED_FOR_EXPRESSION_RULES:
            code_files.append(code_file)
    return code_files


class ReadabilityTest(unittest.TestCase):
    def test_time_band_weighting_owned_by_carbon_components(self):
        bands = ELECTRICITY_TIME_BAND_WEIGHTS
        with patch.object(carbon_components, 'weighted_energy_kwh',
                          wraps=carbon_components.weighted_energy_kwh) as weighted:
            actual = carbon_components.energy_by_time_band(
                PEAK_START_SEC, ONE_HOUR_AFTER_PEAK_START_SEC, POWER_KW, bands)
        self.assertEqual(weighted.call_count, 1)
        self.assertEqual(actual['kwh'], ENERGY_OF_ONE_HOUR_KWH)
        self.assertEqual(actual['peak_kwh'], ENERGY_OF_ONE_HOUR_KWH)
        self.assertEqual(actual['weighted_kwh'], ENERGY_OF_ONE_HOUR_KWH * PEAK_TIME_WEIGHT)
        plain = carbon_components.energy_by_time_band(
            PEAK_START_SEC, ONE_HOUR_AFTER_PEAK_START_SEC, POWER_KW, [])
        self.assertEqual(actual['kwh'], plain['kwh'])
        self.assertEqual(plain['weighted_kwh'], plain['kwh'])
        self.assertEqual(carbon_components.weighted_energy_kwh(
            START_SEC_WITHOUT_TIME_BAND, END_SEC_BEFORE_START, POWER_KW, bands), 0.0)

    def test_episode_reads_as_stages(self):
        for function_name, stages in EPISODE_STAGES.items():
            function_node = top_level_function('episode_procedure.py', function_name)
            line_count = function_node.end_lineno - function_node.lineno + 1
            self.assertLessEqual(line_count, MAX_EPISODE_FUNCTION_LINES, function_name)
            self.assertFalse(any(
                isinstance(node, (ast.Dict, ast.DictComp, ast.ListComp, ast.Lambda))
                for node in ast.walk(function_node)), function_name)
            calls = called_names(function_node)
            for stage in stages:
                self.assertIn(stage, calls)

    def test_training_reads_as_stages(self):
        for function_name, stages in TRAINING_STAGES.items():
            function_node = top_level_function('train_model.py', function_name)
            self.assertFalse(any(
                isinstance(node, (ast.Dict, ast.DictComp, ast.ListComp, ast.Lambda))
                for node in ast.walk(function_node)), function_name)
            calls = called_names(function_node)
            for stage in stages:
                self.assertIn(stage, calls)
            stage_calls = [call for call in calls if call in stages]
            first_positions = [stage_calls.index(stage) for stage in stages]
            self.assertEqual(first_positions, sorted(first_positions), function_name)

    def test_reinforcement_learning_and_simulation_read_order(self):
        for file_name, order in DEFINITION_ORDER_BY_FILE.items():
            names = [node.name for node in syntax_tree(file_name).body
                     if isinstance(node, (ast.ClassDef, ast.FunctionDef))]
            self.assertEqual(sorted(order, key=names.index), order, file_name)
        tree = syntax_tree('discrete_event_simulation/simulation_model.py')
        simulation_model = next(
            node for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == 'SimulationModel')
        methods = [node.name for node in simulation_model.body
                   if isinstance(node, ast.FunctionDef)]
        order = SIMULATION_MODEL_METHOD_ORDER
        self.assertEqual(sorted(order, key=methods.index), order)

    def test_emission_factor_reaches_reward_and_emission_record(self):
        def elapsed_work_time_sec(sec):
            return sec

        def aggregate_energy(sec):
            if sec == TARGET_PERIOD_START_SEC:
                return {'weighted_kwh': 0.0}
            return {'weighted_kwh': WEIGHTED_ENERGY_KWH}

        simulation_model = SimpleNamespace(
            target_quantity_by_product={'MODEL_A': 1}, due_sec_by_product={'MODEL_A': DUE_SEC},
            target_period_number=TARGET_PERIOD_NUMBER,
            target_period_start_sec=TARGET_PERIOD_START_SEC,
            target_period_due_sec_by_product={'MODEL_A': DUE_SEC},
            completion_sec_by_product={'MODEL_A': COMPLETION_SEC},
            elapsed_work_time_sec=elapsed_work_time_sec, aggregate_energy=aggregate_energy)
        with patch.dict(reward.REWARD_WEIGHTS, REWARD_WEIGHTS_FOR_TEST), \
                patch.dict(reward.REWARD_NORMALIZATION_DENOMINATORS,
                           REWARD_NORMALIZATION_DENOMINATORS_FOR_TEST):
            cumulative_reward = reward.CumulativeReward(simulation_model)
            with patch.dict(carbon_components.EMISSION_FACTORS, {'electricity': 1.0}), \
                    patch.object(carbon_components, 'convert_to_carbon_emission',
                                 wraps=carbon_components.convert_to_carbon_emission) as emission:
                self.assertEqual(
                    cumulative_reward.reward_items(COMPLETION_SEC)['carbon_emission'], -1.0)
                self.assertEqual(
                    action.carbon_emission_of_smt_lot(WEIGHTED_ENERGY_KWH), WEIGHTED_ENERGY_KWH)
                self.assertEqual(emission.call_count, EMISSION_CONVERSION_CALL_COUNT)
            with patch.dict(carbon_components.EMISSION_FACTORS,
                            {'electricity': DOUBLED_EMISSION_FACTOR}):
                self.assertEqual(
                    cumulative_reward.reward_items(COMPLETION_SEC)['carbon_emission'],
                    CARBON_REWARD_WITH_DOUBLED_EMISSION_FACTOR)
                self.assertEqual(
                    action.carbon_emission_of_smt_lot(WEIGHTED_ENERGY_KWH),
                    CARBON_EMISSION_WITH_DOUBLED_EMISSION_FACTOR)

    def test_expression_rules(self):
        for code_file in code_files_checked_for_expression_rules():
            name = str(code_file.relative_to(ROOT))
            text = code_file.read_text(encoding='utf-8')
            for line_number, line in enumerate(text.splitlines(), 1):
                stripped = line.strip()
                if stripped.startswith('#'):
                    self.assertTrue(
                        stripped.startswith(SEPARATOR_COMMENT_START)
                        and stripped.endswith(SEPARATOR_COMMENT_END),
                        f'{name}:{line_number} 구분선이 아닌 주석')
                else:
                    self.assertLessEqual(
                        len(line), MAX_LINE_LENGTH, f'{name}:{line_number} 100자 넘는 줄')
            tree = ast.parse(text)
            for node in ast.walk(tree):
                self.assertNotIsInstance(node, ast.Lambda, f'{name}:lambda')
                self.assertNotIsInstance(node, ast.IfExp, f'{name}:삼항식')
                if isinstance(node, (ast.FunctionDef, ast.ClassDef, ast.Module)):
                    self.assertIsNone(ast.get_docstring(node), f'{name}:docstring')
                if isinstance(node, ast.Return):
                    self.assertNotIsInstance(node.value, ast.Tuple, f'{name}:튜플 반환')


if __name__ == '__main__':
    unittest.main()
