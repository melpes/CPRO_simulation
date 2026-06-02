"""Finder A — wip 전체 AAS(5 json + 7 .aasx) 교차참조 해소 감사.
union(CD id) + AAS id + asset globalAssetId 를 만들고, 모든 SME 참조를 전수 추출해
각 참조가 union 안에서 해소되는지 판정. 끊긴 project 참조 + join 키 불일치 보고.
"""
import json
import zipfile
import xml.etree.ElementTree as ET
from collections import defaultdict, Counter

WIP = r'C:/Users/KangTaehui/KG/keti/CPRO_조립공정/시뮬레이션/Package/aas_data/wip/'
NS = '{https://admin-shell.io/aas/3/0}'

JSON_FILES = {
    'MODEL_A': WIP + 'MODEL_A.json',
    'MODEL_B': WIP + 'MODEL_B.json',
    'MODEL_C': WIP + 'MODEL_C.json',
    'wwm':     WIP + 'WorkstationWorkerMatchingDataAAS.json',
    'psm':     WIP + 'ProvisionOfSimulationModel.json',
}
AASX_FILES = {
    'Loader':        WIP + '1_Loader.aasx',
    'SPI':           WIP + '2_SPI.aasx',
    'ScreenPrinter': WIP + '3_ScreenPrinter.aasx',
    'Mounter':       WIP + '4_Mounter.aasx',
    'AOI':           WIP + '5_AOI.aasx',
    'Reflow':        WIP + '6_Reflow.aasx',
    'Unloader':      WIP + '7_Unloader.aasx',
}


# ===== XML -> JSON-shape =====
def _mt(tag):
    t = tag.replace(NS, '')
    return t[0].upper() + t[1:]


def _ls(node):
    if node is None:
        return []
    out = []
    for ls in list(node):
        out.append({'language': ls.findtext(NS + 'language'), 'text': ls.findtext(NS + 'text')})
    return out


def _ref(node):
    """Reference node -> {'type', 'keys':[{'type','value'}]} or None."""
    if node is None:
        return None
    keys = []
    kn = node.find(NS + 'keys')
    if kn is not None:
        for k in list(kn):
            keys.append({'type': k.findtext(NS + 'type'), 'value': k.findtext(NS + 'value')})
    return {'type': node.findtext(NS + 'type'), 'keys': keys}


def _sem(e):
    return _ref(e.find(NS + 'semanticId'))


CONTAINER = {'SubmodelElementCollection', 'SubmodelElementList'}


def _quals(e):
    qn = e.find(NS + 'qualifiers')
    out = []
    if qn is not None:
        for q in list(qn):
            out.append({'type': q.findtext(NS + 'type'), 'value': q.findtext(NS + 'value'),
                        'semanticId': _ref(q.find(NS + 'semanticId'))})
    return out


def _conv(e):
    mt = _mt(e.tag)
    d = {'modelType': mt}
    ids = e.find(NS + 'idShort')
    if ids is not None:
        d['idShort'] = ids.text
    d['description'] = _ls(e.find(NS + 'description'))
    sem = _sem(e)
    if sem:
        d['semanticId'] = sem
    q = _quals(e)
    if q:
        d['qualifiers'] = q
    if mt in CONTAINER:
        val = e.find(NS + 'value')
        d['value'] = [_conv(c) for c in list(val)] if val is not None else []
    elif mt == 'Entity':
        st = e.find(NS + 'statements')
        d['statements'] = [_conv(c) for c in list(st)] if st is not None else []
    elif mt in ('ReferenceElement',):
        v = e.find(NS + 'value')
        d['value'] = _ref(v)
    elif mt in ('RelationshipElement', 'AnnotatedRelationshipElement'):
        d['first'] = _ref(e.find(NS + 'first'))
        d['second'] = _ref(e.find(NS + 'second'))
    elif mt == 'Operation':
        for vk in ('inputVariables', 'outputVariables', 'inoutputVariables'):
            cont = e.find(NS + vk)
            if cont is not None:
                lst = []
                for ov in list(cont):
                    v = ov.find(NS + 'value')
                    kids = list(v) if v is not None else []
                    if kids:
                        lst.append({'value': _conv(kids[0])})
                d[vk] = lst
    else:
        v = e.find(NS + 'value')
        if v is not None and v.text is not None:
            d['value'] = v.text
    return d


