# -*- coding: utf-8 -*-
"""Knowledge Graph — 공정 그래프와 ready_queue.

ManufacturingProcess Submodel 들과 WWM 의 workers 매핑을 받아
`GraphNode` / `GraphEdge` 로 평탄화한 KG 를 구성. ready_queue 는
IndependentSequence / DependentSequence / DependentJoin 분기로 후보 도출.

경로 패턴(참고)::

    ManufacturingProcesses = {model_id: ManufacturingProcess}           # aas_architecture
    workers                = ProvisionofSimulationModelsAAS.workers     # aas_architecture
"""
from dataclasses import dataclass
from typing import Dict, TYPE_CHECKING

from aas_architecture import ManufacturingProcess, ProcessNode

if TYPE_CHECKING:
    from sim_env import Warehouse


@dataclass
class GraphNode:
    ProcessCode  : str      #← ManufacturingProcess.groups.{GroupIdShort}.processes.{ProcessCode}
    GroupIdShort : str      #← ManufacturingProcess.groups.{GroupIdShort}
    model_id     : str      #← ManufacturingProcess.id.split('/')[6]  # 'MODEL_A'
    CycleTimeSec : float    #← ProcessNode.CycleTimeSec.value
    DefectRate   : float    #← ProcessNode.DefectRate.value
    RatedPowerKw : float    #← ProcessNode.RatedPowerKw.value
    InputBOM     : dict     #← ProcessNode.InputBOM

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
                    )
                    for DepPrev in ProcessNode.DepPrev.value.split(';'):
                        DepPrev    = DepPrev.strip()
                        if not DepPrev:
                            continue
                        if DepPrev not in edges:
                            edges[DepPrev] = []
                        edges[DepPrev].append(GraphEdge(
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
            if self._bom_satisfied(ProcessCode, warehouse):
                ready.append(ProcessCode)

        for ProcessCode in DependentSequence:
            node = self.nodes[ProcessCode]
            if node.DepPrev.value in completed:
                if self._bom_satisfied(ProcessCode, warehouse):
                    ready.append(ProcessCode)

        for ProcessCode in DependentJoin:
            node = self.nodes[ProcessCode]
            if all(dep in completed for dep in node.DepPrev.value.split(';')):
                if self._bom_satisfied(ProcessCode, warehouse):
                    ready.append(ProcessCode)

        return ready
