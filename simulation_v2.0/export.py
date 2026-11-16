import csv
import json
from pathlib import Path

import numpy

from aas_preprocessing.aas_reader import SECONDS_PER_DAY, SECONDS_PER_HOUR
from reinforcement_learning import action, reward


# ================================================ 결과 파일 이름 ================================================
RESULT_FILE_NAMES = {
    'metrics': 'metrics.json',
    'episode': 'episode.json',
    'decisions': 'decisions.csv',
}


# ================================================ 결과 표시 자릿수: 시간(시간 단위), 지금 착수할 때의 부담, 작업 우선순위 가중치, 가치, 구간 보상 ================================================
ROUND_DECIMALS = {
    'hours': 3,
    'burden': 4,
    'priority_weight': 4,
    'value': 5,
    'reward': 6,
}


# ================================================ 결정 기록 파일(decisions.csv)의 열: 결정 시각, 공정 착수 행동, 작업 우선순위 가중치(특징 이름 순서), 가치, 구간 보상 ================================================
DECISION_CSV_COLUMNS = (
    ['sec', 'process_start_action'] + action.PRIORITY_FEATURES + ['value', 'reward'])


# ================================================ 강화학습 모델 없이 실행한 결과에 적는 실행 모드 이름, JSON 파일 들여쓰기 ================================================
AS_IS_MODE = 'as_is'
JSON_INDENT = 2


# ================================================ 결과 표시용 시간 변환: 초 → 시간, 초 → 하루 중 시각(시간) ================================================
def seconds_to_hours(seconds):
    return seconds / SECONDS_PER_HOUR


def seconds_to_hour_of_day(seconds):
    return round(seconds % SECONDS_PER_DAY / SECONDS_PER_HOUR, ROUND_DECIMALS['hours'])


# ================================================ 결과 수집: 생산 완료 여부와 시각, 근무시간, 제품별 목표 달성 시각과 생산량 ================================================
def production_and_time_metrics(completion_sec, end_sec, work_time_sec, completion_sec_by_product,
                                production_quantity_by_product):
    completion_hours_by_product = {}
    for product, product_completion_sec in completion_sec_by_product.items():
        if product_completion_sec is None:
            completion_hours_by_product[product] = None
        else:
            completion_hours_by_product[product] = seconds_to_hours(float(product_completion_sec))
    return {
        'complete': completion_sec is not None,
        'completion_sec': completion_sec,
        'end_sec': end_sec,
        'completion_hours': seconds_to_hours(end_sec),
        'work_hours': seconds_to_hours(work_time_sec),
        'completion_hours_by_product': completion_hours_by_product,
        'production_quantity_by_product': dict(production_quantity_by_product),
    }


# ================================================ 결과 수집: 종료 시점 전력량(시간대 가중, 가중 없음, 피크타임)과 SMT·조립·기저부하별 전력량 ================================================
def energy_metrics(energy_account, energy_by_line_type):
    metrics = {
        'weighted_kwh': energy_account['weighted_kwh'],
        'physical_kwh': energy_account['physical_kwh'],
        'peak_kwh': energy_account['peak_kwh'],
        'smt_peak_kwh': energy_account['smt_peak_kwh'],
        'smt_physical_kwh': energy_account['smt_physical_kwh'],
    }
    metrics.update(energy_by_line_type)
    return metrics


# ================================================ 결과 수집: 보상 항목과 합계, 생산 시간 항목을 근무시간 대신 종료 시각으로 계산한 합계 ================================================
def total_reward_by_completion_time(reward_items, end_sec):
    reward_items_by_completion_time = dict(reward_items)
    reward_items_by_completion_time['production_time'] = reward.production_time_reward(
        reward.REWARD_WEIGHTS['production_time'], float(end_sec),
        reward.REWARD_NORMALIZATION_DENOMINATORS['production_time'])
    return sum(reward_items_by_completion_time.values())


def reward_metrics(final_reward_items):
    return {
        'reward_items': final_reward_items,
        'total_reward': sum(final_reward_items.values()),
    }


# ================================================ 결과 수집: 구간 보상 합, 첫 결정의 누적 보상, 결정 횟수 ================================================
def decision_metrics(decisions, decision_counts):
    interval_rewards = [decision['reward'] for decision in decisions]
    if decisions:
        first_decision_cumulative_reward = decisions[0]['cumulative_reward']
    else:
        first_decision_cumulative_reward = None
    return {
        'interval_reward_sum': float(sum(interval_rewards)),
        'first_decision_cumulative_reward': first_decision_cumulative_reward,
        'priority_decision_count': decision_counts[action.PRIORITY_DECISION],
        'start_timing_decision_count': decision_counts[action.START_TIMING_DECISION],
        'priority_weights_decision_count': len(decisions),
    }


