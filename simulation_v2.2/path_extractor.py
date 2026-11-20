import glob
import json
import os
import re
from dataclasses import dataclass, field, fields
from typing import ClassVar


# ================================================ 템플릿 정의: Submodel 역할, 템플릿이 단위를 정한 요소(위치는 Submodel 역할 + idShortPath, 목록 순번은 []) ================================================
SUBMODEL_MAPPING = {
    "SEMANTIC_ID": {
        'https://admin-shell.io/idta/HierarchicalStructures/1/1/Submodel': 'HierarchicalStructures',
        'https://www.smart-factory.kr/ids/sm/Resource/1/0': 'Resource',
        'https://www.smart-factory.kr/ids/sm/Process/1/0': 'Process',
        'https://www.smart-factory.kr/ids/cd/Warehouse/1/0': 'Warehouse',
        'https://www.smart-factory.kr/ids/sm/MCF/MCF/1/0': 'MCF',
        '0173-1#01-AHX837#002': 'TechnicalData',
        'https://www.smart-factory.kr/ids/sm/OperationalData/1/0': 'OperationalData',
    },
    "ID": {
        'https://www.smart-factory.kr/ids/sm/Simulation/1/0': 'Simulation',
    }
}

# 대상(템플릿 위치, 목록 순번은 [], **는 idShort 하나 이상): (대상의 단위, 변환할 단위)
# 단위 자리는 단위 글자 또는 단위가 적힌 요소 위치(….value). 변환할 단위 None은 단위만 붙이고 값은 그대로. 위에서부터 처음 맞는 줄을 씀
# MCF Amount는 계수(RefEmissionFactor)를 곱할 수 있게 계수의 기준 단위(RefImpactUnitforCalculation)로 바꿈
SME_UNIT_MAPPING = {
    'SimulationConfiguration.Run.RunLength': ('SimulationConfiguration.BaseUnits.TimeUnit.value', 's'),
    'RuntimeStatus.Segments[].SamplingInterval': ('SimulationConfiguration.BaseUnits.TimeUnit.value', 's'),
    'RuntimeStatus.Segments[].StartTime': ('SimulationConfiguration.BaseUnits.TimeUnit.value', 's'),
    'RuntimeStatus.Segments[].EndTime': ('SimulationConfiguration.BaseUnits.TimeUnit.value', 's'),
    'SimConnector.Relations.Recipes[].CycleTime': ('SimulationConfiguration.BaseUnits.TimeUnit.value', 's'),
    'SimConnector.Relations.TransportFlows[].TransportTime': ('SimulationConfiguration.BaseUnits.TimeUnit.value', 's'),
    'SimConnector.Relations.TransportFlows[].Distance': ('SimulationConfiguration.BaseUnits.DistanceUnit.value', 'm'),

    'AncillaryInputs.**[].Amount': ('AncillaryInputs.**[].AmountUnit.value', 'AncillaryInputs.**[].RefImpactUnitforCalculation.value'),
    'Residuals.Waste[].Amount': ('Residuals.Waste[].AmountUnit.value', 'Residuals.Waste[].RefImpactUnitforCalculation.value'),
    'Residuals.Releases.**[].Amount': ('Residuals.Releases.**[].AmountUnit.value', 'Residuals.Releases.**[].RefImpactUnitforCalculation.value'),
}


# ================================================ 값·단위 변환: valueType별 변환, 단위 크기(가장 작은 단위 몇 개인지), 기준 단위(시간·거리는 Simulation BaseUnits, 없으면 아래 값) ================================================
VALUE_TYPE_BY_UNIT = {
    "INTEGER": ['xs:int', 'xs:integer', 'xs:long', 'xs:short', 'xs:byte',
                'xs:unsignedInt', 'xs:unsignedLong', 'xs:nonNegativeInteger'],
    "REAL_NUMBER": ['xs:float', 'xs:double', 'xs:decimal'],
    "BOOLEAN": ['xs:boolean'],
    "TIME": ['xs:time'],
    "DURATION": ['xs:duration'],
}

