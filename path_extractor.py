# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


__all__ = [
    'load_workstation_worker_matching_data',
    'load_hierarchical_structures',
    'load_manufacturing_process',
    'load_provision_of_simulation_models',
]


_CD_URL_RE = re.compile(r'/ids/cd/(?P<idShort>[^/]+)/[^/]+/[^/]+/?$')


@dataclass
class GlobalReference:
    value: str

    @property
    def Process(self) -> str:
        m = _CD_URL_RE.search(self.value)
        return m.group('idShort')


@dataclass
class AssignedProcessGroupRef:
    value: List[GlobalReference] = field(default_factory=list)


@dataclass
class SkillLevelProperty:
    idShort: str
    value: int


@dataclass
class SkillLevelType:
    levels: List[SkillLevelProperty] = field(default_factory=list)

    def __getitem__(self, idShort: str) -> int:
        for p in self.levels:
            if p.idShort == idShort:
                return p.value


@dataclass
class WorkstationInformation:
    idShort: str = ''
    AssignedProcessGroups: List[AssignedProcessGroupRef] = field(default_factory=list)
    WorkstationConfigurationRecords: Dict[str, int] = field(default_factory=dict)


@dataclass
class GeneralWorkstationData:
    WorkstationInformation: Dict[str, WorkstationInformation] = field(default_factory=dict)


@dataclass
class WorkstationWorkerMatchingData:
    SkillLevelType: SkillLevelType = field(default_factory=SkillLevelType)
    GeneralWorkstationData: GeneralWorkstationData = field(default_factory=GeneralWorkstationData)


@dataclass
class EntityQualifier:
    SMT_Side: str = ''   # 'single' | 'double'
    SMT_THT: str = ''    # 'TRUE' | 'FALSE'

    def __getitem__(self, key: str) -> str:
        return getattr(self, key)


@dataclass
class Entity:
    idShort: str
    entityType: str  # 'SelfManagedEntity' | 'CoManagedEntity'
    qualifier: EntityQualifier = field(default_factory=EntityQualifier)
    statements: Dict[str, 'Entity'] = field(default_factory=dict)


@dataclass
class HierarchicalStructures:
    ArcheType: str = ''
    entities: Dict[str, Entity] = field(default_factory=dict)

    def entityType(self, category: str) -> Dict[str, Entity]:
        out: Dict[str, Entity] = {}
        for top in self.entities.values():
            self._walk(top, category, out)
        return out

    @staticmethod
    def _walk(ent: Entity, target: str, out: Dict[str, Entity]) -> None:
        if ent.entityType == target:
            out[ent.idShort] = ent
        for child in ent.statements.values():
            HierarchicalStructures._walk(child, target, out)


@dataclass
class Property:
    value: Any = None


@dataclass
class BomQualifier:
    Quantity: float = 0.0


class BomRef(dict):
    def __init__(self, refs: List = None):
        super().__init__()
        self.refs: List = []
        if refs:
            for url, qual in refs:
                self.add(url, qual)

    def add(self, value: str, qualifier: BomQualifier) -> None:
        m = _CD_URL_RE.search(value)
        if m:
            self[m.group('idShort')] = float(qualifier.Quantity)
            self.refs.append((value, qualifier))


@dataclass
class ProcessNode:
    DepType: Property = field(default_factory=Property)
    DepPrev: Property = field(default_factory=Property)
    ProcessGroup: Property = field(default_factory=Property)
    InputBOM: BomRef = field(default_factory=BomRef)


@dataclass
class ProcessGroup:
    processes: Dict[str, ProcessNode] = field(default_factory=dict)

    def __getitem__(self, key: str) -> ProcessNode:
        return self.processes[key]


@dataclass
class ManufacturingProcess:
    groups: Dict[str, ProcessGroup] = field(default_factory=dict)

    def __getitem__(self, key: str) -> ProcessGroup:
        return self.groups[key]


@dataclass
class SimNode:
    CycleTimeSec: Property = field(default_factory=Property)
    RatedPowerKw: Property = field(default_factory=Property)
    DefectRate: Optional[Property] = None
    SamplingRate: Optional[Property] = None


@dataclass
class Ref:
    value: List[str] = field(default_factory=list)


@dataclass
class Action:
    IndependentSequence: List[Ref] = field(default_factory=list)
    DependentSequence: List[Ref] = field(default_factory=list)
    DependentJoin: List[Ref] = field(default_factory=list)


