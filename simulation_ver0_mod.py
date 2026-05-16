# -*- coding: utf-8 -*-
"""simulation_ver0_mod.py — ver0 의 minimal patch (워커 병렬 동작).

`simulation_ver0.py` 는 사용자 원본. 이 파일이 redesign 의 시뮬 모델 base.

운영 규칙 (사용자 합의):
    - ver0 에 **구현된 코드는 변경 / 삭제 최소화**
    - ver0 에 **아직 없는 기능 추가는 OK** (예: ver3 의 produce_unit, run)

ver0 → ver0_mod 변경 (CHANGELOG.md 참조):
    A. ver0 의 누락/미완성 보완 (호출 시 NameError / AttributeError 나는 부분)
    B. 워커 병렬 도입에 필수인 process_job 의 시그니처 + 본문 patch
    C. ver0 에 없는 새 함수/메서드 추가 (produce_unit / run / _check_done)
"""
from dataclasses import dataclass
from typing import Dict, Set

import simpy


@dataclass
class GraphNode:
    ProcessCode  : str      #← ManufacturingProcess.groups.{GroupIdShort}.processes.{ProcessCode}
    GroupIdShort : str      #← ManufacturingProcess.groups.{GroupIdShort}
    model_id     : str      #← ManufacturingProcess.id.split('/')[6]  # 'MODEL_A'
    CycleTimeSec : float    #← ProcessNode.CycleTimeSec.value
    DefectRate   : float    #← ProcessNode.DefectRate.value
    RatedPowerKw : float    #← ProcessNode.RatedPowerKw.value
    InputBOM     : dict     #← ProcessNode.InputBOM
    DepPrev      : str      #← ProcessNode.DepPrev.value  [mod 추가: ver0 누락]
    DepType      : str      #← ProcessNode.DepType.value  [mod 추가: ver0 누락 — JOIN / SEQUENCE]

@dataclass
class GraphEdge:
    DepPrev      : str
    ProcessCode  : str
    DepType      : str
# DepPrev=VD7_40,   ProcessCode=VD7_40_1,  DepType=JOIN
# DepPrev=VD7_20_1, ProcessCode=VD7_40_1,  DepType=JOIN
# DepPrev=VD7_10,   ProcessCode=VD7_10_1,  DepType=SEQUENCE

@dataclass
class KnowledgeGraph:
    nodes        : dict #{ProcessCode: GraphNode}
    edges        : dict #{DepPrev: [GraphEdge, ...]}
    workers      : dict #{WorkstationId: {'worker_count': int, 'ProcessCode': [...]}}
