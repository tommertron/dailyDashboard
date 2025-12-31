# Daily Dashboard

A personal dashboard for daily information display.

## Setup

The dashboard expects several JSON data files to be present. These files are not included in the repository as they contain personal data. Create them in the project root with the following formats:

### anyboxStats.json
Statistics from Anybox link manager.
```json
{
  "all": 549,
  "last7": 20,
  "untagged": 1
}
```

### calendar.json
Calendar events as newline-delimited JSON strings within an `events` field.
```json
{
  "events": "{\"calendar\":\"Family\",\"title\":\"Event Name\",\"end\":\"Dec 31, 2025 at 6:00 PM\",\"allday\":\"No\",\"start\":\"Dec 31, 2025 at 6:00 PM\"}\n{\"calendar\":\"Work\",\"title\":\"Meeting\",\"end\":\"Jan 1, 2026 at 9:00 AM\",\"allday\":\"No\",\"start\":\"Jan 1, 2026 at 9:00 AM\"}"
}
```

### daily-links.json
Links saved today.
```json
{
  "generatedAt": "Dec 31, 2025 at 12:05 PM",
  "links": [
    {
      "url": "https://example.com",
      "title": "Example Site",
      "comment": "Optional comment"
    }
  ]
}
```

### daily-summary.json
AI-generated daily summary.
```json
{
  "summary": "Your daily summary text here.",
  "generated_at": "2025-12-31 13:00:04",
  "date": "2025-12-31"
}
```

### location.json
Current location data.
```json
{
  "updated": "Dec 31, 2025 at 12:50 AM",
  "address": "123 Main St\nCity ST 12345\nCountry",
  "city": "City",
  "region": "Country",
  "lat": "43.123456",
  "state": "ST",
  "long": "-79.123456"
}
```

### sequelEpisodes.json
Upcoming TV episodes from Sequel.
```json
{
  "episodes": [
    {
      "season": "1",
      "episodeTitle": "Episode Title",
      "poster": "https://image.tmdb.org/t/p/w1280/poster.jpg",
      "episodeNumber": "8",
      "show": "Show Name",
      "TheMovieDV": "6415093",
      "releaseDate": "Dec 9, 2025 at 9:00 PM"
    }
  ]
}
```

### starredLinks.json
Starred/favorite links.
```json
{
  "generatedAt": "Dec 31, 2025 at 1:21 PM",
  "links": [
    {
      "url": "https://example.com",
      "title": "Link Title",
      "comment": "Optional comment"
    }
  ]
}
```

### todos.json
Todo items.
```json
{
  "todos": [
    {
      "status": "Open",
      "tags": {},
      "title": "Task name",
      "notes": ""
    },
    {
      "status": "Completed",
      "tags": {},
      "title": "Done task",
      "notes": ""
    }
  ]
}
```

### money.txt
Plain text file for financial notes (format flexible).

### config.json
Application configuration (not tracked).

## Running

```bash
docker compose up
```

Or run directly:
```bash
python server.py
```