SECONDS_PER_DURATION_DATE_MARK = {'Y': 365 * 86400, 'M': 30 * 86400, 'W': 7 * 86400, 'D': 86400}
SECONDS_PER_DURATION_TIME_MARK = {'H': 3600, 'M': 60, 'S': 1}

UNIT_SIZE_BY_QUANTITY = {
    'time': {'s': 1, 'min': 60, 'h': 3600, 'd': 86400},
    'distance': {'mm': 1, 'cm': 10, 'm': 1000, 'km': 1000000},
    'power': {'W': 1, 'kW': 1000, 'kW-h': 1000, 'MW': 1000000},
    'energy': {'Wh': 1, 'kWh': 1000, 'MWh': 1000000},
}
UNITS_KEPT_WITHOUT_CONVERSION = ['%', '°C', 'A', 'V', 'Hz', 'kg', 'lot', 'kgCO2eq']
COMPOUND_UNIT_SEPARATOR = '/'
# SME_UNIT_MAPPING에 없는 요소(CD unit·시각·기간)를 바꿀 단위
BASE_UNIT_BY_QUANTITY = {
    'time': 's',
    'distance': 'm',
    'power': 'kW',
    'energy': 'kWh',
}


# 시각(09:00:00) → 0시부터 초
def time_of_day_text_to_seconds(time_text):
    time_parts = time_text[:len('00:00:00')].split(':')
    total_seconds = 0
    for time_part, seconds_per_part in zip(time_parts, [3600, 60, 1]):
        total_seconds += float(time_part) * seconds_per_part
    return total_seconds


# 기간(PT1H30M) → 초
def duration_text_to_seconds(duration_text):
    date_part, time_mark, time_part = duration_text.removeprefix('P').partition('T')
    date_seconds = sum_duration_part_seconds(date_part, SECONDS_PER_DURATION_DATE_MARK)
    time_seconds = sum_duration_part_seconds(time_part, SECONDS_PER_DURATION_TIME_MARK)
    return date_seconds + time_seconds


def sum_duration_part_seconds(duration_part, seconds_per_mark):
    total_seconds = 0
    number_text = ''
    for character in duration_part:
        if character in seconds_per_mark:
            total_seconds += float(number_text) * seconds_per_mark[character]
            number_text = ''
        else:
            number_text += character
    if number_text:
        raise ValueError(duration_part)
    return total_seconds


def boolean_text_to_value(boolean_text):
    lowered_text = str(boolean_text).strip().lower()
    if lowered_text not in ['true', '1', 'false', '0']:
        raise ValueError(boolean_text)
    return lowered_text in ['true', '1']


# 글자 값 → valueType에 맞춘 값과 그 값의 단위(시각·기간은 초)
def converted_value_by_value_type(value_text, valueType):
    if value_text is None or value_text == '':
        return {'value': None, 'unit': None}
    if valueType in VALUE_TYPE_BY_UNIT['INTEGER']:
        return {'value': int(value_text), 'unit': None}
    if valueType in VALUE_TYPE_BY_UNIT['REAL_NUMBER']:
        return {'value': float(value_text), 'unit': None}
    if valueType in VALUE_TYPE_BY_UNIT['BOOLEAN']:
        return {'value': boolean_text_to_value(value_text), 'unit': None}
    if valueType in VALUE_TYPE_BY_UNIT['TIME']:
        return {'value': time_of_day_text_to_seconds(value_text), 'unit': 's'}
    if valueType in VALUE_TYPE_BY_UNIT['DURATION']:
        return {'value': duration_text_to_seconds(value_text), 'unit': 's'}
    return {'value': value_text, 'unit': None}


def is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


