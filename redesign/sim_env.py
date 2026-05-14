# -*- coding: utf-8 -*-
"""SimPy 기반 시뮬레이션 환경.

KG / Warehouse / 워커 매핑을 받아 공정 작업을 진행. process_job 은
한 (ProcessCode, WorkstationId) 의 cycle_time 동안 점유 → BOM 소비
→ 발주 트리거 → completed 기록. CproSimEnv 는 gym.Env 인터페이스로
reset / step 노출.

경로 패턴(참고)::

    WarehouseManagedBOM = ProvisionofSimulationModelsAAS.WarehouseManagedBOM
    BOMCategory         = ProductAAS[i].submodels['HierarchicalStructures'].value['BOMCategory']
"""
from dataclasses import dataclass
from typing import Dict

import gym
import simpy


@dataclass
class StockItem:
    present_stock      : float
    MinStock           : float
    MaxStock           : float
    OrderRatio         : float

@dataclass
class Warehouse:
    inventory   : Dict[str, Dict[str, StockItem]] #{Category : {item_code  : StockItem}}

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

    def consume(self, ProcessConsumedBOM: dict) -> bool:
        for item_code, Quantity in ProcessConsumedBOM.items():
            for Category in self.inventory:
                if item_code in self.inventory[Category]:
                    self.inventory[Category][item_code].present_stock -= Quantity
                    break
        return any(
            item.present_stock <= item.MinStock * item.OrderRatio
            for Category in self.inventory
            for item in self.inventory[Category].values()
        )

    def replenish(self, env, ReplenishLeadDay) -> None:
        yield env.timeout(ReplenishLeadDay)
        for Category in self.inventory:
            for item in self.inventory[Category].values():
                if item.present_stock <= item.MinStock * item.OrderRatio:
                    item.present_stock += item.MaxStock * item.OrderRatio

def process_job(env, ProcessCode, WorkstationId, kg, warehouse,
                completed, in_progress, ReplenishLeadDay, total_energy_kwh):
    in_progress[WorkstationId] = in_progress.get(WorkstationId, 0) + 1
    node = kg.nodes[ProcessCode]
    yield env.timeout(node.CycleTimeSec)
    total_energy_kwh[0] += (node.CycleTimeSec * node.RatedPowerKw) / 3600
    if node.InputBOM:
        if warehouse.consume(node.InputBOM):
            env.process(warehouse.replenish(env,ReplenishLeadDay))
    completed.add(ProcessCode)
    in_progress[WorkstationId] -= 1

#========시뮬레이션 환경========
class CproSimEnv(gym.Env):
    def __init__(self, KnowledgeGraph, warehouse, workers,
                 IndependentSequence, DependentSequence, DependentJoin,
                 RewardWeights, ReplenishLeadDay, target_qty, MaxEpisodes,
                 WarehouseManagedBOM, BOMCategory,
                 WorkStartTime, WorkEndTIme, break_start_sec, break_end_sec):
        self.KnowledgeGraph       = KnowledgeGraph
        self.warehouse            = warehouse
        self.workers              = workers
        self.IndependentSequence  = IndependentSequence
        self.DependentSequence    = DependentSequence
        self.DependentJoin        = DependentJoin
        self.RewardWeights        = RewardWeights
        self.ReplenishLeadDay     = ReplenishLeadDay
        self.target_qty           = target_qty
        self.MaxEpisodes          = MaxEpisodes
        self.WarehouseManagedBOM  = WarehouseManagedBOM
        self.BOMCategory          = BOMCategory
        self.WorkStartTime        = WorkStartTime
        self.WorkEndTIme          = WorkEndTIme
        self.break_start_sec      = break_start_sec  # int(min.split(':')[0]) * 3600 + int(min.split(':')[1]) * 60
        self.break_end_sec        = break_end_sec    # int(max.split(':')[0]) * 3600 + int(max.split(':')[1]) * 60

    def reset(self):
        self.env                  = simpy.Environment()
        self.completed            = set
        self.in_progress          = {}
        self.total_energy_kwh     = [0.0]
        self.Throughput           = 0
        self.StockShortage        = 0
        self.StockOverflow        = 0
        self.idle_time            = {}
        self.warehouse            = Warehouse.build(
                                      self.WarehouseManagedBOM,
                                      self.BOMCategory
                                    )
        ready                     = self.KnowledgeGraph.ready_queue(
                                      self.IndependentSequence,
                                      self.DependentSequence,
                                      self.DependentJoin,
                                      self.completed,
                                      self.warehouse
                                    )
        return ready

    def _is_work_time(self) -> bool:
        seconds_in_day  = self.env.now % 86400
        return (self.WorkStartTime <= seconds_in_day < self.WorkEndTime and
                not (self.break_start_sec <= seconds_in_day < self.break_end_sec))

    def step(self, action):
        ProcessCode, WorkstationId  = action
        self.env.process(
            process_job(
                self.env,
                ProcessCode,
                WorkstationId,
                self.KnowledgeGraph,
                self.warehouse,
                self.completed,
                self.in_progress,
                self.ReplenishLeadDay,
                self.total_energy_kwh,
            )
        )
        self.env.run(until=self.env.now + self.KnowledgeGraph.nodes[ProcessCode].CycleTimeSec)
