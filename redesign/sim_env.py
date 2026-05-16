# -*- coding: utf-8 -*-
"""SimPy 시뮬레이션 환경 — simulation_ver0_mod.py 와 syntactic 일치.

mod 의 코드를 모듈 분할 (KG 는 kg.py 로, 시뮬은 여기). 트래커 / work_timeout /
wait_stock 등 ver3 부가 기능은 redesign 의 별도 layer 로 추가 가능.

mod 변경 → 이 파일에 동기화.
"""
from dataclasses import dataclass
from typing import Dict, Set

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


def process_job(env, ProcessCode, WorkstationId, KnowledgeGraph, warehouse,
                completed, in_progress, ReplenishLeadDay, EpisodeEnergyKwh,
                worker_resources):
    node = KnowledgeGraph.nodes[ProcessCode]
    resource = worker_resources[WorkstationId]
    with resource.request() as req:
        yield req
        in_progress[WorkstationId] = in_progress.get(WorkstationId, 0) + 1
        yield env.timeout(node.CycleTimeSec)
        EpisodeEnergyKwh[0] += (node.CycleTimeSec * node.RatedPowerKw) / 3600
        in_progress[WorkstationId] -= 1
    if node.InputBOM:
        if warehouse.consume(node.InputBOM):
            env.process(warehouse.replenish(env,ReplenishLeadDay))
    completed.add(ProcessCode)


def produce_unit(env, model_id, unit_id, KnowledgeGraph, warehouse, workers,
                 IndependentSequence, DependentSequence, DependentJoin,
                 worker_resources, in_progress, EpisodeEnergyKwh,
                 ReplenishLeadDay, throughput_counter, agent=None, cpro_env=None):
    done_set : Set[str] = set()
    kg = KnowledgeGraph
    model_pcs    = {pc for pc, n in kg.nodes.items() if n.model_id == model_id}
    terminal_pcs = model_pcs - set(kg.edges.keys())

    while not terminal_pcs.issubset(done_set):
        ready_pcs = [pc for pc in kg.ready_queue(IndependentSequence, DependentSequence,
                                                  DependentJoin, done_set, warehouse)
                     if kg.nodes[pc].model_id == model_id]
        if not ready_pcs:
            yield env.timeout(60)
            continue
        if agent is not None:
            ProcessCode = agent.choose(ready_pcs, model_id, done_set, cpro_env)
        else:
            ProcessCode = ready_pcs[0]
        WorkstationId = ''
        for ws, info in workers.items():
            if ProcessCode in info['ProcessCode']:
                WorkstationId = ws
                break
        if not WorkstationId:
            done_set.add(ProcessCode)
            continue
        yield env.process(process_job(env, ProcessCode, WorkstationId, kg, warehouse,
                                       done_set, in_progress, ReplenishLeadDay,
                                       EpisodeEnergyKwh, worker_resources))
    throughput_counter[0] += 1


#========시뮬레이션 환경========
class CproSimEnv:
    def __init__(self, KnowledgeGraph, warehouse, workers, factory,
                 IndependentSequence, DependentSequence, DependentJoin,
                 RewardWeights, ReplenishLeadDay, target_qty, MaxEpisodes,
                 WarehouseManagedBOM, BOMCategory,
                 WorkStartTime, WorkEndTime, break_start_sec, break_end_sec,
                 IdleWorkerThreshold,
                 TARGET_QTY: Dict[str, int]):
        self.KnowledgeGraph       = KnowledgeGraph
        self.warehouse            = warehouse
        self.workers              = workers
        self.factory              = factory
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
        self.WorkEndTime          = WorkEndTime
        self.break_start_sec      = break_start_sec
        self.break_end_sec        = break_end_sec
        self.IdleWorkerThreshold  = IdleWorkerThreshold
        self.TARGET_QTY           = TARGET_QTY

    def reset(self):
        self.env                  = simpy.Environment()
        self.completed            = set()
        self.in_progress          = {}
        self.EpisodeEnergyKwh     = [0.0]
        self.Throughput           = 0
        self.StockShortageCount   = 0
        self.StockOverflowCount   = 0
        self.idle_time            = {}
        self.IdleViolationCount   = 0
        self.warehouse            = Warehouse.build(
                                      self.WarehouseManagedBOM,
                                      self.BOMCategory
                                    )
        self.worker_resources     = {
            ws_id: simpy.Resource(self.env, capacity=info['worker_count'])
            for ws_id, info in self.workers.items()
        }
        self._throughput_counter  = [0]
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

    def _check_done(self, stop_event, max_sec):
        while True:
            yield self.env.timeout(30)
            self.Throughput = self._throughput_counter[0]
            if self.Throughput >= self.target_qty or self.env.now >= max_sec:
                if not stop_event.triggered:
                    stop_event.succeed()
                return

    def run(self, agent=None, max_sec: float = 60 * 86400):
        """ver3 패턴 — 모든 unit produce_unit 등록 + env.run(until=stop_event) 한 번.

        agent.choose(ready_pcs, model_id, done_set, env) 가 unit 내부 callback.
        agent=None 이면 greedy (ready[0]).
        """
        self.reset()
        stop_event = self.env.event()

        for model_id, qty in self.TARGET_QTY.items():
            for unit_id in range(qty):
                self.env.process(
                    produce_unit(self.env, model_id, unit_id,
                                 self.KnowledgeGraph, self.warehouse, self.workers,
                                 self.IndependentSequence,
                                 self.DependentSequence,
                                 self.DependentJoin,
                                 self.worker_resources, self.in_progress,
                                 self.EpisodeEnergyKwh, self.ReplenishLeadDay,
                                 self._throughput_counter, agent=agent, cpro_env=self)
                )
        self.env.process(self._check_done(stop_event, max_sec))
        self.env.run(until=stop_event)
        self.Throughput = self._throughput_counter[0]
        return {
            'Throughput'       : self.Throughput,
            'makespan_sec'     : float(self.env.now),
            'EpisodeEnergyKwh' : float(self.EpisodeEnergyKwh[0]),
        }
