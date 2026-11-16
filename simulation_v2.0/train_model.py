import argparse
import copy
import glob
import hashlib
import json
import subprocess
import sys
import time
from os import replace as replace_file
from pathlib import Path

import psutil
import torch

import episode_procedure
import export
import scenario_conditions
from reinforcement_learning import action, model, ppo


# ================================================ 학습 설정: 학습 에피소드 수, 신경망 처음 가중치와 seed 계산에 쓰는 초기 seed, 평가와 모델 저장 주기(에피소드), 신경망 입력 차원을 확인하는 시나리오, 학습 전 평가에서 착수 보류가 없도록 공정 착수 신경망 출력층 편향에 채우는 값 (PPO 설정은 reinforcement_learning/ppo.py의 PPO_SETTINGS, 평가 seed는 scenario_conditions.py의 evaluation_seeds) ================================================
TRAINING_SETTINGS = {
    'episodes': 160,
    'initial_seed': 21,
    'evaluation_interval_episodes': 20,
    'input_dimension_scenario': 'S1-2',
    'process_start_mean_bias_without_start_delay': 10.0,
}


# ================================================ 학습 seed 설정: 학습 에피소드의 시뮬레이션 seed 시작값과 간격(초기 seed마다, 시나리오마다), 시나리오 번호, 탐색 seed 시작값을 만드는 자리 간격, 평가 실행의 탐색 seed ================================================
TRAINING_SEED_SETTINGS = {
    'simulation_seed_base': 91000000,
    'simulation_seed_step_per_initial_seed': 100000,
    'simulation_seed_step_per_scenario': 20000,
    'scenario_seed_index': {'S1': 0, 'S1-1': 1, 'S1-2': 2},
    'exploration_seed_spacing': 1000,
    'evaluation_exploration_seed': 0,
}


# ================================================ 학습 실행 목록: 통합 전에 차례로 돌리는 학습 실행의 폴더 이름과 학습 시나리오(평가는 모든 실행이 세 시나리오 전부) ================================================
TRAINING_RUNS = {
    'scenario_S1': ['S1'],
    'scenario_S1-1': ['S1-1'],
    'scenario_S1-2': ['S1-2'],
    'all_scenarios': ['S1', 'S1-1', 'S1-2'],
}


# ================================================ 시나리오별 모델 통합 설정: 통합 모델로 다시 실행해 State를 모으는 반복 횟수, 통합 모델 학습(반복 수, 학습률, 가치 손실 계수, 공정 착수 쪽 손실 가중, minibatch 크기, 기울기 상한, 검증 주기), 판정 허용 비율, 시나리오별 모델의 조건(평가 seed 수, 탐색으로 착수 판단이 바뀐 에피소드 수), State 수집 실행의 seed 시작값과 실행 방식, 시험 실행 seed ================================================
INTEGRATION_SETTINGS = {
    'integrated_model_rollout_rounds': 2,
    'fit_epochs': 60,
    'learning_rate': 0.001,
    'value_loss_coefficient': 0.5,
    'process_start_loss_weight': 10.0,
    'minibatch_size': 32,
    'gradient_norm_limit': 1.0,
    'validation_interval_epochs': 5,
    'tolerance': 0.01,
    'minimum_evaluation_seed_count': 3,
    'minimum_start_judgment_changed_episodes': 10,
    'collection_seed_base': 99700000,
    'collection_exploration_seed_base': 4440000,
    'scenario_model_collection_modes': ['train', 'train', 'eval'],
    'integrated_model_collection_modes': ['train', 'eval'],
    'test_seeds': [98102105, 98102106, 98102107, 98102108, 98102109],
    'test_exploration_seed': 0,
}


# ================================================ 빠른 점검 설정(--quick-check): 반복 1회, 통합 모델 학습 2회, 시험 seed 1개, State 수집은 평가 방식 1회씩 ================================================
QUICK_CHECK_SETTINGS = {
    'integrated_model_rollout_rounds': 1,
    'fit_epochs': 2,
    'test_seed_count': 1,
    'collection_modes': ['eval'],
}


# ================================================ 메모리 대기 설정: 에피소드 실행 전에 기다리는 가용 메모리 기준(바이트)과 다시 확인하는 간격(초) ================================================
MEMORY_WAIT_SETTINGS = {
    'minimum_available_bytes': 1300000000,
    'recheck_wait_sec': 30,
}


# ================================================ 기록 파일 이름: 학습 단계와 통합 단계가 출력 폴더에 쓰는 파일과 폴더 ================================================
RECORD_FILE_NAMES = {
    'training_settings': 'settings.json',
    'resumed_training_settings': 'settings_resume_{run_started_label}.json',
    'last_model': 'model_last.pt',
    'evaluated_model': 'model_episode_{evaluation_tag}.pt',
    'evaluation_episodes': 'evaluation.jsonl',
    'training_episodes': 'training_episodes.jsonl',
    'ppo_updates': 'updates.jsonl',
    'progress': 'progress.json',
    'stop_request': 'STOP',
    'model_selection': 'selection.json',
    'integrated_model': 'integrated_model.pt',
    'as_is_test_folder': 'as_is_test',
    'as_is_test_run_folder': '{scenario}_as_is_{simulation_seed}',
    'test_episodes': 'test.jsonl',
    'integration_log': 'log.json',
    'test_verdict': 'verdict.json',
    'integration_folder': 'integrated',
}


# ================================================ 기록에 적는 표시 값: 학습 전 평가(착수 보류 없는 모델)의 평가 표시, 진행 상태, 통합 단계, 통합 모델을 고른 근거, 시험 실행 구분, 시각 형식 ================================================
EVALUATION_TAG_WITHOUT_START_DELAY = 'untrained_without_start_delay'
PROGRESS_STATUS = {
    'running': 'running',
    'stopped': 'stopped',
    'complete': 'complete',
}
INTEGRATION_STAGES = {
    'after_scenario_model_states': 'scenario_model_states',
    'after_rollout_round': 'integrated_model_rollout_round_{round_number}',
    'final': 'final',
}
INITIAL_MODEL_SELECTION_BASIS = {
    'evaluated_on_all_scenarios': 'best_model_evaluated_on_all_scenarios',
    'first_scenario_model': 'first_scenario_model',
}
STATE_SOURCES = {
    'scenario_model': 'scenario_model',
    'integrated_model': 'integrated_model_round_{round_number}',
    'test': 'test',
}
TEST_RUN_TYPE = 'integrated_model'
TIME_FORMATS = {
    'run_started_label': '%Y%m%dT%H%M%S',
    'record_time': '%m-%d %H:%M:%S',
    'finished_time': '%Y-%m-%d %H:%M:%S',
}


# ================================================ 그 밖의 고정값: 이 코드 파일과 폴더, 임시 파일 접미어, JSON 들여쓰기, 에피소드 번호가 없는 기록을 세지 않게 하는 큰 수, 제곱 지수, 통합 단계 기록에 남기지 않는 긴 결과 항목 ================================================
CODE_FILE = Path(__file__).resolve()
CODE_FOLDER = CODE_FILE.parent
TEMPORARY_FILE_SUFFIX = '.tmp'
JSON_INDENT = 1
EPISODE_NUMBER_WHEN_MISSING = 1000000000
SQUARE_EXPONENT = 2
METRICS_NOT_KEPT_IN_INTEGRATION = [
    'delayed_starts',
    'smt_lot_starts',
    'energy_by_process_kwh',
    'energy_by_machine_kwh',
]
INTEGRATE_COMMAND = 'integrate'
TRAIN_AND_INTEGRATE_COMMAND = 'all'


