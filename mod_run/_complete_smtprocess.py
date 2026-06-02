"""wip/ProvisionOfSimulationModel_smt.json 의 SMTProcess 완성 + semanticId 설비 통일 + CD 적당히 채움.
원본 미수정(wip 복사본만). 통일 스킴은 보고서/주석 참조."""
import json, copy

WIP = r'C:/Users/KangTaehui/KG/keti/CPRO_조립공정/시뮬레이션/Package/aas_data/wip/'
PSM_SMT = WIP + 'ProvisionOfSimulationModel_smt.json'
CD = 'https://www.smart-factory.kr/ids/cd/{}/1/0'
AAS = 'https://www.smart-factory.kr/ids/aas/{}/1/0'       # 설비 AAS id
ASSET_MODEL = 'https://www.smart-factory.kr/ids/asset/{}/1/0'  # 모델 globalAssetId


def find(container, idshort):
    return next(c for c in container['value'] if c.get('idShort') == idshort)


def modelref_cd(idshort):
    return {'type': 'ModelReference', 'keys': [{'type': 'ConceptDescription', 'value': CD.format(idshort)}]}


def extref_cd(idshort):
    return {'type': 'ExternalReference', 'keys': [{'type': 'GlobalReference', 'value': CD.format(idshort)}]}


def make_cd(idshort, preferred, definition, datatype=None):
    content = {'preferredName': [{'language': 'en', 'text': preferred}],
               'definition': [{'language': 'en', 'text': definition}],
               'modelType': 'DataSpecificationIec61360'}
    if datatype:
        content['dataType'] = datatype
    return {'idShort': idshort, 'id': CD.format(idshort),
            'embeddedDataSpecifications': [{
                'dataSpecification': {'type': 'ExternalReference', 'keys': [{'type': 'GlobalReference',
                    'value': 'https://admin-shell.io/DataSpecificationTemplates/DataSpecificationIec61360/3/0'}]},
                'dataSpecificationContent': content}],
            'modelType': 'ConceptDescription'}


d = json.load(open(PSM_SMT, encoding='utf-8'))
sim = d['submodels'][0]['submodelElements'][0]
smtp = find(sim, 'SMTProcess')
smtlines = find(smtp, 'SMTLines')
smtmaterials = find(smtp, 'SMTMaterials')

log = []
# ===== 1) 라인별 설비공정 SMC 수정 =====
for line in smtlines['value']:                       # Line_1, Line_2
    for fac_smc in line['value']:                    # 7 설비공정 SMC
        ids = fac_smc.get('idShort', '')
        fac = ids[:-len('Process')] if ids.endswith('Process') else ids
        # 1-a) 설비 식별 통일: SMC.semanticId → 설비 AAS id (이름 무관)
        fac_smc['semanticId'] = {'type': 'ExternalReference',
                                 'keys': [{'type': 'AssetAdministrationShell', 'value': AAS.format(fac)}]}
        children = fac_smc['value']
        # 1-b) CycleTime → CycleTimeSec (정준)
        for c in children:
            if c.get('idShort') == 'CycleTime':
                c['idShort'] = 'CycleTimeSec'
                c['semanticId'] = modelref_cd('CycleTimeSec')
                c['value'] = extref_cd('CycleTimeSec')
            if c.get('idShort') == 'n_modules':       # 1-d) n_modules → NModules
                c['idShort'] = 'NModules'
                c['semanticId'] = modelref_cd('NModules')
        # 1-c) DepType Property 추가 (DepPrev 다음 위치)
        if not any(c.get('idShort') == 'DepType' for c in children):
            dep_idx = next((i for i, c in enumerate(children) if c.get('idShort') == 'DepPrev'), -1)
            dep_type = {'idShort': 'DepType', 'semanticId': modelref_cd('DepType'),
                        'valueType': 'xs:string', 'value': 'SEQUENCE', 'modelType': 'Property'}
            children.insert(dep_idx + 1, dep_type)
    log.append(f'{line["idShort"]}: {len(line["value"])} 설비공정 수정(식별 통일/CycleTimeSec/DepType)')

