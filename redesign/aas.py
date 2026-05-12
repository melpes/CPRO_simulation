# -*- coding: utf-8 -*-
"""AAS 진입점.

path_extractor 의 4 진입점 (WWM / HS / MP / SIM) 을 한 곳에서 묶고 derive 까지
한 번에 끝낸 ``AASModel`` 을 반환한다. 시뮬·KG·env 코드는 이 모듈만 import.

경로(참고)::

    aas = load_aas('MODEL_A', 'MODEL_A.json', 'WWM.json', sim_obj)
    aas.MP.groups[g].processes[pc]                   # AAS 원형
    aas.cycle_time_of[pc]                            # SIM 추출 (int sec)
    aas.defect_rate_of[pc]                           # SIM 추출 (float)
    aas.rated_kw_of_pc[pc]                           # SIM 추출 (float)
    aas.sampling_rate_of[pc]                         # OQC 만, 그 외 0.0
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from typing import Dict, List

_PKG_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PKG_DIR not in sys.path:
    sys.path.append(_PKG_DIR)

from path_extractor import (
    WorkstationWorkerMatchingData,
    HierarchicalStructures,
    ManufacturingProcess,
    ProvisionofSimulationModelsAAS,
    SimNode,
    ProcessGroup,
    ProcessNode,
    WorkstationInformation,
    BomRef,
    BomQualifier,
    Entity,
    EntityQualifier,
    Property,
    GlobalReference,
    SkillLevelType,
    AssignedProcessGroupRef,
    load_workstation_worker_matching_data,
    load_hierarchical_structures,
    load_manufacturing_process,
    load_provision_of_simulation_models,
)


@dataclass
class AASModel:
    """모델 1개의 WWM/HS/MP + 공장 공유 SIM + derived 매핑."""

    model_id: str
    WWM: WorkstationWorkerMatchingData
    HS:  HierarchicalStructures
    MP:  ManufacturingProcess
    SIM: ProvisionofSimulationModelsAAS         # 공장 공유 (모든 모델 동일 인스턴스)

    # MP container group idShort (예: 'VD7FwInput')
    process_group_of:       Dict[str, str] = field(default_factory=dict)
    # ProcessNode.ProcessGroup qualifier (예: 'MODULE', 'SET', 'OQC', 'RMA')
    abstract_group_of:      Dict[str, str] = field(default_factory=dict)
    process_to_workstation: Dict[str, str] = field(default_factory=dict)
    is_join:                Dict[str, bool] = field(default_factory=dict)
    bom_count:              Dict[str, int]  = field(default_factory=dict)
    dep_prev_of:            Dict[str, List[str]] = field(default_factory=dict)

    # SIM derived (process_code → 값)
    cycle_time_of:    Dict[str, int]   = field(default_factory=dict)
    defect_rate_of:   Dict[str, float] = field(default_factory=dict)
    rated_kw_of_pc:   Dict[str, float] = field(default_factory=dict)
    sampling_rate_of: Dict[str, float] = field(default_factory=dict)

    def process_codes(self) -> List[str]:
        return [pc
                for group in self.MP.groups.values()
                for pc in group.processes.keys()]


def load_aas(model_id: str,
             model_json_path: str,
             wwm_json_path: str,
             sim_obj: ProvisionofSimulationModelsAAS,
             sim_node_group_override: Dict[str, str] = None) -> AASModel:
    """모델 1개 AAS 로드.

    sim_obj 는 공장 공유 (호출자가 1회 load 후 모든 모델에 같은 객체 전달).
    sim_node_group_override: {model_id: sim_node_group_key} — 디폴트
    convention 은 ``f'SIM_{model_id}'``.
    """
    WWM = load_workstation_worker_matching_data(wwm_json_path)
    HS  = load_hierarchical_structures(model_json_path)
    MP  = load_manufacturing_process(model_json_path)
    aas = AASModel(model_id=model_id, WWM=WWM, HS=HS, MP=MP, SIM=sim_obj)
    _derive(aas, sim_node_group_override or {})
    return aas


def load_aas_models(json_dir: str,
                    model_files: Dict[str, str],
                    wwm_filename: str,
                    sim_filename: str,
                    sim_node_group_override: Dict[str, str] = None
                    ) -> Dict[str, AASModel]:
    wwm_path = os.path.join(json_dir, wwm_filename)
    sim_path = os.path.join(json_dir, sim_filename)
    sim_obj  = load_provision_of_simulation_models(sim_path)
    return {
        model_id: load_aas(model_id,
                           os.path.join(json_dir, fname),
                           wwm_path,
                           sim_obj,
                           sim_node_group_override)
        for model_id, fname in model_files.items()
    }


def _derive(aas: AASModel, sim_override: Dict[str, str]) -> None:
    """MP / WWM / SIM 으로부터 시뮬 친화 lookup 매핑을 채운다.

    SIM lookup 규칙:
      - ProcessGroup qualifier 가 'OQC'/'RMA' → SIM.Node['ProcessOQC'/'ProcessRMA']['OQC'/'RMA']
      - 그 외 → SIM.Node[sim_group][process_code], sim_group = override 또는 f'SIM_{model_id}'
    """
    sim_node_map = aas.SIM.SimulationModels.SimulationModel.Node
    sim_group_default = sim_override.get(aas.model_id, f'SIM_{aas.model_id}')

    for group_name, group in aas.MP.groups.items():
        for process_code, node in group.processes.items():
            abstract = str(node.ProcessGroup.value or '')
            aas.process_group_of[process_code]  = group_name
            aas.abstract_group_of[process_code] = abstract
            aas.is_join[process_code]   = (str(node.DepType.value) == 'JOIN')
            aas.bom_count[process_code] = len(node.InputBOM)
            aas.dep_prev_of[process_code] = _split_dep_prev(node.DepPrev.value)

            sim_node = _resolve_sim_node(sim_node_map, sim_group_default,
                                         abstract, process_code)
            aas.cycle_time_of[process_code]    = int(sim_node.CycleTimeSec.value or 0)
            aas.defect_rate_of[process_code]   = (float(sim_node.DefectRate.value)
                                                  if sim_node.DefectRate else 0.0)
            aas.rated_kw_of_pc[process_code]   = float(sim_node.RatedPowerKw.value or 0)
            aas.sampling_rate_of[process_code] = (float(sim_node.SamplingRate.value)
                                                  if sim_node.SamplingRate else 0.0)

    for ws_id, ws_info in aas.WWM.GeneralWorkstationData.WorkstationInformation.items():
        for apg_ref in ws_info.AssignedProcessGroups:
            for ref in apg_ref.value:
                process_code = ref.Process
                if process_code in aas.process_group_of:
                    aas.process_to_workstation[process_code] = ws_id


def _resolve_sim_node(sim_node_map: Dict[str, Dict[str, SimNode]],
                      sim_group_default: str,
                      abstract: str,
                      process_code: str) -> SimNode:
    """ProcessGroup qualifier 'OQC'/'RMA' 는 ProcessOQC/ProcessRMA 의 단일 노드, 그 외는 sim_group_default[pc]."""
    if abstract == 'OQC' and 'ProcessOQC' in sim_node_map:
        return sim_node_map['ProcessOQC']['OQC']
    if abstract == 'RMA' and 'ProcessRMA' in sim_node_map:
        return sim_node_map['ProcessRMA']['RMA']
    return sim_node_map[sim_group_default][process_code]


def _split_dep_prev(raw_value) -> List[str]:
    if raw_value is None:
        return []
    if isinstance(raw_value, str):
        return [p.strip() for p in raw_value.split(';') if p.strip()]
    return [str(p).strip() for p in raw_value if str(p).strip()]
