import math
from dataclasses import dataclass

from aas_preprocessing import aas_reader
from discrete_event_simulation.simulation_model import SimulationModel
from knowledge_graph import (
    Join, KnowledgeGraph, Machine, Process, Require, Sequence, Warehouse, Worker,
    code_from_kg_node_path)


# ================================================ 시뮬레이션 공정의 속성: KG Process 노드의 속성과 공정이 쓰는 투입 자재·설비·작업자 ================================================
@dataclass
class SimulationProcess:
    process_code: str
    product_code: str
    is_defect_event_target_process: bool
    is_defect_event_handling_process: bool
    requires_no_worker_and_no_machine: bool
    CycleTime: float
    simultaneous_processing_quantity: int
    defect_probability_per_output_item: float
    process_rated_power_kw: float
    BranchProbability: float
    RequiresWorker: bool
    worker_work_time_sec: float
    InputItemCodeList: dict
    machine_unit_codes: list
    process_sme_path: str
    machine_kg_node_paths: list
    worker_kg_node_paths: list


# ================================================ 시뮬레이션 모델이 KG에서 가져다 쓰는 관계: 공정의 투입 자재·설비·작업자·선행 공정 ================================================
KG_RELATIONS_USED_BY_SIMULATION = {
    'process_to_input_item': {
        'source_node_class': Process,
        'edge_classes': [Require],
        'target_node_class': Warehouse,
    },
    'process_to_machine': {
        'source_node_class': Process,
        'edge_classes': [Require],
        'target_node_class': Machine,
    },
    'process_to_worker': {
        'source_node_class': Process,
        'edge_classes': [Require],
        'target_node_class': Worker,
    },
    'previous_process_to_process': {
        'source_node_class': Process,
        'edge_classes': [Sequence, Join],
        'target_node_class': Process,
    },
}


# ================================================ SMT 라인 단계 공정의 공정 정격전력(kW): SMT 라인의 전력은 설비 정격전력으로 계산하므로 0 ================================================
SMT_LINE_STEP_PROCESS_RATED_POWER_KW = 0.0


# ================================================ 작업자 그룹을 처음 만들 때의 값: 인원은 작업자 노드를 세어 올리고 UnitsPerWorker는 맡은 공정의 simultaneous_processing_quantity 최댓값으로 올림 ================================================
WORKER_GROUP_STARTING_VALUES = {
    'worker_count': 0,
    'UnitsPerWorker': 1,
}


# ================================================ 제품 BOM 품목의 entityType: 창고가 재고를 관리하는 품목, 공장에서 직접 만드는 품목(SMT 라인이 생산) ================================================
CO_MANAGED_ENTITY_TYPE = 'CoManagedEntity'
SELF_MANAGED_ENTITY_TYPE = 'SelfManagedEntity'


# ================================================ 공정별 선행 공정 코드 적기: 공정별 다음 공정 코드를 뒤집어 적음 ================================================
def collect_previous_process_codes(following_process_codes_by_process_code):
    previous_process_codes_by_process_code = {}
    for process_code, following_process_codes in following_process_codes_by_process_code.items():
        for following_process_code in following_process_codes:
            if following_process_code not in previous_process_codes_by_process_code:
                previous_process_codes_by_process_code[following_process_code] = []
            previous_process_codes_by_process_code[following_process_code].append(process_code)
    return previous_process_codes_by_process_code


# ================================================ 공정 선후관계·투입 자재 조회: 시뮬레이션 공정 목록, 선행·다음 공정, 마지막 공정 판정, 투입 자재 재고 확인 ================================================
class SimulationProcesses:

    def __init__(self, processes, following_process_codes_by_process_code):
        self.processes = processes
        self.following_process_codes_by_process_code = following_process_codes_by_process_code
        self.previous_process_codes_by_process_code = collect_previous_process_codes(
            following_process_codes_by_process_code)

    def previous_process_codes(self, process_code):
        if process_code not in self.previous_process_codes_by_process_code:
            return []
        return self.previous_process_codes_by_process_code[process_code]

    def following_process_codes(self, process_code):
        if process_code not in self.following_process_codes_by_process_code:
            return []
        return self.following_process_codes_by_process_code[process_code]

    def is_last_process(self, process_code):
        if process_code not in self.processes:
            return False
        process = self.processes[process_code]
        has_following_process = process_code in self.following_process_codes_by_process_code
        return not has_following_process and not process.is_defect_event_handling_process

    def are_input_items_in_stock(self, process_code, warehouse_inventory):
        process = self.processes[process_code]
        for item_code, input_quantity in process.InputItemCodeList.items():
            for stock_items_of_category in warehouse_inventory.values():
                if item_code not in stock_items_of_category:
                    continue
                stock_item = stock_items_of_category[item_code]
                has_enough_stock = stock_item.present_stock >= input_quantity
                if not has_enough_stock:
                    return False
        return True


