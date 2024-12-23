from datetime import datetime
from quart import Quart, jsonify, request, abort, send_from_directory, render_template, redirect, url_for, session, websocket, g
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
import json
import requests

with open('/home/personalpeak360/Webseite/config.json', 'r') as file:
    config = json.load(file)


ph = PasswordHasher()

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

url = config['CMS']['url']
DIRECTUS_API_URL = config['CMS']['url']
access_token = config['CMS']['access_token']




from directus_sdk_py import DirectusClient

client = DirectusClient(url=config['CMS']['url'], token=config['CMS']['access_token'])


AUFBAUMODUS = config['Konfiguration']['Aufbaumodus']
VERÖFFENTLICHUNGSDATUM = datetime(2025, 1, 1) # (Jahr, Monat, Tag)



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
async def handle_aufbaumodus():
    if session.get('logged_in'):
        pass
    else:
        if request.path == "/voranmeldung":
            pass
        else:
            success = session.pop('success', None)
            error = session.pop('error', None)

            return await render_template('/Seiten/FEHLER/aufbau.html', success=success, error=error, WHITELABEL_Domain=g.customer_domain, WhiteLabel = g.whitelabel_info, targetDate = VERÖFFENTLICHUNGSDATUM)

import aiosmtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

@app.context_processor
def inject_current_year():
    return {'current_year': datetime.now().year}

async def send_confirmation_email(vorname, nachname, adresse, email, telefonnummer, interessen, WhiteLabel):  
    Nutzer = {
        "Vorname": vorname,
        "Nachname": nachname,
        "EMail": email
    }

    # Render das HTML-Template mit den Daten
    html_content = await render_template(
        '/Seiten/E-Mail_Templates/bestätigung_voranmeldung.html',
        Nutzer=Nutzer,
        WhiteLabel=WhiteLabel
    )

    # Erstelle die E-Mail
    message = MIMEMultipart('alternative')
    message['Subject'] = "Bestätigung deiner Voranmeldung"
    message['From'] = "info@personalpeak360.com"
    message['To'] = email

    # Füge den HTML-Inhalt zur E-Mail hinzu
    html_part = MIMEText(html_content, 'html')
    message.attach(html_part)

    # E-Mail via SMTP senden
    await aiosmtplib.send(
        message,
        hostname=config['EMail_Adresse']['info@personalpeak360.com']['Server']['SMTP'],
        port=config['EMail_Adresse']['info@personalpeak360.com']['Port']['SMTP'],
        start_tls=True,
        username=config['EMail_Adresse']['info@personalpeak360.com']['Benutzername'],
        password=config['EMail_Adresse']['info@personalpeak360.com']['Passwort']
    )

@app.route('/voranmeldung', methods=['POST'])
async def voranmeldung():
    data = await request.form
    
    selected_interests = data.getlist('interests')

    item_data = {
        'Vorname': data.get('vorname'),
        'Nachname': data.get('nachname'),
        'Adresse': f"{data.get('strasse')}, {data.get('plz')} {data.get('stadt')}",
        'EMail': data.get('email'),
        'Telefonnummer': data.get('telefon'),
        'Interessen': selected_interests,
        "AktivierungsCode": data.get('activationCode')
    }
    new_item = client.create_item(collection_name='Voranmeldungen', item_data=item_data)

    # E-Mail senden
    await send_confirmation_email(
        vorname=data.get('vorname'),
        nachname=data.get('nachname'),
        adresse=item_data['Adresse'],
        email=data.get('email'),
        telefonnummer=data.get('telefon'),
        interessen=selected_interests,
        WhiteLabel=g.whitelabel_info
    )

    session['success'] = "Du hast Dich erfolgreich vorangemeldet. Du solltest eine E-Mail erhalten!"
    return redirect(f"https://www.personalpeak360.de/")


@app.route('/', methods=['GET', 'POST'])
async def startseite():
    success = session.pop('success', None)
    error = session.pop('error', None)

    return await render_template('/Seiten/index.html', success=success, error=error, username=session.get('username'), rolle=session.get('rolle'), WHITELABEL_Domain=g.customer_domain, WhiteLabel = g.whitelabel_info)
        


@app.route('/register')
async def register():
    return 'Register'