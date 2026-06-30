#!/bin/sh
set -e

BREWERY_SERVER_URL="{{ server_url }}"
BREWERY_API_KEY="{{ api_key }}"

case "$(uname -m)" in
  arm64)  GOARCH="arm64" ;;
  x86_64) GOARCH="amd64" ;;
  *) echo "error: unsupported architecture: $(uname -m)" >&2; exit 1 ;;
esac

LATEST=$(curl -sI "https://github.com/cpressland/brewery/releases/latest" \
  | grep -i '^location:' \
  | /usr/bin/sed 's|.*/tag/||;s/\r//')

echo "installing brewery-agent $LATEST ($GOARCH)"

curl -fsSL \
  "https://github.com/cpressland/brewery/releases/download/$LATEST/brewery-agent-darwin-$GOARCH" \
  -o /tmp/brewery-agent
chmod +x /tmp/brewery-agent
sudo mv /tmp/brewery-agent /usr/local/bin/brewery-agent

cat > /tmp/com.brewery.agent.plist << 'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.brewery.agent</string>

  <key>ProgramArguments</key>
  <array>
    <string>/usr/local/bin/brewery-agent</string>
  </array>

  <key>EnvironmentVariables</key>
  <dict>
    <key>BREWERY_SERVER_URL</key>
    <string>{{ server_url }}</string>
    <key>BREWERY_API_KEY</key>
    <string>{{ api_key }}</string>
    <key>PATH</key>
    <string>/opt/homebrew/bin:/usr/local/bin:/usr/sbin:/usr/bin:/bin</string>
  </dict>

  <key>StartInterval</key>
  <integer>900</integer>

  <key>RunAtLoad</key>
  <true/>

  <key>StandardOutPath</key>
  <string>/var/log/brewery-agent.log</string>
  <key>StandardErrorPath</key>
  <string>/var/log/brewery-agent.log</string>
</dict>
</plist>
PLIST

if [ -f /Library/LaunchDaemons/com.brewery.agent.plist ]; then
  sudo launchctl unload /Library/LaunchDaemons/com.brewery.agent.plist 2>/dev/null || true
fi

sudo cp /tmp/com.brewery.agent.plist /Library/LaunchDaemons/com.brewery.agent.plist
sudo launchctl load /Library/LaunchDaemons/com.brewery.agent.plist

echo "done. brewery-agent $LATEST is running."
