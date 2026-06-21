# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, ClassVar, Dict, List, Tuple


__all__ = ['ProvisionofSimulationModelsAAS', 'load']


class EntityType(str, Enum):
    SelfManagedEntity = 'SelfManagedEntity'
    CoManagedEntity = 'CoManagedEntity'


class semanticId(str):
    pass


class SMEPath(list):
    @classmethod
    def _parse(cls, raw_reference: dict | None) -> 'SMEPath':
        if not raw_reference:
            return cls()
        return cls(semanticId(key.get('value', '')) for key in raw_reference.get('keys', []))

    @staticmethod
    def _parse_as_list(raw_reference: dict | None) -> List[semanticId]:
        if not raw_reference:
            return []
        return [semanticId(key.get('value', '')) for key in raw_reference.get('keys', [])]


class Qualifier(dict):
    pass


@dataclass(kw_only=True)
class SubmodelElement:
    idShort: str = ''
    semanticId: semanticId
    Qualifier: Qualifier = field(default_factory=Qualifier)
    value: (Dict[str, SubmodelElement]
            | List[SubmodelElement]
            | List[semanticId] | SMEPath
            | str | int | float | bool
            | None) = None

    def __getattr__(self, name: str):
        return self.__dict__.get('value')[name]

    def __getitem__(self, key): return self.value[key]
    def __len__(self): return len(self.value)
    def __contains__(self, key): return key in self.value
    def items(self): return self.value.items()
    def keys(self):  return self.value.keys()
    def values(self):return self.value.values()

    def _walk_entities(self):
        if isinstance(self, Entity):
            yield self
        for children_attr in ('value', 'statements'):
            children = self.__dict__.get(children_attr)
            if isinstance(children, dict):
                for child in children.values():
                    if isinstance(child, SubmodelElement):
                        yield from child._walk_entities()
            elif isinstance(children, list):
                for child in children:
                    if isinstance(child, SubmodelElement):
                        yield from child._walk_entities()


@dataclass(kw_only=True)
class Submodel(SubmodelElement):
    id: str = ''
    value: Dict[str, SubmodelElement] = field(default_factory=dict)


@dataclass(kw_only=True)
class ManufacturingProcess(Submodel):
    _positions: ClassVar[List[Tuple[str, ...]]] = [('ManufacturingProcess',)]

    @property
    def groups(self) -> Dict[str, 'ProcessGroup']:
        return {k: v for k, v in self.value.items() if isinstance(v, ProcessGroup)}

    @property
    def model_id(self) -> str:
        for entry in _aas_registry.values():
            aas_list = entry if isinstance(entry, list) else [entry]
            for aas in aas_list:
                if self in aas.submodels.values():
                    return aas.idShort
        return ''


@dataclass(kw_only=True)
class SubmodelElementCollection(SubmodelElement):
    value: Dict[str, SubmodelElement] = field(default_factory=dict)


@dataclass(kw_only=True)
class ProcessGroup(SubmodelElementCollection):
    _positions:          ClassVar[List[Tuple[str, ...]]] = [('ManufacturingProcess', '*')]
    _positions_excluded: ClassVar[List[Tuple[str, ...]]] = [('ManufacturingProcess', 'ProcessType')]


@dataclass(kw_only=True)
class ProcessNode(SubmodelElementCollection):
    _positions: ClassVar[List[Tuple[str, ...]]] = [
        ('ManufacturingProcess', '*', '*'),
        ('SimulationModels', 'SimulationModel', 'KnowledgeGraph', 'Node', '*', '*'),
    ]

    def _resolve(self, name: str):
        child = self.value[name]
        return child.target if isinstance(child, ReferenceElement) else child

    @property
    def CycleTimeSec(self) -> 'Property':  return self._resolve('CycleTimeSec')
    @property
    def DefectRate(self)   -> 'Property':  return self._resolve('DefectRate')
    @property
    def RatedPowerKw(self) -> 'Property':  return self._resolve('RatedPowerKw')
    @property
    def DepPrev(self)      -> 'Property':  return self._resolve('DepPrev')
    @property
    def DepType(self)      -> 'Property':  return self._resolve('DepType')
    @property
    def DepNext(self)      -> 'Property | None':
        return self._resolve('DepNext') if 'DepNext' in self.value else None
    @property
    def InputBOM(self)     -> 'InputBOM':
        return self._resolve('InputBOM') if 'InputBOM' in self.value else None
    @property
    def DepWaitSec(self)   -> 'DepWaitSec | None':
        for child in self.value.values():
            if isinstance(child, DepWaitSec):
                return child
        return None
    @property
    def SamplingRate(self) -> 'SamplingRate | None':
        for child in self.value.values():
            if isinstance(child, SamplingRate):
                return child
        return None