# ================================================ 시나리오 학습 순서: 출력 폴더 확인 → 강화학습 모델과 optimizer 준비 → (이어 하기) 저장된 내용 불러오기 → 학습 설정 기록 → 학습 전 평가 → [학습 에피소드 실행 → PPO 갱신 → 저장 → 평가] 반복 → 완료 기록 ================================================
def train_scenario_model():
    arguments = read_training_arguments()
    training = ScenarioTraining(
        scenarios_text=arguments.scenarios,
        evaluation_scenarios_text=arguments.evaluation_scenarios,
        initial_seed=arguments.initial_seed,
        target_episode_count=arguments.episodes,
        episodes_per_update=arguments.episodes_per_update,
        evaluation_interval_episodes=arguments.evaluation_interval,
        priority_learning_rate=arguments.priority_learning_rate,
        process_start_learning_rate=arguments.process_start_learning_rate,
        resume_model_file=arguments.resume,
        output_folder=arguments.output_folder,
        production_quantity_per_product=arguments.production_quantity_per_product)
    training.check_output_folder()
    training.prepare_reinforcement_learning_model()
    training.resume_from_saved_model()
    training.save_training_settings()
    training.evaluate_before_training()
    while training.completed_episode_count < training.target_episode_count:
        training.run_training_episodes()
        training.update_with_ppo()
        training.save_last_model_and_progress()
        training.evaluate_at_interval_or_end()
        if training.stop_requested:
            training.save_progress(PROGRESS_STATUS['stopped'])
            return
    training.save_progress(PROGRESS_STATUS['complete'])


# ================================================ 시나리오별 모델 통합 순서: 시나리오별 모델 고르기 → 모델 불러오기 → 시나리오별 모델로 실행해 State 수집 → 시나리오별 모델의 출력 붙이기 → 통합 모델 학습 → [통합 모델로 다시 실행해 State 수집 → 출력 붙이기 → 학습] 반복 → 통합 모델 시험 실행 → As-is 실행 → 판정 기록 ================================================
def integrate_scenario_models():
    arguments = read_integration_arguments()
    integration = ScenarioModelIntegration(
        training_folder_patterns=arguments.training_folders,
        output_folder=arguments.output_folder,
        integrated_model_rollout_rounds=arguments.integrated_model_rollout_rounds,
        fit_epochs=arguments.fit_epochs,
        learning_rate=arguments.learning_rate,
        value_loss_coefficient=arguments.value_loss_coefficient,
        tolerance=arguments.tolerance,
        collection_seed_base=arguments.collection_seed_base,
        test_seeds_text=arguments.test_seeds,
        quick_check=arguments.quick_check,
        minimum_start_judgment_changed_episodes=(
            arguments.minimum_start_judgment_changed_episodes),
        production_quantity_per_product=arguments.production_quantity_per_product)
    integration.select_scenario_models()
    integration.load_scenario_models_and_initial_integrated_model()
    integration.collect_states_with_scenario_models()
    integration.label_states_with_scenario_model_outputs()
    integration.fit_integrated_model()
    integration.save_integrated_model(INTEGRATION_STAGES['after_scenario_model_states'])
    for round_number in range(1, integration.integrated_model_rollout_rounds + 1):
        integration.collect_states_with_integrated_model(round_number)
        integration.label_states_with_scenario_model_outputs()
        integration.fit_integrated_model()
        integration.save_integrated_model(
            INTEGRATION_STAGES['after_rollout_round'].format(round_number=round_number))
    integration.save_integrated_model(INTEGRATION_STAGES['final'])
    integration.test_integrated_model()
    integration.run_as_is_episodes()
    integration.save_test_verdict_and_log()


# ================================================ 학습과 통합을 순서대로 실행: 학습 실행 목록을 하나씩 새 프로세스로 돌리고(저장된 모델이 있으면 이어서), 그 학습 폴더들로 통합 실행 ================================================
def train_and_integrate():
    arguments = read_train_and_integrate_arguments()
    output_folder = Path(arguments.output_folder).resolve()
    quantity_arguments = []
    if arguments.production_quantity_per_product is not None:
        quantity_arguments = [
            '--production-quantity-per-product', str(arguments.production_quantity_per_product)]
    all_scenarios_text = ','.join(scenario_conditions.SCENARIO_NAMES)
    training_folders = []
    for run_name, training_scenarios in TRAINING_RUNS.items():
        training_folder = output_folder / run_name
        command = [
            sys.executable, '-B', str(CODE_FILE),
            '--scenarios', ','.join(training_scenarios),
            '--evaluation-scenarios', all_scenarios_text,
            '--initial-seed', str(arguments.initial_seed),
            '--episodes', str(arguments.episodes),
            '--output-folder', str(training_folder)]
        last_model_file = training_folder / RECORD_FILE_NAMES['last_model']
        if last_model_file.exists():
            command.extend(['--resume', str(last_model_file)])
        command.extend(quantity_arguments)
        subprocess.run(command, check=True, cwd=CODE_FOLDER)
        training_folders.append(str(training_folder))
    command = [sys.executable, '-B', str(CODE_FILE), INTEGRATE_COMMAND, '--training-folders']
    command.extend(training_folders)
    command.extend([
        '--output-folder', str(output_folder / RECORD_FILE_NAMES['integration_folder']),
        '--fit-epochs', str(arguments.fit_epochs),
        '--integrated-model-rollout-rounds', str(arguments.integrated_model_rollout_rounds)])
    command.extend(quantity_arguments)
    subprocess.run(command, check=True, cwd=CODE_FOLDER)


# ================================================ 명령줄 입력: 실행 종류별 인자(주지 않으면 맨 위 설정값) ================================================
def read_training_arguments():
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument('--scenarios', required=True)
    argument_parser.add_argument('--evaluation-scenarios', default=None)
    argument_parser.add_argument(
        '--initial-seed', type=int, default=TRAINING_SETTINGS['initial_seed'])
    argument_parser.add_argument('--episodes', type=int, default=TRAINING_SETTINGS['episodes'])
    argument_parser.add_argument(
        '--episodes-per-update', type=int, default=ppo.PPO_SETTINGS['episodes_per_update'])
    argument_parser.add_argument(
        '--evaluation-interval', type=int,
        default=TRAINING_SETTINGS['evaluation_interval_episodes'])
    argument_parser.add_argument(
        '--priority-learning-rate', type=float,
        default=ppo.PPO_SETTINGS['priority_learning_rate'])
    argument_parser.add_argument(
        '--process-start-learning-rate', type=float,
        default=ppo.PPO_SETTINGS['process_start_learning_rate'])
    argument_parser.add_argument('--resume', default=None)
    argument_parser.add_argument('--output-folder', required=True)
    argument_parser.add_argument('--production-quantity-per-product', type=int, default=None)
    return argument_parser.parse_args()


def read_integration_arguments():
    test_seed_texts = [str(test_seed) for test_seed in INTEGRATION_SETTINGS['test_seeds']]
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument('--training-folders', nargs='+', required=True)
    argument_parser.add_argument('--output-folder', required=True)
    argument_parser.add_argument(
        '--integrated-model-rollout-rounds', type=int,
        default=INTEGRATION_SETTINGS['integrated_model_rollout_rounds'])
    argument_parser.add_argument(
        '--fit-epochs', type=int, default=INTEGRATION_SETTINGS['fit_epochs'])
    argument_parser.add_argument(
        '--learning-rate', type=float, default=INTEGRATION_SETTINGS['learning_rate'])
    argument_parser.add_argument(
        '--value-loss-coefficient', type=float,
        default=INTEGRATION_SETTINGS['value_loss_coefficient'])
    argument_parser.add_argument(
        '--tolerance', type=float, default=INTEGRATION_SETTINGS['tolerance'])
    argument_parser.add_argument(
        '--collection-seed-base', type=int, default=INTEGRATION_SETTINGS['collection_seed_base'])
    argument_parser.add_argument('--test-seeds', default=','.join(test_seed_texts))
    argument_parser.add_argument('--quick-check', action='store_true')
    argument_parser.add_argument(
        '--minimum-start-judgment-changed-episodes', type=int,
        default=INTEGRATION_SETTINGS['minimum_start_judgment_changed_episodes'])
    argument_parser.add_argument('--production-quantity-per-product', type=int, default=None)
    return argument_parser.parse_args()


