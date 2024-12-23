from datetime import datetime
from quart import Quart, jsonify, request, abort, send_from_directory, render_template, redirect, url_for, session, websocket, g
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
import json
import requests
import httpx

with open('/home/personalpeak360/Webseite/config.json', 'r') as file:
    config = json.load(file)




from directus_sdk_py import DirectusClient

client = DirectusClient(url=config['CMS']['url'], token=config['CMS']['access_token'])


AUFBAUMODUS = config['Konfiguration']['Aufbaumodus']
VERÖFFENTLICHUNGSDATUM = datetime(2025, 1, 1) # (Jahr, Monat, Tag)
from mollie.api.client import Client
from mollie.api.error import Error, UnprocessableEntityError, ResponseError

mollie_client = Client()
mollie_client.set_api_key(config['Mollie_API']['API_Token'])

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
async def handle_BildschirmSperrung():
    if session.get('logged_in'):
        if request.path != "/logout":
            if session.get('bildschirm_sperre'):
                if request.method == "GET":
                    name = session.get('name')
                    rolle = session.get('rolle')
                    success = session.pop('success', None)
                    error = session.pop('error', None)

                    return await render_template('/Seiten/lock-screen.html', success=success, error=error , name=name, rolle=rolle, avatar_url=session.get('avatar'), nutzer_level=session.get('Nutzer_Level'), WHITELABEL_Domain=g.customer_domain, WhiteLabel = g.whitelabel_info, nutzername=session.get('username'))
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
    
    rollen_infos = {}

    try:
        data_rolle = client.get_item("Nutzer_Rollen", f"{data[0].get('Rolle_RECHTE', {})['key']}")

        print(data_rolle)
        if 'error' in data_rolle:
            print(f"Fehler: {data['error']}")
        else:
            if data_rolle:  # Überprüfen, ob Daten vorhanden sind
                rollen_infos = data_rolle  # Speichere die Whitelabel-Informationen in g
            else:
                rollen_infos = {}
    except Exception as e:
        print(f"Fehler beim Abrufen der Daten: {e}")

    # Store user details in session
    session['username'] = data[0]['Benutzername']
    g.username = username

    session['id'] = data[0].get('id')

    session['avatar'] = f"https://cdn.personalpeak360.de/avatar/{data[0].get('Avatar')}"
    session['vorname'] = data[0].get('Vorname')
    session['nachname'] = data[0].get('Nachname')
    session['EMail'] = data[0].get('EMail')
    session['name'] = f"{data[0].get('Vorname')} {data[0].get('Nachname')}"
    session['rolle'] = {
        "ID": rollen_infos['id'],
        "Rolle": rollen_infos['Rollenname'],
        "Bezeichnung": rollen_infos['Bezeichnung'],
        "Zusatz-Bezeichnung": rollen_infos['Bezeichnung_Zusatz'],
        "Rechte": rollen_infos['Rechte']
    }
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

    if not data[0].get('Mollie_CUSTOMER_ID'):
        customer = mollie_client.customers.create({
            "name": f"{data[0].get('Vorname')} {data[0].get('Nachname')}",
            "email": f"{data[0].get('EMail')}",
        })

        session['Mollie_CUSTOMER_ID'] = customer['id']

        client.update_item("Nutzer", data[0].get('id'), {"Mollie_CUSTOMER_ID": customer['id']})
    else:
        session['Mollie_CUSTOMER_ID'] = data[0].get('Mollie_CUSTOMER_ID')
    session['Nutzer_Level'] = data[0].get('Nutzer_Level')
    nutzer_id = data[0].get('id')
    nutzer_punkte = int(data[0].get('Punkte'))
    session['Nutzer_Punkte'] = nutzer_punkte
    nutzer_level = session.get('Nutzer_Level')
    whitelabel_details = g.whitelabel_info

    if nutzer_punkte >= whitelabel_details['Badge_Willkommen_Punkte']:
        if nutzer_level != "Willkommen":
            updated_item = client.update_item("Nutzer", nutzer_id, {'Nutzer_Level': "Willkommen"})
            session['Nutzer_Level'] == updated_item.get('Nutzer_Level')
    
    if nutzer_punkte >= whitelabel_details['Badge_2_Punkte']:
        if nutzer_level != "2":
            updated_item = client.update_item("Nutzer", nutzer_id, {'Nutzer_Level': "2"})
            session['Nutzer_Level'] == updated_item.get('Nutzer_Level')
            
    if nutzer_punkte >= whitelabel_details['Badge_3_Punkte']:
        if nutzer_level != "3":
            updated_item = client.update_item("Nutzer", nutzer_id, {'Nutzer_Level': "3"})
            session['Nutzer_Level'] == updated_item.get('Nutzer_Level')
            
    if nutzer_punkte >= whitelabel_details['Badge_4_Punkte']:
        if nutzer_level != "4":
            updated_item = client.update_item("Nutzer", nutzer_id, {'Nutzer_Level': "4"})
            session['Nutzer_Level'] == updated_item.get('Nutzer_Level')
            
    if nutzer_punkte >= whitelabel_details['Badge_5_Punkte']:
        if nutzer_level != "5":
            updated_item = client.update_item("Nutzer", nutzer_id, {'Nutzer_Level': "5"})
            session['Nutzer_Level'] == updated_item.get('Nutzer_Level')
            
    if nutzer_punkte >= whitelabel_details['Badge_6_Punkte']:
        if nutzer_level != "6":
            updated_item = client.update_item("Nutzer", nutzer_id, {'Nutzer_Level': "6"})
            session['Nutzer_Level'] == updated_item.get('Nutzer_Level')

    if session.get('Nutzer_Level') != "6":
        if session.get('Nutzer_Level') == "Willkommen":
            session['Next_Level_Upgrade'] = int(whitelabel_details['Badge_2_Punkte']) - int(nutzer_punkte)
        elif session.get('Nutzer_Level') == "2":
            session['Next_Level_Upgrade'] = int(whitelabel_details['Badge_3_Punkte']) - int(nutzer_punkte)
        elif session.get('Nutzer_Level') == "3":
            session['Next_Level_Upgrade'] = int(whitelabel_details['Badge_4_Punkte']) - int(nutzer_punkte)
        elif session.get('Nutzer_Level') == "4":
            session['Next_Level_Upgrade'] = int(whitelabel_details['Badge_5_Punkte']) - int(nutzer_punkte)
        elif session.get('Nutzer_Level') == "5":
            session['Next_Level_Upgrade'] = int(whitelabel_details['Badge_6_Punkte']) - int(nutzer_punkte)

    if data[0].get('RECHTE') == []:
        client.update_item("Nutzer", data[0].get('id'), {"RECHTE": rollen_infos['Rechte']})

    g.rolle = data[0].get('Rolle')

    try:
        # Check the password using argon2
        ph.verify(passwort_hash, password)
        print("Richtiges Passwort")
        return True  # Anmeldeinformationen korrekt
    except VerifyMismatchError:
        print("Falsches Passwort")
        return False  # Anmeldeinformationen inkorrekt
    
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

