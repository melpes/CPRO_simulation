from dataclasses import dataclass

from aas_preprocessing import aas_reader
from aas_preprocessing.path_extractor import AAS_REFERENCE_ELEMENT_PATHS, PathExtractor


# ================================================ 노드 클래스와 속성: Process, Resource(Machine, Worker), Warehouse, MCF(Electricity) ================================================
@dataclass(frozen=True)
class Node:
    kg_node_path: str


@dataclass(frozen=True)
class Process(Node):
    product_code: str
    is_defect_event_target_process: bool
    is_defect_event_handling_process: bool
    requires_no_worker_and_no_machine: bool
    CycleTime: float
    simultaneous_processing_quantity: int
    defect_probability_per_output_item: float
    process_rated_power_kw: float
    BranchProbability: float
    RequiresWorker: bool
    worker_work_time_sec: float


class Resource(Node):
    pass


@dataclass(frozen=True)
class Machine(Resource):
    MachineGroupCode: str
    rated_power_kw: float
    MaxCapacity: int
    CapacityPerCycle: int
    RequiresOperator: bool


@dataclass(frozen=True)
class Worker(Resource):
    WorkerGroupCode: str


class Warehouse(Node):
    pass


class MCF(Node):
    pass


class Electricity(MCF):
    pass


# ================================================ 노드 간 관계(Edge) 클래스: Require, Sequence, Join, ContributeTo ================================================
@dataclass(frozen=True)
class Edge:
    source: Node
    target: Node


@dataclass(frozen=True)
class Require(Edge):
    InputItemQuantity: float = None


class Sequence(Edge):
    pass


class Join(Edge):
    pass


class ContributeTo(Edge):
    pass


# ================================================ 노드 클래스 사이의 관계 7종: 출발 노드 클래스, Edge 클래스, 도착 노드 클래스, 근거가 되는 AAS 참조 요소 경로 ================================================
AAS_REFERENCE_ELEMENT_PATH_NOT_DEFINED = None
RELATIONS = [
    {
        'source_node_class': Process,
        'edge_class': Require,
        'target_node_class': Warehouse,
        'aas_reference_element_path': AAS_REFERENCE_ELEMENT_PATHS['process_to_input_item'],
    },
    {
        'source_node_class': Process,
        'edge_class': Require,
        'target_node_class': Resource,
        'aas_reference_element_path': AAS_REFERENCE_ELEMENT_PATHS['process_to_machine_or_worker'],
    },
    {
        'source_node_class': Process,
        'edge_class': ContributeTo,
        'target_node_class': MCF,
        'aas_reference_element_path': AAS_REFERENCE_ELEMENT_PATHS['process_to_electricity'],
    },
    {
        'source_node_class': Resource,
        'edge_class': Require,
        'target_node_class': Resource,
        'aas_reference_element_path': AAS_REFERENCE_ELEMENT_PATHS[
            'machine_to_worker_of_same_process'],
    },
    {
        'source_node_class': Process,
        'edge_class': Sequence,
        'target_node_class': Process,
        'aas_reference_element_path': AAS_REFERENCE_ELEMENT_PATHS['previous_process_to_process'],
    },
    {
        'source_node_class': Process,
        'edge_class': Join,
        'target_node_class': Process,
        'aas_reference_element_path': AAS_REFERENCE_ELEMENT_PATHS[
            'previous_process_to_process_with_entry_condition'],
    },
    {
        'source_node_class': MCF,
        'edge_class': ContributeTo,
        'target_node_class': MCF,
        'aas_reference_element_path': AAS_REFERENCE_ELEMENT_PATH_NOT_DEFINED,
    },
]


# ================================================ GNN이 구분하는 관계 수: 관계 7종마다 정방향과 역방향 ================================================
DIRECTIONS_PER_RELATION = 2
NUM_RELATIONS = DIRECTIONS_PER_RELATION * len(RELATIONS)


# ================================================ 노드 클래스별 AAS 추출 메서드: 적힌 순서가 KG의 노드 클래스 순서 ================================================
NODE_EXTRACTION_METHODS = {
    Process: PathExtractor.extract_process_nodes,
    Machine: PathExtractor.extract_machine_nodes,
    Worker: PathExtractor.extract_worker_nodes,
    Warehouse: PathExtractor.extract_warehouse_nodes,
    MCF: PathExtractor.extract_mcf_nodes,
    Electricity: PathExtractor.extract_electricity_nodes,
}


# ================================================ KG 노드 경로의 마지막 마디 읽기: 공정·설비·작업자·품목 코드 ================================================
def code_from_kg_node_path(kg_node_path):
    path_parts = kg_node_path.split(aas_reader.KG_NODE_PATH_SEPARATOR)
    code = path_parts[-1]
    return code


# ================================================ AAS 요소 사이 참조에서 두 노드를 잇는 관계 찾기: 참조가 있으면 Edge에 넣을 값, 없으면 None ================================================
def find_edge_values_in_aas_element_references(
        aas_element_references, source_kg_node_path, target_kg_node_path,
        aas_reference_element_path):
    if source_kg_node_path not in aas_element_references:
        return None
    references_from_source = aas_element_references[source_kg_node_path]
    if target_kg_node_path not in references_from_source:
        return None
    references_to_target = references_from_source[target_kg_node_path]
    if aas_reference_element_path not in references_to_target:
        return None
    edge_values = references_to_target[aas_reference_element_path]
    return edge_values


# ================================================ KG 생성: PathExtractor가 AAS에서 추출한 값으로 노드를 만들고 관계 7종을 차례로 돌며 Edge 만들기 ================================================
class KnowledgeGraph:

    def __init__(self, path_extractor):
        self.nodes_by_class = {}
        self.edges = []
        self.smt_line_steps = path_extractor.extract_smt_line_steps()
        self.generate_nodes(path_extractor)
        self.generate_edges(path_extractor.extract_aas_element_references())

    def generate_nodes(self, path_extractor):
        for node_class, extract_nodes in NODE_EXTRACTION_METHODS.items():
            attributes_by_kg_node_path = extract_nodes(path_extractor)
            nodes = []
            for kg_node_path, attributes in attributes_by_kg_node_path.items():
                node = node_class(kg_node_path, **attributes)
                nodes.append(node)
            self.nodes_by_class[node_class] = nodes

    def generate_edges(self, aas_element_references):
        for relation in RELATIONS:
            edge_class = relation['edge_class']
            source_nodes = self.nodes_of_class(relation['source_node_class'])
            target_nodes = self.nodes_of_class(relation['target_node_class'])
            for source_node in source_nodes:
                for target_node in target_nodes:
                    if source_node == target_node:
                        continue
                    edge_values = find_edge_values_in_aas_element_references(
                        aas_element_references, source_node.kg_node_path,
                        target_node.kg_node_path, relation['aas_reference_element_path'])
                    if edge_values is None:
                        continue
                    edge = edge_class(source_node, target_node, **edge_values)
                    self.edges.append(edge)

    # ================================================ 노드 조회: 노드 클래스와 그 하위 클래스의 노드 목록 ================================================
    def nodes_of_class(self, node_class):
        nodes = []
        for listed_node_class, listed_nodes in self.nodes_by_class.items():
            if issubclass(listed_node_class, node_class):
                nodes.extend(listed_nodes)
        return nodes