def _conv_cd(cd):
    return {'idShort': cd.findtext(NS + 'idShort'), 'id': cd.findtext(NS + 'id')}


def xml_to_env(xml_bytes):
    root = ET.fromstring(xml_bytes)
    env = {'assetAdministrationShells': [], 'submodels': [], 'conceptDescriptions': []}
    shells = root.find(NS + 'assetAdministrationShells')
    if shells is not None:
        for sh in list(shells):
            ai = sh.find(NS + 'assetInformation')
            gid = ai.findtext(NS + 'globalAssetId') if ai is not None else None
            env['assetAdministrationShells'].append(
                {'idShort': sh.findtext(NS + 'idShort'), 'id': sh.findtext(NS + 'id'),
                 'assetInformation': {'globalAssetId': gid}})
    sms = root.find(NS + 'submodels')
    if sms is not None:
        for sm in list(sms):
            smd = {'modelType': 'Submodel', 'idShort': sm.findtext(NS + 'idShort'),
                   'id': sm.findtext(NS + 'id'), 'semanticId': _sem(sm)}
            ses = sm.find(NS + 'submodelElements')
            smd['submodelElements'] = [_conv(c) for c in list(ses)] if ses is not None else []
            env['submodels'].append(smd)
    cds = root.find(NS + 'conceptDescriptions')
    if cds is not None:
        for cd in list(cds):
            env['conceptDescriptions'].append(_conv_cd(cd))
    return env


# ===== load =====
envs = {}
for tag, path in JSON_FILES.items():
    envs[tag] = json.load(open(path, encoding='utf-8'))
for tag, aasx in AASX_FILES.items():
    z = zipfile.ZipFile(aasx)
    inner = [n for n in z.namelist() if n.endswith('.aas.xml')][0]
    envs[tag] = xml_to_env(z.read(inner))

# ===== union 집합 =====
global_cd = {}          # cd id -> tag
aas_ids = {}            # aas id -> tag
asset_ids = {}          # globalAssetId -> tag
submodel_ids = {}       # submodel id -> tag
for tag, env in envs.items():
    for cd in env.get('conceptDescriptions', []):
        if cd.get('id'):
            global_cd.setdefault(cd['id'], tag)
    for sh in env.get('assetAdministrationShells', []):
        if sh.get('id'):
            aas_ids.setdefault(sh['id'], tag)
        g = (sh.get('assetInformation') or {}).get('globalAssetId')
        if g:
            asset_ids.setdefault(g, tag)
    for sm in env.get('submodels', []):
        if sm.get('id'):
            submodel_ids.setdefault(sm['id'], tag)

# union of every id that could be a reference target
ALL_IDS = set(global_cd) | set(aas_ids) | set(asset_ids) | set(submodel_ids)


def is_project(value):
    return isinstance(value, str) and 'smart-factory.kr' in value


def is_external_std(value):
    if not isinstance(value, str):
        return False
    return ('admin-shell.io' in value or 'eclass' in value.lower()
            or value.startswith('0173-') or value.startswith('0112/'))


# ===== per-submodel 로컬 idShort 집합 (BoM first/second 로컬 해소용) =====
def all_idshorts(node, acc):
    for c in (node.get('value') if isinstance(node.get('value'), list) else []) \
             + (node.get('submodelElements') or []) + (node.get('statements') or []):
        if isinstance(c, dict):
            if c.get('idShort'):
                acc.add(c['idShort'])
            all_idshorts(c, acc)
    return acc


local_idshorts = {}      # (tag, submodel_idShort) -> set
local_by_smid = {}       # submodel id (URL) -> set of local idShorts  (cross-submodel 체인 해소)
for tag, env in envs.items():
    for smm in env.get('submodels', []):
        s = all_idshorts(smm, set())
        local_idshorts[(tag, smm.get('idShort'))] = s
        if smm.get('id'):
            local_by_smid.setdefault(smm['id'], set()).update(s)


# ===== reference 전수 추출 =====
# 각 ref: (kind, path, ref_dict)  ref_dict={'type','keys'}
findings = defaultdict(list)   # category -> list of dict
ref_count = 0
resolved = 0


def whitespace_dirty(s):
    return isinstance(s, str) and s != s.strip() and s.strip() != ''


