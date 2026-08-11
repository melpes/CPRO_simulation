# FIFO 기준 전 라인 반응 재측정 — 앞선 검증이 FwInput/Inspection/Aging 3개뿐이었다.
# 엑셀 1-1 최적해(F4-L1-Fo1-S1-I2, 9명 분산)도 함께.
import sys, os, json, time
PACKAGE = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
sys.path.insert(0, PACKAGE); sys.dont_write_bytecode = True
from fifo_sweep_comp2base import tou, batch_log, FILES
NORMAL, PEAK, OFF = 1833.0, 3398.0, 1190.0
import path_extractor, build, run_trained, torch, random
for f in FILES: path_extractor.load(os.path.join(PACKAGE,'aas_data',f))
base_cls = run_trained._schedule_env_cls()
SRC = 'WWM_SemiAssemblyLine'
L = {'F':'WWM_FwInputLine','L':'WWM_LensHolderLine','Fo':'WWM_FocusLine',
     'S':'WWM_SetAssemblyLine','I':'WWM_InspectionLine'}

def sw_cls(base, moves):
    mv = {L[k]: n for k, n in moves.items()}
    class _E(base):
        def reset(self):
            if not hasattr(self,'_w0'): self._w0={w:i['worker_count'] for w,i in self.workers.items()}
            for w,c in self._w0.items(): self.workers[w]['worker_count']=c
            super().reset(); self.sw_fired=None; self._src=0; self._done=False
            self.env.process(self._mon())
        def _run_job(self, ws, job, req):
            yield from super()._run_job(ws, job, req)
            if ws==SRC: self._src+=1
        def _mon(self):
            acc=0.0
            while not self._done:
                yield self.env.timeout(30.0)
                if not self._is_work_time(): continue
                idle=(self._src>0 and self.in_progress.get(SRC,0)==0 and not self._pending[SRC])
                acc=acc+30.0 if idle else 0.0
                if acc>=600.0: self._fire()
        def _fire(self):
            now=self.env.now
            for ws in [SRC,*mv]: self._flush_idle(ws, now)
            for ws,n in mv.items():
                self.workers[ws]['worker_count']+=n
                r=self.worker_resources[ws]
                r._capacity += n*self.workers[ws].get('UnitsPerWorker',1)
                r._trigger_put(None); self._wake_dispatcher(ws)
            m=sum(mv.values())
            self.workers[SRC]['worker_count']-=m
            self.worker_resources[SRC]._capacity -= m*self.workers[SRC].get('UnitsPerWorker',1)
            self._done=True; self.sw_fired=float(now)
    return _E

CASES = [('none', {}), ('F+6',{'F':6}), ('I+6',{'I':6}),
         ('L+6',{'L':6}), ('Fo+6',{'Fo':6}), ('S+6',{'S':6}),
         ('엑셀최적 F4-L1-Fo1-S1-I2', {'F':4,'L':1,'Fo':1,'S':1,'I':2}),
         ('F4-I2 (내 조합)', {'F':4,'I':2})]
print("FIFO(관측 미사용) · q540 · due5 · 18:00 — 라인별 반응")
print(f"{'조합':26s} {'총작업h':>9s} {'makespan':>9s} {'가중kWh':>9s} {'none대비':>9s}")
out={}
for name, mv in CASES:
    t0=time.time(); random.seed(1); torch.manual_seed(1)
    cls = batch_log(base_cls) if not mv else sw_cls(batch_log(base_cls), mv)
    env = build.build_simulation(target_qty={m:540 for m in ('MODEL_A','MODEL_B','MODEL_C')},
                                 due_day={m:5 for m in ('MODEL_A','MODEL_B','MODEL_C')}, env_cls=cls)
    env.WorkEndTime, env.MaxEpisodeSec, env.TariffObs = 18.0*3600.0, 2592000, False
    env.reset()
    env.run(agent=None, max_sec=2592000)
    ms=env.env.now; b,_=tou(env, ms)
    w=b['normal']+b['peak']*(PEAK/NORMAL)+b['night']*(OFF/NORMAL)
    from fifo_sweep_comp2base import worktime
    wh=worktime(env, ms)/3600.0
    out[name]={'work_h':wh,'makespan':ms/86400.0,'wkwh':w}
    d = (out['none']['work_h']-wh)/out['none']['work_h']*100 if 'none' in out else 0
    print(f"{name:26s} {wh:9.2f} {ms/86400:9.4f} {w:9.1f} {d:+8.2f}%  ({time.time()-t0:.0f}s)", flush=True)
    json.dump(out, open('exp_overtime/fifo_all_lines.json','w',encoding='utf-8'), ensure_ascii=False, indent=1)
print('done')
