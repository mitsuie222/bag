from flask import Flask, jsonify, request, render_template, session, redirect, url_for
from urllib.parse import urlparse, urljoin
from functools import wraps
from werkzeug.utils import secure_filename
import json
import os
import csv
import re
import uuid
import random
import unicodedata
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

# app.py はプロジェクト直下に置く。
# 実体（templates / static / data）は bousai_app/ 配下にあるので、そこを参照する。
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
APP_DIR = os.path.join(BASE_DIR, 'bousai_app')

app = Flask(
    __name__,
    template_folder=os.path.join(APP_DIR, 'templates'),
    static_folder=os.path.join(APP_DIR, 'static'),
)
app.secret_key = 'your-secret-key-here'

# 管理者認証情報
ADMIN_CREDENTIALS = {
    'admin': '123'
}

# ────────────────────────────────
# 気象警報・注意報設定
PREFECTURE_CODE = "020000"  # 青森県
AREA_NAME = "青森市"

# ワークショップ課題：青森市の市区町村コードに変更する
AREA_CODE = "1420500"

WARNING_URL = (
    f"https://www.jma.go.jp/bosai/warning/data/r8/{PREFECTURE_CODE}.json"
)

JST = timezone(timedelta(hours=9))

# 警報・注意報のコード一覧
WARNING_CODES = {
    "00": "解除",
    "02": "暴風雪警報",
    "03": "レベル3大雨警報",
    "04": "洪水警報",
    "05": "暴風警報",
    "06": "大雪警報",
    "07": "波浪警報",
    "08": "レベル3高潮警報",
    "09": "レベル3土砂災害警報",
    "10": "レベル2大雨注意報",
    "12": "大雪注意報",
    "13": "風雪注意報",
    "14": "雷注意報",
    "15": "強風注意報",
    "16": "波浪注意報",
    "17": "融雪注意報",
    "18": "洪水注意報",
    "19": "レベル2高潮注意報",
    "20": "濃霧注意報",
    "21": "乾燥注意報",
    "22": "なだれ注意報",
    "23": "低温注意報",
    "24": "霜注意報",
    "25": "着氷注意報",
    "26": "着雪注意報",
    "27": "その他の注意報",
    "29": "レベル2土砂災害注意報",
    "32": "暴風雪特別警報",
    "33": "レベル5大雨特別警報",
    "35": "暴風特別警報",
    "36": "大雪特別警報",
    "37": "波浪特別警報",
    "38": "レベル5高潮特別警報",
    "39": "レベル5土砂災害特別警報",
    "43": "レベル4大雨危険警報",
    "48": "レベル4高潮危険警報",
    "49": "レベル4土砂災害危険警報"
}

# ────────────────────────────────
# サンプルデータの読み込み
DATA_FILE = os.path.join(APP_DIR, 'data', 'shelters.json')
INSTRUCTIONS_FILE = os.path.join(APP_DIR, 'data', 'instructions.json')
HAZARDS_FILE = os.path.join(APP_DIR, 'data', 'hazards.json')
UPLOAD_DIR = os.path.join(APP_DIR, 'uploads')
POSTS_FILE = os.path.join(APP_DIR, 'data', 'damage_posts.json')
CHECKINS_FILE = os.path.join(APP_DIR, 'data', 'checkins.json')
SHELTER_LIST_CSV = os.path.join(BASE_DIR, 'all_evacuation_sites_combined.csv')
TSUNAMI_SHELTER_CSV = os.path.join(BASE_DIR, 'tsunami_shinsui_kuikigai_hinanjo.csv')
SHELTER_COORDINATES_FILE = os.path.join(APP_DIR, 'data', 'shelter_coordinates.json')

REGION_LABELS = {
    'hokubu': '北部',
    'nanbu': '南部',
    'toubu': '東部',
    'chuubu': '中央(1)',
    'chuubu2': '中央(2)',
    'namioka': '浪岡地区',
}

# 地域ごとの大まかな座標範囲。住所地域と矛盾する古い座標を地図に出さない。
REGION_COORDINATE_RANGES = {
    'hokubu': (40.78, 41.0, 140.5, 140.78),
    'nanbu': (40.68, 40.9, 140.55, 140.9),
    'toubu': (40.75, 41.0, 140.7, 141.05),
    'chuubu': (40.75, 40.9, 140.65, 140.85),
    'chuubu2': (40.75, 40.9, 140.65, 140.85),
    'namioka': (40.6, 40.8, 140.45, 140.75),
}

