# -*- coding: utf-8 -*-
"""[임시 실험] qty100: stock x1(baseline) vs x10 비교 그래프.
출력: result/rl_curve_stock10_qty100.png
"""
import json, os
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

R = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'result')
load = lambda f: [json.loads(x) for x in open(os.path.join(R, f), encoding='utf-8')]

b = load('rl_log_qty100.jsonl')          # x1 baseline (44ep)
e = load('rl_log_stock10_qty100.jsonl')  # x10 (10ep)
xb = [r['episode'] for r in b]
xe = [r['episode'] for r in e]

fig, ax = plt.subplots(2, 3, figsize=(17, 8))
fig.suptitle('qty100  stock x1 (baseline)  vs  stock x10   '
             '[TEMP ablation - AAS unchanged]', fontsize=13)


def pair(a, key, title, scale=1.0):
    a.plot(xb, [r[key] * scale for r in b], 'o-', ms=3, lw=1.2, color='C0', label='x1 baseline')
    a.plot(xe, [r[key] * scale for r in e], 's-', ms=4, lw=1.4, color='C3', label='x10 stock')
    a.set_title(title); a.set_xlabel('episode'); a.legend(fontsize=8)


pair(ax[0, 0], 'task/primary_metric', 'makespan (h)  *** KEY ***', 1 / 3600)
pair(ax[0, 1], 'task/throughput_ratio', 'throughput_ratio (1.0=all done)')
pair(ax[0, 2], 'task/energy_kwh', 'task/energy_kwh (active premium)')
pair(ax[1, 0], 'train/rollout_reward', 'rollout_reward (per ep)')
pair(ax[1, 1], 'eval/return_best_so_far', 'best_so_far')
pair(ax[1, 2], 'critic/explained_variance', 'critic/explained_variance')

# 핵심 수치 주석
mb = sum(r['task/primary_metric'] for r in b) / len(b) / 3600
me = sum(r['task/primary_metric'] for r in e) / len(e) / 3600
ax[0, 0].annotate(f'mean {mb:.1f}h -> {me:.1f}h  ({(me-mb)/mb*100:+.0f}%)\nthroughput unchanged (300/300)',
                  xy=(0.5, 0.5), xycoords='axes fraction', fontsize=10,
                  ha='center', color='C3',
                  bbox=dict(boxstyle='round', fc='white', ec='C3'))

fig.tight_layout(rect=[0, 0, 1, 0.95])
out = os.path.join(R, 'rl_curve_stock10_qty100.png')
fig.savefig(out, dpi=130)
print('saved', out, ' | x1 mean ms', round(mb, 2), 'h  x10 mean ms', round(me, 2), 'h')
