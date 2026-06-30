# Brewery

Homebrew package inventory for macOS fleets. A lightweight agent runs on each Mac, collects installed formulae and casks via `brew`, and reports them to a central server. The web UI shows installed packages per host, version distribution across the estate, outdated packages with one-click upgrade queuing, and lets you push install/uninstall/upgrade commands to individual hosts or the whole fleet.

## Components

- **server** — FastAPI + PostgreSQL, serves the REST API and web UI
- **agent** — Go binary, runs as a macOS LaunchDaemon and syncs every 15 minutes

## Server

The server image is published to the GitHub Container Registry.

```sh
podman run -d \
  -e BREWERY_DATABASE_URL=postgresql://brewery:brewery@db/brewery \
  -e BREWERY_API_KEY=your-secret-key \
  -p 6502:6502 \
  ghcr.io/cpressland/brewery:latest
```

A Compose file is included for running Postgres alongside the server:

```sh
podman compose up -d
brewery-server
```

### Server environment variables

| Variable | Default | Description |
|---|---|---|
| `BREWERY_DATABASE_URL` | `postgresql://brewery:brewery@localhost/brewery` | PostgreSQL connection string |
| `BREWERY_API_KEY` | *(unset)* | Shared secret required in agent requests. Leave unset to disable auth |
| `BREWERY_PASSWORD` | *(unset)* | Password for the web UI login page. Leave unset to disable auth |
| `SECRET_KEY` | `brewery-dev-secret` | Secret used to sign session cookies. Set to a random value in production |

## Agent

### Quick install

The server generates a personalised install script at `/install` with the server URL and API key already embedded:

```sh
curl -fsSL https://your-brewery-server/install | sh
```

Logs are written to `/var/log/brewery-agent.log`.

### Build

```sh
cd agent
go build -o brewery-agent .
```

### Manual install

```sh
sudo cp brewery-agent /usr/local/bin/brewery-agent
```

Create `/Library/LaunchDaemons/com.brewery.agent.plist` with `BREWERY_SERVER_URL` and `BREWERY_API_KEY` set, then load the daemon:

```sh
sudo launchctl load /Library/LaunchDaemons/com.brewery.agent.plist
```

Logs are written to `/var/log/brewery-agent.log`.

### Agent environment variables

| Variable | Required | Description |
|---|---|---|
| `BREWERY_SERVER_URL` | Yes | Base URL of the server, e.g. `http://brewery.internal:6502` |
| `BREWERY_API_KEY` | No | Must match the server's `BREWERY_API_KEY` if set |

### Versioning

```sh
brewery-agent --version
```