# ================================================ KG의 관계(Edge)에서 공정별 투입 자재·설비·작업자 모으기 ================================================
def find_kg_edges_used_by_simulation(edges, relation_name):
    relation = KG_RELATIONS_USED_BY_SIMULATION[relation_name]
    found_edges = []
    for edge in edges:
        has_edge_class = type(edge) in relation['edge_classes']
        has_source_node_class = isinstance(edge.source, relation['source_node_class'])
        has_target_node_class = isinstance(edge.target, relation['target_node_class'])
        if has_edge_class and has_source_node_class and has_target_node_class:
            found_edges.append(edge)
    return found_edges


def collect_InputItemCodeList_by_process(edges):
    InputItemCodeList_by_process_path = {}
    for edge in find_kg_edges_used_by_simulation(edges, 'process_to_input_item'):
        process_path = edge.source.kg_node_path
        if process_path not in InputItemCodeList_by_process_path:
            InputItemCodeList_by_process_path[process_path] = {}
        InputItemCodeList = InputItemCodeList_by_process_path[process_path]
        item_code = code_from_kg_node_path(edge.target.kg_node_path)
        InputItemCodeList[item_code] = edge.InputItemQuantity
    return InputItemCodeList_by_process_path


def collect_resource_kg_node_paths_by_process(edges, relation_name):
    resource_kg_node_paths_by_process_path = {}
    for edge in find_kg_edges_used_by_simulation(edges, relation_name):
        process_path = edge.source.kg_node_path
        if process_path not in resource_kg_node_paths_by_process_path:
            resource_kg_node_paths_by_process_path[process_path] = []
        resource_kg_node_paths_by_process_path[process_path].append(edge.target.kg_node_path)
    return resource_kg_node_paths_by_process_path


def codes_from_kg_node_paths(kg_node_paths):
    return [code_from_kg_node_path(kg_node_path) for kg_node_path in kg_node_paths]


# ================================================ SMT 라인 풀기: SMT 라인 Process 노드에 속한 단계를 단계 순서대로 묶기 ================================================
def read_process_flow_order_in_smt_line(smt_line_step):
    return smt_line_step['attributes']['process_flow_order_in_smt_line']


def group_smt_line_steps_by_process_node(smt_line_steps, process_nodes):
    smt_line_steps_by_process_node_path = {}
    for process_node in process_nodes:
        steps_of_process_node = []
        for process_sme_path, step_attributes in smt_line_steps.items():
            if step_attributes['process_kg_node_path'] == process_node.kg_node_path:
                steps_of_process_node.append({
                    'process_sme_path': process_sme_path,
                    'attributes': step_attributes,
                })
        if steps_of_process_node:
            smt_line_steps_by_process_node_path[process_node.kg_node_path] = sorted(
                steps_of_process_node, key=read_process_flow_order_in_smt_line)
    return smt_line_steps_by_process_node_path


# ================================================ SMT 라인 단계의 공정 코드 정하기: 설비가 1대이고 그 설비 코드가 다른 단계·공정 코드와 겹치지 않으면 설비 코드, 아니면 단계의 AAS Process 요소 경로 ================================================
def choose_smt_line_step_candidate_codes(smt_line_steps):
    candidate_code_by_process_sme_path = {}
    for process_sme_path, step_attributes in smt_line_steps.items():
        machine_kg_node_paths = step_attributes['machine_kg_node_paths']
        uses_single_machine = len(machine_kg_node_paths) == 1
        if uses_single_machine:
            only_machine_kg_node_path = machine_kg_node_paths[0]
            candidate_code = code_from_kg_node_path(only_machine_kg_node_path)
        else:
            candidate_code = process_sme_path
        candidate_code_by_process_sme_path[process_sme_path] = candidate_code
    return candidate_code_by_process_sme_path


