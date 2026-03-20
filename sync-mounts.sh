#!/bin/bash
# Sync host files into container to fix inode mismatch from atomic file edits
docker cp index.html dailydashboard-dashboard-1:/app/index.html
docker cp themes/default.css dailydashboard-dashboard-1:/app/themes/default.css
docker cp config.json dailydashboard-dashboard-1:/app/config.json
echo "Synced index.html, themes/default.css, config.json into container"