# 템플릿 위치(SME_UNIT_MAPPING의 키, **는 idShort 하나 이상)와 맞는지
def matches_template_path(path_pattern, template_path):
    path_expression = re.escape(path_pattern).replace(re.escape('**'), '.+')
    return re.fullmatch(path_expression, template_path) is not None


def quantity_of_unit(unit):
    for quantity, unit_sizes in UNIT_SIZE_BY_QUANTITY.items():
        if unit in unit_sizes:
            return quantity
    return None


# 단위의 양(m/s → distance/time). 표에 없는 단위가 섞이면 None
def quantities_of_unit(unit):
    quantities = []
    for unit_part in unit.split(COMPOUND_UNIT_SEPARATOR):
        quantity = quantity_of_unit(unit_part)
        if quantity is None:
            return None
        quantities.append(quantity)
    return COMPOUND_UNIT_SEPARATOR.join(quantities)


# 단위 → BASE_UNIT_BY_QUANTITY의 단위(m/s처럼 나눈 단위는 분자·분모 각각). 표에 없으면 None
def base_unit_of(unit):
    quantities = quantities_of_unit(unit)
    if quantities is None:
        return None
    base_units = [BASE_UNIT_BY_QUANTITY[quantity] for quantity in quantities.split(COMPOUND_UNIT_SEPARATOR)]
    return COMPOUND_UNIT_SEPARATOR.join(base_units)


# 표에 있는 단위나 환산하지 않는 단위로만 이뤄졌는지(kgCO2eq/kWh 등)
def is_known_unit(unit):
    for unit_part in unit.split(COMPOUND_UNIT_SEPARATOR):
        is_kept_unit = unit_part in UNITS_KEPT_WITHOUT_CONVERSION
        if not is_kept_unit and quantity_of_unit(unit_part) is None:
            return False
    return True


def unit_size_in_smallest_unit(unit):
    unit_parts = unit.split(COMPOUND_UNIT_SEPARATOR)
    numerator_size = UNIT_SIZE_BY_QUANTITY[quantity_of_unit(unit_parts[0])][unit_parts[0]]
    denominator_size = 1
    for denominator_unit in unit_parts[1:]:
        denominator_unit_sizes = UNIT_SIZE_BY_QUANTITY[quantity_of_unit(denominator_unit)]
        denominator_size *= denominator_unit_sizes[denominator_unit]
    return {'numerator': numerator_size, 'denominator': denominator_size}


def value_in_base_unit(value, unit, base_unit):
    if unit == base_unit or not is_number(value):
        return value
    unit_size = unit_size_in_smallest_unit(unit)
    base_unit_size = unit_size_in_smallest_unit(base_unit)
    multiplier = unit_size['numerator'] * base_unit_size['denominator']
    divisor = base_unit_size['numerator'] * unit_size['denominator']
    return value * multiplier / divisor


# ================================================ AAS 자료형: Referable(공통 최소 속성) → Identifiable·하위 요소를 가진 자료형 → 모델 타입별 클래스. 필드 이름은 AAS JSON 그대로 ================================================
# 같은 객체도 서로 다른 요소로 다루고(eq=False), 출력은 Referable의 짧은 형식(repr=False)
aas_type = dataclass(eq=False, repr=False, kw_only=True)


@aas_type
class Reference:
    type: str = None
    keys: list = field(default_factory=list)
    jump: object = None

    @classmethod
    def from_json(cls, reference_json):
        if not reference_json:
            return None
        return cls(type=reference_json.get('type'), keys=reference_json.get('keys', []))

    def first_key_value(self):
        if not self.keys:
            return None
        return self.keys[0].get('value')

    def __repr__(self):
        key_values = [str(key.get('value')) for key in self.keys]
        return f"Reference({' / '.join(key_values)})"