@dataclass(kw_only=True)
class SMTEquipmentProcess(SubmodelElementCollection):
    _positions: ClassVar[List[Tuple[str, ...]]] = [
        ('SimulationModels', 'SimulationModel', 'SMTProcess', 'SMTLines', '*', '*'),
    ]

    def _catalog_property(self, child_idShort: str) -> 'Property | None':
        reference = self.value[child_idShort]
        catalog   = _find_submodel_by_id(self.semanticId)
        return _walk_for_match(catalog, reference.semanticId) if catalog is not None else None

    @property
    def CycleTimeSec(self) -> 'Property | None':  return self._catalog_property('CycleTimeSec')
    @property
    def RatedPowerKw(self) -> 'Property | None':  return self._catalog_property('RatedPowerKw')
    @property
    def DepPrev(self) -> 'Property':              return self.value['DepPrev']
    @property
    def DepType(self) -> 'Property':              return self.value['DepType']


@dataclass(kw_only=True)
class BOMCategory(SubmodelElementCollection):
    _positions: ClassVar[List[Tuple[str, ...]]] = [('HierarchicalStructures', 'BOMCategory')]


@dataclass(kw_only=True)
class BOMCategoryEntry(SubmodelElementCollection):
    _positions: ClassVar[List[Tuple[str, ...]]] = [('HierarchicalStructures', 'BOMCategory', '*')]

    @property
    def MinStock(self)   -> int:   return self.value['MinStock'].value
    @property
    def MaxStock(self)   -> int:   return self.value['MaxStock'].value
    @property
    def OrderRatio(self) -> float: return self.value['OrderRatio'].value