# 青森市の地図に表示する座標の許容範囲。座標CSVに混在する他地域の値を除外する。
AOMORI_CITY_LATITUDE_RANGE = (40.6, 41.0)
AOMORI_CITY_LONGITUDE_RANGE = (140.5, 141.2)
ALLOWED_UPLOAD_EXTENSIONS = {
    '.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.heic',
    '.mp4', '.mov', '.avi', '.webm', '.mkv', '.m4v'
}
SHELTER_IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.webp'}
CROWD_STATUSES = ('空いている', 'やや空いている', 'やや混雑', '混雑', '満員')
CSV_ACCESSIBILITY_FIELDS = ('多目的トイレ', 'ペット可', '車いす対応')


def csv_flag(value):
    """CSVの設備値をbooleanへ変換する"""
    return str(value or '').strip().lower() in {'あり', '有', '可', '対応', 'yes', 'true', '1', 'o'}


def normalize_shelter_value(value):
    """避難所名・住所の重複判定用に全角半角と空白を統一する"""
    normalized = unicodedata.normalize('NFKC', str(value or ''))
    for separator in ('−', '－', '―', 'ー', '‐', '‑', '﹣', '–', '—'):
        normalized = normalized.replace(separator, '-')
    return ''.join(character for character in normalized if not character.isspace()).casefold()


NOMINATIM_URL = 'https://nominatim.openstreetmap.org/search'
NOMINATIM_HEADERS = {'User-Agent': 'BousaiApp/1.0 (shelter registration)'}

def load_json(path, default):
    """JSONファイルを読み込む（存在しない・壊れている場合は default を返す）"""
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def load_csv(path):
    """CSVを読み込み、文字コードの違いを吸収する"""
    for encoding in ('utf-8-sig', 'cp932'):
        try:
            with open(path, encoding=encoding, newline='') as f:
                return list(csv.DictReader(f))
        except (FileNotFoundError, UnicodeDecodeError):
            continue
    return []


def load_csv_shelters():
    """避難所CSVを地域情報と座標付きの地図/API用形式へ統合する"""
    saved_shelters = load_json(DATA_FILE, [])
    saved_by_name = {item.get('name'): item for item in saved_shelters}
    coordinates = load_json(SHELTER_COORDINATES_FILE, {})
    merged = {}

    for row in load_csv(SHELTER_LIST_CSV):
        name = (row.get('施設名称') or '').strip()
        if not name:
            continue
        saved = saved_by_name.get(name, {})
        region_code = (row.get('地域区分') or '').strip()
        merged[name] = {
            'id': row.get('No') or saved.get('id'),
            'name': name,
            'district': REGION_LABELS.get(region_code, saved.get('district') or '青森市'),
            'region_code': region_code,
            'area': (row.get('地区(大字・町名)') or '').strip() or '地区未登録',
            'address': row.get('所在地', ''),
            'capacity': saved.get('capacity'),
            'tsunami': row.get('津波') or saved.get('tsunami') or '未登録',
            'landslide': row.get('土砂災害') or saved.get('landslide') or '未登録',
            'description': '避難所一覧CSVに掲載されています。',
            'crowd_status': row.get('混雑度') or '未入力',
            'csv_multipurpose_toilet': csv_flag(row.get('多目的トイレ')),
            'csv_pets_allowed': csv_flag(row.get('ペット可')),
            'csv_wheelchair_accessible': csv_flag(row.get('車いす対応')),
        }

    for shelter in merged.values():
        coordinate = coordinates.get(shelter['name'], {})
        saved = saved_by_name.get(shelter['name'], {})
        lat = coordinate.get('lat', saved.get('lat'))
        lng = coordinate.get('lng', saved.get('lng'))
        is_aomori_city_coordinate = (
            isinstance(lat, (int, float))
            and isinstance(lng, (int, float))
            and AOMORI_CITY_LATITUDE_RANGE[0] <= lat <= AOMORI_CITY_LATITUDE_RANGE[1]
            and AOMORI_CITY_LONGITUDE_RANGE[0] <= lng <= AOMORI_CITY_LONGITUDE_RANGE[1]
        )

        if not is_aomori_city_coordinate:
            lat = saved.get('lat')
            lng = saved.get('lng')
            is_aomori_city_coordinate = (
                isinstance(lat, (int, float))
                and isinstance(lng, (int, float))
                and AOMORI_CITY_LATITUDE_RANGE[0] <= lat <= AOMORI_CITY_LATITUDE_RANGE[1]
                and AOMORI_CITY_LONGITUDE_RANGE[0] <= lng <= AOMORI_CITY_LONGITUDE_RANGE[1]
            )

        region_range = REGION_COORDINATE_RANGES.get(shelter.get('region_code'))
        if is_aomori_city_coordinate and region_range:
            min_lat, max_lat, min_lng, max_lng = region_range
            is_aomori_city_coordinate = (
                min_lat <= lat <= max_lat
                and min_lng <= lng <= max_lng
            )

        shelter['lat'] = lat if is_aomori_city_coordinate else None
        shelter['lng'] = lng if is_aomori_city_coordinate else None

    for saved in saved_shelters:
        if not saved.get('source') == 'custom' or saved.get('name') in merged:
            continue
        merged[saved['name']] = dict(saved)

    return list(merged.values())

