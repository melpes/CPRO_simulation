import math
import random

import simpy

from knowledge_graph import Process, code_from_kg_node_path


# ================================================ SMT 착수 시점 판단: 판단 종류 이름, 보류 중 다시 확인하는 간격(15분), 남은 보류 가능 시간을 0으로 보는 허용 오차, 보류 기록의 규칙 이름 ================================================
START_TIMING_DECISION_KIND = 'start_timing'
START_TIMING_CHECK_INTERVAL_SEC = 900.0
REMAINING_DELAY_TOLERANCE_SEC = 1e-09
START_DELAY_RULE_NAME = 'threshold'


# ================================================ SMT 필름 교체·Chip 보충 이벤트: 발생 기록에 적는 시작·종료 이름, 전용 난수의 이름(시뮬레이션 난수 seed와 이 이름과 SMT 라인 이름을 이은 글자가 seed. 불량 판정 등 다른 난수의 호출 순서를 바꾸지 않음) ================================================
SMT_MATERIAL_EVENT_RECORD_NAMES = {
    'start': 'start',
    'end': 'end',
}
SMT_MATERIAL_EVENT_RANDOM_NAME = 'smt_material_events'


# ================================================ PCB 초기 재고를 올림하기 전에 빼는 부동소수점 여유값 ================================================
INITIAL_PCB_STOCK_ROUNDING_TOLERANCE = 1e-09


# ================================================ PCB 초기 재고: 초기 재고 비율 × 품목별 필요 수량을 올림 ================================================
def initial_pcb_stock_quantity(pcb_initial_stock_ratio, required_quantity):
    initial_quantity = float(pcb_initial_stock_ratio) * required_quantity
    return math.ceil(initial_quantity - INITIAL_PCB_STOCK_ROUNDING_TOLERANCE)


# ================================================ SMT 생산 묶음의 기준 소요시간: 단계 사이클타임 합 + 뒤따르는 어레이 수 × (단계 사이클타임 ÷ 설비 동시 처리 수)의 최댓값 ================================================
def normal_smt_production_duration_sec(step_cycle_times, step_capacities, array_count):
    cycle_times_per_capacity = []
    for step_cycle_time, step_capacity in zip(step_cycle_times, step_capacities):
        cycle_times_per_capacity.append(step_cycle_time / step_capacity)
    longest_cycle_time_per_capacity = max(cycle_times_per_capacity, default=0.0)
    following_array_count = max(array_count - 1, 0)
    return sum(step_cycle_times) + longest_cycle_time_per_capacity * following_array_count


# ================================================ 무한가동의 SMT 생산 대상 선정 규칙: 그 SMT 라인의 생산 계획에 있는 PCB 품목 가운데 지금 PCB 재고(pcb_stock. 조립이 착수할 때 꺼내고 SMT 생산 묶음이 끝나면 입고하는 수량)가 가장 적은 품목. 재고가 같으면 생산 계획에서 먼저 나오는 품목. 생산할 어레이가 없는 품목은 고르지 않음 ================================================
def planned_item_with_least_pcb_stock(pcb_production_plan, pcb_stock):
    selected_planned_item = None
    for planned_item in pcb_production_plan:
        if planned_item['array_count'] <= 0:
            continue
        if selected_planned_item is None:
            selected_planned_item = planned_item
            continue
        selected_pcb_stock = pcb_stock[selected_planned_item['item_code']]
        if pcb_stock[planned_item['item_code']] < selected_pcb_stock:
            selected_planned_item = planned_item
    return selected_planned_item


