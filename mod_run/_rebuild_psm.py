"""psm(ProvisionOfSimulationModel.json) 을 git HEAD psm_smt 기반 + 세션 편집 재적용으로 재구축.
라운드트립 없이 원본(빈 문자열 보존)에 변경만 적용."""
import subprocess, json, copy
def sh(a): return subprocess.run(a,capture_output=True,text=True,encoding='utf-8',cwd=r'C:/Users/KangTaehui/KG/keti/CPRO_조립공정/시뮬레이션/Package').stdout
base=r'C:/Users/KangTaehui/KG/keti/CPRO_조립공정/시뮬레이션/Package/aas_data/'
CD=lambda s:'https://www.smart-factory.kr/ids/cd/%s/1/0'%s
AAS=lambda s:'https://www.smart-factory.kr/ids/aas/%s/1/0'%s
ASSET=lambda s:'https://www.smart-factory.kr/ids/asset/%s/1/0'%s
def modelref(i): return {'type':'ModelReference','keys':[{'type':'ConceptDescription','value':CD(i)}]}
def extref(i): return {'type':'ExternalReference','keys':[{'type':'GlobalReference','value':CD(i)}]}
def make_cd(idshort,preferred,definition,datatype=None):
    c={'preferredName':[{'language':'en','text':preferred}],'definition':[{'language':'en','text':definition}],'modelType':'DataSpecificationIec61360'}
    if datatype: c['dataType']=datatype
    return {'idShort':idshort,'id':CD(idshort),'embeddedDataSpecifications':[{'dataSpecification':{'type':'ExternalReference','keys':[{'type':'GlobalReference','value':'https://admin-shell.io/DataSpecificationTemplates/DataSpecificationIec61360/3/0'}]},'dataSpecificationContent':c}],'modelType':'ConceptDescription'}
def find(o,name,mt='SubmodelElementCollection'):
    if isinstance(o,dict):
        if o.get('idShort')==name and o.get('modelType')==mt: return o
        for v in o.values():
            r=find(v,name,mt)
            if r is not None: return r
    elif isinstance(o,list):
        for v in o:
            r=find(v,name,mt)
            if r is not None: return r

psm=json.loads(sh(['git','show','HEAD:aas_data/ProvisionOfSimulationModel_smt.json']))
template=json.load(open(base+'IDTA 02026-1-0-1_Template_ProvisionOf3DModels.json',encoding='utf-8'))
modelA=json.load(open(base+'MODEL_A.json',encoding='utf-8'))
log=[]

# ===== 1. Models3D 서브모델 =====
m3d=copy.deepcopy(template['submodels'][0])
sml=m3d['submodelElements'][0]
tmpl_smc=sml['value'][0]
sml['value']=[]
for fac in ['Loader','SPI','ScreenPrinter','Mounter','Reflow','Unloader','AOI']:
    smc=copy.deepcopy(tmpl_smc)
    smc['semanticId']={'type':'ExternalReference','keys':[{'type':'GlobalReference','value':CD(fac+'Model3D')}]}
    sml['value'].append(smc)
psm['submodels'].append(m3d)
psm['assetAdministrationShells'][0]['submodels'].append({'type':'ModelReference','keys':[{'type':'Submodel','value':m3d['id']}]})
psm['conceptDescriptions'].extend(copy.deepcopy(template['conceptDescriptions']))
log.append(f"Models3D SM 추가 (7 SMC, +{len(template['conceptDescriptions'])} CD)")

