from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from warehouse import Warehouse

DEP_DELIMITER   = ';'
SHARED_MODEL_ID = 'ALL'


@dataclass
class GraphNode:
    ProcessCode  : str
    GroupIdShort : str
    model_id     : str
    CycleTimeSec : float
    DefectRate   : float
    RatedPowerKw : float
    InputBOM     : dict
    DepWaitSec   : float | None = None
    SamplingRate : float | None = None
    OutputBOM    : dict | None = None


@dataclass
class GraphEdge:
    ProcessCode : str
    DepType     : str


@dataclass
class KnowledgeGraph:
    nodes            : dict
    edges            : dict
    workers          : dict
    NodeFeatureAttrs : list | None = None

    # 구성 — AAS ManufacturingProcess·공유그룹 → 노드/엣지
    @classmethod
    def build(cls, ManufacturingProcesses, workers, shared_groups=None, node_feature_attrs=None) -> 'KnowledgeGraph':
        nodes, edges = {}, {}
        entries = [
            (model_id, GroupIdShort, ProcessCode, ProcessNode)
            for model_id, mp in ManufacturingProcesses.items()
            for GroupIdShort, processes in mp.groups.items()
            for ProcessCode, ProcessNode in processes.items()
        ] + [
            (SHARED_MODEL_ID, GroupIdShort, ProcessCode, ProcessNode)
            for GroupIdShort, group in (shared_groups or {}).items()
            for ProcessCode, ProcessNode in group.value.items()
        ]
        for model_id, GroupIdShort, ProcessCode, ProcessNode in entries:
            DepWaitSec   = ProcessNode.DepWaitSec
            SamplingRate = ProcessNode.SamplingRate
            nodes[ProcessCode] = GraphNode(
                ProcessCode  = ProcessCode,
                GroupIdShort = GroupIdShort,
                model_id     = model_id,
                CycleTimeSec = ProcessNode.CycleTimeSec.value,
                DefectRate   = ProcessNode.DefectRate.value,
                RatedPowerKw = ProcessNode.RatedPowerKw.value,
                InputBOM     = ProcessNode.InputBOM,
                DepWaitSec   = DepWaitSec.value   if DepWaitSec   is not None else None,
                SamplingRate = SamplingRate.value if SamplingRate is not None else None,
            )
            for DepPrev in ProcessNode.DepPrev.value.split(DEP_DELIMITER):
                DepPrev = DepPrev.strip()
                if DepPrev:
                    edges.setdefault(DepPrev, []).append(
                        GraphEdge(ProcessCode=ProcessCode, DepType=ProcessNode.DepType.value))
            DepNext = ProcessNode.DepNext
            if DepNext is not None:
                for DepNext_code in DepNext.value.split(DEP_DELIMITER):
                    DepNext_code = DepNext_code.strip()
                    if DepNext_code:
                        edges.setdefault(ProcessCode, []).append(
                            GraphEdge(ProcessCode=DepNext_code, DepType=ProcessNode.DepType.value))
        return cls(nodes, edges, workers, node_feature_attrs)

    # 런타임 조회 — 완료·재고 기준 실행 가능한 공정
    def DepPrev(self, ProcessCode: str) -> list:
        if not hasattr(self, 'DepPrev_cache'):
            self.DepPrev_cache = {}
            for DepPrev, successors in self.edges.items():
                for edge in successors:
                    self.DepPrev_cache.setdefault(edge.ProcessCode, []).append(DepPrev)
        return self.DepPrev_cache.get(ProcessCode, [])

    def InputBOM_satisfied(self, ProcessCode: str, warehouse: Warehouse) -> bool:
        InputBOM = self.nodes[ProcessCode].InputBOM
        if not InputBOM:
            return True
        return all(
            warehouse.inventory[Category][item_code].present_stock >= Quantity
            for item_code, Quantity in InputBOM.items()
            for Category in warehouse.inventory
            if item_code in warehouse.inventory[Category]
        )

    def ready_queue(self, IndependentSequence, DependentSequence, DependentJoin,
                    completed: set, warehouse: Warehouse, InfiniteStock: bool = False) -> list:
        ready = []
        for ProcessCode in IndependentSequence:
            if ProcessCode not in completed and (InfiniteStock or self.InputBOM_satisfied(ProcessCode, warehouse)):
                ready.append(ProcessCode)
        for ProcessCode in DependentSequence:
            if ProcessCode in completed:
                continue
            if any(d in completed for d in self.DepPrev(ProcessCode)):
                if InfiniteStock or self.InputBOM_satisfied(ProcessCode, warehouse):
                    ready.append(ProcessCode)
        for ProcessCode in DependentJoin:
            if ProcessCode in completed:
                continue
            if all(d in completed for d in self.DepPrev(ProcessCode)):
                if InfiniteStock or self.InputBOM_satisfied(ProcessCode, warehouse):
                    ready.append(ProcessCode)
        return ready
