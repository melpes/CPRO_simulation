from __future__ import annotations
import os, shutil, argparse

import build

_ROOT = os.path.dirname(os.path.abspath(__file__))

CODE_MODULES = ['run_trained.py', 'build.py', 'simulation.py', 'export.py',
                'knowledge_graph.py', 'warehouse.py', 'smt.py', 'carbon.py', 'path_extractor.py']
TEMPLATE_FILES  = ['requirements-infer.txt', 'README.md',
                   'scenario.infinite.json', 'scenario.schedule.json',
                   'scenario.realloc.json', 'scenario.aging.json']
AAS_DIR_NAME    = 'aas_data'
DEPLOY_DIR      = 'deploy'
CHECKPOINT_NAME = 'agent_mod.pt'


def build_package(checkpoint: str, out_dir: str, *, aas_dir: str = None) -> str:
    aas_dir = aas_dir or os.path.join(_ROOT, AAS_DIR_NAME)
    if not os.path.isfile(checkpoint):
        raise FileNotFoundError(f'checkpoint not found: {checkpoint}')
    os.makedirs(out_dir, exist_ok=True)

    for module in CODE_MODULES:
        src = os.path.join(_ROOT, module)
        if not os.path.isfile(src):
            raise FileNotFoundError(f'inference module missing: {module}')
        shutil.copy2(src, os.path.join(out_dir, module))

    aas_out = os.path.join(out_dir, AAS_DIR_NAME)
    os.makedirs(aas_out, exist_ok=True)
    for filename in build.TRAINING_AAS_FILES:
        shutil.copy2(os.path.join(aas_dir, filename), os.path.join(aas_out, filename))

    shutil.copy2(checkpoint, os.path.join(out_dir, CHECKPOINT_NAME))

    for filename in TEMPLATE_FILES:
        shutil.copy2(os.path.join(_ROOT, DEPLOY_DIR, filename), os.path.join(out_dir, filename))

    return out_dir


def main(argv=None):
    parser = argparse.ArgumentParser(description='학습된 체크포인트로 자족 추론 패키지 생성')
    parser.add_argument('--ckpt', required=True)
    parser.add_argument('--out', default=None)
    parser.add_argument('--aas-dir', dest='aas_dir', default=None)
    args = parser.parse_args(argv)

    out_dir = args.out or os.path.join(os.path.dirname(os.path.abspath(args.ckpt)), DEPLOY_DIR)
    package = build_package(args.ckpt, out_dir, aas_dir=args.aas_dir)
    file_count = sum(len(files) for _, _, files in os.walk(package))
    print(f'[package] 자족 추론 패키지 → {package}  ({file_count} files)')
    print(f'[package] 실행:  cd {package} && pip install -r requirements-infer.txt && '
          f'python run_trained.py --in scenario.example.json --out result.json')


if __name__ == '__main__':
    main()
