# 시뮬레이션 인스턴스 실행 코드: simulation_generator.py가 만든 파일. 값은 같은 이름의 json(INSTANCE_FILE_PATH)
# AAS 입력: aas_data
# 실행: python <이 파일> --quantity 제품별 목표 수량 [--replications N] [--seed S] [--instance 다른 json]
# 시나리오: 이 파일을 import해 DEFAULT_MODEL_CLASS를 상속, 메서드를 재정의한 뒤 main(새 클래스)

import argparse
import collections
import itertools
import json
import math
import os
import random
import sys
import simpy
from dataclasses import dataclass


SECONDS_PER_HOUR = 3600.0
SECONDS_PER_DAY = 86400.0
TIME_TOLERANCE = 1e-09
BRANCH_PROBABILITY_TOLERANCE = 1e-09
INSTANCE_FILE_PATH = os.path.splitext(os.path.abspath(__file__))[0] + '.json'


class MachineElement:
    def __init__(self, environment, unit, carbon_boundary):
        self.environment = environment
        self.MachineUnitCode = unit['MachineUnitCode']
        self.resource = simpy.Resource(environment, capacity=unit['CapacityPerCycle'])
        self.carbon_boundary = carbon_boundary
        self.use_count_by_process = collections.Counter()
        self.on_since = None
        # ---------------- 생산성 요소: 켜진 시간(h, 하나라도 가공 중인 시간), 가공 횟수
        self.on_hours = 0.0
        self.cycle_count = 0

    def start_use(self, ProcessCode):
        if not +self.use_count_by_process:
            self.on_since = self.environment.now
        self.use_count_by_process[ProcessCode] += 1

    def end_use(self, ProcessCode):
        self.use_count_by_process[ProcessCode] -= 1
        self.cycle_count += 1
        if not +self.use_count_by_process:
            self.add_on_time(ProcessCode)

    def add_on_time(self, ProcessCode):
        hours = (self.environment.now - self.on_since) / SECONDS_PER_HOUR
        self.on_hours += hours
        self.on_since = self.environment.now
        if self.carbon_boundary is not None and self.carbon_boundary.activity_basis == 'machine_on_time':
            self.carbon_boundary.add_operating_time(ProcessCode, hours)

    # 실행이 끝날 때 켜져 있는 설비의 시간을 마저 더함
    def close_on_time(self):
        in_use = +self.use_count_by_process
        if in_use:
            self.add_on_time(next(iter(in_use)))


class WorkerGroupElement:
    def __init__(self, environment, group, schedule):
        self.environment = environment
        self.WorkerGroupCode = group['WorkerGroupCode']
        self.schedule = schedule
        self.workers = [{'WorkerUnitCode': code, 'ProcessCode': None, 'job_count': 0, 'busy_since': None, 'busy_hours': 0.0}
                        for code in group['WorkerUnitCodes']]
        self.waiting_jobs_by_process = collections.defaultdict(collections.deque)
        self.wake_event = environment.event()
        self.busy_worker_count = 0
        self.busy_since = None
        # ---------------- 생산성 요소: 그룹 작업 시간(h, 한 명이라도 작업 중인 시간), 작업자별 작업 시간(h, 작업이 하나라도 있는 시간), 작업 수
        self.busy_hours = 0.0
        self.job_count = 0

    def has_waiting_jobs(self):
        return any(self.waiting_jobs_by_process.values())

    # 같은 공정을 맡고 있고 자리가 남은 작업자 → 쉬는 작업자
    def available_worker(self, ProcessCode, UnitsPerWorker):
        for worker in self.workers:
            if worker['job_count'] and worker['ProcessCode'] == ProcessCode and worker['job_count'] < UnitsPerWorker:
                return worker
        for worker in self.workers:
            if not worker['job_count']:
                return worker
        return None

    def start_job(self, worker, ProcessCode):
        if not worker['job_count']:
            worker['ProcessCode'] = ProcessCode
            worker['busy_since'] = self.environment.now
            if not self.busy_worker_count:
                self.busy_since = self.environment.now
            self.busy_worker_count += 1
        worker['job_count'] += 1

    def end_job(self, worker):
        worker['job_count'] -= 1
        self.job_count += 1
        if not worker['job_count']:
            self.close_worker_busy_time(worker)

    def close_worker_busy_time(self, worker):
        worker['busy_hours'] += (self.environment.now - worker['busy_since']) / SECONDS_PER_HOUR
        worker['ProcessCode'] = None
        self.busy_worker_count -= 1
        if not self.busy_worker_count:
            self.busy_hours += (self.environment.now - self.busy_since) / SECONDS_PER_HOUR

    # 실행이 끝날 때 작업 중인 시간을 마저 더함
    def close_busy_time(self):
        for worker in self.workers:
            if worker['job_count']:
                worker['busy_hours'] += (self.environment.now - worker['busy_since']) / SECONDS_PER_HOUR
                worker['busy_since'] = self.environment.now
        if self.busy_worker_count:
            self.busy_hours += (self.environment.now - self.busy_since) / SECONDS_PER_HOUR
            self.busy_since = self.environment.now


class CarbonElement:
    def __init__(self, element):
        self.category = element['category']
        self.ClassificationType = element['ClassificationType']
        self.AmountUnit = element['AmountUnit']
        self.RefEmissionFactor = element['RefEmissionFactor'] or 0.0
        self.activity_rate_by_process_code = element['activity_rate_by_process_code']
        self.amount_path = element['amount_path']
        self.is_given_amount = element['given_Amount'] is not None
        self.Amount = element['given_Amount'] or 0.0

    def add_activity(self, ProcessCode, hours):
        activity_rate = self.activity_rate_by_process_code.get(ProcessCode)
        if activity_rate is not None and not self.is_given_amount:
            self.Amount += activity_rate['rate'] * hours

    def ContributionCO2eq(self):
        return self.Amount * self.RefEmissionFactor


