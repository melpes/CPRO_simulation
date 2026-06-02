# -*- coding: utf-8 -*-
"""CPRO 시뮬레이션 빌더 (factory) — AAS → (CproSimEnv, PPOAgent) 단일 진입점.

기존에 `simulation_ver1.__main__` / `_capture_oqc` / `_timeit` / `cpro_ver1_viz` /
`cpro_worker_util` 에 verbatim 복제돼 있던 ~30개 kwarg wiring 블록을 한 곳으로 통합한다.
도구·외피(shell)는 `build_simulation()` / `build_agent()` 만 호출하고 같은 wiring 을 다시 쓰지 않는다.

규칙(CLAUDE.md):
- AAS 접근은 path_extractor 단일 진입점만 사용 — JSON 직접 파싱 없음.
- AAS 미반영 정책상수(`IdlePowerRatio`)는 env 빌더가 주입 — 여기가 단일 주입점.
- torch 는 `build_agent` 에서만 import (`build_simulation` 은 simpy 코어만).
- 입력 AAS 는 호출 전에 로드돼 있어야 한다. 각 도구는 기존 module-top `path_extractor.load` 를
  그대로 유지(`build_simulation(aas_dir=None)` 은 싱글톤을 읽기만). 재로드는 ProductAAS 중복
  append + viz 모듈 캐시 stale 을 부르므로 도구 load 를 여기로 옮기지 않는다.
  `aas_dir` 인자는 외피 단발 호출(빈 싱글톤일 때 1회 로드)용.
"""
from __future__ import annotations
from typing import Dict, Optional, Type
import os

import path_extractor
from path_extractor import AssetAdministrationShell, ProvisionofSimulationModelsAAS

# CPRO 입력 AAS. 다른 공장(헵시바 등)은 files= 로 교체 — 다중기업 일반화 seam(phase-2).
# SMTEquipmentCatalog: SMT 설비 cycle/power 임시 카탈로그(SMTProcess ref 가 deref) — 실 설비 AAS 도착 시 교체.
DEFAULT_AAS_FILES     = ('ProvisionOfSimulationModel.json', 'WorkstationWorkerMatchingDataAAS.json',
                         'MODEL_A.json', 'MODEL_B.json', 'MODEL_C.json',
                         'SMTEquipmentCatalog.json')
DEFAULT_SHARED_GROUPS = ('ProcessOQC',)   # 공용 노드(model_id='ALL'). ProcessRMA 자식 SME 미완 — 후속(E).
IDLE_POWER_RATIO      = 0.10              #← AAS 미반영 정책상수 (CLAUDE.md: 호출부 주입)


def load_aas(aas_dir: str, *, files=DEFAULT_AAS_FILES) -> AssetAdministrationShell:
    """aas_dir 의 입력 AAS 들을 path_extractor 싱글톤에 로드. 외피(shell) 단발 호출용.
    (도구는 기존 module-top load 를 유지 — 여기로 옮기지 않음.)"""
    for file_name in files:
        path_extractor.load(os.path.join(aas_dir, file_name))
    return ProvisionofSimulationModelsAAS


