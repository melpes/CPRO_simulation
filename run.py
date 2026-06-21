# -*- coding: utf-8 -*-
from __future__ import annotations
from typing import Dict, Optional, Type
import os

import path_extractor
from path_extractor import AssetAdministrationShell, ProvisionofSimulationModelsAAS

DEFAULT_AAS_FILES     = ('ProvisionOfSimulationModel.json', 'WorkstationWorkerMatchingDataAAS.json',
                         'MODEL_A.json', 'MODEL_B.json', 'MODEL_C.json',
                         'SMTEquipmentCatalog.json')
DEFAULT_SHARED_GROUPS = ('ProcessOQC',)
IDLE_POWER_RATIO      = 0.10


def load_aas(aas_dir: str, *, files=DEFAULT_AAS_FILES) -> AssetAdministrationShell:
    for file_name in files:
        path_extractor.load(os.path.join(aas_dir, file_name))
    return ProvisionofSimulationModelsAAS


def build_simulation(aas_dir: Optional[str] = None, *,
                     target_qty: Optional[Dict[str, int]] = None,
                     MaxEpisodes: Optional[int] = None,
                     env_cls: Optional[Type] = None,
                     shared_group_names=DEFAULT_SHARED_GROUPS,
                     IdlePowerRatio: float = IDLE_POWER_RATIO,
                     enable_smt: bool = True,
                     files=DEFAULT_AAS_FILES):
    import simulation as sv
    import knowledge_graph as kg_mod
    import warehouse as warehouse_mod

    if aas_dir is not None and not ProvisionofSimulationModelsAAS.submodels:
        load_aas(aas_dir, files=files)

    PSM               = ProvisionofSimulationModelsAAS
    SimulationModel   = PSM.SimulationModels.SimulationModel
    Action            = SimulationModel.KnowledgeGraph.Action
    DefaultParameters = SimulationModel.DefaultParameters
    RewardWeights     = SimulationModel.RewardWeights
    if target_qty is None:
        target_qty = SimulationModel.PurchaseOrder.target_qty()
    DueDay = {model_id: day * 86400
              for model_id, (quantity, day, registered) in SimulationModel.PurchaseOrder.items()}

    ManufacturingProcesses = {mp.model_id: mp for mp in SimulationModel.Warehouse.InputBOM.target}
    shared_groups          = {name: group
                              for name, group in SimulationModel.KnowledgeGraph.Node.value.items()
                              if name in shared_group_names}
    NodeFeatureAttrs = SimulationModel.ModelArchitecture.Observation.ObservationNodeFeatures.attrs()
    KnowledgeGraph   = kg_mod.KnowledgeGraph.build(ManufacturingProcesses, PSM.workers, shared_groups, node_feature_attrs=NodeFeatureAttrs)
    warehouse      = warehouse_mod.Warehouse.build(PSM.CoManagedBOM, SimulationModel.Warehouse.MinStock.target)

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

    env_cls = env_cls or sv.CproSimEnv
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
        RewardWeights           = {weight: float(RewardWeights[weight].value) for weight in
                                   ('W1_TimeElapsed', 'W2_Energy', 'W3_StockOverflow',
                                    'W4_StockShortage', 'W5_Throughput', 'W6_IdleWorker',
                                    'W7_DueDate')},
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
        IdleProcessRatedPowerKw = float(DefaultParameters.IdleProcessRatedPowerKw.value),
        IdlePowerRatio          = IdlePowerRatio,
        SelfManagedBOM          = PSM.SelfManagedBOM,
        SMTLines                = SMTLines,
        DueDay                  = DueDay,
    )


def build_agent(env=None, *, StateDim: Optional[int] = None, checkpoint: Optional[str] = None):
    import torch
    import simulation as sv

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
    encoder = sv.GraphModule(_graph_spec(ModelArchitecture.Encoder),
                             source_dims={'NodeFeatures': NodeFeatureDim, 'GraphTopology': None})
    embedding_dim = next(node['Arguments']['out_channels'] for node in reversed(encoder.spec)
                         if 'out_channels' in node.get('Arguments', {}))
    actor   = sv.GraphModule(_graph_spec(Algorithm.Actor),  source_dims={'ReadyNodeEmbeddings':  embedding_dim, 'StateVector': StateDim})
    critic  = sv.GraphModule(_graph_spec(Algorithm.Critic), source_dims={'PooledNodeEmbedding': embedding_dim, 'StateVector': StateDim})

    algo_cls = sv.import_callable(Algorithm.Operation.value)
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


if __name__ == '__main__':
    import path_extractor
    import simulation

    _ROOT = os.path.dirname(os.path.abspath(__file__))
    for _f in ['ProvisionOfSimulationModel.json', 'WorkstationWorkerMatchingDataAAS.json',
               'MODEL_A.json', 'MODEL_B.json', 'MODEL_C.json']:
        path_extractor.load(os.path.join(_ROOT, 'aas_data', _f))

    SimulationModel = path_extractor.ProvisionofSimulationModelsAAS.SimulationModels.SimulationModel
    MaxEpisodes     = int(SimulationModel.SimulationConfig.MaxEpisodes.value)
    target_qty      = {mp.model_id: int(input(f'{mp.model_id} 목표 생산 수량을 입력하세요: '))
                       for mp in SimulationModel.Warehouse.InputBOM.target}

    env   = build_simulation(target_qty=target_qty, MaxEpisodes=MaxEpisodes)
    agent = build_agent(env)
    simulation.train(env, agent, MaxEpisodes)