def check_chain(ref, kind, path, local=None):
    """Reference(키 체인) 전체를 해소 판정.
    규칙:
     - 첫 키가 union(Submodel/AAS/CD/asset id) 에서 해소되면 체인 앵커됨 → 뒤 SME 키는
       (a) 앵커가 Submodel id 면 그 submodel 의 로컬 idShort, (b) 그 외엔 union/현재 local 에서 해소.
     - 단일/말단 키만 있는 경우 union 또는 현재 local 에서 해소.
     - 외부표준(admin-shell/eclass/IRDI)은 PASS.
     - 아무것도 해소 안 되면 dangling.
    체인 단위로 ref_count 1 증가, 해소되면 resolved 1.
    """
    global ref_count, resolved
    keys = [(kt, kv) for kt, kv in each_key(ref)]
    if not keys:
        return
    ref_count += 1
    # whitespace 오염 검사 (전 키)
    for kt, kv in keys:
        if whitespace_dirty(kv):
            findings['whitespace'].append({'path': path, 'kind': kind, 'value': repr(kv)})
    keys = [(kt, (kv.strip() if isinstance(kv, str) else kv)) for kt, kv in keys]

    first_t, first_v = keys[0]
    # 앵커 판정
    anchor_local = None
    anchored = False
    if first_v in ALL_IDS:
        anchored = True
        if first_v in local_by_smid:
            anchor_local = local_by_smid[first_v]    # 타깃 submodel 로컬 idShort
    elif is_external_std(first_v):
        # 외부표준(IDTA) submodel/CD 앵커 — 내부 구조(SML index 등)는 우리 union 밖, 전체 PASS
        resolved += 1
        return
    if anchored:
        # 뒤 키들이 SME idShort 로서 앵커 submodel(또는 union/현재 local)에서 해소되는지
        unresolved_tail = []
        for kt, kv in keys[1:]:
            if (kv in ALL_IDS or is_external_std(kv)
                    or (anchor_local is not None and kv in anchor_local)
                    or (local is not None and kv in local)
                    or (isinstance(kv, str) and kv.isdigit())):   # SML positional index
                continue
            unresolved_tail.append((kt, kv))
        if not unresolved_tail:
            resolved += 1
            return
        # 앵커는 됐는데 꼬리 SME 가 타깃에 없음 → 끊긴 경로
        bucket = 'dangling_project' if is_project(first_v) else 'dangling_other'
        findings[bucket].append({'path': path, 'kind': kind + '(tail)',
                                 'value': first_v + ' :: ' + ';'.join(f'{t}={v}' for t, v in unresolved_tail)})
        return
    # 앵커 안 됨 — 단일/말단 키가 union/local 에서 직접 해소되는지
    last_v = keys[-1][1]
    if last_v in ALL_IDS or (local is not None and last_v in local) or is_external_std(last_v):
        resolved += 1
        return
    # 전 키가 union/local 어디에도 없음
    cand = first_v
    bucket = 'dangling_project' if is_project(cand) else 'dangling_other'
    findings[bucket].append({'path': path, 'kind': kind, 'value': ';'.join(v for _, v in keys)})


def ref_last(ref):
    if not isinstance(ref, dict):
        return None
    ks = ref.get('keys') or []
    return ks[-1].get('value') if ks else None


def each_key(ref):
    if not isinstance(ref, dict):
        return []
    return [(k.get('type'), k.get('value')) for k in (ref.get('keys') or [])]


def kids(e):
    v = e.get('value')
    if isinstance(v, list):
        return v
    return e.get('submodelElements') or e.get('statements') or []


