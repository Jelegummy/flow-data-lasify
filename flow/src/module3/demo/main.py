"""
ดึงข้อมูลอุทกภัยรายหมู่บ้าน/ชุมชนจาก catalog.disaster.go.th (datastore_search)
กรองเฉพาะจังหวัดที่ระบุ แล้วรวมยอดรายอำเภอ/ปี บันทึกเป็น data/flood_by_amphur_<province>.json
"""
import argparse
import json
import urllib.parse
import urllib.request
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "../../../data"
DATA = BASE_DIR / "data"

RESOURCE_ID = "b959bb4a-f973-4c17-8a94-416527c0e667"
API_URL = "https://catalog.disaster.go.th/api/3/action/datastore_search"
YEARS = ["Y2562", "Y2563", "Y2564", "Y2565", "Y2566", "Y2567"]

parser = argparse.ArgumentParser()
parser.add_argument("--province", default="ลพบุรี",
                    help="ชื่อจังหวัด (ภาษาไทย) เช่น ลพบุรี")
args = parser.parse_args()
province = args.province

params = {"resource_id": RESOURCE_ID,
          "q": province, "limit": 10000, "offset": 0}
url = API_URL + "?" + urllib.parse.urlencode(params)
with urllib.request.urlopen(url) as resp:
    payload = json.load(resp)

records = [
    r for r in payload["result"]["records"]
    if r["PROVINCE_NAME"].strip() == province
]
if not records:
    raise SystemExit(f"ไม่พบข้อมูลจังหวัด: {province}")

amphurs = {}
for r in records:
    amphur = r["AMPHUR_NAME"].strip()
    entry = amphurs.setdefault(amphur, {
        "districts": set(),
        "by_year": {y: 0 for y in YEARS},
        "total": 0,
    })
    entry["districts"].add(r["DISTRICT_NAME"].strip())
    for y in YEARS:
        v = r[y].strip()
        if v.isdigit():
            n = int(v)
            entry["by_year"][y] += n
            entry["total"] += n

out = {
    "province": province,
    "resource_id": RESOURCE_ID,
    "years": YEARS,
    "records_matched": len(records),
    "amphurs": {
        name: {
            "total": e["total"],
            "by_year": e["by_year"],
            "n_districts": len(e["districts"]),
        }
        for name, e in amphurs.items()
    },
}

out_path = DATA / f"flood_by_amphur_{province}.json"
out_path.write_text(json.dumps(
    out, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"Wrote {out_path} ({len(records)} records matched, {len(amphurs)} amphur)")
