from discrete_event_simulation import warehouse
from discrete_event_simulation.simulation_model import SimulationModel


# ================================================ 작업자-공정 이벤트의 구분 값: 작업자가 공정을 시작할 때와 끝낼 때. 이벤트 데이터에 그대로 나감 ================================================
WORKER_PROCESS_EVENT_NAMES = {
    'start': '공정시작',
    'end': '공정종료',
}


# ================================================ 창고 이벤트의 이름: 자재 사용, SMT 라인이 만든 PCB 입고, 발주한 자재 입고 ================================================
WAREHOUSE_EVENT_NAMES = {
    'use': 'consume',
    'produce': 'produce',
    'arrive': 'arrive',
}


# ================================================ 불량 이벤트의 모델 값: SMT 라인이 만든 PCB 어레이의 불량은 제품 코드 대신 이 값 ================================================
PRODUCT_CODE_OF_PCB_DEFECT = 'PCB'


# ================================================ 무한재고 실행에서 창고 이벤트에 보이는 현재고의 출발값: 시뮬레이션은 재고를 차감하지 않으므로 이 값에서 사용량만큼 줄고 입고량만큼 느는 표시용 값을 냄 ================================================
PRESENT_STOCK_SHOWN_FIRST_WHEN_INFINITE_STOCK = 1000000.0


# ================================================ 기록용 창고: 엔진 창고에 자재 사용·PCB 입고·발주 자재 입고 이벤트 기록을 더함. 재고 계산은 엔진 창고 그대로 ================================================
class ApiRecordingWarehouse(warehouse.Warehouse):

    def __init__(self, co_managed_item_codes_by_category, self_managed_item_codes_by_category,
                 stock_policy_by_category, simpy_environment, infinite_stock):
        super().__init__(
            co_managed_item_codes_by_category, self_managed_item_codes_by_category,
            stock_policy_by_category)
        self.simpy_environment = simpy_environment
        self.infinite_stock = infinite_stock
        self.events = []
        self.shown_present_stock_by_item_code = {}
        self.item_code_by_stock_item_id = {}
        for stock_items in self.inventory.values():
            for item_code, stock_item in stock_items.items():
                self.item_code_by_stock_item_id[id(stock_item)] = item_code

    # ================================================ 창고 이벤트 하나 기록: 시각, 이름, 품목 코드, 수량(사용은 음수), 이벤트에 보이는 현재고 ================================================
    def present_stock_in_inventory(self, item_code):
        for stock_items in self.inventory.values():
            if item_code in stock_items:
                return float(stock_items[item_code].present_stock)
        return None

    def shown_present_stock(self, item_code, quantity_change):
        if not self.infinite_stock:
            return self.present_stock_in_inventory(item_code)
        shown_present_stock_before = self.shown_present_stock_by_item_code.get(
            item_code, PRESENT_STOCK_SHOWN_FIRST_WHEN_INFINITE_STOCK)
        self.shown_present_stock_by_item_code[item_code] = (
            shown_present_stock_before + quantity_change)
        return self.shown_present_stock_by_item_code[item_code]

    def record_warehouse_event(self, event_name, item_code, quantity_change):
        self.events.append({
            'sec': float(self.simpy_environment.now),
            'event': event_name,
            'item_code': item_code,
            'quantity': quantity_change,
            'present_stock': self.shown_present_stock(item_code, quantity_change),
        })

    # ================================================ 엔진 창고의 세 동작에 기록 더하기: 자재 사용, 발주 자재 입고, SMT 라인이 만든 PCB 입고 ================================================
    def use_items(self, InputItemCodeList, deducts_stock):
        newly_ordered_stock_items = super().use_items(InputItemCodeList, deducts_stock)
        for item_code, input_quantity in InputItemCodeList.items():
            self.record_warehouse_event(
                WAREHOUSE_EVENT_NAMES['use'], item_code, -float(input_quantity))
        return newly_ordered_stock_items

    def replenish_items(self, simpy_environment, replenishment_lead_time_sec,
                        ordered_stock_items, notify_stock_arrival):
        yield from super().replenish_items(
            simpy_environment, replenishment_lead_time_sec, ordered_stock_items,
            notify_stock_arrival)
        for stock_item in ordered_stock_items:
            arrived_quantity = warehouse.replenishment_quantity(
                stock_item.capacity_quantity, stock_item.replenishment_ratio)
            self.record_warehouse_event(
                WAREHOUSE_EVENT_NAMES['arrive'],
                self.item_code_by_stock_item_id[id(stock_item)], float(arrived_quantity))

    def record_produced_items(self, produced_quantity_by_item_code):
        for item_code, produced_quantity in produced_quantity_by_item_code.items():
            self.record_warehouse_event(
                WAREHOUSE_EVENT_NAMES['produce'], item_code, float(produced_quantity))


