from concurrent.futures import ThreadPoolExecutor
import math
from pathlib import Path
import json
from io import BytesIO
from PIL import Image
import cv2
import requests
import numpy as np
from datetime import datetime, timezone
import time


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "../../../data"
DATA = BASE_DIR
DATA1 = BASE_DIR / "plant"
DATA2 = BASE_DIR / "province"
print(f"DATA: {DATA}")

CROPS = {
    "rice": {"table_name": "agri_landuse_rice_db2_th", "attribute_style_id": 13, "label": "ข้าว", "colour": "#FFFF00"},
    "cane": {"table_name": "agri_landuse_cane_db2_th", "attribute_style_id": 14, "label": "อ้อย", "colour": "#FF73DF"},
    "cassava": {"table_name": "agri_landuse_cassava_db2_th", "attribute_style_id": 15, "label": "มันสำปะหลัง", "colour": "#FFAA00"},
    "corn": {"table_name": "agri_landuse_corn_db2_th", "attribute_style_id": 16, "label": "ข้าวโพด", "colour": "#D1FF73"},
    "palm": {"table_name": "agri_landuse_palm_db2_th", "attribute_style_id": 17, "label": "ปาล์มน้ำมัน", "colour": "#917A7A"},
    "rubber": {"table_name": "agri_landuse_rubber_db2_th", "attribute_style_id": 18, "label": "ยางพารา", "colour": "#38A800"},
    "pineapple": {"table_name": "agri_landuse_pineapple_db2_th", "attribute_style_id": 19, "label": "สับปะรด", "colour": "#BEE8FF"},
}

WMTS_TEMPLATE = (
    "https://webserver.what2grow.in.th/geoserver/gwc/service/wmts"
    "?CQL_FILTER=attribute_style_id={style_id}"
    "&layer=geoshape:{table_name}"
    "&style=&tilematrixset=EPSG:900913"
    "&Service=WMTS&Request=GetTile&Version=1.0.0&Format=image/png"
    "&TileMatrix=EPSG:900913:{z}&TileRow={y}&TileCol={x}"
)

TILE_SIZE = 256
RAI_PER_SQM = 1 / 1600.0


def coordToTile(lat, lon, zoom):
    lat_rad = math.radians(lat)
    n = 2 ** zoom
    xtile = ((lon + 180.0) / 360.0) * n
    ytile = (1.0 - math.log(math.tan(lat_rad) + 1.0 /
                            math.cos(lat_rad)) / math.pi) / 2.0 * n
    return xtile, ytile


def tileToCoord(xtile, ytile, zoom):
    n = 2 ** zoom
    lon = xtile / n * 360.0 - 180.0
    lat_rad = math.atan(math.sinh(math.pi * (1 - 2 * ytile / n)))
    lat = math.degrees(lat_rad)
    return lat, lon


def load_province(province_name):
    geo = json.loads(
        (DATA_DIR / "thailand.geojson").read_text(encoding="utf-8"))
    # print(f"geo: {geo}")

    for feature in geo['features']:
        if province_name in feature['properties']['pro_th']:
            return feature
    raise SystemExit(f"ไม่พบจังหวัด: {province_name}")


def polygon_bbox(feature):
    def flatten(coords):
        if isinstance(coords[0], (int, float)):
            yield coords
        else:
            for c in coords:
                yield from flatten(c)

    pts = list(flatten(feature['geometry']['coordinates']))
    lons = [pt[0] for pt in pts]
    # print(f"lons: {lons}")
    lats = [pt[1] for pt in pts]
    return min(lons), min(lats), max(lons), max(lats)


def bbox_to_tile_range(bbox, zoom):
    lon_min, lat_min, lon_max, lat_max = bbox
    x_min_f, y_min_f = coordToTile(lat_max, lon_min, zoom)
    x_max_f, y_max_f = coordToTile(lat_min, lon_max, zoom)
    x_min, x_max = math.floor(x_min_f), math.floor(x_max_f)
    y_min, y_max = math.floor(y_min_f), math.floor(y_max_f)
    return x_min, x_max, y_min, y_max


def fetch_tile(session, url, x, y, z, retries=4):
    for i in range(retries):
        try:
            res = session.get(url.format(x=x, y=y, z=z), timeout=40)
            if res.status_code == 200:
                # print(f"Fetched tile {x}, {y}, {z}")
                return x, y, Image.open(BytesIO(res.content)).convert("RGBA"), None

        except requests.exceptions.RequestException as e:
            print(f"Error fetching tile {x}, {y}, {z}: {e}")
        time.sleep(1.0 * (i + 1))
    return x, y, None, "failed after retries"