@dataclass
class SimulationModel:
    Node: Dict[str, Dict[str, SimNode]] = field(default_factory=dict)
    Action: Action = field(default_factory=Action)


@dataclass
class SimulationModels:
    SimulationModel: SimulationModel = field(default_factory=SimulationModel)


@dataclass
class ProvisionofSimulationModelsAAS:
    SimulationModels: SimulationModels = field(default_factory=SimulationModels)


# ===== 진입점 =====

def load_workstation_worker_matching_data(json_path: str) -> WorkstationWorkerMatchingData:
    sm = AasView(_find_submodel(_read_json(json_path), 'WorkstationWorkerMatchingData'))
    skill = SkillLevelType(levels=[
        SkillLevelProperty(idShort=p.idShort, value=int(p.value))
        for p in sm.SkillLevelType
    ])
    infos: List[WorkstationInformation] = []
    for wsi in sm.GeneralWorkstationData.WorkstationInformation:
        apgs = [
            AssignedProcessGroupRef(
                value=[GlobalReference(value=k.value) for k in ref.value]
            )
            for ref in wsi.AssignedProcessGroups
        ]
        wcr = {
            rec.WorkerId.value: skill[rec.SkillLevel.value]
            for rec in wsi.WorkstationConfigurationRecords
        }
        infos.append(WorkstationInformation(
            idShort=wsi.idShort,
            AssignedProcessGroups=apgs,
            WorkstationConfigurationRecords=wcr,
        ))
    return WorkstationWorkerMatchingData(
        SkillLevelType=skill,
        GeneralWorkstationData=GeneralWorkstationData(
            WorkstationInformation={ws.idShort: ws for ws in infos}),
    )


def load_hierarchical_structures(json_path: str) -> HierarchicalStructures:
    sm = AasView(_find_submodel(_read_json(json_path), 'HierarchicalStructures'))
    arche = sm.ArcheType.value if 'ArcheType' in sm else ''
    entities = {
        elem.idShort: _parse_entity(elem)
        for elem in sm if elem.modelType == 'Entity'
    }
    return HierarchicalStructures(ArcheType=arche, entities=entities)


def load_manufacturing_process(json_path: str) -> ManufacturingProcess:
    sm = AasView(_find_submodel(_read_json(json_path), 'ManufacturingProcess'))
    groups: Dict[str, ProcessGroup] = {}
    for elem in sm:
        if elem.modelType != 'SubmodelElementCollection':
            continue
        children = list(elem)
        if children and all(c.modelType == 'SubmodelElementCollection' for c in children):
            groups[elem.idShort] = _parse_process_group(elem)
    return ManufacturingProcess(groups=groups)


def load_provision_of_simulation_models(json_path: str) -> ProvisionofSimulationModelsAAS:
    sm = AasView(_find_submodel(_read_json(json_path), 'SimulationModels'))
    smodel = sm.SimulationModel
    node_map: Dict[str, Dict[str, SimNode]] = {}
    for group in smodel.Node:
        node_map[group.idShort] = {
            n.idShort: _parse_sim_node(n) for n in group
        }
    act = smodel.Action
    action = Action(
        IndependentSequence=_parse_ref_list(act.IndependentSequence),
        DependentSequence=_parse_ref_list(act.DependentSequence),
        DependentJoin=_parse_ref_list(act.DependentJoin),
    )
    return ProvisionofSimulationModelsAAS(
        SimulationModels=SimulationModels(
            SimulationModel=SimulationModel(Node=node_map, Action=action)
        )
    )


# ===== 내부 유틸 =====

def _parse_entity(view: 'AasView') -> Entity:
    return Entity(
        idShort=view.idShort,
        entityType=view.entityType,
        qualifier=EntityQualifier(
            SMT_Side=view.qualifier.get('SMT_Side', ''),
            SMT_THT=view.qualifier.get('SMT_THT', ''),
        ),
        statements={
            ce.idShort: _parse_entity(ce)
            for ce in view.statements if ce.modelType == 'Entity'
        },
    )


def _parse_process_group(view: 'AasView') -> ProcessGroup:
    abstract = view.qualifier.get('ProcessGroup', '')
    pg = ProcessGroup(processes={})
    for proc in view:
        process_node = _parse_process_node(proc)
        if not process_node.ProcessGroup.value:
            process_node.ProcessGroup = Property(value=abstract)
        pg.processes[proc.idShort] = process_node
    return pg


