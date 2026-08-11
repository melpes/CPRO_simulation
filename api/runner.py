# -*- coding: utf-8 -*-
# 워커 프로세스 격리 — 시뮬 코드의 프로세스 전역 상태(AAS 싱글턴·RNG·정책 인스턴스)를
# 주소공간 분리로 차단한다. 워커마다 TrainedModel 을 1회 만들고, 잡은 프로세스 내 순차 실행.
#
# 입력은 AAS 가 담당: 실행 요청 시점에 API 프로세스가 aas_data 의 PurchaseOrder 를 읽어
# 잡 입력(po)으로 동결하고, 워커는 그 값으로 시뮬을 돌린다 (요청 후 PUT 이 와도 해당 실행은 불변).
import json
import os
import sys

_MODEL = None


def _package_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def init_worker(ckpt_path: str, aas_dir: str) -> None:
    global _MODEL
    root = _package_root()
    if root not in sys.path:
        sys.path.insert(0, root)
    import torch
    torch.set_num_threads(1)          # 워커 N개 × torch 스레드 = 오버서브스크립션 방지
    from run_trained import TrainedModel
    _MODEL = TrainedModel(checkpoint=ckpt_path, aas_dir=aas_dir)


def _atomic_json(path: str, obj) -> None:
    tmp = f'{path}.tmp'
    with open(tmp, 'w', encoding='utf-8') as fp:
        json.dump(obj, fp, ensure_ascii=False)
    os.replace(tmp, path)


def execute(run_input: dict, seed: int, run_dir: str) -> dict:
    """워커에서 시뮬 1회를 실행하고 산출물 4분류(artifacts.json)를 run_dir 에 쓴다.
    결과(수 MB)를 부모로 피클링해 돌려보내지 않고 파일로 넘긴다."""
    import run_trained

    import export

    po = run_input['po']
    target_qty = {model_id: int(spec['qty']) for model_id, spec in po.items()}
    due_day    = {model_id: int(spec['due_day']) for model_id, spec in po.items()}
    env, summary = _MODEL.simulate(target_qty=target_qty, due_day=due_day,
                                   overrides={}, seed=seed)
    sample_sec = int(os.getenv('CPRO_SAMPLE_SEC', '1800'))   # 문서 예시 샘플링 주기 0.5h
    artifacts = run_trained.artifacts(env, summary, sample_sec=sample_sec)
    snap = export.snapshot(env, summary)   # GET 요청 시 다른 주기로 재버킷하기 위한 원자료

    os.makedirs(run_dir, exist_ok=True)
    _atomic_json(os.path.join(run_dir, 'artifacts.json'), artifacts)
    _atomic_json(os.path.join(run_dir, 'snapshot.json'), snap)

    metric = artifacts['metric']
    summary_line = (f"makespan={metric['makespan_days']:.2f}d "
                    f"throughput={sum(metric['throughput'].values())}/{metric['total_qty']} "
                    f"target_met={metric['target_met']} "
                    f"power={metric['power_kwh']['total']:.1f}kWh")
    return {'summary_line': summary_line}


def model_info() -> dict:
    """학습된 모델셋·기본 수량. 워커 워밍업 겸용(첫 호출이 AAS·정책 로드를 확정한다)."""
    return {'models': sorted(_MODEL.model_set),
            'default_order_quantity': dict(_MODEL.default_target)}
