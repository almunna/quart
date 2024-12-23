import tempfile
from quart import Quart, send_from_directory, jsonify, Response, session
from quart_cors import cors, route_cors
import os
import requests

app = Quart(__name__)
app = cors(app, allow_origin="*")

import logging

logging.basicConfig(level=logging.DEBUG)

# Geben Sie den Pfad zu dem Ordner an, den Sie freigeben möchten
STATIC_FOLDER = '/home/personalpeak360/Webseite/CDN/static'

from quart import Quart, request, jsonify, send_file
import os
import io
from io import BytesIO
from PIL import Image
from cachetools import TTLCache
import json

# Ein Cache mit einer TTL (Time-to-Live) von 7200 Sekunden (2 Stunden)
image_cache_avatar = TTLCache(maxsize=100, ttl=7200)


with open('/home/personalpeak360/Webseite/config.json', 'r') as file:
    config = json.load(file)


app = Quart(__name__, template_folder='static')

app.secret_key = config['Session']['secret']

app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.config['JWT_SECRET_KEY'] = config['Session']['jwt_secret']
# app.config['SESSION_TYPE'] = 'redis'
app.config['SESSION_TYPE'] = 'mongodb'
app.config['SESSION_MONGODB_URI'] = f'mongodb://{config['Session']['mongodb']['user']}:{config['Session']['mongodb']['passwort']}@{config['Session']['mongodb']['url']}/{config['Session']['mongodb']['collection']}'
app.config['SESSION_MONGODB_COLLECTION'] = 'Sessions'
app.config['SESSION_USE_SIGNER'] = False
app.config['SESSION_PROTECTION'] = False
app.config['SESSION_COOKIE_DOMAIN'] = ".personalpeak360.de"
app.config['SESSION_COOKIE_NAME'] = 'PP360-Nutzersession'
app.config['SESSION_COOKIE_MAX_AGE'] = 3600
app.config['SESSION_REVERSE_PROXY'] = True

from directus_sdk_py import DirectusClient
client = DirectusClient(url=config['CMS']['url'], token=config['CMS']['access_token'])

url = config['CMS']['url']
DIRECTUS_API_URL = config['CMS']['url']
access_token = config['CMS']['access_token']



@app.route('/track_time', methods=['POST'])
@route_cors(allow_origin="*")
async def track_time():
    data = await request.get_json()
    print(data)
    time_spent_sek = data.get('time_spent', 0)  / 1000  # Zeit in Sekunden umrechnen
    session_ID = data.get('session_ID')
    session_Nutzer = data.get('session_Nutzer')

    # Eintragung der Verweildauer zu der Session_ID
    updated_item = client.update_item(collection_name='Nutzer_Statistik', item_id=session_ID, item_data={'Verweil_Dauer': time_spent_sek})

    print(f"Der Nutzer '{session_Nutzer}' verbrachte unter der Session_ID #{session_ID} {time_spent_sek:.2f} Sekunden auf der Webseite.")
    return '', 204  # Leere Antwort senden



def optimize_image(image_data, width=None, height=None):
    img = Image.open(io.BytesIO(image_data))
    img_format = img.format
    img = img.convert("RGB")
    
    # Anpassung der Bildgröße basierend auf den Parametern width und height
    if width or height:
        # Bestimmen Sie die neuen Abmessungen unter Beibehaltung des Seitenverhältnisses
        if width and not height:
            width = int(width)
            height = int((width / img.width) * img.height)
        elif height and not width:
            height = int(height)
            width = int((height / img.height) * img.width)
        else:
            width = int(width)
            height = int(height)
        
        img.thumbnail((width, height))
    
    img_io = io.BytesIO()
    img.save(img_io, format=img_format, optimize=True, quality=85)
    img_io.seek(0)
    return img_io

