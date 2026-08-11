# 노이즈 바닥 측정 — 샘플링 시드 변동 vs 재배분 조합 변동, 어느 쪽이 큰가
#   조합 간 폭이 0.31% 였는데 시드 변동이 그보다 크면 지금까지의 순위는 무의미하다.
import sys, os, json, time, statistics as st
PACKAGE = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
sys.path.insert(0, PACKAGE); sys.dont_write_bytecode = True
from fifo_sweep_comp2base import tou, batch_log, FILES
NORMAL, PEAK, OFF = 1833.0, 3398.0, 1190.0
import path_extractor, build, run_trained, torch, random
for f in FILES: path_extractor.load(os.path.join(PACKAGE,'aas_data',f))
base_cls = run_trained._schedule_env_cls()
CK = 'result/runs/q180s__compbase-300ep/agent_last.pt'
SRC = 'WWM_SemiAssemblyLine'
L = ['WWM_FwInputLine','WWM_LensHolderLine','WWM_FocusLine','WWM_SetAssemblyLine',
     'WWM_InspectionLine','WWM_AgingLine','WWM_PackagingLine','WWM_OqcLine']

def sw_cls(base, mv):
    moves = {l:k for l,k in zip(L,mv) if k}
    class _E(base):
        def reset(self):
            super().reset(); self.sw_fired=None; self.env.process(self._w())
        def _w(self):
            while True:
                yield self.env.timeout(30.0)
                if self.sw_fired is not None: return
                if self.in_progress.get(SRC,0)==0 and (self.env.now-self.last_active.get(SRC,0.0))>=600.0:
                    s=self.workers[SRC]
                    for t_,k in moves.items():
                        m=min(k, s['worker_count']-1)
                        if m>0: s['worker_count']-=m; self.workers[t_]['worker_count']+=m
                    self.sw_fired=float(self.env.now); return
    return _E

#          F  L Fo  S  I  A  P  O
CASES = [('none',      None),
         ('F4I3P3',    [4,0,0,0,3,0,3,0]),   # 23조합 중 최선(88.81)
         ('F6',        [6,0,0,0,0,0,0,0])]   # 최악권(89.05)
SEEDS = [9000, 9001, 9002, 9003, 9004]

def run(mv, sseed):
    random.seed(1); torch.manual_seed(1)
    cls = batch_log(base_cls) if mv is None else sw_cls(batch_log(base_cls), mv)
    env = build.build_simulation(target_qty={m:540 for m in ('MODEL_A','MODEL_B','MODEL_C')},
                                 due_day={m:4 for m in ('MODEL_A','MODEL_B','MODEL_C')}, env_cls=cls)
    env.WorkEndTime, env.MaxEpisodeSec, env.TariffObs = 18.0*3600.0, 2592000, False
    env.reset()
    ag = build.build_agent(env, checkpoint=CK); ag.reset_buffer(); ag.train(True)
    torch.manual_seed(sseed); env.run(agent=ag, max_sec=2592000)
    h=env.env.now/3600.0; b,_=tou(env, env.env.now)
    return h, b['normal']+b['peak']*(PEAK/NORMAL)+b['night']*(OFF/NORMAL)

out={}
print("q540 · due4 · 18:00 — 샘플링 시드 5개 × 재배분 3조합")
for name, mv in CASES:
    hs=[]; ws=[]
    for s in SEEDS:
        t0=time.time(); h,w = run(mv, s); hs.append(h); ws.append(w)
        print(f"  {name:8s} seed{s} {h:8.2f}h {w:9.1f}  ({time.time()-t0:.0f}s)", flush=True)
    out[name]={'makespan':hs,'wkwh':ws}
    print(f"  → {name}: {min(hs):.2f}~{max(hs):.2f}h  중앙 {st.median(hs):.2f}  "
          f"std {st.pstdev(hs):.3f}  폭 {(max(hs)-min(hs))/min(hs)*100:.2f}%", flush=True)
    json.dump(out, open('exp_overtime/seed_variance_realloc.json','w',encoding='utf-8'),
              ensure_ascii=False, indent=1)
allh=[h for v in out.values() for h in v['makespan']]
within=[ (max(v['makespan'])-min(v['makespan']))/min(v['makespan'])*100 for v in out.values() ]
meds=[st.median(v['makespan']) for v in out.values()]
print(f"\n시드 내 변동(조합별 폭): {['%.2f%%'%x for x in within]}")
print(f"조합 간 변동(중앙값 폭): {(max(meds)-min(meds))/min(meds)*100:.2f}%")
print(f"→ {'시드 노이즈가 조합 차이보다 크다 (순위 무의미)' if max(within) > (max(meds)-min(meds))/min(meds)*100 else '조합 차이가 노이즈보다 크다'}")
