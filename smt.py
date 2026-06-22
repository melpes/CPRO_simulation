# -*- coding: utf-8 -*-
from __future__ import annotations

AVG_PCB_PER_LINE    = 100.0
N_SMT_LINES         = 2
SUPPLY_INTERVAL_SEC = 3600.0


def start(sim):
    pcb_codes = [code for items in sim._pcb_warehouse.inventory.values() for code in items]
    if sim.SMTLines:
        n_lines = len(sim.SMTLines)
        for line_index, (line_id, equipment) in enumerate(sim.SMTLines.items()):
            line_codes = pcb_codes[line_index::n_lines]
            sim.env.process(smt_line(sim, line_id, equipment, line_codes))
    else:
        sim.env.process(pcb_supply(sim.env, sim._pcb_warehouse))


def smt_line(sim, line_id, equipment, pcb_codes):
    if not pcb_codes or not equipment:
        return
    array_cycle  = sum(cycle for _, cycle, _ in equipment)
    array_energy = sum(power * cycle for _, cycle, power in equipment) / 3600
    while True:
        for code in pcb_codes:
            for _ in range(sim.SmtBatchArrays):
                while not sim._is_work_time():
                    yield sim.env.timeout(sim._off_hours_delta())
                yield sim.env.timeout(array_cycle)
                sim.SMTEnergyKwh += array_energy
                sim.warehouse.produce({code: sim.SmtArrayPcb})
                sim._wake_stock()


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
