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
    # qty=100 이 1일 학습의 올바른 regime — 하한·상한 둘 다 있다:
    #   하한: 일 처리량 ≈ 모델당 18/일(풀런 300unit/134h 환산) → qty>18/model 이면 1일 비포화.
    #   상한: qty≥500 이면 1500+ unit 이 1단계 job 으로 큐를 범람 → greedy 가 하루 내내 초기단계만
    #         처리, AGING→PACK 도달 0 → throughput=0(붕괴) + 보상 degenerate(W5=0 → 다른 항 ∞배).
    #   또한 보상 정규화(W5=produced/total_target, W4/W6=counter/(품목·워커×틱))는 qty~100 에서만
    #   균형 — qty 키우면 W5/W2 만 ∝1/qty 줄고 W4/W6 은 고정이라 재고·유휴가 지배. (scratch/_phi_scale_check.py 실측)
    QTY, EP = 100, 2      # 비포화(20% 완성) + 보상 균형 + throughput>0 동시 만족하는 regime
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
    th = [r['task/throughput'] for r in rows]                  # task/throughput = 총 throughput(int)
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

    # ===== Φ 항별 분해 (마지막 ep terminal 상태) — W3/W4/W6 추가 후 항 스케일 검증 =====
    # train 후 env 는 마지막 에피소드 terminal 상태 보유. potential() 의 6항을 동일 수식으로 재현.
    print('\n===== Φ 항별 분해 (terminal, |항| 이 throughput 항과 1자릿수 내여야 비지배) =====')
    w = env.RewardWeights
    tt = sum(env.target_qty.values())
    work_day = env.WorkEndTime - env.WorkStartTime - (env.break_end_sec - env.break_start_sec)
    maxE_premium = env.RuntimeVariables.MaxEpisodeEnergyKwh(env.KnowledgeGraph, env.target_qty,
                    env.IdleProcessRatedPowerKw, env.IdlePowerRatio)
    terms = {
        'W5_Throughput  ': + (sum(env.Throughput.values()) / tt)            * w['W5_Throughput'],
        'W1_Time        ': - (env.env.now / (work_day * tt))               * w['W1_TimeElapsed'],
        'W2_Energy      ': - (env.EpisodeEnergyKwh / maxE_premium)         * w['W2_Energy'],
        'W3_StockOver   ': - (env.StockOverflowCount / env._stock_violation_norm) * w['W3_StockOverflow'],
        'W4_StockShort  ': - (env.StockShortageCount / env._stock_violation_norm) * w['W4_StockShortage'],
        'W6_Idle        ': - (env.IdleViolationCount / env._idle_violation_norm)  * w['W6_IdleWorker'],
    }
    print(f'  counters: shortage={env.StockShortageCount} overflow={env.StockOverflowCount} '
          f'idle={env.IdleViolationCount}  (norm: stock={env._stock_violation_norm:.0f} idle={env._idle_violation_norm:.0f})')
    for name, val in terms.items():
        print(f'    {name}: {val:+.5f}')
    print(f'    {"Φ(total)      "}: {sum(terms.values()):+.5f}  (env.potential()={env.potential():+.5f})')
    thr_mag = abs(terms['W5_Throughput  ']) or 1e-9
    for name, val in terms.items():
        if name.startswith('W5'): continue
        ratio = abs(val) / thr_mag
        flag = '✓' if ratio <= 10 else '⚠ 지배'
        print(f'    {name} / W5 비율 = {ratio:6.2f}  {flag}')


if __name__ == '__main__':
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