# ================================================ 결과 수집: 에피소드 시작 때 정한 공정 착수 기준값과 그때의 행동·가치 ================================================
def process_start_decision_metrics(process_start_decision):
    if process_start_decision is None:
        process_start_decision = {}
    return {
        'process_start_threshold': process_start_decision.get('process_start_threshold'),
        'process_start_threshold_at_mean': process_start_decision.get(
            'process_start_threshold_at_mean'),
        'process_start_action': process_start_decision.get('process_start_action'),
        'process_start_action_mean': process_start_decision.get('mean'),
        'process_start_value': process_start_decision.get('value'),
        'start_judgment_changed_by_exploration': bool(
            process_start_decision.get('start_judgment_changed_by_exploration')),
        'start_judgment_changed_count': process_start_decision.get(
            'start_judgment_changed_count', 0),
    }


# ================================================ 결과 수집: SMT 생산 묶음별 착수 기록, 착수를 보류한 묶음, 착수 판단 횟수 ================================================
def rounded_first_burden(start_timing_record):
    first_burden = float(start_timing_record.get('first_burden') or 0.0)
    return round(first_burden, ROUND_DECIMALS['burden'])


def start_timing_metrics(start_timing_records, start_timing_judgments):
    delayed_starts = []
    smt_lot_starts = []
    for start_timing_record in start_timing_records:
        request_sec = start_timing_record['start_sec']
        start_sec_after_delay = start_timing_record.get('start_sec_after_delay', request_sec)
        start_delay_hours = round(
            seconds_to_hours(start_timing_record['start_delay_sec']), ROUND_DECIMALS['hours'])
        first_burden = rounded_first_burden(start_timing_record)
        smt_lot_starts.append({
            'smt_line': start_timing_record['smt_line'],
            'request_hour_of_day': seconds_to_hour_of_day(request_sec),
            'start_hour_of_day': seconds_to_hour_of_day(start_sec_after_delay),
            'start_delay_hours': start_delay_hours,
            'first_burden': first_burden,
        })
        if start_timing_record['start_delay_sec'] > 0:
            delayed_starts.append({
                'smt_line': start_timing_record['smt_line'],
                'request_hours': round(seconds_to_hours(request_sec), ROUND_DECIMALS['hours']),
                'request_hour_of_day': seconds_to_hour_of_day(request_sec),
                'start_delay_hours': start_delay_hours,
                'first_burden': first_burden,
            })
    delayed_start_hours = [delayed_start['start_delay_hours'] for delayed_start in delayed_starts]
    delayed_starts_without_burden = []
    for delayed_start in delayed_starts:
        if delayed_start['first_burden'] <= 0.0:
            delayed_starts_without_burden.append(delayed_start)
    judgments_without_emission_record = []
    for start_timing_judgment in start_timing_judgments:
        if start_timing_judgment['burden_basis'] == action.BURDEN_BASIS['no_record']:
            judgments_without_emission_record.append(start_timing_judgment)
    return {
        'delayed_start_count': len(delayed_starts),
        'delayed_start_hours_total': sum(delayed_start_hours),
        'delayed_starts': delayed_starts,
        'smt_lot_starts': smt_lot_starts,
        'delayed_starts_without_burden': len(delayed_starts_without_burden),
        'start_timing_judgment_count': len(start_timing_judgments),
        'start_timing_judgments_without_emission_record': len(judgments_without_emission_record),
    }


# ================================================ 결과 수집: 작업자 그룹별 유휴시간, PCB 부족으로 작업을 못 한 구간 ================================================
def worker_idle_and_pcb_shortage_metrics(worker_idle_time_sec_by_worker_group,
                                         pcb_shortage_wait_records):
    worker_idle_hours_by_worker_group = {}
    for worker_group, idle_time_sec in worker_idle_time_sec_by_worker_group.items():
        worker_idle_hours_by_worker_group[worker_group] = seconds_to_hours(float(idle_time_sec))
    pcb_shortage_work_time_sec = []
    for pcb_shortage_wait_record in pcb_shortage_wait_records:
        pcb_shortage_work_time_sec.append(float(pcb_shortage_wait_record['work_time_sec']))
    return {
        'worker_idle_hours_total': sum(worker_idle_hours_by_worker_group.values()),
        'worker_idle_hours_by_worker_group': worker_idle_hours_by_worker_group,
        'pcb_shortage_wait_count': len(pcb_shortage_wait_records),
        'pcb_shortage_wait_work_hours': seconds_to_hours(sum(pcb_shortage_work_time_sec)),
    }


