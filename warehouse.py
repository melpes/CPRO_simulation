# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict


@dataclass
class StockItem:
    present_stock      : float
    MinStock           : float
    MaxStock           : float
    OrderRatio         : float
    on_order           : bool = False

@dataclass
class Warehouse:
    inventory   : Dict[str, Dict[str, StockItem]]
    
    @classmethod
    def build(cls, WarehouseManagedBOM, BOMCategory) -> 'Warehouse':
        inventory = {}
        for Category, items in WarehouseManagedBOM.items():
            inventory[Category] = {}
            for item_code in items:
                inventory[Category][item_code] = StockItem(
                    present_stock   = BOMCategory[Category].MinStock,
                    MinStock        = BOMCategory[Category].MinStock,
                    MaxStock        = BOMCategory[Category].MaxStock,
                    OrderRatio      = BOMCategory[Category].OrderRatio,
                )
        return cls(inventory)
    
    def consume(self, ProcessConsumedBOM: dict, deduct: bool = True) -> list:
        if not deduct:
            return []
        for item_code, Quantity in ProcessConsumedBOM.items():
            for Category in self.inventory:
                if item_code in self.inventory[Category]:
                    self.inventory[Category][item_code].present_stock -= Quantity
                    break
        ordered = []
        for Category in self.inventory:
            for item in self.inventory[Category].values():
                if (item.present_stock <= item.MinStock * item.OrderRatio
                        and not item.on_order):
                    item.on_order = True
                    ordered.append(item)
        return ordered

    def produce(self, OutputBOM: dict) -> None:
        for item_code, Quantity in OutputBOM.items():
            for Category in self.inventory:
                if item_code in self.inventory[Category]:
                    self.inventory[Category][item_code].present_stock += Quantity
                    break

    def replenish(self, env, ReplenishLeadDay, items, notify=None) -> None:
        yield env.timeout(ReplenishLeadDay)
        for item in items:
            item.present_stock += item.MaxStock * item.OrderRatio
            item.on_order = False
            if item.present_stock <= item.MinStock * item.OrderRatio:
                item.on_order = True
                env.process(self.replenish(env, ReplenishLeadDay, [item], notify))
        if notify:
            notify()


class _StockRouter:
    def __init__(self, main: Warehouse, pcb: Warehouse):
        self.main = main
        self.pcb  = pcb
        self._pcb_items = {code
                           for items in pcb.inventory.values()
                           for code in items}

    @property
    def inventory(self):
        return {**self.main.inventory, **self.pcb.inventory}

    def consume(self, ProcessConsumedBOM: dict, deduct: bool = True) -> list:
        main_bom, pcb_bom = {}, {}
        for code, qty in ProcessConsumedBOM.items():
            (pcb_bom if code in self._pcb_items else main_bom)[code] = qty
        ordered = self.main.consume(main_bom, deduct) if main_bom else []
        if pcb_bom:
            self.pcb.consume(pcb_bom, deduct)
        return ordered

    def produce(self, OutputBOM: dict) -> None:
        main_bom, pcb_bom = {}, {}
        for code, qty in OutputBOM.items():
            (pcb_bom if code in self._pcb_items else main_bom)[code] = qty
        if main_bom:
            self.main.produce(main_bom)
        if pcb_bom:
            self.pcb.produce(pcb_bom)

    def replenish(self, env, ReplenishLeadDay, items, notify=None):
        return self.main.replenish(env, ReplenishLeadDay, items, notify)
