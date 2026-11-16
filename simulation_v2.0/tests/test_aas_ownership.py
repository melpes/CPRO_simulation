import dataclasses
import unittest
from unittest.mock import patch

import torch

import episode_procedure
import knowledge_graph
import scenario_conditions
from aas_preprocessing import aas_reader
from aas_preprocessing.path_extractor import PathExtractor, process_resource_groups
from discrete_event_simulation import simulation_generator
from discrete_event_simulation.simulation_model import SimulationModel
from reinforcement_learning import action, model, state

SCENARIO = 'S1'
SMALL_PRODUCTION_QUANTITY_PER_PRODUCT = 2
SIMULATION_SEED = 98102105
NEW_MODEL_INITIAL_WEIGHT_SEED = 21
MACHINE_FIELDS = {
    'kg_node_path', 'MachineGroupCode', 'rated_power_kw', 'MaxCapacity', 'CapacityPerCycle',
    'RequiresOperator'}
MACHINE_STATIC_FEATURE_NAMES = [
    'Machine.rated_power_kw', 'Machine.MaxCapacity', 'Machine.RequiresOperator']
FIRST_CYCLE_TIME_OF_SHARED_MACHINE_PROCESSES = 11
SEC_AFTER_PROCESSING_ENDS = 2


class AASOwnershipTest(unittest.TestCase):
    def setUp(self):
        self.conditions = scenario_conditions.conditions_of_scenario(SCENARIO)
        self.conditions['production_quantity_per_product'] = (
            SMALL_PRODUCTION_QUANTITY_PER_PRODUCT)
        self.path_extractor = PathExtractor(self.conditions['aas_directory'])
        self.records = self.path_extractor.process_records

    def generate_simulation_model(self):
        with patch.object(episode_procedure, 'PathExtractor', return_value=self.path_extractor):
            episode = episode_procedure.EpisodeProcedure(
                self.conditions, SIMULATION_SEED, SimulationModel)
            episode.generate_simulation_model()
        simulation_model = episode.simulation_model
        simulation_model.reset()
        return simulation_model

    def share_machine(self, source_code, target_codes):
        source = self.records[source_code].Recipes[0].ResourceUnitRef
        for code in target_codes:
            for recipe in self.records[code].Recipes:
                recipe.ResourceUnitRef.value = aas_reader.SMEPath(source.value)
        return source

    def simulation_model_with_shared_machine(self):
        self.share_machine('Line_1_Loader', ('Line_1_ScreenPrinter', 'Line_2_Loader'))
        return self.generate_simulation_model()

    def test_machine_has_only_resource_attributes(self):
        field_names = {field.name for field in dataclasses.fields(knowledge_graph.Machine)}
        self.assertEqual(field_names, MACHINE_FIELDS)
        for attributes in self.path_extractor.extract_machine_nodes().values():
            self.assertEqual(set(attributes), MACHINE_FIELDS - {'kg_node_path'})
        state_builder = state.StateBuilder(self.generate_simulation_model())
        machine_feature_names = [
            name for name in state_builder.static_node_feature_names
            if name.startswith('Machine.')]
        self.assertEqual(machine_feature_names, MACHINE_STATIC_FEATURE_NAMES)

    def test_shared_machine_keeps_each_process_context(self):
        members = {}
        for code, record in self.records.items():
            if record.smt_line_first_process_code:
                members[code] = record
        selected = ['Line_1_Loader', 'Line_1_Mounter', 'Line_2_Loader']
        machine_reference = self.share_machine(selected[0], selected)
        for index, code in enumerate(selected):
            for recipe in self.records[code].Recipes:
                recipe.CycleTime.value = FIRST_CYCLE_TIME_OF_SHARED_MACHINE_PROCESSES + index
        steps = self.path_extractor.extract_smt_line_steps()
        member_paths = {
            aas_reader.kg_node_path_from_sme(record.ProcessCode) for record in members.values()}
        self.assertEqual(set(steps), member_paths)
        kg = knowledge_graph.KnowledgeGraph(self.path_extractor)
        generated = simulation_generator.generate_simulation_processes_and_resources(kg)
        processes = generated['simulation_processes'].processes
        process_by_sme_path = {}
        for process in processes.values():
            process_by_sme_path[process.process_sme_path] = process
        shared_machine_path = aas_reader.kg_node_path_from_sme(machine_reference.target)
        for index, code in enumerate(selected):
            record = self.records[code]
            path = aas_reader.kg_node_path_from_sme(record.ProcessCode)
            attributes = steps[path]
            process = process_by_sme_path[path]
            self.assertEqual(
                attributes['process_kg_node_path'], self.path_extractor.process_kg_node_path(code))
            self.assertEqual(attributes['machine_kg_node_paths'], [shared_machine_path])
            self.assertEqual(process.process_sme_path, path)
            self.assertEqual(process.machine_kg_node_paths, attributes['machine_kg_node_paths'])
            self.assertEqual(
                process.CycleTime, FIRST_CYCLE_TIME_OF_SHARED_MACHINE_PROCESSES + index)
            self.assertEqual(
                process.simultaneous_processing_quantity,
                attributes['simultaneous_processing_quantity'])
            self.assertEqual(
                process.defect_probability_per_output_item,
                record.defect_probability_per_output_item)
            self.assertEqual(process.BranchProbability, record.BranchProbability)
            requires_worker_in_aas = bool(record.ProcessCode.parent_element.RequiresWorker.value)
            self.assertEqual(process.RequiresWorker, requires_worker_in_aas)
            self.assertEqual(process.worker_work_time_sec, attributes['worker_work_time_sec'])
            expected_worker_groups = set()
            for resource_group in process_resource_groups(record):
                if 'WorkerPool' in resource_group:
                    expected_worker_groups.add(resource_group.WorkerGroupCode.value)
            assigned_worker_groups = set()
            for worker_group, worker_group_values in generated['worker_groups'].items():
                if process.process_code in worker_group_values['process_codes']:
                    assigned_worker_groups.add(worker_group)
            self.assertEqual(assigned_worker_groups, expected_worker_groups)
        self.assertEqual(len(processes), len(process_by_sme_path))
        simulation_model = self.generate_simulation_model()
        simulation_processes = simulation_model.simulation_processes.processes
        for line_information in simulation_model.smt_line_information.values():
            step_process_codes = line_information['step_process_codes']
            step_cycle_times = line_information['step_cycle_times']
            self.assertEqual(len(step_process_codes), len(step_cycle_times))
            for step_process_code, cycle_time in zip(step_process_codes, step_cycle_times):
                step_process = simulation_processes[step_process_code]
                self.assertEqual(step_process.CycleTime, cycle_time)
                self.assertIn(step_process.process_sme_path, steps)

    def test_shared_machine_lot_accounting_uses_machine_unit_codes(self):
        simulation_model = self.simulation_model_with_shared_machine()
        smt_line = next(iter(simulation_model.smt_production_plan))
        line_information = simulation_model.smt_line_information[smt_line]
        planned_item = simulation_model.smt_production_plan[smt_line][0]
        array_count = 1
        decision = simulation_model.simpy_environment.process(
            simulation_model.decide_smt_start_timing(
                smt_line, planned_item['item_code'], array_count,
                int(planned_item['quantity_per_array']), None))
        start_timing_record = simulation_model.simpy_environment.run(until=decision)
        machine_unit_codes = line_information['machine_unit_codes']
        self.assertEqual(set(start_timing_record['resources_at_choice']), set(machine_unit_codes))
        self.assertEqual(len(machine_unit_codes), len(set(machine_unit_codes)))
        simulation_model.report_smt_lot_result(start_timing_record, None)
        self.assertEqual(start_timing_record['weighted_kwh'], 0)

    def test_adjacent_processes_can_reuse_same_machine(self):
        simulation_model = self.simulation_model_with_shared_machine()
        step_process_codes = next(iter(simulation_model.step_process_codes_by_smt_line.values()))
        process_code = step_process_codes[0]
        process = simulation_model.simulation_processes.processes[process_code]
        duration_sec = 1
        operation = simulation_model.simpy_environment.process(
            simulation_model.occupy_machines_and_process(
                process, duration_sec, simulation_model.next_machine_names(process_code), set()))
        simulation_model.simpy_environment.run(until=SEC_AFTER_PROCESSING_ENDS)
        self.assertTrue(operation.triggered, '지금 쓰는 설비를 다음 단계용으로 다시 요청하면 멈춤')
        first_machine_resource = simulation_model.machine_resources[process.machine_unit_codes[0]]
        self.assertEqual(first_machine_resource.count, 0)

    def test_shared_machine_as_is_episode_completes(self):
        self.share_machine('Line_1_Loader', ('Line_1_ScreenPrinter', 'Line_2_Loader'))
        with patch.object(episode_procedure, 'PathExtractor', return_value=self.path_extractor):
            episode_result = episode_procedure.run_as_is_episode(self.conditions, SIMULATION_SEED)
        self.assertTrue(episode_result['metrics']['complete'])

    def test_shared_machine_model_episode_completes(self):
        simulation_model = self.simulation_model_with_shared_machine()
        input_dimensions = state.StateBuilder(simulation_model).input_dimensions()
        reinforcement_learning_model = model.create_model(
            input_dimensions, NEW_MODEL_INITIAL_WEIGHT_SEED)
        weights_before = {}
        for name, weight in reinforcement_learning_model.state_dict().items():
            weights_before[name] = weight.clone()
        with patch.object(episode_procedure, 'PathExtractor', return_value=self.path_extractor):
            episode_result = episode_procedure.run_episode(
                self.conditions, SIMULATION_SEED, reinforcement_learning_model,
                action.StartTimingEmissionRecord(None), action.EVALUATION_MODE, 0, False)
        self.assertTrue(episode_result['metrics']['complete'])
        weights_after = reinforcement_learning_model.state_dict()
        for name, weight in weights_before.items():
            self.assertTrue(torch.equal(weight, weights_after[name]), name)

    def test_smt_line_found_from_structure(self):
        smt_line_first_process_codes = set()
        consumed_item_codes = set()
        for record in self.records.values():
            if record.smt_line_first_process_code:
                smt_line_first_process_codes.add(record.smt_line_first_process_code)
            for recipe in record.Recipes:
                for input_item in recipe.InputItemCodeList:
                    consumed_item_codes.add(
                        aas_reader.referenced_code_value(input_item.InputItemCodeRef))
        self.assertGreater(len(smt_line_first_process_codes), 0)
        for first_process_code in smt_line_first_process_codes:
            member_codes = [
                code for code, record in self.records.items()
                if record.smt_line_first_process_code == first_process_code]
            output_item_codes = set()
            for code in member_codes:
                for recipe in self.records[code].Recipes:
                    output_item_codes.add(recipe.OutputItemCode.value)
            self.assertTrue(output_item_codes & consumed_item_codes)
            self.assertFalse(self.records[first_process_code].previous_processes)
            for code in member_codes:
                self.assertEqual(self.records[code].product_code, first_process_code)


if __name__ == '__main__':
    unittest.main()
