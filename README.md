# SailRacer.net Wind Game - Local Version

This local version of the WindGame sailing game can run on your computer in standalone mode with a Python server.

## Prerequisites

- Python 3.x
- Internet connection (for Google Maps API)
- Modern web browser

## Installation and Startup

### Starting the development server

**Option 1: Background mode (recommended)**

```bash
./start-server.sh
```

The server starts in the background and continues running even if you close the terminal.

To stop it:
```bash
./stop-server.sh
```

To view logs in real-time:
```bash
tail -f .server.log
```

**Option 2: Interactive mode**

```bash
python3 server.py
```

The server runs in the foreground. Use `Ctrl+C` to stop it.

**Accessing the game**

The server starts on `http://localhost:8000`

Open your browser at: `http://localhost:8000`

## Features

### Available locally:
- ✅ Complete sailing game with wind simulation
- ✅ Google Maps display
- ✅ Navigation and tacking calculations
- ✅ Performance-based scoring and achievements system
- ✅ Simulated leaderboard
- ✅ Real-time ranking during race
- ✅ Auto-scroll to results at end of game
- ✅ Wave animations based on wind strength

### Requiring Internet:
- 🌐 Google Maps API (for map display)
- 🌐 Google Fonts (for fonts)
- 🌐 jQuery and jQuery UI (CDN)

### Simulation Mode:
Wind data is simulated locally because the real Nanny Cay weather station is not accessible locally. The Python server in `server.py` emulates all PHP endpoints and generates random but realistic wind data.

## File Structure

```
windgame/
├── index.html           # Main game page
├── server.py            # Python development server (emulates PHP endpoints)
├── start-server.sh      # Background server start script
├── stop-server.sh       # Server stop script
├── css/                 # Stylesheets
│   ├── screen.css       # Main and responsive styles
│   └── waves.css        # Wave animations (25 levels)
├── js/                  # JavaScript scripts
│   ├── boat.js          # Boat class for navigation logic
│   └── usgsoverlay.js   # Google Maps overlay to display boats
├── images/              # Images and SVG
│   ├── wave1.png        # Light waves texture (5-50px)
│   ├── wave2.png        # Medium waves texture (100x20-65px)
│   └── wave3.png        # Strong waves texture (50-100px)
└── resdata/             # Results data
    └── table.html       # Simulated leaderboard

```

## Technical Architecture

### Python Server (server.py)

The Python server emulates PHP endpoints from the online version:

- **GET /scripts/service.php**: Generates simulated wind data (direction and speed)
- **GET /scripts/record.php**: Records results and assigns achievements
- **POST /scripts/wind.php**: Returns current wind status
- **POST /scripts/save.php**: Empty endpoint for compatibility
- **GET /images/avatar.php**: Returns a default SVG avatar

### Game Logic (index.html)

#### Game flow:
1. **Initialization**: Load wind data via `loadDataIdle()`
2. **Start**: Click "Start" → `started = true` → 3s countdown
3. **Race**: `process()` loop updates positions every 100ms
4. **Tacking**: Click "Tack" → change tack with 10% speed penalty
5. **End**: When distance < 20m → send results → display

#### Scoring system:
- **finalresult = srdistance - mydistance**
  - Negative = lost (black boat closer)
  - Positive = won (your boat closer)

#### Achievements (based on winning margin):
- ≥ 100m → "Outstanding!"
- ≥ 50m → "Great job!"
- ≥ 20m → "Well done!"
- < 20m → no achievement
- Lost → no achievement

### Navigation and Physics

#### Navigation angles:
- **Wind angle**: 43° (defined in `tackangle`)
- **Tack delay**: Speed penalty for 1 second after tacking
- **Laylines**: Lines showing optimal trajectories to the mark

#### Calculations:
- Distance calculated with Google Maps Geometry API
- Heading calculated with `computeHeading()`
- Movement based on wind speed divided by 2.2

### Real-Time Ranking System

The `updateRanking()` function (lines 838-879) displays ranking during the race:
- Sorts boats by remaining distance
- Displays in `#ranking_display`
- Updated every `process()` frame

### Modifications from online version

1. **Backend**: Python server instead of PHP
2. **Wind data**: Simulated instead of real Nanny Cay weather station
3. **Authentication**: Disabled (no login required)
4. **PHP files**: All removed (not used locally)

## Troubleshooting

### Map doesn't display
- Check your Internet connection
- Check that Google Maps API is not blocked
- Open browser console to see errors

### Wind data doesn't load
- Make sure `server.py` is running
- Check that port 8000 is not already in use
- Check Python server logs in terminal or `.server.log`

### Start button stays disabled
- Wait 2 seconds for initialization to complete
- Reload the page
- Check console for JavaScript errors

### Boats don't appear
- Wait for countdown to finish (3-2-1)
- Check that wind is loaded (look at console logs)

## How to Play

### Objective
Reach the mark (green buoy) before the black computer boat while sailing upwind.

### Instructions

1. **Start the server**: `./start-server.sh` or `python3 server.py`
2. **Open browser**: `http://localhost:8000`
3. **Read the rules**: Info panel displays at startup
4. **Click "Play"**: Hides the panel and prepares the map
5. **Click "Start"**: Starts countdown (3-2-1)
6. **Tack**: Click "Tack" to change tack at the right moment
7. **Watch ranking**: Real-time on the right side of screen
8. **Race end**: When a boat reaches within 20m of the mark
9. **Results**: Panel automatically slides up and scrolls to results

### Strategy

- **Wind**: Observe wind arrow (top right) and adapt your course
- **Laylines**: Blue lines show optimal trajectories
- **Tacking**: Costs 10% speed for 1 second → don't tack too much!
- **Waves**: Animation shows wind strength (faster = stronger)
- **Distance**: Displayed in real-time under wind arrow (margin in meters)

### Buttons

- **Play**: At first launch, hides info panel
- **Start**: Begins the race
- **Tack**: Change tack during race
- **Try again**: If lost, restart a race
- **Play again**: If won, play again

### Achievements

Win with a comfortable margin to get an achievement:
- **100m+ lead**: "Outstanding!"
- **50-99m lead**: "Great job!"
- **20-49m lead**: "Well done!"

## Development

### Important variables

In [index.html](index.html):

- `started` (line 246): Game state (true = racing)
- `finished` (line 245): Race finished
- `finalresult` (line 806): Win/loss margin in meters
- `mydistance` / `srdistance`: Remaining distances for each boat
- `windindex`: Index in wind data array

### Main functions

- `reset()` (line 378): Resets the game
- `loadDataIdle()` (line 434): Loads wind data at rest
- `loadData()` (line 455): Loads wind data to start race
- `process()` (line 755): Main game loop (100ms)
- `onGameFinish()` (line 181): Handles end of game and results display
- `updateRanking()` (line 838): Updates real-time ranking

### Python endpoints

In [server.py](server.py):

- `handle_service()` (line 48): Generates wind data
- `handle_record()` (line 110): Records results and assigns achievements
- `handle_wind()` (line 141): Returns wind status
- `handle_avatar()` (line 194): Generates SVG avatar

## Git Repository

The project is versioned on GitHub: https://github.com/flemouel/windrace.git

```bash
# Clone the repo
git clone https://github.com/flemouel/windrace.git

# Start the server
cd windrace
./start-server.sh
```

## License

Educational project based on SailRacer.net.
