#!/usr/bin/env python3
import json, re, sys, time
from datetime import datetime, timezone
from pathlib import Path
import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "history.json"
HEADERS = {"User-Agent":"Mozilla/5.0 (compatible; SuperCombinazioniArchive/2.0)"}

IT_MONTHS = {
 "gennaio":1,"febbraio":2,"marzo":3,"aprile":4,"maggio":5,"giugno":6,
 "luglio":7,"agosto":8,"settembre":9,"ottobre":10,"novembre":11,"dicembre":12
}

def euro_num(s):
    if not s: return None
    s=s.replace("\xa0"," ").replace("€","").strip()
    m=re.search(r"([\d.]+,\d{2})",s)
    if not m: return None
    return float(m.group(1).replace(".","").replace(",", "."))

def get(url):
    r=requests.get(url,headers=HEADERS,timeout=30)
    r.raise_for_status()
    return r.text

def parse_month(year, month_name):
    url=f"https://www.superenalotto.it/archivio-estrazioni/{year}/{month_name}"
    try: soup=BeautifulSoup(get(url),"html.parser")
    except Exception as e:
        print("month error",year,month_name,e); return []
    out=[]
    # Prefer draw detail links because detail pages contain official prizes.
    links=[]
    for a in soup.find_all("a",href=True):
        href=a["href"]
        if "/archivio-estrazioni/concorso-" in href:
            if href.startswith("/"): href="https://www.superenalotto.it"+href
            if href not in links: links.append(href)
    for href in links:
        row=parse_detail(href)
        if row and row["date"].startswith(str(year)): out.append(row)
        time.sleep(.06)
    return out

def parse_detail(url):
    try: soup=BeautifulSoup(get(url),"html.parser")
    except Exception as e:
        print("detail error",url,e); return None
    text=soup.get_text("\n",strip=True)
    m=re.search(r"Concorso\s*N[º°o]?\s*(\d+)\s+del\s+(\d{1,2})\s+([A-Za-zÀ-ÿ]+)\s+(\d{4})",text,re.I)
    if not m: return None
    contest=int(m.group(1)); day=int(m.group(2)); mon=IT_MONTHS.get(m.group(3).lower()); year=int(m.group(4))
    if not mon: return None

    # Find numbers around the "Combinazione vincente" section.
    main=[]
    h=soup.find(string=re.compile(r"Combinazione vincente",re.I))
    if h:
        parent=h.parent
        # search following text nearby
        for el in parent.find_all_next(limit=40):
            vals=re.findall(r"(?<!\d)([1-9]|[1-8]\d|90)(?!\d)",el.get_text(" ",strip=True))
            for v in vals:
                n=int(v)
                if n not in main: main.append(n)
                if len(main)==6: break
            if len(main)==6: break
    if len(main)!=6:
        # fallback: use page lines immediately after heading
        lines=[x.strip() for x in text.splitlines() if x.strip()]
        try: idx=next(i for i,x in enumerate(lines) if re.search(r"Combinazione vincente",x,re.I))
        except StopIteration: return None
        for x in lines[idx+1:idx+30]:
            if re.fullmatch(r"\d{1,2}",x):
                n=int(x)
                if 1<=n<=90 and n not in main: main.append(n)
                if len(main)==6: break
    if len(main)!=6: return None

    jolly=None; superstar=None
    jm=re.search(r"Jolly\s+(\d{1,2})",text,re.I)
    sm=re.search(r"SuperStar\s+(\d{1,2})",text,re.I)
    if jm: jolly=int(jm.group(1))
    if sm: superstar=int(sm.group(1))

    prizes={}
    for cat in ["6","5+1","5","4","3","2"]:
        mm=re.search(rf"Punti\s+{re.escape(cat)}\s+([\d.]+)\s+([-\d.,\s€]+)",text,re.I)
        if mm:
            winners=int(mm.group(1).replace(".",""))
            val=None if "-" in mm.group(2).strip() and not re.search(r"\d",mm.group(2).strip().replace(".","").replace(",","")) else euro_num(mm.group(2))
            prizes[cat]={"winners":winners,"value":val}

    total_pool=None
    tm=re.search(r"Montepremi totale del Concorso\s+([\d.]+,\d{2})\s*€",text,re.I)
    if tm: total_pool=euro_num(tm.group(1))

    return {
      "date":f"{year:04d}-{mon:02d}-{day:02d}","contest":contest,"combo":sorted(main),
      "jolly":jolly,"superstar":superstar,"prizes":prizes,"total_pool":total_pool,
      "source":"superenalotto.it"
    }

def validate(rows):
    out=[]; seen=set()
    for x in rows:
        c=x.get("combo",[])
        if len(c)!=6 or len(set(c))!=6 or not all(isinstance(n,int) and 1<=n<=90 for n in c): continue
        k=(x["date"],tuple(c))
        if k in seen: continue
        seen.add(k); out.append(x)
    return sorted(out,key=lambda x:x["date"])

def load_existing():
    try: return json.loads(OUT.read_text(encoding="utf-8")).get("draws",[])
    except Exception: return []

def fetch_year(y):
    rows=[]
    for m in IT_MONTHS:
        rows.extend(parse_month(y,m))
    return validate(rows)

def current_jackpot():
    # Current official header/archive pages expose jackpot; parse best-effort.
    for url in ["https://www.superenalotto.it/archivio-estrazioni","https://www.superenalotto.it/quanto-si-vince"]:
        try:
            text=BeautifulSoup(get(url),"html.parser").get_text(" ",strip=True)
            m=re.search(r"Jackpot(?:\s+\w+){0,6}\s+([\d.,]+)\s*(milioni)?\s*€",text,re.I)
            if m:
                if m.group(2):
                    return float(m.group(1).replace(",", "."))*1_000_000
                return float(m.group(1).replace(".","").replace(",","."))
        except Exception: pass
    return None

def main():
    now=datetime.now()
    full="--full" in sys.argv
    existing=load_existing()
    if full or not existing:
        years=range(1997,now.year+1); all_rows=[]
    else:
        years=[now.year]; all_rows=[x for x in existing if not x["date"].startswith(str(now.year))]
    for y in years:
        r=fetch_year(y); print(y,len(r)); all_rows.extend(r)
    all_rows=validate(all_rows)

    latest=all_rows[-1] if all_rows else None
    jp=current_jackpot()
    latest_details=None
    if latest:
        latest_details={
          "contest":latest.get("contest"),"date":latest.get("date"),"prizes":latest.get("prizes",{}),
          "total_pool":latest.get("total_pool"),"next_jackpot":jp
        }
    meta={
      "generated_at":datetime.now(timezone.utc).isoformat(),"count":len(all_rows),
      "first_date":all_rows[0]["date"] if all_rows else None,
      "last_date":all_rows[-1]["date"] if all_rows else None,
      "latest_details":latest_details,
      "source":"superenalotto.it"
    }
    OUT.write_text(json.dumps({"meta":meta,"draws":all_rows},ensure_ascii=False,separators=(",",":")),encoding="utf-8")
    print("saved",len(all_rows))

if __name__=="__main__":
    main()
