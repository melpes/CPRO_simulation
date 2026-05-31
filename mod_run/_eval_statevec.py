# -*- coding: utf-8 -*-
"""state_vec 학습 체크포인트 deterministic eval — qty=100×3 전량완료까지.

비교 대상: result/runs/current_render_05-25/metadata.json
- trained_det (baseline StateDim=0): makespan 388,015s (107.78h)
- greedy:                            makespan 467,701s (129.92h)
- 단축률: 17%
"""
import os, sys, time, torch, json
_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _DIR); sys.path.insert(0, os.path.dirname(_DIR))

import simulation_ver1 as svm
import _timeit as T

CKPT = os.path.join(_DIR, 'result', 'runs',
                    'b2_horizon_statevec_60ep_latest_05-25',
                    'agent_horizon_qty100.pt')
OUT  = os.path.join(_DIR, 'result', 'runs',
                    'b2_horizon_statevec_60ep_latest_05-25',
                    'eval_summary.json')

print(f'[{time.strftime("%H:%M:%S")}] build env (qty=100×3) + agent (StateDim=18)')
sv, env, ag = T.build('simulation_ver1', qty=100, ep=1)
print(f'  agent.StateDim = {ag.StateDim}')
print(f'  Actor first Linear in_features = {ag.Actor.layers[0].in_features}')

print(f'[{time.strftime("%H:%M:%S")}] loading checkpoint: {os.path.basename(CKPT)}')
ag.load_state_dict(torch.load(CKPT))
ag.eval()                                # → choose() 가 argmax 사용 (deterministic)
ag.reset_buffer()

# 전량완료까지 — max_sec 기본값 60일이면 충분
print(f'[{time.strftime("%H:%M:%S")}] env.run(agent=ag) deterministic 시작 (target 300)')
t0 = time.time()
summary = env.run(agent=ag)
dt = time.time() - t0
print(f'[{time.strftime("%H:%M:%S")}] 완료 wall={dt:.1f}s')

result = {
    'agent_source'       : CKPT,
    'agent_arch'         : f'PPOAgent StateDim={ag.StateDim}',
    'env_qty'            : dict(env.target_qty),
    'policy'             : 'trained, deterministic (eval=argmax)',
    'makespan_sec'       : float(summary['makespan_sec']),
    'makespan_h'         : float(summary['makespan_sec']) / 3600,
    'throughput'         : dict(env.Throughput),
    'EpisodeEnergyKwh'   : float(summary['EpisodeEnergyKwh']),
    'ActivePremiumKwh'   : float(summary['ActivePremiumKwh']),
    'decisions'          : len(ag.buf),
    'wall_sec'           : dt,
}
print('\n===== EVAL RESULT =====')
for k, v in result.items():
    print(f'  {k:22s} = {v}')

# 비교
print('\n===== vs current_render_05-25 =====')
baseline = {'makespan_h': 107.78, 'throughput': {'MODEL_A': 100, 'MODEL_B': 100, 'MODEL_C': 100}}
greedy   = {'makespan_h': 129.92, 'throughput': {'MODEL_A': 100, 'MODEL_B': 100, 'MODEL_C': 100}}
print(f'  baseline (StateDim=0 trained_det): makespan={baseline["makespan_h"]:.2f}h thru={baseline["throughput"]}')
print(f'  greedy                            : makespan={greedy["makespan_h"]:.2f}h thru={greedy["throughput"]}')
print(f'  state_vec (StateDim=18)            : makespan={result["makespan_h"]:.2f}h thru={result["throughput"]}')
vs_base = (baseline['makespan_h'] - result['makespan_h']) / baseline['makespan_h'] * 100
vs_grdy = (greedy['makespan_h']   - result['makespan_h']) / greedy['makespan_h']   * 100
print(f'\n  state_vec vs baseline : {vs_base:+.2f}%  (양수=더 빠름)')
print(f'  state_vec vs greedy   : {vs_grdy:+.2f}%  (양수=더 빠름)')

with open(OUT, 'w', encoding='utf-8') as f:
    json.dump({**result, 'comparison': {'baseline_trained_h': baseline['makespan_h'],
                                          'greedy_h': greedy['makespan_h'],
                                          'pct_vs_baseline': vs_base,
                                          'pct_vs_greedy':   vs_grdy}},
              f, ensure_ascii=False, indent=2)
print(f'\n  → {OUT}')
