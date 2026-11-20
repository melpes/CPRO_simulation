import math

import numpy
import torch

import knowledge_graph
from knowledge_graph import Machine, Process, Require, Warehouse, Worker, code_from_kg_node_path


# ================================================ 정적 노드 특징: KG 노드 클래스별로 특징에 쓰는 속성. 적힌 순서가 학습된 모델의 입력 열 순서 ================================================
STATIC_NODE_FEATURE_FIELDS = {
    Process: [
        'CycleTime',
        'simultaneous_processing_quantity',
        'defect_probability_per_output_item',
        'process_rated_power_kw',
        'BranchProbability',
        'worker_work_time_sec',
    ],
    Machine: [
        'rated_power_kw',
        'MaxCapacity',
        'RequiresOperator',
    ],
}


# ================================================ 설비 노드에 더 붙이는 정적 특징: 그 설비를 쓰는 SMT 라인 단계 값의 평균. 오른쪽 값은 단계가 없거나 값이 비었을 때 쓰는 값 ================================================
MACHINE_FEATURES_FROM_SMT_LINE_STEPS = {
    'process_flow_order_in_smt_line': 0.0,
    'CycleTime': 0.0,
    'simultaneous_processing_quantity': 1.0,
    'defect_probability_per_output_item': 0.0,
    'BranchProbability': 1.0,
    'worker_work_time_sec': 0.0,
}


# ================================================ 정적 노드 특징 값 처리: 값이 비었을 때 넣는 값, 로그를 취한 뒤 정규화하는 속성 ================================================
STATIC_FEATURE_VALUE_WHEN_EMPTY = {
    'BranchProbability': 1.0,
}
STATIC_FEATURE_VALUE_WHEN_EMPTY_FOR_OTHER_FIELDS = 0.0
LOG_SCALED_STATIC_FEATURE_FIELDS = ['CycleTime', 'worker_work_time_sec']
SMT_LINE_STEP_COLUMN_PREFIX = 'smt_line_steps'


# ================================================ State 정규화 값: 학습된 모델의 입력에 묶인 값. 시간과 전력량은 기준 실행(S1-2, 제품별 540개, 2026-10-19 사전 검증 1회)의 결과 ================================================
REFERENCE_RUN_COMPLETION_SEC = 243625.0
REFERENCE_RUN_WEIGHTED_ENERGY_KWH = 10188.229662725927
MAX_START_DELAY_SEC = 21600.0
NOT_NORMALIZED = 1.0
SMALLEST_NORMALIZATION_VALUE = 1.0


# ================================================ 동적 노드 특징: 항목 이름과 정규화에 쓰는 값. 적힌 순서가 학습된 모델의 입력 열 순서(항목마다 값 열과 값 유무 열) ================================================
DYNAMIC_NODE_FEATURES = {
    'waiting_job_count': 'total_target_quantity',
    'candidate_job_count': 'total_target_quantity',
    'processing_job_count': 'total_target_quantity',
    'completed_job_count': 'total_target_quantity',
    'remaining_processing_time_sec': 'reference_run_completion_sec',
    'longest_waiting_time_sec': 'reference_run_completion_sec',
    'remaining_start_delay_sec': 'max_start_delay_sec',
    'machine_occupied_ratio': 'not_normalized',
    'machine_operating': 'not_normalized',
    'machine_available_ratio': 'not_normalized',
    'machine_remaining_processing_time_sec': 'reference_run_completion_sec',
    'machine_operating_power_kw': 'total_rated_power_kw',
    'worker_working_ratio': 'not_normalized',
    'worker_available_ratio': 'not_normalized',
    'worker_time_to_work_time_change_sec': 'reference_run_completion_sec',
    'stock_quantity': 'total_target_quantity',
    'required_quantity': 'total_target_quantity',
    'in_production_quantity': 'total_target_quantity',
    'ordered_quantity': 'total_target_quantity',
}


# ================================================ 전역 정보: 항목 이름과 정규화에 쓰는 값. 적힌 순서가 학습된 모델의 입력 열 순서(항목마다 값 열과 값 유무 열) ================================================
GLOBAL_INFORMATION = {
    'elapsed_time_sec': 'reference_run_completion_sec',
    'time_of_day_ratio': 'not_normalized',
    'is_work_time': 'not_normalized',
    'time_to_work_time_change_sec': 'reference_run_completion_sec',
    'electricity_time_band_weight': 'not_normalized',
    'time_to_electricity_time_band_change_sec': 'reference_run_completion_sec',
    'production_progress_rate': 'not_normalized',
    'shortest_time_to_due_sec': 'reference_run_completion_sec',
    'mean_time_to_due_sec': 'reference_run_completion_sec',
    'overdue_product_ratio': 'not_normalized',
    'current_power_kw': 'total_rated_power_kw',
    'cumulative_weighted_energy_kwh': 'reference_run_weighted_energy_kwh',
}


