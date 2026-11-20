import math

import psutil
import torch

from aas_preprocessing.path_extractor import PRODUCT_INDEPENDENT
from discrete_event_simulation import carbon_components
from knowledge_graph import Join, Process, Sequence, code_from_kg_node_path
from reinforcement_learning import model, reward, state


# ================================================ 작업 우선순위 특징: 작업 우선순위 가중치를 곱하는 후보 공정 값. 적힌 순서가 신경망이 내는 가중치 순서 ================================================
PRIORITY_FEATURES = [
    'standard_work_time_sec',
    'unfinished_ratio_to_target',
    'waiting_time_sec',
    'following_process_waiting_workload_sec',
]


# ================================================ 작업 우선순위 결정 설정: 가중치를 다시 정하는 간격, 후보 간 차이가 없는 특징을 빼는 분산 하한, 공정 선택 난수의 seed에 더하는 값 ================================================
PRIORITY_WEIGHTS_DECISION_INTERVAL_SEC = 3600.0
PRIORITY_VARIANCE_EPSILON = 1e-18
PROCESS_SELECTION_SEED_OFFSET = 100000
SQUARE_EXPONENT = 2


# ================================================ 공정 착수 기준값 설정: 신경망 출력을 기준값으로 바꾸는 식(배율 × exp(지수 배율 × 출력)), 착수를 다시 판단하는 간격 ================================================
PROCESS_START_THRESHOLD_SCALE = 0.5
PROCESS_START_THRESHOLD_LOG_SCALE = 2.0
START_TIMING_CHECK_INTERVAL_SEC = 900.0
TIME_COMPARISON_TOLERANCE_SEC = 1e-09


# ================================================ 착수 시점별 배출량 기록 설정: 하루를 나누는 착수 시각 구간 길이, 새 결과를 섞는 비율 ================================================
SECONDS_PER_DAY = 86400.0
START_TIME_SLOT_SEC = 1800.0
START_TIME_SLOT_COUNT = int(SECONDS_PER_DAY / START_TIME_SLOT_SEC)
EMISSION_RECORD_UPDATE_RATE = 0.3
PROCESS_AND_SLOT_SEPARATOR = '|'
EMISSION_RATIO_WHEN_MEAN_IS_ZERO = 1.0


# ================================================ 지금 착수할 때의 부담을 계산한 근거 표시 ================================================
BURDEN_BASIS = {
    'no_record': 'no_emission_record_at_now',
    'recorded': 'recorded_emission_ratio',
}


# ================================================ 실행 방식과 판단 종류 이름, 근무시간 찾기 범위, 메모리 확인 기준 ================================================
TRAIN_MODE = 'train'
EVALUATION_MODE = 'eval'
PRIORITY_DECISION = 'priority'
START_TIMING_DECISION = 'start_timing'
DAYS_TO_SEARCH_WORK_TIME = 8
MINIMUM_AVAILABLE_MEMORY_BYTES = 500000000
MEMORY_CHECK_INTERVAL_DECISION_COUNT = 128


# ================================================ 공정별 다음 공정 코드: KG의 Sequence·Join 관계와 SMT 라인 단계 공정의 다음 공정 ================================================
def collect_following_process_codes(kg_edges, following_process_codes_by_process_code,
                                    smt_line_step_process_codes):
    following_process_codes = {}
    for edge in kg_edges:
        if not isinstance(edge.source, Process):
            continue
        if not isinstance(edge, Sequence) and not isinstance(edge, Join):
            continue
        process_code = code_from_kg_node_path(edge.source.kg_node_path)
        if process_code not in following_process_codes:
            following_process_codes[process_code] = set()
        following_process_codes[process_code].add(code_from_kg_node_path(edge.target.kg_node_path))
    for process_code, process_codes_after in following_process_codes_by_process_code.items():
        if process_code not in smt_line_step_process_codes:
            continue
        if process_code not in following_process_codes:
            following_process_codes[process_code] = set()
        following_process_codes[process_code].update(process_codes_after)
    return following_process_codes


