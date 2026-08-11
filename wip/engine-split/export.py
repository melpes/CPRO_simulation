from __future__ import annotations

import json
import math
import os
from typing import Any, Callable, Dict, List

import carbon

SAMPLE_SEC = 600


class RecordingWarehouse:
    def __init__(self, inner, clock: Callable[[], float]):
        self._inner = inner
        self._clock = clock
        self.events: List[dict] = []
        self.by_item: Dict[str, dict] = {}
        self._code_of: Dict[int, str] = {}
        for category in inner.inventory.values():
            for code, item in category.items():
                self._code_of[id(item)] = code
                self.by_item[code] = {
                    'lowest_present_stock': float(item.present_stock),
                    'stockout_count'     : 0,
                    'total_consumed'     : 0.0,
                    'total_arrived'      : 0.0,
                }

    @property
    def inventory(self):
        return self._inner.inventory

    @property
    def main(self):
        return getattr(self._inner, 'main', self._inner)

    def _stat(self, code: str) -> dict:
        return self.by_item.setdefault(code, {
            'lowest_present_stock': float('inf'), 'stockout_count': 0,
            'total_consumed': 0.0, 'total_arrived': 0.0})

    def _present(self, code: str):
        for category in self._inner.inventory.values():
            if code in category:
                return category[code].present_stock
        return None

    def consume(self, InputBOM: dict, deduct: bool = True) -> list:
        before = {code: self._present(code) for code in InputBOM}
        ordered = self._inner.consume(InputBOM, deduct)
        now = float(self._clock())
        for code, quantity in InputBOM.items():
            after = self._present(code)
            stat = self._stat(code)
            stat['total_consumed'] += quantity
            if after is not None:
                stat['lowest_present_stock'] = min(stat['lowest_present_stock'], float(after))
                if before[code] is not None and before[code] > 0 >= after:
                    stat['stockout_count'] += 1
            self.events.append({'item_code': code, 't_sec': now, 'type': 'consume',
                                'qty': -float(quantity),
                                'present_stock': None if after is None else float(after)})
        for item in ordered:
            code = self._code_of.get(id(item))
            if code is not None:
                self.events.append({'item_code': code, 't_sec': now, 'type': 'order',
                                    'qty': 0.0, 'present_stock': float(item.present_stock)})
        return ordered

    def produce(self, OutputBOM: dict) -> None:
        self._inner.produce(OutputBOM)
        now = float(self._clock())
        for code, quantity in OutputBOM.items():
            self._stat(code)['total_arrived'] += quantity
            after = self._present(code)
            self.events.append({'item_code': code, 't_sec': now, 'type': 'produce',
                                'qty': float(quantity),
                                'present_stock': None if after is None else float(after)})

    def replenish(self, env, ReplenishLeadDay, items, notify=None):
        before = {id(item): item.present_stock for item in items}
        yield from self._inner.replenish(env, ReplenishLeadDay, items, notify)
        now = float(self._clock())
        for item in items:
            code = self._code_of.get(id(item))
            if code is None:
                continue
            delta = item.present_stock - before[id(item)]
            if delta:
                self._stat(code)['total_arrived'] += delta
                self.events.append({'item_code': code, 't_sec': now, 'type': 'arrive',
                                    'qty': float(delta), 'present_stock': float(item.present_stock)})


def _overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


def _union_len(intervals) -> float:
    if not intervals:
        return 0.0
    ordered = sorted(intervals)
    total = 0.0
    current_start, current_end = ordered[0]
    for start, end in ordered[1:]:
        if start > current_end:
            total += current_end - current_start
            current_start, current_end = start, end
        else:
            current_end = max(current_end, end)
    return total + (current_end - current_start)


def _is_terminal(env, process_code: str) -> bool:
    return process_code not in env.KnowledgeGraph.edges


def _grid(makespan: float, sample_sec: int):
    bucket_count = max(1, math.ceil(makespan / sample_sec))
    grid = []
    for i in range(bucket_count):
        low  = i * sample_sec
        high = min((i + 1) * sample_sec, makespan)
        grid.append((low, high, (low + high) / 2.0))
    return grid