@app.route('/download/<file_id>', methods=['GET'])
async def download_file(file_id):
    # URL zum Abrufen der Datei von Directus
    file_url = f"https://cms.personalpeak360.de/assets/{file_id}?access_token={access_token}"

    # Datei von Directus abrufen
    response = requests.get(file_url)

    # Überprüfen, ob die Anfrage erfolgreich war
    if response.status_code == 200:
        # Bestimmen des Content-Type und des Dateinamens
        content_type = response.headers.get('Content-Type', 'application/octet-stream')  # Standardwert
        content_disposition = response.headers.get('Content-Disposition')

        filename = f"{file_id}"  # Standardmäßig die ID als Dateiname verwenden

        # Sicherstellen, dass die Dateiendung korrekt ist
        if 'application/pdf' in content_type:
            extension = '.pdf'
        elif 'image/png' in content_type:
            extension = '.png'
        elif 'image/jpeg' in content_type:
            extension = '.jpg'
        elif 'text/plain' in content_type:
            extension = '.txt'
        else:
            extension = ''  # Für andere Typen keine spezifische Endung setzen

        # Den vollständigen Dateinamen mit der richtigen Endung
        filename_with_extension = filename + extension

        # Schreiben Sie den Inhalt in ein temporäres Verzeichnis
        temp_dir = tempfile.gettempdir()  # Temporäres Verzeichnis
        temp_file_path = os.path.join(temp_dir, filename_with_extension)

        with open(temp_file_path, 'wb') as temp_file:
            temp_file.write(response.content)

        # Datei bereitstellen
        return await send_from_directory(temp_dir, filename_with_extension, as_attachment=True, mimetype=content_type)

    else:
        return jsonify({'error': 'Datei nicht gefunden'}), 404
    

# Beispiel für das Caching, du solltest dies als globale Variable oder in einer geeigneten Speicherstruktur halten
image_cache_avatar = {}


# Bildoptimierungsfunktion (Platzhalter)
def optimize_image(image_data):
    # Deine Logik zur Optimierung des Bildes (z.B. Skalierung oder Kompression)
    return BytesIO(image_data)  # Beispiel, einfach das Bild in BytesIO packen

@app.route('/avatar/<id>', methods=['GET'])
@route_cors(allow_origin="*")
async def avatar(id):
    # Erstellen Sie einen eindeutigen Cache-Schlüssel
    cache_key = f"{id}"

    # Überprüfen, ob das Bild im Cache vorhanden ist
    if cache_key in image_cache_avatar:
        # Wenn ja, direkt die gecachte Response zurückgeben
        print(f"Bild aus Cache geladen für ID: {id}")
        return image_cache_avatar[cache_key]

    image_url = f"https://cms.personalpeak360.de/assets/{id}?access_token={access_token}"

    try:
        print("Anfrage wird NICHT an Cache geleitet")
        # Senden Sie GET-Anfrage, um das Bild herunterzuladen
        response = requests.get(image_url)
        response.raise_for_status()

        # Bildinhaltstyp aus den Antwort-Headern abrufen
        content_type = response.headers.get('content-type', 'application/octet-stream')

        # Antwort mit dem Bildinhalt senden
        image_response = Response(response.content, content_type=content_type)

        # Cache-Control-Header für das Caching im Browser setzen
        image_response.headers['Cache-Control'] = 'public, max-age=31536000'  # 1 Jahr cachen

        # Das Bild zur Cache speichern
        image_cache_avatar[cache_key] = image_response

        return image_response

    except requests.exceptions.RequestException as e:
        return jsonify({"error": f"Fehler beim Abrufen des Avatars: {str(e)}"}), 500


@app.route('/trainingshalle/<id>', methods=['GET'])
async def trainingshalle_data(id):
    image_url = f"https://cms.personalpeak360.de/assets/{id}?access_token={access_token}"
    
    # Hole den Range-Header von der Anfrage
    range_header = request.headers.get('Range', None)
    headers = {}
    if range_header:
        headers['Range'] = range_header

    try:
        # Sende die Anfrage mit dem Range-Header (falls vorhanden)
        response = requests.get(image_url, headers=headers, stream=True)
        response.raise_for_status()

        # Inhaltstyp und Dateigröße aus den Antwort-Headern
        content_type = response.headers.get('content-type', 'application/octet-stream')
        content_length = response.headers.get('content-length')
        status_code = 206 if range_header else 200

        # Erstelle die Antwort mit dem korrekten Inhaltstyp und den Daten
        image_response = Response(response.iter_content(chunk_size=8192), status=status_code, content_type=content_type)
        image_response.headers['Content-Length'] = content_length
        if range_header:
            image_response.headers['Content-Range'] = response.headers.get('Content-Range')

        return image_response

    except requests.exceptions.RequestException:
        return "Fehler beim Abrufen der Trainingshalle-Datei.", 500