@dataclass(kw_only=True)
class RuntimeVariables(SubmodelElementCollection):
    _positions: ClassVar[List[Tuple[str, ...]]] = [
        ('SimulationModels', 'SimulationModel', 'RuntimeVariables'),
    ]

    def IdlePowerKw(self, GraphNode, IdleProcessRatedPowerKw, IdlePowerRatio) -> float:
        return max(GraphNode.RatedPowerKw * IdlePowerRatio, IdleProcessRatedPowerKw)

    def IdleBaselineKwh(self, KnowledgeGraph, now,
                        IdleProcessRatedPowerKw, IdlePowerRatio) -> float:
        return now * sum(
            self.IdlePowerKw(node, IdleProcessRatedPowerKw, IdlePowerRatio)
            for node in KnowledgeGraph.nodes.values()
        ) / 3600

    def MaxEpisodeEnergyKwh(self, KnowledgeGraph, target_qty,
                            IdleProcessRatedPowerKw, IdlePowerRatio) -> float:
        total = sum(target_qty.values())
        return max(1e-6, sum(
            target_qty.get(node.model_id, total)
            * node.CycleTimeSec
            * max(node.RatedPowerKw - self.IdlePowerKw(node, IdleProcessRatedPowerKw, IdlePowerRatio), 0.0)
            for node in KnowledgeGraph.nodes.values()
        ) / 3600)

    def EpisodeEnergyKwh(self, GraphNode, EpisodeEnergyKwh,
                         IdleProcessRatedPowerKw, IdlePowerRatio) -> float:
        idle_kw = self.IdlePowerKw(GraphNode, IdleProcessRatedPowerKw, IdlePowerRatio)
        return EpisodeEnergyKwh + GraphNode.CycleTimeSec * (GraphNode.RatedPowerKw - idle_kw) / 3600

    def CycleCompleted(self, ProcessCode, KnowledgeGraph) -> bool:
        return (ProcessCode in KnowledgeGraph.nodes
                and ProcessCode not in KnowledgeGraph.edges)

    def Throughput(self, ProcessCode, KnowledgeGraph, Throughput) -> dict:
        if self.CycleCompleted(ProcessCode, KnowledgeGraph):
            Throughput[KnowledgeGraph.nodes[ProcessCode].model_id] += 1
        return Throughput

    def StockShortageCount(self, warehouse, StockShortageCount) -> int:
        return StockShortageCount + sum(
            1
            for Category in warehouse.inventory
            for item in warehouse.inventory[Category].values()
            if item.present_stock < item.MinStock
        )

    def StockOverflowCount(self, warehouse, StockOverflowCount) -> int:
        return StockOverflowCount + sum(
            1
            for Category in warehouse.inventory
            for item in warehouse.inventory[Category].values()
            if item.present_stock > item.MaxStock
        )

    def IdleViolationCount(self, workers, in_progress, idle_time, now,
                           IdleWorkerThreshold, IdleViolationCount) -> int:
        for WorkstationId in workers:
            idle_slots = (workers[WorkstationId]['worker_count']
                          - in_progress.get(WorkstationId, 0))
            if idle_slots > 0:
                if WorkstationId not in idle_time:
                    idle_time[WorkstationId] = now
                elif now - idle_time[WorkstationId] > IdleWorkerThreshold:
                    IdleViolationCount += idle_slots
            else:
                idle_time.pop(WorkstationId, None)
        return IdleViolationCount

    def DuePaceDeficit(self, Throughput, target_qty, DueDay, now, DuePaceDeficit) -> float:
        deficit = 0.0
        for model_id in target_qty:
            required = min(now / DueDay[model_id], 1.0)
            progress = Throughput[model_id] / target_qty[model_id]
            deficit += max(0.0, required - progress)
        return DuePaceDeficit + deficit

    def EpisodeReturns(self, rewards, Gamma) -> list:
        EpisodeReturns, G = [], 0.0
        for reward in reversed(rewards):
            G = reward + Gamma * G
            EpisodeReturns.insert(0, G)
        return EpisodeReturns

    def Advantages(self, EpisodeReturns, values) -> list:
        Advantages = [r - v for r, v in zip(EpisodeReturns, values)]
        mean = sum(Advantages) / len(Advantages)
        std = (sum((a - mean) ** 2 for a in Advantages) / len(Advantages)) ** 0.5
        return [(a - mean) / (std + 1e-8) for a in Advantages]


@dataclass(kw_only=True)
class SubmodelElementList(SubmodelElement):
    value: List[SubmodelElement] = field(default_factory=list)

    def __getitem__(self, index: int): return self.value[index]
    def __iter__(self):                return iter(self.value)
    def __len__(self):                 return len(self.value)


@dataclass(kw_only=True)
class InputBOM(SubmodelElementList):
    _positions: ClassVar[List[Tuple[str, ...]]] = [('ManufacturingProcess', '*', '*', 'InputBOM')]

    def items(self):
        for ref in self.value:
            yield _idShort_from_cd(ref.value[0]), ref.Qualifier['Quantity']
    def keys(self):
        for ref in self.value:
            yield _idShort_from_cd(ref.value[0])
    def __getitem__(self, item_code: str):
        for ref in self.value:
            if _idShort_from_cd(ref.value[0]) == item_code:
                return ref.Qualifier['Quantity']
        raise KeyError(item_code)
    def __contains__(self, item_code: str):
        return any(_idShort_from_cd(ref.value[0]) == item_code for ref in self.value)
    def __iter__(self):
        return self.keys()
    def __len__(self):
        return len(self.value)
    def __bool__(self):
        return bool(self.value)


@dataclass(kw_only=True)
class ObservationNodeFeatures(SubmodelElementList):
    _positions: ClassVar[List[Tuple[str, ...]]] = [
        ('SimulationModels', 'SimulationModel', 'ModelArchitecture', 'Observation', 'ObservationNodeFeatures')]

    def attrs(self) -> List[str]:
        return [_idShort_from_cd(ref.value[0]) for ref in self.value]


@dataclass(kw_only=True)
class PurchaseOrder(SubmodelElementCollection):
    _positions: ClassVar[List[Tuple[str, ...]]] = [
        ('SimulationModels', 'SimulationModel', 'PurchaseOrder')]

    def items(self):
        for model_id, order in self.value.items():
            yield model_id, (order.value, order.Qualifier['DueDay'], order.Qualifier['RegisteredDay'])
    def __getitem__(self, model_id: str):
        order = self.value[model_id]
        return (order.value, order.Qualifier['DueDay'], order.Qualifier['RegisteredDay'])
    def target_qty(self) -> Dict[str, int]:
        return {model_id: order.value for model_id, order in self.value.items()}


