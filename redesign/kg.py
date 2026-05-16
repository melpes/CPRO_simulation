# -*- coding: utf-8 -*-
"""KnowledgeGraph — simulation_ver0_mod.py 와 syntactic 일치 + GNN 입력 API.

mod 의 GraphNode / GraphEdge / KnowledgeGraph 그대로. 추가로:
    - ProcessCodes (노드 순번 list)
    - adj_relations (5종 (N,N) ndarray)
    - R_FWD_SEQ/JOIN, R_BWD_SEQ/JOIN, R_SELF, NUM_RELATIONS 상수
    - GroupIdShort_ids(factory), WorkstationId_ids(factory)
    - build_H_static_scalar() (N, 5)
    - build_H_dynamic(done_set, warehouse) (N, 4)
"""
from dataclasses import dataclass, field
from typing import Dict, List, Set, TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from sim_env import Warehouse
    from factory import Factory


R_FWD_SEQ     = 0
R_FWD_JOIN    = 1
R_BWD_SEQ     = 2
R_BWD_JOIN    = 3
R_SELF        = 4
NUM_RELATIONS = 5


@dataclass
class GraphNode:
    ProcessCode  : str
    GroupIdShort : str
    model_id     : str
    CycleTimeSec : float
    DefectRate   : float
    RatedPowerKw : float
    InputBOM     : dict
    DepPrev      : str
    DepType      : str

@dataclass
class GraphEdge:
    DepPrev      : str
    ProcessCode  : str
    DepType      : str

@dataclass
class KnowledgeGraph:
    nodes        : Dict[str, GraphNode]
    edges        : Dict[str, List[GraphEdge]]
    workers      : Dict[str, dict]
    ProcessCodes  : List[str]        = field(default_factory=list)
    adj_relations : List[np.ndarray] = field(default_factory=list)

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
                        DepPrev          = ProcessNode.DepPrev.value,
                        DepType          = ProcessNode.DepType.value,
                    )
                    for DepPrev in ProcessNode.DepPrev.value.split(';'):
                        DepPrev = DepPrev.strip()
                        if not DepPrev:
                            continue
                        if DepPrev not in edges:
                            edges[DepPrev] = []
                        edges[DepPrev].append(GraphEdge(
                            DepPrev      = DepPrev,
                            ProcessCode  = ProcessCode,
                            DepType      = ProcessNode.DepType.value,
                        ))

        # GNN 추가: 노드 순번 + 5종 인접행렬
        ProcessCodes  = list(nodes.keys())
        N             = len(ProcessCodes)
        pc_to_idx     = {pc: i for i, pc in enumerate(ProcessCodes)}
        adj_relations = [np.zeros((N, N), dtype=np.float32) for _ in range(NUM_RELATIONS)]
        for i in range(N):
            adj_relations[R_SELF][i, i] = 1.0
        for DepPrev_pc, edge_list in edges.items():
            if DepPrev_pc not in pc_to_idx:
                continue
            src = pc_to_idx[DepPrev_pc]
            for edge in edge_list:
                if edge.ProcessCode not in pc_to_idx:
                    continue
                dst = pc_to_idx[edge.ProcessCode]
                fwd = R_FWD_JOIN if edge.DepType == 'JOIN' else R_FWD_SEQ
                bwd = R_BWD_JOIN if edge.DepType == 'JOIN' else R_BWD_SEQ
                adj_relations[fwd][src, dst] = 1.0
                adj_relations[bwd][dst, src] = 1.0

        return cls(nodes=nodes, edges=edges, workers=workers,
                   ProcessCodes=ProcessCodes, adj_relations=adj_relations)

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
            if ProcessCode in completed:
                continue
            if self._bom_satisfied(ProcessCode, warehouse):
                ready.append(ProcessCode)

        for ProcessCode in DependentSequence:
            if ProcessCode in completed:
                continue
            node = self.nodes[ProcessCode]
            DepPrev_list = [d.strip() for d in node.DepPrev.split(';') if d.strip()]
            if any(d in completed for d in DepPrev_list):
                if self._bom_satisfied(ProcessCode, warehouse):
                    ready.append(ProcessCode)

        for ProcessCode in DependentJoin:
            if ProcessCode in completed:
                continue
            node = self.nodes[ProcessCode]
            if all(dep in completed for dep in node.DepPrev.split(';')):
                if self._bom_satisfied(ProcessCode, warehouse):
                    ready.append(ProcessCode)

        return ready

    # ── GNN 입력 API ──────────────────────────────────────────────────

    def _workstation_of(self, ProcessCode: str) -> str:
        for ws, info in self.workers.items():
            if ProcessCode in info['ProcessCode']:
                return ws
        return ''

    def GroupIdShort_ids(self, factory: 'Factory') -> np.ndarray:
        return np.array([
            factory.GroupIdShort_to_embedding_index[self.nodes[pc].GroupIdShort]
            for pc in self.ProcessCodes
        ], dtype=np.int64)

    def WorkstationId_ids(self, factory: 'Factory') -> np.ndarray:
        return np.array([
            factory.WorkstationId_to_embedding_index.get(self._workstation_of(pc), 0)
            for pc in self.ProcessCodes
        ], dtype=np.int64)

    def build_H_static_scalar(self) -> np.ndarray:
        """(N, 5): CycleTimeSec/3600, DefectRate, RatedPowerKw/100, worker_count/20, is_join"""
        H = np.zeros((len(self.ProcessCodes), 5), dtype=np.float32)
        for i, pc in enumerate(self.ProcessCodes):
            node = self.nodes[pc]
            ws   = self._workstation_of(pc)
            worker_count = self.workers[ws]['worker_count'] if ws else 0
            edge_types   = {e.DepType for e in self.edges.get(pc, [])}
            # 다음 PC 에 대해 자기가 dep 인 경우 — 여기선 단순화로 어떤 PC 든 JOIN dep 보유 시 1
            is_join_target = 1.0 if any(
                e.DepType == 'JOIN' and e.ProcessCode == pc
                for el in self.edges.values() for e in el
            ) else 0.0
            H[i, 0] = node.CycleTimeSec / 3600
            H[i, 1] = node.DefectRate
            H[i, 2] = node.RatedPowerKw / 100
            H[i, 3] = worker_count / 20
            H[i, 4] = is_join_target
        return H

    def build_H_dynamic(self, done_set: Set[str], warehouse: 'Warehouse') -> np.ndarray:
        """(N, 4): is_in_done_set, bom_satisfied, dep_ready, wip_placeholder (0).

        trackers 없는 mod 일치 버전이라 wip 항은 placeholder 0.
        """
        H = np.zeros((len(self.ProcessCodes), 4), dtype=np.float32)
        for i, pc in enumerate(self.ProcessCodes):
            node         = self.nodes[pc]
            DepPrev_list = [d.strip() for d in node.DepPrev.split(';') if d.strip()]
            H[i, 0] = 1.0 if pc in done_set else 0.0
            H[i, 1] = 1.0 if self._bom_satisfied(pc, warehouse) else 0.0
            if not DepPrev_list:
                H[i, 2] = 1.0
            elif node.DepType == 'JOIN':
                H[i, 2] = 1.0 if all(d in done_set for d in DepPrev_list) else 0.0
            else:
                H[i, 2] = 1.0 if any(d in done_set for d in DepPrev_list) else 0.0
            H[i, 3] = 0.0     # wip placeholder (mod 에 WIPTracker 없음)
        return H
