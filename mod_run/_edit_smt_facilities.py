"""wip/ 의 7 설비 .aasx 편집:
 - RatedPower → RatedPowerKw (MCF 위치 유지, idShort/id/preferredName 만, def·unit·dataType 보존)
 - CycleTimeSec: ScreenPrinter는 PrintingPerformance 의 기존 CycleTime rename(초단위, CD unit/symbol/dataType=psm, def 보존),
   나머지 6설비는 성능영역 최상위에 CycleTimeSec Property 신규(값 비움) + CycleTimeSec CD(=psm) 신설.
원본 SMT/ 미수정. ET 편집 후 재패키징 + 재파싱 검증."""
import zipfile, io, copy
import xml.etree.ElementTree as ET

NS_URL = 'https://admin-shell.io/aas/3/0'
NS = '{%s}' % NS_URL
ET.register_namespace('', NS_URL)
WIP = r'C:/Users/KangTaehui/KG/keti/CPRO_조립공정/시뮬레이션/Package/aas_data/wip/'

# psm 정렬 기준
CTS_DEF = ("The time required to complete one unit of work at a manufacturing process step, measured in seconds. "
           "Used in discrete event simulation to define the duration of a process step timeout. "
           "Represents the standard cycle time under normal operating conditions with the assigned worker group and equipment.")
CD = lambda s: 'https://www.smart-factory.kr/ids/cd/%s/1/0' % s

FAC = {  # fac: (aasx, inner, performance_area)
    'Loader': ('1_Loader.aasx', 'aasx/Loader/Loader.aas.xml', 'PCBOutput'),
    'SPI': ('2_SPI.aasx', 'aasx/SPI/SPI.aas.xml', 'InspectionPerformance'),
    'ScreenPrinter': ('3_ScreenPrinter.aasx', 'aasx/ScreenPrinter/ScreenPrinter.aas.xml', 'PrintingPerformance'),
    'Mounter': ('4_Mounter.aasx', 'aasx/Mounter/Mounter.aas.xml', 'PlacementPerformance'),
    'AOI': ('5_AOI.aasx', 'aasx/AOI/AOI.aas.xml', 'InspectionPerformance'),
    'Reflow': ('6_Reflow.aasx', 'aasx/Reflow/Reflow.aas.xml', 'ThermalPerformance'),
    'Unloader': ('7_Unloader.aasx', 'aasx/Unloader/Unloader.aas.xml', 'PCBInput'),
}
def lname(t): return t.replace(NS, '')
def E(tag, text=None):
    el = ET.Element(NS + tag)
    if text is not None: el.text = text
    return el

def modelref_semid(cd_id):
    sem = E('semanticId'); sem.append(E('type', 'ModelReference'))
    keys = E('keys'); key = E('key'); key.append(E('type', 'ConceptDescription')); key.append(E('value', cd_id))
    keys.append(key); sem.append(keys); return sem

def make_cyc_property():
    p = E('property')
    p.append(E('idShort', 'CycleTimeSec'))
    p.append(modelref_semid(CD('CycleTimeSec')))
    p.append(E('valueType', 'xs:integer'))     # 값 비움(value element 생략)
    return p

def make_cts_cd():
    cd = E('conceptDescription')
    cd.append(E('idShort', 'CycleTimeSec')); cd.append(E('id', CD('CycleTimeSec')))
    eds = E('embeddedDataSpecifications'); ed = E('embeddedDataSpecification')
    ds = E('dataSpecification'); ds.append(E('type', 'ExternalReference'))
    ks = E('keys'); k = E('key'); k.append(E('type', 'GlobalReference'))
    k.append(E('value', 'https://admin-shell.io/DataSpecificationTemplates/DataSpecificationIec61360/3/0'))
    ks.append(k); ds.append(ks); ed.append(ds)
    content = E('dataSpecificationContent'); iec = E('dataSpecificationIec61360')
    pn = E('preferredName'); ls = E('langStringPreferredNameTypeIec61360'); ls.append(E('language', 'en')); ls.append(E('text', 'CycleTimeSec')); pn.append(ls); iec.append(pn)
    iec.append(E('unit', 's')); iec.append(E('symbol', 'CT')); iec.append(E('dataType', 'INTEGER_COUNT'))
    df = E('definition'); ls2 = E('langStringDefinitionTypeIec61360'); ls2.append(E('language', 'en')); ls2.append(E('text', CTS_DEF)); df.append(ls2); iec.append(df)
    content.append(iec); ed.append(content); eds.append(ed); cd.append(eds)
    return cd

def find_all(root, tags):
    return [e for e in root.iter() if lname(e.tag) in tags]

