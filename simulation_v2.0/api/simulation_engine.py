from gc import collect as collect_garbage
from operator import itemgetter
from pathlib import Path

import episode_procedure
import scenario_conditions
from aas_preprocessing.aas_reader import SECONDS_PER_DAY
from api.api_recording_simulation_model import ApiRecordingSimulationModel
from discrete_event_simulation.simulation_model import SimulationModel
from discrete_event_simulation.smt_line import SMT_MATERIAL_EVENT_RECORD_NAMES
from reinforcement_learning import action


# ================================================ 실행 방식별 조건: 실행 요청의 실행 방식마다 쓰는 시나리오(scenario_conditions.py의 이름)와 저장된 강화학습 모델 적용 여부. 적용하지 않으면 선입선출 ================================================
EXECUTION_METHOD_CONDITIONS = {
    'As-is': {'scenario': 'S1', 'reinforcement_learning_model_applied': False},
    '시나리오 1': {'scenario': 'S1', 'reinforcement_learning_model_applied': True},
    '시나리오 2': {'scenario': 'S1-1', 'reinforcement_learning_model_applied': True},
    '시나리오 3': {'scenario': 'S1-2', 'reinforcement_learning_model_applied': True},
}


# ================================================ 박스당 제품 수량: 출처는 작업표준서 BOM의 소요량(MODEL_C는 사진 라벨). AAS에 숫자로 된 요소가 없어 여기에 둠. 근거는 실행 검증/CPRO_사전검토_261112/box_quantity.md ================================================
PRODUCT_QUANTITY_PER_BOX_BY_PRODUCT = {
    'MODEL_A': 8,
    'MODEL_B': 10,
    'MODEL_C': 6,
}


# ================================================ 기본 PO: 실행 이력이 없을 때 쓰는 제품별 수량과 납기일(일). 옛 API(1.1.0)와 같은 값 ================================================
DEFAULT_PURCHASE_ORDER = {
    'target_quantity_per_product': 100,
    'due_day': 5,
}


# ================================================ 기준 정보를 읽는 시나리오: 제품 코드와 완료 공정코드(후속 공정이 없는 공정)를 이 시나리오의 AAS에서 읽음 ================================================
REFERENCE_INFORMATION_SCENARIO = 'S1'


# ================================================ 실시간 실행을 시작하는 시뮬레이션 시각(초): 08:55, 근무 시작 5분 전. 옛 API(1.1.0)와 같은 값 ================================================
REAL_TIME_START_SEC = 32100


# ================================================ 저장된 강화학습 모델을 적용할 때의 값: 평가 모드에서 쓰이지 않는 탐색 난수 seed, 착수 시점별 배출량 기록을 갱신하지 않음 ================================================
MODEL_APPLICATION_SETTINGS = {
    'exploration_seed': 0,
    'update_start_timing_emission_record': False,
}


# ================================================ API 실행에서 시나리오 조건에 덮어쓰는 값: SMT 필름 교체·Chip 보충 이벤트 적용(scenario_conditions.py의 기본은 꺼짐) ================================================
API_RUN_CONDITIONS = {
    'smt_material_events_applied': True,
}


# ================================================ SMT 필름 교체·Chip 보충 이벤트의 구분 값: Simulation AAS의 EventCode(왼쪽)를 내보내는 이름(오른쪽)으로. 설비 이벤트에는 이 이름 뒤에 시작·종료를 붙여 내보냄(필름교체시작, 필름교체종료, Chip보충시작, Chip보충종료). 텔로스 정의서 03_ANIMATION의 1행(필름 교체)과 2행(Chip 보충)에 대응 ================================================
SMT_MATERIAL_EVENT_NAMES = {
    'EV_FILM_CHANGE_Mounter_U1': '필름교체',
    'EV_CHIP_REFILL_Mounter_U1': 'Chip보충',
    'EV_FILM_CHANGE_Mounter_U2': '필름교체',
    'EV_CHIP_REFILL_Mounter_U2': 'Chip보충',
}
SMT_MATERIAL_EVENT_START_AND_END_NAMES = {
    SMT_MATERIAL_EVENT_RECORD_NAMES['start']: '시작',
    SMT_MATERIAL_EVENT_RECORD_NAMES['end']: '종료',
}


