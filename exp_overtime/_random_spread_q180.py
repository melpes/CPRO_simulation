# 랜덤 초기화 정책 20개 — 도달 가능 성능 분포를 재서 "개선 여지 vs 구조적 한계" 판정
import sys, os, json, time
PACKAGE = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
sys.path.insert(0, PACKAGE); sys.dont_write_bytecode = True
from fifo_sweep_comp2base import tou, worktime, batch_log, FILES
NORMAL, PEAK, OFF = 1833.0, 3398.0, 1190.0
QTY = {"MODEL_A": 180, "MODEL_B": 180, "MODEL_C": 180}
DUE, MAXS, END = 3, 2592000, 20.0

import path_extractor, build, run_trained, torch, random
for f in FILES:
    path_extractor.load(os.path.join(PACKAGE, 'aas_data', f))
base_cls = run_trained._schedule_env_cls()

out = []
for s in range(1, 21):
    t0 = time.time()
    random.seed(1); torch.manual_seed(s)      # 환경 고정, 정책만 랜덤
    env = build.build_simulation(target_qty=dict(QTY), due_day={m: DUE for m in QTY},
                                 env_cls=batch_log(base_cls))
    env.WorkEndTime = END*3600.0; env.MaxEpisodeSec = MAXS; env.TariffObs = False
    env.reset()
    agent = build.build_agent(env, checkpoint=None)
    if hasattr(agent, 'reset_buffer'): agent.reset_buffer()
    env.run(agent=agent, max_sec=MAXS)
    ms = env.env.now
    b, _ = tou(env, ms)
    w = b['normal'] + b['peak']*(PEAK/NORMAL) + b['night']*(OFF/NORMAL)
    r = {'policy_seed': s, 'wall': round(time.time()-t0,1),
         'makespan_days': ms/86400.0, 'work_time_h': worktime(env, ms)/3600.0,
         'weighted_kwh': w, 'peak_kwh': b['peak'], 'total_kwh': env.total_energy_kwh(),
         'met': all(env.Throughput[m] >= env.target_qty[m] for m in env.target_qty)}
    out.append(r)
    print(f"[rand] seed={s:2d} makespan={r['makespan_days']:.4f}d work={r['work_time_h']:.2f}h "
          f"wkwh={w:.1f} met={r['met']}", flush=True)
    json.dump(out, open('exp_overtime/random_spread_q180.json','w',encoding='utf-8'),
              ensure_ascii=False, indent=1)
import statistics as st
for k in ('makespan_days','work_time_h','weighted_kwh'):
    v=[r[k] for r in out]
    print(f"{k:15s} min={min(v):9.4f} med={st.median(v):9.4f} max={max(v):9.4f} std={st.pstdev(v):8.5f}")
