import json
import os

import torch

PSM_REALLOC_FILE = 'ProvisionOfSimulationModel_realloc.json'
TGT_FEAT_DIM = 5


def load_params(aas_dir, overrides=None):
    d = json.load(open(os.path.join(aas_dir, PSM_REALLOC_FILE), encoding='utf-8'))

    def find(o, ids):
        if isinstance(o, dict):
            if o.get('idShort') == ids and o.get('modelType') != 'ConceptDescription':
                yield o
            for v in o.values():
                if isinstance(v, (dict, list)):
                    yield from find(v, ids)
        elif isinstance(o, list):
            for v in o:
                yield from find(v, ids)

    def prop(ids):
        return next(find(d, ids))['value']

    scope_smc = next(find(d, 'ReallocationScope'))
    src_list = scope_smc['value'][0]
    targets = [ref['value']['keys'][0]['value'].rstrip('/').rsplit('/', 3)[-3]
               for ref in src_list['value']]
    params = {
        'src':          src_list['idShort'],
        'targets':      targets,
        'threshold':    float(prop('ReallocationIdleThresholdSec')),
        'move_unit':    int(prop('WorkerMoveUnit')),
        'min_resident': int(next(find(d, 'MinResidentWorkers'))['value']),
        'tick':         30.0,
        'entropy_coef': 0.05,
        'mode':         'categorical',
        'dirichlet_c':  10.0,
        'ratio_batch':  0,
        'c_final':      0.0,
        'c_switch_ep':  0,
    }
    for k, v in (overrides or {}).items():
        if k in params and v is not None:
            params[k] = type(params[k])(v)
    return params


def wrap_env_cls(base_cls, rp):
    src, targets = rp['src'], rp['targets']
    thr, tick = rp['threshold'], rp['tick']
    unit, minres = rp['move_unit'], rp['min_resident']
    ratio_mode = rp.get('mode') == 'ratio'

    class ReallocEnv(base_cls):
        def reset(self):
            super().reset()
            self._slots = []
            self.realloc_moves = []
            self.realloc_ratio = None
            self._ratio_p = None
            self._ratio_sent = None
            agent = getattr(self, '_rl_agent', None)
            if agent is not None and (hasattr(agent, 'choose_realloc') or hasattr(agent, 'choose_ratio')):
                self.env.process(self._realloc_monitor(agent))

        def run(self, agent=None, max_sec=None):
            self._rl_agent = agent
            return super().run(agent=agent, max_sec=max_sec)

        @property
        def StateDim(self):
            return super().StateDim + len(self.workers)

        def StateVector(self):
            base = super().StateVector()
            w0 = getattr(self, '_workers0', None) or {ws: i['worker_count']
                                                      for ws, i in self.workers.items()}
            delta = [(self.workers[ws]['worker_count'] - w0[ws]) / w0[ws] for ws in self.workers]
            return torch.cat([base, torch.tensor(delta, dtype=torch.float32)])

        def _realloc_monitor(self, agent):
            while True:
                yield self.env.timeout(tick)
                if not self._is_work_time():
                    continue
                idle_now = max(0, self.workers[src]['worker_count'] - self.in_progress.get(src, 0))
                n = len(self._slots)
                if idle_now > n:
                    self._slots.extend([0.0] * (idle_now - n))
                elif idle_now < n:
                    del self._slots[idle_now:]
                self._slots = [a + tick for a in self._slots]
                while (self._slots and self._slots[0] >= thr
                       and self.workers[src]['worker_count'] - unit >= minres):
                    if ratio_mode:
                        if self._ratio_p is None:
                            self._ratio_p = agent.choose_ratio(self, src, targets)
                            self._ratio_sent = [0] * len(targets)
                            self.realloc_ratio = list(self._ratio_p)
                        k = sum(self._ratio_sent)
                        j = max(range(len(targets)),
                                key=lambda i: self._ratio_p[i] * (k + 1) - self._ratio_sent[i])
                        self._ratio_sent[j] += 1
                        tgt = targets[j]
                    else:
                        tgt = agent.choose_realloc(self, src, targets)
                    del self._slots[0]
                    self._move_worker(src, tgt)

        def _move_worker(self, src_ws, tgt_ws):
            now = self.env.now
            for ws in (src_ws, tgt_ws):
                self._flush_idle(ws, now)
            self.workers[tgt_ws]['worker_count'] += unit
            res = self.worker_resources[tgt_ws]
            res._capacity += unit * self.workers[tgt_ws].get('UnitsPerWorker', 1)
            res._trigger_put(None)
            self._wake_dispatcher(tgt_ws)
            self.workers[src_ws]['worker_count'] -= unit
            self.worker_resources[src_ws]._capacity -= unit * self.workers[src_ws].get('UnitsPerWorker', 1)
            self.realloc_moves.append({'t': float(now), 'tgt': tgt_ws})
            if hasattr(self, 'events'):
                self.events.append({'type': 'realloc', 'line': src_ws, 't0': float(now),
                                    'src': src_ws, 'moves': {tgt_ws: unit}})

    ReallocEnv.realloc_params = dict(rp)
    return ReallocEnv