def assign_smt_line_step_process_codes(smt_line_steps, process_nodes):
    candidate_code_by_process_sme_path = choose_smt_line_step_candidate_codes(smt_line_steps)
    codes_in_use = list(candidate_code_by_process_sme_path.values())
    for process_node in process_nodes:
        codes_in_use.append(code_from_kg_node_path(process_node.kg_node_path))
    process_code_by_process_sme_path = {}
    for process_sme_path, candidate_code in candidate_code_by_process_sme_path.items():
        is_used_only_once = codes_in_use.count(candidate_code) == 1
        if is_used_only_once:
            process_code_by_process_sme_path[process_sme_path] = candidate_code
        else:
            process_code_by_process_sme_path[process_sme_path] = process_sme_path
    return process_code_by_process_sme_path


# ================================================ 시뮬레이션 공정 만들기: SMT 라인 Process 노드는 단계마다 한 공정(투입 자재 없음, 공정 정격전력 0), 그 밖의 Process 노드는 노드마다 한 공정 ================================================
def generate_smt_line_step_process(process_code, product_code, smt_line_step):
    step_attributes = smt_line_step['attributes']
    machine_kg_node_paths = list(step_attributes['machine_kg_node_paths'])
    no_input_items = {}
    return SimulationProcess(
        process_code=process_code,
        product_code=product_code,
        is_defect_event_target_process=step_attributes['is_defect_event_target_process'],
        is_defect_event_handling_process=step_attributes['is_defect_event_handling_process'],
        requires_no_worker_and_no_machine=step_attributes['requires_no_worker_and_no_machine'],
        CycleTime=step_attributes['CycleTime'],
        simultaneous_processing_quantity=step_attributes['simultaneous_processing_quantity'],
        defect_probability_per_output_item=step_attributes['defect_probability_per_output_item'],
        process_rated_power_kw=SMT_LINE_STEP_PROCESS_RATED_POWER_KW,
        BranchProbability=step_attributes['BranchProbability'],
        RequiresWorker=step_attributes['RequiresWorker'],
        worker_work_time_sec=step_attributes['worker_work_time_sec'],
        InputItemCodeList=no_input_items,
        machine_unit_codes=codes_from_kg_node_paths(machine_kg_node_paths),
        process_sme_path=smt_line_step['process_sme_path'],
        machine_kg_node_paths=machine_kg_node_paths,
        worker_kg_node_paths=list(step_attributes['worker_kg_node_paths']))


def generate_process_from_process_node(
        process_node, InputItemCodeList, machine_kg_node_paths, worker_kg_node_paths):
    return SimulationProcess(
        process_code=code_from_kg_node_path(process_node.kg_node_path),
        product_code=process_node.product_code,
        is_defect_event_target_process=process_node.is_defect_event_target_process,
        is_defect_event_handling_process=process_node.is_defect_event_handling_process,
        requires_no_worker_and_no_machine=process_node.requires_no_worker_and_no_machine,
        CycleTime=process_node.CycleTime,
        simultaneous_processing_quantity=process_node.simultaneous_processing_quantity,
        defect_probability_per_output_item=process_node.defect_probability_per_output_item,
        process_rated_power_kw=process_node.process_rated_power_kw,
        BranchProbability=process_node.BranchProbability,
        RequiresWorker=process_node.RequiresWorker,
        worker_work_time_sec=process_node.worker_work_time_sec,
        InputItemCodeList=dict(InputItemCodeList),
        machine_unit_codes=codes_from_kg_node_paths(machine_kg_node_paths),
        process_sme_path=process_node.kg_node_path,
        machine_kg_node_paths=list(machine_kg_node_paths),
        worker_kg_node_paths=list(worker_kg_node_paths))