# ===== 2. SMTProcess 완성 =====
sim=psm['submodels'][0]['submodelElements'][0]
smtp=find(sim,'SMTProcess'); smtlines=find(smtp,'SMTLines'); smtmaterials=find(smtp,'SMTMaterials')
for line in smtlines['value']:
    for fac_smc in line['value']:
        fac=fac_smc['idShort'][:-len('Process')] if fac_smc['idShort'].endswith('Process') else fac_smc['idShort']
        fac_smc['semanticId']={'type':'ExternalReference','keys':[{'type':'AssetAdministrationShell','value':AAS(fac)}]}
        for c in fac_smc['value']:
            if c.get('idShort')=='CycleTime':
                c['idShort']='CycleTimeSec'; c['semanticId']=modelref('CycleTimeSec'); c['value']=extref('CycleTimeSec')
        fac_smc['value']=[c for c in fac_smc['value'] if c.get('idShort')!='n_modules']   # n_modules 삭제
        if not any(c.get('idShort')=='DepType' for c in fac_smc['value']):
            idx=next((i for i,c in enumerate(fac_smc['value']) if c.get('idShort')=='DepPrev'),-1)
            fac_smc['value'].insert(idx+1,{'idShort':'DepType','semanticId':modelref('DepType'),'valueType':'xs:string','value':'SEQUENCE','modelType':'Property'})
for mdl in smtmaterials['value']:
    mdl['semanticId']={'type':'ExternalReference','keys':[{'type':'AssetAdministrationShell','value':ASSET(mdl['idShort'])}]}
log.append("SMTProcess: 설비 semanticId 통일, CycleTime→CycleTimeSec, n_modules 삭제, DepType 추가, SMTMaterials 정렬")

# ===== 3. CD: 중복 제거 + 신설 =====
seen=set(); dedup=[]
for cd in psm['conceptDescriptions']:
    if cd.get('id') in seen: continue
    seen.add(cd.get('id')); dedup.append(cd)
removed_dup=len(psm['conceptDescriptions'])-len(dedup)
psm['conceptDescriptions']=dedup
existing=set(c.get('id') for c in dedup)
EN={'PCB':'Printed circuit board resource flowing through the SMT line. Join key for inter-process material flow.',
 'SolderCream':'Solder cream (solder paste) resource fed into the screen printer.',
 'SolderPastedPCB':'Intermediate product: PCB with solder paste applied (screen printer output).',
 'ChipMountedPCB':'Intermediate product: PCB with chips mounted (mounter output).',
 'ReflowedPCB':'Intermediate product: PCB after reflow soldering (reflow output).',
 'GoodPCB':'PCB that passed AOI inspection (good unit).','DefectPCB':'PCB classified as defective by AOI inspection.',
 'Chips':"Chip component resource that the mounter places onto the PCB; supplied from the PCB's BOM child parts.",
 'Materials':'Operation semantics representing a process resource transformation (input resources to output resources).',
 'SMTProcess':'Container for the entire SMT process.','SMTLines':'Container holding the set of SMT production lines.',
 'Line_1':'SMT production line 1.','Line_2':'SMT production line 2.','SMTMaterials':'Container mapping per-model input resources (e.g., PCB).'}
new_cds=[make_cd(k,k.replace('_',' '),v) for k,v in EN.items()]
new_cds.append(make_cd('DepNext','Successor Process',"The identifier of the successor process or processes that execute after the current manufacturing process step completes. ';'-separated when multiple successors follow (e.g., a shared station routing to each model's next node).",'STRING'))
for fac in ['Loader','SPI','ScreenPrinter','Mounter','Reflow','Unloader','AOI']:
    new_cds.append(make_cd(fac+'Model3D',fac+' 3D Model','Reference concept identifying the 3D model file of the %s equipment provided in the Models3D submodel.'%fac))
# DepType/DepPrev verbatim (모델)
for c in modelA['conceptDescriptions']:
    if c.get('idShort') in ('DepType','DepPrev'): new_cds.append(copy.deepcopy(c))
added=[]
for cd in new_cds:
    if cd['id'] not in existing: psm['conceptDescriptions'].append(cd); existing.add(cd['id']); added.append(cd['idShort'])
log.append(f"CD: 중복제거 {removed_dup}, 신설 {len(added)}")

