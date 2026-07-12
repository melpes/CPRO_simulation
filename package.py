# -*- coding: utf-8 -*-
"""추론 패키지 생성기 — 체크포인트 1개로 '자족 실행 폴더'를 찍어낸다.

생성된 폴더는 부모 repo 없이 단독 실행된다(의존성만 req 로 설치):
    cd <out>
    pip install -r requirements-infer.txt
    python run_trained.py --in scenario.example.json --out result.json

복사물: 추론 코드(폐포 8모듈) + aas_data(5파일) + 체크포인트(→agent_mod.pt) + 템플릿(req·scenario·README).
학습 종료 시 train.py 가 best 체크포인트로 자동 호출(result/runs/<run>/deploy/). 수동도 가능:
    python package.py --ckpt result/runs/<run>/agent_mod.pt
"""
from __future__ import annotations
import os, sys, shutil, argparse

import build

_ROOT = os.path.dirname(os.path.abspath(__file__))

CODE_MODULES = ['run_trained.py', 'build.py', 'simulation.py', 'export.py',
                'knowledge_graph.py', 'warehouse.py', 'smt.py', 'carbon.py', 'path_extractor.py']

TEMPLATE_FILES = ['requirements-infer.txt', 'scenario.example.json', 'README.md']


def build_package(checkpoint: str, out_dir: str, *, aas_dir: str = None) -> str:
    aas_dir = aas_dir or os.path.join(_ROOT, 'aas_data')
    if not os.path.isfile(checkpoint):
        raise FileNotFoundError(f'checkpoint not found: {checkpoint}')
    os.makedirs(out_dir, exist_ok=True)

    for mod in CODE_MODULES:
        src = os.path.join(_ROOT, mod)
        if not os.path.isfile(src):
            raise FileNotFoundError(f'inference module missing: {mod}')
        shutil.copy2(src, os.path.join(out_dir, mod))

    aas_out = os.path.join(out_dir, 'aas_data')
    os.makedirs(aas_out, exist_ok=True)
    for f in build.TRAINING_AAS_FILES:
        shutil.copy2(os.path.join(aas_dir, f), os.path.join(aas_out, f))

    shutil.copy2(checkpoint, os.path.join(out_dir, 'agent_mod.pt'))

    for f in TEMPLATE_FILES:
        shutil.copy2(os.path.join(_ROOT, 'deploy', f), os.path.join(out_dir, f))

    return out_dir


def main(argv=None):
    p = argparse.ArgumentParser(description='학습된 체크포인트로 자족 추론 패키지 생성')
    p.add_argument('--ckpt', required=True, help='체크포인트 .pt')
    p.add_argument('--out', default=None,
                   help='출력 폴더 (기본: <ckpt 폴더>/deploy)')
    p.add_argument('--aas-dir', dest='aas_dir', default=None, help='AAS 디렉토리 (기본: ./aas_data)')
    a = p.parse_args(argv)

    out = a.out or os.path.join(os.path.dirname(os.path.abspath(a.ckpt)), 'deploy')
    pkg = build_package(a.ckpt, out, aas_dir=a.aas_dir)
    n_files = sum(len(files) for _, _, files in os.walk(pkg))
    print(f'[package] 자족 추론 패키지 → {pkg}  ({n_files} files)')
    print(f'[package] 실행:  cd {pkg} && pip install -r requirements-infer.txt && '
          f'python run_trained.py --in scenario.example.json --out result.json')


if __name__ == '__main__':
    main()