# ================================================ 제품별 투입 품목 수량: 제품의 공정과 제품과 무관한 공정이 쓰는 품목 수량의 합(불량 처리 공정 제외) ================================================
def sum_InputItemQuantity_by_product(product_codes, processes, planned_process_codes):
    InputItemQuantity_sum_by_product = {}
    for product_code in product_codes:
        InputItemQuantity_sum_by_item_code = {}
        for process_code, process in processes.items():
            if process_code not in planned_process_codes:
                continue
            if process.product_code not in [product_code, PRODUCT_INDEPENDENT]:
                continue
            if process.is_defect_event_handling_process:
                continue
            for item_code, input_quantity in process.InputItemCodeList.items():
                InputItemQuantity_sum_by_item_code[item_code] = (
                    InputItemQuantity_sum_by_item_code.get(item_code, 0) + input_quantity)
        InputItemQuantity_sum_by_product[product_code] = InputItemQuantity_sum_by_item_code
    return InputItemQuantity_sum_by_product


# ================================================ 후보 공정과 관련된 제품 찾기: 후보 작업의 제품, SMT 라인이 만드는 품목을 쓰는 제품, 공정의 제품 순서로 찾음 ================================================
def find_related_product_codes(product_code_of_job, pcb_item_code_in_production,
                               product_code_of_process, target_product_codes,
                               InputItemQuantity_sum_by_product):
    if product_code_of_job in target_product_codes:
        return [product_code_of_job]
    if pcb_item_code_in_production is not None:
        product_codes_using_item = []
        for product_code in InputItemQuantity_sum_by_product:
            InputItemQuantity_sum_by_item_code = InputItemQuantity_sum_by_product[product_code]
            if InputItemQuantity_sum_by_item_code.get(pcb_item_code_in_production, 0) > 0:
                product_codes_using_item.append(product_code)
        return product_codes_using_item
    if product_code_of_process in target_product_codes:
        return [product_code_of_process]
    if product_code_of_process == PRODUCT_INDEPENDENT:
        return list(target_product_codes)
    return []


# ================================================ 작업 우선순위 특징 값 계산: 목표 대비 미완료 비율(목표 구간 시작부터의 생산량 기준), 목표 구간 안의 대기 시간, 다음 공정의 대기 작업량. 무한가동에서 시간이 지나도 값이 한쪽에 붙거나 커지지 않게 목표 구간 시작부터 다시 셈(목표 수량 실행은 목표 구간이 하나뿐이라 실행 시작부터 센 값과 같음) ================================================
def unfinished_ratio_to_target(related_product_codes, target_quantity_by_product,
                               production_quantity_in_target_period_by_product):
    if not related_product_codes:
        return 0.0
    unfinished_ratio_sum = 0
    for product_code in related_product_codes:
        target_quantity = target_quantity_by_product[product_code]
        production_quantity = production_quantity_in_target_period_by_product[product_code]
        unfinished_quantity = max(0.0, target_quantity - production_quantity)
        unfinished_ratio_sum += unfinished_quantity / max(target_quantity, 1)
    return unfinished_ratio_sum / len(related_product_codes)


def waiting_time_sec(candidate_job, now_sec, target_period_start_sec):
    if candidate_job is None:
        return 0.0
    if 'ready_queue_entry_sec' not in candidate_job:
        return 0.0
    return state.waiting_time_sec_in_target_period(
        now_sec, candidate_job['ready_queue_entry_sec'], target_period_start_sec)


def following_process_waiting_workload_sec(following_process_codes,
                                           waiting_job_count_by_process_code, processes):
    waiting_workload_sec = 0
    for following_process_code in following_process_codes:
        if following_process_code not in processes:
            continue
        waiting_job_count = waiting_job_count_by_process_code.get(following_process_code, 0)
        cycle_time_sec = float(processes[following_process_code].CycleTime)
        waiting_workload_sec += waiting_job_count * cycle_time_sec
    return float(waiting_workload_sec)


# ================================================ 실행 공정 선택: 특징 값을 후보 간 표준화해 작업 우선순위 가중치를 곱한 점수의 softmax 확률로 후보 하나 선택 ================================================
def priority_scores(feature_values_by_candidate, priority_weights):
    candidate_count = len(feature_values_by_candidate)
    scores = [0.0] * candidate_count
    for feature_name, priority_weight in priority_weights.items():
        values = []
        for feature_values in feature_values_by_candidate:
            values.append(float(feature_values[feature_name]))
        mean = sum(values) / candidate_count
        variance = sum((value - mean) ** SQUARE_EXPONENT for value in values) / candidate_count
        if variance <= PRIORITY_VARIANCE_EPSILON:
            continue
        standard_deviation = math.sqrt(variance)
        for candidate_index, value in enumerate(values):
            scores[candidate_index] += priority_weight * (value - mean) / standard_deviation
    return scores