class CarbonBoundary:
    def __init__(self, boundary):
        self.mcf_submodel_id = boundary['mcf_submodel_id']
        self.activity_basis = boundary['activity_basis']
        self.OperatingTime = 0.0
        self.carbon_elements = [CarbonElement(element) for element in boundary['carbon_elements']]

    def record_process_execution(self, ProcessCode, hours):
        if self.activity_basis == 'process_time':
            self.add_operating_time(ProcessCode, hours)

    def add_operating_time(self, ProcessCode, hours):
        self.OperatingTime += hours
        for carbon_element in self.carbon_elements:
            carbon_element.add_activity(ProcessCode, hours)

    def SumCO2eq(self):
        return sum(carbon_element.ContributionCO2eq() for carbon_element in self.carbon_elements)

    def result(self):
        return {
            'OperatingTime': self.OperatingTime,
            'carbon_elements': [{'category': element.category, 'ClassificationType': element.ClassificationType,
                                 'Amount': element.Amount, 'AmountUnit': element.AmountUnit,
                                 'ContributionCO2eq': element.ContributionCO2eq(), 'amount_path': element.amount_path}
                                for element in self.carbon_elements],
            'SumCO2eq': self.SumCO2eq(),
        }


class SimulationModel:
    def __init__(self, instance, seed, target_quantity_by_product):
        self.instance = instance
        self.environment = simpy.Environment()
        self.random = random.Random(seed)
        self.event_random = random.Random(f'{seed}-event')
        self.target_quantity_by_product = target_quantity_by_product
        self.stop_event = self.environment.event()
        self.build_elements()
        self.build_routes()

    # ---------------------------------------------------------------- 준비: 요소 만들기, 흐름표·이벤트 대상표
    def build_elements(self):
        instance = self.instance
        self.carbon_boundaries = {key: CarbonBoundary(boundary) for key, boundary in instance['CarbonBoundaries'].items()}
        self.carbon_boundary_by_process = {}
        boundary_by_machine = {}
        for key, boundary in instance['CarbonBoundaries'].items():
            for ProcessCode in boundary['ProcessCodes']:
                self.carbon_boundary_by_process[ProcessCode] = self.carbon_boundaries[key]
            if boundary['MachineUnitCode']:
                boundary_by_machine[boundary['MachineUnitCode']] = self.carbon_boundaries[key]
        self.machines = {code: MachineElement(self.environment, unit, boundary_by_machine.get(code))
                         for code, unit in instance['MachineUnits'].items()}
        self.worker_groups = {code: WorkerGroupElement(self.environment, group, instance['WorkSchedules'][group['WorkScheduleCode']])
                              for code, group in instance['WorkerGroups'].items()}
        self.self_produced_item_codes = self.module_produced_item_codes()
        self.stock = collections.Counter()
        self.stock_event = self.environment.event()
        self.purchased_item_use = collections.Counter()
        self.ready_order_counter = itertools.count()
        # ---------------- 생산성 요소: 제품별 생산량·완료 시각(목표 수량 도달, 한 대마다), 공정별 완료 수, 불량·수리 수
        self.production_quantity_by_product = collections.Counter()
        self.completion_time_by_product = {}
        self.completion_times_by_product = collections.defaultdict(list)
        self.completed_count_by_process = collections.Counter()
        self.defect_count_by_process = collections.Counter()
        self.repair_count_by_product = collections.Counter()
        self.stuck_unit_count = 0

    def build_routes(self):
        self.flows_from = collections.defaultdict(list)
        for flow in self.instance['ProcessFlows']:
            self.flows_from[flow['FromProcessCode']].append(flow)
        self.events_by_kind_and_target = collections.defaultdict(list)
        self.remaining_until_event = {}
        for event in self.instance['Events']:
            for target in {event['TargetProcessCode'], event['TargetUnitResourceCode']} - {None}:
                self.events_by_kind_and_target[(event['DistributionUnit'], target)].append(event)
            self.remaining_until_event[event['EventCode']] = self.sample_event_interval(event)

    # ---------------------------------------------------------------- 품목(진입 조건 ItemAvailable): 자체 생산 품목은 재고에서 꺼냄(모자라면 착수 불가), 구매 품목은 사용 수만 기록
    def item_conditions(self, ProcessCode):
        groups = self.instance['Processes'][ProcessCode]['EntryConditions']
        return [condition for condition in groups[0] if condition['ConditionType'] == 'ItemAvailable'] if groups else []

    def are_input_items_available(self, ProcessCode):
        for condition in self.item_conditions(ProcessCode):
            if condition['ItemCode'] in self.self_produced_item_codes and self.stock[condition['ItemCode']] < condition['Quantity']:
                return False
        return True

    def consume_input_items(self, ProcessCode):
        for condition in self.item_conditions(ProcessCode):
            if condition['ItemCode'] in self.self_produced_item_codes:
                self.stock[condition['ItemCode']] -= condition['Quantity']
            else:
                self.purchased_item_use[condition['ItemCode']] += condition['Quantity']

    def add_stock(self, ItemCode, quantity):
        self.stock[ItemCode] += quantity
        stock_event, self.stock_event = self.stock_event, self.environment.event()
        stock_event.succeed()

    # ---------------------------------------------------------------- 리소스 ① 근무시간: 근무표의 시작~휴식 시작, 휴식 끝~종료 구간. 근무표가 없으면 제한 없음
    def work_windows(self, schedule):
        start, end = schedule['WorkStartTime'], schedule['WorkEndTime']
        if schedule['BreakStartTime'] is None or not schedule['BreakDurationTime']:
            return [(start, end)]
        return [(start, schedule['BreakStartTime']), (schedule['BreakStartTime'] + schedule['BreakDurationTime'], end)]

    def current_window_end(self, schedule):
        if schedule is None:
            return math.inf
        time_of_day = self.environment.now % SECONDS_PER_DAY
        for window_start, window_end in self.work_windows(schedule):
            if window_start - TIME_TOLERANCE <= time_of_day < window_end - TIME_TOLERANCE:
                return self.environment.now + window_end - time_of_day
        return None

    def seconds_until_next_window(self, schedule):
        time_of_day = self.environment.now % SECONDS_PER_DAY
        for window_start, _ in self.work_windows(schedule):
            if window_start > time_of_day + TIME_TOLERANCE:
                return window_start - time_of_day
        return SECONDS_PER_DAY - time_of_day + self.work_windows(schedule)[0][0]

    def wait_for_work_time(self, schedule, duration=0.0):
        while True:
            window_end = self.current_window_end(schedule)
            if window_end is not None and window_end - self.environment.now + TIME_TOLERANCE >= duration:
                return
            yield self.environment.timeout(self.seconds_until_next_window(schedule))

    def schedule_of(self, WorkScheduleCode):
        return self.instance['WorkSchedules'].get(WorkScheduleCode) if WorkScheduleCode else None

    # ---------------------------------------------------------------- 리소스 ② 설비 고르기: 레시피 설비(KG Process —Require→ Machine) 가운데 대기가 가장 적은 설비
    def machine_for_recipe(self, ProcessCode, recipe):
        if not self.instance['Processes'][ProcessCode]['RequiresMachine']:
            return None
        machines = [self.machines[code] for code in recipe['MachineUnitCodes']]
        if not machines:
            return None
        return min(machines, key=lambda machine: len(machine.resource.queue) + machine.resource.count)

    # ---------------------------------------------------------------- 리소스 ③ 작업자 그룹 작업 배정(진입 조건 ResourceAvailable·ItemAvailable)
    def wake_worker_group(self, group):
        if not group.wake_event.triggered:
            group.wake_event.succeed()

    def dispatch_worker_group(self, group):
        while True:
            if not group.has_waiting_jobs():
                group.wake_event = self.environment.event()
                yield group.wake_event
                continue
            yield from self.wait_for_work_time(group.schedule)
            candidate_jobs = self.candidate_jobs(group)
            if not candidate_jobs:
                group.wake_event = self.environment.event()
                waits = [group.wake_event, self.stock_event,
                         self.environment.timeout(self.seconds_until_next_window(group.schedule))]
                yield simpy.AnyOf(self.environment, waits)
                continue
            job = self.select_job(group, candidate_jobs)
            worker = group.available_worker(job['ProcessCode'], self.units_per_worker(job['ProcessCode']))
            group.waiting_jobs_by_process[job['ProcessCode']].remove(job)
            self.consume_input_items(job['ProcessCode'])
            group.start_job(worker, job['ProcessCode'])
            self.environment.process(self.run_worker_job(group, worker, job))

    def units_per_worker(self, ProcessCode):
        return self.instance['Processes'][ProcessCode]['UnitsPerWorker']

    def candidate_jobs(self, group):
        window_end = self.current_window_end(group.schedule)
        if window_end is None:
            return []
        remaining_time = window_end - self.environment.now + TIME_TOLERANCE
        candidates = []
        for ProcessCode, jobs in group.waiting_jobs_by_process.items():
            if not jobs or jobs[0]['recipe']['CycleTime'] > remaining_time:
                continue
            if group.available_worker(ProcessCode, self.units_per_worker(ProcessCode)) is None:
                continue
            if self.are_input_items_available(ProcessCode):
                candidates.append(jobs[0])
        return candidates

    # 강화학습·시나리오가 재정의하는 의사결정 지점: 기본은 먼저 대기에 들어온 작업
    def select_job(self, group, candidate_jobs):
        return min(candidate_jobs, key=lambda job: job['ready_order'])

    def run_worker_job(self, group, worker, job):
        ProcessCode, recipe = job['ProcessCode'], job['recipe']
        machine = self.machine_for_recipe(ProcessCode, recipe)
        machine_request = None
        if machine is not None:
            machine_request = machine.resource.request()
            yield machine_request
            machine.start_use(ProcessCode)
        start_time = self.environment.now
        yield self.environment.timeout(recipe['CycleTime'])
        if machine is not None:
            machine.end_use(ProcessCode)
            machine.resource.release(machine_request)
        group.end_job(worker)
        self.record_process_execution(ProcessCode, self.environment.now - start_time)
        job['finished'].succeed()
        self.wake_worker_group(group)

    # ---------------------------------------------------------------- 시뮬레이션 ① 실행 시작과 종료: 목표 수량만큼 제품 투입, 작업자 그룹 배정, 모듈 프로세스, 시나리오 프로세스
    def start(self):
        for ProductCode, quantity in self.target_quantity_by_product.items():
            for _ in range(quantity):
                self.environment.process(self.produce_unit(ProductCode))
        for group in self.worker_groups.values():
            self.environment.process(self.dispatch_worker_group(group))
        self.start_module_processes()
        self.start_scenario_processes()
        self.environment.process(self.stop_at_run_length())

    # 시나리오 모듈이 SimPy 프로세스를 더 붙이는 자리(작업자 재배치 등)
    def start_scenario_processes(self):
        pass

    def is_target_reached(self):
        for ProductCode, quantity in self.target_quantity_by_product.items():
            if self.production_quantity_by_product[ProductCode] < quantity:
                return False
        return self.is_module_finished()

    def stop_if_target_reached(self):
        if self.is_target_reached() and not self.stop_event.triggered:
            self.stop_event.succeed()

    def stop_at_run_length(self):
        yield self.environment.timeout(self.instance['SimulationConfiguration']['RunLength'])
        if not self.stop_event.triggered:
            self.stop_event.succeed()

    def run(self):
        self.start()
        self.environment.run(until=self.stop_event)
        for machine in self.machines.values():
            machine.close_on_time()
        for group in self.worker_groups.values():
            group.close_busy_time()
        self.close_module_records()
        return self.result()

    # ---------------------------------------------------------------- 시뮬레이션 ② 레시피 실행: 작업자 공정은 작업자 그룹 대기열로, 그 밖은 설비 확보(없으면 시간만)
    def execute_recipe(self, ProcessCode, recipe):
        if self.instance['Processes'][ProcessCode]['RequiresWorker'] and recipe['WorkerGroupCode']:
            finished = self.environment.event()
            group = self.worker_groups[recipe['WorkerGroupCode']]
            group.waiting_jobs_by_process[ProcessCode].append(
                {'ProcessCode': ProcessCode, 'recipe': recipe, 'finished': finished, 'ready_time': self.environment.now,
                 'ready_order': next(self.ready_order_counter)})
            self.wake_worker_group(group)
            yield finished
            return
        yield from self.occupy_machine_and_process(ProcessCode, recipe)

    def occupy_machine_and_process(self, ProcessCode, recipe):
        machine = self.machine_for_recipe(ProcessCode, recipe)
        request = None
        if machine is not None:
            request = machine.resource.request()
            yield request
            machine.start_use(ProcessCode)
        self.consume_input_items(ProcessCode)
        yield self.environment.timeout(recipe['CycleTime'])
        if machine is not None:
            machine.end_use(ProcessCode)
            machine.resource.release(request)
        self.record_process_execution(ProcessCode, recipe['CycleTime'])

    def record_process_execution(self, ProcessCode, duration):
        self.completed_count_by_process[ProcessCode] += 1
        boundary = self.carbon_boundary_by_process.get(ProcessCode)
        if boundary is not None:
            boundary.record_process_execution(ProcessCode, duration / SECONDS_PER_HOUR)

    # ---------------------------------------------------------------- 시뮬레이션 ③ 공정 흐름·진입 조건: 제품 한 대가 진입 조건(선행 공정)을 채운 공정 실행 → 흐름에 따라 다음 공정 → 마지막 공정에서 생산량 기록
    def produce_unit(self, ProductCode):
        product = self.instance['Products'][ProductCode]
        unit = {'ProductCode': ProductCode, 'OutputItemCode': None, 'output_code_by_process': {},
                'completed': set(), 'running': set(), 'arrived_from': collections.defaultdict(set)}
        running_events = []
        while not set(product['final_process_codes']) & unit['completed']:
            for ProcessCode in self.ready_process_codes(unit, product):
                unit['running'].add(ProcessCode)
                running_events.append(self.environment.process(self.run_process_of_unit(unit, ProcessCode)))
            running_events = [event for event in running_events if not event.triggered]
            if not running_events:
                self.stuck_unit_count += 1
                return
            yield simpy.AnyOf(self.environment, running_events)
        self.production_quantity_by_product[ProductCode] += 1
        self.completion_times_by_product[ProductCode].append(self.environment.now)
        if self.production_quantity_by_product[ProductCode] == self.target_quantity_by_product.get(ProductCode):
            self.completion_time_by_product[ProductCode] = self.environment.now
        self.stop_if_target_reached()

    # 진입 조건 OR 묶음 가운데 하나의 선행 공정 완료 조건을 모두 채운 공정. 투입 품목·자원 조건은 작업 배정 때 확인
    def ready_process_codes(self, unit, product):
        ready = []
        for ProcessCode in product['process_codes']:
            if ProcessCode in unit['completed'] or ProcessCode in unit['running']:
                continue
            if ProcessCode not in product['start_process_codes'] and not unit['arrived_from'][ProcessCode]:
                continue
            for group in self.instance['Processes'][ProcessCode]['EntryConditions']:
                if all(self.is_process_condition_met(unit, ProcessCode, condition) for condition in group):
                    ready.append(ProcessCode)
                    break
        return ready

    def is_process_condition_met(self, unit, ProcessCode, condition):
        if condition['ConditionType'] != 'ProcessCompleted':
            return True
        return condition['ProcessCode'] in unit['arrived_from'][ProcessCode]

    def run_process_of_unit(self, unit, ProcessCode):
        recipe = self.instance['Processes'][ProcessCode]['Recipes'][0]
        input_codes = self.input_codes_of_unit(unit, ProcessCode)
        yield from self.execute_recipe(ProcessCode, recipe)
        is_final = ProcessCode in self.instance['Products'][unit['ProductCode']]['final_process_codes']
        OutputItemCode = self.output_item_code(ProcessCode, input_codes, unit['ProductCode'] if is_final else None)
        self.set_unit_output_code(unit, ProcessCode, OutputItemCode)
        self.record_output(ProcessCode, OutputItemCode, recipe['CycleTime'])
        yield from self.handle_defect_events(unit, ProcessCode)
        unit['running'].discard(ProcessCode)
        unit['completed'].add(ProcessCode)
        self.release_next_processes(unit, ProcessCode)

    # 분기: 이 제품의 공정으로 가는 흐름만. 확률 합이 1인 여러 흐름은 하나를 고르고, 그 밖은 흐름마다 확률로
    def release_next_processes(self, unit, ProcessCode):
        product_process_codes = self.instance['Products'][unit['ProductCode']]['process_codes']
        flows = [flow for flow in self.flows_from[ProcessCode] if flow['ToProcessCode'] in product_process_codes]
        probability_sum = sum(flow['BranchProbability'] for flow in flows)
        if len(flows) > 1 and abs(probability_sum - 1.0) < BRANCH_PROBABILITY_TOLERANCE:
            flows = self.random.choices(flows, weights=[flow['BranchProbability'] for flow in flows])
        else:
            flows = [flow for flow in flows if self.random.random() < flow['BranchProbability']]
        for flow in flows:
            unit['arrived_from'][flow['ToProcessCode']].add(ProcessCode)

    # ---------------------------------------------------------------- 시뮬레이션 ③ 산출 품목 코드(템플릿 규칙): 완제품·부품은 ItemCode, 그 밖은 '{ProcessCode}[정렬한 투입 코드를 +로 연결]'
    # 투입 코드 = 레시피 투입 품목 코드만. 앞 공정 중간재는 넣지 않음(11-18 시험). 규칙을 바꿀 때 이 두 메서드를 재정의
    def output_item_code(self, ProcessCode, input_codes, ItemCode=None):
        if ItemCode is not None:
            return ItemCode
        return f"{ProcessCode}[{'+'.join(sorted(input_codes))}]"

    def input_codes_of_unit(self, unit, ProcessCode):
        return [condition['ItemCode'] for condition in self.item_conditions(ProcessCode)]

    def set_unit_output_code(self, unit, ProcessCode, OutputItemCode):
        unit['output_code_by_process'][ProcessCode] = OutputItemCode
        unit['OutputItemCode'] = OutputItemCode

    # ---------------------------------------------------------------- 시뮬레이션 ④ 이벤트: 분포에서 뽑은 횟수(산출 수량·품목 변경 횟수)마다 발생
    def sample_event_interval(self, event):
        mean = event['Parameters'][0]
        if event['DistributionType'] == 'Exponential':
            return self.event_random.expovariate(1.0 / mean)
        return mean

    def is_event_due(self, event):
        self.remaining_until_event[event['EventCode']] -= 1
        if self.remaining_until_event[event['EventCode']] > 0:
            return False
        self.remaining_until_event[event['EventCode']] += self.sample_event_interval(event)
        return True

    # 불량: 대상 공정의 산출 수량 간격마다 → 처리 공정(HandlingProcess)을 거친 뒤 계속. 처리 공정은 ProcessFlows에 없어 단위의 산출 코드는 들어온 중간재 코드를 그대로 둠
    # 처리 공정 MCF에는 처리 공정 레시피 규칙의 산출 코드로 기록
    def handle_defect_events(self, unit, ProcessCode):
        for event in self.events_by_kind_and_target.get(('OutputItem', ProcessCode), []):
            if not self.is_event_due(event):
                continue
            self.defect_count_by_process[ProcessCode] += 1
            HandlingProcessCode = event['HandlingProcessCode']
            handling_recipe = self.instance['Processes'][HandlingProcessCode]['Recipes'][0]
            yield from self.execute_recipe(HandlingProcessCode, handling_recipe)
            self.record_output(HandlingProcessCode, self.output_item_code(HandlingProcessCode, self.input_codes_of_unit(unit, HandlingProcessCode)),
                               handling_recipe['CycleTime'])
            self.repair_count_by_product[unit['ProductCode']] += 1

    # ---------------------------------------------------------------- 결과: 생산성 요소와 탄소 요소
    def result(self):
        return {
            'end_time': self.environment.now,
            'target_reached': self.is_target_reached(),
            'productivity': {
                'production_quantity_by_product': dict(self.production_quantity_by_product),
                'completion_time_by_product': self.completion_time_by_product,
                'stuck_unit_count': self.stuck_unit_count,
                'defect_count_by_process': dict(self.defect_count_by_process),
                'repair_count_by_product': dict(self.repair_count_by_product),
                'worker_group_busy_hours': {code: group.busy_hours for code, group in self.worker_groups.items()},
                'worker_busy_hours': {worker['WorkerUnitCode']: worker['busy_hours']
                                      for group in self.worker_groups.values() for worker in group.workers},
                'worker_group_job_count': {code: group.job_count for code, group in self.worker_groups.items()},
                'machine_on_hours': {code: machine.on_hours for code, machine in self.machines.items()},
                'machine_cycle_count': {code: machine.cycle_count for code, machine in self.machines.items()},
                'completion_times_by_product': dict(self.completion_times_by_product),
            },
            'carbon': {
                'SumCO2eq_total': sum(boundary.SumCO2eq() for boundary in self.carbon_boundaries.values()),
                'boundaries': {key: boundary.result() for key, boundary in self.carbon_boundaries.items()},
            },
        }

    # ---------------------------------------------------------------- 모듈(SMT 라인, 기저부하, MCF 계산 등)이 재정의하는 자리: 공장에서 만들어 재고로 쓰는 품목, 모듈 SimPy 프로세스, 모듈 종료 여부, 실행 끝 기록 마감, 산출물 기록
    # 모듈은 super()를 불러 다른 모듈과 함께 동작
    def module_produced_item_codes(self):
        return set()

    def start_module_processes(self):
        pass

    def is_module_finished(self):
        return True

    def close_module_records(self):
        pass

    # 공정 실행 1회의 산출물(산출 품목 코드, 처리 시간, 산출 수량). 조립 공정·처리 공정(RMA)·SMT 단계가 부름
    def record_output(self, ProcessCode, OutputItemCode, duration, output_quantity=1):
        pass