def _parse_process_node(view: 'AasView') -> ProcessNode:
    pn = ProcessNode()
    for elem in view:
        idsh = elem.idShort
        if idsh == 'DepType':
            pn.DepType = Property(value=elem.value)
        elif idsh == 'DepPrev':
            pn.DepPrev = Property(value=elem.value)
        elif idsh == 'InputBOM':
            pn.InputBOM = _parse_input_bom(elem)
    pn.ProcessGroup = Property(value=view.qualifier.get('ProcessGroup', ''))
    return pn


def _parse_input_bom(view: 'AasView') -> BomRef:
    bom = BomRef()
    for ref in view:
        qty = float(ref.qualifier.get('Quantity', '0') or 0)
        keys = ref.value
        if len(keys) > 0:
            bom.add(keys[0].value, BomQualifier(Quantity=qty))
    return bom


def _parse_sim_node(view: 'AasView') -> SimNode:
    n = SimNode()
    for elem in view:
        idsh = elem.idShort
        if idsh == 'CycleTimeSec':
            n.CycleTimeSec = Property(value=int(elem.value))
        elif idsh == 'RatedPowerKw':
            n.RatedPowerKw = Property(value=float(elem.value))
        elif idsh == 'DefectRate':
            n.DefectRate = Property(value=float(elem.value))
        elif idsh == 'SamplingRate':
            n.SamplingRate = Property(value=float(elem.value))
    return n


def _parse_ref_list(view: 'AasView') -> List[Ref]:
    out: List[Ref] = []
    for ref_elem in view:
        keys = ref_elem.value
        out.append(Ref(value=[k.value for k in keys]))
    return out


class AasView:
    __slots__ = ('_raw',)

    def __init__(self, raw):
        self._raw = raw

    def __repr__(self):
        if isinstance(self._raw, list):
            return f'<AasView list[{len(self._raw)}]>'
        return (f'<AasView idShort={self._raw.get("idShort")!r} '
                f'mt={self._raw.get("modelType")!r}>')

    def __getattr__(self, name: str):
        if name.startswith('_'):
            raise AttributeError(name)
        raw = self._raw
        if isinstance(raw, dict):
            if name in ('idShort', 'entityType', 'modelType', 'valueType', 'category'):
                return raw.get(name)
            if name == 'qualifier':
                return _QualifierAccess(raw.get('qualifiers') or [])
            if name == 'statements':
                return AasView(raw.get('statements') or [])
            if name == 'value':
                return _value_of(raw)
        return self._child(name)

    def _children(self):
        raw = self._raw
        if isinstance(raw, list):
            return raw
        v = raw.get('value')
        if isinstance(v, list):
            return v
        return raw.get('submodelElements') or raw.get('statements') or []

    def _child(self, idShort: str) -> 'AasView':
        for c in self._children():
            if isinstance(c, dict) and c.get('idShort') == idShort:
                return AasView(c)
        raise AttributeError(f"No child idShort={idShort!r}")

    def __getitem__(self, key):
        if isinstance(key, int):
            c = self._children()[key]
            return AasView(c) if isinstance(c, dict) else c
        return self._child(key)

    def __contains__(self, idShort: str) -> bool:
        return any(isinstance(c, dict) and c.get('idShort') == idShort
                   for c in self._children())

    def __iter__(self):
        for c in self._children():
            yield AasView(c) if isinstance(c, dict) else c

    def __len__(self):
        return len(self._children())


def _value_of(raw: dict):
    mt = raw.get('modelType')
    v = raw.get('value')
    if mt == 'ReferenceElement':
        return AasView((v or {}).get('keys') or [])
    if isinstance(v, list):
        return AasView(v)
    return v


class _QualifierAccess:
    __slots__ = ('_q',)

    def __init__(self, qualifiers: list):
        self._q = qualifiers

    def __getitem__(self, qtype: str):
        for q in self._q:
            if q.get('type') == qtype:
                return q.get('value')
        raise KeyError(qtype)

    def __contains__(self, qtype: str) -> bool:
        return any(q.get('type') == qtype for q in self._q)

    def get(self, qtype: str, default: Any = None) -> Any:
        try:
            return self[qtype]
        except KeyError:
            return default


def _read_json(path: str) -> dict:
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def _find_submodel(doc: dict, idShort: str) -> dict:
    for sm in (doc.get('submodels') or []):
        if sm.get('idShort') == idShort:
            return sm