#        'WWM_FwInputLine': {
#        'worker_count': 2,
#        'ProcessCode' : ['VD7_10', 'VD7_10_1', 'VD7_10_2', 'VD7_10_3',
#                         'BT5_10', 'BT5_11', ...]

    @classmethod
    def build(cls, ManufacturingProcesses, workers) -> 'KnowledgeGraph':
        nodes = {}
        edges = {}
        for model_id, mp in ManufacturingProcesses.items():
            for GroupIdShort, processes in mp.groups.items():
                for ProcessCode, ProcessNode in processes.items():
                    nodes[ProcessCode]   = GraphNode(
                        ProcessCode      = ProcessCode,
                        GroupIdShort     = GroupIdShort,
                        model_id         = model_id,
                        CycleTimeSec     = ProcessNode.CycleTimeSec.value,
                        DefectRate       = ProcessNode.DefectRate.value,
                        RatedPowerKw     = ProcessNode.RatedPowerKw.value,
                        InputBOM         = ProcessNode.InputBOM,
                        DepPrev          = ProcessNode.DepPrev.value,    # mod 추가: ver0 누락
                        DepType          = ProcessNode.DepType.value,    # mod 추가: ver0 누락
                    )
                    for DepPrev in ProcessNode.DepPrev.value.split(';'):
                        DepPrev    = DepPrev.strip()
                        if not DepPrev:
                            continue
                        if DepPrev not in edges:
                            edges[DepPrev] = []
                        edges[DepPrev].append(GraphEdge(
                            DepPrev       = DepPrev,                     # mod 추가: ver0 누락
                            ProcessCode   = ProcessCode,
                            DepType       = ProcessNode.DepType.value,
                        ))
        return cls(nodes, edges, workers)

    def _bom_satisfied(self, ProcessCode: str, warehouse: 'Warehouse') -> bool:
        node = self.nodes[ProcessCode]
        if not node.InputBOM:
            return True
        return all(
            warehouse.inventory[Category][item_code].present_stock >= ProcessConsumedBOM
            for item_code, ProcessConsumedBOM in node.InputBOM.items()
            for Category in warehouse.inventory
            if item_code in warehouse.inventory[Category]
        )

    def ready_queue(self, IndependentSequence, DependentSequence, DependentJoin,
                    completed: set, warehouse: 'Warehouse') -> list:
        ready = []

        for ProcessCode in IndependentSequence:
            if ProcessCode in completed:                                 # mod 추가: 자기 중복 방지
                continue
            if self._bom_satisfied(ProcessCode, warehouse):
                ready.append(ProcessCode)

        for ProcessCode in DependentSequence:
            if ProcessCode in completed:                                 # mod 추가
                continue
            node = self.nodes[ProcessCode]
            # mod 수정: `node.DepPrev.value in completed` → multi-dep any() (ver0 의 .value 잘못)
            DepPrev_list = [d.strip() for d in node.DepPrev.split(';') if d.strip()]
            if any(d in completed for d in DepPrev_list):
                if self._bom_satisfied(ProcessCode, warehouse):
                    ready.append(ProcessCode)

        for ProcessCode in DependentJoin:
            if ProcessCode in completed:                                 # mod 추가
                continue
            node = self.nodes[ProcessCode]
            # mod 수정: `node.DepPrev.value.split(';')` → `node.DepPrev.split(';')` (.value 제거)
            if all(dep in completed for dep in node.DepPrev.split(';')):
                if self._bom_satisfied(ProcessCode, warehouse):
                    ready.append(ProcessCode)

        return ready

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
                worker_resources):                                       # mod 추가 인자
    # mod 수정: simpy.Resource.request() 점유 (워커 capacity 만큼 동시 점유 — 워커 병렬의 핵심)
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
    # mod 수정: ver0 의 `if ProcessCode not in KnowledgeGraph.edges: completed.clear()` 제거.
    # → 한 unit 의 terminal 도달이 다른 unit 의 completed 를 비우면 안 됨.
    #   terminal 검사는 produce_unit 안에서 unit-local 로 처리.


#========mod 추가: ver0 에 없는 새 함수 ====================================

