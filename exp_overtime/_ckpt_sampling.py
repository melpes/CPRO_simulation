# 기존 체크포인트를 argmax 로 쓸 때 vs 샘플링으로 쓸 때 (정본 코드·정적 3피처)
import sys, os, json, statistics as st
PACKAGE = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
sys.path.insert(0, PACKAGE); sys.dont_write_bytecode = True
from fifo_sweep_comp2base import tou, worktime, batch_log, FILES
NORMAL, PEAK, OFF = 1833.0, 3398.0, 1190.0
import path_extractor, build, run_trained, torch, random
for f in FILES: path_extractor.load(os.path.join(PACKAGE,'aas_data',f))
base_cls = run_trained._schedule_env_cls()
CKPT = 'result/runs/q180s__q540val-300ep/agent_mod.pt'

def run(qty, end_h, sampling, sseed=0, ckpt=CKPT):
    random.seed(1); torch.manual_seed(1)
    env = build.build_simulation(target_qty={m:qty for m in ('MODEL_A','MODEL_B','MODEL_C')},
                                 due_day={m:(3 if qty<=180 else 5) for m in ('MODEL_A','MODEL_B','MODEL_C')},
                                 env_cls=batch_log(base_cls))
    env.WorkEndTime=end_h*3600.0; env.MaxEpisodeSec=2592000; env.TariffObs=False
    env.reset()
    ag = build.build_agent(env, checkpoint=ckpt); ag.reset_buffer(); ag.train(sampling)
    if sampling: torch.manual_seed(9000+sseed)
    env.run(agent=ag, max_sec=2592000)
    ms = env.env.now
    b,_ = tou(env, ms)
    w = b['normal']+b['peak']*(PEAK/NORMAL)+b['night']*(OFF/NORMAL)
    return ms/86400.0, worktime(env,ms)/3600.0, w

print("【q180 · 20:00 · q180s-300ep 체크포인트】")
a = run(180, 20.0, False)
print(f"  argmax        makespan={a[0]:.4f}  생산시간={a[1]:.2f}h  가중kWh={a[2]:.1f}")
S=[run(180,20.0,True,s) for s in range(1,9)]
ms=[x[0] for x in S]
for i,x in enumerate(S,1):
    print(f"  샘플링 seed{i}  makespan={x[0]:.4f}  생산시간={x[1]:.2f}h  가중kWh={x[2]:.1f}")
print(f"  → 샘플링 min {min(ms):.4f} / med {st.median(ms):.4f} / max {max(ms):.4f}")
print(f"  → 기준: 규칙최선 1.6295 · 랜덤argmax중앙 1.6700 · FIFO 1.7493")
json.dump({'argmax':a,'sampling':S}, open('exp_overtime/ckpt_sampling_q180.json','w',
          encoding='utf-8'), ensure_ascii=False, indent=1)
