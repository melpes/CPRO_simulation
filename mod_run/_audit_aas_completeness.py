"""AAS JSON 완전성 감사: description 누락 / semanticId 누락 / CD 없음(dangling) / CD 불완전 / 중복 CD id.

- dangling CD 판정은 6개 파일 CD id 의 글로벌 union 기준 (path_extractor 가 합쳐 로드하므로).
- 보고는 파일별. dangling 은 네임스페이스로 분류 (smart-factory.kr = 프로젝트 CD = 실제 누락 / 그 외 = 외부 표준 = 예상).
- 비-CD semanticId 참조(SM→Submodel, 그리고 Qualifier 는 노드 레벨 아님)는 dangling 검사에서 제외.
- modelType 기준 재귀 (SMC/SML value, Entity statements, ARE annotations, Operation variables).
- psm_smt 의 Models3D 서브트리는 별도 분리(방금 import 한 IDTA 템플릿 — 예상된 미비).
- 콘솔엔 요약(상한), 전체 상세는 markdown 리포트 파일로.
"""
import json
import copy
from collections import Counter, defaultdict

BASE = r'C:/Users/KangTaehui/KG/keti/CPRO_조립공정/시뮬레이션/Package/aas_data/'
REPORT = r'C:/Users/KangTaehui/KG/keti/CPRO_조립공정/시뮬레이션/Package/mod_run/_aas_audit_report.md'

FILES = {
    'MODEL_A':  'MODEL_A.json',
    'MODEL_B':  'MODEL_B.json',
    'MODEL_C':  'MODEL_C.json',
    'wwm':      'WorkstationWorkerMatchingDataAAS.json',
    'psm':      'ProvisionOfSimulationModel.json',
    'psm_smt':  'ProvisionOfSimulationModel_smt.json',
}

RECURSE = {
    'SubmodelElementCollection': lambda e: e.get('value') or [],
    'SubmodelElementList':       lambda e: e.get('value') or [],
    'Entity':                    lambda e: e.get('statements') or [],
    'AnnotatedRelationshipElement': lambda e: e.get('annotations') or [],
}


def text_nonempty(mlp) -> bool:
    if not mlp:
        return False
    return any((d.get('text') or '').strip() for d in mlp)


def sem_info(node):
    """semanticId → (reftype, keytype, value) 또는 None(누락)."""
    s = node.get('semanticId')
    if not s:
        return None
    keys = s.get('keys') or []
    if not keys or not keys[-1].get('value'):
        return None
    return (s.get('type'), keys[-1].get('type'), keys[-1].get('value'))


def is_cd_ref(info) -> bool:
    """이 semanticId 가 CD 로 해소되어야 하는 참조인가."""
    if info is None:
        return False
    reftype, keytype, _ = info
    if reftype == 'ExternalReference' and keytype == 'GlobalReference':
        return True
    if reftype == 'ModelReference' and keytype == 'ConceptDescription':
        return True
    return False  # ModelReference→Submodel 등 제외


def cd_issues(cd):
    """CD 불완전 항목 리스트. unit 은 soft note 로 별도."""
    issues = []
    soft = []
    eds = cd.get('embeddedDataSpecifications')
    if not eds:
        return ['no embeddedDataSpecifications'], []
    content = None
    for ed in eds:
        c = ed.get('dataSpecificationContent')
        if c:
            content = c
            break
    if not content:
        return ['no dataSpecificationContent'], []
    if not text_nonempty(content.get('preferredName')):
        issues.append('no preferredName')
    if not text_nonempty(content.get('definition')):
        issues.append('no definition')
    if not content.get('dataType'):
        issues.append('no dataType')
    if not content.get('unit'):
        soft.append('no unit')
    return issues, soft


def walk(elements, path, parent_type, root_sm, out):
    for i, e in enumerate(elements):
        if not isinstance(e, dict):
            continue
        mt = e.get('modelType')
        ids = e.get('idShort')
        seg = ids if ids is not None else f'[{i}]'
        node_path = f'{path}/{seg}'
        out.append({'path': node_path, 'mt': mt, 'idShort': ids,
                    'parent': parent_type, 'root_sm': root_sm, 'node': e})
        if mt in RECURSE:
            walk(RECURSE[mt](e), node_path, mt, root_sm, out)
        elif mt == 'Operation':
            for vk in ('inputVariables', 'outputVariables', 'inoutputVariables'):
                for ov in e.get(vk) or []:
                    v = ov.get('value')
                    if isinstance(v, dict):
                        walk([v], node_path, 'Operation', root_sm, out)


