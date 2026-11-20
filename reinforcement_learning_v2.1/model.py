from os import environ

# ================================================ 계산 스레드 수 고정: 실행마다 계산 순서가 같도록 스레드 1개만 사용 ================================================
CALCULATION_THREAD_COUNT = 1
THREAD_COUNT_ENVIRONMENT_VARIABLES = ['OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'OPENBLAS_NUM_THREADS']
for environment_variable in THREAD_COUNT_ENVIRONMENT_VARIABLES:
    environ[environment_variable] = str(CALCULATION_THREAD_COUNT)

import torch

from reinforcement_learning import state

torch.set_num_threads(CALCULATION_THREAD_COUNT)
if torch.get_num_interop_threads() != CALCULATION_THREAD_COUNT:
    torch.set_num_interop_threads(CALCULATION_THREAD_COUNT)


# ================================================ 신경망 크기: 새 모델을 만들 때 쓰는 값(저장된 모델은 모델 파일에 적힌 크기로 만듦) ================================================
NETWORK_SIZES = {
    'node_embedding_dimension': 32,
    'hidden_layer_size': 64,
}


# ================================================ 행동 분포의 로그 표준편차: 새 모델의 처음 값과 허용 범위 ================================================
ACTION_DISTRIBUTION_SETTINGS = {
    'initial_log_standard_deviation': -1.0,
    'log_standard_deviation_min': -3.0,
    'log_standard_deviation_max': 1.0,
}


# ================================================ 신경망 출력 개수: 작업 우선순위 가중치, 공정 착수 행동, 상태 가치 ================================================
PRIORITY_WEIGHT_COUNT = 4
PROCESS_START_ACTION_COUNT = 1
STATE_VALUE_COUNT = 1


# ================================================ 저장된 모델 파일: 기본 경로, 지금 상태와 같아야 하는 입력 차원 이름 ================================================
DEFAULT_MODEL_FILE = 'model/integrated_model.pt'
INPUT_DIMENSION_NAMES = [
    'node_feature_dimension',
    'global_information_dimension',
    'relation_count',
]


# ================================================ 텐서 축 번호: 노드가 나열된 축, 맨 끝 축 ================================================
NODE_AXIS = -2
LAST_AXIS = -1


# ================================================ 노드 연결(Edge) 자료를 신경망 입력 텐서로 변환 ================================================
def edge_connection_tensors(edge_connections):
    relation_group_ranges = []
    for group_range in edge_connections['relation_group_ranges']:
        relation_group_ranges.append(dict(group_range))
    return {
        'source_node_indices': torch.as_tensor(
            edge_connections['source_node_indices'], dtype=torch.long),
        'edge_group_indices': torch.as_tensor(
            edge_connections['edge_group_indices'], dtype=torch.long),
        'edge_mean_weights': torch.as_tensor(
            edge_connections['edge_mean_weights'], dtype=torch.float32),
        'group_target_node_indices': torch.as_tensor(
            edge_connections['group_target_node_indices'], dtype=torch.long),
        'relation_group_ranges': relation_group_ranges,
    }


# ================================================ GNN 층: 관계(Edge)별 가중치로 이웃 노드 값의 평균을 모아 노드 값 갱신 ================================================
class RelationalGraphConvolution(torch.nn.Module):

    def __init__(self, input_size, output_size, relation_count):
        super().__init__()
        empty_relation_weights = torch.empty(relation_count, input_size, output_size)
        self.relation_weights = torch.nn.Parameter(empty_relation_weights)
        self.own_node_layer = torch.nn.Linear(input_size, output_size)
        torch.nn.init.xavier_uniform_(self.relation_weights)

    def forward(self, node_values, edge_connections):
        source_node_values = node_values.index_select(
            NODE_AXIS, edge_connections['source_node_indices'])
        edge_mean_weights = edge_connections['edge_mean_weights'].unsqueeze(LAST_AXIS)
        edge_values = source_node_values * edge_mean_weights
        group_target_node_indices = edge_connections['group_target_node_indices']
        empty_group_values = node_values.new_zeros(
            *node_values.shape[:NODE_AXIS], group_target_node_indices.numel(),
            node_values.size(LAST_AXIS))
        group_values = empty_group_values.index_add(
            NODE_AXIS, edge_connections['edge_group_indices'], edge_values)
        updated_node_values = self.own_node_layer(node_values)
        for group_range in edge_connections['relation_group_ranges']:
            group_start = group_range['group_start']
            group_end = group_range['group_end']
            group_values_of_relation = group_values[..., group_start:group_end, :]
            relation_weight = self.relation_weights[group_range['relation_index']]
            target_node_indices = group_target_node_indices[group_start:group_end]
            updated_node_values = updated_node_values.index_add(
                NODE_AXIS, target_node_indices, group_values_of_relation @ relation_weight)
        return updated_node_values


# ================================================ GNN 층 묶음과 Linear 층 묶음 생성 ================================================
def create_gnn_layers(node_feature_dimension, hidden_layer_size, node_embedding_dimension,
                      relation_count):
    return torch.nn.ModuleList([
        RelationalGraphConvolution(node_feature_dimension, hidden_layer_size, relation_count),
        RelationalGraphConvolution(hidden_layer_size, hidden_layer_size, relation_count),
        RelationalGraphConvolution(hidden_layer_size, node_embedding_dimension, relation_count),
    ])


def create_fully_connected_layers(input_size, output_size, hidden_layer_size):
    return torch.nn.Sequential(
        torch.nn.Linear(input_size, hidden_layer_size),
        torch.nn.ReLU(),
        torch.nn.Linear(hidden_layer_size, hidden_layer_size),
        torch.nn.ReLU(),
        torch.nn.Linear(hidden_layer_size, hidden_layer_size),
        torch.nn.ReLU(),
        torch.nn.Linear(hidden_layer_size, output_size),
    )


def set_output_layer_weights_to_zero(fully_connected_layers):
    output_layer = fully_connected_layers[-1]
    torch.nn.init.zeros_(output_layer.weight)
    torch.nn.init.zeros_(output_layer.bias)


# ================================================ 상태 벡터 계산: GNN으로 노드 임베딩을 만들고 공장 상태와 전역 정보를 이어 붙임 ================================================
def node_embeddings(gnn_layers, node_features, edge_connections):
    node_values = node_features
    for gnn_layer in gnn_layers[:-1]:
        node_values = torch.relu(gnn_layer(node_values, edge_connections))
    output_layer = gnn_layers[-1]
    return output_layer(node_values, edge_connections)


def state_vector(gnn_layers, node_features, edge_connections, global_information):
    embeddings = node_embeddings(gnn_layers, node_features, edge_connections)
    factory_state = state.factory_state(embeddings)
    return torch.cat([factory_state, global_information], dim=LAST_AXIS)


# ================================================ 강화학습 모델: 작업 우선순위 신경망과 공정 착수 신경망 ================================================
class ReinforcementLearningModel(torch.nn.Module):

    def __init__(self, node_feature_dimension, global_information_dimension, relation_count,
                 initial_weight_seed, node_embedding_dimension, hidden_layer_size,
                 initial_log_standard_deviation):
        super().__init__()
        self.model_settings = {
            'node_feature_dimension': node_feature_dimension,
            'global_information_dimension': global_information_dimension,
            'relation_count': relation_count,
            'initial_weight_seed': initial_weight_seed,
            'node_embedding_dimension': node_embedding_dimension,
            'hidden_layer_size': hidden_layer_size,
            'initial_log_standard_deviation': initial_log_standard_deviation,
        }
        factory_state_dimension = state.factory_state_dimension(node_embedding_dimension)
        state_dimension = factory_state_dimension + global_information_dimension
        priority_input_dimension = state_dimension + PROCESS_START_ACTION_COUNT
        initial_log_standard_deviation = float(initial_log_standard_deviation)
        with torch.random.fork_rng(devices=[]):
            torch.manual_seed(initial_weight_seed)
            self.priority_gnn_layers = create_gnn_layers(
                node_feature_dimension, hidden_layer_size, node_embedding_dimension,
                relation_count)
            self.priority_mean_layers = create_fully_connected_layers(
                priority_input_dimension, PRIORITY_WEIGHT_COUNT, hidden_layer_size)
            set_output_layer_weights_to_zero(self.priority_mean_layers)
            self.priority_value_layers = create_fully_connected_layers(
                priority_input_dimension, STATE_VALUE_COUNT, hidden_layer_size)
            self.process_start_gnn_layers = create_gnn_layers(
                node_feature_dimension, hidden_layer_size, node_embedding_dimension,
                relation_count)
            self.process_start_mean_layers = create_fully_connected_layers(
                state_dimension, PROCESS_START_ACTION_COUNT, hidden_layer_size)
            set_output_layer_weights_to_zero(self.process_start_mean_layers)
            self.process_start_value_layers = create_fully_connected_layers(
                state_dimension, STATE_VALUE_COUNT, hidden_layer_size)
            self.priority_log_standard_deviation = torch.nn.Parameter(
                torch.full((PRIORITY_WEIGHT_COUNT,), initial_log_standard_deviation))
            self.process_start_log_standard_deviation = torch.nn.Parameter(
                torch.full((PROCESS_START_ACTION_COUNT,), initial_log_standard_deviation))

    def priority_forward(self, node_features, edge_connections, global_information,
                         process_start_action):
        factory_state_and_global_information = state_vector(
            self.priority_gnn_layers, node_features, edge_connections, global_information)
        network_input = torch.cat(
            [factory_state_and_global_information, process_start_action.reshape(1)])
        mean = self.priority_mean_layers(network_input)
        log_standard_deviation = self.priority_log_standard_deviation.clamp(
            ACTION_DISTRIBUTION_SETTINGS['log_standard_deviation_min'],
            ACTION_DISTRIBUTION_SETTINGS['log_standard_deviation_max'])
        value = self.priority_value_layers(network_input).squeeze(LAST_AXIS)
        return {
            'mean': mean,
            'log_standard_deviation': log_standard_deviation,
            'value': value,
        }

    def process_start_forward(self, node_features, edge_connections, global_information):
        network_input = state_vector(
            self.process_start_gnn_layers, node_features, edge_connections, global_information)
        mean = self.process_start_mean_layers(network_input).squeeze(LAST_AXIS)
        log_standard_deviation = self.process_start_log_standard_deviation.clamp(
            ACTION_DISTRIBUTION_SETTINGS['log_standard_deviation_min'],
            ACTION_DISTRIBUTION_SETTINGS['log_standard_deviation_max']).squeeze(LAST_AXIS)
        value = self.process_start_value_layers(network_input.detach()).squeeze(LAST_AXIS)
        return {
            'mean': mean,
            'log_standard_deviation': log_standard_deviation,
            'value': value,
        }

    def priority_parameters(self):
        parameters = [self.priority_log_standard_deviation]
        parameters.extend(self.priority_gnn_layers.parameters())
        parameters.extend(self.priority_mean_layers.parameters())
        parameters.extend(self.priority_value_layers.parameters())
        return parameters

    def process_start_action_parameters(self):
        parameters = [self.process_start_log_standard_deviation]
        parameters.extend(self.process_start_gnn_layers.parameters())
        parameters.extend(self.process_start_mean_layers.parameters())
        return parameters

    def process_start_parameters(self):
        parameters = self.process_start_action_parameters()
        parameters.extend(self.process_start_value_layers.parameters())
        return parameters

    def parameters_except_log_standard_deviation(self):
        parameters = list(self.priority_gnn_layers.parameters())
        parameters.extend(self.priority_mean_layers.parameters())
        parameters.extend(self.priority_value_layers.parameters())
        parameters.extend(self.process_start_gnn_layers.parameters())
        parameters.extend(self.process_start_mean_layers.parameters())
        parameters.extend(self.process_start_value_layers.parameters())
        return parameters


# ================================================ 저장된 모델의 입력 차원 확인: 지금 상태의 차원과 다르면 오류 ================================================
def check_input_dimensions(model_settings, input_dimensions):
    mismatches = []
    for dimension_name in INPUT_DIMENSION_NAMES:
        saved_dimension = model_settings.get(dimension_name)
        current_dimension = input_dimensions[dimension_name]
        if saved_dimension != current_dimension:
            mismatches.append(
                f'{dimension_name}: 저장된 모델 {saved_dimension}, 지금 상태 {current_dimension}')
    if mismatches:
        raise ValueError('저장된 모델과 지금 상태의 입력 차원이 다름 (' + '; '.join(mismatches) + ')')


# ================================================ 새 모델 생성과 저장된 모델 불러오기 ================================================
def create_model(input_dimensions, initial_weight_seed):
    reinforcement_learning_model = ReinforcementLearningModel(
        node_feature_dimension=input_dimensions['node_feature_dimension'],
        global_information_dimension=input_dimensions['global_information_dimension'],
        relation_count=input_dimensions['relation_count'],
        initial_weight_seed=initial_weight_seed,
        node_embedding_dimension=NETWORK_SIZES['node_embedding_dimension'],
        hidden_layer_size=NETWORK_SIZES['hidden_layer_size'],
        initial_log_standard_deviation=ACTION_DISTRIBUTION_SETTINGS[
            'initial_log_standard_deviation'])
    reinforcement_learning_model.eval()
    return reinforcement_learning_model


def load_model(model_file, input_dimensions):
    saved_content = torch.load(model_file, weights_only=False, map_location='cpu')
    check_input_dimensions(saved_content['model_settings'], input_dimensions)
    reinforcement_learning_model = ReinforcementLearningModel(**saved_content['model_settings'])
    reinforcement_learning_model.load_state_dict(saved_content['model_weights'], strict=True)
    reinforcement_learning_model.eval()
    return {
        'reinforcement_learning_model': reinforcement_learning_model,
        'saved_content': saved_content,
    }


def saved_start_timing_emission_record(saved_content, scenario):
    if 'start_timing_emission_records' in saved_content:
        return saved_content['start_timing_emission_records'][scenario]
    return saved_content['start_timing_emission_record']
