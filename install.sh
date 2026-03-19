#!/bin/bash
set -e

# Daily Dashboard Installer
# Usage: curl -fsSL https://raw.githubusercontent.com/tommertron/dailyDashboard/main/install.sh | bash

VERSION="1.0.0"
DEFAULT_INSTALL_DIR="${HOME}/.daily-dashboard"
DEFAULT_PORT="8000"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Parse arguments
INSTALL_DIR="$DEFAULT_INSTALL_DIR"
PORT="$DEFAULT_PORT"
UPDATE_MODE=false
UNINSTALL_MODE=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --port)
            PORT="$2"
            shift 2
            ;;
        --dir)
            INSTALL_DIR="$2"
            shift 2
            ;;
        --update)
            UPDATE_MODE=true
            shift
            ;;
        --uninstall)
            UNINSTALL_MODE=true
            shift
            ;;
        --help|-h)
            echo "Daily Dashboard Installer v${VERSION}"
            echo ""
            echo "Usage: install.sh [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --port PORT    Set custom port (default: 8000)"
            echo "  --dir PATH     Custom install directory (default: ~/.daily-dashboard)"
            echo "  --update       Update existing installation"
            echo "  --uninstall    Remove installation"
            echo "  --help         Show this help message"
            exit 0
            ;;
        *)
            echo -e "${RED}Unknown option: $1${NC}"
            exit 1
            ;;
    esac
done

# Print banner
echo ""
echo -e "${BLUE}╔════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║       Daily Dashboard Installer        ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════╝${NC}"
echo ""

# Uninstall mode
if [ "$UNINSTALL_MODE" = true ]; then
    echo -e "${YELLOW}Uninstalling Daily Dashboard...${NC}"

    if [ -d "$INSTALL_DIR" ]; then
        cd "$INSTALL_DIR"
        if [ -f "docker-compose.yml" ]; then
            docker compose down 2>/dev/null || true
        fi
        cd ..

        read -p "Remove all data files? This cannot be undone. (y/N) " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            rm -rf "$INSTALL_DIR"
            echo -e "${GREEN}Daily Dashboard completely removed.${NC}"
        else
            echo -e "${YELLOW}Keeping data files at $INSTALL_DIR${NC}"
            echo "Container stopped but files preserved."
        fi
    else
        echo -e "${YELLOW}Installation not found at $INSTALL_DIR${NC}"
    fi
    exit 0
fi

# Check prerequisites
echo "Checking prerequisites..."

# Check Docker
if ! command -v docker &> /dev/null; then
    echo -e "${RED}Docker is required but not installed.${NC}"
    echo ""
    echo "Install Docker:"
    echo "  macOS: https://docs.docker.com/desktop/mac/install/"
    echo "  Linux: https://docs.docker.com/engine/install/"
    exit 1
fi

# Check if Docker is running
if ! docker info &> /dev/null; then
    echo -e "${RED}Docker is installed but not running.${NC}"
    echo "Please start Docker and try again."
    exit 1
fi

# Check Docker Compose
if ! docker compose version &> /dev/null; then
    echo -e "${RED}Docker Compose is required but not available.${NC}"
    echo "Docker Compose is included with Docker Desktop."
    echo "For Linux, see: https://docs.docker.com/compose/install/"
    exit 1
fi

echo -e "${GREEN}Prerequisites OK${NC}"
echo ""

# Update mode
if [ "$UPDATE_MODE" = true ]; then
    echo -e "${YELLOW}Updating Daily Dashboard...${NC}"

    if [ ! -d "$INSTALL_DIR" ]; then
        echo -e "${RED}Installation not found at $INSTALL_DIR${NC}"
        echo "Run without --update to install."
        exit 1
    fi

    cd "$INSTALL_DIR"

    # Stop container
    docker compose down 2>/dev/null || true

    # Update code
    if [ -d ".git" ]; then
        echo "Pulling latest changes..."
        git pull origin main
    else
        echo "Downloading latest version..."
        curl -sL https://github.com/tommertron/dailyDashboard/archive/main.tar.gz | tar xz --strip-components=1 --exclude='*.json' --exclude='*.txt'
    fi

    # Rebuild and start
    echo "Rebuilding container..."
    docker compose up -d --build

    echo ""
    echo -e "${GREEN}Update complete!${NC}"
    echo -e "Dashboard running at: ${BLUE}http://localhost:${PORT}${NC}"
    exit 0
fi

# Fresh install
echo "Installing to: $INSTALL_DIR"
echo "Port: $PORT"
echo ""

# Create install directory
if [ -d "$INSTALL_DIR" ]; then
    echo -e "${YELLOW}Directory already exists: $INSTALL_DIR${NC}"
    read -p "Overwrite? Existing data will be preserved. (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Installation cancelled."
        exit 1
    fi
fi

mkdir -p "$INSTALL_DIR"
cd "$INSTALL_DIR"

# Download or clone repository
echo "Downloading Daily Dashboard..."
if command -v git &> /dev/null; then
    if [ -d ".git" ]; then
        git pull origin main
    else
        git clone https://github.com/tommertron/dailyDashboard.git .
    fi
else
    curl -sL https://github.com/tommertron/dailyDashboard/archive/main.tar.gz | tar xz --strip-components=1
fi