@app.route('/', methods=['GET', 'POST'])
async def login():
    if session.get('logged_in') != True:
        redirect_url = None  # Voreinstellung auf None setzen
        if request.cookies.get('PP360-Redirect') != None:
            redirect_url = request.cookies.get('PP360-Redirect')
            if redirect_url.startswith("http://"):
                # Replace "http://" with "https://"
                redirect_url = redirect_url.replace("http://", "https://")
            print(redirect_url)


        if request.method == 'POST':
            data = await request.form

            recaptcha_response = data.get('g-recaptcha-response')
            google_data = {
                'secret': config['Google_Recaptcha']['key'],
                'response': recaptcha_response
            }
            
            # Überprüfen des reCAPTCHA
            response = requests.post('https://www.google.com/recaptcha/api/siteverify', data=google_data)
            result = response.json()

            if not result.get('success'):
                session['error'] = f'Das Captcha war ungültig. Bitte versuche es erneut!'
                return redirect(f'https://auth.{g.customer_domain}/')
            

            username = data.get('username')
            password = data.get('password')
            #return f"NUtzer: {username}, Passwort {password}"
            remember_me = data.get('remember-me')
            print(data.get('remember-me'))

            
            if await check_credentials(username, password):
                ip = request.headers.get('X-Forwarded-For')  # Holen Sie die IP des Benutzers
                banned_ips = session.get('Banned_IPs', [])

                if banned_ips is None:
                    banned_ips = []

                if ip not in banned_ips:
                    session['success'] = f'Sie sind nun als {g.rolle} angemeldet!'
                    session['logged_in'] = True
                    session['username'] = g.username
                    session['ip'] = ip
                    
                    # IP-Adresse des Benutzers abrufen
                    ip = request.headers.get('X-Forwarded-For')
                    # Durchgeführte Aktion
                    action = "Anmeldung"

                    print("Remember_Me: ", remember_me)
                    if remember_me == 'on':
                        session.permanent = True  # Macht die Session permanent
                        session['_permanent'] = True
                    else:
                        session.permanent = False  # Setzt die Session auf nicht permanent
                        session['_permanent'] = False

                    return redirect(f"https://auth.{g.customer_domain}/willkommen")
                else:
                    session['error'] = f'Diese IP-Adresse wurde für das Benutzerkonto gesperrt.'
                    return redirect(f"https://www.{g.customer_domain}/")
            else:
                session['error'] = f'Ungültige Anmeldeinformationen.'
                return redirect(f"https://auth.{g.customer_domain}/")

        # GET-Anfrage, zeigt die Login-Seite an
        
        success = session.pop('success', None)
        error = session.pop('error', None)
        return await render_template('/Seiten/login.html', success=success, error=error, redirect=redirect_url, customer_domain = g.customer_domain, WhiteLabel = g.whitelabel_info)
    else:
        if request.cookies.get('PP360-Redirect') is not None:
            redirect_url = request.cookies.get('PP360-Redirect')  # Holen Sie den Redirect-URL aus dem Cookie
            response = redirect(redirect_url)  # Erstellen Sie eine Antwort mit einer Umleitung
            response.set_cookie('PP360-Redirect', '', expires=0, path='/', domain=f'.{g.whitelabel_info['Domain']}', secure=True, httponly=True)
            
            return response
        else:
            return redirect(f"https://www.{g.customer_domain}/")
        

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
        
