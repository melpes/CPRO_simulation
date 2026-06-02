"""검증 발견 #1~#7 을 wip/ .aasx 직접 수정. (json 은 이후 삭제)
 psm: #1 WWM_FwInputLine BT5_12/13/14→12A/12B.. (6키), #2 VD7Pagkaging→VD7Packaging, #6 RMA Dep필드+DependentSequence(OQC 미러)
 MODEL_B: #3 MODEL_B_NVD1→MODEL_B_BT5 (전역)
 MODEL_A: #7 PCB+03903424→PCB_03903424 + ref value 공백 트림, #4 gimbal CD id교정 + VD7FwInput/WORKER_SET/WORKER_FW CD 신설
 MODEL_C: #4 WORKER_FW/NO44_FW_JIG CD 신설 + 공백 트림
 wwm: #4 UnitsPerWorker CD 신설
"""
import zipfile, posixpath
import xml.etree.ElementTree as ET

NS_URL='https://admin-shell.io/aas/3/0'; NS='{%s}'%NS_URL
ET.register_namespace('', NS_URL)
WIP=r'C:/Users/KangTaehui/KG/keti/CPRO_조립공정/시뮬레이션/Package/aas_data/wip/'
CD=lambda s:'https://www.smart-factory.kr/ids/cd/%s/1/0'%s
def lname(t): return t.replace(NS,'')
def E(tag,text=None):
    e=ET.Element(NS+tag)
    if text is not None: e.text=text
    return e
def gref_key(cd_id):
    k=E('key'); k.append(E('type','GlobalReference')); k.append(E('value',cd_id)); return k
def make_cd(idshort,preferred,definition,datatype='STRING'):
    cd=E('conceptDescription'); cd.append(E('idShort',idshort)); cd.append(E('id',CD(idshort)))
    eds=E('embeddedDataSpecifications'); ed=E('embeddedDataSpecification')
    ds=E('dataSpecification'); ds.append(E('type','ExternalReference')); ks=E('keys'); k=E('key')
    k.append(E('type','GlobalReference')); k.append(E('value','https://admin-shell.io/DataSpecificationTemplates/DataSpecificationIec61360/3/0'))
    ks.append(k); ds.append(ks); ed.append(ds)
    cont=E('dataSpecificationContent'); iec=E('dataSpecificationIec61360')
    pn=E('preferredName'); ls=E('langStringPreferredNameTypeIec61360'); ls.append(E('language','en')); ls.append(E('text',preferred)); pn.append(ls); iec.append(pn)
    if datatype: iec.append(E('dataType',datatype))
    df=E('definition'); ls2=E('langStringDefinitionTypeIec61360'); ls2.append(E('language','en')); ls2.append(E('text',definition)); df.append(ls2); iec.append(df)
    cont.append(iec); ed.append(cont); eds.append(ed); cd.append(eds); return cd
def prop(idshort,cd_id,valuetype,value):
    p=E('property'); p.append(E('idShort',idshort))
    sem=E('semanticId'); sem.append(E('type','ModelReference')); ks=E('keys'); k=E('key'); k.append(E('type','ConceptDescription')); k.append(E('value',cd_id)); ks.append(k); sem.append(ks)
    p.append(sem); p.append(E('valueType',valuetype)); p.append(E('value',value)); return p
def findall(root,tags): return [e for e in root.iter() if lname(e.tag) in tags]

def load_xml(zf):
    with zipfile.ZipFile(WIP+zf) as z:
        names=z.namelist(); data={n:z.read(n) for n in names}
    inner=[n for n in names if n.endswith('.aas.xml')][0]
    return names,data,inner
def save(zf,names,data):
    with zipfile.ZipFile(WIP+zf,'w',zipfile.ZIP_DEFLATED) as zo:
        for n in names: zo.writestr(n,data[n])

log=[]
# ===== MODEL_B: #3 (pure string) =====
names,data,inner=load_xml('MODEL_B.aasx')
xml=data[inner].decode('utf-8'); c=xml.count('MODEL_B_NVD1')
data[inner]=xml.replace('MODEL_B_NVD1','MODEL_B_BT5').encode('utf-8'); save('MODEL_B.aasx',names,data)
log.append(f"MODEL_B: #3 MODEL_B_NVD1→MODEL_B_BT5 ({c}회)")

# ===== psm: #1 #2 #6 =====
names,data,inner=load_xml('ProvisionOfSimulationModel.aasx')
xml=data[inner].decode('utf-8'); n2=xml.count('VD7Pagkaging')
xml=xml.replace('VD7Pagkaging','VD7Packaging')          # #2
root=ET.fromstring(xml.encode('utf-8'))
# #1 WWM_FwInputLine keys 교체
SPLIT={CD('BT5_12'):[CD('BT5_12A'),CD('BT5_12B')],CD('BT5_13'):[CD('BT5_13A'),CD('BT5_13B')],CD('BT5_14'):[CD('BT5_14A'),CD('BT5_14B')]}
n1=0
for re_el in findall(root,('referenceElement',)):
    if re_el.findtext(NS+'idShort')=='WWM_FwInputLine':
        keysel=re_el.find(NS+'value/'+NS+'keys')
        newkeys=[]
        for k in list(keysel):
            v=k.findtext(NS+'value')
            if v in SPLIT:
                for nid in SPLIT[v]: newkeys.append(gref_key(nid)); n1+=1
            else: newkeys.append(k)
        for k in list(keysel): keysel.remove(k)
        for k in newkeys: keysel.append(k)