def read_train_and_integrate_arguments():
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument('--output-folder', required=True)
    argument_parser.add_argument('--episodes', type=int, default=TRAINING_SETTINGS['episodes'])
    argument_parser.add_argument(
        '--initial-seed', type=int, default=TRAINING_SETTINGS['initial_seed'])
    argument_parser.add_argument(
        '--fit-epochs', type=int, default=INTEGRATION_SETTINGS['fit_epochs'])
    argument_parser.add_argument(
        '--integrated-model-rollout-rounds', type=int,
        default=INTEGRATION_SETTINGS['integrated_model_rollout_rounds'])
    argument_parser.add_argument('--production-quantity-per-product', type=int, default=None)
    return argument_parser.parse_args()


# ================================================ 기록 파일 읽고 쓰기: JSON 파일 저장(임시 파일에 쓴 뒤 교체), JSONL 한 줄 추가, JSONL 읽기(깨진 줄은 건너뜀), 파일의 sha256 ================================================
def write_json_file(file_path, content):
    temporary_file = Path(str(file_path) + TEMPORARY_FILE_SUFFIX)
    content_text = json.dumps(content, ensure_ascii=False, indent=JSON_INDENT)
    temporary_file.write_text(content_text, encoding='utf-8')
    replace_file(temporary_file, file_path)


def append_json_line(file_path, record):
    with open(file_path, 'a', encoding='utf-8') as record_file:
        record_file.write(json.dumps(record, ensure_ascii=False) + '\n')


def read_json_lines(file_path):
    records = []
    with open(file_path, encoding='utf-8') as record_file:
        for line in record_file:
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records


def sha256_of_file(file_path):
    return hashlib.sha256(Path(file_path).read_bytes()).hexdigest()


# ================================================ 학습과 통합이 함께 쓰는 계산: 시나리오 조건 조회(제품별 생산 수량을 주면 그 값으로), 평균, 가용 메모리 대기 ================================================
def conditions_by_scenario_with(production_quantity_per_product):
    conditions_by_scenario = {}
    for scenario in scenario_conditions.SCENARIO_NAMES:
        conditions = scenario_conditions.conditions_of_scenario(scenario)
        if production_quantity_per_product is not None:
            conditions['production_quantity_per_product'] = production_quantity_per_product
        conditions_by_scenario[scenario] = conditions
    return conditions_by_scenario


def mean_of(values):
    return sum(values) / len(values)


def mean_of_metric(metrics_list, metric_name):
    return mean_of([metrics[metric_name] for metrics in metrics_list])


def wait_for_available_memory():
    while psutil.virtual_memory().available < MEMORY_WAIT_SETTINGS['minimum_available_bytes']:
        time.sleep(MEMORY_WAIT_SETTINGS['recheck_wait_sec'])


# ================================================ 학습 seed 계산: 탐색 seed 시작값(초기 seed와 학습 시나리오 글자 코드 합), 학습 에피소드의 시뮬레이션 seed(초기 seed, 시나리오 번호, 에피소드 번호) ================================================
def exploration_seed_base_of(initial_seed, scenarios_text):
    spacing = TRAINING_SEED_SETTINGS['exploration_seed_spacing']
    character_code_sum = sum(ord(character) for character in scenarios_text)
    return (initial_seed * spacing + character_code_sum) * spacing


def training_simulation_seed(initial_seed, scenario, episode_number):
    seed_step_of_initial_seed = (
        initial_seed * TRAINING_SEED_SETTINGS['simulation_seed_step_per_initial_seed'])
    seed_step_of_scenario = (
        TRAINING_SEED_SETTINGS['scenario_seed_index'][scenario]
        * TRAINING_SEED_SETTINGS['simulation_seed_step_per_scenario'])
    return (TRAINING_SEED_SETTINGS['simulation_seed_base'] + seed_step_of_initial_seed
            + seed_step_of_scenario + episode_number)


