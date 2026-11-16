import random
from collections import defaultdict

import simpy

from aas_preprocessing.aas_reader import SECONDS_PER_DAY
from aas_preprocessing.path_extractor import PRODUCT_INDEPENDENT
from discrete_event_simulation.carbon_components import CarbonComponents
from discrete_event_simulation.productivity_components import (
    ProductivityComponents, is_target_quantity_reached)
from discrete_event_simulation.smt_line import SmtLine
from discrete_event_simulation.warehouse import Warehouse


# ================================================ 확인 간격(초): 종료 조건 확인, 근무시간 내내 작업 중으로 두는 작업자 그룹의 상태 갱신 ================================================
TERMINATION_CHECK_INTERVAL_SEC = 30
WORKING_STATE_UPDATE_INTERVAL_SEC = 30


# ================================================ 작업 우선순위 판단: 판단 종류 이름, 선택을 요청하는 최소 후보 공정 종류 수, Ready Queue가 이미 확보한 작업자 자리 수 ================================================
PRIORITY_DECISION_KIND = 'priority'
MINIMUM_CANDIDATE_PROCESS_COUNT_FOR_PRIORITY_CHOICE = 2
WORKER_SLOT_COUNT_HELD_BY_READY_QUEUE = 1


# ================================================ 무한가동의 목표 구간: 첫 목표 구간의 번호, 목표 구간이 끝난 이유 이름(모든 제품이 목표 구간 목표 수량을 채움, 채우지 못한 채 목표 구간 납기가 지남) ================================================
FIRST_TARGET_PERIOD_NUMBER = 1
TARGET_PERIOD_END_REASONS = {
    'target_quantity_reached': 'target_quantity_reached',
    'due_passed': 'due_passed',
}


# ================================================ 무한가동의 제품별 수량: 제품별 비율 × 비율 1당 수량. 목표 구간 목표 수량(비율 1당 수량은 시나리오 조건의 production_quantity_per_product)과 유지 수량(비율 1당 유지 수량)을 이 식으로 구함. AAS의 제품이 제품별 비율에 없으면 멈춤 ================================================
def quantity_by_product_ratio(product_codes, product_ratio, quantity_per_ratio_unit):
    product_codes_without_ratio = []
    for product_code in product_codes:
        if product_code not in product_ratio:
            product_codes_without_ratio.append(product_code)
    if product_codes_without_ratio:
        raise ValueError(f'무한가동의 제품별 비율에 없는 AAS 제품: {product_codes_without_ratio}')
    quantity_by_product = {}
    for product_code in product_codes:
        quantity_by_product[product_code] = product_ratio[product_code] * quantity_per_ratio_unit
    return quantity_by_product


# ================================================ 무한가동에서 다음 목표 구간으로 넘기는 생산량: 목표 구간 목표 수량을 넘겨 생산한 수량 ================================================
def production_quantity_carried_over_to_next_target_period(production_quantity, target_quantity):
    return max(0, production_quantity - target_quantity)


# ================================================ 목표 구간 납기: 목표 구간 시작 시각 + 제품별 납기(시나리오 조건의 due_day × 하루 초. 목표 구간 시작부터 잰 초). 목표 수량 실행은 목표 구간이 0초에 시작하는 하나뿐이라 제품별 납기와 같음 ================================================
def due_sec_by_product_of_target_period(target_period_start_sec, due_sec_by_product):
    target_period_due_sec_by_product = {}
    for product, due_sec in due_sec_by_product.items():
        target_period_due_sec_by_product[product] = target_period_start_sec + due_sec
    return target_period_due_sec_by_product


# ================================================ 근무시간 계산: 근무시간 여부, 다음 근무 재개까지 남은 시간, 0초부터의 누적 근무시간(휴게·근무 외 제외) ================================================
def is_work_time_of_day(sec_in_day, WorkStartTime, WorkEndTime, BreakStartTime, break_end_sec):
    is_between_work_start_and_end = WorkStartTime <= sec_in_day < WorkEndTime
    is_break_time = BreakStartTime <= sec_in_day < break_end_sec
    return is_between_work_start_and_end and not is_break_time


def seconds_until_next_work_time(sec_in_day, WorkStartTime, BreakStartTime, break_end_sec):
    if sec_in_day < WorkStartTime:
        return WorkStartTime - sec_in_day
    if BreakStartTime <= sec_in_day < break_end_sec:
        return break_end_sec - sec_in_day
    return SECONDS_PER_DAY - sec_in_day + WorkStartTime


def work_time_within_period(sec_in_day, period_start_sec, period_end_sec):
    if sec_in_day > period_start_sec:
        return max(0.0, min(sec_in_day, period_end_sec) - period_start_sec)
    return 0.0