# ================================================ 기록용 시뮬레이션 모델: 엔진 시뮬레이션 모델에 API가 내보내는 기록(제품 단위 번호, 작업자-공정 이벤트, 진행 수량, 불량 이벤트, 창고 이벤트, 제품 완성 기록)을 더함. 생산 진행은 엔진 그대로 ================================================
class ApiRecordingSimulationModel(SimulationModel):

    # ================================================ 기록 속성 만들기: 엔진의 실행 상태 초기화 뒤 기록용 창고로 바꾸고 기록을 비움 ================================================
    def reset(self):
        super().reset()
        self.warehouse = ApiRecordingWarehouse(
            self.co_managed_item_codes_by_category, self.self_managed_item_codes_by_category,
            self.stock_policy_by_category, self.simpy_environment, self.infinite_stock)
        self.unit_number_by_unit_id = {}
        self.numbered_units = []
        self.worker_process_events = []
        self.defect_events = []
        self.product_completion_records = []
        self.started_unit_numbers = set()
        self.in_progress_quantity_by_product = {}
        for product in self.target_quantity_by_product:
            self.in_progress_quantity_by_product[product] = 0

    # ================================================ 제품 단위 번호: 제품 한 대(또는 PCB 어레이 한 장)가 작업자 공정·설비 사용·불량 판정에 처음 나타난 순서. 0부터 ================================================
    def unit_number_of(self, completed_process_codes):
        unit_id = id(completed_process_codes)
        if unit_id not in self.unit_number_by_unit_id:
            self.unit_number_by_unit_id[unit_id] = len(self.unit_number_by_unit_id)
            self.numbered_units.append(completed_process_codes)
        return self.unit_number_by_unit_id[unit_id]

    def on_machine_used(
            self, process, worker_group, start_sec, end_sec, completed_process_codes):
        self.unit_number_of(completed_process_codes)

    # ================================================ 작업자-공정 이벤트와 진행 수량: 작업자 공정 한 건의 시작과 종료를 기록. 제품의 첫 작업자 공정이 시작되면 진행 수량에 더하고 마지막 공정이 끝나면 뺌 ================================================
    def record_worker_process_event(
            self, event_name, product_code, worker_group, process_code, unit_number):
        self.worker_process_events.append({
            'sec': float(self.simpy_environment.now),
            'event': event_name,
            'product_code': product_code,
            'worker_group': worker_group,
            'process_code': process_code,
            'unit_number': unit_number,
        })

    def run_job_with_worker(self, worker_group, job, worker_request):
        process_code = job['process_code']
        product_code = self.product_of_job(job)
        unit_number = self.unit_number_of(job['completed_process_codes'])
        is_product = product_code in self.in_progress_quantity_by_product
        if is_product and unit_number not in self.started_unit_numbers:
            self.started_unit_numbers.add(unit_number)
            self.in_progress_quantity_by_product[product_code] += 1
        self.record_worker_process_event(
            WORKER_PROCESS_EVENT_NAMES['start'], product_code, worker_group, process_code,
            unit_number)
        yield from super().run_job_with_worker(worker_group, job, worker_request)
        self.record_worker_process_event(
            WORKER_PROCESS_EVENT_NAMES['end'], product_code, worker_group, process_code,
            unit_number)
        if is_product and self.simulation_processes.is_last_process(process_code):
            self.in_progress_quantity_by_product[product_code] -= 1

    # ================================================ 불량 이벤트: 불량으로 판정된 순간의 제품, 판정한 공정과 그 라인, 제품 단위 번호. 라인은 탄소배출량의 MCF 라인과 같은 기준(작업자 그룹, 작업자 그룹이 없는 SMT 단계는 SMT 라인) ================================================
    def on_defect(self, product, process_code, completed_process_codes):
        product_code = product
        if product in self.smt_production_plan:
            product_code = PRODUCT_CODE_OF_PCB_DEFECT
        self.defect_events.append({
            'sec': float(self.simpy_environment.now),
            'product_code': product_code,
            'worker_group': self.mcf_line_of_process(process_code),
            'process_code': process_code,
            'unit_number': self.unit_number_of(completed_process_codes),
        })

    # ================================================ 제품 완성 기록: 제품의 마지막 공정(완료 공정)이 끝나 생산량이 1 늘어난 순간의 시각, 제품, 그때까지 그 제품의 생산량(실행 시작부터). 박스 완료 이벤트가 이 기록을 읽음 ================================================
    def record_production(self, process_code):
        is_last_process = super().record_production(process_code)
        product_code = self.simulation_processes.processes[process_code].product_code
        if is_last_process and product_code in self.production_quantity_by_product:
            self.product_completion_records.append({
                'sec': float(self.simpy_environment.now),
                'product_code': product_code,
                'production_quantity': self.production_quantity_by_product[product_code],
            })
        return is_last_process
