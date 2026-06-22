# -*- coding: utf-8 -*-
from __future__ import annotations
from typing import Dict, Optional, Type
import os

import path_extractor
from path_extractor import AssetAdministrationShell, ProvisionofSimulationModelsAAS

DEFAULT_AAS_FILES     = ('ProvisionOfSimulationModel.json', 'WorkstationWorkerMatchingDataAAS.json',
                         'MODEL_A.json', 'MODEL_B.json', 'MODEL_C.json',
                         'SMTEquipmentCatalog.json')

# 학습이 실제로 로드하는 5파일 (SMTEquipmentCatalog 제외). 추론(run_trained)은 학습과
# 동일 파일셋이어야 .pt regime·KPI가 일치하므로 train.py·run_trained.py 가 이 상수를 공유한다.
# SMTEquipmentCatalog 를 더하면 SMT 라인 설비의 CycleTimeSec/RatedPowerKw 참조가 카탈로그에서
# 해결돼 smt_line 이 실가동(SMT 에너지 가산) → 학습(폴백)과 동작이 달라진다.
TRAINING_AAS_FILES    = ('ProvisionOfSimulationModel.json', 'WorkstationWorkerMatchingDataAAS.json',
                         'MODEL_A.json', 'MODEL_B.json', 'MODEL_C.json')


def load_aas(aas_dir: str, *, files=DEFAULT_AAS_FILES) -> AssetAdministrationShell:
    for file_name in files:
        path_extractor.load(os.path.join(aas_dir, file_name))
    return ProvisionofSimulationModelsAAS


def build_simulation(aas_dir: Optional[str] = None, *,
                     target_qty: Optional[Dict[str, int]] = None,
                     due_day: Optional[Dict[str, int]] = None,
                     MaxEpisodes: Optional[int] = None,
                     env_cls: Optional[Type] = None,
                     enable_smt: bool = True,
                     files=DEFAULT_AAS_FILES):
    import simulation
    import knowledge_graph
    import warehouse as code_warehouse

    if aas_dir is not None and not ProvisionofSimulationModelsAAS.submodels:
        load_aas(aas_dir, files=files)

    PSM               = ProvisionofSimulationModelsAAS
    SimulationModel   = PSM.SimulationModels.SimulationModel
    Action            = SimulationModel.KnowledgeGraph.Action
    DefaultParameters = SimulationModel.DefaultParameters
    RewardWeights     = SimulationModel.RewardWeights
    DueDay, target_from_po = {}, {}
    for model_id, (quantity, day, registered) in SimulationModel.PurchaseOrder.items():
        target_from_po[model_id] = quantity
        DueDay[model_id]         = day * 86400
    if target_qty is None:
        target_qty = target_from_po
    if due_day is not None:                         # 납기일(일 단위) 오버라이드 — 지정 모델만 덮어쓰고 나머지는 PO 유지
        unknown = set(due_day) - set(target_qty)
        if unknown:
            raise ValueError(f'due_day override references unknown models: {sorted(unknown)} (target: {sorted(target_qty)})')
        for model_id, day in due_day.items():
            DueDay[model_id] = day * 86400

    ManufacturingProcesses = {mp.model_id: mp for mp in SimulationModel.Warehouse.InputBOM.target}
    shared_groups          = {name: group
                              for name, group in SimulationModel.KnowledgeGraph.Node.value.items()
                              if not name.startswith('SIM_')
                              and any(node.SamplingRate is not None for node in group.value.values())}
    NodeFeatureAttrs = SimulationModel.ModelArchitecture.Observation.ObservationNodeFeatures.attrs()
    KnowledgeGraph   = knowledge_graph.KnowledgeGraph.build(ManufacturingProcesses, PSM.workers, shared_groups, node_feature_attrs=NodeFeatureAttrs)
    warehouse      = code_warehouse.Warehouse.build(PSM.CoManagedBOM, SimulationModel.Warehouse.MinStock.target)

    if MaxEpisodes is None:
        MaxEpisodes = int(SimulationModel.SimulationConfig.MaxEpisodes.value)

    SMTLines = None
    SMTProcess = SimulationModel.value.get('SMTProcess') if enable_smt else None
    if SMTProcess is not None:
        lines = SMTProcess.SMTLines.value
        probe = next(iter(next(iter(lines.values())).value.values()))
        if probe.CycleTimeSec is not None:
            SMTLines = {
                line_id: [(name, node.CycleTimeSec.value, node.RatedPowerKw.value)
                          for name, node in line.value.items()]
                for line_id, line in lines.items()
            }

    env_cls = env_cls or simulation.CproSimEnv
    return env_cls(
        KnowledgeGraph          = KnowledgeGraph,
        warehouse               = warehouse,
        workers                 = PSM.workers,
        IndependentSequence     = [node.idShort for ref in Action.IndependentSequence
                                                 for node in ref.target if node is not None],
        DependentSequence       = [node.idShort for ref in Action.DependentSequence
                                                 for node in ref.target if node is not None],
        DependentJoin           = [node.idShort for ref in Action.DependentJoin
                                                 for node in ref.target if node is not None],
        RewardWeights           = {name: float(prop.value) for name, prop in RewardWeights.value.items()},
        ReplenishLeadDay        = int(DefaultParameters.ReplenishLeadDay.value) * 86400,
        target_qty              = dict(target_qty),
        MaxEpisodes             = MaxEpisodes,
        WarehouseManagedBOM     = PSM.CoManagedBOM,
        BOMCategory             = SimulationModel.Warehouse.MinStock.target,
        WorkStartTime           = DefaultParameters.WorkStartTime.target.value,
        WorkEndTime             = DefaultParameters.WorkEndTime.target.value,
        break_start_sec         = DefaultParameters.BreakDurationMin.target.min,
        break_end_sec           = DefaultParameters.BreakDurationMin.target.max,
        IdleWorkerThreshold     = int(DefaultParameters.IdleWorkerThreshold.value),
        RuntimeVariables        = SimulationModel.RuntimeVariables,
        IdleProcessRatedPowerKw          = float(DefaultParameters.IdleProcessRatedPowerKw.value),
        SelfManagedBOM          = PSM.SelfManagedBOM,
        SMTLines                = SMTLines,
        DueDay                  = DueDay,
    )


