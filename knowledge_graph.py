# AAS 기반 지식그래프(KG): path_extractor가 읽은 AAS에서 노드와 노드 간 관계(Edge)를 만듦
# - 노드·관계 종류는 simulation_v2.1 knowledge_graph.py 정의를 따름. 강화학습용 계산 속성(작업시간 특징 등)은 넣지 않음
# - simulation_generator가 공정의 투입 품목·설비·작업자, 선후 공정, 탄소 경계 공정을 이 관계에서 가져옴
from dataclasses import dataclass, field

import path_extractor


# ================================================ 노드 클래스와 속성: Process, Resource(Machine, Worker), Warehouse, MCF(Electricity) ================================================
@dataclass(eq=False)
class Node:
    kg_node_path: str
    element: object = field(repr=False)  # 노드가 된 AAS 요소(코드 요소가 든 목록 항목)


@dataclass(eq=False)
class Process(Node):
    RequiresMachine: bool = None
    RequiresWorker: bool = None


class Resource(Node):
    pass


@dataclass(eq=False)
class Machine(Resource):
    MachineGroupCode: str = None
    RequiresOperator: bool = None
    CapacityPerCycle: int = None
    MaxCapacity: int = None


@dataclass(eq=False)
class Worker(Resource):
    WorkerGroupCode: str = None


class Warehouse(Node):
    pass


class MCF(Node):
    pass


# MCF 공통요소 노드: 요소마다 노드. 지금 AAS에 대응 줄이 있는 공통요소가 전력뿐이라 Electricity만 둠
class Electricity(MCF):
    pass


MCF_NODE_CLASS_BY_COMMON_ELEMENT = {'Electricity': Electricity}


# ================================================ 노드 간 관계(Edge) 클래스: Require, Sequence, Join, ContributeTo ================================================
@dataclass(eq=False)
class Edge:
    source: Node
    target: Node


@dataclass(eq=False)
class Require(Edge):
    InputItemQuantity: float = None


class Sequence(Edge):
    pass


class Join(Edge):
    pass


class ContributeTo(Edge):
    pass


# ================================================ KG 노드 경로: 코드 요소가 든 목록부터 Submodel까지 idShort(중간 목록은 순번) + 코드 ================================================
def kg_node_path(code_element):
    parts = [str(code_element.value)]
    current = code_element.parent.parent
    while not isinstance(current, path_extractor.Submodel):
        parent = current.parent
        parts.append(str(current.index_in_parent) if isinstance(parent, path_extractor.SubmodelElementList) else current.idShort)
        current = parent
    parts.append(current.idShort)
    return '/'.join(reversed(parts))


def code_from_kg_node_path(path):
    return path.rsplit('/', 1)[-1]