def generate_processes_by_process_node(
        process_nodes, smt_line_steps_by_process_node_path, process_code_by_process_sme_path,
        InputItemCodeList_by_process_path, machine_kg_node_paths_by_process_path,
        worker_kg_node_paths_by_process_path):
    processes_by_process_node_path = {}
    for process_node in process_nodes:
        process_node_path = process_node.kg_node_path
        processes_of_process_node = []
        if process_node_path in smt_line_steps_by_process_node_path:
            for smt_line_step in smt_line_steps_by_process_node_path[process_node_path]:
                process_code = process_code_by_process_sme_path[smt_line_step['process_sme_path']]
                step_process = generate_smt_line_step_process(
                    process_code, process_node.product_code, smt_line_step)
                processes_of_process_node.append(step_process)
        else:
            process = generate_process_from_process_node(
                process_node,
                InputItemCodeList_by_process_path.get(process_node_path, {}),
                machine_kg_node_paths_by_process_path.get(process_node_path, []),
                worker_kg_node_paths_by_process_path.get(process_node_path, []))
            processes_of_process_node.append(process)
        processes_by_process_node_path[process_node_path] = processes_of_process_node
    return processes_by_process_node_path


def list_step_process_codes_by_smt_line(
        smt_line_steps_by_process_node_path, processes_by_process_node_path):
    step_process_codes_by_smt_line = {}
    for smt_line_node_path in smt_line_steps_by_process_node_path:
        smt_line_process_code = code_from_kg_node_path(smt_line_node_path)
        step_process_codes = []
        for process in processes_by_process_node_path[smt_line_node_path]:
            step_process_codes.append(process.process_code)
        step_process_codes_by_smt_line[smt_line_process_code] = step_process_codes
    return step_process_codes_by_smt_line


# ================================================ 선행 공정 연결: SMT 라인 안에서는 앞 단계, KG의 Sequence·Join 관계에서는 앞 Process 노드의 마지막 공정 ================================================
def connect_previous_processes(processes_by_process_node_path, edges):
    previous_processes_by_process_code = {}
    for processes_of_process_node in processes_by_process_node_path.values():
        for step_index, process in enumerate(processes_of_process_node):
            previous_processes = []
            is_first_process_of_node = step_index == 0
            if not is_first_process_of_node:
                previous_step_process = processes_of_process_node[step_index - 1]
                previous_processes.append({
                    'process_code': previous_step_process.process_code,
                    'edge_class': Sequence,
                })
            previous_processes_by_process_code[process.process_code] = previous_processes
    for edge in find_kg_edges_used_by_simulation(edges, 'previous_process_to_process'):
        processes_of_previous_node = processes_by_process_node_path[edge.source.kg_node_path]
        processes_of_following_node = processes_by_process_node_path[edge.target.kg_node_path]
        last_process_of_previous_node = processes_of_previous_node[-1]
        first_process_of_following_node = processes_of_following_node[0]
        previous_processes_by_process_code[first_process_of_following_node.process_code].append({
            'process_code': last_process_of_previous_node.process_code,
            'edge_class': type(edge),
        })
    return previous_processes_by_process_code


# ================================================ 공정 순서 정리: 같은 product_code의 공정끼리 모으고, 그 순서로 다음 공정 코드 적기 ================================================
def order_processes_by_product(processes_by_process_node_path):
    processes_by_product_code = {}
    for processes_of_process_node in processes_by_process_node_path.values():
        for process in processes_of_process_node:
            if process.product_code not in processes_by_product_code:
                processes_by_product_code[process.product_code] = {}
            processes_by_product_code[process.product_code][process.process_code] = process
    processes = {}
    for processes_of_product in processes_by_product_code.values():
        processes.update(processes_of_product)
    return processes


def collect_following_process_codes(processes, previous_processes_by_process_code):
    following_process_codes_by_process_code = {}
    for process_code in processes:
        for previous_process in previous_processes_by_process_code[process_code]:
            previous_process_code = previous_process['process_code']
            if previous_process_code not in following_process_codes_by_process_code:
                following_process_codes_by_process_code[previous_process_code] = []
            following_process_codes_by_process_code[previous_process_code].append(process_code)
    return following_process_codes_by_process_code


# ================================================ 선후관계 종류별 공정 목록: 선행 공정 없음, 선행 공정 중 하나 완료(Sequence), 선행 공정 모두 완료(Join). 불량 이벤트 처리 공정은 제외 ================================================
def group_process_codes_by_previous_process_condition(
        processes, previous_processes_by_process_code):
    process_codes_without_previous_process = []
    process_codes_after_any_previous_process = []
    process_codes_after_all_previous_processes = []
    for process_code, process in processes.items():
        if process.is_defect_event_handling_process:
            continue
        previous_processes = previous_processes_by_process_code[process_code]
        has_join_edge = False
        for previous_process in previous_processes:
            if previous_process['edge_class'] is Join:
                has_join_edge = True
        if not previous_processes:
            process_codes_without_previous_process.append(process_code)
        elif has_join_edge:
            process_codes_after_all_previous_processes.append(process_code)
        else:
            process_codes_after_any_previous_process.append(process_code)
    return {
        'process_codes_without_previous_process': process_codes_without_previous_process,
        'process_codes_after_any_previous_process': process_codes_after_any_previous_process,
        'process_codes_after_all_previous_processes': process_codes_after_all_previous_processes,
    }