# #6 RMA: Dep 필드 + DependentSequence
rma=next((e for e in findall(root,('submodelElementCollection',)) if e.findtext(NS+'idShort')=='RMA'),None)
rv=rma.find(NS+'value')
for ids,val in [('DepType','SEQUENCE'),('DepPrev','VD7_100;BT5_110;NVD_110'),('DepNext','VD7_110;BT5_120;NVD_120')]:
    if not any(c.findtext(NS+'idShort')==ids for c in rv): rv.append(prop(ids,CD(ids),'xs:string',val))
depseq=next((e for e in findall(root,('submodelElementList',)) if e.findtext(NS+'idShort')=='DependentSequence'),None)
re_rma=E('referenceElement'); val=E('value'); val.append(E('type','ExternalReference')); ks=E('keys'); ks.append(gref_key(CD('RMA'))); val.append(ks); re_rma.append(val)
depseq.find(NS+'value').append(re_rma)
data[inner]=ET.tostring(root,encoding='utf-8',xml_declaration=True); save('ProvisionOfSimulationModel.aasx',names,data)
log.append(f"psm: #2 VD7Pagkaging→VD7Packaging({n2}), #1 BT5_12/13/14→split({n1}키 추가), #6 RMA Dep3+DependentSequence")

# ===== 공백 트림 헬퍼 =====
def trim_values(root):
    n=0
    for e in root.iter():
        if lname(e.tag)=='value' and e.text and e.text!=e.text.strip():
            e.text=e.text.strip(); n+=1
    return n

# ===== MODEL_A: #7 + #4 =====
names,data,inner=load_xml('MODEL_A.aasx')
xml=data[inner].decode('utf-8'); n7=xml.count('PCB+03903424')
xml=xml.replace('PCB+03903424','PCB_03903424')           # #7 typo
root=ET.fromstring(xml.encode('utf-8'))
ntrim=trim_values(root)                                  # #7 공백
# gimbal CD id 교정
fixed=0
for cd in findall(root,('conceptDescription',)):
    if cd.findtext(NS+'idShort')=='VD7GimbalAssembly' and cd.findtext(NS+'id')==CD('WORKER_SET'):
        cd.find(NS+'id').text=CD('VD7GimbalAssembly'); fixed+=1
cds=root.find(NS+'conceptDescriptions')
NEW_A=[make_cd('VD7FwInput','VD7FwInput','A manufacturing process group for the firmware/front-end input stage of the VD7 camera model.'),
       make_cd('WORKER_SET','WORKER_SET','Worker group identifier for the set-assembly stage.'),
       make_cd('WORKER_FW','WORKER_FW','Worker group identifier for the firmware-input stage.')]
exist=set(c.findtext(NS+'id') for c in findall(root,('conceptDescription',)))
addedA=[]
for cd in NEW_A:
    if cd.findtext(NS+'id') not in exist: cds.append(cd); addedA.append(cd.findtext(NS+'idShort'))
data[inner]=ET.tostring(root,encoding='utf-8',xml_declaration=True); save('MODEL_A.aasx',names,data)
log.append(f"MODEL_A: #7 PCB+→PCB_({n7})+공백트림({ntrim}), #4 gimbalCD id교정({fixed})+신설{addedA}")

# ===== MODEL_C: #4 =====
names,data,inner=load_xml('MODEL_C.aasx')
root=ET.fromstring(data[inner])
ntrimC=trim_values(root)
cds=root.find(NS+'conceptDescriptions')
NEW_C=[make_cd('WORKER_FW','WORKER_FW','Worker group identifier for the firmware-input stage.'),
       make_cd('NO44_FW_JIG','NO44_FW_JIG','Jig/fixture identifier (No.44 FW jig) used in the firmware-input process.')]
exist=set(c.findtext(NS+'id') for c in findall(root,('conceptDescription',)))
addedC=[]
for cd in NEW_C:
    if cd.findtext(NS+'id') not in exist: cds.append(cd); addedC.append(cd.findtext(NS+'idShort'))
data[inner]=ET.tostring(root,encoding='utf-8',xml_declaration=True); save('MODEL_C.aasx',names,data)
log.append(f"MODEL_C: 공백트림({ntrimC}), #4 신설{addedC}")

# ===== wwm: #4 UnitsPerWorker =====
names,data,inner=load_xml('WorkstationWorkerMatchingDataAAS.aasx')
root=ET.fromstring(data[inner])
cds=root.find(NS+'conceptDescriptions')
exist=set(c.findtext(NS+'id') for c in findall(root,('conceptDescription',)))
addedW=[]
if CD('UnitsPerWorker') not in exist:
    cds.append(make_cd('UnitsPerWorker','UnitsPerWorker','Number of product units a single worker monitors concurrently on this line; absent defaults to 1.','INTEGER_COUNT'))
    addedW.append('UnitsPerWorker')
data[inner]=ET.tostring(root,encoding='utf-8',xml_declaration=True); save('WorkstationWorkerMatchingDataAAS.aasx',names,data)
log.append(f"wwm: #4 신설{addedW}")

print('\n'.join(log))
EOF