@app.route('/register', methods=['GET', 'POST'])
async def register():
    if AUFBAUMODUS != True:
        if session.get('logged_in') != True:
            Referrer_ID = request.args.get('Referrer_ID')
            if Referrer_ID:
                Referrer_Nutzer = client.get_item('Nutzer', int(Referrer_ID))
            else:
                Referrer_Nutzer = None

            redirect_url = None  # Voreinstellung auf None setzen
            if request.cookies.get('PP360-Redirect') != None:
                redirect_url = request.cookies.get('PP360-Redirect')
                if redirect_url.startswith("http://"):
                    # Replace "http://" with "https://"
                    redirect_url = redirect_url.replace("http://", "https://")
                print(redirect_url)


            if request.method == 'POST':
                data = await request.form

                recaptcha_response = data.get('g-recaptcha-response')
                google_data = {
                    'secret': config['Google_Recaptcha']['key'],
                    'response': recaptcha_response
                }
                
                # Überprüfen des reCAPTCHA
                response = requests.post('https://www.google.com/recaptcha/api/siteverify', data=google_data)
                result = response.json()

                if not result.get('success'):
                    session['error'] = f'Das Captcha war ungültig. Bitte versuche es erneut!'
                    return redirect(f'https://auth.{g.customer_domain}/register')
                
                Nutzer_Daten = {
                    "Vorname": data.get('Vorname'),
                    "Nachname": data.get('Nachname'),
                    "Benutzername": data.get('Benutzername'),
                    "EMail": data.get('EMail'),
                    "Passwort": data.get('Passwort')
                }

                Nutzer_AUSSTEHEND = client.create_item("Nutzer_AUSSTEHEND", item_data=Nutzer_Daten)


                emailTemplate = await render_template('/Email-Templates/KontoAktivieren.html', Nutzer = Nutzer_AUSSTEHEND['data'], WhiteLabel = g.whitelabel_info)
                await send_html_email("Aktiviere Dein Benutzerkonto", Nutzer_AUSSTEHEND['data']['EMail'], emailTemplate)

                session['success'] = "Du hast eine Bestätigungs-Email zur Aktivierung deines Benutzerkontos erhalten."

                

            # GET-Anfrage, zeigt die Login-Seite an
            
            success = session.pop('success', None)
            error = session.pop('error', None)

            if Referrer_ID:
                if Referrer_Nutzer:
                    success = f"Du wurdest erfolgreich von '{Referrer_Nutzer['Vorname']} {Referrer_Nutzer['Nachname']}' angeworben. Registriere dich nun :)"

            return await render_template('/Seiten/register.html', success=success, error=error, redirect=redirect_url, customer_domain = g.customer_domain, WhiteLabel = g.whitelabel_info, Referrer_Nutzer=Referrer_Nutzer)
        else:
            if request.cookies.get('PP360-Redirect') is not None:
                redirect_url = request.cookies.get('PP360-Redirect')  # Holen Sie den Redirect-URL aus dem Cookie
                response = redirect(redirect_url)  # Erstellen Sie eine Antwort mit einer Umleitung
                response.set_cookie('PP360-Redirect', '', expires=0, path='/', domain=f'.{g.whitelabel_info['Domain']}', secure=True, httponly=True)
                
                return response
            else:
                return redirect(f"https://www.{g.customer_domain}/")
    else:
        session['error'] = f'Die Registrierung ist derzeit deaktiviert.'
        return redirect(f"https://auth.{g.customer_domain}/")

