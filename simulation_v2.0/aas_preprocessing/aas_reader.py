from __future__ import annotations
import glob
import json
import os
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


# ================================================ 단위 환산표: 양(量)마다 기준 단위와, 기준 단위 1에 해당하는 각 단위의 수 ================================================
UNIT_CONVERSION_TABLE = {
    'power': {
        'base_unit': 'kW',
        'amount_in_one_base_unit': {'kW': 1.0, 'W': 1000.0},
    },
}


# ================================================ 시나리오 폴더에서 읽는 파일: AAS JSON 파일, AAS로 읽지 않는 설정 파일 ================================================
SCENARIO_CONFIG_FILE = 'config.json'
AAS_FILE_NAME_PATTERN = '*.json'
ALL_SUBFOLDERS_PATTERN = '**'


# ================================================ KG 노드 경로의 구분 문자 ================================================
KG_NODE_PATH_SEPARATOR = '.'


# ================================================ 시간 단위별 초 ================================================
SECONDS_PER_DAY = 86400
SECONDS_PER_HOUR = 3600
SECONDS_PER_MINUTE = 60
SECONDS_PER_SECOND = 1


# ================================================ valueType별 값 변환: 참·거짓, 시각(초), 기간(초) ================================================
TRUE_VALUES = [True, 'true', 'True', 'TRUE', 1, '1']
TIME_PART_SEPARATOR = ':'
SECONDS_PER_TIME_PART = [SECONDS_PER_HOUR, SECONDS_PER_MINUTE, SECONDS_PER_SECOND]
DURATION_NUMBER_PATTERN = r'\d+(?:\.\d+)?'
DURATION_PATTERN = re.compile(
    rf'P(?:(?P<day>{DURATION_NUMBER_PATTERN})D)?'
    rf'(?:T(?:(?P<hour>{DURATION_NUMBER_PATTERN})H)?'
    rf'(?:(?P<minute>{DURATION_NUMBER_PATTERN})M)?'
    rf'(?:(?P<second>{DURATION_NUMBER_PATTERN})S)?)?$')
SECONDS_PER_DURATION_UNIT = {
    'day': SECONDS_PER_DAY,
    'hour': SECONDS_PER_HOUR,
    'minute': SECONDS_PER_MINUTE,
    'second': SECONDS_PER_SECOND,
}


def is_true_value(value):
    return value in TRUE_VALUES


def time_text_to_seconds(time_text):
    time_parts = time_text.split(TIME_PART_SEPARATOR)
    total_seconds = 0
    for time_part, seconds_per_part in zip(time_parts, SECONDS_PER_TIME_PART):
        total_seconds += int(time_part) * seconds_per_part
    return total_seconds


def duration_text_to_seconds(duration_text):
    duration_match = DURATION_PATTERN.match(duration_text)
    amount_by_unit = duration_match.groupdict()
    total_seconds = 0
    for unit, seconds_per_unit in SECONDS_PER_DURATION_UNIT.items():
        amount = amount_by_unit[unit]
        if amount:
            total_seconds += float(amount) * seconds_per_unit
    return total_seconds


VALUE_TYPE_PREFIX_SEPARATOR = ':'
VALUE_TYPE_CONVERTERS = {
    'int': int,
    'integer': int,
    'long': int,
    'short': int,
    'byte': int,
    'float': float,
    'double': float,
    'decimal': float,
    'boolean': is_true_value,
    'time': time_text_to_seconds,
    'duration': duration_text_to_seconds,
}


# ================================================ AAS 자료형 정의 ================================================
class semanticId(str):
    pass


class SMEPath(list):
    pass


class Qualifier(dict):
    pass


class EntityType(str, Enum):
    SelfManagedEntity = 'SelfManagedEntity'
    CoManagedEntity = 'CoManagedEntity'


@dataclass(kw_only=True, eq=False)
class Referable:
    idShort: str = ''
    semanticId: semanticId = semanticId('')
    Qualifier: Qualifier = field(default_factory=Qualifier)
    aas_list: AASList = None

    def __getattr__(self, idShort):
        if isinstance(self, dict) and idShort in self:
            return self[idShort]
        raise AttributeError(idShort)


