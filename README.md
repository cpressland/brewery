# Brewery

Homebrew package inventory for macOS fleets. A lightweight agent runs on each Mac, collects installed formulae and casks via `brew`, and reports them to a central server. A web UI shows installed packages per host and version distribution across the estate.

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
| `BREWERY_HOST` | `0.0.0.0` | Bind address |
| `BREWERY_PORT` | `6502` | Bind port |

## Agent

### Quick install

```sh
BREWERY_SERVER_URL=http://brewery.internal:6502 \
BREWERY_API_KEY=your-secret-key \
curl -fsSL https://raw.githubusercontent.com/cpressland/brewery/main/install.sh | sh
```

`BREWERY_API_KEY` is optional — omit it if the server has no API key set.

### Build

```sh
cd agent
go build -o brewery-agent .
```

### Install

```sh
sudo cp brewery-agent /usr/local/bin/brewery-agent
sudo cp com.brewery.agent.plist /Library/LaunchDaemons/com.brewery.agent.plist
```

Edit `/Library/LaunchDaemons/com.brewery.agent.plist` to set `BREWERY_SERVER_URL` (and optionally `BREWERY_API_KEY`), then load the daemon:

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
