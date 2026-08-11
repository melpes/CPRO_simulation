"""논문 폴더의 오픈액세스 PDF 본문을 받아 실험 조건(수치+단위)을 뽑아낸다.

초록에는 조건이 몇 개뿐이고 실제 공정 조건은 본문 Experimental/Methods 파트에 있다.
"""

import glob
import json
import os
import re
import sys
import time

import requests

OUT_DIR = r"C:\Users\KangTaehui\KG\keti\CPRO_조립공정\시뮬레이션\Package\docs\원본자료\keti-fab\포털수집"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"

# 공정 조건으로 볼 단위
UNIT = (r"(?:°C|℃|K\b|rpm|RPM|sccm|slm|Torr|mTorr|mbar|Pa\b|kPa|MPa|bar\b"
        r"|W\b|kW|mW|V\b|kV|mA|A\b|nm|µm|μm|um\b|mm|cm\b|Å"
        r"|s\b|sec|min\b|h\b|hr|wt\.?%|vol\.?%|%|mM|M\b|mJ|J/cm2|mg/mL|cP|mN/m)")
COND = re.compile(r"[^.\n]{0,120}?\d+(?:\.\d+)?\s*" + UNIT + r"[^.\n]{0,80}")

sess = requests.Session()
sess.headers["User-Agent"] = UA


MAILTO = "vegakangtaehui@gmail.com"


def alt_pdf_urls(doi):
    """출판사가 막을 때 쓸 대체 OA 경로 (Unpaywall → Europe PMC)."""
    urls = []
    d = (doi or "").replace("https://doi.org/", "").strip()
    if not d:
        return urls
    try:
        r = sess.get(f"https://api.unpaywall.org/v2/{d}", params={"email": MAILTO}, timeout=30)
        if r.status_code == 200:
            j = r.json()
            for loc in ([j.get("best_oa_location")] + (j.get("oa_locations") or [])):
                if loc and loc.get("url_for_pdf"):
                    urls.append(loc["url_for_pdf"])
    except Exception:
        pass
    try:
        r = sess.get("https://www.ebi.ac.uk/europepmc/webservices/rest/search",
                     params={"query": f"DOI:{d}", "format": "json", "resultType": "core"}, timeout=30)
        for res in r.json().get("resultList", {}).get("result", [])[:1]:
            pmcid = res.get("pmcid")
            if pmcid:
                urls.append(f"https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextPDF")
    except Exception:
        pass
    # 중복 제거, 순서 유지
    seen, out = set(), []
    for u in urls:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def try_download(urls, path):
    for u in urls:
        try:
            r = sess.get(u, timeout=90, allow_redirects=True)
            if r.status_code == 200 and r.content.startswith(b"%PDF"):
                with open(path, "wb") as f:
                    f.write(r.content)
                return u
        except Exception:
            pass
        time.sleep(1)
    return None


def pdf_text(path):
    try:
        import pypdf
        r = pypdf.PdfReader(path)
        return "\n".join((p.extract_text() or "") for p in r.pages)
    except Exception as e:
        return f"__ERROR__ {e}"


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    summary = []

    for meta in sorted(glob.glob(os.path.join(OUT_DIR, "*", "논문", "*.txt"))):
        if os.path.basename(meta).startswith("_"):
            continue
        lines = open(meta, encoding="utf-8").read().split("\n")
        urls = [l.strip() for l in lines[:5] if l.strip().startswith("http")]
        doi = next((u for u in urls if "doi.org" in u), "")
        pdf_urls = [u for u in urls if "doi.org" not in u]
        if not pdf_urls and not doi:
            continue
        url = pdf_urls[0] if pdf_urls else doi
        pdir = os.path.dirname(meta)
        eq = os.path.basename(os.path.dirname(pdir))
        base = os.path.splitext(os.path.basename(meta))[0]
        pdf_path = os.path.join(pdir, base + ".pdf")
        txt_path = os.path.join(pdir, base + "_본문.txt")

        if not os.path.exists(pdf_path):
            got = try_download(pdf_urls + alt_pdf_urls(doi), pdf_path)
            if not got:
                print(f"  x {eq[:18]:20} {base[:34]:36} 받기실패(대체경로 포함)")
                summary.append({"설비": eq, "논문": base, "상태": "실패"})
                continue
            url = got

        t = pdf_text(pdf_path)
        if t.startswith("__ERROR__"):
            print(f"  ! {eq[:18]:20} {base[:34]:36} 파싱실패")
            summary.append({"설비": eq, "논문": base, "상태": "파싱실패"})
            continue

        conds = [re.sub(r"\s+", " ", m.group(0)).strip() for m in COND.finditer(t)]
        # 중복·짧은 조각 제거
        seen, keep = set(), []
        for c in conds:
            k = c[:60]
            if len(c) < 15 or k in seen:
                continue
            seen.add(k)
            keep.append(c)

        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(f"# {base}\n출처: {url}\n\n## 추출된 공정 조건 후보 ({len(keep)}건)\n\n")
            for c in keep:
                f.write("- " + c + "\n")
            f.write("\n\n" + "=" * 60 + "\n# 본문 전체\n\n" + t)

        summary.append({"설비": eq, "논문": base, "상태": "완료",
                        "쪽수_추정": t.count("\f") + 1, "조건후보": len(keep)})
        print(f"  o {eq[:18]:20} {base[:34]:36} 조건 {len(keep):>4}건")

    with open(os.path.join(OUT_DIR, "_paper_pdf_summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    ok = [s for s in summary if s["상태"] == "완료"]
    print(f"\n완료 {len(ok)}/{len(summary)}건 / 조건 후보 합 {sum(s.get('조건후보',0) for s in ok)}")


if __name__ == "__main__":
    main()