shelters = load_csv_shelters()
registered_shelters = load_json(DATA_FILE, [])
instructions = load_json(INSTRUCTIONS_FILE, [])
damage_posts = load_json(POSTS_FILE, [])
checkins = load_json(CHECKINS_FILE, {})
hazards = load_json(HAZARDS_FILE, [])


def seed_demo_damage_posts():
    """地図確認用に青森市内へ集中した仮の被害投稿を生成する"""
    demo_count = sum(1 for post in damage_posts if post.get('is_demo'))
    if demo_count >= 30:
        return
    randomizer = random.Random(20260910)
    addresses = [
        '青森市古川三丁目', '青森市新町一丁目', '青森市本町二丁目',
        '青森市中央三丁目', '青森市浜田二丁目', '青森市大野',
        '青森市筒井一丁目', '青森市小柳四丁目', '青森市浅虫',
        '青森市浪打一丁目'
    ]
    for index in range(demo_count, 30):
        latitude = 40.80 + randomizer.uniform(-0.035, 0.035)
        longitude = 140.74 + randomizer.uniform(-0.065, 0.085)
        address = addresses[index % len(addresses)]
        damage_posts.append({
            'id': f'demo-{index + 1}',
            'comment': f'仮の災害情報 {index + 1}: 周辺の安全確認が必要です。',
            'address': address,
            'latitude': latitude,
            'longitude': longitude,
            'is_demo': True,
            'created_at': get_japan_time() if 'get_japan_time' in globals() else ''
        })
    try:
        with open(POSTS_FILE, 'w', encoding='utf-8') as f:
            json.dump(damage_posts, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


def save_checkins():
    """避難所ごとのチェックイン一覧をJSONへ保存する"""
    with open(CHECKINS_FILE, 'w', encoding='utf-8') as f:
        json.dump(checkins, f, ensure_ascii=False, indent=2)


seed_demo_damage_posts()


def sync_registered_shelter_details():
    """登録済みJSONの開設状態・混雑度・設備情報を検索用データへ反映する"""
    registered_by_name = {
        item.get('name'): item for item in registered_shelters
    }
    shelter_by_name = {item.get('name'): item for item in shelters}
    for registered in registered_shelters:
        if registered.get('address'):
            continue
        source = shelter_by_name.get(registered.get('name'))
        if source and source.get('address'):
            registered['address'] = source['address']
    for shelter in shelters:
        registered = registered_by_name.get(shelter.get('name'), {})
        shelter['is_open'] = registered.get('is_open', True) if registered else True
        registered_status = registered.get('crowd_status')
        csv_status = shelter.get('crowd_status')
        shelter['crowd_status'] = (
            registered_status if registered_status in CROWD_STATUSES
            else csv_status if csv_status in CROWD_STATUSES
            else '空いている'
        )
        shelter['wheelchair_accessible'] = (
            bool(registered['wheelchair_accessible'])
            if 'wheelchair_accessible' in registered
            else shelter.get('csv_wheelchair_accessible', False)
        )
        shelter['multipurpose_toilet'] = (
            bool(registered['multipurpose_toilet'])
            if 'multipurpose_toilet' in registered
            else shelter.get('csv_multipurpose_toilet', False)
        )
        shelter['pets_allowed'] = (
            bool(registered['pets_allowed'])
            if 'pets_allowed' in registered
            else shelter.get('csv_pets_allowed', False)
        )


sync_registered_shelter_details()

def save_instructions():
    """指示ボードのデータをファイルに保存する"""
    try:
        with open(INSTRUCTIONS_FILE, 'w', encoding='utf-8') as f:
            json.dump(instructions, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def save_damage_posts():
    """災害投稿の記録をファイルに保存する"""
    try:
        with open(POSTS_FILE, 'w', encoding='utf-8') as f:
            json.dump(damage_posts, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def save_shelters(new_shelters):
    """避難所データをファイルに保存して、メモリ上の一覧を更新する"""
    global shelters
    shelters = new_shelters
    try:
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(shelters, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def save_registered_shelters():
    """登録済み避難所だけをJSONへ保存する"""
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(registered_shelters, f, ensure_ascii=False, indent=2)
    sync_registered_shelter_details()


def save_hazards():
    """危険箇所データをJSONへ保存する"""
    with open(HAZARDS_FILE, 'w', encoding='utf-8') as f:
        json.dump(hazards, f, ensure_ascii=False, indent=2)


def normalize_address(address):
    """全角数字やハイフンを住所検索しやすい形式へ正規化する"""
    normalized = unicodedata.normalize('NFKC', address).strip()
    for separator in ('−', '－', '―', 'ー', '‐', '‑', '﹣', '–', '—'):
        normalized = normalized.replace(separator, '-')
    return normalized


def geocode_shelter_address(address):
    """Nominatimで住所を検索し、青森市内の座標だけを返す"""
    normalized = normalize_address(address)
    queries = [normalized]
    block_query = re.sub(r'(\d+丁目)\d+(?:-\d+)?$', r'\1', normalized)
    block_query = re.sub(r'([町字])\d+(?:-\d+)?$', r'\1', block_query)
    if block_query != normalized:
        queries.append(block_query)

    for query in queries:
        search_query = query if '青森市' in query else f'青森市 {query}'
        params = urllib.parse.urlencode({
            'q': search_query,
            'format': 'jsonv2',
            'limit': 5,
            'countrycodes': 'jp',
            'viewbox': '140.55,41.0,140.95,40.55',
            'bounded': 1,
        })
        geocode_request = urllib.request.Request(
            f'{NOMINATIM_URL}?{params}', headers=NOMINATIM_HEADERS
        )
        with urllib.request.urlopen(geocode_request, timeout=10) as response:
            results = json.loads(response.read())
        result = next(
            (item for item in results if '青森市' in item.get('display_name', '')),
            None
        )
        if result:
            latitude = float(result['lat'])
            longitude = float(result['lon'])
            if (AOMORI_CITY_LATITUDE_RANGE[0] <= latitude <= AOMORI_CITY_LATITUDE_RANGE[1]
                    and AOMORI_CITY_LONGITUDE_RANGE[0] <= longitude <= AOMORI_CITY_LONGITUDE_RANGE[1]):
                return latitude, longitude
    raise ValueError('住所を地図上で検索できませんでした。')
# ────────────────────────────────

# ────────────────────────────────
# 認証関連の設定とヘルパー関数
def is_safe_url(target):
    """リダイレクト先URLが安全かどうかチェック"""
    ref_url = urlparse(request.host_url)
    test_url = urlparse(urljoin(request.host_url, target))
    return test_url.scheme in ('http', 'https') and ref_url.netloc == test_url.netloc

def login_required(f):
    """認証が必要なページに付けるデコレータ"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            # 現在のURLをnextパラメータとしてログイン画面にリダイレクト
            return redirect(url_for('login', next=request.url))
        return f(*args, **kwargs)
    return decorated_function

def get_japan_time():
    """日本時間（JST）の現在時刻を取得する"""
    return datetime.now(JST).strftime("%Y年%m月%d日 %H:%M")


@app.template_filter('instruction_time')
def format_instruction_time(value):
    """送信履歴の日時を月日・時刻で表示する"""
    if not value:
        return ''
    try:
        parsed = datetime.strptime(value, "%Y年%m月%d日 %H:%M")
        return f"{parsed.month}/{parsed.day} {parsed.hour}:{parsed.minute:02d}"
    except (TypeError, ValueError):
        return value


def format_report_time(iso_str):
    """気象庁の発表時刻（ISO形式）をJSTの表示用文字列に変換する"""
    if not iso_str:
        return "不明"
    try:
        parsed = datetime.fromisoformat(iso_str.replace('Z', '+00:00'))
        if parsed.tzinfo:
            parsed = parsed.astimezone(JST)
        return parsed.strftime("%Y年%m月%d日 %H:%M")
    except ValueError:
        return iso_str


def filter_shelters(district=None, area=None):
    """地域・地区の指定に一致する避難所のみ、なければ全件を返す"""
    return [
        shelter for shelter in shelters
        if (not district or shelter.get('district') == district)
        and (not area or shelter.get('area') == area)
    ]


def parse_area_warnings(warning_data):
    """気象庁の新形式JSONから対象市区町村の発表・継続中の情報を抽出する"""
    if not isinstance(warning_data, list):
        raise ValueError("気象庁の警報・注意報データが新形式の配列ではありません")

    warnings = []
    seen_codes = set()
    report_datetimes = []

    for report in warning_data:
        if not isinstance(report, dict):
            continue

        report_datetime = report.get("reportDatetime")
        if isinstance(report_datetime, str) and report_datetime:
            report_datetimes.append(report_datetime)

        warning = report.get("warning")
        if not isinstance(warning, dict):
            continue

        class20_items = warning.get("class20Items", [])
        if not isinstance(class20_items, list):
            continue

        area = next(
            (
                item for item in class20_items
                if isinstance(item, dict)
                and item.get("areaCode") == AREA_CODE
            ),
            None
        )
        if not area:
            continue

        kinds = area.get("kinds", [])
        if not isinstance(kinds, list):
            continue

        for kind in kinds:
            if not isinstance(kind, dict):
                continue

            status = kind.get("status", "")
            code = kind.get("code", "")
            if status not in ("発表", "継続") or not code or code in seen_codes:
                continue

            warnings.append({
                "name": WARNING_CODES.get(
                    code,
                    f"不明な警報・注意報 (コード: {code})"
                ),
                "code": code,
                "status": status
            })
            seen_codes.add(code)

    latest_report_datetime = max(report_datetimes, default="")
    return warnings, latest_report_datetime


def get_weather_warnings():
    """対象市区町村の警報・注意報を取得する"""
    try:
        # 青森県の新形式（令和8年～）警報・注意報データを取得
        with urllib.request.urlopen(url=WARNING_URL, timeout=10) as res:
            warning_data = json.loads(res.read())

        warnings, report_datetime = parse_area_warnings(warning_data)

        return {
            "area_name": AREA_NAME,
            "warnings": warnings,
            "report_time": format_report_time(report_datetime),
            "last_fetch_time": get_japan_time()
        }

    except Exception:
        return {
            "area_name": AREA_NAME,
            "warnings": [],
            "report_time": "取得失敗",
            "last_fetch_time": get_japan_time(),
            "error": True
        }


DISASTER_WARNING_CODES = {
    'flood': {'04', '18'},
    'landslide': {'09', '29', '33', '39', '43', '49'},
    'snow': {'02', '06', '12', '13', '17', '22', '26', '32', '36'},
}


def get_disaster_info(category):
    """ホーム画面の災害カテゴリ別情報を返す"""
    if category in DISASTER_WARNING_CODES:
        weather = get_weather_warnings()
        warnings = [
            warning for warning in weather.get('warnings', [])
            if warning.get('code') in DISASTER_WARNING_CODES[category]
        ]
        available = not weather.get('error', False)
        return {
            'category': category,
            'source': '気象庁 青森県警報・注意報',
            'items': warnings,
            'available': available,
            'message': (
                '気象庁の警報・注意報を取得できませんでした。'
                if not available else
                '該当する警報・注意報があります。'
                if warnings else
                '該当する警報・注意報は発表されていません。'
            )
        }

    if category == 'tsunami':
        return {
            'category': category,
            'source': '気象庁 津波情報',
            'items': [],
            'available': True,
            'message': '現在、津波情報は発表されていません。'
        }

    return {
        'category': category,
        'source': '公開情報未提供',
        'items': [],
        'available': False,
        'message': '現在、このカテゴリの公開情報は提供されていません。'
    }


# トップページ：templates/index.html を返す（住民向け指示も表示する）
@app.route('/', methods=['GET', 'POST'])
def index():
    resident_notices = [i for i in instructions if i.get('target') == '住民']
    bulletin_posts = instructions[:4]
    if request.method == 'POST':
        address = normalize_address(request.form.get('address', ''))
        if not address:
            return render_template('index.html', resident_notices=resident_notices,
                                   bulletin_posts=bulletin_posts,
                                   error=True, message='住所を入力してください。'), 400
        uploads = [
            item for item in request.files.getlist('attachment')
            if item and item.filename
        ]
        if len(uploads) > 3:
            return render_template('index.html', resident_notices=resident_notices,
                                   bulletin_posts=bulletin_posts,
                                   error=True, message='選択できるファイルは最大3つまでです。'), 400

        prepared = []
        for upload in uploads:
            extension = os.path.splitext(upload.filename)[1].lower()
            if extension not in ALLOWED_UPLOAD_EXTENSIONS:
                return render_template(
                    'index.html', resident_notices=resident_notices, error=True,
                    bulletin_posts=bulletin_posts,
                    message='許可されていないファイル形式です。'
                ), 400
            stem = secure_filename(os.path.splitext(upload.filename)[0]) or 'upload'
            prepared.append((upload, extension, stem))

        latitude = longitude = None
        try:
            latitude, longitude = geocode_shelter_address(address)
        except Exception:
            pass

        os.makedirs(UPLOAD_DIR, exist_ok=True)
        comment = request.form.get('comment', '').strip()
        for upload, extension, stem in prepared:
            stored_name = f'{uuid.uuid4().hex}_{stem}{extension}'
            upload.save(os.path.join(UPLOAD_DIR, stored_name))
            damage_posts.append({
                'comment': comment,
                'address': address,
                'latitude': latitude,
                'longitude': longitude,
                'original_filename': upload.filename,
                'stored_filename': stored_name,
                'extension': extension,
                'content_type': upload.mimetype,
                'created_at': datetime.now(JST).isoformat()
            })
        if not prepared:
            damage_posts.append({
                'comment': comment,
                'address': address,
                'latitude': latitude,
                'longitude': longitude,
                'original_filename': '',
                'stored_filename': '',
                'extension': '',
                'content_type': '',
                'created_at': datetime.now(JST).isoformat()
            })
        save_damage_posts()
        return render_template('index.html', resident_notices=resident_notices,
                               bulletin_posts=bulletin_posts,
                               success=True, message='情報提供ありがとうございます。')
    return render_template(
        'index.html',
        resident_notices=resident_notices,
        bulletin_posts=bulletin_posts
    )


@app.route('/api/damage_posts')
def api_damage_posts():
    return jsonify([
        post for post in damage_posts
        if post.get('latitude') is not None and post.get('longitude') is not None
    ])

# ログインページ
@app.route('/login', methods=['GET', 'POST'])
def login():
    # リダイレクト先を取得（デフォルトは避難所登録画面）
    next_url = request.args.get('next') or request.form.get('next')

    # 安全でないURLの場合はデフォルトページにリダイレクト
    if not next_url or not is_safe_url(next_url):
        next_url = url_for('shelter_register')

    if request.method == 'POST':
        password = request.form.get('password', '').strip()

        # 認証チェック
        username = next(
            (name for name, registered_password in ADMIN_CREDENTIALS.items()
             if registered_password == password),
            None
        )
        if username:
            session['logged_in'] = True
            session['username'] = username
            # ログイン成功後は指定されたページにリダイレクト
            return redirect(next_url)
        return render_template('login.html', error=True, message="パスワードが正しくありません。", next=next_url)

    # ログイン済みの場合は指定されたページにリダイレクト
    if session.get('logged_in'):
        return redirect(next_url)

    return render_template('login.html', next=next_url)

# ログアウト
@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

# 新しい避難所の場所を追加するページ
@app.route('/shelter_add', methods=['GET', 'POST'])
@login_required
def shelter_add():
    form_data = request.form.to_dict()
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        address = normalize_address(request.form.get('address', ''))
        description = request.form.get('description', '').strip()
        amenities = [item for item in ('pet', 'toilet', 'wheelchair') if request.form.get(item) == 'on']
        upload = request.files.get('image')
        extension = os.path.splitext(upload.filename or '')[1].lower() if upload else ''

        if not name or not address or not upload or not upload.filename:
            return render_template('shelter_add.html', error=True, message='避難所名、住所、画像は必須です。', form_data=form_data)
        if extension not in SHELTER_IMAGE_EXTENSIONS:
            return render_template('shelter_add.html', error=True, message='画像はjpg、jpeg、png、gif、webpのみ登録できます。', form_data=form_data)
        normalized_name = normalize_shelter_value(name)
        normalized_address = normalize_shelter_value(address)
        if any(normalize_shelter_value(item.get('name')) == normalized_name for item in shelters):
            return render_template('shelter_add.html', error=True, message='同じ名前の避難所はすでに登録されています。', form_data=form_data)
        if any(normalize_shelter_value(item.get('address')) == normalized_address for item in shelters):
            return render_template('shelter_add.html', error=True, message='同じ住所の避難所はすでに登録されています。', form_data=form_data)

        try:
            latitude, longitude = geocode_shelter_address(address)
        except Exception:
            return render_template('shelter_add.html', error=True, message='住所から地図位置を取得できませんでした。住所を確認してください。', form_data=form_data)

        shelter_id = max((int(item.get('id')) for item in registered_shelters if str(item.get('id', '')).isdigit()), default=0) + 1
        os.makedirs(os.path.join(APP_DIR, 'static', 'uploads'), exist_ok=True)
        safe_stem = secure_filename(os.path.splitext(upload.filename)[0]) or 'shelter'
        stored_name = f'{shelter_id}_shelter_{uuid.uuid4().hex[:8]}_{safe_stem}{extension}'
        upload.save(os.path.join(APP_DIR, 'static', 'uploads', stored_name))

        record = {
            'id': shelter_id,
            'name': name,
            'address': address,
            'description': description,
            'amenities': amenities,
            'latitude': latitude,
            'longitude': longitude,
            'lat': latitude,
            'lng': longitude,
            'image_url': url_for('static', filename=f'uploads/{stored_name}'),
            'source': 'custom',
            'crowd_status': '未入力',
            'wheelchair_accessible': 'wheelchair' in amenities,
            'multipurpose_toilet': 'toilet' in amenities,
            'pets_allowed': 'pet' in amenities,
        }
        registered_shelters.insert(0, record)
        shelters.insert(0, dict(record))
        try:
            save_registered_shelters()
        except OSError:
            registered_shelters.pop(0)
            shelters.pop(0)
            return render_template('shelter_add.html', error=True, message='避難所を保存できませんでした。', form_data=form_data)
        return redirect(url_for('shelter_register'))

    return render_template('shelter_add.html', form_data={})


# 避難所登録ページ
@app.route('/shelter_register', methods=['GET', 'POST'])
@login_required
def shelter_register():
    def render_register(**context):
        context.setdefault('shelters', shelters)
        context.setdefault('registered_shelters', registered_shelters)
        context.setdefault('crowd_statuses', CROWD_STATUSES)
        context.setdefault('hazards', hazards)
        context.setdefault('form_data', {})
        return render_template('shelter_register.html', **context)

    if request.method == 'POST':
        action = request.form.get('action', 'register')
        form_data = request.form.to_dict()

        if action == 'add_hazard':
            hazard_name = request.form.get('hazard_name', '').strip()
            try:
                latitude = float(request.form.get('latitude', ''))
                longitude = float(request.form.get('longitude', ''))
            except (TypeError, ValueError):
                latitude = longitude = None
            if not hazard_name or latitude is None or longitude is None:
                return render_register(error=True, message='危険箇所名と地図上の位置を指定してください。', form_data=form_data)
            hazard = {
                'id': max((item.get('id', 0) for item in hazards), default=0) + 1,
                'name': hazard_name,
                'latitude': latitude,
                'longitude': longitude,
            }
            hazards.append(hazard)
            try:
                save_hazards()
            except OSError:
                hazards.pop()
                return render_register(error=True, message='危険箇所を保存できませんでした。', form_data=form_data)
            return render_register(success=True, message='危険箇所を登録しました。', form_data={})

        shelter_id = request.form.get('shelter_id', '').strip()
        address = request.form.get('address', '').strip()
        selected = next((item for item in shelters if str(item.get('id')) == shelter_id), None)
        if not selected or selected.get('address', '').strip() != address:
            return render_register(error=True, message='避難所名と住所を選択してください。', form_data=form_data)

        existing_index = next(
            (index for index, item in enumerate(registered_shelters)
             if item.get('name') == selected.get('name')),
            None
        )

        if action == 'delete':
            if existing_index is None:
                return render_register(error=True, message='登録済みの避難所ではありません。', form_data=form_data)
            previous = [dict(item) for item in registered_shelters]
            registered_shelters[existing_index]['is_open'] = False
            try:
                save_registered_shelters()
            except OSError:
                registered_shelters[:] = previous
                return render_register(error=True, message='避難所を解除できませんでした。', form_data=form_data)
            return render_register(success=True, message='避難所を解除しました。', form_data={})

        crowd_status = request.form.get('crowd_status', '')
        if crowd_status not in CROWD_STATUSES:
            return render_register(error=True, message='混雑状況を選択してください。', form_data=form_data)

        previous = [dict(item) for item in registered_shelters]
        record = dict(selected)
        record.update({
            'id': selected.get('id'),
            'address': address,
            'crowd_status': crowd_status,
            'wheelchair_accessible': request.form.get('wheelchair_accessible') == 'on',
            'multipurpose_toilet': request.form.get('multipurpose_toilet') == 'on',
            'pets_allowed': request.form.get('pets_allowed') == 'on',
            'is_open': True,
        })
        if existing_index is None:
            registered_shelters.append(record)
        else:
            registered_shelters[existing_index] = record
        try:
            save_registered_shelters()
        except OSError:
            registered_shelters[:] = previous
            return render_register(error=True, message='避難所情報を保存できませんでした。', form_data=form_data)
        return render_register(success=True, message='避難所情報を登録・更新しました。', form_data={})

    return render_register()


@app.route('/registered_shelters')
@login_required
def registered_shelters_list():
    return render_template('search_results.html', results=registered_shelters, registered_only=True)


@app.route('/open_shelters')
@login_required
def open_shelters_list():
    results = [item for item in registered_shelters if item.get('is_open', True) is not False]
    return render_template('search_results.html', results=results, registered_only=True, open_only=True)


@app.route('/registered_shelters/toggle/<shelter_id>', methods=['POST'])
@login_required
def toggle_shelter_status(shelter_id):
    shelter = next(
        (item for item in registered_shelters if str(item.get('id')) == shelter_id),
        None
    )
    if shelter is not None:
        shelter['is_open'] = not (shelter.get('is_open') is not False)
        save_registered_shelters()
    return redirect(url_for('registered_shelters_list'))


@app.route('/api/shelters/<shelter_id>/checkins', methods=['GET', 'POST'])
def shelter_checkins(shelter_id):
    shelter = next((item for item in shelters if str(item.get('id')) == shelter_id), None)
    if shelter is None:
        return jsonify({'error': 'Shelter not found'}), 404

    shelter_checkins_list = checkins.setdefault(shelter_id, [])
    if request.method == 'POST':
        payload = request.get_json(silent=True) or {}
        name = str(payload.get('name') or '匿名の利用者').strip()[:40] or '匿名の利用者'
        shelter_checkins_list.insert(0, {
            'name': name,
            'created_at': get_japan_time(),
        })
        save_checkins()
    return jsonify(shelter_checkins_list)


# 避難所検索ページ
@app.route('/shelter_search')
def shelter_search():
    return render_template('shelter_search.html')

# 全施設一覧ページ
@app.route('/all_shelters')
def all_shelters():
    return render_template('search_results.html', results=shelters)


# 指示ボード：指示・発信の登録と一覧表示
@app.route('/board', methods=['GET', 'POST'])
@login_required
def board():
    form_data = request.form.to_dict()
    if request.method == 'POST':
        subject = request.form.get('subject', '').strip()
        content = request.form.get('content', '').strip()
        attachment = request.form.get('attachment', '').strip()
        target = request.form.get('target', '').strip()
        district = request.form.get('district', '').strip()

        if not subject or not content:
            return render_template('board.html', instructions=instructions[:4],
                                   error=True, message='件名と連絡内容を入力してください。',
                                   form_data=form_data)
        if not district:
            return render_template('board.html', instructions=instructions[:4],
                                   error=True, message='地区を選択してください。',
                                   form_data=form_data)
        if target not in ('全員', '住民', '職員'):
            return render_template('board.html', instructions=instructions[:4],
                                   error=True, message='連絡対象を選択してください。',
                                   form_data=form_data)

        now = get_japan_time()
        new_instruction = {
            'id': max((item.get('id', 0) for item in instructions), default=0) + 1,
            'target': target,
            'information_type': '指示' if target == '職員' else '発信',
            'subject': subject,
            'content': content,
            'attachment': attachment,
            'district': district,
            'status': '発信中',
            'created_at': now,
            'updated_at': now,
        }
        instructions.insert(0, new_instruction)
        save_instructions()
        return redirect(url_for('board'))

    return render_template('board.html', instructions=instructions[:4],
                           form_data={}, show_history=False)


@app.route('/board/history')
@login_required
def board_history():
    return render_template('board.html', instructions=instructions,
                           form_data={}, show_history=True)


@app.route('/board/history/delete/<int:instruction_id>', methods=['POST'])
@login_required
def delete_board_history(instruction_id):
    instruction = next((item for item in instructions
                        if item.get('id') == instruction_id), None)
    if instruction is not None:
        instructions.remove(instruction)
        save_instructions()
    if request.headers.get('Accept') == 'application/json':
        return jsonify({'deleted': instruction is not None})
    return redirect(url_for('board_history'))

# 検索結果ページ：templates/search_results.html を返す
@app.route('/search_results')
def search_results():
    results = filter_shelters(
        request.args.get('district'),
        request.args.get('area')
    )
    return render_template('search_results.html', results=results)

# JSON API：/shelters?district=地区名
@app.route('/shelters', methods=['GET'])
def get_shelters():
    results = filter_shelters(
        request.args.get('district'),
        request.args.get('area')
    )

    if not results:
        # 見つからなければエラー JSON を返す
        return jsonify({'error': 'No shelters found'}), 404

    # 見つかったらリストを JSON で返す
    return jsonify(results)

# 気象警報・注意報API
@app.route('/api/weather_warnings')
def api_weather_warnings():
    """気象警報・注意報をJSON形式で返すAPI"""
    return jsonify(get_weather_warnings())


@app.route('/api/disaster_info/<category>')
def api_disaster_info(category):
    allowed_categories = {'tsunami', 'flood', 'road_flood', 'landslide', 'snow', 'bear'}
    if category not in allowed_categories:
        return jsonify({'error': 'Unknown disaster category'}), 404
    return jsonify(get_disaster_info(category))

if __name__ == '__main__':
    app.run(debug=True, port=5000)