@app.route('/KontoAktivierung/<SECRET>', methods=['GET'])
async def KontoAktivierung(SECRET):
    request_directus = {
        "query": {
            "filter": {
                "Secret": {
                    "_eq": SECRET  # Filter für die Domain
                }
            }
        }
    }


    # Die Items von der Collection "WhiteLabel" abrufen
    try:
        data = client.get_items("Nutzer_AUSSTEHEND", request_directus)

        print(data)
        if 'error' in data:
            session['error'] = f'Der Token für die Konto-Aktivierung war ungültig.'
            return redirect(f"https://auth.{g.customer_domain}/")
        else:
            if data:  # Überprüfen, ob Daten vorhanden sind
                Austehende_NutzerDetails = data[0]  # Speichere die Whitelabel-Informationen in g
            else:
                session['error'] = f'Der Token für die Konto-Aktivierung war ungültig.'
                return redirect(f"https://auth.{g.customer_domain}/")
    except Exception as e:
        session['error'] = f'Der Token für die Konto-Aktivierung war ungültig.'
        return redirect(f"https://auth.{g.customer_domain}/")

    item_data = {
        "Vorname": Austehende_NutzerDetails['Vorname'],
        "Nachname": Austehende_NutzerDetails['Nachname'],
        "Benutzername": Austehende_NutzerDetails['Benutzername'],
        "EMail": Austehende_NutzerDetails['EMail'],
        "Passwort": Austehende_NutzerDetails['Passwort'],
        "Referrer_BENUTZERNAME": Austehende_NutzerDetails['Referrer_BENUTZERNAME'],
        "Nutzer_Level": "Willkommen",
        "Rolle_RECHTE": {"key":7,"collection":"Nutzer_Rollen"},
        "Punkte": 0
    }

    client.create_item("Nutzer", item_data = item_data)
    client.delete_item("Nutzer_AUSSTEHEND", int(Austehende_NutzerDetails['id']))

    session['success'] = f'Dein Benutzerkonto wurde aktiviert. Du kannst Dich jetzt anmelden!'
    return redirect(f"https://auth.{g.customer_domain}/")

        
