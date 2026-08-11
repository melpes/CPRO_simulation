# 1-1 재배분 비율 재탐색 — 샘플링 배포 기준. 기존 후보는 argmax 기준으로 선정된 것이라
# 병목(FwInput 82% 포화 / Inspection 2위)에 무게를 실은 조합까지 넓혀 본다.
import sys, os, json, time
PACKAGE = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
sys.path.insert(0, PACKAGE); sys.dont_write_bytecode = True
from fifo_sweep_comp2base import tou, batch_log, FILES
NORMAL, PEAK, OFF = 1833.0, 3398.0, 1190.0
import path_extractor, build, run_trained, torch, random
for f in FILES: path_extractor.load(os.path.join(PACKAGE,'aas_data',f))
base_cls = run_trained._schedule_env_cls()
CK = 'result/runs/q180s__compbase-300ep/agent_last.pt'
SRC = 'WWM_SemiAssemblyLine'
L = ['WWM_FwInputLine','WWM_LensHolderLine','WWM_FocusLine','WWM_SetAssemblyLine','WWM_InspectionLine']

GRID = [('none',        None),
        ('4-1-1-1-2*',  [4,1,1,1,2]),   # 기존 1위(argmax)
        ('5-1-1-1-2',   [5,1,1,1,2]),   # 샘플링 1위(앞선 확인)
        ('6-1-1-1-1',   [6,1,1,1,1]),
        ('7-1-1-0-1',   [7,1,1,0,1]),
        ('8-1-0-0-1',   [8,1,0,0,1]),
        ('10-0-0-0-0',  [10,0,0,0,0]),  # FwInput 몰빵
        ('8-0-0-0-2',   [8,0,0,0,2]),
        ('6-0-0-0-4',   [6,0,0,0,4]),
        ('5-0-0-0-5',   [5,0,0,0,5]),
        ('4-0-0-0-6',   [4,0,0,0,6]),
        ('0-0-0-0-10',  [0,0,0,0,10])]  # Inspection 몰빵

def sw_cls(base, mv):
    if not mv: return base
    moves = {l: k for l, k in zip(L, mv) if k}
    TRIG, TICK = 600.0, 30.0
    class _E(base):
        def reset(self):
            super().reset(); self.sw_fired = None
            self.env.process(self._w())
        def _w(self):
            while True:
                yield self.env.timeout(TICK)
                if self.sw_fired is not None: return
                if self.in_progress.get(SRC,0)==0 and (self.env.now-self.last_active.get(SRC,0.0))>=TRIG:
                    s = self.workers[SRC]
                    for t_, k in moves.items():
                        m = min(k, s['worker_count']-1)
                        if m>0: s['worker_count']-=m; self.workers[t_]['worker_count']+=m
                    self.sw_fired=float(self.env.now); return
    return _E

out=[]
print("q540 · due4 · 18:00 · 샘플링 배포 · 정책 q180s__compbase-300ep")
print(f"{'비율(F-L-Fo-S-I)':18s} {'makespan':>10s} {'가중kWh':>10s} {'FwInput최종':>11s}")
for name, mv in GRID:
    t0=time.time(); random.seed(1); torch.manual_seed(1)
    env = build.build_simulation(target_qty={m:540 for m in ('MODEL_A','MODEL_B','MODEL_C')},
                                 due_day={m:4 for m in ('MODEL_A','MODEL_B','MODEL_C')},
                                 env_cls=sw_cls(batch_log(base_cls), mv))
    env.WorkEndTime, env.MaxEpisodeSec, env.TariffObs = 18.0*3600.0, 2592000, False
    env.reset()
    ag = build.build_agent(env, checkpoint=CK); ag.reset_buffer(); ag.train(True)
    torch.manual_seed(9000); env.run(agent=ag, max_sec=2592000)
    h = env.env.now/3600.0; b,_ = tou(env, env.env.now)
    w = b['normal']+b['peak']*(PEAK/NORMAL)+b['night']*(OFF/NORMAL)
    fw = env.workers['WWM_FwInputLine']['worker_count']
    met = all(env.Throughput[m] >= env.target_qty[m] for m in env.target_qty)
    out.append({'ratio':name,'makespan_h':h,'wkwh':w,'fw_final':fw,'met':met})
    print(f"{name:18s} {h:9.2f}h {w:10.1f} {fw:9d}명  met={met} ({time.time()-t0:.0f}s)", flush=True)
    json.dump(out, open('exp_overtime/realloc_grid.json','w',encoding='utf-8'), ensure_ascii=False, indent=1)
best = min(out, key=lambda r: r['makespan_h'])
print(f"\n최선: {best['ratio']}  {best['makespan_h']:.2f}h")
