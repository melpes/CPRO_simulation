# -*- coding: utf-8 -*-
"""실험 진입점 — PSM 단일 진입으로 모든 변수 로드 → KG / Warehouse / Factory / CproSimEnv 결합.

새 PSM 스키마 (2026-05-15):
    SimulationModel.SimulationConfig.{TypeOfModel, MaxEpisodes}
    SimulationModel.KnowledgeGraph.Node.{SIM_MODEL_A|B|C, ProcessOQC, ProcessRMA}
    SimulationModel.KnowledgeGraph.Action.{IndependentSequence|DependentSequence|DependentJoin|AssignedProcessGroups}
    SimulationModel.RewardWeights.{W1_TimeElapsed..W6_IdleWorker}
    SimulationModel.DefaultParameters.{WorkStartTime|WorkEndTime|BreakDurationMin|ReplenishLeadDay|IdleWorkerThreshold|MinOutsourcing|...}
    SimulationModel.RuntimeVariables.{CycleCompleted|Throughput|EpisodeEnergyKwh|...}
    SimulationModel.Warehouse.{InputBOM|MinStock|MaxStock|OrderRatio}
    SimulationModel.ModelArchitecture.{GNN, PPO}

흐름::

    load_all_aas()                    AAS 4 JSON → PSM 트리
        ↓
    build_env()                       PSM → KG / Warehouse / Factory / CproSimEnv
        ↓
    build_agent(env)                  ProcessGNN + PPOAgent
        ↓
    for episode in range(MaxEpisodes):
        env.reset()
        while not done:
            action_idx = agent.act(env, ready_mask)
            ready, reward, done, info = env.step((PC, WS))
            agent.store_reward(reward, done)
        agent.update()
"""
import os
import sys

import numpy as np

_PKG_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PKG_DIR not in sys.path:
    sys.path.append(_PKG_DIR)

import path_extractor
from path_extractor import ProvisionofSimulationModelsAAS

import cpro_config as C
from kg       import KnowledgeGraph
from sim_env  import Warehouse, CproSimEnv
from factory  import Factory
from networks import ProcessGNN, PPOAgent


#========AAS JSON 로딩========
JSON_FILES = [
    'ProvisionOfSimulationModel.json',
    'WorkstationWorkerMatchingDataAAS.json',
    'MODEL_A.json',
    'MODEL_B.json',
    'MODEL_C.json',
]

def load_all_aas(json_dir: str = _PKG_DIR) -> None:
    for filename in JSON_FILES:
        path_extractor.load(os.path.join(json_dir, filename))


