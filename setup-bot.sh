#!/bin/bash

# Configuration
BOT_NAME="my-telegram-bot"
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLIST_FILE="$HOME/Library/LaunchAgents/com.user.${BOT_NAME}.plist"
MONITOR_PLIST_FILE="$HOME/Library/LaunchAgents/com.user.${BOT_NAME}-monitor.plist"
LOG_FILE="$PROJECT_DIR/out/log/service.log"
MONITOR_LOG_FILE="$PROJECT_DIR/out/log/git-monitor.log"

# Create the logs directory if it doesn't exist
mkdir -p "$PROJECT_DIR/out/log"
mkdir -p "$HOME/Library/LaunchAgents"

# Create the LaunchAgent plist file
cat >"$PLIST_FILE" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.user.${BOT_NAME}</string>

    <key>WorkingDirectory</key>
    <string>${PROJECT_DIR}</string>

    <key>EnvironmentVariables</key>
    <dict>
        <key>PYTHONPATH</key>
        <string>${PROJECT_DIR}</string>
        <key>PATH</key>
        <string>/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    </dict>

    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>run-bot.sh</string>
    </array>

    <key>StandardOutPath</key>
    <string>${LOG_FILE}</string>

    <key>StandardErrorPath</key>
    <string>${LOG_FILE}</string>

    <key>RunAtLoad</key>
    <true/>

    <key>KeepAlive</key>
    <true/>

    <key>ThrottleInterval</key>
    <integer>10</integer>
</dict>
</plist>
EOF

# Set proper permissions
chmod 644 "$PLIST_FILE"

# Configure the git monitor script with the correct paths
sed -i '' "s|^PROJECT_DIR=.*|PROJECT_DIR=\"$PROJECT_DIR\"|" "$PROJECT_DIR/monitor-git-updates.sh"
sed -i '' "s|^PLIST_FILE=.*|PLIST_FILE=\"$PLIST_FILE\"|" "$PROJECT_DIR/monitor-git-updates.sh"
sed -i '' "s|^LOG_FILE=.*|LOG_FILE=\"$MONITOR_LOG_FILE\"|" "$PROJECT_DIR/monitor-git-updates.sh"

# Make the monitor script executable
chmod +x "$PROJECT_DIR/monitor-git-updates.sh"

# Create the monitor LaunchAgent plist file
cat >"$MONITOR_PLIST_FILE" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.user.${BOT_NAME}-monitor</string>

    <key>WorkingDirectory</key>
    <string>${PROJECT_DIR}</string>

    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>monitor-git-updates.sh</string>
    </array>

    <key>StandardOutPath</key>
    <string>${MONITOR_LOG_FILE}</string>

    <key>StandardErrorPath</key>
    <string>${MONITOR_LOG_FILE}</string>

    <key>StartInterval</key>
    <integer>300</integer>

    <key>RunAtLoad</key>
    <true/>
</dict>
</plist>
EOF

# Set proper permissions
chmod 644 "$MONITOR_PLIST_FILE"

# Load both services
launchctl load "$PLIST_FILE"
launchctl load "$MONITOR_PLIST_FILE"

echo "Telegram bot service has been set up with git update monitoring!"
echo "Service logs available at: $LOG_FILE"
echo "Git monitor logs available at: $MONITOR_LOG_FILE"
echo "Git repository will be checked for updates every 5 minutes"
