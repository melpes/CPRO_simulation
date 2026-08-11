# 재배분 트리거 시점 스윕 — 비율이 아니라 '언제 옮기나'가 레버인가
#   trigger=0 은 사실상 초기 배치 변경(시작 직후 이동)
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
L = ['WWM_FwInputLine','WWM_LensHolderLine','WWM_FocusLine','WWM_SetAssemblyLine',
     'WWM_InspectionLine','WWM_AgingLine','WWM_PackagingLine','WWM_OqcLine']

def sw_cls(base, mv, trig):
    moves = {l: k for l, k in zip(L, mv) if k}
    class _E(base):
        def reset(self):
            super().reset(); self.sw_fired = None
            self.env.process(self._w())
        def _w(self):
            while True:
                yield self.env.timeout(30.0)
                if self.sw_fired is not None: return
                idle = self.env.now - self.last_active.get(SRC, 0.0)
                if self.in_progress.get(SRC,0)==0 and idle >= trig:
                    s = self.workers[SRC]
                    for t_, k in moves.items():
                        m = min(k, s['worker_count']-1)
                        if m>0: s['worker_count']-=m; self.workers[t_]['worker_count']+=m
                    self.sw_fired=float(self.env.now); return
    return _E

#          F  L Fo  S  I  A  P  O
CASES = [('없음',            None,               None),
         ('F6 · trig 0h',    [6,0,0,0,0,0,0,0],  0.0),
         ('F6 · trig 10분',  [6,0,0,0,0,0,0,0],  600.0),
         ('F6 · trig 1h',    [6,0,0,0,0,0,0,0],  3600.0),
         ('F6 · trig 3h',    [6,0,0,0,0,0,0,0],  10800.0),
         ('F9 · trig 0h',    [9,0,0,0,0,0,0,0],  0.0),
         ('F4I3P3 · trig 0h',[4,0,0,0,3,0,3,0],  0.0),
         ('F7L1Fo1I1 · 0h',  [7,1,1,0,1,0,0,0],  0.0)]

out=[]
print("q540 · due4 · 18:00 · 샘플링 — 트리거 시점 스윕")
print(f"{'조건':20s} {'makespan':>10s} {'가중kWh':>10s} {'재배분 발동':>11s} {'FwInput':>8s}")
for name, mv, trig in CASES:
    t0=time.time(); random.seed(1); torch.manual_seed(1)
    cls = batch_log(base_cls) if mv is None else sw_cls(batch_log(base_cls), mv, trig)
    env = build.build_simulation(target_qty={m:540 for m in ('MODEL_A','MODEL_B','MODEL_C')},
                                 due_day={m:4 for m in ('MODEL_A','MODEL_B','MODEL_C')}, env_cls=cls)
    env.WorkEndTime, env.MaxEpisodeSec, env.TariffObs = 18.0*3600.0, 2592000, False
    env.reset()
    ag = build.build_agent(env, checkpoint=CK); ag.reset_buffer(); ag.train(True)
    torch.manual_seed(9000); env.run(agent=ag, max_sec=2592000)
    h=env.env.now/3600.0; b,_=tou(env, env.env.now)
    w=b['normal']+b['peak']*(PEAK/NORMAL)+b['night']*(OFF/NORMAL)
    fired = getattr(env,'sw_fired',None)
    fw = env.workers['WWM_FwInputLine']['worker_count']
    out.append({'case':name,'makespan_h':h,'wkwh':w,
                'fired_h':(fired/3600.0 if fired else None),'fw':fw})
    print(f"{name:20s} {h:9.2f}h {w:10.1f} "
          f"{(f'{fired/3600:.2f}h' if fired else '-'):>11s} {fw:6d}명  ({time.time()-t0:.0f}s)", flush=True)
    json.dump(out, open('exp_overtime/realloc_trigger.json','w',encoding='utf-8'), ensure_ascii=False, indent=1)
ms=[r['makespan_h'] for r in out]
print(f"\n범위 {min(ms):.2f}~{max(ms):.2f}h  폭 {(max(ms)-min(ms))/min(ms)*100:.2f}%")
print("최선:", min(out,key=lambda r:r['makespan_h'])['case'])
