#!/bin/bash

# WindGame local server startup script
LOGDIR="logs"
PIDFILE="${LOGDIR}/server.pid"
LOGFILE="${LOGDIR}/server.log"

mkdir -p "$LOGDIR"

# Check if server is already running
if [ -f "$PIDFILE" ]; then
    PID=$(cat "$PIDFILE")
    if ps -p $PID > /dev/null 2>&1; then
        echo "⚠️  Server is already running (PID: $PID)"
        echo "📍 URL: http://localhost:8000"
        echo "🛑 Use ./stop-server.sh to stop it"
        exit 1
    else
        # PID exists but process is no longer active
        rm -f "$PIDFILE"
    fi
fi

# Check if Python3 is available
if ! command -v python3 &> /dev/null; then
    echo "❌ Error: Python3 required"
    echo "Install Python3 to continue"
    echo "macOS: brew install python3"
    echo "Ubuntu: sudo apt install python3"
    exit 1
fi

echo "🌊 Starting WindGame server in background..."
echo "📍 URL: http://localhost:8000"
echo "📝 Logs: $LOGFILE"
echo ""

# Start server in background
nohup python3 backend/server.py >> "$LOGFILE" 2>&1 &
SERVER_PID=$!

# Save PID
echo $SERVER_PID > "$PIDFILE"

# Wait a bit to check server starts correctly
sleep 2

# Check if process is still active
if ps -p $SERVER_PID > /dev/null 2>&1; then
    echo "✅ Server started successfully (PID: $SERVER_PID)"
    echo "🛑 Use ./stop-server.sh to stop it"
    echo "📊 Use 'tail -f $LOGFILE' to view logs"
else
    echo "❌ Error: Server failed to start"
    echo "📝 Check $LOGFILE for details"
    rm -f "$PIDFILE"
    exit 1
fi
