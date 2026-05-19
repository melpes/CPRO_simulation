"""짧은 시뮬 (24h) 으로 stuck 진단. menv.run() 의 setup 만 모방."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

from path_extractor import load_aas
import cpro_simulation_ver3 as v
from cpro_aas_validator import validate_aas

aas_models = {m: load_aas(m, f'{m}.json') for m in ['MODEL_A','MODEL_B','MODEL_C']}
aas_models['COMMON'] = load_aas('COMMON', 'WorkstationWorkerMatchingDataAAS.json')
validate_aas(aas_models)
sd = v.FallbackDataLoader()
data = v.CombinedDataLoader(sd, aas_models)
v._apply_schedule(data.schedule)

order = {'MODEL_A': 5, 'MODEL_B': 5, 'MODEL_C': 5}
menv = v.ManufacturingEnv(data, order)
menv._init_sim()
menv.agent = None

# menv.run() setup 모방
env = menv.env
env.process(v.run_rma(env, menv.rma, menv.wres, menv.wh, menv.energy,
                      menv.idle, menv.wip, menv.stats, menv.data,
                      progress=menv.progress, plogger=menv.plogger))
env.process(menv._event_smt_breakdown(env))
env.process(menv._event_worker_absent(env))
env.process(menv._event_replenishment(env))
env.process(menv.wh.snapshot_loop(env, interval=3600))
env.process(menv.wip.snapshot_loop(env, interval=3600))
menv._smt_schedule()
for m in menv.order:
    for uid in range(menv.order[m]):
        env.process(v.produce_unit(env, m, uid, menv.data, menv.graphs[m],
                                    menv.wres, menv.wh, menv.rma, menv.energy,
                                    menv.idle, menv.wip, menv.stats,
                                    menv.progress, menv=menv, plogger=menv.plogger))

env.run(until=30 * 24 * 3600)  # 30일

print('\n=== unit_completions (path 별) ===')
from collections import Counter
path_count = Counter()
for k, info in menv.wh.unit_completions.items():
    path_count[info.get('path')] += 1
for p, n in path_count.most_common():
    print(f'  {p}: {n}')

print('\n=== 미완성 unit 의 BT5_100 / NVD_110 done 상태 (done_set 직접 못 봄, kg_incomplete_log 확인) ===')
for entry in menv.wh.kg_incomplete_log[:5]:
    print(f'  {entry["model_id"]} #{entry["unit_id"]} t={entry["time_h"]:.1f}h missing={entry["missing_pcs"][:8]}')

print(f'\n=== sim time: {env.now/3600:.1f}h ===')

print('\n=== stats ===')
for k, val in sorted(menv.stats.items()):
    if val:
        print(f'  {k}: {val}')

print('\n=== unit_states ===')
from collections import Counter
state_count = Counter()
sample_stuck = {}
for (mid, uid), st in menv.unit_states.items():
    key = (mid, st.get('state'))
    state_count[key] += 1
    if key not in sample_stuck:
        sample_stuck[key] = (uid, st)
for k, n in state_count.most_common():
    print(f'  {k}: {n}')
print('\n=== 각 상태 첫 sample ===')
for k, (uid, st) in sample_stuck.items():
    print(f'  {k} #{uid}: pc={st.get("pc")} done={st.get("done_n")}/{st.get("total_n")} ready={st.get("ready")}')

print('\n=== PCB stock ===')
for code in ['03203204','03203145','03203315','03903424','03902715','PCB_03203204',
             'PCB_03903424','PCB_03902715']:
    if code in menv.wh.stock:
        print(f'  {code}: {menv.wh.stock[code]}')

print('\n=== SMT 라인 ===')
for sid, line in menv.smt_lines.items():
    print(f'  {sid}: assigned_model={line.assigned_model}, '
          f'mag_buf={dict(line.mag_buf)}, stage_active={list(line.stage_active.keys())}')

print('\n=== smt_per_model ===')
for k, n in sorted(menv.wh.smt_per_model.items()):
    print(f'  {k}: {n}')

print('\n=== outsource_pool ===')
if hasattr(menv, 'outsource_pool') and menv.outsource_pool:
    p = menv.outsource_pool
    print(f'  truck:{len(p.truck)}, in_transit:{len(p.in_transit)}, dispatched:{p.dispatched_count}')

print('\n=== unit 별 시작-종료 시간 ===')
for (mid, uid), info in menv.wh.unit_completions.items():
    print(f'  {mid} #{uid}: end={info["end_time"]/3600:.2f}h, path={info["path"]}, done={info.get("done_n")}/{info.get("total_n")}')

print('\n=== 워커 그룹별 누적 idle 시간 / capacity ===')
for wgrp, cap in menv.data.workers.items():
    idle_sec = menv.idle.total_idle.get(wgrp, 0.0)
    busy_max = cap * env.now
    if busy_max > 0:
        util = 100 * (1 - idle_sec / busy_max)
        print(f'  {wgrp:22s} cap={cap:2d} idle={idle_sec/3600:6.1f}h  util={util:5.1f}%')