def tgt_feats(env, ws, pending_total=None):
    env._flush_idle(ws, env.env.now)
    info = env.workers[ws]
    wc = max(1, info['worker_count'])
    w0 = getattr(env, '_workers0', {}).get(ws, info['worker_count'])
    elapsed = max(1.0, env._work_elapsed(env.env.now))
    if pending_total is None:
        backlog = len(env._pending[ws]) / max(1, len(info['ProcessCode']))
    else:
        backlog = len(env._pending[ws]) / max(1, pending_total)
    return [
        env.in_progress.get(ws, 0) / wc,
        (info['worker_count'] - w0) / w0,
        backlog,
        1.0 - min(1.0, env.line_idle_time[ws] / (wc * elapsed)),
        env._cont_idle[ws] / max(1.0, float(env.IdleWorkerThreshold)),
    ]


def _make_agent_cls():
    import simulation as sim
    base_agent = getattr(sim, '_PPOAgentOrig', sim.PPOAgent)

    class ReallocPPOAgent(base_agent):
        ReallocEntropyCoef = 0.05
        DirichletC = 10.0
        RatioBatchK = 0
        CFinal = 0.0
        CSwitchEp = 0
        CurrentEpisode = 0

        def __init__(self, **kw):
            super().__init__(**kw)
            emb_dim = int(next(node['Arguments']['out_channels']
                               for node in reversed(self.GNNEncoder.spec)
                               if 'out_channels' in node.get('Arguments', {})))
            glob = emb_dim + self.StateDim
            self.ReallocScorer = torch.nn.Sequential(
                torch.nn.Linear(TGT_FEAT_DIM + glob, 64), torch.nn.ReLU(),
                torch.nn.Linear(64, 64), torch.nn.ReLU(),
                torch.nn.Linear(64, 1))
            lr = self.optimizer.param_groups[0]['lr']
            self.optimizer = torch.optim.Adam(self.parameters(), lr=lr)
            if self.RatioBatchK:
                from collections import deque
                self._ratio_hist = deque(maxlen=self.RatioBatchK)
                self._ratio_opt = torch.optim.Adam(self.ReallocScorer.parameters(), lr=lr)

        def _dirichlet_c(self):
            if self.CFinal and self.CSwitchEp and self.CurrentEpisode >= self.CSwitchEp:
                return self.CFinal
            return self.DirichletC

        def _realloc_logits(self, tgt, glob):
            k = tgt.size(0)
            return self.ReallocScorer(
                torch.cat([tgt, glob.unsqueeze(0).expand(k, -1)], dim=-1)).squeeze(-1)

        @torch.no_grad()
        def choose_realloc(self, env, src, targets):
            kg = env.KnowledgeGraph
            emb = self.GNNEncoder(NodeFeatures=sim.obs_node_features(kg),
                                  GraphTopology=sim.obs_graph_topology(kg))
            pooled = emb.mean(dim=0)
            state = env.StateVector()
            glob = torch.cat([pooled, state])
            tgt = torch.tensor([tgt_feats(env, ws) for ws in targets], dtype=torch.float32)
            dist = torch.distributions.Categorical(logits=self._realloc_logits(tgt, glob))
            idx = dist.sample() if self.training else dist.probs.argmax()
            value = self.Critic(PooledNodeEmbedding=pooled.unsqueeze(0), StateVector=state).squeeze()
            self.buf.append({'head': 'realloc', 'tgt': tgt,
                             'idx': int(idx.item()), 'logp': dist.log_prob(idx),
                             'value': value, 'state': state, 'phi': float(env.potential())})
            return targets[int(idx.item())]

        def _ratio_dist(self, tgt, glob, c=None):
            m = torch.softmax(self._realloc_logits(tgt, glob), dim=0)
            alpha = torch.clamp((c or self._dirichlet_c()) * m, min=0.05)
            return torch.distributions.Dirichlet(alpha), m

        @torch.no_grad()
        def choose_ratio(self, env, src, targets):
            kg = env.KnowledgeGraph
            emb = self.GNNEncoder(NodeFeatures=sim.obs_node_features(kg),
                                  GraphTopology=sim.obs_graph_topology(kg))
            pooled = emb.mean(dim=0)
            state = env.StateVector()
            glob = torch.cat([pooled, state])
            pend_total = sum(len(env._pending[ws]) for ws in targets)
            tgt = torch.tensor([tgt_feats(env, ws, pending_total=pend_total) for ws in targets],
                               dtype=torch.float32)
            c = self._dirichlet_c()
            dist, m = self._ratio_dist(tgt, glob, c=c)
            p = dist.sample() if self.training else m
            value = self.Critic(PooledNodeEmbedding=pooled.unsqueeze(0), StateVector=state).squeeze()
            self.buf.append({'head': 'ratio', 'tgt': tgt, 'p': p, 'c': c,
                             'logp': dist.log_prob(p),
                             'value': value, 'state': state, 'phi': float(env.potential())})
            return [float(v) for v in p]

        def learn(self, episode_return, KnowledgeGraph):
            if not self.buf:
                return None
            n        = len(self.buf)
            values   = torch.stack([b['value'] for b in self.buf])
            old_logp = torch.stack([b['logp']  for b in self.buf])
            phi      = [b['phi'] for b in self.buf]

            rewards = torch.tensor(
                [(phi[i + 1] if i < n - 1 else float(episode_return)) - phi[i]
                 for i in range(n)], dtype=torch.float32)

            advantages = torch.zeros(n)
            gae = 0.0
            for t in reversed(range(n)):
                v_next = values[t + 1] if t < n - 1 else 0.0
                delta  = rewards[t] + self.Gamma * v_next - values[t]
                gae    = delta + self.Gamma * self.GaeLambda * gae
                advantages[t] = gae
            returns = advantages + values
            for i, b in enumerate(self.buf):
                if b.get('head') == 'ratio':
                    returns[i] = float(episode_return) - phi[i]
                    advantages[i] = returns[i] - values[i]
            adv     = (advantages - advantages.mean()) / (advantages.std() + 1e-8)
            grad_norm = 0.0
            for _ in range(self.UpdateEpochs):
                node_list      = list(KnowledgeGraph.nodes.keys())
                node_features  = sim.obs_node_features(KnowledgeGraph)
                graph_topology = sim.obs_graph_topology(KnowledgeGraph)
                perm = torch.randperm(n).tolist()
                for s in range(0, n, self.BatchSize):
                    mb = perm[s:s + self.BatchSize]
                    embeddings = self.GNNEncoder(NodeFeatures=node_features, GraphTopology=graph_topology)
                    pooled_all = embeddings.mean(dim=0)
                    new_logp, entropy, value_preds, ecoef = [], [], [], []
                    for i in mb:
                        b = self.buf[i]
                        if b.get('head') == 'ratio':
                            glob = torch.cat([pooled_all, b['state']])
                            dist, _ = self._ratio_dist(b['tgt'], glob, c=b.get('c'))
                            new_logp.append(dist.log_prob(b['p']))
                            value_preds.append(self.Critic(
                                PooledNodeEmbedding=pooled_all.unsqueeze(0),
                                StateVector=b['state']).squeeze())
                            ecoef.append(0.0)
                        elif b.get('head') == 'realloc':
                            glob = torch.cat([pooled_all, b['state']])
                            dist = torch.distributions.Categorical(
                                logits=self._realloc_logits(b['tgt'], glob))
                            new_logp.append(dist.log_prob(torch.tensor(b['idx'])))
                            value_preds.append(self.Critic(
                                PooledNodeEmbedding=pooled_all.unsqueeze(0),
                                StateVector=b['state']).squeeze())
                            ecoef.append(self.ReallocEntropyCoef)
                        else:
                            ready_emb = torch.stack([embeddings[node_list.index(pc)] for pc in b['ready']])
                            dist = torch.distributions.Categorical(
                                self.Actor(ReadyNodeEmbeddings=ready_emb, StateVector=b['state']))
                            new_logp.append(dist.log_prob(torch.tensor(b['idx'])))
                            value_preds.append(self.Critic(
                                PooledNodeEmbedding=ready_emb.mean(dim=0, keepdim=True),
                                StateVector=b['state']).squeeze())
                            ecoef.append(self.EntropyCoef)
                        entropy.append(dist.entropy())
                    new_logp    = torch.stack(new_logp)
                    entropy     = torch.stack(entropy)
                    value_preds = torch.stack(value_preds)
                    mb_adv      = adv[mb]
                    mb_oldlogp  = old_logp[mb]
                    mb_returns  = returns[mb]
                    ratio       = torch.exp(new_logp - mb_oldlogp)
                    actor_loss  = -torch.min(
                                      ratio * mb_adv,
                                      torch.clamp(ratio, 1 - self.ClipEpsilon, 1 + self.ClipEpsilon) * mb_adv
                                  ).mean()
                    critic_loss = torch.nn.functional.mse_loss(value_preds, mb_returns)
                    loss        = (actor_loss + self.ValueLossCoef * critic_loss
                                   - (torch.tensor(ecoef) * entropy).mean())
                    self.optimizer.zero_grad()
                    loss.backward()
                    grad_norm = float(torch.nn.utils.clip_grad_norm_(self.parameters(), 0.5))
                    self.optimizer.step()

            if self.RatioBatchK:
                for b in self.buf:
                    if b.get('head') == 'ratio':
                        self._ratio_hist.append({
                            'tgt': b['tgt'], 'p': b['p'].detach(), 'c': b.get('c'),
                            'logp': float(b['logp']), 'state': b['state'],
                            'ret': float(episode_return) - b['phi'],
                            'val': float(b['value'])})
                if self._ratio_hist:
                    ents = list(self._ratio_hist)
                    adv_r = torch.tensor([e['ret'] - e['val'] for e in ents])
                    if len(ents) > 1:
                        adv_r = (adv_r - adv_r.mean()) / (adv_r.std() + 1e-8)
                    with torch.no_grad():
                        emb = self.GNNEncoder(NodeFeatures=node_features, GraphTopology=graph_topology)
                        pooled_fix = emb.mean(dim=0)
                    for _ in range(self.UpdateEpochs):
                        new_lp = torch.stack([
                            self._ratio_dist(e['tgt'], torch.cat([pooled_fix, e['state']]),
                                             c=e['c'])[0].log_prob(e['p'])
                            for e in ents])
                        old_lp = torch.tensor([e['logp'] for e in ents])
                        rt = torch.exp(new_lp - old_lp)
                        loss_r = -torch.min(
                            rt * adv_r,
                            torch.clamp(rt, 1 - self.ClipEpsilon, 1 + self.ClipEpsilon) * adv_r).mean()
                        self._ratio_opt.zero_grad()
                        loss_r.backward()
                        torch.nn.utils.clip_grad_norm_(self.ReallocScorer.parameters(), 0.5)
                        self._ratio_opt.step()

            with torch.no_grad():
                resid_var  = float((mb_returns - value_preds).var(unbiased=False))
                ret_var    = float(mb_returns.var(unbiased=False))
                clip_frac  = float(((ratio - 1.0).abs() > self.ClipEpsilon).float().mean())
                approx_kl  = float((mb_oldlogp - new_logp).mean())
                re_idx = [i for i, b in enumerate(self.buf) if b.get('head') in ('realloc', 'ratio')]
                re_ent = None
                if re_idx:
                    embeddings = self.GNNEncoder(NodeFeatures=node_features, GraphTopology=graph_topology)
                    pooled_all = embeddings.mean(dim=0)
                    ents = []
                    for i in re_idx:
                        b = self.buf[i]
                        glob = torch.cat([pooled_all, b['state']])
                        if b.get('head') == 'ratio':
                            dist, _ = self._ratio_dist(b['tgt'], glob)
                        else:
                            dist = torch.distributions.Categorical(
                                logits=self._realloc_logits(b['tgt'], glob))
                        ents.append(float(dist.entropy()))
                    re_ent = sum(ents) / len(ents)
                return {
                    'critic/explained_variance': (float('nan') if ret_var < 1e-9
                                                  else 1.0 - resid_var / ret_var),
                    'critic/value_loss'        : float(critic_loss),
                    'critic/v_mean'            : float(value_preds.mean()),
                    'critic/v_max'             : float(value_preds.max()),
                    'critic/returns_var'       : ret_var,
                    'stability/approx_kl'      : approx_kl,
                    'stability/clip_fraction'  : clip_frac,
                    'stability/grad_norm'      : grad_norm,
                    'stability/learning_rate'  : float(self.optimizer.param_groups[0]['lr']),
                    'exploration/entropy'      : float(entropy.mean()),
                    'actor/loss'               : float(actor_loss),
                    'realloc/decisions'        : len(re_idx),
                    'realloc/entropy'          : re_ent,
                }

    return ReallocPPOAgent


def install(rp):
    import simulation as sim
    if not hasattr(sim, '_PPOAgentOrig'):
        sim._PPOAgentOrig = sim.PPOAgent
    cls = _make_agent_cls()
    cls.ReallocEntropyCoef = float(rp['entropy_coef'])
    cls.DirichletC = float(rp.get('dirichlet_c', 10.0))
    cls.RatioBatchK = int(rp.get('ratio_batch', 0))
    cls.CFinal = float(rp.get('c_final', 0.0))
    cls.CSwitchEp = int(rp.get('c_switch_ep', 0))
    sim.PPOAgent = cls
    return cls
