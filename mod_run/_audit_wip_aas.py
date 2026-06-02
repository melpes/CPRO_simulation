"""wip 전체 AAS 완결성 감사 (Finder D). _audit_all_aas.py 의 wip 버전.
경로만 wip/ 로 바꿔 동일 로직 재사용. psm 은 통합 단일 파일.
"""
import json
import re
import zipfile
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict

PKG = r'C:/Users/KangTaehui/KG/keti/CPRO_조립공정/시뮬레이션/Package/'
WIP = PKG + 'aas_data/wip/'
NS = '{https://admin-shell.io/aas/3/0}'

JSON_FILES = {
    'MODEL_A': WIP + 'MODEL_A.json',
    'MODEL_B': WIP + 'MODEL_B.json',
    'MODEL_C': WIP + 'MODEL_C.json',
    'wwm':     WIP + 'WorkstationWorkerMatchingDataAAS.json',
    'psm':     WIP + 'ProvisionOfSimulationModel.json',
}
AASX_FILES = {
    'Loader':        (WIP + '1_Loader.aasx',        'aasx/Loader/Loader.aas.xml'),
    'SPI':           (WIP + '2_SPI.aasx',           'aasx/SPI/SPI.aas.xml'),
    'ScreenPrinter': (WIP + '3_ScreenPrinter.aasx', 'aasx/ScreenPrinter/ScreenPrinter.aas.xml'),
    'Mounter':       (WIP + '4_Mounter.aasx',       'aasx/Mounter/Mounter.aas.xml'),
    'AOI':           (WIP + '5_AOI.aasx',           'aasx/AOI/AOI.aas.xml'),
    'Reflow':        (WIP + '6_Reflow.aasx',        'aasx/Reflow/Reflow.aas.xml'),
    'Unloader':      (WIP + '7_Unloader.aasx',      'aasx/Unloader/Unloader.aas.xml'),
}


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


def _desc(e):
    return _ls(e.find(NS + 'description'))


def _sem(e):
    s = e.find(NS + 'semanticId')
    if s is None:
        return None
    keys = []
    kn = s.find(NS + 'keys')
    if kn is not None:
        for k in list(kn):
            keys.append({'type': k.findtext(NS + 'type'), 'value': k.findtext(NS + 'value')})
    return {'type': s.findtext(NS + 'type'), 'keys': keys}


CONTAINER = {'SubmodelElementCollection', 'SubmodelElementList'}


def _conv(e):
    mt = _mt(e.tag)
    d = {'modelType': mt}
    ids = e.find(NS + 'idShort')
    if ids is not None:
        d['idShort'] = ids.text
    desc = _desc(e)
    if desc:
        d['description'] = desc
    sem = _sem(e)
    if sem:
        d['semanticId'] = sem
    if mt in CONTAINER:
        val = e.find(NS + 'value')
        d['value'] = [_conv(c) for c in list(val)] if val is not None else []
    elif mt == 'Entity':
        st = e.find(NS + 'statements')
        d['statements'] = [_conv(c) for c in list(st)] if st is not None else []
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
    return d


def _conv_cd(cd):
    out = {'idShort': cd.findtext(NS + 'idShort'), 'id': cd.findtext(NS + 'id'),
           'description': _desc(cd), 'embeddedDataSpecifications': []}
    eds = cd.find(NS + 'embeddedDataSpecifications')
    if eds is not None:
        for ed in list(eds):
            content = ed.find(NS + 'dataSpecificationContent')
            iec = content.find(NS + 'dataSpecificationIec61360') if content is not None else None
            dsc = {}
            if iec is not None:
                dsc['preferredName'] = _ls(iec.find(NS + 'preferredName'))
                dsc['definition'] = _ls(iec.find(NS + 'definition'))
                dsc['dataType'] = iec.findtext(NS + 'dataType')
            out['embeddedDataSpecifications'].append({'dataSpecificationContent': dsc})
    return out


def xml_to_env(xml_bytes):
    root = ET.fromstring(xml_bytes)
    env = {'assetAdministrationShells': [], 'submodels': [], 'conceptDescriptions': []}
    shells = root.find(NS + 'assetAdministrationShells')
    if shells is not None:
        for sh in list(shells):
            env['assetAdministrationShells'].append({'idShort': sh.findtext(NS + 'idShort'), 'id': sh.findtext(NS + 'id')})
    sms = root.find(NS + 'submodels')
    if sms is not None:
        for sm in list(sms):
            smd = {'modelType': 'Submodel', 'idShort': sm.findtext(NS + 'idShort'),
                   'id': sm.findtext(NS + 'id'), 'description': _desc(sm)}
            sem = _sem(sm)
            if sem:
                smd['semanticId'] = sem
            ses = sm.find(NS + 'submodelElements')
            smd['submodelElements'] = [_conv(c) for c in list(ses)] if ses is not None else []
            env['submodels'].append(smd)
    cds = root.find(NS + 'conceptDescriptions')
    if cds is not None:
        for cd in list(cds):
            env['conceptDescriptions'].append(_conv_cd(cd))
    return env


RECURSE = {
    'SubmodelElementCollection': lambda e: e.get('value') or [],
    'SubmodelElementList':       lambda e: e.get('value') or [],
    'Entity':                    lambda e: e.get('statements') or [],
    'AnnotatedRelationshipElement': lambda e: e.get('annotations') or [],
}
CAMEL_OK = re.compile(r'^[A-Za-z][A-Za-z0-9]*$')


def text_nonempty(mlp):
    return bool(mlp) and any((d.get('text') or '').strip() for d in mlp)


def sem_value(node):
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