@dataclass(kw_only=True, eq=False)
class Submodel(Referable, dict):
    id: str = ''

    @property
    def value(self):
        return self


@dataclass(kw_only=True, eq=False)
class SubmodelElement(Referable):
    parent_element: Any = field(default=None, repr=False)


@dataclass(kw_only=True, eq=False)
class Property(SubmodelElement):
    value: Any = None


@dataclass(kw_only=True, eq=False)
class MultiLanguageProperty(SubmodelElement):
    value: list = field(default_factory=list)


@dataclass(kw_only=True, eq=False)
class File(SubmodelElement):
    value: str = ''
    contentType: str = ''


@dataclass(kw_only=True, eq=False)
class Range(SubmodelElement):
    min: Any = None
    max: Any = None


@dataclass(kw_only=True, eq=False)
class SubmodelElementCollection(SubmodelElement, dict):

    @property
    def value(self):
        return self


@dataclass(kw_only=True, eq=False)
class SubmodelElementList(SubmodelElement, list):

    @property
    def value(self):
        return self


@dataclass(kw_only=True, eq=False)
class Entity(SubmodelElement, dict):
    entityType: EntityType = None

    @property
    def statements(self):
        return self


@dataclass(kw_only=True, eq=False)
class Operation(SubmodelElement):
    inputVariables: dict = field(default_factory=dict)
    outputVariables: dict = field(default_factory=dict)
    inoutputVariables: dict = field(default_factory=dict)


@dataclass(kw_only=True, eq=False)
class RelationshipElement(SubmodelElement):
    first: SMEPath = field(default_factory=SMEPath)
    second: SMEPath = field(default_factory=SMEPath)


@dataclass(kw_only=True, eq=False)
class ReferenceElement(SubmodelElement):
    value: SMEPath = field(default_factory=SMEPath)

    @property
    def target(self):
        return find_referenced_element(self)


@dataclass(kw_only=True, eq=False)
class AssetAdministrationShell(Referable, dict):
    id: str = ''

    @property
    def submodels(self):
        return self


@dataclass(kw_only=True, eq=False)
class ConceptDescription(Referable):
    id: str = ''
    unit: str = ''


@dataclass
class AASList:
    shells: dict = field(default_factory=dict)
    submodels: dict = field(default_factory=dict)
    concept_descriptions: dict = field(default_factory=dict)
    aas_reading_problem_messages: list = field(default_factory=list)


# ================================================ modelType 이름별 AAS 자료형 클래스 ================================================
AAS_CLASS_BY_MODEL_TYPE = {
    'Property': Property,
    'MultiLanguageProperty': MultiLanguageProperty,
    'File': File,
    'Operation': Operation,
    'Range': Range,
    'ReferenceElement': ReferenceElement,
    'RelationshipElement': RelationshipElement,
    'Entity': Entity,
    'SubmodelElementCollection': SubmodelElementCollection,
    'SubmodelElementList': SubmodelElementList,
    'Submodel': Submodel,
}
AAS_CLASS_FOR_OTHER_MODEL_TYPE = Property