class ScenarioTraining:

    # ================================================ 학습 한 번에 쓰는 값 보관: 학습·평가 시나리오, seed, 에피소드 수와 주기, 학습률, 이어 할 모델 파일, 출력 폴더, 시나리오 조건 ================================================
    def __init__(self, scenarios_text, evaluation_scenarios_text, initial_seed,
                 target_episode_count, episodes_per_update, evaluation_interval_episodes,
                 priority_learning_rate, process_start_learning_rate, resume_model_file,
                 output_folder, production_quantity_per_product):
        self.scenarios_text = scenarios_text
        self.training_scenarios = scenarios_text.split(',')
        if evaluation_scenarios_text:
            self.evaluation_scenarios = evaluation_scenarios_text.split(',')
        else:
            self.evaluation_scenarios = scenarios_text.split(',')
        self.evaluation_seeds = (
            scenario_conditions.COMMON_EXPERIMENT_CONDITIONS['evaluation_seeds'])
        self.initial_seed = initial_seed
        self.target_episode_count = target_episode_count
        self.episodes_per_update = episodes_per_update
        self.evaluation_interval_episodes = evaluation_interval_episodes
        self.priority_learning_rate = priority_learning_rate
        self.process_start_learning_rate = process_start_learning_rate
        self.resume_model_file = resume_model_file
        self.output_folder = Path(output_folder)
        self.production_quantity_per_product = production_quantity_per_product
        self.conditions_by_scenario = conditions_by_scenario_with(
            production_quantity_per_product)
        self.exploration_seed_base = exploration_seed_base_of(initial_seed, scenarios_text)
        self.run_started_label = time.strftime(TIME_FORMATS['run_started_label'])
        self.input_dimensions = None
        self.reinforcement_learning_model = None
        self.optimizers = None
        self.start_timing_emission_record = None
        self.completed_episode_count = 0
        self.resume_information = None
        self.edge_connections = None
        self.update_episodes = []
        self.stop_requested = False

    # ================================================ 출력 폴더 확인: 학습 기록이 이미 있는 폴더에서는 새 학습을 시작하지 않음 ================================================
    def check_output_folder(self):
        self.output_folder.mkdir(parents=True, exist_ok=True)
        if self.resume_model_file:
            return
        settings_file = self.output_folder / RECORD_FILE_NAMES['training_settings']
        last_model_file = self.output_folder / RECORD_FILE_NAMES['last_model']
        if settings_file.exists() or last_model_file.exists():
            raise FileExistsError('기존 학습 기록이 있는 폴더에 새로 시작하지 않음(이어 하기는 --resume)')

    # ================================================ 강화학습 모델과 optimizer 준비: 입력 차원 확인, 새 신경망, 작업 우선순위용과 공정 착수용 optimizer, 빈 착수 시점별 배출량 기록 ================================================
    def prepare_reinforcement_learning_model(self):
        dimension_scenario = TRAINING_SETTINGS['input_dimension_scenario']
        self.input_dimensions = episode_procedure.input_dimensions_of(
            self.conditions_by_scenario[dimension_scenario])
        self.reinforcement_learning_model = model.create_model(
            self.input_dimensions, self.initial_seed)
        self.optimizers = ppo.create_optimizers(
            self.reinforcement_learning_model, self.priority_learning_rate,
            self.process_start_learning_rate)
        self.start_timing_emission_record = action.StartTimingEmissionRecord(None)

    # ================================================ 이어 하기: 저장된 모델 파일에서 신경망 가중치, optimizer 상태, 끝낸 에피소드 수, 착수 시점별 배출량 기록 불러오기 ================================================
    def resume_from_saved_model(self):
        if not self.resume_model_file:
            return
        saved_content = torch.load(
            self.resume_model_file, weights_only=False, map_location='cpu')
        model.check_input_dimensions(saved_content['model_settings'], self.input_dimensions)
        if saved_content['model_settings'] != self.reinforcement_learning_model.model_settings:
            raise ValueError('이어 할 모델 파일의 신경망 설정이 지금 설정과 다름')
        self.reinforcement_learning_model.load_state_dict(
            saved_content['model_weights'], strict=True)
        self.optimizers['priority'].load_state_dict(saved_content['priority_optimizer_state'])
        self.optimizers['process_start'].load_state_dict(
            saved_content['process_start_optimizer_state'])
        self.completed_episode_count = int(saved_content['completed_episode_count'])
        self.start_timing_emission_record = action.StartTimingEmissionRecord(
            saved_content['start_timing_emission_record'])
        self.resume_information = {
            'model_file': str(Path(self.resume_model_file).resolve()),
            'completed_episode_count': self.completed_episode_count,
            'sha256': sha256_of_file(self.resume_model_file),
        }

    # ================================================ 학습 설정 기록: 이번 실행의 설정값과 코드 파일의 sha256을 출력 폴더에 저장 ================================================
    def save_training_settings(self):
        if self.resume_model_file:
            file_name = RECORD_FILE_NAMES['resumed_training_settings'].format(
                run_started_label=self.run_started_label)
        else:
            file_name = RECORD_FILE_NAMES['training_settings']
        source_sha256 = {}
        for code_file in sorted(CODE_FOLDER.rglob('*.py')):
            source_sha256[code_file.relative_to(CODE_FOLDER).as_posix()] = (
                sha256_of_file(code_file))
        write_json_file(self.output_folder / file_name, {
            'training_scenarios': self.training_scenarios,
            'evaluation_scenarios': self.evaluation_scenarios,
            'evaluation_seeds': self.evaluation_seeds,
            'initial_seed': self.initial_seed,
            'episodes': self.target_episode_count,
            'episodes_per_update': self.episodes_per_update,
            'evaluation_interval_episodes': self.evaluation_interval_episodes,
            'priority_learning_rate': self.priority_learning_rate,
            'process_start_learning_rate': self.process_start_learning_rate,
            'production_quantity_per_product': self.production_quantity_per_product,
            'output_folder': str(self.output_folder),
            'run_started_label': self.run_started_label,
            'resume_information': self.resume_information,
            'exploration_seed_base': self.exploration_seed_base,
            'priority_features': action.PRIORITY_FEATURES,
            'model_settings': self.reinforcement_learning_model.model_settings,
            'model_class': type(self.reinforcement_learning_model).__name__,
            'ppo_settings': ppo.PPO_SETTINGS,
            'source_sha256': source_sha256,
        })

    # ================================================ 에피소드 1회 실행과 기록: 실행 결과에 시나리오, 실행 시작 표시, 기록 시각을 더함 ================================================
    def run_recorded_episode(self, reinforcement_learning_model, scenario, simulation_seed,
                             mode, exploration_seed, update_start_timing_emission_record):
        episode_result = episode_procedure.run_episode(
            conditions=self.conditions_by_scenario[scenario],
            simulation_seed=simulation_seed,
            reinforcement_learning_model=reinforcement_learning_model,
            start_timing_emission_record=self.start_timing_emission_record,
            mode=mode,
            exploration_seed=exploration_seed,
            update_start_timing_emission_record=update_start_timing_emission_record)
        metrics = episode_result['metrics']
        metrics['scenario'] = scenario
        metrics['run_started_label'] = self.run_started_label
        metrics['time'] = time.strftime(TIME_FORMATS['record_time'])
        return episode_result

    # ================================================ 평가: 평가 시나리오와 평가 seed 전부를 평가 방식으로 실행해 기록 ================================================
    def evaluate_model(self, evaluation_tag, reinforcement_learning_model):
        evaluation_file = self.output_folder / RECORD_FILE_NAMES['evaluation_episodes']
        for scenario in self.evaluation_scenarios:
            for simulation_seed in self.evaluation_seeds:
                episode_result = self.run_recorded_episode(
                    reinforcement_learning_model=reinforcement_learning_model,
                    scenario=scenario,
                    simulation_seed=simulation_seed,
                    mode=action.EVALUATION_MODE,
                    exploration_seed=TRAINING_SEED_SETTINGS['evaluation_exploration_seed'],
                    update_start_timing_emission_record=False)
                metrics = episode_result['metrics']
                metrics['evaluation_tag'] = evaluation_tag
                append_json_line(evaluation_file, metrics)

    def evaluated_model_file(self, evaluation_tag):
        file_name = RECORD_FILE_NAMES['evaluated_model'].format(evaluation_tag=evaluation_tag)
        return self.output_folder / file_name

    def evaluate_and_save_model(self):
        self.evaluate_model(self.completed_episode_count, self.reinforcement_learning_model)
        self.save_model(self.evaluated_model_file(self.completed_episode_count))

    # ================================================ 학습 전 평가: 착수 보류가 없도록 공정 착수 신경망 출력층 편향을 채운 사본의 평가, 학습 전 모델의 평가와 저장 ================================================
    def evaluate_before_training(self):
        if self.completed_episode_count != 0:
            return
        model_without_start_delay = copy.deepcopy(self.reinforcement_learning_model)
        process_start_output_layer = model_without_start_delay.process_start_mean_layers[-1]
        with torch.no_grad():
            process_start_output_layer.bias.fill_(
                TRAINING_SETTINGS['process_start_mean_bias_without_start_delay'])
        self.evaluate_model(EVALUATION_TAG_WITHOUT_START_DELAY, model_without_start_delay)
        self.evaluate_and_save_model()

    # ================================================ 학습 에피소드 실행: 갱신 1회에 쓰는 수만큼 학습 시나리오를 번갈아 학습 방식으로 실행하고 결정 기록을 모음 ================================================
    def run_training_episodes(self):
        training_episodes_file = self.output_folder / RECORD_FILE_NAMES['training_episodes']
        self.update_episodes = []
        for update_episode_index in range(self.episodes_per_update):
            episode_number = self.completed_episode_count
            scenario_index = episode_number % len(self.training_scenarios)
            scenario = self.training_scenarios[scenario_index]
            episode_result = self.run_recorded_episode(
                reinforcement_learning_model=self.reinforcement_learning_model,
                scenario=scenario,
                simulation_seed=training_simulation_seed(
                    self.initial_seed, scenario, episode_number),
                mode=action.TRAIN_MODE,
                exploration_seed=self.exploration_seed_base + episode_number,
                update_start_timing_emission_record=True)
            if self.edge_connections is None:
                self.edge_connections = episode_result['edge_connections']
            metrics = episode_result['metrics']
            metrics['episode'] = episode_number
            metrics['decision_records'] = export.decision_records(episode_result['decisions'])
            append_json_line(training_episodes_file, metrics)
            self.update_episodes.append({
                'decisions': episode_result['decisions'],
                'process_start_decision': episode_result['process_start_decision'],
            })
            self.completed_episode_count += 1

    # ================================================ PPO 갱신: 모은 에피소드의 결정 기록으로 신경망 가중치를 갱신하고 갱신 결과를 기록 ================================================
    def update_with_ppo(self):
        update_statistics = ppo.ppo_update(
            self.reinforcement_learning_model, self.optimizers, self.update_episodes,
            self.edge_connections, self.exploration_seed_base + self.completed_episode_count)
        update_statistics['completed_episode_count'] = self.completed_episode_count
        update_statistics['run_started_label'] = self.run_started_label
        update_statistics['time'] = time.strftime(TIME_FORMATS['record_time'])
        append_json_line(self.output_folder / RECORD_FILE_NAMES['ppo_updates'], update_statistics)

    # ================================================ 저장: 신경망 가중치, optimizer 상태, 끝낸 에피소드 수, 착수 시점별 배출량 기록을 모델 파일로, 진행 상황을 기록 파일로 ================================================
    def save_model(self, model_file):
        temporary_file = Path(str(model_file) + TEMPORARY_FILE_SUFFIX)
        torch.save({
            'model_settings': self.reinforcement_learning_model.model_settings,
            'model_weights': self.reinforcement_learning_model.state_dict(),
            'priority_optimizer_state': self.optimizers['priority'].state_dict(),
            'process_start_optimizer_state': self.optimizers['process_start'].state_dict(),
            'completed_episode_count': self.completed_episode_count,
            'start_timing_emission_record': self.start_timing_emission_record.saved_content(),
            'train_scenarios': self.training_scenarios,
        }, temporary_file)
        replace_file(temporary_file, model_file)

    def save_progress(self, status):
        write_json_file(self.output_folder / RECORD_FILE_NAMES['progress'], {
            'completed_episode_count': self.completed_episode_count,
            'target_episode_count': self.target_episode_count,
            'status': status,
            'time': time.strftime(TIME_FORMATS['record_time']),
            'run_started_label': self.run_started_label,
        })

    def save_last_model_and_progress(self):
        self.save_model(self.output_folder / RECORD_FILE_NAMES['last_model'])
        self.save_progress(PROGRESS_STATUS['running'])

    # ================================================ 평가 주기 확인: 평가 주기이거나 마지막 에피소드이거나 중단 요청(STOP 파일)이 있으면 평가하고 그 시점의 모델을 저장 ================================================
    def evaluate_at_interval_or_end(self):
        self.stop_requested = (self.output_folder / RECORD_FILE_NAMES['stop_request']).exists()
        is_evaluation_interval = (
            self.completed_episode_count % self.evaluation_interval_episodes == 0)
        is_last_episode = self.completed_episode_count >= self.target_episode_count
        already_evaluated = self.evaluated_model_file(self.completed_episode_count).exists()
        if is_evaluation_interval or self.stop_requested or is_last_episode:
            if not already_evaluated:
                self.evaluate_and_save_model()


