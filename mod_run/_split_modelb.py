# -*- coding: utf-8 -*-
"""MODEL_B 의 BT5_12/13/14 를 A·B 두 분기로 분리.

분기 A : BT5_10 → BT5_12A → BT5_13A → BT5_14A → BT5_20 ┐
분기 B : BT5_11 → BT5_12B → BT5_13B → BT5_14B → BT5_30 ┴→ BT5_31(JOIN)

구조적(파이썬 dict 순회) 편집만. 문자열 치환 금지(BT5_120/121.. 와 겹침).
멱등(이미 BT5_12A 있으면 skip). 타임스탬프 .bak 생성. 끝에 3-단언 검증.

추가: PSM IdleProcessRatedPowerKw 1.0 → 0.0993 (전 공정 RatedPowerKw 최저값의 50%).
"""
import json, copy, shutil, time, os, sys

# 이 스크립트는 루트의 입력 JSON(MODEL_B/PSM/WWM)을 편집 → DIR = 패키지 루트.
DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, DIR)                                   # verify() 의 path_extractor
TS  = time.strftime('%Y%m%d_%H%M%S')

SPLIT   = {'BT5_12': ['BT5_12A', 'BT5_12B'],
           'BT5_13': ['BT5_13A', 'BT5_13B'],
           'BT5_14': ['BT5_14A', 'BT5_14B']}
DEPPREV = {'BT5_12A': 'BT5_10',  'BT5_12B': 'BT5_11',
           'BT5_13A': 'BT5_12A', 'BT5_13B': 'BT5_12B',
           'BT5_14A': 'BT5_13A', 'BT5_14B': 'BT5_13B'}
IDLE_KW = '0.0993'                       # = round(min RatedPowerKw 0.1986 * 0.5, 4)