# ================================================ KG 생성 ================================================
class KnowledgeGraph:
    def __init__(self, extracted):
        self.extracted = extracted
        self.simulation = extracted.submodels_with_role('Simulation')[0]
        self.resource = extracted.submodels_with_role('Resource')[0]
        self.process = extracted.submodels_with_role('Process')[0]
        self.warehouse = extracted.submodels_with_role('Warehouse')[0]
        self.nodes_by_path = {}
        self.edges = []
        self.edge_keys = set()
        self.issues = []
        self.generate_nodes()
        self.generate_edges()

    def add_node(self, node):
        self.nodes_by_path[node.kg_node_path] = node
        return node

    def add_edge(self, edge_class, source, target, **values):
        key = (edge_class, source.kg_node_path, target.kg_node_path, tuple(sorted(values.items())))
        if key not in self.edge_keys:
            self.edge_keys.add(key)
            self.edges.append(edge_class(source, target, **values))

    # ---------------------------------------------------------------- 노드
    def generate_nodes(self):
        for category in self.process.ProcessCategories:
            self.add_node(Process(kg_node_path(category.ProcessCode), category, RequiresMachine=bool(category.RequiresMachine.value),
                                  RequiresWorker=bool(category.RequiresWorker.value)))
        machine = self.resource.ResourceCategories.Machine
        group_by_unit_code = {reference.jump.value: group for group in machine.MachineGroup for reference in group.MachinePool.MachineUnitList}
        for unit in machine.MachineUnit:
            group = group_by_unit_code.get(unit.MachineUnitCode.value)
            self.add_node(Machine(kg_node_path(unit.MachineUnitCode), unit, MachineGroupCode=group.MachineGroupCode.value if group else None,
                                  RequiresOperator=group.RequiresOperator.value if group else None,
                                  CapacityPerCycle=unit.CapacityPerCycle.value, MaxCapacity=unit.MaxCapacity.value))
        for group in self.resource.ResourceCategories.Worker.WorkerGroup:
            for reference in group.WorkerPool.WorkerUnitList:
                self.add_node(Worker(kg_node_path(reference.jump), reference.jump.parent, WorkerGroupCode=group.WorkerGroupCode.value))
        for section in self.warehouse.Sections:
            for stored_item in section.StoredItems:
                for sub_category in stored_item.SubCategories:
                    path = f'{kg_node_path_of_list_item(sub_category)}/{sub_category.ItemCodeRef.jump.idShort}'
                    self.add_node(Warehouse(path, sub_category))
        for mcf in self.extracted.submodels_with_role('MCF'):
            for element_list in [*mcf.AncillaryInputs, mcf.Residuals.Waste, *mcf.Residuals.Releases]:
                if not len(element_list):
                    continue
                node_class = MCF_NODE_CLASS_BY_COMMON_ELEMENT.get(element_list.idShort)
                if node_class is None:
                    self.issues.append({'kind': 'KG', 'message': f'{mcf.id} {element_list.idShort}: 공통요소 노드 클래스 없음'})
                    continue
                self.add_node(node_class(f'{mcf.id}/{element_list.id_short_path}', element_list))

    # ---------------------------------------------------------------- 관계
    def generate_edges(self):
        for recipe in self.simulation.SimConnector.Relations.Recipes:
            process = self.nodes_by_path[kg_node_path(recipe.ProcessCode.jump)]
            # Process —Require→ Warehouse: Recipes.InputItemCodeList(투입량은 InputItemQuantity)
            for input_item in recipe.InputItemCodeList:
                sub_category = input_item.InputItemCodeRef.jump.parent
                warehouse = self.nodes_by_path[f'{kg_node_path_of_list_item(sub_category)}/{sub_category.ItemCodeRef.jump.idShort}']
                self.add_edge(Require, process, warehouse, InputItemQuantity=input_item.InputItemQuantity.value)
            # Process —Require→ Machine·Worker: Recipes.ResourceUnitRef(설비 단위), 없으면 ResourceGroupRef 그룹의 단위들
            # Machine —Require→ Worker: 같은 공정의 설비와 작업자
            machines, workers = [], []
            if recipe.ResourceUnitRef.jump:
                machines.append(self.nodes_by_path[kg_node_path(recipe.ResourceUnitRef.jump)])
            group = recipe.ResourceGroupRef.jump.parent
            if not recipe.ResourceUnitRef.jump:
                machines += [self.nodes_by_path[kg_node_path(reference.jump)] for reference in group.MachinePool.MachineUnitList]
            workers += [self.nodes_by_path[kg_node_path(reference.jump)] for reference in group.WorkerPool.WorkerUnitList]
            for resource in machines + workers:
                self.add_edge(Require, process, resource)
            for machine in machines:
                for worker in workers:
                    self.add_edge(Require, machine, worker)
        # Process —ContributeTo→ MCF 공통요소: MCF ManufacturingProcess.Recipes.ProcessCode
        for mcf in self.extracted.submodels_with_role('MCF'):
            mcf_nodes = [node for node in self.nodes_by_path.values() if isinstance(node, MCF) and node.kg_node_path.startswith(f'{mcf.id}/')]
            for mcf_recipe in mcf.ManufacturingProcess.Recipes:
                process = self.nodes_by_path[kg_node_path(mcf_recipe.ProcessCode.jump)]
                for mcf_node in mcf_nodes:
                    self.add_edge(ContributeTo, process, mcf_node)
        # Process —Sequence·Join→ Process: ProcessFlows.EntryConditionList 진입점마다 선행 공정 조건(ProcessCompleted)
        #   1개면 Sequence, 2개 이상(모두 끝나야 진입)이면 Join. 도착 공정은 흐름의 ToProcessRef
        for flow in self.simulation.SimConnector.Relations.ProcessFlows:
            process = self.nodes_by_path[kg_node_path(flow.ToProcessRef.jump)]
            for entry_condition in flow.EntryConditionList:
                previous_processes = [self.nodes_by_path[kg_node_path(condition.ConditionListRef.jump)]
                                      for condition in entry_condition.ConditionList if condition.ConditionType.value == 'ProcessCompleted']
                edge_class = Sequence if len(previous_processes) == 1 else Join
                for previous_process in previous_processes:
                    self.add_edge(edge_class, previous_process, process)

    # ---------------------------------------------------------------- 조회
    def nodes_of_class(self, node_class):
        return [node for node in self.nodes_by_path.values() if isinstance(node, node_class)]

    def edges_from(self, source, edge_classes, target_class):
        return [edge for edge in self.edges
                if edge.source is source and isinstance(edge, edge_classes) and isinstance(edge.target, target_class)]

    def edges_to(self, target, edge_classes, source_class):
        return [edge for edge in self.edges
                if edge.target is target and isinstance(edge, edge_classes) and isinstance(edge.source, source_class)]

    # 인스턴스 json에 담는 모양: 노드(클래스·경로·속성), Edge(클래스·출발·도착·값)
    def to_dict(self):
        nodes = [{'node_class': type(node).__name__, 'kg_node_path': node.kg_node_path,
                  **{name: value for name, value in vars(node).items() if name not in ('kg_node_path', 'element')}}
                 for node in self.nodes_by_path.values()]
        edges = [{'edge_class': type(edge).__name__, 'source': edge.source.kg_node_path, 'target': edge.target.kg_node_path,
                  **{name: value for name, value in vars(edge).items() if name not in ('source', 'target')}}
                 for edge in self.edges]
        return {'nodes': nodes, 'edges': edges}


# 코드 요소가 아닌 목록 항목(Warehouse SubCategories)의 경로: 목록부터 Submodel까지
def kg_node_path_of_list_item(list_item):
    parts = []
    current = list_item.parent
    while not isinstance(current, path_extractor.Submodel):
        parent = current.parent
        parts.append(str(current.index_in_parent) if isinstance(parent, path_extractor.SubmodelElementList) else current.idShort)
        current = parent
    parts.append(current.idShort)
    return '/'.join(reversed(parts))