# Initialize data files if they don't exist
echo "Initializing data files..."

# JSON array files
for file in calendar.json daily-links.json starredLinks.json sequelEpisodes.json readlater.json; do
    [ -f "$file" ] || echo '[]' > "$file"
done

# JSON object files
[ -f "anyboxStats.json" ] || echo '{"total_links": 0, "added_last_7_days": 0, "untagged_count": 0}' > anyboxStats.json
[ -f "daily-summary.json" ] || echo '{"summary": "Welcome to Daily Dashboard! Configure your settings to get started.", "generated_at": "", "date": ""}' > daily-summary.json
[ -f "location.json" ] || echo '{"city": "Unknown", "lat": "0", "long": "0"}' > location.json
[ -f "wisdom.json" ] || echo '{"wisdom": "The journey of a thousand miles begins with a single step.", "source": "Lao Tzu"}' > wisdom.json

# Text files
[ -f "money.txt" ] || echo '' > money.txt
[ -f "untaggedLinks.txt" ] || echo '' > untaggedLinks.txt

# Config file (API keys - empty by default)
if [ ! -f "config.json" ]; then
    cat > config.json << 'CONFIGEOF'
{
  "name": "",
  "openWeatherApiKey": "",
  "openaiApiKey": "",
  "homeAssistantApiKey": "",
  "homeAssistantUrl": "",
  "tmdbApiKey": ""
}
CONFIGEOF
fi

# Settings file (use defaults from server.py)
if [ ! -f "settings.json" ]; then
    cat > settings.json << 'SETTINGSEOF'
{
  "version": 2,
  "panels": {
    "weather": {"visible": true},
    "schedule": {"visible": true},
    "tasks": {"visible": true},
    "bills": {"visible": true},
    "readLater": {"visible": true},
    "wisdom": {"visible": true},
    "piStatus": {"visible": false},
    "shed": {"visible": false},
    "home": {"visible": false},
    "tvShows": {"visible": false},
    "anybox": {"visible": false}
  },
  "homeAssistant": {
    "url": "",
    "panels": {}
  },
  "apiUrls": {
    "channelsDvr": "",
    "piMonitor": ""
  },
  "refreshIntervals": {
    "autoRefresh": 300000
  },
  "theme": {
    "preference": "default"
  }
}
SETTINGSEOF
fi

# Create docker-compose.yml with correct port
cat > docker-compose.yml << COMPOSEEOF
services:
  dashboard:
    build: .
    ports:
      - "${PORT}:8000"
    environment:
      - TZ=\${TZ:-UTC}
    volumes:
      # Config and settings
      - ./config.json:/app/config.json:ro
      - ./settings.json:/app/settings.json
      # Script files
      - ./generate_summary.py:/app/generate_summary.py:ro
      # Data files
      - ./calendar.json:/app/calendar.json
      - ./location.json:/app/location.json
      - ./daily-links.json:/app/daily-links.json
      - ./daily-summary.json:/app/daily-summary.json
      - ./money.txt:/app/money.txt
      - ./untaggedLinks.txt:/app/untaggedLinks.txt
      - ./starredLinks.json:/app/starredLinks.json
      - ./sequelEpisodes.json:/app/sequelEpisodes.json
      - ./anyboxStats.json:/app/anyboxStats.json
      - ./readlater.json:/app/readlater.json
      - ./wisdom.json:/app/wisdom.json
      # HTML files
      - ./index.html:/app/index.html:ro
      - ./lcars.html:/app/lcars.html:ro
      # Themes
      - ./themes:/app/themes:ro
    restart: unless-stopped
COMPOSEEOF

# Set permissions
chmod 644 *.json *.txt 2>/dev/null || true

# Build and start container
echo ""
echo "Building and starting container..."
docker compose up -d --build

# Wait for container to be healthy
echo "Waiting for dashboard to start..."
sleep 3

# Check if running
if docker compose ps | grep -q "running"; then
    echo ""
    echo -e "${GREEN}════════════════════════════════════════${NC}"
    echo -e "${GREEN}  Daily Dashboard installed successfully!${NC}"
    echo -e "${GREEN}════════════════════════════════════════${NC}"
    echo ""
    echo -e "  Open your dashboard at:"
    echo -e "  ${BLUE}http://localhost:${PORT}${NC}"
    echo ""
    echo -e "  ${YELLOW}Next steps:${NC}"
    echo "  1. Open the dashboard in your browser"
    echo "  2. Click Settings (gear icon)"
    echo "  3. Go to 'API Keys' tab to add your keys"
    echo "     - Weather: free at openweathermap.org/api"
    echo "     - OpenAI: optional, for AI summaries"
    echo ""
    echo -e "  ${YELLOW}Documentation:${NC}"
    echo "  https://github.com/tommertron/dailyDashboard#readme"
    echo ""
    echo -e "  ${YELLOW}Commands:${NC}"
    echo "  Update:    cd $INSTALL_DIR && git pull && docker compose up -d --build"
    echo "  Stop:      cd $INSTALL_DIR && docker compose down"
    echo "  Logs:      cd $INSTALL_DIR && docker compose logs -f"
    echo ""
else
    echo -e "${RED}Container failed to start. Check logs:${NC}"
    echo "  cd $INSTALL_DIR && docker compose logs"
    exit 1
fi