@app.route('/PasswortVergessen', methods=['GET', 'POST'])
async def PasswortVergessen():
    if session.get('logged_in') != True:
        Referrer_ID = request.args.get('Referrer_ID')

        redirect_url = None  # Voreinstellung auf None setzen
        if request.cookies.get('PP360-Redirect') != None:
            redirect_url = request.cookies.get('PP360-Redirect')
            if redirect_url.startswith("http://"):
                # Replace "http://" with "https://"
                redirect_url = redirect_url.replace("http://", "https://")
            print(redirect_url)

        if Referrer_ID:
            Referrer_Nutzer = client.get_item('Nutzer', session.get('id'))


        if request.method == 'POST':
            data = await request.form

            recaptcha_response = data.get('g-recaptcha-response')
            google_data = {
                'secret': config['Google_Recaptcha']['key'],
                'response': recaptcha_response
            }
            
            # Überprüfen des reCAPTCHA
            response = requests.post('https://www.google.com/recaptcha/api/siteverify', data=google_data)
            result = response.json()

            if not result.get('success'):
                session['error'] = f'Das Captcha war ungültig. Bitte versuche es erneut!'
                return redirect(f'https://auth.{g.customer_domain}/')
            

            username = data.get('username')
            password = data.get('password')
            #return f"NUtzer: {username}, Passwort {password}"
            remember_me = data.get('remember-me')
            print(data.get('remember-me'))

            
            if await check_credentials(username, password):
                ip = request.headers.get('X-Forwarded-For')  # Holen Sie die IP des Benutzers
                banned_ips = session.get('Banned_IPs', [])

                if banned_ips is None:
                    banned_ips = []

                if ip not in banned_ips:
                    session['success'] = f'Sie sind nun als {g.rolle} angemeldet!'
                    session['logged_in'] = True
                    session['username'] = g.username
                    session['ip'] = ip
                    
                    # IP-Adresse des Benutzers abrufen
                    ip = request.headers.get('X-Forwarded-For')
                    # Durchgeführte Aktion
                    action = "Anmeldung"

                    print("Remember_Me: ", remember_me)
                    if remember_me == 'on':
                        session.permanent = True  # Macht die Session permanent
                        session['_permanent'] = True
                    else:
                        session.permanent = False  # Setzt die Session auf nicht permanent
                        session['_permanent'] = False

                    return redirect(f"https://auth.{g.customer_domain}/willkommen")
                else:
                    session['error'] = f'Diese IP-Adresse wurde für das Benutzerkonto gesperrt.'
                    return redirect(f"https://www.{g.customer_domain}/")
            else:
                session['error'] = f'Ungültige Anmeldeinformationen.'
                return redirect(f"https://auth.{g.customer_domain}/")

        # GET-Anfrage, zeigt die Login-Seite an
        
        success = session.pop('success', None)
        error = session.pop('error', None)

        return await render_template('/Seiten/Passwort/Vergessen.html', success=success, error=error, redirect=redirect_url, customer_domain = g.customer_domain, WhiteLabel = g.whitelabel_info, Referrer_Nutzer=Referrer_Nutzer)
    else:
        session['error'] = "Sie sind bereits angemeldet."
        return redirect(f"https://auth.{g.customer_domain}/willkommen")
        

@app.route('/logout', methods=['GET', 'POST'])
async def logout():
    if session.get('logged_in'):
        success = session.pop('success', None)
        error = session.pop('error', None)

        # IP-Adresse des Benutzers abrufen
        ip = request.headers.get('X-Forwarded-For')
        # Durchgeführte Aktion
        action = "Abmeldung"

        # Löschen aller relevanten Daten aus der Sitzung
        session.pop('Banned_IPs', None)
        session.pop('id', None)
        session.pop('UUID', None)
        session.pop('avatar', None)
        session.pop('rolle', None)
        session.pop('name', None)
        session.pop('email', None)
        session.pop('vorname', None)
        session.pop('nachname', None)
        session.pop('ip', None)
        session.pop('firma', None)
        session.pop('firmenname', None)
        session.pop('firma_UstIdNr', None)
        session.pop('firma_domain', None)
        session.pop('firma_logo', None)
        session.pop('lieferungs_adressen', None)
        session.pop('rechnungs_adressen', None)
        session.pop('random_session_id', None)
        session.pop('timestamp', None)
        session.pop('rechte', None)
        session.pop('WhiteLabel_Domain', None)
        session.pop('WhiteLabel_Admin', None)
        session.pop('WhiteLabel', None)
        session.pop('Nutzer_Level', None)
        session.pop('bildschirm_sperre', None)

        session.pop('Next_Level_Upgrade', None)
        session.pop('Nutzer_Punkte', None)

        session.pop('username', None)
        session.pop('logged_in', None)

        # Erstelle eine Antwort und lösche das Cookie
        response = redirect(f"https://www.{g.customer_domain}/")
        return response
    else:
        session['error'] = "Sie sind nicht angemeldet."
        return redirect(f"https://www.{g.customer_domain}/")