class SmtLine:

    # ================================================ SMT 라인 속성 만들기: 라인별 단계·설비 정보, 생산 기록, 착수 시점 판단 기록, PCB 재고, 필름 교체·Chip 보충 이벤트 ================================================
    def reset_smt_line(self):
        self.smt_line_information = self.collect_smt_line_information()
        self.check_start_delay_allowed_process_kg_node_paths()
        self.produced_pcb_arrays = []
        self.smt_production_records = []
        self.start_timing_records = []
        self.active_start_timing_by_smt_line = {}
        self.previous_pcb_item_code_by_smt_line = {}
        self.pcb_array_in_production_by_smt_line = {}
        self.reset_pcb_stock()
        self.reset_smt_material_events()

    # ================================================ SMT 라인별 단계·설비 정보: 라인의 Process 노드, 단계 공정, 설비, 단계 사이클타임, 단계별 설비 동시 처리 수 ================================================
    def find_smt_line_process_node(self, smt_line):
        smt_line_process_nodes = []
        for process_node in self.knowledge_graph.nodes_of_class(Process):
            smt_line_process_code = code_from_kg_node_path(process_node.kg_node_path)
            step_process_codes = self.step_process_codes_by_smt_line.get(smt_line_process_code)
            if process_node.product_code == smt_line and step_process_codes:
                smt_line_process_nodes.append(process_node)
        if len(smt_line_process_nodes) != 1:
            raise ValueError(f'SMT 라인 {smt_line}: 단계가 있는 Process 노드가 하나가 아님')
        return smt_line_process_nodes[0]

    def step_capacity(self, step_process):
        machine_capacities = []
        for machine_unit_code in step_process.machine_unit_codes:
            machine_capacities.append(int(self.machines[machine_unit_code]['MaxCapacity']))
        if not machine_capacities:
            return int(step_process.simultaneous_processing_quantity)
        if min(machine_capacities) <= 0:
            raise ValueError(f'SMT 라인 단계 {step_process.process_code}: 설비 MaxCapacity가 0 이하')
        return min(machine_capacities)

    def collect_smt_line_information(self):
        smt_line_information = {}
        for smt_line in self.smt_production_plan:
            smt_line_process_node = self.find_smt_line_process_node(smt_line)
            smt_line_process_code = code_from_kg_node_path(smt_line_process_node.kg_node_path)
            step_process_codes = list(self.step_process_codes_by_smt_line[smt_line_process_code])
            machine_unit_codes = []
            step_cycle_times = []
            step_capacities = []
            for step_process_code in step_process_codes:
                step_process = self.simulation_processes.processes[step_process_code]
                for machine_unit_code in step_process.machine_unit_codes:
                    if machine_unit_code not in machine_unit_codes:
                        machine_unit_codes.append(machine_unit_code)
                step_cycle_times.append(float(step_process.CycleTime))
                step_capacities.append(self.step_capacity(step_process))
            smt_line_information[smt_line] = {
                'process_kg_node_path': smt_line_process_node.kg_node_path,
                'process_code': smt_line_process_code,
                'step_process_codes': step_process_codes,
                'machine_unit_codes': machine_unit_codes,
                'step_cycle_times': step_cycle_times,
                'step_capacities': step_capacities,
            }
        return smt_line_information

    def check_start_delay_allowed_process_kg_node_paths(self):
        smt_line_process_kg_node_paths = []
        for line_information in self.smt_line_information.values():
            smt_line_process_kg_node_paths.append(line_information['process_kg_node_path'])
        if self.start_delay_allowed_process_kg_node_paths is None:
            self.start_delay_allowed_process_kg_node_paths = smt_line_process_kg_node_paths
        unknown_paths = []
        for process_kg_node_path in self.start_delay_allowed_process_kg_node_paths:
            if process_kg_node_path not in smt_line_process_kg_node_paths:
                unknown_paths.append(process_kg_node_path)
        if unknown_paths:
            raise ValueError(f'SMT 라인에 연결되지 않은 착수 보류 허용 공정 경로: {unknown_paths}')

    # ================================================ PCB 재고 초기화: 품목별 필요 수량(공정 투입 수량 × 제품 목표 수량)과 초기 재고, PCB를 쓰는 작업자 그룹, 조립이 PCB를 재고에서 꺼냈음을 알리는 SimPy event ================================================
    def reset_pcb_stock(self):
        self.pcb_stock = {}
        self.required_pcb_quantity_by_item_code = {}
        self.pcb_taken_from_stock_event = self.simpy_environment.event()
        self.initial_pcb_stock = {}
        self.pcb_consuming_worker_groups = []
        self.pcb_shortage_start = {}
        self.pcb_shortage_wait_records = []
        if not self.pcb_stock_limited:
            return
        required_quantity_by_item_code = {}
        for pcb_production_plan in self.smt_production_plan.values():
            for planned_item in pcb_production_plan:
                required_quantity_by_item_code[planned_item['item_code']] = 0
        pcb_consuming_worker_groups = set()
        for process_code, process in self.simulation_processes.processes.items():
            if process.product_code not in self.target_quantity_by_product:
                continue
            target_quantity = self.target_quantity_by_product[process.product_code]
            for item_code, input_quantity in process.InputItemCodeList.items():
                if item_code not in required_quantity_by_item_code:
                    continue
                required_quantity_by_item_code[item_code] += input_quantity * target_quantity
                worker_group = self.worker_group_of(process_code)
                if worker_group is not None and self.needs_worker(process):
                    pcb_consuming_worker_groups.add(worker_group)
        self.required_pcb_quantity_by_item_code = required_quantity_by_item_code
        for pcb_item_code, required_quantity in required_quantity_by_item_code.items():
            initial_quantity = initial_pcb_stock_quantity(
                self.pcb_initial_stock_ratio, required_quantity)
            self.initial_pcb_stock[pcb_item_code] = initial_quantity
            self.pcb_stock[pcb_item_code] = float(initial_quantity)
        self.pcb_consuming_worker_groups = sorted(pcb_consuming_worker_groups)

    # ================================================ PCB 재고 확인: 공정이 쓰는 PCB 수량, 재고가 모자란 작업을 후보에서 빼기 ================================================
    def required_pcb_quantities(self, process_code):
        process = self.simulation_processes.processes[process_code]
        required_quantity_by_item_code = {}
        for item_code, input_quantity in process.InputItemCodeList.items():
            if item_code in self.pcb_stock:
                required_quantity_by_item_code[item_code] = input_quantity
        return required_quantity_by_item_code

    def filter_jobs_by_pcb_stock(self, worker_group, jobs):
        jobs_with_enough_pcb = []
        short_pcb_item_codes = set()
        for job in jobs:
            short_pcb_item_codes_of_job = []
            required_quantities = self.required_pcb_quantities(job['process_code'])
            for pcb_item_code, required_quantity in required_quantities.items():
                if self.pcb_stock[pcb_item_code] < required_quantity:
                    short_pcb_item_codes_of_job.append(pcb_item_code)
            if short_pcb_item_codes_of_job:
                short_pcb_item_codes.update(short_pcb_item_codes_of_job)
            else:
                jobs_with_enough_pcb.append(job)
        if not jobs_with_enough_pcb and worker_group not in self.pcb_shortage_start:
            self.pcb_shortage_start[worker_group] = {
                'start_sec': float(self.simpy_environment.now),
                'pcb_item_codes': sorted(short_pcb_item_codes),
            }
        return jobs_with_enough_pcb

    # ================================================ PCB 재고 차감·입고: 조립 작업 착수 때 차감하고 PCB 부족 대기 구간 기록(무한가동이면 PCB를 꺼냈음을 SMT 라인에 알림), SMT 생산이 끝나면 입고하고 Ready Queue를 깨움 ================================================
    def take_pcb_from_stock(self, worker_group, process_code):
        required_quantities = self.required_pcb_quantities(process_code)
        for pcb_item_code, required_quantity in required_quantities.items():
            self.pcb_stock[pcb_item_code] -= required_quantity
        if self.infinite_operation_conditions['applied'] and required_quantities:
            self.notify_pcb_taken_from_stock()
        if worker_group not in self.pcb_shortage_start:
            return
        pcb_shortage = self.pcb_shortage_start.pop(worker_group)
        now_sec = self.simpy_environment.now
        shortage_start_sec = pcb_shortage['start_sec']
        work_time_sec = (
            self.elapsed_work_time_sec(now_sec) - self.elapsed_work_time_sec(shortage_start_sec))
        self.pcb_shortage_wait_records.append({
            'worker_group': worker_group,
            'pcb_item_codes': pcb_shortage['pcb_item_codes'],
            'start_sec': shortage_start_sec,
            'end_sec': float(now_sec),
            'work_time_sec': work_time_sec,
        })

    def notify_pcb_taken_from_stock(self):
        pcb_taken_from_stock_event = self.pcb_taken_from_stock_event
        self.pcb_taken_from_stock_event = self.simpy_environment.event()
        if not pcb_taken_from_stock_event.triggered:
            pcb_taken_from_stock_event.succeed()

    def add_pcb_to_stock(self, pcb_item_code, pcb_count):
        self.pcb_stock[pcb_item_code] += pcb_count
        for worker_group in self.pcb_consuming_worker_groups:
            self.wake_ready_queue(worker_group)

    # ================================================ PCB 어레이 1장 생산: SMT 라인 단계 공정을 모두 거치고 시작·종료 시각 기록. SMT 라인은 한 번에 PCB 품목 하나의 어레이만 생산하므로 생산 중인 PCB 품목과 어레이 1장의 PCB 수량을 라인마다 적어 둠(MCF 레시피별 기록이 읽음) ================================================
    def produce_pcb_array(self, smt_line, pcb_item_code, pcb_count_per_array, action_selector):
        start_sec = float(self.simpy_environment.now)
        yield from self.produce_unit(smt_line, action_selector)
        self.warehouse.record_produced_items({pcb_item_code: pcb_count_per_array})
        self.produced_pcb_arrays.append({
            'smt_line': smt_line,
            'pcb_item_code': pcb_item_code,
            'pcb_count': pcb_count_per_array,
            'start_sec': start_sec,
            'end_sec': float(self.simpy_environment.now),
        })

    def start_pcb_array_productions(
            self, smt_line, pcb_item_code, array_count, pcb_count_per_array, action_selector):
        self.pcb_array_in_production_by_smt_line[smt_line] = {
            'pcb_item_code': pcb_item_code,
            'pcb_count_per_array': pcb_count_per_array,
        }
        array_productions = []
        for array_index in range(array_count):
            array_production = self.simpy_environment.process(self.produce_pcb_array(
                smt_line, pcb_item_code, pcb_count_per_array, action_selector))
            array_productions.append(array_production)
        return array_productions

    # ================================================ SMT 필름 교체·Chip 보충 이벤트 속성 만들기: 발생 기록, 적용할 때만 SMT 라인별 이벤트(Simulation AAS의 개별 자원 대상 이벤트 가운데 대상 설비가 그 라인의 설비인 것)에 대기 시간을 붙이고 라인별 전용 난수를 만듦 ================================================
    def reset_smt_material_events(self):
        self.smt_material_event_records = []
        self.smt_material_events_by_smt_line = {}
        self.smt_material_event_random_by_smt_line = {}
        for smt_line in self.smt_line_information:
            self.smt_material_events_by_smt_line[smt_line] = []
        if not self.smt_material_event_conditions['applied']:
            return
        simulation_seed = self.smt_material_event_conditions['simulation_seed']
        wait_sec_by_EventCode = self.smt_material_event_conditions['wait_sec_by_EventCode']
        for smt_line in self.smt_line_information:
            random_seed = f'{simulation_seed}:{SMT_MATERIAL_EVENT_RANDOM_NAME}:{smt_line}'
            self.smt_material_event_random_by_smt_line[smt_line] = random.Random(random_seed)
        for target_unit_resource_event in self.target_unit_resource_events:
            smt_line = self.find_smt_line_of_machine(
                target_unit_resource_event['target_unit_code'])
            smt_material_event = dict(target_unit_resource_event)
            EventCode = target_unit_resource_event['EventCode']
            smt_material_event['wait_sec'] = float(wait_sec_by_EventCode[EventCode])
            self.smt_material_events_by_smt_line[smt_line].append(smt_material_event)

    def find_smt_line_of_machine(self, machine_unit_code):
        for smt_line, line_information in self.smt_line_information.items():
            if machine_unit_code in line_information['machine_unit_codes']:
                return smt_line
        raise ValueError(f'개별 자원 대상 이벤트의 대상 설비 {machine_unit_code}: SMT 라인의 설비가 아님')

    # ================================================ SMT 필름 교체·Chip 보충 이벤트 발생: SMT 라인의 생산 대상 PCB 품목이 바뀔 때 이벤트마다 전용 난수로 발생 여부를 정하고, 발생한 이벤트를 차례로 대기 시간만큼 기다려 그 라인의 다음 품목 착수를 늦춤. 남은 근무시간 안에 대기가 끝나지 않으면 다음 근무 시작으로 미룸. 대기 중 설비 전력은 더하지 않음 ================================================
    def list_occurred_smt_material_events(self, smt_line):
        smt_material_event_random = self.smt_material_event_random_by_smt_line[smt_line]
        occurred_smt_material_events = []
        for smt_material_event in self.smt_material_events_by_smt_line[smt_line]:
            occurrence_probability = smt_material_event['occurrence_probability_per_recipe_change']
            if smt_material_event_random.random() < occurrence_probability:
                occurred_smt_material_events.append(smt_material_event)
        return occurred_smt_material_events

    def wait_for_smt_material_events(self, smt_line, pcb_item_code):
        if not self.smt_material_event_conditions['applied']:
            return
        for smt_material_event in self.list_occurred_smt_material_events(smt_line):
            wait_sec = smt_material_event['wait_sec']
            while not self.can_start_in_work_time(wait_sec):
                yield self.simpy_environment.timeout(self.seconds_until_work_time())
            self.record_smt_material_event(
                SMT_MATERIAL_EVENT_RECORD_NAMES['start'], smt_line, pcb_item_code,
                smt_material_event)
            yield self.simpy_environment.timeout(wait_sec)
            self.record_smt_material_event(
                SMT_MATERIAL_EVENT_RECORD_NAMES['end'], smt_line, pcb_item_code,
                smt_material_event)

    def record_smt_material_event(self, record_name, smt_line, pcb_item_code, smt_material_event):
        self.smt_material_event_records.append({
            'sec': float(self.simpy_environment.now),
            'event': record_name,
            'EventCode': smt_material_event['EventCode'],
            'smt_line': smt_line,
            'machine_name': smt_material_event['target_unit_code'],
            'pcb_item_code': pcb_item_code,
        })

    # ================================================ SMT 라인의 PCB 생산: 목표 수량 실행은 생산 계획의 품목을 계획 순서대로 한 번씩 생산. 무한가동은 생산 대상 선정 규칙(PCB 재고가 가장 적은 품목)으로 고른 품목을 계속 생산하고, 고른 품목의 PCB 재고도 상한 이상이면(모든 품목의 재고가 참) 조립이 PCB를 재고에서 꺼낼 때까지 기다림 ================================================
    def run_smt_line(self, smt_line, pcb_production_plan, action_selector):
        self.previous_pcb_item_code_by_smt_line[smt_line] = None
        if self.infinite_operation_conditions['applied']:
            yield from self.produce_pcb_item_with_least_stock_repeatedly(
                smt_line, pcb_production_plan, action_selector)
        else:
            yield from self.produce_planned_pcb_items(
                smt_line, pcb_production_plan, action_selector)

    def produce_planned_pcb_items(self, smt_line, pcb_production_plan, action_selector):
        for planned_item in pcb_production_plan:
            if planned_item['array_count'] <= 0:
                continue
            yield from self.produce_pcb_item(smt_line, planned_item, action_selector)

    def produce_pcb_item_with_least_stock_repeatedly(
            self, smt_line, pcb_production_plan, action_selector):
        while True:
            planned_item = planned_item_with_least_pcb_stock(pcb_production_plan, self.pcb_stock)
            if planned_item is None:
                return
            if self.is_pcb_stock_enough_for_target_period(planned_item['item_code']):
                yield self.pcb_taken_from_stock_event
                continue
            yield from self.produce_pcb_item(smt_line, planned_item, action_selector)

    # ================================================ 무한가동의 PCB 재고 상한 규칙: 품목의 PCB 재고가 한 목표 구간의 필요 수량(공정 투입 수량 × 제품의 목표 구간 목표 수량) 이상이면 그 품목을 더 만들지 않음 ================================================
    def is_pcb_stock_enough_for_target_period(self, pcb_item_code):
        required_quantity = self.required_pcb_quantity_by_item_code[pcb_item_code]
        return self.pcb_stock[pcb_item_code] >= required_quantity

    # ================================================ PCB 품목 하나의 생산 묶음: 품목이 바뀌면 필름 교체·Chip 보충 이벤트 대기 → 근무시간 대기 → 착수 시점 판단 → 어레이 전량 생산 → PCB 재고 입고 → 결과 전달 ================================================
    def produce_pcb_item(self, smt_line, planned_item, action_selector):
        pcb_item_code = planned_item['item_code']
        array_count = planned_item['array_count']
        pcb_count_per_array = int(planned_item['quantity_per_array'])
        previous_pcb_item_code = self.previous_pcb_item_code_by_smt_line[smt_line]
        is_first_pcb_item = previous_pcb_item_code is None
        is_pcb_item_changed = pcb_item_code != previous_pcb_item_code
        if is_pcb_item_changed and not is_first_pcb_item:
            yield from self.wait_for_smt_material_events(smt_line, pcb_item_code)
        self.previous_pcb_item_code_by_smt_line[smt_line] = pcb_item_code
        while not self.is_work_time():
            yield self.simpy_environment.timeout(self.seconds_until_work_time())
        smt_production_record = {
            'smt_line': smt_line,
            'pcb_item_code': pcb_item_code,
            'array_count': array_count,
            'pcb_count': array_count * pcb_count_per_array,
            'start_request_sec': float(self.simpy_environment.now),
        }
        start_timing_record = yield from self.decide_smt_start_timing(
            smt_line, pcb_item_code, array_count, pcb_count_per_array, action_selector)
        array_productions = self.start_pcb_array_productions(
            smt_line, pcb_item_code, array_count, pcb_count_per_array, action_selector)
        yield simpy.AllOf(self.simpy_environment, array_productions)
        smt_production_record['end_sec'] = float(self.simpy_environment.now)
        if self.pcb_stock:
            self.add_pcb_to_stock(pcb_item_code, array_count * pcb_count_per_array)
        self.smt_production_records.append(smt_production_record)
        self.report_smt_lot_result(start_timing_record, action_selector)

    # ================================================ PCB 재고 제한을 끈 경우의 SMT 라인 생산: 착수 시점 판단과 재고 반영 없이 생산 계획의 어레이를 품목 순서대로 생산 ================================================
    def run_smt_line_without_stock_limit(self, smt_line, pcb_production_plan, action_selector):
        for planned_item in pcb_production_plan:
            array_productions = self.start_pcb_array_productions(
                smt_line, planned_item['item_code'], planned_item['array_count'],
                int(planned_item['quantity_per_array']), action_selector)
            yield simpy.AllOf(self.simpy_environment, array_productions)

    # ================================================ SMT 착수 시점 판단 기록 만들기: 요청 시각, 보류 없이 생산할 때 걸리는 시간, 그때 SMT 설비의 사용 수와 시간대 가중 전력량 ================================================
    def open_start_timing_record(self, smt_line, pcb_item_code, array_count, pcb_count_per_array):
        line_information = self.smt_line_information[smt_line]
        machine_unit_codes = line_information['machine_unit_codes']
        normal_duration_sec = normal_smt_production_duration_sec(
            line_information['step_cycle_times'], line_information['step_capacities'], array_count)
        machine_request_counts = {}
        for machine_unit_code in machine_unit_codes:
            machine_resource = self.machine_resources[machine_unit_code]
            machine_request_counts[machine_unit_code] = machine_resource.count
        start_timing_record = {
            'kind': START_TIMING_DECISION_KIND,
            'smt_line': smt_line,
            'process_code': line_information['process_code'],
            'process_kg_node_path': line_information['process_kg_node_path'],
            'pcb_item_code': pcb_item_code,
            'quantity': int(array_count * pcb_count_per_array),
            'start_sec': float(self.simpy_environment.now),
            'end_sec': None,
            'normal_duration_sec': float(normal_duration_sec),
            'resources_at_choice': machine_request_counts,
            'energy_before': self.machines_weighted_energy_kwh(machine_unit_codes),
        }
        self.start_timing_records.append(start_timing_record)
        self.active_start_timing_by_smt_line[smt_line] = start_timing_record
        return start_timing_record

    # ================================================ SMT 착수 시점 판단: 보류를 허용한 SMT 라인이면 강화학습 실행 객체에 묻고, 아니면 바로 착수. 판단 결과를 기록에 채움 ================================================
    def decide_smt_start_timing(
            self, smt_line, pcb_item_code, array_count, pcb_count_per_array, action_selector):
        start_timing_record = self.open_start_timing_record(
            smt_line, pcb_item_code, array_count, pcb_count_per_array)
        allowed_process_kg_node_paths = self.start_delay_allowed_process_kg_node_paths
        is_start_delay_allowed = (
            start_timing_record['process_kg_node_path'] in allowed_process_kg_node_paths)
        if action_selector is None or not is_start_delay_allowed:
            start_timing_choice = {'start_delay_sec': 0.0, 'automatic': True}
        else:
            start_timing_choice = yield from self.hold_until_start(
                start_timing_record, action_selector)
        start_delay_sec = float(start_timing_choice['start_delay_sec'])
        start_timing_record['start_timing_choice'] = start_timing_choice
        start_timing_record['start_delay_sec'] = start_delay_sec
        start_timing_record['start_sec_after_delay'] = (
            start_timing_record['start_sec'] + start_delay_sec)
        return start_timing_record

    # ================================================ 착수 보류: 강화학습 실행 객체에 지금 착수할지 묻고, 보류하면 15분 뒤 다시 확인(보류 상한까지) ================================================
    def hold_until_start(self, start_timing_record, action_selector):
        start_request_sec = start_timing_record['start_sec']
        action_selector.decision_counts[START_TIMING_DECISION_KIND] += 1
        check_count = 0
        while True:
            passed_sec = float(self.simpy_environment.now) - start_request_sec
            remaining_delay_sec = float(self.max_start_delay_sec) - passed_sec
            starts_now = self.ask_start_timing(
                start_timing_record, remaining_delay_sec, action_selector)
            if check_count == 0:
                first_burden = float(action_selector.last_start_now_burden)
                start_timing_record['first_burden'] = first_burden
            check_count += 1
            if starts_now:
                break
            yield self.simpy_environment.timeout(
                min(START_TIMING_CHECK_INTERVAL_SEC, remaining_delay_sec))
        return {
            'start_delay_sec': float(self.simpy_environment.now) - start_request_sec,
            'rule': START_DELAY_RULE_NAME,
            'check_count': check_count,
        }

    def ask_start_timing(self, start_timing_record, remaining_delay_sec, action_selector):
        if remaining_delay_sec <= REMAINING_DELAY_TOLERANCE_SEC:
            return True
        self.decision_context = start_timing_record
        try:
            starts_now = action_selector.judge_start_timing(
                start_timing_record, remaining_delay_sec)
        finally:
            self.decision_context = None
        return starts_now

    # ================================================ SMT 생산 묶음 결과 전달: 판단 기록에 종료 시각과 SMT 설비의 시간대 가중 전력량을 채워 강화학습 실행 객체에 전달 ================================================
    def report_smt_lot_result(self, start_timing_record, action_selector):
        smt_line = start_timing_record['smt_line']
        machine_unit_codes = self.smt_line_information[smt_line]['machine_unit_codes']
        weighted_kwh_now = self.machines_weighted_energy_kwh(machine_unit_codes)
        weighted_kwh_before = start_timing_record['energy_before']
        start_timing_record['end_sec'] = float(self.simpy_environment.now)
        start_timing_record['weighted_kwh'] = weighted_kwh_now - weighted_kwh_before
        del self.active_start_timing_by_smt_line[smt_line]
        if action_selector is not None:
            action_selector.record_start_timing_result(start_timing_record)
