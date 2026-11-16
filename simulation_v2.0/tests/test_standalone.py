import ast
import sys
import unittest
from pathlib import Path

import torch

import episode_procedure
import scenario_conditions
from discrete_event_simulation.simulation_model import SimulationModel
from reinforcement_learning import model, state

ROOT = Path(__file__).resolve().parents[1]
SCENARIO = 'S1'
PRODUCTION_QUANTITY_PER_PRODUCT = 540
NEW_MODEL_INITIAL_WEIGHT_SEED = 21
NODE_FEATURE_DIMENSION = 59
PRIORITY_WEIGHT_COUNT = 4
FOLDERS_OF_OTHER_CODE = ['/experiments/', '/auto3/']
FOLDERS_NOT_CHECKED = ['tests']


class StandaloneTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.conditions = scenario_conditions.conditions_of_scenario(SCENARIO)
        episode = episode_procedure.EpisodeProcedure(cls.conditions, None, SimulationModel)
        episode.generate_simulation_model()
        cls.simulation_model = episode.simulation_model
        cls.simulation_model.reset()
        cls.state_builder = state.StateBuilder(cls.simulation_model)

    def test_simulation_model_and_graph(self):
        self.assertEqual(set(scenario_conditions.SCENARIO_NAMES), {'S1', 'S1-1', 'S1-2'})
        simulation_model = self.simulation_model
        self.assertEqual(
            set(simulation_model.target_quantity_by_product.values()),
            {PRODUCTION_QUANTITY_PER_PRODUCT})
        self.assertGreater(len(simulation_model.simulation_processes.processes), 0)
        self.assertGreater(len(simulation_model.knowledge_graph.edges), 0)
        self.assertTrue(simulation_model.pcb_stock_limited)
        self.assertGreater(len(simulation_model.smt_production_plan), 0)

    def test_saved_model_file_supported(self):
        input_dimensions = self.state_builder.input_dimensions()
        loaded = model.load_model(model.DEFAULT_MODEL_FILE, input_dimensions)
        self.assertFalse(loaded['reinforcement_learning_model'].training)
        for scenario in scenario_conditions.SCENARIO_NAMES:
            with self.subTest(scenario=scenario):
                conditions = scenario_conditions.conditions_of_scenario(scenario)
                loaded = episode_procedure.load_reinforcement_learning_model(
                    model.DEFAULT_MODEL_FILE, conditions)
                emission_record = loaded['start_timing_emission_record']
                self.assertGreater(emission_record.recorded_start_time_slot_count(), 0)

    def test_new_model_forward(self):
        input_dimensions = self.state_builder.input_dimensions()
        reinforcement_learning_model = model.create_model(
            input_dimensions, NEW_MODEL_INITIAL_WEIGHT_SEED)
        current_state = self.state_builder.build_state(None)
        edge_connections = model.edge_connection_tensors(self.state_builder.edge_connections)
        node_features = torch.as_tensor(current_state['node_features'])
        global_information = torch.as_tensor(current_state['global_information'])
        with torch.no_grad():
            process_start_output = reinforcement_learning_model.process_start_forward(
                node_features, edge_connections, global_information)
            priority_output = reinforcement_learning_model.priority_forward(
                node_features, edge_connections, global_information,
                process_start_output['mean'].reshape(1))
        self.assertEqual(tuple(priority_output['mean'].shape), (PRIORITY_WEIGHT_COUNT,))
        self.assertTrue(torch.isfinite(priority_output['mean']).all())
        self.assertTrue(torch.isfinite(process_start_output['value']))
        model_settings = reinforcement_learning_model.model_settings
        self.assertEqual(model_settings['node_feature_dimension'], NODE_FEATURE_DIMENSION)
        self.assertEqual(model_settings['node_feature_dimension'], node_features.shape[1])
        self.assertEqual(
            model_settings['global_information_dimension'], global_information.shape[0])

    def test_no_external_code_loading(self):
        for module in tuple(sys.modules.values()):
            module_file = str(getattr(module, '__file__', '')).replace('\\', '/')
            for folder in FOLDERS_OF_OTHER_CODE:
                self.assertNotIn(folder, module_file)
        for code_file in ROOT.rglob('*.py'):
            name = str(code_file.relative_to(ROOT))
            if code_file.relative_to(ROOT).parts[0] in FOLDERS_NOT_CHECKED:
                continue
            tree = ast.parse(code_file.read_text(encoding='utf-8'))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                    self.assertNotIn(node.func.id, {'exec', 'eval'}, name)
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                    self.assertNotEqual(ast.unparse(node.func), 'sys.path.insert', name)
        self.assertFalse((ROOT / 'smt.py').exists())


if __name__ == '__main__':
    unittest.main()
