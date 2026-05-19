# -*- coding: utf-8 -*-
"""simulation_ver0.py 의 ML 구조 시각화.

1) hierarchy.png      : PPOAgent → GNNEncoder/Actor/Critic → ModuleList → 레이어 클래스 n계층 트리
2) gnn/actor/critic   : 각 서브넷 forward 를 torchview 로 추적한 텐서 흐름 그래프
"""
import os
import sys

_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _DIR)

import torch
from torch_geometric.data import Data
from torchview import draw_graph
import graphviz

import simulation_ver0 as sv  # __main__ 가드 있어 import 안전

OUT = os.path.join(_DIR, 'ml_viz')
os.makedirs(OUT, exist_ok=True)

# 더미 차원 (구조만 보면 되므로 작은 값)
NodeFeatureDim  = 6
HiddenDim       = 32
OutputDim       = 16
NumLayers       = 4
GNNEmbeddingDim = OutputDim

agent = sv.PPOAgent(
    NodeFeatureDim  = NodeFeatureDim,
    HiddenDim       = HiddenDim,
    OutputDim       = OutputDim,
    NumLayers       = NumLayers,
    GNNEmbeddingDim = GNNEmbeddingDim,
    LearningRate    = 3e-4,
    ClipEpsilon     = 0.2,
    Gamma           = 0.99,
    GaeLambda       = 0.95,
    EntropyCoef     = 0.01,
    ValueLossCoef   = 0.5,
    UpdateEpochs    = 4,
    BatchSize       = 32,
)

# ========1) 클래스 계층 트리========
_PALETTE = {0: '#1f3a5f', 1: '#2e5e8c', 2: '#4a86b8', 3: '#7fb3d5', 4: '#b0d4e8'}


def _brief(module: torch.nn.Module) -> str:
    extra = module.extra_repr()
    return extra if extra else module.__class__.__name__


def _add(dot: graphviz.Digraph, module: torch.nn.Module, name: str,
         parent_id: str, depth: int, max_depth: int, counter: list) -> None:
    counter[0] += 1
    node_id  = f'n{counter[0]}'
    children = list(module.named_children())
    cls      = module.__class__.__name__
    label    = f'{name}\\n[{cls}]'
    if not children:
        label += f'\\n{_brief(module)}'
    color = _PALETTE.get(min(depth, 4), '#cccccc')
    dot.node(node_id, label, fillcolor=color,
             fontcolor='white' if depth <= 2 else 'black')
    if parent_id is not None:
        dot.edge(parent_id, node_id)
    if depth < max_depth:
        for child_name, child in children:
            _add(dot, child, child_name, node_id, depth + 1, max_depth, counter)


def build_hierarchy(root: torch.nn.Module, root_name: str, max_depth: int = 10):
    dot = graphviz.Digraph('ml_hierarchy', format='png')
    dot.attr(rankdir='TB', bgcolor='white')
    dot.attr('node', shape='box', style='rounded,filled',
             fontname='Consolas', fontsize='11')
    dot.attr('edge', color='#888888', arrowsize='0.7')
    _add(dot, root, root_name, None, 0, max_depth, [0])
    path = dot.render(os.path.join(OUT, 'hierarchy'), cleanup=True)
    print('written:', path)


build_hierarchy(agent, 'PPOAgent')

# 콘솔에도 트리 출력
print('\n=== nn.Module 계층 ===')


def _print_tree(module, name='PPOAgent', prefix=''):
    extra = module.extra_repr()
    tag   = f' ({extra})' if extra and not list(module.named_children()) else ''
    print(f'{prefix}{name}: {module.__class__.__name__}{tag}')
    kids = list(module.named_children())
    for i, (cname, child) in enumerate(kids):
        last = i == len(kids) - 1
        _print_tree(child, cname,
                    prefix + ('└─ ' if last else '├─ '))


_print_tree(agent)

# ========2) 텐서 흐름 (서브넷별, torchviz autograd 그래프)========
# Actor/Critic 는 forward 안에서 nn.Linear 를 동적 생성(코드 버그)하고
# GNNEncoder 는 PyG 메시지패싱이라, 모듈훅 기반 torchview 가 실패한다.
# autograd 그래프를 추적하는 torchviz 는 두 경우 모두 처리 가능.
from torchviz import make_dot

N = 12  # 더미 노드 수


def _save_dot(output, params, name):
    dot = make_dot(output, params=params,
                    show_attrs=False, show_saved=False)
    dot.attr(rankdir='TB')
    dot.render(os.path.join(OUT, name), format='png', cleanup=True)
    print('written:', os.path.join(OUT, name) + '.png')


# GNNEncoder.forward(data: Data) → (N, OutputDim)
try:
    data = Data(
        x          = torch.randn(N, NodeFeatureDim),
        edge_index = torch.randint(0, N, (2, N * 2)),
    )
    out = agent.GNNEncoder(data)
    _save_dot(out, dict(agent.GNNEncoder.named_parameters()), 'gnn')
except Exception as e:
    print('GNNEncoder 실패:', repr(e))

# Actor.forward(x, ActionSpaceDim) → (1, ActionSpaceDim) softmax
try:
    x   = torch.randn(1, GNNEmbeddingDim)
    out = agent.Actor(x, 5)
    _save_dot(out, dict(agent.Actor.named_parameters()), 'actor')
except Exception as e:
    print('Actor 실패:', repr(e))

# Critic.forward(x) → (1, 1) value
try:
    x   = torch.randn(1, GNNEmbeddingDim)
    out = agent.Critic(x)
    _save_dot(out, dict(agent.Critic.named_parameters()), 'critic')
except Exception as e:
    print('Critic 실패:', repr(e))

print('\n완료 →', OUT)
