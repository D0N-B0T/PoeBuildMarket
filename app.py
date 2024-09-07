from bs4 import BeautifulSoup
from flask import Flask, render_template, request, jsonify
from flask_caching import Cache
import requests
import json
import os
import time
import re
from apscheduler.schedulers.background import BackgroundScheduler
from flask import session


app = Flask(__name__)
app.config['CACHE_TYPE'] = 'filesystem'  # Uso de filesystem para rendimiento
app.config['CACHE_DIR'] = 'cache'  # Directorio de caché
cache = Cache(app)
app.config['SECRET_KEY'] = 'your_secret_key'  # Cambia 'your_secret_key' por una clave secreta fuerte

API_URLS = [
    'https://poe-hub.com/api/build-listing/Settlers/Scion',
    'https://poe-hub.com/api/build-listing/Settlers/Templar',
    'https://poe-hub.com/api/build-listing/Settlers/Ranger',
    'https://poe-hub.com/api/build-listing/Settlers/Witch',
    'https://poe-hub.com/api/build-listing/Settlers/Marauder',
    'https://poe-hub.com/api/build-listing/Settlers/Shadow',
    'https://poe-hub.com/api/build-listing/Settlers/Duelist'
]

CACHE_FILE = 'builds_cache.json'
CACHE_TIMEOUT = 300  # 5 minutos

# --- Manejo de Caché ---
def fetch_builds_from_api():
    """Obtiene las builds desde la API."""
    try:
        responses = [requests.get(url) for url in API_URLS]
        data = [res.json() for res in responses]
        all_builds = [item for sublist in [d.get('data', []) for d in data] for item in sublist]
        return all_builds
    except Exception as e:
        print(f"Error fetching builds: {e}")
        return []

def remove_duplicate_builds(builds):
    """Elimina builds duplicadas basado en el link de pobb.in."""
    seen_links = set()
    unique_builds = []
    for build in builds:
        pob_link = build.get('pobLink')  # Suponiendo que 'pobLink' es el campo donde se almacena el link de pobb.in
        if pob_link and pob_link not in seen_links:
            unique_builds.append(build)
            seen_links.add(pob_link)

    return unique_builds

def load_cached_builds():
    """Carga builds desde el archivo cacheado o renueva la caché eliminando duplicados basados en pobb.in."""
    if os.path.exists(CACHE_FILE) and (time.time() - os.path.getmtime(CACHE_FILE)) < CACHE_TIMEOUT:
        with open(CACHE_FILE, 'r') as file:
            builds = json.load(file)
            return remove_duplicate_builds(builds)
    # Intentar restaurar desde la copia de seguridad en caso de que el archivo principal no esté disponible
    if not os.path.exists(CACHE_FILE):
        restore_from_backup()

    print("Renovando caché...")
    builds = fetch_builds_from_api()
    unique_builds = remove_duplicate_builds(builds)
    save_builds_to_cache(unique_builds)
    return unique_builds

def update_cache():
    """Actualiza la caché con nuevas builds eliminando duplicados basados en pobb.in."""
    try:
        current_builds = load_cached_builds()
        new_builds = fetch_builds_from_api()
        print(f"Actualizando caché... ({len(new_builds)} builds)")

        # Unimos las builds actuales y nuevas, y eliminamos duplicados usando el link de pobb.in
        all_builds = current_builds + new_builds
        unique_builds = remove_duplicate_builds(all_builds)

        save_builds_to_cache(unique_builds)
    except Exception as e:
        print(f"Error updating cache: {e}")
        restore_from_backup()  # Intentar restaurar desde la copia de seguridad en caso de error



def save_builds_to_cache(builds):
    """Guarda las builds en el archivo de caché y realiza una copia de seguridad."""
    try:
        # Guardar builds en el archivo principal
        with open(CACHE_FILE, 'w') as file:
            json.dump(builds, file)

        # Realizar copia de seguridad
        backup_file = CACHE_FILE + '.backup'
        with open(backup_file, 'w') as file:
            json.dump(builds, file)

        print("Datos guardados y copia de seguridad realizada.")
    except Exception as e:
        print(f"Error saving builds to cache: {e}")

def restore_from_backup():
    """Restaura builds desde el archivo de copia de seguridad."""
    backup_file = CACHE_FILE + '.backup'
    if os.path.exists(backup_file):
        with open(backup_file, 'r') as file:
            builds = json.load(file)
            save_builds_to_cache(builds)  # Restaurar al archivo principal
            print("Restauración desde copia de seguridad completada.")
    else:
        print("No se encontró copia de seguridad para restaurar.")

@app.route('/favorite', methods=['POST'])
def add_favorite():
    """Agrega una build a la lista de favoritas."""
    build_id = request.json.get('build_id')
    if not build_id:
        return jsonify({"error": "No build_id provided"}), 400

    # Inicializar lista de favoritos si no existe
    if 'favorites' not in session:
        session['favorites'] = []

    # Agregar la build a favoritos si no está ya añadida
    if build_id not in session['favorites']:
        session['favorites'].append(build_id)
        session.modified = True  # Marca la sesión como modificada

    return jsonify({"success": True, "favorites": session['favorites']})


