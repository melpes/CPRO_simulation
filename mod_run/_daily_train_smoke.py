# -*- coding: utf-8 -*-
"""1일(86400s) 학습 smoke test — train() 의 episode_max_sec=86400 적용 검증.

목적: 1일 horizon 으로 학습 1~2 ep 돌려 throughput 비포화 + returns_var > 0 (학습 신호)
확인. 모델별 1000 unit 목표 (1일 안에 절대 못 끝나게).

검증 항목:
  - episode_max_sec=86400 적용 → makespan_sec == 86400 (target_qty 도달 X)
  - Throughput 모델별 절대값 (1일에 몇 개 처리)
  - returns_var > 1e-6 (per-step reward 의미 신호)
  - ev (explained_variance) 비-NaN
"""
import os, sys, time, traceback, json

DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, DIR)
sys.path.insert(0, os.path.dirname(DIR))

import _timeit as T


def main():
    # 검증된 풀런(300unit, makespan 134.3h)에서 일 처리량 ≈ 54unit/day ≈ 모델당 18/일.
    # qty 가 18/model 초과면 1일 비포화 보장 → 검증된 코루틴 수(300=100/model)면 충분·고속.
    QTY, EP = 100, 2      # 1일에 못 끝나는(>18/model) qty + 2 ep (신호 변동 보기)
    print(f'==== 1일 학습 smoke ====  qty={QTY}/model, ep={EP}, horizon=86400s(=1일)')

    sv, env, agent = T.build('simulation_ver1', QTY, EP)
    print(f'  state_dim={env.state_dim}  agent.StateDim={agent.StateDim}')

    run_name  = 'daily_smoke_' + time.strftime('%Y-%m-%d_%H-%M-%S')
    log_path  = os.path.join(DIR, 'result', 'runs', run_name, 'rl_log.jsonl')

    print(f'\ntrain {EP}ep → result/runs/{run_name}/  episode_max_sec=86400')
    t0 = time.perf_counter()
    sv.train(env, agent, EP, run_name=run_name, episode_max_sec=86400)
    dt = time.perf_counter() - t0
    print(f'\ntrain wall={dt:.1f}s ({dt/EP:.1f}s/ep)')

    rows = [json.loads(l) for l in open(log_path, encoding='utf-8')]
    print(f'\n===== rl_log ({len(rows)} ep) =====')
    for r in rows:
        print(f"  ep{r['episode']}: "
              f"R={r['train/rollout_reward']:+.4f} "
              f"thru={r['task/throughput']} "
              f"decisions={r['sanity/episode_length']} "
              f"ret_var={r['critic/returns_var']:.5f} "
              f"ev={r['critic/explained_variance']} "
              f"kl={r['stability/approx_kl']:+.2e}")

    # 핵심 검증 (makespan 은 rl_log 미기록 — train() stdout 의 'makespan=86400' 으로 확인)
    print('\n===== 검증 =====')
    rv = [r['critic/returns_var'] for r in rows]
    th = [sum(r['task/throughput'].values()) for r in rows]
    total_target = QTY * 3
    print(f'  throughput 합: {th}  (1일에 처리한 총 unit 수)')
    print(f'  returns_var: {rv}')
    if max(rv) > 1e-6:
        print('  ✓ returns_var > 1e-6 — 학습 신호 발생')
    else:
        print('  ⚠ returns_var ≈ 0 — reward 정규화 분모 재설계 필요')
    if all(t < total_target for t in th):
        print(f'  ✓ throughput 비포화 (1일에 {th} < target {total_target}) — 학습 leverage 있음')
    else:
        print(f'  ⚠ 1일에 target 도달 — qty 더 키워야')


if __name__ == '__main__':
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
