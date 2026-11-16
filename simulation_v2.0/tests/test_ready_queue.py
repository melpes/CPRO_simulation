import ast
import unittest
from pathlib import Path
from types import SimpleNamespace

import simpy

from discrete_event_simulation.simulation_model import SimulationModel

ROOT = Path(__file__).resolve().parents[1]
READY_QUEUE_METHODS_IN_ONE_BLOCK = [
    'ready_queue', 'wake_ready_queue', 'are_input_items_ready', 'ready_process_codes',
    'jobs_fitting_remaining_work_time', 'needs_priority_choice', 'request_priority_choice',
    'choose_job', 'select_and_start_jobs',
]
PCB_STOCK_METHODS_OF_SMT_LINE = [
    'required_pcb_quantities', 'filter_jobs_by_pcb_stock', 'take_pcb_from_stock']
JOBS_WITH_OTHER_PROCESS_IN_THE_MIDDLE = [
    {'process_code': 'A', 'id': 1}, {'process_code': 'B', 'id': 2},
    {'process_code': 'A', 'id': 3}]
JOBS_WITH_OTHER_PROCESS_AT_THE_END = [
    {'process_code': 'A', 'id': 1}, {'process_code': 'A', 'id': 2},
    {'process_code': 'B', 'id': 3}]
NOW_SEC = 100
WORK_END_SEC = 200
CYCLE_TIME_FITTING_REMAINING_WORK_TIME = 100
CYCLE_TIME_OVER_REMAINING_WORK_TIME = 101


def methods_of_class(file_name, class_name):
    tree = ast.parse((ROOT / file_name).read_text(encoding='utf-8'))
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return {child.name: child for child in node.body if isinstance(child, ast.FunctionDef)}
    raise AssertionError(f'{file_name}에 {class_name} 클래스가 없음')


def called_names(function_node):
    return [ast.unparse(node.func) for node in ast.walk(function_node)
            if isinstance(node, ast.Call)]