# ================================================ AAS 파일 불러오기: 시나리오 폴더의 AAS JSON 파일을 AAS 자료형으로 바꿔 AASList에 담기 ================================================
class AASReader:

    def __init__(self, aas_directory):
        self.aas_list = AASList()
        aas_file_path_pattern = os.path.join(
            aas_directory, ALL_SUBFOLDERS_PATTERN, AAS_FILE_NAME_PATTERN)
        json_file_paths = glob.glob(aas_file_path_pattern, recursive=True)
        for json_file_path in sorted(json_file_paths):
            if os.path.basename(json_file_path) != SCENARIO_CONFIG_FILE:
                self.load_aas_file(json_file_path)
        self.register_submodels_by_id()

    def load_aas_file(self, aas_file_path):
        with open(aas_file_path, encoding='utf-8') as aas_file:
            aas_file_json = json.load(aas_file)
        for concept_description_json in aas_file_json.get('conceptDescriptions', []):
            self.register_concept_description(concept_description_json)
        first_shell_json = aas_file_json['assetAdministrationShells'][0]
        shell = AssetAdministrationShell(
            idShort=first_shell_json.get('idShort', ''),
            id=first_shell_json.get('id', ''),
            aas_list=self.aas_list)
        self.aas_list.shells[shell.id] = shell
        for submodel_json in aas_file_json.get('submodels', []):
            shell[submodel_json['idShort']] = self.build_aas_element(submodel_json)

    def register_concept_description(self, concept_description_json):
        concept_descriptions = self.aas_list.concept_descriptions
        concept_description_id = concept_description_json['id']
        if concept_description_id not in concept_descriptions:
            concept_descriptions[concept_description_id] = ConceptDescription(
                idShort=concept_description_json.get('idShort', ''),
                id=concept_description_id,
                aas_list=self.aas_list)
        concept_description = concept_descriptions[concept_description_id]
        registered_unit = concept_description.unit
        unit = read_concept_description_unit(concept_description_json)
        if unit and registered_unit and registered_unit != unit:
            self.aas_list.aas_reading_problem_messages.append(
                f'{concept_description.id} unit 충돌 {registered_unit} vs {unit}')
        if not registered_unit:
            concept_description.unit = unit

    def register_submodels_by_id(self):
        for shell in self.aas_list.shells.values():
            for submodel in shell.values():
                if submodel.id not in self.aas_list.submodels:
                    self.aas_list.submodels[submodel.id] = submodel

    # ================================================ AAS JSON 요소를 modelType에 맞는 AAS 자료형으로 변환 ================================================
    def build_aas_element(self, element_json):
        model_type = element_json['modelType']
        aas_class = AAS_CLASS_BY_MODEL_TYPE.get(model_type, AAS_CLASS_FOR_OTHER_MODEL_TYPE)
        element = aas_class(
            idShort=element_json.get('idShort', ''),
            semanticId=read_semantic_id(element_json),
            Qualifier=read_qualifiers(element_json),
            aas_list=self.aas_list)
        valueType = element_json.get('valueType')
        if isinstance(element, Submodel):
            element.id = element_json.get('id', '')
            self.add_child_elements_by_idShort(element, element_json)
        elif isinstance(element, SubmodelElementCollection):
            self.add_child_elements_by_idShort(element, element_json)
        elif isinstance(element, Entity):
            element.entityType = EntityType(element_json['entityType'])
            self.add_entity_statements(element, element_json)
        elif isinstance(element, SubmodelElementList):
            self.add_list_items(element, element_json)
        elif isinstance(element, ReferenceElement):
            element.value = reference_key_values(element_json.get('value'))
        elif isinstance(element, RelationshipElement):
            element.first = reference_key_values(element_json.get('first'))
            element.second = reference_key_values(element_json.get('second'))
        elif isinstance(element, Operation):
            self.add_operation_variables(
                element.inputVariables, element_json.get('inputVariables'))
            self.add_operation_variables(
                element.outputVariables, element_json.get('outputVariables'))
            self.add_operation_variables(
                element.inoutputVariables, element_json.get('inoutputVariables'))
        elif isinstance(element, Range):
            element.min = convert_value_by_value_type(element_json.get('min'), valueType)
            element.max = convert_value_by_value_type(element_json.get('max'), valueType)
        elif isinstance(element, File):
            element.value = element_json.get('value', '')
            element.contentType = element_json.get('contentType', '')
        elif isinstance(element, MultiLanguageProperty):
            if element_json.get('value'):
                element.value = element_json['value']
        else:
            element.value = convert_value_by_value_type(element_json.get('value'), valueType)
        return element

    def add_child_elements_by_idShort(self, parent_element, parent_element_json):
        child_element_jsons = parent_element_json.get('submodelElements')
        if not child_element_jsons:
            child_element_jsons = parent_element_json.get('value')
        if not child_element_jsons:
            return
        for child_element_json in child_element_jsons:
            child_element = self.build_aas_element(child_element_json)
            set_parent_element(child_element, parent_element)
            parent_element[child_element_json.get('idShort', '')] = child_element

    def add_entity_statements(self, entity, entity_json):
        statement_jsons = entity_json.get('statements')
        if not statement_jsons:
            return
        for statement_json in statement_jsons:
            statement = self.build_aas_element(statement_json)
            set_parent_element(statement, entity)
            entity[statement_json['idShort']] = statement

    def add_list_items(self, submodel_element_list, submodel_element_list_json):
        list_item_jsons = submodel_element_list_json.get('value')
        if not list_item_jsons:
            return
        for list_item_json in list_item_jsons:
            list_item = self.build_aas_element(list_item_json)
            set_parent_element(list_item, submodel_element_list)
            submodel_element_list.append(list_item)

    def add_operation_variables(self, operation_variables, operation_variable_jsons):
        if not operation_variable_jsons:
            return
        for operation_variable_json in operation_variable_jsons:
            variable_element_json = operation_variable_json['value']
            variable_element = self.build_aas_element(variable_element_json)
            operation_variables[variable_element_json['idShort']] = variable_element