# 없는 요소·따라갈 수 없는 참조 자리: 경로를 이어 써도 오류 없이 값은 None, 반복은 빈 목록, 참·거짓은 거짓
class MissingElement:
    value = None
    id = None
    idShort = None
    entityType = None
    children = ()
    children_by_idShort = {}

    def __init__(self, path):
        self.path = path

    def __getattr__(self, name):
        if name.startswith('_'):
            raise AttributeError(name)
        return MissingElement(f'{self.path}.{name}')

    def __getitem__(self, index):
        return MissingElement(f'{self.path}[{index}]')

    def __iter__(self):
        return iter(())

    def __len__(self):
        return 0

    def __bool__(self):
        return False

    def __repr__(self):
        return f'MissingElement({self.path})'


# 모든 AAS 객체 공통: idShort, semanticId, 상위 요소, 역참조. 있는 요소는 하위 요소가 없어도 참
@aas_type
class Referable:
    CONNECTED_REFERENCE_KEYS: ClassVar[list] = []
    idShort: str = None
    modelType: str = None
    semanticId: Reference = None
    parent: object = None
    source_file: str = None
    index_in_parent: int = None
    referenced_by: list = field(default_factory=list)

    # JSON에 같은 이름의 키가 있는 필드만 JSON 값으로 채움. Reference 필드는 Reference로
    @classmethod
    def from_json(cls, element_json, parent, source_file):
        json_values = {}
        for aas_field in fields(cls):
            if aas_field.name not in element_json:
                continue
            json_value = element_json[aas_field.name]
            if aas_field.type is Reference:
                json_value = Reference.from_json(json_value)
            json_values[aas_field.name] = json_value
        return cls(**json_values, parent=parent, source_file=source_file)

    def __repr__(self):
        return f'{self.modelType or type(self).__name__}({self.idShort})'

    def __bool__(self):
        return True

    @property
    def submodel(self):
        current = self
        while current is not None and not isinstance(current, Submodel):
            current = current.parent
        return current

    # AAS 표준 idShortPath(Recipes[0].CycleTime)
    @property
    def id_short_path(self):
        return self.path_from_submodel(True)

    # 템플릿에서의 위치(Recipes[].CycleTime)
    @property
    def template_path(self):
        return self.path_from_submodel(False)

    def path_from_submodel(self, shows_list_index):
        if self.parent is None or isinstance(self, Submodel):
            return ''
        parent_path = self.parent.path_from_submodel(shows_list_index)
        if isinstance(self.parent, SubmodelElementList):
            if shows_list_index:
                return f'{parent_path}[{self.index_in_parent}]'
            return f'{parent_path}[]'
        if parent_path:
            return f'{parent_path}.{self.idShort}'
        return self.idShort

    def semantic_id_value(self):
        if self.semanticId is None:
            return None
        return self.semanticId.first_key_value()


@aas_type
class Identifiable(Referable):
    id: str = None


# 하위 요소를 가진 자료형: idShort(obj.Child)·순번(obj[0])으로 내려가기. 없는 하위 요소는 MissingElement
@aas_type
class ElementContainer(Referable):
    CHILD_KEYS: ClassVar[list] = []
    children: list = field(default_factory=list)
    children_by_idShort: dict = field(default_factory=dict)

    def child_jsons(self, element_json):
        child_jsons = []
        for child_key in self.CHILD_KEYS:
            child_jsons += element_json.get(child_key) or []
        return child_jsons

    def add_child(self, child):
        child.index_in_parent = len(self.children)
        self.children.append(child)
        if child.idShort not in self.children_by_idShort:
            self.children_by_idShort[child.idShort] = child

    def __getattr__(self, name):
        children_by_idShort = self.__dict__.get('children_by_idShort', {})
        if name in children_by_idShort:
            return children_by_idShort[name]
        if name.startswith('_'):
            raise AttributeError(name)
        return MissingElement(f"{self.__dict__.get('idShort')}.{name}")

    def __getitem__(self, index):
        return self.children[index]

    def __iter__(self):
        return iter(self.children)

    def __len__(self):
        return len(self.children)