def edit_facility(fac, xml_bytes):
    root = ET.fromstring(xml_bytes)
    log = []
    # ---- RatedPower → RatedPowerKw (property) ----
    for p in find_all(root, ('property',)):
        if p.findtext(NS + 'idShort') == 'RatedPower':
            sem = p.find(NS + 'semanticId')
            kv = sem.find('.//' + NS + 'value') if sem is not None else None
            if kv is not None and kv.text == CD('RatedPower'):
                p.find(NS + 'idShort').text = 'RatedPowerKw'
                kv.text = CD('RatedPowerKw'); log.append('prop RatedPower→RatedPowerKw')
    # ---- RatedPower CD → RatedPowerKw (idShort/id/preferredName, def·unit·dataType 보존) ----
    for cd in find_all(root, ('conceptDescription',)):
        if cd.findtext(NS + 'id') == CD('RatedPower'):
            cd.find(NS + 'idShort').text = 'RatedPowerKw'; cd.find(NS + 'id').text = CD('RatedPowerKw')
            pn = cd.find('.//' + NS + 'preferredName/' + NS + 'langStringPreferredNameTypeIec61360/' + NS + 'text')
            if pn is not None: pn.text = 'RatedPowerKw'
            log.append('CD RatedPower→RatedPowerKw')
    # ---- CycleTimeSec ----
    if fac == 'ScreenPrinter':
        # PrintingPerformance 의 CycleTime(prop) rename + 초단위
        area = next((e for e in find_all(root, ('submodelElementCollection', 'submodelElementList')) if e.findtext(NS + 'idShort') == 'PrintingPerformance'), None)
        val = area.find(NS + 'value')
        for p in list(val):
            if lname(p.tag) == 'property' and p.findtext(NS + 'idShort') == 'CycleTime':
                old_cd = p.find('.//' + NS + 'semanticId/' + NS + 'keys/' + NS + 'key/' + NS + 'value')
                old_cd_id = old_cd.text
                p.find(NS + 'idShort').text = 'CycleTimeSec'
                old_cd.text = CD('CycleTimeSec')
                vt = p.find(NS + 'valueType')
                if vt is not None: vt.text = 'xs:integer'
                log.append(f'prop CycleTime→CycleTimeSec (was {old_cd_id})')
                # 해당 CD rename + unit/symbol/dataType=psm, def 보존
                for cd in find_all(root, ('conceptDescription',)):
                    if cd.findtext(NS + 'id') == old_cd_id:
                        cd.find(NS + 'idShort').text = 'CycleTimeSec'; cd.find(NS + 'id').text = CD('CycleTimeSec')
                        pn = cd.find('.//' + NS + 'preferredName/' + NS + 'langStringPreferredNameTypeIec61360/' + NS + 'text')
                        if pn is not None: pn.text = 'CycleTimeSec'
                        iec = cd.find('.//' + NS + 'dataSpecificationIec61360')
                        def set_or_add(parent, tag, text, before_tags):
                            el = parent.find(NS + tag)
                            if el is None:
                                el = E(tag, text)
                                idx = len(list(parent))
                                for i, ch in enumerate(parent):
                                    if lname(ch.tag) in before_tags: idx = i; break
                                parent.insert(idx, el)
                            else: el.text = text
                        # 순서: preferredName, unit, symbol, dataType, definition
                        set_or_add(iec, 'unit', 's', ('symbol', 'dataType', 'definition'))
                        set_or_add(iec, 'symbol', 'CT', ('dataType', 'definition'))
                        set_or_add(iec, 'dataType', 'INTEGER_COUNT', ('definition',))
                        log.append(f'CD {old_cd_id}→CycleTimeSec (unit=s/symbol=CT/INTEGER_COUNT, def 보존)')
    else:
        # 성능영역 최상위에 CycleTimeSec 신규 + CD 신설
        area_name = FAC[fac][2]
        area = next((e for e in find_all(root, ('submodelElementCollection', 'submodelElementList')) if e.findtext(NS + 'idShort') == area_name), None)
        area.find(NS + 'value').append(make_cyc_property())
        root.find(NS + 'conceptDescriptions').append(make_cts_cd())
        log.append(f'CycleTimeSec prop 신규 @ {area_name} + CD 신설')
    return ET.tostring(root, encoding='utf-8', xml_declaration=True), log

# ===== 실행 + 검증 =====
for fac, (zf, inner, area) in FAC.items():
    path = WIP + zf
    members = {}
    with zipfile.ZipFile(path) as zin:
        infos = zin.infolist()
        for it in infos: members[it.filename] = zin.read(it.filename)
    new_xml, log = edit_facility(fac, members[inner])
    members[inner] = new_xml
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as zout:
        for it in infos:
            zout.writestr(it, members[it.filename])
    # 검증: 재파싱 + 핵심 확인
    r = ET.fromstring(members[inner])
    has_rpk = any(p.findtext(NS + 'idShort') == 'RatedPowerKw' for p in find_all(r, ('property',)))
    cts = [p for p in find_all(r, ('property',)) if p.findtext(NS + 'idShort') == 'CycleTimeSec']
    cts_cd = any(cd.findtext(NS + 'id') == CD('CycleTimeSec') for cd in find_all(r, ('conceptDescription',)))
    rpk_cd = any(cd.findtext(NS + 'id') == CD('RatedPowerKw') for cd in find_all(r, ('conceptDescription',)))
    print(f"[{fac}] {'; '.join(log)}")
    print(f"    검증: RatedPowerKw prop={has_rpk} CD={rpk_cd} | CycleTimeSec prop={len(cts)} CD={cts_cd} | 재파싱 OK")