# ================================================ 시나리오별 모델 고르기: 학습 폴더들의 평가 기록에서 평가된 모델마다 평균 결과를 모으고, 시나리오마다 보상이 가장 높은 모델과 통합 모델의 시작 가중치로 쓸 모델을 고름 ================================================
def evaluated_models_of_training_folder(training_folder):
    evaluation_file = training_folder / RECORD_FILE_NAMES['evaluation_episodes']
    metrics_by_tag_and_scenario = {}
    for metrics in read_json_lines(evaluation_file):
        metrics_by_scenario = metrics_by_tag_and_scenario.setdefault(
            metrics['evaluation_tag'], {})
        metrics_by_scenario.setdefault(metrics['scenario'], []).append(metrics)
    evaluated_models = []
    for evaluation_tag, metrics_by_scenario in metrics_by_tag_and_scenario.items():
        if evaluation_tag == EVALUATION_TAG_WITHOUT_START_DELAY:
            continue
        model_file_name = RECORD_FILE_NAMES['evaluated_model'].format(
            evaluation_tag=evaluation_tag)
        model_file = training_folder / model_file_name
        if not model_file.exists():
            continue
        for scenario, metrics_list in metrics_by_scenario.items():
            evaluated_seeds = {metrics['seed'] for metrics in metrics_list}
            if len(evaluated_seeds) < INTEGRATION_SETTINGS['minimum_evaluation_seed_count']:
                continue
            evaluated_models.append({
                'training_folder': str(training_folder.resolve()),
                'evaluation_tag': evaluation_tag,
                'scenario': scenario,
                'model_file': str(model_file),
                'total_reward_by_completion_time': mean_of_metric(
                    metrics_list, 'total_reward_by_completion_time'),
                'completion_hours': mean_of_metric(metrics_list, 'completion_hours'),
                'weighted_kwh': mean_of_metric(metrics_list, 'weighted_kwh'),
            })
    return evaluated_models


def collect_evaluated_models(training_folder_patterns):
    evaluated_models = []
    for folder_pattern in training_folder_patterns:
        for training_folder_text in sorted(glob.glob(str(CODE_FOLDER / folder_pattern))):
            training_folder = Path(training_folder_text)
            if not (training_folder / RECORD_FILE_NAMES['evaluation_episodes']).exists():
                continue
            evaluated_models.extend(evaluated_models_of_training_folder(training_folder))
    return evaluated_models


def is_higher_reward_or_later_evaluation(reward, evaluation_tag, best_reward,
                                         best_evaluation_tag):
    if reward != best_reward:
        return reward > best_reward
    return evaluation_tag > best_evaluation_tag


def select_best_model_by_scenario(evaluated_models):
    scenario_models = {}
    for scenario in scenario_conditions.SCENARIO_NAMES:
        best_model = None
        for evaluated_model in evaluated_models:
            if evaluated_model['scenario'] != scenario:
                continue
            if best_model is None or is_higher_reward_or_later_evaluation(
                    evaluated_model['total_reward_by_completion_time'],
                    evaluated_model['evaluation_tag'],
                    best_model['total_reward_by_completion_time'],
                    best_model['evaluation_tag']):
                best_model = evaluated_model
        if best_model is None:
            raise RuntimeError(f'{scenario} 시나리오를 평가한 모델이 학습 폴더에 없음')
        scenario_models[scenario] = best_model
    return scenario_models


def select_integration_initial_model(evaluated_models, scenario_models):
    candidates = {}
    for evaluated_model in evaluated_models:
        candidate = candidates.setdefault(evaluated_model['model_file'], {
            'training_folder': evaluated_model['training_folder'],
            'evaluation_tag': evaluated_model['evaluation_tag'],
            'model_file': evaluated_model['model_file'],
            'total_reward_by_completion_time_by_scenario': {},
        })
        reward_by_scenario = candidate['total_reward_by_completion_time_by_scenario']
        reward_by_scenario[evaluated_model['scenario']] = (
            evaluated_model['total_reward_by_completion_time'])
    best_candidate = None
    best_reward_sum = None
    for candidate in candidates.values():
        reward_by_scenario = candidate['total_reward_by_completion_time_by_scenario']
        if len(reward_by_scenario) != len(scenario_conditions.SCENARIO_NAMES):
            continue
        reward_sum = sum(reward_by_scenario.values())
        if best_candidate is None or is_higher_reward_or_later_evaluation(
                reward_sum, candidate['evaluation_tag'],
                best_reward_sum, best_candidate['evaluation_tag']):
            best_candidate = candidate
            best_reward_sum = reward_sum
    if best_candidate is not None:
        initial_model = dict(best_candidate)
        initial_model['selection_basis'] = (
            INITIAL_MODEL_SELECTION_BASIS['evaluated_on_all_scenarios'])
        return initial_model
    first_scenario_model = scenario_models[scenario_conditions.SCENARIO_NAMES[0]]
    return {
        'training_folder': first_scenario_model['training_folder'],
        'evaluation_tag': first_scenario_model['evaluation_tag'],
        'model_file': first_scenario_model['model_file'],
        'selection_basis': INITIAL_MODEL_SELECTION_BASIS['first_scenario_model'],
    }


def count_start_judgment_changed_episodes(training_folder, scenario, evaluation_tag):
    training_episodes_file = (
        CODE_FOLDER / training_folder / RECORD_FILE_NAMES['training_episodes'])
    if not training_episodes_file.exists():
        return 0
    changed_episode_count = 0
    for metrics in read_json_lines(training_episodes_file):
        if metrics.get('scenario') != scenario:
            continue
        if int(metrics.get('episode', EPISODE_NUMBER_WHEN_MISSING)) >= evaluation_tag:
            continue
        if metrics.get('start_judgment_changed_by_exploration'):
            changed_episode_count += 1
    return changed_episode_count


# ================================================ 통합 모델 학습에 쓰는 State 고르기: 검증용 표시가 같은 State(없으면 전부) ================================================
def states_with_validation_flag(states, is_validation):
    selected_states = [state for state in states if state['is_validation'] == is_validation]
    if selected_states:
        return selected_states
    return states


def records_of_scenario(records, scenario):
    return [record for record in records if record['scenario'] == scenario]