@app.route('/unfavorite', methods=['POST'])
def remove_favorite():
    """Elimina una build de la lista de favoritas."""
    build_id = request.json.get('build_id')
    if not build_id:
        return jsonify({"error": "No build_id provided"}), 400

    if 'favorites' in session and build_id in session['favorites']:
        session['favorites'].remove(build_id)
        session.modified = True

    return jsonify({"success": True, "favorites": session['favorites']})


scheduler = BackgroundScheduler()
scheduler.add_job(update_cache, 'interval', seconds=CACHE_TIMEOUT)
scheduler.start()

# --- Funciones de Utilidad ---
def extract_price(price_str):
    """Extrae el precio numérico de una cadena de texto."""
    try:
        match = re.search(r'(\d+\.?\d*)', price_str)
        return float(match.group(1)) if match else 0.0
    except ValueError:
        return 0.0

# --- Rutas de la Aplicación ---
@app.route('/api/pob-data', methods=['GET'])
def pob_data():
    link = request.args.get('link')
    if not link:
        return jsonify({"error": "No link provided"}), 400

    try:
        response = requests.get(link)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')

        title_meta = soup.find('meta', attrs={'data-xx': '1.5'})
        title = title_meta['content'] if title_meta else 'No title found.'
        description_meta = soup.find('meta', attrs={'data-xx': '1.6'})
        description = description_meta['content'] if description_meta else 'No description found.'

        # Extracción de detalles
        details = re.search(r'â¤ Life: ([^â¤]+)', description)
        details = details.group(1).strip() if details else 'No details found.'

        resistencias = re.search(r'â¤ Resistances: ([^â¤]+)', description)
        resistencias = resistencias.group(1).strip() if resistencias else 'No recommendations found.'

        # Extracción de valores numéricos
        life = re.search(r'(\d{1,3}(?:,\d{3})*) \[(\d+%)\]', details)
        es = re.search(r'ES: (\d+)', details)
        ward = re.search(r'Ward: (\d+)', details)
        mana = re.search(r'Mana: (\d+) \[(\d+%)\]', details)
        ehp = re.search(r'eHP: ([\d,]+)', details)

        return jsonify({
            "title": title,
            "details": details,
            "es": es.group(1) if es else 'No ES found',
            "ward": ward.group(1) if ward else 'No Ward found',
            "mana": mana.group(1) if mana else 'No Mana found',
            "mana_percent": mana.group(2) if mana else 'No Mana percent found',
            "ehp": ehp.group(1) if ehp else 'No eHP found',
            "life": life.group(1) if life else 'No life found',
            "resistencias": resistencias,
        })
    except Exception as e:
        print(f"Error: {e}")
        return jsonify({"error": "Error al obtener datos"}), 500

@app.route('/', methods=['GET'])
def index():
    # Filtros de búsqueda
    search = request.args.get('search', '').lower()
    class_filter = request.args.get('class', '')
    ascendancy_filter = request.args.get('ascendancy', '')
    mainSkill_filter = request.args.get('mainSkill', '')
    min_price_filter = request.args.get('minPrice', '')
    max_price_filter = request.args.get('maxPrice', '')
    build_type_filter = request.args.get('buildType', '')
    sort = request.args.get('sort', '')  # Ordenamiento

    builds = load_cached_builds()

    # Aplicar filtros
    if search:
        builds = [b for b in builds if search in (str(b.get('name', '')).lower() + ' ' + str(b.get('mainSkill', '')).lower())]
    if class_filter:
        builds = [b for b in builds if b.get('class') == class_filter]
    if ascendancy_filter:
        builds = [b for b in builds if b.get('ascendancy') == ascendancy_filter]
    if mainSkill_filter:
        builds = [b for b in builds if b.get('mainSkill') == mainSkill_filter]
    if build_type_filter:
        builds = [b for b in builds if b.get('buildType') == build_type_filter]
    if min_price_filter:
        builds = [b for b in builds if extract_price(b.get('price', '0')) >= float(min_price_filter)]
    if max_price_filter:
        builds = [b for b in builds if extract_price(b.get('price', '0')) <= float(max_price_filter)]

    # Ordenamiento
    if sort == 'price_asc':
        builds = sorted(builds, key=lambda b: extract_price(b.get('price', '0')))
    elif sort == 'price_desc':
        builds = sorted(builds, key=lambda b: extract_price(b.get('price', '0')), reverse=True)

    unique_classes = sorted(set(b.get('class') for b in builds if b.get('class')))
    unique_ascendancies = sorted(set(b.get('ascendancy') for b in builds if b.get('ascendancy')))
    unique_skills = sorted(set(b.get('mainSkill') for b in builds if b.get('mainSkill')))

    return render_template('index.html', builds=builds, unique_classes=unique_classes, unique_ascendancies=unique_ascendancies, unique_skills=unique_skills)

if __name__ == '__main__':
    app.run(debug=True)
