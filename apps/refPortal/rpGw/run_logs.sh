#!/bin/bash

app="refportalservice"

# Start logging services in the background
sudo docker service logs -f --raw ${app}_stack_app1 &
PID1=$!

sudo docker service logs -f --raw ${app}_stack_app2 &
PID2=$!

# Function to stop logging on Ctrl+C or Ctrl+Break
cleanup() {
    echo "Stopping log monitoring..."
    kill $PID1 $PID2 2>/dev/null  # Kill background processes
    exit 0
}

# Trap SIGINT (Ctrl+C) and SIGTERM (Ctrl+Break)
trap cleanup SIGINT SIGTERM

# Wait for both processes and pipe output to `grc cat`
wait $PID1
wait $PID2 | grc cat