# ================================================ 통합 모델 판정: 시험 실행(통합 모델)과 As-is 실행의 평균 결과 비교. 생산 완료 시간과 시간대 가중 전력량이 As-is의 (1 + 허용 비율)배 이하이고 모든 시험 실행이 생산을 끝내면 통과 ================================================
def scenario_test_verdict(integrated_model_metrics, as_is_metrics, tolerance):
    complete_count = 0
    for metrics in integrated_model_metrics:
        if metrics['complete']:
            complete_count += 1
    verdict = {
        'integrated_model_completion_hours': mean_of_metric(
            integrated_model_metrics, 'completion_hours'),
        'as_is_completion_hours': mean_of_metric(as_is_metrics, 'completion_hours'),
        'integrated_model_work_hours': mean_of_metric(integrated_model_metrics, 'work_hours'),
        'integrated_model_weighted_kwh': mean_of_metric(
            integrated_model_metrics, 'weighted_kwh'),
        'as_is_weighted_kwh': mean_of_metric(as_is_metrics, 'weighted_kwh'),
        'integrated_model_physical_kwh': mean_of_metric(
            integrated_model_metrics, 'physical_kwh'),
        'as_is_physical_kwh': mean_of_metric(as_is_metrics, 'physical_kwh'),
        'integrated_model_smt_peak_kwh': mean_of_metric(
            integrated_model_metrics, 'smt_peak_kwh'),
        'as_is_smt_peak_kwh': mean_of_metric(as_is_metrics, 'smt_peak_kwh'),
        'integrated_model_total_reward_by_completion_time': mean_of_metric(
            integrated_model_metrics, 'total_reward_by_completion_time'),
        'as_is_total_reward_by_completion_time': mean_of_metric(
            as_is_metrics, 'total_reward_by_completion_time'),
        'integrated_model_delayed_start_count': mean_of_metric(
            integrated_model_metrics, 'delayed_start_count'),
        'integrated_model_process_start_threshold': mean_of_metric(
            integrated_model_metrics, 'process_start_threshold'),
        'integrated_model_complete_count': complete_count,
        'test_run_count': len(integrated_model_metrics),
    }
    allowed_ratio = 1 + tolerance
    verdict['pass_time'] = (
        verdict['integrated_model_completion_hours']
        <= verdict['as_is_completion_hours'] * allowed_ratio)
    verdict['pass_carbon'] = (
        verdict['integrated_model_weighted_kwh'] <= verdict['as_is_weighted_kwh'] * allowed_ratio)
    all_complete = complete_count == len(integrated_model_metrics)
    verdict['pass'] = verdict['pass_time'] and verdict['pass_carbon'] and all_complete
    return verdict