def load_instance(instance_file_path):
    with open(instance_file_path, encoding='utf-8') as instance_file:
        return json.load(instance_file)


def run_replications(model_class, instance, replications, seed, target_quantity_by_product):
    results = []
    for replication in range(replications):
        model = model_class(instance, seed + replication, target_quantity_by_product)
        results.append(model.run())
    return results


def print_result_summary(results):
    for replication, result in enumerate(results):
        productivity = result['productivity']
        print(f"[{replication}] 종료 {result['end_time']:,.0f} s | 목표 달성 {result['target_reached']} | "
              f"생산량 {productivity['production_quantity_by_product']} | "
              f"탄소배출량 {result['carbon']['SumCO2eq_total']:,.4f} kgCO2eq")


def main(model_class=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--instance', default=INSTANCE_FILE_PATH)
    parser.add_argument('--replications', type=int)
    parser.add_argument('--seed', type=int, default=0)
    parser.add_argument('--quantity', type=int, required=True, help='제품별 목표 수량(템플릿에 수요 칸이 없어 실행마다 입력)')
    parser.add_argument('--output', default=os.path.splitext(INSTANCE_FILE_PATH)[0] + '_result.json')
    arguments = parser.parse_args()
    instance = load_instance(arguments.instance)
    replications = arguments.replications or instance['SimulationConfiguration']['Replications']
    target_quantity_by_product = {ProductCode: arguments.quantity for ProductCode in instance['Products']}
    results = run_replications(model_class or DEFAULT_MODEL_CLASS, instance, replications, arguments.seed,
                               target_quantity_by_product)
    print_result_summary(results)
    with open(arguments.output, 'w', encoding='utf-8') as result_file:
        json.dump(results, result_file, ensure_ascii=False, indent=1, default=str)


class SmtLineModel(SimulationModel):
    def build_elements(self):
        super().build_elements()
        self.smt_line_runs = []
        # ---------------- 생산성 요소: 라인·품목별 생산 PCB 수, 라인 완료 시각, 멈춤 이벤트 횟수·시간(h)
        self.produced_pcb_count_by_line_item = collections.Counter()
        self.completion_time_by_line = {}
        self.stop_count_by_event = collections.Counter()
        self.stop_hours_by_event = collections.Counter()

    def module_produced_item_codes(self):
        smt_item_codes = {code for line in self.instance['SmtLines'].values() for code in line['produced_item_codes']}
        return super().module_produced_item_codes() | smt_item_codes

    def start_module_processes(self):
        super().start_module_processes()
        for line_code, plan in self.plan_smt_lines().items():
            self.smt_line_runs.append(self.environment.process(self.run_smt_line(line_code, plan)))

    def is_module_finished(self):
        return super().is_module_finished() and all(line_run.triggered for line_run in self.smt_line_runs)

    # 목표 수량으로 PCB 품목별 필요 수량
    def required_quantity_by_item(self):
        required = collections.Counter()
        for ProductCode, quantity in self.target_quantity_by_product.items():
            for ProcessCode in self.instance['Products'][ProductCode]['process_codes']:
                for condition in self.item_conditions(ProcessCode):
                    if condition['ItemCode'] in self.self_produced_item_codes:
                        required[condition['ItemCode']] += condition['Quantity'] * quantity
        return required

    # 품목을 코드 순으로 그 품목을 만드는 라인에 번갈아 배정(simulation_v2.1 규칙), 어레이 수 = 필요 수량 ÷ 어레이당 PCB 수 올림
    def plan_smt_lines(self):
        lines = self.instance['SmtLines']
        plans = {line_code: [] for line_code in lines}
        for item_index, (ItemCode, quantity) in enumerate(sorted(self.required_quantity_by_item().items())):
            line_codes = sorted(code for code, line in lines.items() if ItemCode in line['produced_item_codes'])
            line_code = line_codes[item_index % len(line_codes)]
            plans[line_code].append({'ItemCode': ItemCode,
                                     'array_count': math.ceil(quantity / lines[line_code]['pcb_count_per_array'])})
        return plans

    def run_smt_line(self, line_code, plan):
        line = self.instance['SmtLines'][line_code]
        schedule = self.schedule_of(line['WorkScheduleCode'])
        for item_index, planned_item in enumerate(plan):
            if item_index > 0:
                yield from self.handle_recipe_change_events(line, schedule)
            yield from self.wait_for_work_time(schedule)
            arrays = [self.environment.process(self.produce_pcb_array(line, planned_item['ItemCode']))
                      for _ in range(planned_item['array_count'])]
            yield simpy.AllOf(self.environment, arrays)
            pcb_count = planned_item['array_count'] * line['pcb_count_per_array']
            self.produced_pcb_count_by_line_item[(line_code, planned_item['ItemCode'])] += pcb_count
            self.add_stock(planned_item['ItemCode'], pcb_count)
        self.completion_time_by_line[line_code] = self.environment.now
        self.environment.process(self.stop_after_smt_line_end())

    def stop_after_smt_line_end(self):
        yield self.environment.timeout(0)
        self.stop_if_target_reached()

    # 어레이 1장이 단계 설비를 차례로 점유: 단계 CycleTime이 근무 구간 안에 끝날 때까지 기다린 뒤(simulation_v2.1 규칙) 다음 설비를 잡고 앞 설비를 놓음
    # 산출 품목 코드는 템플릿 규칙(단계 레시피 투입 품목, 마지막 단계는 PCB 품목 코드)
    def produce_pcb_array(self, line, ItemCode):
        schedule = self.schedule_of(line['WorkScheduleCode'])
        held = None
        for step_index, (ProcessCode, MachineUnitCode) in enumerate(zip(line['ProcessCodes'], line['MachineUnitCodes'])):
            recipe = self.instance['Processes'][ProcessCode]['Recipes'][0]
            input_codes = [condition['ItemCode'] for condition in self.item_conditions(ProcessCode)]
            machine = self.machines[MachineUnitCode]
            yield from self.wait_for_work_time(schedule, recipe['CycleTime'])
            request = machine.resource.request()
            yield request
            if held is not None:
                held['machine'].resource.release(held['request'])
            machine.start_use(ProcessCode)
            yield self.environment.timeout(recipe['CycleTime'])
            machine.end_use(ProcessCode)
            is_last = step_index == len(line['ProcessCodes']) - 1
            OutputItemCode = self.output_item_code(ProcessCode, input_codes, ItemCode if is_last else None)
            self.record_process_execution(ProcessCode, recipe['CycleTime'])
            self.record_output(ProcessCode, OutputItemCode, recipe['CycleTime'], line['pcb_count_per_array'])
            held = {'machine': machine, 'request': request}
        held['machine'].resource.release(held['request'])

    # 품목 변경 멈춤: 라인 생산 품목이 바뀔 때 라인 설비 대상 이벤트의 간격을 세고, 발생하면 근무 구간 안에서 멈춤 시간만큼 다음 품목 착수를 늦춤
    def handle_recipe_change_events(self, line, schedule):
        for MachineUnitCode in line['MachineUnitCodes']:
            for event in self.events_by_kind_and_target.get(('RecipeChange', MachineUnitCode), []):
                if not self.is_event_due(event):
                    continue
                yield from self.wait_for_work_time(schedule, event['Duration'])
                yield self.environment.timeout(event['Duration'])
                self.stop_count_by_event[event['EventCode']] += 1
                self.stop_hours_by_event[event['EventCode']] += event['Duration'] / SECONDS_PER_HOUR

    def result(self):
        result = super().result()
        result['smt_lines'] = {
            'produced_pcb_count_by_line_item': {f'{line}/{item}': count
                                                for (line, item), count in self.produced_pcb_count_by_line_item.items()},
            'completion_time_by_line': self.completion_time_by_line,
            'stop_count_by_event': dict(self.stop_count_by_event),
            'stop_hours_by_event': dict(self.stop_hours_by_event),
        }
        return result


class BaseLoadModel(SimulationModel):
    def start_module_processes(self):
        super().start_module_processes()
        base_load = self.instance['BaseLoad']
        self.base_load_boundary = self.carbon_boundaries[base_load['BoundaryCode']]
        self.base_load_schedule = self.schedule_of(base_load['WorkScheduleCode'])
        self.base_load_since = None
        if self.base_load_schedule is not None:
            self.environment.process(self.run_base_load())

    def run_base_load(self):
        WorkStartTime, WorkEndTime = self.base_load_schedule['WorkStartTime'], self.base_load_schedule['WorkEndTime']
        while True:
            time_of_day = self.environment.now % SECONDS_PER_DAY
            if time_of_day < WorkStartTime:
                yield self.environment.timeout(WorkStartTime - time_of_day)
            elif time_of_day < WorkEndTime:
                self.base_load_since = self.environment.now
                yield self.environment.timeout(WorkEndTime - time_of_day)
                self.add_base_load_time()
            else:
                yield self.environment.timeout(SECONDS_PER_DAY - time_of_day + WorkStartTime)

    def add_base_load_time(self):
        hours = (self.environment.now - self.base_load_since) / SECONDS_PER_HOUR
        self.base_load_boundary.add_operating_time(self.instance['BaseLoad']['BoundaryCode'], hours)
        self.base_load_since = None

    def close_module_records(self):
        super().close_module_records()
        if self.base_load_since is not None:
            self.add_base_load_time()


@dataclass
class Item:
    code: str
    use: dict              # 산출물 1단위당 투입량 {OutputItemCode: 수량}
    ef: float | None       # RefEmissionFactor (원소재)
    pcf_ref: str | None    # PCFEmission이 가리키는 CarbonFootprint id (구매 부품)


@dataclass
class Output:
    code: str
    unit: str
    quantity: float        # OutputItemQuantity
    period: float          # OperatingPeriod


@dataclass
class MCFData:
    boundary_id: str
    basis: str             # AllocationBasis
    items: list
    outputs: list
    ancillary_inputs: list  # [(사용량, 배출계수)]: AncillaryInputs 공통요소 줄 전부
    residuals: list        # [(발생량, 배출계수)]: Residuals 공통요소 줄 전부


@dataclass
class Product:
    code: str
    unit: str
    quantity: float
    factor: float          # AllocatedFactor
    allocated: float       # AllocatedCO2eq
    excluded: list         # 제외된 투입물 코드
    complete: bool
    contributions: list    # [(Tier, ProductCode, 제품 1단위당 kgCO2e)]

    @property
    def pcf(self):
        return self.allocated / self.quantity


@dataclass
class Result:
    input_material: float
    ancillary: float
    residual: float
    amounts: list          # 보조 투입물 줄별 사용량 (Amount에 기록)
    products: list

    @property
    def total(self):
        return self.input_material + self.ancillary + self.residual


def calc_mcf(data, registry, tier):
    """M2~M5. registry: {CarbonFootprint id: UpstreamPCF} (이전 Tier에서 생성했거나 공급사가 제공한 PCF)."""
    # M2 환산계수: {투입물 코드: (계수, 상류 PCF 또는 None)}. 찾지 못한 구매 부품은 포함되지 않음(제외)
    factors = {}
    for it in data.items:
        if it.ef is not None:
            factors[it.code] = (it.ef, None)
        elif it.pcf_ref in registry:
            factors[it.code] = (registry[it.pcf_ref].pcf, registry[it.pcf_ref])

    # M3 배출량
    material = {o.code: sum(it.use.get(o.code, 0.0) * o.quantity * factors[it.code][0]
                            for it in data.items if it.code in factors) for o in data.outputs}
    ancillary = sum(amount * ef for amount, ef in data.ancillary_inputs)
    residual = sum(amount * ef for amount, ef in data.residuals)

    # M4 할당 가중치: 산출물이 하나면 1, 여러 개면 AllocationBasis 기준
    weight = {o.code: 1.0 if len(data.outputs) == 1 else (o.period if data.basis == "OperatingTime" else o.quantity)
              for o in data.outputs}
    total_weight = sum(weight.values())

    products = []
    for o in data.outputs:
        factor = weight[o.code] / total_weight
        allocated = material[o.code] + (ancillary + residual) * factor
        used = [it for it in data.items if it.use.get(o.code, 0.0) > 0]
        linked = [(it, factors[it.code][1]) for it in used if it.code in factors and factors[it.code][1]]

        # M5 Tier별 기여: 이 경계의 배출(제품 1단위당) + 상류 기여 x 투입량
        upstream_part = sum(it.use[o.code] * up.pcf for it, up in linked)
        merged = {(tier, o.code): allocated / o.quantity - upstream_part}
        for it, up in linked:
            for t, code, value in up.contributions:
                merged[(t, code)] = merged.get((t, code), 0.0) + value * it.use[o.code]
        products.append(Product(
            o.code, o.unit, o.quantity, factor, allocated,
            excluded=[it.code for it in used if it.code not in factors],
            complete=all(it.code in factors for it in used) and all(up.complete for _, up in linked),
            contributions=sorted(((t, c, val) for (t, c), val in merged.items()), key=lambda x: (-x[0], x[1])),
        ))
    return Result(sum(material.values()), ancillary, residual, [amount for amount, _ in data.ancillary_inputs], products)


class McfModel(SimulationModel):
    def build_elements(self):
        super().build_elements()
        self.OutputItemQuantity_by_mcf = collections.defaultdict(collections.Counter)
        self.OperatingPeriod_by_mcf = collections.defaultdict(collections.Counter)

    def record_output(self, ProcessCode, OutputItemCode, duration, output_quantity=1):
        super().record_output(ProcessCode, OutputItemCode, duration, output_quantity)
        boundary = self.carbon_boundary_by_process.get(ProcessCode)
        if boundary is not None and boundary.mcf_submodel_id in self.instance['MCFCalculations']:
            self.OutputItemQuantity_by_mcf[boundary.mcf_submodel_id][OutputItemCode] += output_quantity
            self.OperatingPeriod_by_mcf[boundary.mcf_submodel_id][OutputItemCode] += duration / SECONDS_PER_HOUR

    # calc_mcf 입력: 실행에서 나온 산출물만(산출 0이면 PCF를 나눌 수 없음), 공통요소 줄은 AncillaryInputs·Residuals 아래 위치로 나눔
    def mcf_data(self, mcf_submodel_id, boundary):
        calculation = self.instance['MCFCalculations'][mcf_submodel_id]
        quantities, periods = self.OutputItemQuantity_by_mcf[mcf_submodel_id], self.OperatingPeriod_by_mcf[mcf_submodel_id]
        outputs = [Output(code, None, quantities[code], periods[code]) for code in calculation['output_codes'] if quantities[code] > 0]
        items = [Item(item['code'], item['use'], item['ef'], item['pcf_ref']) for item in calculation['items']]
        lines_under = lambda container: [(element.Amount, element.RefEmissionFactor) for element in boundary.carbon_elements
                                         if element.amount_path.startswith(container)]
        return MCFData(mcf_submodel_id, calculation['AllocationBasis'], items, outputs,
                       lines_under('AncillaryInputs'), lines_under('Residuals'))

    # registry: 상류 PCF 없음(공급사 PCF·이전 Tier 미연결), tier: 이 공장 한 단계라 1
    def result(self):
        result = super().result()
        for boundary_key, boundary in self.carbon_boundaries.items():
            if boundary.mcf_submodel_id not in self.instance['MCFCalculations']:
                continue
            calculation = self.instance['MCFCalculations'][boundary.mcf_submodel_id]
            quantities = self.OutputItemQuantity_by_mcf[boundary.mcf_submodel_id]
            calculated = calc_mcf(self.mcf_data(boundary.mcf_submodel_id, boundary), {}, 1)
            result['carbon']['boundaries'][boundary_key].update({
                'InputMaterialEmissions': calculated.input_material,
                'AncillaryInputEmissions': calculated.ancillary,
                'ResidualEmissions': calculated.residual,
                'SumCO2eq': calculated.total,
                'AllocationBasis': calculation['AllocationBasis'],
                'Allocation': [{'OutputItemCode': product.code, 'OutputItemQuantity': product.quantity,
                                'OperatingPeriod': self.OperatingPeriod_by_mcf[boundary.mcf_submodel_id][product.code],
                                'AllocatedFactor': product.factor, 'AllocatedCO2eq': product.allocated,
                                'PCF': product.pcf, 'ExcludedInputs': product.excluded}
                               for product in calculated.products],
                'not_produced_outputs': [code for code in calculation['output_codes'] if not quantities[code]],
                'outputs_not_in_mcf': sorted(set(quantities) - set(calculation['output_codes'])),
            })
        result['carbon']['SumCO2eq_total'] = sum(boundary['SumCO2eq'] for boundary in result['carbon']['boundaries'].values())
        return result


class InstanceModel(McfModel, BaseLoadModel, SmtLineModel):
    pass


DEFAULT_MODEL_CLASS = InstanceModel


if __name__ == '__main__':
    main()