@dataclass(kw_only=True)
class Property(SubmodelElement):
    value: Any = None


@dataclass(kw_only=True)
class DepWaitSec(Property):
    _positions: ClassVar[List[Tuple[str, ...]]] = [
        ('ManufacturingProcess', '*', '*', 'CuringTimeSec'),
    ]


@dataclass(kw_only=True)
class SamplingRate(Property):
    _positions: ClassVar[List[Tuple[str, ...]]] = [
        ('SimulationModels', 'SimulationModel', 'KnowledgeGraph', 'Node', '*', '*', 'SamplingRate'),
    ]


@dataclass(kw_only=True)
class Range(SubmodelElement):
    min: Any = None
    max: Any = None


@dataclass(kw_only=True)
class Entity(SubmodelElement):
    entityType: EntityType
    statements: Dict[str, SubmodelElement] = field(default_factory=dict)

    def __getattr__(self, name: str):
        statements = self.__dict__.get('statements')
        if isinstance(statements, dict) and name in statements:
            return statements[name]
        raise AttributeError(name)


@dataclass(kw_only=True)
class RelationshipElement(SubmodelElement):
    first: List[semanticId] | SMEPath
    second: List[semanticId] | SMEPath


def _is_identifier(key: str) -> bool:
    return '://' in key or '#' in key


def _resolve_identifier(identifier: str):
    for entry in _aas_registry.values():
        aas_list = entry if isinstance(entry, list) else [entry]
        for aas in aas_list:
            for submodel in aas.submodels.values():
                if submodel.id == identifier:
                    return submodel
                found = _walk_for_match(submodel, identifier)
                if found is not None:
                    return found
    return None


def _walk_for_match(node, target_identifier: str):
    if node.semanticId == target_identifier:
        return node
    for children_attr in ('value', 'statements'):
        children = node.__dict__.get(children_attr)
        if isinstance(children, dict):
            for child in children.values():
                found = _walk_for_match(child, target_identifier)
                if found is not None:
                    return found
        elif isinstance(children, list):
            for child in children:
                if isinstance(child, SubmodelElement):
                    found = _walk_for_match(child, target_identifier)
                    if found is not None:
                        return found
    return None


@dataclass(kw_only=True)
class ReferenceElement(SubmodelElement):
    value: List[semanticId] | SMEPath

    @classmethod
    def _parse_value(cls, raw_reference: dict | None):
        return SMEPath._parse_as_list(raw_reference)

    def __getitem__(self, key):
        return self.target[key]

    @property
    def target(self):
        keys = self.value
        if not keys:
            return None
        first = _resolve_identifier(keys[0])
        if first is None:
            return None
        if len(keys) == 1:
            return first
        if all(_is_identifier(key) for key in keys[1:]):
            node = first
            for key in keys[1:]:
                found = _walk_for_match(node, key)
                if found is None:
                    return [_resolve_identifier(key) for key in keys]
                node = found
            return node
        node = first
        for key in keys[1:]:
            node = node.value[key]
        return node


@dataclass(kw_only=True)
class ProcessNodePropertyRef(ReferenceElement):
    _positions: ClassVar[List[Tuple[str, ...]]] = [
        ('SimulationModels', 'SimulationModel', 'Node', '*', '*', 'CycleTimeSec'),
        ('SimulationModels', 'SimulationModel', 'Node', '*', '*', 'DefectRate'),
        ('SimulationModels', 'SimulationModel', 'Node', '*', '*', 'RatedPowerKw'),
    ]
    value: SMEPath

    @classmethod
    def _parse_value(cls, raw_reference): return SMEPath._parse(raw_reference)

    @property
    def target(self) -> Property:
        keys = self.value
        node = _find_submodel_by_id(keys[0])
        for key in keys[1:]:
            node = node.value[key]
        return node