# JSON submodels(Submodel 참조 목록)는 submodel_references로 옮기고, submodels에는 연결된 Submodel을 담음
@aas_type
class AssetAdministrationShell(Identifiable, ElementContainer):
    assetInformation: dict = None
    submodels: list = field(default_factory=list)
    submodel_references: list = field(default_factory=list)

    def __post_init__(self):
        self.submodel_references = [Reference.from_json(reference_json)
                                    for reference_json in self.submodels or []]
        self.submodels = []


@aas_type
class Submodel(Identifiable, ElementContainer):
    CHILD_KEYS: ClassVar[list] = ['submodelElements']
    qualifiers: list = field(default_factory=list)
    role: str = None


@aas_type
class ConceptDescription(Identifiable):
    embeddedDataSpecifications: list = field(default_factory=list)
    unit: str = None

    def __post_init__(self):
        for data_specification in self.embeddedDataSpecifications or []:
            unit = data_specification.get('dataSpecificationContent', {}).get('unit')
            if unit and self.unit is None:
                self.unit = unit


@aas_type
class SubmodelElement(Referable):
    qualifiers: list = field(default_factory=list)


# value는 valueType·단위를 바꾼 값, value_text는 원래 글자. unit은 원래 단위, base_unit은 바꾼 단위
@aas_type
class Property(SubmodelElement):
    valueType: str = None
    value: object = None
    valueId: Reference = None
    value_text: str = None
    unit: str = None
    base_unit: str = None

    def __post_init__(self):
        self.value_text = self.value


@aas_type
class Range(SubmodelElement):
    valueType: str = None
    min: object = None
    max: object = None
    min_text: str = None
    max_text: str = None
    unit: str = None
    base_unit: str = None

    def __post_init__(self):
        self.min_text = self.min
        self.max_text = self.max


@aas_type
class MultiLanguageProperty(SubmodelElement):
    value: list = field(default_factory=list)
    valueId: Reference = None


@aas_type
class File(SubmodelElement):
    contentType: str = None
    value: str = None


@aas_type
class Blob(File):
    pass


# jump: 참조가 가리키는 AAS·Submodel·요소·CD. 비었거나 따라갈 수 없으면 MissingElement
@aas_type
class ReferenceElement(SubmodelElement):
    CONNECTED_REFERENCE_KEYS: ClassVar[list] = ['value']
    value: Reference = None

    @property
    def jump(self):
        if self.value is None or self.value.jump is None:
            return MissingElement(f'{self.idShort}.jump')
        return self.value.jump


@aas_type
class RelationshipElement(SubmodelElement):
    CONNECTED_REFERENCE_KEYS: ClassVar[list] = ['first', 'second']
    first: Reference = None
    second: Reference = None


@aas_type
class Entity(SubmodelElement, ElementContainer):
    CHILD_KEYS: ClassVar[list] = ['statements']
    entityType: str = None
    globalAssetId: str = None
    specificAssetIds: list = field(default_factory=list)


@aas_type
class SubmodelElementCollection(SubmodelElement, ElementContainer):
    CHILD_KEYS: ClassVar[list] = ['value']


@aas_type
class SubmodelElementList(SubmodelElement, ElementContainer):
    CHILD_KEYS: ClassVar[list] = ['value']
    typeValueListElement: str = None
    valueTypeListElement: str = None
    orderRelevant: bool = None


# 변수는 JSON에서 {'value': 요소}로 한 겹 싸여 있음
@aas_type
class Operation(SubmodelElement, ElementContainer):
    CHILD_KEYS: ClassVar[list] = ['inputVariables', 'outputVariables', 'inoutputVariables']

    def child_jsons(self, element_json):
        return [variable_json.get('value', {}) for variable_json in super().child_jsons(element_json)]


@aas_type
class Capability(SubmodelElement):
    pass


# modelType 이름과 같은 이름의 클래스. 없으면 SubmodelElement
def element_class_of_model_type(model_type):
    element_class = globals().get(model_type)
    if isinstance(element_class, type) and issubclass(element_class, SubmodelElement):
        return element_class
    return SubmodelElement


