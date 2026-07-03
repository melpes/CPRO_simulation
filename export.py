# -*- coding: utf-8 -*-
"""추론(deploy) 실행 산출물 가공·출력.

학습이 아니라 학습완료→deploy된 정책을 run_trained 로 1회 실행할 때, 그 스케줄 결과를
KETI/TELOS/BI 가 받을 구조화 페이로드(생산성/탄소 × KPI·집계·이벤트·시계열)로 가공한다.

데이터 출처(시뮬 본체 무수정):
  - schedule 이벤트  : _ScheduleEnv 가 env.events 에 기록(workstation/model/process_code/start/end/unit_id)
  - warehouse 이벤트 : RecordingWarehouse(여기 정의) 프록시가 consume/produce/replenish 가로채 기록
  - 설비(SMT) 이벤트 : smt.py 훅 → env.smt_events / env.smt_op_time
  - 시계열·순간전력  : 위 이벤트에서 SAMPLE_SEC(10분) 그리드로 파생(라이브 샘플링 불필요)
"""
from __future__ import annotations

import json
import math
import os
from typing import Any, Callable, Dict, List

import carbon

SAMPLE_SEC = 600  # 시계열 샘플링 간격(초) = 10분


# ────────────────────────────────────────────────────────────────────────────
# 창고 기록 프록시 — 실 warehouse(Warehouse | _StockRouter)를 감싼다.
# _ScheduleEnv.reset 에서 env.warehouse 를 이걸로 교체. 학습 경로엔 설치하지 않는다.
# ────────────────────────────────────────────────────────────────────────────
class RecordingWarehouse:
    def __init__(self, inner, clock: Callable[[], float]):
        self._inner = inner
        self._clock = clock                      # () -> env.now
        self.events: List[dict] = []
        self.by_item: Dict[str, dict] = {}
        self._code_of: Dict[int, str] = {}       # id(StockItem) -> item_code (replenish 용)
        for cat in inner.inventory.values():
            for code, item in cat.items():
                self._code_of[id(item)] = code
                self.by_item[code] = {
                    'lowest_present_stock': float(item.present_stock),
                    'stockout_count'     : 0,
                    'total_consumed'     : 0.0,
                    'total_arrived'      : 0.0,
                }

    # env 가 warehouse.inventory 를 직접 읽는 경로(state_vec·Stock*Count) 위임
    @property
    def inventory(self):
        return self._inner.inventory

    @property
    def main(self):
        # W3/W4 카운트용 주창고 위임(_counted_warehouse) — 라우터면 main, 아니면 inner 자체
        return getattr(self._inner, 'main', self._inner)

    def _stat(self, code: str) -> dict:
        return self.by_item.setdefault(code, {
            'lowest_present_stock': float('inf'), 'stockout_count': 0,
            'total_consumed': 0.0, 'total_arrived': 0.0})

    def _present(self, code: str):
        for cat in self._inner.inventory.values():
            if code in cat:
                return cat[code].present_stock
        return None

    def consume(self, ProcessConsumedBOM: dict, deduct: bool = True) -> list:
        before = {code: self._present(code) for code in ProcessConsumedBOM}
        ordered = self._inner.consume(ProcessConsumedBOM, deduct)
        t = float(self._clock())
        for code, qty in ProcessConsumedBOM.items():
            after = self._present(code)
            st = self._stat(code)
            st['total_consumed'] += qty
            if after is not None:
                st['lowest_present_stock'] = min(st['lowest_present_stock'], float(after))
                if before[code] is not None and before[code] > 0 >= after:
                    st['stockout_count'] += 1
            self.events.append({'item_code': code, 't_sec': t, 'type': 'consume',
                                'qty': -float(qty),
                                'present_stock': None if after is None else float(after)})
        for item in ordered:                                   # 재주문 트리거
            code = self._code_of.get(id(item))
            if code is not None:
                self.events.append({'item_code': code, 't_sec': t, 'type': 'order',
                                    'qty': 0.0, 'present_stock': float(item.present_stock)})
        return ordered

    def produce(self, OutputBOM: dict) -> None:
        self._inner.produce(OutputBOM)
        t = float(self._clock())
        for code, qty in OutputBOM.items():
            self._stat(code)['total_arrived'] += qty
            after = self._present(code)
            self.events.append({'item_code': code, 't_sec': t, 'type': 'produce',
                                'qty': float(qty),
                                'present_stock': None if after is None else float(after)})

    def replenish(self, env, ReplenishLeadDay, items, notify=None):
        before = {id(it): it.present_stock for it in items}
        yield from self._inner.replenish(env, ReplenishLeadDay, items, notify)
        t = float(self._clock())
        for it in items:
            code = self._code_of.get(id(it))
            if code is None:
                continue
            delta = it.present_stock - before[id(it)]
            if delta:
                self._stat(code)['total_arrived'] += delta
                self.events.append({'item_code': code, 't_sec': t, 'type': 'arrive',
                                    'qty': float(delta), 'present_stock': float(it.present_stock)})


