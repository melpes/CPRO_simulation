# -*- coding: utf-8 -*-
"""학습 진입점. AAS(5파일) 로드 → build.build_simulation/build_agent → train 루프.

수량·납기일·에피소드 수는 전부 AAS(PurchaseOrder·SimulationConfig)에서 자동으로 읽는다.
산출물: result/runs/run_<날짜시각>/ (rl_log.jsonl · agent_mod.pt).
graceful 중단: run 폴더에 빈 STOP 파일 → 다음 에피소드 시작 시 안전 종료 + best 보존.
"""
from __future__ import annotations
import os, time

import torch

from util.rl_logger import RLLogger
from simulation import EPISODE_DURATION_SEC


def train(env, agent, MaxEpisodes, run_name=None, episode_max_sec=EPISODE_DURATION_SEC):
    _ROOT = os.path.dirname(os.path.abspath(__file__))

    if run_name is None:
        run_name = 'run_' + time.strftime('%Y-%m-%d_%H-%M-%S')
    _OUT = os.path.join(_ROOT, 'result', 'runs', run_name)
    os.makedirs(_OUT, exist_ok=True)
    print(f'[train] outputs → result/runs/{run_name}/', flush=True)
    logger = RLLogger(os.path.join(_OUT, 'rl_log.jsonl'))
    ckpt   = os.path.join(_OUT, 'agent_mod.pt')

    for episode in range(MaxEpisodes):
        if os.path.exists(os.path.join(_OUT, 'STOP')):
            print(f'[ep {episode}] STOP sentinel — graceful exit', flush=True)
            break
        agent.reset_buffer()
        summary = env.run(agent=agent, max_sec=episode_max_sec)
        R = env.episode_reward()
        decisions = len(agent.buf)
        metrics = agent.learn(R, env.KnowledgeGraph)
        is_best = logger.log_episode(
            episode, R=R, makespan=summary['makespan_sec'],
            energy=summary['EpisodeEnergyKwh'],
            throughput=dict(env.Throughput), target_qty=dict(env.target_qty),
            decisions=decisions, metrics=metrics,
            violations={'stock_shortage': env.StockShortageCount,
                        'stock_overflow': env.StockOverflowCount,
                        'idle_violation': env.IdleViolationCount,
                        'due_pace_deficit': env.DuePaceDeficit,
                        **{f'due_pace/{model_id}': value
                           for model_id, value in env.DuePaceDeficitByModel.items()}})
        if is_best:
            torch.save(agent.state_dict(), ckpt)
        thru = ' '.join(f'{m}:{env.Throughput[m]}/{env.target_qty[m]}' for m in env.target_qty)
        ev = (metrics or {}).get('critic/explained_variance')
        print(f'[ep {episode:>4}] R={R:+.4f} decisions={decisions} '
              f'makespan={summary["makespan_sec"]:.0f} E={summary["EpisodeEnergyKwh"]:.2f} '
              f'thru=[{thru}] ev={ev} {"BEST↑" if is_best else ""}')

    # 학습 종료 → best 체크포인트로 자족 추론 패키지 자동 생성 (result/runs/<run>/deploy/)
    if os.path.exists(ckpt):
        import package
        pkg = package.build_package(ckpt, os.path.join(_OUT, 'deploy'))
        print(f'[train] deploy package → {os.path.relpath(pkg, _ROOT)}/', flush=True)


if __name__ == '__main__':
    import path_extractor
    import build

    _ROOT = os.path.dirname(os.path.abspath(__file__))
    for _f in build.TRAINING_AAS_FILES:                # 학습은 5파일 (SMTEquipmentCatalog 제외)
        path_extractor.load(os.path.join(_ROOT, 'aas_data', _f))

    env   = build.build_simulation()                   # 수량·납기일·에피소드 모두 AAS(PurchaseOrder·SimulationConfig)에서
    agent = build.build_agent(env)
    train(env, agent, env.MaxEpisodes)
