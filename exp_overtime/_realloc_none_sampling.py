# 재배분 없이(none) 기존 정책을 argmax / 샘플링으로 — 재배분 무용화의 원인 분리
import sys, os, json, time
PACKAGE = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
sys.path.insert(0, PACKAGE); sys.dont_write_bytecode = True
from fifo_sweep_comp2base import tou, batch_log, FILES
NORMAL, PEAK, OFF = 1833.0, 3398.0, 1190.0
import path_extractor, build, run_trained, torch, random
for f in FILES: path_extractor.load(os.path.join(PACKAGE,'aas_data',f))
base_cls = run_trained._schedule_env_cls()

CKPTS = [('q180s__compbase-300ep(1-1 원본)', 'result/runs/q180s__compbase-300ep/agent_last.pt'),
         ('q180s__q540val-300ep',            'result/runs/q180s__q540val-300ep/agent_mod.pt')]

def run(ckpt, sampling):
    random.seed(1); torch.manual_seed(1)
    env = build.build_simulation(target_qty={m:540 for m in ('MODEL_A','MODEL_B','MODEL_C')},
                                 due_day={m:4 for m in ('MODEL_A','MODEL_B','MODEL_C')},
                                 env_cls=batch_log(base_cls))
    env.WorkEndTime, env.MaxEpisodeSec, env.TariffObs = 18.0*3600.0, 2592000, False
    env.reset()
    ag = build.build_agent(env, checkpoint=ckpt); ag.reset_buffer(); ag.train(sampling)
    if sampling: torch.manual_seed(9000)
    env.run(agent=ag, max_sec=2592000)
    ms = env.env.now; b,_ = tou(env, ms)
    w = b['normal']+b['peak']*(PEAK/NORMAL)+b['night']*(OFF/NORMAL)
    return ms/3600.0, w, all(env.Throughput[m] >= env.target_qty[m] for m in env.target_qty)

print("q540 · due4 · 18:00 · 재배분 없음(none) — 배포 방식만 다름")
for name, ck in CKPTS:
    if not os.path.exists(ck):
        print(f"  {name}: 체크포인트 없음"); continue
    for mode, s in (('argmax', False), ('샘플링', True)):
        t0=time.time(); h, w, met = run(ck, s)
        print(f"  {name:32s} {mode:6s}  makespan {h:7.2f}h ({h/24:.3f}d)  가중kWh {w:8.1f}  met={met}  ({time.time()-t0:.0f}s)", flush=True)