# ================================================ AAS JSON에서 값 읽기: ConceptDescription 단위, semanticId, qualifiers, 참조의 key 값, valueType에 맞춘 값 ================================================
def read_concept_description_unit(concept_description_json):
    specifications = concept_description_json.get('embeddedDataSpecifications', [])
    for specification in specifications:
        specification_content = specification.get('dataSpecificationContent')
        if specification_content and specification_content.get('unit'):
            return specification_content['unit']
    return ''


def read_semantic_id(element_json):
    semantic_id_json = element_json.get('semanticId')
    if not semantic_id_json:
        return semanticId('')
    keys = semantic_id_json.get('keys', [])
    if not keys:
        return semanticId('')
    first_key = keys[0]
    return semanticId(first_key['value'])


def read_qualifiers(element_json):
    qualifiers = Qualifier()
    for qualifier_json in element_json.get('qualifiers', []):
        qualifier_type = qualifier_json['type']
        qualifier_value = qualifier_json.get('value')
        qualifier_value_type = qualifier_json.get('valueType')
        qualifiers[qualifier_type] = convert_value_by_value_type(
            qualifier_value, qualifier_value_type)
    return qualifiers


def reference_key_values(reference_json):
    key_values = SMEPath()
    if not reference_json:
        return key_values
    keys = reference_json.get('keys')
    if not keys:
        return key_values
    for key in keys:
        key_values.append(key['value'])
    return key_values


def convert_value_by_value_type(value, valueType):
    if not valueType:
        return value
    value_type_parts = valueType.split(VALUE_TYPE_PREFIX_SEPARATOR)
    value_type_name_after_prefix = value_type_parts[-1]
    converter = VALUE_TYPE_CONVERTERS.get(value_type_name_after_prefix)
    is_empty_value = value is None or value == ''
    if converter is None or is_empty_value:
        return value
    return converter(value)


def set_parent_element(child_element, parent_element):
    child_element.parent_element = parent_element


# ================================================ 값을 단위와 함께 읽기와 단위 변환: 단위는 요소 semanticId의 ConceptDescription unit ================================================
def read_value_with_unit(property_element):
    return {
        'value': property_element.value,
        'unit': read_unit_from_concept_description(property_element),
    }


def read_unit_from_concept_description(element):
    concept_descriptions = element.aas_list.concept_descriptions
    concept_description = concept_descriptions[element.semanticId]
    return concept_description.unit


def convert_unit(value_with_unit, target_unit):
    source_unit = value_with_unit['unit']
    for unit_conversion in UNIT_CONVERSION_TABLE.values():
        amount_in_one_base_unit = unit_conversion['amount_in_one_base_unit']
        if source_unit not in amount_in_one_base_unit:
            continue
        if target_unit not in amount_in_one_base_unit:
            continue
        source_value = float(value_with_unit['value'])
        value_in_base_unit = source_value / amount_in_one_base_unit[source_unit]
        if target_unit == unit_conversion['base_unit']:
            return value_in_base_unit
        return value_in_base_unit * amount_in_one_base_unit[target_unit]
    raise ValueError(f'단위 환산표에 없는 단위: {source_unit} → {target_unit}')