# ================================================ 모델에 주지 않는 전역 정보: 열 자리는 남기고 값과 값 유무를 모두 0으로 둠 ================================================
GLOBAL_INFORMATION_NOT_GIVEN_TO_MODEL = [
    'electricity_time_band_weight',
    'time_to_electricity_time_band_change_sec',
]


# ================================================ 항목 하나가 차지하는 열 수(값 열, 값 유무 열)와 시간 단위 ================================================
COLUMNS_PER_ITEM = 2
VALUE_IS_AVAILABLE = 1.0
SECONDS_PER_DAY = 86400.0


# ================================================ 공장 상태: 노드 임베딩의 평균값·최대값 ================================================
NODE_AXIS = 0
EMBEDDING_AXIS = -1
FEATURE_AXIS = 1


def factory_state(node_embeddings):
    mean_of_nodes = node_embeddings.mean(NODE_AXIS)
    max_of_nodes = node_embeddings.max(NODE_AXIS).values
    return torch.cat([mean_of_nodes, max_of_nodes], dim=EMBEDDING_AXIS)


def factory_state_dimension(node_embedding_dimension):
    mean_dimension = node_embedding_dimension
    max_dimension = node_embedding_dimension
    return mean_dimension + max_dimension


# ================================================ GNN 입력의 노드 줄 순서: KG 노드 클래스 순서대로 나열, 노드 번호를 찾는 이름은 공정이면 공정 코드, 그 밖은 KG 노드 경로 ================================================
def list_kg_nodes_in_class_order(nodes_by_class):
    kg_nodes = []
    for nodes in nodes_by_class.values():
        kg_nodes.extend(nodes)
    return kg_nodes


def node_name_in_gnn_input(node):
    if isinstance(node, Process):
        return code_from_kg_node_path(node.kg_node_path)
    return node.kg_node_path


def number_nodes_by_name(kg_nodes):
    node_index_by_name = {}
    for node_index, node in enumerate(kg_nodes):
        node_index_by_name[node_name_in_gnn_input(node)] = node_index
    return node_index_by_name


# ================================================ 설비별 SMT 라인 단계 값의 평균: 공정과 설비가 Require로 이어진 단계만 모음 ================================================
def average_smt_line_step_values_by_machine(edges, machine_nodes, smt_line_steps):
    machine_paths_required_by_process_path = {}
    for edge in edges:
        if not isinstance(edge, Require):
            continue
        if isinstance(edge.source, Process) and isinstance(edge.target, Machine):
            process_path = edge.source.kg_node_path
            if process_path not in machine_paths_required_by_process_path:
                machine_paths_required_by_process_path[process_path] = set()
            machine_paths_required_by_process_path[process_path].add(edge.target.kg_node_path)
    steps_by_machine_path = {}
    for machine_node in machine_nodes:
        steps_by_machine_path[machine_node.kg_node_path] = []
    for smt_line_step in smt_line_steps.values():
        machine_paths_required = machine_paths_required_by_process_path.get(
            smt_line_step['process_kg_node_path'], set())
        for machine_path in smt_line_step['machine_kg_node_paths']:
            if machine_path in machine_paths_required:
                steps_by_machine_path[machine_path].append(smt_line_step)
    average_values_by_machine_path = {}
    for machine_path, steps in steps_by_machine_path.items():
        average_values = {}
        for field, default_value in MACHINE_FEATURES_FROM_SMT_LINE_STEPS.items():
            step_values = []
            for step in steps:
                step_value = step.get(field)
                if step_value is None:
                    step_value = default_value
                step_values.append(step_value)
            if step_values:
                average_values[field] = sum(step_values) / len(step_values)
            else:
                average_values[field] = default_value
        average_values_by_machine_path[machine_path] = average_values
    return average_values_by_machine_path


# ================================================ 정적 노드 특징 값 하나 읽기와 열 하나 정규화: 빈 값 채우기, 로그, 열의 최대 절대값으로 나누기 ================================================
def static_feature_value(raw_value, field):
    value = raw_value
    if value is None:
        value = STATIC_FEATURE_VALUE_WHEN_EMPTY.get(
            field, STATIC_FEATURE_VALUE_WHEN_EMPTY_FOR_OTHER_FIELDS)
    value = float(value)
    if field in LOG_SCALED_STATIC_FEATURE_FIELDS:
        value = math.log1p(max(value, 0.0))
    return value


def divide_by_largest_absolute_value(values):
    largest_absolute_value = 0.0
    for value in values:
        largest_absolute_value = max(largest_absolute_value, abs(value))
    if largest_absolute_value == 0.0:
        largest_absolute_value = SMALLEST_NORMALIZATION_VALUE
    return [value / largest_absolute_value for value in values]