@dataclass(kw_only=True)
class ProcessNodeListRef(ReferenceElement):
    _positions: ClassVar[List[Tuple[str, ...]]] = [
        ('SimulationModels', 'SimulationModel', 'KnowledgeGraph', 'Action', 'IndependentSequence', '*'),
        ('SimulationModels', 'SimulationModel', 'KnowledgeGraph', 'Action', 'DependentSequence', '*'),
        ('SimulationModels', 'SimulationModel', 'KnowledgeGraph', 'Action', 'DependentJoin', '*'),
        ('SimulationModels', 'SimulationModel', 'KnowledgeGraph', 'Action', 'AssignedProcessGroups', '*'),
    ]
    value: List[semanticId]
    @property
    def target(self) -> List[ProcessNode]:
        return [_find_typed_by_semantic(url, ProcessNode) for url in self.value]


@dataclass(kw_only=True)
class AssignedProcessGroupsRef(ReferenceElement):
    _positions: ClassVar[List[Tuple[str, ...]]] = [
        ('WorkstationWorkerMatchingData', 'GeneralWorkstationData', 'WorkstationInformation', '*', 'AssignedProcessGroups', '*'),
    ]
    value: List[semanticId]
    @property
    def target(self) -> List[ProcessNode]:
        return [node for url in self.value
                if (node := _find_typed_by_semantic(url, ProcessNode)) is not None]


@dataclass(kw_only=True)
class MPSubmodelListRef(ReferenceElement):
    _positions: ClassVar[List[Tuple[str, ...]]] = [
        ('SimulationModels', 'SimulationModel', 'Warehouse', 'InputBOM'),
    ]
    value: List[semanticId]
    @property
    def target(self) -> List[ManufacturingProcess]:
        return [_find_submodel_by_id(url) for url in self.value]


@dataclass(kw_only=True)
class BOMCategoryRef(ReferenceElement):
    _positions: ClassVar[List[Tuple[str, ...]]] = [
        ('SimulationModels', 'SimulationModel', 'Warehouse', 'MinStock'),
        ('SimulationModels', 'SimulationModel', 'Warehouse', 'MaxStock'),
        ('SimulationModels', 'SimulationModel', 'Warehouse', 'OrderRatio'),
    ]
    value: List[semanticId]
    @property
    def target(self) -> BOMCategory:
        return _find_typed_by_semantic(self.value[0], BOMCategory)


@dataclass(kw_only=True)
class WWMPropertyRef(ReferenceElement):
    _positions: ClassVar[List[Tuple[str, ...]]] = [
        ('SimulationModels', 'SimulationModel', 'DefaultParameters', 'WorkStartTime'),
        ('SimulationModels', 'SimulationModel', 'DefaultParameters', 'WorkEndTime'),
        ('SimulationModels', 'SimulationModel', 'DefaultParameters', 'BreakDurationMin'),
    ]
    value: SMEPath

    @classmethod
    def _parse_value(cls, raw_reference): return SMEPath._parse(raw_reference)

    @property
    def target(self) -> Property:
        wwm_submodel = _find_submodel_by_id(self.value[0])
        return _walk_for_match(wwm_submodel, self.value[1])


def _find_submodel_by_id(url: str):
    for entry in _aas_registry.values():
        aas_list = entry if isinstance(entry, list) else [entry]
        for aas in aas_list:
            for submodel in aas.submodels.values():
                if submodel.id == url:
                    return submodel
    return None


def _find_submodel_by_semantic(url: str):
    for entry in _aas_registry.values():
        aas_list = entry if isinstance(entry, list) else [entry]
        for aas in aas_list:
            for submodel in aas.submodels.values():
                if submodel.semanticId == url:
                    return submodel
    return None


def _find_typed_by_semantic(url: str, target_type: type):
    for entry in _aas_registry.values():
        aas_list = entry if isinstance(entry, list) else [entry]
        for aas in aas_list:
            for submodel in aas.submodels.values():
                found = _walk_for_typed(submodel, url, target_type)
                if found is not None:
                    return found
    return None


def _walk_for_typed(node, target_url: str, target_type: type):
    if isinstance(node, target_type) and node.semanticId == target_url:
        return node
    for children_attr in ('value', 'statements'):
        children = node.__dict__.get(children_attr)
        if isinstance(children, dict):
            for child in children.values():
                found = _walk_for_typed(child, target_url, target_type)
                if found is not None: return found
        elif isinstance(children, list):
            for child in children:
                if isinstance(child, SubmodelElement):
                    found = _walk_for_typed(child, target_url, target_type)
                    if found is not None: return found
    return None