def build_payload(env, summary: Dict[str, Any], *, sample_sec: int = SAMPLE_SEC) -> Dict[str, Any]:
    KnowledgeGraph = env.KnowledgeGraph
    events    = list(getattr(env, 'events', []))
    makespan  = float(summary.get('makespan_sec')
                      or max((event['end_sec'] for event in events), default=0.0))
    target    = {model_id: int(quantity) for model_id, quantity in env.target_qty.items()}
    total_target = sum(target.values()) or 1
    throughput = {model_id: int(v) for model_id, v in (summary.get('Throughput') or env.Throughput).items()}
    base_power_kw = env.DefaultProcessConsumedPowerKw
    smt_events = list(getattr(env, 'smt_events', []))

    def _in_work(t: float) -> bool:
        sec_in_day = t % 86400.0
        return (env.WorkStartTime <= sec_in_day < env.WorkEndTime
                and not (env.break_start_sec <= sec_in_day < env.break_end_sec))

    # 워커 가동/유휴 집계
    busy: Dict[str, dict] = {}
    line_intervals: Dict[str, list] = {}
    for event in events:
        bucket = busy.setdefault(event['workstation'], {'q': 0, 'busy_sec': 0.0})
        bucket['q'] += 1
        bucket['busy_sec'] += event['end_sec'] - event['start_sec']
        line_intervals.setdefault(event['workstation'], []).append((event['start_sec'], event['end_sec']))
    workers = {}
    for ws, info in env.workers.items():
        worker_count = info['worker_count']
        capacity = worker_count * makespan or 1.0
        busy_sec = busy.get(ws, {}).get('busy_sec', 0.0)
        idle = max(0.0, capacity - busy_sec)
        operating_sec = _union_len(line_intervals.get(ws, []))
        workers[ws] = {'worker_count': worker_count,
                       'processed_quantity': busy.get(ws, {}).get('q', 0),
                       'operating_sec': round(operating_sec, 1),
                       'operating_ratio': round(operating_sec / makespan, 4) if makespan else 0.0,
                       'idle_sec': round(idle, 1),
                       'idle_ratio': round(idle / capacity, 4) if capacity else 0.0}

    # 모델별 실제 납기일 (마지막 종단 공정 완료시각)
    terminal_end: Dict[str, float] = {}
    for event in events:
        if _is_terminal(env, event['process_code']):
            terminal_end[event['model']] = max(terminal_end.get(event['model'], 0.0), event['end_sec'])
    actual_due_day = {model_id: math.ceil(terminal_end[model_id] / 86400.0) for model_id in terminal_end}

    # 유닛 구간 (WIP 계산용)
    unit_span: Dict[Any, dict] = {}
    for event in events:
        unit = unit_span.setdefault(event.get('unit_id', id(event)),
                                    {'start': event['start_sec'], 'end': 0.0})
        unit['start'] = min(unit['start'], event['start_sec'])
        if _is_terminal(env, event['process_code']):
            unit['end'] = max(unit['end'], event['end_sec'])
    units = list(unit_span.values())

    # 시계열 — 완료·WIP·순간전력·누적에너지
    grid = _grid(makespan, sample_sec)
    t_series, cumulative_completed, completion_ratio, wip, active_workers = [], [], [], [], []
    line_active: Dict[str, list] = {ws: [] for ws in env.workers}
    instant_power, cumulative_energy = [], []
    # 버킷별 에너지 분해 — 기저(공장 기저전력) / SMT / 라인별 조립. 셋의 합이 cumulative_energy 증가분.
    idle_energy, smt_energy = [], []
    line_energy: Dict[str, list] = {ws: [] for ws in env.workers}
    # 버킷별 라인 작업자 1인당 평균 유휴시간(초) — 근무시간 기준
    line_idle_per_worker: Dict[str, list] = {ws: [] for ws in env.workers}
    running_energy = 0.0
    for low, high, mid in grid:
        t_series.append(round(high, 1))
        done = sum(1 for event in events
                   if _is_terminal(env, event['process_code']) and event['end_sec'] <= high)
        cumulative_completed.append(done)
        completion_ratio.append(round(done / total_target, 4))
        wip.append(sum(1 for unit in units if unit['start'] <= high and not (unit['end'] and unit['end'] <= high)))
        per_line = {ws: 0 for ws in env.workers}
        for event in events:
            if event['start_sec'] <= mid < event['end_sec']:
                per_line[event['workstation']] = per_line.get(event['workstation'], 0) + 1
        for ws in line_active:
            line_active[ws].append(per_line.get(ws, 0))
        active_workers.append(sum(per_line.values()))

        premium_power = 0.0
        for event in events:
            if event['start_sec'] <= mid < event['end_sec']:
                premium_power += KnowledgeGraph.nodes[event['process_code']].RatedPowerKw
        smt_power = sum(s['power_kw'] for s in smt_events if s['start_sec'] <= mid < s['end_sec'])
        instant_power.append(round((base_power_kw if _in_work(mid) else 0.0) + premium_power + smt_power, 3))

        bucket_idle_kwh = base_power_kw * (env._work_elapsed(high) - env._work_elapsed(low)) / 3600.0
        bucket_premium_kwh = 0.0
        bucket_line_kwh  = {ws: 0.0 for ws in env.workers}
        bucket_line_busy = {ws: 0.0 for ws in env.workers}
        for event in events:
            overlap = _overlap(event['start_sec'], event['end_sec'], low, high)
            if not overlap:
                continue
            energy = overlap * KnowledgeGraph.nodes[event['process_code']].RatedPowerKw / 3600.0
            bucket_premium_kwh += energy
            ws = event['workstation']
            bucket_line_kwh[ws]  = bucket_line_kwh.get(ws, 0.0) + energy
            bucket_line_busy[ws] = bucket_line_busy.get(ws, 0.0) + overlap
        bucket_smt_kwh = sum(_overlap(s['start_sec'], s['end_sec'], low, high) * s['power_kw'] / 3600.0
                             for s in smt_events)
        running_energy += bucket_idle_kwh + bucket_premium_kwh + bucket_smt_kwh
        cumulative_energy.append(round(running_energy, 4))

        idle_energy.append(round(bucket_idle_kwh, 4))
        smt_energy.append(round(bucket_smt_kwh, 4))
        bucket_work_sec = env._work_elapsed(high) - env._work_elapsed(low)     # 버킷 내 근무시간
        for ws, info in env.workers.items():
            line_energy[ws].append(round(bucket_line_kwh.get(ws, 0.0), 4))
            worker_count = info['worker_count'] or 1
            per_worker_busy = bucket_line_busy.get(ws, 0.0) / worker_count
            line_idle_per_worker[ws].append(round(max(0.0, bucket_work_sec - per_worker_busy), 1))

    # 에너지 총량 (유휴/가동/SMT 분해)
    total_kwh   = float(summary.get('EpisodeEnergyKwh') or 0.0)
    premium_kwh = float(summary.get('ActivePremiumKwh') or 0.0)
    smt_kwh     = float(getattr(env, 'SMTEnergyKwh', 0.0))
    idle_kwh    = max(0.0, total_kwh - premium_kwh - smt_kwh)
    active_kwh  = total_kwh - idle_kwh

    # 창고 품목별 집계
    warehouse = env.warehouse
    warehouse_by_item = {}
    for code, stat in getattr(warehouse, 'by_item', {}).items():
        low = stat.get('lowest_present_stock')
        warehouse_by_item[code] = {**stat,
                                   'lowest_present_stock': None if low in (float('inf'), float('-inf')) else low}
    warehouse_events = getattr(warehouse, 'events', [])

    return {
        'meta': {
            'sample_sec'   : sample_sec,
            'makespan_sec' : round(makespan, 1),
            'makespan_days': round(makespan / 86400.0, 3),
            'scenario_mode': getattr(env, 'ScenarioMode', 'FINITE'),
        },
        'productivity': {
            'kpi': {
                'makespan_sec'  : round(makespan, 1),
                'throughput'    : throughput,
                'order_quantity': target,
                'due_day'       : {model_id: round(env.DueDay[model_id] / 86400.0) for model_id in target},
                'actual_due_day': actual_due_day,
            },
            'by_entity': {
                'workers'            : workers,
                'warehouse_by_item'  : warehouse_by_item,
                'equipment_op_time'  : getattr(env, 'smt_op_time', {}),
            },
            'events': {
                'schedule'  : events,
                'warehouse' : warehouse_events,
                'equipment' : smt_events,
            },
            'timeseries': {
                'sample_sec'         : sample_sec,
                't_sec'              : t_series,
                'cumulative_completed': cumulative_completed,
                'completion_ratio'   : completion_ratio,
                'wip'                : wip,
                'active_workers'     : active_workers,
                'line_active_workers': line_active,
                'line_idle_sec_per_worker': line_idle_per_worker,
            },
        },
        'carbon': {
            'kpi': {
                'total_power_kwh'    : round(total_kwh, 2),
                'idle_power_kwh'     : round(idle_kwh, 2),
                'active_power_kwh'   : round(active_kwh, 2),
                'total_carbon_kgco2e': round(carbon.TotalEmission(total_kwh), 2),
            },
            'timeseries': {
                'sample_sec'           : sample_sec,
                't_sec'                : t_series,
                'instant_power_kw'     : instant_power,
                'cumulative_energy_kwh': cumulative_energy,
                'idle_energy_kwh'      : idle_energy,      # 버킷별 기저부하
                'smt_energy_kwh'       : smt_energy,       # 버킷별 SMT
                'line_energy_kwh'      : line_energy,      # 버킷별 라인 조립
            },
        },
    }


def write_json(payload: Dict[str, Any], path: str) -> str:
    os.makedirs(os.path.dirname(os.path.abspath(path)) or '.', exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return path


def send(payload: Dict[str, Any]) -> None:
    raise NotImplementedError('export.send: 외부 API 계약 미정')