def selection_probabilities(feature_values_by_candidate, priority_weights):
    scores = priority_scores(feature_values_by_candidate, priority_weights)
    return torch.softmax(torch.tensor(scores, dtype=torch.float64), 0)


def select_candidate_index(feature_values_by_candidate, priority_weights, generator):
    if len(feature_values_by_candidate) == 1:
        return 0
    probabilities = selection_probabilities(feature_values_by_candidate, priority_weights)
    return int(torch.multinomial(probabilities, 1, generator=generator))


# ================================================ 공정 착수 기준값: 신경망 출력(공정 착수 행동)을 기준값으로 변환 ================================================
def process_start_threshold_from_action(process_start_action):
    exponent = PROCESS_START_THRESHOLD_LOG_SCALE * float(process_start_action)
    return PROCESS_START_THRESHOLD_SCALE * math.exp(exponent)


# ================================================ 근무시간을 반영한 착수 시각: 하루의 근무시간 구간(휴게 제외)과, 근무시간이 아니면 다음 근무 시작 시각 ================================================
def work_time_intervals(WorkStartTime, BreakStartTime, break_end_sec, WorkEndTime):
    intervals = []
    if break_end_sec > BreakStartTime:
        intervals.append({'start_sec': float(WorkStartTime), 'end_sec': float(BreakStartTime)})
        intervals.append({'start_sec': float(break_end_sec), 'end_sec': float(WorkEndTime)})
    else:
        intervals.append({'start_sec': float(WorkStartTime), 'end_sec': float(WorkEndTime)})
    return [interval for interval in intervals if interval['end_sec'] > interval['start_sec']]


def start_sec_in_work_time(sec, intervals):
    day_start_sec = math.floor(sec / SECONDS_PER_DAY) * SECONDS_PER_DAY
    for day_offset in range(DAYS_TO_SEARCH_WORK_TIME):
        interval_base_sec = day_start_sec + day_offset * SECONDS_PER_DAY
        for interval in intervals:
            if interval_base_sec + interval['end_sec'] > sec:
                return max(sec, interval_base_sec + interval['start_sec'])
    raise ValueError('근무시간 구간을 찾을 수 없음')


# ================================================ SMT 생산 묶음 하나의 탄소 배출량: 시간대 가중 전력량을 탄소 배출량으로 환산 ================================================
def carbon_emission_of_smt_lot(weighted_energy_kwh):
    return float(carbon_components.convert_to_carbon_emission(weighted_energy_kwh))


