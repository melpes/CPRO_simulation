# 간트용 events 추출 — 같은 정책, argmax vs 샘플링 (q540·due4·18:00·재배분 없음)
import sys, os, json
PACKAGE = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
sys.path.insert(0, PACKAGE); sys.dont_write_bytecode = True
from fifo_sweep_comp2base import batch_log, FILES
import path_extractor, build, run_trained, torch, random
for f in FILES: path_extractor.load(os.path.join(PACKAGE,'aas_data',f))
base_cls = run_trained._schedule_env_cls()
CK = 'result/runs/q180s__compbase-300ep/agent_last.pt'
os.makedirs('exp_overtime/gantt', exist_ok=True)

for mode, samp in (('argmax', False), ('sampling', True)):
    random.seed(1); torch.manual_seed(1)
    env = build.build_simulation(target_qty={m:540 for m in ('MODEL_A','MODEL_B','MODEL_C')},
                                 due_day={m:4 for m in ('MODEL_A','MODEL_B','MODEL_C')},
                                 env_cls=batch_log(base_cls))
    env.WorkEndTime, env.MaxEpisodeSec, env.TariffObs = 18.0*3600.0, 2592000, False
    env.reset()
    ag = build.build_agent(env, checkpoint=CK); ag.reset_buffer(); ag.train(samp)
    if samp: torch.manual_seed(9000)
    env.run(agent=ag, max_sec=2592000)
    p = f'exp_overtime/gantt/events_{mode}.jsonl'
    with open(p, 'w', encoding='utf-8') as fp:
        for ev in env.events:
            fp.write(json.dumps(ev, ensure_ascii=False) + '\n')
    meta = {'mode': mode, 'makespan_sec': env.env.now,
            'workers': {w: i['worker_count'] for w, i in env.workers.items()},
            'work_start': env.WorkStartTime, 'work_end': env.WorkEndTime,
            'break': [env.break_start_sec, env.break_end_sec], 'events': len(env.events)}
    json.dump(meta, open(f'exp_overtime/gantt/meta_{mode}.json','w',encoding='utf-8'),
              ensure_ascii=False, indent=1)
    print(f"{mode}: makespan {env.env.now/3600:.2f}h, events {len(env.events):,}", flush=True)