def _idShort_from_cd(identifier: str) -> str:
    if '/ids/cd/' in identifier:
        return identifier.split('/ids/cd/')[1].split('/')[0]
    return identifier


@dataclass(kw_only=True)
class AssetAdministrationShell:
    idShort: str = ''
    submodels: Dict[str, Submodel] = field(default_factory=dict)

    def __getattr__(self, name: str) -> Submodel:
        return self.__dict__.get('submodels')[name]

    @property
    def workers(self) -> Dict[str, Dict[str, Any]]:
        wwm = _aas_registry['WorkstationWorkerMatchingDataAAS']
        if not wwm.submodels:
            return {}
        workstation_info = (wwm.submodels['WorkstationWorkerMatchingData']
                            .value['GeneralWorkstationData']
                            .value['WorkstationInformation'])
        return {
            ws.idShort: {
                'worker_count': len(ws.WorkstationConfigurationRecords),
                'UnitsPerWorker': (ws.value['UnitsPerWorker'].value
                                   if 'UnitsPerWorker' in ws.value else 1),
                'ProcessCode': [node.idShort
                                for ref in ws.AssignedProcessGroups
                                for node in ref.target]
            }
            for ws in workstation_info.values()
        }

    def _grouped_bom(self, self_managed: bool | None) -> Dict[str, List[str]]:
        result: Dict[str, List[str]] = {}
        for aas in ProductAAS:
            hs = aas.submodels.get('HierarchicalStructures')
            if hs is None:
                continue
            for entity in hs._walk_entities():
                category = entity.Qualifier.get('Category')
                if not category:
                    continue
                is_self = entity.entityType == EntityType.SelfManagedEntity
                if self_managed is not None and is_self != self_managed:
                    continue
                bucket = result.setdefault(category, [])
                if entity.idShort not in bucket:
                    bucket.append(entity.idShort)
        return result

    @property
    def WarehouseManagedBOM(self) -> Dict[str, List[str]]:
        return self._grouped_bom(None)

    @property
    def CoManagedBOM(self) -> Dict[str, List[str]]:
        return self._grouped_bom(False)

    @property
    def SelfManagedBOM(self) -> Dict[str, List[str]]:
        return self._grouped_bom(True)


ProvisionofSimulationModelsAAS = AssetAdministrationShell()
WorkstationWorkerMatchingDataAAS = AssetAdministrationShell()
ProductAAS: List[AssetAdministrationShell] = []


_aas_registry: Dict[str, AssetAdministrationShell | List[AssetAdministrationShell]] = {
    'ProductAAS': ProductAAS,
    'WorkstationWorkerMatchingDataAAS': WorkstationWorkerMatchingDataAAS,
    'ProvisionofSimulationModelsAAS': ProvisionofSimulationModelsAAS,
}


def load(json_path: str) -> None:
    with open(json_path, encoding='utf-8') as file:
        raw_data = json.load(file)

    aas_idShort = raw_data['assetAdministrationShells'][0]['idShort']

    if aas_idShort == 'ProvisionofSimulationModelsAAS':
        target_aas = ProvisionofSimulationModelsAAS
    elif aas_idShort == 'WorkstationWorkerMatchingDataAAS':
        target_aas = WorkstationWorkerMatchingDataAAS
    else:
        target_aas = AssetAdministrationShell()
        ProductAAS.append(target_aas)

    target_aas.idShort = aas_idShort
    target_aas.submodels = {
        raw_submodel['idShort']: _build_sme(raw_submodel, (raw_submodel['idShort'],))
        for raw_submodel in raw_data.get('submodels', [])
    }


