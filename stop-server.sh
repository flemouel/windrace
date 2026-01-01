#!/bin/bash

# WindGame local server stop script
PIDFILE=".server.pid"
LOGFILE=".server.log"

# Check if PID file exists
if [ ! -f "$PIDFILE" ]; then
    echo "ℹ️  No server running"
    exit 0
fi

# Read PID
PID=$(cat "$PIDFILE")

# Check if process exists
if ! ps -p $PID > /dev/null 2>&1; then
    echo "ℹ️  Server is no longer active (PID: $PID)"
    rm -f "$PIDFILE"
    exit 0
fi

echo "🛑 Stopping WindGame server (PID: $PID)..."

# Try to stop process gracefully (SIGTERM)
kill $PID 2>/dev/null

# Wait up to 5 seconds for process to terminate
for i in {1..10}; do
    if ! ps -p $PID > /dev/null 2>&1; then
        echo "✅ Server stopped successfully"
        rm -f "$PIDFILE"
        exit 0
    fi
    sleep 0.5
done

# If process is still active, force stop (SIGKILL)
echo "⚠️  Force stopping server..."
kill -9 $PID 2>/dev/null
sleep 1

if ! ps -p $PID > /dev/null 2>&1; then
    echo "✅ Server stopped (forced)"
    rm -f "$PIDFILE"
    exit 0
else
    echo "❌ Unable to stop server"
    exit 1
fi
