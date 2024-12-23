#!/bin/bash
# AUTOSTART

echo "Starte Skripte..."

# Starte die Skripte in einzelnen Bildschirmsitzungen
start_script() {
    local name=$1
    local directory=$2
    local script=$3

    screen -S "$name" -d -m bash -c "cd $directory && ./start.sh"
    sleep 1
    if screen -ls | grep -q "$name"; then
        echo "Skript für $name gestartet."
    else
        echo "Fehler beim Starten des Skripts für $name."
    fi
}

# Aufruf der Funktion für jedes Skript
start_script "Webseite" "/home/personalpeak360/Webseite/Frontend" "./start.sh"
start_script "Authentication-Server" "/home/personalpeak360/Webseite/Authentication" "./start.sh"
start_script "Admin-Panel" "/home/personalpeak360/Webseite/Admin-Panel" "./start.sh"
start_script "CDN" "/home/personalpeak360/Webseite/CDN" "./start.sh"