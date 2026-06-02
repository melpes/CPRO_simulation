"""psm_smt 에만 있고 psm 엔 없는 오류(델타)만 추출. psm 을 기준선으로.
dangling 판정은 6개 파일 CD union 기준(감사 본편과 동일)."""
import json
from collections import Counter

BASE = r'C:/Users/KangTaehui/KG/keti/CPRO_조립공정/시뮬레이션/Package/aas_data/'
FILES = {
    'MODEL_A': 'MODEL_A.json', 'MODEL_B': 'MODEL_B.json', 'MODEL_C': 'MODEL_C.json',
    'wwm': 'WorkstationWorkerMatchingDataAAS.json',
    'psm': 'ProvisionOfSimulationModel.json', 'psm_smt': 'ProvisionOfSimulationModel_smt.json',
}
RECURSE = {
    'SubmodelElementCollection': lambda e: e.get('value') or [],
    'SubmodelElementList':       lambda e: e.get('value') or [],
    'Entity':                    lambda e: e.get('statements') or [],
    'AnnotatedRelationshipElement': lambda e: e.get('annotations') or [],
}


def text_nonempty(mlp):
    return bool(mlp) and any((d.get('text') or '').strip() for d in mlp)


def sem_info(node):
    s = node.get('semanticId')
    if not s:
        return None
    keys = s.get('keys') or []
    if not keys or not keys[-1].get('value'):
        return None
    return (s.get('type'), keys[-1].get('type'), keys[-1].get('value'))


def is_cd_ref(info):
    if info is None:
        return False
    rt, kt, _ = info
    return (rt == 'ExternalReference' and kt == 'GlobalReference') or (rt == 'ModelReference' and kt == 'ConceptDescription')


def cd_hard_issues(cd):
    eds = cd.get('embeddedDataSpecifications')
    if not eds:
        return ['no embeddedDataSpecifications']
    c = next((e.get('dataSpecificationContent') for e in eds if e.get('dataSpecificationContent')), None)
    if not c:
        return ['no dataSpecificationContent']
    iss = []
    if not text_nonempty(c.get('preferredName')):
        iss.append('no preferredName')
    if not text_nonempty(c.get('definition')):
        iss.append('no definition')
    if not c.get('dataType'):
        iss.append('no dataType')
    return iss


def walk(elements, path, root_sm, out):
    for i, e in enumerate(elements):
        if not isinstance(e, dict):
            continue
        mt = e.get('modelType')
        seg = e.get('idShort') if e.get('idShort') is not None else f'[{i}]'
        p = f'{path}/{seg}'
        out.append({'path': p, 'mt': mt, 'root_sm': root_sm, 'node': e})
        if mt in RECURSE:
            walk(RECURSE[mt](e), p, root_sm, out)
        elif mt == 'Operation':
            for vk in ('inputVariables', 'outputVariables', 'inoutputVariables'):
                for ov in e.get(vk) or []:
                    v = ov.get('value')
                    if isinstance(v, dict):
                        walk([v], p, root_sm, out)


data = {t: json.load(open(BASE + f, encoding='utf-8')) for t, f in FILES.items()}
global_cd = set()
for d in data.values():
    for cd in d.get('conceptDescriptions', []):
        global_cd.add(cd['id'])


def audit(tag):
    d = data[tag]
    nodes = []
    for sm in d.get('submodels', []):
        rs = sm.get('idShort')
        nodes.append({'path': rs, 'mt': 'Submodel', 'root_sm': rs, 'node': sm})
        walk(sm.get('submodelElements', []), rs, rs, nodes)
    descr = {}          # path -> actionable?(bool)
    sem = set()         # paths (semanticId 누락)
    dangling = {}       # cd_id -> (count, root_sm set)
    for n in nodes:
        info = sem_info(n['node'])
        if not text_nonempty(n['node'].get('description')):
            covered = is_cd_ref(info) and info[2] in global_cd
            descr[n['path']] = (not covered, n['root_sm'])
        if info is None:
            sem.add((n['path'], n['root_sm']))
        elif is_cd_ref(info) and info[2] not in global_cd:
            cnt, roots = dangling.get(info[2], (0, set()))
            dangling[info[2]] = (cnt + 1, roots | {n['root_sm']})
    cds = d.get('conceptDescriptions', [])
    cd_inc = {cd['id']: cd_hard_issues(cd) for cd in cds if cd_hard_issues(cd)}
    dup = {k for k, v in Counter(cd['id'] for cd in cds).items() if v > 1}
    return {'descr': descr, 'sem': sem, 'dangling': dangling, 'cd_inc': cd_inc, 'dup': dup}


P = audit('psm')
S = audit('psm_smt')

print('=' * 70)
print('psm_smt 에만 있고 psm 엔 없는 오류 (델타)')
print('=' * 70)

# A. description 누락 (actionable) — psm_smt 경로 중 psm 에 없는 것
sd_paths = {p for p, (act, rs) in S['descr'].items() if act}
pd_paths = {p for p, (act, rs) in P['descr'].items() if act}
only = sorted(sd_paths - pd_paths)
print(f'\n[A] description 누락(actionable) — psm_smt 전용: {len(only)}개')
by_sm = Counter(S['descr'][p][1] for p in only)
print('    소속 submodel:', dict(by_sm))
for p in only[:50]:
    print('   -', p)
if len(only) > 50:
    print(f'   … 외 {len(only)-50}개')

# B. semanticId 누락 — path 기준
sp = {p for p, rs in S['sem']}
pp = {p for p, rs in P['sem']}
only_sem = sorted(sp - pp)
print(f'\n[B] semanticId 누락 — psm_smt 전용: {len(only_sem)}개')
for p in only_sem[:50]:
    print('   -', p)

# C. dangling CD (참조하나 CD 없음) — cd_id 기준
only_dang = {k: S['dangling'][k] for k in S['dangling'] if k not in P['dangling']}
print(f'\n[C] dangling CD — psm_smt 전용: 고유 {len(only_dang)}종')
for cid, (cnt, roots) in sorted(only_dang.items(), key=lambda x: -x[1][0]):
    short = cid.split('/ids/cd/')[-1] if '/ids/cd/' in cid else cid
    print(f'   - {short:28} ×{cnt:<3} (submodel: {",".join(sorted(roots))})')

# D. CD 불완전(hard) — cd_id 기준
only_inc = {k: S['cd_inc'][k] for k in S['cd_inc'] if k not in P['cd_inc']}
m3d = {k: v for k, v in only_inc.items() if 'admin-shell.io/idta/Models3D' in k}
other = {k: v for k, v in only_inc.items() if 'admin-shell.io/idta/Models3D' not in k}
print(f'\n[D] CD 불완전(hard) — psm_smt 전용: {len(only_inc)}개')
print(f'    └ Models3D 템플릿 import분: {len(m3d)}개 (예상)')
print(f'    └ 그 외: {len(other)}개')
for cid, iss in list(other.items())[:50]:
    short = cid.split('/ids/cd/')[-1] if '/ids/cd/' in cid else cid
    print(f'   - {short}: {", ".join(iss)}')

# E. 중복 CD id — cd_id 기준
only_dup = S['dup'] - P['dup']
print(f'\n[E] 중복 CD id — psm_smt 전용: {len(only_dup)}개')
for k in sorted(only_dup):
    print('   -', k)
