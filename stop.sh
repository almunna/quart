#!/bin/bash
# AUTOSTOP

echo "Stoppe Skript für Admin-Panel..."
screen -S Admin-Panel -X quit
echo "Skript für Admin-Panel gestoppt."

echo "Stoppe Skript für CDN..."
screen -S CDN -X quit
echo "Skript für CDN gestoppt."

echo "Stoppe Skript für Authentication-Server..."
screen -S Authentication -X quit
echo "Skript für Authentication-Server gestoppt."

echo "Stoppe Skript für Dashboard..."
screen -S Dashboard -X quit
echo "Skript für Dashboard gestoppt."

echo "Stoppe Skript für Webseite..."
screen -S Webseite -X quit
echo "Skript für Webseite gestoppt."