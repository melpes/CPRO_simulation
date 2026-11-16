import argparse

import episode_procedure
import export
import scenario_conditions
from reinforcement_learning import action, model


# ================================================ 평가 실행 기본 설정: 저장된 모델 파일, 시나리오, 시뮬레이션 난수 seed, 평가 모드에서 쓰이지 않는 탐색 난수 seed, 착수 시점별 배출량 기록을 갱신하지 않음 ================================================
EVALUATION_SETTINGS = {
    'model_file': model.DEFAULT_MODEL_FILE,
    'scenario': 'S1',
    'simulation_seed': 98102105,
    'exploration_seed': 0,
    'update_start_timing_emission_record': False,
}


# ================================================ 실행 뒤 화면에 보이는 결과 항목 ================================================
PRINTED_METRICS = ['complete', 'completion_sec', 'weighted_kwh']


# ================================================ 명령줄 입력: 모델 파일, 시나리오, seed, 결과 폴더, As-is 실행 여부, 제품별 생산 수량(주지 않으면 시나리오 조건의 값) ================================================
def read_command_line_arguments():
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument('--model-file', default=EVALUATION_SETTINGS['model_file'])
    argument_parser.add_argument(
        '--scenario', choices=scenario_conditions.SCENARIO_NAMES,
        default=EVALUATION_SETTINGS['scenario'])
    argument_parser.add_argument(
        '--seed', type=int, default=EVALUATION_SETTINGS['simulation_seed'])
    argument_parser.add_argument('--output-folder', required=True)
    argument_parser.add_argument('--as-is', action='store_true')
    argument_parser.add_argument('--production-quantity-per-product', type=int, default=None)
    return argument_parser.parse_args()


# ================================================ 저장된 강화학습 모델로 시나리오 1회 실행(평가 모드) ================================================
def evaluate_saved_model(model_file, conditions, simulation_seed):
    loaded = episode_procedure.load_reinforcement_learning_model(model_file, conditions)
    return episode_procedure.run_episode(
        conditions, simulation_seed, loaded['reinforcement_learning_model'],
        loaded['start_timing_emission_record'], action.EVALUATION_MODE,
        EVALUATION_SETTINGS['exploration_seed'],
        EVALUATION_SETTINGS['update_start_timing_emission_record'])


# ================================================ 실행: 시나리오 조건 조회 → 저장된 모델 평가 실행 또는 As-is 실행 → 결과 파일 저장 → 결과 요약 출력 ================================================
def main():
    arguments = read_command_line_arguments()
    conditions = scenario_conditions.conditions_of_scenario(arguments.scenario)
    if arguments.production_quantity_per_product is not None:
        conditions['production_quantity_per_product'] = (
            arguments.production_quantity_per_product)
    if arguments.as_is:
        episode_result = episode_procedure.run_as_is_episode(conditions, arguments.seed)
        decisions = []
        process_start_decision = None
        edge_connections = None
    else:
        episode_result = evaluate_saved_model(arguments.model_file, conditions, arguments.seed)
        decisions = episode_result['decisions']
        process_start_decision = episode_result['process_start_decision']
        edge_connections = episode_result['edge_connections']
    metrics = episode_result['metrics']
    metrics['scenario'] = arguments.scenario
    export.save_episode_files(
        arguments.output_folder, metrics, decisions, process_start_decision, edge_connections)
    printed_metrics = {}
    for metric_name in PRINTED_METRICS:
        printed_metrics[metric_name] = metrics[metric_name]
    print(printed_metrics)


if __name__ == '__main__':
    main()