# ===== 4. 순수 한글 → 영어 =====
KMAP={"재고 상한 (g).":"Maximum stock level (g).","발주량 비율.":"Order quantity ratio.","SMT 라인 정의.":"SMT line definition."}
kfix=[0]
def fixk(o):
    if isinstance(o,dict):
        for t in (o.get('description') or []):
            if isinstance(t,dict) and t.get('text') in KMAP: t['text']=KMAP[t['text']]; t['language']='en'; kfix[0]+=1
        for v in o.values(): fixk(v)
    elif isinstance(o,list):
        for v in o: fixk(v)
fixk(psm)
log.append(f"순수한글 교정 {kfix[0]}")

# ===== 5. Critic.GNNEmbeddingDim example.com → Actor 동일 =====
actor=[None]; critic=[None]
def fg(o,path):
    if isinstance(o,dict):
        if o.get('idShort')=='GNNEmbeddingDim':
            if 'Actor' in path: actor[0]=o
            if 'Critic' in path: critic[0]=o
        for v in o.values(): fg(v,path+'/'+str(o.get('idShort')))
    elif isinstance(o,list):
        for v in o: fg(v,path)
fg(psm,'')
if actor[0] and critic[0]:
    critic[0]['semanticId']=copy.deepcopy(actor[0]['semanticId']); critic[0]['value']=copy.deepcopy(actor[0]['value'])
    log.append("Critic.GNNEmbeddingDim → Actor 동일(example.com 제거)")

# ===== 6. 검증 수정 =====
kg=find(sim,'KnowledgeGraph')
# #1 WWM_FwInputLine BT5_12/13/14 → split
apg=find(kg,'AssignedProcessGroups','SubmodelElementList')
SPLIT={CD('BT5_12'):[CD('BT5_12A'),CD('BT5_12B')],CD('BT5_13'):[CD('BT5_13A'),CD('BT5_13B')],CD('BT5_14'):[CD('BT5_14A'),CD('BT5_14B')]}
fw=next((l for l in apg['value'] if l.get('idShort')=='WWM_FwInputLine'),None)
nk=[]
for k in fw['value']['keys']:
    if k['value'] in SPLIT:
        for nid in SPLIT[k['value']]: nk.append({'type':'GlobalReference','value':nid})
    else: nk.append(k)
fw['value']['keys']=nk
# #5 Semi: BT5_90 제거 + BT5_60 추가
semi=next(l for l in apg['value'] if l.get('idShort')=='WWM_SemiAssemblyLine')
semi['value']['keys']=[k for k in semi['value']['keys'] if k['value']!=CD('BT5_90')]
semi['value']['keys'].append({'type':'GlobalReference','value':CD('BT5_60')})
# #6 RMA Dep 필드 + DependentSequence
rma=find(kg,'RMA')
DEP='VD7_70;VD7_70_1;VD7_70_2;BT5_70;BT5_71;BT5_72;BT5_73;BT5_74;BT5_75;NVD_90;NVD_91;NVD_92'
for ids,val in [('DepType','SEQUENCE'),('DepPrev',DEP),('DepNext',DEP)]:
    if not any(c.get('idShort')==ids for c in rma['value']):
        rma['value'].append({'idShort':ids,'semanticId':modelref(ids),'valueType':'xs:string','value':val,'modelType':'Property'})
action=find(kg,'Action')
depseq=next(c for c in action['value'] if c.get('idShort')=='DependentSequence')
depseq['value'].append({'modelType':'ReferenceElement','value':{'type':'ExternalReference','keys':[{'type':'GlobalReference','value':CD('RMA')}]}})
log.append("검증: #1 WWM_FwInputLine split, #5 semi-set, #6 RMA Dep+seq")

# ===== 저장 (#2 VD7Pagkaging 는 post-string) =====
s=json.dumps(psm,indent=2,ensure_ascii=False).replace('VD7Pagkaging','VD7Packaging')
open(base+'ProvisionOfSimulationModel.json','w',encoding='utf-8').write(s)
print('\n'.join(log))
print(f"\n총 submodels={len(psm['submodels'])} CD={len(psm['conceptDescriptions'])}")
