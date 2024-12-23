import asyncio
from asyncio import queues
from collections import defaultdict
from crypt import methods
from datetime import datetime
import io
import logging
import os
from pickletools import float8
import random
import string
import tempfile
from time import time
import uuid
from quart import Quart, Response, g, jsonify, make_response, request, abort, send_file, send_from_directory, render_template, redirect, url_for, session, websocket
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
import json
import base64
import math
import time
from datetime import datetime, timedelta
import locale
# Setze das Locale auf Deutsch
locale.setlocale(locale.LC_TIME, 'de_DE.UTF-8')
from elevenlabs import play
from elevenlabs.client import ElevenLabs
import requests
import deepl
from math import log10
import math
from functools import lru_cache
from pdf_reports import pug_to_html, write_report, preload_stylesheet

import openfoodfacts

# User-Agent is mandatory
Food_API = openfoodfacts.API(user_agent="Personal-Peak-360/2.0")


import mysql.connector
from mysql.connector import Error



from mollie.api.client import Client
from mollie.api.error import Error, UnprocessableEntityError, ResponseError

with open('/home/personalpeak360/Webseite/config.json', 'r') as file:
    config = json.load(file)

mollie_client = Client()
mollie_client.set_api_key(config['Mollie_API']['API_Token'])

ph = PasswordHasher()

app = Quart(__name__, template_folder='static')

app.secret_key = config['Session']['secret']

app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # Maximale Dateigröße 50MB
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

url = config['CMS']['url']
DIRECTUS_API_URL = config['CMS']['url']
access_token = config['CMS']['access_token']

from directus_sdk_py import DirectusClient
client = DirectusClient(url=config['CMS']['url'], token=config['CMS']['access_token'])


# Definiere den benutzerdefinierten Filter
def ceil_zero_decimal(value):
    return math.ceil(value)

def format_date_custom(datum):
    try:
        # Aktuelles Datum im Format "YYYY-MM-DD"
        heute = datetime.today().strftime('%Y-%m-%d')
        
        # Wenn das Datum "Heute" ist, konvertiere es ins heutige Datum im Format "YYYY-MM-DD"
        if datum == "Heute":
            return heute
        
        # Prüfen, ob das Datum bereits im Format "YYYY-MM-DD" ist
        try:
            datum_obj = datetime.strptime(datum, '%Y-%m-%d')  # Format: "YYYY-MM-DD"
        except ValueError:
            # Falls nicht, versuchen, es aus dem Format "dd.mm.yyyy" zu konvertieren
            datum_obj = datetime.strptime(datum, '%d.%m.%Y')  # Format: "dd.mm.yyyy"

        # Rückgabe im gewünschten Format "YYYY-MM-DD"
        return datum_obj.strftime('%Y-%m-%d')
    
    except ValueError:
        # Rückgabe des ursprünglichen Werts, falls ungültiges Datum
        return datum

# Registriere den Filter in der Jinja2-Umgebung
app.jinja_env.filters['ceil_zero_decimal'] = ceil_zero_decimal
app.jinja_env.filters['format_date_custom'] = format_date_custom

def give_reward(user_id, reward_type):
    reward = rewards.get(reward_type)
    if reward:
        points = reward["points"]
        reason = reward["reason"]
        asyncio.create_task(broadcast_notification(user_id, points, reason))


rewards = config['Belohnungen']
class User:
    def __init__(self, websocket):
        self.websocket = websocket
        self.timestamp = datetime.now()
        self.queue = asyncio.Queue()


class WebSocketManager:
    def __init__(self):
        self.connected_users = {}

    async def add_user(self, user_id, websocket):
        if user_id in self.connected_users:
            print(f"Benutzer {user_id} ist bereits verbunden. Verbindung wird geschlossen.")
            await self.connected_users[user_id]['websocket'].close()  # Vorherige Verbindung schließen

        # Speichern des Benutzers und seiner Verbindung
        self.connected_users[user_id] = {
            'websocket': websocket,
            'timestamp': datetime.now(),
            'queue': asyncio.Queue()
        }

    async def send_notification(self, user_id, points, reason):
        message = f"Du hast {points} Punkt/e verdient, indem Du {reason}. Mach weiter so!"
        if user_id in self.connected_users:
            await self.connected_users[user_id]['queue'].put(message)  # Nachricht zur Warteschlange hinzufügen
        else:
            print(f"Benutzer {user_id} ist nicht verbunden.")

    async def broadcast_notification(self, user_id, points, reason):
        if user_id in self.connected_users:
            nutzer_details = client.get_item("Nutzer", int(user_id))  # Verwenden Sie await, wenn es asynchron ist
            for uid, user in self.connected_users.items():
                if int(uid) != int(user_id):  # Nur an andere Benutzer senden
                    message = f"{nutzer_details['Vorname']} {nutzer_details['Nachname']} hat soeben {points} Punkt/e verdient, durch {reason}."
                    await user['queue'].put(message)  # Nachricht zur Warteschlange hinzufügen
                else:
                    print("Nachricht wurde nicht gesendet, da die IDs gleich sind!")

    async def process_notifications(self, user_id):
        if user_id in self.connected_users:
            while True:
                message = await self.connected_users[user_id]['queue'].get()  # Wartet auf eine Nachricht in der Warteschlange
                try:
                    await self.connected_users[user_id]['websocket'].send(message)  # Sende die Nachricht
                except Exception as e:
                    print(f"Fehler beim Senden der Benachrichtigung an Benutzer {user_id}: {e}")
                    break
                finally:
                    self.connected_users[user_id]['queue'].task_done()  # Markiere die Aufgabe als erledigt

    async def check_user_activity(self, user_id):
        while user_id in self.connected_users:
            print("Automatische Punktevergabe wurde automatisch aktiviert.")
            await asyncio.sleep(600)  # Warte 10 Minuten
            last_timestamp = self.connected_users[user_id]['timestamp']
            if last_timestamp and (datetime.now() - last_timestamp >= timedelta(minutes=10)):
                print(self.connected_users)

                # Führe die gewünschte Aktion aus
                await self.send_notification(user_id, 1, "10 Minuten auf unserer Webseite verbracht hast")
                await self.broadcast_notification(user_id, 1, "das Verbringen von 10 Minuten auf unserer Webseite.")

                nutzer = client.get_item("Nutzer", int(user_id))
                punkte = nutzer['Punkte']
                if punkte == None:
                    punkte = 0

                client.update_item("Nutzer", int(user_id), item_data={"Punkte": (int(punkte) + 1)})
                
                # Aktualisiere den Zeitstempel
                self.connected_users[user_id]['timestamp'] = datetime.now()

# Instanz der WebSocketManager-Klasse
ws_manager = WebSocketManager()

@app.websocket('/ws/<ID>')
async def websocket_endpoint(ID):
    if ID is None:
        await websocket.send("User-ID ist erforderlich")
        return

    print(f"Benutzer-ID bei Verbindung: {ID}")

    # Benutzer zur Verwaltung hinzufügen
    await ws_manager.add_user(ID, websocket)

    # Starte die Benachrichtigungsbearbeitung für den Benutzer
    asyncio.create_task(ws_manager.process_notifications(ID))

    # Starte die Aktivitätsüberprüfung für den Benutzer
    asyncio.create_task(ws_manager.check_user_activity(ID))

    try:
        while True:
            message = await websocket.receive()  # Wartet auf Nachrichten vom Client
            print(f"Nachricht von {ID}: {message}")
            # Hier können Sie die Logik für empfangene Nachrichten implementieren
    except Exception as e:
        print(f"Fehler bei der WebSocket-Verbindung: {e}")
    finally:
        if ID in ws_manager.connected_users:
            del ws_manager.connected_users[ID]  # Benutzer entfernen
        print(f"Verbundene Benutzer nach der Trennung: {list(ws_manager.connected_users.keys())}")

# Benachrichtigungsfunktionen (sofern nötig)
async def send_notification(user_id, points, reason):
    await ws_manager.send_notification(user_id, points, reason)

async def broadcast_notification(user_id, points, reason):
    await ws_manager.broadcast_notification(user_id, points, reason)




@app.template_filter('format_time_VerweilDauer')
def format_time_VerweilDauer(seconds):
    if seconds is None:
        return "Nicht bekannt"  # Standardwert, falls None
    
    # Umwandlung in float und Runden
    seconds = float(seconds)
    
    # Berechnung von Tagen, Stunden, Minuten und Sekunden
    days = seconds // 86400  # 1 Tag = 86400 Sekunden
    hours = (seconds % 86400) // 3600  # 1 Stunde = 3600 Sekunden
    minutes = (seconds % 3600) // 60  # 1 Minute = 60 Sekunden
    seconds = seconds % 60  # Restliche Sekunden

    # Formatierung der Ausgabe
    parts = []
    if days > 0:
        parts.append(f"{int(days)} Tag{'e' if days > 1 else ''}")
    if hours > 0:
        parts.append(f"{int(hours)} Stunde{'n' if hours > 1 else ''}")
    if minutes > 0:
        parts.append(f"{int(minutes)} Minute{'n' if minutes > 1 else ''}")
    if seconds > 0 or not parts:  # Wenn kein anderer Wert vorhanden ist, zeige auch Sekunden an
        if seconds < 1:
            return "weniger als 1 Sekunde"
        else:
            parts.append(f"{int(seconds)} Sekunde{'n' if seconds > 1.5 else ''}")

    return "ca. " + ", ".join(parts)  # Teile durch Komma verbinden



async def check_credentials(username, password):
    # Parameters for the GET request
    params = {
        'access_token': access_token,
        'filter[Benutzername][_eq]': username
    }

    # Send the GET request
    nutzer = requests.get(url + "items/Nutzer", params=params)

    data = []

    if nutzer.status_code == 200:  # Ensure a successful response
        try:
            data = nutzer.json().get('data', [])
        except ValueError:
            # Log the raw response content if it's not JSON
            print("Response is not in JSON format:", nutzer.text)
            data = []
    else:
        print(f"Request failed with status code {nutzer.status_code}")

    if not data:
        print("Benutzername nicht gefunden")
        return False  # Benutzername nicht gefunden

    # Fetch the hashed password from the new "Passwort" field
    passwort_hash = data[0].get('Passwort')
    
    # Check if the password hash exists
    if not passwort_hash:
        print("Passwort Hash nicht gefunden")
        return False  # Passwort Hash nicht gefunden

    # Store user details in session
    session['username'] = data[0]['Benutzername']
    g.username = username

    session['id'] = data[0].get('id')

    session['avatar'] = f"https://cdn.personalpeak360.de/avatar/{data[0].get('Avatar')}"
    session['vorname'] = data[0].get('Vorname')
    session['nachname'] = data[0].get('Nachname')
    session['name'] = f"{data[0].get('Vorname')} {data[0].get('Nachname')}"
    session['rolle'] = data[0].get('Rolle')
    session['Nutzer_Level'] = data[0].get('Nutzer_Level')
    session['WhiteLabel_Domain'] = g.customer_domain.replace("auth.", "", 1)
    session['WhiteLabel'] = g.whitelabel_info
    print(data[0].get('WhiteLabel'))
    if data[0].get('WhiteLabel'):
        print("---- Nutzer ist kein Admin eines White-Labels ----")
        print(f"Nutzerdaten: {data[0]}")
        print(data[0].get('WhiteLabel'))
        session['WhiteLabel_Admin'] = {
            "id": data[0].get('WhiteLabel')['key'],  # Sichere Abfrage des Schlüssels 'key'
            "admin": True
        }
    else:
        print("++++ Nutzer ist Admin eines White-Labels ++++")
        print(data[0].get('WhiteLabel'))
        session['WhiteLabel_Admin'] = {
            "id": None,
            "admin": False
        }


    g.rolle = data[0].get('Rolle')

    try:
        # Check the password using argon2
        ph.verify(passwort_hash, password)
        print("Richtiges Passwort")
        return True  # Anmeldeinformationen korrekt
    except VerifyMismatchError:
        print("Falsches Passwort")
        return False  # Anmeldeinformationen inkorrekt


@app.before_request
async def check_berechtigungen():
    g.berechtigungen = {
        "Admin-Bereich": {
            "Benutzer": True,
            "Analyse": True,
            "Benutzer": True,
            "Benutzer": True,
            "Benutzer": True,
            "Benutzer": True,
            "Benutzer": True
        }
    }
    

@app.before_request
async def handle_whitelabel():
    customer_domain = request.host
    g.customer_domain = customer_domain
    print(f"Aufruf über: '{customer_domain}'")
    nach_subdomain = subdomain = customer_domain.split('.')[1]
    print(f"Teil nach Subdomain: '{nach_subdomain}'")

    # AUFRUF ÜBER PERSONALPEAK (SUB-)DOMAIN
    if customer_domain.endswith('.personalpeak360.de') and nach_subdomain == "personalpeak360":
        subdomain = customer_domain.split('.')[0]
        print(f"Subdomain: {subdomain}")
        # Wenn die Subdomain nicht "dashboard", "auth" oder "cdn" ist, diese in customer_domain übernehmen
        if subdomain not in ['dashboard', 'auth', 'cdn', 'www']:
            customer_domain = subdomain + '.personalpeak360.de'

            app.config['SESSION_COOKIE_DOMAIN'] = f".{customer_domain}"
        else:
            customer_domain = 'personalpeak360.de'
            app.config['SESSION_COOKIE_DOMAIN'] = '.personalpeak360.de'

    # AUFRUF ÜBER EIGENE (SUB-)DOMAIN
    else:
        subdomain = customer_domain.split('.')[0]
        domain_after_subdomain = '.'.join(customer_domain.split('.')[1:])
        print(f"DOMAIN AFTER SUBDOMAIN {domain_after_subdomain}")
        # Wenn die Subdomain nicht "dashboard", "auth" oder "cdn" ist, diese in customer_domain übernehmen
        if subdomain not in ['dashboard', 'auth', 'cdn', 'www']:
            customer_domain = domain_after_subdomain

            app.config['SESSION_COOKIE_DOMAIN'] = f".{domain_after_subdomain}"
        else:
            customer_domain = customer_domain
            app.config['SESSION_COOKIE_DOMAIN'] = f'.{customer_domain}'
    
    g.customer_domain = customer_domain
    
    print(customer_domain)

    request_directus = {
        "query": {
            "filter": {
                "Domain": {
                    "_eq": customer_domain  # Filter für die Domain
                }
            }
        }
    }

    # Die Items von der Collection "WhiteLabel" abrufen
    try:
        data = client.get_items("WhiteLabel", request_directus)

        print(data)
        if 'error' in data:
            print(f"Fehler: {data['error']}")
            g.whitelabel_info = {}
            print(f"Keine WhiteLabel-Informationen für {customer_domain} gefunden.")
            return await render_template("/Seiten/FEHLER/keineLizenz.html", domain = customer_domain)
        else:
            if data:  # Überprüfen, ob Daten vorhanden sind
                g.whitelabel_info = data[0]  # Speichere die Whitelabel-Informationen in g
                print(f"WhiteLabel-Info: {g.whitelabel_info}")
            else:
                g.whitelabel_info = {}
                print(f"Keine WhiteLabel-Informationen für {customer_domain} gefunden.")
                return await render_template("/Seiten/FEHLER/keineLizenz.html", domain = customer_domain)
    except Exception as e:
        print(f"Fehler beim Abrufen der Daten: {e}")


@app.before_request
async def check_ip_block():
    if not session.get('logged_in'):
        session['error'] = "Sie müssen sich anmelden!"

        # URL auf HTTPS umstellen
        redirect_url = request.url if request.url.startswith("https://") else request.url.replace("http://", "https://")
        # Setzen des Cookies
        # Setzen des Cookies mit Pfad auf '/'
        response = redirect(f"https://auth.{g.whitelabel_info['Domain']}")
        response = await make_response(response)
        max_age = 30 * 24 * 60 * 60  # Cookie für 30 Tage gültig
        expires = datetime.utcnow() + timedelta(seconds=max_age)
        response.set_cookie('PP360-Redirect', redirect_url, max_age=max_age, expires=expires, path='/', domain=f".{g.whitelabel_info['Domain']}", secure=True, httponly=True)
        print(f'Setting redirect URL: {redirect_url}')
        return response
    else:
        return


@app.before_request
async def handle_BildschirmSperrung():
    if session.get('logged_in'):
        if request.path != "/logout":
            if session.get('bildschirm_sperre'):
                if request.method == "GET":
                    name = session.get('name')
                    rolle = session.get('rolle')
                    success = session.pop('success', None)
                    punkte = session.pop('Punkte_Nachricht', None)
                    punkte_nachricht = punkte
                    error = session.pop('error', None)

                    return await render_template('/parts/Seiten/lock-screen.html', success=success, error=error, punkte = punkte, punkte_nachricht = punkte_nachricht , name=name, rolle=rolle, avatar_url=session.get('avatar'), nutzer_level=session.get('Nutzer_Level'), WHITELABEL_Domain=g.customer_domain, WhiteLabel = g.whitelabel_info, nutzername=session.get('username'))
                else:
                    data = await request.form

                    username = session.get('username')
                    password = data.get('passwort')
                    #return f"NUtzer: {username}, Passwort {password}"

                    
                    if await check_credentials(username, password):
                        ip = request.headers.get('X-Forwarded-For')  # Holen Sie die IP des Benutzers
                        banned_ips = session.get('Banned_IPs', [])

                        if banned_ips is None:
                            banned_ips = []

                        if ip not in banned_ips:
                            session['success'] = f'Sie sind nun wieder als {g.rolle} angemeldet!'
                            session['logged_in'] = True
                            session['bildschirm_sperre'] = False
                            session['username'] = g.username
                            session['ip'] = ip
                            
                            # IP-Adresse des Benutzers abrufen
                            ip = request.headers.get('X-Forwarded-For')
                            # Durchgeführte Aktion
                            action = "Anmeldung"

                            return redirect(f"https://auth.{g.customer_domain}/willkommen")
                        else:
                            session['error'] = f'Diese IP-Adresse wurde für das Benutzerkonto gesperrt.'
                            return redirect(f"https://www.{g.customer_domain}/")
                    else:
                        session['error'] = f'Ungültige Anmeldeinformationen.'
                        return redirect(f"https://auth.{g.customer_domain}/")
        else:
            pass
    else:
        pass


from user_agents import parse


@app.before_request
async def Log_Requests():
    # Aktuelles Datum und Uhrzeit
    now = datetime.now()
    date_time = now.strftime("%H:%M:%S")
    
    # Pfad und URL der Anfrage
    path = request.path
    url = request.url
    ip_address = request.headers.get('X-Forwarded-For')
    
    # User-Agent-String abrufen
    user_agent_string = request.headers.get('User-Agent')
    user_agent = parse(user_agent_string)

    # Gerätetyp bestimmen
    device = "Desktop" if user_agent.is_pc else "Mobilgerät" if user_agent.is_mobile else "Tablet"

    # User-Agent auf Deutsch übersetzen
    browser = f"{user_agent.browser.family} {user_agent.browser.version_string}"
    os = f"{user_agent.os.family} {user_agent.os.version_string}"
    platform = f"{user_agent.device.family}"

    # Log-Eintrag erstellen
    log_entry = {
        "Nutzer_ID": session.get('id'),
        "Typ": "Seitenaufruf",
        "Datum": now.date().isoformat(),
        "Daten": {
            "Datum": now.date().isoformat(),
            "Uhrzeit": date_time,
            "Path": path,
            "URL": url,
            "IP": ip_address,
            "Fehlermeldung": session.get('error'),
            "Erfolgsmeldung": session.get('success'),
            "Gerät": {
                "Browser": browser,
                "Betriebssystem": os,
                "Plattform": platform,
                "Gerät": device
            },
            "Instanz": g.customer_domain
        }
    }

    new_item = client.create_item(collection_name='Nutzer_Statistik', item_data=log_entry)

    # Optional: Log in der Konsole ausgeben
    print(log_entry)

    print(new_item['data']['id'])

    g.Session_Info = {
        "LogEntry_ID": new_item['data']['id']  # Hier wird die id korrekt abgerufen
    }


async def fetch_data(date_filter, id):
    request = {
        "query": {
            "filter": {
                "Datum": date_filter,
                "Nutzer_ID": {
                    "_eq": id
                }
            },
            "limit": 2000
        }
    }
    items = client.get_items("Nutzer_Statistik", request)
    if items == {"error": "No data found for this request : 'data'"}:
        items = []
    return items



@app.route('/')
async def dashboard():
    success = session.pop('success', None)
    punkte = session.pop('Punkte_Nachricht', None)
    punkte_nachricht = punkte
    error = session.pop('error', None)
    
    header = await render_template('/parts/Elemente/header.html', url= request.url, WhiteLabel = g.whitelabel_info, avatar_url=session.get('avatar'), rolle=session.get('rolle'), name=session.get('name'), Nutzer_Punkte=session.get('Nutzer_Punkte'))
    sidebar = await render_template('/parts/Elemente/sidebar.html', WhiteLabel = g.whitelabel_info, rolle=session.get('rolle'))
    footer = await render_template('/parts/Elemente/footer.html', WhiteLabel = g.whitelabel_info, Session_Info=g.Session_Info['LogEntry_ID'], nutzername=session.get('username'), nutzer_ID=session.get('id'))
    theme_customizer = await render_template('/parts/Elemente/theme-customizer.html', WhiteLabel = g.whitelabel_info)


    query_ranking = {
        "query": {
            "limit": 5,
            "sort": "-Punkte"  # Ensure sorting is a list, not a string
        }
    }
    nutzer_ranking = client.get_items('Nutzer', query_ranking)

    aktueller_nutzer = client.get_item('Nutzer', session.get('id'))

    print(nutzer_ranking)
    print(g.whitelabel_info['id'])

    return await render_template('/parts/Seiten/Startseite.html', header=header, sidebar=sidebar, footer=footer, theme_customizer=theme_customizer, success=success, error=error, punkte = punkte, punkte_nachricht = punkte_nachricht, Nutzer_Punkte=session.get('Nutzer_Punkte'), username=session.get('username'), rolle=session.get('rolle'), name=session.get('name'), avatar_url=session.get('avatar'), WhiteLabel = g.whitelabel_info, nutzer_level=session.get('Nutzer_Level'), Next_Level_Upgrade=session.get('Next_Level_Upgrade'), Nutzer_Ranking=nutzer_ranking, Aktueller_Nutzer=aktueller_nutzer, Nutzer_ID = session.get('id'))


@app.route('/kachel/<kachel>')
async def kacheln(kachel):
    success = session.pop('success', None)
    punkte = session.pop('Punkte_Nachricht', None)
    punkte_nachricht = punkte
    error = session.pop('error', None)
    
    header = await render_template('/parts/Elemente/header.html', url= request.url, WhiteLabel = g.whitelabel_info, avatar_url=session.get('avatar'), rolle=session.get('rolle'), name=session.get('name'), Nutzer_Punkte=session.get('Nutzer_Punkte'))
    sidebar = await render_template('/parts/Elemente/sidebar.html', WhiteLabel = g.whitelabel_info, rolle=session.get('rolle'))
    footer = await render_template('/parts/Elemente/footer.html', WhiteLabel = g.whitelabel_info, Session_Info=g.Session_Info['LogEntry_ID'], nutzername=session.get('username'), nutzer_ID=session.get('id'))
    theme_customizer = await render_template('/parts/Elemente/theme-customizer.html', WhiteLabel = g.whitelabel_info)

    if kachel == "Admin-Bereich":
        return await render_template('/parts/Seiten/Kacheln/Admin-Bereich.html', header=header, sidebar=sidebar, footer=footer, theme_customizer=theme_customizer, success=success, error=error, punkte = punkte, punkte_nachricht = punkte_nachricht, username=session.get('username'), rolle=session.get('rolle'), name=session.get('name'), avatar_url=session.get('avatar'), WhiteLabel = g.whitelabel_info, nutzer_level=session.get('Nutzer_Level'))
    elif kachel == "Cockpit":
        return await render_template('/parts/Seiten/Kacheln/Cockpit.html', header=header, sidebar=sidebar, footer=footer, theme_customizer=theme_customizer, success=success, error=error, punkte = punkte, punkte_nachricht = punkte_nachricht, username=session.get('username'), rolle=session.get('rolle'), name=session.get('name'), avatar_url=session.get('avatar'), WhiteLabel = g.whitelabel_info, nutzer_level=session.get('Nutzer_Level'))
    elif kachel == "Ernährungshalle":
        return await render_template('/parts/Seiten/Kacheln/Ernährungshalle.html', header=header, sidebar=sidebar, footer=footer, theme_customizer=theme_customizer, success=success, error=error, punkte = punkte, punkte_nachricht = punkte_nachricht, username=session.get('username'), rolle=session.get('rolle'), name=session.get('name'), avatar_url=session.get('avatar'), WhiteLabel = g.whitelabel_info, nutzer_level=session.get('Nutzer_Level'))
    elif kachel == "Trainingshalle":
        return await render_template('/parts/Seiten/Kacheln/Trainingshalle.html', header=header, sidebar=sidebar, footer=footer, theme_customizer=theme_customizer, success=success, error=error, punkte = punkte, punkte_nachricht = punkte_nachricht, username=session.get('username'), rolle=session.get('rolle'), name=session.get('name'), avatar_url=session.get('avatar'), WhiteLabel = g.whitelabel_info, nutzer_level=session.get('Nutzer_Level'))


def allowed_file(filename):
    # Überprüfe, ob die Datei eine erlaubte Erweiterung hat
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in {'mp4'}

import tempfile

async def generate_VoiceOver(text, lang_code):
    """Generates a VoiceOver audio file and returns the path to the temporary file."""
    ElevenLabs_Client = ElevenLabs(api_key=g.whitelabel_info['API_TOKEN_ElevenLabs'])  # API key
    
    # Select voice and model here
    audio = ElevenLabs_Client.generate(
        text=text,
        voice="Brian",  # You can change the voice here
        model="eleven_multilingual_v2",  # The model supporting multilingual
    )

    audio = b''.join(audio)  # Convert generator to bytes

    # Create a temporary file to save the audio
    with tempfile.NamedTemporaryFile(delete=False, suffix='.mp3') as temp_file:
        temp_file.write(audio)  # Write bytes to the file
        temp_file_path = temp_file.name  # Get the temporary file path

    return temp_file_path


async def process_voiceover(text, lang_code):
    """Generiert und lädt ein VoiceOver hoch."""
    # VoiceOver generieren
    temp_audio_path = await generate_VoiceOver(text, lang_code)

    print("######################################")
    print("## VOICEOVER UPLOAD WURDE GESTARTET ##")
    print("######################################")

    # Temporäre Datei hochladen
    upload_data = {
        "title": "Voiceover",
        "description": f"Voiceover für Übung",
        "tags": ["Voiceover", "Übung"],
        "type": "audio/mpeg"  # Der Dateityp, je nach Dateiformat
    }

    # Datei hochladen (hier benötigst du die Methode upload_file vom Client)
    uploaded_file = client.upload_file(temp_audio_path, upload_data)

    # Temporäre Datei nach dem Upload löschen
    os.remove(temp_audio_path)

    print("####################################")
    print("## VOICEOVER UPLOAD WURDE BEENDET ##")
    print("####################################")

    return uploaded_file['id']


from werkzeug.datastructures import FileStorage
import mimetypes


@app.route('/admin/trainingshalle/übungen', methods=['GET', 'POST'])
async def ADMIN_Trainingshalle_Uebungen():
    if request.method == "GET":
        success = session.pop('success', None)
        punkte = session.pop('Punkte_Nachricht', None)
        punkte_nachricht = punkte
        error = session.pop('error', None)

        header = await render_template('/parts/Elemente/header.html', url= request.url, 
                                                    WhiteLabel=g.whitelabel_info, 
                                                    avatar_url=session.get('avatar'), 
                                                    rolle=session.get('rolle'), 
                                                    name=session.get('name'), Nutzer_Punkte=session.get('Nutzer_Punkte'))
        sidebar = await render_template('/parts/Elemente/sidebar.html', 
                                        WhiteLabel=g.whitelabel_info, rolle=session.get('rolle'))
        footer = await render_template('/parts/Elemente/footer.html', WhiteLabel = g.whitelabel_info, Session_Info=g.Session_Info['LogEntry_ID'], nutzername=session.get('username'), nutzer_ID=session.get('id'))

        theme_customizer = await render_template('/parts/Elemente/theme-customizer.html', 
                                                WhiteLabel=g.whitelabel_info)
        
        
        # Die Items von der Collection "Nutzer" abrufen
        try:
            data = client.get_items("Uebungen")

            if 'error' in data:
                Übungen = []
                print(f"Fehler: {data['error']}")
            else:
                if data:  # Überprüfen, ob Daten vorhanden sind
                    Übungen = data  # Speichere die Whitelabel-Informationen in g
                else:
                    Übungen = []
        except Exception as e:
            print(f"Fehler beim Abrufen der Daten: {e}")

        Übungs_Liste = []

        for Übung in Übungen:
            if Übung['WhiteLabel'] == {'key': g.whitelabel_info['id'], 'collection': 'WhiteLabel'} and Übung['Ersteller'] == {'key': session.get('id'), 'collection': 'Nutzer'}:
                Übungs_Liste.append(Übung)


        # Rendern der Vorschau-HTML-Vorlage mit den erhaltenen Parametern
        return await render_template(f'/parts/Seiten/Admin-Bereich/Trainingshalle/Übungen.html', 
                                    header=header,
                                    error=error, 
                                    success=success, 
                                    sidebar=sidebar, 
                                    footer=footer, 
                                    theme_customizer=theme_customizer,
                                    username=session.get('username'), 
                                    rolle=session.get('rolle'), 
                                    name=session.get('name'), 
                                    avatar_url=session.get('avatar'), 
                                    WhiteLabel=g.whitelabel_info,
                                    Übungen = Übungs_Liste)
    else:
        if request.args.get('Art') == "Update":
            Übung_ID = request.args.get('ID')

            # Aktuellen Datenbestand der zu ändernden Übung abrufen
            AktuelleÜbung_Details = client.get_item("Uebungen", Übung_ID)

            request.body_timeout = None

            # Formulardaten und Dateien abrufen
            data = await request.form
            files = await request.files
            whitelabel_id = session.get('WhiteLabel_Admin')['id']

            Übung_Details = {
                "Typ": data.get('Typ'),
                "Name": data.get('Name'),
                "Hinweise": data.get('Hinweise'),
                "Tipps": data.get('Tipps'),
                "Muskelgruppen": data.getlist('Muskelgruppen'),
                "Suchbegriffe": data.getlist('suchbegriffe[]')
            }

            if data.get('Typ') == "Gesundheit":
                Übung_Details['Gesundheitsproblem'] = data.get('Gesundheitsproblem')
            else:
                Übung_Details['Gesundheitsproblem'] = None

            # Hilfsfunktion zum temporären Speichern der Datei
            async def save_temp_file(file_storage):
                temp_file = tempfile.NamedTemporaryFile(delete=False)
                try:
                    temp_file.write(file_storage.read())
                    temp_file.close()
                    return temp_file.name
                except Exception as e:
                    temp_file.close()
                    os.remove(temp_file.name)
                    raise e

            async def upload_video(file_storage):
                print("##################################")
                print("## VIDEO UPLOAD WURDE GESTARTET ##")
                print("##################################")
                temp_file_path = await save_temp_file(file_storage)
                upload_data = {
                    "title": file_storage.filename,
                    "description": f"Video-Animation für Übung '{Übung_Details['Name']}'",
                    "tags": ["Video-Animation", "Übung", f"{Übung_Details['Name']}"],
                    "type": file_storage.content_type
                }
                uploaded_file = client.upload_file(temp_file_path, upload_data)
                os.remove(temp_file_path)
                print("################################")
                print("## VIDEO UPLOAD WURDE BEENDET ##")
                print("################################")
                return uploaded_file['id']

            async def upload_voiceover(file_storage):
                print("######################################")
                print("## VOICEOVER UPLOAD WURDE GESTARTET ##")
                print("######################################")
                temp_file_path = await save_temp_file(file_storage)
                upload_data = {
                    "title": file_storage.filename,
                    "description": f"Voiceover für Übung '{Übung_Details['Name']}'",
                    "tags": ["Voiceover", "Übung", f"{Übung_Details['Name']}"],
                    "type": file_storage.content_type
                }
                uploaded_file = client.upload_file(temp_file_path, upload_data)
                os.remove(temp_file_path)
                print("####################################")
                print("## VOICEOVER UPLOAD WURDE BEENDET ##")
                print("####################################")
                return uploaded_file['id']
            
            # Ergebnis-Dictionary, um die Daten zu speichern
            Texte = {}


            if files['Video_Animation']:
                video_upload = upload_video(files['Video_Animation'])
                try:
                    file_ID_Animation = await video_upload
                except Exception as e:
                    app.logger.error(f"Fehler beim Upload der Video-Animation: {e}")
            else:
                file_ID_Animation = AktuelleÜbung_Details['Animation']

            # Verfügbare Sprachen
            languages = ["DE", "EN", "ES", "AR", "GR", "RU"]

            # Hole die Liste aus dem Request-Daten
            selected_text_languages = data.getlist("languagesSelect_Text[]")
            selected_voiceover_languages = data.getlist("languagesSelect_Voiceover[]")


            for lang in languages:
                # Textdaten
                Texte[lang] = {
                    "Name": data.get(f"Name_{lang}"),
                    "Hinweise": data.get(f"Hinweise_{lang}"),
                    "Tipps": data.get(f"Tipps_{lang}")
                }


            # Texte übersetzen, falls "Bestimmte" ausgewählt wurde
            if data.get("Generiere_Texte") == "Bestimmte" and selected_text_languages:
                for lang in selected_text_languages:
                    if lang not in Texte:
                        Texte[lang] = {}

                    translator = deepl.Translator(g.whitelabel_info['API_TOKEN_Deepl'])
                    
                    # Variable, um festzustellen, ob mindestens ein Textabschnitt vorhanden ist
                    hat_text = False

                    # Dynamisch Quellsprache bestimmen
                    def finde_quellsprache(field):
                        for lang in languages:
                            if data.get(f"{field}_{lang}"):
                                return lang
                    
                    quellsprache_hinweise = finde_quellsprache("Hinweise")
                    quellsprache_tipps = finde_quellsprache("Tipps")
                    quellsprache_name = finde_quellsprache("Name")


                    if quellsprache_name:
                        ausgangstext_name = data.get(f"Name_{quellsprache_name}", "")
                        
                        if lang == "GR":
                            Texte[lang]["Name"] = translator.translate_text(ausgangstext_name, target_lang="EL").text
                        elif lang == "EN":
                            Texte[lang]["Name"] = translator.translate_text(ausgangstext_name, target_lang="EN-US").text
                        else:
                            Texte[lang]["Name"] = translator.translate_text(ausgangstext_name, target_lang=lang).text
                    if quellsprache_hinweise:
                        ausgangstext_hinweise = data.get(f"Hinweise_{quellsprache_hinweise}", "")
                        
                        if lang == "GR":
                            Texte[lang]["Hinweise"] = translator.translate_text(ausgangstext_hinweise, target_lang="EL").text
                        elif lang == "EN":
                            Texte[lang]["Hinweise"] = translator.translate_text(ausgangstext_hinweise, target_lang="EN-US").text
                        else:
                            Texte[lang]["Hinweise"] = translator.translate_text(ausgangstext_hinweise, target_lang=lang).text
                    if quellsprache_tipps:
                        ausgangstext_tipps = data.get(f"Tipps_{quellsprache_tipps}", "")
                        
                        if lang == "GR":
                            Texte[lang]["Tipps"] = translator.translate_text(ausgangstext_tipps, target_lang="EL").text
                        elif lang == "EN":
                            Texte[lang]["Tipps"] = translator.translate_text(ausgangstext_tipps, target_lang="EN-US").text
                        else:
                            Texte[lang]["Tipps"] = translator.translate_text(ausgangstext_tipps, target_lang=lang).text


            # AktuelleÜbung_Details['Texte']

            for lang in languages:
                # Voiceover-Datei hochladen
                voiceover_file = files.get(f"Voiceover_{lang}")
                if voiceover_file:
                    voiceover_upload = upload_voiceover(voiceover_file)
                    try:
                        file_ID_Voiceover = await voiceover_upload
                        Texte[lang]["Voiceover_ID"] = file_ID_Voiceover
                    except Exception as e:
                        app.logger.error(f"Fehler beim Upload des Voiceovers ({lang}): {e}")
                        Texte[lang]["Voiceover_ID"] = None
                else:
                    if 'Voiceover_ID' in AktuelleÜbung_Details['Texte'][lang] and AktuelleÜbung_Details['Texte'][lang]['Voiceover_ID']:
                        Texte[lang]["Voiceover_ID"] = AktuelleÜbung_Details['Texte'][lang]['Voiceover_ID']
                    else:
                        Texte[lang]["Voiceover_ID"] = None

            if data.get("Generiere_Texte") == "Alles":
                # Initialisiere die Liste für die Sprachen ohne Voiceover
                texte_für_voiceover = {}
                languages = ["DE", "EN", "ES", "AR", "GR", "RU"]

                # Variable, um festzustellen, ob mindestens ein Textabschnitt vorhanden ist
                hat_text = False

                # Dynamisch Quellsprache bestimmen
                def finde_quellsprache(field):
                    for lang in languages:
                        if data.get(f"{field}_{lang}"):
                            return lang
                    return None

                quellsprache_hinweise = finde_quellsprache("Hinweise")
                quellsprache_tipps = finde_quellsprache("Tipps")
                quellsprache_name = finde_quellsprache("Name")

                if not (quellsprache_hinweise or quellsprache_tipps or quellsprache_name):
                    print("Keine Quelltexte gefunden. Abbruch.")
                    return

                # Durchlaufe alle Sprachen
                for lang in languages:
                    hinweise_text = data.get(f"Hinweise_{lang}")
                    tipps_text = data.get(f"Tipps_{lang}")
                    name_text = data.get(f"Name_{lang}")

                    if (hinweise_text and tipps_text and name_text) and not files.get(f"Voiceover_{lang}"):
                        texte_für_voiceover[lang] = {
                            "Hinweise": hinweise_text or "",
                            "Tipps": tipps_text or "",
                            "Name": name_text or ""
                        }
                        hat_text = True

                # Falls kein Text gefunden wurde, abbrechen
                if not hat_text:
                    print("Keine Texte zum Generieren gefunden.")
                    return

                print(f"TEXTE FÜR VOICEOVER: {texte_für_voiceover}")

                # Sprachen generieren mit Deepl Pro API
                fehlende_sprachen = [lang for lang in languages if lang not in texte_für_voiceover]
                for sprache in fehlende_sprachen:
                    if sprache == "GR":
                        try:
                            translator = deepl.Translator(g.whitelabel_info['API_TOKEN_Deepl'])

                            # Generiere Hinweise
                            if quellsprache_hinweise:
                                ausgangstext_hinweise = data.get(f"Hinweise_{quellsprache_hinweise}", "")
                                if ausgangstext_hinweise:
                                    übersetzter_hinweise = translator.translate_text(ausgangstext_hinweise, target_lang="EL")
                                    texte_für_voiceover.setdefault(sprache, {})["Hinweise"] = übersetzter_hinweise.text
                                    Texte[sprache]["Hinweise"] = übersetzter_hinweise.text
                                    print(f"Hinweise für {sprache}: {übersetzter_hinweise.text}")

                            # Generiere Tipps
                            if quellsprache_tipps:
                                ausgangstext_tipps = data.get(f"Tipps_{quellsprache_tipps}", "")
                                if ausgangstext_tipps:
                                    übersetzter_tipps = translator.translate_text(ausgangstext_tipps, target_lang="EL")
                                    texte_für_voiceover[sprache]["Tipps"] = übersetzter_tipps.text
                                    Texte[sprache]["Tipps"] = übersetzter_tipps.text
                                    print(f"Tipps für {sprache}: {übersetzter_tipps.text}")

                            # Generiere Namen
                            if quellsprache_name:
                                ausgangstext_name = data.get(f"Name_{quellsprache_name}", "")
                                if ausgangstext_name:
                                    übersetzter_name = translator.translate_text(ausgangstext_name, target_lang="EL")
                                    texte_für_voiceover[sprache]["Name"] = übersetzter_name.text
                                    Texte[sprache]["Name"] = übersetzter_name.text
                                    print(f"Name für {sprache}: {übersetzter_name.text}")

                        except Exception as e:
                            print(f"Fehler bei der Übersetzung für {sprache}: {str(e)}")
                    elif sprache == "EN":
                        try:
                            translator = deepl.Translator(g.whitelabel_info['API_TOKEN_Deepl'])

                            # Generiere Hinweise
                            if quellsprache_hinweise:
                                ausgangstext_hinweise = data.get(f"Hinweise_{quellsprache_hinweise}", "")
                                if ausgangstext_hinweise:
                                    übersetzter_hinweise = translator.translate_text(ausgangstext_hinweise, target_lang="EN-US")
                                    texte_für_voiceover.setdefault(sprache, {})["Hinweise"] = übersetzter_hinweise.text
                                    Texte[sprache]["Hinweise"] = übersetzter_hinweise.text
                                    print(f"Hinweise für {sprache}: {übersetzter_hinweise.text}")

                            # Generiere Tipps
                            if quellsprache_tipps:
                                ausgangstext_tipps = data.get(f"Tipps_{quellsprache_tipps}", "")
                                if ausgangstext_tipps:
                                    übersetzter_tipps = translator.translate_text(ausgangstext_tipps, target_lang="EN-US")
                                    texte_für_voiceover[sprache]["Tipps"] = übersetzter_tipps.text
                                    Texte[sprache]["Tipps"] = übersetzter_tipps.text
                                    print(f"Tipps für {sprache}: {übersetzter_tipps.text}")

                            # Generiere Namen
                            if quellsprache_name:
                                ausgangstext_name = data.get(f"Name_{quellsprache_name}", "")
                                if ausgangstext_name:
                                    übersetzter_name = translator.translate_text(ausgangstext_name, target_lang="EN-US")
                                    texte_für_voiceover[sprache]["Name"] = übersetzter_name.text
                                    Texte[sprache]["Name"] = übersetzter_name.text
                                    print(f"Name für {sprache}: {übersetzter_name.text}")

                        except Exception as e:
                            print(f"Fehler bei der Übersetzung für {sprache}: {str(e)}")
                    else:
                        try:
                            translator = deepl.Translator(g.whitelabel_info['API_TOKEN_Deepl'])

                            # Generiere Hinweise
                            if quellsprache_hinweise:
                                ausgangstext_hinweise = data.get(f"Hinweise_{quellsprache_hinweise}", "")
                                if ausgangstext_hinweise:
                                    übersetzter_hinweise = translator.translate_text(ausgangstext_hinweise, target_lang=sprache)
                                    texte_für_voiceover.setdefault(sprache, {})["Hinweise"] = übersetzter_hinweise.text
                                    Texte[sprache]["Hinweise"] = übersetzter_hinweise.text
                                    print(f"Hinweise für {sprache}: {übersetzter_hinweise.text}")

                            # Generiere Tipps
                            if quellsprache_tipps:
                                ausgangstext_tipps = data.get(f"Tipps_{quellsprache_tipps}", "")
                                if ausgangstext_tipps:
                                    übersetzter_tipps = translator.translate_text(ausgangstext_tipps, target_lang=sprache)
                                    texte_für_voiceover[sprache]["Tipps"] = übersetzter_tipps.text
                                    Texte[sprache]["Tipps"] = übersetzter_tipps.text
                                    print(f"Tipps für {sprache}: {übersetzter_tipps.text}")

                            # Generiere Namen
                            if quellsprache_name:
                                ausgangstext_name = data.get(f"Name_{quellsprache_name}", "")
                                if ausgangstext_name:
                                    übersetzter_name = translator.translate_text(ausgangstext_name, target_lang=sprache)
                                    texte_für_voiceover[sprache]["Name"] = übersetzter_name.text
                                    Texte[sprache]["Name"] = übersetzter_name.text
                                    print(f"Name für {sprache}: {übersetzter_name.text}")

                        except Exception as e:
                            print(f"Fehler bei der Übersetzung für {sprache}: {str(e)}")





            if data.get("Generiere_Voiceover") == "Alles":
                # Initialisiere die Liste für die Sprachen ohne Voiceover
                texte_für_voiceover = {}

                # Durchlaufe alle Sprachen
                for lang in languages:
                    # Überprüfe, ob es sowohl "Hinweise" als auch "Tipps" gibt und ob kein Voiceover hochgeladen wurde
                    if (data.get(f"Hinweise_{lang}") or data.get(f"Tipps_{lang}")) and not files.get(f"Voiceover_{lang}"):
                        zusammengesetzter_text = f"{data.get(f'Hinweise_{lang}')}\n{data.get(f'Tipps_{lang}')}"
                        texte_für_voiceover[lang] = zusammengesetzter_text

                # Jetzt enthält `texte_ohne_voiceover` die Sprachen und ihre entsprechenden Texte
                print(f"TEXTE FÜR VOICEOVER: {texte_für_voiceover}")

                for sprache, text in texte_für_voiceover.items():
                    ergebnis = await process_voiceover(text, sprache)
                    
                    print("Sprache: " + sprache)
                    print(ergebnis)
                    Texte[sprache]["Voiceover_ID"] = ergebnis

                    client.delete_file(AktuelleÜbung_Details['Texte'][lang]['Voiceover_ID']) # ALTES VOICEOVER LÖSCHEN
                
            elif data.get("Generiere_Voiceover") == "Änderungen":
                # Initialisiere die Liste für die Sprachen ohne Voiceover
                texte_ohne_voiceover = {}

                # Durchlaufe alle Sprachen
                for lang in languages:
                    # Überprüfe, ob es sowohl "Hinweise" als auch "Tipps" gibt und ob kein Voiceover hochgeladen wurde
                    if (data.get(f"Hinweise_{lang}") and data.get(f"Tipps_{lang}") 
                        and not files.get(f"Voiceover_{lang}") 
                        and (data.get(f"Hinweise_{lang}") != AktuelleÜbung_Details['Texte'][lang]['Hinweise'] 
                            or data.get(f"Tipps_{lang}") != AktuelleÜbung_Details['Texte'][lang]['Tipps'])):

                        # Erstelle den zusammengefügten Text
                        zusammengesetzter_text = f"{data.get(f'Hinweise_{lang}')}\n{data.get(f'Tipps_{lang}')}"
                        texte_ohne_voiceover[lang] = zusammengesetzter_text

                # Jetzt enthält `texte_ohne_voiceover` die Sprachen und ihre entsprechenden Texte
                print(f"TEXTE OHNE VOICEOVER: {texte_ohne_voiceover}")

                for sprache, text in texte_ohne_voiceover.items():
                    ergebnis = await process_voiceover(text, sprache)
                    
                    print("Sprache: " + sprache)
                    print(ergebnis)
                    Texte[sprache]["Voiceover_ID"] = ergebnis

                    client.delete_file(AktuelleÜbung_Details['Texte'][lang]['Voiceover_ID']) # ALTES VOICEOVER LÖSCHEN
            # Voiceover generieren, falls "Bestimmte" ausgewählt wurde
            elif data.get("Generiere_Voiceover") == "Bestimmte" and selected_voiceover_languages:
                for lang in selected_voiceover_languages:
                    zusammengesetzter_text = f"{Texte[lang].get('Hinweise', '')}\n{Texte[lang].get('Tipps', '')}"
                    if zusammengesetzter_text.strip():
                        voiceover_id = await process_voiceover(zusammengesetzter_text, lang)
                        Texte[lang]["Voiceover_ID"] = voiceover_id
            else:
                pass


            # Erstellen des Upload-Datensatzes
            upload_data = {
                "Typ": Übung_Details['Typ'],
                "Texte": Texte,
                "Suchbegriffe": Übung_Details['Suchbegriffe'],
                "Muskelgruppen": Übung_Details['Muskelgruppen'],
                "Gesundheitsproblem": Übung_Details['Gesundheitsproblem'],
                "Animation": file_ID_Animation
            }
            client.update_item("Uebungen", Übung_ID, upload_data)
        
            session['success'] = f"Die Übung wurde erfolgreich aktualisiert."
            return redirect(f"https://dashboard.{g.customer_domain}/admin/trainingshalle/übungen")
        else:
            request.body_timeout = None

            # Formulardaten und Dateien abrufen
            data = await request.form
            files = await request.files
            whitelabel_id = session.get('WhiteLabel_Admin')['id']

            Übung_Details = {
                "Typ": data.get('Typ'),
                "Name": data.get('Name'),
                "Hinweise": data.get('Hinweise'),
                "Tipps": data.get('Tipps'),
                "Muskelgruppen": data.getlist('Muskelgruppen'),
                "Suchbegriffe": data.getlist('suchbegriffe[]')
            }

            if data.get('Typ') == "Gesundheit":
                Übung_Details['Gesundheitsproblem'] = data.get('Gesundheitsproblem')
            else:
                Übung_Details['Gesundheitsproblem'] = None

            # Hilfsfunktion zum temporären Speichern der Datei
            async def save_temp_file(file_storage):
                temp_file = tempfile.NamedTemporaryFile(delete=False)
                try:
                    temp_file.write(file_storage.read())
                    temp_file.close()
                    return temp_file.name
                except Exception as e:
                    temp_file.close()
                    os.remove(temp_file.name)
                    raise e

            async def upload_video(file_storage):
                print("##################################")
                print("## VIDEO UPLOAD WURDE GESTARTET ##")
                print("##################################")
                temp_file_path = await save_temp_file(file_storage)
                upload_data = {
                    "title": file_storage.filename,
                    "description": f"Video-Animation für Übung '{Übung_Details['Name']}'",
                    "tags": ["Video-Animation", "Übung", f"{Übung_Details['Name']}"],
                    "type": file_storage.content_type
                }
                uploaded_file = client.upload_file(temp_file_path, upload_data)
                os.remove(temp_file_path)
                print("################################")
                print("## VIDEO UPLOAD WURDE BEENDET ##")
                print("################################")
                return uploaded_file['id']

            async def upload_voiceover(file_storage):
                print("######################################")
                print("## VOICEOVER UPLOAD WURDE GESTARTET ##")
                print("######################################")
                temp_file_path = await save_temp_file(file_storage)
                upload_data = {
                    "title": file_storage.filename,
                    "description": f"Voiceover für Übung '{Übung_Details['Name']}'",
                    "tags": ["Voiceover", "Übung", f"{Übung_Details['Name']}"],
                    "type": file_storage.content_type
                }
                uploaded_file = client.upload_file(temp_file_path, upload_data)
                os.remove(temp_file_path)
                print("####################################")
                print("## VOICEOVER UPLOAD WURDE BEENDET ##")
                print("####################################")
                return uploaded_file['id']

            
            # Ergebnis-Dictionary, um die Daten zu speichern
            Texte = {}
            
            if 'Video_Animation' not in files:
                session['error'] = "Du hast entweder die Animation oder das Voiceover vergessen hochzuladen."
                return redirect(f"https://dashboard.{g.customer_domain}/admin/trainingshalle/übungen")

            video_upload = upload_video(files['Video_Animation'])
            try:
                file_ID_Animation = await video_upload
            except Exception as e:
                app.logger.error(f"Fehler beim Upload der Video-Animation: {e}")


            # Verfügbare Sprachen
            languages = ["DE", "EN", "ES", "AR", "GR", "RU"]

            

            # Hole die Liste aus dem Request-Daten
            selected_text_languages = data.getlist("languagesSelect_Text[]")
            selected_voiceover_languages = data.getlist("languagesSelect_Voiceover[]")



            for lang in languages:
                # Textdaten
                Texte[lang] = {
                    "Name": data.get(f"Name_{lang}"),
                    "Hinweise": data.get(f"Hinweise_{lang}"),
                    "Tipps": data.get(f"Tipps_{lang}")
                }

            # Texte übersetzen, falls "Bestimmte" ausgewählt wurde
            if data.get("Generiere_Texte") == "Bestimmte" and selected_text_languages:
                for lang in selected_text_languages:
                    if lang not in Texte:
                        Texte[lang] = {}

                    translator = deepl.Translator(g.whitelabel_info['API_TOKEN_Deepl'])
                    
                    # Variable, um festzustellen, ob mindestens ein Textabschnitt vorhanden ist
                    hat_text = False

                    # Dynamisch Quellsprache bestimmen
                    def finde_quellsprache(field):
                        for lang in languages:
                            if data.get(f"{field}_{lang}"):
                                return lang
                    
                    quellsprache_hinweise = finde_quellsprache("Hinweise")
                    quellsprache_tipps = finde_quellsprache("Tipps")
                    quellsprache_name = finde_quellsprache("Name")


                    if quellsprache_name:
                        ausgangstext_name = data.get(f"Name_{quellsprache_name}", "")
                        
                        if lang == "GR":
                            Texte[lang]["Name"] = translator.translate_text(ausgangstext_name, target_lang="EL").text
                        elif lang == "EN":
                            Texte[lang]["Name"] = translator.translate_text(ausgangstext_name, target_lang="EN-US").text
                        else:
                            Texte[lang]["Name"] = translator.translate_text(ausgangstext_name, target_lang=lang).text
                    if quellsprache_hinweise:
                        ausgangstext_hinweise = data.get(f"Hinweise_{quellsprache_hinweise}", "")
                        
                        if lang == "GR":
                            Texte[lang]["Hinweise"] = translator.translate_text(ausgangstext_hinweise, target_lang="EL").text
                        elif lang == "EN":
                            Texte[lang]["Hinweise"] = translator.translate_text(ausgangstext_hinweise, target_lang="EN-US").text
                        else:
                            Texte[lang]["Hinweise"] = translator.translate_text(ausgangstext_hinweise, target_lang=lang).text
                    if quellsprache_tipps:
                        ausgangstext_tipps = data.get(f"Tipps_{quellsprache_tipps}", "")
                        
                        if lang == "GR":
                            Texte[lang]["Tipps"] = translator.translate_text(ausgangstext_tipps, target_lang="EL").text
                        elif lang == "EN":
                            Texte[lang]["Tipps"] = translator.translate_text(ausgangstext_tipps, target_lang="EN-US").text
                        else:
                            Texte[lang]["Tipps"] = translator.translate_text(ausgangstext_tipps, target_lang=lang).text


            if data.get("Generiere_Texte") == "Alles":
                # Initialisiere die Liste für die Sprachen ohne Voiceover
                texte_für_voiceover = {}
                languages = ["DE", "EN", "ES", "AR", "GR", "RU"]

                # Variable, um festzustellen, ob mindestens ein Textabschnitt vorhanden ist
                hat_text = False

                # Dynamisch Quellsprache bestimmen
                def finde_quellsprache(field):
                    for lang in languages:
                        if data.get(f"{field}_{lang}"):
                            return lang
                    return None

                quellsprache_hinweise = finde_quellsprache("Hinweise")
                quellsprache_tipps = finde_quellsprache("Tipps")
                quellsprache_name = finde_quellsprache("Name")

                if not (quellsprache_hinweise or quellsprache_tipps or quellsprache_name):
                    print("Keine Quelltexte gefunden. Abbruch.")
                    return

                # Durchlaufe alle Sprachen
                for lang in languages:
                    hinweise_text = data.get(f"Hinweise_{lang}")
                    tipps_text = data.get(f"Tipps_{lang}")
                    name_text = data.get(f"Name_{lang}")

                    if (hinweise_text and tipps_text and name_text) and not files.get(f"Voiceover_{lang}"):
                        texte_für_voiceover[lang] = {
                            "Hinweise": hinweise_text or "",
                            "Tipps": tipps_text or "",
                            "Name": name_text or ""
                        }
                        hat_text = True

                # Falls kein Text gefunden wurde, abbrechen
                if not hat_text:
                    print("Keine Texte zum Generieren gefunden.")
                    return

                print(f"TEXTE FÜR VOICEOVER: {texte_für_voiceover}")

                # Sprachen generieren mit Deepl Pro API
                fehlende_sprachen = [lang for lang in languages if lang not in texte_für_voiceover]
                for sprache in fehlende_sprachen:
                    if sprache == "GR":
                        try:
                            translator = deepl.Translator(g.whitelabel_info['API_TOKEN_Deepl'])

                            # Generiere Hinweise
                            if quellsprache_hinweise:
                                ausgangstext_hinweise = data.get(f"Hinweise_{quellsprache_hinweise}", "")
                                if ausgangstext_hinweise:
                                    übersetzter_hinweise = translator.translate_text(ausgangstext_hinweise, target_lang="EL")
                                    texte_für_voiceover.setdefault(sprache, {})["Hinweise"] = übersetzter_hinweise.text
                                    Texte[sprache]["Hinweise"] = übersetzter_hinweise.text
                                    print(f"Hinweise für {sprache}: {übersetzter_hinweise.text}")

                            # Generiere Tipps
                            if quellsprache_tipps:
                                ausgangstext_tipps = data.get(f"Tipps_{quellsprache_tipps}", "")
                                if ausgangstext_tipps:
                                    übersetzter_tipps = translator.translate_text(ausgangstext_tipps, target_lang="EL")
                                    texte_für_voiceover[sprache]["Tipps"] = übersetzter_tipps.text
                                    Texte[sprache]["Tipps"] = übersetzter_tipps.text
                                    print(f"Tipps für {sprache}: {übersetzter_tipps.text}")

                            # Generiere Namen
                            if quellsprache_name:
                                ausgangstext_name = data.get(f"Name_{quellsprache_name}", "")
                                if ausgangstext_name:
                                    übersetzter_name = translator.translate_text(ausgangstext_name, target_lang="EL")
                                    texte_für_voiceover[sprache]["Name"] = übersetzter_name.text
                                    Texte[sprache]["Name"] = übersetzter_name.text
                                    print(f"Name für {sprache}: {übersetzter_name.text}")

                        except Exception as e:
                            print(f"Fehler bei der Übersetzung für {sprache}: {str(e)}")
                    elif sprache == "EN":
                        try:
                            translator = deepl.Translator(g.whitelabel_info['API_TOKEN_Deepl'])

                            # Generiere Hinweise
                            if quellsprache_hinweise:
                                ausgangstext_hinweise = data.get(f"Hinweise_{quellsprache_hinweise}", "")
                                if ausgangstext_hinweise:
                                    übersetzter_hinweise = translator.translate_text(ausgangstext_hinweise, target_lang="EN-US")
                                    texte_für_voiceover.setdefault(sprache, {})["Hinweise"] = übersetzter_hinweise.text
                                    Texte[sprache]["Hinweise"] = übersetzter_hinweise.text
                                    print(f"Hinweise für {sprache}: {übersetzter_hinweise.text}")

                            # Generiere Tipps
                            if quellsprache_tipps:
                                ausgangstext_tipps = data.get(f"Tipps_{quellsprache_tipps}", "")
                                if ausgangstext_tipps:
                                    übersetzter_tipps = translator.translate_text(ausgangstext_tipps, target_lang="EN-US")
                                    texte_für_voiceover[sprache]["Tipps"] = übersetzter_tipps.text
                                    Texte[sprache]["Tipps"] = übersetzter_tipps.text
                                    print(f"Tipps für {sprache}: {übersetzter_tipps.text}")

                            # Generiere Namen
                            if quellsprache_name:
                                ausgangstext_name = data.get(f"Name_{quellsprache_name}", "")
                                if ausgangstext_name:
                                    übersetzter_name = translator.translate_text(ausgangstext_name, target_lang="EN-US")
                                    texte_für_voiceover[sprache]["Name"] = übersetzter_name.text
                                    Texte[sprache]["Name"] = übersetzter_name.text
                                    print(f"Name für {sprache}: {übersetzter_name.text}")

                        except Exception as e:
                            print(f"Fehler bei der Übersetzung für {sprache}: {str(e)}")
                    else:
                        try:
                            translator = deepl.Translator(g.whitelabel_info['API_TOKEN_Deepl'])

                            # Generiere Hinweise
                            if quellsprache_hinweise:
                                ausgangstext_hinweise = data.get(f"Hinweise_{quellsprache_hinweise}", "")
                                if ausgangstext_hinweise:
                                    übersetzter_hinweise = translator.translate_text(ausgangstext_hinweise, target_lang=sprache)
                                    texte_für_voiceover.setdefault(sprache, {})["Hinweise"] = übersetzter_hinweise.text
                                    Texte[sprache]["Hinweise"] = übersetzter_hinweise.text
                                    print(f"Hinweise für {sprache}: {übersetzter_hinweise.text}")

                            # Generiere Tipps
                            if quellsprache_tipps:
                                ausgangstext_tipps = data.get(f"Tipps_{quellsprache_tipps}", "")
                                if ausgangstext_tipps:
                                    übersetzter_tipps = translator.translate_text(ausgangstext_tipps, target_lang=sprache)
                                    texte_für_voiceover[sprache]["Tipps"] = übersetzter_tipps.text
                                    Texte[sprache]["Tipps"] = übersetzter_tipps.text
                                    print(f"Tipps für {sprache}: {übersetzter_tipps.text}")

                            # Generiere Namen
                            if quellsprache_name:
                                ausgangstext_name = data.get(f"Name_{quellsprache_name}", "")
                                if ausgangstext_name:
                                    übersetzter_name = translator.translate_text(ausgangstext_name, target_lang=sprache)
                                    texte_für_voiceover[sprache]["Name"] = übersetzter_name.text
                                    Texte[sprache]["Name"] = übersetzter_name.text
                                    print(f"Name für {sprache}: {übersetzter_name.text}")

                        except Exception as e:
                            print(f"Fehler bei der Übersetzung für {sprache}: {str(e)}")

            
            if data.get('Generiere_Voiceover') == "Alles":
                # Initialisiere die Liste für die Sprachen ohne Voiceover
                texte_für_voiceover = {}

                # Durchlaufe alle Sprachen
                for lang in languages:
                    # Überprüfe, ob es sowohl "Hinweise" als auch "Tipps" gibt und ob kein Voiceover hochgeladen wurde
                    if (
                        Texte.get(lang, {}).get("Hinweise") 
                        and Texte.get(lang, {}).get("Tipps") 
                        and not files.get(f"Voiceover_{lang}")
                    ):
                        if not texte_für_voiceover.get(lang):
                            zusammengesetzter_text = f"{Texte[lang]['Hinweise']}\n{Texte[lang]['Tipps']}"
                            texte_für_voiceover[lang] = zusammengesetzter_text


                # Jetzt enthält `texte_ohne_voiceover` die Sprachen und ihre entsprechenden Texte
                print(f"TEXTE FÜR VOICEOVER: {texte_für_voiceover}")

                for sprache, text in texte_für_voiceover.items():
                    ergebnis = await process_voiceover(text, sprache)
                    
                    print("Sprache: " + sprache)
                    print(ergebnis)
                    Texte[sprache]["Voiceover_ID"] = ergebnis
            
            # Voiceover generieren, falls "Bestimmte" ausgewählt wurde
            elif data.get("Generiere_Voiceover") == "Bestimmte" and selected_voiceover_languages:
                for lang in selected_voiceover_languages:
                    zusammengesetzter_text = f"{Texte[lang].get('Hinweise', '')}\n{Texte[lang].get('Tipps', '')}"
                    if zusammengesetzter_text.strip():
                        voiceover_id = await process_voiceover(zusammengesetzter_text, lang)
                        Texte[lang]["Voiceover_ID"] = voiceover_id
            else:
                # Voiceover-Datei hochladen
                voiceover_file = files.get(f"Voiceover_{lang}")
                if voiceover_file:
                    voiceover_upload = upload_voiceover(voiceover_file)
                    try:
                        file_ID_Voiceover = await voiceover_upload
                        Texte[lang]["Voiceover_ID"] = file_ID_Voiceover
                    except Exception as e:
                        app.logger.error(f"Fehler beim Upload des Voiceovers ({lang}): {e}")
                        Texte[lang]["Voiceover_ID"] = None
                else:
                    Texte[lang]["Voiceover_ID"] = None


            # Erstellen des Upload-Datensatzes
            upload_data = {
                "Typ": Übung_Details['Typ'],
                "Texte": Texte,
                "Suchbegriffe": Übung_Details['Suchbegriffe'],
                "Muskelgruppen": Übung_Details['Muskelgruppen'],
                "Gesundheitsproblem": Übung_Details['Gesundheitsproblem'],
                "Animation": file_ID_Animation,
                "WhiteLabel": {'key': int(whitelabel_id), 'collection': 'WhiteLabel'},
                "Ersteller": {'key': int(session.get('id')), 'collection': 'Nutzer'}
            }
            
            client.create_item("Uebungen", item_data=upload_data)

            session['success'] = f"Die Übung wurde erfolgreich erstellt."
            return redirect(f"https://dashboard.{g.customer_domain}/admin/trainingshalle/übungen")


@app.route('/admin/trainingshalle/Upload-Analyse', methods=['GET', 'POST'])
async def ADMIN_Trainingshalle_UploadAnalyse():
    if request.method == "GET":
        success = session.pop('success', None)
        punkte = session.pop('Punkte_Nachricht', None)
        punkte_nachricht = punkte
        error = session.pop('error', None)

        header = await render_template('/parts/Elemente/header.html', url= request.url, 
                                                    WhiteLabel=g.whitelabel_info, 
                                                    avatar_url=session.get('avatar'), 
                                                    rolle=session.get('rolle'), 
                                                    name=session.get('name'), Nutzer_Punkte=session.get('Nutzer_Punkte'))
        sidebar = await render_template('/parts/Elemente/sidebar.html', 
                                        WhiteLabel=g.whitelabel_info, rolle=session.get('rolle'))
        footer = await render_template('/parts/Elemente/footer.html', WhiteLabel = g.whitelabel_info, Session_Info=g.Session_Info['LogEntry_ID'], nutzername=session.get('username'), nutzer_ID=session.get('id'))

        theme_customizer = await render_template('/parts/Elemente/theme-customizer.html', 
                                                WhiteLabel=g.whitelabel_info)
        
        # Die Items von der Collection "Nutzer" abrufen
        try:
            data = client.get_items("Nutzer")

            print(data)
            if 'error' in data:
                nutzer_details = []
                print(f"Fehler: {data['error']}")
            else:
                if data:  # Überprüfen, ob Daten vorhanden sind
                    nutzer_details = data  # Speichere die Whitelabel-Informationen in g
                    print(f"Nutzer-Details: {nutzer_details}")
                else:
                    nutzer_details = []
                    print(f"Fehler beim Abruf der Nutzer.")
        except Exception as e:
            print(f"Fehler beim Abrufen der Daten: {e}")

        nutzer_ids = [nutzer['id'] for nutzer in data if nutzer['Referrer'] == session.get('id')] # Nutzer, für welche der Admin zuständig ist bzw. welche dieser angelegt hat
        nutzer_liste = [nutzer for nutzer in data if nutzer['Referrer'] == session.get('id')] # Nutzer, für welche der Admin zuständig ist bzw. welche dieser angelegt hat


        Anfragen = client.get_items("Upload_UND_Analyse")

        for anfrage in Anfragen:
            Kunden_Details = client.get_item("Nutzer", anfrage['Kunde']['key'])
            anfrage['Kunden_Details'] = Kunden_Details


        # Rendern der Vorschau-HTML-Vorlage mit den erhaltenen Parametern
        return await render_template(f'/parts/Seiten/Admin-Bereich/Trainingshalle/UploadUndAnalyse.html', 
                                    header=header,
                                    error=error, 
                                    success=success, 
                                    sidebar=sidebar, 
                                    footer=footer, 
                                    theme_customizer=theme_customizer,
                                    username=session.get('username'), 
                                    rolle=session.get('rolle'), 
                                    name=session.get('name'), 
                                    avatar_url=session.get('avatar'), 
                                    WhiteLabel=g.whitelabel_info,
                                    Anfragen = Anfragen,
                                    Nutzer_Liste = nutzer_liste)
    else:
        form = await request.form
        files = await request.files
        Art = request.args.get('Art')
        Typ = request.args.get('Typ')



        Video_Upload = files.get("Video")
        
        

        if Video_Upload:
            # Temporären Pfad erstellen
            tmp_dir = tempfile.gettempdir()
            tmp_path = os.path.join(tmp_dir, Video_Upload.filename)

            
            filename = Video_Upload.filename
            content_type = Video_Upload.content_type

            # Die Datei speichern
            await Video_Upload.save(tmp_path)

            # Überprüfen, ob die Datei gespeichert wurde
            if os.path.exists(tmp_path):
                print(f"Video gespeichert unter {tmp_path}")

                upload_data = {
                    "title": filename,
                    "description": f"Video für Analyse-Antwort",
                    "tags": ["Analyse-Antwort", "Video", "Antwort"],
                    "type": content_type
                }
                VideoUpload_ID = client.upload_file(tmp_path, upload_data)


                item_data = {
                    "WhiteLabel": {"key": g.whitelabel_info['id'], "collection" : "WhiteLabel"},
                    "Typ": "Trainer",
                    "Trainer": {"key": session.get('id'), "collection" : "Nutzer"},
                    "Video": VideoUpload_ID,
                    "Nachricht": form.get("Nachricht")
                }

                if form.get('Anfrage') != "Keine":
                    Anfrage = {"key": form.get('Anfrage'), "collection" : "Upload_UND_Analyse"}
                    Anfrage_Details = client.get_item("Upload_UND_Analyse", form.get('Anfrage'))
                    Kunden_Details = client.get_item("Nutzer", Anfrage_Details['Kunde']['key'])
                    item_data['Antwort_Auf'] = Anfrage
                    item_data['Kunde'] = {"key": int(Kunden_Details['id']), "collection" : "Nutzer"}

                    client.update_item("Upload_UND_Analyse", form.get('Anfrage'), {"Status": "Abgeschlossen"})
                else:
                    Anfrage = {}

                if form.get('Nutzer') != "Keine":
                    Kunde = {"key": int(form.get('Nutzer')), "collection" : "Nutzer"}
                    item_data['Kunde'] = Kunde
                else:
                    Kunde = {}

                client.create_item("Upload_UND_Analyse", item_data)

                # Sobald die Datei nicht mehr gebraucht wird, löschen
                os.remove(tmp_path)
                print(f"Video gelöscht von {tmp_path}")

            session['success'] = "Deine Analyse-Antwort wurde erfolgreich an Deinen Kunden geschickt."
            return redirect(f"https://dashboard.{g.whitelabel_info['Domain']}/admin/trainingshalle/Upload-Analyse")
        else:
            session['error'] = "Du hast kein Video hochgeladen."
            return redirect(f"https://dashboard.{g.whitelabel_info['Domain']}/admin/trainingshalle/Upload-Analyse")


@app.route('/admin/trainingshalle/pläne', methods=['GET', 'POST'])
async def ADMIN_Trainingshalle_Pläne():
    if request.method == "GET":
        success = session.pop('success', None)
        punkte = session.pop('Punkte_Nachricht', None)
        punkte_nachricht = punkte
        error = session.pop('error', None)

        header = await render_template('/parts/Elemente/header.html', url= request.url, 
                                                    WhiteLabel=g.whitelabel_info, 
                                                    avatar_url=session.get('avatar'), 
                                                    rolle=session.get('rolle'), 
                                                    name=session.get('name'), Nutzer_Punkte=session.get('Nutzer_Punkte'))
        sidebar = await render_template('/parts/Elemente/sidebar.html', 
                                        WhiteLabel=g.whitelabel_info, rolle=session.get('rolle'))
        footer = await render_template('/parts/Elemente/footer.html', WhiteLabel = g.whitelabel_info, Session_Info=g.Session_Info['LogEntry_ID'], nutzername=session.get('username'), nutzer_ID=session.get('id'))

        theme_customizer = await render_template('/parts/Elemente/theme-customizer.html', 
                                                WhiteLabel=g.whitelabel_info)
        
        # Die Items von der Collection "Nutzer" abrufen
        try:
            data = client.get_items("Nutzer")

            print(data)
            if 'error' in data:
                nutzer_details = []
                print(f"Fehler: {data['error']}")
            else:
                if data:  # Überprüfen, ob Daten vorhanden sind
                    nutzer_details = data  # Speichere die Whitelabel-Informationen in g
                    print(f"Nutzer-Details: {nutzer_details}")
                else:
                    nutzer_details = []
                    print(f"Fehler beim Abruf der Nutzer.")
        except Exception as e:
            print(f"Fehler beim Abrufen der Daten: {e}")

        nutzer_ids = [nutzer['id'] for nutzer in data if nutzer['Referrer'] == session.get('id')] # Nutzer, für welche der Admin zuständig ist bzw. welche dieser angelegt hat
        nutzer_liste = [nutzer for nutzer in data if nutzer['Referrer'] == session.get('id')] # Nutzer, für welche der Admin zuständig ist bzw. welche dieser angelegt hat

        
        try:
            data = client.get_items("Uebungen")

            print(data)
            if 'error' in data:
                Übungen = []
                print(f"Fehler: {data['error']}")
            else:
                if data:  # Überprüfen, ob Daten vorhanden sind
                    Übungen = data  # Speichere die Whitelabel-Informationen in g
                    print(f"Übungen: {Übungen}")
                else:
                    Übungen = []
                    print(f"Fehler beim Abruf der Nutzer.")
        except Exception as e:
            print(f"Fehler beim Abrufen der Daten: {e}")

        try:
            data = client.get_items("Trainingsplan")

            print(data)
            if 'error' in data:
                Trainingspläne = []
                print(f"Fehler: {data['error']}")
            else:
                if data:  # Überprüfen, ob Daten vorhanden sind
                    Trainingspläne = data  # Speichere die Whitelabel-Informationen in g
                    print(f"Trainingspläne: {Trainingspläne}")
                else:
                    Trainingspläne = []
                    print(f"Fehler beim Abruf der Nutzer.")
        except Exception as e:
            print(f"Fehler beim Abrufen der Daten: {e}")
        
        for plan in Trainingspläne:
            if plan['Art'] != "Vorgefertigt":
                kunden_details = client.get_item("Nutzer", plan['Nutzer']['key'])
                plan['Nutzer_Details'] = kunden_details
            else:
                kunden_details = {}

            
            ersteller_details = client.get_item("Nutzer", plan['Nutzer_Ersteller']['key'])
            plan['Ersteller_Details'] = ersteller_details   

            for woche, uebungen in plan['Daten'].items():
                for uebung in uebungen:
                    uebung['Details'] = client.get_item("Uebungen", uebung['Übung_ID'])
            
        try:
            data = client.get_items("Trainingsplan_Anfragen")

            print(data)
            if 'error' in data:
                Trainingsplan_Anfragen = []
                print(f"Fehler: {data['error']}")
            else:
                if data:  # Überprüfen, ob Daten vorhanden sind
                    Trainingsplan_Anfragen = data  # Speichere die Whitelabel-Informationen in g
                    print(f"Trainingsplan_Anfragen: {Trainingsplan_Anfragen}")
                else:
                    Trainingsplan_Anfragen = []
                    print(f"Fehler beim Abruf der Nutzer.")
        except Exception as e:
            print(f"Fehler beim Abrufen der Daten: {e}")

        for Anfrage in Trainingsplan_Anfragen:
            print(Anfrage)

            kunden_details = client.get_item("Nutzer", Anfrage['Kunde']['key'])
            fitnesstest_details = client.get_item("FitnessTest_ERGEBNISSE", Anfrage['FitnessTest_Ergebnisse']['key'])
            if Anfrage['Status'] != "Abgeschlossen":
                trainingsplan_details = {}
            else:
                trainingsplan_details = client.get_item("Trainingsplan", Anfrage['Trainingsplan']['key'])

            Anfrage['Kunden_Details'] = kunden_details
            Anfrage['Fitness-Test_Details'] = fitnesstest_details
            Anfrage['Trainingsplan_Details'] = trainingsplan_details
            
            if Anfrage['Status'] == "Abgeschlossen":
                for key, übungen in Anfrage['Trainingsplan_Details']['Daten'].items():
                    print("Key:", key)
                    for übung in übungen:
                        for Übung_Details in Übungen:
                            if Übung_Details['id'] == übung['Übung_ID']:
                                übung['Übung_Details'] = Übung_Details

        print(Trainingsplan_Anfragen)


        # Rendern der Vorschau-HTML-Vorlage mit den erhaltenen Parametern
        return await render_template(f'/parts/Seiten/Admin-Bereich/Trainingshalle/Trainingsplan.html', 
                                    header=header,
                                    error=error, 
                                    success=success, 
                                    sidebar=sidebar, 
                                    footer=footer, 
                                    theme_customizer=theme_customizer,
                                    username=session.get('username'), 
                                    rolle=session.get('rolle'), 
                                    name=session.get('name'), 
                                    avatar_url=session.get('avatar'), 
                                    WhiteLabel=g.whitelabel_info,
                                    Trainingspläne = Trainingspläne,
                                    Trainingsplan_Anfragen = Trainingsplan_Anfragen,
                                    Übungen = Übungen,
                                    Nutzer_Liste = nutzer_liste)
    
    else:
        data = await request.form

        Art = request.args.get('art')

        # Basisdaten
        name = data.get("Name")
        kunde = data.get("Kunde")
        anfrage = data.get("Anfrage")

        if Art == "übung":
            # Wochen-Daten initialisieren
            weeks = data.get("weeks")
            wochen_daten = {}

            # Übungen nach Wochen gruppieren
            for key, value in data.items():
                if "_sets_week" in key or "_repetitions_week" in key or "_restTime_week" in key or "_notes_week" in key or "_name_week" in key:
                    # Zerlege den Schlüssel
                    parts = key.split("_")
                    exercise_id = parts[0]  # ID der Übung
                    field_type = parts[1]  # Typ des Feldes: sets, repetitions, etc.
                    week_number = f"Woche_{parts[2].replace('week', '')}"  # Woche extrahieren

                    # Stelle sicher, dass die Woche existiert
                    if week_number not in wochen_daten:
                        wochen_daten[week_number] = []

                    # Finde oder erstelle die Übung
                    exercise = next((e for e in wochen_daten[week_number] if e["Übung_ID"] == exercise_id), None)
                    if not exercise:
                        exercise = {"Übung_ID": exercise_id, "Sätze": 0, "Wiederholungen": 0, "Pause": 0, "Notizen": "", "Name": ""}
                        wochen_daten[week_number].append(exercise)

                    # Werte zuordnen
                    if field_type == "sets":
                        exercise["Sätze"] = value
                    elif field_type == "repetitions":
                        exercise["Wiederholungen"] = value
                    elif field_type == "restTime":
                        exercise["Pause"] = value
                    elif field_type == "notes":
                        exercise["Notizen"] = value
                    elif field_type == "name":
                        exercise["Name"] = value


            # Antwort vorbereiten
            response = {
                "Name": name,
                "Kunde_ID": kunde,
                "Anfrage_ID": anfrage,
                "Wochen_Anzahl": weeks,
                "Wochen_Daten": wochen_daten,
            }

            item_data = {
                "Typ": "Übungen",
                "Name": response['Name'],
                "WhiteLabel": {'key': g.whitelabel_info['id'], 'collection': 'WhiteLabel'},
                "Nutzer_Ersteller": {'key': session.get('id'), 'collection': 'Nutzer'},
                "Art": "Individuell",
                "Daten": response['Wochen_Daten']
            }
            if data.get("Anfrage"):
                item_data['Anfrage'] = {'key': response['Anfrage_ID'], 'collection': 'Trainingsplan_Anfragen'}
                client.update_item("Trainingsplan_Anfragen", response['Anfrage_ID'], {
                    "Status": "Abgeschlossen"
                })
                Anfrage_Details = client.get_item("Trainingsplan_Anfragen", response['Anfrage_ID'])
                item_data['Nutzer'] = {'key': Anfrage_Details['Kunde']['key'], 'collection': 'Nutzer'}
            else:
                item_data['Nutzer'] = {'key': response['Kunde_ID'], 'collection': 'Nutzer'}

            Trainingsplan = client.create_item("Trainingsplan", item_data)
            if data.get("Anfrage"):
                client.update_item("Trainingsplan_Anfragen", response['Anfrage_ID'], {
                    "Trainingsplan": {'key': Trainingsplan['data']['id'], 'collection': 'Trainingsplan'}
                })

        elif Art == "vorlage_übung":
            # Wochen-Daten initialisieren
            weeks = data.get("weeks")
            wochen_daten = {}

            # Übungen nach Wochen gruppieren
            for key, value in data.items():
                if "_sets_week" in key or "_repetitions_week" in key or "_restTime_week" in key or "_notes_week" in key or "_name_week" in key:
                    # Zerlege den Schlüssel
                    parts = key.split("_")
                    exercise_id = parts[0]  # ID der Übung
                    field_type = parts[1]  # Typ des Feldes: sets, repetitions, etc.
                    week_number = f"Woche_{parts[2].replace('week', '')}"  # Woche extrahieren

                    # Stelle sicher, dass die Woche existiert
                    if week_number not in wochen_daten:
                        wochen_daten[week_number] = []

                    # Finde oder erstelle die Übung
                    exercise = next((e for e in wochen_daten[week_number] if e["Übung_ID"] == exercise_id), None)
                    if not exercise:
                        exercise = {"Übung_ID": exercise_id, "Sätze": 0, "Wiederholungen": 0, "Pause": 0, "Notizen": "", "Name": ""}
                        wochen_daten[week_number].append(exercise)

                    # Werte zuordnen
                    if field_type == "sets":
                        exercise["Sätze"] = value
                    elif field_type == "repetitions":
                        exercise["Wiederholungen"] = value
                    elif field_type == "restTime":
                        exercise["Pause"] = value
                    elif field_type == "notes":
                        exercise["Notizen"] = value
                    elif field_type == "name":
                        exercise["Name"] = value


            # Antwort vorbereiten
            response = {
                "Name": name,
                "Wochen_Anzahl": weeks,
                "Wochen_Daten": wochen_daten,
            }

            item_data = {
                "Typ": "Übungen",
                "Name": response['Name'],
                "WhiteLabel": {'key': g.whitelabel_info['id'], 'collection': 'WhiteLabel'},
                "Nutzer_Ersteller": {'key': session.get('id'), 'collection': 'Nutzer'},
                "Art": "Vorgefertigt",
                "Daten": response['Wochen_Daten']
            }

            Trainingsplan = client.create_item("Trainingsplan", item_data)

        elif Art == "datei":
            # Überprüfen, ob eine Datei hochgeladen wurde
            uploaded_files = await request.files
            print("Hochgeladene Dateien:", uploaded_files)

            uploaded_file = uploaded_files.get('Datei')
            if not uploaded_file:
                print("Keine Datei gefunden")
                return jsonify({"error": "Keine Datei hochgeladen"}), 400

            print(f"Gefundene Datei: {uploaded_file.filename}")
            

            # Validierung der Datei: Name und Format
            if not uploaded_file.filename.endswith(('.doc', '.docx', '.pdf')):
                return jsonify({"error": "Ungültiges Dateiformat"}), 400

            # Temporäre Datei erstellen und speichern
            with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(uploaded_file.filename)[1]) as temp_file:
                temp_path = temp_file.name
                await uploaded_file.save(temp_path)
                print(f"Datei wurde temporär gespeichert: {temp_path}")

            try:
                # JSON-Struktur vorbereiten
                response = {
                    "Name": name,
                    "Kunde_ID": kunde,
                    "Anfrage_ID": anfrage,
                    "Datei": {
                        "Name": uploaded_file.filename,
                        "Temp_Path": temp_path,
                        "Content-Typ": uploaded_file.content_type,
                    }
                }


                
                upload_data = {
                    "title": response['Datei']['Name'],
                    "description": f"Datei für Trainingsplan '{response['Name']}'",
                    "tags": ["Trainingsplan", "Datei", response['Name']],
                    "type": response['Datei']['Content-Typ']  # MIME-Typ hinzufügen
                }
                # Hier können Sie die Datei weiterverarbeiten, z. B. lesen oder hochladen.
                Datei_Upload = client.upload_file(response['Datei']['Temp_Path'], upload_data)

                item_data = {
                    "Typ": "Datei",
                    "Name": response['Name'],
                    "Nutzer_Ersteller": {'key': int(session.get("id")), 'collection': 'Nutzer'},
                    "WhiteLabel": {'key': g.whitelabel_info['id'], 'collection': 'WhiteLabel'},
                    "Art": "Individuell",
                    "Datei": Datei_Upload['id']
                }
                # Bedingung: Nutzer oder Anfrage setzen
                if 'Kunde_ID' in response and response['Kunde_ID']:
                    item_data["Nutzer"] = {'key': int(response['Kunde_ID']), 'collection': 'Nutzer'}
                elif 'Anfrage_ID' in response and response['Anfrage_ID']:
                    item_data["Nutzer"] = {'key': int(data.get('Anfrage_Kunde')), 'collection': 'Nutzer'}
                    item_data["Anfrage"] = {'key': response['Anfrage_ID'], 'collection': 'Trainingsplan_Anfragen'}
                # Trainingsplan anlegen
                Trainingsplan_Data = client.create_item("Trainingsplan", item_data)

            finally:
                # Temporäre Datei löschen
                if os.path.exists(temp_path):
                    os.remove(temp_path)
                    print(f"Temporäre Datei gelöscht: {temp_path}")

                if response.get('Anfrage'):
                    anfrage_id = response['Anfrage']
                elif response.get('Anfrage_ID'):
                    anfrage_id = response['Anfrage_ID']
                else:
                    anfrage_id = None

                print(Trainingsplan_Data)

                if anfrage_id:
                    client.update_item("Trainingsplan_Anfragen", anfrage_id, {
                        "Status": "Abgeschlossen",
                        "Trainingsplan": {'key': Trainingsplan_Data['data']['id'], 'collection': 'Trainingsplan'}
                    })

        elif Art == "vorlage_datei":
            # Überprüfen, ob eine Datei hochgeladen wurde
            uploaded_files = await request.files
            print("Hochgeladene Dateien:", uploaded_files)

            uploaded_file = uploaded_files.get('Datei')
            if not uploaded_file:
                print("Keine Datei gefunden")
                return jsonify({"error": "Keine Datei hochgeladen"}), 400

            print(f"Gefundene Datei: {uploaded_file.filename}")
            

            # Validierung der Datei: Name und Format
            if not uploaded_file.filename.endswith(('.doc', '.docx', '.pdf')):
                return jsonify({"error": "Ungültiges Dateiformat"}), 400

            # Temporäre Datei erstellen und speichern
            with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(uploaded_file.filename)[1]) as temp_file:
                temp_path = temp_file.name
                await uploaded_file.save(temp_path)
                print(f"Datei wurde temporär gespeichert: {temp_path}")

            try:
                # JSON-Struktur vorbereiten
                response = {
                    "Name": name,
                    "Kunde_ID": kunde,
                    "Anfrage_ID": anfrage,
                    "Datei": {
                        "Name": uploaded_file.filename,
                        "Temp_Path": temp_path,
                        "Content-Typ": uploaded_file.content_type,
                    }
                }


                
                upload_data = {
                    "title": response['Datei']['Name'],
                    "description": f"Datei für Trainingsplan '{response['Name']}'",
                    "tags": ["Trainingsplan", "Datei", response['Name']],
                    "type": response['Datei']['Content-Typ']  # MIME-Typ hinzufügen
                }
                # Hier können Sie die Datei weiterverarbeiten, z. B. lesen oder hochladen.
                Datei_Upload = client.upload_file(response['Datei']['Temp_Path'], upload_data)

                item_data = {
                    "Typ": "Datei",
                    "Name": response['Name'],
                    "Nutzer_Ersteller": {'key': int(session.get("id")), 'collection': 'Nutzer'},
                    "WhiteLabel": {'key': g.whitelabel_info['id'], 'collection': 'WhiteLabel'},
                    "Art": "Vorgefertigt",
                    "Datei": Datei_Upload['id']
                }
                # Trainingsplan anlegen
                Trainingsplan_Data = client.create_item("Trainingsplan", item_data)

            finally:
                # Temporäre Datei löschen
                if os.path.exists(temp_path):
                    os.remove(temp_path)
                    print(f"Temporäre Datei gelöscht: {temp_path}")

                print(Trainingsplan_Data)

        session['success'] = "Der Trainingsplan wurde erfolgreich erstellt und verschickt."
        return redirect(f"https://dashboard.{g.whitelabel_info['Domain']}/admin/trainingshalle/pläne")


@app.route('/admin/trainingshalle/fitness-tests', methods=['GET', 'POST'])
async def ADMIN_Trainingshalle_FitnessTests():
    if request.method == "GET":
        success = session.pop('success', None)
        punkte = session.pop('Punkte_Nachricht', None)
        punkte_nachricht = punkte
        error = session.pop('error', None)

        header = await render_template('/parts/Elemente/header.html', url= request.url, 
                                                    WhiteLabel=g.whitelabel_info, 
                                                    avatar_url=session.get('avatar'), 
                                                    rolle=session.get('rolle'), 
                                                    name=session.get('name'), Nutzer_Punkte=session.get('Nutzer_Punkte'))
        sidebar = await render_template('/parts/Elemente/sidebar.html', 
                                        WhiteLabel=g.whitelabel_info, rolle=session.get('rolle'))
        footer = await render_template('/parts/Elemente/footer.html', WhiteLabel = g.whitelabel_info, Session_Info=g.Session_Info['LogEntry_ID'], nutzername=session.get('username'), nutzer_ID=session.get('id'))

        theme_customizer = await render_template('/parts/Elemente/theme-customizer.html', 
                                                WhiteLabel=g.whitelabel_info)


        # Die Items von der Collection "Nutzer" abrufen
        try:
            data = client.get_items("Nutzer")

            print(data)
            if 'error' in data:
                nutzer_details = []
                print(f"Fehler: {data['error']}")
            else:
                if data:  # Überprüfen, ob Daten vorhanden sind
                    nutzer_details = data  # Speichere die Whitelabel-Informationen in g
                    print(f"Nutzer-Details: {nutzer_details}")
                else:
                    nutzer_details = []
                    print(f"Fehler beim Abruf der Nutzer.")
        except Exception as e:
            print(f"Fehler beim Abrufen der Daten: {e}")
            
        nutzer_ids = [nutzer['id'] for nutzer in data if nutzer['Referrer'] == session.get('id')] # Nutzer, für welche der Admin zuständig ist bzw. welche dieser angelegt hat
        nutzer_liste = [nutzer for nutzer in data if nutzer['Referrer'] == session.get('id')] # Nutzer, für welche der Admin zuständig ist bzw. welche dieser angelegt hat
        
        
        request_directus = {
            "query": {
                "filter": {
                    "WhiteLabel": {
                        "id": {
                            "_eq": int(g.whitelabel_info['id'])
                        }
                    }
                }
            }
        }

        try:
            data = client.get_items("Fitnesstest_INDIVIDUELL", request_directus)

            print(data)
            if 'error' in data:
                Individuelle_Anfragen = []
                print(f"Fehler: {data['error']}")
            else:
                if data:  # Überprüfen, ob Daten vorhanden sind
                    Individuelle_Anfragen = data  # Speichere die Whitelabel-Informationen in g
                    print(f"Individuelle_Anfragen: {Individuelle_Anfragen}")
                else:
                    Individuelle_Anfragen = []
                    print(f"Fehler beim Abruf der Daten.")
        except Exception as e:
            print(f"Fehler beim Abrufen der Daten: {e}")

        for anfrage in Individuelle_Anfragen:
            # Prüfen, ob der Nutzer-Schlüssel in der Nutzerliste vorhanden ist
            nutzer = next((nutzer for nutzer in nutzer_liste if anfrage['Nutzer']['key'] == nutzer['id']), None)

            anfrage['Nutzer-Details'] = nutzer

            
            # Hole Daten aus client.get_item, wenn Uebung vorhanden ist
            for key, value in anfrage.items():
                if key.startswith("Uebung_") and value:  # Nur wenn ein Uebungswert vorhanden ist
                    uebung_data = client.get_item("Uebungen", value["key"])
                    anfrage[key] = uebung_data  # Ersetze den Key mit den Daten aus der API


        try:
            data = client.get_items("FitnessTest_ALLGEMEIN", request_directus)

            print(data)
            if 'error' in data:
                Fitnesstest_EINTRÄGE = []
                print(f"Fehler: {data['error']}")
            else:
                if data:  # Überprüfen, ob Daten vorhanden sind
                    Fitnesstest_EINTRÄGE = data  # Speichere die Whitelabel-Informationen in g
                    print(f"Fitnesstest_EINTRÄGE: {Fitnesstest_EINTRÄGE}")
                else:
                    Fitnesstest_EINTRÄGE = []
                    print(f"Fehler beim Abruf der Nutzer.")
        except Exception as e:
            print(f"Fehler beim Abrufen der Daten: {e}")

        # Umformatieren der Daten
        filtered_data = {}

        for item in Fitnesstest_EINTRÄGE:
            typ = item.get('Typ')  # Typ als Schlüssel
            # Hole Daten aus client.get_item, wenn Uebung vorhanden ist
            for key, value in item.items():
                if key.startswith("Uebung_") and value:  # Nur wenn ein Uebungswert vorhanden ist
                    uebung_data = client.get_item("Uebungen", value["key"])
                    item[key] = uebung_data  # Ersetze den Key mit den Daten aus der API
            
            # Restliche Daten filtern, Typ ausschließen
            filtered_data[typ] = {key: value for key, value in item.items() if key != 'Typ'}

        print(filtered_data)


        # Rendern der Vorschau-HTML-Vorlage mit den erhaltenen Parametern
        return await render_template(f'/parts/Seiten/Admin-Bereich/Trainingshalle/Fitness-Tests.html', 
                                    header=header,
                                    error=error, 
                                    success=success, 
                                    sidebar=sidebar, 
                                    footer=footer, 
                                    theme_customizer=theme_customizer,
                                    username=session.get('username'), 
                                    rolle=session.get('rolle'), 
                                    name=session.get('name'), 
                                    avatar_url=session.get('avatar'), 
                                    WhiteLabel=g.whitelabel_info,
                                    Fitnesstest_EINTRÄGE = filtered_data,
                                    Individuelle_Anfragen = Individuelle_Anfragen,
                                    Nutzer_Liste = nutzer_liste)
    else:
        Art = request.args.get('Art')
        Form_Data = await request.form

        if Art != "Individuell":
            if Art == "Fitnessstudio":
                request_directus = {
                    "query": {
                        "filter": {
                            "WhiteLabel": {
                                "id": {
                                    "_eq": int(g.whitelabel_info['id'])
                                }
                            },
                            "Typ": {
                                "_eq": "Fitnessstudio"
                            }
                        }
                    }
                }
            elif Art == "Zuhause_GERÄTE":
                request_directus = {
                    "query": {
                        "filter": {
                            "WhiteLabel": {
                                "id": {
                                    "_eq": int(g.whitelabel_info['id'])
                                }
                            },
                            "Typ": {
                                "_eq": "Zuhause_GERÄTE"
                            }
                        }
                    }
                }
            elif Art == "Zuhause":
                request_directus = {
                    "query": {
                        "filter": {
                            "WhiteLabel": {
                                "id": {
                                    "_eq": int(g.whitelabel_info['id'])
                                }
                            },
                            "Typ": {
                                "_eq": "Zuhause"
                            }
                        }
                    }
                }
            elif Art == "Gesundheitliche_Probleme":
                request_directus = {
                    "query": {
                        "filter": {
                            "WhiteLabel": {
                                "id": {
                                    "_eq": int(g.whitelabel_info['id'])
                                }
                            },
                            "Typ": {
                                "_eq": "Gesundheit"
                            }
                        }
                    }
                }

            try:
                data = client.get_items("FitnessTest_ALLGEMEIN", request_directus)

                print(data)
                if 'error' in data:
                    Fitnesstest_EINTRAG = {}
                    print(f"Fehler: {data['error']}")
                else:
                    if data:  # Überprüfen, ob Daten vorhanden sind
                        Fitnesstest_EINTRAG = data[0]  # Speichere die Whitelabel-Informationen in g
                        print(f"Fitnesstest_EINTRAG: {Fitnesstest_EINTRAG}")
                    else:
                        Fitnesstest_EINTRAG = {}
                        print(f"Fehler beim Abruf der Nutzer.")
            except Exception as e:
                print(f"Fehler beim Abrufen der Daten: {e}")

            item_data = {
                "WhiteLabel": {"key": int(g.whitelabel_info['id']), "collection": "WhiteLabel"},
                "Typ": "Fitnessstudio" if Art == "Fitnessstudio" else \
                    "Zuhause_GERÄTE" if Art == "Zuhause_GERÄTE" else \
                    "Zuhause" if Art == "Zuhause" else \
                    "Gesundheit" if Art == "Gesundheitliche_Probleme" else None
            }

            # Dynamische Zuweisung nur, wenn Werte nicht leer sind
            for key in [f"Übung_{i}" for i in range(1, 11)]:
                value = Form_Data.get(key, "").strip()  # Hole und trimme den Wert
                if value:  # Nur, wenn der Wert nicht leer ist
                    new_key = key.replace("Übung", "Uebung")  # Ändere den Schlüssel
                    item_data[new_key] = {"key": value, "collection": "Uebungen"}

            print(item_data)

            # WENN 'Fitnesstests' der spezifischen Art bereits existieren, dann werden Sie geupdatet;
                # ANSONSTEN werden Sie neu erstellt
            if Fitnesstest_EINTRAG == {}:
                # Existiert noch nicht
                client.create_item("FitnessTest_ALLGEMEIN", item_data=item_data)
            else:
                # Existiert schon
                client.update_item("FitnessTest_ALLGEMEIN", Fitnesstest_EINTRAG['id'], item_data=item_data)

            session['success'] = f"Fitnesstest wurde erfolgreich aktualisiert."
            return redirect(url_for('ADMIN_Trainingshalle_FitnessTests'))
        else:
            #! 1. SCHRITT:  
            ############??   Fitness-Test (individuell) in Directus erstellen
            item_data = {
                "WhiteLabel": {'key': int(g.whitelabel_info['id']), 'collection': 'WhiteLabel'},
                "Ersteller": {'key': int(session.get('id')), 'collection': 'Nutzer'},
                "Nutzer": {'key': int(Form_Data.get('Kunde')), 'collection': 'Nutzer'},
                "Grund": Form_Data.get('Grund')
            }
            # Dynamisch Felder mit "Übung_" suchen und in "Uebung_" umbenennen
            for key in Form_Data:
                if key.startswith("Übung_"):
                    # Umbenennen von "Übung_*" nach "Uebung_*"
                    new_key = key.replace("Übung_", "Uebung_")
                    item_data[new_key] = {'key': Form_Data.get(key), 'collection': 'Uebungen'}

            FitnessTest_ID = client.create_item("Fitnesstest_INDIVIDUELL", item_data)

            #! 2. SCHRITT:  
            ############??   Individuellen Fitness-Test dem richtigen Nutzer zuweisen und zur Durchführung zwingen!
            Nutzer_ID = item_data['Nutzer']['key']
            item_data = {
                "Fitnesstest_Individuell": {'key': FitnessTest_ID['data']['id'], 'collection': 'Fitnesstest_INDIVIDUELL'},
                "Fitness_Test": True
            }
            client.update_item("Nutzer", int(Nutzer_ID), item_data)


            session['success'] = f"Fitnesstest wurde erfolgreich erstellt und an den Kunden geschickt."
            return redirect(url_for('ADMIN_Trainingshalle_FitnessTests'))



@app.route('/admin/white-label/einstellungen', methods=['GET', 'POST'])
async def WhiteLabel_Einstellungen():
    print(session.get('WhiteLabel_Admin')['admin'])
    if session.get('WhiteLabel_Admin')['admin']:
        print(g.whitelabel_info)
        if request.method == "GET":

            if request.args.get('delete'):
                if request.args.get('delete') == "ecommerce_shop":
                    produkt_id = request.args.get('id')

                    client.delete_item("ECommerce_Shop", produkt_id)

                    session['success'] = f"Das Produkt wurde erfolgreich gelöscht."
                    return redirect(f"https://dashboard.{g.whitelabel_info['Domain']}/admin/white-label/einstellungen?quickstart=ecommerce")
            
            if request.args.get('deaktivieren'):
                if request.args.get('deaktivieren') == "auszeichnungen":
                    updated_item = client.update_item(collection_name='WhiteLabel', item_id=session.get('WhiteLabel_Admin')['id'],
                                  item_data={'Badges_Status': False})

                    session['success'] = f"Die Deaktivierung der Auszeichnungen war erfolgreich."
                    return redirect(f"https://dashboard.{g.whitelabel_info['Domain']}/admin/white-label/einstellungen?quickstart=auszeichnungen")
                else:
                    session['error'] = f"Diese Aktion ist leider ungültig."
                    return redirect(f"https://dashboard.{g.whitelabel_info['Domain']}/admin/white-label/einstellungen?quickstart=auszeichnungen")
            if request.args.get('aktivieren'):
                if request.args.get('aktivieren') == "auszeichnungen":
                    updated_item = client.update_item(collection_name='WhiteLabel', item_id=session.get('WhiteLabel_Admin')['id'],
                                  item_data={'Badges_Status': True})

                    session['success'] = f"Die Aktivierung der Auszeichnungen war erfolgreich."
                    return redirect(f"https://dashboard.{g.whitelabel_info['Domain']}/admin/white-label/einstellungen?quickstart=auszeichnungen")
                else:
                    session['error'] = f"Diese Aktion ist leider ungültig."
                    return redirect(f"https://dashboard.{g.whitelabel_info['Domain']}/admin/white-label/einstellungen?quickstart=auszeichnungen")
            
            
            if request.args.get('Standard_Badge'):
                old_id = request.args.get('old')

                if request.args.get('Standard_Badge') in ["Willkommen","2","3","4","5","6"]:
                    value = ""
                    if request.args.get('Standard_Badge') == "Willkommen":
                        value = "6c552f22-883d-49bd-b651-5f2f9c5b6b36"
                        if old_id != value:
                            # Alte Datei löschen
                            client.delete_file(file_id=old_id)

                    elif request.args.get('Standard_Badge') == "2":
                        value = "bfce42d9-92da-4c64-bb4c-9358ff1fa4e8"
                        if old_id != value:
                            # Alte Datei löschen
                            client.delete_file(file_id=old_id)

                    elif request.args.get('Standard_Badge') == "3":
                        value = "4b24c4c9-bdc0-40d9-93ea-bed6e87deaab"
                        if old_id != value:
                            # Alte Datei löschen
                            client.delete_file(file_id=old_id)
                            
                    elif request.args.get('Standard_Badge') == "4":
                        value = "97f488b2-dc7f-43a4-b9c0-d36bf1291358"
                        if old_id != value:
                            # Alte Datei löschen
                            client.delete_file(file_id=old_id)
                            
                    elif request.args.get('Standard_Badge') == "5":
                        value = "709bad1b-50c5-4c6f-87c5-f06e49d948e8"
                        if old_id != value:
                            # Alte Datei löschen
                            client.delete_file(file_id=old_id)
                            
                    elif request.args.get('Standard_Badge') == "6":
                        value = "8d83ebf3-8642-4931-944e-177885c1ea0d"
                        if old_id != value:
                            # Alte Datei löschen
                            client.delete_file(file_id=old_id)

                    updated_item = client.update_item(collection_name='WhiteLabel', item_id=session.get('WhiteLabel_Admin')['id'], item_data={f'Badge_{request.args.get('Standard_Badge')}': f"{value}"})

                    session['success'] = f"Das Zurücksetzen des Badge auf die Standard-Option war erfolgreich."
                    return redirect(f"https://dashboard.{g.whitelabel_info['Domain']}/admin/white-label/einstellungen?quickstart=auszeichnungen")
                else:
                    session['error'] = f"Dieses Badge ist leider ungültig."
                    return redirect(f"https://dashboard.{g.whitelabel_info['Domain']}/admin/white-label/einstellungen?quickstart=auszeichnungen")

            request_directus = {
                "query": {
                    "filter": {
                        "WhiteLabel": {
                            "id": {
                                "_eq": int(g.whitelabel_info['id'])
                            }
                        }
                    }
                }
            }
            Ecommerce_Produkte = client.get_items('ECommerce_Shop', request_directus)

            success = session.pop('success', None)
            punkte = session.pop('Punkte_Nachricht', None)
            punkte_nachricht = punkte
            error = session.pop('error', None)
            
            header = await render_template('/parts/Elemente/header.html', url= request.url, WhiteLabel = g.whitelabel_info, avatar_url=session.get('avatar'), rolle=session.get('rolle'), name=session.get('name'), Nutzer_Punkte=session.get('Nutzer_Punkte'))
            sidebar = await render_template('/parts/Elemente/sidebar.html', WhiteLabel = g.whitelabel_info, rolle=session.get('rolle'))
            footer = await render_template('/parts/Elemente/footer.html', WhiteLabel = g.whitelabel_info, Session_Info=g.Session_Info['LogEntry_ID'], nutzername=session.get('username'), nutzer_ID=session.get('id'))
            theme_customizer = await render_template('/parts/Elemente/theme-customizer.html', WhiteLabel = g.whitelabel_info)

            WhiteLabel_Admin_Content = client.get_item(collection_name='WhiteLabel', item_id=f'{session.get('WhiteLabel_Admin')['id']}')

            if WhiteLabel_Admin_Content['id'] != g.whitelabel_info['id']:
                session['error'] = f"Du hast leider keinen Zugriff auf die WhiteLabel-Instanz von '{g.whitelabel_info['Bezeichnung']}'."
                return redirect(f"https://dashboard.{g.whitelabel_info['Domain']}")

            quickStart_TAB = request.args.get('quickstart')

            return await render_template('/parts/Seiten/Admin-Bereich/WhiteLabel-Einstellungen.html', header=header, sidebar=sidebar, footer=footer, theme_customizer=theme_customizer, success=success, error=error, punkte = punkte, punkte_nachricht = punkte_nachricht, username=session.get('username'), rolle=session.get('rolle'), name=session.get('name'), avatar_url=session.get('avatar'), WhiteLabel = WhiteLabel_Admin_Content, quickStart_TAB=quickStart_TAB, Ecommerce_Produkte=Ecommerce_Produkte)
        else:
            if request.args.get('preview'):
                # Verarbeite die POST-Daten
                data = await request.form
                files = await request.files
                titel = data.get('titel')
                beschreibung = data.get('beschreibung')
                video = files.get('video')  # Hole die hochgeladene Video-Datei

                video_base64 = None

                if video and allowed_file(video.filename):
                    video_bytes = video.read()  # Lese die Datei in Bytes (kein await)
                    video_base64 = base64.b64encode(video_bytes).decode('utf-8')  # Konvertiere in Base64

                # Erstelle die Video-URL für die Vorschau
                video_url = f"data:video/mp4;base64,{video_base64}" if video_base64 else None

                header = await render_template('/parts/Elemente/header.html', 
                                                url= request.url, 
                                                WhiteLabel=g.whitelabel_info, 
                                                avatar_url=session.get('avatar'), 
                                                rolle=session.get('rolle'), 
                                                name=session.get('name'), Nutzer_Punkte=session.get('Nutzer_Punkte'))
                sidebar = await render_template('/parts/Elemente/sidebar.html', 
                                                WhiteLabel=g.whitelabel_info, rolle=session.get('rolle'))
                footer = await render_template('/parts/Elemente/footer.html', WhiteLabel = g.whitelabel_info, Session_Info=g.Session_Info['LogEntry_ID'], nutzername=session.get('username'), nutzer_ID=session.get('id'))

                theme_customizer = await render_template('/parts/Elemente/theme-customizer.html', 
                                                        WhiteLabel=g.whitelabel_info)
                
                # Rendern der Vorschau-HTML-Vorlage mit den erhaltenen Parametern
                return await render_template(f'/parts/Seiten/Admin-Bereich/WhiteLabel-Templates/{request.args.get('preview')}.html', 
                                            header=header, 
                                            sidebar=sidebar, 
                                            footer=footer, 
                                            theme_customizer=theme_customizer, 
                                            titel=titel, 
                                            beschreibung=beschreibung, 
                                            username=session.get('username'), 
                                            rolle=session.get('rolle'), 
                                            name=session.get('name'), 
                                            avatar_url=session.get('avatar'), 
                                            WhiteLabel=g.whitelabel_info, 
                                            video_url=video_url)
            elif request.args.get('neu'):
                if request.args.get('neu') == "ecommerce_shop":
                    data = await request.form
                    files = await request.files

                    rechte= []

                    item_data = {
                        "Bezeichnung": data.get('name'),
                        "Beschreibung": data.get('beschreibung'),
                        "Preis": round(float(data.get('preis').replace(',', '.')), 2),  # Rundet auf 2 Dezimalstellen
                        "Preis_Rabatt": round(float(data.get('preis_rabatt').replace(',', '.')), 2),
                        "Rechte": rechte,
                        "WhiteLabel": {"key": int(session.get('WhiteLabel_Admin')['id']),"collection":"WhiteLabel"}
                    }

                    client.create_item('ECommerce_Shop', item_data=item_data)

                    session['success'] = f"Das Produkt '{data.get('name')}' wurde erfolgreich angelegt."
                    return redirect(f"https://dashboard.{g.whitelabel_info['Domain']}/admin/white-label/einstellungen?quickstart=ecommerce")

            elif request.args.get('update'):
                whitelabel_id = session.get('WhiteLabel_Admin')['id']

                if request.args.get('update') == "landingpage":
                    data = await request.form
                    files = await request.files

                    return jsonify({
                        f"Änderung für '{request.args.get('update')}'": {
                            "Daten": dict(data),  # Umformung der Daten in ein Dictionary
                            "Dateien": {file.filename: file.mimetype for file in files.values()}  # Dateiinformationen in einem Dictionary
                        }
                    })
                elif request.args.get('update') == "allgemein":
                    data = await request.form
                    files = await request.files
                    whitelabel_id = session.get('WhiteLabel_Admin')['id']

                    # Hilfsfunktion zum temporären Speichern der Datei
                    async def save_temp_file(file_storage):
                        # Erstelle eine temporäre Datei
                        temp_file = tempfile.NamedTemporaryFile(delete=False)
                        try:
                            # Schreibe den Inhalt der hochgeladenen Datei in die temporäre Datei
                            temp_file.write(file_storage.read())
                            temp_file.close()  # Schließe die Datei
                            return temp_file.name  # Gibt den Pfad zur temporären Datei zurück
                        except Exception as e:
                            temp_file.close()
                            os.remove(temp_file.name)  # Lösche die temporäre Datei im Fehlerfall
                            raise e

                    # Update der alten Datei mit der ID 'logoLang_old_ID'
                    if data.get('logoLang_old_ID'):
                        old_logo_id = data.get('logoLang_old_ID')
                        if 'logo_lang' in files:
                            new_file_storage = files['logo_lang']
                            temp_file_path = await save_temp_file(new_file_storage)  # Speichere die Datei temporär

                            # Neue Datei hochladen
                            upload_data = {
                                "title": new_file_storage.filename,
                                "description": "Neues langes Logo",
                                "tags": ["logo", "lange version"],
                                "type": new_file_storage.content_type  # MIME-Typ hinzufügen
                            }
                            uploaded_file = client.upload_file(temp_file_path, upload_data)
                            new_file_id = uploaded_file['id']  # Neuen File-ID speichern

                            # Alte Datei löschen
                            client.delete_file(file_id=old_logo_id)

                            # Lösche die temporäre Datei
                            os.remove(temp_file_path)

                            # Hier kannst du die Referenz in deiner Datenbank oder deinem Modell aktualisieren, wenn nötig
                            updated_item = client.update_item(collection_name='WhiteLabel', item_id=f'{whitelabel_id}', item_data={'Logo_lang': f'{new_file_id}'})
                            print(f"Update-Response von 'Logo_lang': {updated_item}")

                    # Update der alten Datei mit der ID 'logoKurz_old_ID'
                    if data.get('logoKurz_old_ID'):
                        old_short_logo_id = data.get('logoKurz_old_ID')
                        if 'logo_kurz' in files:
                            new_file_storage = files['logo_kurz']
                            temp_file_path = await save_temp_file(new_file_storage)
                            upload_data = {
                                "title": new_file_storage.filename,
                                "description": "Neues kurzes Logo",
                                "tags": ["logo", "kurze version"],
                                "type": new_file_storage.content_type  # MIME-Typ hinzufügen
                            }
                            uploaded_file = client.upload_file(temp_file_path, upload_data)
                            new_file_id = uploaded_file['id']
                            client.delete_file(file_id=old_short_logo_id)
                            os.remove(temp_file_path)

                            # Hier kannst du die Referenz in deiner Datenbank oder deinem Modell aktualisieren, wenn nötig
                            updated_item = client.update_item(collection_name='WhiteLabel', item_id=f'{whitelabel_id}', item_data={'Logo_kurz': f'{new_file_id}'})
                            print(f"Update-Response von 'Logo_lang': {updated_item}")

                    # Update der alten Datei mit der ID 'logoIcon_old_ID'
                    if data.get('logoIcon_old_ID'):
                        old_icon_id = data.get('logoIcon_old_ID')
                        if 'logo_icon' in files:
                            new_file_storage = files['logo_icon']
                            temp_file_path = await save_temp_file(new_file_storage)
                            upload_data = {
                                "title": new_file_storage.filename,
                                "description": "Neues Icon-Logo",
                                "tags": ["logo", "icon version"],
                                "type": new_file_storage.content_type  # MIME-Typ hinzufügen
                            }
                            uploaded_file = client.upload_file(temp_file_path, upload_data)
                            new_file_id = uploaded_file['id']
                            client.delete_file(file_id=old_icon_id)
                            os.remove(temp_file_path)

                            # Hier kannst du die Referenz in deiner Datenbank oder deinem Modell aktualisieren, wenn nötig
                            updated_item = client.update_item(collection_name='WhiteLabel', item_id=f'{whitelabel_id}', item_data={'Logo_Icon': f'{data.get('')}'})
                            print(f"Update-Response von 'Logo_lang': {updated_item}")

                    # Update der alten Datei mit der ID 'favicon_old_ID'
                    if data.get('favicon_old_ID'):
                        old_favicon_id = data.get('favicon_old_ID')
                        if 'favicon' in files:
                            new_file_storage = files['favicon']
                            temp_file_path = await save_temp_file(new_file_storage)
                            upload_data = {
                                "title": new_file_storage.filename,
                                "description": "Neuer Favicon",
                                "tags": ["favicon"],
                                "type": new_file_storage.content_type  # MIME-Typ hinzufügen
                            }
                            uploaded_file = client.upload_file(temp_file_path, upload_data)
                            new_file_id = uploaded_file['id']
                            client.delete_file(file_id=old_favicon_id)
                            os.remove(temp_file_path)

                            # Hier kannst du die Referenz in deiner Datenbank oder deinem Modell aktualisieren, wenn nötig
                            updated_item = client.update_item(collection_name='WhiteLabel', item_id=f'{whitelabel_id}', item_data={'Favicon': f'{new_file_id}'})
                            print(f"Update-Response von 'Logo_lang': {updated_item}")

                    updated_item = client.update_item(collection_name='WhiteLabel', item_id=f'{whitelabel_id}', item_data={'Bezeichnung': f'{data.get('bezeichnung')}', 'Domain': f'{data.get('domain')}', 'Primary': f'{data.get('primary_color')}', 'Secondary': f'{data.get('secondary_color')}', 'Third': f'{data.get('third_color')}', 'API_TOKEN_Deepl': f'{data.get('API_TOKEN_Deepl')}', 'API_TOKEN_ElevenLabs': f'{data.get('API_TOKEN_ElevenLabs')}', 'API_TOKEN_Mollie': f'{data.get('API_TOKEN_Mollie')}'})
                    print(f"Update-Response von 'Logo_lang': {updated_item}")


                    session['success'] = f"Du hast erfolgreich das WhiteLabel-Design geändert."
                    return redirect(f"https://dashboard.{g.whitelabel_info['Domain']}/admin/white-label/einstellungen?quickstart=allgemein")
                elif request.args.get('update') == "auszeichnungen":
                    data = await request.form
                    files = await request.files

                    # Hilfsfunktion zum temporären Speichern der Datei
                    async def save_temp_file(file_storage):
                        # Erstelle eine temporäre Datei
                        temp_file = tempfile.NamedTemporaryFile(delete=False)
                        try:
                            # Schreibe den Inhalt der hochgeladenen Datei in die temporäre Datei
                            temp_file.write(file_storage.read())
                            temp_file.close()  # Schließe die Datei
                            return temp_file.name  # Gibt den Pfad zur temporären Datei zurück
                        except Exception as e:
                            temp_file.close()
                            os.remove(temp_file.name)  # Lösche die temporäre Datei im Fehlerfall
                            raise e

                    # Update der alten Datei mit der ID 'Badge_Willkommen_OLD_ID'
                    if data.get('Badge_Willkommen_OLD_ID'):
                        old_logo_id = data.get('Badge_Willkommen_OLD_ID')
                        if 'Badge_Willkommen' in files:
                            new_file_storage = files['Badge_Willkommen']
                            temp_file_path = await save_temp_file(new_file_storage)  # Speichere die Datei temporär

                            # Neue Datei hochladen
                            upload_data = {
                                "title": new_file_storage.filename,
                                "description": "Neues Badge Willkommen",
                                "tags": ["badge", "willkommen"],
                                "type": new_file_storage.content_type  # MIME-Typ hinzufügen
                            }
                            uploaded_file = client.upload_file(temp_file_path, upload_data)
                            new_file_id = uploaded_file['id']  # Neuen File-ID speichern

                            if data.get('Badge_Willkommen_OLD_ID') != "6c552f22-883d-49bd-b651-5f2f9c5b6b36":
                                # Alte Datei löschen
                                client.delete_file(file_id=old_logo_id)

                            # Lösche die temporäre Datei
                            os.remove(temp_file_path)

                            # Hier kannst du die Referenz in deiner Datenbank oder deinem Modell aktualisieren, wenn nötig
                            updated_item = client.update_item(collection_name='WhiteLabel', item_id=f'{whitelabel_id}', item_data={'Badge_Willkommen': f'{new_file_id}'})
                            print(f"Update-Response von 'Badge_Willkommen': {updated_item}")
                    updated_item = client.update_item(collection_name='WhiteLabel', item_id=f'{whitelabel_id}', item_data={'Badge_Willkommen_Text': f'{data.get('Badge_Willkommen_Text')}',
                                                                                                                            'Badge_Willkommen_Punkte': f'{data.get('Badge_Willkommen_Punkte')}'})

                    # Update der alten Datei mit der ID 'Badge_2_OLD_ID'
                    if data.get('Badge_2_OLD_ID'):
                        old_logo_id = data.get('Badge_2_OLD_ID')
                        if 'Badge_2' in files:
                            new_file_storage = files['Badge_2']
                            temp_file_path = await save_temp_file(new_file_storage)  # Speichere die Datei temporär

                            # Neue Datei hochladen
                            upload_data = {
                                "title": new_file_storage.filename,
                                "description": "Neues Badge 2",
                                "tags": ["badge", "2"],
                                "type": new_file_storage.content_type  # MIME-Typ hinzufügen
                            }
                            uploaded_file = client.upload_file(temp_file_path, upload_data)
                            new_file_id = uploaded_file['id']  # Neuen File-ID speichern

                            if data.get('Badge_2_OLD_ID') != "bfce42d9-92da-4c64-bb4c-9358ff1fa4e8":
                                # Alte Datei löschen
                                client.delete_file(file_id=old_logo_id)

                            # Lösche die temporäre Datei
                            os.remove(temp_file_path)

                            # Hier kannst du die Referenz in deiner Datenbank oder deinem Modell aktualisieren, wenn nötig
                            updated_item = client.update_item(collection_name='WhiteLabel', item_id=f'{whitelabel_id}', item_data={'Badge_2': f'{new_file_id}'})
                            print(f"Update-Response von 'Badge_2': {updated_item}")
                    updated_item = client.update_item(collection_name='WhiteLabel', item_id=f'{whitelabel_id}', item_data={'Badge_2_Text': f'{data.get('Badge_2_Text')}',
                                                                                                                            'Badge_2_Punkte': f'{data.get('Badge_2_Punkte')}'})

                    # Update der alten Datei mit der ID 'Badge_3_OLD_ID'
                    if data.get('Badge_3_OLD_ID'):
                        old_logo_id = data.get('Badge_3_OLD_ID')
                        if 'Badge_3' in files:
                            new_file_storage = files['Badge_3']
                            temp_file_path = await save_temp_file(new_file_storage)  # Speichere die Datei temporär

                            # Neue Datei hochladen
                            upload_data = {
                                "title": new_file_storage.filename,
                                "description": "Neues Badge 3",
                                "tags": ["badge", "3"],
                                "type": new_file_storage.content_type  # MIME-Typ hinzufügen
                            }
                            uploaded_file = client.upload_file(temp_file_path, upload_data)
                            new_file_id = uploaded_file['id']  # Neuen File-ID speichern

                            if data.get('Badge_3_OLD_ID') != "4b24c4c9-bdc0-40d9-93ea-bed6e87deaab":
                                # Alte Datei löschen
                                client.delete_file(file_id=old_logo_id)

                            # Lösche die temporäre Datei
                            os.remove(temp_file_path)

                            # Hier kannst du die Referenz in deiner Datenbank oder deinem Modell aktualisieren, wenn nötig
                            updated_item = client.update_item(collection_name='WhiteLabel', item_id=f'{whitelabel_id}', item_data={'Badge_3': f'{new_file_id}'})
                            print(f"Update-Response von 'Badge_3': {updated_item}")
                    updated_item = client.update_item(collection_name='WhiteLabel', item_id=f'{whitelabel_id}', item_data={'Badge_3_Text': f'{data.get('Badge_3_Text')}',
                                                                                                                            'Badge_3_Punkte': f'{data.get('Badge_3_Punkte')}'})

                    # Update der alten Datei mit der ID 'Badge_4_OLD_ID'
                    if data.get('Badge_4_OLD_ID'):
                        old_logo_id = data.get('Badge_4_OLD_ID')
                        if 'Badge_4' in files:
                            new_file_storage = files['Badge_4']
                            temp_file_path = await save_temp_file(new_file_storage)  # Speichere die Datei temporär

                            # Neue Datei hochladen
                            upload_data = {
                                "title": new_file_storage.filename,
                                "description": "Neues Badge 4",
                                "tags": ["badge", "4"],
                                "type": new_file_storage.content_type  # MIME-Typ hinzufügen
                            }
                            uploaded_file = client.upload_file(temp_file_path, upload_data)
                            new_file_id = uploaded_file['id']  # Neuen File-ID speichern

                            if data.get('Badge_4_OLD_ID') != "97f488b2-dc7f-43a4-b9c0-d36bf1291358":
                                # Alte Datei löschen
                                client.delete_file(file_id=old_logo_id)

                            # Lösche die temporäre Datei
                            os.remove(temp_file_path)

                            # Hier kannst du die Referenz in deiner Datenbank oder deinem Modell aktualisieren, wenn nötig
                            updated_item = client.update_item(collection_name='WhiteLabel', item_id=f'{whitelabel_id}', item_data={'Badge_4': f'{new_file_id}'})
                            print(f"Update-Response von 'Badge_4': {updated_item}")
                    updated_item = client.update_item(collection_name='WhiteLabel', item_id=f'{whitelabel_id}', item_data={'Badge_4_Text': f'{data.get('Badge_4_Text')}',
                                                                                                                            'Badge_4_Punkte': f'{data.get('Badge_4_Punkte')}'})

                    # Update der alten Datei mit der ID 'Badge_5_OLD_ID'
                    if data.get('Badge_5_OLD_ID'):
                        old_logo_id = data.get('Badge_5_OLD_ID')
                        if 'Badge_5' in files:
                            new_file_storage = files['Badge_5']
                            temp_file_path = await save_temp_file(new_file_storage)  # Speichere die Datei temporär

                            # Neue Datei hochladen
                            upload_data = {
                                "title": new_file_storage.filename,
                                "description": "Neues Badge 5",
                                "tags": ["badge", "5"],
                                "type": new_file_storage.content_type  # MIME-Typ hinzufügen
                            }
                            uploaded_file = client.upload_file(temp_file_path, upload_data)
                            new_file_id = uploaded_file['id']  # Neuen File-ID speichern

                            if data.get('Badge_5_OLD_ID') != "709bad1b-50c5-4c6f-87c5-f06e49d948e8":
                                # Alte Datei löschen
                                client.delete_file(file_id=old_logo_id)

                            # Lösche die temporäre Datei
                            os.remove(temp_file_path)

                            # Hier kannst du die Referenz in deiner Datenbank oder deinem Modell aktualisieren, wenn nötig
                            updated_item = client.update_item(collection_name='WhiteLabel', item_id=f'{whitelabel_id}', item_data={'Badge_5': f'{new_file_id}'})
                            print(f"Update-Response von 'Badge_5': {updated_item}")
                    updated_item = client.update_item(collection_name='WhiteLabel', item_id=f'{whitelabel_id}', item_data={'Badge_5_Text': f'{data.get('Badge_5_Text')}',
                                                                                                                            'Badge_5_Punkte': f'{data.get('Badge_5_Punkte')}'})

                    # Update der alten Datei mit der ID 'Badge_6_OLD_ID'
                    if data.get('Badge_6_OLD_ID'):
                        old_logo_id = data.get('Badge_6_OLD_ID')
                        if 'Badge_6' in files:
                            new_file_storage = files['Badge_6']
                            temp_file_path = await save_temp_file(new_file_storage)  # Speichere die Datei temporär

                            # Neue Datei hochladen
                            upload_data = {
                                "title": new_file_storage.filename,
                                "description": "Neues Badge Stufe 6",
                                "tags": ["badge", "6"],
                                "type": new_file_storage.content_type  # MIME-Typ hinzufügen
                            }
                            uploaded_file = client.upload_file(temp_file_path, upload_data)
                            new_file_id = uploaded_file['id']  # Neuen File-ID speichern

                            if data.get('Badge_6_OLD_ID') != "8d83ebf3-8642-4931-944e-177885c1ea0d":
                                # Alte Datei löschen
                                client.delete_file(file_id=old_logo_id)

                            # Lösche die temporäre Datei
                            os.remove(temp_file_path)

                            # Hier kannst du die Referenz in deiner Datenbank oder deinem Modell aktualisieren, wenn nötig
                            updated_item = client.update_item(collection_name='WhiteLabel', item_id=f'{whitelabel_id}', item_data={'Badge_6': f'{new_file_id}'})
                            print(f"Update-Response von 'Badge_6': {updated_item}")
                    updated_item = client.update_item(collection_name='WhiteLabel', item_id=f'{whitelabel_id}', item_data={'Badge_6_Text': f'{data.get('Badge_6_Text')}',
                                                                                                                            'Badge_6_Punkte': f'{data.get('Badge_6_Punkte')}'})


                    session['success'] = f"Du hast erfolgreich die Auszeichnungen Deiner WhiteLabel-Instanz geändert."
                    return redirect(f"https://dashboard.{g.whitelabel_info['Domain']}/admin/white-label/einstellungen?quickstart=auszeichnungen")
                elif request.args.get('update') == "landingpage":
                    data = await request.form
                    files = await request.files

                    return jsonify({
                        f"Änderung für '{request.args.get('update')}'": {
                            "Daten": dict(data),  # Umformung der Daten in ein Dictionary
                            "Dateien": {file.filename: file.mimetype for file in files.values()}  # Dateiinformationen in einem Dictionary
                        }
                    })
                elif request.args.get('update') == "buchhaltung":
                    data = await request.form

                    data = {
                        "Firmenname": data.get('betreiber_firma'),
                        "UmsatzsteuerID": data.get('betreiber_ustid'),
                        "Vorname": data.get('betreiber_vorname'),
                        "Nachname": data.get('betreiber_nachname'),
                        "Strasse": data.get('betreiber_strasse'),
                        "Hausnummer": data.get('betreiber_hausnummer'),
                        "PLZ": data.get('betreiber_postleitzahl'),
                        "Ort": data.get('betreiber_ort'),
                        "EMail": data.get('betreiber_email'),


                        "Rechnungsformat": data.get('rechnung_format'),
                        "KleinunternehmerRegelung": True if data.get('kleinunternehmer_regelung') == "0Prozent" else False
                    }

                    client.update_item('WhiteLabel', whitelabel_id, data)

                    session['success'] = f"Du hast erfolgreich die Informationen zur Buchhaltung Deiner WhiteLabel-Instanz geändert."
                    return redirect(f"https://dashboard.{g.whitelabel_info['Domain']}/admin/white-label/einstellungen?quickstart=buchhaltung")
                else:
                    session['error'] = f"Bei '{request.args.get('update')}' handelt es sich um keine gültige Angabe."
                    return redirect(f"https://dashboard.{g.whitelabel_info['Domain']}/admin/white-label/einstellungen")
            else:
                session['error'] = "Dies war eine fehlerhafte Anfrage."
                return redirect(f"https://dashboard.{g.whitelabel_info['Domain']}/admin/white-label/einstellungen")
    else:
        session['error'] = "Auf diese Seite haben nur Super- bzw. Lower-Admins oder deren Vertretung Zugriff."
        return redirect(f"https://dashboard.{g.whitelabel_info['Domain']}")


import pytz

def datetimeformat(value, format='%d.%m.%Y um %H:%M Uhr', timezone='Europe/Berlin'):
    # Konvertiere das ISO-Datum in ein naives Datum (ohne Zeitzone)
    dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
    
    # Definiere die Zeitzone
    local_tz = pytz.timezone(timezone)
    
    # Wandle das naive Datum in UTC um und dann in die gewünschte Zeitzone
    dt_aware = dt.astimezone(local_tz)
    
    # Formatiere das Datum in das gewünschte Format
    return dt_aware.strftime(format)

app.jinja_env.filters['datetimeformat'] = datetimeformat

@app.route('/admin/voranmeldungen', methods=['GET', 'POST'])
async def Voranmeldungen_Uebersicht():
    success = session.pop('success', None)
    punkte = session.pop('Punkte_Nachricht', None)
    punkte_nachricht = punkte
    error = session.pop('error', None)

    if session.get('rolle')['Rolle'] == "Super-Super-Admin":
        header = await render_template('/parts/Elemente/header.html', url= request.url, 
                                                    WhiteLabel=g.whitelabel_info, 
                                                    avatar_url=session.get('avatar'), 
                                                    rolle=session.get('rolle'), 
                                                    name=session.get('name'), Nutzer_Punkte=session.get('Nutzer_Punkte'))
        sidebar = await render_template('/parts/Elemente/sidebar.html', 
                                        WhiteLabel=g.whitelabel_info, rolle=session.get('rolle'))
        footer = await render_template('/parts/Elemente/footer.html', WhiteLabel = g.whitelabel_info, Session_Info=g.Session_Info['LogEntry_ID'], nutzername=session.get('username'), nutzer_ID=session.get('id'))

        theme_customizer = await render_template('/parts/Elemente/theme-customizer.html', 
                                                WhiteLabel=g.whitelabel_info)
        

        # Die Items von der Collection "Voranmeldungen" abrufen
        try:
            data = client.get_items("Voranmeldungen")

            print(data)
            if 'error' in data:
                nutzer_details = []
                print(f"Fehler: {data['error']}")
            else:
                if data:  # Überprüfen, ob Daten vorhanden sind
                    nutzer_details = data  # Speichere die Whitelabel-Informationen in g
                    print(f"Nutzer-Details: {nutzer_details}")
                else:
                    nutzer_details = []
                    print(f"Fehler beim Abruf der Nutzer.")
        except Exception as e:
            print(f"Fehler beim Abrufen der Daten: {e}")

        print(session.get('id'))
        
        # Rendern der Vorschau-HTML-Vorlage mit den erhaltenen Parametern
        return await render_template(f'/parts/Seiten/Admin-Bereich/Voranmeldungen.html', 
                                    header=header,
                                    error=error, 
                                    success=success, 
                                    sidebar=sidebar, 
                                    footer=footer, 
                                    theme_customizer=theme_customizer,
                                    username=session.get('username'), 
                                    rolle=session.get('rolle'), 
                                    name=session.get('name'), 
                                    avatar_url=session.get('avatar'), 
                                    WhiteLabel=g.whitelabel_info,
                                    nutzer_liste=nutzer_details)
    
    else:
        session['error'] = "Auf diese Seite haben nur Super-Super-Admin's oder deren Vertretung Zugriff."
        return redirect(f"https://dashboard.{session.get('WhiteLabel')['Domain']}/")
    

@app.route('/admin/voranmeldung/<aktion>/<id>', methods=['GET', 'POST'])
async def Voranmeldungen_Aktionen(id, aktion):
    if session.get('rolle')['Rolle'] == "Super-Super-Admin":
        if aktion == "delete":
            client.delete_item(collection_name='Voranmeldungen', item_id=id)
            
            session['success'] = f"Die Voranmeldung wurde erfolgreich gelöscht."
            return redirect(f'https://dashboard.{session.get('WhiteLabel')['Domain']}/admin/voranmeldungen')
        else:
            session['error'] = f"Die Aktion war ungültig für '#{id}'."
            return redirect(f'https://dashboard.{g.whitelabel_info['Domain']}/admin/voranmeldungen')
        
    else:
        session['error'] = "Auf diese Seite haben nur Super-Super-Admin's oder deren Vertretung Zugriff."
        return redirect(f"https://dashboard.{session.get('WhiteLabel')['Domain']}/")


@app.route('/admin/benutzer/übersicht', methods=['GET', 'POST'])
async def Benutzer_Uebersicht():
    success = session.pop('success', None)
    punkte = session.pop('Punkte_Nachricht', None)
    punkte_nachricht = punkte
    error = session.pop('error', None)

    if session.get('WhiteLabel_Admin')['admin']:
        header = await render_template('/parts/Elemente/header.html', url= request.url, 
                                                    WhiteLabel=g.whitelabel_info, 
                                                    avatar_url=session.get('avatar'), 
                                                    rolle=session.get('rolle'), 
                                                    name=session.get('name'), Nutzer_Punkte=session.get('Nutzer_Punkte'))
        sidebar = await render_template('/parts/Elemente/sidebar.html', 
                                        WhiteLabel=g.whitelabel_info, rolle=session.get('rolle'))
        footer = await render_template('/parts/Elemente/footer.html', WhiteLabel = g.whitelabel_info, Session_Info=g.Session_Info['LogEntry_ID'], nutzername=session.get('username'), nutzer_ID=session.get('id'))

        theme_customizer = await render_template('/parts/Elemente/theme-customizer.html', 
                                                WhiteLabel=g.whitelabel_info)

        whitelabel_details = []

        # Die Items von der Collection "WhiteLabel" abrufen
        try:
            data = client.get_items("WhiteLabel")

            print(data)
            if 'error' in data:
                whitelabel_details = []
                print(f"Fehler: {data['error']}")
            else:
                if data:  # Überprüfen, ob Daten vorhanden sind
                    whitelabel_details = data  # Speichere die Whitelabel-Informationen in g
                    print(f"WhiteLabel-Details: {whitelabel_details}")
                else:
                    whitelabel_details = []
                    print(f"Fehler beim Abruf der Nutzer.")
        except Exception as e:
            print(f"Fehler beim Abrufen der Daten: {e}")


        
        request_directus = {
            "query": {
                "filter": {
                    "Referrer": {
                        "_eq": session.get('id')
                    }
                }
            }
        }

        # Die Items von der Collection "WhiteLabel" abrufen
        try:
            data = client.get_items("Nutzer", request_directus)

            print(data)
            if 'error' in data:
                nutzer_details = []
                print(f"Fehler: {data['error']}")
            else:
                if data:  # Überprüfen, ob Daten vorhanden sind
                    nutzer_details = data  # Speichere die Whitelabel-Informationen in g
                    print(f"Nutzer-Details: {nutzer_details}")
                else:
                    nutzer_details = []
                    print(f"Fehler beim Abruf der Nutzer.")
        except Exception as e:
            print(f"Fehler beim Abrufen der Daten: {e}")


        

        # Die Items von der Collection "WhiteLabel" abrufen
        try:
            rollen_data = client.get_items("Nutzer_Rollen")

            print(data)
            if 'error' in rollen_data:
                rollen_details = []
                print(f"Fehler: {data['error']}")
            else:
                if rollen_data:  # Überprüfen, ob Daten vorhanden sind
                    rollen_details = rollen_data  # Speichere die Whitelabel-Informationen in g
                    print(f"Rollen-Details: {rollen_details}")
                else:
                    rollen_details = []
                    print(f"Fehler beim Abruf der Nutzer.")
        except Exception as e:
            print(f"Fehler beim Abrufen der Daten: {e}")

        print(session.get('id'))
        
        # Rendern der Vorschau-HTML-Vorlage mit den erhaltenen Parametern
        return await render_template(f'/parts/Seiten/Admin-Bereich/Benutzer-Uebersicht.html', 
                                    header=header,
                                    error=error, 
                                    success=success, 
                                    sidebar=sidebar, 
                                    footer=footer, 
                                    theme_customizer=theme_customizer,
                                    username=session.get('username'), 
                                    rolle=session.get('rolle'), 
                                    name=session.get('name'), 
                                    avatar_url=session.get('avatar'), 
                                    WhiteLabel=g.whitelabel_info,
                                    nutzer_liste=nutzer_details,
                                    whitelabels=whitelabel_details,
                                    rollen_liste=rollen_details)
    
    else:
        session['error'] = "Auf diese Seite haben nur Super- bzw. Lower-Admins oder deren Vertretung Zugriff."
        return redirect(f"https://dashboard.{session.get('WhiteLabel')['Domain']}/")


@app.route('/admin/benutzer/erstellen', methods=['POST'])
async def Benutzer_Erstellen():
    data = await request.form
    files = await request.files

    rolle = data.get('rolle')
    
    rechte = client.get_item('Nutzer_Rollen', int(rolle))
    
    WhiteLabel_Details = {}
    # White-Label wenn nötig anlegen
    try:
        if data.get('whitelabel_create') == "kein":
            WhiteLabel_Details = {
                "Typ": "Kein"
            }
        elif data.get('whitelabel_create') == "bestehend":
            WhiteLabel_Details = {
                "Typ": "Bestehend",
                "ID": data.get('whitelabel-select')
            }
        elif data.get('whitelabel_create') == "neu":
            WhiteLabel_Details = {
                "Typ": "Neu",
                "Domain": f"{data.get('domain')}.personalpeak360.de",
                "Bezeichnung": data.get('name'),
                "Farbe_Primary": data.get('primary'),
                "Farbe_Secondary": data.get('secondary'),
                "Farbe_Third": data.get('third')
            }

            # Bilder müssen im Anschluss richtig hochgeladen werden bzw. in Bytes umgewandelt werden um verarbeitet zu werden
    except:
        pass
    
    if WhiteLabel_Details['Typ'] == "Kein":
        item_data = {
            'Vorname': data.get('vorname'),
            'Nachname': data.get('nachname'),
            'Benutzername': data.get('benutzername'),
            'Passwort': data.get('passwort'),
            'Rolle_RECHTE': {"key": int(data.get('rolle')),"collection":"Nutzer_Rollen"},
            'Referrer': session.get('id'),
            'RECHTE': rechte['Rechte']
        }
        new_item = client.create_item(collection_name='Nutzer', item_data=item_data)

    elif WhiteLabel_Details['Typ'] == "Bestehend":
        item_data = {
            'Vorname': data.get('vorname'),
            'Nachname': data.get('nachname'),
            'Benutzername': data.get('benutzername'),
            'Passwort': data.get('passwort'),
            'WhiteLabel': {"key": int(WhiteLabel_Details['ID']),"collection":"WhiteLabel"},
            'Rolle_RECHTE': {"key": int(data.get('rolle')),"collection":"Nutzer_Rollen"},
            'Referrer': session.get('id'),
            'RECHTE': rechte['Rechte']
        }
        new_item = client.create_item(collection_name='Nutzer', item_data=item_data)

    elif WhiteLabel_Details['Typ'] == "Neu":
        # Hilfsfunktion zum temporären Speichern der Datei
        async def save_temp_file(file_storage):
            # Erstelle eine temporäre Datei
            temp_file = tempfile.NamedTemporaryFile(delete=False)
            try:
                # Schreibe den Inhalt der hochgeladenen Datei in die temporäre Datei
                temp_file.write(file_storage.read())
                temp_file.close()  # Schließe die Datei
                return temp_file.name  # Gibt den Pfad zur temporären Datei zurück
            except Exception as e:
                temp_file.close()
                os.remove(temp_file.name)  # Lösche die temporäre Datei im Fehlerfall
                raise e
            
        # Standard-Werte für Logos (PP360-Logos)
        logoLang_file_id = ""
        logoKurz_file_id = ""
        logoIcon_file_id = ""
        Favicon_file_id = ""

        if 'logo_lang' in files:
            new_file_storage = files['logo_lang']
            temp_file_path = await save_temp_file(new_file_storage)  # Speichere die Datei temporär

            # Neue Datei hochladen
            upload_data = {
                "title": new_file_storage.filename,
                "description": "Langes Logo",
                "tags": ["logo", "lange version"],
                "type": new_file_storage.content_type  # MIME-Typ hinzufügen
            }
            uploaded_file = client.upload_file(temp_file_path, upload_data)
            logoLang_file_id = uploaded_file['id']  # Neuen File-ID speichern

            # Lösche die temporäre Datei
            os.remove(temp_file_path)

        if 'logo_kurz' in files:
            new_file_storage = files['logo_kurz']
            temp_file_path = await save_temp_file(new_file_storage)  # Speichere die Datei temporär

            # Neue Datei hochladen
            upload_data = {
                "title": new_file_storage.filename,
                "description": "Kurzes Logo",
                "tags": ["logo", "kurze version"],
                "type": new_file_storage.content_type  # MIME-Typ hinzufügen
            }
            uploaded_file = client.upload_file(temp_file_path, upload_data)
            logoKurz_file_id = uploaded_file['id']  # Neuen File-ID speichern

            # Lösche die temporäre Datei
            os.remove(temp_file_path)

        if 'logo_icon' in files:
            new_file_storage = files['logo_icon']
            temp_file_path = await save_temp_file(new_file_storage)  # Speichere die Datei temporär

            # Neue Datei hochladen
            upload_data = {
                "title": new_file_storage.filename,
                "description": "Icon Logo",
                "tags": ["logo", "icon version"],
                "type": new_file_storage.content_type  # MIME-Typ hinzufügen
            }
            uploaded_file = client.upload_file(temp_file_path, upload_data)
            logoIcon_file_id = uploaded_file['id']  # Neuen File-ID speichern

            # Lösche die temporäre Datei
            os.remove(temp_file_path)

        if 'favicon' in files:
            new_file_storage = files['favicon']
            temp_file_path = await save_temp_file(new_file_storage)  # Speichere die Datei temporär

            # Neue Datei hochladen
            upload_data = {
                "title": new_file_storage.filename,
                "description": "Favicon",
                "tags": ["logo", "favicon"],
                "type": new_file_storage.content_type  # MIME-Typ hinzufügen
            }
            uploaded_file = client.upload_file(temp_file_path, upload_data)
            Favicon_file_id = uploaded_file['id']  # Neuen File-ID speichern

            # Lösche die temporäre Datei
            os.remove(temp_file_path)

        item_data = {
            'Domain': WhiteLabel_Details['Domain'],
            'Bezeichnung': WhiteLabel_Details['Bezeichnung'],
            'Primary': WhiteLabel_Details['Farbe_Primary'],
            'Secondary': WhiteLabel_Details['Farbe_Secondary'],
            'Third': WhiteLabel_Details['Farbe_Third'],

            "Logo_lang": f"{logoLang_file_id}",
            "Logo_kurz": f"{logoKurz_file_id}",
            "Logo_Icon": f"{logoIcon_file_id}",
            "Favicon": f"{Favicon_file_id}"
        }
        new_WhiteLabel = client.create_item(collection_name='WhiteLabel', item_data=item_data)
        print(new_WhiteLabel)

        item_data = {
            'Vorname': data.get('vorname'),
            'Nachname': data.get('nachname'),
            'Benutzername': data.get('benutzername'),
            'Passwort': data.get('passwort'),
            'WhiteLabel': {"key": int(new_WhiteLabel['data']['id']),"collection":"WhiteLabel"},
            'Rolle_RECHTE': {"key": int(data.get('rolle')),"collection":"Nutzer_Rollen"},
            'Referrer': session.get('id'),
            'RECHTE': rechte['Rechte']
        }


        new_item = client.create_item(collection_name='Nutzer', item_data=item_data)

    session['success'] = f"Der Nutzer '{data.get('benutzername')}' wurde erfolgreich angelegt."
    return redirect(f"https://dashboard.{session.get('WhiteLabel')['Domain']}/admin/benutzer/%C3%BCbersicht")

@app.template_filter('format_date')
def format_date(value, format="%d.%m.%Y"):
    if isinstance(value, str):
        try:
            date_value = datetime.strptime(value, "%Y-%m-%d")
            return date_value.strftime(format)
        except ValueError:
            return value  # Im Fehlerfall den Originalwert zurückgeben
    return value  # Im Fehlerfall den Originalwert zurückgeben

@app.template_filter('to_float')
def to_float(value):
    try:
        return f"{float(value):.2f}".replace('.', ',')
    except (ValueError, TypeError):
        return "0,00"  # Rückgabe bei Fehler
    
import calendar


# Benutzerdefinierter Filter
@app.template_filter('add_days')
def add_days_filter(value, days):
    try:
        # Umwandlung in datetime
        date_obj = datetime.fromisoformat(value)
        # Hinzufügen der Tage
        new_date = date_obj + timedelta(days=days)
        return new_date.isoformat()
    except Exception:
        return value  # Rückgabe des Originalwerts, falls ein Fehler auftritt

app.jinja_env.filters['add_days'] = add_days_filter


@app.route('/admin/benutzer/<aktion>/<id>', methods=['GET', 'POST'])
async def Benutzer_Aktionen(aktion, id):
    success = session.pop('success', None)
    punkte = session.pop('Punkte_Nachricht', None)
    punkte_nachricht = punkte
    error = session.pop('error', None)

    request_directus = {
        "query": {
            "filter": {
                "Referrer": {
                    "_eq": session.get('id')
                }
            }
        }
    }
    data = []

    # Die Items von der Collection "WhiteLabel" abrufen
    try:
        data = client.get_items("Nutzer")

        print(data)
        if 'error' in data:
            nutzer_details = []
            print(f"Fehler: {data['error']}")
        else:
            if data:  # Überprüfen, ob Daten vorhanden sind
                nutzer_details = data  # Speichere die Whitelabel-Informationen in g
                print(f"Nutzer-Details: {nutzer_details}")
            else:
                nutzer_details = []
                print(f"Fehler beim Abruf der Nutzer.")
    except Exception as e:
        print(f"Fehler beim Abrufen der Daten: {e}")

    nutzer_details = {}
    refferer_rights = False
    for nutzer in data:
        if nutzer['id'] == int(id) and nutzer['Referrer'] == session.get('id'):
            refferer_rights = True
            nutzer_details = nutzer
        if nutzer['id'] == int(id) and nutzer['id'] == int(session.get('id')):
            refferer_rights = True
            nutzer_details = nutzer
    
    if refferer_rights == True:
        if aktion == "delete":
            client.delete_item(collection_name='Nutzer', item_id=nutzer_details['id'])
            
            session['success'] = f"Der Nutzer '{nutzer_details['Benutzername']}' wurde erfolgreich gelöscht."
            return redirect(f'https://dashboard.{session.get('WhiteLabel')['Domain']}/admin/benutzer/übersicht')
        elif aktion == "details":
            # Abruf der Informationen des Referrers
            request_directus = {
                "query": {
                    "filter": {
                        "id": {
                            "_eq": nutzer_details['Referrer']
                        }
                    }
                }
            }
            data = []

            # Die Items von der Collection "WhiteLabel" abrufen
            try:
                data = client.get_items("Nutzer", request_directus)

                print(data)
                if 'error' in data:
                    referrer_details = []
                    print(f"Fehler: {data['error']}")
                else:
                    if data:  # Überprüfen, ob Daten vorhanden sind
                        referrer_details = data[0]  # Speichere die Whitelabel-Informationen in g
                        print(f"Referrer-Details: {referrer_details}")
                    else:
                        referrer_details = []
                        print(f"Fehler beim Abruf des Referrers.")
            except Exception as e:
                print(f"Fehler beim Abrufen der Daten: {e}")

            data_Rolle = {}
            try:
                data_Rolle = client.get_item("Nutzer_Rollen", nutzer_details['Rolle_RECHTE']['key'])

                print(data)
                if 'error' in data_Rolle:
                    data_Rolle = {}
                    print(f"Fehler: {data['error']}")
                else:
                    if data:  # Überprüfen, ob Daten vorhanden sind
                        data_Rolle = data_Rolle  # Speichere die Whitelabel-Informationen in g
                        print(f"Referrer-Details: {data_Rolle}")
                    else:
                        data_Rolle = {}
                        print(f"Fehler beim Abruf des Referrers.")
            except Exception as e:
                print(f"Fehler beim Abrufen der Daten: {e}")

            
            request_directus = {
                "query": {
                    "filter": {
                        "Nutzer_ID": {
                            "_eq": nutzer_details['id']
                        }
                    },
                    "limit": 2000,
                    "sort": "-Zeitstempel"  # 'Zeitstempel' durch das entsprechende Zeitfeld ersetzen
                }
            }

            Statistik_data = []
            Statistik_response = []

            try:
                Statistik_response = client.get_items("Nutzer_Statistik", request_directus)

                print(Statistik_response)
                if 'error' in Statistik_response:
                    Statistik_data = []
                    print(f"Fehler: {Statistik_response['error']}")
                else:
                    if Statistik_response:  # Überprüfen, ob Daten vorhanden sind
                        Statistik_data = Statistik_response  # Speichere die Whitelabel-Informationen in g
                        print(f"Nutzer-Statistik: {Statistik_data}")
                    else:
                        Statistik_data = []
                        print(f"Fehler beim Abruf der Nutzer-Statistik.")
            except Exception as e:
                print(f"Fehler beim Abrufen der Daten: {e}")

            print(Statistik_data)

            # Umwandeln in ein datetime-Objekt
            erstellungsdatum = datetime.fromisoformat(nutzer_details['Erstellung'])

            # Formatieren in das gewünschte Format
            formatiertes_datum = erstellungsdatum.strftime("%d.%m.%Y um %H:%M Uhr")

            nutzer_details['Erstellung'] = formatiertes_datum


            today = datetime.now().date()
            yesterday = today - timedelta(days=1)
            last_7_days_start = today - timedelta(days=7)
            # Liste der Daten generieren
            last_7_days_date_list = [(last_7_days_start + timedelta(days=i)).isoformat() for i in range((today - last_7_days_start).days + 1)]
            # Start des Monats
            this_month_start = today.replace(day=1)
            # Letzter Tag des Monats ermitteln
            days_in_month = calendar.monthrange(today.year, today.month)[1]
            this_month_end = today.replace(day=days_in_month)
            # Liste der Daten vom Monatsanfang bis zum Monatsende generieren
            date_list_this_month = [(this_month_start + timedelta(days=i)).isoformat() for i in range((this_month_end - this_month_start).days + 1)]

            today_seconds = await fetch_data({"_eq": today.isoformat()}, nutzer_details['id'])
            yesterday_seconds = await fetch_data({"_eq": yesterday.isoformat()}, nutzer_details['id'])
            last_7_days_seconds = await fetch_data({"_in": last_7_days_date_list}, nutzer_details['id'])
            this_month_seconds = await fetch_data({"_in": date_list_this_month}, nutzer_details['id'])

            def parse_verweil_dauer(item):
                # Versuche, den Wert zu einer Zahl (float) zu konvertieren, ansonsten setze ihn auf 0
                try:
                    return int(float(item.get("Verweil_Dauer", 0) or 0))  # float für Dezimalzahlen, dann zu int
                except (ValueError, TypeError):
                    return 0

            def convert_seconds(seconds):
                """Konvertiert Sekunden in eine lesbare Einheit."""
                if seconds < 60:
                    return {"value": float(seconds), "unit": "Sekunden"}
                elif seconds < 3600:
                    return {"value": float(seconds / 60), "unit": "Minuten"}
                else:
                    return {"value": float(seconds / 3600), "unit": "Stunden"}

            statistics = {
                "heute online": convert_seconds(sum(parse_verweil_dauer(item) for item in today_seconds)),
                "gestern online": convert_seconds(sum(parse_verweil_dauer(item) for item in yesterday_seconds)),
                "letzten 7 Tagen online": convert_seconds(sum(parse_verweil_dauer(item) for item in last_7_days_seconds)),
                "diesen Monat online": convert_seconds(sum(parse_verweil_dauer(item) for item in this_month_seconds)),
            }
            
            from urllib.parse import urlparse

            liste = []
            for item in Statistik_data:
                # URL aufteilen und den Domain-Teil extrahieren
                url = item['Daten']['URL'].split('//')[-1]  # Entferne das Protokoll (http:// oder https://)

                # Den Domain-Teil isolieren, indem alles nach dem ersten '/' entfernt wird
                subdomain = url.split('/')[0]  # Entfernt alles nach dem ersten '/'

                # Extrahiere nur den Hostnamen (alle Teile ab dem zweiten Punkt)
                hostname = '.'.join(subdomain.split('.')[1:])  # Entferne den ersten Teil (Subdomain)

                # Überprüfen, ob der Hostname bereits in der Liste ist
                if not any(hostname in d for d in liste):
                    liste.append({f"{hostname}": {}})

            # Gehe durch die Liste der verbleibenden Hostnamen und rufe die Whitelabel-Informationen ab
            for entry in liste:
                for hostname in entry:
                    # Erstelle die Anfrage an Directus
                    request_directus = {
                        "query": {
                            "filter": {
                                "Domain": {
                                    "_eq": hostname  # Filter für die Domain
                                }
                            }
                        }
                    }

                    # Die Items von der Collection "WhiteLabel" abrufen
                    try:
                        data = client.get_items("WhiteLabel", request_directus)

                        if 'error' in data:
                            print(f"Fehler: {data['error']}")
                            entry[hostname] = None  # Keine Info bei Fehler
                        else:
                            if data:  # Überprüfen, ob Daten vorhanden sind
                                entry[hostname] = data[0]  # Daten an den Hostnamen anhängen
                                print(f"WhiteLabel-Info für {hostname}: {data[0]}")
                            else:
                                entry[hostname] = None  # Keine Daten vorhanden
                                print(f"Keine WhiteLabel-Informationen für {hostname} gefunden.")
                    except Exception as e:
                        print(f"Fehler beim Abrufen der Daten: {e}")
                        entry[hostname] = None  # Keine Info bei Ausnahme

            # Ausgabe der Liste mit den angehängten Whitelabel-Infos
            print(liste)


            request_directus = {
                "query": {
                    "filter": {
                        "Nutzer": {
                            "id": {
                                "_eq": int(nutzer_details['id'])
                            }
                        }
                    }
                }
            }
            Test_Verlauf = client.get_items("FitnessTest_ERGEBNISSE", request_directus)


            header = await render_template('/parts/Elemente/header.html', url= request.url, 
                                                        WhiteLabel=g.whitelabel_info, 
                                                        avatar_url=session.get('avatar'), 
                                                        rolle=session.get('rolle'), 
                                                        name=session.get('name'), Nutzer_Punkte=session.get('Nutzer_Punkte'))
            sidebar = await render_template('/parts/Elemente/sidebar.html', 
                                            WhiteLabel=g.whitelabel_info, rolle=session.get('rolle'), selected_NUTZER=nutzer_details)
            footer = await render_template('/parts/Elemente/footer.html', WhiteLabel = g.whitelabel_info, Session_Info=g.Session_Info['LogEntry_ID'], nutzername=session.get('username'), nutzer_ID=session.get('id'))

            theme_customizer = await render_template('/parts/Elemente/theme-customizer.html', 
                                                    WhiteLabel=g.whitelabel_info)
            

            # Rendern der Vorschau-HTML-Vorlage mit den erhaltenen Parametern
            return await render_template(f'/parts/Seiten/Admin-Bereich/Benutzer-Details.html', 
                                        header=header, 
                                        sidebar=sidebar, 
                                        footer=footer, 
                                        error=error,
                                        success=success,
                                        theme_customizer=theme_customizer,
                                        username=session.get('username'), 
                                        rolle=session.get('rolle'), 
                                        name=session.get('name'), 
                                        avatar_url=session.get('avatar'), 
                                        WhiteLabel=g.whitelabel_info,
                                        nutzer=nutzer_details,
                                        referrer=referrer_details,
                                        statistik_data=Statistik_response,
                                        online_Statistik=statistics,
                                        WhiteLabel_Liste=liste,
                                        Rollen_Info=data_Rolle,
                                        Test_Verlauf=Test_Verlauf)
        elif aktion == "update_badge":
            data = await request.form
            neue_medaille = data.get('badge')

            updated_item = client.update_item(collection_name='Nutzer', item_id=f'{id}', item_data={'Nutzer_Level': f'{neue_medaille}'})

            session['success'] = f"Die Stufe bzw. Medaille wurde geändert."
            return redirect(f'https://dashboard.{g.whitelabel_info['Domain']}/admin/benutzer/details/{id}')
        elif aktion == "update_EinstiegsFragebogen_Status":
            modus = request.args.get('modus') # OB Fitness-Test aktiviert oder deaktiviert werden soll

            # Modus in einen booleschen Wert umwandeln
            if modus is not None:
                if modus.lower() in ['true', '1', 'yes']:
                    modus_aktiviert = True
                    modus_text = "aktiviert"
                elif modus.lower() in ['false', '0', 'no']:
                    modus_aktiviert = ""
                    modus_text = "deaktiviert"
                else:
                    modus_aktiviert = None  # Ungültiger Wert
                    modus_text = "None"
            else:
                modus_aktiviert = None  # Kein Modus angegeben

            updated_item = client.update_item(collection_name='Nutzer', item_id=f'{id}', item_data={'Einstiegs_Fragebogen': f'{modus_aktiviert}'})

            session['success'] = f"Der Einstiegs-Fragebogen wurde {modus_text}."
            return redirect(f'https://dashboard.{g.whitelabel_info['Domain']}/admin/benutzer/details/{id}')
        elif aktion == "update_FitnessTest_Status":
            modus = request.args.get('modus') # OB Fitness-Test aktiviert oder deaktiviert werden soll

            # Modus in einen booleschen Wert umwandeln
            if modus is not None:
                if modus.lower() in ['true', '1', 'yes']:
                    modus_aktiviert = True
                    modus_text = "aktiviert"
                elif modus.lower() in ['false', '0', 'no']:
                    modus_aktiviert = ""
                    modus_text = "deaktiviert"
                else:
                    modus_aktiviert = None  # Ungültiger Wert
                    modus_text = "None"
            else:
                modus_aktiviert = None  # Kein Modus angegeben

            updated_item = client.update_item(collection_name='Nutzer', item_id=f'{id}', item_data={'Fitness_Test': f'{modus_aktiviert}'})

            session['success'] = f"Der Fitness-Test wurde {modus_text}."
            return redirect(f'https://dashboard.{g.whitelabel_info['Domain']}/admin/benutzer/details/{id}')
        else:
            session['error'] = f"Die Aktion war ungültig für '#{id}'."
            return redirect(f'https://dashboard.{g.whitelabel_info['Domain']}/admin/benutzer/übersicht')
    else:
        return jsonify({'Error': "Dem Nutzer fehlen die Berechtigungen!", "Aktion": aktion})

@app.route('/admin/kanban', methods=['GET', 'POST'])
async def Admin_Kanban():
    if request.method == "POST":
        data = await request.form
        Tabs = data.getlist('tabs[]')

        boards = []

        for tab in Tabs:
            boards.append({
                "id": f"{tab}",
                "title": f"{tab}",
                "item": []
            },)

        new_kanban = client.create_item("KanbanBoards", {
            "Boards": boards,
            "Nutzer_ID": [f"{session.get('id')}"],
            "Nutzer_ID_ERSTELLER": {'key': session.get('id'), 'collection': 'Nutzer'},
            "Name": data.get('name')
        })

        print(new_kanban)

        session['success'] = "Dein Kanban-Board wurde erstellt."
        return redirect(f"https://dashboard.{g.whitelabel_info['Domain']}/admin/kanban/{new_kanban['data']['id']}")
    else:
        success = session.pop('success', None)
        punkte = session.pop('Punkte_Nachricht', None)
        punkte_nachricht = punkte
        error = session.pop('error', None)

        header = await render_template('/parts/Elemente/header.html', url= request.url, 
                                                    WhiteLabel=g.whitelabel_info, 
                                                    avatar_url=session.get('avatar'), 
                                                    rolle=session.get('rolle'), 
                                                    name=session.get('name'), Nutzer_Punkte=session.get('Nutzer_Punkte'))
        sidebar = await render_template('/parts/Elemente/sidebar.html', 
                                        WhiteLabel=g.whitelabel_info, rolle=session.get('rolle'))
        footer = await render_template('/parts/Elemente/footer.html', WhiteLabel = g.whitelabel_info, Session_Info=g.Session_Info['LogEntry_ID'], nutzername=session.get('username'), nutzer_ID=session.get('id'))

        theme_customizer = await render_template('/parts/Elemente/theme-customizer.html', 
                                                WhiteLabel=g.whitelabel_info)
        

        try:
            kanban_board = client.get_items("KanbanBoards")
        except AssertionError as e:
            session['error'] = "Das Kanban-Board wurde nicht gefunden."
            return redirect(f"https://dashboard.{g.whitelabel_info['Domain']}/admin/kanban")

        boards_liste = []
        for board in kanban_board:
            if str(session.get('id')) in board['Nutzer_ID']:
                boards_liste.append(board)


        
        # Rendern der Vorschau-HTML-Vorlage mit den erhaltenen Parametern
        return await render_template(f'/parts/Seiten/Admin-Bereich/Kanban-Board.html', 
                                    header=header,
                                    error=error, 
                                    success=success, 
                                    sidebar=sidebar, 
                                    footer=footer, 
                                    theme_customizer=theme_customizer,
                                    username=session.get('username'), 
                                    rolle=session.get('rolle'), 
                                    name=session.get('name'), 
                                    avatar_url=session.get('avatar'), 
                                    WhiteLabel=g.whitelabel_info,
                                    Kanban_Boards = boards_liste)


@app.route('/admin/kanban/<ID>', methods=['GET'])
async def Admin_Kanban_DETAILS(ID):
    success = session.pop('success', None)
    punkte = session.pop('Punkte_Nachricht', None)
    punkte_nachricht = punkte
    error = session.pop('error', None)

    header = await render_template('/parts/Elemente/header.html', url= request.url, 
                                                WhiteLabel=g.whitelabel_info, 
                                                avatar_url=session.get('avatar'), 
                                                rolle=session.get('rolle'), 
                                                name=session.get('name'), Nutzer_Punkte=session.get('Nutzer_Punkte'))
    sidebar = await render_template('/parts/Elemente/sidebar.html', 
                                    WhiteLabel=g.whitelabel_info, rolle=session.get('rolle'))
    footer = await render_template('/parts/Elemente/footer.html', WhiteLabel = g.whitelabel_info, Session_Info=g.Session_Info['LogEntry_ID'], nutzername=session.get('username'), nutzer_ID=session.get('id'))

    theme_customizer = await render_template('/parts/Elemente/theme-customizer.html', 
                                            WhiteLabel=g.whitelabel_info)
    
    
    query = {
        "query": {
            "filter": {
                "Nutzer_ID": {
                    "_contains": str(session.get('id'))
                }
            },
            "limit": 1
        }
    }

    try:
        kanban_board = client.get_item("KanbanBoards", ID, query)
    except AssertionError as e:
        session['error'] = "Das Kanban-Board wurde nicht gefunden."
        return redirect(f"https://dashboard.{g.whitelabel_info['Domain']}/admin/kanban")

    found = False
    for nutzer in kanban_board.get('Nutzer_ID', []):
        if nutzer == str(session.get('id')):
            found = True

    nutzer_liste = []
    for nutzer in kanban_board.get('Nutzer_ID', []):
        nutzer_details = client.get_item("Nutzer", int(nutzer))

        nutzer_liste.append(
            nutzer_details
        )

    if kanban_board and found:
        # Das Kanban-Board existiert und gehört dem Nutzer; hier weitere Verarbeitung
        pass
    else:
        session['error'] = "Das Kanban-Board wurde nicht gefunden oder Du hast keinen Zugriff."
        return redirect(f"https://dashboard.{g.whitelabel_info['Domain']}/admin/kanban")
    
    
    # Rendern der Vorschau-HTML-Vorlage mit den erhaltenen Parametern
    return await render_template(f'/parts/Seiten/Admin-Bereich/Kanban-Board_DETAILS.html', 
                                header=header,
                                error=error, 
                                success=success, 
                                sidebar=sidebar, 
                                footer=footer, 
                                theme_customizer=theme_customizer,
                                username=session.get('username'), 
                                rolle=session.get('rolle'), 
                                name=session.get('name'), 
                                avatar_url=session.get('avatar'), 
                                WhiteLabel=g.whitelabel_info,
                                Kanban_Board = kanban_board,
                                Nutzer_ID = int(session.get('id')),
                                Nutzer_Liste = nutzer_liste)


import uuid

@app.route('/admin/kanban/<ID>/GenerateLink', methods=['GET'])
async def Admin_Kanban_EINLADUNG(ID):
    UUID = str(uuid.uuid4())

    query = {
        "query": {
            "filter": {
                "Nutzer_ID": {
                    "_contains": str(session.get('id'))
                }
            },
            "limit": 1
        }
    }

    try:
        kanban_board = client.get_item("KanbanBoards", ID, query)
    except AssertionError as e:
        session['error'] = "Das Kanban-Board wurde nicht gefunden."
        return redirect(f"https://dashboard.{g.whitelabel_info['Domain']}/admin/kanban")

    found = False
    for nutzer in kanban_board.get('Nutzer_ID', []):
        if nutzer == str(session.get('id')):
            found = True

    if kanban_board and found:
        # Das Kanban-Board existiert und gehört dem Nutzer; hier weitere Verarbeitung
        pass
    else:
        session['error'] = "Das Kanban-Board wurde nicht gefunden oder Du hast keinen Zugriff."
        return redirect(f"https://dashboard.{g.whitelabel_info['Domain']}/admin/kanban")

    Tokens_Liste = []

    if kanban_board['Tokens']:
        for token in kanban_board['Tokens']:
            Tokens_Liste.append(token)
    
    Tokens_Liste.append(UUID)

    client.update_item("KanbanBoards", ID, {"Tokens": Tokens_Liste})

    return jsonify({'link': f'https://dashboard.{g.whitelabel_info['Domain']}/admin/kanban/join/{UUID}'})


@app.route('/admin/kanban/join/<TOKEN>', methods=['GET'])
async def Admin_Kanban_JOIN(TOKEN):
    try:
        kanban_board = client.get_items("KanbanBoards")
    except AssertionError as e:
        session['error'] = "Das Kanban-Board wurde nicht gefunden."
        return redirect(f"https://dashboard.{g.whitelabel_info['Domain']}/admin/kanban")

    found = False

    for board in kanban_board:
        if TOKEN in board['Tokens']:
            board_Details = board
            found = True
            break

    if kanban_board and found:
        # Das Kanban-Board existiert und gehört dem Nutzer; hier weitere Verarbeitung
        pass
    else:
        session['error'] = "Das Kanban-Board wurde nicht gefunden oder Du hast keinen Zugriff."
        return redirect(f"https://dashboard.{g.whitelabel_info['Domain']}/admin/kanban")

    Tokens_Liste = []

    for token in board['Tokens']:
        if TOKEN != token:
            Tokens_Liste.append(token)

    nutzer_liste = []
    for nutzer in board['Nutzer_ID']:
        if nutzer != f"{session.get('id')}":
            nutzer_liste.append(nutzer)
        else:
            session['error'] = "Du hast bereits Zugriff auf das Kanban-Board."
            return redirect(f"https://dashboard.{g.whitelabel_info['Domain']}/admin/kanban/{board_Details['id']}")

    nutzer_liste.append(f"{session.get('id')}")
    
    client.update_item("KanbanBoards", board_Details['id'], {"Tokens": Tokens_Liste, "Nutzer_ID": nutzer_liste})

    session['success'] = f"Du bist erfolgreich den Kanban-Board '{board_Details['Name']}' beigetreten."
    return redirect(f"https://dashboard.{g.whitelabel_info['Domain']}/admin/kanban/{board_Details['id']}")


@app.route('/admin/kanban/delete-join-token/<TOKEN>', methods=['GET'])
async def Admin_Kanban_DELETE_JOIN_TOKEN(TOKEN):
    try:
        kanban_board = client.get_items("KanbanBoards")
    except AssertionError as e:
        session['error'] = "Das Kanban-Board wurde nicht gefunden."
        return redirect(f"https://dashboard.{g.whitelabel_info['Domain']}/admin/kanban")

    found = False

    found_token = ""
    for board in kanban_board:
        if TOKEN in board['Tokens']:
            board_Details = board
            found = True
            found_token = TOKEN
            break

    if kanban_board and found:
        # Das Kanban-Board existiert und gehört dem Nutzer; hier weitere Verarbeitung
        pass
    else:
        session['error'] = "Das Kanban-Board wurde nicht gefunden oder Du hast keinen Zugriff."
        return redirect(f"https://dashboard.{g.whitelabel_info['Domain']}/admin/kanban")

    Tokens_Liste = []

    for token in board['Tokens']:
        if TOKEN != token:
            Tokens_Liste.append(token)


    client.update_item("KanbanBoards", board_Details['id'], {"Tokens": Tokens_Liste})

    session['success'] = f"Du hast erfolgreich den Einladungslink mit dem Token '{found_token}' gelöscht."
    return redirect(f"https://dashboard.{g.whitelabel_info['Domain']}/admin/kanban/{board_Details['id']}")


@app.route('/admin/kanban/update/<ID>', methods=['POST'])
async def Admin_Kanban_UPDATE(ID):
    exportierte_Daten = await request.get_json()
    client.update_item("KanbanBoards", ID, {"Boards": exportierte_Daten})
    return jsonify({"Sucess": "Das Update war erfolgreich"})


import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

async def send_html_email(subject, recipient, email_body):
    # SMTP-Servereinstellungen
    smtp_server = config['EMail_Adresse']['info@personalpeak360.com']['Server']['SMTP']
    smtp_port = config['EMail_Adresse']['info@personalpeak360.com']['Port']['SMTP']  # oder 465 für SSL
    smtp_user = config['EMail_Adresse']['info@personalpeak360.com']['Benutzername']
    smtp_password = config['EMail_Adresse']['info@personalpeak360.com']['Passwort']

    # E-Mail zusammenstellen
    message = MIMEMultipart("alternative")
    message["From"] = smtp_user
    message["To"] = recipient
    message["Subject"] = subject
    # HTML-Inhalt hinzufügen
    html_part = MIMEText(email_body, "html")
    message.attach(html_part)

    # Verbindung zum SMTP-Server und Senden der E-Mail
    try:
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()  # TLS-Verbindung starten
            server.login(smtp_user, smtp_password)
            server.sendmail(smtp_user, recipient, message.as_string())
            print("E-Mail erfolgreich gesendet.")
    except Exception as e:
        print(f"Fehler beim Senden der E-Mail: {e}")

@app.route('/admin/buchhaltung/erstellen/<Typ>', methods=['POST'])
async def Buchhaltung_Erstellen(Typ):
    if session.get('WhiteLabel_Admin')['admin']:
        if Typ == "rechnung":
            data = await request.form

            # Einzelwerte abrufen
            kunde = data.get('Kunde')
            status = data.get('status')
            rechnungsdatum = data.get('rechnungsdatum')
            faelligkeitsdatum = data.get('fälligkeitsdatum')
            typ = data.get('typ')
            verlängerungsdatum = data.get('verlängerungsdatum') if typ == "Wiederkehrend" else ""

            # Listenwerte abrufen
            tabs = data.getlist('tabs[]')
            descriptions = data.getlist('descriptions[]')
            prices = data.getlist('prices[]')
            quantities = data.getlist('quantities[]')

            # Positionen erstellen, indem die Listen zusammengeführt werden
            positionen = [
                {
                    "Bezeichnung": tabs[i],
                    "Beschreibung": descriptions[i],
                    "Preis": float(prices[i]),
                    "Anzahl": int(quantities[i])
                }
                for i in range(len(tabs))
            ]

            # JSON-Datenstruktur
            form_data = {
                "Nutzer": {'key': int(kunde), 'collection': 'Nutzer'},
                "Status": status,
                "Rechnungsdatum": rechnungsdatum,
                "Faelligkeitsdatum": faelligkeitsdatum,
                "Items": positionen,
                "Typ": typ,
                "Verlaengerungsdatum": verlängerungsdatum,
                "WhiteLabel": {'key': int(g.whitelabel_info['id']), 'collection': 'WhiteLabel'}
            }

            new_rechnung = client.create_item('Rechnungen', item_data=form_data)

            ID = await calculate_Next_WL_InvoiceID(int(g.whitelabel_info['id'])) - 1

            nutzer = client.get_item('Nutzer', int(kunde))

            gesamtbetrag = 0.00
            # Berechnung des Gesamtbetrags
            for item in new_rechnung['data']['Items']:
                gesamtbetrag += float(item['Preis']) * int(item['Anzahl'])

            new_rechnung['data']['Preise'] = {}
            new_rechnung['data']['Preise']['Zwischensumme'] = gesamtbetrag
            
            # Annahme: Der Steuerbetrag ist in Prozent angegeben (z. B. 19%)
            steuersatz = 0
            if g.whitelabel_info['KleinunternehmerRegelung'] == False:
                steuersatz = 19
            
            # Berechnung des Steuerbetrags
            new_rechnung['data']['Preise']['Steuer'] = (steuersatz * gesamtbetrag) / 100

            # Berechnung des Gesamtbetrags
            new_rechnung['data']['Preise']['Gesamt'] = new_rechnung['data']['Preise']['Steuer'] + gesamtbetrag

            print(new_rechnung)

            emailTemplate = await render_template('/Email-Templates/rechnung.html', Nutzer = nutzer, Rechnung=new_rechnung['data'], Rechnung_ID = ID, WhiteLabel = g.whitelabel_info)
            await send_html_email("Neue Rechnung", nutzer['EMail'], emailTemplate)

            session['success'] = f"Die Rechnung #{ID} wurde erfolgreich angelegt."
            return redirect(f"https://dashboard.{g.whitelabel_info['Domain']}/admin/buchhaltung/übersicht/rechnungen")
        elif Typ == "angebot":
            data = await request.form

            # Einzelwerte abrufen
            kunde = data.get('Kunde')
            angebotsdatum = data.get('angebotsdatum')
            gueltigkeitsdatum = data.get('gueltigkeitsdatum')

            # Listenwerte abrufen
            tabs = data.getlist('tabs[]')
            descriptions = data.getlist('descriptions[]')
            prices = data.getlist('prices[]')
            quantities = data.getlist('quantities[]')

            # Positionen erstellen, indem die Listen zusammengeführt werden
            positionen = [
                {
                    "Bezeichnung": tabs[i],
                    "Beschreibung": descriptions[i],
                    "Preis": float(prices[i]),
                    "Anzahl": int(quantities[i])
                }
                for i in range(len(tabs))
            ]

            # JSON-Datenstruktur
            form_data = {
                "Nutzer": {'key': int(kunde), 'collection': 'Nutzer'},
                "Status": "Offen",
                "Angebotsdatum": angebotsdatum,
                "Gueltigkeitsdatum": gueltigkeitsdatum,
                "Items": positionen,
                "WhiteLabel": {'key': int(g.whitelabel_info['id']), 'collection': 'WhiteLabel'}
            }

            new_rechnung = client.create_item('Angebote', item_data=form_data)

            ID = await calculate_Next_WL_AngebotID(int(g.whitelabel_info['id'])) - 1

            nutzer = client.get_item('Nutzer', int(kunde))

            gesamtbetrag = 0.00
            # Berechnung des Gesamtbetrags
            for item in new_rechnung['data']['Items']:
                gesamtbetrag += float(item['Preis']) * int(item['Anzahl'])

            new_rechnung['data']['Preise'] = {}
            new_rechnung['data']['Preise']['Zwischensumme'] = gesamtbetrag
            
            # Annahme: Der Steuerbetrag ist in Prozent angegeben (z. B. 19%)
            steuersatz = 0
            if g.whitelabel_info['KleinunternehmerRegelung'] == False:
                steuersatz = 19
            
            # Berechnung des Steuerbetrags
            new_rechnung['data']['Preise']['Steuer'] = (steuersatz * gesamtbetrag) / 100

            # Berechnung des Gesamtbetrags
            new_rechnung['data']['Preise']['Gesamt'] = new_rechnung['data']['Preise']['Steuer'] + gesamtbetrag

            print(new_rechnung)

            emailTemplate = await render_template('/Email-Templates/angebot.html', Nutzer = nutzer, Rechnung=new_rechnung['data'], Rechnung_ID = ID, WhiteLabel = g.whitelabel_info)
            await send_html_email("Neues Angebot", nutzer['EMail'], emailTemplate)

            session['success'] = f"Das Angebot #{ID} wurde erfolgreich angelegt."
            return redirect(f"https://dashboard.{g.whitelabel_info['Domain']}/admin/buchhaltung/übersicht/angebote")
    else:
        session['error'] = "Auf diese Seite haben nur Super- bzw. Lower-Admins oder deren Vertretung Zugriff."
        return redirect(f"https://dashboard.{g.whitelabel_info['Domain']}")


@app.route('/admin/buchhaltung/übersicht/<Typ>', methods=['GET'])
async def Buchhaltung_Übersicht(Typ):
    print(session.get('WhiteLabel_Admin')['admin'])
    if session.get('WhiteLabel_Admin')['admin']:
        # Die Items von der Collection "Nutzer" abrufen
        try:
            data = client.get_items("Nutzer")

            print(data)
            if 'error' in data:
                nutzer_details = []
                print(f"Fehler: {data['error']}")
            else:
                if data:  # Überprüfen, ob Daten vorhanden sind
                    nutzer_details = data  # Speichere die Whitelabel-Informationen in g
                    print(f"Nutzer-Details: {nutzer_details}")
                else:
                    nutzer_details = []
                    print(f"Fehler beim Abruf der Nutzer.")
        except Exception as e:
            print(f"Fehler beim Abrufen der Daten: {e}")
            
        nutzer_ids = [nutzer['id'] for nutzer in data if nutzer['Referrer'] == session.get('id')] # Nutzer, für welche der Admin zuständig ist bzw. welche dieser angelegt hat
        nutzer_liste = [nutzer for nutzer in data if nutzer['Referrer'] == session.get('id')] # Nutzer, für welche der Admin zuständig ist bzw. welche dieser angelegt hat
        
        if Typ == "rechnungen":
            try:
                data = client.get_items("Rechnungen")
                if 'error' in data:
                    rechnungen = []
                    print(f"Fehler: {data['error']}")
                else:
                    # Filtern und eine Liste erstellen mit den passenden Rechnungen
                    rechnungen = [
                        rechnungs_item for rechnungs_item in data 
                        if rechnungs_item.get('WhiteLabel', {}).get('key') == int(session.get('WhiteLabel_Admin')['id'])
                    ]
                    
                    if not rechnungen:
                        print(f"Keine Rechnungen für das angegebene WhiteLabel (#{session.get('WhiteLabel_Admin')['id']}) gefunden.")
            except Exception as e:
                print(f"Fehler beim Abrufen der Daten: {e}")
            i = 0

            for rechnungs_item in rechnungen:
                i += 1
                rechnungs_item['WhiteLabel_RechnungsID'] = i

                if rechnungs_item['WhiteLabel']['key'] == int(session.get('WhiteLabel_Admin')['id']):
                    # Fälligkeitsdatum in ein Datum-Objekt umwandeln
                    faelligkeitsdatum = datetime.strptime(rechnungs_item['Faelligkeitsdatum'], "%Y-%m-%d").date()
                    
                    if rechnungs_item['Status'] != "Bezahlt":
                        # Überprüfung, ob die Rechnung überfällig ist
                        if faelligkeitsdatum < datetime.now().date():
                            rechnungs_item['Status'] = "Überfällig"

                    gesamtbetrag = 0.00
                    # Berechnung des Gesamtbetrags
                    for item in rechnungs_item['Items']:
                        gesamtbetrag += float(item['Preis']) * int(item['Anzahl'])

                    rechnungs_item['Preise'] = {}
                    rechnungs_item['Preise']['Zwischensumme'] = gesamtbetrag

                    rechnungs_item['WhiteLabel-Details'] = client.get_item("WhiteLabel", int(session.get('WhiteLabel_Admin')['id']))
                     
                    steuersatz = 0
                    if rechnungs_item['WhiteLabel-Details']['KleinunternehmerRegelung'] == False:
                        steuersatz = 19
                        # Berechnung des Steuerbetrags
                        rechnungs_item['Preise']['Steuer'] = (steuersatz * gesamtbetrag) / 100
                    else:
                        # Berechnung des Steuerbetrags
                        rechnungs_item['Preise']['Steuer'] = 0.00

                    # Berechnung des Gesamtbetrags
                    rechnungs_item['Preise']['Gesamt'] = rechnungs_item['Preise']['Steuer'] + gesamtbetrag

                    
                    # Nutzer-Details hinzufügen
                    for nutzer in nutzer_details:
                        if rechnungs_item['Nutzer']['key'] == nutzer['id']:
                            rechnungs_item['Nutzer-Details'] = nutzer
                            break  # Breche die innere Schleife ab, wenn der Nutzer gefunden wurde



            print(g.whitelabel_info)

            success = session.pop('success', None)
            punkte = session.pop('Punkte_Nachricht', None)
            punkte_nachricht = punkte
            error = session.pop('error', None)
            
            header = await render_template('/parts/Elemente/header.html', url= request.url, WhiteLabel = g.whitelabel_info, avatar_url=session.get('avatar'), rolle=session.get('rolle'), name=session.get('name'), Nutzer_Punkte=session.get('Nutzer_Punkte'))
            sidebar = await render_template('/parts/Elemente/sidebar.html', WhiteLabel = g.whitelabel_info, rolle=session.get('rolle'))
            footer = await render_template('/parts/Elemente/footer.html', WhiteLabel = g.whitelabel_info, Session_Info=g.Session_Info['LogEntry_ID'], nutzername=session.get('username'), nutzer_ID=session.get('id'))
            theme_customizer = await render_template('/parts/Elemente/theme-customizer.html', WhiteLabel = g.whitelabel_info)

            WhiteLabel_Admin_Content = client.get_item(collection_name='WhiteLabel', item_id=f'{session.get('WhiteLabel_Admin')['id']}')

            if WhiteLabel_Admin_Content['id'] != g.whitelabel_info['id']:
                session['error'] = f"Du hast leider keinen Zugriff auf die Buchhaltung der WhiteLabel-Instanz '{g.whitelabel_info['Bezeichnung']}'."
                return redirect(f"https://dashboard.{g.whitelabel_info['Domain']}")

            quickStart_TAB = request.args.get('quickstart')

            return await render_template('/parts/Seiten/Admin-Bereich/Buchhaltung/Übersicht_Rechnung.html', header=header, sidebar=sidebar, footer=footer, theme_customizer=theme_customizer, success=success, error=error, punkte = punkte, punkte_nachricht = punkte_nachricht, username=session.get('username'), rolle=session.get('rolle'), name=session.get('name'), avatar_url=session.get('avatar'), WhiteLabel = WhiteLabel_Admin_Content, quickStart_TAB=quickStart_TAB, rechnungs_liste=rechnungen, nutzer_liste=nutzer_liste)

        elif Typ == "angebote":
            try:
                data = client.get_items("Angebote")
                if 'error' in data:
                    rechnungen = []
                    print(f"Fehler: {data['error']}")
                else:
                    # Filtern und eine Liste erstellen mit den passenden Rechnungen
                    rechnungen = [
                        rechnungs_item for rechnungs_item in data 
                        if rechnungs_item.get('WhiteLabel', {}).get('key') == int(session.get('WhiteLabel_Admin')['id'])
                    ]
                    
                    if not rechnungen:
                        print(f"Keine Rechnungen für das angegebene WhiteLabel (#{session.get('WhiteLabel_Admin')['id']}) gefunden.")
            except Exception as e:
                print(f"Fehler beim Abrufen der Daten: {e}")
            i = 0

            for rechnungs_item in rechnungen:
                i += 1
                rechnungs_item['WhiteLabel_AngebotsID'] = i

                if rechnungs_item['WhiteLabel']['key'] == int(session.get('WhiteLabel_Admin')['id']):
                    # Fälligkeitsdatum in ein Datum-Objekt umwandeln
                    faelligkeitsdatum = datetime.strptime(rechnungs_item['Gueltigkeitsdatum'], "%Y-%m-%d").date()
                    
                    if rechnungs_item['Status'] != "Angenommen" and rechnungs_item['Status'] != "Abgelehnt":
                        # Überprüfung, ob die Rechnung überfällig ist
                        if faelligkeitsdatum < datetime.now().date():
                            rechnungs_item['Status'] = "Abgelaufen"

                    gesamtbetrag = 0.00
                    # Berechnung des Gesamtbetrags
                    for item in rechnungs_item['Items']:
                        gesamtbetrag += float(item['Preis']) * int(item['Anzahl'])

                    rechnungs_item['Preise'] = {}
                    rechnungs_item['Preise']['Zwischensumme'] = gesamtbetrag
                    
                    # Annahme: Der Steuerbetrag ist in Prozent angegeben (z. B. 19%)
                    steuerbetrag = 0  # Beispielwert für die Steuer (19% oder eine andere)
                    
                    # Berechnung des Steuerbetrags
                    rechnungs_item['Preise']['Steuer'] = (steuerbetrag * gesamtbetrag) / 100

                    # Berechnung des Gesamtbetrags
                    rechnungs_item['Preise']['Gesamt'] = rechnungs_item['Preise']['Steuer'] + gesamtbetrag

                    
                    # Nutzer-Details hinzufügen
                    for nutzer in nutzer_details:
                        if rechnungs_item['Nutzer']['key'] == nutzer['id']:
                            rechnungs_item['Nutzer-Details'] = nutzer
                            break  # Breche die innere Schleife ab, wenn der Nutzer gefunden wurde


            success = session.pop('success', None)
            punkte = session.pop('Punkte_Nachricht', None)
            punkte_nachricht = punkte
            error = session.pop('error', None)
            
            header = await render_template('/parts/Elemente/header.html', url= request.url, WhiteLabel = g.whitelabel_info, avatar_url=session.get('avatar'), rolle=session.get('rolle'), name=session.get('name'), Nutzer_Punkte=session.get('Nutzer_Punkte'))
            sidebar = await render_template('/parts/Elemente/sidebar.html', WhiteLabel = g.whitelabel_info, rolle=session.get('rolle'))
            footer = await render_template('/parts/Elemente/footer.html', WhiteLabel = g.whitelabel_info, Session_Info=g.Session_Info['LogEntry_ID'], nutzername=session.get('username'), nutzer_ID=session.get('id'))
            theme_customizer = await render_template('/parts/Elemente/theme-customizer.html', WhiteLabel = g.whitelabel_info)

            WhiteLabel_Admin_Content = client.get_item(collection_name='WhiteLabel', item_id=f'{session.get('WhiteLabel_Admin')['id']}')

            if WhiteLabel_Admin_Content['id'] != g.whitelabel_info['id']:
                session['error'] = f"Du hast leider keinen Zugriff auf die Buchhaltung der WhiteLabel-Instanz '{g.whitelabel_info['Bezeichnung']}'."
                return redirect(f"https://dashboard.{g.whitelabel_info['Domain']}")

            quickStart_TAB = request.args.get('quickstart')

            return await render_template('/parts/Seiten/Admin-Bereich/Buchhaltung/Übersicht_Angebot.html', header=header, sidebar=sidebar, footer=footer, theme_customizer=theme_customizer, success=success, error=error, punkte = punkte, punkte_nachricht = punkte_nachricht, username=session.get('username'), rolle=session.get('rolle'), name=session.get('name'), avatar_url=session.get('avatar'), WhiteLabel = WhiteLabel_Admin_Content, quickStart_TAB=quickStart_TAB, rechnungs_liste=rechnungen, nutzer_liste=nutzer_liste)

        else:
            return redirect("https://dashboard.personalpeak360.de/admin/buchhaltung/übersicht/rechnungen")

    else:
        session['error'] = "Auf diese Seite haben nur Super- bzw. Lower-Admins oder deren Vertretung Zugriff."
        return redirect(f"https://dashboard.{g.whitelabel_info['Domain']}")
    
@app.template_filter('format_datetime')
def format_datetime(value, input_format, output_format):
    dt = datetime.strptime(value, input_format)
    return dt.strftime(output_format)

async def calculate_Next_WL_InvoiceID(WhiteLabel_ID):
    try:
        data = client.get_items("Rechnungen")
        if 'error' in data:
            rechnungen = []
            print(f"Fehler: {data['error']}")
        else:
            # Filtern und eine Liste erstellen mit den passenden Rechnungen
            rechnungen = [
                rechnungs_item for rechnungs_item in data 
                if rechnungs_item.get('WhiteLabel', {}).get('key') == int(WhiteLabel_ID)
            ]
            
            if not rechnungen:
                print(f"Keine Rechnungen für das angegebene WhiteLabel (#{WhiteLabel_ID}) gefunden.")
    except Exception as e:
        print(f"Fehler beim Abrufen der Daten: {e}")
    i = 0

    for rechnungs_item in rechnungen:
        i += 1

    next_ID = i + 1

    return next_ID

async def calculate_Next_WL_AngebotID(WhiteLabel_ID):
    try:
        data = client.get_items("Angebote")
        if 'error' in data:
            rechnungen = []
            print(f"Fehler: {data['error']}")
        else:
            # Filtern und eine Liste erstellen mit den passenden Rechnungen
            rechnungen = [
                rechnungs_item for rechnungs_item in data 
                if rechnungs_item.get('WhiteLabel', {}).get('key') == int(WhiteLabel_ID)
            ]
            
            if not rechnungen:
                print(f"Keine Rechnungen für das angegebene WhiteLabel (#{WhiteLabel_ID}) gefunden.")
    except Exception as e:
        print(f"Fehler beim Abrufen der Daten: {e}")
    i = 0

    for rechnungs_item in rechnungen:
        i += 1

    next_ID = i + 1

    return next_ID

async def getInvoice_FROM_WhiteLabelInvoiceID(WL_Invoice_ID): # Nützlich um eine Rechnung anhand der WhiteLabel Rechnungsnummer abzurufen
    # Die Items von der Collection "Nutzer" abrufen
    try:
        data = client.get_items("Nutzer")

        print(data)
        if 'error' in data:
            nutzer_details = []
            print(f"Fehler: {data['error']}")
        else:
            if data:  # Überprüfen, ob Daten vorhanden sind
                nutzer_details = data  # Speichere die Whitelabel-Informationen in g
                print(f"Nutzer-Details: {nutzer_details}")
            else:
                nutzer_details = []
                print(f"Fehler beim Abruf der Nutzer.")
    except Exception as e:
        print(f"Fehler beim Abrufen der Daten: {e}")

    try:
        data = client.get_items("Rechnungen")
        if 'error' in data:
            rechnungen = []
            print(f"Fehler: {data['error']}")
        else:
            # Filtern und eine Liste erstellen mit den passenden Rechnungen
            rechnungen = [
                rechnungs_item for rechnungs_item in data 
                if rechnungs_item.get('WhiteLabel', {}).get('key') == int(session.get('WhiteLabel_Admin')['id'])
            ]
            
            if not rechnungen:
                print(f"Keine Rechnungen für das angegebene WhiteLabel (#{session.get('WhiteLabel_Admin')['id']}) gefunden.")
    except Exception as e:
        print(f"Fehler beim Abrufen der Daten: {e}")

    i = 0

    rechnungs_item = {}

    found = False
    for rechnungs_item in rechnungen:
        i += 1
        if i == int(WL_Invoice_ID):
            found = True
            rechnungs_item = rechnungs_item
            break

    if found != True:
        return "Not_Found"

    whiteLabel_Details = {}
    try:
        data = client.get_item("WhiteLabel", item_id=int(rechnungs_item.get('WhiteLabel', {}).get('key')))
        if 'error' in data:
            rechnungen = []
            print(f"Fehler: {data['error']}")
        else:
            whiteLabel_Details = data

    except Exception as e:
        print(f"Fehler beim Abrufen der Daten: {e}")
    
    rechnungs_item['WhiteLabel-Details'] = whiteLabel_Details

    
    # Festlegung der WhiteLabel Rechnungsnummer
    rechnungs_item['WhiteLabel_RechnungsID'] = WL_Invoice_ID

    # Fälligkeitsdatum in ein Datum-Objekt umwandeln
    faelligkeitsdatum = datetime.strptime(rechnungs_item['Faelligkeitsdatum'], "%Y-%m-%d").date()
    
    if rechnungs_item['Status'] != "Bezahlt":
        # Überprüfung, ob die Rechnung überfällig ist
        if faelligkeitsdatum < datetime.now().date():
            rechnungs_item['Status'] = "Überfällig"

    gesamtbetrag = 0.00
    # Berechnung des Gesamtbetrags
    for item in rechnungs_item['Items']:
        gesamtbetrag += float(item['Preis']) * int(item['Anzahl'])

    rechnungs_item['Preise'] = {}
    rechnungs_item['Preise']['Zwischensumme'] = gesamtbetrag
    
    # Annahme: Der Steuerbetrag ist in Prozent angegeben (z. B. 19%)
    steuersatz = 0
    if rechnungs_item['WhiteLabel-Details']['KleinunternehmerRegelung'] == False:
        steuersatz = 19

    if steuersatz == 0:
        notes_base = "Im Sinne der Kleinunternehmerregelung nach § 19 UStG enthält der ausgewiesene Betrag keine Umsatzsteuer."
        notes = f"{rechnungs_item['Anmerkung_Oeffentlich']}\n\n{notes_base}" if rechnungs_item['Anmerkung_Oeffentlich'] else notes_base
    else:
        notes = f"{rechnungs_item['Anmerkung_Oeffentlich']}" if rechnungs_item['Anmerkung_Oeffentlich'] else None
    rechnungs_item['Hinweise'] = notes
    
    rechnungs_item['Steuersatz'] = steuersatz

    # Berechnung des Steuerbetrags
    rechnungs_item['Preise']['Steuer'] = (steuersatz * gesamtbetrag) / 100

    # Berechnung des Gesamtbetrags
    rechnungs_item['Preise']['Gesamt'] = rechnungs_item['Preise']['Steuer'] + gesamtbetrag

    
    # Nutzer-Details hinzufügen
    for nutzer in nutzer_details:
        if rechnungs_item['Nutzer']['key'] == nutzer['id']:
            rechnungs_item['Nutzer-Details'] = nutzer
            break  # Breche die innere Schleife ab, wenn der Nutzer gefunden wurde
    
    return rechnungs_item


async def getAngebot_FROM_WhiteLabelInvoiceID(WL_Invoice_ID): # Nützlich um eine Rechnung anhand der WhiteLabel Rechnungsnummer abzurufen
    # Die Items von der Collection "Nutzer" abrufen
    try:
        data = client.get_items("Nutzer")

        print(data)
        if 'error' in data:
            nutzer_details = []
            print(f"Fehler: {data['error']}")
        else:
            if data:  # Überprüfen, ob Daten vorhanden sind
                nutzer_details = data  # Speichere die Whitelabel-Informationen in g
                print(f"Nutzer-Details: {nutzer_details}")
            else:
                nutzer_details = []
                print(f"Fehler beim Abruf der Nutzer.")
    except Exception as e:
        print(f"Fehler beim Abrufen der Daten: {e}")

    try:
        data = client.get_items("Angebote")
        if 'error' in data:
            rechnungen = []
            print(f"Fehler: {data['error']}")
        else:
            # Filtern und eine Liste erstellen mit den passenden Rechnungen
            rechnungen = [
                rechnungs_item for rechnungs_item in data 
                if rechnungs_item.get('WhiteLabel', {}).get('key') == int(session.get('WhiteLabel_Admin')['id'])
            ]
            
            if not rechnungen:
                print(f"Keine Rechnungen für das angegebene WhiteLabel (#{session.get('WhiteLabel_Admin')['id']}) gefunden.")
    except Exception as e:
        print(f"Fehler beim Abrufen der Daten: {e}")

    i = 0

    rechnungs_item = {}

    found = False
    for rechnungs_item in rechnungen:
        i += 1
        if i == int(WL_Invoice_ID):
            found = True
            rechnungs_item = rechnungs_item
            break

    if found != True:
        return "Not_Found"

    whiteLabel_Details = {}
    try:
        data = client.get_item("WhiteLabel", item_id=int(rechnungs_item.get('WhiteLabel', {}).get('key')))
        if 'error' in data:
            rechnungen = []
            print(f"Fehler: {data['error']}")
        else:
            whiteLabel_Details = data

    except Exception as e:
        print(f"Fehler beim Abrufen der Daten: {e}")
    
    rechnungs_item['WhiteLabel-Details'] = whiteLabel_Details

    
    # Festlegung der WhiteLabel Rechnungsnummer
    rechnungs_item['WhiteLabel_AngebotsID'] = WL_Invoice_ID

    # Fälligkeitsdatum in ein Datum-Objekt umwandeln
    faelligkeitsdatum = datetime.strptime(rechnungs_item['Gueltigkeitsdatum'], "%Y-%m-%d").date()
    
    if rechnungs_item['Status'] != "Bezahlt":
        # Überprüfung, ob die Rechnung überfällig ist
        if faelligkeitsdatum < datetime.now().date():
            rechnungs_item['Status'] = "Überfällig"

    gesamtbetrag = 0.00
    # Berechnung des Gesamtbetrags
    for item in rechnungs_item['Items']:
        gesamtbetrag += float(item['Preis']) * int(item['Anzahl'])

    rechnungs_item['Preise'] = {}
    rechnungs_item['Preise']['Zwischensumme'] = gesamtbetrag
    
    # Annahme: Der Steuerbetrag ist in Prozent angegeben (z. B. 19%)
    steuersatz = 0
    if rechnungs_item['WhiteLabel-Details']['KleinunternehmerRegelung'] == False:
        steuersatz = 19

    if steuersatz == 0:
        notes_base = "Im Sinne der Kleinunternehmerregelung nach § 19 UStG enthält der ausgewiesene Betrag keine Umsatzsteuer."
        notes = f"{rechnungs_item['Anmerkung_Oeffentlich']}\n\n{notes_base}" if rechnungs_item['Anmerkung_Oeffentlich'] else notes_base
    else:
        notes = f"{rechnungs_item['Anmerkung_Oeffentlich']}" if rechnungs_item['Anmerkung_Oeffentlich'] else None
    rechnungs_item['Hinweise'] = notes
    
    rechnungs_item['Steuersatz'] = steuersatz

    # Berechnung des Steuerbetrags
    rechnungs_item['Preise']['Steuer'] = (steuersatz * gesamtbetrag) / 100

    # Berechnung des Gesamtbetrags
    rechnungs_item['Preise']['Gesamt'] = rechnungs_item['Preise']['Steuer'] + gesamtbetrag

    
    # Nutzer-Details hinzufügen
    for nutzer in nutzer_details:
        if rechnungs_item['Nutzer']['key'] == nutzer['id']:
            rechnungs_item['Nutzer-Details'] = nutzer
            break  # Breche die innere Schleife ab, wenn der Nutzer gefunden wurde
    
    return rechnungs_item

from lxml import etree
def create_ubl_invoice(rechnungs_item):
    # Create the root element
    invoice = etree.Element("Invoice", xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2")

    # Add UBL version
    ubl_version = etree.SubElement(invoice, "UBLVersionID")
    ubl_version.text = "2.1"

    # Add invoice ID
    invoice_id = etree.SubElement(invoice, "ID")
    invoice_id.text = rechnungs_item['WhiteLabel_RechnungsID']

    # Add issue date
    issue_date = etree.SubElement(invoice, "IssueDate")
    issue_date.text = datetime.strptime(rechnungs_item['Rechnungsdatum'], '%Y-%m-%d').strftime('%Y-%m-%d')

    # Add due date
    due_date = etree.SubElement(invoice, "DueDate")
    due_date.text = datetime.strptime(rechnungs_item['Faelligkeitsdatum'], '%Y-%m-%d').strftime('%Y-%m-%d')

    # Add invoice currency
    currency = etree.SubElement(invoice, "DocumentCurrencyCode")
    currency.text = "EUR"

    # Add supplier details
    accounting_supplier_party = etree.SubElement(invoice, "AccountingSupplierParty")
    supplier_party = etree.SubElement(accounting_supplier_party, "Party")
    supplier_name = etree.SubElement(supplier_party, "PartyName")
    supplier_name_text = etree.SubElement(supplier_name, "Name")
    supplier_name_text.text = rechnungs_item['WhiteLabel-Details']['Firmenname']

    supplier_address = etree.SubElement(supplier_party, "PostalAddress")
    street_name = etree.SubElement(supplier_address, "StreetName")
    street_name.text = rechnungs_item['WhiteLabel-Details']['Strasse']
    building_number = etree.SubElement(supplier_address, "BuildingNumber")
    building_number.text = rechnungs_item['WhiteLabel-Details']['Hausnummer']
    postal_zone = etree.SubElement(supplier_address, "PostalZone")
    postal_zone.text = str(rechnungs_item['WhiteLabel-Details']['PLZ'])
    city_name = etree.SubElement(supplier_address, "CityName")
    city_name.text = rechnungs_item['WhiteLabel-Details']['Ort']
    country = etree.SubElement(supplier_address, "Country")
    country_id = etree.SubElement(country, "IdentificationCode")
    country_id.text = "DE"

    # Add customer details
    accounting_customer_party = etree.SubElement(invoice, "AccountingCustomerParty")
    customer_party = etree.SubElement(accounting_customer_party, "Party")
    customer_name = etree.SubElement(customer_party, "PartyName")
    customer_name_text = etree.SubElement(customer_name, "Name")
    customer_name_text.text = f"{rechnungs_item['Nutzer-Details']['Vorname']} {rechnungs_item['Nutzer-Details']['Nachname']}"

    customer_address = etree.SubElement(customer_party, "PostalAddress")
    street_name = etree.SubElement(customer_address, "StreetName")
    street_name.text = rechnungs_item['Nutzer-Details']['Strasse']
    building_number = etree.SubElement(customer_address, "BuildingNumber")
    building_number.text = rechnungs_item['Nutzer-Details']['Hausnummer']
    postal_zone = etree.SubElement(customer_address, "PostalZone")
    postal_zone.text = rechnungs_item['Nutzer-Details']['PLZ']
    city_name = etree.SubElement(customer_address, "CityName")
    city_name.text = rechnungs_item['Nutzer-Details']['Ort']
    country = etree.SubElement(customer_address, "Country")
    country_id = etree.SubElement(country, "IdentificationCode")
    country_id.text = "DE"

    # Add invoice lines
    i = 0
    for item in rechnungs_item['Items']:
        i+=1
        invoice_line = etree.SubElement(invoice, "InvoiceLine")
        line_id = etree.SubElement(invoice_line, "ID")
        line_id.text = str(i)

        quantity = etree.SubElement(invoice_line, "InvoicedQuantity")
        quantity.text = str(item['Anzahl'])

        line_extension_amount = etree.SubElement(invoice_line, "LineExtensionAmount")
        line_extension_amount.text = f"{item['Preis']:.2f}"

        item_element = etree.SubElement(invoice_line, "Item")
        description = etree.SubElement(item_element, "Description")
        description.text = item['Bezeichnung']

        price = etree.SubElement(invoice_line, "Price")
        price_amount = etree.SubElement(price, "PriceAmount")
        price_amount.text = f"{item['Preis']:.2f}"

    # Generate XML string
    xml_string = etree.tostring(invoice, pretty_print=True, xml_declaration=True, encoding='UTF-8')
    return xml_string

from PyPDF2 import PdfReader, PdfWriter

@app.route('/admin/buchhaltung/<Art>/<Aktion>/<ID>', methods=['GET','POST'])
async def Buchhaltung_Details(Art, Aktion, ID):
    print(session.get('WhiteLabel_Admin')['admin'])
    if session.get('WhiteLabel_Admin')['admin']:
        if Art == "rechnung":
            if Aktion == "details":
                rechnungs_item = await getInvoice_FROM_WhiteLabelInvoiceID(ID)

                if rechnungs_item == "Not_Found":    
                    session['error'] = f"Die Rechnung mit der Whitelabel-Rechnungsnummer #{ID} konnte nicht gefunden werden."
                    return redirect(f"https://dashboard.{g.whitelabel_info['Domain']}/admin/buchhaltung/übersicht/rechnungen")

                print(g.whitelabel_info)

                heute = datetime.now().strftime('%Y-%m-%d')

                success = session.pop('success', None)
                punkte = session.pop('Punkte_Nachricht', None)
                punkte_nachricht = punkte
                error = session.pop('error', None)
                
                header = await render_template('/parts/Elemente/header.html', url= request.url, WhiteLabel = g.whitelabel_info, avatar_url=session.get('avatar'), rolle=session.get('rolle'), name=session.get('name'), Nutzer_Punkte=session.get('Nutzer_Punkte'))
                sidebar = await render_template('/parts/Elemente/sidebar.html', WhiteLabel = g.whitelabel_info, rolle=session.get('rolle'))
                footer = await render_template('/parts/Elemente/footer.html', WhiteLabel = g.whitelabel_info, Session_Info=g.Session_Info['LogEntry_ID'], nutzername=session.get('username'), nutzer_ID=session.get('id'))
                theme_customizer = await render_template('/parts/Elemente/theme-customizer.html', WhiteLabel = g.whitelabel_info)

                WhiteLabel_Admin_Content = client.get_item(collection_name='WhiteLabel', item_id=f'{session.get('WhiteLabel_Admin')['id']}')

                if WhiteLabel_Admin_Content['id'] != g.whitelabel_info['id']:
                    session['error'] = f"Du hast leider keinen Zugriff auf die Buchhaltung der WhiteLabel-Instanz '{g.whitelabel_info['Bezeichnung']}'."
                    return redirect(f"https://dashboard.{g.whitelabel_info['Domain']}")

                return await render_template('/parts/Seiten/Admin-Bereich/Buchhaltung/Rechnung.html', header=header, sidebar=sidebar, footer=footer, theme_customizer=theme_customizer, success=success, error=error, punkte = punkte, punkte_nachricht = punkte_nachricht, username=session.get('username'), rolle=session.get('rolle'), name=session.get('name'), avatar_url=session.get('avatar'), WhiteLabel = WhiteLabel_Admin_Content, rechnung=rechnungs_item, heute=heute)
            elif Aktion == "bezahlen":
                rechnungs_item = await getInvoice_FROM_WhiteLabelInvoiceID(ID)

                return jsonify(rechnungs_item)
            elif Aktion == "Deaktiviere_AutoVerlängerung":
                WL_ID = request.args.get('WL_ID')

                client.update_item("Rechnungen", ID, {"Typ": "Einmalig", "Verlaengerungsdatum": ""})

                session['success'] = f"Die automatische Verlängerung der Rechnung #{WL_ID} wurde erfolgreich deaktiviert."
                return redirect(f"https://dashboard.{g.whitelabel_info['Domain']}/admin/buchhaltung/rechnung/details/{WL_ID}")
            elif Aktion == "Aktiviere_AutoVerlängerung":
                WL_ID = request.args.get('WL_ID')

                data = await request.form

                client.update_item("Rechnungen", ID, {"Typ": "Wiederkehrend", "Verlaengerungsdatum": data.get('verlaengerungs_datum')})

                session['success'] = f"Die automatische Verlängerung der Rechnung #{WL_ID} wurde erfolgreich aktiviert."
                return redirect(f"https://dashboard.{g.whitelabel_info['Domain']}/admin/buchhaltung/rechnung/details/{WL_ID}")
            elif Aktion == "Change_Status":
                WL_ID = request.args.get('WL_ID')
                data = await request.form

                client.update_item("Rechnungen", ID, {"Status": f"{data.get('status')}"})

                session['success'] = f"Der Status der Rechnung #{WL_ID} wurde auf '{data.get('status')}' geändert."
                return redirect(f"https://dashboard.{g.whitelabel_info['Domain']}/admin/buchhaltung/rechnung/details/{WL_ID}")
            elif Aktion == "generate_PDF":
                rechnungs_item = await getInvoice_FROM_WhiteLabelInvoiceID(ID)

                nutzer_data = {
                    "Vorname": rechnungs_item['Nutzer-Details']['Vorname'],
                    "Nachname": rechnungs_item['Nutzer-Details']['Nachname'],
                    "ID": "Nicht vorhanden"
                }

                adresse = {
                    "Strasse": rechnungs_item['Nutzer-Details']['Strasse'],
                    "Hausnummer": rechnungs_item['Nutzer-Details']['Hausnummer'],
                    "PLZ": rechnungs_item['Nutzer-Details']['PLZ'],
                    "Ort": rechnungs_item['Nutzer-Details']['Ort'],
                }

                steuersatz = rechnungs_item['Steuersatz']

                if rechnungs_item['Status'] == "Bezahlt":
                    bezahlterBetrag = rechnungs_item['Preise']['Gesamt']
                else:
                    bezahlterBetrag = 0

                if rechnungs_item['WhiteLabel-Details']['KleinunternehmerRegelung']:
                    notes_base = "Im Sinne der Kleinunternehmerregelung nach § 19 UStG enthält der ausgewiesene Betrag keine Umsatzsteuer."
                    notes = f"{rechnungs_item['Anmerkung_Oeffentlich']}\n\n{notes_base}" if rechnungs_item['Anmerkung_Oeffentlich'] else notes_base

                    payload = {
                        "header": "RECHNUNG",
                        "currency": "EUR",
                        "tax_title": "Steuer",
                        "fields[tax]": "%",
                        "tax": steuersatz,
                        "notes_title": "Hinweise & Anmerkungen",
                        "payment_terms_title": "Fälligkeitsdatum",
                        "to_title": "Rechnungsempfänger",
                        "balance_title": "Offener Betrag",

                        "custom_fields[1][name]": "Status",
                        "custom_fields[1][value]": rechnungs_item['Status'],

                        "shipping": 0,
                        "amount_paid": bezahlterBetrag,
                        "discounts": 0,

                        "from": f"{rechnungs_item['WhiteLabel-Details']['Firmenname']}\n{rechnungs_item['WhiteLabel-Details']['Strasse']} {rechnungs_item['WhiteLabel-Details']['Hausnummer']}\n{rechnungs_item['WhiteLabel-Details']['PLZ']} {rechnungs_item['WhiteLabel-Details']['Ort']}\nDeutschland\nUSt-IdNr: {rechnungs_item['WhiteLabel-Details']['UmsatzsteuerID']}",
                        "to": f"{nutzer_data['Vorname']} {nutzer_data['Nachname']}\n{adresse['Strasse']} {adresse['Hausnummer']}\n{adresse['PLZ']} {adresse['Ort']}\nDeutschland",
                        "logo": f"https://cdn.personalpeak360.de/white-label/{ rechnungs_item['WhiteLabel-Details']['Logo_lang'] }",
                        "number": rechnungs_item['WhiteLabel_RechnungsID'],
                        "date": format_datetime(rechnungs_item['Rechnungsdatum'], '%Y-%m-%d', '%d.%m.%Y'),
                        "payment_terms": format_datetime(rechnungs_item['Faelligkeitsdatum'], '%Y-%m-%d', '%d.%m.%Y'),
                        "notes": notes,
                        "terms": f"Bitte begleichen Sie den Rechnungsbetrag in Höhe von {f'{rechnungs_item['Preise']['Gesamt']:.2f}'.replace('.', ',')} € bis zum {format_datetime(rechnungs_item['Faelligkeitsdatum'], '%Y-%m-%d', '%d.%m.%Y')} über den Cockpit-Bereich im Dashboard."
                    }
                else:
                    notes = f"{rechnungs_item['Anmerkung_Oeffentlich']}\n\n{notes_base}" if rechnungs_item['Anmerkung_Oeffentlich'] else None
                    if notes:
                        payload = {
                            "header": "RECHNUNG",
                            "currency": "EUR",
                            "tax_title": "Steuer",
                            "fields[tax]": "%",
                            "tax": steuersatz,
                            "notes_title": "Hinweise & Anmerkungen",
                            "payment_terms_title": "Fälligkeitsdatum",
                            "to_title": "Rechnungsempfänger",
                            "balance_title": "Offener Betrag",

                            "custom_fields[1][name]": "Status",
                            "custom_fields[1][value]": rechnungs_item['Status'],

                            "shipping": 0,
                            "amount_paid": bezahlterBetrag,
                            "discounts": 0,

                            "from": f"{rechnungs_item['WhiteLabel-Details']['Firmenname']}\n{rechnungs_item['WhiteLabel-Details']['Strasse']} {rechnungs_item['WhiteLabel-Details']['Hausnummer']}\n{rechnungs_item['WhiteLabel-Details']['PLZ']} {rechnungs_item['WhiteLabel-Details']['Ort']}\nDeutschland\nUSt-IdNr: {rechnungs_item['WhiteLabel-Details']['UmsatzsteuerID']}",
                            "to": f"{nutzer_data['Vorname']} {nutzer_data['Nachname']}\n{adresse['Strasse']} {adresse['Hausnummer']}\n{adresse['PLZ']} {adresse['Ort']}\nDeutschland",
                            "logo": f"https://cdn.personalpeak360.de/white-label/{ rechnungs_item['WhiteLabel-Details']['Logo_lang'] }",
                            "number": rechnungs_item['WhiteLabel_RechnungsID'],
                            "date": format_datetime(rechnungs_item['Rechnungsdatum'], '%Y-%m-%d', '%d.%m.%Y'),
                            "payment_terms": format_datetime(rechnungs_item['Faelligkeitsdatum'], '%Y-%m-%d', '%d.%m.%Y'),
                            "notes": notes,
                            "terms": f"Bitte begleichen Sie den Rechnungsbetrag in Höhe von {f'{rechnungs_item['Preise']['Gesamt']:.2f}'.replace('.', ',')} € bis zum {format_datetime(rechnungs_item['Faelligkeitsdatum'], '%Y-%m-%d', '%d.%m.%Y')} über den Cockpit-Bereich im Dashboard."
                        }
                    else:
                        payload = {
                            "header": "RECHNUNG",
                            "currency": "EUR",
                            "tax_title": "Steuer",
                            "fields[tax]": "%",
                            "tax": steuersatz,
                            "notes_title": "Hinweise & Anmerkungen",
                            "payment_terms_title": "Fälligkeitsdatum",
                            "to_title": "Rechnungsempfänger",
                            "balance_title": "Offener Betrag",

                            "custom_fields[1][name]": "Status",
                            "custom_fields[1][value]": rechnungs_item['Status'],

                            "shipping": 0,
                            "amount_paid": bezahlterBetrag,
                            "discounts": 0,

                            "from": f"{rechnungs_item['WhiteLabel-Details']['Firmenname']}\n{rechnungs_item['WhiteLabel-Details']['Strasse']} {rechnungs_item['WhiteLabel-Details']['Hausnummer']}\n{rechnungs_item['WhiteLabel-Details']['PLZ']} {rechnungs_item['WhiteLabel-Details']['Ort']}\nDeutschland\nUSt-IdNr: {rechnungs_item['WhiteLabel-Details']['UmsatzsteuerID']}",
                            "to": f"{nutzer_data['Vorname']} {nutzer_data['Nachname']}\n{adresse['Strasse']} {adresse['Hausnummer']}\n{adresse['PLZ']} {adresse['Ort']}\nDeutschland",
                            "logo": f"https://cdn.personalpeak360.de/white-label/{ rechnungs_item['WhiteLabel-Details']['Logo_lang'] }",
                            "number": rechnungs_item['WhiteLabel_RechnungsID'],
                            "date": format_datetime(rechnungs_item['Rechnungsdatum'], '%Y-%m-%d', '%d.%m.%Y'),
                            "payment_terms": format_datetime(rechnungs_item['Faelligkeitsdatum'], '%Y-%m-%d', '%d.%m.%Y'),
                            "terms": f"Bitte begleichen Sie den Rechnungsbetrag in Höhe von {f'{rechnungs_item['Preise']['Gesamt']:.2f}'.replace('.', ',')} € bis zum {format_datetime(rechnungs_item['Faelligkeitsdatum'], '%Y-%m-%d', '%d.%m.%Y')} über den Cockpit-Bereich im Dashboard."
                        }


                item_count = 0
                # Add items to the payload
                for item in rechnungs_item['Items']:

                    payload[f"items[{item_count}][name]"] = f"{item['Bezeichnung']}\n{item['Beschreibung']}"
                    payload[f"items[{item_count}][quantity]"] = item['Anzahl']
                    payload[f"items[{item_count}][unit_cost]"] = item['Preis']
                    item_count +=1

                headers = {
                    "Authorization": f"Bearer {config['Rechnungs_API']['API_Token']}",
                    "Accept-Language": "de-DE"
                }

                response = requests.post(config['Rechnungs_API']['URL'], headers=headers, data=payload)

                if response.status_code == 200:
                    # Modify PDF properties
                    pdf_content = response.content
                    pdf_reader = PdfReader(io.BytesIO(pdf_content))
                    pdf_writer = PdfWriter()

                    for page in pdf_reader.pages:
                        pdf_writer.add_page(page)

                    # Set PDF metadata
                    created_date = datetime.now().strftime('D:%Y%m%d%H%M%S')
                    pdf_writer.add_metadata({
                        '/Title': f"Rechnung #{rechnungs_item['WhiteLabel_RechnungsID']}",
                        '/Filename': f"Rechnung-{rechnungs_item['WhiteLabel_RechnungsID']}",
                        '/Author': "Wärner Technologie Services",
                        '/Creator': "WTS-Rechnungsprogramm | Version 1.9",
                        '/Producer': "WTS-Generator | Version 1.9",
                        '/Subject': "Rechnung",
                        '/CreationDate': created_date
                    })

                    output = io.BytesIO()
                    pdf_writer.write(output)
                    output.seek(0)

                    return await send_file(
                        output,
                        mimetype='application/pdf',
                        as_attachment=True,
                        attachment_filename=f"Rechnung #{rechnungs_item['WhiteLabel_RechnungsID']}.pdf"
                    )
            elif Aktion == "generate_E-Invoice":
                rechnungs_item = await getInvoice_FROM_WhiteLabelInvoiceID(ID)

                ubl_xml = create_ubl_invoice(rechnungs_item)

                # Gib die XML-Datei als Antwort zurück
                return Response(
                    ubl_xml,
                    content_type='application/xml',
                    headers={
                        "Content-Disposition": f"attachment; filename=Rechnung_{ID}.xml"
                    }
                )
            
            else:
                session['error'] = "Die Aktion für Rechnungen war ungültig."
                return redirect(f"https://dashboard.{g.whitelabel_info['Domain']}/admin/buchhaltung/rechnungen")

        elif Art == "angebot":
            if Aktion == "details":
                rechnungs_item = await getAngebot_FROM_WhiteLabelInvoiceID(ID)

                if rechnungs_item == "Not_Found":    
                    session['error'] = f"Das Angebot mit der Whitelabel-Angebotsnummer #{ID} konnte nicht gefunden werden."
                    return redirect(f"https://dashboard.{g.whitelabel_info['Domain']}/admin/buchhaltung/übersicht/angebote")

                print(g.whitelabel_info)

                heute = datetime.now().strftime('%Y-%m-%d')

                success = session.pop('success', None)
                punkte = session.pop('Punkte_Nachricht', None)
                punkte_nachricht = punkte
                error = session.pop('error', None)
                
                header = await render_template('/parts/Elemente/header.html', url= request.url, WhiteLabel = g.whitelabel_info, avatar_url=session.get('avatar'), rolle=session.get('rolle'), name=session.get('name'), Nutzer_Punkte=session.get('Nutzer_Punkte'))
                sidebar = await render_template('/parts/Elemente/sidebar.html', WhiteLabel = g.whitelabel_info, rolle=session.get('rolle'))
                footer = await render_template('/parts/Elemente/footer.html', WhiteLabel = g.whitelabel_info, Session_Info=g.Session_Info['LogEntry_ID'], nutzername=session.get('username'), nutzer_ID=session.get('id'))
                theme_customizer = await render_template('/parts/Elemente/theme-customizer.html', WhiteLabel = g.whitelabel_info)

                WhiteLabel_Admin_Content = client.get_item(collection_name='WhiteLabel', item_id=f'{session.get('WhiteLabel_Admin')['id']}')

                if WhiteLabel_Admin_Content['id'] != g.whitelabel_info['id']:
                    session['error'] = f"Du hast leider keinen Zugriff auf die Buchhaltung der WhiteLabel-Instanz '{g.whitelabel_info['Bezeichnung']}'."
                    return redirect(f"https://dashboard.{g.whitelabel_info['Domain']}")

                return await render_template('/parts/Seiten/Admin-Bereich/Buchhaltung/Angebot.html', header=header, sidebar=sidebar, footer=footer, theme_customizer=theme_customizer, success=success, error=error, punkte = punkte, punkte_nachricht = punkte_nachricht, username=session.get('username'), rolle=session.get('rolle'), name=session.get('name'), avatar_url=session.get('avatar'), WhiteLabel = WhiteLabel_Admin_Content, rechnung=rechnungs_item, heute=heute)
            elif Aktion == "zurückziehen":
                client.delete_item('Angebote', int(ID))

                session['success'] = "Das Angebot wurde erfolgreich zurückgezogen."
                return redirect(f"https://dashboard.{g.whitelabel_info['Domain']}/admin/buchhaltung/übersicht/angebote")
            elif Aktion == "generate_PDF":
                rechnungs_item = await getAngebot_FROM_WhiteLabelInvoiceID(ID)

                nutzer_data = {
                    "Vorname": rechnungs_item['Nutzer-Details']['Vorname'],
                    "Nachname": rechnungs_item['Nutzer-Details']['Nachname'],
                    "ID": "Nicht vorhanden"
                }

                adresse = {
                    "Strasse": rechnungs_item['Nutzer-Details']['Strasse'],
                    "Hausnummer": rechnungs_item['Nutzer-Details']['Hausnummer'],
                    "PLZ": rechnungs_item['Nutzer-Details']['PLZ'],
                    "Ort": rechnungs_item['Nutzer-Details']['Ort'],
                }

                steuersatz = rechnungs_item['Steuersatz']

                if rechnungs_item['Status'] == "Bezahlt":
                    bezahlterBetrag = rechnungs_item['Preise']['Gesamt']
                else:
                    bezahlterBetrag = 0

                if rechnungs_item['WhiteLabel-Details']['KleinunternehmerRegelung']:
                    notes_base = "Im Sinne der Kleinunternehmerregelung nach § 19 UStG enthält der ausgewiesene Betrag keine Umsatzsteuer."
                    notes = f"{rechnungs_item['Anmerkung_Oeffentlich']}\n\n{notes_base}" if rechnungs_item['Anmerkung_Oeffentlich'] else notes_base

                    payload = {
                        "header": "ANGEBOT",
                        "currency": "EUR",
                        "tax_title": "Steuer",
                        "fields[tax]": "%",
                        "tax": steuersatz,
                        "notes_title": "Hinweise & Anmerkungen",
                        "payment_terms_title": "Gültigkeitsdatum",
                        "to_title": "Angebotsempfänger",
                        "balance_title": "Angebotsbetrag",

                        "custom_fields[1][name]": "Status",
                        "custom_fields[1][value]": rechnungs_item['Status'],

                        "shipping": 0,
                        "amount_paid": bezahlterBetrag,
                        "discounts": 0,

                        "from": f"{rechnungs_item['WhiteLabel-Details']['Firmenname']}\n{rechnungs_item['WhiteLabel-Details']['Strasse']} {rechnungs_item['WhiteLabel-Details']['Hausnummer']}\n{rechnungs_item['WhiteLabel-Details']['PLZ']} {rechnungs_item['WhiteLabel-Details']['Ort']}\nDeutschland\nUSt-IdNr: {rechnungs_item['WhiteLabel-Details']['UmsatzsteuerID']}",
                        "to": f"{nutzer_data['Vorname']} {nutzer_data['Nachname']}\n{adresse['Strasse']} {adresse['Hausnummer']}\n{adresse['PLZ']} {adresse['Ort']}\nDeutschland",
                        "logo": f"https://cdn.personalpeak360.de/white-label/{ rechnungs_item['WhiteLabel-Details']['Logo_lang'] }",
                        "number": rechnungs_item['WhiteLabel_AngebotsID'],
                        "date": format_datetime(rechnungs_item['Angebotsdatum'], '%Y-%m-%d', '%d.%m.%Y'),
                        "payment_terms": format_datetime(rechnungs_item['Gueltigkeitsdatum'], '%Y-%m-%d', '%d.%m.%Y'),
                        "notes": notes,
                        "terms": f"Bitte nehmen oder lehnen Sie dieses Angebot in Höhe von {f'{rechnungs_item['Preise']['Gesamt']:.2f}'.replace('.', ',')} € bis zum {format_datetime(rechnungs_item['Gueltigkeitsdatum'], '%Y-%m-%d', '%d.%m.%Y')} über den Cockpit-Bereich im Dashboard an oder ab."
                    }
                else:
                    notes = f"{rechnungs_item['Anmerkung_Oeffentlich']}\n\n{notes_base}" if rechnungs_item['Anmerkung_Oeffentlich'] else None
                    if notes:
                        payload = {
                            "header": "ANGEBOT",
                            "currency": "EUR",
                            "tax_title": "Steuer",
                            "fields[tax]": "%",
                            "tax": steuersatz,
                            "notes_title": "Hinweise & Anmerkungen",
                            "payment_terms_title": "Gültigkeitsdatum",
                            "to_title": "Angebotsempfänger",
                            "balance_title": "Angebotsbetrag",

                            "custom_fields[1][name]": "Status",
                            "custom_fields[1][value]": rechnungs_item['Status'],

                            "shipping": 0,
                            "amount_paid": bezahlterBetrag,
                            "discounts": 0,

                            "from": f"{rechnungs_item['WhiteLabel-Details']['Firmenname']}\n{rechnungs_item['WhiteLabel-Details']['Strasse']} {rechnungs_item['WhiteLabel-Details']['Hausnummer']}\n{rechnungs_item['WhiteLabel-Details']['PLZ']} {rechnungs_item['WhiteLabel-Details']['Ort']}\nDeutschland\nUSt-IdNr: {rechnungs_item['WhiteLabel-Details']['UmsatzsteuerID']}",
                            "to": f"{nutzer_data['Vorname']} {nutzer_data['Nachname']}\n{adresse['Strasse']} {adresse['Hausnummer']}\n{adresse['PLZ']} {adresse['Ort']}\nDeutschland",
                            "logo": f"https://cdn.personalpeak360.de/white-label/{ rechnungs_item['WhiteLabel-Details']['Logo_lang'] }",
                            "number": rechnungs_item['WhiteLabel_AngebotsID'],
                            "date": format_datetime(rechnungs_item['Angebotsdatum'], '%Y-%m-%d', '%d.%m.%Y'),
                            "payment_terms": format_datetime(rechnungs_item['Gueltigkeitsdatum'], '%Y-%m-%d', '%d.%m.%Y'),
                            "notes": notes,
                            "terms": f"Bitte nehmen oder lehnen Sie dieses Angebot in Höhe von {f'{rechnungs_item['Preise']['Gesamt']:.2f}'.replace('.', ',')} € bis zum {format_datetime(rechnungs_item['Gueltigkeitsdatum'], '%Y-%m-%d', '%d.%m.%Y')} über den Cockpit-Bereich im Dashboard an oder ab."
                        }
                    else:
                        payload = {
                            "header": "ANGEBOT",
                            "currency": "EUR",
                            "tax_title": "Steuer",
                            "fields[tax]": "%",
                            "tax": steuersatz,
                            "notes_title": "Hinweise & Anmerkungen",
                            "payment_terms_title": "Gültigkeitsdatum",
                            "to_title": "Angebotsempfänger",
                            "balance_title": "Angebotsbetrag",

                            "custom_fields[1][name]": "Status",
                            "custom_fields[1][value]": rechnungs_item['Status'],

                            "shipping": 0,
                            "amount_paid": bezahlterBetrag,
                            "discounts": 0,

                            "from": f"{rechnungs_item['WhiteLabel-Details']['Firmenname']}\n{rechnungs_item['WhiteLabel-Details']['Strasse']} {rechnungs_item['WhiteLabel-Details']['Hausnummer']}\n{rechnungs_item['WhiteLabel-Details']['PLZ']} {rechnungs_item['WhiteLabel-Details']['Ort']}\nDeutschland\nUSt-IdNr: {rechnungs_item['WhiteLabel-Details']['UmsatzsteuerID']}",
                            "to": f"{nutzer_data['Vorname']} {nutzer_data['Nachname']}\n{adresse['Strasse']} {adresse['Hausnummer']}\n{adresse['PLZ']} {adresse['Ort']}\nDeutschland",
                            "logo": f"https://cdn.personalpeak360.de/white-label/{ rechnungs_item['WhiteLabel-Details']['Logo_lang'] }",
                            "number": rechnungs_item['WhiteLabel_AngebotsID'],
                            "date": format_datetime(rechnungs_item['Angebotsdatum'], '%Y-%m-%d', '%d.%m.%Y'),
                            "payment_terms": format_datetime(rechnungs_item['Gueltigkeitsdatum'], '%Y-%m-%d', '%d.%m.%Y'),
                            "terms": f"Bitte nehmen oder lehnen Sie dieses Angebot in Höhe von {f'{rechnungs_item['Preise']['Gesamt']:.2f}'.replace('.', ',')} € bis zum {format_datetime(rechnungs_item['Gueltigkeitsdatum'], '%Y-%m-%d', '%d.%m.%Y')} über den Cockpit-Bereich im Dashboard an oder ab."
                        }


                item_count = 0
                # Add items to the payload
                for item in rechnungs_item['Items']:

                    payload[f"items[{item_count}][name]"] = f"{item['Bezeichnung']}\n{item['Beschreibung']}"
                    payload[f"items[{item_count}][quantity]"] = item['Anzahl']
                    payload[f"items[{item_count}][unit_cost]"] = item['Preis']
                    item_count +=1

                headers = {
                    "Authorization": f"Bearer {config['Rechnungs_API']['API_Token']}",
                    "Accept-Language": "de-DE"
                }

                response = requests.post(config['Rechnungs_API']['URL'], headers=headers, data=payload)

                if response.status_code == 200:
                    # Modify PDF properties
                    pdf_content = response.content
                    pdf_reader = PdfReader(io.BytesIO(pdf_content))
                    pdf_writer = PdfWriter()

                    for page in pdf_reader.pages:
                        pdf_writer.add_page(page)

                    # Set PDF metadata
                    created_date = datetime.now().strftime('D:%Y%m%d%H%M%S')
                    pdf_writer.add_metadata({
                        '/Title': f"Angebot #{rechnungs_item['WhiteLabel_AngebotsID']}",
                        '/Filename': f"Angebot-{rechnungs_item['WhiteLabel_AngebotsID']}",
                        '/Author': "Wärner Technologie Services",
                        '/Creator': "WTS-Rechnungsprogramm | Version 1.9",
                        '/Producer': "WTS-Generator | Version 1.9",
                        '/Subject': "Angebot",
                        '/CreationDate': created_date
                    })

                    output = io.BytesIO()
                    pdf_writer.write(output)
                    output.seek(0)

                    return await send_file(
                        output,
                        mimetype='application/pdf',
                        as_attachment=True,
                        attachment_filename=f"Angebot #{rechnungs_item['WhiteLabel_AngebotsID']}.pdf"
                    )
            else:
                session['error'] = "Die Aktion für Angebote war ungültig."
                return redirect(f"https://dashboard.{g.whitelabel_info['Domain']}/admin/buchhaltung/angebote")
        else:
            session['error'] = "Die Aktion für Rechnungen war ungültig."
            return redirect(f"https://dashboard.{g.whitelabel_info['Domain']}/admin/buchhaltung/rechnungen")

    else:
        session['error'] = "Auf diese Seite haben nur Super- bzw. Lower-Admins oder deren Vertretung Zugriff."
        return redirect(f"https://dashboard.{g.whitelabel_info['Domain']}")


@app.route('/admin/live-chat', methods=['GET'])
async def AdminBereich_LiveChat():
    print(session.get('WhiteLabel_Admin')['admin'])
    if session.get('WhiteLabel_Admin')['admin']:
        success = session.pop('success', None)
        punkte = session.pop('Punkte_Nachricht', None)
        punkte_nachricht = punkte
        error = session.pop('error', None)

        header = await render_template('/parts/Elemente/header.html', url= request.url, 
                                                    WhiteLabel=g.whitelabel_info, 
                                                    avatar_url=session.get('avatar'), 
                                                    rolle=session.get('rolle'), 
                                                    name=session.get('name'), Nutzer_Punkte=session.get('Nutzer_Punkte'))
        sidebar = await render_template('/parts/Elemente/sidebar.html', 
                                        WhiteLabel=g.whitelabel_info, rolle=session.get('rolle'))
        footer = await render_template('/parts/Elemente/footer.html', WhiteLabel = g.whitelabel_info, Session_Info=g.Session_Info['LogEntry_ID'], nutzername=session.get('username'), nutzer_ID=session.get('id'))

        theme_customizer = await render_template('/parts/Elemente/theme-customizer.html', 
                                                WhiteLabel=g.whitelabel_info)
        

        # Die Items von der Collection "Nutzer" abrufen
        try:
            data = client.get_items("Nutzer")

            print(data)
            if 'error' in data:
                nutzer_details = []
                print(f"Fehler: {data['error']}")
            else:
                if data:  # Überprüfen, ob Daten vorhanden sind
                    nutzer_details = data  # Speichere die Whitelabel-Informationen in g
                    print(f"Nutzer-Details: {nutzer_details}")
                else:
                    nutzer_details = []
                    print(f"Fehler beim Abruf der Nutzer.")
        except Exception as e:
            print(f"Fehler beim Abrufen der Daten: {e}")

        nutzer_ids = [nutzer['id'] for nutzer in data if nutzer['Referrer'] == session.get('id')] # Nutzer, für welche der Admin zuständig ist bzw. welche dieser angelegt hat


        
        live_chats = client.get_items(
            collection_name="LiveChats"
        )

        # Filtere die Live Chats für den aktuellen Nutzer
        live_chats = [chat for chat in live_chats if chat['Nutzer']['key'] in nutzer_ids]

        # Füge die Nutzer-Details zu jedem Live Chat hinzu
        for chat in live_chats:
            # Finde die entsprechenden Nutzer-Details für den aktuellen Live Chat
            nutzer_id = chat['Nutzer']['key']
            nutzer_detail = next((nutzer for nutzer in nutzer_details if nutzer['id'] == nutzer_id), None)
            
            if nutzer_detail:
                chat['Nutzer_Details'] = nutzer_detail  # Füge die Nutzer-Details hinzu



        live_chats_AUSSTEHEND = client.get_items(
            collection_name="LiveChats_AUSSTEHEND",
            query = {
                "query": {
                    "filter": {
                        "Nutzer": {
                            "id": {
                                "_in": nutzer_ids
                            }
                        }
                    }
                }
            }
        )

        # Filtere die Live Chats für den aktuellen Nutzer
        live_chats_AUSSTEHEND = [chat for chat in live_chats_AUSSTEHEND if chat['Nutzer']['key'] in nutzer_ids]

        # Füge die Nutzer-Details zu jedem Live Chat hinzu
        for chat in live_chats_AUSSTEHEND:
            # Finde die entsprechenden Nutzer-Details für den aktuellen Live Chat
            nutzer_id = chat['Nutzer']['key']
            nutzer_detail = next((nutzer for nutzer in nutzer_details if nutzer['id'] == nutzer_id), None)
            
            if nutzer_detail:
                chat['Nutzer_Details'] = nutzer_detail  # Füge die Nutzer-Details hinzu
        
        # Rendern der Vorschau-HTML-Vorlage mit den erhaltenen Parametern
        return await render_template(f'/parts/Seiten/Admin-Bereich/Live-Chat.html', 
                                    header=header,
                                    error=error, 
                                    success=success, 
                                    sidebar=sidebar, 
                                    footer=footer, 
                                    theme_customizer=theme_customizer,
                                    username=session.get('username'), 
                                    rolle=session.get('rolle'), 
                                    name=session.get('name'), 
                                    avatar_url=session.get('avatar'), 
                                    WhiteLabel=g.whitelabel_info,
                                    live_chats = live_chats,
                                    live_chats_AUSSTEHEND = live_chats_AUSSTEHEND)

    else:
        session['error'] = "Auf diese Seite haben nur Super- bzw. Lower-Admins oder deren Vertretung Zugriff."
        return redirect(f"https://dashboard.{g.whitelabel_info['Domain']}")

    
@app.route('/admin/live-chat/<ID>', methods=['GET'])
async def AdminBereich_LiveChat_DETAILS(ID):
    success = session.pop('success', None)
    punkte = session.pop('Punkte_Nachricht', None)
    punkte_nachricht = punkte
    error = session.pop('error', None)

    header = await render_template('/parts/Elemente/header.html', url= request.url, 
                                                WhiteLabel=g.whitelabel_info, 
                                                avatar_url=session.get('avatar'), 
                                                rolle=session.get('rolle'), 
                                                name=session.get('name'), Nutzer_Punkte=session.get('Nutzer_Punkte'))
    sidebar = await render_template('/parts/Elemente/sidebar.html', 
                                    WhiteLabel=g.whitelabel_info, rolle=session.get('rolle'))
    footer = await render_template('/parts/Elemente/footer.html', WhiteLabel = g.whitelabel_info, Session_Info=g.Session_Info['LogEntry_ID'], nutzername=session.get('username'), nutzer_ID=session.get('id'))

    theme_customizer = await render_template('/parts/Elemente/theme-customizer.html', 
                                            WhiteLabel=g.whitelabel_info)
    

    live_chat = client.get_item(
        collection_name="LiveChats",
        item_id=ID
    )

    
    chat_nachrichten = client.get_items(
        collection_name="Chat_Nachrichten",
        query = {
            "query": {
                "filter": {
                    "Chat": {
                        "id": {
                            "_eq": ID
                        }
                    }
                },
                "sort": "Zeitstempel"  # 'Zeitstempel' durch das entsprechende Zeitfeld ersetze
            }
        }
    )
    print(chat_nachrichten)

    if chat_nachrichten:
        chat_nachrichten = chat_nachrichten
    else:
        chat_nachrichten = None

    chat_nachrichten = [nachricht for nachricht in chat_nachrichten if nachricht['Chat']['key'] == ID]

    nachrichten_sender = set()

    for message in chat_nachrichten:
        nachrichten_sender.add(message['Nutzer']['key'])  # Fügt den Key zur Menge hinzu

    # Umwandlung der Menge in eine Liste, falls benötigt
    nachrichten_sender_list = list(nachrichten_sender)

    sender_liste = []  # Eine leere Liste für die Sender-Infos
    for sender in nachrichten_sender_list:
        infos = client.get_item("Nutzer", sender)
        sender_liste.append(infos)  # Fügt die Infos zur Liste hinzu


    # Create a user map
    user_map = {nutzer['id']: nutzer for nutzer in sender_liste}


    chat_details = {
        "ID": live_chat['id'],
        "Thema": live_chat['Thema'],
        "Zeitpunkt": live_chat['Zeitpunkt'],
        "Nachrichten": chat_nachrichten,
        "Sender_Liste": sender_liste,
        "Nutzer_Map": user_map
    }

    
    # Rendern der Vorschau-HTML-Vorlage mit den erhaltenen Parametern
    return await render_template(f'/parts/Seiten/Admin-Bereich/Live-Chat_DETAILS.html', 
                                header=header,
                                error=error, 
                                success=success, 
                                sidebar=sidebar, 
                                footer=footer, 
                                theme_customizer=theme_customizer,
                                username=session.get('username'), 
                                rolle=session.get('rolle'), 
                                name=session.get('name'), 
                                avatar_url=session.get('avatar'), 
                                WhiteLabel=g.whitelabel_info,
                                chat_details = chat_details,
                                Nutzer_ID = session.get('id'))


@app.route('/admin/live-chat/<ID>/<Aktion>', methods=['GET'])
async def AdminBereich_LiveChat_AKTIONEN(ID, Aktion):
    print(session.get('WhiteLabel_Admin')['admin'])
    if session.get('WhiteLabel_Admin')['admin']:
        if Aktion == "annehmen":
            LiveChats_AUSSTEHEND = {}

            # Die Items von der Collection "Nutzer" abrufen
            try:
                data = client.get_item("LiveChats_AUSSTEHEND", ID)

                print(data)
                if 'error' in data:
                    LiveChats_AUSSTEHEND = {}
                    print(f"Fehler: {data['error']}")
                else:
                    if data:  # Überprüfen, ob Daten vorhanden sind
                        LiveChats_AUSSTEHEND = data  # Speichere die Whitelabel-Informationen in g
                        print(f"LiveChats_AUSSTEHEND: {LiveChats_AUSSTEHEND}")
                    else:
                        LiveChats_AUSSTEHEND = {}
                        print(f"Fehler beim Abruf der LiveChats_AUSSTEHEND.")
            except Exception as e:
                print(f"Fehler beim Abrufen der Daten: {e}")

            if LiveChats_AUSSTEHEND == {}:
                session['error'] = "Bei der Änderung ist ein Fehler aufgetreten."
                return redirect(f"https://dashboard.{g.whitelabel_info['Domain']}/admin/live-chat")

            client.delete_item("LiveChats_AUSSTEHEND", ID)

            client.create_item("LiveChats", {
                "Zeitpunkt": LiveChats_AUSSTEHEND['Zeitpunkt'],
                "Thema": LiveChats_AUSSTEHEND['Thema'],
                "Nutzer": LiveChats_AUSSTEHEND['Nutzer']
            })

            session['success'] = "Der Termin für den Live-Chat wurde bestätigt. Der Nutzer hat eine Email erhalten."
            return redirect(f"https://dashboard.{g.whitelabel_info['Domain']}/admin/live-chat")
        elif Aktion == "ablehnen":
            client.update_item("LiveChats_AUSSTEHEND" , ID, {
                "Status": "Abgelehnt"
            })

            session['success'] = "Der Termin für den Live-Chat wurde abgelehnt."
            return redirect(f"https://dashboard.{g.whitelabel_info['Domain']}/admin/live-chat")
    else:
        session['error'] = "Auf diese Seite haben nur Super- bzw. Lower-Admins oder deren Vertretung Zugriff."
        return redirect(f"https://dashboard.{g.whitelabel_info['Domain']}")



@app.route('/cockpit/profil', methods=['GET'])
async def Cockpit_Profil():
    # Abruf der Informationen des Referrers
    request_directus = {
        "query": {
            "filter": {
                "id": {
                    "_eq": session.get('id')
                }
            }
        }
    }
    data = []

    # Die Items von der Collection "WhiteLabel" abrufen
    try:
        data = client.get_items("Nutzer", request_directus)

        print(data)
        if 'error' in data:
            nutzer_details = {}
            print(f"Fehler: {data['error']}")
        else:
            if data:  # Überprüfen, ob Daten vorhanden sind
                nutzer_details = data[0]  # Speichere die Whitelabel-Informationen in g
                print(f"Nutzer-Details: {nutzer_details}")
            else:
                nutzer_details = {}
                print(f"Fehler beim Abruf des Referrers.")
    except Exception as e:
        print(f"Fehler beim Abrufen der Daten: {e}")

    if nutzer_details['Referrer']:
        # Abruf der Informationen des Referrers
        request_directus = {
            "query": {
                "filter": {
                    "id": {
                        "_eq": int(nutzer_details['Referrer'])
                    }
                }
            }
        }
        data = []

        # Die Items von der Collection "WhiteLabel" abrufen
        try:
            data = client.get_items("Nutzer", request_directus)

            print(data)
            if 'error' in data:
                nutzer_details = {}
                print(f"Fehler: {data['error']}")
            else:
                if data:  # Überprüfen, ob Daten vorhanden sind
                    referrer_details = data[0]  # Speichere die Whitelabel-Informationen in g
                    print(f"Referrer-Details: {referrer_details}")
                else:
                    referrer_details = {}
                    print(f"Fehler beim Abruf des Referrers.")
        except Exception as e:
            print(f"Fehler beim Abrufen der Daten: {e}")
    else:
        referrer_details = {}

    data_Rolle = {}
    try:
        data_Rolle = client.get_item("Nutzer_Rollen", nutzer_details['Rolle_RECHTE']['key'])

        print(data)
        if 'error' in data_Rolle:
            data_Rolle = {}
            print(f"Fehler: {data['error']}")
        else:
            if data:  # Überprüfen, ob Daten vorhanden sind
                data_Rolle = data_Rolle  # Speichere die Whitelabel-Informationen in g
                print(f"Referrer-Details: {data_Rolle}")
            else:
                data_Rolle = {}
                print(f"Fehler beim Abruf des Referrers.")
    except Exception as e:
        print(f"Fehler beim Abrufen der Daten: {e}")

    
    request_directus = {
        "query": {
            "filter": {
                "Nutzer_ID": {
                    "_eq": nutzer_details['id']
                }
            },
            "limit": 2000,
            "sort": "-Zeitstempel"  # 'Zeitstempel' durch das entsprechende Zeitfeld ersetzen
        }
    }

    Statistik_data = []
    Statistik_response = []

    try:
        Statistik_response = client.get_items("Nutzer_Statistik", request_directus)

        print(Statistik_response)
        if 'error' in Statistik_response:
            Statistik_data = []
            print(f"Fehler: {Statistik_response['error']}")
        else:
            if Statistik_response:  # Überprüfen, ob Daten vorhanden sind
                Statistik_data = Statistik_response  # Speichere die Whitelabel-Informationen in g
                print(f"Nutzer-Statistik: {Statistik_data}")
            else:
                Statistik_data = []
                print(f"Fehler beim Abruf der Nutzer-Statistik.")
    except Exception as e:
        print(f"Fehler beim Abrufen der Daten: {e}")

    print(Statistik_data)

    # Umwandeln in ein datetime-Objekt
    erstellungsdatum = datetime.fromisoformat(nutzer_details['Erstellung'])

    # Formatieren in das gewünschte Format
    formatiertes_datum = erstellungsdatum.strftime("%d.%m.%Y um %H:%M Uhr")

    nutzer_details['Erstellung'] = formatiertes_datum


    today = datetime.now().date()
    yesterday = today - timedelta(days=1)
    last_7_days_start = today - timedelta(days=7)
    # Liste der Daten generieren
    last_7_days_date_list = [(last_7_days_start + timedelta(days=i)).isoformat() for i in range((today - last_7_days_start).days + 1)]
    # Start des Monats
    this_month_start = today.replace(day=1)
    # Letzter Tag des Monats ermitteln
    days_in_month = calendar.monthrange(today.year, today.month)[1]
    this_month_end = today.replace(day=days_in_month)
    # Liste der Daten vom Monatsanfang bis zum Monatsende generieren
    date_list_this_month = [(this_month_start + timedelta(days=i)).isoformat() for i in range((this_month_end - this_month_start).days + 1)]

    today_seconds = await fetch_data({"_eq": today.isoformat()}, nutzer_details['id'])
    yesterday_seconds = await fetch_data({"_eq": yesterday.isoformat()}, nutzer_details['id'])
    last_7_days_seconds = await fetch_data({"_in": last_7_days_date_list}, nutzer_details['id'])
    this_month_seconds = await fetch_data({"_in": date_list_this_month}, nutzer_details['id'])

    def parse_verweil_dauer(item):
        # Versuche, den Wert zu einer Zahl (float) zu konvertieren, ansonsten setze ihn auf 0
        try:
            return int(float(item.get("Verweil_Dauer", 0) or 0))  # float für Dezimalzahlen, dann zu int
        except (ValueError, TypeError):
            return 0

    def convert_seconds(seconds):
        """Konvertiert Sekunden in eine lesbare Einheit."""
        if seconds < 60:
            return {"value": float(seconds), "unit": "Sekunden"}
        elif seconds < 3600:
            return {"value": float(seconds / 60), "unit": "Minuten"}
        else:
            return {"value": float(seconds / 3600), "unit": "Stunden"}

    statistics = {
        "heute online": convert_seconds(sum(parse_verweil_dauer(item) for item in today_seconds)),
        "gestern online": convert_seconds(sum(parse_verweil_dauer(item) for item in yesterday_seconds)),
        "letzten 7 Tagen online": convert_seconds(sum(parse_verweil_dauer(item) for item in last_7_days_seconds)),
        "diesen Monat online": convert_seconds(sum(parse_verweil_dauer(item) for item in this_month_seconds)),
    }
    
    from urllib.parse import urlparse

    liste = []
    for item in Statistik_data:
        # URL aufteilen und den Domain-Teil extrahieren
        url = item['Daten']['URL'].split('//')[-1]  # Entferne das Protokoll (http:// oder https://)

        # Den Domain-Teil isolieren, indem alles nach dem ersten '/' entfernt wird
        subdomain = url.split('/')[0]  # Entfernt alles nach dem ersten '/'

        # Extrahiere nur den Hostnamen (alle Teile ab dem zweiten Punkt)
        hostname = '.'.join(subdomain.split('.')[1:])  # Entferne den ersten Teil (Subdomain)

        # Überprüfen, ob der Hostname bereits in der Liste ist
        if not any(hostname in d for d in liste):
            liste.append({f"{hostname}": {}})

    # Gehe durch die Liste der verbleibenden Hostnamen und rufe die Whitelabel-Informationen ab
    for entry in liste:
        for hostname in entry:
            # Erstelle die Anfrage an Directus
            request_directus = {
                "query": {
                    "filter": {
                        "Domain": {
                            "_eq": hostname  # Filter für die Domain
                        }
                    }
                }
            }

            # Die Items von der Collection "WhiteLabel" abrufen
            try:
                data = client.get_items("WhiteLabel", request_directus)

                if 'error' in data:
                    print(f"Fehler: {data['error']}")
                    entry[hostname] = None  # Keine Info bei Fehler
                else:
                    if data:  # Überprüfen, ob Daten vorhanden sind
                        entry[hostname] = data[0]  # Daten an den Hostnamen anhängen
                        print(f"WhiteLabel-Info für {hostname}: {data[0]}")
                    else:
                        entry[hostname] = None  # Keine Daten vorhanden
                        print(f"Keine WhiteLabel-Informationen für {hostname} gefunden.")
            except Exception as e:
                print(f"Fehler beim Abrufen der Daten: {e}")
                entry[hostname] = None  # Keine Info bei Ausnahme

    # Ausgabe der Liste mit den angehängten Whitelabel-Infos
    print(liste)


    success = session.pop('success', None)
    punkte = session.pop('Punkte_Nachricht', None)
    punkte_nachricht = punkte
    error = session.pop('error', None)

    header = await render_template('/parts/Elemente/header.html', url= request.url, 
                                                WhiteLabel=g.whitelabel_info, 
                                                avatar_url=session.get('avatar'), 
                                                rolle=session.get('rolle'), 
                                                name=session.get('name'), Nutzer_Punkte=session.get('Nutzer_Punkte'))
    sidebar = await render_template('/parts/Elemente/sidebar.html', 
                                    WhiteLabel=g.whitelabel_info, rolle=session.get('rolle'))
    footer = await render_template('/parts/Elemente/footer.html', WhiteLabel = g.whitelabel_info, Session_Info=g.Session_Info['LogEntry_ID'], nutzername=session.get('username'), nutzer_ID=session.get('id'))

    theme_customizer = await render_template('/parts/Elemente/theme-customizer.html', 
                                            WhiteLabel=g.whitelabel_info)
    
    
    # Rendern der Vorschau-HTML-Vorlage mit den erhaltenen Parametern
    return await render_template(f'/parts/Seiten/Cockpit/Mein-Profil.html', 
                                header=header,
                                error=error, 
                                success=success, 
                                sidebar=sidebar, 
                                footer=footer, 
                                theme_customizer=theme_customizer,
                                username=session.get('username'), 
                                rolle=session.get('rolle'), 
                                name=session.get('name'), 
                                avatar_url=session.get('avatar'), 
                                WhiteLabel=g.whitelabel_info,
                                nutzer=nutzer_details,
                                referrer=referrer_details,
                                statistik_data=Statistik_response,
                                online_Statistik=statistics,
                                WhiteLabel_Liste=liste,
                                Rollen_Info=data_Rolle)


@app.route('/cockpit/tagebuch', methods=['GET'])
async def Cockpit_Tagebuch():
    success = session.pop('success', None)
    punkte = session.pop('Punkte_Nachricht', None)
    punkte_nachricht = punkte
    error = session.pop('error', None)

    header = await render_template('/parts/Elemente/header.html', url= request.url, 
                                                WhiteLabel=g.whitelabel_info, 
                                                avatar_url=session.get('avatar'), 
                                                rolle=session.get('rolle'), 
                                                name=session.get('name'), Nutzer_Punkte=session.get('Nutzer_Punkte'))
    sidebar = await render_template('/parts/Elemente/sidebar.html', 
                                    WhiteLabel=g.whitelabel_info, rolle=session.get('rolle'))
    footer = await render_template('/parts/Elemente/footer.html', WhiteLabel = g.whitelabel_info, Session_Info=g.Session_Info['LogEntry_ID'], nutzername=session.get('username'), nutzer_ID=session.get('id'))

    theme_customizer = await render_template('/parts/Elemente/theme-customizer.html', 
                                            WhiteLabel=g.whitelabel_info)
    
    
    # Rendern der Vorschau-HTML-Vorlage mit den erhaltenen Parametern
    return await render_template(f'/parts/Seiten/Cockpit/Tagebuch.html', 
                                header=header,
                                error=error, 
                                success=success, 
                                sidebar=sidebar, 
                                footer=footer, 
                                theme_customizer=theme_customizer,
                                username=session.get('username'), 
                                rolle=session.get('rolle'), 
                                name=session.get('name'), 
                                avatar_url=session.get('avatar'), 
                                WhiteLabel=g.whitelabel_info)


@app.route('/cockpit/ECommerce_Shop', methods=['GET'])
async def Cockpit_ECommerceShop():
    success = session.pop('success', None)
    punkte = session.pop('Punkte_Nachricht', None)
    punkte_nachricht = punkte
    error = session.pop('error', None)

    header = await render_template('/parts/Elemente/header.html', url= request.url, 
                                                WhiteLabel=g.whitelabel_info, 
                                                avatar_url=session.get('avatar'), 
                                                rolle=session.get('rolle'), 
                                                name=session.get('name'), Nutzer_Punkte=session.get('Nutzer_Punkte'))
    sidebar = await render_template('/parts/Elemente/sidebar.html', 
                                    WhiteLabel=g.whitelabel_info, rolle=session.get('rolle'))
    footer = await render_template('/parts/Elemente/footer.html', WhiteLabel = g.whitelabel_info, Session_Info=g.Session_Info['LogEntry_ID'], nutzername=session.get('username'), nutzer_ID=session.get('id'))

    theme_customizer = await render_template('/parts/Elemente/theme-customizer.html', 
                                            WhiteLabel=g.whitelabel_info)
    
    if request.args.get('callback') == "true":
        interne_id = request.args.get('interneID')
        query = {
            "query": {
                "filter": {
                    "UUID": {
                        "_eq": interne_id
                    }
                },
                "limit": 2000
            }
        }
        daten = client.get_items('ECommerceShop_ZAHLUNGEN', query)

        mollie_id = daten[0]['Mollie_ID']
    else:
        mollie_id = None

    request_directus = {
        "query": {
            "filter": {
                "WhiteLabel": {
                    "id": {
                        "_eq": int(g.whitelabel_info['id'])
                    }
                }
            }
        }
    }
    Ecommerce_Produkte = client.get_items('ECommerce_Shop', request_directus)


    Nutzer_Details = client.get_item("Nutzer", session.get('id'))

    EcommerceProdukte_FILTERED = []

    for item in Ecommerce_Produkte:
        # Überprüfe, ob alle Rechte des Produkts in den Nutzerrechten enthalten sind
        if all(benefit in Nutzer_Details['RECHTE'] for benefit in item['Rechte']):
            # Wenn alle Rechte vorhanden sind, füge es nicht hinzu
            continue
        else:
            # Ansonsten füge das Produkt zur gefilterten Liste hinzu
            EcommerceProdukte_FILTERED.append(item)
    
    
    # Rendern der Vorschau-HTML-Vorlage mit den erhaltenen Parametern
    return await render_template(f'/parts/Seiten/Cockpit/ECommerce_Shop.html', 
                                header=header,
                                error=error, 
                                success=success, 
                                sidebar=sidebar, 
                                footer=footer, 
                                theme_customizer=theme_customizer,
                                username=session.get('username'), 
                                rolle=session.get('rolle'), 
                                name=session.get('name'), 
                                avatar_url=session.get('avatar'), 
                                WhiteLabel=g.whitelabel_info,
                                Produkte = EcommerceProdukte_FILTERED, 
                                callback = request.args.get('callback'), 
                                mollieid = mollie_id)

@app.route('/cockpit/freischalten/<Produkt_ID>', methods=['GET'])
async def Cockpit_ECommerceShop_FREISCHALTEN(Produkt_ID):
    Produkt_Details = client.get_item("ECommerce_Shop", Produkt_ID)

    customer = mollie_client.customers.get(session.get('Mollie_CUSTOMER_ID'))

    if Produkt_Details['Preis_RABATT']:
        preis = Produkt_Details['Preis_RABATT']
    else:
        preis = Produkt_Details['Preis']

    
    # Heutiges Datum im gewünschten Format (YYYY-MM-DD)
    heute = datetime.now().strftime("%Y-%m-%d")

    zahlungsID_intern = ''.join(random.choices(string.ascii_letters + string.digits, k=10)) # Ebenfalls in Directus
    paymentID_INtern = f"zahlung_{zahlungsID_intern}"

    payment = mollie_client.payments.create(
        {
            "amount": {
                "currency": "EUR", 
                "value": f"{preis}"
            },
            "description": f"Bezahlung für Zusatzfunktion {Produkt_Details['Bezeichnung']}",
            "webhookUrl": f"https://dashboard.{g.whitelabel_info['Domain']}/cockpit/ECommerce_Shop?callback=true&interneID={paymentID_INtern}",
            "redirectUrl": f"https://dashboard.{g.whitelabel_info['Domain']}/cockpit/ECommerce_Shop?callback=true&interneID={paymentID_INtern}",
            "metadata": {"Zusatzfunktion": Produkt_Details['Bezeichnung']},
            "cancelUrl": f"https://dashboard.{g.whitelabel_info['Domain']}/cockpit/ECommerce_Shop?cancel=true"
        }
    )


    checkout_url = payment.checkout_url
    order_id = payment.id

    body = {
        'UUID': paymentID_INtern,
        'Mollie_ID': order_id,
        'Checkout_URL': checkout_url,
        'Zusatzfunktion_ID': Produkt_Details['id']
    }
    # Eintrag der Zahlung
    client.create_item("ECommerceShop_ZAHLUNGEN", body)

    return redirect(checkout_url)

@app.route('/cockpit/ECommerce_Shop/erfolgreichBezahlt/<orderID>', methods=['GET'])
async def render_cockpit_EcommerceShop_erfolgreichBezahlt(orderID):
    payment = mollie_client.payments.get(orderID)
    
    query = {
        "query": {
            "filter": {
                "Mollie_ID": {
                    "_eq": orderID
                }
            },
            "limit": 1
        }
    }
    zahlungen = client.get_items('ECommerceShop_ZAHLUNGEN', query)

    if zahlungen:  # 'data' enthält die Ergebnisse der Abfrage
        pass
    else:
        session['error'] = "Die Zahlung war ungültig."
        return redirect(f"https://dashboard.{g.whitelabel_info['Domain']}/cockpit/ECommerce_Shop")

    if payment.STATUS_PAID == "paid":
        client.delete_item("ECommerceShop_ZAHLUNGEN", zahlungen[0]['id'])

        
        produkt = client.get_item("ECommerce_Shop", zahlungen[0]['Zusatzfunktion_ID'])

        print(f"Rechte: {produkt['Rechte']}")

        nutzer_details = client.get_item("Nutzer", session.get('id'))
        Derzeitige_Rechte = []
        Derzeitige_Rechte = nutzer_details['RECHTE']

        for item in produkt['Rechte']:
            if item not in Derzeitige_Rechte:
                Derzeitige_Rechte.append(item)

        client.update_item("Nutzer", session.get('id'), {"RECHTE": Derzeitige_Rechte})


        session['success'] = f"Die Zusatzfunktion wurde vollständig beglichen und somit aktiviert."
        return redirect(f"https://dashboard.{g.whitelabel_info['Domain']}/cockpit/ECommerce_Shop")
    else:
        session['error'] = "Der Betrag wurde nicht beglichen."
        return redirect(f"https://dashboard.{g.whitelabel_info['Domain']}/cockpit/ECommerce_Shop")    


@app.route('/cockpit/kalender', methods=['GET', 'POST'])
async def Cockpit_Kalender():
    if request.method == "GET":
        success = session.pop('success', None)
        punkte = session.pop('Punkte_Nachricht', None)
        punkte_nachricht = punkte
        error = session.pop('error', None)

        today = datetime.now().strftime('%Y-%m-%d')  # Formatiere das Datum

        header = await render_template('/parts/Elemente/header.html', url= request.url, 
                                                    WhiteLabel=g.whitelabel_info, 
                                                    avatar_url=session.get('avatar'), 
                                                    rolle=session.get('rolle'), 
                                                    name=session.get('name'), Nutzer_Punkte=session.get('Nutzer_Punkte'))
        sidebar = await render_template('/parts/Elemente/sidebar.html', 
                                        WhiteLabel=g.whitelabel_info, rolle=session.get('rolle'))
        footer = await render_template('/parts/Elemente/footer.html', WhiteLabel = g.whitelabel_info, Session_Info=g.Session_Info['LogEntry_ID'], nutzername=session.get('username'), nutzer_ID=session.get('id'))

        theme_customizer = await render_template('/parts/Elemente/theme-customizer.html', 
                                                WhiteLabel=g.whitelabel_info)


        Nutzer_Details = client.get_item('Nutzer', session.get('id'))

        Termine = Nutzer_Details['Termine']

        
        
        # Rendern der Vorschau-HTML-Vorlage mit den erhaltenen Parametern
        return await render_template(f'/parts/Seiten/Cockpit/Kalender.html', 
                                    header=header,
                                    error=error, 
                                    success=success, 
                                    sidebar=sidebar, 
                                    footer=footer, 
                                    theme_customizer=theme_customizer,
                                    username=session.get('username'), 
                                    rolle=session.get('rolle'), 
                                    name=session.get('name'), 
                                    avatar_url=session.get('avatar'), 
                                    WhiteLabel=g.whitelabel_info,
                                    today = today,
                                    Termine = Termine)
    else:
        data = await request.get_json()
    
        if not data:
            return jsonify({'error': 'Keine Daten empfangen'}), 400

        try:
            # Angenommen, die Nutzerdaten werden aktualisiert
            # Hier kannst du die Logik zum Speichern der Termine implementieren
            client.update_item("Nutzer", session.get('id'), {"Termine": data})
            
            # Rückmeldung, dass die Daten erfolgreich empfangen wurden
            return jsonify({'success': 'Deine Termine wurden ins Backend geschrieben!'}), 200
        
        except Exception as e:
            return jsonify({'error': str(e)}), 500  # Fehlerbehandlung


@app.template_filter()
def format_datetime_TIMEZONE(value, input_format='%Y-%m-%dT%H:%M:%S.%fZ', output_format='%d.%m.%Y um %H:%M Uhr'):
    try:
        dt = datetime.strptime(value, input_format)  # Verwendung des vollständigen Formats
        return dt.strftime(output_format)
    except ValueError:
        return f"Ungültiges Datum: {value}"

@app.template_filter()
def format_datetime_time(value, input_format='%Y-%m-%dT%H:%M:%S.%fZ', output_format='%d.%m.%Y um %H:%M Uhr'):
    try:
        # Versuche das Datumsformat mit Millisekunden zu parsen
        try:
            dt = datetime.strptime(value, input_format)
        except ValueError:
            # Wenn das Format mit Millisekunden fehlschlägt, versuche es ohne
            dt = datetime.strptime(value, '%Y-%m-%dT%H:%M:%S')
        
        return dt.strftime(output_format)
    except ValueError:
        return f"Ungültiges Datum: {value}"



@app.route('/cockpit/live-chat/anfrage', methods=['POST'])
async def Cockpit_LiveChat_ANFRAGE():
    data = await request.form

    # Extrahiere das Datum und die Uhrzeit
    datum = data.get('Datum')
    uhrzeit = data.get('Uhrzeit')

    timestamp = f"{datum}T{uhrzeit}"  # Format: YYYY-MM-DDTHH:MM

    client.create_item("LiveChats_AUSSTEHEND", {
        "Zeitpunkt": timestamp,
        "Nutzer": {"key": session.get('id'), "collection": "Nutzer"},
        "Thema": data.get('Thema')
    })

    session['success'] = "Deine Anfrage für einen Live-Chat wurde erfolgreich versandt."
    return redirect(f"https://dashboard.{g.whitelabel_info['Domain']}/cockpit/live-chat")

@app.route('/cockpit/live-chat', methods=['GET'])
async def Cockpit_LiveChat():
    success = session.pop('success', None)
    punkte = session.pop('Punkte_Nachricht', None)
    punkte_nachricht = punkte
    error = session.pop('error', None)

    header = await render_template('/parts/Elemente/header.html', url= request.url, 
                                                WhiteLabel=g.whitelabel_info, 
                                                avatar_url=session.get('avatar'), 
                                                rolle=session.get('rolle'), 
                                                name=session.get('name'), Nutzer_Punkte=session.get('Nutzer_Punkte'))
    sidebar = await render_template('/parts/Elemente/sidebar.html', 
                                    WhiteLabel=g.whitelabel_info, rolle=session.get('rolle'))
    footer = await render_template('/parts/Elemente/footer.html', WhiteLabel = g.whitelabel_info, Session_Info=g.Session_Info['LogEntry_ID'], nutzername=session.get('username'), nutzer_ID=session.get('id'))

    theme_customizer = await render_template('/parts/Elemente/theme-customizer.html', 
                                            WhiteLabel=g.whitelabel_info)
    

    live_chats = client.get_items(
        collection_name="LiveChats"
    )

    # Filtere die Live Chats für den aktuellen Nutzer
    live_chats = [chat for chat in live_chats if chat['Nutzer']['key'] == session.get('id')]
    
    # Rendern der Vorschau-HTML-Vorlage mit den erhaltenen Parametern
    return await render_template(f'/parts/Seiten/Cockpit/Live-Chat.html', 
                                header=header,
                                error=error, 
                                success=success, 
                                sidebar=sidebar, 
                                footer=footer, 
                                theme_customizer=theme_customizer,
                                username=session.get('username'), 
                                rolle=session.get('rolle'), 
                                name=session.get('name'), 
                                avatar_url=session.get('avatar'), 
                                WhiteLabel=g.whitelabel_info,
                                live_chats = live_chats)

    
@app.route('/cockpit/live-chat/<ID>', methods=['GET'])
async def Cockpit_LiveChat_DETAILS(ID):
    success = session.pop('success', None)
    punkte = session.pop('Punkte_Nachricht', None)
    punkte_nachricht = punkte
    error = session.pop('error', None)

    header = await render_template('/parts/Elemente/header.html', url= request.url, 
                                                WhiteLabel=g.whitelabel_info, 
                                                avatar_url=session.get('avatar'), 
                                                rolle=session.get('rolle'), 
                                                name=session.get('name'), Nutzer_Punkte=session.get('Nutzer_Punkte'))
    sidebar = await render_template('/parts/Elemente/sidebar.html', 
                                    WhiteLabel=g.whitelabel_info, rolle=session.get('rolle'))
    footer = await render_template('/parts/Elemente/footer.html', WhiteLabel = g.whitelabel_info, Session_Info=g.Session_Info['LogEntry_ID'], nutzername=session.get('username'), nutzer_ID=session.get('id'))

    theme_customizer = await render_template('/parts/Elemente/theme-customizer.html', 
                                            WhiteLabel=g.whitelabel_info)
    

    live_chat = client.get_item(
        collection_name="LiveChats",
        item_id=ID
    )

    if live_chat['Nutzer']['key'] != session.get('id'):
        session['error'] = "Du hast keinen Zugriff auf diesen Live-Chat."
        return redirect(f"https://dashboard.{g.whitelabel_info['Domain']}/cockpit/live-chat")


    
    chat_nachrichten = client.get_items(
        collection_name="Chat_Nachrichten",
        query = {
            "query": {
                "filter": {
                    "Chat": {
                        "id": {
                            "_eq": ID
                        }
                    }
                },
                "sort": "Zeitstempel"  # 'Zeitstempel' durch das entsprechende Zeitfeld ersetze
            }
        }
    )
    print(chat_nachrichten)

    if chat_nachrichten:
        chat_nachrichten = chat_nachrichten
    else:
        chat_nachrichten = None

    chat_nachrichten = [nachricht for nachricht in chat_nachrichten if nachricht['Chat']['key'] == ID]

    nachrichten_sender = set()

    for message in chat_nachrichten:
        nachrichten_sender.add(message['Nutzer']['key'])  # Fügt den Key zur Menge hinzu

    # Umwandlung der Menge in eine Liste, falls benötigt
    nachrichten_sender_list = list(nachrichten_sender)

    sender_liste = []  # Eine leere Liste für die Sender-Infos
    for sender in nachrichten_sender_list:
        infos = client.get_item("Nutzer", sender)
        sender_liste.append(infos)  # Fügt die Infos zur Liste hinzu


    # Create a user map
    user_map = {nutzer['id']: nutzer for nutzer in sender_liste}


    chat_details = {
        "ID": live_chat['id'],
        "Thema": live_chat['Thema'],
        "Zeitpunkt": live_chat['Zeitpunkt'],
        "Nachrichten": chat_nachrichten,
        "Sender_Liste": sender_liste,
        "Nutzer_Map": user_map
    }

    
    # Rendern der Vorschau-HTML-Vorlage mit den erhaltenen Parametern
    return await render_template(f'/parts/Seiten/Cockpit/Live-Chat_DETAILS.html', 
                                header=header,
                                error=error, 
                                success=success, 
                                sidebar=sidebar, 
                                footer=footer, 
                                theme_customizer=theme_customizer,
                                username=session.get('username'), 
                                rolle=session.get('rolle'), 
                                name=session.get('name'), 
                                avatar_url=session.get('avatar'), 
                                WhiteLabel=g.whitelabel_info,
                                chat_details = chat_details,
                                Nutzer_ID = session.get('id'))


# Logging konfigurieren
logging.basicConfig(level=logging.INFO)

websocket_rooms = defaultdict(set)
online_users = {}

def server_process(queue):
    global online_users
    while True:
        data = queue.get()  # Warte auf eine Nachricht
        if data['action'] == 'exit':  # Beenden, wenn die Exit-Nachricht empfangen wird
            break
        elif data['action'] == 'add':
            online_users[data['user_id']] = data['user_data']
        elif data['action'] == 'remove' and data['user_id'] in online_users:
            del online_users[data['user_id']]
        print(online_users)

async def send_task(ws, queue, id, user_id):
    while True:
        message = await queue.get()
        try:
            await ws.send(message)
        except Exception as e:
            print(f"Fehler beim Senden der Nachricht an Benutzer-ID {user_id} in Ticket {id}: {e}")
            break

async def get_current_time():
    time_zone = pytz.timezone('Europe/Berlin')
    now = datetime.now(time_zone)
    formatted_time = now.strftime('%I:%M %p')
    return now

@app.websocket("/cockpit/ws/live-chat/<id>")
async def ws(id):
    global websocket_rooms, online_users
    queue = asyncio.Queue()

    
    user_id = session.get('id')  # ID des Benutzers abrufen

    # Initialisieren des Benutzers im websocket_rooms, wenn noch nicht vorhanden
    if id not in websocket_rooms:
        websocket_rooms[id] = {}

    websocket_rooms[id][user_id] = queue

    task = None

    if id not in online_users:
        online_users[id] = set()

    if user_id:  # Überprüfe, ob die Benutzer-ID vorhanden ist, bevor du sie hinzufügst
        online_users[id].add(user_id)
        print(f"#### Online in Live-Chat #{id}: {online_users[id]} ####")
    else:
        print("Keine Benutzer-ID in der Session gefunden.")

    try:
        task = asyncio.ensure_future(send_task(websocket._get_current_object(), queue, id, user_id))
        while True:
            try:
                message = await websocket.receive()

                message_data = {
                    "Nachricht": message,
                    "Sender": {
                        "Nutzer_ID": user_id,
                        "Name": f"{session.get('vorname')} {session.get('nachname')}",
                        "Avatar": session.get('avatar'),
                        "Rolle": session.get('rolle')['Bezeichnung']
                    }
                }
                
                if message_data['Nachricht'] != "Keep alive":
                    if message_data['Nachricht'] == "<<< CLOSE >>>":
                        client.delete_item('LiveChats', id)
                    else:
                        item_data = {
                            "Chat": {"key":f"{id}","collection":"LiveChats"},
                            "Nutzer": {"key":f"{user_id}","collection":"Nutzer"},
                            "Nachricht": f"{message}"
                        }
                        client.create_item("Chat_Nachrichten", item_data=item_data)

                        print(message_data['Sender']['Name'] + " hat die Nachricht '" + message + f"' im Chat #{id} gesendet.")
                        # Nachrichten an andere Queues im selben Raum senden
                        for user, user_queue in websocket_rooms[id].items():
                            if user != user_id:
                                await user_queue.put(json.dumps(message_data))
                else:
                    print("Keep Alive")
                    keep_alive_message = json.dumps({"Nachricht": "Keep alive"})
                    await queue.put(keep_alive_message)
            except Exception as e:
                print(f"Ein Fehler ist aufgetreten: {e}")
                break

    finally:
        print(f"Vor dem Entfernen: {online_users[id]}")
        online_users[id] = {user for user in online_users[id] if user != user_id}
        print(f"{user_id} wurde aus online_users entfernt.")
        print(f"NACH dem Entfernen: {online_users.get(id, 'N/A')}")

        if id in websocket_rooms and user_id in websocket_rooms[id]:
            del websocket_rooms[id][user_id]
            print(user_id, " hat die Verbindung getrennt.")
            if not websocket_rooms[id]:  # Wenn keine Benutzer mehr im Raum sind, entferne den Raum
                del websocket_rooms[id]

    if task:
        task.cancel()
        await task

import aiofiles
import tempfile

@app.route('/upload', methods=['POST'])
async def upload_file():
    files = await request.files
    whitelabel_id = session.get('WhiteLabel_Admin')['id']

    # Hilfsfunktion zum temporären Speichern der Datei
    async def save_temp_file(file_storage):
        # Erstelle eine temporäre Datei
        temp_file = tempfile.NamedTemporaryFile(delete=False)  # delete=False, um die Datei nach dem Schließen zu behalten
        try:
            # Schreibe den Inhalt der hochgeladenen Datei in die temporäre Datei
            temp_file.write(file_storage.read())  # Keine await hier, da es synchron ist
            temp_file.close()  # Schließe die Datei
            return temp_file.name  # Gibt den Pfad zur temporären Datei zurück
        except Exception as e:
            temp_file.close()
            os.remove(temp_file.name)  # Lösche die temporäre Datei im Fehlerfall
            raise e

    new_file_storage = files['file']
    
    # Speichern der Datei temporär
    temp_file_path = await save_temp_file(new_file_storage)  

    # Neue Datei hochladen
    upload_data = {
        "title": new_file_storage.filename,
        "type": new_file_storage.content_type  # MIME-Typ hinzufügen
    }

    # Hochladen der Datei zu Directus
    try:
        uploaded_file = client.upload_file(temp_file_path, upload_data)  # Stellen Sie sicher, dass dies asynchron ist
        new_file_id = uploaded_file['id']  # Neuen File-ID speichern
        return jsonify({'success': True, 'data': new_file_id}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        # Löschen der temporären Datei, egal ob der Upload erfolgreich war oder nicht
        if os.path.exists(temp_file_path):
            os.remove(temp_file_path)




@app.route('/cockpit/buchhaltung/übersicht/<Typ>', methods=['GET'])
async def COCKPIT_Buchhaltung_Übersicht(Typ):
    Nutzer_Details = {}

    # Die Items von der Collection "Nutzer" abrufen
    try:
        data = client.get_item("Nutzer", item_id=session.get('id'))

        print(data)
        if 'error' in data:
            Nutzer_Details = {}
            print(f"Fehler: {data['error']}")
        else:
            if data:  # Überprüfen, ob Daten vorhanden sind
                Nutzer_Details = data  # Speichere die Whitelabel-Informationen in g
                print(f"Nutzer-Details: {Nutzer_Details}")
            else:
                Nutzer_Details = {}
                print(f"Fehler beim Abruf der Nutzer.")
    except Exception as e:
        print(f"Fehler beim Abrufen der Daten: {e}")
    
    if Typ == "rechnungen":
        try:
            data = client.get_items("Rechnungen")
            if 'error' in data:
                rechnungen = []
                print(f"Fehler: {data['error']}")
            else:
                # Filtern und eine Liste erstellen mit den passenden Rechnungen
                rechnungen = [
                    rechnungs_item for rechnungs_item in data 
                    if rechnungs_item.get('WhiteLabel', {}).get('key') == int(g.whitelabel_info['id'])
                ]
                
                if not rechnungen:
                    print(f"Keine Rechnungen für das angegebene WhiteLabel (#{session.get('WhiteLabel_Admin')['id']}) gefunden.")
        except Exception as e:
            print(f"Fehler beim Abrufen der Daten: {e}")
        i = 0

        filtered_rechnungen = []

        for rechnungs_item in rechnungen:
            i += 1
            rechnungs_item['WhiteLabel_RechnungsID'] = i
            
            if rechnungs_item['Nutzer']['key'] == int(session.get('id')):
                rechnungs_item['Nutzer-Details'] = Nutzer_Details

                # Fälligkeitsdatum in ein Datum-Objekt umwandeln
                faelligkeitsdatum = datetime.strptime(rechnungs_item['Faelligkeitsdatum'], "%Y-%m-%d").date()
                
                if rechnungs_item['Status'] != "Bezahlt":
                    # Überprüfung, ob die Rechnung überfällig ist
                    if faelligkeitsdatum < datetime.now().date():
                        rechnungs_item['Status'] = "Überfällig"

                gesamtbetrag = 0.00
                # Berechnung des Gesamtbetrags
                for item in rechnungs_item['Items']:
                    gesamtbetrag += float(item['Preis']) * int(item['Anzahl'])

                rechnungs_item['Preise'] = {}
                rechnungs_item['Preise']['Zwischensumme'] = gesamtbetrag
                
                # Annahme: Der Steuerbetrag ist in Prozent angegeben (z. B. 19%)
                steuerbetrag = 0  # Beispielwert für die Steuer (19% oder eine andere)
                
                # Berechnung des Steuerbetrags
                rechnungs_item['Preise']['Steuer'] = (steuerbetrag * gesamtbetrag) / 100

                # Berechnung des Gesamtbetrags
                rechnungs_item['Preise']['Gesamt'] = rechnungs_item['Preise']['Steuer'] + gesamtbetrag
        
                # Füge den gefilterten Eintrag der neuen Liste hinzu
                filtered_rechnungen.append(rechnungs_item)

                



        print(g.whitelabel_info)

        success = session.pop('success', None)
        punkte = session.pop('Punkte_Nachricht', None)
        punkte_nachricht = punkte
        error = session.pop('error', None)
        
        header = await render_template('/parts/Elemente/header.html', url= request.url, WhiteLabel = g.whitelabel_info, avatar_url=session.get('avatar'), rolle=session.get('rolle'), name=session.get('name'), Nutzer_Punkte=session.get('Nutzer_Punkte'))
        sidebar = await render_template('/parts/Elemente/sidebar.html', WhiteLabel = g.whitelabel_info, rolle=session.get('rolle'))
        footer = await render_template('/parts/Elemente/footer.html', WhiteLabel = g.whitelabel_info, Session_Info=g.Session_Info['LogEntry_ID'], nutzername=session.get('username'), nutzer_ID=session.get('id'))
        theme_customizer = await render_template('/parts/Elemente/theme-customizer.html', WhiteLabel = g.whitelabel_info)

        WhiteLabel_Admin_Content = client.get_item(collection_name='WhiteLabel', item_id=f'{session.get('WhiteLabel_Admin')['id']}')

        if WhiteLabel_Admin_Content['id'] != g.whitelabel_info['id']:
            session['error'] = f"Du hast leider keinen Zugriff auf die Buchhaltung der WhiteLabel-Instanz '{g.whitelabel_info['Bezeichnung']}'."
            return redirect(f"https://dashboard.{g.whitelabel_info['Domain']}")

        quickStart_TAB = request.args.get('quickstart')

        return await render_template('/parts/Seiten/Cockpit/Buchhaltung/Übersicht_Rechnung.html', header=header, sidebar=sidebar, footer=footer, theme_customizer=theme_customizer, success=success, error=error, punkte = punkte, punkte_nachricht = punkte_nachricht, username=session.get('username'), rolle=session.get('rolle'), name=session.get('name'), avatar_url=session.get('avatar'), WhiteLabel = WhiteLabel_Admin_Content, quickStart_TAB=quickStart_TAB, rechnungs_liste=filtered_rechnungen)

    elif Typ == "angebote":
        try:
            data = client.get_items("Angebote")
            if 'error' in data:
                rechnungen = []
                print(f"Fehler: {data['error']}")
            else:
                # Filtern und eine Liste erstellen mit den passenden Rechnungen
                rechnungen = [
                    rechnungs_item for rechnungs_item in data 
                    if rechnungs_item.get('WhiteLabel', {}).get('key') == int(g.whitelabel_info['id'])
                ]
                
                if not rechnungen:
                    print(f"Keine Rechnungen für das angegebene WhiteLabel (#{session.get('WhiteLabel_Admin')['id']}) gefunden.")
        except Exception as e:
            print(f"Fehler beim Abrufen der Daten: {e}")
        i = 0

        filtered_angebote = []

        for rechnungs_item in rechnungen:
            i += 1
            rechnungs_item['WhiteLabel_AngebotsID'] = i
            
            if rechnungs_item['Nutzer']['key'] == int(session.get('id')):
                rechnungs_item['Nutzer-Details'] = Nutzer_Details

                # Fälligkeitsdatum in ein Datum-Objekt umwandeln
                faelligkeitsdatum = datetime.strptime(rechnungs_item['Gueltigkeitsdatum'], "%Y-%m-%d").date()
                
                if rechnungs_item['Status'] != "Bezahlt":
                    # Überprüfung, ob die Rechnung überfällig ist
                    if faelligkeitsdatum < datetime.now().date():
                        rechnungs_item['Status'] = "Überfällig"

                gesamtbetrag = 0.00
                # Berechnung des Gesamtbetrags
                for item in rechnungs_item['Items']:
                    gesamtbetrag += float(item['Preis']) * int(item['Anzahl'])

                rechnungs_item['Preise'] = {}
                rechnungs_item['Preise']['Zwischensumme'] = gesamtbetrag
                
                # Annahme: Der Steuerbetrag ist in Prozent angegeben (z. B. 19%)
                steuerbetrag = 0  # Beispielwert für die Steuer (19% oder eine andere)
                
                # Berechnung des Steuerbetrags
                rechnungs_item['Preise']['Steuer'] = (steuerbetrag * gesamtbetrag) / 100

                # Berechnung des Gesamtbetrags
                rechnungs_item['Preise']['Gesamt'] = rechnungs_item['Preise']['Steuer'] + gesamtbetrag
        
                # Füge den gefilterten Eintrag der neuen Liste hinzu
                filtered_angebote.append(rechnungs_item)

                



        print(g.whitelabel_info)

        success = session.pop('success', None)
        punkte = session.pop('Punkte_Nachricht', None)
        punkte_nachricht = punkte
        error = session.pop('error', None)
        
        header = await render_template('/parts/Elemente/header.html', url= request.url, WhiteLabel = g.whitelabel_info, avatar_url=session.get('avatar'), rolle=session.get('rolle'), name=session.get('name'), Nutzer_Punkte=session.get('Nutzer_Punkte'))
        sidebar = await render_template('/parts/Elemente/sidebar.html', WhiteLabel = g.whitelabel_info, rolle=session.get('rolle'))
        footer = await render_template('/parts/Elemente/footer.html', WhiteLabel = g.whitelabel_info, Session_Info=g.Session_Info['LogEntry_ID'], nutzername=session.get('username'), nutzer_ID=session.get('id'))
        theme_customizer = await render_template('/parts/Elemente/theme-customizer.html', WhiteLabel = g.whitelabel_info)

        WhiteLabel_Admin_Content = client.get_item(collection_name='WhiteLabel', item_id=f'{session.get('WhiteLabel_Admin')['id']}')

        if WhiteLabel_Admin_Content['id'] != g.whitelabel_info['id']:
            session['error'] = f"Du hast leider keinen Zugriff auf die Buchhaltung der WhiteLabel-Instanz '{g.whitelabel_info['Bezeichnung']}'."
            return redirect(f"https://dashboard.{g.whitelabel_info['Domain']}")

        quickStart_TAB = request.args.get('quickstart')

        return await render_template('/parts/Seiten/Cockpit/Buchhaltung/Übersicht_Angebot.html', header=header, sidebar=sidebar, footer=footer, theme_customizer=theme_customizer, success=success, error=error, punkte = punkte, punkte_nachricht = punkte_nachricht, username=session.get('username'), rolle=session.get('rolle'), name=session.get('name'), avatar_url=session.get('avatar'), WhiteLabel = WhiteLabel_Admin_Content, quickStart_TAB=quickStart_TAB, rechnungs_liste=filtered_angebote)

    else:
        return redirect("https://dashboard.personalpeak360.de/cockpit/buchhaltung/übersicht/rechnungen")
import string

@app.route('/cockpit/buchhaltung/<Art>/<Aktion>/<ID>', methods=['GET','POST'])
async def COCKPIT_Buchhaltung_Details(Art, Aktion, ID):
    if Art == "rechnung":
        if Aktion == "details":
            rechnungs_item = await getInvoice_FROM_WhiteLabelInvoiceID(ID)

            if rechnungs_item == "Not_Found":    
                session['error'] = f"Die Rechnung mit der Whitelabel-Rechnungsnummer #{ID} konnte nicht gefunden werden."
                return redirect(f"https://dashboard.{g.whitelabel_info['Domain']}/admin/buchhaltung/übersicht/rechnungen")

            print(g.whitelabel_info)

            heute = datetime.now().strftime('%Y-%m-%d')

            success = session.pop('success', None)
            punkte = session.pop('Punkte_Nachricht', None)
            punkte_nachricht = punkte
            error = session.pop('error', None)
            
            header = await render_template('/parts/Elemente/header.html', url= request.url, WhiteLabel = g.whitelabel_info, avatar_url=session.get('avatar'), rolle=session.get('rolle'), name=session.get('name'), Nutzer_Punkte=session.get('Nutzer_Punkte'))
            sidebar = await render_template('/parts/Elemente/sidebar.html', WhiteLabel = g.whitelabel_info, rolle=session.get('rolle'))
            footer = await render_template('/parts/Elemente/footer.html', WhiteLabel = g.whitelabel_info, Session_Info=g.Session_Info['LogEntry_ID'], nutzername=session.get('username'), nutzer_ID=session.get('id'))
            theme_customizer = await render_template('/parts/Elemente/theme-customizer.html', WhiteLabel = g.whitelabel_info)

            WhiteLabel_Admin_Content = client.get_item(collection_name='WhiteLabel', item_id=f'{session.get('WhiteLabel_Admin')['id']}')

            if WhiteLabel_Admin_Content['id'] != g.whitelabel_info['id']:
                session['error'] = f"Du hast leider keinen Zugriff auf die Buchhaltung der WhiteLabel-Instanz '{g.whitelabel_info['Bezeichnung']}'."
                return redirect(f"https://dashboard.{g.whitelabel_info['Domain']}")
            
            if request.args.get('callback') == "true":
                interne_id = request.args.get('interneID')
                query = {
                    "query": {
                        "filter": {
                            "UUID": {
                                "_eq": interne_id
                            }
                        },
                        "limit": 2000
                    }
                }
                daten = client.get_items('Rechnungen_Zahlungen', query)

                mollie_id = daten[0]['Mollie_ID']
            else:
                mollie_id = None

            return await render_template('/parts/Seiten/Cockpit/Buchhaltung/Rechnung.html', header=header, sidebar=sidebar, footer=footer, theme_customizer=theme_customizer, success=success, error=error, punkte = punkte, punkte_nachricht = punkte_nachricht, username=session.get('username'), rolle=session.get('rolle'), name=session.get('name'), avatar_url=session.get('avatar'), WhiteLabel = WhiteLabel_Admin_Content, rechnung=rechnungs_item, heute=heute, callback = request.args.get('callback'), mollieid = mollie_id)
        elif Aktion == "bezahlen":
            if request.args.get('cancel'):
                session['error'] = f"Die Bezahlung für die Rechnung #{ID} wurde abgebrochen."
                return redirect(f"https://dashboard.{g.whitelabel_info['Domain']}/cockpit/buchhaltung/rechnung/details/{ID}")

            rechnungs_item = await getInvoice_FROM_WhiteLabelInvoiceID(ID)
            
            zahlungsID_intern = ''.join(random.choices(string.ascii_letters + string.digits, k=10)) # Ebenfalls in Directus
            paymentID_INtern = f"zahlung_{zahlungsID_intern}"

            # return jsonify(rechnungs_item)
            payment = mollie_client.payments.create(
                {
                    "amount": {"currency": "EUR", "value": f"{round(rechnungs_item['Preise']['Gesamt'], 2):.2f}"},
                    "description": f"Bezahlung für Rechnung #{ID}",
                    "webhookUrl": f"https://dashboard.{g.whitelabel_info['Domain']}/cockpit/buchhaltung/rechnung/details/{ID}?callback=true&interneID={paymentID_INtern}",
                    "redirectUrl": f"https://dashboard.{g.whitelabel_info['Domain']}/cockpit/buchhaltung/rechnung/details/{ID}?callback=true&interneID={paymentID_INtern}",
                    "metadata": {"Rechnung": str(ID)},
                    "method": f"",
                    "cancelUrl": f"https://dashboard.{g.whitelabel_info['Domain']}/cockpit/buchhaltung/rechnung/bezahlen/{ID}?cancel=True",
                }
            )

            checkout_url = payment.checkout_url
            order_id = payment.id

            body = {
                'Rechnung': {"key": int(rechnungs_item['id']), "collection": "Rechnung"},
                'UUID': paymentID_INtern,
                'Mollie_ID': order_id,
                'Checkout_URL': checkout_url,
            }
            # Eintrag der Zahlung
            client.create_item("Rechnungen_Zahlungen", body)

            return redirect(checkout_url)
        elif Aktion == "generate_PDF":
            rechnungs_item = await getInvoice_FROM_WhiteLabelInvoiceID(ID)

            nutzer_data = {
                "Vorname": rechnungs_item['Nutzer-Details']['Vorname'],
                "Nachname": rechnungs_item['Nutzer-Details']['Nachname'],
                "ID": "Nicht vorhanden"
            }

            adresse = {
                "Strasse": rechnungs_item['Nutzer-Details']['Strasse'],
                "Hausnummer": rechnungs_item['Nutzer-Details']['Hausnummer'],
                "PLZ": rechnungs_item['Nutzer-Details']['PLZ'],
                "Ort": rechnungs_item['Nutzer-Details']['Ort'],
            }

            steuersatz = rechnungs_item['Steuersatz']

            if rechnungs_item['Status'] == "Bezahlt":
                bezahlterBetrag = rechnungs_item['Preise']['Gesamt']
            else:
                bezahlterBetrag = 0

            if rechnungs_item['WhiteLabel-Details']['KleinunternehmerRegelung']:
                notes_base = "Im Sinne der Kleinunternehmerregelung nach § 19 UStG enthält der ausgewiesene Betrag keine Umsatzsteuer."
                notes = f"{rechnungs_item['Anmerkung_Oeffentlich']}\n\n{notes_base}" if rechnungs_item['Anmerkung_Oeffentlich'] else notes_base

                payload = {
                    "header": "RECHNUNG",
                    "currency": "EUR",
                    "tax_title": "Steuer",
                    "fields[tax]": "%",
                    "tax": steuersatz,
                    "notes_title": "Hinweise & Anmerkungen",
                    "payment_terms_title": "Fälligkeitsdatum",
                    "to_title": "Rechnungsempfänger",
                    "balance_title": "Offener Betrag",

                    "custom_fields[1][name]": "Status",
                    "custom_fields[1][value]": rechnungs_item['Status'],

                    "shipping": 0,
                    "amount_paid": bezahlterBetrag,
                    "discounts": 0,

                    "from": f"{rechnungs_item['WhiteLabel-Details']['Firmenname']}\n{rechnungs_item['WhiteLabel-Details']['Strasse']} {rechnungs_item['WhiteLabel-Details']['Hausnummer']}\n{rechnungs_item['WhiteLabel-Details']['PLZ']} {rechnungs_item['WhiteLabel-Details']['Ort']}\nDeutschland\nUSt-IdNr: {rechnungs_item['WhiteLabel-Details']['UmsatzsteuerID']}",
                    "to": f"{nutzer_data['Vorname']} {nutzer_data['Nachname']}\n{adresse['Strasse']} {adresse['Hausnummer']}\n{adresse['PLZ']} {adresse['Ort']}\nDeutschland",
                    "logo": f"https://cdn.personalpeak360.de/white-label/{ rechnungs_item['WhiteLabel-Details']['Logo_lang'] }",
                    "number": rechnungs_item['WhiteLabel_RechnungsID'],
                    "date": format_datetime(rechnungs_item['Rechnungsdatum'], '%Y-%m-%d', '%d.%m.%Y'),
                    "payment_terms": format_datetime(rechnungs_item['Faelligkeitsdatum'], '%Y-%m-%d', '%d.%m.%Y'),
                    "notes": notes,
                    "terms": f"Bitte begleichen Sie den Rechnungsbetrag in Höhe von {f'{rechnungs_item['Preise']['Gesamt']:.2f}'.replace('.', ',')} € bis zum {format_datetime(rechnungs_item['Faelligkeitsdatum'], '%Y-%m-%d', '%d.%m.%Y')} über den Cockpit-Bereich im Dashboard."
                }
            else:
                notes = f"{rechnungs_item['Anmerkung_Oeffentlich']}\n\n{notes_base}" if rechnungs_item['Anmerkung_Oeffentlich'] else None
                if notes:
                    payload = {
                        "header": "RECHNUNG",
                        "currency": "EUR",
                        "tax_title": "Steuer",
                        "fields[tax]": "%",
                        "tax": steuersatz,
                        "notes_title": "Hinweise & Anmerkungen",
                        "payment_terms_title": "Fälligkeitsdatum",
                        "to_title": "Rechnungsempfänger",
                        "balance_title": "Offener Betrag",

                        "custom_fields[1][name]": "Status",
                        "custom_fields[1][value]": rechnungs_item['Status'],

                        "shipping": 0,
                        "amount_paid": bezahlterBetrag,
                        "discounts": 0,

                        "from": f"{rechnungs_item['WhiteLabel-Details']['Firmenname']}\n{rechnungs_item['WhiteLabel-Details']['Strasse']} {rechnungs_item['WhiteLabel-Details']['Hausnummer']}\n{rechnungs_item['WhiteLabel-Details']['PLZ']} {rechnungs_item['WhiteLabel-Details']['Ort']}\nDeutschland\nUSt-IdNr: {rechnungs_item['WhiteLabel-Details']['UmsatzsteuerID']}",
                        "to": f"{nutzer_data['Vorname']} {nutzer_data['Nachname']}\n{adresse['Strasse']} {adresse['Hausnummer']}\n{adresse['PLZ']} {adresse['Ort']}\nDeutschland",
                        "logo": f"https://cdn.personalpeak360.de/white-label/{ rechnungs_item['WhiteLabel-Details']['Logo_lang'] }",
                        "number": rechnungs_item['WhiteLabel_RechnungsID'],
                        "date": format_datetime(rechnungs_item['Rechnungsdatum'], '%Y-%m-%d', '%d.%m.%Y'),
                        "payment_terms": format_datetime(rechnungs_item['Faelligkeitsdatum'], '%Y-%m-%d', '%d.%m.%Y'),
                        "notes": notes,
                        "terms": f"Bitte begleichen Sie den Rechnungsbetrag in Höhe von {f'{rechnungs_item['Preise']['Gesamt']:.2f}'.replace('.', ',')} € bis zum {format_datetime(rechnungs_item['Faelligkeitsdatum'], '%Y-%m-%d', '%d.%m.%Y')} über den Cockpit-Bereich im Dashboard."
                    }
                else:
                    payload = {
                        "header": "RECHNUNG",
                        "currency": "EUR",
                        "tax_title": "Steuer",
                        "fields[tax]": "%",
                        "tax": steuersatz,
                        "notes_title": "Hinweise & Anmerkungen",
                        "payment_terms_title": "Fälligkeitsdatum",
                        "to_title": "Rechnungsempfänger",
                        "balance_title": "Offener Betrag",

                        "custom_fields[1][name]": "Status",
                        "custom_fields[1][value]": rechnungs_item['Status'],

                        "shipping": 0,
                        "amount_paid": bezahlterBetrag,
                        "discounts": 0,

                        "from": f"{rechnungs_item['WhiteLabel-Details']['Firmenname']}\n{rechnungs_item['WhiteLabel-Details']['Strasse']} {rechnungs_item['WhiteLabel-Details']['Hausnummer']}\n{rechnungs_item['WhiteLabel-Details']['PLZ']} {rechnungs_item['WhiteLabel-Details']['Ort']}\nDeutschland\nUSt-IdNr: {rechnungs_item['WhiteLabel-Details']['UmsatzsteuerID']}",
                        "to": f"{nutzer_data['Vorname']} {nutzer_data['Nachname']}\n{adresse['Strasse']} {adresse['Hausnummer']}\n{adresse['PLZ']} {adresse['Ort']}\nDeutschland",
                        "logo": f"https://cdn.personalpeak360.de/white-label/{ rechnungs_item['WhiteLabel-Details']['Logo_lang'] }",
                        "number": rechnungs_item['WhiteLabel_RechnungsID'],
                        "date": format_datetime(rechnungs_item['Rechnungsdatum'], '%Y-%m-%d', '%d.%m.%Y'),
                        "payment_terms": format_datetime(rechnungs_item['Faelligkeitsdatum'], '%Y-%m-%d', '%d.%m.%Y'),
                        "terms": f"Bitte begleichen Sie den Rechnungsbetrag in Höhe von {f'{rechnungs_item['Preise']['Gesamt']:.2f}'.replace('.', ',')} € bis zum {format_datetime(rechnungs_item['Faelligkeitsdatum'], '%Y-%m-%d', '%d.%m.%Y')} über den Cockpit-Bereich im Dashboard."
                    }


            item_count = 0
            # Add items to the payload
            for item in rechnungs_item['Items']:

                payload[f"items[{item_count}][name]"] = f"{item['Bezeichnung']}\n{item['Beschreibung']}"
                payload[f"items[{item_count}][quantity]"] = item['Anzahl']
                payload[f"items[{item_count}][unit_cost]"] = item['Preis']
                item_count +=1

            headers = {
                "Authorization": f"Bearer {config['Rechnungs_API']['API_Token']}",
                "Accept-Language": "de-DE"
            }

            response = requests.post(config['Rechnungs_API']['URL'], headers=headers, data=payload)

            if response.status_code == 200:
                # Modify PDF properties
                pdf_content = response.content
                pdf_reader = PdfReader(io.BytesIO(pdf_content))
                pdf_writer = PdfWriter()

                for page in pdf_reader.pages:
                    pdf_writer.add_page(page)

                # Set PDF metadata
                created_date = datetime.now().strftime('D:%Y%m%d%H%M%S')
                pdf_writer.add_metadata({
                    '/Title': f"Rechnung #{rechnungs_item['WhiteLabel_RechnungsID']}",
                    '/Filename': f"Rechnung-{rechnungs_item['WhiteLabel_RechnungsID']}",
                    '/Author': "Wärner Technologie Services",
                    '/Creator': "WTS-Rechnungsprogramm | Version 1.9",
                    '/Producer': "WTS-Generator | Version 1.9",
                    '/Subject': "Rechnung",
                    '/CreationDate': created_date
                })

                output = io.BytesIO()
                pdf_writer.write(output)
                output.seek(0)

                return await send_file(
                    output,
                    mimetype='application/pdf',
                    as_attachment=True,
                    attachment_filename=f"Rechnung #{rechnungs_item['WhiteLabel_RechnungsID']}.pdf"
                )
        elif Aktion == "generate_E-Invoice":
            rechnungs_item = await getInvoice_FROM_WhiteLabelInvoiceID(ID)

            ubl_xml = create_ubl_invoice(rechnungs_item)

            # Gib die XML-Datei als Antwort zurück
            return Response(
                ubl_xml,
                content_type='application/xml',
                headers={
                    "Content-Disposition": f"attachment; filename=Rechnung_{ID}.xml"
                }
            )
        
        else:
            session['error'] = "Die Aktion für Rechnungen war ungültig."
            return redirect(f"https://dashboard.{g.whitelabel_info['Domain']}/admin/buchhaltung/rechnungen")

    elif Art == "angebot":
        if Aktion == "details":
            rechnungs_item = await getAngebot_FROM_WhiteLabelInvoiceID(ID)

            if rechnungs_item == "Not_Found":    
                session['error'] = f"Das Angebot mit der Whitelabel-Angebotsnummer #{ID} konnte nicht gefunden werden."
                return redirect(f"https://dashboard.{g.whitelabel_info['Domain']}/cockpit/buchhaltung/übersicht/angebote")

            print(g.whitelabel_info)

            heute = datetime.now().strftime('%Y-%m-%d')

            success = session.pop('success', None)
            punkte = session.pop('Punkte_Nachricht', None)
            punkte_nachricht = punkte
            error = session.pop('error', None)
            
            header = await render_template('/parts/Elemente/header.html', url= request.url, WhiteLabel = g.whitelabel_info, avatar_url=session.get('avatar'), rolle=session.get('rolle'), name=session.get('name'), Nutzer_Punkte=session.get('Nutzer_Punkte'))
            sidebar = await render_template('/parts/Elemente/sidebar.html', WhiteLabel = g.whitelabel_info, rolle=session.get('rolle'))
            footer = await render_template('/parts/Elemente/footer.html', WhiteLabel = g.whitelabel_info, Session_Info=g.Session_Info['LogEntry_ID'], nutzername=session.get('username'), nutzer_ID=session.get('id'))
            theme_customizer = await render_template('/parts/Elemente/theme-customizer.html', WhiteLabel = g.whitelabel_info)

            WhiteLabel_Admin_Content = client.get_item(collection_name='WhiteLabel', item_id=f'{session.get('WhiteLabel_Admin')['id']}')

            if WhiteLabel_Admin_Content['id'] != g.whitelabel_info['id']:
                session['error'] = f"Du hast leider keinen Zugriff auf die Buchhaltung der WhiteLabel-Instanz '{g.whitelabel_info['Bezeichnung']}'."
                return redirect(f"https://dashboard.{g.whitelabel_info['Domain']}")

            return await render_template('/parts/Seiten/Cockpit/Buchhaltung/Angebot.html', header=header, sidebar=sidebar, footer=footer, theme_customizer=theme_customizer, success=success, error=error, punkte = punkte, punkte_nachricht = punkte_nachricht, username=session.get('username'), rolle=session.get('rolle'), name=session.get('name'), avatar_url=session.get('avatar'), WhiteLabel = WhiteLabel_Admin_Content, rechnung=rechnungs_item, heute=heute)
        elif Aktion == "generate_PDF":
            rechnungs_item = await getAngebot_FROM_WhiteLabelInvoiceID(ID)

            nutzer_data = {
                "Vorname": rechnungs_item['Nutzer-Details']['Vorname'],
                "Nachname": rechnungs_item['Nutzer-Details']['Nachname'],
                "ID": "Nicht vorhanden"
            }

            adresse = {
                "Strasse": rechnungs_item['Nutzer-Details']['Strasse'],
                "Hausnummer": rechnungs_item['Nutzer-Details']['Hausnummer'],
                "PLZ": rechnungs_item['Nutzer-Details']['PLZ'],
                "Ort": rechnungs_item['Nutzer-Details']['Ort'],
            }

            steuersatz = rechnungs_item['Steuersatz']

            if rechnungs_item['Status'] == "Bezahlt":
                bezahlterBetrag = rechnungs_item['Preise']['Gesamt']
            else:
                bezahlterBetrag = 0

            if rechnungs_item['WhiteLabel-Details']['KleinunternehmerRegelung']:
                notes_base = "Im Sinne der Kleinunternehmerregelung nach § 19 UStG enthält der ausgewiesene Betrag keine Umsatzsteuer."
                notes = f"{rechnungs_item['Anmerkung_Oeffentlich']}\n\n{notes_base}" if rechnungs_item['Anmerkung_Oeffentlich'] else notes_base

                payload = {
                    "header": "ANGEBOT",
                    "currency": "EUR",
                    "tax_title": "Steuer",
                    "fields[tax]": "%",
                    "tax": steuersatz,
                    "notes_title": "Hinweise & Anmerkungen",
                    "payment_terms_title": "Gültigkeitsdatum",
                    "to_title": "Angebotsempfänger",
                    "balance_title": "Angebotsbetrag",

                    "custom_fields[1][name]": "Status",
                    "custom_fields[1][value]": rechnungs_item['Status'],

                    "shipping": 0,
                    "amount_paid": bezahlterBetrag,
                    "discounts": 0,

                    "from": f"{rechnungs_item['WhiteLabel-Details']['Firmenname']}\n{rechnungs_item['WhiteLabel-Details']['Strasse']} {rechnungs_item['WhiteLabel-Details']['Hausnummer']}\n{rechnungs_item['WhiteLabel-Details']['PLZ']} {rechnungs_item['WhiteLabel-Details']['Ort']}\nDeutschland\nUSt-IdNr: {rechnungs_item['WhiteLabel-Details']['UmsatzsteuerID']}",
                    "to": f"{nutzer_data['Vorname']} {nutzer_data['Nachname']}\n{adresse['Strasse']} {adresse['Hausnummer']}\n{adresse['PLZ']} {adresse['Ort']}\nDeutschland",
                    "logo": f"https://cdn.personalpeak360.de/white-label/{ rechnungs_item['WhiteLabel-Details']['Logo_lang'] }",
                    "number": rechnungs_item['WhiteLabel_AngebotsID'],
                    "date": format_datetime(rechnungs_item['Angebotsdatum'], '%Y-%m-%d', '%d.%m.%Y'),
                    "payment_terms": format_datetime(rechnungs_item['Gueltigkeitsdatum'], '%Y-%m-%d', '%d.%m.%Y'),
                    "notes": notes,
                    "terms": f"Bitte nehmen oder lehnen Sie dieses Angebot in Höhe von {f'{rechnungs_item['Preise']['Gesamt']:.2f}'.replace('.', ',')} € bis zum {format_datetime(rechnungs_item['Gueltigkeitsdatum'], '%Y-%m-%d', '%d.%m.%Y')} über den Cockpit-Bereich im Dashboard an oder ab."
                }
            else:
                notes = f"{rechnungs_item['Anmerkung_Oeffentlich']}\n\n{notes_base}" if rechnungs_item['Anmerkung_Oeffentlich'] else None
                if notes:
                    payload = {
                        "header": "ANGEBOT",
                        "currency": "EUR",
                        "tax_title": "Steuer",
                        "fields[tax]": "%",
                        "tax": steuersatz,
                        "notes_title": "Hinweise & Anmerkungen",
                        "payment_terms_title": "Gültigkeitsdatum",
                        "to_title": "Angebotsempfänger",
                        "balance_title": "Angebotsbetrag",

                        "custom_fields[1][name]": "Status",
                        "custom_fields[1][value]": rechnungs_item['Status'],

                        "shipping": 0,
                        "amount_paid": bezahlterBetrag,
                        "discounts": 0,

                        "from": f"{rechnungs_item['WhiteLabel-Details']['Firmenname']}\n{rechnungs_item['WhiteLabel-Details']['Strasse']} {rechnungs_item['WhiteLabel-Details']['Hausnummer']}\n{rechnungs_item['WhiteLabel-Details']['PLZ']} {rechnungs_item['WhiteLabel-Details']['Ort']}\nDeutschland\nUSt-IdNr: {rechnungs_item['WhiteLabel-Details']['UmsatzsteuerID']}",
                        "to": f"{nutzer_data['Vorname']} {nutzer_data['Nachname']}\n{adresse['Strasse']} {adresse['Hausnummer']}\n{adresse['PLZ']} {adresse['Ort']}\nDeutschland",
                        "logo": f"https://cdn.personalpeak360.de/white-label/{ rechnungs_item['WhiteLabel-Details']['Logo_lang'] }",
                        "number": rechnungs_item['WhiteLabel_AngebotsID'],
                        "date": format_datetime(rechnungs_item['Angebotsdatum'], '%Y-%m-%d', '%d.%m.%Y'),
                        "payment_terms": format_datetime(rechnungs_item['Gueltigkeitsdatum'], '%Y-%m-%d', '%d.%m.%Y'),
                        "notes": notes,
                        "terms": f"Bitte nehmen oder lehnen Sie dieses Angebot in Höhe von {f'{rechnungs_item['Preise']['Gesamt']:.2f}'.replace('.', ',')} € bis zum {format_datetime(rechnungs_item['Gueltigkeitsdatum'], '%Y-%m-%d', '%d.%m.%Y')} über den Cockpit-Bereich im Dashboard an oder ab."
                    }
                else:
                    payload = {
                        "header": "ANGEBOT",
                        "currency": "EUR",
                        "tax_title": "Steuer",
                        "fields[tax]": "%",
                        "tax": steuersatz,
                        "notes_title": "Hinweise & Anmerkungen",
                        "payment_terms_title": "Gültigkeitsdatum",
                        "to_title": "Angebotsempfänger",
                        "balance_title": "Angebotsbetrag",

                        "custom_fields[1][name]": "Status",
                        "custom_fields[1][value]": rechnungs_item['Status'],

                        "shipping": 0,
                        "amount_paid": bezahlterBetrag,
                        "discounts": 0,

                        "from": f"{rechnungs_item['WhiteLabel-Details']['Firmenname']}\n{rechnungs_item['WhiteLabel-Details']['Strasse']} {rechnungs_item['WhiteLabel-Details']['Hausnummer']}\n{rechnungs_item['WhiteLabel-Details']['PLZ']} {rechnungs_item['WhiteLabel-Details']['Ort']}\nDeutschland\nUSt-IdNr: {rechnungs_item['WhiteLabel-Details']['UmsatzsteuerID']}",
                        "to": f"{nutzer_data['Vorname']} {nutzer_data['Nachname']}\n{adresse['Strasse']} {adresse['Hausnummer']}\n{adresse['PLZ']} {adresse['Ort']}\nDeutschland",
                        "logo": f"https://cdn.personalpeak360.de/white-label/{ rechnungs_item['WhiteLabel-Details']['Logo_lang'] }",
                        "number": rechnungs_item['WhiteLabel_AngebotsID'],
                        "date": format_datetime(rechnungs_item['Angebotsdatum'], '%Y-%m-%d', '%d.%m.%Y'),
                        "payment_terms": format_datetime(rechnungs_item['Gueltigkeitsdatum'], '%Y-%m-%d', '%d.%m.%Y'),
                        "terms": f"Bitte nehmen oder lehnen Sie dieses Angebot in Höhe von {f'{rechnungs_item['Preise']['Gesamt']:.2f}'.replace('.', ',')} € bis zum {format_datetime(rechnungs_item['Gueltigkeitsdatum'], '%Y-%m-%d', '%d.%m.%Y')} über den Cockpit-Bereich im Dashboard an oder ab."
                    }


            item_count = 0
            # Add items to the payload
            for item in rechnungs_item['Items']:

                payload[f"items[{item_count}][name]"] = f"{item['Bezeichnung']}\n{item['Beschreibung']}"
                payload[f"items[{item_count}][quantity]"] = item['Anzahl']
                payload[f"items[{item_count}][unit_cost]"] = item['Preis']
                item_count +=1

            headers = {
                "Authorization": f"Bearer {config['Rechnungs_API']['API_Token']}",
                "Accept-Language": "de-DE"
            }

            response = requests.post(config['Rechnungs_API']['URL'], headers=headers, data=payload)

            if response.status_code == 200:
                # Modify PDF properties
                pdf_content = response.content
                pdf_reader = PdfReader(io.BytesIO(pdf_content))
                pdf_writer = PdfWriter()

                for page in pdf_reader.pages:
                    pdf_writer.add_page(page)

                # Set PDF metadata
                created_date = datetime.now().strftime('D:%Y%m%d%H%M%S')
                pdf_writer.add_metadata({
                    '/Title': f"Angebot #{rechnungs_item['WhiteLabel_AngebotsID']}",
                    '/Filename': f"Angebot-{rechnungs_item['WhiteLabel_AngebotsID']}",
                    '/Author': "Wärner Technologie Services",
                    '/Creator': "WTS-Rechnungsprogramm | Version 1.9",
                    '/Producer': "WTS-Generator | Version 1.9",
                    '/Subject': "Angebot",
                    '/CreationDate': created_date
                })
 
                output = io.BytesIO()
                pdf_writer.write(output)
                output.seek(0)

                return await send_file(
                    output,
                    mimetype='application/pdf',
                    as_attachment=True,
                    attachment_filename=f"Angebot #{rechnungs_item['WhiteLabel_AngebotsID']}.pdf"
                )
        elif Aktion == "annehmen":
            WhiteLabel_Rechnung_ID = request.args.get('WL_ID')
            client.update_item("Angebote", ID, {"Status": "Angenommen"})

            session['success'] = f"Das Angebot #{WhiteLabel_Rechnung_ID} wurde erfolgreich angenommen."
            return redirect(f"https://dashboard.{g.whitelabel_info['Domain']}/cockpit/buchhaltung/angebot/details/{WhiteLabel_Rechnung_ID}")
        
        elif Aktion == "ablehnen":
            WhiteLabel_Rechnung_ID = request.args.get('WL_ID')
            client.update_item("Angebote", ID, {"Status": "Abgelehnt"})

            session['success'] = f"Das Angebot #{WhiteLabel_Rechnung_ID} wurde erfolgreich abgelehnt."
            return redirect(f"https://dashboard.{g.whitelabel_info['Domain']}/cockpit/buchhaltung/angebot/details/{WhiteLabel_Rechnung_ID}")
        else:
            session['error'] = "Die Aktion für Angebote war ungültig."
            return redirect(f"https://dashboard.{g.whitelabel_info['Domain']}/cockpit/buchhaltung/angebote")
    else:
        session['error'] = "Die Aktion für Rechnungen war ungültig."
        return redirect(f"https://dashboard.{g.whitelabel_info['Domain']}/cockpit/buchhaltung/rechnungen")
    
@app.route('/webhook/<payment_ID>', methods=['POST'])
async def webhook(payment_ID):
    data = await request.form
    payment_id = data.get("id")

    try:
        payment = mollie_client.payments.get(payment_ID)
        if payment.is_paid() or payment.is_authorized():
            status = "paid"
        elif payment.is_created():
            status = "wait"
        else:
            status = "failed"
    except Exception as e:
        status = "failed"

    return jsonify({"status": status})

@app.route('/buchhaltung/rechnung/<id>/erfolgreichBezahlt/<orderID>', methods=['GET'])
async def render_buchhaltung_rechnung_erfolgreichBezahlt(id, orderID):
    payment = mollie_client.payments.get(orderID)
    WhiteLabel_ID = request.args.get('WL_ID')
    
    query = {
        "query": {
            "filter": {
                "Mollie_ID": {
                    "_eq": orderID
                }
            },
            "limit": 1
        }
    }
    zahlungen = client.get_items('Rechnungen_Zahlungen', query)

    if zahlungen:  # 'data' enthält die Ergebnisse der Abfrage
        pass
    else:
        session['error'] = "Die Zahlung war ungültig."
        return redirect(f"https://dashboard.{g.whitelabel_info['Domain']}/cockpit/buchhaltung/rechnung/details/{WhiteLabel_ID}")

    if payment.STATUS_PAID == "paid":
        new_rechnung = client.update_item("Rechnungen", id, {"Status": "Bezahlt"})

        new_rechnung = new_rechnung['data']

        nutzer = client.get_item('Nutzer', int(new_rechnung['Nutzer']['key']))

        client.delete_item("Rechnungen_Zahlungen", zahlungen[0]['id'])

        emailTemplate = await render_template('/Email-Templates/zahlung.html', Nutzer = nutzer, Rechnung=new_rechnung, ID = WhiteLabel_ID, Betrag = float(payment.amount['value']), WhiteLabel = g.whitelabel_info)
        await send_html_email("Neue Zahlung erhalten", nutzer['EMail'], emailTemplate)

        session['success'] = f"Die Rechnung #{WhiteLabel_ID} wurde vollständig beglichen."
        return redirect(f"https://dashboard.{g.whitelabel_info['Domain']}/cockpit/buchhaltung/rechnung/details/{WhiteLabel_ID}")
    else:
        session['error'] = "Der Betrag wurde nicht beglichen."
        return redirect(f"https://dashboard.{g.whitelabel_info['Domain']}/cockpit/buchhaltung/rechnung/details/{WhiteLabel_ID}")


@app.context_processor
def inject_current_year():
    return {'current_year': datetime.now().year}

@app.route('/test/email-template/livechat')
async def TEST_EMailTemplates_Rechnung():
    Nutzer = {
        "Vorname": "Max",
        "Nachname": "Mustermann",
        "EMail": "Max.Mustermann@EMail.de"
    }

    Termin = {
        "Thema": "THEMA",
        "Zeitpunkt": "2024-11-07T12:00:00"
    }

    return await render_template('/Email-Templates/live-chat_bestätigung.html', Nutzer = Nutzer , Termin = Termin, WhiteLabel = g.whitelabel_info)




@app.before_request
async def Middleware_Trainingshalle():
    if request.method == "GET":
        # Prüfen, ob der Pfad mit "/trainingshalle" beginnt
        if request.path.startswith("/trainingshalle"):
            print(f"Trainingshalle-Aufruf: {request.path}")  # Log-Ausgabe

            # Stelle sicher, dass die Session-ID vorhanden ist
            user_id = session.get('id')

            # Abrufen der Nutzer-Details
            Nutzer_Details = client.get_item("Nutzer", item_id=user_id)



            request_directus = {
                "query": {
                    "filter": {
                        "Nutzer": {
                            "id": {
                                "_eq": int(session.get('id'))
                            }
                        },
                        "WhiteLabel": {
                            "id": {
                                "_eq": g.whitelabel_info['id']
                            }
                        }
                    },
                    "sort": ["-Zeitstempel"],  # Sortiere nach Zeitstempel in absteigender Reihenfolge
                    "limit": 1  # Hole nur den neuesten Eintrag
                }
            }

            # Abrufen der Fitness-Test-Ergebnisse
            response = client.get_items("FitnessTest_ERGEBNISSE", request_directus)

            try:
                # Überprüfen, ob Daten vorhanden sind
                Test_Verlauf = response[0]

                if Test_Verlauf:
                    # Nimm den letzten Eintrag basierend auf dem Zeitstempel
                    letzter_eintrag = Test_Verlauf

                    # Überprüfen, ob "Abgeschlossen" auf False steht
                    if not letzter_eintrag.get("Abgeschlossen", True):  # Standardwert True, falls "Abgeschlossen" nicht existiert
                        variable = "Nicht abgeschlossen"
                    else:
                        variable = "Abgeschlossen"
                else:
                    variable = "Keine Daten verfügbar"

                print(variable)
            except Exception as e:
                print(f"Fehler beim Abrufen oder Verarbeiten der Daten: {str(e)}")
                letzter_eintrag = {}
                variable = "Keine Daten verfügbar"




            # Trainingshalle-Details setzen
            g.Trainingshalle_Details = {
                "Status": bool(Nutzer_Details.get('Trainingshalle_ART')),
                "Art": Nutzer_Details.get('Trainingshalle_ART', ""),
                "Fitness_Test": Nutzer_Details.get('Fitness_Test', False),
                "Letzter_FitnessTest": {
                    "Status": variable,
                    "Daten": letzter_eintrag
                },
                "Nutzer_Details": Nutzer_Details,
                "Test_Typ": "Individuell" if Nutzer_Details.get('Fitnesstest_Individuell') else "Allgemein"
            }

            if "/fitness-test" not in request.path:
                # Weiterleitung bei Fitness-Test
                if g.Trainingshalle_Details['Fitness_Test']:
                    session['error'] = "Um auf die Trainingshalle zuzugreifen, musst Du zuerst den Fitness-Test absolvieren."
                    redirect_url = f"https://dashboard.{g.whitelabel_info['Domain']}/trainingshalle/fitness-test"
                    print(f"Redirect zu: {redirect_url}")
                    return redirect(redirect_url)
    else:
        # Stelle sicher, dass die Session-ID vorhanden ist
        user_id = session.get('id')


        # Abrufen der Nutzer-Details
        Nutzer_Details = client.get_item("Nutzer", item_id=user_id)

        # Trainingshalle-Details setzen
        g.Trainingshalle_Details = {
            "Status": bool(Nutzer_Details.get('Trainingshalle_ART')),
            "Art": Nutzer_Details.get('Trainingshalle_ART', ""),
            "Fitness_Test": Nutzer_Details.get('Fitness_Test', False),
        }


@app.route('/trainingshalle/aktualisieren/<Art>', methods=['POST'])
async def Trainingshalle_Aktualisierung(Art):
    redirect_url = request.args.get('Redirect_URL')
    data = await request.form
    Methode = data.get('Trainings_Art')


    if Art == "Methode":
        client.update_item("Nutzer", session.get('id'), item_data = {
            "Trainingshalle_ART": Methode
        })

        if Methode == "Fitnessstudio":
            Methode = "Fitnessstudio"
        elif Methode == "Zuhause":
            Methode = "Zuhause"
        elif Methode == "Zuhause_GERÄTE":
            Methode = "Zuhause (mit Geräten)"
        elif Methode == "Gesundheit":
            Methode = "gesundheitliche Probleme"

        session['success'] = f"Deine Trainingsmethode wurde erfolgreich auf '{Methode}' gesetzt!"
        return redirect(redirect_url)
    
@app.route('/trainingshalle/übungen', methods=['GET', 'POST'])
async def Trainingshalle_Uebungen():
    if request.method == 'GET':
        success = session.pop('success', None)
        punkte = session.pop('Punkte_Nachricht', None)
        punkte_nachricht = punkte
        error = session.pop('error', None)

        header = await render_template('/parts/Elemente/header.html', url= request.url, 
                                                    WhiteLabel=g.whitelabel_info, 
                                                    avatar_url=session.get('avatar'), 
                                                    rolle=session.get('rolle'), 
                                                    name=session.get('name'), Nutzer_Punkte=session.get('Nutzer_Punkte'))
        sidebar = await render_template('/parts/Elemente/sidebar.html', 
                                        WhiteLabel=g.whitelabel_info, rolle=session.get('rolle'))
        footer = await render_template('/parts/Elemente/footer.html', WhiteLabel = g.whitelabel_info, Session_Info=g.Session_Info['LogEntry_ID'], nutzername=session.get('username'), nutzer_ID=session.get('id'))

        theme_customizer = await render_template('/parts/Elemente/theme-customizer.html', 
                                                WhiteLabel=g.whitelabel_info)
        

        Übungen = client.get_items("Uebungen")

        
        # Rendern der Vorschau-HTML-Vorlage mit den erhaltenen Parametern
        return await render_template(f'/parts/Seiten/Trainingshalle/Übungen.html', 
                                    header=header,
                                    error=error, 
                                    success=success, 
                                    sidebar=sidebar, 
                                    footer=footer, 
                                    theme_customizer=theme_customizer,
                                    username=session.get('username'), 
                                    rolle=session.get('rolle'), 
                                    name=session.get('name'), 
                                    avatar_url=session.get('avatar'), 
                                    WhiteLabel=g.whitelabel_info,
                                    Übungen = Übungen,
                                    Trainingshalle_Details = g.Trainingshalle_Details)
    
    else:
        # Standardwerte für die Paginierung
        DEFAULT_PAGE = 1
        DEFAULT_PAGE_SIZE = 10

        # Hole die Parameter für die Paginierung aus der Anfrage
        page = int(request.args.get('SEITE', DEFAULT_PAGE))
        page_size = int(request.args.get('page_size', DEFAULT_PAGE_SIZE))

        # Sicherheitsüberprüfung: Stelle sicher, dass die Werte gültig sind
        page = max(page, 1)
        page_size = max(page_size, 1)

        if request.args.get('SUCHE_Name'):
            suche_name = request.args.get('SUCHE_Name').lower()  # Sucheingabe in Kleinbuchstaben umwandeln
            alle_übungen = client.get_items("Uebungen") or []   # Alle Daten abrufen

            # Filtern der Übungen basierend auf `SUCHE_Name`
            Übungen = [
                übung for übung in alle_übungen
                if any(
                    suche_name in (übung.get("Texte", {}).get(lang, {}).get("Name", "").lower() or "")
                    for lang in ["DE", "EN", "ES", "AR", "GR", "RU"]
                )
            ]

        elif request.args.get('SUCHE_Muskelgruppe'):
            muskelgruppen_liste = request.args.get('SUCHE_Muskelgruppe').split(',')
            print("Gesuchte Muskelgruppen (Liste):", muskelgruppen_liste)

            alle_Übungen = client.get_items("Uebungen")
            print("Alle Übungen:", alle_Übungen)

            Übungen = [
                übung for übung in alle_Übungen
                if all(muskel in übung.get("Muskelgruppen", []) for muskel in muskelgruppen_liste)
            ]
            print("Gefilterte Übungen:", Übungen)
        elif request.args.get('SUCHE_Kategorie'):
            kategorie_liste = request.args.get('SUCHE_Kategorie').split(',')
            print("Gesuchte Kategorien (Liste):", kategorie_liste)

            query = {
                "query": {
                    "filter": {
                        "Typ": {
                            "_in": kategorie_liste
                        }
                    }
                }
            }
            Übungen = client.get_items("Uebungen", query)
        elif request.args.get('SUCHE_Gesundheitsproblem'):
            gesundheitsproblem = request.args.get('SUCHE_Gesundheitsproblem')

            if gesundheitsproblem == "Alles":
                Übungen = client.get_items("Uebungen")
            else:
                query = {
                    "query": {
                        "filter": {
                            "Gesundheitsproblem": {
                                "_eq": gesundheitsproblem
                            }
                        }
                    }
                }
                Übungen = client.get_items("Uebungen", query)
        else:
            Übungen = client.get_items("Uebungen")

        

        # Berechne die Anzahl der Seiten und die Anzahl der Ergebnisse
        anzahl_ergebnisse = len(Übungen)
        anzahl_seiten = (anzahl_ergebnisse + page_size - 1) // page_size  # Rundet nach oben

        # Berechne den Indexbereich für die aktuelle Seite
        start_index = (page - 1) * page_size
        end_index = start_index + page_size

        # Erzeuge die Antwort
        response_item = {
            "Seiten": anzahl_seiten,
            "Anzahl": anzahl_ergebnisse,
            "Aktuelle_Seite": page,
            "Seiten_Inhalt": Übungen[start_index:end_index]
        }

        return jsonify(response_item)


@app.route('/trainingshalle/tagebuch', methods=['GET', 'POST'])
async def Trainingshalle_Tagebuch():
    if request.method == 'GET':
        success = session.pop('success', None)
        punkte = session.pop('Punkte_Nachricht', None)
        punkte_nachricht = punkte
        error = session.pop('error', None)

        header = await render_template('/parts/Elemente/header.html', url= request.url, 
                                                    WhiteLabel=g.whitelabel_info, 
                                                    avatar_url=session.get('avatar'), 
                                                    rolle=session.get('rolle'), 
                                                    name=session.get('name'), Nutzer_Punkte=session.get('Nutzer_Punkte'))
        sidebar = await render_template('/parts/Elemente/sidebar.html', 
                                        WhiteLabel=g.whitelabel_info, rolle=session.get('rolle'))
        footer = await render_template('/parts/Elemente/footer.html', WhiteLabel = g.whitelabel_info, Session_Info=g.Session_Info['LogEntry_ID'], nutzername=session.get('username'), nutzer_ID=session.get('id'))

        theme_customizer = await render_template('/parts/Elemente/theme-customizer.html', 
                                                WhiteLabel=g.whitelabel_info)

        # Dein request_directus Dictionary
        request_directus = {
            "query": {
                "filter": {
                    "Nutzer": {
                        "id": {
                            "_eq": int(session.get('id'))
                        }
                    }
                }
            }
        }

        # Versuch, die Items von der Collection "Tagebuch_TRAINING" in Directus abzurufen
        try:
            data = client.get_items("Tagebuch_TRAINING", request_directus)

            if 'error' in data:
                print(f"Fehler: {data['error']}")
                Tagebuch_DATA = []
            else:
                if data:  # Überprüfen, ob Daten vorhanden sind
                    Tagebuch_DATA = data  # Annahme: Die Daten sind unter dem Schlüssel 'data'
                else:
                    Tagebuch_DATA = []

        except Exception as e:
            print(f"Fehler beim Abrufen der Daten: {e}")
            Tagebuch_DATA = []

        # Liste der letzten 7 Tage erstellen und mit Directus-Daten füllen
        Tagebuch_Einträge = []
        for i in range(8):  # Schleife für die letzten 7 Tage
            day = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
            
            # Initialisiere die Untereinträge mit "Gut" und leerem Text
            sub_entries = {
                f"Frage{j}": {"Vote": "", "Text": ""}
                for j in range(1, 6)
            }

            # Falls passende Daten für den Tag aus Directus vorhanden sind, aktualisiere die Einträge
            for item in Tagebuch_DATA:
                if item['Datum'] == day:  # Annahme: Directus hat ein Feld 'datum'
                    for j in range(1, 6):
                        sub_entries[f"Frage{j}"] = {
                            "Vote": item.get(f"Frage{j}", ""),  # "Gut" oder "Schlecht"
                            "Text": item.get(f"Frage{j}_TEXT", "")
                        }

            Tagebuch_Einträge.append({day: sub_entries})
        
        # Rendern der Vorschau-HTML-Vorlage mit den erhaltenen Parametern
        return await render_template(f'/parts/Seiten/Trainingshalle/Tagebuch.html', 
                                    header=header,
                                    error=error, 
                                    success=success, 
                                    sidebar=sidebar, 
                                    footer=footer, 
                                    theme_customizer=theme_customizer,
                                    username=session.get('username'), 
                                    rolle=session.get('rolle'), 
                                    name=session.get('name'), 
                                    avatar_url=session.get('avatar'), 
                                    WhiteLabel=g.whitelabel_info,
                                    current_date = datetime.now(),
                                    Tagebuch_Einträge = Tagebuch_Einträge,
                                    Trainingshalle_Details = g.Trainingshalle_Details)
    else:
        try:
            # Get the data from the request
            data = await request.get_json()

            # Extract the fields
            date = data.get('Datum')
            feedback_id = data.get('Nummer der Frage')
            typ = data.get('Typ')
            vote = data.get('Vote') if typ == "Vote" else None
            text = data.get('Text') if typ == "Text" else None

            # Check for missing required fields
            if not date or feedback_id is None or not typ or (typ == "Vote" and not vote):
                return jsonify({"error": "Missing required fields"}), 400

            # Construct the response in the specified format
            response = {
                "Datum": date,
                "Nummer der Frage": int(feedback_id),
                "Typ": typ,
                "Nutzer_ID": int(session.get('id'))
            }

            if typ == "Vote":
                response["Vote"] = vote
            else:
                response["Text"] = text or ""

            print(response)

            # Dein request_directus Dictionary
            request_directus = {
                "query": {
                    "filter": {
                        "Nutzer": {
                            "id": {
                                "_eq": int(session.get('id'))
                            }
                        },
                        "Datum": {
                            "_eq": date
                        }
                    }
                }
            }

            # Versuch, die Items von der Collection "Tagebuch_TRAINING" in Directus abzurufen
            try:
                data = client.get_items("Tagebuch_TRAINING", request_directus)

                if 'error' in data:
                    print(f"Fehler: {data['error']}")
                    Tagebuch_DATA = []
                else:
                    Tagebuch_DATA = data or []

            except Exception as e:
                print(f"Fehler beim Abrufen der Daten: {e}")
                Tagebuch_DATA = []

            # Prüfen, ob der Eintrag an dem Datum existiert
            entry_exists = False
            existing_entry_data = {}
            for item in Tagebuch_DATA:
                if item['Datum'] == date:
                    entry_exists = True
                    existing_entry_data = item
                    break

            # Nur einen neuen Eintrag erstellen, wenn er noch nicht existiert
            if not entry_exists:
                print("Eintrag wird erstellt!")
                # Construct the item data to be added to Directus
                item_data = {
                    "Datum": date,
                    "Nutzer": {"key": int(session.get('id')), "collection": "Nutzer"},
                    f"Frage{feedback_id}": vote if typ == "Vote" else "",
                    f"Frage{feedback_id}_TEXT": text if typ == "Text" else ""
                }

                # Create the item in Directus
                client.create_item("Tagebuch_TRAINING", item_data=item_data)
            else:
                print(f"Eintrag (#{existing_entry_data['id']}) wird aktualisiert!")

                # Debug: Überprüfen, ob die ID korrekt ist
                print("ID für das Update:", existing_entry_data['id'])

                # Erstelle item_data nur mit den Feldern, die nicht leer sind
                item_data = {}

                if typ == "Vote" and vote:
                    item_data[f"Frage{feedback_id}"] = vote

                if typ == "Text" and text:
                    # Stelle sicher, dass nur das spezifische Textfeld aktualisiert wird
                    item_data[f"Frage{feedback_id}_TEXT"] = text

                # Debug: Überprüfen, ob die Daten korrekt sind
                print("Daten für das Update:", item_data)

                # Versuche, das Item zu aktualisieren
                try:
                    if item_data:  # Nur aktualisieren, wenn item_data nicht leer ist
                        client.update_item("Tagebuch_TRAINING", item_id=existing_entry_data['id'], item_data=item_data)
                        print("Update erfolgreich!")
                    else:
                        print("Keine Änderungen vorgenommen, da keine neuen Daten vorhanden sind.")
                except Exception as e:
                    print(f"Fehler beim Aktualisieren: {e}")

            return jsonify(response), 200

        except Exception as e:
            return jsonify({"error": str(e)}), 500




@app.route('/trainingshalle/fitness-test', methods=['GET', 'POST'])
async def Trainingshalle_FitnessTest():
    if request.method == 'GET':
        if g.Trainingshalle_Details['Nutzer_Details']['Fitness_Test'] == False:
            session['error'] = "Es gibt derzeit keine Nötigkeit, erneut einen Fitness-Test durchzuführen."
            return redirect(f"https://dashboard.{g.whitelabel_info['Domain']}")

        success = session.pop('success', None)
        punkte = session.pop('Punkte_Nachricht', None)
        punkte_nachricht = punkte
        error = session.pop('error', None)

        header = await render_template('/parts/Elemente/header.html', url= request.url, 
                                                    WhiteLabel=g.whitelabel_info, 
                                                    avatar_url=session.get('avatar'), 
                                                    rolle=session.get('rolle'), 
                                                    name=session.get('name'), Nutzer_Punkte=session.get('Nutzer_Punkte'))
        sidebar = await render_template('/parts/Elemente/sidebar.html', 
                                        WhiteLabel=g.whitelabel_info, rolle=session.get('rolle'))
        footer = await render_template('/parts/Elemente/footer.html', WhiteLabel = g.whitelabel_info, Session_Info=g.Session_Info['LogEntry_ID'], nutzername=session.get('username'), nutzer_ID=session.get('id'))

        theme_customizer = await render_template('/parts/Elemente/theme-customizer.html', 
                                                WhiteLabel=g.whitelabel_info)

        if g.Trainingshalle_Details['Nutzer_Details']['Fitnesstest_Individuell']:
            Fitness_Test = client.get_item("Fitnesstest_INDIVIDUELL", item_id=g.Trainingshalle_Details['Nutzer_Details']['Fitnesstest_Individuell']['key'])

            fehlende_uebungen = []
            for i in range(1, 11):  # Überprüft Uebung_1 bis Uebung_10
                uebung_key = f'Uebung_{i}'
                if uebung_key in Fitness_Test:
                    # Überprüft, ob der Wert der Übung leer oder None ist
                    if not Fitness_Test[uebung_key]:
                        fehlende_uebungen.append(uebung_key)
                else:
                    fehlende_uebungen.append(uebung_key)

            print(fehlende_uebungen)

            if fehlende_uebungen:
                Art = g.Trainingshalle_Details.get('Art', '')  # Standardwert als leere Zeichenkette, falls 'Art' nicht existiert

                if Art == "Fitnessstudio":
                    result = "das Training im Fitnessstudio"
                elif Art == "Zuhause":
                    result = "das Training Zuhause"
                elif Art == "Zuhause_GERÄTE":
                    result = "das Training Zuhause (mit Geräten)"
                elif Art == "Gesundheit":
                    result = "das Training mit Gesundheitsproblemen"
                else:
                    result = ""  # Falls keine der Bedingungen zutrifft, wird ein leerer String zurückgegeben

                session['error'] = f"Leider ist für {result} noch kein vollständiger Fitness-Test verfügbar. Trete mit Deinem Trainer in Kontakt um die Trainingshalle zu nutzen!"
                return redirect(f'https://dashboard.{g.whitelabel_info['Domain']}')
        else:
            # Dein request_directus Dictionary
            request_directus = {
                "query": {
                    "filter": {
                        "WhiteLabel": {
                            "id": {
                                "_eq": int(g.whitelabel_info['id'])
                            }
                        },
                        "Typ": {
                            "_eq": g.Trainingshalle_Details['Art']
                        }
                    }
                }
            }

            try:
                # Abrufen der Fitness-Test-Daten
                data = client.get_items("FitnessTest_ALLGEMEIN", request_directus)

                if 'error' in data:
                    print(f"Fehler: {data['error']}")
                    Fitness_Test = {}

                    if g.Trainingshalle_Details["Status"]:
                        Art = g.Trainingshalle_Details.get('Art', '')  # Standardwert als leere Zeichenkette, falls 'Art' nicht existiert

                        if Art == "Fitnessstudio":
                            result = "das Training im Fitnessstudio"
                        elif Art == "Zuhause":
                            result = "das Training Zuhause"
                        elif Art == "Zuhause_GERÄTE":
                            result = "das Training Zuhause (mit Geräten)"
                        elif Art == "Gesundheit":
                            result = "das Training mit Gesundheitsproblemen"
                        else:
                            result = ""  # Falls keine der Bedingungen zutrifft, wird ein leerer String zurückgegeben

                        session['error'] = f"Leider ist für {result} noch kein vollständiger Fitness-Test verfügbar. Trete mit Deinem Trainer in Kontakt um die Trainingshalle zu nutzen!"
                        return redirect(f'https://dashboard.{g.whitelabel_info['Domain']}')
                else:
                    Fitness_Test = data[0] or {}

                fehlende_uebungen = []
                for i in range(1, 11):  # Überprüft Uebung_1 bis Uebung_10
                    uebung_key = f'Uebung_{i}'
                    if uebung_key in Fitness_Test:
                        # Überprüft, ob der Wert der Übung leer oder None ist
                        if not Fitness_Test[uebung_key]:
                            fehlende_uebungen.append(uebung_key)
                    else:
                        fehlende_uebungen.append(uebung_key)

                print(fehlende_uebungen)

                if fehlende_uebungen:
                    Art = g.Trainingshalle_Details.get('Art', '')  # Standardwert als leere Zeichenkette, falls 'Art' nicht existiert

                    if Art == "Fitnessstudio":
                        result = "das Training im Fitnessstudio"
                    elif Art == "Zuhause":
                        result = "das Training Zuhause"
                    elif Art == "Zuhause_GERÄTE":
                        result = "das Training Zuhause (mit Geräten)"
                    elif Art == "Gesundheit":
                        result = "das Training mit Gesundheitsproblemen"
                    else:
                        result = ""  # Falls keine der Bedingungen zutrifft, wird ein leerer String zurückgegeben

                    session['error'] = f"Leider ist für {result} noch kein vollständiger Fitness-Test verfügbar. Trete mit Deinem Trainer in Kontakt um die Trainingshalle zu nutzen!"
                    return redirect(f'https://dashboard.{g.whitelabel_info['Domain']}')

            except Exception as e:
                print(f"Fehler beim Abrufen der Daten oder bei der Überprüfung: {e}")
                Fitness_Test = {}

                if g.Trainingshalle_Details["Status"]:
                    Art = g.Trainingshalle_Details.get('Art', '')  # Standardwert als leere Zeichenkette, falls 'Art' nicht existiert

                    if Art == "Fitnessstudio":
                        result = "das Training im Fitnessstudio"
                    elif Art == "Zuhause":
                        result = "das Training Zuhause"
                    elif Art == "Zuhause_GERÄTE":
                        result = "das Training Zuhause (mit Geräten)"
                    elif Art == "Gesundheit":
                        result = "das Training mit Gesundheitsproblemen"
                    else:
                        result = ""  # Falls keine der Bedingungen zutrifft, wird ein leerer String zurückgegeben

                    session['error'] = f"Leider ist für {result} noch kein vollständiger Fitness-Test verfügbar. Trete mit Deinem Trainer in Kontakt um die Trainingshalle zu nutzen!"
                    return redirect(f'https://dashboard.{g.whitelabel_info['Domain']}')

            
        # Iteration über alle Übungen
        for key, value in Fitness_Test.items():
            if key.startswith('Uebung_') and isinstance(value, dict):
                uebung_key = value['key']
                
                übungs_details = client.get_item("Uebungen", uebung_key)

                # Ersetzen der Inhalte
                Fitness_Test[key] = übungs_details
            

        
        # Rendern der Vorschau-HTML-Vorlage mit den erhaltenen Parametern
        return await render_template(f'/parts/Seiten/Trainingshalle/Fitness-Test.html', 
                                    header=header,
                                    error=error, 
                                    success=success, 
                                    sidebar=sidebar, 
                                    footer=footer, 
                                    theme_customizer=theme_customizer,
                                    username=session.get('username'), 
                                    rolle=session.get('rolle'), 
                                    name=session.get('name'), 
                                    avatar_url=session.get('avatar'), 
                                    WhiteLabel=g.whitelabel_info,
                                    Fitness_Test = json.dumps(Fitness_Test),
                                    Fitness_Test_DETAILS_NONJSON = Fitness_Test,
                                    current_date = datetime.now(),
                                    Trainingshalle_Details = g.Trainingshalle_Details)
    else:
        data = await request.json

        # Eingabedaten abrufen
        try:
            weight = int(data.get("weight"))  # in kg
            height = float(data.get("height")) / 100  # in m (Konvertiere von cm zu m)
            age = int(data.get("age"))  # in years
            gender = data.get("gender")  # "Weiblich" oder "Männlich"
            fitness_level = data.get("fitness_level")  # "Anfänger", "Fortgeschritten", "Profi"
            difficulty = int(data.get("difficulty"))  # Wert vom Slider
        except (ValueError, TypeError):
            return jsonify({"error": "Invalid or missing input data"}), 400

        if any(val is None for val in [weight, height, age, gender, fitness_level, difficulty]):
            return jsonify({"error": "Missing required fields"}), 400

        # Basiswiederholungen
        if fitness_level == "Anfänger":
            base_reps = 10
        elif fitness_level == "Fortgeschritten":
            base_reps = 20
        elif fitness_level == "Profi":
            base_reps = 30
        else:
            base_reps = 10  # Standardwert

        # Geschlechts-Faktor
        gender_factor = 2 if gender == "Männlich" else 0

        # Gewichtsfaktor
        avg_weight = 70 if gender == "Männlich" else 60
        weight_factor = (avg_weight - weight) // 10 if weight < avg_weight else -(weight - avg_weight) // 10

        # Alters-Faktor
        if age > 30:
            age_factor = (age - 30) // 10
        else:
            age_factor = -(30 - age) // 10

        # BMI-Berechnung
        bmi = weight / (height ** 2)

        # KFA-Berechnung
        if gender == "Weiblich":
            kfa = 1.2 * bmi + 0.23 * age - 5.4
        elif gender == "Männlich":
            kfa = 1.2 * bmi + 0.23 * age - 10.8 - 5.4
        else:
            return jsonify({"error": "Ungültiges Geschlecht"}), 400

        # KFA-Faktor
        kfa_factor = 0 if kfa <= 20 else 0.5 * (kfa - 20)

        # Maximale Wiederholungen berechnen und abrunden
        try:
            max_reps = math.floor(base_reps + (10 - difficulty) + gender_factor + weight_factor - age_factor - kfa_factor)
        except Exception as e:
            return jsonify({"error": f"Calculation error: {str(e)}"}), 500

        # Punkte basierend auf Wiederholungen berechnen (0-10 Skala)
        points = max(1, 10 - difficulty)

        # Fitnesslevel bestimmen
        if 90 <= points <= 100:
            level = "Superathlet"
            statement = ("Unglaublich! Ihre Ergebnisse zeigen, dass Sie in herausragender körperlicher Verfassung sind. "
                        "Wir erstellen jetzt einen fortgeschrittenen Trainingsplan, der Sie auf die nächste Stufe bringt. "
                        "Ihr individueller Plan wird innerhalb von 48 Stunden verfügbar sein.")
            color = "green"
        elif 70 <= points <= 89:
            level = "Fit und stark"
            statement = ("Großartige Arbeit! Sie haben eine starke Basis. Wir entwickeln einen Trainingsplan, "
                        "der Ihre Kraft, Ausdauer und Balance weiter verbessert.")
            color = "lightgreen"
        elif 50 <= points <= 69:
            level = "Gute Leistung"
            statement = ("Toll gemacht! Ihre Ergebnisse zeigen eine solide Fitnessbasis, auf der wir aufbauen können. "
                        "Wir erstellen einen Trainingsplan, der gezielt an Ihren Stärken anknüpft.")
            color = "yellow"
        elif 30 <= points <= 49:
            level = "Fortschrittlich"
            statement = ("Gut gemacht! Sie haben den ersten wichtigen Schritt gemacht. Wir erstellen einen persönlichen "
                        "Trainingsplan, der Ihnen hilft, gezielt Kraft, Ausdauer und Beweglichkeit aufzubauen.")
            color = "orange"
        else:
            level = "Einsteiger"
            statement = ("Willkommen auf Ihrer Fitnessreise! Es ist großartig, dass Sie bereit sind, an sich zu arbeiten. "
                        "Wir erstellen einen Trainingsplan für Anfänger, der Ihnen hilft, Stück für Stück Fortschritte zu machen.")
            color = "red"


        return jsonify({
            "max_reps": max_reps,
            "level": {
                "points": round(points, 2),
                "fitness_level": level,
                "statement": statement,
                "color": color
            },
            "details": {
                "base_reps": base_reps,
                "gender_factor": gender_factor,
                "weight_factor": weight_factor,
                "age_factor": age_factor,
                "kfa_factor": kfa_factor,
                "kfa": round(kfa, 2),
                "bmi": round(bmi, 2),
                "difficulty": difficulty
            }
        })

@app.route('/trainingshalle/fitness-test/GesamtErgebnis', methods=['POST'])
async def Trainingshalle_FitnessTest_GesamtErgebnis():
    """
    Berechnet das Fitnesslevel basierend auf den normalisierten Gesamtpunkten.
    """
    data = await request.json

    try:
        total_points = int(data.get("total_points"))  # Gesamtpunkte aus allen Übungen
        num_exercises = int(data.get("num_exercises"))  # Anzahl der Übungen
    except (ValueError, TypeError):
        return jsonify({"error": "Invalid or missing input data"}), 400

    if total_points < 0 or num_exercises <= 0:
        return jsonify({"error": "Invalid input values"}), 400

    # Normalisierung der Gesamtpunkte
    max_possible_points = num_exercises * 10
    normalized_points = (total_points / max_possible_points) * 100

    # Fitnesslevel bestimmen
    if normalized_points >= 90:
        level = "Superathlet"
        statement = ("Unglaublich! Deine Ergebnisse zeigen, dass Du in herausragender körperlicher Verfassung bist.")
        color = "green"
    elif normalized_points >= 70:
        level = "Fit und stark"
        statement = ("Großartige Arbeit! Du hast eine starke Basis.")
        color = "lightgreen"
    elif normalized_points >= 50:
        level = "Gute Leistung"
        statement = ("Toll gemacht! Deine Ergebnisse zeigen eine solide Fitnessbasis.")
        color = "yellow"
    elif normalized_points >= 30:
        level = "Fortschrittlich"
        statement = ("Gut gemacht! Du hast den ersten wichtigen Schritt gemacht.")
        color = "orange"
    else:
        level = "Einsteiger"
        statement = ("Willkommen auf Deiner Fitnessreise!")
        color = "red"




    print("LISTE MIT DEN EINZELNEN ÜBUNGEN")

    # Umwandlung in das gewünschte Format
    item_data = {}
    for i, exercise in enumerate(data.get("exercises"), start=1):
        item_data[f"Uebung_{i}"] = {
            "Maximale_Wiederholungen": exercise['max_reps'],
            "Erreichte_Punkte": exercise['points'],
            "Name": exercise['exercise_name']
        }
    item_data['Typ'] = data.get("Trainings_Methode")
    item_data['Nutzer'] = {"key": int(session.get('id')), "collection": "Nutzer"}
    item_data['WhiteLabel'] = {"key": g.whitelabel_info['id'], "collection": "Nutzer"}
    item_data['Gesamt_Punktzahl'] = round(int(normalized_points), 2)
    item_data['Ergebnis'] = {
        "Fitness_Level": level,
        "Statement": statement,
        "Farbe": color
    }
    item_data['Daten'] = {
        "Geschlecht": data.get("Daten").get("Geschlecht"),
        "Gewicht": data.get("Daten").get("Gewicht"),
        "Grösse": data.get("Daten").get("Grösse"),
        "Fitness_Level": data.get("Daten").get("Fitness_Level"),
        "Alter": data.get("Daten").get("Alter"),
        "Messungen": {
            "Oberarm": data.get("Daten").get("Messungen").get("Oberarm"),
            "Taille": data.get("Daten").get("Messungen").get("Taille"),
            "Hüfte": data.get("Daten").get("Messungen").get("Hüfte"),
            "Oberschenkel": data.get("Daten").get("Messungen").get("Oberschenkel"),
        }
    }


    print(json.dumps(item_data, indent=4, ensure_ascii=False))

    ### ERGEBNIS IN DATENBANK SCHREIBEN! ###
    Fitness_Test = client.create_item("FitnessTest_ERGEBNISSE", item_data)

    request_directus = {
        "query": {
            "filter": {
                "Nutzer": {
                    "id": {
                        "_eq": int(session.get('id'))
                    }
                },
                "WhiteLabel": {
                    "id": {
                        "_eq": g.whitelabel_info['id']
                    }
                }
            }
        }
    }
    Test_Verlauf = client.get_items("FitnessTest_ERGEBNISSE", request_directus)

    client.update_item("Nutzer", item_id=int(session.get('id')), item_data={
        "Fitness_Test": False,
        "Fitnesstest_Individuell": {}
    })

    client.create_item("Trainingsplan_Anfragen", item_data={
        "FitnessTest_Ergebnisse": {"key": Fitness_Test['data']['id'], "collection": "FitnessTest_ERGEBNISSE"},
        "Kunde": {"key": int(session.get('id')), "collection": "Nutzer"},
        "WhiteLabel": {"key": g.whitelabel_info['id'], "collection": "WhiteLabel"},
        "Status": "Warten"
    })
    print(data.get('Fitness_Test_ID'))
    if data.get('Fitness_Test_ID'):
        client.update_item("Fitnesstest_INDIVIDUELL", data.get('Fitness_Test_ID'), {"Abgeschlossen": True})



    return jsonify({
        "Test_Verlauf": Test_Verlauf,
        "fitness_level": level,
        "statement": statement,
        "color": color,
        "points": round(normalized_points, 2)  # Normierte Punkte zurückgeben
    })



@app.route('/create_training_plan', methods=['POST'])
async def create_training_plan():
    data = await request.form

    Art = request.args.get('art')

    # Basisdaten
    name = data.get("Name")
    kunde = data.get("Kunde")
    anfrage = data.get("Anfrage")

    if Art == "übung":
        # Wochen-Daten initialisieren
        weeks = data.get("weeks")
        wochen_daten = {}

        # Übungen nach Wochen gruppieren
        for key, value in data.items():
            if "_sets_week" in key or "_repetitions_week" in key or "_restTime_week" in key or "_notes_week" in key or "_name_week" in key:
                # Zerlege den Schlüssel
                parts = key.split("_")
                exercise_id = parts[0]  # ID der Übung
                field_type = parts[1]  # Typ des Feldes: sets, repetitions, etc.
                week_number = f"Woche_{parts[2].replace('week', '')}"  # Woche extrahieren

                # Stelle sicher, dass die Woche existiert
                if week_number not in wochen_daten:
                    wochen_daten[week_number] = []

                # Finde oder erstelle die Übung
                exercise = next((e for e in wochen_daten[week_number] if e["Übung_ID"] == exercise_id), None)
                if not exercise:
                    exercise = {"Übung_ID": exercise_id, "Sätze": 0, "Wiederholungen": 0, "Pause": 0, "Notizen": "", "Name": ""}
                    wochen_daten[week_number].append(exercise)

                # Werte zuordnen
                if field_type == "sets":
                    exercise["Sätze"] = int(value)
                elif field_type == "repetitions":
                    exercise["Wiederholungen"] = int(value)
                elif field_type == "restTime":
                    exercise["Pause"] = int(value)
                elif field_type == "notes":
                    exercise["Notizen"] = value
                elif field_type == "name":
                    exercise["Name"] = value


        # Antwort vorbereiten
        response = {
            "Name": name,
            "Kunde_ID": kunde,
            "Anfrage_ID": anfrage,
            "Wochen_Anzahl": weeks,
            "Wochen_Daten": wochen_daten,
        }
    elif Art == "datei":
        # Überprüfen, ob eine Datei hochgeladen wurde
        uploaded_files = await request.files
        print("Hochgeladene Dateien:", uploaded_files)

        uploaded_file = uploaded_files.get('Datei')
        if not uploaded_file:
            print("Keine Datei gefunden")
            return jsonify({"error": "Keine Datei hochgeladen"}), 400

        print(f"Gefundene Datei: {uploaded_file.filename}")


        # Validierung der Datei: Name und Format
        if not uploaded_file.filename.endswith(('.doc', '.docx', '.pdf')):
            return jsonify({"error": "Ungültiges Dateiformat"}), 400

        # Temporäre Datei erstellen und speichern
        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(uploaded_file.filename)[1]) as temp_file:
            temp_path = temp_file.name
            await uploaded_file.save(temp_path)
            print(f"Datei wurde temporär gespeichert: {temp_path}")

        try:
            # Daten aus dem Formular extrahieren
            form_data = await request.form
            kunde = form_data.get('Kunde')
            anfrage = form_data.get('Anfrage')
            plan_name = form_data.get('Name')

            # JSON-Struktur vorbereiten
            response = {
                "Name": plan_name,
                "Kunde": kunde,
                "Anfrage": anfrage,
                "Datei": {
                    "Name": uploaded_file.filename,
                    "Temp_Path": temp_path,
                    "Content-Typ": uploaded_file.content_type,
                }
            }

            # Hier können Sie die Datei weiterverarbeiten, z. B. lesen oder hochladen.

        finally:
            # Temporäre Datei löschen
            if os.path.exists(temp_path):
                os.remove(temp_path)
                print(f"Temporäre Datei gelöscht: {temp_path}")

    return jsonify(response), 201

@app.route('/trainingshalle/Upload-Analyse', methods=['GET', 'POST'])
async def Trainingshalle_UploadUndAnalyse():
    if request.method == 'GET':
        success = session.pop('success', None)
        punkte = session.pop('Punkte_Nachricht', None)
        punkte_nachricht = punkte
        error = session.pop('error', None)

        header = await render_template('/parts/Elemente/header.html', url= request.url, 
                                                    WhiteLabel=g.whitelabel_info, 
                                                    avatar_url=session.get('avatar'), 
                                                    rolle=session.get('rolle'), 
                                                    name=session.get('name'), Nutzer_Punkte=session.get('Nutzer_Punkte'))
        sidebar = await render_template('/parts/Elemente/sidebar.html', 
                                        WhiteLabel=g.whitelabel_info, rolle=session.get('rolle'))
        footer = await render_template('/parts/Elemente/footer.html', WhiteLabel = g.whitelabel_info, Session_Info=g.Session_Info['LogEntry_ID'], nutzername=session.get('username'), nutzer_ID=session.get('id'))

        theme_customizer = await render_template('/parts/Elemente/theme-customizer.html', 
                                                WhiteLabel=g.whitelabel_info)
        
        # Rendern der Vorschau-HTML-Vorlage mit den erhaltenen Parametern
        return await render_template(f'/parts/Seiten/Trainingshalle/UploadUndAnalyse.html', 
                                    header=header,
                                    error=error, 
                                    success=success, 
                                    sidebar=sidebar, 
                                    footer=footer, 
                                    theme_customizer=theme_customizer,
                                    username=session.get('username'), 
                                    rolle=session.get('rolle'), 
                                    name=session.get('name'), 
                                    avatar_url=session.get('avatar'), 
                                    WhiteLabel=g.whitelabel_info,
                                    current_date = datetime.now(),
                                    Trainingshalle_Details = g.Trainingshalle_Details)
    else:
        form = await request.form
        files = await request.files
        Art = request.args.get('Art')
        Typ = request.args.get('Typ')

        if Art == "Suche":
            if Typ == "Meine":
                # Standardwerte für die Paginierung
                DEFAULT_PAGE = 1
                DEFAULT_PAGE_SIZE = 10

                # Hole die Parameter für die Paginierung aus der Anfrage
                page = int(request.args.get('SEITE', DEFAULT_PAGE))
                page_size = int(request.args.get('page_size', DEFAULT_PAGE_SIZE))

                # Sicherheitsüberprüfung: Stelle sicher, dass die Werte gültig sind
                page = max(page, 1)
                page_size = max(page_size, 1)

                query = {
                    "query": {
                        "filter": {
                            "_and": [
                                {
                                    "Typ": {
                                        "_eq": "Kunde"
                                    }
                                },
                                {
                                    "Kunde": {
                                        "id": {
                                            "_eq": session.get('id')
                                        }
                                    }
                                }
                            ]
                        }
                    }
                }

                Anfragen = client.get_items("Upload_UND_Analyse", query)
                print(Anfragen)

                for Anfrage in Anfragen:
                    if Anfrage['Status'] == "Abgeschlossen" and Anfrage['Antwort']:
                        Antwort_Details = client.get_item("Upload_UND_Analyse", Anfrage['Antwort']['key'])
                        Trainer_Details = client.get_item("Nutzer", Antwort_Details['Trainer']['key'])
                        Anfrage['Antwort_Details'] = Antwort_Details
                        Anfrage['Antwort_Details']['Trainer_Details'] = Trainer_Details

                

                # Berechne die Anzahl der Seiten und die Anzahl der Ergebnisse
                anzahl_ergebnisse = len(Anfragen)
                anzahl_seiten = (anzahl_ergebnisse + page_size - 1) // page_size  # Rundet nach oben

                # Berechne den Indexbereich für die aktuelle Seite
                start_index = (page - 1) * page_size
                end_index = start_index + page_size

                # Erzeuge die Antwort
                response_item = {
                    "Seiten": anzahl_seiten,
                    "Anzahl": anzahl_ergebnisse,
                    "Aktuelle_Seite": page,
                    "Seiten_Inhalt": Anfragen[start_index:end_index]
                }

                return jsonify(response_item)
            elif Typ == "Trainer":
                # Standardwerte für die Paginierung
                DEFAULT_PAGE = 1
                DEFAULT_PAGE_SIZE = 10

                # Hole die Parameter für die Paginierung aus der Anfrage
                page = int(request.args.get('SEITE', DEFAULT_PAGE))
                page_size = int(request.args.get('page_size', DEFAULT_PAGE_SIZE))

                # Sicherheitsüberprüfung: Stelle sicher, dass die Werte gültig sind
                page = max(page, 1)
                page_size = max(page_size, 1)

                query = {
                    "query": {
                        "filter": {
                            "_and": [
                                {
                                    "Typ": {
                                        "_eq": "Trainer"
                                    }
                                },
                                {
                                    "Kunde": {
                                        "id": {
                                            "_eq": session.get('id')
                                        }
                                    }
                                }
                            ]
                        }
                    }
                }

                Übungen = client.get_items("Upload_UND_Analyse", query)
                print(Übungen)

                

                # Berechne die Anzahl der Seiten und die Anzahl der Ergebnisse
                anzahl_ergebnisse = len(Übungen)
                anzahl_seiten = (anzahl_ergebnisse + page_size - 1) // page_size  # Rundet nach oben

                # Berechne den Indexbereich für die aktuelle Seite
                start_index = (page - 1) * page_size
                end_index = start_index + page_size

                # Erzeuge die Antwort
                response_item = {
                    "Seiten": anzahl_seiten,
                    "Anzahl": anzahl_ergebnisse,
                    "Aktuelle_Seite": page,
                    "Seiten_Inhalt": Übungen[start_index:end_index]
                }

                return jsonify(response_item)
        else:
            Video_Upload = files.get("Video")

            if Video_Upload:
                # Temporären Pfad erstellen
                tmp_dir = tempfile.gettempdir()
                tmp_path = os.path.join(tmp_dir, Video_Upload.filename)

                
                filename = Video_Upload.filename
                content_type = Video_Upload.content_type

                # Die Datei speichern
                await Video_Upload.save(tmp_path)

                # Überprüfen, ob die Datei gespeichert wurde
                if os.path.exists(tmp_path):
                    print(f"Video gespeichert unter {tmp_path}")

                    upload_data = {
                        "title": filename,
                        "description": f"Video für Analyse-Anfrage",
                        "tags": ["Analyse-Anfrage", "Video", "Anfrage"],
                        "type": content_type
                    }
                    VideoUpload_ID = client.upload_file(tmp_path, upload_data)

                    item_data = {
                        "WhiteLabel": {"key": g.whitelabel_info['id'], "collection" : "WhiteLabel"},
                        "Typ": "Kunde",
                        "Kunde": {"key": session.get('id'), "collection" : "Nutzer"},
                        "Video": VideoUpload_ID,
                        "Nachricht": form.get("Nachricht")
                    }
                    client.create_item("Upload_UND_Analyse", item_data)

                    # Sobald die Datei nicht mehr gebraucht wird, löschen
                    os.remove(tmp_path)
                    print(f"Video gelöscht von {tmp_path}")

                session['success'] = "Deine Analyse-Anfrage wurde erfolgreich an Deinen Trainer geschickt."
                return redirect(f"https://dashboard.{g.whitelabel_info['Domain']}/trainingshalle/Upload-Analyse")
            else:
                return jsonify({"message": "Kein Video hochgeladen."})



@app.route('/trainingshalle/Trainingspläne', methods=['GET', 'POST'])
async def Trainingshalle_TrainingsPlaene():
    if request.method == 'GET':
        success = session.pop('success', None)
        punkte = session.pop('Punkte_Nachricht', None)
        punkte_nachricht = punkte
        error = session.pop('error', None)

        header = await render_template('/parts/Elemente/header.html', url= request.url, 
                                                    WhiteLabel=g.whitelabel_info, 
                                                    avatar_url=session.get('avatar'), 
                                                    rolle=session.get('rolle'), 
                                                    name=session.get('name'), Nutzer_Punkte=session.get('Nutzer_Punkte'))
        sidebar = await render_template('/parts/Elemente/sidebar.html', 
                                        WhiteLabel=g.whitelabel_info, rolle=session.get('rolle'))
        footer = await render_template('/parts/Elemente/footer.html', WhiteLabel = g.whitelabel_info, Session_Info=g.Session_Info['LogEntry_ID'], nutzername=session.get('username'), nutzer_ID=session.get('id'))

        theme_customizer = await render_template('/parts/Elemente/theme-customizer.html', 
                                                WhiteLabel=g.whitelabel_info)
        
        # Rendern der Vorschau-HTML-Vorlage mit den erhaltenen Parametern
        return await render_template(f'/parts/Seiten/Trainingshalle/Trainingspläne.html', 
                                    header=header,
                                    error=error, 
                                    success=success, 
                                    sidebar=sidebar, 
                                    footer=footer, 
                                    theme_customizer=theme_customizer,
                                    username=session.get('username'), 
                                    rolle=session.get('rolle'), 
                                    name=session.get('name'), 
                                    avatar_url=session.get('avatar'), 
                                    WhiteLabel=g.whitelabel_info,
                                    current_date = datetime.now(),
                                    Trainingshalle_Details = g.Trainingshalle_Details)
    else:
        form = await request.form
        files = await request.files
        Art = request.args.get('Art')
        Typ = request.args.get('Typ')

        if Art == "Suche":
            if Typ == "Meine":
                # Standardwerte für die Paginierung
                DEFAULT_PAGE = 1
                DEFAULT_PAGE_SIZE = 10

                # Hole die Parameter für die Paginierung aus der Anfrage
                page = int(request.args.get('SEITE', DEFAULT_PAGE))
                page_size = int(request.args.get('page_size', DEFAULT_PAGE_SIZE))

                # Sicherheitsüberprüfung: Stelle sicher, dass die Werte gültig sind
                page = max(page, 1)
                page_size = max(page_size, 1)

                query = {
                    "query": {
                        "filter": {
                            "_and": [
                                {
                                    "Art": {
                                        "_eq": "Individuell"
                                    }
                                },
                                {
                                    "Nutzer": {
                                        "id": {
                                            "_eq": session.get('id')
                                        }
                                    }
                                }
                            ]
                        }
                    }
                }

                Trainingspläne = client.get_items("Trainingsplan", query)
                print(Trainingspläne)

                Filtered_Trainingspläne = []

                for Plan in Trainingspläne:
                    if Plan['Nutzer'] == {'key': session.get('id'), 'collection': 'Nutzer'}:
                        Trainer_Details = client.get_item("Nutzer", Plan['Nutzer_Ersteller']['key'])

                        if Plan['Typ'] == "Übungen":
                            for woche, uebungen in Plan['Daten'].items():
                                for uebung in uebungen:
                                    uebung['Details'] = client.get_item("Uebungen", uebung['Übung_ID'])
                        else:
                            pass


                        # Trainingsplan zu gefilterten Ergebnissen hinzufügen
                        Filtered_Trainingspläne.append(Plan)

                

                # Berechne die Anzahl der Seiten und die Anzahl der Ergebnisse
                anzahl_ergebnisse = len(Trainingspläne)
                anzahl_seiten = (anzahl_ergebnisse + page_size - 1) // page_size  # Rundet nach oben

                # Berechne den Indexbereich für die aktuelle Seite
                start_index = (page - 1) * page_size
                end_index = start_index + page_size

                # Erzeuge die Antwort
                response_item = {
                    "Seiten": anzahl_seiten,
                    "Anzahl": anzahl_ergebnisse,
                    "Aktuelle_Seite": page,
                    "Seiten_Inhalt": Filtered_Trainingspläne[start_index:end_index]
                }

                return jsonify(response_item)
            elif Typ == "Trainer":
                # Standardwerte für die Paginierung
                DEFAULT_PAGE = 1
                DEFAULT_PAGE_SIZE = 10

                # Hole die Parameter für die Paginierung aus der Anfrage
                page = int(request.args.get('SEITE', DEFAULT_PAGE))
                page_size = int(request.args.get('page_size', DEFAULT_PAGE_SIZE))

                # Sicherheitsüberprüfung: Stelle sicher, dass die Werte gültig sind
                page = max(page, 1)
                page_size = max(page_size, 1)

                query = {
                    "query": {
                        "filter": {
                            "_and": [
                                {
                                    "Art": {
                                        "_eq": "Vorgefertigt"
                                    }
                                }
                            ]
                        }
                    }
                }

                Trainingspläne = client.get_items("Trainingsplan", query)
                print(Trainingspläne)

                Filtered_Trainingspläne = []

                for Plan in Trainingspläne:
                    if Plan['WhiteLabel'] == {'key': g.whitelabel_info['id'], 'collection': 'WhiteLabel'}:
                        Trainer_Details = client.get_item("Nutzer", Plan['Nutzer_Ersteller']['key'])

                        if Plan['Typ'] == "Übungen":
                            for woche, uebungen in Plan['Daten'].items():
                                for uebung in uebungen:
                                    uebung['Details'] = client.get_item("Uebungen", uebung['Übung_ID'])
                        else:
                            pass


                        # Trainingsplan zu gefilterten Ergebnissen hinzufügen
                        Filtered_Trainingspläne.append(Plan)

                

                # Berechne die Anzahl der Seiten und die Anzahl der Ergebnisse
                anzahl_ergebnisse = len(Trainingspläne)
                anzahl_seiten = (anzahl_ergebnisse + page_size - 1) // page_size  # Rundet nach oben

                # Berechne den Indexbereich für die aktuelle Seite
                start_index = (page - 1) * page_size
                end_index = start_index + page_size

                # Erzeuge die Antwort
                response_item = {
                    "Seiten": anzahl_seiten,
                    "Anzahl": anzahl_ergebnisse,
                    "Aktuelle_Seite": page,
                    "Seiten_Inhalt": Filtered_Trainingspläne[start_index:end_index]
                }

                return jsonify(response_item)









@app.before_request
async def Middleware_ErnährungsAnalyse():
    if request.method == "GET":
        # Prüfen, ob der Pfad mit "/trainingshalle" beginnt
        if request.path.startswith("/Ernährung-Analyse"):
            print(f"Ernährungsanalyse-Aufruf: {request.path}")  # Log-Ausgabe

            # Stelle sicher, dass die Session-ID vorhanden ist
            user_id = session.get('id')

            # Abrufen der Nutzer-Details
            Nutzer_Details = client.get_item("Nutzer", item_id=user_id)



            request_directus = {
                "query": {
                    "filter": {
                        "Nutzer": {
                            "id": {
                                "_eq": int(session.get('id'))
                            }
                        },
                        "WhiteLabel": {
                            "id": {
                                "_eq": g.whitelabel_info['id']
                            }
                        }
                    },
                    "sort": ["-Zeitstempel"],  # Sortiere nach Zeitstempel in absteigender Reihenfolge
                    "limit": 1  # Hole nur den neuesten Eintrag
                }
            }

            # Abrufen der Fitness-Test-Ergebnisse
            response = client.get_items("FitnessTest_ERGEBNISSE", request_directus)

            try:
                # Überprüfen, ob Daten vorhanden sind
                Test_Verlauf = response[0]

                if Test_Verlauf:
                    # Nimm den letzten Eintrag basierend auf dem Zeitstempel
                    letzter_eintrag = Test_Verlauf

                    # Überprüfen, ob "Abgeschlossen" auf False steht
                    if not letzter_eintrag.get("Abgeschlossen", True):  # Standardwert True, falls "Abgeschlossen" nicht existiert
                        variable = "Nicht abgeschlossen"
                    else:
                        variable = "Abgeschlossen"
                else:
                    variable = "Keine Daten verfügbar"

                print(variable)
            except Exception as e:
                print(f"Fehler beim Abrufen oder Verarbeiten der Daten: {str(e)}")
                letzter_eintrag = {}
                variable = "Keine Daten verfügbar"




            # Trainingshalle-Details setzen
            g.ErnährungsAnalyse_Details = {
                "Status": bool(Nutzer_Details.get('Aktivitaets_Level')),
                "Art": Nutzer_Details.get('Aktivitaets_Level', ""),
                "Einstiegs_Fragebogen": Nutzer_Details.get('Einstiegs_Fragebogen', False),
                "Pflicht_Messung": Nutzer_Details.get('Messungs_Pflicht', False),
                "Letzter_FitnessTest": {
                    "Status": variable,
                    "Daten": letzter_eintrag
                },
                "Nutzer_Details": Nutzer_Details,
                "Test_Typ": "Individuell" if Nutzer_Details.get('Fitnesstest_Individuell') else "Allgemein"
            }

            if "Einstiegs-Fragebogen" not in request.path:
                # Weiterleitung bei Fitness-Test
                if g.ErnährungsAnalyse_Details['Einstiegs_Fragebogen']:
                    session['error'] = "Um auf die Ernährung & Analyse zuzugreifen, musst Du zuerst den Einstiegs-Fragebochen ausfüllen."
                    redirect_url = f"https://dashboard.{g.whitelabel_info['Domain']}/Ernährung-Analyse/Einstiegs-Fragebogen"
                    print(f"Redirect zu: {redirect_url}")
                    return redirect(redirect_url)

            if "/Messung/Neu" not in request.path:
                # Weiterleitung zur initialen Messung
                if g.ErnährungsAnalyse_Details['Pflicht_Messung']:
                    session['error'] = "Um auf die Ernährung & Analyse zuzugreifen, musst Du noch eine Messung durchführen."
                    redirect_url = f"https://dashboard.{g.whitelabel_info['Domain']}/Ernährung-Analyse/Messung/Neu"
                    print(f"Redirect zu: {redirect_url}")
                    return redirect(redirect_url)

    else:
        # Stelle sicher, dass die Session-ID vorhanden ist
        user_id = session.get('id')


        # Abrufen der Nutzer-Details
        Nutzer_Details = client.get_item("Nutzer", item_id=user_id)

        # Trainingshalle-Details setzen
        g.ErnährungsAnalyse_Details = {
            "Status": bool(Nutzer_Details.get('Trainingshalle_ART')),
            "Art": Nutzer_Details.get('Trainingshalle_ART', ""),
            "Fitness_Test": Nutzer_Details.get('Fitness_Test', False),
        }


@app.route('/Ernährung-Analyse/aktualisieren/<Art>', methods=['POST'])
async def ErnährungsAnalyse_Aktualisierung(Art):
    redirect_url = request.args.get('Redirect_URL')
    data = await request.form
    Methode = data.get('Aktivitäts-Level')

    if Art == "Level":
        client.update_item("Nutzer", session.get('id'), item_data = {
            "Aktivitaets_Level": Methode
        })

        session['success'] = f"Dein Aktivitäts-Level wurde erfolgreich auf '{Methode}' gesetzt!"
        return redirect(redirect_url)
    
    elif Art == "Ziel":
        Ziel = data.get('Ernährungs-Ziel')

        client.update_item("Nutzer", session.get('id'), item_data = {
            "Ernaehrungs_ZIEL": Ziel
        })

        session['success'] = f"Dein Ernährungs-Ziel wurde erfolgreich auf '{Ziel}' gesetzt!"
        return redirect(redirect_url)



@app.route('/Ernährung-Analyse/Einstiegs-Fragebogen', methods=['GET', 'POST'])
async def ErnährungsAnalyse_EinstiegsFragebogen():
    if request.method == 'GET':
        if g.ErnährungsAnalyse_Details['Nutzer_Details']['Einstiegs_Fragebogen'] == False:
            session['error'] = "Es gibt derzeit keine Nötigkeit, erneut den Einstiegs-Fragebogen für die Ernährungs-Analyse auszufüllen."
            return redirect(f"https://dashboard.{g.whitelabel_info['Domain']}")

        success = session.pop('success', None)
        punkte = session.pop('Punkte_Nachricht', None)
        punkte_nachricht = punkte
        error = session.pop('error', None)

        header = await render_template('/parts/Elemente/header.html', url= request.url, 
                                                    WhiteLabel=g.whitelabel_info, 
                                                    avatar_url=session.get('avatar'), 
                                                    rolle=session.get('rolle'), 
                                                    name=session.get('name'), Nutzer_Punkte=session.get('Nutzer_Punkte'))
        sidebar = await render_template('/parts/Elemente/sidebar.html', 
                                        WhiteLabel=g.whitelabel_info, rolle=session.get('rolle'))
        footer = await render_template('/parts/Elemente/footer.html', WhiteLabel = g.whitelabel_info, Session_Info=g.Session_Info['LogEntry_ID'], nutzername=session.get('username'), nutzer_ID=session.get('id'))

        theme_customizer = await render_template('/parts/Elemente/theme-customizer.html', 
                                                WhiteLabel=g.whitelabel_info)

        
        # Rendern der Vorschau-HTML-Vorlage mit den erhaltenen Parametern
        return await render_template(f'/parts/Seiten/Ernährung-Analyse/Einstiegs-Fragebogen.html', 
                                    header=header,
                                    error=error, 
                                    success=success, 
                                    sidebar=sidebar, 
                                    footer=footer, 
                                    theme_customizer=theme_customizer,
                                    username=session.get('username'), 
                                    rolle=session.get('rolle'), 
                                    name=session.get('name'), 
                                    avatar_url=session.get('avatar'), 
                                    WhiteLabel=g.whitelabel_info,
                                    current_date = datetime.now(),
                                    ErnährungsAnalyse_Details = g.ErnährungsAnalyse_Details)
    else:
        try:
            # JSON-Daten aus der Anfrage abrufen
            data = await request.json

            # Neue Felder extrahieren
            ernaehrungsgewohnheiten = data.get('Ernährungsgewohnheiten', '')
            diaeten = data.get('Diäten', '')
            lebensmittel_meiden = data.get('Lebensmittel_Meiden', '')
            stresslevel = data.get('Stresslevel', '')
            gesundheit = data.get('Gesundheit', '')
            motivation = data.get('Motivation', '')
            kommentar = data.get('Kommentar', '')

            # Beispielhafte Validierung (falls Pflichtfelder benötigt werden)
            if not stresslevel:  # Optional oder nur prüfen, wenn notwendig
                return jsonify({"success": False, "message": "Bitte geben Sie ein Stresslevel an."}), 400

            client.create_item("Einstiegs_Fragebogen", {
                "Nutzer": {'key': int(session.get('id')), 'collection': 'Nutzer'},
                "WhiteLabel": {'key': g.whitelabel_info['id'], 'collection': 'WhiteLabel'},
                "Ernaehrungsgewohnheiten": ernaehrungsgewohnheiten,
                "Diaeten": diaeten,
                "Lebensmittel_Meiden": lebensmittel_meiden,
                "Stresslevel": stresslevel,
                "Gesundheit": gesundheit,
                "Motivation": motivation,
                "Kommentar": kommentar
            })

            client.update_item("Nutzer", int(session.get('id')), {
                "Einstiegs_Fragebogen": False
            })

            # Erfolgsantwort
            return jsonify({
                "success": True,
                "message": "Die Daten wurden erfolgreich gespeichert.",
                "data_received": data  # Optional: Debugging-Zwecke
            }), 200

        except Exception as e:
            # Fehlerbehandlung
            return jsonify({"success": False, "message": str(e)}), 500



@app.route('/Ernährung-Analyse/Messung/<Aktion>', methods=['GET', 'POST'])
async def ErnährungsAnalyse_Messung_AKTION(Aktion):
    if request.method == 'GET':
        success = session.pop('success', None)
        punkte = session.pop('Punkte_Nachricht', None)
        punkte_nachricht = punkte
        error = session.pop('error', None)

        header = await render_template('/parts/Elemente/header.html', url= request.url, 
                                                    WhiteLabel=g.whitelabel_info, 
                                                    avatar_url=session.get('avatar'), 
                                                    rolle=session.get('rolle'), 
                                                    name=session.get('name'), Nutzer_Punkte=session.get('Nutzer_Punkte'))
        sidebar = await render_template('/parts/Elemente/sidebar.html', 
                                        WhiteLabel=g.whitelabel_info, rolle=session.get('rolle'))
        footer = await render_template('/parts/Elemente/footer.html', WhiteLabel = g.whitelabel_info, Session_Info=g.Session_Info['LogEntry_ID'], nutzername=session.get('username'), nutzer_ID=session.get('id'))

        theme_customizer = await render_template('/parts/Elemente/theme-customizer.html', 
                                                WhiteLabel=g.whitelabel_info)

        if Aktion == "Neu":
            # Rendern der Vorschau-HTML-Vorlage mit den erhaltenen Parametern
            return await render_template(f'/parts/Seiten/Ernährung-Analyse/Messungen/Neue-Messung.html', 
                                        header=header,
                                        error=error, 
                                        success=success, 
                                        sidebar=sidebar, 
                                        footer=footer, 
                                        theme_customizer=theme_customizer,
                                        username=session.get('username'), 
                                        rolle=session.get('rolle'), 
                                        name=session.get('name'), 
                                        avatar_url=session.get('avatar'), 
                                        WhiteLabel=g.whitelabel_info,
                                        current_date = datetime.now(),
                                        ErnährungsAnalyse_Details = g.ErnährungsAnalyse_Details)
        else:
            # Dein request_directus Dictionary
            request_directus = {
                "query": {
                    "filter": {
                        "Nutzer": {
                            "id": {
                                "_eq": int(session.get('id'))
                            }
                        }
                    }
                }
            }

            # Versuch, die Items von der Collection "Tagebuch_ERNAEHRUNG" in Directus abzurufen
            try:
                data = client.get_item("Messungen", Aktion, request_directus)

                if 'error' in data:
                    print(f"Fehler: {data['error']}")
                    
                    session['error'] = "Diese Messung wurde leider nicht gefunden oder Du hast keine Berechtigung auf diese."
                    return redirect(f"https://dashboard.{g.whitelabel_info['Domain']}/Ernährung-Analyse/Messungen")
                else:
                    Messungs_DETAILS = data or {}

            except Exception as e:
                print(f"Fehler beim Abrufen der Daten: {e}")
                    
                session['error'] = "Diese Messung wurde leider nicht gefunden oder Du hast keine Berechtigung auf diese."
                return redirect(f"https://dashboard.{g.whitelabel_info['Domain']}/Ernährung-Analyse/Messungen")

            # Rendern der Vorschau-HTML-Vorlage mit den erhaltenen Parametern
            return await render_template(f'/parts/Seiten/Ernährung-Analyse/Messungen/Details.html', 
                                        header=header,
                                        error=error, 
                                        success=success, 
                                        sidebar=sidebar, 
                                        footer=footer, 
                                        theme_customizer=theme_customizer,
                                        username=session.get('username'), 
                                        rolle=session.get('rolle'), 
                                        name=session.get('name'), 
                                        avatar_url=session.get('avatar'), 
                                        WhiteLabel=g.whitelabel_info,
                                        current_date = datetime.now(),
                                        Messungs_DETAILS=Messungs_DETAILS,
                                        ErnährungsAnalyse_Details = g.ErnährungsAnalyse_Details)

    else:
        data = await request.form

        gender = data.get("Geschlecht")
        weight = float(data.get("Gewicht"))
        height = float(data.get("Grösse"))
        age = int(data.get("Alter"))
        waist = float(data.get("Taille_CM"))
        hip = float(data.get("Hüfte_CM", 0))  # Hip might not always be provided
        thigh = float(data.get("Oberschenkel_CM", 0))  # Thigh might not always be provided
        arm = float(data.get("Oberarm_CM"))

        # Mifflin-St Jeor Formula
        bmr_mifflin = (10 * weight + 6.25 * height - 5 * age + 5) if gender == "male" else (10 * weight + 6.25 * height - 5 * age - 161)

        # Harris-Benedict Formula
        bmr_harris = (88.362 + 13.397 * weight + 4.799 * height - 5.677 * age) if gender == "male" else (447.593 + 9.247 * weight + 3.098 * height - 4.33 * age)

        # WHO/FAO/UNU (Schofield) Formula
        if gender == "Männlich":
            if 18 <= age <= 30:
                bmr_schofield = 15.3 * weight + 679
            elif 30 < age <= 60:
                bmr_schofield = 11.6 * weight + 879
            else:
                bmr_schofield = 13.5 * weight + 487
        else:
            if 18 <= age <= 30:
                bmr_schofield = 14.7 * weight + 496
            elif 30 < age <= 60:
                bmr_schofield = 8.7 * weight + 829
            else:
                bmr_schofield = 10.5 * weight + 596

        # Average BMR
        average_bmr = (bmr_mifflin + bmr_harris + bmr_schofield) / 3

        # BMI Calculation
        bmi = weight / ((height / 100) ** 2)

        # Body Fat Percentage Calculation
        if gender == "Männlich":
            body_fat_percentage = 78.315 * log10(waist - arm) - 70.041 * log10(height) + 36.76
        else:
            body_fat_percentage = 163.205 * log10(waist + hip - arm) - 97.684 * log10(height) - 78.387

        # Lean Body Mass (LBM)
        lbm = weight * (1 - body_fat_percentage / 100)

        # FFMI Calculation
        ffmi = lbm / ((height / 100) ** 2)


        Gesamtumsatz = {
            "Sitzend": round(average_bmr, 2) * 1.2,
            "Stehend": round(average_bmr, 2) * 1.375,
            "Aktiv": (round(average_bmr, 2) * 1.55) + (0.1 * round(average_bmr, 2)),
            "Athlet": (round(average_bmr, 2) * 1.725) + (0.1 * round(average_bmr, 2))
        }

        # Funktion zum Aufrunden auf die nächsten 0,5 Liter
        def round_to_next_half_liter(value):
            return math.ceil(value * 2) / 2
        
        # Funktion zum Berechnen der Anzahl der 0,5-Liter-Gläser
        def calculate_glasses(value):
            rounded_value = round_to_next_half_liter(value)
            return int(rounded_value / 0.5)  # Anzahl der 0,5-Liter-Gläser

        # Berechnung weiterer Ergebnisse
        Weitere_Ergebnisse = {
            "Grunddaten": {
                "Geschlecht": gender,
                "Gewicht": weight,
                "Größe": height,
                "Alter": age,
                "Taille_CM": waist,
                "Hüfte_CM": hip,
                "Oberschenkel_CM": thigh,
                "Oberarm_CM": arm,
            },
            "Gesamtumsatz": Gesamtumsatz,
            "Gewichtsreduktion": {
                "Sitzend": {
                    "Max_Defizit": (Gesamtumsatz['Sitzend'] - round(average_bmr, 2)) * 0.625,
                    "Min_Kalorien": Gesamtumsatz['Sitzend'] - ((Gesamtumsatz['Sitzend'] - round(average_bmr, 2)) * 0.625)
                },
                "Stehend": {
                    "Max_Defizit": (Gesamtumsatz['Stehend'] - round(average_bmr, 2)) * 0.625,
                    "Min_Kalorien": Gesamtumsatz['Stehend'] - ((Gesamtumsatz['Stehend'] - round(average_bmr, 2)) * 0.625)
                },
                "Aktiv": {
                    "Max_Defizit": (Gesamtumsatz['Aktiv'] - round(average_bmr, 2)) * 0.5,
                    "Min_Kalorien": Gesamtumsatz['Aktiv'] - ((Gesamtumsatz['Aktiv'] - round(average_bmr, 2)) * 0.5)
                },
                "Athlet": {
                    "Max_Defizit": (Gesamtumsatz['Athlet'] - round(average_bmr, 2)) * 0.5,
                    "Min_Kalorien": Gesamtumsatz['Athlet'] - ((Gesamtumsatz['Athlet'] - round(average_bmr, 2)) * 0.5)
                }
            },
            "Muskelaufbau": {
                "Sitzend": {
                    "Min_Gain": Gesamtumsatz['Sitzend'] * 0.1,  # 10%
                    "Min_Kalorien": Gesamtumsatz['Sitzend'] + (Gesamtumsatz['Sitzend'] * 0.1)
                },
                "Stehend": {
                    "Min_Gain": Gesamtumsatz['Stehend'] * 0.13,  # 13%
                    "Min_Kalorien": Gesamtumsatz['Stehend'] + (Gesamtumsatz['Stehend'] * 0.13)
                },
                "Aktiv": {
                    "Min_Gain": Gesamtumsatz['Aktiv'] * 0.16,  # 16%
                    "Min_Kalorien": Gesamtumsatz['Aktiv'] + (Gesamtumsatz['Aktiv'] * 0.16)
                },
                "Athlet": {
                    "Min_Gain": Gesamtumsatz['Athlet'] * 0.2,  # 20%
                    "Min_Kalorien": Gesamtumsatz['Athlet'] + (Gesamtumsatz['Athlet'] * 0.2)
                }
            },
            "Wasserempfehlung": {
                "Sitzend": {
                    "ml": round_to_next_half_liter(weight * 0.03),  # 30 ml pro kg
                    "glas": calculate_glasses(weight * 0.03),  # Anzahl 0,5-Liter-Gläser
                },
                "Stehend": {
                    "ml": round_to_next_half_liter(weight * 0.035),  # 35 ml pro kg
                    "glas": calculate_glasses(weight * 0.035),  # Anzahl 0,5-Liter-Gläser
                },
                "Aktiv": {
                    "ml": round_to_next_half_liter(weight * 0.04),  # 40 ml pro kg
                    "glas": calculate_glasses(weight * 0.04),  # Anzahl 0,5-Liter-Gläser
                },
                "Athlet": {
                    "ml": round_to_next_half_liter(weight * 0.045),  # 45 ml pro kg
                    "glas": calculate_glasses(weight * 0.045),  # Anzahl 0,5-Liter-Gläser
                }
            }
        }



        item_data = {
            "Nutzer": {'key': int(session.get('id')), 'collection': 'Nutzer'},
            "Grundumsatz_BMR": round(average_bmr, 2),
            "BodyMassIndex_BMI": round(bmi, 2),
            "Korperfettanteil": round(body_fat_percentage, 2),
            "fettfreieMasse_LBM": round(lbm, 2),
            "FettfreieMasseIndex_FFMI": round(ffmi, 2),
            "Ergebnis_DATEN": Weitere_Ergebnisse
        }

        messung_item = client.create_item("Messungen", item_data)
        
        client.update_item("Nutzer", int(session.get('id')), {"Messungs_Pflicht": False})

        session['success'] = "Die Messung wurde erfolgreich im System hinterlegt."
        return redirect(f"https://dashboard.{g.whitelabel_info['Domain']}/Ernährung-Analyse/Messung/{messung_item['data']['id']}")





@app.route('/Ernährung-Analyse/Tagebuch', methods=['GET', 'POST'])
async def ErnährungsAnalyse_Tagebuch():
    if request.method == 'GET':
        success = session.pop('success', None)
        punkte = session.pop('Punkte_Nachricht', None)
        punkte_nachricht = punkte
        error = session.pop('error', None)

        header = await render_template('/parts/Elemente/header.html', url= request.url, 
                                                    WhiteLabel=g.whitelabel_info, 
                                                    avatar_url=session.get('avatar'), 
                                                    rolle=session.get('rolle'), 
                                                    name=session.get('name'), Nutzer_Punkte=session.get('Nutzer_Punkte'))
        sidebar = await render_template('/parts/Elemente/sidebar.html', 
                                        WhiteLabel=g.whitelabel_info, rolle=session.get('rolle'))
        footer = await render_template('/parts/Elemente/footer.html', WhiteLabel = g.whitelabel_info, Session_Info=g.Session_Info['LogEntry_ID'], nutzername=session.get('username'), nutzer_ID=session.get('id'))

        theme_customizer = await render_template('/parts/Elemente/theme-customizer.html', 
                                                WhiteLabel=g.whitelabel_info)

        # Dein request_directus Dictionary
        request_directus = {
            "query": {
                "filter": {
                    "Nutzer": {
                        "id": {
                            "_eq": int(session.get('id'))
                        }
                    }
                }
            }
        }

        # Versuch, die Items von der Collection "Tagebuch_ERNAEHRUNG" in Directus abzurufen
        try:
            data = client.get_items("Tagebuch_ERNAEHRUNG", request_directus)

            if 'error' in data:
                print(f"Fehler: {data['error']}")
                Tagebuch_DATA = []
            else:
                if data:  # Überprüfen, ob Daten vorhanden sind
                    Tagebuch_DATA = data  # Annahme: Die Daten sind unter dem Schlüssel 'data'
                else:
                    Tagebuch_DATA = []

        except Exception as e:
            print(f"Fehler beim Abrufen der Daten: {e}")
            Tagebuch_DATA = []

        # Liste der letzten 7 Tage erstellen und mit Directus-Daten füllen
        Tagebuch_Einträge = []
        for i in range(8):  # Schleife für die letzten 7 Tage
            day = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
            
            # Initialisiere die Untereinträge mit "Gut" und leerem Text
            sub_entries = {
                f"Frage{j}": {"Vote": "", "Text": ""}
                for j in range(1, 6)
            }

            # Falls passende Daten für den Tag aus Directus vorhanden sind, aktualisiere die Einträge
            for item in Tagebuch_DATA:
                if item['Datum'] == day:  # Annahme: Directus hat ein Feld 'datum'
                    for j in range(1, 6):
                        sub_entries[f"Frage{j}"] = {
                            "Vote": item.get(f"Frage{j}", ""),  # "Gut" oder "Schlecht"
                            "Text": item.get(f"Frage{j}_TEXT", "")
                        }

            Tagebuch_Einträge.append({day: sub_entries})
        
        # Rendern der Vorschau-HTML-Vorlage mit den erhaltenen Parametern
        return await render_template(f'/parts/Seiten/Ernährung-Analyse/Tagebuch.html', 
                                    header=header,
                                    error=error, 
                                    success=success, 
                                    sidebar=sidebar, 
                                    footer=footer, 
                                    theme_customizer=theme_customizer,
                                    username=session.get('username'), 
                                    rolle=session.get('rolle'), 
                                    name=session.get('name'), 
                                    avatar_url=session.get('avatar'), 
                                    WhiteLabel=g.whitelabel_info,
                                    current_date = datetime.now(),
                                    Tagebuch_Einträge = Tagebuch_Einträge,
                                    ErnährungsAnalyse_Details = g.ErnährungsAnalyse_Details)
    else:
        try:
            # Get the data from the request
            data = await request.get_json()

            # Extract the fields
            date = data.get('Datum')
            feedback_id = data.get('Nummer der Frage')
            typ = data.get('Typ')
            vote = data.get('Vote') if typ == "Vote" else None
            text = data.get('Text') if typ == "Text" else None

            # Check for missing required fields
            if not date or feedback_id is None or not typ or (typ == "Vote" and not vote):
                return jsonify({"error": "Missing required fields"}), 400

            # Construct the response in the specified format
            response = {
                "Datum": date,
                "Nummer der Frage": int(feedback_id),
                "Typ": typ,
                "Nutzer_ID": int(session.get('id'))
            }

            if typ == "Vote":
                response["Vote"] = vote
            else:
                response["Text"] = text or ""

            print(response)

            # Dein request_directus Dictionary
            request_directus = {
                "query": {
                    "filter": {
                        "Nutzer": {
                            "id": {
                                "_eq": int(session.get('id'))
                            }
                        },
                        "Datum": {
                            "_eq": date
                        }
                    }
                }
            }

            # Versuch, die Items von der Collection "Tagebuch_ERNAEHRUNG" in Directus abzurufen
            try:
                data = client.get_items("Tagebuch_ERNAEHRUNG", request_directus)

                if 'error' in data:
                    print(f"Fehler: {data['error']}")
                    Tagebuch_DATA = []
                else:
                    Tagebuch_DATA = data or []

            except Exception as e:
                print(f"Fehler beim Abrufen der Daten: {e}")
                Tagebuch_DATA = []

            # Prüfen, ob der Eintrag an dem Datum existiert
            entry_exists = False
            existing_entry_data = {}
            for item in Tagebuch_DATA:
                if item['Datum'] == date:
                    entry_exists = True
                    existing_entry_data = item
                    break

            # Nur einen neuen Eintrag erstellen, wenn er noch nicht existiert
            if not entry_exists:
                print("Eintrag wird erstellt!")
                # Construct the item data to be added to Directus
                item_data = {
                    "Datum": date,
                    "Nutzer": {"key": int(session.get('id')), "collection": "Nutzer"},
                    f"Frage{feedback_id}": vote if typ == "Vote" else "",
                    f"Frage{feedback_id}_TEXT": text if typ == "Text" else ""
                }

                # Create the item in Directus
                client.create_item("Tagebuch_ERNAEHRUNG", item_data=item_data)
            else:
                print(f"Eintrag (#{existing_entry_data['id']}) wird aktualisiert!")

                # Debug: Überprüfen, ob die ID korrekt ist
                print("ID für das Update:", existing_entry_data['id'])

                # Erstelle item_data nur mit den Feldern, die nicht leer sind
                item_data = {}

                if typ == "Vote" and vote:
                    item_data[f"Frage{feedback_id}"] = vote

                if typ == "Text" and text:
                    # Stelle sicher, dass nur das spezifische Textfeld aktualisiert wird
                    item_data[f"Frage{feedback_id}_TEXT"] = text

                # Debug: Überprüfen, ob die Daten korrekt sind
                print("Daten für das Update:", item_data)

                # Versuche, das Item zu aktualisieren
                try:
                    if item_data:  # Nur aktualisieren, wenn item_data nicht leer ist
                        client.update_item("Tagebuch_ERNAEHRUNG", item_id=existing_entry_data['id'], item_data=item_data)
                        print("Update erfolgreich!")
                    else:
                        print("Keine Änderungen vorgenommen, da keine neuen Daten vorhanden sind.")
                except Exception as e:
                    print(f"Fehler beim Aktualisieren: {e}")

            return jsonify(response), 200

        except Exception as e:
            return jsonify({"error": str(e)}), 500



@app.route('/Ernährung-Analyse/Tracking', methods=['GET', 'POST'])
async def ErnährungsAnalyse_Tracking():
    if request.method == 'GET':
        success = session.pop('success', None)
        punkte = session.pop('Punkte_Nachricht', None)
        punkte_nachricht = punkte
        error = session.pop('error', None)

        header = await render_template('/parts/Elemente/header.html', url= request.url, 
                                                    WhiteLabel=g.whitelabel_info, 
                                                    avatar_url=session.get('avatar'), 
                                                    rolle=session.get('rolle'), 
                                                    name=session.get('name'), Nutzer_Punkte=session.get('Nutzer_Punkte'))
        sidebar = await render_template('/parts/Elemente/sidebar.html', 
                                        WhiteLabel=g.whitelabel_info, rolle=session.get('rolle'))
        footer = await render_template('/parts/Elemente/footer.html', WhiteLabel = g.whitelabel_info, Session_Info=g.Session_Info['LogEntry_ID'], nutzername=session.get('username'), nutzer_ID=session.get('id'))

        theme_customizer = await render_template('/parts/Elemente/theme-customizer.html', 
                                                WhiteLabel=g.whitelabel_info)

        
        # Dein request_directus Dictionary
        request_directus = {
            "query": {
                "filter": {
                    "Nutzer": {
                        "id": {
                            "_eq": int(session.get('id'))
                        }
                    }
                },
                "sort": "-date_created",
                "limit": 1
            }
        }

        # Versuch, die Items von der Collection "Tagebuch_ERNAEHRUNG" in Directus abzurufen
        try:
            data = client.get_items("Messungen", request_directus)

            if 'error' in data:
                print(f"Fehler: {data['error']}")
                Letzte_Messung = {}
            else:
                Letzte_Messung = data[0] or {}

        except Exception as e:
            print(f"Fehler beim Abrufen der Daten: {e}")
            Letzte_Messung = {}


        # Dein request_directus Dictionary
        request_directus = {
            "query": {
                "filter": {
                    "Nutzer": {
                        "id": {
                            "_eq": int(session.get('id'))
                        }
                    },
                    "Datum": {
                        "_eq": datetime.now().strftime("%Y-%m-%d")
                    }
                },
                "limit": 1
            }
        }

        # Versuch, die Items von der Collection "Tagebuch_ERNAEHRUNG" in Directus abzurufen
        try:
            data = client.get_items("Ernaehrungs_TRACKING", request_directus)

            if 'error' in data:
                print(f"Fehler: {data['error']}")
                Heutige_TRACKING_DATEN = {
                    "Wasser": 0,
                    "Kalorien_ANZAHL": 0,
                    "Kalorien_LISTE": []
                }
            else:
                Heutige_TRACKING_DATEN = data[0] or {"Wasser": 0,"Kalorien_ANZAHL": 0,"Kalorien_LISTE": []}
            
                if Heutige_TRACKING_DATEN != {"Wasser": 0,"Kalorien_ANZAHL": 0,"Kalorien_LISTE": []}:
                    TEMP_Summe_Kalorien = 0

                    for kalorien in Heutige_TRACKING_DATEN['Kalorien']:
                        TEMP_Summe_Kalorien += kalorien['Anzahl_KALORIEN']

                Heutige_TRACKING_DATEN['Kalorien_ANZAHL'] = TEMP_Summe_Kalorien

        except Exception as e:
            print(f"Fehler beim Abrufen der Daten: {e}")
            Heutige_TRACKING_DATEN = {"Wasser": 0,"Kalorien_ANZAHL": 0,"Kalorien_LISTE": []}


        # Berechne die letzten 7 Tage
        today = datetime.now()
        last_7_days = [(today - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(7)]

        # Filter für Directus-Abfrage
        request_directus = {
            "query": {
                "filter": {
                    "Nutzer": {
                        "id": {
                            "_eq": int(session.get('id'))
                        }
                    },
                    "Datum": {
                        "_gte": (today - timedelta(days=6)).strftime("%Y-%m-%d"),  # 7 Tage zurück
                        "_lte": today.strftime("%Y-%m-%d")  # Heute
                    }
                },
                "sort": "-Datum",
                "limit": 7
            }
        }

        # Berechnung der letzten 7 Tage mit datetime-Objekten
        last_7_days = [(today - timedelta(days=i)) for i in range(7)]  # datetime-Objekte

        try:
            # Daten von Directus abrufen
            data = client.get_items("Ernaehrungs_TRACKING", request_directus)  # Passen Sie den Collection-Namen an

            if 'error' in data:
                print(f"Fehler: {data['error']}")
                fetched_data = {}
            else:
                # Mapping von Datum zu Daten (z. B. Kalorienanzahl)
                fetched_data = {entry['Datum']: entry for entry in data}

            # Sicherstellen, dass jeder Tag der letzten 7 Tage enthalten ist
            last_7_days_data = {
                day.strftime("%d.%m.%Y") if day.date() != today.date() else "Heute": fetched_data.get(day.strftime("%Y-%m-%d"), {})
                for day in last_7_days
            }

        except Exception as e:
            print(f"Fehler beim Abrufen der Daten: {e}")
            last_7_days_data = {
                day.strftime("%d.%m.%Y") if day.date() != today.date() else "Heute": {} for day in last_7_days
            }
        
        # Temporäre Variable zur Speicherung der Kalorien-Summe
        TEMP_Summe_Kalorien = 0

        # Über alle Einträge in den letzten 7 Tagen iterieren
        for key, value in last_7_days_data.items():
            # Sicherstellen, dass der Schlüssel 'Kalorien' existiert und eine Liste ist
            for kalorien in value.get('Kalorien', []):
                TEMP_Summe_Kalorien += kalorien.get('Anzahl_KALORIEN', 0)  # Standardwert 0, falls 'Anzahl_KALORIEN' fehlt
            
            # Gesamtsumme der Kalorien als neuen Schlüssel hinzufügen
            value['Kalorien_ANZAHL'] = TEMP_Summe_Kalorien
            
            # TEMP_Summe_Kalorien zurücksetzen
            TEMP_Summe_Kalorien = 0


        
        # Rendern der Vorschau-HTML-Vorlage mit den erhaltenen Parametern
        return await render_template(f'/parts/Seiten/Ernährung-Analyse/Ernährungs-Tracking.html', 
                                    header=header,
                                    error=error, 
                                    success=success, 
                                    sidebar=sidebar, 
                                    footer=footer, 
                                    theme_customizer=theme_customizer,
                                    username=session.get('username'), 
                                    rolle=session.get('rolle'), 
                                    name=session.get('name'), 
                                    avatar_url=session.get('avatar'), 
                                    WhiteLabel=g.whitelabel_info,
                                    current_date = datetime.now(),
                                    ErnährungsAnalyse_Details = g.ErnährungsAnalyse_Details,
                                    Letzte_Messung=Letzte_Messung,
                                    Heutige_TRACKING_DATEN=Heutige_TRACKING_DATEN,
                                    Letzte7Tage_TRACKING_DATEN=last_7_days_data)
    else:
        try:
            # Get the data from the request
            data_JSON = await request.get_json()

            # Extract the fields
            date = datetime.now().strftime("%Y-%m-%d")
            typ = data_JSON.get('Typ')

            response = {}

            # Dein request_directus Dictionary
            request_directus = {
                "query": {
                    "filter": {
                        "Nutzer": {
                            "id": {
                                "_eq": int(session.get('id'))
                            }
                        },
                        "Datum": {
                            "_eq": date
                        }
                    }
                }
            }

            # Versuch, die Items von der Collection "Ernaehrungs_TRACKING" in Directus abzurufen
            try:
                data = client.get_items("Ernaehrungs_TRACKING", request_directus)

                if 'error' in data:
                    print(f"Fehler: {data['error']}")
                    Tagebuch_DATA = []
                else:
                    Tagebuch_DATA = data or []

            except Exception as e:
                print(f"Fehler beim Abrufen der Daten: {e}")
                Tagebuch_DATA = []

            # Prüfen, ob der Eintrag an dem Datum existiert
            entry_exists = False
            existing_entry_data = {}
            for item in Tagebuch_DATA:
                if item['Datum'] == date:
                    entry_exists = True
                    existing_entry_data = item
                    break

            # Nur einen neuen Eintrag erstellen, wenn er noch nicht existiert
            if not entry_exists:
                print("Eintrag wird erstellt!")
                # Construct the item data to be added to Directus
                item_data = {
                    "Datum": date,
                    "Nutzer": {"key": int(session.get('id')), "collection": "Nutzer"},
                }

                if typ == "Wasser" and data_JSON.get('Wasser') is not None:
                    item_data["Wasser"] = int(data_JSON.get('Wasser'))
                    item_data["Wasser_GESAMT"] = int(data_JSON.get('Wasser_GESAMT'))
                    response["Wasser"] = int(data_JSON.get('Wasser'))

                if typ == "Kalorien" and data_JSON.get('Item'):
                    response[f"Kalorien"] = [data_JSON.get('Item')]

                # Create the item in Directus
                client.create_item("Ernaehrungs_TRACKING", item_data=item_data)
            else:
                print(f"Eintrag (#{existing_entry_data['id']}) wird aktualisiert!")

                # Debug: Überprüfen, ob die ID korrekt ist
                print("ID für das Update:", existing_entry_data['id'])

                # Erstelle item_data nur mit den Feldern, die nicht leer sind
                item_data = {}

                if typ == "Wasser" and data_JSON.get('Wasser') is not None:
                    item_data["Wasser"] = int(data_JSON.get('Wasser'))
                    item_data["Wasser_GESAMT"] = int(data_JSON.get('Wasser_GESAMT'))

                if typ == "Kalorien" and data_JSON.get('Item'):
                    existing_data = client.get_item("Ernaehrungs_TRACKING", existing_entry_data['id'])
                    Kalorien_DATA = existing_data.get('Kalorien', [])  # Standardwert [] verwenden, falls 'Kalorien' nicht existiert
                    new_item = data_JSON.get('Item')
                    new_item['Anzahl_KALORIEN'] = float(data_JSON.get('Anzahl'))
                    if new_item:
                        Kalorien_DATA.append(new_item)

                    # Aktualisierte Kalorien-Daten zurückschreiben
                    item_data["Kalorien"] = Kalorien_DATA

                    item_data["Kalorien_INFO"] = {
                        "Erreicht": float(data_JSON.get('Kalorien_DATA').get('Erreicht')),
                        "Ziel": float(data_JSON.get('Kalorien_DATA').get('Ziel'))
                    }

                response = item_data

                # Debug: Überprüfen, ob die Daten korrekt sind
                print("Daten für das Update:", item_data)

                # Versuche, das Item zu aktualisieren
                try:
                    if item_data:  # Nur aktualisieren, wenn item_data nicht leer ist
                        client.update_item("Ernaehrungs_TRACKING", item_id=existing_entry_data['id'], item_data=item_data)
                        print("Update erfolgreich!")
                    else:
                        print("Keine Änderungen vorgenommen, da keine neuen Daten vorhanden sind.")
                except Exception as e:
                    print(f"Fehler beim Aktualisieren: {e}")

            return jsonify({"success": response}), 200

        except Exception as e:
            return jsonify({"error": str(e)}), 500




# Verbindung zur MySQL-Datenbank herstellen
def fetch_products_from_db(suche):
    try:
        connection = mysql.connector.connect(
            host='127.0.0.1',  # localhost
            port=3306,         # MySQL-Port
            user='root',       # Benutzername
            password='HM3LZQe[B/iW46Glum+D6j3pcf9$-',  # Passwort
            database='Food_DB'  # Name der Datenbank
        )
        cursor = connection.cursor(dictionary=True)

        # SQL-Abfrage basierend auf der Suchanfrage
        sql_query = """
        SELECT * FROM foodcals_extended
        WHERE name LIKE %s
        LIMIT 20;
        """
        cursor.execute(sql_query, (f"%{suche}%",))

        results = cursor.fetchall()
        return results

    except mysql.connector.Error as e:
        print(f"Fehler bei der Datenbankverbindung: {e}")
        return []

    finally:
        if 'connection' in locals() and connection.is_connected():
            cursor.close()
            connection.close()


@lru_cache(maxsize=40)  # Cache für bis zu 100 unterschiedliche Suchbegriffe
def cached_text_search(suche, seite, seite_limit):
    try:
        print("Anfrage wird verarbeitet...")  # Nur bei Cache-Miss
        
        # API-Abfrage
        results = Food_API.product.text_search(suche, seite, seite_limit)
        return results
    except Exception as e:
        print(f"Fehler bei der API-Abfrage: {e}")
        return {'products': []}  # Leeres Ergebnis als Fallback


@app.route('/food-api/suche')
async def foodApi_SUCHE():
     # Eingabe abfragen

    suche = request.args.get('Suche', '').strip()
    seite = request.args.get('Seite', 1)
    seite_limit = request.args.get('Seite_LIMIT', 10)

    # Prüfen, ob die Eingabe eine mögliche EAN ist
    def is_ean(suche):
        return suche.isdigit() and len(suche) in [8, 12, 13, 14]

    results = None
    produkte = []
    gesehen = set()  # Set zur Überprüfung von Duplikaten

    if is_ean(suche):
        # Wenn EAN, suche direkt das Produkt
        produkt = Food_API.product.get(suche)
        if produkt:
            # Nur ein Produkt wird zurückgegeben
            product_name = produkt.get('product_name_de') or produkt.get('product_name')
            deutsches_produkt = {
                "Typ": "API",
                'product_name': product_name,
                'ingredients_text_de': produkt.get('ingredients_text_de'),
                'labels_de': produkt.get('labels_de'),
                'categories_de': produkt.get('categories_de'),
                'packaging_de': produkt.get('packaging_de'),
                'brands': produkt.get('brands'),
                'quantity': produkt.get('quantity'),
                'nutriments': produkt.get('nutriments'),
                'allergens': produkt.get('allergens'),
                'traces': produkt.get('traces'),
                'additives_tags': produkt.get('additives_tags'),
                'countries_tags': produkt.get('countries_tags'),
                'languages_tags': produkt.get('languages_tags'),
                'Menge': {
                    "Portion": {
                        "Menge": produkt.get('serving_quantity'),
                        "Einheit": produkt.get('serving_quantity_unit')
                    },
                    "Produkt": {
                        "Menge": produkt.get('product_quantity'),
                        "Einheit": produkt.get('product_quantity_unit')
                    }
                },
                'images': {
                    'image_url': produkt.get('image_url'),
                    'image_small_url': produkt.get('image_small_url'),
                    'image_ingredients_url': produkt.get('image_ingredients_url'),
                    'image_ingredients_small_url': produkt.get('image_ingredients_small_url'),
                    'image_nutrition_url': produkt.get('image_nutrition_url'),
                    'image_nutrition_small_url': produkt.get('image_nutrition_small_url'),
                },
                'Scores': {
                    'NutriScore': produkt.get('nutrition_grades'),
                    'NovaScore': produkt.get('nova_group'),
                    'EcoScore': produkt.get('ecoscore_grade'),
                }
            }
            produkte.append(deutsches_produkt)

            return jsonify(produkte)
    else:
        # Andernfalls Textsuche durchführen
        # Produkte aus der MySQL-Datenbank
        db_results = fetch_products_from_db(suche)
        for db_produkt in db_results:
            if db_produkt['name'] not in gesehen:
                produkte.append({
                    "Typ": "Datenbank",
                    'product_name': db_produkt['name'],
                    'ingredients_text_de': None,
                    'labels_de': None,
                    'categories_de': None,
                    'packaging_de': None,
                    'brands': "Nicht definiert",
                    'quantity': db_produkt['serving'],
                    'nutriments': {
                        'calories': db_produkt['calories'],
                        'carbs': db_produkt['carbs'],
                        'fat': db_produkt['fat'],
                        'protein': db_produkt['protein'],
                        'sodium': db_produkt['sodium'],
                        'potassium': db_produkt['potassium'],
                        'calcium': db_produkt['calcium'],
                        'phosphorus': db_produkt['phosphorus'],
                        'iron': db_produkt['iron'],
                        'magnesium': db_produkt['magnesium'],
                        'copper': db_produkt['copper'],
                        'zinc': db_produkt['zinc'],
                    },
                    'allergens': None,
                    'traces': None,
                    'additives_tags': None,
                    'countries_tags': None,
                    'languages_tags': None,
                    'Menge': {
                        "Portion": {
                            "Menge": db_produkt['serving'],
                            "Einheit": ""
                        },
                        "Produkt": {
                            "Menge": db_produkt['serving'],
                            "Einheit": ""
                        }
                    },
                    'images': {
                        'image_url': f"https://cdn.{g.whitelabel_info['Domain']}/assets/images/Food-API/default.svg" if not db_produkt['image_url'] or 'example.com' in db_produkt['image_url']
                            else db_produkt['image_url'],
                        'image_small_url': None,
                        'image_ingredients_url': None,
                        'image_ingredients_small_url': None,
                        'image_nutrition_url': None,
                        'image_nutrition_small_url': None,
                    },
                    'Scores': {
                        'NutriScore': (
                            'unknown' if not db_produkt['nutriscore'] or db_produkt['nutriscore'].lower() == 'nicht verfügbar'
                            else db_produkt['nutriscore'].lower()
                        ),
                        'NovaScore': (
                            'unknown' if not db_produkt['novascore'] or db_produkt['novascore'].lower() == 'nicht verfügbar'
                            else db_produkt['novascore'].lower()
                        ),
                        'EcoScore': (
                            'unknown' if not db_produkt['ecoscore'] or db_produkt['ecoscore'].lower() == 'nicht verfügbar'
                            else db_produkt['ecoscore'].lower()
                        ),
                    }
                })
                gesehen.add(db_produkt['name'])



        # Produkte von der API
        try:
            # API-Abfrage mit Caching
            results = cached_text_search(suche, seite, seite_limit)
            # Verarbeite die Ergebnisse, wenn sie erfolgreich abgerufen wurden
            for produkt in results.get('products', []):
                product_name = produkt.get('product_name_de') or produkt.get('product_name')
                deutsches_produkt = {
                    "Typ": "API",
                    'product_name': product_name,
                    'ingredients_text_de': produkt.get('ingredients_text_de'),
                    'labels_de': produkt.get('labels_de'),
                    'categories_de': produkt.get('categories_de'),
                    'packaging_de': produkt.get('packaging_de'),
                    'brands': produkt.get('brands'),
                    'quantity': produkt.get('quantity'),
                    'nutriments': produkt.get('nutriments'),
                    'allergens': produkt.get('allergens'),
                    'traces': produkt.get('traces'),
                    'additives_tags': produkt.get('additives_tags'),
                    'countries_tags': produkt.get('countries_tags'),
                    'languages_tags': produkt.get('languages_tags'),
                    'Menge': {
                        "Portion": {
                            "Menge": produkt.get('serving_quantity'),
                            "Einheit": produkt.get('serving_quantity_unit')
                        },
                        "Produkt": {
                            "Menge": produkt.get('product_quantity'),
                            "Einheit": produkt.get('product_quantity_unit')
                        }
                    },
                    'images': {
                        'image_url': produkt.get('image_url'),
                        'image_small_url': produkt.get('image_small_url'),
                        'image_ingredients_url': produkt.get('image_ingredients_url'),
                        'image_ingredients_small_url': produkt.get('image_ingredients_small_url'),
                        'image_nutrition_url': produkt.get('image_nutrition_url'),
                        'image_nutrition_small_url': produkt.get('image_nutrition_small_url'),
                    },
                    'Scores': {
                        'NutriScore': produkt.get('nutrition_grades') or 'unknown',
                        'NovaScore': produkt.get('nova_group') or 'unknown',
                        'EcoScore': produkt.get('ecoscore_grade') or 'unknown',
                    }
                }
                produkte.append(deutsches_produkt)

        except Exception as e:
            # Fehlerbehandlung
            print(f"Fehler bei der API-Abfrage: {e}")
            results = {'products': []}  # Leere Ergebnisse als Fallback

        return jsonify(produkte)



@app.route('/Ernährung-Analyse/Messungen', methods=['GET'])
async def ErnährungsAnalyse_Messungen():
    if request.method == 'GET':
        success = session.pop('success', None)
        punkte = session.pop('Punkte_Nachricht', None)
        punkte_nachricht = punkte
        error = session.pop('error', None)

        header = await render_template('/parts/Elemente/header.html', url= request.url, 
                                                    WhiteLabel=g.whitelabel_info, 
                                                    avatar_url=session.get('avatar'), 
                                                    rolle=session.get('rolle'), 
                                                    name=session.get('name'), Nutzer_Punkte=session.get('Nutzer_Punkte'))
        sidebar = await render_template('/parts/Elemente/sidebar.html', 
                                        WhiteLabel=g.whitelabel_info, rolle=session.get('rolle'))
        footer = await render_template('/parts/Elemente/footer.html', WhiteLabel = g.whitelabel_info, Session_Info=g.Session_Info['LogEntry_ID'], nutzername=session.get('username'), nutzer_ID=session.get('id'))

        theme_customizer = await render_template('/parts/Elemente/theme-customizer.html', 
                                                WhiteLabel=g.whitelabel_info)

        # Dein request_directus Dictionary
        request_directus = {
            "query": {
                "filter": {
                    "Nutzer": {
                        "id": {
                            "_eq": int(session.get('id'))
                        }
                    }
                }
            }
        }

        # Versuch, die Items von der Collection "Tagebuch_ERNAEHRUNG" in Directus abzurufen
        try:
            data = client.get_items("Messungen", request_directus)

            if 'error' in data:
                print(f"Fehler: {data['error']}")
                Messungen = []
            else:
                Messungen = data or []

        except Exception as e:
            print(f"Fehler beim Abrufen der Daten: {e}")
            Messungen = []

        
        # Rendern der Vorschau-HTML-Vorlage mit den erhaltenen Parametern
        return await render_template(f'/parts/Seiten/Ernährung-Analyse/Messungen/Übersicht.html', 
                                    header=header,
                                    error=error, 
                                    success=success, 
                                    sidebar=sidebar, 
                                    footer=footer, 
                                    theme_customizer=theme_customizer,
                                    username=session.get('username'), 
                                    rolle=session.get('rolle'), 
                                    name=session.get('name'), 
                                    avatar_url=session.get('avatar'), 
                                    WhiteLabel=g.whitelabel_info,
                                    current_date = datetime.now(),
                                    ErnährungsAnalyse_Details = g.ErnährungsAnalyse_Details,
                                    Messungen = Messungen)



@app.route('/TEST/Pdf-Bericht')
async def TEST_PDF_BERICHT():
    # Log-Dateipfad definieren
    log_file = "/home/personalpeak360/Webseite/TEST_BERICHT/Template-Creation.log"

    # Logger erstellen
    logger = logging.getLogger("TemplateCreationLogger")
    logger.setLevel(logging.INFO)  # Setzt den Logging-Level

    # FileHandler für Datei-Logging hinzufügen
    file_handler = logging.FileHandler(log_file)
    file_handler.setLevel(logging.INFO)

    # Format für Logs definieren
    formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    file_handler.setFormatter(formatter)

    # Handler hinzufügen
    logger.addHandler(file_handler)

    # Optional: Logs auch im Terminal ausgeben
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    try:
        # Pug in HTML konvertieren
        logger.info("Starte Pug-zu-HTML-Konvertierung...")
        html = pug_to_html(
            "/home/personalpeak360/Webseite/TEST_BERICHT/template.pug",
            title="Mein Test-Bericht",
            WhiteLabel_Logo=f"https://cdn.personalpeak360.de/white-label/{g.whitelabel_info['Logo_lang']}"
        )
        logger.info("Pug-zu-HTML-Konvertierung erfolgreich abgeschlossen.")

        # Temporären Bytes-Stream für PDF erstellen
        logger.info("Erstelle temporären PDF-Bytes-Stream...")
        pdf_stream = io.BytesIO()
        write_report(html, pdf_stream)  # PDF in den Bytes-Stream schreiben
        pdf_stream.seek(0)  # Zeiger an den Anfang setzen
        logger.info("PDF-Bytes-Stream erfolgreich erstellt.")

        logger.info("Prozess erfolgreich abgeschlossen.")

    except Exception as e:
        logger.error(f"Fehler während der Template-Erstellung: {str(e)}")
    
    # PDF direkt als Vorschau zurückgeben
    return Response(
        pdf_stream.read(),
        mimetype='application/pdf',
        headers={
            'Content-Disposition': 'inline; filename="Test-Bericht.pdf"'
        }
    )