# ================================================ 참조 따라가기: ReferenceElement가 가리키는 요소와 코드 값 찾기, 하위 요소 모두 돌기 ================================================
def find_referenced_element(reference_element):
    aas_list = reference_element.aas_list
    key_values = reference_element.value
    if not key_values:
        return None
    submodel_or_shell_id = key_values[0]
    idShort_path = key_values[1:]
    if submodel_or_shell_id in aas_list.submodels:
        current_element = aas_list.submodels[submodel_or_shell_id]
    elif submodel_or_shell_id in aas_list.shells:
        current_element = aas_list.shells[submodel_or_shell_id]
    else:
        aas_list.aas_reading_problem_messages.append(
            f'{reference_element.idShort}: 뿌리 부재 — {submodel_or_shell_id}')
        return None
    for key_value in idShort_path:
        if isinstance(current_element, list):
            is_index_in_list = key_value.isdigit() and int(key_value) < len(current_element)
            if not is_index_in_list:
                aas_list.aas_reading_problem_messages.append(
                    f'{reference_element.idShort}: 인덱스 초과 — '
                    f'{key_value} / {len(current_element)}')
                return None
            current_element = current_element[int(key_value)]
        elif isinstance(current_element, dict) and key_value in current_element:
            current_element = current_element[key_value]
        else:
            aas_list.aas_reading_problem_messages.append(
                f'{reference_element.idShort}: 자식 부재 — {key_value}')
            return None
    return current_element


def referenced_code_value(reference_element):
    concept_descriptions = reference_element.aas_list.concept_descriptions
    key_values = reference_element.value
    has_single_key = len(key_values) == 1
    if has_single_key:
        only_key_value = key_values[0]
        if only_key_value in concept_descriptions:
            return concept_descriptions[only_key_value].idShort
    referenced_element = reference_element.target
    if isinstance(referenced_element, ReferenceElement):
        return referenced_code_value(referenced_element)
    return referenced_element.value


def iterate_all_sub_elements(parent_element):
    if isinstance(parent_element, Operation):
        child_elements = list(parent_element.inputVariables.values())
        child_elements += list(parent_element.outputVariables.values())
        child_elements += list(parent_element.inoutputVariables.values())
    elif isinstance(parent_element, dict):
        child_elements = list(parent_element.values())
    elif isinstance(parent_element, list):
        child_elements = list(parent_element)
    else:
        child_elements = []
    for child_element in child_elements:
        if isinstance(child_element, SubmodelElement):
            yield child_element
            yield from iterate_all_sub_elements(child_element)


# ================================================ KG 노드 경로 만들기: Submodel idShort부터 목록까지의 idShort 경로 끝에 목록 항목의 코드 값 붙이기 ================================================
def kg_node_path_from_sme(code_element, code_value=None):
    if code_value is None:
        code_value = code_element.value
    list_item = code_element.parent_element
    submodel_element_list = list_item.parent_element
    if not isinstance(submodel_element_list, SubmodelElementList):
        raise ValueError(f'{code_element.idShort}: 목록 항목의 이름 요소가 아님')
    path_parts_from_end = [str(code_value)]
    current_element = submodel_element_list
    while not isinstance(current_element, Submodel):
        parent_element = current_element.parent_element
        if isinstance(parent_element, SubmodelElementList):
            index_in_list = index_in_submodel_element_list(parent_element, current_element)
            path_part = str(index_in_list)
        else:
            path_part = current_element.idShort
        path_parts_from_end.append(path_part)
        current_element = parent_element
    path_parts_from_end.append(current_element.idShort)
    path_parts = reversed(path_parts_from_end)
    return KG_NODE_PATH_SEPARATOR.join(path_parts)


def index_in_submodel_element_list(submodel_element_list, list_item):
    for index, listed_item in enumerate(submodel_element_list):
        if listed_item is list_item:
            return index
    return None
