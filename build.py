# -*- coding: utf-8 -*-
from __future__ import annotations
from typing import Dict, Optional, Type
import os

import path_extractor
from path_extractor import AssetAdministrationShell, ProvisionofSimulationModelsAAS

_EQUIPMENT_AAS_FILES  = ('1_Loader.json', '2_SPI.json', '3_ScreenPrinter.json', '4_Mounter.json',
                         '5_AOI.json', '6_Reflow.json', '7_Unloader.json')

TRAINING_AAS_FILES    = ('ProvisionOfSimulationModel.json', 'WorkstationWorkerMatchingDataAAS.json',
                         'MODEL_A.json', 'MODEL_B.json', 'MODEL_C.json') + _EQUIPMENT_AAS_FILES

DEFAULT_AAS_FILES     = TRAINING_AAS_FILES


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
    if due_day is not None:
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

    _sc = SimulationModel.SimulationConfig.value
    _dp = DefaultParameters.value
    _flag = lambda d, k: (str(d[k].value).strip().lower() in ('true', '1')) if k in d else False
    ScenarioMode     = _sc['ScenarioMode'].value if 'ScenarioMode' in _sc else 'FINITE'
    InfiniteStock    = _flag(_dp, 'InfiniteStock')
    MaxEpisodeSec    = int(_sc['MaxEpisodeSec'].value)

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
        DefaultProcessConsumedPowerKw    = float(DefaultParameters.DefaultProcessConsumedPowerKw.value),
        SelfManagedBOM          = PSM.SelfManagedBOM,
        SMTLines                = SMTLines,
        DueDay                  = DueDay,
        InfiniteStock           = InfiniteStock,
        ScenarioMode            = ScenarioMode,
        MaxEpisodeSec           = MaxEpisodeSec,
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
        _ckpt = torch.load(checkpoint)
        if isinstance(_ckpt, dict) and 'model' in _ckpt:
            agent.load_state_dict(_ckpt['model'])
            if _ckpt.get('optim') is not None:
                agent.optimizer.load_state_dict(_ckpt['optim'])
        else:
            agent.load_state_dict(_ckpt)
        agent.eval()
        agent.reset_buffer()
    return agent