def camel_violation(ids):
    if ids is None:
        return None
    if ' ' in ids:
        return 'space'
    if '_' in ids:
        return 'underscore'
    if not CAMEL_OK.match(ids):
        return 'special'
    if ids[0].isdigit():
        return 'startsDigit'
    if ids[0].islower():
        return 'startsLower'
    return None


def walk(elements, path, parent_mt, root_sm, out):
    for i, e in enumerate(elements):
        if not isinstance(e, dict):
            continue
        mt = e.get('modelType')
        ids = e.get('idShort')
        seg = ids if ids is not None else f'[{i}]'
        p = f'{path}/{seg}'
        is_sml_child = (parent_mt == 'SubmodelElementList')
        out.append({'path': p, 'mt': mt, 'idShort': ids, 'parent_mt': parent_mt,
                    'is_sml_child': is_sml_child, 'root_sm': root_sm, 'node': e})
        if mt in RECURSE:
            walk(RECURSE[mt](e), p, mt, root_sm, out)
        elif mt == 'Operation':
            for vk in ('inputVariables', 'outputVariables', 'inoutputVariables'):
                for ov in e.get(vk) or []:
                    v = ov.get('value')
                    if isinstance(v, dict):
                        walk([v], p, 'Operation', root_sm, out)


def cd_incomplete(cd):
    miss = []
    if not (cd.get('idShort') or '').strip():
        miss.append('idShort')
    eds = cd.get('embeddedDataSpecifications')
    if not eds:
        miss.append('embeddedDataSpec')
        return miss
    content = next((e.get('dataSpecificationContent') for e in eds if e.get('dataSpecificationContent')), None)
    if not content:
        miss.append('dataSpecificationContent')
        return miss
    if not text_nonempty(content.get('preferredName')):
        miss.append('preferredName')
    if not (content.get('dataType') or '').strip():
        miss.append('dataType')
    if not text_nonempty(content.get('definition')):
        miss.append('definition')
    return miss


envs = {}
for tag, path in JSON_FILES.items():
    envs[tag] = json.load(open(path, encoding='utf-8'))
for tag, (aasx, inner) in AASX_FILES.items():
    z = zipfile.ZipFile(aasx)
    envs[tag] = xml_to_env(z.read(inner))

global_cd = {}
for tag, env in envs.items():
    for cd in env.get('conceptDescriptions', []):
        if cd.get('id'):
            global_cd.setdefault(cd['id'], cd)

report = {'files': {}, 'global_cd_count': len(global_cd)}
for tag, env in envs.items():
    nodes = []
    for sm in env.get('submodels', []):
        rs = sm.get('idShort')
        nodes.append({'path': rs, 'mt': 'Submodel', 'idShort': rs, 'parent_mt': 'env',
                      'is_sml_child': False, 'root_sm': rs, 'node': sm})
        walk(sm.get('submodelElements', []), rs, 'Submodel', rs, nodes)

    res = {'n_submodels': len(env.get('submodels', [])),
           'n_nodes': len(nodes), 'n_cd': len(env.get('conceptDescriptions', [])),
           'idShort_missing': [], 'camel_violation': defaultdict(list),
           'desc_missing': [], 'sem_missing': [], 'dangling': defaultdict(list),
           'cd_incomplete': [], 'dup_cd_id': {}}

    for n in nodes:
        mt = n['mt']
        if mt != 'Submodel' and not n['is_sml_child'] and (n['idShort'] is None or not str(n['idShort']).strip()):
            res['idShort_missing'].append(n['path'])
        if not n['is_sml_child'] and n['idShort']:
            v = camel_violation(n['idShort'])
            if v:
                res['camel_violation'][v].append((n['idShort'], n['path']))
        if not text_nonempty(n['node'].get('description')):
            res['desc_missing'].append((mt, n['path']))
        info = sem_value(n['node'])
        if mt != 'Submodel' and info is None:
            res['sem_missing'].append((mt, n['path'], n['idShort']))
        if info and is_cd_ref(info) and info[2] not in global_cd:
            ns = 'project' if 'smart-factory.kr' in info[2] else 'external'
            res['dangling'][ns].append((info[2], n['path']))

    for cd in env.get('conceptDescriptions', []):
        miss = cd_incomplete(cd)
        if miss:
            res['cd_incomplete'].append((cd.get('idShort'), cd.get('id'), miss))
    dup = {k: v for k, v in Counter(cd.get('id') for cd in env.get('conceptDescriptions', [])).items() if v > 1 and k}
    res['dup_cd_id'] = dup

    report['files'][tag] = res

json.dump(report, open(PKG + 'mod_run/_aas_wip_audit.json', 'w', encoding='utf-8'),
          ensure_ascii=False, indent=1, default=lambda o: list(o) if isinstance(o, set) else dict(o))

print(f'{"file":13}{"SM":>4}{"nodes":>7}{"CD":>6}{"idMiss":>8}{"camelV":>8}{"descMiss":>10}{"semMiss":>9}{"dangP":>7}{"dangE":>7}{"cdInc":>7}{"dupId":>7}')
for tag, r in report['files'].items():
    camel = sum(len(v) for v in r['camel_violation'].values())
    dp = len(r['dangling'].get('project', []))
    de = len(r['dangling'].get('external', []))
    print(f'{tag:13}{r["n_submodels"]:>4}{r["n_nodes"]:>7}{r["n_cd"]:>6}{len(r["idShort_missing"]):>8}{camel:>8}'
          f'{len(r["desc_missing"]):>10}{len(r["sem_missing"]):>9}{dp:>7}{de:>7}{len(r["cd_incomplete"]):>7}{len(r["dup_cd_id"]):>7}')
print(f'\n글로벌 CD union: {len(global_cd)}')
