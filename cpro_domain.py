# -*- coding: utf-8 -*-
"""ver1 도메인 모델 (③ 분할). GraphNode/GraphEdge/KnowledgeGraph/StockItem/Warehouse/_StockRouter.
AAS·simpy·torch 무관 순수 도메인 — AAS 객체는 주입받고 path_extractor 를 import 하지 않는다(코어 leaf)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict


@dataclass
class GraphNode:
    ProcessCode  : str      #← ManufacturingProcess.groups.{GroupIdShort}.processes.{ProcessCode}
    GroupIdShort : str      #← ManufacturingProcess.groups.{GroupIdShort}
    model_id     : str      #← ManufacturingProcess.id.split('/')[6]  # 'MODEL_A'. 공용 노드(OQC/RMA)는 'ALL'
    CycleTimeSec : float    #← ProcessNode.CycleTimeSec.value
    DefectRate   : float    #← ProcessNode.DefectRate.value
    RatedPowerKw : float    #← ProcessNode.RatedPowerKw.value
    InputBOM     : dict     #← ProcessNode.InputBOM
    DepWaitSec   : float | None = None   #← ProcessNode.DepWaitSec.value (자식 SME 없으면 None).
                            # cycle 후 후속 ready 까지 추가 대기 (워커 비점유). 본드 경화·AGING 등.
    SamplingRate : float | None = None   #← ProcessNode.SamplingRate.value (자식 SME 없으면 None).
                            # None = 항상 실행. 0.05 = 5% 만 실행, 95% 는 ready 됐을 때 즉시 done 마킹.
    OutputBOM    : dict | None = None    #← ProcessNode.Materials.outputVariables (A안: 완료 시 창고 적재 {item_code: Quantity}).
                            # None = 산출물 없음(일반 조립노드). SMT 등 자체생산 노드만 보유.
                            # AAS 연동(SMTProcess→OutputBOM 추출)은 SMT 노드 파서 도입 시 — 현재는 메커니즘만.
# DepPrev/DepType 는 노드에 캐싱하지 않는다. 의존 관계의 단일 표현은 edges
# (이전 공정 → 다음 공정 + type). 이전 공정이 필요하면 _predecessors 로 검색.

@dataclass
class GraphEdge:
    ProcessCode  : str      #← ProcessNode.{ProcessCode}            (다음 공정)
    DepType      : str      #← ProcessNode.DepType.value   ('SEQUENCE' | 'JOIN')
# edges 의 dict 키가 이전 공정. 키(이전 공정) → [GraphEdge(다음 공정, type)]
# VD7_40   → [GraphEdge(VD7_40_1, JOIN)]
# VD7_20_1 → [GraphEdge(VD7_40_1, JOIN)]
# VD7_10   → [GraphEdge(VD7_10_1, SEQUENCE)]

@dataclass
class KnowledgeGraph:
    nodes        : dict #{ProcessCode: GraphNode}
    edges        : dict #{DepPrev: [GraphEdge, ...]}
    workers      : dict #{WorkstationId: {'worker_count': int, 'ProcessCode': [...]}}
#        'WWM_FwInputLine': {
#        'worker_count': 2,
#        'ProcessCode' : ['VD7_10', 'VD7_10_1', 'VD7_10_2', 'VD7_10_3',
#                         'BT5_10', 'BT5_11', ...]
    NodeFeatureAttrs : list | None = None  #← ModelArchitecture.Observation.ObservationNodeFeatures.attrs() — GNN 노드 피처 속성명(순서=벡터 순서). obs_node_features 가 노드별 getattr. None=RL 미사용(예 gantt).

    @classmethod
    def build(cls, ManufacturingProcesses, workers, shared_groups=None, node_feature_attrs=None) -> 'KnowledgeGraph':
        # ManufacturingProcesses: {model_id: ManufacturingProcess submodel}  ← 모델별 MP
        # shared_groups: {GroupIdShort: ProcessGroup SMC}  ← PSM 의 ProcessOQC/ProcessRMA. model_id='ALL' 노드 — 공용 설비.
        nodes = {}
        edges = {}
        def _add_node(model_id, GroupIdShort, ProcessCode, ProcessNode):
            DepWait  = ProcessNode.DepWaitSec       # DepWaitSec(Property) | None
            SamplRate = ProcessNode.SamplingRate    # SamplingRate(Property) | None
            nodes[ProcessCode] = GraphNode(
                ProcessCode      = ProcessCode,
                GroupIdShort     = GroupIdShort,
                model_id         = model_id,
                CycleTimeSec     = ProcessNode.CycleTimeSec.value,
                DefectRate       = ProcessNode.DefectRate.value,
                RatedPowerKw     = ProcessNode.RatedPowerKw.value,
                InputBOM         = ProcessNode.InputBOM,
                DepWaitSec       = DepWait.value     if DepWait     is not None else None,
                SamplingRate     = SamplRate.value   if SamplRate   is not None else None,
            )
            # DepPrev → reverse edge (DepPrev → self) 등록. 기존 모델별 노드 정의 방식.
            for DepPrev in ProcessNode.DepPrev.value.split(';'):
                DepPrev = DepPrev.strip()
                if not DepPrev:
                    continue
                edges.setdefault(DepPrev, []).append(GraphEdge(
                    ProcessCode = ProcessCode, DepType = ProcessNode.DepType.value))
            # DepNext → forward edge (self → DepNext) 등록. 공용 노드(OQC) 가 자신의
            # 후속을 선언해 모델별 MP 의 DepPrev 변경 없이 reverse-edge 형성. 옵셔널.
            DepNext_prop = ProcessNode.DepNext
            if DepNext_prop is not None:
                for nxt in DepNext_prop.value.split(';'):
                    nxt = nxt.strip()
                    if not nxt:
                        continue
                    edges.setdefault(ProcessCode, []).append(GraphEdge(
                        ProcessCode = nxt, DepType = ProcessNode.DepType.value))
        # 모델별 MP 노드들
        for model_id, mp in ManufacturingProcesses.items():
            for GroupIdShort, processes in mp.groups.items():
                for ProcessCode, ProcessNode in processes.items():
                    _add_node(model_id, GroupIdShort, ProcessCode, ProcessNode)
        # 공용 노드 (PSM ProcessOQC/ProcessRMA — model_id='ALL')
        if shared_groups:
            for GroupIdShort, group in shared_groups.items():
                for ProcessCode, ProcessNode in group.value.items():
                    _add_node('ALL', GroupIdShort, ProcessCode, ProcessNode)
        return cls(nodes, edges, workers, node_feature_attrs)
    
    def _bom_satisfied(self, ProcessCode: str, warehouse: Warehouse) -> bool:
        InputBOM = self.nodes[ProcessCode].InputBOM
        if not InputBOM:
            return True
        return all(
            warehouse.inventory[Category][item_code].present_stock >= ProcessConsumedBOM
            for item_code, ProcessConsumedBOM in InputBOM.items()
            for Category in warehouse.inventory
            if item_code in warehouse.inventory[Category]
        )
    
    def _predecessors(self, ProcessCode: str) -> list:
        # edges(이전 공정 → 다음 공정) 역방향 맵. edges 는 build 후 불변이라 1회 캐싱
        # (ready_queue 가 매 평가마다 호출 → 매번 전 엣지 스캔하던 비용 제거, Track F).
        if not hasattr(self, '_pred_cache'):
            self._pred_cache = {}
            for DepPrev, GraphEdges in self.edges.items():
                for GraphEdge in GraphEdges:
                    self._pred_cache.setdefault(GraphEdge.ProcessCode, []).append(DepPrev)
        return self._pred_cache.get(ProcessCode, [])

    def ready_queue(self, IndependentSequence, DependentSequence, DependentJoin,
                    completed: set, warehouse: Warehouse) -> list:
        ready = []

        for ProcessCode in IndependentSequence:
            if ProcessCode in completed:
                continue
            if self._bom_satisfied(ProcessCode, warehouse):
                ready.append(ProcessCode)

        for ProcessCode in DependentSequence:
            if ProcessCode in completed:
                continue
            DepPrev_list = self._predecessors(ProcessCode)
            if any(d in completed for d in DepPrev_list):
                if self._bom_satisfied(ProcessCode, warehouse):
                    ready.append(ProcessCode)

        for ProcessCode in DependentJoin:
            if ProcessCode in completed:
                continue
            DepPrev_list = self._predecessors(ProcessCode)
            if all(d in completed for d in DepPrev_list):
                if self._bom_satisfied(ProcessCode, warehouse):
                    ready.append(ProcessCode)

        return ready

@dataclass
class StockItem:
    present_stock      : float    # 초기재고 = MinStock
    MinStock           : float
    MaxStock           : float
    OrderRatio         : float
    on_order           : bool = False   # 발주 outstanding 여부 — True 면 재발주 금지

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
    
    def consume(self, ProcessConsumedBOM: dict) -> list:
        # 차감 후 '발주점(MinStock·OrderRatio) 이하 & 아직 발주 안 나간' 품목을 발주.
        # 반환: 이번에 신규 발주된 StockItem 리스트(빈 리스트=발주 없음, falsy).
        for item_code, Quantity in ProcessConsumedBOM.items():
            for Category in self.inventory:
                if item_code in self.inventory[Category]:
                    self.inventory[Category][item_code].present_stock -= Quantity
                    break
        ordered = []
        for Category in self.inventory:
            for item in self.inventory[Category].values():
                if (item.present_stock <= item.MinStock * item.OrderRatio
                        and not item.on_order):                # 이미 발주 나간 품목 재발주 금지
                    item.on_order = True
                    ordered.append(item)
        return ordered

    def produce(self, OutputBOM: dict) -> None:
        # 노드 완료 시 산출물을 창고에 적재 (A안: SMT 등 자체생산 하위조립체). consume 의 역연산.
        for item_code, Quantity in OutputBOM.items():
            for Category in self.inventory:
                if item_code in self.inventory[Category]:
                    self.inventory[Category][item_code].present_stock += Quantity
                    break

    def replenish(self, env, ReplenishLeadDay, items, notify=None) -> None:
        # 발주된 품목만 lead time 후 발주량(MaxStock·OrderRatio) 입고 + 발주 해제.
        # ★ 입고 직후 발주점 재검사 (deadlock 방지): 누적 부족분이 1회 발주량보다 클 때,
        #   해당 부품의 모든 consumer 노드가 ready 차단되면 consume 못 일어남 → trigger 영구 차단.
        #   on_order=False 직후 발주점 이하면 즉시 추가 발주 1회. on_order 단일 락 유지하므로
        #   consume 시 폭증 트리거는 여전히 차단됨 (도착 시점 1회만 추가).
        # notify: 입고(BOM 해제) 직후 호출 — BOM 대기로 잠든 produce_unit 깨우기(Track F).
        #   재귀 발주에도 그대로 전달해 모든 입고가 깨우기를 트리거하도록(이벤트 누락 방지).
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
    """메인(CoManaged) + PCB(SelfManaged) 두 Warehouse 인스턴스를 묶어
    Warehouse 와 동일한 인터페이스(inventory / consume / replenish)로 노출.
    Warehouse·StockItem 구조는 무변경 — item_code 소속으로만 라우팅."""
    def __init__(self, main: Warehouse, pcb: Warehouse):
        self.main = main
        self.pcb  = pcb
        self._pcb_items = {code
                           for items in pcb.inventory.values()
                           for code in items}

    @property
    def inventory(self):                                  # _bom_satisfied 읽기용 (병합 뷰)
        return {**self.main.inventory, **self.pcb.inventory}

    def consume(self, ProcessConsumedBOM: dict) -> list:
        main_bom, pcb_bom = {}, {}
        for code, qty in ProcessConsumedBOM.items():
            (pcb_bom if code in self._pcb_items else main_bom)[code] = qty
        ordered = self.main.consume(main_bom) if main_bom else []
        if pcb_bom:
            self.pcb.consume(pcb_bom)                      # PCB 보충은 cpro_smt 코루틴 담당
        return ordered

    def produce(self, OutputBOM: dict) -> None:           # 산출물 적재 (A안). PCB→pcb 창고, 그 외→메인 (consume 과 동일 라우팅)
        main_bom, pcb_bom = {}, {}
        for code, qty in OutputBOM.items():
            (pcb_bom if code in self._pcb_items else main_bom)[code] = qty
        if main_bom:
            self.main.produce(main_bom)
        if pcb_bom:
            self.pcb.produce(pcb_bom)

    def replenish(self, env, ReplenishLeadDay, items, notify=None):    # 메인만 (PCB 는 일정증가 별도)
        return self.main.replenish(env, ReplenishLeadDay, items, notify)