def iterate_all_elements(container):
    for child in container.children:
        yield child
        if isinstance(child, ElementContainer):
            yield from iterate_all_elements(child)


def child_at_id_short_path(container, id_short_path):
    for idShort in id_short_path.split('.'):
        if not isinstance(container, ElementContainer):
            return None
        container = container.children_by_idShort.get(idShort)
    return container


# ================================================ 경로 파싱: 파일 읽기 → 참조 연결·역참조 → Submodel 역할 → 기준 단위 → 값 변환(valueType·단위) → semanticId 색인 ================================================
AAS_JSON_TOP_LEVEL_KEYS = ['assetAdministrationShells', 'submodels', 'conceptDescriptions']
AAS_FILE_EXTENSIONS = ['.json', '.aasx', '.xml']
RATED_POWER_SEMANTIC_ID = '0173-1#02-AAC970#009'

@dataclass
class ExtractionIssue:
    kind: str
    message: str
    source_file: str = None
    id_short_path: str = None


@dataclass
class ExtractedAAS:
    source_files: list = field(default_factory=list)
    asset_administration_shells: list = field(default_factory=list)
    submodels: list = field(default_factory=list)
    submodels_by_role: dict = field(default_factory=dict)
    concept_descriptions: dict = field(default_factory=dict)
    identifiables_by_id: dict = field(default_factory=dict)
    elements_by_semantic_id: dict = field(default_factory=dict)
    base_units: dict = field(default_factory=dict)
    issues: list = field(default_factory=list)

    def submodels_with_role(self, role):
        return self.submodels_by_role.get(role, [])

    def elements_with_semantic_id(self, semantic_id):
        return self.elements_by_semantic_id.get(semantic_id, [])

    # AAS 하나(설비)의 Submodel 안에서 정격전력 요소
    def rated_power_elements_of_aas(self, asset_administration_shell):
        rated_power_elements = []
        for element in self.elements_with_semantic_id(RATED_POWER_SEMANTIC_ID):
            if element.submodel in asset_administration_shell.submodels:
                rated_power_elements.append(element)
        return rated_power_elements


