# 🌊 WindGame - Démarrage Rapide

## Lancement en 2 étapes

### 1. Démarrer le serveur

```bash
./start-server.sh
```

Ou manuellement avec PHP:
```bash
php -S localhost:8000
```

Ou avec Python:
```bash
python3 server.py
```

### 2. Ouvrir dans le navigateur

Ouvrez votre navigateur à: **http://localhost:8000**

## ⚠️ Prérequis

- **PHP** (recommandé) ou **Python 3** installé
  - Vérifiez PHP: `php -v`
  - Vérifiez Python: `python3 --version`
- Connexion Internet (pour Google Maps)

## 🎮 Comment jouer

1. La carte se charge automatiquement
2. Cliquez sur **"Start"** pour commencer
3. Cliquez sur **"Tack"** pour virer de bord
4. Battez le bateau noir!

## 🔧 Différences avec la version en ligne

- ✅ **Données de vent simulées** (au lieu de la vraie station météo)
- ✅ **Pas besoin de connexion** (sauf pour Google Maps)
- ✅ **Pas d'authentification requise**

## 📁 Structure

```
windgame/
├── index.html          ← Page principale
├── start-server.sh     ← Script de lancement
├── css/                ← Styles
├── js/                 ← Code JavaScript
├── images/             ← Images et icônes
├── scripts/            ← Backend PHP (simulé)
└── README.md           ← Documentation complète
```

## ❓ Problèmes courants

**La carte ne s'affiche pas?**
→ Vérifiez votre connexion Internet

**Erreur de serveur?**
→ Vérifiez que PHP ou Python est installé
→ PHP: `php -v`
→ Python: `python3 --version`

**Port 8000 déjà utilisé?**
→ PHP: `php -S localhost:8080`
→ Python: Modifiez `server.py` ligne 134

---

Pour plus de détails, voir [README.md](README.md)