# ================================================ 작업자 그룹과 설비: 그룹별 인원·UnitsPerWorker·맡은 공정 코드, 설비별 정격전력(kW)·MaxCapacity·CapacityPerCycle ================================================
def find_worker_group_codes_of_process(worker_kg_node_paths, worker_group_code_by_worker_path):
    worker_group_codes = []
    for worker_kg_node_path in worker_kg_node_paths:
        worker_group_code = worker_group_code_by_worker_path[worker_kg_node_path]
        if worker_group_code not in worker_group_codes:
            worker_group_codes.append(worker_group_code)
    return worker_group_codes


def generate_worker_groups(worker_nodes, processes):
    worker_groups = {}
    worker_group_code_by_worker_path = {}
    for worker_node in worker_nodes:
        worker_group_code = worker_node.WorkerGroupCode
        worker_group_code_by_worker_path[worker_node.kg_node_path] = worker_group_code
        if worker_group_code not in worker_groups:
            worker_groups[worker_group_code] = dict(WORKER_GROUP_STARTING_VALUES)
            worker_groups[worker_group_code]['process_codes'] = []
        worker_groups[worker_group_code]['worker_count'] += 1
    for process_code, process in processes.items():
        worker_group_codes = find_worker_group_codes_of_process(
            process.worker_kg_node_paths, worker_group_code_by_worker_path)
        for worker_group_code in worker_group_codes:
            worker_group = worker_groups[worker_group_code]
            worker_group['process_codes'].append(process_code)
            worker_group['UnitsPerWorker'] = max(
                worker_group['UnitsPerWorker'], int(process.simultaneous_processing_quantity))
    return worker_groups


def generate_machines(machine_nodes):
    machines = {}
    for machine_node in machine_nodes:
        machine_unit_code = code_from_kg_node_path(machine_node.kg_node_path)
        machines[machine_unit_code] = {
            'rated_power_kw': machine_node.rated_power_kw,
            'MaxCapacity': machine_node.MaxCapacity,
            'CapacityPerCycle': machine_node.CapacityPerCycle,
        }
    return machines


# ================================================ KG로 시뮬레이션 공정·자원 생성: 공정과 선후관계, 선후관계 종류별 공정 목록, 작업자 그룹, 설비, SMT 라인별 단계 공정 ================================================
def generate_simulation_processes_and_resources(kg):
    process_nodes = kg.nodes_of_class(Process)
    machine_nodes = kg.nodes_of_class(Machine)
    worker_nodes = kg.nodes_of_class(Worker)
    InputItemCodeList_by_process_path = collect_InputItemCodeList_by_process(kg.edges)
    machine_kg_node_paths_by_process_path = collect_resource_kg_node_paths_by_process(
        kg.edges, 'process_to_machine')
    worker_kg_node_paths_by_process_path = collect_resource_kg_node_paths_by_process(
        kg.edges, 'process_to_worker')
    smt_line_steps_by_process_node_path = group_smt_line_steps_by_process_node(
        kg.smt_line_steps, process_nodes)
    process_code_by_process_sme_path = assign_smt_line_step_process_codes(
        kg.smt_line_steps, process_nodes)
    processes_by_process_node_path = generate_processes_by_process_node(
        process_nodes, smt_line_steps_by_process_node_path, process_code_by_process_sme_path,
        InputItemCodeList_by_process_path, machine_kg_node_paths_by_process_path,
        worker_kg_node_paths_by_process_path)
    previous_processes_by_process_code = connect_previous_processes(
        processes_by_process_node_path, kg.edges)
    processes = order_processes_by_product(processes_by_process_node_path)
    following_process_codes_by_process_code = collect_following_process_codes(
        processes, previous_processes_by_process_code)
    simulation_processes = SimulationProcesses(processes, following_process_codes_by_process_code)
    process_codes_by_previous_process_condition = (
        group_process_codes_by_previous_process_condition(
            processes, previous_processes_by_process_code))
    processes_and_resources = {
        'simulation_processes': simulation_processes,
        'worker_groups': generate_worker_groups(worker_nodes, processes),
        'machines': generate_machines(machine_nodes),
        'step_process_codes_by_smt_line': list_step_process_codes_by_smt_line(
            smt_line_steps_by_process_node_path, processes_by_process_node_path),
    }
    processes_and_resources.update(process_codes_by_previous_process_condition)
    return processes_and_resources


