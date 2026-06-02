# -*- coding: utf-8 -*-
"""1일(86400s) 스케줄링 캡처 + 간트 렌더.

스모크 학습(_daily_train_smoke, qty=100 ep2, StateDim=18)이 만든 에이전트로 1일 에피소드를
greedy 와 함께 캡처 → events 저장 → _redraw_gantt_slots 로 간트.

env.now=0=자정, 작업 09:00~18:00. 1일 horizon 이라 간트는 D1 하루분만 채워짐.
_capture_oqc 의 RecEnv·make_env·AAS load 를 그대로 재사용 (중복 회피).

출력: mod_run/result/runs/{MMDDHHMM}_daily_smoke/
"""
import os, sys, json, time, subprocess
import torch

_DIR  = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_DIR)
sys.path.insert(0, _DIR); sys.path.insert(0, _ROOT)

import _capture_oqc as cap        # AAS load + RecEnv + make_env + GNN/TC 상수 재사용
import simulation_ver1 as sv

SM  = cap.SM
GNN = cap.GNN
TC  = cap.TC

RUN_NAME   = time.strftime('%m%d%H%M') + '_daily_smoke'
OUT        = os.path.join(_DIR, 'result', 'runs', RUN_NAME)
SMOKE_CKPT = os.path.join(_DIR, 'result', 'runs',
                          'daily_smoke_2026-05-31_21-56-52', 'agent_mod.pt')
MAX_SEC    = 86400            # 1일
os.makedirs(OUT, exist_ok=True)


def build_smoke_agent(state_dim):
    import cpro_factory as cf                       # agent wiring 단일 구현
    return cf.build_agent(StateDim=state_dim, checkpoint=SMOKE_CKPT)


def capture(label, agent):
    print(f'[{time.strftime("%H:%M:%S")}] {label} 1일 sim 시작 (max_sec={MAX_SEC}s)...', flush=True)
    env = cap.make_env(seed=42)
    t0  = time.time()
    summary = env.run(agent=agent, max_sec=MAX_SEC)
    dt  = time.time() - t0
    ev  = env.events
    print(f'[{time.strftime("%H:%M:%S")}] {label} 완료 dt={dt:.1f}s events={len(ev)} '
          f'makespan={summary["makespan_sec"]:.0f}s ({summary["makespan_sec"]/3600:.1f}h) '
          f'thru={summary["Throughput"]}', flush=True)
    p = os.path.join(OUT, f'events_{label}.jsonl')
    with open(p, 'w', encoding='utf-8') as fp:
        for (m, pc, ln, t0_, t_cyc, t_tot) in ev:
            fp.write(json.dumps({'model': m, 'pc': pc, 'line': ln,
                                 't0': float(t0_), 't_cycle': float(t_cyc),
                                 't_total': float(t_tot)}) + '\n')
    return summary


def main():
    print(f'대상 폴더: {OUT}', flush=True)
    s_g = capture('greedy', None)
    # state_dim 알아내기 위해 env 1개 — make_env 가 state_dim 제공
    state_dim = cap.make_env(seed=42).state_dim
    ag  = build_smoke_agent(state_dim)
    s_t = capture('trained_det', ag)

    smr = [f'# 1일 스케줄링 간트 (qty=100/100/100, max_sec=86400)  /  {RUN_NAME}', '',
           '스모크 학습(qty=100 ep2, StateDim=18) 에이전트로 1일 에피소드 캡처.',
           'env.now=0=자정, 작업 09:00~18:00. 1일 horizon → target(100) 미달, D1 하루분 스케줄.',
           '',
           '## throughput (1일에 처리한 unit)', '']
    for label, s in [('greedy', s_g), ('trained_det', s_t)]:
        smr.append(f'- {label}: {dict(s["Throughput"])}  makespan={s["makespan_sec"]:.0f}s')
    smr += ['', '## 산출물',
            '- `events_*.jsonl`, `gantt_*.png` (WWM_OqcLine 포함, RMA 제외)',
            f'- 에이전트: `daily_smoke_2026-05-31_21-56-52/agent_mod.pt` (2ep, StateDim=18)']
    with open(os.path.join(OUT, 'summary.md'), 'w', encoding='utf-8') as fp:
        fp.write('\n'.join(smr) + '\n')

    print(f'\n[{time.strftime("%H:%M:%S")}] 간트 렌더링...', flush=True)
    r = subprocess.run([sys.executable, os.path.join(_DIR, '_redraw_gantt_slots.py'), RUN_NAME],
                       capture_output=True, text=True, encoding='utf-8')
    print(r.stdout, flush=True)
    if r.returncode != 0:
        print('GANTT STDERR:', r.stderr, flush=True)
    print('\n=== summary ===\n' + '\n'.join(smr))


if __name__ == '__main__':
    main()