# ================================================ 정적 노드 특징 행렬 생성: 노드 클래스 표시 열, 클래스별 속성 열, 설비의 SMT 라인 단계 열 ================================================
def generate_static_node_features(nodes_by_class, edges, smt_line_steps,
                                  simulation_process_by_process_code):
    node_classes = list(nodes_by_class)
    feature_names = []
    for node_class in node_classes:
        feature_names.append(f'is_{node_class.__name__}')
    step_values_by_machine_path = average_smt_line_step_values_by_machine(
        edges, nodes_by_class[Machine], smt_line_steps)
    normalized_columns = []
    for node_class in node_classes:
        nodes = nodes_by_class[node_class]
        for field in STATIC_NODE_FEATURE_FIELDS.get(node_class, []):
            values = []
            for node in nodes:
                raw_value = getattr(node, field)
                process_code = code_from_kg_node_path(node.kg_node_path)
                is_process_rated_power = field == 'process_rated_power_kw' and node_class is Process
                if is_process_rated_power and process_code in simulation_process_by_process_code:
                    simulation_process = simulation_process_by_process_code[process_code]
                    raw_value = simulation_process.process_rated_power_kw
                values.append(static_feature_value(raw_value, field))
            normalized_columns.append({
                'node_class': node_class,
                'feature_name': f'{node_class.__name__}.{field}',
                'values': divide_by_largest_absolute_value(values),
            })
        if node_class is not Machine:
            continue
        for field in MACHINE_FEATURES_FROM_SMT_LINE_STEPS:
            values = []
            for node in nodes:
                raw_value = step_values_by_machine_path[node.kg_node_path][field]
                values.append(static_feature_value(raw_value, field))
            normalized_columns.append({
                'node_class': node_class,
                'feature_name': f'{SMT_LINE_STEP_COLUMN_PREFIX}.{field}',
                'values': divide_by_largest_absolute_value(values),
            })
    for column in normalized_columns:
        feature_names.append(column['feature_name'])
    node_count = 0
    for nodes in nodes_by_class.values():
        node_count += len(nodes)
    static_node_features = torch.zeros(node_count, len(feature_names))
    first_node_index = 0
    for class_index, node_class in enumerate(node_classes):
        class_node_count = len(nodes_by_class[node_class])
        last_node_index = first_node_index + class_node_count
        static_node_features[first_node_index:last_node_index, class_index] = 1.0
        for column_offset, column in enumerate(normalized_columns):
            if column['node_class'] is not node_class:
                continue
            column_index = len(node_classes) + column_offset
            for node_offset, value in enumerate(column['values']):
                static_node_features[first_node_index + node_offset, column_index] = value
        first_node_index = last_node_index
    return {
        'static_node_features': static_node_features,
        'static_node_feature_names': feature_names,
    }


# ================================================ 노드 연결(Edge) 생성: KG Edge마다 정방향·역방향 연결을 만들고 관계와 도착 노드가 같은 연결끼리 묶음 ================================================
def relation_index_of_edge(edge):
    for relation_index, relation in enumerate(knowledge_graph.RELATIONS):
        is_edge_class = isinstance(edge, relation['edge_class'])
        is_source_class = isinstance(edge.source, relation['source_node_class'])
        is_target_class = isinstance(edge.target, relation['target_node_class'])
        if is_edge_class and is_source_class and is_target_class:
            return relation_index
    raise ValueError(f'KG 관계 7종에 없는 Edge: {edge}')


