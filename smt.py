# -*- coding: utf-8 -*-
from __future__ import annotations

import math

AVG_PCB_PER_LINE    = 100.0
N_SMT_LINES         = 2
SUPPLY_INTERVAL_SEC = 3600.0


def po_pcb_plan(sim):
    """PO(target_qty) × KG 노드 InputBOM 에서 PCB 코드별 필요 수량 산출 — 계획생산 기본 계획."""
    pcb_codes = {code for items in sim._pcb_warehouse.inventory.values() for code in items}
    plan = {}
    for node in sim.KnowledgeGraph.nodes.values():
        for code, qty in (node.InputBOM or {}).items():
            if code in pcb_codes:
                plan[code] = plan.get(code, 0) + qty * sim.target_qty.get(node.model_id, 0)
    return {code: int(qty) for code, qty in sorted(plan.items()) if qty > 0}


def plan_energy_kwh(sim, plan):
    """계획 전량 생산 시 SMT 총 에너지(kWh) 해석식 — W2 분모(MaxEpisodeEnergyKwh)용.
    설비별 가동시간 = 종류별 첫 어레이 cycle + 이후 어레이당 min(cycle, AOI cycle).
    라인 배분과 무관(현행 라인 사양 동일 가정 — 첫 라인 기준)."""
    if not (plan and sim.SMTLines):
        return 0.0
    equipment  = next(iter(sim.SMTLines.values()))
    base_cycle = next((cycle for name, cycle, _ in equipment if 'AOI' in name),
                      equipment[-1][1])
    kwh = 0.0
    for qty in plan.values():
        n_arrays = max(1, math.ceil(qty / sim.SmtArrayPcb))
        for _, cycle, power in equipment:
            kwh += power * (cycle + (n_arrays - 1) * min(cycle, base_cycle)) / 3600
    return kwh


def start(sim):
    pcb_codes = [code for items in sim._pcb_warehouse.inventory.values() for code in items]
    plan = getattr(sim, 'SmtPlan', 'auto')
    if plan == 'auto':
        plan = po_pcb_plan(sim) if sim.ScenarioMode != 'STEADY' else None
    sim.SmtPlanEffective = plan if sim.SMTLines else None
    if sim.SMTLines and plan:
        queue = [(code, qty) for code, qty in plan.items() if qty > 0]
        sim.smt_plan_log = []
        for line_id, equipment in sim.SMTLines.items():
            sim.env.process(smt_line_planned(sim, line_id, equipment, queue))
    elif sim.SMTLines:
        n_lines = len(sim.SMTLines)
        for line_index, (line_id, equipment) in enumerate(sim.SMTLines.items()):
            line_codes = pcb_codes[line_index::n_lines]
            sim.env.process(smt_line(sim, line_id, equipment, line_codes))
    else:
        sim.env.process(pcb_supply(sim.env, sim._pcb_warehouse))


def smt_line(sim, line_id, equipment, pcb_codes):
    """파이프라인 SMT 라인 — 동시에 여러 어레이 재공.
    · 캐파: AOI=1 기준, 각 설비 cap=ceil(cycle/AOI cycle) (AOI 보다 빠른 설비도 최소 1)
      → 모든 설비 처리율 ≥ 투입률(1/AOI cycle), 병목 없음. 배출 페이스 = AOI cycle/장.
    · 전력: 어레이 수와 무관 — 근무시간 동안 설비 정격(RatedPowerKw) 연속 소모.
    · PCB 종류 교체: 직전 종류가 Loader~AOI 를 모두 빠져나가 라인이 빈 뒤에만 투입."""
    if not pcb_codes or not equipment:
        return
    base_cycle = next((cycle for name, cycle, _ in equipment if 'AOI' in name),
                      equipment[-1][1])
    flush      = sum(cycle for _, cycle, _ in equipment)
    total_kw   = sum(power for _, _, power in equipment)
    if not hasattr(sim, 'smt_line_caps'):
        sim.smt_line_caps = {}
    sim.smt_line_caps[line_id] = {name: max(1, math.ceil(cycle / base_cycle)) for name, cycle, _ in equipment}

    def worked(dt):
        """근무시간 기준 dt 초 진행(야간·휴게 정지). 진행 구간만큼 설비별 정격 전력 적산."""
        remaining = dt
        while remaining > 0:
            while not sim._is_work_time():
                yield sim.env.timeout(sim._off_hours_delta())
            sid   = sim.env.now % 86400
            bound = sim.break_start_sec if sid < sim.break_start_sec else sim.WorkEndTime
            step  = min(remaining, bound - sid)
            yield sim.env.timeout(step)
            sim.SMTEnergyKwh += total_kw * step / 3600
            sim.line_energy[line_id] = sim.line_energy.get(line_id, 0.0) + total_kw * step / 3600
            _eq = sim.smt_equip_energy.setdefault(line_id, {})
            for name, _, power in equipment:
                _eq[name] = _eq.get(name, 0.0) + power * step / 3600
            remaining -= step

    while True:
        for code in pcb_codes:
            yield from worked(flush)
            for k in range(sim.SmtBatchArrays):
                if k:
                    yield from worked(base_cycle)
                sim.warehouse.produce({code: sim.SmtArrayPcb})
                sim._wake_stock()
                _rec = getattr(sim, 'smt_record', None)
                if _rec is not None:
                    _rec(line_id, equipment, code, sim.env.now, flush, total_kw * flush / 3600)


