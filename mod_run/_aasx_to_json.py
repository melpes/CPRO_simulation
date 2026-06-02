"""AAS .aasx(XML) → AAS JSON 충실 변환 (이 프로젝트 데이터에 나타나는 패턴 전부 처리).
손실 없음을 요소 카운트로 검증."""
import zipfile, json, sys
import xml.etree.ElementTree as ET

NS_URL='https://admin-shell.io/aas/3/0'; NS='{%s}'%NS_URL
def ln(t): return t.replace(NS,'')

SME_MT={'property':'Property','multiLanguageProperty':'MultiLanguageProperty','range':'Range','blob':'Blob',
        'file':'File','referenceElement':'ReferenceElement','relationshipElement':'RelationshipElement',
        'annotatedRelationshipElement':'AnnotatedRelationshipElement','submodelElementCollection':'SubmodelElementCollection',
        'submodelElementList':'SubmodelElementList','entity':'Entity','capability':'Capability','operation':'Operation',
        'basicEventElement':'BasicEventElement'}
ID_MT={'submodel':'Submodel','conceptDescription':'ConceptDescription','assetAdministrationShell':'AssetAdministrationShell'}
ARRAY={'assetAdministrationShells','submodels','conceptDescriptions','submodelElements','statements',
       'qualifiers','keys','embeddedDataSpecifications','isCaseOf','supplementalSemanticIds',
       'inputVariables','outputVariables','inoutputVariables','valueReferencePairs','annotations','specificAssetIds'}
LANGSTRING={'description','displayName','preferredName','shortName','definition'}

def langset(e):
    out=[]
    for ls in list(e):
        out.append({'language':ls.findtext(NS+'language'),'text':ls.findtext(NS+'text')})
    return out

def conv(e, parent_tag=None):
    tag=ln(e.tag); kids=list(e)
    if not kids:
        return e.text   # leaf text
    if tag in LANGSTRING:
        return langset(e)
    if tag=='dataSpecificationContent':
        iec=kids[0]                      # dataSpecificationIec61360 평탄화
        d=obj(iec); d['modelType']='DataSpecificationIec61360'; return d
    if tag in ARRAY:
        return [conv(c,tag) for c in kids]
    if tag=='value':
        if parent_tag in ('submodelElementCollection','submodelElementList'):
            return [conv(c,tag) for c in kids]
        if parent_tag=='multiLanguageProperty':
            return langset(e)
        if parent_tag=='operationVariable':
            return conv(kids[0],tag)
        # referenceElement.value / 기타 Reference: type+keys 객체
        return obj(e)
    return obj(e)

def obj(e):
    d={}
    t=ln(e.tag)
    if t in SME_MT: d['modelType']=SME_MT[t]
    elif t in ID_MT: d['modelType']=ID_MT[t]
    for c in list(e):
        d[ln(c.tag)]=conv(c, t)
    return d

def xml_to_env(xml_bytes):
    root=ET.fromstring(xml_bytes)
    env={}
    for c in list(root):
        env[ln(c.tag)]=conv(c, 'environment')
    return env

# ===== 검증: XML 요소 카운트 vs JSON 산출 카운트 =====
def count_xml(xml_bytes):
    root=ET.fromstring(xml_bytes); c={}
    for e in root.iter():
        c[ln(e.tag)]=c.get(ln(e.tag),0)+1
    return c
def count_json(o, c=None):
    if c is None: c={}
    if isinstance(o,dict):
        mt=o.get('modelType')
        if mt: c[mt]=c.get(mt,0)+1
        for v in o.values(): count_json(v,c)
    elif isinstance(o,list):
        for v in o: count_json(v,c)
    return c

if __name__=='__main__':
    aasx=sys.argv[1]; outjson=sys.argv[2] if len(sys.argv)>2 else None
    z=zipfile.ZipFile(aasx); inner=[n for n in z.namelist() if n.endswith('.aas.xml')][0]
    xb=z.read(inner)
    env=xml_to_env(xb)
    xc=count_xml(xb); jc=count_json(env)
    # SME/Identifiable 타입별 XML태그수 vs JSON modelType수 대조
    print(f"[{aasx.split('/')[-1]}]")
    mismatch=0
    for tag,mt in {**SME_MT,**ID_MT}.items():
        if xc.get(tag,0)!=jc.get(mt,0):
            print(f"  MISMATCH {tag}({mt}): XML {xc.get(tag,0)} vs JSON {jc.get(mt,0)}"); mismatch+=1
    print(f"  submodels={len(env.get('submodels',[]))} CDs={len(env.get('conceptDescriptions',[]))} AAS={len(env.get('assetAdministrationShells',[]))} | 타입 mismatch={mismatch}")
    if outjson:
        open(outjson,'w',encoding='utf-8').write(json.dumps(env,indent=2,ensure_ascii=False))
        print(f"  → {outjson}")
