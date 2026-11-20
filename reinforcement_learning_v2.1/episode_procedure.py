import random
import time
from gc import collect as collect_garbage

import export
from aas_preprocessing.aas_reader import SECONDS_PER_DAY
from aas_preprocessing.path_extractor import PathExtractor
from discrete_event_simulation import carbon_components, simulation_generator
from discrete_event_simulation.simulation_model import SimulationModel, quantity_by_product_ratio
from reinforcement_learning import action, model, reward, state


# ================================================ 에피소드 1회 실행 순서(강화학습 모델 적용): 환경 준비 → 강화학습 모델 준비 → 생산 실행 → 종료 시 전력량 계산 → 구간 보상 계산 → 결과 수집 ================================================
def run_episode(conditions, simulation_seed, reinforcement_learning_model,
                start_timing_emission_record, mode, exploration_seed,
                update_start_timing_emission_record):
    episode = EpisodeProcedure(conditions, simulation_seed, SimulationModel)
    episode.prepare_simulation_model()
    episode.prepare_reinforcement_learning_model(
        reinforcement_learning_model, start_timing_emission_record, mode, exploration_seed,
        update_start_timing_emission_record)
    episode.run_production()
    episode.calculate_energy_at_end()
    episode.calculate_interval_rewards()
    episode_result = episode.collect_result()
    del episode
    collect_garbage()
    return episode_result


# ================================================ 에피소드 1회 실행 순서(As-is, 강화학습 모델 없이 선입선출): 환경 준비 → 생산 실행 → 종료 시 전력량 계산 → 보상 항목 계산 → 결과 수집 ================================================
def run_as_is_episode(conditions, simulation_seed):
    episode = EpisodeProcedure(conditions, simulation_seed, SimulationModel)
    episode.prepare_simulation_model()
    episode.run_production()
    episode.calculate_energy_at_end()
    episode.calculate_interval_rewards()
    episode_result = episode.collect_as_is_result()
    del episode
    collect_garbage()
    return episode_result


# ================================================ 저장된 강화학습 모델 불러오기: 시나리오 조건의 입력 차원 확인, 신경망 가중치, 그 시나리오의 착수 시점별 배출량 기록 ================================================
def input_dimensions_of(conditions):
    episode = EpisodeProcedure(conditions, None, SimulationModel)
    episode.generate_simulation_model()
    return state.StateBuilder(episode.simulation_model).input_dimensions()


def load_reinforcement_learning_model(model_file, conditions):
    loaded = model.load_model(model_file, input_dimensions_of(conditions))
    saved_record = model.saved_start_timing_emission_record(
        loaded['saved_content'], conditions['scenario'])
    return {
        'reinforcement_learning_model': loaded['reinforcement_learning_model'],
        'start_timing_emission_record': action.StartTimingEmissionRecord(saved_record),
        'saved_content': loaded['saved_content'],
    }