# ===== 2) SMTMaterials.MODEL_X semanticId → 모델 globalAssetId 재사용 =====
for mdl in smtmaterials['value']:
    mdl['semanticId'] = {'type': 'ExternalReference',
                         'keys': [{'type': 'AssetAdministrationShell', 'value': ASSET_MODEL.format(mdl['idShort'])}]}
log.append(f'SMTMaterials: {len(smtmaterials["value"])} 모델 자산참조 재사용')

# ===== 3) conceptDescriptions: 중복 제거 + 누락 CD 신설 =====
cds = d['conceptDescriptions']
# 3-a) RatedPowerKw 중복 제거(첫 항목만)
seen, deduped = set(), []
removed_dup = 0
for cd in cds:
    if cd.get('id') in seen:
        removed_dup += 1
        continue
    seen.add(cd.get('id')); deduped.append(cd)
d['conceptDescriptions'] = deduped
cds = deduped
existing_ids = set(c.get('id') for c in cds)

# 3-b) 누락 CD 신설 (적당히: preferredName+definition, 값형은 dataType)
NEW_CDS = [
    make_cd('PCB', 'PCB', 'SMT 라인을 흐르는 인쇄회로기판 자원. 공정 간 물질흐름 join key.'),
    make_cd('SolderCream', 'Solder Cream', '스크린프린터 투입 솔더크림(솔더 페이스트) 자원.'),
    make_cd('SolderPastedPCB', 'Solder-pasted PCB', '솔더가 도포된 PCB 중간 산출물(스크린프린터 출력).'),
    make_cd('ChipMountedPCB', 'Chip-mounted PCB', '칩이 실장된 PCB 중간 산출물(마운터 출력).'),
    make_cd('ReflowedPCB', 'Reflowed PCB', '리플로우 솔더링이 완료된 PCB 중간 산출물(리플로우 출력).'),
    make_cd('GoodPCB', 'Good PCB', 'AOI 검사를 통과한 양품 PCB.'),
    make_cd('DefectPCB', 'Defect PCB', 'AOI 검사에서 불량으로 분류된 PCB.'),
    make_cd('Chips', 'Chips', '마운터가 PCB에 실장하는 칩 부품 자원. 해당 PCB의 BOM 하위 부품에서 공급.'),
    make_cd('Materials', 'Materials', '공정의 자원 변환(입력 자원→출력 자원)을 나타내는 Operation 의미.'),
    make_cd('SMTProcess', 'SMT Process', 'SMT 공정 전체를 담는 컨테이너.'),
    make_cd('SMTLines', 'SMT Lines', 'SMT 생산 라인 집합 컨테이너.'),
    make_cd('Line_1', 'Line 1', 'SMT 생산 라인 1.'),
    make_cd('Line_2', 'Line 2', 'SMT 생산 라인 2.'),
    make_cd('SMTMaterials', 'SMT Materials', '모델별 투입 자원(PCB 등) 매핑 컨테이너.'),
    make_cd('NModules', 'Number of Modules', '설비 동시 가동 모듈/헤드 수(마운터 병렬성).', 'INTEGER_COUNT'),
    make_cd('DepType', 'Dependency Type', '공정 의존 유형. SEQUENCE(선행 완료시 ready) 또는 JOIN.', 'STRING'),
    make_cd('DepPrev', 'Predecessor Process', "선행 공정 idShort(';' 구분). 라인 토폴로지 정의.", 'STRING'),
]
added = []
for cd in NEW_CDS:
    if cd['id'] not in existing_ids:
        cds.append(cd); added.append(cd['idShort'])

# ===== 저장 (원본 포맷 보존: indent=2, ensure_ascii=False, no trailing newline) =====
open(PSM_SMT, 'w', encoding='utf-8').write(json.dumps(d, indent=2, ensure_ascii=False))

print('\n'.join(log))
print(f'\nRatedPowerKw 등 중복 CD 제거: {removed_dup}')
print(f'신설 CD ({len(added)}): {added}')
print(f'최종 CD 수: {len(cds)}')
