# -*- coding: utf-8 -*-
"""ver1 관측 producer 카탈로그 (③ 분할). KnowledgeGraph/env 위에서만 동작(duck-typed, 클래스 import X)."""
from __future__ import annotations

import torch


#========관측 카탈로그 (observe — 닫힌 producer 집합, KnowledgeGraph/env 위에서만)========
# (a) 환경 관측 producer. AAS 인코더 Inputs 가 CD ref(cd/NodeFeatures·cd/GraphTopology)로 가리키고
# 해석기가 카탈로그 id 로 resolve, 알고리즘(choose)이 호출해 텐서 공급. (b) ready/pooled 임베딩은
# 알고리즘 내부값이라 여기 없음(choose 가 actor/critic 에 직접 공급). raw AAS 안 봄 — 도메인 클래스 위.
def obs_node_features(kg):
    """노드별 NodeFeatureAttrs gather → (N, F). 구성=AAS ObservationNodeFeatures(CD 리스트)."""
    if kg.NodeFeatureAttrs is None:
        raise RuntimeError('KnowledgeGraph.NodeFeatureAttrs 미설정 — ObservationNodeFeatures(AAS) 필요')
    sample  = next(iter(kg.nodes.values()))
    missing = [attr for attr in kg.NodeFeatureAttrs if not hasattr(sample, attr)]
    if missing:
        raise RuntimeError(f'ObservationNodeFeatures 항목이 GraphNode 속성이 아님: {missing}')
    return torch.tensor([[getattr(kg.nodes[pc], attr) for attr in kg.NodeFeatureAttrs]
                         for pc in kg.nodes], dtype=torch.float)

def obs_graph_topology(kg):
    """공정 precedence(DepPrev/DepType edges) → edge_index (2, E). 토폴로지(고정)."""
    node_index = {pc: i for i, pc in enumerate(kg.nodes)}
    src, dst = [], []
    for DepPrev, GraphEdges in kg.edges.items():
        for GraphEdge in GraphEdges:
            if DepPrev in node_index and GraphEdge.ProcessCode in node_index:
                src.append(node_index[DepPrev]); dst.append(node_index[GraphEdge.ProcessCode])
    return torch.tensor([src, dst], dtype=torch.long)

def obs_state_vector(env):
    """전역 상태 → (StateDim,). 구성=RuntimeVariables/Params, 정규화=코드."""
    return env.state_vec()

OBSERVATION_CATALOG = {                                   # 닫힌 어휘 — AAS 외부 ref 가 가리킬 수 있는 관측 소스
    'NodeFeatures':  obs_node_features,
    'GraphTopology': obs_graph_topology,
    'StateVector':   obs_state_vector,
}
