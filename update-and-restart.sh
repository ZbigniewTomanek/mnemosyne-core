#!/bin/bash

echo "Checking for repository updates..."
git fetch -a

# Compare commits
echo "New commits found. Updating repository..."
git reset --hard origin/main

echo "Restarting service..."
launchctl unload /Users/zbigi/Library/LaunchAgents/com.user.my-telegram-bot.plist
launchctl load /Users/zbigi/Library/LaunchAgents/com.user.my-telegram-bot.plist

echo "Update completed successfully!"
