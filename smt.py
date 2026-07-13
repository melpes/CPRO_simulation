from __future__ import annotations

import math

AOI_EQUIPMENT = 'AOI'


# 진입 — SMT 라인 시작 (계획 생산 / 단순 공급)
def start(sim):
    plan = getattr(sim, 'SmtPlan', 'auto')
    if plan == 'auto':
        plan = po_pcb_plan(sim) if sim.ScenarioMode != 'STEADY' else None
    sim.SmtPlanEffective = plan if sim.SMTLines else None
    if sim.SMTLines and plan:
        queue = [(item_code, Quantity) for item_code, Quantity in plan.items() if Quantity > 0]
        sim.smt_plan_log = []
        for line_id, equipment in sim.SMTLines.items():
            sim.env.process(smt_line_planned(sim, line_id, equipment, queue))


# 계획 — PO 기준 PCB 수량 산출 / 에너지 추정
def po_pcb_plan(sim):
    pcb_codes = {code for items in sim._pcb_warehouse.inventory.values() for code in items}
    plan = {}
    for node in sim.KnowledgeGraph.nodes.values():
        for item_code, Quantity in (node.InputBOM or {}).items():
            if item_code in pcb_codes:
                plan[item_code] = plan.get(item_code, 0) + Quantity * sim.target_qty.get(node.model_id, 0)
    return {item_code: int(Quantity) for item_code, Quantity in sorted(plan.items()) if Quantity > 0}


def plan_energy_kwh(sim, plan):
    if not (plan and sim.SMTLines):
        return 0.0
    equipment  = next(iter(sim.SMTLines.values()))
    base_cycle = next((cycle for name, cycle, _ in equipment if AOI_EQUIPMENT in name), equipment[-1][1])
    kwh = 0.0
    for Quantity in plan.values():
        array_count = max(1, math.ceil(Quantity / sim.SmtArrayPcb))
        for _, cycle, power in equipment:
            kwh += power * (cycle + (array_count - 1) * min(cycle, base_cycle)) / 3600
    return kwh


# 라인 생산 — 계획 큐를 소진하며 PCB 생산·에너지 적산
def smt_line_planned(sim, line_id, equipment, queue):
    if not equipment:
        return
    base_cycle = next((cycle for name, cycle, _ in equipment if AOI_EQUIPMENT in name), equipment[-1][1])
    flush      = sum(cycle for _, cycle, _ in equipment)

    def worked(dt):
        remaining = dt
        while remaining > 0:
            while not sim._is_work_time():
                yield sim.env.timeout(sim._off_hours_delta())
            sec_in_day = sim.env.now % 86400
            bound = sim.break_start_sec if sec_in_day < sim.break_start_sec else sim.WorkEndTime
            step  = min(remaining, bound - sec_in_day)
            yield sim.env.timeout(step)
            remaining -= step

    while queue:
        item_code, Quantity = queue.pop(0)
        array_count = max(1, math.ceil(Quantity / sim.SmtArrayPcb))
        start_sec, produced = sim.env.now, 0
        for k in range(array_count):
            yield from worked(flush if k == 0 else base_cycle)
            batch = min(sim.SmtArrayPcb, Quantity - produced)
            sim.warehouse.produce({item_code: batch})
            produced += batch
            equip_energy = sim.smt_equip_energy.setdefault(line_id, {})
            kwh = 0.0
            for name, cycle, power in equipment:
                on_sec = cycle if k == 0 else min(cycle, base_cycle)
                equip_kwh = power * on_sec / 3600
                equip_energy[name] = equip_energy.get(name, 0.0) + equip_kwh
                kwh += equip_kwh
            sim.SMTEnergyKwh += kwh
            sim.line_energy[line_id] = sim.line_energy.get(line_id, 0.0) + kwh
            sim._wake_stock()
            record = getattr(sim, 'smt_record', None)
            if record is not None:
                record(line_id, equipment, item_code, sim.env.now, flush if k == 0 else base_cycle, kwh)
        sim.smt_plan_log.append({'line': line_id, 'code': item_code, 'pcb': produced,
                                 'arrays': array_count, 'start_sec': start_sec, 'end_sec': sim.env.now})
