#!/bin/bash

# Script de démarrage du serveur local WindGame
echo "🌊 Démarrage du serveur WindGame..."
echo "📍 URL: http://localhost:8000"
echo "⛵ Appuyez sur Ctrl+C pour arrêter le serveur"
echo ""

# Vérifier si PHP est disponible
if command -v php &> /dev/null; then
    echo "Utilisation du serveur PHP..."
    php -S localhost:8000
# Sinon utiliser Python
elif command -v python3 &> /dev/null; then
    echo "Utilisation du serveur Python..."
    python3 server.py
else
    echo "❌ Erreur: PHP ou Python3 requis"
    echo "Installez PHP ou Python3 pour continuer"
    exit 1
fi