# ================================================ 결과 수집: 작업 우선순위 가중치 평균 ================================================
def mean_priority_weights(decisions):
    if not decisions:
        return None
    priority_weights_by_decision = [decision['priority_weights'] for decision in decisions]
    return numpy.mean(priority_weights_by_decision, axis=0).tolist()


# ================================================ 강화학습 모델로 실행한 에피소드의 결과 수집: 위 구역의 결과를 차례로 합침 ================================================
def collect_episode_metrics(
        simulation_seed, mode, completion_sec, end_sec, work_time_sec, completion_sec_by_product,
        production_quantity_by_product, energy_account, energy_by_line_type, final_reward_items,
        decisions, decision_counts, process_start_decision, start_timing_records,
        start_timing_judgments, worker_idle_time_sec_by_worker_group, pcb_shortage_wait_records,
        recorded_start_time_slot_count, run_wall_clock_sec):
    metrics = {'seed': simulation_seed, 'mode': mode}
    metrics.update(production_and_time_metrics(
        completion_sec, end_sec, work_time_sec, completion_sec_by_product,
        production_quantity_by_product))
    metrics.update(energy_metrics(energy_account, energy_by_line_type))
    metrics.update(reward_metrics(final_reward_items))
    metrics.update(decision_metrics(decisions, decision_counts))
    metrics.update(process_start_decision_metrics(process_start_decision))
    metrics.update(start_timing_metrics(start_timing_records, start_timing_judgments))
    metrics.update(worker_idle_and_pcb_shortage_metrics(
        worker_idle_time_sec_by_worker_group, pcb_shortage_wait_records))
    metrics['mean_priority_weights'] = mean_priority_weights(decisions)
    metrics['recorded_start_time_slot_count'] = recorded_start_time_slot_count
    metrics['run_wall_clock_sec'] = run_wall_clock_sec
    metrics['total_reward_by_completion_time'] = total_reward_by_completion_time(
        final_reward_items, end_sec)
    return metrics


# ================================================ 강화학습 모델 없이 실행한 에피소드(As-is, 선입선출)의 결과 수집: smt_peak_kwh는 지금 결과와 같이 SMT 설비만의 피크타임 전력량(강화학습 모델 실행의 결과에서는 SMT 공정까지 더한 값) ================================================
def collect_as_is_metrics(
        simulation_seed, completion_sec, end_sec, work_time_sec, completion_sec_by_product,
        production_quantity_by_product, energy_account, energy_by_line_type, final_reward_items,
        worker_idle_time_sec_by_worker_group, pcb_shortage_wait_records, run_wall_clock_sec):
    metrics = {'seed': simulation_seed, 'mode': AS_IS_MODE}
    metrics.update(production_and_time_metrics(
        completion_sec, end_sec, work_time_sec, completion_sec_by_product,
        production_quantity_by_product))
    metrics.update(energy_metrics(energy_account, energy_by_line_type))
    metrics['smt_peak_kwh'] = energy_account['smt_peak_kwh']
    metrics.update(reward_metrics(final_reward_items))
    metrics.update(worker_idle_and_pcb_shortage_metrics(
        worker_idle_time_sec_by_worker_group, pcb_shortage_wait_records))
    metrics['run_wall_clock_sec'] = run_wall_clock_sec
    metrics['total_reward_by_completion_time'] = total_reward_by_completion_time(
        final_reward_items, end_sec)
    return metrics