def walk(e, path, local):
    mt = e.get('modelType')
    ids = e.get('idShort')
    # semanticId (CD/Submodel 단일 ref — 체인이지만 보통 1키)
    sem = e.get('semanticId')
    if isinstance(sem, dict):
        check_chain(sem, 'semanticId', path, local)
    # qualifiers
    for q in e.get('qualifiers') or []:
        qsem = q.get('semanticId')
        if isinstance(qsem, dict):
            check_chain(qsem, 'qualifier.semanticId', path + f'[Q:{q.get("type")}]', local)
    # ReferenceElement.value (KG ModelReference 크로스-서브모델 체인 포함)
    if mt == 'ReferenceElement':
        v = e.get('value')
        if isinstance(v, dict):
            check_chain(v, 'ReferenceElement.value', path, local)
    # Relationship first/second (BoM: keys 는 로컬 엔티티 fragment, referredSemanticId 는 ModelRef 체인)
    if mt in ('RelationshipElement', 'AnnotatedRelationshipElement'):
        for fld in ('first', 'second'):
            v = e.get(fld)
            if isinstance(v, dict):
                check_chain(v, f'Relationship.{fld}', path, local)
                rsi = v.get('referredSemanticId')
                if isinstance(rsi, dict):
                    check_chain(rsi, f'Relationship.{fld}.referredSemanticId', path, local)
    # recurse containers
    if mt in CONTAINER or mt == 'Entity':
        for i, c in enumerate(kids(e)):
            seg = c.get('idShort') or f'[{i}]'
            walk(c, path + '/' + str(seg), local)
    elif mt == 'Operation':
        for vk in ('inputVariables', 'outputVariables', 'inoutputVariables'):
            for j, ov in enumerate(e.get(vk) or []):
                v = ov.get('value')
                if isinstance(v, dict):
                    seg = v.get('idShort') or f'[{j}]'
                    walk(v, path + f'/{vk}/' + str(seg), local)


for tag, env in envs.items():
    for sm in env.get('submodels', []):
        rs = sm.get('idShort')
        base = f'{tag}:{rs}'
        local = local_idshorts.get((tag, rs), set())
        for c in sm.get('submodelElements', []):
            seg = c.get('idShort') or '[?]'
            walk(c, base + '/' + str(seg), local)

# ===== 특수 join 검증 =====
# (1) psm SMTProcess 설비 SMC.semanticId(ExternalReference,AAS) == 설비 .aasx AAS id
# (2) CycleTimeSec/RatedPowerKw ReferenceElement.value(cd ref) == 설비 property semanticId
psm = envs['psm']
sm = [s for s in psm['submodels'] if s['idShort'] == 'SimulationModels'][0]


def _kids(e):
    return e.get('value') if isinstance(e.get('value'), list) else (e.get('submodelElements') or [])


def _find(elems, name):
    for e in elems:
        if e.get('idShort') == name:
            return e


join_report = {'equipment_smc_aas_ref': [], 'lookup_keys': [], 'equip_props_by_sem': {}}

# 설비 property semanticId 수집 (각 설비 .aasx 의 모든 property semanticId set)
equip_sem = {}   # tag -> set of semanticId last-values present as property semanticId
for tag in AASX_FILES:
    s = set()

    def collect(e):
        sem = e.get('semanticId')
        lv = ref_last(sem) if isinstance(sem, dict) else None
        if lv:
            s.add(lv)
        for c in kids(e):
            collect(c)
    for smm in envs[tag]['submodels']:
        for c in smm.get('submodelElements', []):
            collect(c)
    equip_sem[tag] = s

model = _find(_kids(sm), 'SimulationModel')
smt = _find(_kids(model), 'SMTProcess')
lines = _find(smt['value'], 'SMTLines')
aas_to_tag = {v: k for k, v in [(t, t) for t in AASX_FILES]}  # not used; map by id below
# map AAS id -> tag
aasid_to_tag = {}
for tag in AASX_FILES:
    for sh in envs[tag]['assetAdministrationShells']:
        aasid_to_tag[sh['id']] = tag

for line in lines['value']:
    for proc in line['value']:
        psem = ref_last(proc.get('semanticId'))
        tag = aasid_to_tag.get(psem)
        rec = {'process': f"{line['idShort']}/{proc['idShort']}", 'smc_sem': psem,
               'resolves_to_equipment': tag}
        join_report['equipment_smc_aas_ref'].append(rec)
        # lookup keys
        for child in proc.get('value', []):
            if child.get('modelType') == 'ReferenceElement':
                lookup = ref_last(child.get('value'))
                present = (tag is not None) and (lookup in equip_sem.get(tag, set()))
                join_report['lookup_keys'].append({
                    'process': f"{line['idShort']}/{proc['idShort']}",
                    'lookup_child': child['idShort'], 'lookup_sem': lookup,
                    'equipment': tag, 'found_in_equipment': present})