def builds_canvas(url, x_min, x_max, y_min, y_max, zoom, workers=8):
    width_tiles = x_max - x_min + 1
    # print(width_tiles)
    height_tiles = y_max - y_min + 1
    # print(height_tiles)
    print(f"Building canvas of size {width_tiles}x{height_tiles} tiles")
    canvas = Image.new("RGBA", (width_tiles * TILE_SIZE,
                       height_tiles * TILE_SIZE), (0, 0, 0, 0))
    # cv2.imwrite(f"{DATA_DIR}/canvas_old.png", np.array(canvas))
    # print(f"canvas size: {canvas.size}")
    session = requests.Session()
    jobs = [(x, y) for y in range(y_min, y_max + 1)
            for x in range(x_min, x_max + 1)]
    # print(f"Total jobs: {jobs}")

    done = 0

    errors = []

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(
            fetch_tile, session, url, x, y, zoom) for x, y in jobs]
        for future in futures:
            x, y, img, err = future.result()
            # print(f"feature result: x={x}, y={y}, img={img}, err={err}")
            done += 1
            if img is None:
                errors.append((x, y, err))
            else:
                px = (x - x_min) * TILE_SIZE
                # print(f"px: {px}")
                py = (y - y_min) * TILE_SIZE
                # print(f"py: {py}")
                canvas.paste(img, (px, py))
            if done % 50 == 0 or done == len(jobs):
                print(f"tiles fetched: {done}/{len(jobs)}")

    canvas.save(DATA1 / "canvas.png")
    # print("canvas", canvas)
    return canvas, errors


def crop_mask_from_canvas(canvas):
    arr = np.array(canvas)
    # print(f"arr shape: {arr}")
    # print(f"arr : {arr}")
    alpha = arr[:, :, 3]
    # print(f"alpha shape: {alpha.shape}")
    # print(f"alpha: {alpha}")
    # print(f"arr shape: {arr.shape}")
    # print(f"arr", arr[0][0])
    mask = np.where(alpha > 32, 255, 0).astype(np.uint8)
    # print(f"mask shape: {mask.shape}")
    # print(f"mask: {mask}")
    cv2.imwrite(f"{DATA1}/mask.png", mask)
    return mask


def build_province_mask(feature, x_min, y_min, width_px, height_px, zoom):
    mask = np.zeros((height_px, width_px), dtype=np.uint8)
    # print(f"province_mask shape: {mask.shape}")
    # cv2.imwrite(f"{DATA}/mask_default.png", mask)
    geom = feature['geometry']
    # print("geom", geom)
    polys = geom["coordinates"] if geom["type"] == "MultiPolygon" else [
        geom["coordinates"]]
    # print("polys", polys)

    for poly in polys:
        exterior = poly[0]
        # print("exterior", exterior)
        pts = []
        for lon, lat in exterior:
            # print(f"lon: {lon}, lat: {lat}")
            xt, yt = coordToTile(lat, lon, zoom)
            # print(f"xt: {xt}, yt: {yt}")
            px = (xt - x_min) * TILE_SIZE
            # print(f"px: {px}")
            py = (yt - y_min) * TILE_SIZE
            # print(f"py: {py}")
            pts.append([px, py])
        pts = np.array([pts], dtype=np.int32)
        # print(f"pts: {pts}")
        cv2.fillPoly(mask, pts, 255)
        # print(f"mask", mask[992][303])
    cv2.imwrite(f"{DATA2}/province_mask.png", mask)
    # print(f"province_mask shape: {mask.shape}")
    # print(f"province_mask: {mask}")
    return mask


