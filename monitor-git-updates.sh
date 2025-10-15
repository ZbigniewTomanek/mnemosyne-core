#!/bin/bash

# Git Monitor Script for Telegram Bot Service
# This script checks for new git commits and restarts the service if updates are found

# These values will be configured by setup-bot.sh
PROJECT_DIR=""
PLIST_FILE=""
LOG_FILE=""
BRANCH="main"

# Create log directory if it doesn't exist
mkdir -p "$PROJECT_DIR/out/log"

log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "$LOG_FILE"
  echo "$1"
}

# Record the current commit hash
get_current_commit() {
  git -C "$PROJECT_DIR" rev-parse HEAD
}

# Check for updates and restart if needed
check_and_update() {
  cd "$PROJECT_DIR" || exit 1

  # Save current commit hash
  CURRENT_COMMIT=$(get_current_commit)

  log "Checking for updates on branch $BRANCH..."

  # Fetch from remote
  git fetch origin "$BRANCH" >> "$LOG_FILE" 2>&1

  # Get latest commit hash
  LATEST_COMMIT=$(git rev-parse origin/"$BRANCH")

  # If there are new commits
  if [ "$CURRENT_COMMIT" != "$LATEST_COMMIT" ]; then
    log "New commits detected: $CURRENT_COMMIT -> $LATEST_COMMIT"

    # Pull the changes
    log "Pulling updates..."
    git pull origin "$BRANCH" >> "$LOG_FILE" 2>&1

    # Restart the service
    log "Restarting telegram bot service..."
    launchctl unload "$PLIST_FILE" >> "$LOG_FILE" 2>&1
    launchctl load "$PLIST_FILE" >> "$LOG_FILE" 2>&1

    log "Service restarted successfully"
  else
    log "No updates found."
  fi
}

# Run the update check
check_and_update
