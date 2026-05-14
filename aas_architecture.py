# -*- coding: utf-8 -*-
"""AAS 메타모델 — 시뮬레이션이 AAS 데이터를 받는 유일한 창구.

지금 단계: 각 SME / 데이터형식이 갖는 **속성만** 선언. 접근 규칙·로직은 추후 부착.

자식 접근 통일 규칙 (TBD)
    container.idShort        # 자식 idShort 가 고정 — idShort 그대로 속성명
    container[idShort]       # 자식 idShort 가 다양 (SMC)
    container[i]             # 정수 인덱스 (SML, 순서 의미)
    container[...]           # 모든 자식
    container[predicate]     # callable 필터

SME 자체 필드
    .idShort  .semanticId  .Qualifier  .value  ...

Qualifier
    sme.Qualifier              → {type: value} dict
    sme.Qualifier['SMT_Side']  → value 직접

경로 deref (TBD)
    refElem.target
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List


__all__ = ['ProvisionofSimulationModelsAAS', 'load']


# region
# ====================================================================
# 열거형
# ====================================================================
class EntityType(str, Enum):
    SelfManagedEntity = 'SelfManagedEntity'
    CoManagedEntity = 'CoManagedEntity'
# endregion


# region
# ====================================================================
# 참조 / 경로 / Qualifier (데이터 형식)
# ====================================================================
class semanticId(str):
    """ConceptDescription 참조 — 인스턴스 자체가 CD URL 문자열.

    >>> s = semanticId('https://.../ids/cd/Process/1/0')
    >>> s == 'https://.../ids/cd/Process/1/0'   # True (str 그 자체)
    """


class SMEPath(list):
    """SME 경로 — 식별자(URL/IRDI)와 idShort 들의 sequence (list 의 일종).

    `List[semanticId]` 와의 차이:
        - SMEPath: 키들이 chain 으로 연결돼 단일 대상 SME 를 가리킴 (target = 경로 끝)
        - List[semanticId]: 각 키가 독립된 대상을 가리킴 (target = 대상들의 list)
    """
    @classmethod
    def _parse(cls, raw_reference: dict | None) -> 'SMEPath':
        """raw reference dict → SMEPath 인스턴스 (체인 경로용). 내부 전용."""
        if not raw_reference:
            return cls()
        return cls(semanticId(key.get('value', '')) for key in raw_reference.get('keys', []))

    @staticmethod
    def _parse_as_list(raw_reference: dict | None) -> List[semanticId]:
        """raw reference dict → List[semanticId] (각 키가 독립 대상인 ref 용).
        SMEPath 가 아닌 일반 reference 들의 공통 파서 — SMEPath 안에 모아둠. 내부 전용."""
        if not raw_reference:
            return []
        return [semanticId(key.get('value', '')) for key in raw_reference.get('keys', [])]


class Qualifier(dict):
    """`{type: value}` dict 자체. 이름 Qualifier 로 식별, 추후 메서드 부착 위치."""
# endregion


# region
# ====================================================================
# SubmodelElement 베이스 — 모든 SME 공통 필드
# ====================================================================
@dataclass(kw_only=True)
class SubmodelElement:
    # region [구조]
    idShort: str = ''
    semanticId: semanticId                                       # 필수
    Qualifier: Qualifier = field(default_factory=Qualifier)      # {type: value}
    value: (Dict[str, SubmodelElement]                           # Submodel, SMC 자식
            | List[SubmodelElement]                              # SML 자식
            | List[semanticId] | SMEPath                         # ReferenceElement 경로
            | str | int | float | bool                           # Property scalar
            | None) = None
    # endregion

    # region [로직]
    def __getattr__(self, name: str):
        """`.idShort` 자식 접근: `value` dict 에서 lookup. (Submodel/SMC 가 해당)
        `value` 가 dict 가 아닌 SME (Property scalar, SML list 등) 는 자연스럽게 TypeError."""
        return self.__dict__.get('value')[name]

    # dict-like / list-like 위임 (value 가 dict/list 인 SME — Submodel/SMC/SML — 에만 의미 있음)
    def __getitem__(self, key): return self.value[key]
    def __len__(self): return len(self.value)
    def __contains__(self, key): return key in self.value
    def items(self): return self.value.items()
    def keys(self):  return self.value.keys()
    def values(self):return self.value.values()

    def _walk_entities(self):
        """이 노드 트리 아래 모든 Entity yield (자기 자신 포함). 재귀."""
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
    # endregion
# endregion


# region
# ====================================================================
# 구체 SME 타입 — 자체 필드만
# ====================================================================
@dataclass(kw_only=True)
class Submodel(SubmodelElement):
    """자식 idShort 로 키된 dict."""
    id: str = ''                                                 # AAS V3 unique identifier (URL)
    value: Dict[str, SubmodelElement] = field(default_factory=dict)


@dataclass(kw_only=True)
class SubmodelElementCollection(SubmodelElement):
    """자식 idShort 로 키된 dict."""
    value: Dict[str, SubmodelElement] = field(default_factory=dict)


@dataclass(kw_only=True)
class SubmodelElementList(SubmodelElement):
    """순서 의미 — index 로 접근하는 list."""
    value: List[SubmodelElement] = field(default_factory=list)

    def __getitem__(self, index: int): return self.value[index]
    def __iter__(self):                return iter(self.value)
    def __len__(self):                 return len(self.value)


@dataclass(kw_only=True)
class Property(SubmodelElement):
    value: Any = None


@dataclass(kw_only=True)
class Range(SubmodelElement):
    min: Any = None
    max: Any = None


@dataclass(kw_only=True)
class Entity(SubmodelElement):
    # region [구조]
    entityType: EntityType                                       # 필수 (default 없음)
    statements: Dict[str, SubmodelElement] = field(default_factory=dict)
    # endregion

    # region [로직]
    def __getattr__(self, name: str):
        """Entity 의 자식은 `value` 가 아니라 `statements` dict 에서 lookup."""
        statements = self.__dict__.get('statements')
        if isinstance(statements, dict) and name in statements:
            return statements[name]
        raise AttributeError(name)
    # endregion


@dataclass(kw_only=True)
class RelationshipElement(SubmodelElement):
    first: List[semanticId] | SMEPath                            # 필수
    second: List[semanticId] | SMEPath                           # 필수


@dataclass(kw_only=True)
class ReferenceElement(SubmodelElement):
    # region [구조]
    value: List[semanticId] | SMEPath                            # 필수 — 가리키는 경로
    # endregion

    # region [로직: 파서]
    @classmethod
    def _parse_value(cls, raw_reference: dict | None):
        """raw reference → value 필드 값. 기본은 List[semanticId].
        SMEPath 가 필요한 자식 클래스는 override 해서 SMEPath._parse 사용. 내부 전용."""
        return SMEPath._parse_as_list(raw_reference)
    # endregion

    # region [로직: target 위임]
    def __getitem__(self, key):
        """ref[i] / ref[idShort] → target[i] / target[idShort] (자기 자신을 target 처럼)."""
        return self.target[key]
    # endregion

    # region [로직]
    @property
    def target(self):
        """value 의 키들로 대상 SME 를 찾는다. 각 키는 외부 식별자(URL/IRDI) 또는 idShort.
            - 식별자: 모든 AAS walk 해서 Submodel.id 또는 SME.semanticId 와 직접 일치 비교
            - idShort: 현재 노드의 자식 dict lookup
            - 첫 키 resolve 후 나머지를 path 로 시도 → path 깨지면 keys 전체를 list 로 간주
        """
        keys = self.value
        if not keys:
            return None
        first = _resolve_identifier(keys[0])
        if first is None:                                          # 대상 AAS 미로드 등 → 조기 None
            return None
        if len(keys) == 1:
            return first
        # keys[1:] 가 모두 식별자 — path 안에서 찾을 수 있으면 path, 아니면 list
        if all(_is_identifier(key) for key in keys[1:]):
            node = first
            for key in keys[1:]:
                found = _walk_for_match(node, key)
                if found is None:
                    return [_resolve_identifier(key) for key in keys]
                node = found
            return node
        # 첫 식별자 + idShort 들 (단일 path)
        node = first
        for key in keys[1:]:
            node = node.value[key]
        return node
    # endregion
# endregion


# region
# ====================================================================
# 내부 — 외부 식별자 (URL/IRDI) → SME 매칭
# Submodel.id 또는 SME.semanticId 와 문자열 직접 비교.
# ====================================================================
def _is_identifier(key: str) -> bool:
    """key 가 외부 식별자(IRI URL 또는 IRDI) 인지. idShort 와 구분.
    - IRI: '://' 포함 (URL)
    - IRDI: '#' 포함 (ECLASS '0173-1#XX-NNNNNN#VVV', CDD 등)"""
    return '://' in key or '#' in key


def _resolve_identifier(identifier: str):
    """모든 AAS 의 submodel walk 해서 Submodel.id 또는 SME.semanticId 가
    identifier 와 정확히 일치하는 SME 반환. 못 찾으면 None."""
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
    """node subtree 에서 semanticId == target_identifier 인 SME 찾기 (자기 자신 포함).
    `value` (Submodel/SMC/SML) 와 `statements` (Entity) 만 자식 컨테이너로 인정.
    ReferenceElement.value (List[semanticId] str 들) 같은 비-SME 리스트는 자식 아님."""
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
# endregion


# region
# ====================================================================
# 도메인 SME 클래스 — 위치 기반 매칭 (`_DOMAIN_BY_POSITION`)
# 각 클래스는 트리의 특정 위치에서 인스턴스화. 자기 속성의 타입을 @property 로 명시.
# 자유롭게 추가/제거 가능 — 위치 매칭 안 되면 generic SME 로 fallback.
# ====================================================================

@dataclass(kw_only=True)
class ManufacturingProcess(Submodel):
    """제품 AAS 의 ManufacturingProcess Submodel."""
    @property
    def groups(self) -> Dict[str, 'ProcessGroup']:
        """ProcessType 같은 비-그룹 자식 제외."""
        return {k: v for k, v in self.value.items() if isinstance(v, ProcessGroup)}

    @property
    def model_id(self) -> str:
        """이 MP 가 속한 ProductAAS 의 idShort (registry walk)."""
        for entry in _aas_registry.values():
            aas_list = entry if isinstance(entry, list) else [entry]
            for aas in aas_list:
                if self in aas.submodels.values():
                    return aas.idShort
        return ''


@dataclass(kw_only=True)
class ProcessGroup(SubmodelElementCollection):
    """공정 그룹 — `value: Dict[str, ProcessNode]`."""


@dataclass(kw_only=True)
class ProcessNode(SubmodelElementCollection):
    """공정 노드. 자식 SME 들은 idShort 로 접근. 자식 중 ReferenceElement 면 자동 deref.
    자식 타입:
        CycleTimeSec  → Property (int)
        DefectRate    → Property (float)
        RatedPowerKw  → Property (float)
        DepPrev       → Property (str, ';' 구분으로 join)
        DepType       → Property (str: 'SEQUENCE'|'JOIN'|'FORK')
        InputBOM      → InputBOM (dict-like {item_code: Quantity})
    """
    def _resolve(self, name: str):
        child = self.value[name]
        return child.target if isinstance(child, ReferenceElement) else child

    @property
    def CycleTimeSec(self) -> Property:  return self._resolve('CycleTimeSec')
    @property
    def DefectRate(self)   -> Property:  return self._resolve('DefectRate')
    @property
    def RatedPowerKw(self) -> Property:  return self._resolve('RatedPowerKw')
    @property
    def DepPrev(self)      -> Property:  return self._resolve('DepPrev')
    @property
    def DepType(self)      -> Property:  return self._resolve('DepType')
    @property
    def InputBOM(self)     -> 'InputBOM':
        """InputBOM 없는 노드도 있으므로 None 허용 (시뮬은 `if not node.InputBOM` 검사)."""
        return self._resolve('InputBOM') if 'InputBOM' in self.value else None


@dataclass(kw_only=True)
class InputBOM(SubmodelElementList):
    """공정 input BOM. SML of ReferenceElement 를 dict-like `{item_code: Quantity}` 로 노출.
    item_code = ref 의 첫 키 (CD URL) 의 idShort 부분. Quantity = ref 의 Qualifier['Quantity']."""
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
class BOMCategory(SubmodelElementCollection):
    """BOMCategory 컨테이너 — `value: Dict[Category_idShort, BOMCategoryEntry]`."""


@dataclass(kw_only=True)
class BOMCategoryEntry(SubmodelElementCollection):
    """단일 BOM 카테고리. 자식 Property 값을 직접 노출 (Property wrapper 제거).
        MinStock   → int
        MaxStock   → int
        OrderRatio → float
    """
    @property
    def MinStock(self)   -> int:   return self.value['MinStock'].value
    @property
    def MaxStock(self)   -> int:   return self.value['MaxStock'].value
    @property
    def OrderRatio(self) -> float: return self.value['OrderRatio'].value


# ---- 도메인 ReferenceElement 들 (target 타입 명확화로 disambiguation) ----

@dataclass(kw_only=True)
class ProcessNodePropertyRef(ReferenceElement):
    """PSM Node.SIM_MODEL_*.<proc>.{CycleTimeSec/DefectRate/RatedPowerKw}.
    value: SMEPath ([SM URL, ProcessGroup_idShort, ProcessNode_idShort, Property_idShort]).
    target: MODEL_N.MP 안의 실제 Property."""
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
    """PSM Action.{IndependentSequence/DependentSequence/DependentJoin/AssignedProcessGroups}.*.
    value: List[semanticId] (ProcessNode CD URL 들).
    target: ProcessNode 들의 list (각 CD URL semanticId 매칭, ProcessNode 타입 필터)."""
    value: List[semanticId]
    @property
    def target(self) -> List[ProcessNode]:
        return [_find_typed_by_semantic(url, ProcessNode) for url in self.value]


@dataclass(kw_only=True)
class AssignedProcessGroupsRef(ReferenceElement):
    """WWM 의 WorkstationInformation.*.AssignedProcessGroups.*.
    value: List[semanticId] — 각 URL 은 ProcessNode CD URL.
    target: 매칭되는 ProcessNode 의 list. 매칭 안 되는 URL (의도된 누락 케이스 OQC/RMA 등) 은 skip."""
    value: List[semanticId]
    @property
    def target(self) -> List[ProcessNode]:
        return [node for url in self.value
                if (node := _find_typed_by_semantic(url, ProcessNode)) is not None]


@dataclass(kw_only=True)
class MPSubmodelListRef(ReferenceElement):
    """PSM Warehouse.InputBOM.
    value: List[semanticId] (MP Submodel URL 들).
    target: ManufacturingProcess Submodel 들의 list."""
    value: List[semanticId]
    @property
    def target(self) -> List[ManufacturingProcess]:
        return [_find_submodel_by_id(url) for url in self.value]


@dataclass(kw_only=True)
class BOMCategoryRef(ReferenceElement):
    """PSM Warehouse.{MinStock/MaxStock/OrderRatio}.
    value: List[semanticId] (BOMCategory CD URL, 단일).
    target: BOMCategory SMC."""
    value: List[semanticId]
    @property
    def target(self) -> BOMCategory:
        return _find_typed_by_semantic(self.value[0], BOMCategory)


@dataclass(kw_only=True)
class WWMPropertyRef(ReferenceElement):
    """PSM DefaultParameters.{WorkStartTime/WorkEndTime/BreakDurationMin}.
    value: SMEPath ([WWM submodel id URL, Property CD URL]).
    target: WWM 안의 Property (semanticId 가 두 번째 키와 매칭)."""
    value: SMEPath

    @classmethod
    def _parse_value(cls, raw_reference): return SMEPath._parse(raw_reference)

    @property
    def target(self) -> Property:
        wwm_submodel = _find_submodel_by_id(self.value[0])
        return _walk_for_match(wwm_submodel, self.value[1])


# 위치 패턴 → 도메인 클래스 매핑. 더 구체적 (wildcard 적은) 패턴이 먼저.
_DOMAIN_BY_POSITION = [
    # SME 구조 (data source AAS 들)
    (('ManufacturingProcess',),                                       ManufacturingProcess),
    (('ManufacturingProcess', 'ProcessType'),                         SubmodelElementCollection),   # 예외: 그룹 아님
    (('ManufacturingProcess', '*'),                                   ProcessGroup),
    (('ManufacturingProcess', '*', '*'),                              ProcessNode),
    (('ManufacturingProcess', '*', '*', 'InputBOM'),                  InputBOM),
    (('HierarchicalStructures', 'BOMCategory'),                       BOMCategory),
    (('HierarchicalStructures', 'BOMCategory', '*'),                  BOMCategoryEntry),

    # PSM 안의 도메인 ReferenceElement 들 (각자 target 타입 고정)
    (('SimulationModels', 'SimulationModel', 'Node', '*', '*', 'CycleTimeSec'),      ProcessNodePropertyRef),
    (('SimulationModels', 'SimulationModel', 'Node', '*', '*', 'DefectRate'),        ProcessNodePropertyRef),
    (('SimulationModels', 'SimulationModel', 'Node', '*', '*', 'RatedPowerKw'),      ProcessNodePropertyRef),
    (('SimulationModels', 'SimulationModel', 'Action', 'IndependentSequence', '*'),  ProcessNodeListRef),
    (('SimulationModels', 'SimulationModel', 'Action', 'DependentSequence', '*'),    ProcessNodeListRef),
    (('SimulationModels', 'SimulationModel', 'Action', 'DependentJoin', '*'),        ProcessNodeListRef),
    (('SimulationModels', 'SimulationModel', 'Action', 'AssignedProcessGroups', '*'),ProcessNodeListRef),
    (('WorkstationWorkerMatchingData', 'GeneralWorkstationData', 'WorkstationInformation', '*', 'AssignedProcessGroups', '*'), AssignedProcessGroupsRef),
    (('SimulationModels', 'SimulationModel', 'Warehouse', 'InputBOM'),               MPSubmodelListRef),
    (('SimulationModels', 'SimulationModel', 'Warehouse', 'MinStock'),               BOMCategoryRef),
    (('SimulationModels', 'SimulationModel', 'Warehouse', 'MaxStock'),               BOMCategoryRef),
    (('SimulationModels', 'SimulationModel', 'Warehouse', 'OrderRatio'),             BOMCategoryRef),
    (('SimulationModels', 'SimulationModel', 'DefaultParameters', 'WorkStartTime'),  WWMPropertyRef),
    (('SimulationModels', 'SimulationModel', 'DefaultParameters', 'WorkEndTime'),    WWMPropertyRef),
    (('SimulationModels', 'SimulationModel', 'DefaultParameters', 'BreakDurationMin'),WWMPropertyRef),
]


# ---- 도메인 ref 용 타입 필터 lookup 헬퍼들 ----

def _find_submodel_by_id(url: str):
    """Submodel.id 가 url 과 일치하는 Submodel 인스턴스 반환. 없으면 None."""
    for entry in _aas_registry.values():
        aas_list = entry if isinstance(entry, list) else [entry]
        for aas in aas_list:
            for submodel in aas.submodels.values():
                if submodel.id == url:
                    return submodel
    return None


def _find_submodel_by_semantic(url: str):
    """Submodel.semanticId 가 url 과 일치하는 Submodel 반환."""
    for entry in _aas_registry.values():
        aas_list = entry if isinstance(entry, list) else [entry]
        for aas in aas_list:
            for submodel in aas.submodels.values():
                if submodel.semanticId == url:
                    return submodel
    return None


def _find_typed_by_semantic(url: str, target_type: type):
    """semanticId == url 이고 isinstance(target_type) 인 SME 반환.
    같은 semanticId 의 여러 SME 중 target_type 만 골라내 disambiguation."""
    for entry in _aas_registry.values():
        aas_list = entry if isinstance(entry, list) else [entry]
        for aas in aas_list:
            for submodel in aas.submodels.values():
                found = _walk_for_typed(submodel, url, target_type)
                if found is not None:
                    return found
    return None


def _walk_for_typed(node, target_url: str, target_type: type):
    """node subtree 에서 semanticId==target_url 이고 isinstance(target_type) 인 첫 SME."""
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
    """CD URL 의 idShort 부분 추출 (예외적 유틸 — InputBOM 등 idShort 키가 필요한 경우에만).
    일반적인 ref 매칭은 semanticId 직접 비교 사용."""
    if '/ids/cd/' in identifier:
        return identifier.split('/ids/cd/')[1].split('/')[0]
    return identifier    # IRDI 등은 그대로 (확장 시 처리)
# endregion


# region
# ====================================================================
# AAS 컨테이너 + 외부 노출 인스턴스
# 시뮬 코드는 모듈 레벨 인스턴스 `ProvisionofSimulationModelsAAS` 만 다룸.
# ====================================================================
@dataclass(kw_only=True)
class AssetAdministrationShell:
    """AAS 컨테이너 클래스. 범용 타입."""
    # region [구조]
    idShort: str = ''
    submodels: Dict[str, Submodel] = field(default_factory=dict)
    # endregion

    # region [로직]
    def __getattr__(self, name: str) -> Submodel:
        """submodel idShort 로 attribute 접근. `aas.SimulationModels` 등.
        누락 시 KeyError 자연 발생 (hasattr/getattr default 호환 X — 호출부에서 처리)."""
        return self.__dict__.get('submodels')[name]

    @property
    def workers(self) -> Dict[str, Dict[str, Any]]:
        """WWM 의 WorkstationInformation 으로부터 `{WorkstationId: {worker_count, ProcessCode}}` 구성.
        AssignedProcessGroups 의 각 ref → ProcessNode 들 → idShort 평탄화.
        AAS 인스턴스 무관하게 동일 결과 (WWM 단일 출처).
        """
        wwm = _aas_registry['WorkstationWorkerMatchingDataAAS']
        if not wwm.submodels:
            return {}
        workstation_info = (wwm.submodels['WorkstationWorkerMatchingData']
                            .value['GeneralWorkstationData']
                            .value['WorkstationInformation'])
        return {
            ws.idShort: {
                'worker_count': len(ws.WorkstationConfigurationRecords),
                'ProcessCode': [node.idShort
                                for ref in ws.AssignedProcessGroups
                                for node in ref.target]
            }
            for ws in workstation_info.values()
        }

    @property
    def WarehouseManagedBOM(self) -> Dict[str, List[str]]:
        """모든 ProductAAS 의 HierarchicalStructures entities 를 Qualifier['Category'] 로 그룹핑.
        `{Category: [item_code, ...]}`. 모델 간 동일 item_code 는 중복 제거."""
        result: Dict[str, List[str]] = {}
        for aas in ProductAAS:
            hs = aas.submodels.get('HierarchicalStructures')
            if hs is None:
                continue
            for entity in hs._walk_entities():
                category = entity.Qualifier.get('Category')
                if not category:
                    continue
                bucket = result.setdefault(category, [])
                if entity.idShort not in bucket:
                    bucket.append(entity.idShort)
        return result
    # endregion


# AAS 인스턴스 (모듈 레벨). 외부 노출은 `ProvisionofSimulationModelsAAS` 뿐.
ProvisionofSimulationModelsAAS = AssetAdministrationShell()
WorkstationWorkerMatchingDataAAS = AssetAdministrationShell()
ProductAAS: List[AssetAdministrationShell] = []                  # MODEL_N 들 (load 호출 시 채워짐)


# 모든 로드된 AAS 인스턴스 보관 (내부). cross-AAS deref 시 lookup 용.
_aas_registry: Dict[str, AssetAdministrationShell | List[AssetAdministrationShell]] = {
    'ProductAAS': ProductAAS,
    'WorkstationWorkerMatchingDataAAS': WorkstationWorkerMatchingDataAAS,
    'ProvisionofSimulationModelsAAS': ProvisionofSimulationModelsAAS,
}


def load(json_path: str) -> None:
    """JSON 파일 하나 로드. 여러 번 호출해 여러 AAS 를 합쳐 사용.

    AAS idShort 로 라우팅:
      - 'ProvisionofSimulationModelsAAS' → 모듈 레벨 PSM 인스턴스 채움
      - 'WorkstationWorkerMatchingDataAAS' → 모듈 레벨 WWM 인스턴스 채움
      - 그 외 (MODEL_N 등) → 새 AssetAdministrationShell 만들어 ProductAAS 리스트에 append

    ReferenceElement 들은 lazy — target 접근 시점에 _aas_registry 통해 cross-AAS deref (TBD).
    """
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
# endregion


# region
# ====================================================================
# 내부 — JSON dict → SME 인스턴스 빌더 (재귀, 위치 기반 도메인 매칭)
# ====================================================================
def _build_sme(raw_sme: dict, position: tuple) -> SubmodelElement:
    """raw JSON dict → SubmodelElement 인스턴스 (재귀).
    position: 이 SME 의 트리상 위치 (submodel_idShort, ..., self_idShort).
              도메인 클래스 매칭 (_DOMAIN_BY_POSITION) 에 사용."""

    # 공통 필드
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
    # 모르는 modelType — base
    return SubmodelElement(**base_fields)


def _match_domain(position: tuple):
    """_DOMAIN_BY_POSITION 에서 position 과 일치하는 첫 패턴의 도메인 클래스 반환.
    `*` 는 wildcard. 더 구체적인 패턴이 먼저 와야 함."""
    for pattern, cls in _DOMAIN_BY_POSITION:
        if len(pattern) != len(position):
            continue
        if all(p == '*' or p == s for s, p in zip(position, pattern)):
            return cls
    return None


def _cast_value(raw_value, valueType: str | None):
    """raw value 를 AAS valueType (xs:int, xs:double, xs:time 등) 에 맞춰 캐스트.
    valueType 없거나 알려지지 않은 타입이면 raw 그대로 반환."""
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
        # xs:time "HH:MM" / "HH:MM:SS" → 자정 기준 초 (시뮬에서 사용하는 표현).
        parts = raw_value.split(':')
        hours = int(parts[0])
        minutes = int(parts[1]) if len(parts) > 1 else 0
        seconds = int(parts[2]) if len(parts) > 2 else 0
        return hours * 3600 + minutes * 60 + seconds
    return raw_value
# endregion
