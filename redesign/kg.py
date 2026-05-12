# -*- coding: utf-8 -*-
"""Knowledge Graph — 통합 KG (disjoint union of 모든 모델).

노드 키 = ``(model_id, process_code)`` tuple. **한 노드(pc)에는 시뮬 중
여러 unit 이 동시에 ready 상태가 될 수 있다** — 이 ready unit queue 는
``sim_env`` 가 별도로 관리하고, KG 의 ``is_ready`` 는 "그 (m, pc) 에
ready 인 unit 이 1개 이상 존재" 의 binary 신호.

Edge 는 5 relation 으로 분류해 R-GCN 입력 5개 adj 행렬로 변환::

    R_FWD_JOIN = 0   # prev → pc, pc 가 JOIN
    R_FWD_SEQ  = 1   # prev → pc, pc 가 non-JOIN
    R_BWD_JOIN = 2   # pc → prev, pc 가 JOIN
    R_BWD_SEQ  = 3   # pc → prev, pc 가 non-JOIN
    R_SELF     = 4   # 자기 자신 (단위행렬)

경로 패턴(참고)::

    node = kg.nodes[(model_id, process_code)]
    node.cycle_time_sec    ← factory.models[m].cycle_time_of[pc]   # SIM 추출
    node.is_join           ← factory.models[m].is_join[pc]
    node.line_idx          ← factory.line_to_idx[factory.models[m].process_to_workstation[pc]]
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Tuple

import numpy as np

from factory import Factory


# ── relation index ────────────────────────────────────────────────────────

R_FWD_JOIN = 0
R_FWD_SEQ  = 1
R_BWD_JOIN = 2
R_BWD_SEQ  = 3
R_SELF     = 4
NUM_RELATIONS = 5


NodeKey = Tuple[str, str]   # (model_id, process_code)


# ── 노드 ──────────────────────────────────────────────────────────────────


@dataclass
class KGNode:
    """통합 KG 의 노드.

    정적 부분은 ``KnowledgeGraph.__init__`` 에서 1회 채우고,
    동적 부분은 ``sim_env`` 의 dispatcher 가 ``refresh_dynamic()`` 으로
    매 act() 직전 한 번 갱신한다.
    """
    # 식별
    model_id: str
    process_code: str

    # 정적 — AAS / factory 에서 1회 derive
    cycle_time_sec: float = 0.0
    defect_rate:    float = 0.0
    rated_kw:       float = 0.0
    bom_count:      int   = 0
    process_group_idx: int = 0
    line_idx:          int = 0
    is_join:          bool = False

    # 동적 — sim_env 가 매 act() 직전 갱신
    is_ready:           bool  = False
    worker_util:        float = 0.0
    bom_satisfied:      bool  = False
    time_since_eligible: float = 0.0

    # 동적 보조: 처음 ready=True 가 된 시각 (time_since_eligible 계산용)
    _eligible_since: float = -1.0


# ── 엣지 ──────────────────────────────────────────────────────────────────


@dataclass
class KGEdge:
    src: NodeKey
    dst: NodeKey
    relation_idx: int


# ── 통합 KG ──────────────────────────────────────────────────────────────


class KnowledgeGraph:
    """모든 모델의 KG 를 disjoint union 으로 묶은 통합 그래프.

    R-GCN 입력 (H, 5개 adj) 와 정책 마스크 (ready_mask, line_mask) 변환을 담당.
    """

    def __init__(self, factory: Factory):
        self.factory = factory

        # 노드 순서 고정 (idx 매핑 stable)
        self.node_keys: List[NodeKey] = factory.all_node_keys()
        self.idx_of: Dict[NodeKey, int] = {
            key: i for i, key in enumerate(self.node_keys)
        }

        # 노드 dict — 정적 부분 채움
        self.nodes: Dict[NodeKey, KGNode] = {}
        for (model_id, process_code) in self.node_keys:
            self.nodes[(model_id, process_code)] = self._build_static_node(
                model_id, process_code)

        # 엣지 + 5개 adj 행렬
        self.edges: List[KGEdge] = self._build_edges()
        self.adj_relations: List[np.ndarray] = self._build_adj_matrices()

    # ── 정적 노드 1개 구성 (경로 명시) ────────────────────────────────

    def _build_static_node(self, model_id: str, process_code: str) -> KGNode:
        factory = self.factory
        aas = factory.models[model_id]
        group_name = aas.process_group_of[process_code]
        workstation_id = aas.process_to_workstation.get(process_code, '')

        return KGNode(
            model_id          = model_id,
            process_code      = process_code,
            cycle_time_sec    = float(aas.cycle_time_of[process_code]),
            defect_rate       = float(aas.defect_rate_of[process_code]),
            rated_kw          = factory.rated_kw_of(model_id, process_code),
            bom_count         = aas.bom_count[process_code],
            process_group_idx = factory.pg_to_idx[group_name],
            # WWM 미매핑 → factory.unmapped_line_idx (실제 라인 ID 와 매칭 X → dispatch 제외)
            line_idx          = factory.line_to_idx.get(workstation_id, factory.unmapped_line_idx),
            is_join           = aas.is_join[process_code],
        )

    # ── 엣지 / adj ────────────────────────────────────────────────────

    def _build_edges(self) -> List[KGEdge]:
        edges: List[KGEdge] = []
        for (model_id, process_code) in self.node_keys:
            node = self.nodes[(model_id, process_code)]
            prevs = self.factory.models[model_id].dep_prev_of[process_code]
            for prev_pc in prevs:
                src = (model_id, prev_pc)
                dst = (model_id, process_code)
                if src not in self.idx_of:
                    continue
                if node.is_join:
                    edges.append(KGEdge(src, dst, R_FWD_JOIN))
                    edges.append(KGEdge(dst, src, R_BWD_JOIN))
                else:
                    edges.append(KGEdge(src, dst, R_FWD_SEQ))
                    edges.append(KGEdge(dst, src, R_BWD_SEQ))
        # self-loop
        for key in self.node_keys:
            edges.append(KGEdge(key, key, R_SELF))
        return edges

    def _build_adj_matrices(self) -> List[np.ndarray]:
        N = len(self.node_keys)
        mats = [np.zeros((N, N), dtype=np.float32) for _ in range(NUM_RELATIONS)]
        for edge in self.edges:
            i = self.idx_of[edge.src]
            j = self.idx_of[edge.dst]
            mats[edge.relation_idx][i, j] = 1.0
        return mats

    # ── 동적 feat 갱신 (sim_env dispatcher 에서 호출) ─────────────────

    def refresh_dynamic(self,
                        sim_now: float,
                        ready_units_count: Dict[NodeKey, int],
                        worker_util_by_group: Dict[str, float],
                        bom_satisfied_of:    Dict[NodeKey, bool]) -> None:
        """매 act() 직전 한 번 호출. 4 개 동적 슬롯 갱신.

        Args:
            sim_now: ``env.now``
            ready_units_count: (m, pc) 별 ready unit 수 (>=1 면 is_ready=True)
            worker_util_by_group: worker_group → util ∈ [0, 1]
            bom_satisfied_of: (m, pc) 별 BOM 모두 충족 여부
        """
        factory = self.factory
        for key, node in self.nodes.items():
            is_ready = ready_units_count.get(key, 0) > 0
            node.is_ready      = is_ready
            node.bom_satisfied = bom_satisfied_of.get(key, False)

            worker_group = factory.worker_of(*key)
            node.worker_util = worker_util_by_group.get(worker_group, 0.0)

            # time_since_eligible: 처음 ready 된 시점 기록 → 그 후 sim_now - 시점
            if is_ready:
                if node._eligible_since < 0:
                    node._eligible_since = sim_now
                node.time_since_eligible = sim_now - node._eligible_since
            else:
                node._eligible_since = -1.0
                node.time_since_eligible = 0.0

    # ── R-GCN 입력 / 정책 마스크 빌드 ─────────────────────────────────

    def build_H_static_scalar(self) -> np.ndarray:
        """정적 scalar 5 + is_join = 6-d 의 (N, 6) 정적 부분 (embedding 제외).

        full H 는 ``networks`` 에서 embedding lookup 후 concat.
        """
        rows = []
        for key in self.node_keys:
            node = self.nodes[key]
            rows.append([
                node.cycle_time_sec,
                node.defect_rate,
                node.rated_kw,
                float(node.bom_count),
                1.0 if node.is_join else 0.0,
            ])
        return np.asarray(rows, dtype=np.float32)

    def build_H_dynamic(self) -> np.ndarray:
        """동적 4-d (N, 4) — refresh_dynamic 후 호출."""
        rows = []
        for key in self.node_keys:
            node = self.nodes[key]
            rows.append([
                1.0 if node.is_ready else 0.0,
                node.worker_util,
                1.0 if node.bom_satisfied else 0.0,
                node.time_since_eligible,
            ])
        return np.asarray(rows, dtype=np.float32)

    def pg_ids(self) -> np.ndarray:
        return np.asarray([self.nodes[k].process_group_idx for k in self.node_keys],
                          dtype=np.int64)

    def line_ids(self) -> np.ndarray:
        return np.asarray([self.nodes[k].line_idx for k in self.node_keys],
                          dtype=np.int64)

    def ready_mask(self) -> np.ndarray:
        """(N,) bool. is_ready 가 True 인 노드만 정책 후보."""
        return np.asarray([self.nodes[k].is_ready for k in self.node_keys],
                          dtype=bool)

    def line_filter_mask(self, line_idx: int) -> np.ndarray:
        """(N,) bool. 해당 line_idx 노드만 True. ready_mask 와 AND 로 사용."""
        return np.asarray([self.nodes[k].line_idx == line_idx for k in self.node_keys],
                          dtype=bool)

    # ── 편의 접근 ────────────────────────────────────────────────────

    def __len__(self) -> int:
        return len(self.node_keys)