# ================================================ 이벤트 하나에 담는 항목: read_new_events가 돌려주는 다섯 목록의 원소가 갖는 키 ================================================
EVENT_KEYS = {
    'machine_events': ['sec', 'event', 'machine_name'],
    'worker_process_events': [
        'sec', 'event', 'product_code', 'worker_group', 'process_code', 'unit_number'],
    'warehouse_events': ['sec', 'event', 'item_code', 'quantity', 'present_stock'],
    'defect_events': ['sec', 'product_code', 'worker_group', 'process_code', 'unit_number'],
    'box_completion_events': ['sec', 'product_code', 'box_number', 'product_quantity_per_box'],
}


# ================================================ 시뮬레이션 실행기: 실행기 프로세스마다 하나. 불러 둔 강화학습 모델과 진행 중인 에피소드를 갖고 서버 계층이 부르는 일곱 가지 일을 함 ================================================
class SimulationRunner:

    def __init__(self):
        self.model_file_path = None
        self.aas_data_directory = None
        self.loaded_model_by_scenario = {}
        self.episode = None
        self.read_event_count = {}
        self.read_smt_material_event_record_count = 0
        self.read_product_completion_record_count = 0

    # ================================================ 실행기 준비: 모델 파일과 AAS 폴더 위치를 보관하고, 강화학습 모델을 적용하는 시나리오마다 저장된 모델을 한 번 불러 둠 ================================================
    def conditions_of_scenario(self, scenario):
        conditions = scenario_conditions.conditions_of_scenario(scenario)
        aas_folder_name = Path(conditions['aas_directory']).name
        conditions['aas_directory'] = str(Path(self.aas_data_directory) / aas_folder_name)
        return conditions

    def prepare(self, model_file_path, aas_data_directory):
        self.model_file_path = model_file_path
        self.aas_data_directory = aas_data_directory
        for method_conditions in EXECUTION_METHOD_CONDITIONS.values():
            scenario = method_conditions['scenario']
            is_loaded = scenario in self.loaded_model_by_scenario
            if method_conditions['reinforcement_learning_model_applied'] and not is_loaded:
                self.loaded_model_by_scenario[scenario] = (
                    episode_procedure.load_reinforcement_learning_model(
                        model_file_path, self.conditions_of_scenario(scenario)))

    # ================================================ 기준 정보 읽기: AAS의 제품 코드, 기본 PO, 제품마다 후속 공정이 없는 공정 하나(완료 공정코드), 박스당 제품 수량 ================================================
    def read_reference_information(self):
        conditions = self.conditions_of_scenario(REFERENCE_INFORMATION_SCENARIO)
        no_simulation_seed = None
        episode = episode_procedure.EpisodeProcedure(
            conditions, no_simulation_seed, SimulationModel)
        episode.generate_simulation_model()
        simulation_model = episode.simulation_model
        product_codes = list(simulation_model.target_quantity_by_product)
        default_target_quantity_by_product = {}
        default_due_day_by_product = {}
        completion_process_code_by_product = {}
        for product_code in product_codes:
            default_target_quantity_by_product[product_code] = (
                DEFAULT_PURCHASE_ORDER['target_quantity_per_product'])
            default_due_day_by_product[product_code] = DEFAULT_PURCHASE_ORDER['due_day']
            last_process_codes = sorted(simulation_model.list_last_process_codes(product_code))
            if len(last_process_codes) != 1:
                raise ValueError(
                    f'제품 {product_code}: 후속 공정이 없는 공정이 하나가 아님 {last_process_codes}')
            completion_process_code_by_product[product_code] = last_process_codes[0]
        return {
            'product_codes': product_codes,
            'default_target_quantity_by_product': default_target_quantity_by_product,
            'default_due_day_by_product': default_due_day_by_product,
            'completion_process_code_by_product': completion_process_code_by_product,
            'product_quantity_per_box_by_product': dict(PRODUCT_QUANTITY_PER_BOX_BY_PRODUCT),
        }

    # ================================================ 시뮬레이션 시작: 실행 방식의 시나리오 조건에 요청값(무한가동 여부, 무한가동이 아니면 제품별 수량·납기일, 기간)을 넣어 기록용 시뮬레이션 모델 생성 → 강화학습 모델 연결(As-is 제외) → 생산 시작 → 실시간 실행 시작 시각까지 진행 → 확인용 불량률 적용. 시작한 시각과 함께 그 시나리오의 AAS 폴더와 MCF 레시피 구조(MCF 인스턴스 기록에 씀)를 돌려줌. 무한가동은 수량·납기일 없이 scenario_conditions.py의 무한가동 조건(제품별 비율, 유지 수량)으로 기간이 끝날 때까지 생산 ================================================
    def start(self, execution_method, infinite_operation, target_quantity_by_product,
              due_day_by_product, simulation_period_day, defect_rate_for_check, random_seed):
        self.episode = None
        collect_garbage()
        method_conditions = EXECUTION_METHOD_CONDITIONS[execution_method]
        scenario = method_conditions['scenario']
        conditions = self.conditions_of_scenario(scenario)
        conditions.update(API_RUN_CONDITIONS)
        conditions['infinite_operation'] = infinite_operation
        if not infinite_operation:
            conditions['target_quantity_by_product'] = dict(target_quantity_by_product)
            conditions['due_day_by_product'] = dict(due_day_by_product)
        conditions['simulation_period_day'] = simulation_period_day
        self.episode = episode_procedure.EpisodeProcedure(
            conditions, random_seed, ApiRecordingSimulationModel)
        self.episode.prepare_simulation_model()
        if method_conditions['reinforcement_learning_model_applied']:
            loaded_model = self.loaded_model_by_scenario[scenario]
            self.episode.prepare_reinforcement_learning_model(
                loaded_model['reinforcement_learning_model'],
                loaded_model['start_timing_emission_record'], action.EVALUATION_MODE,
                MODEL_APPLICATION_SETTINGS['exploration_seed'],
                MODEL_APPLICATION_SETTINGS['update_start_timing_emission_record'])
        self.episode.start_production()
        self.episode.advance_production(REAL_TIME_START_SEC)
        if defect_rate_for_check is not None:
            self.apply_defect_rate_for_check(defect_rate_for_check)
        self.read_event_count = {}
        for event_kind in EVENT_KEYS:
            self.read_event_count[event_kind] = 0
        self.read_smt_material_event_record_count = 0
        self.read_product_completion_record_count = 0
        return {
            'simulation_time_sec': self.now_sec(),
            'aas_directory': conditions['aas_directory'],
            'mcf_recipe_structure': self.episode.simulation_model.mcf_recipe_structure,
        }

    def now_sec(self):
        return float(self.episode.simulation_model.simpy_environment.now)

    # ================================================ 확인용 불량률 적용: AAS 불량 이벤트의 대상 공정과 SMT 라인의 마지막 단계(AOI)의 불량 확률을 요청값으로 덮어씀 ================================================
    def apply_defect_rate_for_check(self, defect_rate_for_check):
        simulation_model = self.episode.simulation_model
        processes = simulation_model.simulation_processes.processes
        process_codes_for_check = []
        for process_code, process in processes.items():
            if process.is_defect_event_target_process:
                process_codes_for_check.append(process_code)
        for step_process_codes in simulation_model.step_process_codes_by_smt_line.values():
            last_step_process_code = step_process_codes[-1]
            process_codes_for_check.append(last_step_process_code)
        for process_code in process_codes_for_check:
            processes[process_code].defect_probability_per_output_item = float(
                defect_rate_for_check)

    # ================================================ 시뮬레이션 진행: 지정한 시각까지 진행. 목표 생산이 끝났거나 시뮬레이션 기간이 다 되면 끝 ================================================
    def advance(self, until_sec):
        is_running = self.episode.advance_production(until_sec)
        return {
            'simulation_time_sec': self.now_sec(),
            'simulation_finished': not is_running,
        }

    # ================================================ 실시간 상태 읽기: 지금까지의 작업자 유휴시간과 설비 전력량을 누적한 뒤 생산량, 진행 수량, 작업자 수, 전력을 읽음 ================================================
    def read_real_time_state(self):
        simulation_model = self.episode.simulation_model
        simulation_model.accumulate_worker_idle_time_and_machine_energy_until_now()
        worker_count_by_worker_group = {}
        running_job_count_by_worker_group = {}
        for worker_group, worker_group_values in simulation_model.worker_groups.items():
            worker_count_by_worker_group[worker_group] = worker_group_values['worker_count']
            running_job_count_by_worker_group[worker_group] = (
                simulation_model.running_job_count_by_worker_group.get(worker_group, 0))
        real_time_state = {
            'production_quantity_by_product': dict(
                simulation_model.production_quantity_by_product),
            'in_progress_quantity_by_product': dict(
                simulation_model.in_progress_quantity_by_product),
            'worker_count_by_worker_group': worker_count_by_worker_group,
            'running_job_count_by_worker_group': running_job_count_by_worker_group,
        }
        real_time_state.update(self.read_machine_power())
        real_time_state.update(self.read_worker_group_power())
        real_time_state.update(self.read_base_load_power())
        real_time_state['smt_material_events'] = self.read_smt_material_events()
        return real_time_state

    # ================================================ SMT 필름 교체·Chip 보충 이벤트 읽기: 지금까지의 발생 기록에서 시작과 종료를 짝지어 이벤트마다 구분 이름, SMT 라인, 설비, 시작 시각, 종료 시각(진행 중이면 None) ================================================
    def read_smt_material_events(self):
        start_record_name = SMT_MATERIAL_EVENT_RECORD_NAMES['start']
        smt_material_events = []
        ongoing_event_by_EventCode = {}
        for record in self.episode.simulation_model.smt_material_event_records:
            EventCode = record['EventCode']
            if record['event'] == start_record_name:
                smt_material_event = {
                    'event': SMT_MATERIAL_EVENT_NAMES[EventCode],
                    'smt_line': record['smt_line'],
                    'machine_name': record['machine_name'],
                    'start_sec': record['sec'],
                    'end_sec': None,
                }
                smt_material_events.append(smt_material_event)
                ongoing_event_by_EventCode[EventCode] = smt_material_event
            else:
                ongoing_event_by_EventCode[EventCode]['end_sec'] = record['sec']
        return smt_material_events

    # ================================================ 공용 설비: 동시에 받는 수가 0 이하라 설비 자원을 만들지 않은 설비(압축기 등). 설비별 전력과 설비 이벤트에서 빼고 그 전력을 쓰는 라인에 나눠 넣음 ================================================
    def list_shared_machine_names(self):
        simulation_model = self.episode.simulation_model
        shared_machine_names = []
        for machine_name in simulation_model.machines:
            if machine_name not in simulation_model.machine_resources:
                shared_machine_names.append(machine_name)
        return shared_machine_names

    # ================================================ 설비별 전력: 쓰는 공정이 있으면 정격전력, 없으면 0. 누적은 설비의 시간대 가중 전력량 ================================================
    def read_machine_power(self):
        simulation_model = self.episode.simulation_model
        shared_machine_names = self.list_shared_machine_names()
        power_kw_by_machine = {}
        weighted_energy_kwh_by_machine = {}
        for machine_name, machine_values in simulation_model.machines.items():
            if machine_name in shared_machine_names:
                continue
            if simulation_model.machine_use_count_by_worker_group[machine_name]:
                power_kw_by_machine[machine_name] = machine_values['rated_power_kw']
            else:
                power_kw_by_machine[machine_name] = 0.0
            weighted_energy_kwh_by_machine[machine_name] = (
                simulation_model.machine_weighted_energy_kwh[machine_name])
        return {
            'power_kw_by_machine': power_kw_by_machine,
            'weighted_energy_kwh_by_machine': weighted_energy_kwh_by_machine,
        }

    # ================================================ 라인별 전력: (배정 인원과 진행 중 작업 수 가운데 작은 값) × 그 작업자 그룹 공정들의 정격전력 평균 + 공용 설비 몫. 누적은 공정의 시간대 가중 전력량 + 공용 설비 몫 ================================================
    def mean_process_rated_power_kw(self, process_codes):
        processes = self.episode.simulation_model.simulation_processes.processes
        process_rated_powers_kw = []
        for process_code in process_codes:
            if process_code in processes:
                process_rated_powers_kw.append(processes[process_code].process_rated_power_kw)
        if not process_rated_powers_kw:
            return 0.0
        return sum(process_rated_powers_kw) / len(process_rated_powers_kw)

    def read_worker_group_power(self):
        simulation_model = self.episode.simulation_model
        shared_machine_names = self.list_shared_machine_names()
        power_kw_by_worker_group = {}
        weighted_energy_kwh_by_worker_group = {}
        for worker_group, worker_group_values in simulation_model.worker_groups.items():
            running_job_count = simulation_model.running_job_count_by_worker_group.get(
                worker_group, 0)
            working_worker_count = min(worker_group_values['worker_count'], running_job_count)
            power_kw = working_worker_count * self.mean_process_rated_power_kw(
                worker_group_values['process_codes'])
            weighted_energy_kwh = (
                simulation_model.process_weighted_energy_kwh_by_worker_group.get(
                    worker_group, 0.0))
            for machine_name in shared_machine_names:
                weighted_energy_kwh_of_machine = (
                    simulation_model.machine_weighted_energy_kwh_by_worker_group[machine_name])
                weighted_energy_kwh += weighted_energy_kwh_of_machine.get(worker_group, 0.0)
                using_worker_groups = (
                    simulation_model.machine_use_count_by_worker_group[machine_name])
                if worker_group in using_worker_groups:
                    rated_power_kw = simulation_model.machines[machine_name]['rated_power_kw']
                    power_kw += rated_power_kw / len(using_worker_groups)
            power_kw_by_worker_group[worker_group] = power_kw
            weighted_energy_kwh_by_worker_group[worker_group] = weighted_energy_kwh
        return {
            'power_kw_by_worker_group': power_kw_by_worker_group,
            'weighted_energy_kwh_by_worker_group': weighted_energy_kwh_by_worker_group,
        }

    # ================================================ 기저부하 전력: 하루 중 시각이 근무 시작 이상 근무 종료 미만이면 기저부하 kW(점심에도 켜짐), 아니면 0. 누적은 기저부하의 시간대 가중 전력량 ================================================
    def read_base_load_power(self):
        simulation_model = self.episode.simulation_model
        sec_in_day = self.now_sec() % SECONDS_PER_DAY
        is_between_work_start_and_end = (
            simulation_model.WorkStartTime <= sec_in_day < simulation_model.WorkEndTime)
        if is_between_work_start_and_end:
            base_load_power_kw = simulation_model.base_load_kw
        else:
            base_load_power_kw = 0.0
        return {
            'base_load_power_kw': base_load_power_kw,
            'base_load_weighted_energy_kwh': simulation_model.base_load_weighted_energy_kwh(),
        }

    # ================================================ 탄소배출량 읽기: MCF 탄소배출량을 계산해 공정별 전력 탄소배출량(그 공정 레시피들의 공유 배출 × AllocatedFactor 합, 곧 그 공정이 쓴 전력량 × 배출계수. 앞 공정에서 넘어온 몫은 넣지 않아 공정끼리 더해도 겹치지 않음), 라인별 전력 탄소배출량(그 라인 공정들의 합), 기저부하의 전력 탄소배출량, 공장 합(라인 합 + 기저부하)을 꺼냄. 이 네 값은 MCF의 AllocatedCO2eq·SumCO2eq(투입 재료에서 넘어온 몫 포함)와 다른 값이라 그 이름을 쓰지 않음. 누적값(레시피별 AllocatedCO2eq, MCF별 SumCO2eq)은 MCF 탄소배출량 계산 결과 그대로 mcf_carbon_emissions에 따로 담음 ================================================
    def read_carbon_emission(self):
        simulation_model = self.episode.simulation_model
        simulation_model.accumulate_worker_idle_time_and_machine_energy_until_now()
        mcf_carbon_emissions = simulation_model.mcf_carbon_emissions()
        process_code_by_simulation_recipe_index = (
            simulation_model.process_code_by_simulation_recipe_index)
        electricity_carbon_emission_of_every_process = {}
        base_load_electricity_carbon_emission = 0.0
        for mcf_carbon_emission in mcf_carbon_emissions['mcf_carbon_emissions']:
            if mcf_carbon_emission['is_base_load_mcf']:
                base_load_electricity_carbon_emission += mcf_carbon_emission['shared_emission']
            for allocation in mcf_carbon_emission['Allocation']:
                process_code = process_code_by_simulation_recipe_index[
                    allocation['simulation_recipe_index']]
                electricity_carbon_emission_before = (
                    electricity_carbon_emission_of_every_process.get(process_code, 0.0))
                electricity_carbon_emission_of_every_process[process_code] = (
                    electricity_carbon_emission_before + allocation['allocated_shared_emission'])
        electricity_carbon_emission_by_process = {}
        worker_group_by_process = {}
        electricity_carbon_emission_by_worker_group = {}
        process_codes_by_mcf_line = simulation_model.list_process_codes_by_mcf_line()
        for mcf_line, process_codes in process_codes_by_mcf_line.items():
            electricity_carbon_emission_by_worker_group[mcf_line] = 0.0
            for process_code in process_codes:
                electricity_carbon_emission = electricity_carbon_emission_of_every_process.get(
                    process_code, 0.0)
                electricity_carbon_emission_by_worker_group[mcf_line] += electricity_carbon_emission
                is_executed = process_code in simulation_model.operating_time_sec_by_process
                if is_executed or electricity_carbon_emission:
                    electricity_carbon_emission_by_process[process_code] = (
                        electricity_carbon_emission)
                    worker_group_by_process[process_code] = mcf_line
        line_electricity_carbon_emission = sum(electricity_carbon_emission_by_worker_group.values())
        return {
            'electricity_carbon_emission_by_process': electricity_carbon_emission_by_process,
            'worker_group_by_process': worker_group_by_process,
            'electricity_carbon_emission_by_worker_group': (
                electricity_carbon_emission_by_worker_group),
            'base_load_electricity_carbon_emission': base_load_electricity_carbon_emission,
            'factory_electricity_carbon_emission': (
                line_electricity_carbon_emission + base_load_electricity_carbon_emission),
            'mcf_carbon_emissions': mcf_carbon_emissions['mcf_carbon_emissions'],
            'recipes_without_mcf': mcf_carbon_emissions['recipes_without_mcf'],
        }

    # ================================================ 새 이벤트 읽기: 네 기록마다 지난번까지 읽은 개수를 기억해 그 뒤에 생긴 것만 돌려줌. 설비 이벤트는 엔진의 설비 가동·정지 기록에서 공용 설비를 뺀 것에 SMT 필름 교체·Chip 보충 이벤트의 시작·종료를 더해 시각 순으로. 박스 완료 이벤트는 제품 완성 기록에서 박스 완료 규칙으로 만듦 ================================================
    def read_new_events(self):
        simulation_model = self.episode.simulation_model
        recorded_events = {
            'machine_events': simulation_model.machine_on_off_records,
            'worker_process_events': simulation_model.worker_process_events,
            'warehouse_events': simulation_model.warehouse.events,
            'defect_events': simulation_model.defect_events,
        }
        new_events = {}
        for event_kind, events in recorded_events.items():
            new_events[event_kind] = events[self.read_event_count[event_kind]:]
            self.read_event_count[event_kind] = len(events)
        shared_machine_names = self.list_shared_machine_names()
        machine_events = []
        for machine_event in new_events['machine_events']:
            if machine_event['machine_name'] not in shared_machine_names:
                machine_events.append(machine_event)
        machine_events += self.read_new_smt_material_events_as_machine_events()
        new_events['machine_events'] = sorted(machine_events, key=itemgetter('sec'))
        new_events['box_completion_events'] = self.read_new_box_completion_events()
        return new_events

    def read_new_smt_material_events_as_machine_events(self):
        smt_material_event_records = self.episode.simulation_model.smt_material_event_records
        new_records = smt_material_event_records[self.read_smt_material_event_record_count:]
        self.read_smt_material_event_record_count = len(smt_material_event_records)
        machine_events = []
        for record in new_records:
            event_name = SMT_MATERIAL_EVENT_NAMES[record['EventCode']]
            start_or_end_name = SMT_MATERIAL_EVENT_START_AND_END_NAMES[record['event']]
            machine_events.append({
                'sec': record['sec'],
                'event': event_name + start_or_end_name,
                'machine_name': record['machine_name'],
            })
        return machine_events

    # ================================================ 박스 완료 규칙: 한 제품의 완성품(완료 공정이 끝난 제품)이 박스당 제품 수량만큼 찰 때마다 박스 하나가 완료된 것으로 봄. 생산량이 박스당 제품 수량의 배수가 된 순간이 박스 완료이고, 박스 번호는 그 제품의 몇 번째 박스인지(1부터). 박스를 채우지 못하고 남은 완성품은 박스 완료가 아님 ================================================
    def is_box_full_at_production_quantity(self, production_quantity, product_quantity_per_box):
        return production_quantity % product_quantity_per_box == 0

    def box_number_at_production_quantity(self, production_quantity, product_quantity_per_box):
        return production_quantity // product_quantity_per_box

    # ================================================ 새 박스 완료 이벤트 읽기: 지난번 읽은 뒤의 제품 완성 기록 가운데 박스 완료 규칙에 맞는 것마다 박스 완료 시각(그 박스의 마지막 제품이 완성된 시뮬레이션 시각), 제품, 박스 번호, 박스당 제품 수량. 박스당 제품 수량이 없는 제품은 박스 완료 이벤트를 내지 않음 ================================================
    def read_new_box_completion_events(self):
        product_completion_records = self.episode.simulation_model.product_completion_records
        new_records = product_completion_records[self.read_product_completion_record_count:]
        self.read_product_completion_record_count = len(product_completion_records)
        box_completion_events = []
        for record in new_records:
            product_code = record['product_code']
            if product_code not in PRODUCT_QUANTITY_PER_BOX_BY_PRODUCT:
                continue
            product_quantity_per_box = PRODUCT_QUANTITY_PER_BOX_BY_PRODUCT[product_code]
            production_quantity = record['production_quantity']
            if self.is_box_full_at_production_quantity(
                    production_quantity, product_quantity_per_box):
                box_completion_events.append({
                    'sec': record['sec'],
                    'product_code': product_code,
                    'box_number': self.box_number_at_production_quantity(
                        production_quantity, product_quantity_per_box),
                    'product_quantity_per_box': product_quantity_per_box,
                })
        return box_completion_events