def produce_unit(env, model_id, unit_id, KnowledgeGraph, warehouse, workers,
                 IndependentSequence, DependentSequence, DependentJoin,
                 worker_resources, in_progress, EpisodeEnergyKwh,
                 ReplenishLeadDay, throughput_counter, agent=None, cpro_env=None):
    """한 unit 의 KG 진행. terminal 도달 시 throughput_counter +1.

    여러 unit 의 produce_unit 가 simpy 에 동시 등록되어 흐름. 워커 자원 contention
    으로 **전체 공장 워커 수만큼 병렬 작업**.
    """
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
# mod 수정: gym.Env 상속 제거 (ver0 는 import gym 안 함 → 상속해도 동작 X)
class CproSimEnv:
    def __init__(self, KnowledgeGraph, warehouse, workers,
                 IndependentSequence, DependentSequence, DependentJoin,
                 RewardWeights, ReplenishLeadDay, target_qty, MaxEpisodes,
                 WarehouseManagedBOM, BOMCategory,
                 WorkStartTime, WorkEndTime, break_start_sec, break_end_sec,
                 IdleWorkerThreshold,
                 TARGET_QTY: Dict[str, int]):                            # mod 추가 인자
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
        self.WorkEndTime          = WorkEndTime
        self.break_start_sec      = break_start_sec  # int(min.split(':')[0]) * 3600 + int(min.split(':')[1]) * 60
        self.break_end_sec        = break_end_sec    # int(max.split(':')[0]) * 3600 + int(max.split(':')[1]) * 60
        self.IdleWorkerThreshold  = IdleWorkerThreshold
        self.TARGET_QTY           = TARGET_QTY                           # mod 추가

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
        self.worker_resources     = {                                    # mod 추가
            ws_id: simpy.Resource(self.env, capacity=info['worker_count'])
            for ws_id, info in self.workers.items()
        }
        self._throughput_counter  = [0]                                  # mod 추가 (produce_unit 가 +1)
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
                self.EpisodeEnergyKwh,
                self.worker_resources,                                   # mod 추가
            )
        )
        self.env.run(until=self.env.now + self.KnowledgeGraph.nodes[ProcessCode].CycleTimeSec)
        if (ProcessCode in self.KnowledgeGraph.nodes and ProcessCode not in self.KnowledgeGraph.edges):
            self.Throughput += 1

        for Category in self.warehouse.inventory:
            for item in self.warehouse.inventory[Category].values():
                if item.present_stock < item.MinStock:
                    self.StockShortageCount += 1
                if item.present_stock > item.MaxStock:
                    self.StockOverflowCount += 1

        if self._is_work_time():
            for WorkstationId in self.workers:
                idle_slots = (self.workers[WorkstationId]['worker_count'] -
                              self.in_progress.get(WorkstationId, 0))
                if idle_slots > 0:
                    if WorkstationId not in self.idle_time:
                        self.idle_time[WorkstationId] = self.env.now
                    elif (self.env.now - self.idle_time[WorkstationId]
                          > self.IdleWorkerThreshold):
                        self.IdleViolationCount += idle_slots
                else:
                    self.idle_time.pop(WorkstationId, None)

        work_day_sec = self.WorkEndTime - self.WorkStartTime - (self.break_end_sec - self.break_start_sec)

        reward = (
            - (self.env.now / work_day_sec)                         * self.RewardWeights['W1_TimeElapsed']
            - self.EpisodeEnergyKwh[0] / self.MaxEpisodeEnergyKwh   * self.RewardWeights['W2_Energy']
            - self.StockOverflowCount  / step_count                 * self.RewardWeights['W3_StockOverflow']
            - self.StockShortageCount  / step_count                 * self.RewardWeights['W4_StockShortage']
            + (self.Throughput / self.target_qty)                   * self.RewardWeights['W5_Throughput']
            - self.IdleViolationCount  / step_count                 * self.RewardWeights['W6_IdleWorker']
        )

        done = self.Throughput >= self.target_qty
        observation = {
            'ready'          : self.KnowledgeGraph.ready_queue(
                                  self.IndependentSequence,
                                  self.DependentSequence,
                                  self.DependentJoin,
                                  self.completed,
                                  self.warehouse
                              ),
            'in_progress'    : self.in_progress,
            'inventory'      : {
                                 Category: {
                                     item_code: item.present_stock
                                     for item_code, item in items.items()
                                 }
                                 for Category, items in self.warehouse.inventory.items()
                              },
            'Throughput'    : self.Throughput,
        }
        return observation, reward, done, {}

    #========mod 추가: ver0 에 없는 새 메서드 ==========================

    def _check_done(self, stop_event, max_sec):
        """매 30 초 시뮬 시간마다 검사: Throughput 도달 또는 makespan 초과 시 stop."""
        while True:
            yield self.env.timeout(30)
            self.Throughput = self._throughput_counter[0]
            if self.Throughput >= self.target_qty or self.env.now >= max_sec:
                if not stop_event.triggered:
                    stop_event.succeed()
                return

    def run(self, agent=None, max_sec: float = 60 * 86400):
        """ver3 패턴 — 모든 unit produce_unit 등록 + env.run(until=stop_event) 한 번 진행.

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
