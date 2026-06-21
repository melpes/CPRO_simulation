# -*- coding: utf-8 -*-
from __future__ import annotations

AVG_PCB_PER_LINE   = 100.0
N_SMT_LINES        = 2
SUPPLY_INTERVAL_SEC = 3600.0


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
