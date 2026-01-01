# SailRacer.net Wind Game - Version Locale

Cette version locale du jeu de voile WindGame peut fonctionner sur votre ordinateur tout en accédant à Internet pour les services externes (Google Maps, etc.).

## Prérequis

- Un serveur web local avec support PHP (Apache, Nginx, ou un serveur de développement PHP)
- Une connexion Internet (pour Google Maps API et autres services externes)
- Un navigateur web moderne

## Installation

### Option 1: Serveur PHP intégré (Recommandé pour le développement)

La façon la plus simple est d'utiliser le serveur web intégré de PHP:

```bash
php -S localhost:8000
```

Puis ouvrez votre navigateur à: `http://localhost:8000`

### Option 2: MAMP/XAMPP/WAMP

1. Copiez ce dossier dans le répertoire htdocs/www de votre serveur local
2. Démarrez votre serveur Apache et PHP
3. Accédez à `http://localhost/windgame/`

## Fonctionnalités

### Disponibles en local:
- ✅ Jeu de voile complet avec simulation de vent
- ✅ Affichage de la carte Google Maps
- ✅ Calculs de navigation et virements
- ✅ Système de scoring et achievements
- ✅ Leaderboard simulé

### Nécessitant Internet:
- 🌐 Google Maps API (pour l'affichage de la carte)
- 🌐 Google Fonts (pour les polices)
- 🌐 jQuery et jQuery UI (CDN)
- 🌐 Facebook/Twitter sharing (optionnel)

### Mode Simulation:
Les données de vent sont simulées localement car la station météo réelle de Nanny Cay n'est pas accessible en local. Les fichiers PHP dans `/scripts/` génèrent des données de vent aléatoires mais réalistes.

## Structure des fichiers

```
windgame/
├── index.html           # Page principale
├── css/                 # Feuilles de style
├── js/                  # Scripts JavaScript
├── images/              # Images et SVG
├── scripts/             # Scripts PHP backend (simulés)
│   ├── service.php      # Simulation de données de vent
│   ├── record.php       # Enregistrement des scores
│   ├── wind.php         # Affichage état du vent
│   └── save.php         # Sauvegarde pour partage
└── generated/           # Contenu dynamique
    └── table.html       # Leaderboard

```

## Modifications par rapport à la version en ligne

1. **Données de vent**: Simulées localement au lieu de la vraie station météo de Nanny Cay
2. **Chemins des fichiers**: Adaptés pour fonctionner localement
3. **Backend PHP**: Scripts simplifiés pour le mode développement
4. **Authentification**: Désactivée (connexion non nécessaire pour jouer)

## Dépannage

### La carte ne s'affiche pas
- Vérifiez votre connexion Internet
- Vérifiez que Google Maps API n'est pas bloqué

### Les données de vent ne se chargent pas
- Assurez-vous que PHP fonctionne correctement
- Vérifiez les permissions des fichiers dans `/scripts/`

### Erreur 404 sur les ressources
- Vérifiez que tous les dossiers (css, js, images, scripts, generated) sont présents
- Lancez le serveur depuis le bon répertoire

## Comment jouer

1. Ouvrez le jeu dans votre navigateur
2. Cliquez sur "Start" pour commencer
3. Cliquez sur "Tack" pour virer de bord au bon moment
4. Essayez de battre le bateau noir (ordinateur) jusqu'à la marque!

Le jeu simule une course au près - vous devez gérer vos virements pour profiter des changements de vent et arriver avant l'ordinateur.

## Licence

Ce projet est une copie locale pour développement/apprentissage. Les droits appartiennent à SailRacer.net.