class ScenarioModelIntegration:

    # ================================================ 통합 한 번에 쓰는 값 보관: 학습 폴더, 출력 폴더, 통합 설정(빠른 점검이면 빠른 점검 설정), 시나리오 조건, 모은 State와 기록 ================================================
    def __init__(self, training_folder_patterns, output_folder, integrated_model_rollout_rounds,
                 fit_epochs, learning_rate, value_loss_coefficient, tolerance,
                 collection_seed_base, test_seeds_text, quick_check,
                 minimum_start_judgment_changed_episodes, production_quantity_per_product):
        self.training_folder_patterns = training_folder_patterns
        self.output_folder = CODE_FOLDER / output_folder
        self.output_folder.mkdir(parents=True, exist_ok=True)
        self.integrated_model_file = self.output_folder / RECORD_FILE_NAMES['integrated_model']
        self.integrated_model_rollout_rounds = integrated_model_rollout_rounds
        self.fit_epochs = fit_epochs
        self.test_seeds = [int(seed_text) for seed_text in test_seeds_text.split(',')]
        self.scenario_model_collection_modes = (
            INTEGRATION_SETTINGS['scenario_model_collection_modes'])
        self.integrated_model_collection_modes = (
            INTEGRATION_SETTINGS['integrated_model_collection_modes'])
        self.quick_check = quick_check
        if quick_check:
            self.integrated_model_rollout_rounds = (
                QUICK_CHECK_SETTINGS['integrated_model_rollout_rounds'])
            self.fit_epochs = QUICK_CHECK_SETTINGS['fit_epochs']
            self.test_seeds = self.test_seeds[:QUICK_CHECK_SETTINGS['test_seed_count']]
            self.scenario_model_collection_modes = QUICK_CHECK_SETTINGS['collection_modes']
            self.integrated_model_collection_modes = QUICK_CHECK_SETTINGS['collection_modes']
        self.learning_rate = learning_rate
        self.value_loss_coefficient = value_loss_coefficient
        self.tolerance = tolerance
        self.collection_seed_base = collection_seed_base
        self.minimum_start_judgment_changed_episodes = minimum_start_judgment_changed_episodes
        self.conditions_by_scenario = conditions_by_scenario_with(
            production_quantity_per_product)
        self.input_dimensions = None
        self.scenario_models = {}
        self.integration_initial_model = None
        self.process_start_teaching = {}
        self.scenario_model_networks = {}
        self.start_timing_emission_records = {}
        self.integrated_model = None
        self.edge_connections_by_scenario = {}
        self.priority_states = []
        self.process_start_states = []
        self.collected_episodes = []
        self.task_sequence_number = 0
        self.fit_records = []
        self.test_metrics = []
        self.as_is_metrics = []

    # ================================================ 시나리오별 모델 고르기: 시나리오마다 평가 보상이 가장 높은 모델, 통합 모델의 시작 가중치로 쓸 모델, 시나리오별 모델의 공정 착수 행동을 배울지(탐색으로 착수 판단이 바뀐 학습 에피소드 수가 기준 이상일 때) ================================================
    def select_scenario_models(self):
        evaluated_models = collect_evaluated_models(self.training_folder_patterns)
        self.scenario_models = select_best_model_by_scenario(evaluated_models)
        self.integration_initial_model = select_integration_initial_model(
            evaluated_models, self.scenario_models)
        for scenario, scenario_model in self.scenario_models.items():
            changed_episode_count = count_start_judgment_changed_episodes(
                scenario_model['training_folder'], scenario,
                int(scenario_model['evaluation_tag']))
            self.process_start_teaching[scenario] = {
                'start_judgment_changed_episode_count': changed_episode_count,
                'teaches_process_start_action': (
                    changed_episode_count >= self.minimum_start_judgment_changed_episodes),
            }
        write_json_file(self.output_folder / RECORD_FILE_NAMES['model_selection'], {
            'scenario_models': self.scenario_models,
            'integration_initial_model': self.integration_initial_model,
            'process_start_teaching': self.process_start_teaching,
            'minimum_start_judgment_changed_episodes': (
                self.minimum_start_judgment_changed_episodes),
            'evaluated_models': evaluated_models,
        })

    # ================================================ 모델 불러오기: 시나리오별 모델의 신경망과 착수 시점별 배출량 기록, 통합 모델의 시작 신경망 ================================================
    def load_scenario_models_and_initial_integrated_model(self):
        dimension_scenario = TRAINING_SETTINGS['input_dimension_scenario']
        self.input_dimensions = episode_procedure.input_dimensions_of(
            self.conditions_by_scenario[dimension_scenario])
        for scenario, scenario_model in self.scenario_models.items():
            loaded = model.load_model(scenario_model['model_file'], self.input_dimensions)
            self.scenario_model_networks[scenario] = loaded['reinforcement_learning_model']
            self.start_timing_emission_records[scenario] = (
                model.saved_start_timing_emission_record(loaded['saved_content'], scenario))
        loaded = model.load_model(
            self.integration_initial_model['model_file'], self.input_dimensions)
        self.integrated_model = loaded['reinforcement_learning_model']

    # ================================================ State 수집: 시나리오와 실행 방식마다 에피소드를 실행해 작업 우선순위 결정 시각의 State와 에피소드 시작 때 공정 착수 결정의 State를 모음 ================================================
    def collection_tasks(self, model_file_by_scenario, modes, source):
        tasks = []
        for scenario in scenario_conditions.SCENARIO_NAMES:
            for mode in modes:
                tasks.append({
                    'model_file': model_file_by_scenario[scenario],
                    'scenario': scenario,
                    'mode': mode,
                    'simulation_seed': self.collection_seed_base + self.task_sequence_number,
                    'exploration_seed': (
                        INTEGRATION_SETTINGS['collection_exploration_seed_base']
                        + self.task_sequence_number),
                    'source': source,
                })
                self.task_sequence_number += 1
        return tasks

    def run_task_episode(self, task):
        wait_for_available_memory()
        scenario = task['scenario']
        loaded = model.load_model(task['model_file'], self.input_dimensions)
        start_timing_emission_record = action.StartTimingEmissionRecord(
            self.start_timing_emission_records[scenario])
        episode_result = episode_procedure.run_episode(
            conditions=self.conditions_by_scenario[scenario],
            simulation_seed=task['simulation_seed'],
            reinforcement_learning_model=loaded['reinforcement_learning_model'],
            start_timing_emission_record=start_timing_emission_record,
            mode=task['mode'],
            exploration_seed=task['exploration_seed'],
            update_start_timing_emission_record=False)
        metrics = episode_result['metrics']
        metrics['scenario'] = scenario
        for metric_name in METRICS_NOT_KEPT_IN_INTEGRATION:
            metrics.pop(metric_name, None)
        return episode_result

    def collect_states(self, tasks, evaluation_mode_states_are_for_validation):
        for task in tasks:
            episode_result = self.run_task_episode(task)
            scenario = task['scenario']
            if scenario not in self.edge_connections_by_scenario:
                self.edge_connections_by_scenario[scenario] = model.edge_connection_tensors(
                    episode_result['edge_connections'])
            episode_index = len(self.collected_episodes)
            metrics = episode_result['metrics']
            collected_episode = dict(task)
            collected_episode['total_reward_by_completion_time'] = (
                metrics['total_reward_by_completion_time'])
            collected_episode['completion_hours'] = metrics['completion_hours']
            collected_episode['priority_state_count'] = len(episode_result['decisions'])
            collected_episode['process_start_threshold'] = metrics['process_start_threshold']
            self.collected_episodes.append(collected_episode)
            is_validation = (
                evaluation_mode_states_are_for_validation
                and task['mode'] == action.EVALUATION_MODE)
            for decision in episode_result['decisions']:
                self.priority_states.append({
                    'episode_index': episode_index,
                    'scenario': scenario,
                    'is_validation': is_validation,
                    'node_features': torch.as_tensor(decision['node_features']),
                    'global_information': torch.as_tensor(decision['global_information']),
                    'process_start_action': torch.tensor(
                        [decision['process_start_action']], dtype=torch.float32),
                })
            process_start_decision = episode_result['process_start_decision']
            if process_start_decision is not None:
                teaching = self.process_start_teaching[scenario]
                self.process_start_states.append({
                    'episode_index': episode_index,
                    'scenario': scenario,
                    'is_validation': is_validation,
                    'teaches_process_start_action': teaching['teaches_process_start_action'],
                    'node_features': torch.as_tensor(process_start_decision['node_features']),
                    'global_information': torch.as_tensor(
                        process_start_decision['global_information']),
                })

    def collect_states_with_scenario_models(self):
        model_file_by_scenario = {}
        for scenario, scenario_model in self.scenario_models.items():
            model_file_by_scenario[scenario] = scenario_model['model_file']
        tasks = self.collection_tasks(
            model_file_by_scenario, self.scenario_model_collection_modes,
            STATE_SOURCES['scenario_model'])
        self.collect_states(tasks, not self.quick_check)

    def collect_states_with_integrated_model(self, round_number):
        model_file_by_scenario = {}
        for scenario in scenario_conditions.SCENARIO_NAMES:
            model_file_by_scenario[scenario] = str(self.integrated_model_file)
        tasks = self.collection_tasks(
            model_file_by_scenario, self.integrated_model_collection_modes,
            STATE_SOURCES['integrated_model'].format(round_number=round_number))
        self.collect_states(tasks, False)

    # ================================================ 시나리오별 모델의 출력 붙이기: 모은 State마다 그 시나리오 모델이 내는 행동 평균과 가치(통합 모델이 따라 배울 값) ================================================
    def label_states_with_scenario_model_outputs(self):
        with torch.no_grad():
            for priority_state in self.priority_states:
                if 'scenario_model_mean' in priority_state:
                    continue
                scenario = priority_state['scenario']
                network_output = self.scenario_model_networks[scenario].priority_forward(
                    priority_state['node_features'], self.edge_connections_by_scenario[scenario],
                    priority_state['global_information'], priority_state['process_start_action'])
                priority_state['scenario_model_mean'] = network_output['mean']
                priority_state['scenario_model_value'] = network_output['value']
            for process_start_state in self.process_start_states:
                if 'scenario_model_mean' in process_start_state:
                    continue
                scenario = process_start_state['scenario']
                network_output = self.scenario_model_networks[scenario].process_start_forward(
                    process_start_state['node_features'],
                    self.edge_connections_by_scenario[scenario],
                    process_start_state['global_information'])
                process_start_state['scenario_model_mean'] = network_output['mean']
                process_start_state['scenario_model_value'] = network_output['value']

    # ================================================ 통합 모델의 손실: 통합 모델과 시나리오별 모델의 출력 차이(행동 평균의 차이 제곱 + 가치 손실 계수 × 가치의 차이 제곱) ================================================
    def integrated_model_priority_output(self, priority_state):
        scenario = priority_state['scenario']
        return self.integrated_model.priority_forward(
            priority_state['node_features'], self.edge_connections_by_scenario[scenario],
            priority_state['global_information'], priority_state['process_start_action'])

    def integrated_model_process_start_output(self, process_start_state):
        scenario = process_start_state['scenario']
        return self.integrated_model.process_start_forward(
            process_start_state['node_features'], self.edge_connections_by_scenario[scenario],
            process_start_state['global_information'])

    def priority_state_loss(self, priority_state):
        network_output = self.integrated_model_priority_output(priority_state)
        mean_difference = network_output['mean'] - priority_state['scenario_model_mean']
        value_difference = network_output['value'] - priority_state['scenario_model_value']
        mean_loss = (mean_difference ** SQUARE_EXPONENT).mean()
        value_loss = value_difference ** SQUARE_EXPONENT
        return mean_loss + self.value_loss_coefficient * value_loss

    def process_start_state_loss(self, process_start_state):
        network_output = self.integrated_model_process_start_output(process_start_state)
        mean = network_output['mean']
        if process_start_state['teaches_process_start_action']:
            mean_loss = (mean - process_start_state['scenario_model_mean']) ** SQUARE_EXPONENT
        else:
            mean_loss = 0.0 * mean
        value_difference = network_output['value'] - process_start_state['scenario_model_value']
        value_loss = value_difference ** SQUARE_EXPONENT
        state_loss = mean_loss + self.value_loss_coefficient * value_loss
        return INTEGRATION_SETTINGS['process_start_loss_weight'] * state_loss

    def mean_loss_of_states(self, priority_states, process_start_states):
        priority_losses = [
            self.priority_state_loss(priority_state) for priority_state in priority_states]
        process_start_losses = [
            self.process_start_state_loss(process_start_state)
            for process_start_state in process_start_states]
        return torch.stack(priority_losses).mean() + torch.stack(process_start_losses).mean()

    # ================================================ 검증: 검증용 State의 손실과 시나리오별 평균 절대 오차(작업 우선순위 행동 평균, 공정 착수 행동 평균) ================================================
    def validation_losses(self):
        with torch.no_grad():
            priority_states = states_with_validation_flag(self.priority_states, True)
            process_start_states = states_with_validation_flag(self.process_start_states, True)
            validation_loss = self.mean_loss_of_states(priority_states, process_start_states)
            losses = {'validation_loss': float(validation_loss)}
            for scenario in scenario_conditions.SCENARIO_NAMES:
                priority_errors = []
                for priority_state in records_of_scenario(priority_states, scenario):
                    network_output = self.integrated_model_priority_output(priority_state)
                    mean_difference = (
                        network_output['mean'] - priority_state['scenario_model_mean'])
                    priority_errors.append(mean_difference.abs().mean())
                if priority_errors:
                    losses[f'{scenario}_priority_mean_absolute_error'] = float(
                        torch.stack(priority_errors).mean())
                process_start_errors = []
                for process_start_state in records_of_scenario(process_start_states, scenario):
                    network_output = self.integrated_model_process_start_output(
                        process_start_state)
                    mean_difference = (
                        network_output['mean'] - process_start_state['scenario_model_mean'])
                    process_start_errors.append(mean_difference.abs())
                if process_start_errors:
                    losses[f'{scenario}_process_start_mean_absolute_error'] = float(
                        torch.stack(process_start_errors).mean())
            return losses

    # ================================================ 통합 모델 학습: 학습용 State를 섞어 minibatch마다 한 걸음씩 갱신하고, 검증 손실이 가장 낮았던 가중치를 고름 ================================================
    def fit_one_epoch(self, optimizer, parameters, priority_states, process_start_states,
                      shuffle_generator):
        shuffled_indices = torch.randperm(
            len(priority_states), generator=shuffle_generator).tolist()
        minibatch_size = INTEGRATION_SETTINGS['minibatch_size']
        for minibatch_start in range(0, len(shuffled_indices), minibatch_size):
            minibatch_indices = shuffled_indices[minibatch_start:minibatch_start + minibatch_size]
            minibatch_states = [priority_states[index] for index in minibatch_indices]
            loss = self.mean_loss_of_states(minibatch_states, process_start_states)
            optimizer.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(
                parameters, INTEGRATION_SETTINGS['gradient_norm_limit'])
            optimizer.step()

    def fit_integrated_model(self):
        parameters = self.integrated_model.parameters_except_log_standard_deviation()
        optimizer = torch.optim.Adam(parameters, lr=self.learning_rate)
        shuffle_generator = torch.Generator().manual_seed(len(self.priority_states))
        priority_states = states_with_validation_flag(self.priority_states, False)
        process_start_states = states_with_validation_flag(self.process_start_states, False)
        best = {
            'validation_loss': self.validation_losses()['validation_loss'],
            'model_weights': copy.deepcopy(self.integrated_model.state_dict()),
            'epoch': 0,
        }
        for epoch in range(1, self.fit_epochs + 1):
            self.integrated_model.train()
            self.fit_one_epoch(
                optimizer, parameters, priority_states, process_start_states, shuffle_generator)
            self.integrated_model.eval()
            is_validation_epoch = epoch % INTEGRATION_SETTINGS['validation_interval_epochs'] == 0
            if is_validation_epoch or epoch == self.fit_epochs:
                losses = self.validation_losses()
                fit_record = {'epoch': epoch}
                fit_record.update(losses)
                self.fit_records.append(fit_record)
                if losses['validation_loss'] < best['validation_loss']:
                    best = {
                        'validation_loss': losses['validation_loss'],
                        'model_weights': copy.deepcopy(self.integrated_model.state_dict()),
                        'epoch': epoch,
                    }
        self.integrated_model.load_state_dict(best['model_weights'])
        self.fit_records.append({
            'chosen_epoch': best['epoch'],
            'validation_loss': best['validation_loss'],
            'priority_state_count': len(self.priority_states),
            'process_start_state_count': len(self.process_start_states),
        })

    # ================================================ 통합 모델 저장: 신경망 가중치, 시나리오별 착수 시점별 배출량 기록, 고른 모델 정보, 통합 단계 ================================================
    def save_integrated_model(self, integration_stage):
        torch.save({
            'model_settings': self.integrated_model.model_settings,
            'model_weights': self.integrated_model.state_dict(),
            'start_timing_emission_records': self.start_timing_emission_records,
            'scenario_models': self.scenario_models,
            'integration_initial_model': self.integration_initial_model,
            'integration_stage': integration_stage,
        }, self.integrated_model_file)

    # ================================================ 통합 모델 시험 실행: 저장한 통합 모델로 시나리오와 시험 seed마다 평가 방식 실행 ================================================
    def test_integrated_model(self):
        for scenario in scenario_conditions.SCENARIO_NAMES:
            for simulation_seed in self.test_seeds:
                episode_result = self.run_task_episode({
                    'model_file': str(self.integrated_model_file),
                    'scenario': scenario,
                    'mode': action.EVALUATION_MODE,
                    'simulation_seed': simulation_seed,
                    'exploration_seed': INTEGRATION_SETTINGS['test_exploration_seed'],
                    'source': STATE_SOURCES['test'],
                })
                self.test_metrics.append(episode_result['metrics'])

    # ================================================ As-is 실행: 같은 시나리오와 시험 seed로 강화학습 모델 없이 선입선출 실행(결과 파일이 이미 있으면 그 파일을 읽음) ================================================
    def load_or_run_as_is_episode(self, scenario, simulation_seed):
        run_folder_name = RECORD_FILE_NAMES['as_is_test_run_folder'].format(
            scenario=scenario, simulation_seed=simulation_seed)
        run_folder = self.output_folder / RECORD_FILE_NAMES['as_is_test_folder'] / run_folder_name
        metrics_file = run_folder / export.RESULT_FILE_NAMES['metrics']
        if metrics_file.exists():
            return json.loads(metrics_file.read_text(encoding='utf-8'))
        wait_for_available_memory()
        episode_result = episode_procedure.run_as_is_episode(
            self.conditions_by_scenario[scenario], simulation_seed)
        metrics = episode_result['metrics']
        metrics['scenario'] = scenario
        run_folder.mkdir(parents=True, exist_ok=True)
        metrics_file.write_text(json.dumps(metrics, ensure_ascii=False), encoding='utf-8')
        return metrics

    def run_as_is_episodes(self):
        for scenario in scenario_conditions.SCENARIO_NAMES:
            for simulation_seed in self.test_seeds:
                self.as_is_metrics.append(
                    self.load_or_run_as_is_episode(scenario, simulation_seed))

    # ================================================ 판정 기록: 시험 실행 결과, 시나리오별 판정과 전체 판정, 통합 단계의 실행·학습 기록 저장 ================================================
    def save_test_verdict_and_log(self):
        test_file = self.output_folder / RECORD_FILE_NAMES['test_episodes']
        with open(test_file, 'w', encoding='utf-8') as record_file:
            for metrics in self.test_metrics:
                record = dict(metrics)
                record['run_type'] = TEST_RUN_TYPE
                record_file.write(json.dumps(record, ensure_ascii=False) + '\n')
        verdict = {
            'tolerance': self.tolerance,
            'test_seeds': self.test_seeds,
            'quick_check': self.quick_check,
            'process_start_teaching': self.process_start_teaching,
            'minimum_start_judgment_changed_episodes': (
                self.minimum_start_judgment_changed_episodes),
            'scenarios': {},
        }
        for scenario in scenario_conditions.SCENARIO_NAMES:
            verdict['scenarios'][scenario] = scenario_test_verdict(
                records_of_scenario(self.test_metrics, scenario),
                records_of_scenario(self.as_is_metrics, scenario),
                self.tolerance)
        verdict['pass'] = all(
            scenario_verdict['pass'] for scenario_verdict in verdict['scenarios'].values())
        write_json_file(self.output_folder / RECORD_FILE_NAMES['integration_log'], {
            'collected_episodes': self.collected_episodes,
            'fit_records': self.fit_records,
            'scenario_models': self.scenario_models,
            'integration_initial_model': self.integration_initial_model,
            'finished': time.strftime(TIME_FORMATS['finished_time']),
        })
        write_json_file(self.output_folder / RECORD_FILE_NAMES['test_verdict'], verdict)
        print(json.dumps(verdict, ensure_ascii=False))


# ================================================ 실행: 명령줄 첫 단어로 실행 종류 선택(없으면 시나리오 학습, integrate는 시나리오별 모델 통합, all은 학습과 통합을 순서대로) ================================================
def main():
    if len(sys.argv) > 1 and sys.argv[1] == INTEGRATE_COMMAND:
        sys.argv.pop(1)
        integrate_scenario_models()
    elif len(sys.argv) > 1 and sys.argv[1] == TRAIN_AND_INTEGRATE_COMMAND:
        sys.argv.pop(1)
        train_and_integrate()
    else:
        train_scenario_model()


if __name__ == '__main__':
    main()