def generate_edge_connections(edges, node_index_by_name):
    node_count = len(node_index_by_name)
    source_node_indices = []
    group_numbers = []
    for edge in edges:
        relation_index = relation_index_of_edge(edge)
        forward_relation = knowledge_graph.DIRECTIONS_PER_RELATION * relation_index
        backward_relation = forward_relation + 1
        source_node_index = node_index_by_name[node_name_in_gnn_input(edge.source)]
        target_node_index = node_index_by_name[node_name_in_gnn_input(edge.target)]
        source_node_indices.append(source_node_index)
        group_numbers.append(forward_relation * node_count + target_node_index)
        source_node_indices.append(target_node_index)
        group_numbers.append(backward_relation * node_count + source_node_index)
    sorted_group_numbers = sorted(set(group_numbers))
    group_index_by_group_number = {}
    for group_index, group_number in enumerate(sorted_group_numbers):
        group_index_by_group_number[group_number] = group_index
    edge_count_by_group_number = {}
    for group_number in group_numbers:
        edge_count_by_group_number[group_number] = (
            edge_count_by_group_number.get(group_number, 0) + 1)
    edge_group_indices = []
    edge_mean_weights = []
    for group_number in group_numbers:
        edge_group_indices.append(group_index_by_group_number[group_number])
        edge_mean_weights.append(1.0 / edge_count_by_group_number[group_number])
    group_target_node_indices = []
    relation_index_by_group = []
    for group_number in sorted_group_numbers:
        group_target_node_indices.append(group_number % node_count)
        relation_index_by_group.append(group_number // node_count)
    relation_group_ranges = []
    for relation_index in range(knowledge_graph.NUM_RELATIONS):
        if relation_index not in relation_index_by_group:
            continue
        group_start = relation_index_by_group.index(relation_index)
        group_count = relation_index_by_group.count(relation_index)
        relation_group_ranges.append({
            'relation_index': relation_index,
            'group_start': group_start,
            'group_end': group_start + group_count,
        })
    return {
        'source_node_indices': torch.tensor(source_node_indices, dtype=torch.long),
        'edge_group_indices': torch.tensor(edge_group_indices, dtype=torch.long),
        'edge_mean_weights': torch.tensor(edge_mean_weights),
        'group_target_node_indices': torch.tensor(group_target_node_indices, dtype=torch.long),
        'relation_group_ranges': relation_group_ranges,
    }


# ================================================ GNN 입력 생성: KG로 정적 노드 특징 행렬과 노드 연결 만들기 ================================================
def generate_gnn_input(kg, simulation_process_by_process_code):
    kg_nodes = list_kg_nodes_in_class_order(kg.nodes_by_class)
    node_index_by_name = number_nodes_by_name(kg_nodes)
    static_features = generate_static_node_features(
        kg.nodes_by_class, kg.edges, kg.smt_line_steps, simulation_process_by_process_code)
    return {
        'static_node_features': static_features['static_node_features'],
        'static_node_feature_names': static_features['static_node_feature_names'],
        'edge_connections': generate_edge_connections(kg.edges, node_index_by_name),
    }


# ================================================ SMT 라인 찾기: SMT 생산 계획의 라인마다 그 라인의 KG 공정과 단계 공정 코드 ================================================
def find_smt_lines(smt_line_names, process_nodes, step_process_codes_by_smt_line):
    smt_lines = []
    for smt_line in smt_line_names:
        line_process_nodes = []
        for process_node in process_nodes:
            process_code = code_from_kg_node_path(process_node.kg_node_path)
            has_steps = bool(step_process_codes_by_smt_line.get(process_code))
            if process_node.product_code == smt_line and has_steps:
                line_process_nodes.append(process_node)
        if len(line_process_nodes) != 1:
            raise ValueError(f'SMT 라인에 대응하는 KG 공정이 하나가 아님: {smt_line}')
        line_process_node = line_process_nodes[0]
        line_process_code = code_from_kg_node_path(line_process_node.kg_node_path)
        smt_lines.append({
            'smt_line': smt_line,
            'line_process_code': line_process_code,
            'step_process_codes': list(step_process_codes_by_smt_line[line_process_code]),
        })
    return smt_lines


# ================================================ 정규화 값 계산: 전체 목표 수량, 공정·설비 정격전력과 기저부하의 합 ================================================
def total_target_quantity(target_quantity_by_product):
    return max(SMALLEST_NORMALIZATION_VALUE, sum(target_quantity_by_product.values()))


def total_rated_power_kw(process_rated_powers_kw, machine_rated_powers_kw, base_load_kw):
    process_power_kw = 0
    for process_rated_power_kw in process_rated_powers_kw:
        process_power_kw += float(process_rated_power_kw or 0.0)
    machine_power_kw = 0
    for rated_power_kw in machine_rated_powers_kw:
        machine_power_kw += float(rated_power_kw)
    total_power_kw = process_power_kw + machine_power_kw + float(base_load_kw)
    return max(SMALLEST_NORMALIZATION_VALUE, total_power_kw)


def normalization_value_by_item(normalization_name_by_item, normalization_values):
    normalization_value_by_item_name = {}
    for item_name, normalization_name in normalization_name_by_item.items():
        normalization_value = normalization_values[normalization_name]
        normalization_value_by_item_name[item_name] = float(normalization_value)
    return normalization_value_by_item_name


# ================================================ 항목 값 정규화: 항목마다 값 열(값 ÷ 정규화 값)과 값 유무 열(있으면 1). 값이 없는 항목은 두 열 모두 0 ================================================
def normalize_with_availability(values, normalization_value_by_item_name):
    column_count = len(normalization_value_by_item_name) * COLUMNS_PER_ITEM
    normalized = numpy.zeros(column_count, dtype=numpy.float32)
    for item_index, item_name in enumerate(normalization_value_by_item_name):
        value = values.get(item_name)
        if value is None:
            continue
        value_column = item_index * COLUMNS_PER_ITEM
        availability_column = value_column + 1
        normalized[value_column] = float(value) / normalization_value_by_item_name[item_name]
        normalized[availability_column] = VALUE_IS_AVAILABLE
    if not numpy.isfinite(normalized).all():
        raise ValueError(f'State에 유한하지 않은 값이 있음: {values}')
    return normalized


# ================================================ 근무시간 상태: 지금이 근무시간인지, 다음 근무·휴게 시각까지 남은 시간 ================================================
def work_time_status(now_sec, WorkStartTime, BreakStartTime, break_end_sec, WorkEndTime):
    sec_of_day = now_sec % SECONDS_PER_DAY
    seconds_to_changes = []
    for change_sec in [WorkStartTime, BreakStartTime, break_end_sec, WorkEndTime]:
        seconds_to_change = (float(change_sec) - sec_of_day) % SECONDS_PER_DAY
        if seconds_to_change == 0.0:
            seconds_to_change = SECONDS_PER_DAY
        seconds_to_changes.append(seconds_to_change)
    is_between_work_start_and_end = WorkStartTime <= sec_of_day < WorkEndTime
    is_break = BreakStartTime <= sec_of_day < break_end_sec
    return {
        'is_work_time': is_between_work_start_and_end and not is_break,
        'time_to_work_time_change_sec': min(seconds_to_changes),
    }


# ================================================ 목표 구간 안의 대기 시간: 대기 목록에 들어온 시각과 목표 구간 시작 시각 가운데 늦은 쪽부터 지금까지(무한가동에서 대기 시간이 끝없이 커지지 않게 목표 구간 시작부터 다시 셈. 목표 수량 실행은 목표 구간 시작이 0초라 들어온 시각부터의 시간과 같음) ================================================
def waiting_time_sec_in_target_period(now_sec, ready_queue_entry_sec, target_period_start_sec):
    waiting_start_sec = max(ready_queue_entry_sec, target_period_start_sec)
    return max(0.0, now_sec - waiting_start_sec)


# ================================================ 공정 노드의 동적 특징: 대기·후보·처리 중 작업 수, 목표 구간 시작부터의 완료 작업 수, 남은 처리 시간, 목표 구간 안의 가장 긴 대기 시간, 남은 착수 보류 시간 ================================================
def process_node_values(process_codes, now_sec, waiting_jobs_by_process_code, candidate_jobs,
                        running_operations, completed_count_in_target_period_by_process,
                        target_period_start_sec):
    values = {}
    waiting_jobs = []
    for process_code in process_codes:
        waiting_jobs.extend(waiting_jobs_by_process_code.get(process_code, []))
    values['waiting_job_count'] = len(waiting_jobs)
    if candidate_jobs is not None:
        candidate_job_count = 0
        for candidate_job in candidate_jobs:
            if candidate_job['process_code'] in process_codes:
                candidate_job_count += 1
        values['candidate_job_count'] = candidate_job_count
    remaining_processing_times = []
    for operation in running_operations:
        if operation['process_code'] in process_codes:
            remaining_time_sec = max(0.0, operation['expected_end_sec'] - now_sec)
            remaining_processing_times.append(remaining_time_sec)
    values['processing_job_count'] = len(remaining_processing_times)
    values['remaining_processing_time_sec'] = max(remaining_processing_times, default=0.0)
    completed_job_count = 0
    for process_code in process_codes:
        completed_job_count += completed_count_in_target_period_by_process.get(process_code, 0)
    values['completed_job_count'] = completed_job_count
    waiting_times = []
    every_job_has_entry_sec = True
    for waiting_job in waiting_jobs:
        if 'ready_queue_entry_sec' not in waiting_job:
            every_job_has_entry_sec = False
            break
        waiting_times.append(waiting_time_sec_in_target_period(
            now_sec, waiting_job['ready_queue_entry_sec'], target_period_start_sec))
    if every_job_has_entry_sec:
        values['longest_waiting_time_sec'] = max(waiting_times, default=0.0)
    return values


def group_jobs_by_process_code(waiting_jobs):
    waiting_jobs_by_process_code = {}
    for waiting_job in waiting_jobs:
        process_code = waiting_job['process_code']
        if process_code not in waiting_jobs_by_process_code:
            waiting_jobs_by_process_code[process_code] = []
        waiting_jobs_by_process_code[process_code].append(waiting_job)
    return waiting_jobs_by_process_code


def remaining_start_delay_values(active_start_timing, now_sec):
    if active_start_timing is None:
        return {'remaining_start_delay_sec': 0.0}
    if 'start_sec_after_delay' not in active_start_timing:
        return {}
    remaining_sec = max(0.0, active_start_timing['start_sec_after_delay'] - now_sec)
    return {'remaining_start_delay_sec': remaining_sec}


# ================================================ 설비 노드의 동적 특징: 점유 비율, 가동 여부, 남은 용량 비율, 가동 전력, 남은 처리 시간 ================================================
def machine_node_values(machine_resource, use_count_by_worker_group, rated_power_kw,
                        expected_end_secs_of_operations, now_sec):
    values = {}
    if machine_resource is not None:
        capacity = machine_resource.capacity
        occupied_count = machine_resource.count
        values['machine_occupied_ratio'] = occupied_count / capacity
        values['machine_available_ratio'] = (capacity - occupied_count) / capacity
    if use_count_by_worker_group is not None:
        is_operating = bool(use_count_by_worker_group)
        values['machine_operating'] = is_operating
        values['machine_operating_power_kw'] = float(is_operating) * rated_power_kw
    remaining_processing_times = []
    for expected_end_sec in expected_end_secs_of_operations:
        remaining_processing_times.append(max(0.0, expected_end_sec - now_sec))
    values['machine_remaining_processing_time_sec'] = max(remaining_processing_times, default=0.0)
    return values


# ================================================ 작업자 노드의 동적 특징: 작업자 그룹의 작업 중 비율, 근무시간의 남은 인원 비율, 다음 근무·휴게 시각까지 남은 시간 ================================================
def worker_node_values(worker_group_resource, is_work_time, time_to_work_time_change_sec):
    values = {}
    if worker_group_resource is None:
        return values
    capacity = worker_group_resource.capacity
    working_count = worker_group_resource.count
    values['worker_working_ratio'] = working_count / capacity
    if is_work_time:
        values['worker_available_ratio'] = (capacity - working_count) / capacity
    else:
        values['worker_available_ratio'] = 0.0
    values['worker_time_to_work_time_change_sec'] = time_to_work_time_change_sec
    return values


# ================================================ 창고(품목) 노드의 동적 특징: 재고, 대기 작업의 투입 수량, SMT 라인에서 생산 중인 수량, 발주된 수량 ================================================
def sum_required_quantity_by_item_code(waiting_jobs, simulation_process_by_process_code):
    required_quantity_by_item_code = {}
    for waiting_job in waiting_jobs:
        simulation_process = simulation_process_by_process_code[waiting_job['process_code']]
        for item_code, input_quantity in simulation_process.InputItemCodeList.items():
            required_quantity_by_item_code[item_code] = (
                required_quantity_by_item_code.get(item_code, 0) + input_quantity)
    return required_quantity_by_item_code


def warehouse_node_values(item_code, pcb_stock, stock_item, required_quantity, is_smt_item,
                          active_start_timings):
    values = {}
    if item_code in pcb_stock:
        values['stock_quantity'] = pcb_stock[item_code]
        values['ordered_quantity'] = 0.0
    elif stock_item is not None:
        values['stock_quantity'] = stock_item.present_stock
        if stock_item.on_order:
            values['ordered_quantity'] = (
                stock_item.capacity_quantity * stock_item.replenishment_ratio)
        else:
            values['ordered_quantity'] = 0.0
    values['required_quantity'] = required_quantity
    if is_smt_item:
        in_production_quantity = 0
        for active_start_timing in active_start_timings:
            if active_start_timing.get('pcb_item_code') == item_code:
                in_production_quantity += active_start_timing['quantity']
        values['in_production_quantity'] = in_production_quantity
    return values


# ================================================ 전역 정보 값: 목표 구간 시작부터 지난 시간, 하루 중 시각, 근무시간, 생산 진척률, 납기까지 남은 시간(납기가 없으면 값 없음), 지금 전력, 목표 구간 시작부터의 누적 전력 사용량 ================================================
def global_information_values(now_sec, elapsed_sec_in_target_period, is_work_time,
                              time_to_work_time_change_sec, progress_rates,
                              due_secs_of_unfinished_products, current_power_kw,
                              cumulative_weighted_energy_kwh):
    values = {
        'elapsed_time_sec': elapsed_sec_in_target_period,
        'time_of_day_ratio': now_sec % SECONDS_PER_DAY / SECONDS_PER_DAY,
        'is_work_time': is_work_time,
        'time_to_work_time_change_sec': time_to_work_time_change_sec,
        'production_progress_rate': float(numpy.mean(progress_rates)),
        'current_power_kw': current_power_kw,
        'cumulative_weighted_energy_kwh': cumulative_weighted_energy_kwh,
    }
    if None in due_secs_of_unfinished_products:
        return values
    times_to_due = [due_sec - now_sec for due_sec in due_secs_of_unfinished_products]
    overdue_product_count = 0
    for time_to_due in times_to_due:
        if time_to_due < 0:
            overdue_product_count += 1
    values['shortest_time_to_due_sec'] = min(times_to_due, default=0.0)
    if times_to_due:
        values['mean_time_to_due_sec'] = float(numpy.mean(times_to_due))
    else:
        values['mean_time_to_due_sec'] = 0.0
    values['overdue_product_ratio'] = overdue_product_count / max(1, len(times_to_due))
    return values


# ================================================ State 생성: 시뮬레이션 모델의 지금 값을 읽어 노드 특징 행렬과 전역 정보 만들기 ================================================
class StateBuilder:

    def __init__(self, simulation_model):
        self.simulation_model = simulation_model
        kg = simulation_model.knowledge_graph
        processes = simulation_model.simulation_processes.processes
        gnn_input = generate_gnn_input(kg, processes)
        static_node_features = gnn_input['static_node_features'].detach().cpu().numpy().copy()
        static_node_features.setflags(write=False)
        self.static_node_features = static_node_features
        self.static_node_feature_names = gnn_input['static_node_feature_names']
        self.edge_connections = gnn_input['edge_connections']
        self.kg_nodes = list_kg_nodes_in_class_order(kg.nodes_by_class)
        self.smt_lines = find_smt_lines(
            list(simulation_model.smt_production_plan), kg.nodes_of_class(Process),
            simulation_model.step_process_codes_by_smt_line)
        self.smt_line_by_line_process_code = {}
        for smt_line in self.smt_lines:
            self.smt_line_by_line_process_code[smt_line['line_process_code']] = smt_line
        self.smt_item_codes = set()
        for production_plans in simulation_model.smt_production_plan.values():
            for production_plan in production_plans:
                self.smt_item_codes.add(production_plan['item_code'])
        process_rated_powers_kw = [process.process_rated_power_kw for process in processes.values()]
        machine_rated_powers_kw = []
        for machine in simulation_model.machines.values():
            machine_rated_powers_kw.append(machine['rated_power_kw'])
        normalization_values = {
            'total_target_quantity': total_target_quantity(
                simulation_model.target_quantity_by_product),
            'total_rated_power_kw': total_rated_power_kw(
                process_rated_powers_kw, machine_rated_powers_kw, simulation_model.base_load_kw),
            'reference_run_completion_sec': REFERENCE_RUN_COMPLETION_SEC,
            'reference_run_weighted_energy_kwh': REFERENCE_RUN_WEIGHTED_ENERGY_KWH,
            'max_start_delay_sec': MAX_START_DELAY_SEC,
            'not_normalized': NOT_NORMALIZED,
        }
        self.dynamic_node_feature_normalization = normalization_value_by_item(
            DYNAMIC_NODE_FEATURES, normalization_values)
        self.global_information_normalization = normalization_value_by_item(
            GLOBAL_INFORMATION, normalization_values)

    # ================================================ 모델 입력 차원: 노드 특징 열 수, 전역 정보 열 수, 관계 수 ================================================
    def input_dimensions(self):
        static_feature_count = self.static_node_features.shape[FEATURE_AXIS]
        dynamic_feature_count = len(DYNAMIC_NODE_FEATURES) * COLUMNS_PER_ITEM
        return {
            'node_feature_dimension': static_feature_count + dynamic_feature_count,
            'global_information_dimension': len(GLOBAL_INFORMATION) * COLUMNS_PER_ITEM,
            'relation_count': int(knowledge_graph.NUM_RELATIONS),
        }

    # ================================================ 제품의 납기 시각: 지금 목표 구간의 납기(목표 수량 실행은 목표 구간이 하나뿐이라 시나리오 조건의 납기와 같고, 무한가동은 목표 구간 시작 + 시나리오 조건의 납기). 납기가 없는 제품은 None ================================================
    def due_sec_of_product(self, product_code):
        target_period_due_sec_by_product = (
            self.simulation_model.target_period_due_sec_by_product)
        due_sec = target_period_due_sec_by_product.get(product_code)
        if due_sec is None:
            return None
        return float(due_sec)

    # ================================================ 지금 State 계산: 노드마다 동적 특징을 정규화해 정적 특징 옆에 붙이고 전역 정보를 만듦 ================================================
    def build_state(self, candidate_jobs):
        simulation_model = self.simulation_model
        now_sec = float(simulation_model.simpy_environment.now)
        work_time = work_time_status(
            now_sec, simulation_model.WorkStartTime, simulation_model.BreakStartTime,
            simulation_model.break_end_sec, simulation_model.WorkEndTime)
        waiting_jobs = []
        for jobs_of_worker_group in simulation_model.waiting_jobs_by_worker_group.values():
            waiting_jobs.extend(jobs_of_worker_group)
        waiting_jobs_by_process_code = group_jobs_by_process_code(waiting_jobs)
        required_quantity_by_item_code = sum_required_quantity_by_item_code(
            waiting_jobs, simulation_model.simulation_processes.processes)
        running_operations = list(simulation_model.running_operations.values())
        completed_count_in_target_period_by_process = (
            simulation_model.completed_count_in_target_period_by_process())
        stock_item_by_item_code = {}
        for stock_items_of_category in simulation_model.warehouse.inventory.values():
            stock_item_by_item_code.update(stock_items_of_category)
        dynamic_node_features = []
        for node in self.kg_nodes:
            node_code = code_from_kg_node_path(node.kg_node_path)
            values = {}
            if isinstance(node, Process):
                values = self.process_node_values_now(
                    node_code, now_sec, waiting_jobs_by_process_code, candidate_jobs,
                    running_operations, completed_count_in_target_period_by_process)
            elif isinstance(node, Machine):
                values = self.machine_node_values_now(node_code, now_sec, running_operations)
            elif isinstance(node, Worker):
                values = worker_node_values(
                    simulation_model.worker_group_resources.get(node.WorkerGroupCode),
                    work_time['is_work_time'], work_time['time_to_work_time_change_sec'])
            elif isinstance(node, Warehouse):
                values = self.warehouse_node_values_now(
                    node_code, stock_item_by_item_code.get(node_code),
                    required_quantity_by_item_code.get(node_code, 0.0))
            dynamic_node_features.append(normalize_with_availability(
                values, self.dynamic_node_feature_normalization))
        dynamic_node_features = numpy.asarray(dynamic_node_features, dtype=numpy.float32)
        node_features = numpy.concatenate(
            [self.static_node_features, dynamic_node_features], axis=FEATURE_AXIS)
        return {
            'node_features': node_features,
            'global_information': self.build_global_information(now_sec, work_time),
        }

    # ================================================ 노드 하나의 지금 값 읽기: 공정(SMT 라인 공정은 단계 공정들의 값을 합침), 설비, 창고(품목) ================================================
    def process_node_values_now(self, process_code, now_sec, waiting_jobs_by_process_code,
                                candidate_jobs, running_operations,
                                completed_count_in_target_period_by_process):
        simulation_model = self.simulation_model
        smt_line = self.smt_line_by_line_process_code.get(process_code)
        process_codes = [process_code]
        if smt_line is not None:
            process_codes = smt_line['step_process_codes']
        values = process_node_values(
            process_codes, now_sec, waiting_jobs_by_process_code, candidate_jobs,
            running_operations, completed_count_in_target_period_by_process,
            simulation_model.target_period_start_sec)
        if smt_line is not None:
            active_start_timing = simulation_model.active_start_timing_by_smt_line.get(
                smt_line['smt_line'])
            values.update(remaining_start_delay_values(active_start_timing, now_sec))
        return values

    def machine_node_values_now(self, machine_code, now_sec, running_operations):
        simulation_model = self.simulation_model
        processes = simulation_model.simulation_processes.processes
        expected_end_secs_of_operations = []
        for operation in running_operations:
            machine_unit_codes = processes[operation['process_code']].machine_unit_codes
            if machine_code in (machine_unit_codes or []):
                expected_end_secs_of_operations.append(operation['expected_end_sec'])
        return machine_node_values(
            simulation_model.machine_resources.get(machine_code),
            simulation_model.machine_use_count_by_worker_group.get(machine_code),
            simulation_model.machines[machine_code]['rated_power_kw'],
            expected_end_secs_of_operations, now_sec)

    def warehouse_node_values_now(self, item_code, stock_item, required_quantity):
        simulation_model = self.simulation_model
        active_start_timings = list(simulation_model.active_start_timing_by_smt_line.values())
        return warehouse_node_values(
            item_code, simulation_model.pcb_stock, stock_item, required_quantity,
            item_code in self.smt_item_codes, active_start_timings)

    # ================================================ 지금 전역 정보 계산: 지난 시간, 생산 진척률, 누적 전력 사용량은 목표 구간 시작부터 센 값(무한가동에서 시간이 지나도 커지지 않게. 목표 수량 실행은 목표 구간이 하나뿐이라 실행 시작부터 센 값과 같음). 모델에 주지 않는 항목은 값을 넣지 않아 0으로 남김 ================================================
    def build_global_information(self, now_sec, work_time):
        simulation_model = self.simulation_model
        target_quantity_by_product = simulation_model.target_quantity_by_product
        production_quantity_by_product = (
            simulation_model.production_quantity_in_target_period_by_product)
        progress_rates = []
        due_secs_of_unfinished_products = []
        for product_code, target_quantity in target_quantity_by_product.items():
            production_quantity = production_quantity_by_product[product_code]
            progress_rates.append(min(1.0, production_quantity / max(target_quantity, 1)))
            if production_quantity < target_quantity:
                due_secs_of_unfinished_products.append(self.due_sec_of_product(product_code))
        operating_machine_power_kw = 0
        machine_use_counts = simulation_model.machine_use_count_by_worker_group
        for machine_code, use_count_by_worker_group in machine_use_counts.items():
            if use_count_by_worker_group:
                operating_machine_power_kw += simulation_model.machines[machine_code][
                    'rated_power_kw']
        sec_of_day = now_sec % SECONDS_PER_DAY
        base_load_kw_now = 0.0
        if simulation_model.WorkStartTime <= sec_of_day < simulation_model.WorkEndTime:
            base_load_kw_now = simulation_model.base_load_kw
        process_power_kw = simulation_model.process_power_integral.power_kw
        current_power_kw = process_power_kw + operating_machine_power_kw + base_load_kw_now
        elapsed_sec_in_target_period = now_sec - simulation_model.target_period_start_sec
        values = global_information_values(
            now_sec, elapsed_sec_in_target_period, work_time['is_work_time'],
            work_time['time_to_work_time_change_sec'], progress_rates,
            due_secs_of_unfinished_products, current_power_kw,
            simulation_model.cumulative_weighted_energy_kwh_in_target_period())
        for item_name in GLOBAL_INFORMATION_NOT_GIVEN_TO_MODEL:
            values.pop(item_name, None)
        return normalize_with_availability(values, self.global_information_normalization)