join_report['equip_props_by_sem'] = {t: sorted(s) for t, s in equip_sem.items()}

# ===== SMTMaterials PCB 체인 해소 (이미 check_ref 가 처리하지만 따로 요약) =====
matsmc = _find(smt['value'], 'SMTMaterials')
mat_report = []
if matsmc:
    for mdl in matsmc['value']:
        asset_sem = ref_last(mdl.get('semanticId'))
        for child in mdl.get('value', []):
            if child.get('modelType') == 'ReferenceElement':
                chain = [k for _, k in each_key(child.get('value'))]
                unresolved = [c for c in chain if c not in ALL_IDS and not is_external_std(c)]
                mat_report.append({'model_smc': mdl['idShort'], 'asset_sem': asset_sem,
                                   'asset_resolves': asset_sem in asset_ids,
                                   'pcb_chain_len': len(chain),
                                   'unresolved': unresolved})

# ===== KnowledgeGraph 토폴로지 정합 =====
# (a) SMTLines 공정노드 DepPrev 가 같은 라인 공정 idShort 가리키는지
# (b) KG Node 컨벤션: node.semanticId.last == cd/<idShort>/1/0
# (c) Action(IndependentSequence/DependentSequence/DependentJoin/AssignedProcessGroups) 의
#     공정노드 ref(cd/<token>/1/0) 의 token 이 실제 KG node idShort 인지 (phantom 검출)
kg = _find(_kids(model), 'KnowledgeGraph')
kg_report = {'smtlines_dep': [], 'node_convention_exceptions': [],
             'action_phantom_nodes': [], 'total_kg_nodes': 0}

# (a) SMTLines
for line in lines['value']:
    procnames = [p['idShort'] for p in line['value']]
    for proc in line['value']:
        dp = _find(proc['value'], 'DepPrev')
        dt = _find(proc['value'], 'DepType')
        dpv = dp.get('value') if dp else None
        targets = [t for t in (dpv.split(';') if dpv else []) if t]
        miss = [t for t in targets if t not in procnames]
        kg_report['smtlines_dep'].append({
            'process': f"{line['idShort']}/{proc['idShort']}",
            'DepType': dt.get('value') if dt else None, 'DepPrev': dpv,
            'missing_targets': miss})

node_grp = _find(kg['value'], 'Node')
kg_nodes = set()
if node_grp:
    for grp in node_grp['value']:
        for n in (grp.get('value') or []):
            nid = n['idShort']
            kg_nodes.add(nid)
            lv = ref_last(n.get('semanticId'))
            expected = f'https://www.smart-factory.kr/ids/cd/{nid}/1/0'
            if lv != expected:
                kg_report['node_convention_exceptions'].append({'node': nid, 'semanticId': lv})
kg_report['total_kg_nodes'] = len(kg_nodes)

action_grp = _find(kg['value'], 'Action')
if action_grp:
    def scan_action(e, path):
        for c in (e.get('value') or []) if isinstance(e.get('value'), list) else []:
            cp = path + '/' + str(c.get('idShort'))
            if c.get('modelType') == 'ReferenceElement':
                v = c.get('value')
                for kt, kv in each_key(v):
                    if isinstance(kv, str) and '/cd/' in kv:
                        token = kv.split('/cd/', 1)[1].rsplit('/1/0', 1)[0]
                        if token not in kg_nodes:
                            kg_report['action_phantom_nodes'].append({'location': cp, 'token': token})
            scan_action(c, cp)
    scan_action(action_grp, 'Action')

# ===== value-side whitespace (값/참조 문자열 선후행 공백) =====
value_ws = []


def scan_ws(o, path):
    if isinstance(o, dict):
        v = o.get('value')
        if isinstance(v, str) and v != v.strip() and v.strip():
            value_ws.append({'kind': 'Property.value', 'path': path + '/' + str(o.get('idShort'))})
        ids = o.get('idShort')
        if isinstance(ids, str) and ids != ids.strip() and ids.strip():
            value_ws.append({'kind': 'idShort', 'path': path})
        for k, vv in o.items():
            scan_ws(vv, path + '/' + str(o.get('idShort') or k))
    elif isinstance(o, list):
        for i, x in enumerate(o):
            scan_ws(x, path + f'[{i}]')