def build_agent(env=None, *, StateDim: Optional[int] = None, checkpoint: Optional[str] = None):
    import torch
    import simulation

    SimulationModel   = ProvisionofSimulationModelsAAS.SimulationModels.SimulationModel
    ModelArchitecture = SimulationModel.ModelArchitecture
    Algorithm         = ModelArchitecture.Algorithm
    Arguments         = Algorithm.Arguments

    if StateDim is None:
        StateDim = env.state_dim if env is not None else 0

    def _input_source(child):
        if isinstance(child, path_extractor.ReferenceElement):
            return path_extractor._idShort_from_cd(child.value[0])
        return child.value

    def _graph_spec(graph_smc):
        spec = []
        for node_id, node in graph_smc.value.items():
            operation = node.Operation.value
            arguments = {name: child.value for name, child in node.value['Arguments'].value.items()} if 'Arguments' in node.value else {}
            inputs    = {name: _input_source(child) for name, child in node.value['Inputs'].value.items()} if 'Inputs' in node.value else {}
            spec.append({'id': node_id, 'Operation': operation, 'Arguments': arguments, 'Inputs': inputs})
        return spec

    NodeFeatureDim = len(ModelArchitecture.Observation.ObservationNodeFeatures)
    encoder = simulation.GraphModule(_graph_spec(ModelArchitecture.Encoder),
                             source_dims={'NodeFeatures': NodeFeatureDim, 'GraphTopology': None})
    embedding_dim = next(node['Arguments']['out_channels'] for node in reversed(encoder.spec)
                         if 'out_channels' in node.get('Arguments', {}))
    actor   = simulation.GraphModule(_graph_spec(Algorithm.Actor),  source_dims={'ReadyNodeEmbeddings':  embedding_dim, 'StateVector': StateDim})
    critic  = simulation.GraphModule(_graph_spec(Algorithm.Critic), source_dims={'PooledNodeEmbedding': embedding_dim, 'StateVector': StateDim})

    algo_cls = simulation.import_callable(Algorithm.Operation.value)
    agent = algo_cls(
        encoder=encoder, actor=actor, critic=critic, StateDim=StateDim,
        LearningRate     = float(Arguments.LearningRate.value),
        ClipEpsilon      = float(Arguments.ClipEpsilon.value),
        Gamma            = float(Arguments.Gamma.value),
        GaeLambda        = float(Arguments.GaeLambda.value),
        EntropyCoef      = float(Arguments.EntropyCoef.value),
        ValueLossCoef    = float(Arguments.ValueLossCoef.value),
        UpdateEpochs     = Arguments.UpdateEpochs.value,
        BatchSize        = int(Arguments.BatchSize.value),
        RuntimeVariables = SimulationModel.RuntimeVariables,
    )
    if checkpoint is not None:
        agent.load_state_dict(torch.load(checkpoint))
        agent.eval()
        agent.reset_buffer()
    return agent