#========PSM 단일 진입점으로 변수 추출 → 환경 빌드========
def build_env() -> CproSimEnv:
    PSM                       = ProvisionofSimulationModelsAAS
    SimulationModel           = PSM.SimulationModels.SimulationModel
    KG_submodel               = SimulationModel.KnowledgeGraph
    Action                    = KG_submodel.Action
    PSM_Warehouse             = SimulationModel.Warehouse
    DefaultParameters         = SimulationModel.DefaultParameters
    RewardWeightsSME          = SimulationModel.RewardWeights
    SimulationConfig          = SimulationModel.SimulationConfig

    # ── KG 입력
    ManufacturingProcesses    = {mp.model_id: mp for mp in PSM_Warehouse.InputBOM.target}
    workers                   = PSM.workers
    kg                        = KnowledgeGraph.build(ManufacturingProcesses, workers)

    # ── Warehouse 입력
    WarehouseManagedBOM       = PSM.WarehouseManagedBOM
    BOMCategory               = PSM_Warehouse.MinStock.target
    warehouse                 = Warehouse.build(WarehouseManagedBOM, BOMCategory)

    # ── PSM Action
    IndependentSequence       = [node.idShort for ref in Action.IndependentSequence for node in ref.target]
    DependentSequence         = [node.idShort for ref in Action.DependentSequence   for node in ref.target]
    DependentJoin             = [node.idShort for ref in Action.DependentJoin       for node in ref.target]

    # ── PSM DefaultParameters
    WorkStartTime             = DefaultParameters.WorkStartTime.target.value
    WorkEndTime               = DefaultParameters.WorkEndTime.target.value
    BreakStartSec             = DefaultParameters.BreakDurationMin.target.min
    BreakEndSec               = DefaultParameters.BreakDurationMin.target.max
    ReplenishLeadDay          = int(DefaultParameters.ReplenishLeadDay.value)   * 3600
    IdleWorkerThreshold       = int(DefaultParameters.IdleWorkerThreshold.value)

    RewardWeights             = {
        'W1_TimeElapsed'      : float(RewardWeightsSME.W1_TimeElapsed.value),
        'W2_Energy'           : float(RewardWeightsSME.W2_Energy.value),
        'W3_StockOverflow'    : float(RewardWeightsSME.W3_StockOverflow.value),
        'W4_StockShortage'    : float(RewardWeightsSME.W4_StockShortage.value),
        'W5_Throughput'       : float(RewardWeightsSME.W5_Throughput.value),
        'W6_IdleWorker'       : float(RewardWeightsSME.W6_IdleWorker.value),
    }
    MaxEpisodes               = int(SimulationConfig.MaxEpisodes.value)
    TARGET_QTY                = C.TARGET_QTY

    factory                   = Factory.build(
        kg, workers,
        WorkStartTime, WorkEndTime, BreakStartSec, BreakEndSec,
        TARGET_QTY, C.MAX_DAYS,
    )

    return CproSimEnv(
        KnowledgeGraph        = kg,
        warehouse             = warehouse,
        workers               = workers,
        factory               = factory,
        IndependentSequence   = IndependentSequence,
        DependentSequence     = DependentSequence,
        DependentJoin         = DependentJoin,
        RewardWeights         = RewardWeights,
        ReplenishLeadDay      = ReplenishLeadDay,
        target_qty            = sum(TARGET_QTY.values()),
        MaxEpisodes           = MaxEpisodes,
        WarehouseManagedBOM   = WarehouseManagedBOM,
        BOMCategory           = BOMCategory,
        WorkStartTime         = WorkStartTime,
        WorkEndTime           = WorkEndTime,
        break_start_sec       = BreakStartSec,
        break_end_sec         = BreakEndSec,
        IdleWorkerThreshold   = IdleWorkerThreshold,
        TARGET_QTY            = TARGET_QTY,
    )


#========Agent 빌드========
def build_agent(env: CproSimEnv) -> PPOAgent:
    kg      = env.KnowledgeGraph
    factory = env.factory
    gnn = ProcessGNN(
        num_GroupIdShort  = len(factory.GroupIdShort_to_embedding_index),
        num_WorkstationId = len(factory.WorkstationId_to_embedding_index),
    )
    n_models  = len({n.model_id for n in kg.nodes.values()})
    n_workers = len(env.workers)
    state_dim = 1 + n_models + n_workers + 1
    return PPOAgent(gnn=gnn, factory=factory, kg=kg, state_dim=state_dim)


if __name__ == '__main__':
    import time
    load_all_aas()
    env      = build_env()
    agent    = build_agent(env)
    kg       = env.KnowledgeGraph
    print(f'[build]  N nodes={len(kg.ProcessCodes)}  '
          f'state_dim={agent.state_dim}  target_qty={env.target_qty}')

    # ver3 패턴 학습 루프: env.run(agent) 한 번에 전체 시뮬 진행 + agent.update()
    for episode in range(3):
        t0 = time.time()
        agent.reset_episode()
        result = env.run(agent=agent, max_sec=60 * 86400)
        agent.finalize_episode(env)
        ep_reward = agent.update()
        dt = time.time() - t0
        print(f'[ep{episode}] wall={dt:>5.1f}s  '
              f'Throughput={result["Throughput"]}/{env.target_qty}  '
              f'makespan={result["makespan_sec"]/86400:.2f}d  '
              f'kwh={result["EpisodeEnergyKwh"]:.2f}  '
              f'reward_sum={ep_reward:+.4f}')