def _load(f):  return json.load(open(os.path.join(DIR, f), encoding='utf-8'))
def _save(f, d):
    shutil.copy2(os.path.join(DIR, f), os.path.join(DIR, f'{f}.{TS}.bak'))
    json.dump(d, open(os.path.join(DIR, f), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)


def _child(node, idShort):
    return next(c for c in node['value'] if c.get('idShort') == idShort)


def _retag_cd_url(obj, old, new):
    """obj 안의 모든 .../cd/<old>/... GlobalReference value 를 <new> 로."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == 'value' and isinstance(v, str) and f'/cd/{old}/' in v:
                obj[k] = v.replace(f'/cd/{old}/', f'/cd/{new}/')
            else:
                _retag_cd_url(v, old, new)
    elif isinstance(obj, list):
        for x in obj:
            _retag_cd_url(x, old, new)


def _make_cd(cds, base, new):
    src = next((c for c in cds if c.get('idShort') == base), None)
    if src is None or any(c.get('idShort') == new for c in cds):
        return
    cd = copy.deepcopy(src)
    cd['idShort'] = new
    cd['id'] = cd['id'].replace(f'/cd/{base}/', f'/cd/{new}/')
    for dn in cd.get('displayName', []):
        if dn.get('text') == base: dn['text'] = new
    for eds in cd.get('embeddedDataSpecifications', []):
        for pn in eds.get('dataSpecificationContent', {}).get('preferredName', []):
            if pn.get('text') == base: pn['text'] = new
    cds.append(cd)


# ---------- 1. MODEL_B.json ----------
def edit_model_b():
    d = _load('MODEL_B.json')
    mp = next(s for s in d['submodels'] if s['idShort'] == 'ManufacturingProcess')

    def walk(e):
        out = []
        if isinstance(e, dict):
            if e.get('idShort') == 'BT5FwInput':
                out.append(e)
            for v in (e.get('submodelElements'), e.get('value')):
                if isinstance(v, list):
                    for c in v: out += walk(c)
        return out

    fw = walk(mp)[0]
    ids = [v['idShort'] for v in fw['value']]
    if 'BT5_12A' in ids:
        print('MODEL_B: 이미 분리됨 — skip'); return d

    new_value = []
    for node in fw['value']:
        base = node['idShort']
        if base in SPLIT:
            for new in SPLIT[base]:
                clone = copy.deepcopy(node)
                clone['idShort'] = new
                _retag_cd_url(clone['semanticId'], base, new)
                for q in clone.get('qualifiers', []):
                    if q.get('type') == 'RefNo':
                        q['value'] = new[4:]              # '12' → '12A'/'12B'
                _child(clone, 'DepPrev')['value'] = DEPPREV[new]
                new_value.append(clone)
        else:
            new_value.append(node)
    fw['value'] = new_value

    # 후행 노드 DepPrev 재배선
    def relink(e):
        if isinstance(e, dict):
            if e.get('idShort') == 'BT5_20':
                _child(e, 'DepPrev')['value'] = 'BT5_14A'
            if e.get('idShort') == 'BT5_30':
                _child(e, 'DepPrev')['value'] = 'BT5_14B'
            for v in (e.get('submodelElements'), e.get('value')):
                if isinstance(v, list):
                    for c in v: relink(c)
    relink(mp)

    cds = d.setdefault('conceptDescriptions', [])
    for base, news in SPLIT.items():
        for new in news: _make_cd(cds, base, new)

    _save('MODEL_B.json', d)
    print('MODEL_B: BT5FwInput →', [v['idShort'] for v in fw['value']])
    return d


# ---------- 2. ProvisionOfSimulationModel.json ----------
def edit_psm():
    d = _load('ProvisionOfSimulationModel.json')
    changed = False

    def walk(e):
        if isinstance(e, dict):
            ids = e.get('idShort')

            # 2a. DependentSequence — BT5 ReferenceElement keys 확장
            if ids == 'DependentSequence':
                for ref in e.get('value', []):
                    keys = ref.get('value', {}).get('keys')
                    if not keys: continue
                    tails = [k['value'].split('/cd/')[-1].split('/')[0] for k in keys]
                    if 'BT5_12' not in tails: continue
                    if 'BT5_12A' in tails: continue
                    nk = []
                    for k in keys:
                        t = k['value'].split('/cd/')[-1].split('/')[0]
                        if t in SPLIT:
                            for new in SPLIT[t]:
                                kk = copy.deepcopy(k)
                                kk['value'] = k['value'].replace(f'/cd/{t}/', f'/cd/{new}/')
                                nk.append(kk)
                        else:
                            nk.append(k)
                    ref['value']['keys'] = nk

            # 2b. IdleProcessRatedPowerKw Property 값 하향
            if ids == 'IdleProcessRatedPowerKw' and e.get('modelType') == 'Property':
                e['value'] = IDLE_KW

            for k in ('submodels', 'submodelElements', 'value'):
                v = e.get(k)
                if isinstance(v, list):
                    for c in v: walk(c)
        elif isinstance(e, list):
            for c in e: walk(c)

    walk(d)

    # 2c. KnowledgeGraph/Node/SIM_MODEL_B — BT5_12/13/14 SMC → 6 복제
    def node_section(e, par=None):
        if isinstance(e, dict):
            if e.get('idShort') and e['idShort'].startswith('SIM_MODEL_B') \
               and isinstance(e.get('value'), list) \
               and any(c.get('idShort') in SPLIT for c in e['value']):
                if not any(c.get('idShort') == 'BT5_12A' for c in e['value']):
                    nv = []
                    for n in e['value']:
                        b = n.get('idShort')
                        if b in SPLIT:
                            for new in SPLIT[b]:
                                cl = copy.deepcopy(n)
                                cl['idShort'] = new
                                _retag_cd_url(cl.get('semanticId', {}), b, new)
                                for re_ in cl.get('value', []):
                                    for kk in re_.get('value', {}).get('keys', []):
                                        if kk.get('type') == 'SubmodelElementCollection' \
                                           and kk.get('value') == b:
                                            kk['value'] = new
                                nv.append(cl)
                        else:
                            nv.append(n)
                    e['value'] = nv
            for k in ('submodels', 'submodelElements', 'value'):
                v = e.get(k)
                if isinstance(v, list):
                    for c in v: node_section(c, e)
        elif isinstance(e, list):
            for c in e: node_section(c, par)
    node_section(d)

    cds = d.setdefault('conceptDescriptions', [])
    for base, news in SPLIT.items():
        for new in news: _make_cd(cds, base, new)

    _save('ProvisionOfSimulationModel.json', d)
    print('PSM: DependentSequence 확장 / Node SIM_MODEL_B 복제 / '
          f'IdleProcessRatedPowerKw → {IDLE_KW} / CD +6')
    return d


# ---------- 3. WorkstationWorkerMatchingDataAAS.json ----------
def edit_wwm():
    d = _load('WorkstationWorkerMatchingDataAAS.json')

    def walk(e):
        if isinstance(e, dict):
            ks = e.get('keys')
            if isinstance(ks, list) and any(
                    k.get('value', '').split('/cd/')[-1].split('/')[0] in SPLIT
                    for k in ks if isinstance(k, dict)):
                tails = [k['value'].split('/cd/')[-1].split('/')[0] for k in ks]
                if not any(t.endswith(('12A', '13A', '14A')) for t in tails):
                    nk = []
                    for k in ks:
                        t = k['value'].split('/cd/')[-1].split('/')[0]
                        if t in SPLIT:
                            for new in SPLIT[t]:
                                kk = copy.deepcopy(k)
                                kk['value'] = k['value'].replace(f'/cd/{t}/', f'/cd/{new}/')
                                nk.append(kk)
                        else:
                            nk.append(k)
                    e['keys'] = nk
            for kk in ('submodels', 'submodelElements', 'value', 'keys'):
                v = e.get(kk)
                if isinstance(v, list):
                    for c in v: walk(c)
                elif isinstance(v, dict):
                    walk(v)
        elif isinstance(e, list):
            for c in e: walk(c)
    walk(d)
    _save('WorkstationWorkerMatchingDataAAS.json', d)
    print('WWM: workstation ProcessCode 6분리')
    return d


# ---------- 검증 ----------
def verify():
    import importlib, path_extractor as pe
    importlib.reload(pe)
    for f in ['ProvisionOfSimulationModel.json', 'WorkstationWorkerMatchingDataAAS.json',
              'MODEL_A.json', 'MODEL_B.json', 'MODEL_C.json']:
        pe.load(os.path.join(DIR, f))
    PSM = pe.ProvisionofSimulationModelsAAS
    SM  = PSM.SimulationModels.SimulationModel
    A   = SM.KnowledgeGraph.Action
    svm = importlib.import_module('simulation_ver0_mod')
    KG  = svm.KnowledgeGraph.build(
        {mp.model_id: mp for mp in SM.Warehouse.InputBOM.target}, PSM.workers)
    IS = [n.idShort for r in A.IndependentSequence for n in r.target]
    DS = [n.idShort for r in A.DependentSequence  for n in r.target]
    DJ = [n.idShort for r in A.DependentJoin      for n in r.target]
    for c in ['BT5_12A', 'BT5_12B', 'BT5_13A', 'BT5_13B', 'BT5_14A', 'BT5_14B']:
        assert c in KG.nodes, f'{c} KG.nodes 누락'
        assert c in DS,       f'{c} DS 누락'
    assert 'BT5_12' not in KG.nodes and 'BT5_12' not in DS, 'old BT5_12 잔존'
    wh = svm.Warehouse.build(PSM.CoManagedBOM, SM.Warehouse.MinStock.target)
    rq = lambda done: set(KG.ready_queue(IS, DS, DJ, done, wh))
    r0 = rq(set())
    assert 'BT5_10' in r0 and 'BT5_11' in r0, f'독립공정 미준비 {r0 & {"BT5_10","BT5_11"}}'
    assert 'BT5_12A' not in r0 and 'BT5_12B' not in r0, '12A/B 가 선행없이 ready'
    r10 = rq({'BT5_10'})
    assert 'BT5_12A' in r10 and 'BT5_12B' not in r10, f'10완료시 12A만 ready 아님: {("BT5_12A" in r10, "BT5_12B" in r10)}'
    r11 = rq({'BT5_11'})
    assert 'BT5_12B' in r11 and 'BT5_12A' not in r11, '11완료시 12B만 ready 아님'
    r2030 = rq({'BT5_20', 'BT5_30'})
    assert 'BT5_31' in r2030, '20·30 완료시 31 JOIN 미준비'
    r20 = rq({'BT5_20'})
    assert 'BT5_31' not in r20, '20만으로 31 ready(JOIN 아님)'
    assert KG.nodes['BT5_20'].model_id == 'MODEL_B'
    print('검증 통과: 12A/B·13A/B·14A/B 분기 토폴로지 + 31 JOIN + IdleKw',
          PSM.SimulationModels.SimulationModel.DefaultParameters.IdleProcessRatedPowerKw.value)


if __name__ == '__main__':
    edit_model_b()
    edit_psm()
    edit_wwm()
    verify()