# ────────────────────────────────────────────────────────────────────────────
# 파생 헬퍼
# ────────────────────────────────────────────────────────────────────────────
def _overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


def _union_len(intervals) -> float:
    """겹치는 [start,end] 구간들의 합집합 길이 = 라인이 ≥1명 가동 중이던 wall-clock 시간."""
    if not intervals:
        return 0.0
    ivs = sorted(intervals)
    total = 0.0
    cs, ce = ivs[0]
    for s, e in ivs[1:]:
        if s > ce:
            total += ce - cs
            cs, ce = s, e
        else:
            ce = max(ce, e)
    return total + (ce - cs)


def _is_terminal(env, pc: str) -> bool:
    return pc not in env.KnowledgeGraph.edges


def _grid(makespan: float, sample_sec: int):
    n = max(1, math.ceil(makespan / sample_sec))
    out = []
    for i in range(n):
        lo = i * sample_sec
        hi = min((i + 1) * sample_sec, makespan)
        out.append((lo, hi, (lo + hi) / 2.0))
    return out


# ────────────────────────────────────────────────────────────────────────────
# 메인 — 완료된 env + summary → 구조화 페이로드
# ────────────────────────────────────────────────────────────────────────────
def build_payload(env, summary: Dict[str, Any], *, sample_sec: int = SAMPLE_SEC) -> Dict[str, Any]:
    kg        = env.KnowledgeGraph
    events    = list(getattr(env, 'events', []))                  # schedule
    makespan  = float(summary.get('makespan_sec')
                      or max((e['end_sec'] for e in events), default=0.0))
    target    = {m: int(q) for m, q in env.target_qty.items()}
    total_tg  = sum(target.values()) or 1
    throughput = {m: int(v) for m, v in (summary.get('Throughput') or env.Throughput).items()}
    base_kw   = env.RuntimeVariables.BaselinePowerKw(             # 근무시간 기저 전력(kW, 설비=워크스테이션 단위)
                    env.workers, env.DefaultProcessConsumedPowerKw)
    smt_events = list(getattr(env, 'smt_events', []))

    def _in_work(t: float) -> bool:                               # 기저 소모는 근무시간(휴게 제외)만
        sid = t % 86400.0
        return (env.WorkStartTime <= sid < env.WorkEndTime
                and not (env.break_start_sec <= sid < env.break_end_sec))

    # --- 엔티티별 집계: 라인(설비)별 (스케줄 이벤트에서) ---
    busy: Dict[str, dict] = {}
    line_ivs: Dict[str, list] = {}
    for e in events:
        d = busy.setdefault(e['workstation'], {'q': 0, 'busy_sec': 0.0})
        d['q'] += 1
        d['busy_sec'] += e['end_sec'] - e['start_sec']
        line_ivs.setdefault(e['workstation'], []).append((e['start_sec'], e['end_sec']))
    workers = {}
    for ws, info in env.workers.items():
        wc  = info['worker_count']
        cap = wc * makespan or 1.0                       # 워커-초 정원
        bs  = busy.get(ws, {}).get('busy_sec', 0.0)      # 워커-초 가동(작업 점유 합)
        idle = max(0.0, cap - bs)
        op_sec = _union_len(line_ivs.get(ws, []))        # 라인이 ≥1명 가동하던 wall-clock 시간
        workers[ws] = {'worker_count': wc,                                  # 인원수
                       'processed_quantity': busy.get(ws, {}).get('q', 0),
                       'operating_sec': round(op_sec, 1),                    # 라인 가동시간(동작)
                       'operating_ratio': round(op_sec / makespan, 4) if makespan else 0.0,
                       'idle_sec': round(idle, 1),
                       'idle_ratio': round(idle / cap, 4) if cap else 0.0}

    # --- actual_due_day: 모델별 마지막 완성 시각 → 일 ---
    term_end: Dict[str, float] = {}
    for e in events:
        if _is_terminal(env, e['process_code']):
            term_end[e['model']] = max(term_end.get(e['model'], 0.0), e['end_sec'])
    actual_due_day = {m: math.ceil(term_end[m] / 86400.0) for m in term_end}

    # --- unit 단위 시각(WIP 시계열용) ---
    unit_span: Dict[Any, dict] = {}
    for e in events:
        u = unit_span.setdefault(e.get('unit_id', id(e)),
                                 {'start': e['start_sec'], 'end': 0.0})
        u['start'] = min(u['start'], e['start_sec'])
        if _is_terminal(env, e['process_code']):
            u['end'] = max(u['end'], e['end_sec'])
    units = list(unit_span.values())

    # --- 시계열 (10분 그리드) ---
    grid = _grid(makespan, sample_sec)
    ts_t, cum_done, ratio, wip, act_workers = [], [], [], [], []
    line_active: Dict[str, list] = {ws: [] for ws in env.workers}      # 라인(설비)별 가동 작업자 수
    inst_power, cum_energy = [], []
    running_e = 0.0
    for lo, hi, mid in grid:
        ts_t.append(round(hi, 1))
        done = sum(1 for e in events
                   if _is_terminal(env, e['process_code']) and e['end_sec'] <= hi)
        cum_done.append(done)
        ratio.append(round(done / total_tg, 4))
        wip.append(sum(1 for u in units if u['start'] <= hi and not (u['end'] and u['end'] <= hi)))
        per_line = {ws: 0 for ws in env.workers}                       # 이 시점 라인별 가동 작업자
        for e in events:
            if e['start_sec'] <= mid < e['end_sec']:
                per_line[e['workstation']] = per_line.get(e['workstation'], 0) + 1
        for ws in line_active:
            line_active[ws].append(per_line.get(ws, 0))
        act_workers.append(sum(per_line.values()))

        # 순간 전력(kW) = 근무시간 기저 + 가동(공정 정격) + SMT
        prem = 0.0
        for e in events:
            if e['start_sec'] <= mid < e['end_sec']:
                node = kg.nodes[e['process_code']]
                prem += node.RatedPowerKw
        smt_p = sum(s['power_kw'] for s in smt_events if s['start_sec'] <= mid < s['end_sec'])
        inst_power.append(round((base_kw if _in_work(mid) else 0.0) + prem + smt_p, 3))

        # 버킷 에너지(kWh) → 누적
        e_idle = base_kw * (env._work_elapsed(hi) - env._work_elapsed(lo)) / 3600.0
        e_prem = 0.0
        for e in events:
            node = kg.nodes[e['process_code']]
            e_prem += _overlap(e['start_sec'], e['end_sec'], lo, hi) \
                      * node.RatedPowerKw / 3600.0
        e_smt = sum(_overlap(s['start_sec'], s['end_sec'], lo, hi) * s['power_kw'] / 3600.0
                    for s in smt_events)
        running_e += e_idle + e_prem + e_smt
        cum_energy.append(round(running_e, 4))

    # --- 탄소/전력 KPI ---
    total_e   = float(summary.get('EpisodeEnergyKwh') or 0.0)
    premium_e = float(summary.get('ActivePremiumKwh') or 0.0)
    smt_e     = float(getattr(env, 'SMTEnergyKwh', 0.0))
    idle_e    = max(0.0, total_e - premium_e - smt_e)
    active_e  = total_e - idle_e                                  # 가동 = 총 - 유휴

    # --- warehouse 집계/이벤트 (프록시가 설치돼 있으면) ---
    wh = env.warehouse
    wh_by_item = {}
    for code, st in getattr(wh, 'by_item', {}).items():
        low = st.get('lowest_present_stock')
        wh_by_item[code] = {**st,
                            'lowest_present_stock': None if low in (float('inf'), float('-inf')) else low}
    wh_events  = getattr(wh, 'events', [])

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
                'due_day'       : {m: round(env.DueDay[m] / 86400.0) for m in target},
                'actual_due_day': actual_due_day,
            },
            'by_entity': {
                'workers'            : workers,
                'warehouse_by_item'  : wh_by_item,
                'equipment_op_time'  : getattr(env, 'smt_op_time', {}),   # 설비별 가동시간(초)
            },
            'events': {
                'schedule'  : events,
                'warehouse' : wh_events,
                'equipment' : smt_events,                                  # 설비별 가동 이벤트
            },
            'timeseries': {
                'sample_sec'         : sample_sec,
                't_sec'              : ts_t,
                'cumulative_completed': cum_done,
                'completion_ratio'   : ratio,
                'wip'                : wip,
                'active_workers'     : act_workers,           # 전체 합
                'line_active_workers': line_active,           # 라인(설비)별 가동 작업자 수 {line:[...]}
            },
        },
        'carbon': {
            'kpi': {
                'total_power_kwh'    : round(total_e, 2),
                'idle_power_kwh'     : round(idle_e, 2),
                'active_power_kwh'   : round(active_e, 2),
                'total_carbon_kgco2e': round(carbon.total(total_e), 2),
            },
            'timeseries': {
                'sample_sec'           : sample_sec,
                't_sec'                : ts_t,
                'instant_power_kw'     : inst_power,
                'cumulative_energy_kwh': cum_energy,
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