def contours_to_geojson(mask, x_min, y_min, zoom, crop_key, crop, sqm_per_px, min_rai):
    contours, _ = cv2.findContours(
        mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    # print(f"พบ {len(contours)} blob (ก่อนกรองขนาดเล็ก)")
    # print(contours)
    features = []
    for contour in contours:
        area_px = cv2.contourArea(contour)
        # print(f"area_px: {area_px}")
        area_rai = area_px * sqm_per_px * RAI_PER_SQM
        area_rai = round(area_rai, 1)

        # print(f"area_rai: {area_rai}")
        if area_rai < min_rai:
            continue

        simplified = cv2.approxPolyDP(contour, epsilon=1.5, closed=True)
        # print(f"simplified: {simplified}")
        ring = []
        for px, py in simplified.reshape(-1, 2):
            # print(f"px: {px}, py: {py}")
            xt = x_min + px / TILE_SIZE
            yt = y_min + py / TILE_SIZE
            lat, lon = tileToCoord(xt, yt, zoom)
            ring.append([round(lon, 6), round(lat, 6)])
            # print(f"lon: {lon}, lat: {lat}")
        if len(ring) < 3:
            continue
        ring.append(ring[0])

        M = cv2.moments(contour)
        cx_px, cy_px = M["m10"] / M["m00"], M["m01"] / M["m00"]
        centroid_lat, centroid_lon = tileToCoord(
            x_min + cx_px / TILE_SIZE, y_min + cy_px / TILE_SIZE, zoom)

        features.append({
            "type": "Feature",
            "properties": {
                "crop": crop_key,
                "crop_label": crop["label"],
                "colour": crop["colour"],
                "area_rai": round(area_rai, 1),
                "centroid": [round(centroid_lon, 6), round(centroid_lat, 6)],
            },
            "geometry": {"type": "Polygon", "coordinates": [ring]},
        })

    features.sort(key=lambda f: -f["properties"]["area_rai"])
    return features


province = "ลพบุรี"
zoom = 10
n = load_province(province)
polygon = polygon_bbox(n)
lon_min, lat_min, lon_max, lat_max = polygon
# print(
#     f"lon_min: {lon_min}, lat_min: {lat_min}, lon_max: {lon_max}, lat_max: {lat_max}")
x_min, x_max, y_min, y_max = bbox_to_tile_range(polygon, zoom)
print(f"x_min: {x_min}, x_max: {x_max}, y_min: {y_min}, y_max: {y_max}")

crop = CROPS["rice"]
url = WMTS_TEMPLATE.format(
    style_id=crop["attribute_style_id"], table_name=crop["table_name"], x="{x}", y="{y}", z="{z}")

canvas, errors = builds_canvas(
    url, x_min, x_max, y_min, y_max, zoom, workers=8)

crop_mask = crop_mask_from_canvas(canvas)
# print(f"crop_mask shape: {crop_mask}")

province_mask = build_province_mask(
    n, x_min, y_min, canvas.width, canvas.height, zoom)
# print(f"province_mask shape: {province_mask}")

final_mask = cv2.bitwise_and(crop_mask, province_mask)
# np.set_printoptions(threshold=np.inf)
# with open("final_mask.txt", "w") as f:
#     f.write(str(final_mask))
# print(f"final_mask shape: {final_mask[999][1023]}")
cv2.imwrite(f"{DATA2}/final_mask.png", final_mask)

lat_mid = (lat_min + lat_max) / 2
# print(f"lat_mid: {lat_mid}")
# print(math.cos(math.radians(lat_mid)))
meters_per_px = 156543.03392804097 * \
    math.cos(math.radians(lat_mid)) / (2 ** zoom)
# print(f"meters_per_px: {meters_per_px}")
sqm_per_px = meters_per_px ** 2
# print(f"sqm_per_px: {sqm_per_px}")
final = np.array([
    [0, 0, 0, 255, 255, 0, 0],
    [0, 0, 0, 255, 255, 0, 0],
    [0, 0, 0,   0, 255, 255, 0],
    [0, 0, 0,   0,   0, 255, 255],
    [0, 0, 0,   0,   0, 255, 255],
], dtype=np.uint8)
print(f"final", final.shape)

final1 = np.array([
    [0, 0, 255, 255, 255, 0, 0],
    [0, 0, 255, 255, 255, 0, 0],
    [0, 0, 255,   0, 255, 255, 0],
    [0, 0, 255,   0,   0, 255, 0],
    [0, 0, 255,   255,   255, 255, 0],
], dtype=np.uint8)
# print(f"final1", final1.shape)
features = contours_to_geojson(final_mask, x_min, y_min, zoom,
                               crop_key="rice", crop=crop, sqm_per_px=sqm_per_px, min_rai=5.0)

for i, f in enumerate(features[:10]):
    print(f"  blob #{i+1}: {f['properties']['area_rai']:,.1f} ไร่")

meta = {
    "fetched_at": datetime.now(timezone.utc).isoformat(),
    "zoom": zoom,
    "source": WMTS_TEMPLATE.split("?")[0],
}
out_geojson = {"type": "FeatureCollection",
               "meta": meta, "features": features}

DATA_DIR.mkdir(exist_ok=True)
out_path = DATA / f"plots_{province}.geojson"
out_path.write_text(json.dumps(
    out_geojson, ensure_ascii=False), encoding="utf-8")

# print(tile_range)
# print(f"จังหวัด: {province}, feature: {n[0]}")