# ================================================ 제품별 조건 준비: 제품 코드가 AAS에 있는지 확인, 납기(일)를 초로 변환 ================================================
def check_product_codes_are_in_aas(product_codes, value_by_product, value_name):
    unknown_product_codes = []
    for product_code in value_by_product:
        if product_code not in product_codes:
            unknown_product_codes.append(product_code)
    if unknown_product_codes:
        raise ValueError(
            f'{value_name}: AAS에 없는 제품 코드 {sorted(unknown_product_codes)}'
            f' (AAS의 제품 코드: {product_codes})')


def convert_due_day_to_sec(product_codes, due_day_by_product):
    due_sec_by_product = {}
    for product_code in product_codes:
        if product_code in due_day_by_product:
            due_day = due_day_by_product[product_code]
            due_sec_by_product[product_code] = due_day * aas_reader.SECONDS_PER_DAY
    return due_sec_by_product


# ================================================ SMT 생산 계획: 공장에서 직접 만드는 품목의 필요 수량을 어레이 수로 바꿔 SMT 라인에 차례로 나누기 ================================================
def find_smt_line_product_codes(processes, step_process_codes_by_smt_line):
    smt_line_product_codes = []
    for step_process_codes in step_process_codes_by_smt_line.values():
        for step_process_code in step_process_codes:
            product_code = processes[step_process_code].product_code
            if product_code not in smt_line_product_codes:
                smt_line_product_codes.append(product_code)
    return smt_line_product_codes


def sum_required_self_managed_item_quantities(
        processes, self_managed_item_codes_by_category, target_quantity_by_product):
    self_managed_item_codes = []
    for item_codes in self_managed_item_codes_by_category.values():
        self_managed_item_codes.extend(item_codes)
    required_quantity_by_item_code = {}
    for process in processes.values():
        if process.product_code not in target_quantity_by_product:
            continue
        target_quantity = target_quantity_by_product[process.product_code]
        for item_code, input_quantity in process.InputItemCodeList.items():
            if item_code not in self_managed_item_codes:
                continue
            if item_code not in required_quantity_by_item_code:
                required_quantity_by_item_code[item_code] = 0
            required_quantity_by_item_code[item_code] += input_quantity * target_quantity
    return required_quantity_by_item_code


def find_largest_simultaneous_processing_quantity(processes, product_code):
    simultaneous_processing_quantities = []
    for process in processes.values():
        if process.product_code == product_code:
            simultaneous_processing_quantities.append(int(process.simultaneous_processing_quantity))
    return max(simultaneous_processing_quantities)


def plan_smt_production(
        processes, step_process_codes_by_smt_line, self_managed_item_codes_by_category,
        target_quantity_by_product):
    smt_line_product_codes = find_smt_line_product_codes(
        processes, step_process_codes_by_smt_line)
    required_quantity_by_item_code = sum_required_self_managed_item_quantities(
        processes, self_managed_item_codes_by_category, target_quantity_by_product)
    if not smt_line_product_codes or not required_quantity_by_item_code:
        return {}
    first_smt_line_product_code = smt_line_product_codes[0]
    quantity_per_array = find_largest_simultaneous_processing_quantity(
        processes, first_smt_line_product_code)
    sorted_smt_line_product_codes = sorted(smt_line_product_codes)
    smt_production_plan = {}
    for smt_line_product_code in sorted_smt_line_product_codes:
        smt_production_plan[smt_line_product_code] = []
    for item_index, item_code in enumerate(sorted(required_quantity_by_item_code)):
        required_quantity = required_quantity_by_item_code[item_code]
        smt_line_index = item_index % len(sorted_smt_line_product_codes)
        smt_line_product_code = sorted_smt_line_product_codes[smt_line_index]
        smt_production_plan[smt_line_product_code].append({
            'item_code': item_code,
            'array_count': math.ceil(required_quantity / quantity_per_array),
            'quantity_per_array': quantity_per_array,
        })
    return smt_production_plan