class ReadyQueueTest(unittest.TestCase):
    def test_precedence_inventory_and_product(self):
        names = ['A', 'B', 'C', 'S', 'J', 'OTHER']
        processes = {}
        for name in names:
            product_code = 'M1'
            if name == 'OTHER':
                product_code = 'M2'
            processes[name] = SimpleNamespace(product_code=product_code)

        def previous_process_codes(process_code):
            return ['A', 'B']

        def are_input_items_in_stock(process_code, warehouse_inventory):
            return process_code != 'B'

        simulation_processes = SimpleNamespace(
            processes=processes, previous_process_codes=previous_process_codes,
            are_input_items_in_stock=are_input_items_in_stock)
        simulation_model = SimpleNamespace(
            simulation_processes=simulation_processes,
            process_codes_without_previous_process=['A', 'B', 'C', 'OTHER'],
            process_codes_after_any_previous_process=['S'],
            process_codes_after_all_previous_processes=['J'],
            infinite_stock=False, warehouse=SimpleNamespace(inventory=None), product_by_unit={})

        def are_input_items_ready(process_code):
            return SimulationModel.are_input_items_ready(simulation_model, process_code)

        simulation_model.are_input_items_ready = are_input_items_ready
        self.assertEqual(
            SimulationModel.ready_process_codes(simulation_model, 'M1', {'A'}), ['C', 'S'])
        self.assertEqual(
            SimulationModel.ready_process_codes(simulation_model, 'M1', {'A', 'B'}),
            ['C', 'S', 'J'])
        simulation_model.infinite_stock = True
        self.assertEqual(
            SimulationModel.ready_process_codes(simulation_model, 'M1', {'A'}), ['B', 'C', 'S'])

    def test_candidate_time_and_stock_preserve_order(self):
        jobs = [dict(job) for job in JOBS_WITH_OTHER_PROCESS_IN_THE_MIDDLE]
        calls = []

        def filter_jobs_by_pcb_stock(worker_group, fitting_jobs):
            calls.append({'worker_group': worker_group, 'fitting_jobs': fitting_jobs})
            return fitting_jobs

        processes = {
            'A': SimpleNamespace(CycleTime=CYCLE_TIME_FITTING_REMAINING_WORK_TIME),
            'B': SimpleNamespace(CycleTime=CYCLE_TIME_OVER_REMAINING_WORK_TIME)}
        simulation_model = SimpleNamespace(
            simpy_environment=SimpleNamespace(now=NOW_SEC), WorkEndTime=WORK_END_SEC,
            simulation_processes=SimpleNamespace(processes=processes),
            pcb_stock={'PCB': 1}, filter_jobs_by_pcb_stock=filter_jobs_by_pcb_stock)
        self.assertEqual(
            SimulationModel.jobs_fitting_remaining_work_time(simulation_model, 'W', jobs),
            [jobs[0], jobs[-1]])
        self.assertEqual(len(calls), 1)
        self.assertEqual(
            SimulationModel.jobs_fitting_remaining_work_time(simulation_model, 'W', [jobs[1]]), [])
        self.assertEqual(len(calls), 1)

    def test_ready_rules_are_in_one_block(self):
        file_name = 'discrete_event_simulation/simulation_model.py'
        methods = list(methods_of_class(file_name, 'SimulationModel'))
        self.assertIn('ready_queue', methods)
        start = methods.index('ready_queue')
        block_end = start + len(READY_QUEUE_METHODS_IN_ONE_BLOCK)
        self.assertEqual(methods[start:block_end], READY_QUEUE_METHODS_IN_ONE_BLOCK)
        smt_line_methods = list(methods_of_class(
            'discrete_event_simulation/smt_line.py', 'SmtLine'))
        start = smt_line_methods.index(PCB_STOCK_METHODS_OF_SMT_LINE[0])
        block_end = start + len(PCB_STOCK_METHODS_OF_SMT_LINE)
        self.assertEqual(smt_line_methods[start:block_end], PCB_STOCK_METHODS_OF_SMT_LINE)
        kg_tree = ast.parse((ROOT / 'knowledge_graph.py').read_text(encoding='utf-8'))
        self.assertFalse(any(
            isinstance(node, ast.FunctionDef) and node.name == 'ready_queue'
            for node in ast.walk(kg_tree)))

    def test_final_candidates_wait_for_resource(self):
        clock = simpy.Environment()
        resource = simpy.Resource(clock, capacity=1)
        occupied = resource.request()
        jobs = [dict(job) for job in JOBS_WITH_OTHER_PROCESS_AT_THE_END]

        def is_work_time():
            return True

        def jobs_fitting_remaining_work_time(worker_group, waiting_jobs):
            return list(waiting_jobs)

        simulation_model = SimpleNamespace(
            simpy_environment=clock, worker_group_resources={'W': resource},
            waiting_jobs_by_worker_group={'W': jobs}, ready_queue_wake_event_by_worker_group={},
            is_work_time=is_work_time,
            jobs_fitting_remaining_work_time=jobs_fitting_remaining_work_time)
        waiting = clock.process(SimulationModel.ready_queue(simulation_model, 'W'))
        clock.run(until=1)
        self.assertFalse(waiting.triggered)
        resource.release(occupied)
        ready_queue_result = clock.run(until=waiting)
        worker_request = ready_queue_result['worker_request']
        self.assertTrue(worker_request.triggered)
        self.assertEqual(resource.count, 1)
        self.assertEqual(ready_queue_result['fitting_jobs'], jobs)
        self.assertEqual(ready_queue_result['candidate_process_codes'], ['A', 'B'])
        resource.release(worker_request)

    def test_job_selection_only_selects_and_starts(self):
        methods = methods_of_class(
            'discrete_event_simulation/simulation_model.py', 'SimulationModel')
        ready_queue_calls = called_names(methods['ready_queue'])
        selection_calls = called_names(methods['select_and_start_jobs'])
        self.assertIn('worker_group_resource.request', ready_queue_calls)
        self.assertIn('self.jobs_fitting_remaining_work_time', ready_queue_calls)
        self.assertIn('self.ready_queue', selection_calls)
        self.assertNotIn('worker_group_resource.request', selection_calls)
        self.assertNotIn('self.jobs_fitting_remaining_work_time', selection_calls)


if __name__ == '__main__':
    unittest.main()
