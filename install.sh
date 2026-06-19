#!/bin/sh
set -e

BREWERY_SERVER_URL="${BREWERY_SERVER_URL:?Set BREWERY_SERVER_URL before running this script}"
BREWERY_API_KEY="${BREWERY_API_KEY:-}"

case "$(uname -m)" in
  arm64)  GOARCH="arm64" ;;
  x86_64) GOARCH="amd64" ;;
  *) echo "error: unsupported architecture: $(uname -m)" >&2; exit 1 ;;
esac

LATEST=$(curl -sI "https://github.com/cpressland/brewery/releases/latest" \
  | grep -i '^location:' \
  | sed 's|.*/tag/||;s/\r//')

echo "installing brewery-agent $LATEST ($GOARCH)"

curl -fsSL \
  "https://github.com/cpressland/brewery/releases/download/$LATEST/brewery-agent-darwin-$GOARCH" \
  -o /tmp/brewery-agent
chmod +x /tmp/brewery-agent
sudo mv /tmp/brewery-agent /usr/local/bin/brewery-agent

curl -fsSL \
  "https://raw.githubusercontent.com/cpressland/brewery/refs/heads/main/com.brewery.agent.plist" \
  -o /tmp/com.brewery.agent.plist

sed -i '' \
  -e "s|http://your-brewery-server:6502|$BREWERY_SERVER_URL|" \
  -e "s|<string></string>|<string>$BREWERY_API_KEY</string>|" \
  /tmp/com.brewery.agent.plist

if [ -f /Library/LaunchDaemons/com.brewery.agent.plist ]; then
  sudo launchctl unload /Library/LaunchDaemons/com.brewery.agent.plist 2>/dev/null || true
fi

sudo cp /tmp/com.brewery.agent.plist /Library/LaunchDaemons/com.brewery.agent.plist
sudo launchctl load /Library/LaunchDaemons/com.brewery.agent.plist

echo "done. brewery-agent $LATEST is running."