# ================================================ 시뮬레이션 모델의 누적 값 요약(API가 읽는 키): 생산량, 전력량, 목표 달성 시각, 불량·수리 횟수, 작업자 유휴시간 ================================================
def environment_summary(simulation_model):
    completion_sec_by_product = {}
    for product, completion_sec in simulation_model.completion_sec_by_product.items():
        if completion_sec is None:
            completion_sec_by_product[product] = None
        else:
            completion_sec_by_product[product] = float(completion_sec)
    machine_energy = {}
    for machine_name, weighted_kwh in simulation_model.machine_weighted_energy_kwh.items():
        machine_energy[machine_name] = float(weighted_kwh)
    machine_line_energy = {}
    machine_energy_by_worker_group = simulation_model.machine_weighted_energy_kwh_by_worker_group
    for machine_name, weighted_kwh_by_worker_group in machine_energy_by_worker_group.items():
        machine_line_energy[machine_name] = {}
        for worker_group, weighted_kwh in weighted_kwh_by_worker_group.items():
            machine_line_energy[machine_name][worker_group] = float(weighted_kwh)
    line_energy = {}
    process_energy_by_worker_group = simulation_model.process_weighted_energy_kwh_by_worker_group
    for worker_group, weighted_kwh in process_energy_by_worker_group.items():
        line_energy[worker_group] = float(weighted_kwh)
    worker_idle_time_sec = simulation_model.worker_idle_time_sec_by_worker_group
    idle_time_sec_per_worker = {}
    for worker_group, idle_time_sec in worker_idle_time_sec.items():
        worker_count = simulation_model.worker_groups[worker_group]['worker_count']
        idle_time_sec_per_worker[worker_group] = float(idle_time_sec) / worker_count
    return {
        'Throughput': dict(simulation_model.production_quantity_by_product),
        'makespan_sec': float(simulation_model.simpy_environment.now),
        'EpisodeEnergyKwh': float(simulation_model.total_weighted_energy_kwh()),
        'ActivePremiumKwh': float(simulation_model.process_weighted_energy_kwh),
        'IdleEnergyKwh': float(simulation_model.base_load_weighted_energy_kwh()),
        'MachineEnergyKwh': float(sum(machine_energy.values())),
        'MachineEnergy': machine_energy,
        'MachineLineEnergy': machine_line_energy,
        'CompletionSec': completion_sec_by_product,
        'DefectCount': dict(simulation_model.defect_count_by_product),
        'RMACount': dict(simulation_model.repair_count_by_product),
        'LineEnergy': line_energy,
        'LineIdleTime': idle_time_sec_per_worker,
        'TotalIdleTime': float(sum(worker_idle_time_sec.values())),
    }


# ================================================ 결정 기록을 짧은 행으로: 결정 시각(시간), 작업 우선순위 가중치, 가치, 구간 보상 ================================================
def decision_records(decisions):
    records = []
    for decision in decisions:
        record = [round(seconds_to_hours(decision['sec']), ROUND_DECIMALS['hours'])]
        for priority_weight in decision['priority_weights']:
            record.append(round(float(priority_weight), ROUND_DECIMALS['priority_weight']))
        record.append(round(decision['value'], ROUND_DECIMALS['value']))
        record.append(round(decision['reward'], ROUND_DECIMALS['reward']))
        records.append(record)
    return records


# ================================================ 실행 결과 파일 저장: 결과(metrics.json), 결과와 결정 기록 전체(episode.json), 결정 시각별 행동 표(decisions.csv) ================================================
def to_json_value(value):
    if isinstance(value, numpy.ndarray):
        return value.tolist()
    if isinstance(value, numpy.generic):
        return value.item()
    if hasattr(value, 'detach'):
        return value.detach().cpu().tolist()
    raise TypeError(type(value).__name__)


def decision_csv_row(decision):
    row = {
        'sec': decision['sec'],
        'process_start_action': decision['process_start_action'],
        'value': decision['value'],
        'reward': decision['reward'],
    }
    priority_weights = decision['priority_weights']
    for feature_name, priority_weight in zip(action.PRIORITY_FEATURES, priority_weights):
        row[feature_name] = priority_weight
    return row


def save_episode_files(output_folder, metrics, decisions, process_start_decision,
                       edge_connections):
    output_folder = Path(output_folder)
    output_folder.mkdir(parents=True, exist_ok=True)
    metrics_text = json.dumps(
        metrics, ensure_ascii=False, indent=JSON_INDENT, default=to_json_value)
    (output_folder / RESULT_FILE_NAMES['metrics']).write_text(metrics_text, encoding='utf-8')
    episode = {
        'metrics': metrics,
        'decisions': list(decisions),
        'process_start_decision': process_start_decision,
        'edge_connections': edge_connections,
    }
    episode_text = json.dumps(episode, ensure_ascii=False, default=to_json_value)
    (output_folder / RESULT_FILE_NAMES['episode']).write_text(episode_text, encoding='utf-8')
    decisions_file = output_folder / RESULT_FILE_NAMES['decisions']
    with decisions_file.open('w', encoding='utf-8-sig', newline='') as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=DECISION_CSV_COLUMNS)
        writer.writeheader()
        for decision in decisions:
            writer.writerow(decision_csv_row(decision))
    return output_folder
