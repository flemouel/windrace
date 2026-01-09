# 🌊 WindGame - Quick Start

## Launch in 2 steps

### 1. Start the server

**Recommended method (background):**
```bash
./start-server.sh
```

**Alternative (foreground):**
```bash
python3 backend/server.py
```

**To stop the server:**
```bash
./stop-server.sh
```

### 2. Open in browser

Open your browser at: **http://localhost:8000**

## ⚠️ Prerequisites

- **Python 3.x** installed
  - Check: `python3 --version`
- Internet connection (for Google Maps)

## 🎮 How to Play

1. **Read the rules**: Info panel displays at startup
2. Click **"Play"** to hide the panel
3. Click **"Start"** to begin the race (countdown 3-2-1)
4. Click **"Tack"** to change tack at the right moment
5. **Watch the ranking** in real-time on the right
6. Beat the black boat to win!

## 🏆 Achievements

Win with a good margin to get an achievement:
- **100m+ lead**: "Outstanding!" 🌟
- **50-99m**: "Great job!" ⭐
- **20-49m**: "Well done!" ✨

## 🔧 Differences from online version

- ✅ **Local Python server** (replaces PHP)
- ✅ **Real wind data** from winddata/wind_data.json (direction + speed)
- ✅ **No authentication** (play directly)
- ✅ **Real-time ranking** during race
- ✅ **Auto-scroll to results** at end of game

## 📁 Structure

```
windgame/
├── frontend/
│   └── index.html      ← Main game page
├── start-server.sh     ← Launch script
├── stop-server.sh      ← Stop script
├── backend/            ← Backend server
│   └── server.py       ← Python server (emulates PHP endpoints)
├── css/                ← Styles + wave animations
├── js/                 ← JavaScript code (navigation, boats)
├── images/             ← Images, SVG, wave textures
├── winddata/           ← Wind data
│   └── wind_data.json  ← Real wind data (direction + speed)
└── resdata/            ← Results data (leaderboard)
```

## ❓ Common Issues

**Map doesn't display?**
→ Check your Internet connection
→ Open browser console (F12)

**Server doesn't start?**
→ Check that Python 3 is installed: `python3 --version`
→ Check that port 8000 is free

**Port 8000 already in use?**
→ Edit `backend/server.py` line 255: change `8000` to `8080`

**Start button stays grayed out?**
→ Wait 2 seconds (loading wind data)
→ Reload the page

**Boats don't appear?**
→ Wait for countdown to finish (3-2-1)
→ Check console for errors

---

For more details, see [README.md](README.md)
