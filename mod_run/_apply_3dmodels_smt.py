"""일회성: (1) MODEL_B 에서 AgingTestDurationSec CD 제거,
(2) psm_smt 에 ProvisionOf3DModels 템플릿의 Models3D SM 추가
    - SM/SML 그대로, SML 하위 SMC 를 SMT 7설비(AOI 마지막)용으로 7개 복제 + semanticId 변경
    - 템플릿 CD 98개 그대로 psm_smt 에 복붙
모든 파일은 원본 포맷(indent, ensure_ascii=False, no trailing newline) 보존."""
import json
import copy

BASE = r'C:/Users/KangTaehui/KG/keti/CPRO_조립공정/시뮬레이션/Package/aas_data/'

MODEL_B  = BASE + 'MODEL_B.json'
PSM_SMT  = BASE + 'ProvisionOfSimulationModel_smt.json'
TEMPLATE = BASE + 'IDTA 02026-1-0-1_Template_ProvisionOf3DModels.json'

AGING_CD_ID = 'https://www.smart-factory.kr/ids/cd/AgingTestDurationSec/1/0'

# 공정 순서 (AOI 가 파일번호 5 이지만 공정상 마지막)
FACILITIES = ['Loader', 'SPI', 'ScreenPrinter', 'Mounter', 'Reflow', 'Unloader', 'AOI']
FACILITY_CD = 'https://www.smart-factory.kr/ids/cd/{name}Model3D/1/0'


def load(path):
    return json.load(open(path, encoding='utf-8'))


def write(path, data, indent):
    # 원본은 trailing newline 없음 → json.dumps 출력 그대로(개행 미추가)
    with open(path, 'w', encoding='utf-8') as file:
        file.write(json.dumps(data, indent=indent, ensure_ascii=False))


# ========== (1) MODEL_B: AgingTestDurationSec CD 제거 ==========
model_b = load(MODEL_B)
before = len(model_b['conceptDescriptions'])
model_b['conceptDescriptions'] = [cd for cd in model_b['conceptDescriptions'] if cd['id'] != AGING_CD_ID]
after = len(model_b['conceptDescriptions'])
assert before - after == 1, f'AgingTestDurationSec 제거 실패: {before}->{after}'
write(MODEL_B, model_b, indent=1)
print(f'[MODEL_B] conceptDescriptions {before} -> {after} (AgingTestDurationSec 제거)')

# ========== (2) psm_smt: Models3D SM 추가 ==========
template = load(TEMPLATE)
psm = load(PSM_SMT)

models3d_sm = copy.deepcopy(template['submodels'][0])          # SM Models3D (그대로)
sml = models3d_sm['submodelElements'][0]                       # SML Model3D (그대로)
assert sml['idShort'] == 'Model3D' and sml['modelType'] == 'SubmodelElementList'
template_smc = sml['value'][0]                                 # 복제 대상 SMC 1개

new_smcs = []
for name in FACILITIES:
    smc = copy.deepcopy(template_smc)
    smc['semanticId'] = {                                      # 설비별 semanticId 로 교체
        'type': 'ExternalReference',
        'keys': [{'type': 'GlobalReference', 'value': FACILITY_CD.format(name=name)}],
    }
    new_smcs.append(smc)
sml['value'] = new_smcs

# AAS shell 에 새 submodel 참조 추가
psm['assetAdministrationShells'][0]['submodels'].append({
    'type': 'ModelReference',
    'keys': [{'type': 'Submodel', 'value': models3d_sm['id']}],
})
# submodel 본체 추가
psm['submodels'].append(models3d_sm)
# 템플릿 CD 98개 그대로 복붙
cd_before = len(psm['conceptDescriptions'])
psm['conceptDescriptions'].extend(copy.deepcopy(template['conceptDescriptions']))
cd_after = len(psm['conceptDescriptions'])

write(PSM_SMT, psm, indent=2)
print(f'[psm_smt] submodels +1 (Models3D), SMC {len(new_smcs)}개, CD {cd_before} -> {cd_after}')