# ================================================ 착수 시점별 배출량 기록: 공정과 착수 시각 구간마다 평균 대비 배출량 비율을 기록하고 조회 ================================================
def start_time_slot(start_sec):
    return int(start_sec % SECONDS_PER_DAY // START_TIME_SLOT_SEC)


def process_and_slot_name(process_kg_node_path, slot):
    return f'{process_kg_node_path}{PROCESS_AND_SLOT_SEPARATOR}{slot}'


class StartTimingEmissionRecord:

    def __init__(self, saved_record):
        self.mean_unit_emission_by_process = {}
        self.emission_ratio_by_process_and_start_time_slot = {}
        self.record_count_by_process_and_start_time_slot = {}
        if saved_record:
            self.mean_unit_emission_by_process = dict(
                saved_record['mean_unit_emission_by_process'])
            self.emission_ratio_by_process_and_start_time_slot = dict(
                saved_record['emission_ratio_by_process_and_start_time_slot'])
            self.record_count_by_process_and_start_time_slot = dict(
                saved_record['record_count_by_process_and_start_time_slot'])

    def saved_content(self):
        return {
            'mean_unit_emission_by_process': dict(self.mean_unit_emission_by_process),
            'emission_ratio_by_process_and_start_time_slot': dict(
                self.emission_ratio_by_process_and_start_time_slot),
            'record_count_by_process_and_start_time_slot': dict(
                self.record_count_by_process_and_start_time_slot),
            'start_time_slot_sec': START_TIME_SLOT_SEC,
            'update_rate': EMISSION_RECORD_UPDATE_RATE,
        }

    def record(self, process_kg_node_path, start_sec, unit_emission):
        update_rate = EMISSION_RECORD_UPDATE_RATE
        previous_mean = self.mean_unit_emission_by_process.get(process_kg_node_path)
        if previous_mean is None:
            new_mean = unit_emission
        else:
            new_mean = (1 - update_rate) * previous_mean + update_rate * unit_emission
        self.mean_unit_emission_by_process[process_kg_node_path] = new_mean
        if new_mean > 0:
            emission_ratio = unit_emission / new_mean
        else:
            emission_ratio = EMISSION_RATIO_WHEN_MEAN_IS_ZERO
        name = process_and_slot_name(process_kg_node_path, start_time_slot(start_sec))
        previous_ratio = self.emission_ratio_by_process_and_start_time_slot.get(name)
        if previous_ratio is None:
            new_ratio = emission_ratio
        else:
            new_ratio = (1 - update_rate) * previous_ratio + update_rate * emission_ratio
        self.emission_ratio_by_process_and_start_time_slot[name] = new_ratio
        previous_count = self.record_count_by_process_and_start_time_slot.get(name, 0)
        self.record_count_by_process_and_start_time_slot[name] = previous_count + 1
        return emission_ratio

    def emission_ratio_at(self, process_kg_node_path, start_sec):
        slot = start_time_slot(start_sec)
        for slots_back in range(START_TIME_SLOT_COUNT):
            earlier_slot = (slot - slots_back) % START_TIME_SLOT_COUNT
            name = process_and_slot_name(process_kg_node_path, earlier_slot)
            emission_ratio = self.emission_ratio_by_process_and_start_time_slot.get(name)
            if emission_ratio is not None:
                return emission_ratio
        return None

    def recorded_start_time_slot_count(self):
        return len(self.emission_ratio_by_process_and_start_time_slot)

    # ================================================ 지금 착수할 때의 부담: 지금 착수할 때의 배출량 비율에서, 보류할 수 있는 시간 안에 착수할 때의 가장 낮은 비율을 뺀 값 ================================================
    def burden_of_starting_now(self, process_kg_node_path, now_sec, remaining_delay_sec,
                               intervals):
        ratio_now = self.emission_ratio_at(
            process_kg_node_path, start_sec_in_work_time(now_sec, intervals))
        if ratio_now is None:
            return {'burden': 0.0, 'basis': BURDEN_BASIS['no_record']}
        lowest_ratio = ratio_now
        check_count = 1
        while (check_count * START_TIMING_CHECK_INTERVAL_SEC
               <= remaining_delay_sec + TIME_COMPARISON_TOLERANCE_SEC):
            later_sec = now_sec + check_count * START_TIMING_CHECK_INTERVAL_SEC
            ratio_later = self.emission_ratio_at(
                process_kg_node_path, start_sec_in_work_time(later_sec, intervals))
            if ratio_later is not None:
                lowest_ratio = min(lowest_ratio, ratio_later)
            check_count += 1
        return {'burden': max(0.0, ratio_now - lowest_ratio), 'basis': BURDEN_BASIS['recorded']}


# ================================================ 가용 메모리 확인: 부족하면 실행 중단 ================================================
def check_available_memory():
    if psutil.virtual_memory().available < MINIMUM_AVAILABLE_MEMORY_BYTES:
        raise MemoryError('가용 메모리 500MB 미만')


# ================================================ 행동 선택: 에피소드 동안 강화학습 모델로 작업 우선순위 가중치와 공정 착수 기준값을 정하고, 실행 공정 선택과 착수 판단에 적용 ================================================
class ActionSelector:

    def __init__(self, simulation_model, state_builder, reinforcement_learning_model,
                 start_timing_emission_record, mode, simulation_seed, exploration_seed,
                 update_start_timing_emission_record):
        if len(PRIORITY_FEATURES) != model.PRIORITY_WEIGHT_COUNT:
            raise ValueError('작업 우선순위 특징 수와 신경망의 가중치 출력 수가 다름')
        self.simulation_model = simulation_model
        self.state_builder = state_builder
        self.reinforcement_learning_model = reinforcement_learning_model
        self.start_timing_emission_record = start_timing_emission_record
        self.mode = mode
        self.update_start_timing_emission_record = update_start_timing_emission_record
        self.cumulative_reward = reward.CumulativeReward(simulation_model)
        self.decision_counts = {PRIORITY_DECISION: 0, START_TIMING_DECISION: 0}
        self.process_selection_generator = torch.Generator().manual_seed(
            simulation_seed + PROCESS_SELECTION_SEED_OFFSET)
        self.exploration_generator = torch.Generator().manual_seed(int(exploration_seed))
        self.edge_connections = model.edge_connection_tensors(state_builder.edge_connections)
        self.next_priority_decision_sec = -math.inf
        self.current_action = None
        self.decisions = []
        self.target_period_numbers_of_decisions = []
        self.process_start_decision = None
        self.start_timing_judgments = []
        self.last_start_now_burden = 0.0
        self.work_time_intervals = work_time_intervals(
            simulation_model.WorkStartTime, simulation_model.BreakStartTime,
            simulation_model.break_end_sec, simulation_model.WorkEndTime)
        self.prepare_related_products_and_following_processes()
        check_available_memory()

    # ================================================ 관련 제품과 다음 공정을 찾는 데 쓰는 값 준비: SMT 라인 단계 공정의 라인 공정, 제품별 투입 품목 수량, 공정별 다음 공정 ================================================
    def prepare_related_products_and_following_processes(self):
        simulation_model = self.simulation_model
        simulation_processes = simulation_model.simulation_processes
        self.line_process_code_by_step_process_code = {}
        for smt_line in self.state_builder.smt_lines:
            for step_process_code in smt_line['step_process_codes']:
                self.line_process_code_by_step_process_code[step_process_code] = (
                    smt_line['line_process_code'])
        planned_process_codes = set(
            simulation_model.process_codes_without_previous_process
            + simulation_model.process_codes_after_any_previous_process
            + simulation_model.process_codes_after_all_previous_processes)
        self.InputItemQuantity_sum_by_product = sum_InputItemQuantity_by_product(
            list(simulation_model.target_quantity_by_product), simulation_processes.processes,
            planned_process_codes)
        self.following_process_codes_by_process_code = collect_following_process_codes(
            simulation_model.knowledge_graph.edges,
            simulation_processes.following_process_codes_by_process_code,
            self.line_process_code_by_step_process_code)

    # ================================================ 후보 공정의 관련 제품: 시뮬레이션 모델에서 후보 작업의 제품과 SMT 라인이 지금 만드는 품목을 읽어 찾음 ================================================
    def related_product_codes(self, process_code, candidate_job):
        simulation_model = self.simulation_model
        product_code_of_job = None
        if candidate_job is not None:
            product_code_of_job = simulation_model.product_of_job(candidate_job)
        line_process_code = self.line_process_code_by_step_process_code.get(
            process_code, process_code)
        smt_line = self.state_builder.smt_line_by_line_process_code.get(line_process_code)
        pcb_item_code_in_production = None
        if smt_line is not None:
            active_start_timing = simulation_model.active_start_timing_by_smt_line.get(
                smt_line['smt_line'], {})
            pcb_item_code_in_production = active_start_timing.get('pcb_item_code')
        product_code_of_process = None
        processes = simulation_model.simulation_processes.processes
        if process_code in processes:
            product_code_of_process = processes[process_code].product_code
        return find_related_product_codes(
            product_code_of_job, pcb_item_code_in_production, product_code_of_process,
            list(simulation_model.target_quantity_by_product),
            self.InputItemQuantity_sum_by_product)

    # ================================================ 후보 공정마다 작업 우선순위 특징 4개 계산 ================================================
    def priority_feature_values(self, candidate_process_codes, candidate_jobs):
        simulation_model = self.simulation_model
        now_sec = float(simulation_model.simpy_environment.now)
        processes = simulation_model.simulation_processes.processes
        waiting_job_count_by_process_code = {}
        for waiting_jobs in simulation_model.waiting_jobs_by_worker_group.values():
            for waiting_job in waiting_jobs:
                process_code = waiting_job['process_code']
                waiting_job_count_by_process_code[process_code] = (
                    waiting_job_count_by_process_code.get(process_code, 0) + 1)
        feature_values_by_candidate = []
        for process_code in candidate_process_codes:
            candidate_job = None
            for job in candidate_jobs:
                if job['process_code'] == process_code:
                    candidate_job = job
                    break
            related_product_codes = self.related_product_codes(process_code, candidate_job)
            following_process_codes = self.following_process_codes_by_process_code.get(
                process_code, [])
            feature_values_by_candidate.append({
                'standard_work_time_sec': float(processes[process_code].CycleTime),
                'unfinished_ratio_to_target': unfinished_ratio_to_target(
                    related_product_codes, simulation_model.target_quantity_by_product,
                    simulation_model.production_quantity_in_target_period_by_product),
                'waiting_time_sec': waiting_time_sec(
                    candidate_job, now_sec, simulation_model.target_period_start_sec),
                'following_process_waiting_workload_sec': following_process_waiting_workload_sec(
                    following_process_codes, waiting_job_count_by_process_code, processes),
            })
        return feature_values_by_candidate

    # ================================================ 공정 착수 기준값 결정: 에피소드의 첫 결정 때 한 번, 공정 착수 신경망의 출력으로 정함 ================================================
    def decide_process_start_threshold(self, current_state):
        node_features = torch.as_tensor(current_state['node_features'], dtype=torch.float32)
        global_information = torch.as_tensor(
            current_state['global_information'], dtype=torch.float32)
        with torch.no_grad():
            output = self.reinforcement_learning_model.process_start_forward(
                node_features, self.edge_connections, global_information)
            mean = output['mean']
            log_standard_deviation = output['log_standard_deviation']
            standard_deviation = log_standard_deviation.exp()
            if self.mode == TRAIN_MODE:
                exploration_noise = torch.randn((), generator=self.exploration_generator)
                process_start_action = mean + standard_deviation * exploration_noise
            else:
                process_start_action = mean.clone()
            action_distribution = torch.distributions.Normal(mean, standard_deviation)
            log_probability = action_distribution.log_prob(process_start_action)
        self.process_start_decision = {
            'sec': float(self.simulation_model.simpy_environment.now),
            'node_features': current_state['node_features'].copy(),
            'global_information': current_state['global_information'].copy(),
            'process_start_action': float(process_start_action),
            'mean': float(mean),
            'log_standard_deviation': float(log_standard_deviation),
            'log_probability': float(log_probability),
            'value': float(output['value']),
            'process_start_threshold': process_start_threshold_from_action(
                float(process_start_action)),
            'process_start_threshold_at_mean': process_start_threshold_from_action(float(mean)),
            'start_judgment_changed_by_exploration': False,
            'start_judgment_changed_count': 0,
        }

    # ================================================ 작업 우선순위 가중치 결정: 지금 State로 작업 우선순위 신경망을 불러 가중치를 정하고 결정 기록에 추가 ================================================
    def decide_priority_weights(self, candidate_jobs):
        current_state = self.state_builder.build_state(candidate_jobs)
        if self.process_start_decision is None:
            self.decide_process_start_threshold(current_state)
        now_sec = float(self.simulation_model.simpy_environment.now)
        node_features = torch.as_tensor(current_state['node_features'], dtype=torch.float32)
        global_information = torch.as_tensor(
            current_state['global_information'], dtype=torch.float32)
        process_start_action = self.process_start_decision['process_start_action']
        with torch.no_grad():
            output = self.reinforcement_learning_model.priority_forward(
                node_features, self.edge_connections, global_information,
                torch.tensor([process_start_action], dtype=torch.float32))
            mean = output['mean']
            log_standard_deviation = output['log_standard_deviation']
            standard_deviation = log_standard_deviation.exp()
            if self.mode == TRAIN_MODE:
                exploration_noise = torch.randn(
                    model.PRIORITY_WEIGHT_COUNT, generator=self.exploration_generator)
                priority_weights = mean + standard_deviation * exploration_noise
            else:
                priority_weights = mean.clone()
            action_distribution = torch.distributions.Normal(mean, standard_deviation)
            log_probability = action_distribution.log_prob(priority_weights).sum()
        self.decisions.append({
            'sec': now_sec,
            'node_features': current_state['node_features'].copy(),
            'global_information': current_state['global_information'].copy(),
            'process_start_action': process_start_action,
            'priority_weights': priority_weights.numpy().astype('float32'),
            'mean': mean.numpy().astype('float32'),
            'log_standard_deviation': log_standard_deviation.numpy().astype('float32'),
            'log_probability': float(log_probability),
            'value': float(output['value']),
            'cumulative_reward': self.cumulative_reward.total_at(now_sec),
        })
        self.target_period_numbers_of_decisions.append(
            self.simulation_model.target_period_number)
        priority_weight_by_feature = {}
        for feature_name, priority_weight in zip(PRIORITY_FEATURES, priority_weights.tolist()):
            priority_weight_by_feature[feature_name] = priority_weight
        self.current_action = {
            'priority_weights': priority_weight_by_feature,
            'process_start_threshold': self.process_start_decision['process_start_threshold'],
        }
        interval_sec = PRIORITY_WEIGHTS_DECISION_INTERVAL_SEC
        self.next_priority_decision_sec = (math.floor(now_sec / interval_sec) + 1) * interval_sec

    # ================================================ 실행 공정 선택(시뮬레이션 모델이 부름): 후보 공정이 여러 개일 때 작업 우선순위로 하나를 고름. 후보 작업은 시뮬레이션 모델의 판단 문맥에서 읽음 ================================================
    def select_process(self, candidate_process_codes):
        candidate_jobs = self.simulation_model.decision_context['candidate_jobs']
        decision_count = sum(self.decision_counts.values())
        if decision_count % MEMORY_CHECK_INTERVAL_DECISION_COUNT == 0:
            check_available_memory()
        now_sec = float(self.simulation_model.simpy_environment.now)
        if self.current_action is None or now_sec >= self.next_priority_decision_sec:
            self.decide_priority_weights(candidate_jobs)
        feature_values_by_candidate = self.priority_feature_values(
            candidate_process_codes, candidate_jobs)
        selected_index = select_candidate_index(
            feature_values_by_candidate, self.current_action['priority_weights'],
            self.process_selection_generator)
        self.decision_counts[PRIORITY_DECISION] += 1
        return candidate_process_codes[selected_index]

    # ================================================ 공정 착수 판단(시뮬레이션 모델이 부름): 지금 착수할 때의 부담이 공정 착수 기준값 이하이면 착수 ================================================
    def judge_start_timing(self, start_timing_record, remaining_delay_sec):
        if self.current_action is None:
            candidate_jobs_not_given = None
            self.decide_priority_weights(candidate_jobs_not_given)
        now_sec = float(self.simulation_model.simpy_environment.now)
        burden = self.start_timing_emission_record.burden_of_starting_now(
            start_timing_record['process_kg_node_path'], now_sec, remaining_delay_sec,
            self.work_time_intervals)
        process_start_decision = self.process_start_decision
        start_now = burden['burden'] <= process_start_decision['process_start_threshold']
        start_now_at_mean = (
            burden['burden'] <= process_start_decision['process_start_threshold_at_mean'])
        changed_by_exploration = start_now != start_now_at_mean
        if changed_by_exploration:
            process_start_decision['start_judgment_changed_by_exploration'] = True
            process_start_decision['start_judgment_changed_count'] += 1
        self.last_start_now_burden = burden['burden']
        self.start_timing_judgments.append({
            'sec': now_sec,
            'smt_line': start_timing_record['smt_line'],
            'start_now_burden': burden['burden'],
            'burden_basis': burden['basis'],
            'process_start_threshold': process_start_decision['process_start_threshold'],
            'start_now': bool(start_now),
            'remaining_delay_sec': remaining_delay_sec,
            'start_judgment_changed_by_exploration': changed_by_exploration,
        })
        return start_now

    # ================================================ SMT 생산 묶음 완료 때 배출량 기록 갱신(시뮬레이션 모델이 부름): 표준 생산 시간 1초당 배출량을 착수 시점별 배출량 기록에 반영 ================================================
    def record_start_timing_result(self, start_timing_record):
        if not self.update_start_timing_emission_record:
            return
        normal_duration_sec = float(start_timing_record['normal_duration_sec'])
        if normal_duration_sec <= 0:
            return
        start_sec = start_timing_record['start_sec']
        if 'start_sec_after_delay' in start_timing_record:
            start_sec = start_timing_record['start_sec_after_delay']
        carbon_emission = carbon_emission_of_smt_lot(start_timing_record['weighted_kwh'])
        unit_emission = carbon_emission / normal_duration_sec
        actual_start_sec = start_sec_in_work_time(float(start_sec), self.work_time_intervals)
        self.start_timing_emission_record.record(
            start_timing_record['process_kg_node_path'], actual_start_sec, unit_emission)


# ================================================ 행동 선택 준비: 시뮬레이션 모델로 State 생성 객체를 만들고 행동 선택 객체를 만듦 ================================================
def create_action_selector(simulation_model, reinforcement_learning_model,
                           start_timing_emission_record, mode, simulation_seed,
                           exploration_seed, update_start_timing_emission_record):
    state_builder = state.StateBuilder(simulation_model)
    return ActionSelector(
        simulation_model, state_builder, reinforcement_learning_model,
        start_timing_emission_record, mode, simulation_seed, exploration_seed,
        update_start_timing_emission_record)
