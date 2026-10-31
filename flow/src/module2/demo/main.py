from pathlib import Path
import json
import subprocess


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "../../../data"
PROVINCES_GEOJSON = DATA_DIR / "thailand.geojson"
SOURCE_PBF = DATA_DIR / "thailand-260820.osm.pbf"
DATA = BASE_DIR / "data"


def load_province_bbox(province):
    geo = json.loads(PROVINCES_GEOJSON.read_text(encoding="utf-8"))
    matched = [f for f in geo["features"]
               if province in f["properties"]["pro_th"]]
    if not matched:
        raise SystemExit(f"ไม่พบจังหวัด: {province}")
    feature = matched[0]

    def flatten(coords):
        if isinstance(coords[0], (int, float)):
            yield coords
        else:
            for c in coords:
                yield from flatten(c)

    pts = list(flatten(feature["geometry"]["coordinates"]))
    lons = [p[0] for p in pts]
    lats = [p[1] for p in pts]

    # print(
    #     f"Province: {province}, BBox: ({min(lons)}, {min(lats)}, {max(lons)}, {max(lats)})")
    return feature, min(lons), min(lats), max(lons), max(lats)


def run(cmd: list[str]):
    print(f"$ {' '.join(cmd)}")
    subprocess.run(cmd, check=True)


def write_polygon_geojson(feature: dict, out_geojson: Path):
    polygon = {
        "type": "Feature",
        "properties": {},
        "geometry": feature["geometry"],
    }
    out_geojson.write_text(json.dumps(
        polygon, ensure_ascii=False), encoding="utf-8")


def extract_province_pbf(source_pbf: Path, polygon_geojson: Path, out_pbf: Path):
    run([
        "osmium", "extract", "--polygon", str(
            polygon_geojson), "-s", "complete_ways",
        "-o", str(out_pbf), "--overwrite", str(source_pbf),
    ])


def export_roads_geojson(province_pbf: Path, roads_pbf: Path, roads_geojson: Path):
    run(["osmium", "tags-filter", str(province_pbf),
        "w/highway", "-o", str(roads_pbf), "--overwrite"])
    run(["osmium", "export", str(roads_pbf), "-o", str(roads_geojson),
        "-f", "geojson", "--overwrite", "--geometry-types=linestring"])


province = "ลพบุรี"

feature, min_lon, min_lat, max_lon, max_lat = load_province_bbox(province)
roads_geojson = DATA / f"{province}_roads.geojson"
province_pbf = DATA / f"{province}_province.osm.pbf"
roads_pbf = DATA / f"{province}_roads.osm.pbf"
polygon_geojson = DATA / f"{province}_boundary.geojson"
write_polygon_geojson(feature, polygon_geojson)
extract_province_pbf(SOURCE_PBF, polygon_geojson, province_pbf)
export_roads_geojson(province_pbf, roads_pbf, roads_geojson)