def smt_line_planned(sim, line_id, equipment, queue):
    """계획생산 SMT 라인 — 공유 큐에서 PCB 종류 하나를 집어 전량 생산 후 다음 종류.
    · 페이스: AOI(캐파 1) 기준 — 종류별 첫 어레이는 flush(Σcycle) 후, 이후 AOI cycle 마다 1장.
    · 전력(on/off 이분화): 설비가 어레이를 물고 있는 동안만 정격 소모.
      어레이 투입 간격 = AOI cycle 이므로 설비별 가동시간
      = 첫 장 cycle_i + 이후 장당 min(cycle_i, AOI cycle)  (cycle_i > AOI cycle 설비는 연속 가동).
    · 계획 소진 시 라인 정지(전력 0). 생산 이력은 sim.smt_plan_log 에 기록."""
    if not equipment:
        return
    base_cycle = next((cycle for name, cycle, _ in equipment if 'AOI' in name),
                      equipment[-1][1])
    flush      = sum(cycle for _, cycle, _ in equipment)
    if not hasattr(sim, 'smt_line_caps'):
        sim.smt_line_caps = {}
    sim.smt_line_caps[line_id] = {name: max(1, math.ceil(cycle / base_cycle)) for name, cycle, _ in equipment}

    def worked(dt):
        """근무시간 기준 dt 초 진행(야간·휴게 정지) — 전력 적산은 어레이 단위 accrue()가 담당."""
        remaining = dt
        while remaining > 0:
            while not sim._is_work_time():
                yield sim.env.timeout(sim._off_hours_delta())
            sid   = sim.env.now % 86400
            bound = sim.break_start_sec if sid < sim.break_start_sec else sim.WorkEndTime
            step  = min(remaining, bound - sid)
            yield sim.env.timeout(step)
            remaining -= step

    def accrue(first):
        """어레이 1장 배출분 설비별 가동 에너지 적산. 반환=이번 장 kWh."""
        kwh = 0.0
        _eq = sim.smt_equip_energy.setdefault(line_id, {})
        for name, cycle, power in equipment:
            on_sec = cycle if first else min(cycle, base_cycle)
            e = power * on_sec / 3600
            _eq[name] = _eq.get(name, 0.0) + e
            kwh += e
        sim.SMTEnergyKwh += kwh
        sim.line_energy[line_id] = sim.line_energy.get(line_id, 0.0) + kwh
        return kwh

    while queue:
        code, qty = queue.pop(0)
        n_arrays  = max(1, math.ceil(qty / sim.SmtArrayPcb))
        t0, produced = sim.env.now, 0
        for k in range(n_arrays):
            yield from worked(flush if k == 0 else base_cycle)
            batch = min(sim.SmtArrayPcb, qty - produced)
            sim.warehouse.produce({code: batch})
            produced += batch
            kwh = accrue(k == 0)
            sim._wake_stock()
            _rec = getattr(sim, 'smt_record', None)
            if _rec is not None:
                _rec(line_id, equipment, code, sim.env.now, flush if k == 0 else base_cycle, kwh)
        sim.smt_plan_log.append({'line': line_id, 'code': code, 'pcb': produced,
                                 'arrays': n_arrays, 'start_sec': t0, 'end_sec': sim.env.now})


def pcb_supply(env, pcb_warehouse,
               avg_pcb_per_line: float = AVG_PCB_PER_LINE,
               n_lines: int = N_SMT_LINES,
               interval: float = SUPPLY_INTERVAL_SEC):
    items = [(Category, item_code)
             for Category, codes in pcb_warehouse.inventory.items()
             for item_code in codes]
    n_types = len(items) or 1
    increment = avg_pcb_per_line * n_lines / n_types
    while True:
        yield env.timeout(interval)
        for Category, item_code in items:
            pcb_warehouse.inventory[Category][item_code].present_stock += increment
