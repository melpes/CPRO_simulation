# -*- coding: utf-8 -*-
"""state_vec 주입 후 end-to-end smoke test.

목적: qty=2 × 2ep 로 forward/backward/shape 정합성과 returns_var > 0 (학습 신호 발생)
까지 한 번에 확인. 진짜 학습 효과는 별도 본 실험에서 60ep 돌려 비교.
"""
import os, sys, time, io, contextlib, traceback

DIR   = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, DIR)
sys.path.insert(0, os.path.dirname(DIR))

import torch
import _timeit as T
import simulation_ver1 as svm


def main():
    print('==== state_vec smoke ====')
    QTY, EP = 2, 2
    print(f'build: qty={QTY} ep={EP}')
    sv, env, agent = T.build('simulation_ver1', QTY, EP)

    # 1) state_dim / state_vec 검증
    env.reset()
    sd = env.state_dim
    sv_tensor = env.state_vec()
    print(f'  state_dim={sd}  state_vec.shape={tuple(sv_tensor.shape)}  '
          f'dtype={sv_tensor.dtype}')
    assert sv_tensor.shape == (sd,), 'state_vec dim mismatch'
    assert agent.StateDim == sd, f'agent.StateDim({agent.StateDim}) != env.state_dim({sd})'
    assert agent.Actor.layers[0].in_features == int(agent.Actor.layers[0].in_features), 'Actor in_feat OK'
    print(f'  Actor first Linear in_features={agent.Actor.layers[0].in_features} '
          f'(expect GNNEmbeddingDim + StateDim)')
    print(f'  Critic first Linear in_features={agent.Critic.layers[0].in_features}')

    # 2) 1 결정점 forward 단독 확인 — ready_pcs 가짜로 만들어 호출
    kg = env.KnowledgeGraph
    ready_sample = list(kg.nodes.keys())[:3]
    agent.reset_buffer()
    pick = agent.choose(ready_sample, env)
    print(f'  choose sample → pick={pick}  buf[0].keys={list(agent.buf[0].keys())}')
    assert 'state' in agent.buf[0] and agent.buf[0]['state'] is not None, 'state not stored'
    assert agent.buf[0]['state'].shape == (sd,), 'stored state dim mismatch'

    # 3) train 2 ep — ver1 train 은 result/runs/<run_name>/ 에 기록 (실행별 폴더)
    run_name  = 'smoke_statevec_' + time.strftime('%Y-%m-%d_%H-%M-%S')
    smoke_log = os.path.join(DIR, 'result', 'runs', run_name, 'rl_log.jsonl')

    print(f'\ntrain {EP}ep — train(run_name={run_name!r}) → result/runs/{run_name}/')
    t0 = time.perf_counter()
    sv.train(env, agent, EP, run_name=run_name)
    dt = time.perf_counter() - t0

    print(f'\ntrain wall={dt:.1f}s')

    # 4) smoke log 검증
    import json
    rows = [json.loads(l) for l in open(smoke_log, encoding='utf-8')]
    print(f'\n===== smoke log ({len(rows)} ep) =====')
    for r in rows:
        print(f"  ep{r['episode']} R={r['train/rollout_reward']:+.4f} "
              f"decisions={r['sanity/episode_length']} "
              f"throughput={r['task/throughput']} "
              f"ret_var={r['critic/returns_var']:.5f} "
              f"ev={r['critic/explained_variance']} "
              f"kl={r['stability/approx_kl']:+.2e}")

    rv = [r['critic/returns_var'] for r in rows]
    print(f'\n  returns_var range: {min(rv):.5f} ~ {max(rv):.5f}')
    if max(rv) > 1e-6:
        print('  ✓ returns_var > 1e-6 — 학습 신호 발생 (per-step reward 가 결정점마다 의미있게 변함)')
    else:
        print('  ⚠ returns_var ≈ 0 — 여전히 무신호. shaping 검토 필요')
    print('\n==== smoke 완료 ====')


if __name__ == '__main__':
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