# ===== duplicate CD id (파일 내) + 내용 동일성 =====
dup_cd = {}
for tag in JSON_FILES:
    e = envs[tag]
    by = defaultdict(list)
    for cd in e.get('conceptDescriptions', []):
        if cd.get('id'):
            by[cd['id']].append(cd)
    ids_with_dup = {k: v for k, v in by.items() if len(v) > 1}
    if ids_with_dup:
        identical = 0
        differing = 0
        for cid, objs in ids_with_dup.items():
            base = json.dumps(objs[0], ensure_ascii=False, sort_keys=True)
            if all(json.dumps(o, ensure_ascii=False, sort_keys=True) == base for o in objs[1:]):
                identical += 1
            else:
                differing += 1
        dup_cd[tag] = {'dup_ids': len(ids_with_dup),
                       'extra_copies': sum(len(v) - 1 for v in ids_with_dup.values()),
                       'identical_content': identical, 'differing_content': differing}
    scan_ws(e, tag)

report = {
    'counts': {'refs_checked': ref_count, 'resolved': resolved,
               'dangling_project': len(findings['dangling_project']),
               'dangling_other': len(findings['dangling_other']),
               'whitespace': len(findings['whitespace']),
               'cd_union': len(global_cd), 'aas_ids': len(aas_ids),
               'asset_ids': len(asset_ids), 'submodel_ids': len(submodel_ids)},
    'dangling_project': findings['dangling_project'],
    'dangling_other': findings['dangling_other'],
    'whitespace': findings['whitespace'],
    'join': join_report,
    'materials': mat_report,
    'kg': kg_report,
    'value_whitespace': value_ws,
    'duplicate_cd': dup_cd,
}
json.dump(report, open(WIP + '../../mod_run/_xref_wip_out.json', 'w', encoding='utf-8'),
          ensure_ascii=False, indent=1, default=str)

print('=== COUNTS ===')
print(json.dumps(report['counts'], ensure_ascii=False, indent=1))
print('\n=== JOIN: equipment SMC -> AAS ===')
for r in join_report['equipment_smc_aas_ref']:
    print(f"  {r['process']:24} sem={r['smc_sem']}  -> {r['resolves_to_equipment']}")
print('\n=== JOIN: lookup keys (CycleTimeSec/RatedPowerKw -> equipment property semanticId) ===')
for r in join_report['lookup_keys']:
    flag = 'OK ' if r['found_in_equipment'] else 'MISS'
    print(f"  [{flag}] {r['process']:24} {r['lookup_child']:14} sem={r['lookup_sem']}  equip={r['equipment']}")
print('\n=== MATERIALS ===')
for r in mat_report:
    print(f"  {r['model_smc']:8} asset={r['asset_sem']} resolves={r['asset_resolves']} chain={r['pcb_chain_len']} unresolved={r['unresolved']}")
print('\n=== KG topology ===')
print('  total KG nodes:', kg_report['total_kg_nodes'])
smt_miss = [d for d in kg_report['smtlines_dep'] if d['missing_targets']]
print('  SMTLines DepPrev missing-target issues:', len(smt_miss), smt_miss)
print('  node semanticId convention exceptions:', kg_report['node_convention_exceptions'])
print('  Action phantom node refs:', kg_report['action_phantom_nodes'])
print('\n=== value-side whitespace ===')
for r in value_ws:
    print('  ', r)
print('\n=== duplicate CD id ===')
for tag, d in dup_cd.items():
    print('  ', tag, d)
print('\n=== dangling_project (count {}) ==='.format(len(findings['dangling_project'])))
for r in findings['dangling_project']:
    print('  ', r['kind'], r['path'], '->', r['value'])
print('\n=== dangling_other UNIQUE values (count {}) ==='.format(len(findings['dangling_other'])))
from collections import Counter as _C
uniq = _C(r['value'] for r in findings['dangling_other'])
print('  distinct:', len(uniq))
# group by kind for non-BoM danglers
non_bom = [r for r in findings['dangling_other']
           if not r['kind'].startswith('Relationship')]
print('  non-Relationship dangling_other:', len(non_bom))
for r in non_bom[:50]:
    print('   ', r['kind'], r['path'], '->', r['value'])
print('\n=== whitespace ===')
for r in findings['whitespace'][:30]:
    print('  ', r)
