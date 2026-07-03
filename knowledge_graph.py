# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, TYPE_CHECKING

if TYPE_CHECKING:
    from warehouse import Warehouse


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
    ProcessCode  : str
    DepType      : str

@dataclass
class KnowledgeGraph:
    nodes        : dict
    edges        : dict
    workers      : dict
    NodeFeatureAttrs : list | None = None

    @classmethod
    def build(cls, ManufacturingProcesses, workers, shared_groups=None, node_feature_attrs=None) -> 'KnowledgeGraph':
        nodes = {}
        edges = {}
        def _add_node(model_id, GroupIdShort, ProcessCode, ProcessNode):
            DepWait  = ProcessNode.DepWaitSec
            SamplRate = ProcessNode.SamplingRate
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
            for DepPrev in ProcessNode.DepPrev.value.split(';'):
                DepPrev = DepPrev.strip()
                if not DepPrev:
                    continue
                edges.setdefault(DepPrev, []).append(GraphEdge(
                    ProcessCode = ProcessCode, DepType = ProcessNode.DepType.value))
            DepNext_prop = ProcessNode.DepNext
            if DepNext_prop is not None:
                for nxt in DepNext_prop.value.split(';'):
                    nxt = nxt.strip()
                    if not nxt:
                        continue
                    edges.setdefault(ProcessCode, []).append(GraphEdge(
                        ProcessCode = nxt, DepType = ProcessNode.DepType.value))
        for model_id, mp in ManufacturingProcesses.items():
            for GroupIdShort, processes in mp.groups.items():
                for ProcessCode, ProcessNode in processes.items():
                    _add_node(model_id, GroupIdShort, ProcessCode, ProcessNode)
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
        if not hasattr(self, '_pred_cache'):
            self._pred_cache = {}
            for DepPrev, GraphEdges in self.edges.items():
                for GraphEdge in GraphEdges:
                    self._pred_cache.setdefault(GraphEdge.ProcessCode, []).append(DepPrev)
        return self._pred_cache.get(ProcessCode, [])

    def ready_queue(self, IndependentSequence, DependentSequence, DependentJoin,
                    completed: set, warehouse: Warehouse, infinite_stock: bool = False) -> list:
        ready = []

        for ProcessCode in IndependentSequence:
            if ProcessCode in completed:
                continue
            if infinite_stock or self._bom_satisfied(ProcessCode, warehouse):
                ready.append(ProcessCode)

        for ProcessCode in DependentSequence:
            if ProcessCode in completed:
                continue
            DepPrev_list = self._predecessors(ProcessCode)
            if any(d in completed for d in DepPrev_list):
                if infinite_stock or self._bom_satisfied(ProcessCode, warehouse):
                    ready.append(ProcessCode)

        for ProcessCode in DependentJoin:
            if ProcessCode in completed:
                continue
            DepPrev_list = self._predecessors(ProcessCode)
            if all(d in completed for d in DepPrev_list):
                if infinite_stock or self._bom_satisfied(ProcessCode, warehouse):
                    ready.append(ProcessCode)

        return ready