@app.route('/willkommen')
async def willkommen():
    if session.get('logged_in'):
        nutzername = session.get('username')
        name = session.get('name')
        rolle = session.get('rolle')
        success = session.pop('success', None)
        error = session.pop('error', None)

        Next_Level_Upgrade = session.get('Next_Level_Upgrade')
        
        query_ranking = {
            "query": {
                "limit": 5,
                "sort": "-Punkte"  # Ensure sorting is a list, not a string
            }
        }
        nutzer_ranking = client.get_items('Nutzer', query_ranking)

        aktueller_nutzer = client.get_item('Nutzer', session.get('id'))

        return await render_template('/Seiten/Willkommen.html', url=request.url, success=success, error=error , name=name, rolle=rolle, avatar_url=session.get('avatar'), nutzer_level=session.get('Nutzer_Level'), Nutzer_Punkte=session.get('Nutzer_Punkte'), WHITELABEL_Domain=g.customer_domain, WhiteLabel = g.whitelabel_info, nutzername=nutzername, Session_Info=g.Session_Info['LogEntry_ID'], Next_Level_Upgrade=Next_Level_Upgrade, Nutzer_Ranking=nutzer_ranking, Aktueller_Nutzer=aktueller_nutzer, Nutzer_ID = session.get('id'))
    else:
        session['error'] = "Sie sind nicht angemeldet."
        return redirect(f"https://auth.{g.customer_domain}/")
    

# Der Endpunkt, der die Parameter verarbeitet
@app.route('/test-settings', methods=['POST'])
async def scrollable():
    data = await request.form

    # Nimmt Parameter von der HTML-Seite entgegen
    parameter1 = data.get('parameter1')
    parameter2 = data.get('parameter2')
    
    # Rendern einer HTML-Vorlage und Übergabe der Parameter
    return await render_template('/Seiten/test-whitelabel_TEMPLATE.html', param1=parameter1, param2=parameter2)

@app.route('/white-label/settings', methods=['GET'])
async def whitelabel_settings():
    # Rendern einer HTML-Vorlage und Übergabe der Parameter
    return await render_template('/Seiten/test-whitelabel.html')


@app.route('/sperren')
async def bildschirm_sperren():
    session['bildschirm_sperre'] = True
    session['success'] = "Ihr Bildschirm wurde erfolgreich gesperrt."
    
    if request.args.get('redirect_url'):
        return redirect(request.args.get('redirect_url').replace('http://','https://'))
    else:
        return redirect(f"https://auth.{g.customer_domain}/sperrbildschirm")

@app.route('/sperrbildschirm', methods=['POST', 'GET'])
async def sperrbildschirm():
    if session.get('logged_in'):
        if request.method == "GET":
            if request.args.get('redirect_url'):
                return redirect(request.args.get('redirect_url'))
            else:
                name = session.get('name')
                rolle = session.get('rolle')
                success = session.pop('success', None)
                error = session.pop('error', None)

                return await render_template('/Seiten/lock-screen.html', success=success, error=error , name=name, rolle=rolle, avatar_url=session.get('avatar'), nutzer_level=session.get('Nutzer_Level'), WHITELABEL_Domain=g.customer_domain, WhiteLabel = g.whitelabel_info, nutzername=session.get('username'))
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
        session['error'] = f'Sie sind nicht angemeldet.'
        return redirect(f"https://auth.{g.customer_domain}/")
    

@app.context_processor
def inject_current_year():
    return {'current_year': datetime.now().year}

@app.route('/test/email-template/aktivieren')
async def TEST_EMailTemplates_BenutzerkontoAKTIVIEREN():
    Nutzer = {
        "Vorname": "Max",
        "Nachname": "Mustermann",
        "EMail": "Max.Mustermann@EMail.de",
        "Secret": "UUID"
    }

    return await render_template('/Email-Templates/KontoAktivieren.html', Nutzer = Nutzer, WhiteLabel = g.whitelabel_info)