class EpisodeProcedure:

    # ================================================ 에피소드 한 번에 쓰는 값 보관: 시나리오 조건, 시뮬레이션 난수 seed, 시뮬레이션 모델 클래스, 실행 시작 시점 ================================================
    def __init__(self, conditions, simulation_seed, simulation_model_class):
        self.conditions = conditions
        self.simulation_seed = simulation_seed
        self.simulation_model_class = simulation_model_class
        self.started_at = time.perf_counter()
        self.simulation_model = None
        self.action_selector = None
        self.mode = export.AS_IS_MODE

    # ================================================ 환경 준비: 난수 seed를 정하고 시나리오 조건으로 시뮬레이션 모델 생성. 무한가동이면 목표 구간 하나가 목표 수량 실행 한 번과 같은 조건: 제품별 목표 수량은 제품별 비율 × production_quantity_per_product, 제품별 납기는 목표 구간 시작부터 due_day ================================================
    def prepare_simulation_model(self):
        random.seed(self.simulation_seed)
        self.generate_simulation_model()

    def generate_simulation_model(self):
        conditions = self.conditions
        path_extractor = PathExtractor(conditions['aas_directory'])
        target_quantity_by_product = {}
        due_day_by_product = {}
        for product_code in path_extractor.extract_product_codes():
            target_quantity_by_product[product_code] = (
                conditions['production_quantity_per_product'])
            due_day_by_product[product_code] = conditions['due_day']
        if 'target_quantity_by_product' in conditions:
            target_quantity_by_product = conditions['target_quantity_by_product']
            due_day_by_product = conditions['due_day_by_product']
        if conditions['electricity_time_band_weights_applied']:
            electricity_time_band_weights = conditions['electricity_time_band_weights']
        else:
            electricity_time_band_weights = []
        worker_reallocation_conditions = {'enabled': conditions['worker_reallocation_enabled']}
        worker_reallocation_conditions.update(conditions['worker_reallocation_conditions'])
        infinite_operation_conditions = {'applied': conditions['infinite_operation']}
        infinite_operation_conditions.update(conditions['infinite_operation_conditions'])
        if conditions['infinite_operation']:
            product_codes = path_extractor.extract_product_codes()
            target_quantity_by_product = quantity_by_product_ratio(
                product_codes, infinite_operation_conditions['product_ratio'],
                conditions['production_quantity_per_product'])
            due_day_by_product = {}
            for product_code in product_codes:
                due_day_by_product[product_code] = conditions['due_day']
        smt_material_event_conditions = {
            'applied': conditions['smt_material_events_applied'],
            'wait_sec_by_EventCode': conditions['smt_material_event_wait_sec_by_EventCode'],
            'simulation_seed': self.simulation_seed,
        }
        self.simulation_model = simulation_generator.generate_simulation_model(
            path_extractor, target_quantity_by_product, due_day_by_product,
            conditions['base_load_kw'], electricity_time_band_weights,
            conditions['infinite_stock'], conditions['pcb_stock_limited'],
            conditions['pcb_initial_stock_ratio'], worker_reallocation_conditions,
            conditions['start_delay_allowed_process_kg_node_paths'],
            conditions['max_start_delay_sec'],
            smt_material_event_conditions=smt_material_event_conditions,
            infinite_operation_conditions=infinite_operation_conditions,
            simulation_model_class=self.simulation_model_class)

    # ================================================ 강화학습 모델 준비: 신경망을 평가 상태로 두고, State 생성 객체와 행동 선택 객체를 시뮬레이션 모델에 연결 ================================================
    def prepare_reinforcement_learning_model(
            self, reinforcement_learning_model, start_timing_emission_record, mode,
            exploration_seed, update_start_timing_emission_record):
        reinforcement_learning_model.eval()
        self.mode = mode
        self.action_selector = action.create_action_selector(
            self.simulation_model, reinforcement_learning_model, start_timing_emission_record,
            mode, self.simulation_seed, exploration_seed, update_start_timing_emission_record)

    # ================================================ 생산 실행: 생산을 시작하고 AAS의 RunLength까지 진행(나눠 진행할 때는 시작 뒤 진행을 여러 번 부름). 조건에 simulation_period_day가 있으면 그 기간이 실행 길이(무한가동은 실행 길이에서만 끝남) ================================================
    def run_production(self):
        self.start_production()
        self.advance_production(self.simulation_model.RunLength)

    def start_production(self):
        RunLength = None
        if 'simulation_period_day' in self.conditions:
            RunLength = self.conditions['simulation_period_day'] * SECONDS_PER_DAY
        self.simulation_model.start(self.action_selector, RunLength)

    def advance_production(self, until_sec):
        return self.simulation_model.advance(until_sec)

    # ================================================ 종료 시 전력량 계산: 생산 완료 시각(끝나지 않았으면 지금 시각)까지의 전력량 집계 ================================================
    def calculate_energy_at_end(self):
        self.completion_sec = self.simulation_model.production_completion_sec()
        if self.completion_sec is None:
            self.end_sec = float(self.simulation_model.simpy_environment.now)
        else:
            self.end_sec = self.completion_sec
        self.energy_account = self.simulation_model.aggregate_energy(self.end_sec)

    # ================================================ 구간 보상 계산: 종료 시점의 보상 항목(지금 목표 구간의 시작부터 센 값)과 끝난 목표 구간마다 그 목표 구간이 끝난 시점의 보상 항목을 계산하고, 결정 구간마다 변한 누적 보상을 결정 기록에 채움 ================================================
    def calculate_interval_rewards(self):
        if self.action_selector is None:
            cumulative_reward = reward.CumulativeReward(self.simulation_model)
            decisions = []
            target_period_numbers_of_decisions = []
            self.process_start_decision = None
        else:
            cumulative_reward = self.action_selector.cumulative_reward
            decisions = self.action_selector.decisions
            target_period_numbers_of_decisions = (
                self.action_selector.target_period_numbers_of_decisions)
            self.process_start_decision = self.action_selector.process_start_decision
        self.final_reward_items = cumulative_reward.reward_items(self.end_sec)
        self.reward_items_of_ended_target_periods = (
            cumulative_reward.reward_items_of_ended_target_periods())
        self.decisions = reward.interval_rewards(
            decisions, target_period_numbers_of_decisions, self.final_reward_items,
            self.reward_items_of_ended_target_periods)

    # ================================================ 결과 수집: 시뮬레이션 모델과 행동 선택 객체에서 값을 꺼내 export의 결과 수집 함수에 전달 ================================================
    def energy_by_line_type(self):
        simulation_model = self.simulation_model
        smt_process_codes = set()
        for step_process_codes in simulation_model.step_process_codes_by_smt_line.values():
            smt_process_codes.update(step_process_codes)
        return carbon_components.energy_by_line_type(
            self.energy_account, smt_process_codes, simulation_model.list_smt_machine_names())

    def collect_result(self):
        simulation_model = self.simulation_model
        action_selector = self.action_selector
        emission_record = action_selector.start_timing_emission_record
        metrics = export.collect_episode_metrics(
            simulation_seed=self.simulation_seed,
            mode=self.mode,
            completion_sec=self.completion_sec,
            end_sec=self.end_sec,
            work_time_sec=simulation_model.elapsed_work_time_sec(self.end_sec),
            completion_sec_by_product=simulation_model.completion_sec_by_product,
            production_quantity_by_product=simulation_model.production_quantity_by_product,
            energy_account=self.energy_account,
            energy_by_line_type=self.energy_by_line_type(),
            final_reward_items=self.final_reward_items,
            decisions=self.decisions,
            decision_counts=action_selector.decision_counts,
            process_start_decision=self.process_start_decision,
            start_timing_records=simulation_model.start_timing_records,
            start_timing_judgments=action_selector.start_timing_judgments,
            worker_idle_time_sec_by_worker_group=(
                simulation_model.worker_idle_time_sec_by_worker_group),
            pcb_shortage_wait_records=simulation_model.pcb_shortage_wait_records,
            recorded_start_time_slot_count=emission_record.recorded_start_time_slot_count(),
            run_wall_clock_sec=time.perf_counter() - self.started_at)
        return {
            'metrics': metrics,
            'decisions': self.decisions,
            'process_start_decision': self.process_start_decision,
            'edge_connections': action_selector.state_builder.edge_connections,
        }

    def collect_as_is_result(self):
        simulation_model = self.simulation_model
        metrics = export.collect_as_is_metrics(
            simulation_seed=self.simulation_seed,
            completion_sec=self.completion_sec,
            end_sec=self.end_sec,
            work_time_sec=simulation_model.elapsed_work_time_sec(self.end_sec),
            completion_sec_by_product=simulation_model.completion_sec_by_product,
            production_quantity_by_product=simulation_model.production_quantity_by_product,
            energy_account=self.energy_account,
            energy_by_line_type=self.energy_by_line_type(),
            final_reward_items=self.final_reward_items,
            worker_idle_time_sec_by_worker_group=(
                simulation_model.worker_idle_time_sec_by_worker_group),
            pcb_shortage_wait_records=simulation_model.pcb_shortage_wait_records,
            run_wall_clock_sec=time.perf_counter() - self.started_at)
        return {'metrics': metrics}