@app.route('/white-label/<id>', methods=['GET'])
@route_cors(allow_origin="*")
async def whitelabel_data(id):
    width = request.args.get('width')
    height = request.args.get('height')

    # Erstellen Sie einen eindeutigen Cache-Schlüssel
    cache_key = f"{id}_{width}_{height}"

    # Überprüfen, ob das Bild im Cache vorhanden ist
    if cache_key in image_cache_avatar:
        # Wenn ja, direkt die gecachte Response zurückgeben
        return image_cache_avatar[cache_key]

    image_url = f"https://cms.personalpeak360.de/assets/{id}?access_token={access_token}"

    try:
        print("Anfrage wird NICHT an Cache geleitet")
        # Senden Sie GET-Anfrage, um das Bild herunterzuladen
        response = requests.get(image_url)
        response.raise_for_status()

        # Bildinhaltstyp aus den Antwort-Headern abrufen
        content_type = response.headers.get('content-type', 'application/octet-stream')

        # Antwort mit dem korrekten Inhaltstyp und Original-Bilddaten senden
        image_response = Response(response.content, content_type=content_type)

        # Das Bild zur Cache speichern
        image_cache_avatar[cache_key] = image_response

        return image_response

    except requests.exceptions.RequestException as e:
        return f"Fehler beim Abrufen der WhiteLabel-Datei.", 500
    

@app.route('/trainingsplan-datei/<id>', methods=['GET'])
async def trainingsplan_Datei(id):
    # Breite und Höhe aus den Query-Parametern holen
    width = request.args.get('width')
    height = request.args.get('height')

    # Eindeutiger Cache-Schlüssel basierend auf ID, Breite und Höhe
    cache_key = f"{id}_{width}_{height}"

    # Prüfen, ob das Bild bereits im Cache ist
    if cache_key in image_cache_avatar:
        print("Anfrage wird an Cache geleitet")
        return image_cache_avatar[cache_key]

    # URL des Bildes mit Zugriffstoken
    image_url = f"https://cms.personalpeak360.de/assets/{id}?access_token={access_token}"

    try:
        print("Anfrage wird NICHT an Cache geleitet")
        # Bild von der angegebenen URL herunterladen
        response = requests.get(image_url)
        response.raise_for_status()

        # Bild-Inhaltstyp aus den Antwort-Headern holen
        content_type = response.headers.get('content-type', 'application/octet-stream')

        # Antwort mit dem Bildinhalt erstellen
        image_response = Response(response.content, content_type=content_type)

        # Antwort im Cache speichern
        image_cache_avatar[cache_key] = image_response

        return image_response

    except requests.exceptions.RequestException as e:
        print(f"Fehler beim Abrufen der Datei: {e}")
        return Response("Fehler beim Abrufen der Datei.", status=500)

import hashlib


def generate_etag(file_path):
    """Generiert einen ETag basierend auf dem Dateihash"""
    with open(file_path, "rb") as f:
        return hashlib.md5(f.read()).hexdigest()

@app.route('/<path:filename>')
@route_cors(allow_origin="*")
async def serve_file(filename):
    print(f"File: {filename}")
    try:
        file_path = os.path.join(STATIC_FOLDER, filename)
        if os.path.exists(file_path):
            etag = generate_etag(file_path)
            response = await send_from_directory(STATIC_FOLDER, filename)

            # Setze den ETag-Header
            response.headers['ETag'] = etag

            # Wenn der ETag vom Client passt, sende eine 304 Not Modified Antwort
            if request.headers.get('If-None-Match') == etag:
                return Response(status=304)

            # Cache-Control Header setzen
            response.headers['Cache-Control'] = 'public, max-age=31536000'
            return response
        else:
            return jsonify({"error": "File not found"}), 404
    except Exception as e:
        return jsonify({"error": str(e)})

if __name__ == "__main__":
    app.run(debug=True)


@app.route('/')
@route_cors(allow_origin="*")
async def index():
    return 'CDN Server is running!'