def calculate_elapsed_work_time_sec(
        sec, WorkStartTime, WorkEndTime, BreakStartTime, break_end_sec):
    break_duration_sec = break_end_sec - BreakStartTime
    work_time_per_day_sec = WorkEndTime - WorkStartTime - break_duration_sec
    passed_day_count = int(sec // float(SECONDS_PER_DAY))
    sec_in_day = sec - passed_day_count * float(SECONDS_PER_DAY)
    work_time_before_break_sec = work_time_within_period(
        sec_in_day, WorkStartTime, BreakStartTime)
    work_time_after_break_sec = work_time_within_period(sec_in_day, break_end_sec, WorkEndTime)
    work_time_today_sec = work_time_before_break_sec + work_time_after_break_sec
    return passed_day_count * work_time_per_day_sec + work_time_today_sec


class SimulationModel(SmtLine, ProductivityComponents, CarbonComponents):

    # ================================================ 입력 값 보관: KG와 시뮬레이션 공정, 작업자 그룹·설비, 생산 계획·목표, 근무시간, 창고, 전력, 시나리오 조건 ================================================
    def __init__(
            self, knowledge_graph, simulation_processes, worker_groups, machines,
            step_process_codes_by_smt_line, process_codes_without_previous_process,
            process_codes_after_any_previous_process, process_codes_after_all_previous_processes,
            smt_production_plan, target_quantity_by_product, due_sec_by_product, RunLength,
            WorkStartTime, WorkEndTime, BreakStartTime, break_end_sec,
            co_managed_item_codes_by_category,
            self_managed_item_codes_by_category, stock_policy_by_category,
            replenishment_lead_time_sec, infinite_stock, base_load_kw,
            electricity_time_band_weights, target_unit_resource_events, mcf_recipe_structure,
            pcb_stock_limited,
            pcb_initial_stock_ratio, worker_reallocation_conditions,
            start_delay_allowed_process_kg_node_paths, max_start_delay_sec,
            smt_material_event_conditions, infinite_operation_conditions):
        self.knowledge_graph = knowledge_graph
        self.simulation_processes = simulation_processes
        self.worker_groups = worker_groups
        self.machines = machines
        self.step_process_codes_by_smt_line = step_process_codes_by_smt_line
        self.process_codes_without_previous_process = process_codes_without_previous_process
        self.process_codes_after_any_previous_process = process_codes_after_any_previous_process
        self.process_codes_after_all_previous_processes = process_codes_after_all_previous_processes
        self.smt_production_plan = smt_production_plan
        self.target_quantity_by_product = target_quantity_by_product
        self.due_sec_by_product = due_sec_by_product
        self.RunLength = float(RunLength)
        self.WorkStartTime = WorkStartTime
        self.WorkEndTime = WorkEndTime
        self.BreakStartTime = BreakStartTime
        self.break_end_sec = break_end_sec
        self.co_managed_item_codes_by_category = co_managed_item_codes_by_category
        self.self_managed_item_codes_by_category = self_managed_item_codes_by_category
        self.stock_policy_by_category = stock_policy_by_category
        self.replenishment_lead_time_sec = replenishment_lead_time_sec
        self.infinite_stock = infinite_stock
        self.base_load_kw = base_load_kw
        self.electricity_time_band_weights = electricity_time_band_weights
        self.target_unit_resource_events = target_unit_resource_events
        self.mcf_recipe_structure = mcf_recipe_structure
        self.pcb_stock_limited = pcb_stock_limited
        self.pcb_initial_stock_ratio = pcb_initial_stock_ratio
        self.worker_reallocation_conditions = worker_reallocation_conditions
        self.start_delay_allowed_process_kg_node_paths = start_delay_allowed_process_kg_node_paths
        self.max_start_delay_sec = max_start_delay_sec
        self.smt_material_event_conditions = smt_material_event_conditions
        self.infinite_operation_conditions = infinite_operation_conditions
        self.reset()

    # ================================================ 실행 상태 초기화: SimPy 시계, 생산성 지표, 창고, 작업자·설비 자원, 전력 기록, Ready Queue, SMT 라인, 작업자 재배치, 처리 중 공정 기록, 목표 구간 ================================================
    def reset(self):
        self.simpy_environment = simpy.Environment()
        self.reset_productivity_components()
        self.running_job_count_by_worker_group = {}
        self.warehouse = Warehouse(
            self.co_managed_item_codes_by_category, self.self_managed_item_codes_by_category,
            self.stock_policy_by_category)
        self.worker_group_resources = {}
        for worker_group, worker_group_values in self.worker_groups.items():
            worker_capacity = (
                worker_group_values['worker_count'] * worker_group_values['UnitsPerWorker'])
            self.worker_group_resources[worker_group] = simpy.Resource(
                self.simpy_environment, capacity=worker_capacity)
        self.machine_resources = {}
        for machine_name, machine_values in self.machines.items():
            if machine_values['MaxCapacity'] > 0:
                self.machine_resources[machine_name] = simpy.Resource(
                    self.simpy_environment, capacity=machine_values['MaxCapacity'])
        self.reset_carbon_components()
        self.waiting_jobs_by_worker_group = {}
        self.ready_queue_wake_event_by_worker_group = {}
        for worker_group in self.worker_groups:
            self.waiting_jobs_by_worker_group[worker_group] = []
            self.ready_queue_wake_event_by_worker_group[worker_group] = (
                self.simpy_environment.event())
        self.stock_arrival_event = self.simpy_environment.event()
        self.reset_smt_line()
        self.worker_reallocation_sec = None
        self.completed_job_count_of_reallocation_source = 0
        if self.worker_reallocation_conditions['enabled']:
            self.simpy_environment.process(self.monitor_worker_reallocation())
        self.completed_count_by_process = defaultdict(int)
        self.product_by_unit = {}
        self.running_operations = {}
        self.decision_context = None
        self.reset_target_period()

    # ================================================ 시작: 작업자 그룹별 Ready Queue, 제품별 생산(무한가동이면 유지 수량만큼 시작해 계속 생산, 아니면 목표 수량 전량), SMT 라인 생산, 종료 조건 확인을 SimPy process로 등록 ================================================
    def start(self, action_selector=None, RunLength=None):
        self.reset()
        if RunLength is None:
            RunLength = float(self.RunLength)
        self.stop_event = self.simpy_environment.event()
        always_assigned_worker_groups = self.always_assigned_worker_groups()
        for worker_group in self.worker_groups:
            if worker_group in always_assigned_worker_groups:
                self.simpy_environment.process(self.keep_worker_group_assigned(worker_group))
            else:
                self.simpy_environment.process(
                    self.select_and_start_jobs(worker_group, action_selector))
        if self.infinite_operation_conditions['applied']:
            self.start_infinite_operation(action_selector)
        else:
            self.start_production_of_target_quantity(action_selector)
        smt_line_runs = []
        for smt_line, pcb_production_plan in self.smt_production_plan.items():
            if self.pcb_stock_limited:
                smt_line_run = self.run_smt_line(smt_line, pcb_production_plan, action_selector)
            else:
                smt_line_run = self.run_smt_line_without_stock_limit(
                    smt_line, pcb_production_plan, action_selector)
            smt_line_runs.append(self.simpy_environment.process(smt_line_run))
        self.simpy_environment.process(
            self.watch_termination_condition(smt_line_runs, RunLength))

    def start_production_of_target_quantity(self, action_selector):
        for product, target_quantity in self.target_quantity_by_product.items():
            for unit_index in range(target_quantity):
                self.simpy_environment.process(self.produce_unit(product, action_selector))

    # ================================================ 종료 조건 확인: 30초마다 목표 생산량 달성과 SMT 라인 생산 종료, 또는 실행 시간 상한 도달을 확인. 무한가동은 목표 생산량 달성으로 끝나지 않고 실행 시간 상한에서만 끝남 ================================================
    def is_target_production_finished(self, smt_line_runs):
        if self.infinite_operation_conditions['applied']:
            return False
        for product, target_quantity in self.target_quantity_by_product.items():
            if self.production_quantity_by_product[product] < target_quantity:
                return False
        for smt_line_run in smt_line_runs:
            if not smt_line_run.triggered:
                return False
        return True

    def watch_termination_condition(self, smt_line_runs, RunLength):
        while not self.stop_event.triggered:
            yield self.simpy_environment.timeout(TERMINATION_CHECK_INTERVAL_SEC)
            ends_by_target = self.is_target_production_finished(smt_line_runs)
            if ends_by_target or self.simpy_environment.now >= RunLength:
                if not self.stop_event.triggered:
                    self.stop_event.succeed()
                return

    # ================================================ 진행: 주어진 시각까지 진행(이미 끝났으면 False), 끝까지 실행 ================================================
    def advance(self, until_sec):
        if self.stop_event.triggered:
            return False
        if until_sec > self.simpy_environment.now:
            remaining_sec = until_sec - self.simpy_environment.now
            self.simpy_environment.run(until=simpy.AnyOf(
                self.simpy_environment,
                [self.stop_event, self.simpy_environment.timeout(remaining_sec)]))
        return not self.stop_event.triggered

    def run(self, action_selector=None, RunLength=None):
        self.start(action_selector, RunLength)
        self.simpy_environment.run(until=self.stop_event)
        self.accumulate_worker_idle_time_and_machine_energy_until_now()

    def accumulate_worker_idle_time_and_machine_energy_until_now(self):
        for worker_group in self.worker_groups:
            self.accumulate_worker_idle_time(worker_group, self.simpy_environment.now)
        for machine_name in self.machines:
            self.accumulate_machine_energy(machine_name)

    # ================================================ Ready Queue: 대기 작업과 근무시간을 기다려 작업자를 확보하고 후보 작업을 돌려줌 ================================================
    def ready_queue(self, worker_group):
        worker_group_resource = self.worker_group_resources[worker_group]
        wake_event_by_worker_group = self.ready_queue_wake_event_by_worker_group
        while True:
            if not self.waiting_jobs_by_worker_group[worker_group]:
                wake_event_by_worker_group[worker_group] = self.simpy_environment.event()
                yield wake_event_by_worker_group[worker_group]
                continue
            if not self.is_work_time():
                yield self.simpy_environment.timeout(self.seconds_until_work_time())
                continue
            worker_request = worker_group_resource.request()
            yield worker_request
            waiting_jobs = self.waiting_jobs_by_worker_group[worker_group]
            if not waiting_jobs:
                worker_group_resource.release(worker_request)
                continue
            fitting_jobs = self.jobs_fitting_remaining_work_time(worker_group, waiting_jobs)
            if not fitting_jobs:
                worker_group_resource.release(worker_request)
                wake_event_by_worker_group[worker_group] = self.simpy_environment.event()
                next_work_time = self.simpy_environment.timeout(self.seconds_until_work_time())
                yield simpy.AnyOf(
                    self.simpy_environment,
                    [next_work_time, wake_event_by_worker_group[worker_group]])
                continue
            candidate_process_codes = []
            for job in fitting_jobs:
                if job['process_code'] not in candidate_process_codes:
                    candidate_process_codes.append(job['process_code'])
            return {
                'worker_request': worker_request,
                'fitting_jobs': fitting_jobs,
                'candidate_process_codes': candidate_process_codes,
            }

    def wake_ready_queue(self, worker_group):
        for job in reversed(self.waiting_jobs_by_worker_group[worker_group]):
            if 'ready_queue_entry_sec' in job:
                break
            job['ready_queue_entry_sec'] = float(self.simpy_environment.now)
        wake_event = self.ready_queue_wake_event_by_worker_group[worker_group]
        if not wake_event.triggered:
            wake_event.succeed()

    # ================================================ Ready Queue: 선후관계와 투입 자재 조건을 만족한 공정, 남은 근무시간 안에 끝나는 작업 ================================================
    def are_input_items_ready(self, process_code):
        if self.infinite_stock:
            return True
        return self.simulation_processes.are_input_items_in_stock(
            process_code, self.warehouse.inventory)

    def ready_process_codes(self, product, completed_process_codes):
        self.product_by_unit[id(completed_process_codes)] = product
        ready_process_codes = []
        for process_code in self.process_codes_without_previous_process:
            if process_code in completed_process_codes:
                continue
            if self.are_input_items_ready(process_code):
                ready_process_codes.append(process_code)
        for process_code in self.process_codes_after_any_previous_process:
            if process_code in completed_process_codes:
                continue
            is_any_previous_process_completed = False
            for previous_code in self.simulation_processes.previous_process_codes(process_code):
                if previous_code in completed_process_codes:
                    is_any_previous_process_completed = True
            if is_any_previous_process_completed and self.are_input_items_ready(process_code):
                ready_process_codes.append(process_code)
        for process_code in self.process_codes_after_all_previous_processes:
            if process_code in completed_process_codes:
                continue
            are_all_previous_processes_completed = True
            for previous_code in self.simulation_processes.previous_process_codes(process_code):
                if previous_code not in completed_process_codes:
                    are_all_previous_processes_completed = False
            if are_all_previous_processes_completed and self.are_input_items_ready(process_code):
                ready_process_codes.append(process_code)
        ready_process_codes_of_product = []
        for process_code in ready_process_codes:
            product_code = self.simulation_processes.processes[process_code].product_code
            if product_code == product or product_code == PRODUCT_INDEPENDENT:
                ready_process_codes_of_product.append(process_code)
        return ready_process_codes_of_product

    def jobs_fitting_remaining_work_time(self, worker_group, waiting_jobs):
        remaining_work_time_sec = self.WorkEndTime - self.simpy_environment.now % SECONDS_PER_DAY
        fitting_jobs = []
        for job in waiting_jobs:
            process = self.simulation_processes.processes[job['process_code']]
            if process.CycleTime <= remaining_work_time_sec:
                fitting_jobs.append(job)
        if fitting_jobs and self.pcb_stock:
            fitting_jobs = self.filter_jobs_by_pcb_stock(worker_group, fitting_jobs)
        return fitting_jobs

    # ================================================ 작업 선택과 실행 시작: 후보가 작업자 여유나 설비 여유보다 많으면 강화학습 실행 객체에 작업 우선순위 선택을 요청, 아니면 첫 대기 작업 ================================================
    def needs_priority_choice(self, fitting_jobs, worker_group_resource):
        candidate_process_codes = set()
        for job in fitting_jobs:
            candidate_process_codes.add(job['process_code'])
        if len(candidate_process_codes) < MINIMUM_CANDIDATE_PROCESS_COUNT_FOR_PRIORITY_CHOICE:
            return False
        available_worker_slot_count = (
            worker_group_resource.capacity - worker_group_resource.count
            + WORKER_SLOT_COUNT_HELD_BY_READY_QUEUE)
        if len(fitting_jobs) > available_worker_slot_count:
            return True
        requesting_job_count_by_machine = {}
        for job in fitting_jobs:
            process = self.simulation_processes.processes[job['process_code']]
            for machine_name in set(process.machine_unit_codes):
                if machine_name in self.machine_resources:
                    job_count = requesting_job_count_by_machine.get(machine_name, 0)
                    requesting_job_count_by_machine[machine_name] = job_count + 1
        for machine_name, requesting_job_count in requesting_job_count_by_machine.items():
            machine_resource = self.machine_resources[machine_name]
            if requesting_job_count > machine_resource.capacity - machine_resource.count:
                return True
        return False

    def request_priority_choice(self, candidate_process_codes, fitting_jobs, action_selector):
        self.decision_context = {
            'kind': PRIORITY_DECISION_KIND,
            'candidate_jobs': fitting_jobs,
        }
        try:
            chosen_process_code = action_selector.select_process(candidate_process_codes)
        finally:
            self.decision_context = None
        return chosen_process_code

    def choose_job(self, ready_queue_result, worker_group_resource, action_selector):
        fitting_jobs = ready_queue_result['fitting_jobs']
        candidate_process_codes = ready_queue_result['candidate_process_codes']
        has_enough_candidates = (
            len(candidate_process_codes) >= MINIMUM_CANDIDATE_PROCESS_COUNT_FOR_PRIORITY_CHOICE)
        if action_selector is None or not has_enough_candidates:
            return fitting_jobs[0]
        if not self.needs_priority_choice(fitting_jobs, worker_group_resource):
            return fitting_jobs[0]
        chosen_process_code = self.request_priority_choice(
            candidate_process_codes, fitting_jobs, action_selector)
        for job in fitting_jobs:
            if job['process_code'] == chosen_process_code:
                return job

    def select_and_start_jobs(self, worker_group, action_selector):
        worker_group_resource = self.worker_group_resources[worker_group]
        while True:
            ready_queue_result = yield from self.ready_queue(worker_group)
            job = self.choose_job(ready_queue_result, worker_group_resource, action_selector)
            self.waiting_jobs_by_worker_group[worker_group].remove(job)
            if self.pcb_stock:
                self.take_pcb_from_stock(worker_group, job['process_code'])
            self.simpy_environment.process(self.run_job_with_worker(
                worker_group, job, ready_queue_result['worker_request']))

    def product_of_job(self, job):
        unit_id = id(job['completed_process_codes'])
        if unit_id in self.product_by_unit:
            product = self.product_by_unit[unit_id]
        else:
            product = self.simulation_processes.processes[job['process_code']].product_code
        is_product = product in self.target_quantity_by_product
        is_smt_line = product in self.smt_production_plan
        if not is_product and not is_smt_line:
            raise ValueError('제품과 무관한 공정의 작업이 어느 제품의 것인지 찾을 수 없음')
        return product

    # ================================================ 제품 한 대 생산: 불량 판정과 수리, 시작할 수 있는 공정을 Ready Queue에 넣거나 바로 실행, 마지막 공정이 끝나면 종료 ================================================
    def list_last_process_codes(self, product):
        last_process_codes = set()
        for process_code, process in self.simulation_processes.processes.items():
            is_last_process = self.simulation_processes.is_last_process(process_code)
            if process.product_code == product and is_last_process:
                last_process_codes.add(process_code)
        return last_process_codes

    def list_unfinished_events(self, finish_events):
        unfinished_events = []
        for finish_event in finish_events:
            if not finish_event.triggered:
                unfinished_events.append(finish_event)
        return unfinished_events

    def produce_unit(self, product, action_selector=None):
        completed_process_codes = set()
        last_process_codes = self.list_last_process_codes(product)
        running_process_codes = set()
        unfinished_events = []
        skipped_process_codes = set()
        judged_process_codes = set()
        is_defective = False
        while True:
            finished_process_codes = []
            for process_code in completed_process_codes - judged_process_codes:
                if process_code not in skipped_process_codes:
                    finished_process_codes.append(process_code)
            judged_process_codes |= completed_process_codes
            is_defective = self.judge_defects(
                product, finished_process_codes, is_defective, completed_process_codes)
            for process_code in finished_process_codes:
                process = self.simulation_processes.processes[process_code]
                if not (is_defective and process.is_defect_event_target_process):
                    continue
                yield from self.request_repair(completed_process_codes, running_process_codes)
                is_defective = False
                self.count_repair(product)
            if last_process_codes.issubset(completed_process_codes):
                return
            for process_code in self.ready_process_codes(product, completed_process_codes):
                if process_code in running_process_codes or process_code in completed_process_codes:
                    continue
                finish_event = self.start_process_of_unit(
                    process_code, completed_process_codes, running_process_codes,
                    skipped_process_codes)
                if finish_event is not None:
                    unfinished_events.append(finish_event)
            unfinished_events = self.list_unfinished_events(unfinished_events)
            if not unfinished_events:
                yield self.stock_arrival_event
                continue
            yield simpy.AnyOf(self.simpy_environment, unfinished_events)
            unfinished_events = self.list_unfinished_events(unfinished_events)

    def start_process_of_unit(
            self, process_code, completed_process_codes, running_process_codes,
            skipped_process_codes):
        process = self.simulation_processes.processes[process_code]
        if process.BranchProbability is not None and random.random() >= process.BranchProbability:
            completed_process_codes.add(process_code)
            skipped_process_codes.add(process_code)
            return None
        if process.BranchProbability is not None:
            self.reserve_recipe_execution_of_sampled_process(process, completed_process_codes)
        worker_group = self.worker_group_of(process_code)
        if worker_group is None or not self.needs_worker(process):
            if not process.CycleTime:
                recipe_execution = self.start_recipe_execution(process, completed_process_codes)
                no_process_weighted_kwh = 0.0
                self.record_recipe_execution(recipe_execution, no_process_weighted_kwh)
                completed_process_codes.add(process_code)
                return None
            running_process_codes.add(process_code)
            finish_event = self.simpy_environment.event()
            self.simpy_environment.process(self.run_process_without_worker(
                process_code, completed_process_codes, running_process_codes, finish_event,
                self.proceeds_only_in_work_time(process)))
            return finish_event
        running_process_codes.add(process_code)
        finish_event = self.simpy_environment.event()
        self.waiting_jobs_by_worker_group[worker_group].append({
            'process_code': process_code,
            'completed_process_codes': completed_process_codes,
            'running_process_codes': running_process_codes,
            'finish_event': finish_event,
        })
        self.wake_ready_queue(worker_group)
        return finish_event

    def request_repair(self, completed_process_codes, running_process_codes):
        repair_process_code = None
        for process_code, process in self.simulation_processes.processes.items():
            if process.is_defect_event_handling_process:
                repair_process_code = process_code
                break
        worker_group = None
        if repair_process_code:
            worker_group = self.worker_group_of(repair_process_code)
        if worker_group is None:
            return
        finish_event = self.simpy_environment.event()
        self.waiting_jobs_by_worker_group[worker_group].append({
            'process_code': repair_process_code,
            'completed_process_codes': completed_process_codes,
            'running_process_codes': running_process_codes,
            'finish_event': finish_event,
        })
        self.wake_ready_queue(worker_group)
        yield finish_event

    # ================================================ 공정 실행: 작업자 공정 한 건(유휴시간 누적, 설비 점유, 전력 누적, 자재 사용, 완료 처리), 작업자가 필요 없는 공정. 설비 점유와 공정 처리(occupy_machines_and_process)에서 실행된 MCF 레시피를 골라 설비 사용과 공정 전력량, 산출 수량을 레시피별로 기록 ================================================
    def run_job_with_worker(self, worker_group, job, worker_request):
        process_code = job['process_code']
        process = self.simulation_processes.processes[process_code]
        self.accumulate_worker_idle_time(worker_group, self.simpy_environment.now)
        running_job_count = self.running_job_count_by_worker_group.get(worker_group, 0)
        self.running_job_count_by_worker_group[worker_group] = running_job_count + 1
        start_sec = self.simpy_environment.now
        no_next_machine_names = []
        yield from self.occupy_machines_and_process(
            process, process.CycleTime, no_next_machine_names, job['completed_process_codes'])
        self.worker_group_resources[worker_group].release(worker_request)
        weighted_kwh = self.accumulate_process_weighted_energy(
            start_sec, self.simpy_environment.now, process.process_rated_power_kw)
        self.accumulate_process_weighted_energy_of_worker_group(worker_group, weighted_kwh)
        if process.InputItemCodeList:
            self.use_input_items(process.InputItemCodeList)
        self.accumulate_worker_idle_time(worker_group, self.simpy_environment.now)
        self.running_job_count_by_worker_group[worker_group] -= 1
        self.wake_ready_queue(worker_group)
        job['completed_process_codes'].add(process_code)
        job['running_process_codes'].discard(process_code)
        if not process.is_defect_event_handling_process:
            self.complete_process(process_code)
        if not job['finish_event'].triggered:
            job['finish_event'].succeed()
        source_worker_group = self.worker_reallocation_conditions.get('source_worker_group')
        if worker_group == source_worker_group:
            self.completed_job_count_of_reallocation_source += 1

    def use_input_items(self, InputItemCodeList):
        deducts_stock = not self.infinite_stock
        newly_ordered_stock_items = self.warehouse.use_items(
            InputItemCodeList, deducts_stock)
        if newly_ordered_stock_items:
            self.simpy_environment.process(self.warehouse.replenish_items(
                self.simpy_environment, self.replenishment_lead_time_sec,
                newly_ordered_stock_items, self.notify_stock_arrival))

    def run_process_without_worker(
            self, process_code, completed_process_codes, running_process_codes, finish_event,
            proceeds_only_in_work_time):
        process = self.simulation_processes.processes[process_code]
        while proceeds_only_in_work_time and not self.can_start_in_work_time(process.CycleTime):
            yield self.simpy_environment.timeout(self.seconds_until_work_time())
        start_sec = self.simpy_environment.now
        yield from self.occupy_machines_and_process(
            process, process.CycleTime, self.next_machine_names(process_code),
            completed_process_codes)
        self.accumulate_process_weighted_energy(
            start_sec, self.simpy_environment.now, process.process_rated_power_kw)
        completed_process_codes.add(process_code)
        running_process_codes.discard(process_code)
        self.complete_process(process_code)
        if not finish_event.triggered:
            finish_event.succeed()

    def can_start_in_work_time(self, duration_sec):
        if not self.is_work_time():
            return False
        remaining_work_time_sec = self.WorkEndTime - self.simpy_environment.now % SECONDS_PER_DAY
        return duration_sec <= remaining_work_time_sec

    def occupy_machines_and_process(
            self, process, duration_sec, next_machine_names, completed_process_codes):
        process_code = process.process_code
        process_power_record = self.record_process_power_start(
            process_code, float(process.process_rated_power_kw or 0.0))
        machine_requests = {}
        for machine_name in process.machine_unit_codes:
            if machine_name in self.machine_resources:
                machine_requests[machine_name] = self.machine_resources[machine_name].request()
        for machine_request in machine_requests.values():
            yield machine_request
        worker_group = None
        if process.machine_unit_codes:
            worker_group = self.worker_group_of(process_code)
        recipe_execution = self.start_recipe_execution(process, completed_process_codes)
        simulation_recipe_index = recipe_execution['simulation_recipe_index']
        for machine_name in process.machine_unit_codes:
            self.record_machine_start(machine_name, worker_group, simulation_recipe_index)
        start_sec = self.simpy_environment.now
        self.record_operation_start(process, duration_sec, completed_process_codes)
        yield self.simpy_environment.timeout(duration_sec)
        self.accumulate_process_operating_time(process_code, duration_sec)
        self.record_operation_end(process, completed_process_codes)
        for machine_name in process.machine_unit_codes:
            self.record_machine_stop(machine_name, worker_group, simulation_recipe_index)
        if process.machine_unit_codes:
            self.on_machine_used(
                process, worker_group, start_sec, self.simpy_environment.now,
                completed_process_codes)
        for machine_name in next_machine_names:
            next_machine_resource = self.machine_resources[machine_name]
            next_machine_request = next_machine_resource.request()
            yield next_machine_request
            next_machine_resource.release(next_machine_request)
        for machine_name, machine_request in machine_requests.items():
            self.machine_resources[machine_name].release(machine_request)
        process_weighted_kwh = self.record_process_power_end(process_power_record)
        self.record_recipe_execution(recipe_execution, process_weighted_kwh)

    def on_machine_used(
            self, process, worker_group, start_sec, end_sec, completed_process_codes):
        pass

    def next_machine_names(self, process_code):
        processes = self.simulation_processes.processes
        current_machine_names = set(processes[process_code].machine_unit_codes)
        next_machine_names = []
        for following_code in self.simulation_processes.following_process_codes(process_code):
            for machine_name in processes[following_code].machine_unit_codes:
                is_in_use_now = machine_name in current_machine_names
                if machine_name in self.machine_resources and not is_in_use_now:
                    next_machine_names.append(machine_name)
        return next_machine_names

    # ================================================ 공정 종료 처리: 생산량·목표 달성 시각 기록, 공정별 완료 횟수. 무한가동이면 모든 제품이 목표 구간 목표 수량을 채웠을 때 새 목표 구간 시작 ================================================
    def complete_process(self, process_code):
        self.record_production(process_code)
        self.completed_count_by_process[process_code] += 1
        is_infinite_operation = self.infinite_operation_conditions['applied']
        if is_infinite_operation and self.is_every_target_quantity_reached_in_target_period():
            self.start_new_target_period(TARGET_PERIOD_END_REASONS['target_quantity_reached'])

    # ================================================ 처리 중 공정 기록: 설비 처리 시작 때 기록(시작, 예상 종료, 제품), 처리가 끝나면 삭제 ================================================
    def record_operation_start(self, process, duration_sec, completed_process_codes):
        unit_id = id(completed_process_codes)
        now_sec = float(self.simpy_environment.now)
        if unit_id in self.product_by_unit:
            product = self.product_by_unit[unit_id]
        else:
            product = process.product_code
        self.running_operations[(unit_id, process.process_code)] = {
            'process_code': process.process_code,
            'start_sec': now_sec,
            'expected_end_sec': now_sec + float(duration_sec),
            'duration_sec': float(duration_sec),
            'product': product,
        }

    def record_operation_end(self, process, completed_process_codes):
        self.running_operations.pop((id(completed_process_codes), process.process_code))

    # ================================================ 작업자 그룹: 공정의 담당 그룹, 작업자 필요 여부, 근무시간 내내 작업 중으로 두는 그룹(담당 공정이 모두 작업자 불필요) ================================================
    def worker_group_of(self, process_code):
        for worker_group, worker_group_values in self.worker_groups.items():
            if process_code in worker_group_values['process_codes']:
                return worker_group
        return None

    def needs_worker(self, process):
        return process.RequiresWorker

    def always_assigned_worker_groups(self):
        processes = self.simulation_processes.processes
        always_assigned_worker_groups = set()
        for worker_group, worker_group_values in self.worker_groups.items():
            if not worker_group_values['process_codes']:
                continue
            needs_no_worker = True
            for process_code in worker_group_values['process_codes']:
                if process_code in processes and processes[process_code].RequiresWorker:
                    needs_no_worker = False
            if needs_no_worker:
                always_assigned_worker_groups.add(worker_group)
        return always_assigned_worker_groups

    def keep_worker_group_assigned(self, worker_group):
        while True:
            if not self.is_work_time():
                self.running_job_count_by_worker_group[worker_group] = 0
                yield self.simpy_environment.timeout(self.seconds_until_work_time())
                continue
            worker_count = self.worker_groups[worker_group]['worker_count']
            self.running_job_count_by_worker_group[worker_group] = worker_count
            self.accumulate_worker_idle_time(worker_group, self.simpy_environment.now)
            yield self.simpy_environment.timeout(WORKING_STATE_UPDATE_INTERVAL_SEC)

    # ================================================ 근무시간 규칙(모든 공정): 작업자도 설비도 쓰지 않는 공정(AAS의 RequiresWorker와 RequiresMachine이 모두 false)만 근무시간 밖에도 진행, 그 밖의 공정은 근무시간에만 진행 ================================================
    def proceeds_only_in_work_time(self, process):
        if process.requires_no_worker_and_no_machine:
            return False
        return True

    # ================================================ 근무시간: 지금이 근무시간인지, 다음 근무 재개까지 남은 초, 누적 근무시간 ================================================
    def is_work_time(self):
        return is_work_time_of_day(
            self.simpy_environment.now % SECONDS_PER_DAY, self.WorkStartTime, self.WorkEndTime,
            self.BreakStartTime, self.break_end_sec)

    def seconds_until_work_time(self):
        return seconds_until_next_work_time(
            self.simpy_environment.now % SECONDS_PER_DAY, self.WorkStartTime,
            self.BreakStartTime, self.break_end_sec)

    def elapsed_work_time_sec(self, sec):
        return calculate_elapsed_work_time_sec(
            sec, self.WorkStartTime, self.WorkEndTime, self.BreakStartTime, self.break_end_sec)

    # ================================================ 자재 입고 알림: 자재를 기다리던 제품 생산을 깨움 ================================================
    def notify_stock_arrival(self):
        stock_arrival_event = self.stock_arrival_event
        self.stock_arrival_event = self.simpy_environment.event()
        if not stock_arrival_event.triggered:
            stock_arrival_event.succeed()

    # ================================================ 작업자 재배치: 출발 작업자 그룹의 유휴 인원이 기준 이상인 상태가 기준 시간 이어지면 작업자 수와 자원 용량을 한 번 옮김 ================================================
    def is_worker_reallocation_condition_met(self):
        conditions = self.worker_reallocation_conditions
        source_worker_group = conditions['source_worker_group']
        has_source_completed_job = self.completed_job_count_of_reallocation_source > 0
        if conditions['require_source_completion'] and not has_source_completed_job:
            return False
        worker_count = self.worker_groups[source_worker_group]['worker_count']
        running_job_count = self.running_job_count_by_worker_group.get(source_worker_group, 0)
        return worker_count - running_job_count >= conditions['minimum_idle_worker_count']

    def monitor_worker_reallocation(self):
        conditions = self.worker_reallocation_conditions
        check_interval_sec = conditions['check_interval_sec']
        idle_duration_sec = 0.0
        while self.worker_reallocation_sec is None:
            yield self.simpy_environment.timeout(check_interval_sec)
            if not self.is_work_time():
                continue
            if self.is_worker_reallocation_condition_met():
                idle_duration_sec = idle_duration_sec + check_interval_sec
            else:
                idle_duration_sec = 0.0
            if idle_duration_sec < conditions['idle_duration_sec']:
                continue
            self.reallocate_workers()

    def reallocate_workers(self):
        conditions = self.worker_reallocation_conditions
        source_worker_group = conditions['source_worker_group']
        moved_worker_count_by_worker_group = conditions['moved_worker_count_by_worker_group']
        now_sec = float(self.simpy_environment.now)
        self.accumulate_worker_idle_time(source_worker_group, now_sec)
        for worker_group in moved_worker_count_by_worker_group:
            self.accumulate_worker_idle_time(worker_group, now_sec)
        for worker_group, moved_worker_count in moved_worker_count_by_worker_group.items():
            worker_group_values = self.worker_groups[worker_group]
            worker_group_values['worker_count'] += moved_worker_count
            worker_group_resource = self.worker_group_resources[worker_group]
            added_capacity = moved_worker_count * worker_group_values['UnitsPerWorker']
            worker_group_resource._capacity += added_capacity
            worker_group_resource._trigger_put(None)
            self.wake_ready_queue(worker_group)
        total_moved_worker_count = sum(moved_worker_count_by_worker_group.values())
        source_worker_group_values = self.worker_groups[source_worker_group]
        source_worker_group_values['worker_count'] -= total_moved_worker_count
        removed_capacity = total_moved_worker_count * source_worker_group_values['UnitsPerWorker']
        self.worker_group_resources[source_worker_group]._capacity -= removed_capacity
        self.worker_reallocation_sec = now_sec

    # ================================================ 무한가동의 조립 생산(PO 없이 계속 생산): 제품마다 끝나지 않은 대수를 유지 수량(제품별 비율 × 비율 1당 유지 수량)으로 유지. 시작할 때 제품 순서대로(제품별로 전량, 목표 수량 실행과 같은 순서) 유지 수량만큼 생산을 시작하고, 한 대가 완성되면 같은 제품 한 대를 새로 시작. 어느 작업을 먼저 할지는 목표 수량 실행과 같이 작업자 그룹이 대기 목록에서 고름 ================================================
    def maintained_unfinished_quantity_by_product(self):
        infinite_operation_conditions = self.infinite_operation_conditions
        return quantity_by_product_ratio(
            list(self.target_quantity_by_product), infinite_operation_conditions['product_ratio'],
            infinite_operation_conditions['maintained_unfinished_quantity_per_ratio_unit'])

    def start_infinite_operation(self, action_selector):
        if not self.pcb_stock_limited:
            raise ValueError('무한가동은 PCB 재고 제한을 켠 조건에서만 실행할 수 있음')
        maintained_quantity_by_product = self.maintained_unfinished_quantity_by_product()
        for product, maintained_quantity in maintained_quantity_by_product.items():
            for unit_index in range(maintained_quantity):
                self.simpy_environment.process(
                    self.produce_units_one_after_another(product, action_selector))
        self.simpy_environment.process(
            self.end_target_period_at_due(self.target_period_number))

    def produce_units_one_after_another(self, product, action_selector):
        while True:
            yield from self.produce_unit(product, action_selector)

    # ================================================ 무한가동의 목표 구간(목표 수량 실행 한 번과 같은 조건. 강화학습 모델 입력과 보상을 목표 구간마다 새로 셈): 모든 제품이 목표 구간 목표 수량을 채우거나 목표 구간 납기(목표 구간 시작 + 제품별 납기)가 지나면, 둘 중 먼저 오는 쪽에서 끝나고 새 목표 구간 시작. 목표 수량을 넘겨 생산한 수량은 다음 목표 구간으로 넘김. 목표 구간 시작부터 다시 세는 값: 지난 시간, 제품별 생산량과 목표 달성 시각, 납기, 공정별 완료 횟수, 누적 시간대 가중 전력량, 대기 시간, 보상. 목표 수량 실행은 목표 구간이 하나뿐이라 실행 시작부터 센 값과 같음 ================================================
    def reset_target_period(self):
        self.target_period_number = FIRST_TARGET_PERIOD_NUMBER
        self.target_period_start_sec = 0.0
        self.target_period_due_sec_by_product = due_sec_by_product_of_target_period(
            self.target_period_start_sec, self.due_sec_by_product)
        self.completed_count_by_process_at_target_period_start = {}
        self.cumulative_weighted_energy_kwh_at_target_period_start = 0.0
        self.target_period_records = []

    def is_every_target_quantity_reached_in_target_period(self):
        for product, target_quantity in self.target_quantity_by_product.items():
            production_quantity = self.production_quantity_in_target_period_by_product[product]
            if not is_target_quantity_reached(production_quantity, target_quantity):
                return False
        return True

    def start_new_target_period(self, end_reason):
        now_sec = float(self.simpy_environment.now)
        self.target_period_records.append({
            'target_period_number': self.target_period_number,
            'start_sec': self.target_period_start_sec,
            'end_sec': now_sec,
            'end_reason': end_reason,
            'production_quantity_by_product': dict(
                self.production_quantity_in_target_period_by_product),
            'due_sec_by_product': dict(self.target_period_due_sec_by_product),
            'completion_sec_by_product': dict(self.completion_sec_by_product),
        })
        self.target_period_number += 1
        self.target_period_start_sec = now_sec
        self.target_period_due_sec_by_product = due_sec_by_product_of_target_period(
            self.target_period_start_sec, self.due_sec_by_product)
        self.carry_over_production_quantity_to_new_target_period(now_sec)
        self.completed_count_by_process_at_target_period_start = dict(
            self.completed_count_by_process)
        self.cumulative_weighted_energy_kwh_at_target_period_start = (
            self.cumulative_weighted_energy_kwh())
        self.simpy_environment.process(
            self.end_target_period_at_due(self.target_period_number))

    def carry_over_production_quantity_to_new_target_period(self, target_period_start_sec):
        production_quantity_by_product = self.production_quantity_in_target_period_by_product
        for product, target_quantity in self.target_quantity_by_product.items():
            carried_over_quantity = production_quantity_carried_over_to_next_target_period(
                production_quantity_by_product[product], target_quantity)
            production_quantity_by_product[product] = carried_over_quantity
            self.completion_sec_by_product[product] = None
            if is_target_quantity_reached(carried_over_quantity, target_quantity):
                self.completion_sec_by_product[product] = target_period_start_sec

    def end_target_period_at_due(self, target_period_number):
        latest_due_sec = max(self.target_period_due_sec_by_product.values())
        yield self.simpy_environment.timeout(latest_due_sec - self.simpy_environment.now)
        if self.target_period_number == target_period_number:
            self.start_new_target_period(TARGET_PERIOD_END_REASONS['due_passed'])

    def completed_count_in_target_period_by_process(self):
        count_at_start_by_process = self.completed_count_by_process_at_target_period_start
        completed_count_in_target_period_by_process = {}
        for process_code, completed_count in self.completed_count_by_process.items():
            count_at_start = count_at_start_by_process.get(process_code, 0)
            completed_count_in_target_period_by_process[process_code] = (
                completed_count - count_at_start)
        return completed_count_in_target_period_by_process

    def cumulative_weighted_energy_kwh_in_target_period(self):
        weighted_energy_kwh_at_start = self.cumulative_weighted_energy_kwh_at_target_period_start
        return self.cumulative_weighted_energy_kwh() - weighted_energy_kwh_at_start
