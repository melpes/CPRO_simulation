import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROCESS_FIELDS = [
    'product_code', 'is_defect_event_target_process', 'is_defect_event_handling_process',
    'requires_no_worker_and_no_machine', 'CycleTime', 'simultaneous_processing_quantity',
    'defect_probability_per_output_item', 'process_rated_power_kw', 'BranchProbability',
    'RequiresWorker', 'worker_work_time_sec',
]
MACHINE_FIELDS = [
    'MachineGroupCode', 'rated_power_kw', 'MaxCapacity', 'CapacityPerCycle', 'RequiresOperator']


def classes_of_file(file_name):
    tree = ast.parse((ROOT / file_name).read_text(encoding='utf-8'))
    return {node.name: node for node in tree.body if isinstance(node, ast.ClassDef)}


def field_names(class_node):
    return [node.target.id for node in class_node.body if isinstance(node, ast.AnnAssign)]


def method_names(class_node):
    return [node.name for node in class_node.body if isinstance(node, ast.FunctionDef)]


class KnowledgeGraphReadingTest(unittest.TestCase):
    def setUp(self):
        self.kg_classes = classes_of_file('knowledge_graph.py')
        self.simulation_classes = classes_of_file(
            'discrete_event_simulation/simulation_generator.py')

    def test_schema_before_execution_records(self):
        kg_class_names = list(self.kg_classes)
        self.assertEqual(kg_class_names[0], 'Node')
        for schema_class_name in ('Process', 'Machine', 'Worker', 'Warehouse', 'Edge'):
            self.assertLess(
                kg_class_names.index(schema_class_name), kg_class_names.index('KnowledgeGraph'))
        self.assertNotIn('SimulationProcess', kg_class_names)
        simulation_class_names = list(self.simulation_classes)
        self.assertLess(
            simulation_class_names.index('SimulationProcess'),
            simulation_class_names.index('SimulationProcesses'))
        methods = method_names(self.simulation_classes['SimulationProcesses'])
        methods_after_initialization = [name for name in methods if name != '__init__']
        self.assertEqual(methods_after_initialization[0], 'previous_process_codes')

    def test_aas_feature_names_and_order(self):
        self.assertEqual(field_names(self.kg_classes['Process']), PROCESS_FIELDS)
        self.assertEqual(field_names(self.kg_classes['Machine']), MACHINE_FIELDS)
        simulation_process_fields = field_names(self.simulation_classes['SimulationProcess'])
        self.assertEqual(simulation_process_fields[0], 'process_code')
        first_field_after_code = 1
        last_shared_field = first_field_after_code + len(PROCESS_FIELDS)
        self.assertEqual(
            simulation_process_fields[first_field_after_code:last_shared_field], PROCESS_FIELDS)


if __name__ == '__main__':
    unittest.main()