def _build_sme(raw_sme: dict, position: tuple) -> SubmodelElement:

    semantic_keys = (raw_sme.get('semanticId') or {}).get('keys') or []
    semantic_value = semantic_keys[0].get('value', '') if semantic_keys else ''
    base_fields = {
        'idShort': raw_sme.get('idShort', ''),
        'semanticId': semanticId(semantic_value),
        'Qualifier': Qualifier(
            (qualifier['type'], _cast_value(qualifier.get('value'), qualifier.get('valueType')))
            for qualifier in raw_sme.get('qualifiers', [])
        ),
    }

    modelType = raw_sme['modelType']
    domain_cls = _match_domain(position)

    if modelType == 'Property':
        cls = domain_cls if (domain_cls and issubclass(domain_cls, Property)) else Property
        return cls(**base_fields,
                   value=_cast_value(raw_sme.get('value'), raw_sme.get('valueType')))
    if modelType == 'Range':
        cls = domain_cls if (domain_cls and issubclass(domain_cls, Range)) else Range
        valueType = raw_sme.get('valueType')
        return cls(**base_fields,
                   min=_cast_value(raw_sme.get('min'), valueType),
                   max=_cast_value(raw_sme.get('max'), valueType))
    if modelType == 'SubmodelElementCollection':
        cls = domain_cls if (domain_cls and issubclass(domain_cls, SubmodelElementCollection)) else SubmodelElementCollection
        children = {child['idShort']: _build_sme(child, position + (child['idShort'],))
                    for child in raw_sme.get('value', [])}
        return cls(**base_fields, value=children)
    if modelType == 'SubmodelElementList':
        cls = domain_cls if (domain_cls and issubclass(domain_cls, SubmodelElementList)) else SubmodelElementList
        return cls(
            **base_fields,
            value=[_build_sme(child, position + ('*',)) for child in raw_sme.get('value', [])],
        )
    if modelType == 'Submodel':
        cls = domain_cls if (domain_cls and issubclass(domain_cls, Submodel)) else Submodel
        children = {child['idShort']: _build_sme(child, position + (child['idShort'],))
                    for child in raw_sme.get('submodelElements', [])}
        return cls(**base_fields, id=raw_sme.get('id', ''), value=children)
    if modelType == 'Entity':
        cls = domain_cls if (domain_cls and issubclass(domain_cls, Entity)) else Entity
        return cls(
            **base_fields,
            entityType=EntityType(raw_sme['entityType']),
            statements={child['idShort']: _build_sme(child, position + (child['idShort'],))
                        for child in raw_sme.get('statements', [])},
        )
    if modelType == 'ReferenceElement':
        cls = domain_cls if (domain_cls and issubclass(domain_cls, ReferenceElement)) else ReferenceElement
        return cls(**base_fields, value=cls._parse_value(raw_sme.get('value')))
    if modelType == 'RelationshipElement':
        cls = domain_cls if (domain_cls and issubclass(domain_cls, RelationshipElement)) else RelationshipElement
        return cls(
            **base_fields,
            first=SMEPath._parse_as_list(raw_sme.get('first')),
            second=SMEPath._parse_as_list(raw_sme.get('second')),
        )
    return SubmodelElement(**base_fields)


def _match_domain(position: tuple):
    best_cls = None
    best_specificity = -1
    for cls in _walk_subclasses(SubmodelElement):
        for pattern in getattr(cls, '_positions_excluded', ()):
            if _position_matches(position, pattern):
                return None
        for pattern in getattr(cls, '_positions', ()):
            if _position_matches(position, pattern):
                specificity = sum(1 for slot in pattern if slot != '*')
                if specificity > best_specificity:
                    best_cls = cls
                    best_specificity = specificity
    return best_cls


def _position_matches(position: tuple, pattern: tuple) -> bool:
    if len(pattern) != len(position):
        return False
    return all(p == '*' or p == s for s, p in zip(position, pattern))


def _walk_subclasses(root: type):
    for sub in root.__subclasses__():
        yield sub
        yield from _walk_subclasses(sub)


def _cast_value(raw_value, valueType: str | None):
    if raw_value is None or not valueType:
        return raw_value
    type_name = valueType.split(':')[-1]
    if type_name in ('int', 'integer', 'long', 'short', 'byte'):
        return int(raw_value)
    if type_name in ('float', 'double', 'decimal'):
        return float(raw_value)
    if type_name == 'boolean':
        return raw_value in (True, 'true', 'True', 'TRUE', 1, '1')
    if type_name == 'time':
        parts = raw_value.split(':')
        hours = int(parts[0])
        minutes = int(parts[1]) if len(parts) > 1 else 0
        seconds = int(parts[2]) if len(parts) > 2 else 0
        return hours * 3600 + minutes * 60 + seconds
    return raw_value