# ================================================ 시뮬레이션 모델에 넘길 값 생성: AAS 추출 → KG 생성 → 시뮬레이션 공정·자원 생성 → SMT 생산 계획 → 시나리오 조건과 함께 묶기 ================================================
def generate_simulation_model_arguments(
        path_extractor, target_quantity_by_product, due_day_by_product, base_load_kw,
        electricity_time_band_weights, infinite_stock):
    product_codes = path_extractor.extract_product_codes()
    check_product_codes_are_in_aas(
        product_codes, target_quantity_by_product, 'target_quantity_by_product')
    check_product_codes_are_in_aas(product_codes, due_day_by_product, 'due_day_by_product')
    kg = KnowledgeGraph(path_extractor)
    processes_and_resources = generate_simulation_processes_and_resources(kg)
    bom_item_codes = path_extractor.extract_bom_item_codes()
    self_managed_item_codes_by_category = bom_item_codes[SELF_MANAGED_ENTITY_TYPE]
    work_schedule = path_extractor.extract_work_schedule()
    smt_production_plan = plan_smt_production(
        processes_and_resources['simulation_processes'].processes,
        processes_and_resources['step_process_codes_by_smt_line'],
        self_managed_item_codes_by_category, target_quantity_by_product)
    simulation_model_arguments = {'knowledge_graph': kg}
    simulation_model_arguments.update(processes_and_resources)
    simulation_model_arguments.update({
        'smt_production_plan': smt_production_plan,
        'target_quantity_by_product': dict(target_quantity_by_product),
        'due_sec_by_product': convert_due_day_to_sec(product_codes, due_day_by_product),
        'RunLength': path_extractor.extract_run_length(),
        'WorkStartTime': work_schedule['WorkStartTime'],
        'WorkEndTime': work_schedule['WorkEndTime'],
        'BreakStartTime': work_schedule['BreakStartTime'],
        'break_end_sec': work_schedule['break_end_sec'],
        'co_managed_item_codes_by_category': bom_item_codes[CO_MANAGED_ENTITY_TYPE],
        'self_managed_item_codes_by_category': self_managed_item_codes_by_category,
        'stock_policy_by_category': path_extractor.extract_stock_policies(),
        'replenishment_lead_time_sec': path_extractor.extract_replenishment_lead_time_sec(),
        'infinite_stock': infinite_stock,
        'base_load_kw': base_load_kw,
        'electricity_time_band_weights': electricity_time_band_weights,
        'target_unit_resource_events': path_extractor.extract_target_unit_resource_events(),
        'mcf_recipe_structure': path_extractor.extract_mcf_recipe_structure(),
    })
    return simulation_model_arguments


# ================================================ 시뮬레이션 모델 생성: 넘길 값을 만들어 PCB 재고·작업자 재배치·SMT 착수 보류·SMT 필름 교체와 Chip 보충 이벤트·무한가동 조건과 함께 시뮬레이션 모델 클래스에 전달 ================================================
def generate_simulation_model(
        path_extractor, target_quantity_by_product, due_day_by_product, base_load_kw,
        electricity_time_band_weights, infinite_stock, pcb_stock_limited,
        pcb_initial_stock_ratio, worker_reallocation_conditions,
        start_delay_allowed_process_kg_node_paths, max_start_delay_sec,
        smt_material_event_conditions, infinite_operation_conditions,
        simulation_model_class=SimulationModel):
    simulation_model_arguments = generate_simulation_model_arguments(
        path_extractor, target_quantity_by_product, due_day_by_product, base_load_kw,
        electricity_time_band_weights, infinite_stock)
    simulation_model = simulation_model_class(
        pcb_stock_limited=pcb_stock_limited,
        pcb_initial_stock_ratio=pcb_initial_stock_ratio,
        worker_reallocation_conditions=worker_reallocation_conditions,
        start_delay_allowed_process_kg_node_paths=start_delay_allowed_process_kg_node_paths,
        max_start_delay_sec=max_start_delay_sec,
        smt_material_event_conditions=smt_material_event_conditions,
        infinite_operation_conditions=infinite_operation_conditions,
        **simulation_model_arguments)
    return simulation_model
