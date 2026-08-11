# -*- coding: utf-8 -*-
# 시나리오별 독립 실행 패키지 생성기.
#   각 패키지 = 시뮬레이션 구동부(engine + 도메인) + 실행부 1개(해당 시나리오) + API + AAS + 정책.
#   부모 repo 없이 단독으로 CLI·API 둘 다 구동된다.
from __future__ import annotations

import argparse
import os
import shutil

import build

_ROOT = os.path.dirname(os.path.abspath(__file__))

# 시뮬레이션 구동부 — 전 시나리오 공통
ENGINE_MODULES = ['engine.py', 'build.py', 'simulation.py', 'export.py',
                  'knowledge_graph.py', 'warehouse.py', 'smt.py', 'carbon.py', 'path_extractor.py']

# 시나리오 실행부 — 패키지마다 하나만, scenario.py 로 이름을 바꿔 넣는다
SCENARIOS = ['schedule', 'infinite', 'realloc', 'aging']
SCENARIO_DIR = 'scenarios'

API_PACKAGE     = 'api'
AAS_DIR_NAME    = 'aas_data'
DEPLOY_DIR      = 'deploy'
CHECKPOINT_NAME = 'agent_mod.pt'
DEPLOY_FILES    = ['requirements-infer.txt', 'requirements-api.txt',
                   'Dockerfile', '.dockerignore', 'API.md']


def build_scenario_package(scenario: str, checkpoint: str, out_dir: str, *, aas_dir: str = None) -> str:
    if scenario not in SCENARIOS:
        raise ValueError(f'알 수 없는 시나리오: {scenario} (가능: {SCENARIOS})')
    aas_dir = aas_dir or os.path.join(_ROOT, AAS_DIR_NAME)
    if not os.path.isfile(checkpoint):
        raise FileNotFoundError(f'체크포인트 없음: {checkpoint}')

    if os.path.isdir(out_dir):
        shutil.rmtree(out_dir)
    os.makedirs(out_dir)

    for module in ENGINE_MODULES:                                   # 구동부
        shutil.copy2(os.path.join(_ROOT, module), os.path.join(out_dir, module))

    shutil.copy2(os.path.join(_ROOT, SCENARIO_DIR, f'{scenario}.py'),   # 실행부 1개
                 os.path.join(out_dir, 'scenario.py'))

    shutil.copytree(os.path.join(_ROOT, API_PACKAGE), os.path.join(out_dir, API_PACKAGE),
                    ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))

    aas_out = os.path.join(out_dir, AAS_DIR_NAME)                   # AAS + 정책
    os.makedirs(aas_out)
    for filename in build.TRAINING_AAS_FILES:
        shutil.copy2(os.path.join(aas_dir, filename), os.path.join(aas_out, filename))
    shutil.copy2(checkpoint, os.path.join(out_dir, CHECKPOINT_NAME))

    for filename in DEPLOY_FILES:                                   # 배포 파일
        source = os.path.join(_ROOT, DEPLOY_DIR, filename)
        if os.path.isfile(source):
            shutil.copy2(source, os.path.join(out_dir, filename))

    example = os.path.join(_ROOT, DEPLOY_DIR, f'scenario.{scenario}.json')   # 입력 예시
    if os.path.isfile(example):
        shutil.copy2(example, os.path.join(out_dir, 'scenario.json'))

    return out_dir


def main(argv=None):
    parser = argparse.ArgumentParser(description='시나리오별 독립 실행 패키지 생성')
    parser.add_argument('--ckpt', required=True, help='학습된 체크포인트 .pt')
    parser.add_argument('--out', default=os.path.join(_ROOT, 'dist'), help='출력 폴더')
    parser.add_argument('--aas-dir', dest='aas_dir', default=None)
    parser.add_argument('--scenario', choices=SCENARIOS, default=None,
                        help='특정 시나리오만 생성 (생략 시 4개 전부)')
    args = parser.parse_args(argv)

    for scenario in ([args.scenario] if args.scenario else SCENARIOS):
        out_dir = os.path.join(args.out, f'cpro-{scenario}')
        build_scenario_package(scenario, args.ckpt, out_dir, aas_dir=args.aas_dir)
        count = sum(len(files) for _, _, files in os.walk(out_dir))
        print(f'[package] {scenario:9} → {out_dir}  ({count} files)')

    print()
    print('실행:  cd <패키지>  &&  pip install -r requirements-api.txt')
    print('  API :  uvicorn api.main:app --host 0.0.0.0 --port 8000 --workers 1')


if __name__ == '__main__':
    main()