class PathExtractor:
    def __init__(self):
        self.extracted = ExtractedAAS()
        self.all_elements = []

    def extract(self, file_paths):
        for file_path in file_paths:
            self.read_file(file_path)
        self.connect_references()
        self.assign_submodel_roles()
        self.extracted.base_units = dict(BASE_UNIT_BY_QUANTITY)
        self.convert_values()
        self.index_semantic_ids()
        return self.extracted

    def record_issue(self, kind, message, element=None, source_file=None):
        issue = ExtractionIssue(kind=kind, message=message, source_file=source_file)
        if element is not None:
            issue.source_file = element.source_file
            issue.id_short_path = element.id_short_path
        self.extracted.issues.append(issue)

    # 지금은 json만 읽고 aasx·xml은 자리만 둠
    def read_file(self, file_path):
        extension = os.path.splitext(file_path)[1].lower()
        if extension == '.json':
            self.read_json_file(file_path)
        if extension == '.aasx':
            self.record_issue('읽지 않음', 'aasx 읽기는 아직 없음', source_file=file_path)
        if extension == '.xml':
            self.record_issue('읽지 않음', 'xml 읽기는 아직 없음', source_file=file_path)

    # AAS 최상위 키가 없는 json(config.json 등)은 건너뜀
    def read_json_file(self, file_path):
        with open(file_path, encoding='utf-8') as json_file:
            environment_json = json.load(json_file)
        is_aas_json = isinstance(environment_json, dict)
        is_aas_json = is_aas_json and set(AAS_JSON_TOP_LEVEL_KEYS) & set(environment_json)
        if not is_aas_json:
            return
        self.extracted.source_files.append(file_path)
        for shell_json in environment_json.get('assetAdministrationShells', []):
            shell = self.build_identifiable(AssetAdministrationShell, shell_json, file_path)
            self.extracted.asset_administration_shells.append(shell)
        for submodel_json in environment_json.get('submodels', []):
            submodel = self.build_identifiable(Submodel, submodel_json, file_path)
            self.add_child_elements(submodel, submodel_json)
            self.extracted.submodels.append(submodel)
        for concept_description_json in environment_json.get('conceptDescriptions', []):
            concept_description = self.build_identifiable(
                ConceptDescription, concept_description_json, file_path)
            self.extracted.concept_descriptions.setdefault(
                concept_description.id, concept_description)

    # 같은 id가 또 나오면 처음 것을 남김(CD는 파일마다 겹쳐 확인 필요에 안 적음)
    def build_identifiable(self, identifiable_class, identifiable_json, file_path):
        identifiable = identifiable_class.from_json(identifiable_json, None, file_path)
        identifiables_by_id = self.extracted.identifiables_by_id
        if identifiable.id not in identifiables_by_id:
            identifiables_by_id[identifiable.id] = identifiable
        elif identifiable_class is not ConceptDescription:
            self.record_issue('중복 id', identifiable.id, source_file=file_path)
        return identifiable

    def add_child_elements(self, container, container_json):
        for child_json in container.child_jsons(container_json):
            model_type = child_json.get('modelType')
            child_class = element_class_of_model_type(model_type)
            child = child_class.from_json(child_json, container, container.source_file)
            container.add_child(child)
            self.all_elements.append(child)
            if isinstance(child, ElementContainer):
                self.add_child_elements(child, child_json)

    # AAS의 Submodel 참조와 요소의 참조를 따라가 jump·referenced_by 채움
    def connect_references(self):
        for shell in self.extracted.asset_administration_shells:
            for submodel_reference in shell.submodel_references:
                submodel = self.connect_reference(shell, submodel_reference, 'submodels')
                if submodel is None:
                    continue
                shell.submodels.append(submodel)
                shell.add_child(submodel)
                if submodel.parent is None:
                    submodel.parent = shell
        for element in self.all_elements:
            for reference_key in element.CONNECTED_REFERENCE_KEYS:
                reference = getattr(element, reference_key)
                if reference is not None:
                    self.connect_reference(element, reference, reference_key)

    # 첫 key의 id로 AAS·Submodel·CD를 찾고, 다음 key부터 SML이면 순번, 아니면 idShort
    def connect_reference(self, referring_element, reference, reference_name):
        target = self.extracted.identifiables_by_id.get(reference.first_key_value())
        for key in reference.keys[1:]:
            if not isinstance(target, ElementContainer):
                target = None
                break
            target = self.child_of_key(target, key.get('value'))
        reference.jump = target
        if target is None and reference.type == 'ModelReference':
            self.record_issue('참조', f'따라갈 수 없음: {reference}', element=referring_element)
        if target is not None:
            reverse_reference = {'referring_element': referring_element,
                                 'reference_name': reference_name}
            target.referenced_by.append(reverse_reference)
        return target

    def child_of_key(self, container, key_value):
        if not isinstance(container, SubmodelElementList):
            return container.children_by_idShort.get(key_value)
        if not str(key_value).isdigit() or int(key_value) >= len(container.children):
            return None
        return container.children[int(key_value)]

    # semanticId로, semanticId가 없으면 Submodel id로
    def assign_submodel_roles(self):
        for submodel in self.extracted.submodels:
            role = SUBMODEL_MAPPING['SEMANTIC_ID'].get(submodel.semantic_id_value())
            if role is None:
                role = SUBMODEL_MAPPING['ID'].get(submodel.id)
            submodel.role = role
            if role is not None:
                self.extracted.submodels_by_role.setdefault(role, []).append(submodel)

    def convert_values(self):
        for element in self.all_elements:
            if isinstance(element, Property):
                element.value = self.converted_value(element, element.value_text)
            if isinstance(element, Range):
                element.min = self.converted_value(element, element.min_text)
                element.max = self.converted_value(element, element.max_text, False)

    # valueType에 맞추고 변환할 단위로 바꿈. 못 바꾸는 값은 그대로 두고 확인 필요에 적음
    def converted_value(self, element, value_text, records_unit_issue=True):
        try:
            converted = converted_value_by_value_type(value_text, element.valueType)
        except ValueError:
            message = f'{element.valueType}로 바꿀 수 없어 글자 그대로 둠: {value_text}'
            self.record_issue('값 형식', message, element=element)
            return value_text
        unit, target_unit = self.units_of_element(element, converted['unit'])
        element.unit = unit
        if unit is None:
            return converted['value']
        if target_unit is None:
            if not is_known_unit(unit) and records_unit_issue:
                self.record_issue('단위', f'단위 표에 없는 단위: {unit}', element=element)
            return converted['value']
        unit_quantities = quantities_of_unit(unit)
        if unit_quantities is None or unit_quantities != quantities_of_unit(target_unit):
            if records_unit_issue:
                self.record_issue('단위', f'{unit}을 {target_unit}로 바꿀 수 없음', element=element)
            return converted['value']
        element.base_unit = target_unit
        return value_in_base_unit(converted['value'], unit, target_unit)

    # (대상의 단위, 변환할 단위). 찾는 순서: 시각·기간은 초 → SME_UNIT_MAPPING → CD unit
    def units_of_element(self, element, unit_from_value_type):
        if unit_from_value_type is not None:
            return unit_from_value_type, base_unit_of(unit_from_value_type)
        for path_pattern, (unit_source, target_unit) in SME_UNIT_MAPPING.items():
            if matches_template_path(path_pattern, element.template_path):
                unit = self.unit_from_mapping(element, unit_source)
                return unit, self.unit_from_mapping(element, target_unit)
        concept_description = self.extracted.concept_descriptions.get(element.semantic_id_value())
        if concept_description is None or concept_description.unit is None:
            return None, None
        return concept_description.unit, base_unit_of(concept_description.unit)

    # 단위 자리가 위치면 그 요소 속성 값(같은 묶음 안에서, 없으면 Submodel 맨 위부터 idShort로), 아니면 단위 글자 그대로
    def unit_from_mapping(self, element, unit_source):
        if unit_source is None or '.' not in unit_source:
            return unit_source
        unit_element_pattern, attribute_name = unit_source.rsplit('.', 1)
        for sibling in element.parent.children:
            if matches_template_path(unit_element_pattern, sibling.template_path):
                return getattr(sibling, attribute_name)
        unit_element = child_at_id_short_path(element.submodel, unit_element_pattern)
        if unit_element is None:
            self.record_issue('단위', f'단위 요소가 없음: {unit_element_pattern}', element=element)
            return None
        return getattr(unit_element, attribute_name)

    def index_semantic_ids(self):
        for element in self.all_elements:
            semantic_id = element.semantic_id_value()
            if semantic_id is not None:
                self.extracted.elements_by_semantic_id.setdefault(semantic_id, []).append(element)


# ================================================ 진입점: AAS 폴더(하위 폴더까지)·파일을 읽어 추출 결과를 돌려줌 ================================================
def collect_aas_file_paths(aas_paths):
    if isinstance(aas_paths, (str, os.PathLike)):
        aas_paths = [aas_paths]
    file_paths = []
    for aas_path in aas_paths:
        if not os.path.isdir(aas_path):
            file_paths.append(str(aas_path))
            continue
        for extension in AAS_FILE_EXTENSIONS:
            pattern = os.path.join(aas_path, '**', f'*{extension}')
            file_paths += sorted(glob.glob(pattern, recursive=True))
    return file_paths


def extract(aas_paths):
    return PathExtractor().extract(collect_aas_file_paths(aas_paths))