def build_simulation(aas_dir: Optional[str] = None, *,
                     target_qty: Dict[str, int],
                     MaxEpisodes: Optional[int] = None,
                     env_cls: Optional[Type] = None,
                     shared_group_names=DEFAULT_SHARED_GROUPS,
                     IdlePowerRatio: float = IDLE_POWER_RATIO,
                     enable_smt: bool = True,
                     files=DEFAULT_AAS_FILES):
    """로드된 AAS 싱글톤 → CproSimEnv 인스턴스 (→ 반환).
    env_cls 로 기록용 서브클래스(RecEnv/RecMod/UtilEnv 등) 주입 가능 (없으면 CproSimEnv).
    aas_dir 지정 + 싱글톤 비어있을 때만 직접 로드 (외피 단발 호출). 도구는 aas_dir 생략."""
    import simulation_ver1 as sv

    if aas_dir is not None and not ProvisionofSimulationModelsAAS.submodels:
        load_aas(aas_dir, files=files)

    PSM               = ProvisionofSimulationModelsAAS
    SimulationModel   = PSM.SimulationModels.SimulationModel                         #← SimulationModels.SimulationModel
    Action            = SimulationModel.KnowledgeGraph.Action                        #← KnowledgeGraph.Action
    DefaultParameters = SimulationModel.DefaultParameters                            #← DefaultParameters
    RewardWeights     = SimulationModel.RewardWeights                                #← RewardWeights

    ManufacturingProcesses = {mp.model_id: mp for mp in SimulationModel.Warehouse.InputBOM.target}  #← Warehouse.InputBOM
    shared_groups          = {name: group
                              for name, group in SimulationModel.KnowledgeGraph.Node.value.items()
                              if name in shared_group_names}
    KnowledgeGraph = sv.KnowledgeGraph.build(ManufacturingProcesses, PSM.workers, shared_groups)
    warehouse      = sv.Warehouse.build(PSM.CoManagedBOM, SimulationModel.Warehouse.MinStock.target)

    if MaxEpisodes is None:
        MaxEpisodes = int(SimulationModel.SimulationConfig.MaxEpisodes.value)         #← SimulationConfig.MaxEpisodes

    # SMT 라인 설비(cycle/power) 추출 — SMTProcess.SMTLines.<Line_N>.<설비>Process (SMTEquipmentProcess).
    # 설비 카탈로그(SMTEquipmentCatalog.json) 가 로드된 경우만 cycle/power resolve → SMT 활성.
    # 미로드(도구의 자체 5-파일 load 등)면 None → CproSimEnv 가 구 cpro_smt stub 으로 fallback.
    SMTLines = None                                                                    #← SMTProcess.SMTLines
    SMTProcess = SimulationModel.value.get('SMTProcess') if enable_smt else None
    if SMTProcess is not None:
        lines = SMTProcess.SMTLines.value
        probe = next(iter(next(iter(lines.values())).value.values()))                 # 첫 라인 첫 설비
        if probe.CycleTimeSec is not None:                                            # 카탈로그 로드 확인
            SMTLines = {
                line_id: [(name, node.CycleTimeSec.value, node.RatedPowerKw.value)
                          for name, node in line.value.items()]
                for line_id, line in lines.items()
            }

    env_cls = env_cls or sv.CproSimEnv
    return env_cls(
        KnowledgeGraph          = KnowledgeGraph,
        warehouse               = warehouse,
        workers                 = PSM.workers,                                        #← WWM
        IndependentSequence     = [node.idShort for ref in Action.IndependentSequence
                                                 for node in ref.target if node is not None],
        DependentSequence       = [node.idShort for ref in Action.DependentSequence
                                                 for node in ref.target if node is not None],
        DependentJoin           = [node.idShort for ref in Action.DependentJoin
                                                 for node in ref.target if node is not None],
        RewardWeights           = {weight: float(RewardWeights[weight].value) for weight in
                                   ('W1_TimeElapsed', 'W2_Energy', 'W3_StockOverflow',
                                    'W4_StockShortage', 'W5_Throughput', 'W6_IdleWorker')},
        ReplenishLeadDay        = int(DefaultParameters.ReplenishLeadDay.value) * 3600,
        target_qty              = dict(target_qty),
        MaxEpisodes             = MaxEpisodes,
        WarehouseManagedBOM     = PSM.CoManagedBOM,                                    #← ProductAAS HS (CoManaged)
        BOMCategory             = SimulationModel.Warehouse.MinStock.target,           #← Warehouse.MinStock
        WorkStartTime           = DefaultParameters.WorkStartTime.target.value,
        WorkEndTime             = DefaultParameters.WorkEndTime.target.value,
        break_start_sec         = DefaultParameters.BreakDurationMin.target.min,
        break_end_sec           = DefaultParameters.BreakDurationMin.target.max,
        IdleWorkerThreshold     = int(DefaultParameters.IdleWorkerThreshold.value),
        RuntimeVariables        = SimulationModel.RuntimeVariables,                    #← RuntimeVariables (AAS 명시 연산)
        IdleProcessRatedPowerKw = float(DefaultParameters.IdleProcessRatedPowerKw.value),
        IdlePowerRatio          = IdlePowerRatio,                                      #← 정책상수 주입
        SelfManagedBOM          = PSM.SelfManagedBOM,                                  #← PCB(SelfManaged) 별도창고
        SMTLines                = SMTLines,                                            #← SMTProcess.SMTLines (설비 cycle/power)
    )


def build_agent(env=None, *, StateDim: Optional[int] = None, checkpoint: Optional[str] = None):
    """로드된 AAS 싱글톤 + env.state_dim → PPOAgent (→ 반환).
    checkpoint 주면 load_state_dict + eval (결정형 평가용). StateDim 미지정 시 env.state_dim
    (env 없으면 0 — StateDim=0 으로 학습된 구 체크포인트 호환)."""
    import torch
    import simulation_ver1 as sv

    SimulationModel = ProvisionofSimulationModelsAAS.SimulationModels.SimulationModel
    GNN             = SimulationModel.ModelArchitecture.GNN                            #← ModelArchitecture.GNN
    TrainingConfig  = SimulationModel.ModelArchitecture.PPO.TrainingConfig             #← ModelArchitecture.PPO.TrainingConfig

    if StateDim is None:
        StateDim = env.state_dim if env is not None else 0

    agent = sv.PPOAgent(
        NodeFeatureDim   = int(GNN.NodeFeatureDim.value),
        HiddenDim        = int(GNN.HiddenDim.value),
        OutputDim        = int(GNN.OutputDim.value),
        NumLayers        = int(GNN.NumLayers.value),
        GNNEmbeddingDim  = int(GNN.OutputDim.value),                                   #← PPO.Actor.GNNEmbeddingDim → OutputDim
        LearningRate     = float(TrainingConfig.LearningRate.value),
        ClipEpsilon      = float(TrainingConfig.ClipEpsilon.value),
        Gamma            = float(TrainingConfig.Gamma.value),
        GaeLambda        = float(TrainingConfig.GaeLambda.value),
        EntropyCoef      = float(TrainingConfig.EntropyCoef.value),
        ValueLossCoef    = float(TrainingConfig.ValueLossCoef.value),
        UpdateEpochs     = TrainingConfig.UpdateEpochs.value,
        BatchSize        = int(TrainingConfig.BatchSize.value),
        RuntimeVariables = SimulationModel.RuntimeVariables,
        StateDim         = StateDim,
    )
    if checkpoint is not None:
        agent.load_state_dict(torch.load(checkpoint))
        agent.eval()
        agent.reset_buffer()
    return agent