# ===== 로드 + 글로벌 CD union =====
data = {tag: json.load(open(BASE + fn, encoding='utf-8')) for tag, fn in FILES.items()}
global_cd = {}            # id -> cd (첫 등장)
for tag, d in data.items():
    for cd in d.get('conceptDescriptions', []):
        global_cd.setdefault(cd['id'], cd)


def cd_complete_with_definition(cd_id) -> bool:
    cd = global_cd.get(cd_id)
    if cd is None:
        return False
    hard, _ = cd_issues(cd)
    return ('no definition' not in hard) and ('no embeddedDataSpecifications' not in hard) and ('no dataSpecificationContent' not in hard)


# ===== 파일별 감사 =====
lines = ['# AAS JSON 완전성 감사 리포트', '',
         f'대상: {", ".join(FILES.keys())}',
         'dangling 판정 = 6개 파일 CD id 글로벌 union 기준. (smart-factory.kr = 프로젝트 CD = 실제 / 그 외 = 외부 표준 = 예상)', '']
summary_rows = []

for tag, d in data.items():
    nodes = []
    for sm in d.get('submodels', []):
        root_sm = sm.get('idShort')
        nodes.append({'path': root_sm, 'mt': 'Submodel', 'idShort': root_sm,
                      'parent': 'env', 'root_sm': root_sm, 'node': sm})
        walk(sm.get('submodelElements', []), root_sm, 'Submodel', root_sm, nodes)

    cds = d.get('conceptDescriptions', [])

    def partition(node):
        return 'Models3D' if (tag == 'psm_smt' and node['root_sm'] == 'Models3D') else 'main'

    # 카테고리 수집
    cat = {'main': defaultdict(list), 'Models3D': defaultdict(list)}
    for n in nodes:
        grp = partition(n)
        info = sem_info(n['node'])
        # A. description 누락
        if not text_nonempty(n['node'].get('description')):
            covered = is_cd_ref(info) and cd_complete_with_definition(info[2])
            cat[grp]['descr'].append((n, 'covered' if covered else 'actionable'))
        # B. semanticId 누락
        if info is None:
            cat[grp]['sem'].append(n)
        # C. dangling CD
        elif is_cd_ref(info) and info[2] not in global_cd:
            ns = 'project' if 'smart-factory.kr' in info[2] else 'external'
            cat[grp]['dangling'].append((n, info[2], ns))

    # D. CD 불완전 + E. 중복 id
    cd_incomplete = []
    for cd in cds:
        hard, soft = cd_issues(cd)
        if hard or soft:
            cd_incomplete.append((cd.get('idShort'), cd.get('id'), hard, soft))
    dup_ids = {k: v for k, v in Counter(cd['id'] for cd in cds).items() if v > 1}

    # ---- 요약 카운트 ----
    def counts(grp):
        c = cat[grp]
        descr_action = sum(1 for _, s in c['descr'] if s == 'actionable')
        return {
            'nodes': sum(1 for n in nodes if partition(n) == grp),
            'descr_total': len(c['descr']),
            'descr_action': descr_action,
            'sem': len(c['sem']),
            'dangling_proj': sum(1 for x in c['dangling'] if x[2] == 'project'),
            'dangling_ext': sum(1 for x in c['dangling'] if x[2] == 'external'),
        }
    cm = counts('main')
    summary_rows.append((tag, len([n for n in nodes if n['mt'] == 'Submodel']),
                         cm['nodes'], len(cds), cm['descr_total'], cm['descr_action'],
                         cm['sem'], cm['dangling_proj'], cm['dangling_ext'],
                         len([x for x in cd_incomplete if x[2]]),
                         len(dup_ids)))

    # ---- 리포트 본문 ----
    lines.append(f'\n## {tag}  (`{FILES[tag]}`)')
    lines.append(f'- Submodel {len([n for n in nodes if n["mt"]=="Submodel"])}개 · '
                 f'SME {cm["nodes"]-len([n for n in nodes if n["mt"]=="Submodel"]) if False else len([n for n in nodes if n["mt"]!="Submodel" and partition(n)=="main"])}개(main) · CD {len(cds)}개')
    if dup_ids:
        lines.append(f'- **중복 CD id**: ' + '; '.join(f'`{k.split("/ids/cd/")[-1]}` ×{v}' for k, v in dup_ids.items()))

    def dump_cat(grp, header):
        c = cat[grp]
        lines.append(f'\n### [{header}]')
        # A
        act = [n for n, s in c['descr'] if s == 'actionable']
        cov = [n for n, s in c['descr'] if s == 'covered']
        lines.append(f'**A. description 누락**: 총 {len(c["descr"])} (actionable {len(act)} / CD로 커버 {len(cov)})')
        if act:
            byk = Counter((n['mt'], n['parent']) for n in act)
            lines.append('  - actionable (CD 정의도 없음) modelType×parent: ' +
                         ', '.join(f'{mt}@{p}×{cnt}' for (mt, p), cnt in byk.most_common()))
            for n in act[:30]:
                lines.append(f'    - `{n["path"]}` ({n["mt"]}, parent={n["parent"]}, idShort={n["idShort"]})')
            if len(act) > 30:
                lines.append(f'    - … 외 {len(act)-30}개')
        # B
        lines.append(f'**B. semanticId 누락**: {len(c["sem"])}')
        if c['sem']:
            byk = Counter((n['mt'], n['parent'], n['idShort'] is None) for n in c['sem'])
            lines.append('  - modelType×parent×(idShort없음): ' +
                         ', '.join(f'{mt}@{p}{"(익명)" if anon else ""}×{cnt}' for (mt, p, anon), cnt in byk.most_common()))
            for n in c['sem'][:30]:
                lines.append(f'    - `{n["path"]}` ({n["mt"]}, parent={n["parent"]}, idShort={n["idShort"]})')
            if len(c['sem']) > 30:
                lines.append(f'    - … 외 {len(c["sem"])-30}개')
        # C
        proj = [x for x in c['dangling'] if x[2] == 'project']
        ext = [x for x in c['dangling'] if x[2] == 'external']
        lines.append(f'**C. dangling CD (참조하나 CD 없음)**: project {len(proj)} / external {len(ext)}')
        for label, lst in (('project(실제 누락)', proj), ('external(예상)', ext)):
            if lst:
                uniq = Counter(x[1] for x in lst)
                lines.append(f'  - {label}: 고유 {len(uniq)}종')
                for cid, cnt in uniq.most_common(40):
                    lines.append(f'    - `{cid}` ×{cnt}')
                if len(uniq) > 40:
                    lines.append(f'    - … 외 {len(uniq)-40}종')

    dump_cat('main', 'main (시뮬 모델 본체)')
    if any(cat['Models3D'].values()):
        dump_cat('Models3D', 'Models3D 서브트리 — 방금 import 한 IDTA 3D 템플릿 (미비는 예상됨)')

    # D
    hard_inc = [x for x in cd_incomplete if x[2]]
    soft_inc = [x for x in cd_incomplete if not x[2] and x[3]]
    lines.append(f'\n### [CD 불완전] hard {len(hard_inc)} / soft(unit만) {len(soft_inc)}')
    if hard_inc:
        byk = Counter(tuple(x[2]) for x in hard_inc)
        lines.append('  - 결함 조합 분포: ' + '; '.join(f'{"+".join(k)}×{v}' for k, v in byk.most_common()))
        for ids, cid, hard, soft in hard_inc[:40]:
            lines.append(f'    - `{ids}` ({cid.split("/ids/cd/")[-1] if "/ids/cd/" in cid else cid}): {", ".join(hard)}' + (f' [+soft {",".join(soft)}]' if soft else ''))
        if len(hard_inc) > 40:
            lines.append(f'    - … 외 {len(hard_inc)-40}개')

# ===== 요약 테이블 =====
hdr = ['file', 'SM', 'SME(main)', 'CD', 'descrMiss', 'descrAction', 'semMiss', 'dangProj', 'dangExt', 'cdInc', 'dupId']
tbl = ['', '## 요약 테이블 (main 기준)', '', '| ' + ' | '.join(hdr) + ' |', '|' + '---|' * len(hdr)]
for r in summary_rows:
    tbl.append('| ' + ' | '.join(str(x) for x in r) + ' |')

report = '\n'.join([tbl_line for tbl_line in tbl] + [''] + lines)
open(REPORT, 'w', encoding='utf-8').write(report)

# 콘솔: 요약 테이블만
print('\n'.join(tbl))
print(f'\n전체 상세 리포트 → {REPORT}')