SIMULATION_RUNNER = SimulationRunner()


# ================================================ 시뮬레이션 실행기 준비: 실행기 프로세스마다 한 번, AAS와 저장된 강화학습 모델 불러오기 ================================================
def prepare_simulation_runner(model_file_path, aas_data_directory):
    SIMULATION_RUNNER.prepare(model_file_path, aas_data_directory)


# ================================================ 기준 정보 읽기: 제품 코드, 기본 PO 수량·납기일, 완료 공정코드, 박스당 제품 수량 ================================================
def read_reference_information():
    return SIMULATION_RUNNER.read_reference_information()


# ================================================ 시뮬레이션 시작: 실행 방식에 맞는 시뮬레이션 모델을 만들고 실시간 실행을 시작할 시각까지 진행. 시작한 시각, 그 시나리오의 AAS 폴더, MCF 레시피 구조를 돌려줌 ================================================
def start_simulation(
        execution_method, infinite_operation, target_quantity_by_product, due_day_by_product,
        simulation_period_day, defect_rate_for_check, random_seed):
    return SIMULATION_RUNNER.start(
        execution_method, infinite_operation, target_quantity_by_product, due_day_by_product,
        simulation_period_day, defect_rate_for_check, random_seed)


# ================================================ 시뮬레이션 진행: 지정한 시뮬레이션 시각까지 진행 ================================================
def advance_simulation(until_sec):
    return SIMULATION_RUNNER.advance(until_sec)


# ================================================ 실시간 상태 읽기: 지금 시각의 생산량, 진행 수량, 작업자 수, 전력 ================================================
def read_real_time_state():
    return SIMULATION_RUNNER.read_real_time_state()


# ================================================ 탄소배출량 읽기: 공정별·라인(작업자 그룹)별·기저부하·공장 전체의 전력 탄소배출량과 MCF 탄소배출량 계산 결과(레시피별 AllocatedCO2eq, MCF별 SumCO2eq) ================================================
def read_carbon_emission():
    return SIMULATION_RUNNER.read_carbon_emission()


# ================================================ 새 이벤트 읽기: 지난번 읽은 뒤에 생긴 설비, 작업자 공정, 창고, 불량, 박스 완료 이벤트 ================================================
def read_new_events():
    return SIMULATION_RUNNER.read_new_events()
