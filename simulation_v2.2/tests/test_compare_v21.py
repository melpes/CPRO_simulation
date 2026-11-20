import importlib.util
import json
import os
import re
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.dont_write_bytecode = True

import simulation_generator

AAS_PATH = os.path.join(ROOT, 'aas_data')
REFERENCE_FILE = os.path.join(HERE, 'v21_asis_540.json')
TARGET_QUANTITY_PER_PRODUCT = 540
# 허용 차이(비율): 넘으면 v2.1과 크게 다른 것으로 봄
TOLERANCE = {'completion_hours': 0.02, 'completion_hours_by_product': 0.02, 'smt_completion_hours_by_line': 0.02,
             'smt_kwh': 0.03, 'assembly_kwh': 0.02, 'base_load_kwh': 0.02}
TEMPLATE_OUTPUT_CODE = re.compile(r'^[^\[\]+]+\[.*\]$')


def load_instance_module(instance_py_path):
    spec = importlib.util.spec_from_file_location('sim_instance_under_test', instance_py_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def relative_difference(value, reference):
    return abs(value - reference) / abs(reference) if reference else abs(value)


class SimulationV21ComparisonTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary_folder = tempfile.TemporaryDirectory()
        instance_py_path = os.path.join(cls.temporary_folder.name, 'sim_instance.py')
        cls.instance = simulation_generator.generate(AAS_PATH, instance_py_path)
        cls.module = load_instance_module(instance_py_path)
        with open(REFERENCE_FILE, encoding='utf-8') as reference_file:
            cls.reference = json.load(reference_file)

        # v2.1 시나리오 조건(PCB 초기 재고 비율 1.0)과 맞춤: 필요한 PCB를 처음부터 재고로 둠
        class InitialStockModel(cls.module.DEFAULT_MODEL_CLASS):
            def start_scenario_processes(self):
                for ItemCode, quantity in self.required_quantity_by_item().items():
                    self.stock[ItemCode] += quantity

            def set_unit_output_code(self, unit, ProcessCode, OutputItemCode):
                super().set_unit_output_code(unit, ProcessCode, OutputItemCode)
                self.output_code_samples.setdefault(ProcessCode, OutputItemCode)

        cls.runs = {}
        for seed in cls.reference['by_seed']:
            model = InitialStockModel(cls.instance, int(seed), {code: TARGET_QUANTITY_PER_PRODUCT for code in cls.instance['Products']})
            model.output_code_samples = {}
            result = model.run()
            smt_kwh = assembly_kwh = base_load_kwh = 0.0
            for boundary in model.carbon_boundaries.values():
                kwh = sum(element.Amount for element in boundary.carbon_elements if element.category == 'Electricity')
                if boundary.activity_basis == 'machine_on_time':
                    smt_kwh += kwh
                elif boundary.activity_basis == 'work_time':
                    base_load_kwh += kwh
                else:
                    assembly_kwh += kwh
            cls.runs[seed] = {
                'result': result, 'model': model,
                'measured': {
                    'completion_hours': result['end_time'] / 3600,
                    'completion_hours_by_product': {code: time / 3600 for code, time in
                                                    result['productivity']['completion_time_by_product'].items()},
                    'smt_completion_hours_by_line': {line: time / 3600 for line, time in
                                                     result['smt_lines']['completion_time_by_line'].items()},
                    'smt_kwh': smt_kwh, 'assembly_kwh': assembly_kwh, 'base_load_kwh': base_load_kwh,
                },
            }
        cls.print_comparison()

    @classmethod
    def tearDownClass(cls):
        cls.temporary_folder.cleanup()

    @classmethod
    def print_comparison(cls):
        for seed, run in cls.runs.items():
            reference, measured = cls.reference['by_seed'][seed], run['measured']
            print(f'\n[seed {seed}] 항목: v2.1 / v2.2 / 차이')
            for name in ('completion_hours', 'smt_kwh', 'assembly_kwh', 'base_load_kwh'):
                print(f'  {name}: {reference[name]:,.2f} / {measured[name]:,.2f} / '
                      f'{relative_difference(measured[name], reference[name]) * 100:.2f}%')
            for code, hours in reference['completion_hours_by_product'].items():
                value = measured['completion_hours_by_product'].get(code, float('nan'))
                print(f'  {code} 완료 h: {hours:,.2f} / {value:,.2f} / {relative_difference(value, hours) * 100:.2f}%')
            for line, hours in reference['smt_completion_hours_by_line'].items():
                value = measured['smt_completion_hours_by_line'].get(line, float('nan'))
                print(f'  SMT {line} 완료 h: {hours:,.2f} / {value:,.2f} / {relative_difference(value, hours) * 100:.2f}%')

    def test_target_reached(self):
        for seed, run in self.runs.items():
            with self.subTest(seed=seed):
                self.assertTrue(run['result']['target_reached'])
                self.assertEqual(run['result']['productivity']['stuck_unit_count'], 0)

    def test_close_to_v21(self):
        for seed, run in self.runs.items():
            reference, measured = self.reference['by_seed'][seed], run['measured']
            for name in ('completion_hours', 'smt_kwh', 'assembly_kwh', 'base_load_kwh'):
                with self.subTest(seed=seed, metric=name):
                    self.assertLessEqual(relative_difference(measured[name], reference[name]), TOLERANCE[name])
            for code, hours in reference['completion_hours_by_product'].items():
                with self.subTest(seed=seed, product=code):
                    self.assertLessEqual(relative_difference(measured['completion_hours_by_product'][code], hours),
                                         TOLERANCE['completion_hours_by_product'])
            for line, hours in reference['smt_completion_hours_by_line'].items():
                with self.subTest(seed=seed, smt_line=line):
                    self.assertLessEqual(relative_difference(measured['smt_completion_hours_by_line'][line], hours),
                                         TOLERANCE['smt_completion_hours_by_line'])

    def test_units_per_worker_only_aging(self):
        values = {code: process['UnitsPerWorker'] for code, process in self.instance['Processes'].items()
                  if process['UnitsPerWorker'] is not None}
        self.assertEqual({code for code, value in values.items() if value != 1}, {'BT5_100', 'NVD_110', 'VD7_100'})

    def test_smt_machine_capacity(self):
        capacities = {code: unit['CapacityPerCycle'] for code, unit in self.instance['MachineUnits'].items()}
        self.assertEqual({code for code, value in capacities.items() if value == 14}, {'Reflow_U1', 'Reflow_U2'})
        self.assertTrue(all(value in (1, 14) for value in capacities.values()))
        for code, unit in self.instance['MachineUnits'].items():
            self.assertEqual(unit['MaxCapacity'], unit['CapacityPerCycle'], code)

    def test_output_codes_follow_template_rule(self):
        samples = next(iter(self.runs.values()))['model'].output_code_samples
        for code, product in self.instance['Products'].items():
            for final_process_code in product['final_process_codes']:
                self.assertEqual(samples[final_process_code], code)
        intermediate = {code: output for code, output in samples.items() if output not in self.instance['Products']}
        self.assertTrue(intermediate)
        for process_code, output in intermediate.items():
            self.assertTrue(output.startswith(f'{process_code}['), output)
            self.assertRegex(output, TEMPLATE_OUTPUT_CODE)
            self.assertEqual(output.count('['), 1, output)


if __name__ == '__main__':
    unittest.main(verbosity=2)
