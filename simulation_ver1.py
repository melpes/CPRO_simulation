# -*- coding: utf-8 -*-
"""ver1 단일 진입 facade (③ 분할). 코어는 cpro_domain/cpro_observe/cpro_nn/cpro_sim 로 분리.
AAS Operation 경로('simulation_ver1.PPOAgent'·op_concat_state·op_squeeze_last) 와
'import simulation_ver1 as sv' 사용처 호환을 위해 공개 심볼을 re-export. 진실의 정의처는 각 cpro_* 모듈."""
from __future__ import annotations

from cpro_domain  import GraphNode, GraphEdge, KnowledgeGraph, StockItem, Warehouse, _StockRouter
from cpro_observe import obs_node_features, obs_graph_topology, obs_state_vector, OBSERVATION_CATALOG
from cpro_nn      import import_callable, op_concat_state, op_squeeze_last, GraphModule, PPOAgent
from cpro_sim     import EPISODE_DURATION_SEC, CproSimEnv, train

__all__ = [
    'GraphNode', 'GraphEdge', 'KnowledgeGraph', 'StockItem', 'Warehouse', '_StockRouter',
    'obs_node_features', 'obs_graph_topology', 'obs_state_vector', 'OBSERVATION_CATALOG',
    'import_callable', 'op_concat_state', 'op_squeeze_last', 'GraphModule', 'PPOAgent',
    'EPISODE_DURATION_SEC', 'CproSimEnv', 'train',
]


if __name__ == '__main__':
    import os

    import path_extractor
    import cpro_factory as cf

    _ROOT = os.path.dirname(os.path.abspath(__file__))                 # 패키지 루트 (이 파일 위치) — AAS JSON
    for _f in ['ProvisionOfSimulationModel.json', 'WorkstationWorkerMatchingDataAAS.json',
               'MODEL_A.json', 'MODEL_B.json', 'MODEL_C.json']:
        path_extractor.load(os.path.join(_ROOT, 'aas_data', _f))

    # wiring 은 cpro_factory 단일 구현. 여기선 입력(목표 수량) → build → 학습(train) (기존 동작 유지).
    SimulationModel = path_extractor.ProvisionofSimulationModelsAAS.SimulationModels.SimulationModel
    MaxEpisodes     = int(SimulationModel.SimulationConfig.MaxEpisodes.value)
    target_qty      = {mp.model_id: int(input(f'{mp.model_id} 목표 생산 수량을 입력하세요: '))
                       for mp in SimulationModel.Warehouse.InputBOM.target}            #← Warehouse.InputBOM

    env   = cf.build_simulation(target_qty=target_qty, MaxEpisodes=MaxEpisodes)
    agent = cf.build_agent(env)

    train(env, agent, MaxEpisodes)
