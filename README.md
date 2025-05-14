# STRMGen

STRMGen is a Python-based tool and web API/UI for generating Emby/Kodi-compatible `.strm` files (and optional accompanying metadata) from IPTV/M3U playlists and TMDb data.

## Features

* **.strm File Generation**: Create `.strm` files for movies and TV shows based on IPTV/M3U or Dispatcharr streams.
* **Optional Metadata**: Generate Emby-compatible `.nfo` files alongside `.strm` files.
* **Poster & Fanart Images**: Download `poster.jpg` and `fanart.jpg` for movies; `seasonXX.tbn` for TV seasons; `thumb.jpg` for episodes.
* **FastAPI Service & Web UI**: REST API for batch processing, on-demand generation, and a built-in web interface for manual control.
* **Configurable**: Supports both `config.json` and environment variables for settings.
* **Scheduling**: Automatic periodic updates via APScheduler (e.g., daily or on startup).
* **Emby Integration (Optional)**: Trigger library scans via Emby API for newly added content.

## Prerequisites

1. **Python 3.12+** installed.
2. **PostgreSQL**: You need an external PostgreSQL instance. Create a database and user with appropriate privileges:

   ```sql
   CREATE DATABASE strmgen;
   CREATE USER strmgen_user WITH PASSWORD 'secure_password';
   GRANT ALL PRIVILEGES ON DATABASE strmgen TO strmgen_user;
   ```
3. **TMDb API Key**: Sign up at [TMDb](https://www.themoviedb.org/) and obtain an API key.
4. **Emby (Optional)**: If you want automatic library scans, configure:

   * `emby_api_url` (e.g., `http://YOUR_SERVER:8096/emby`)
   * `emby_api_key` (your Emby API token)
   * `emby_movie_library_id` (numeric library ID)

## Installation

1. Clone the repo:

   ```bash
   git clone https://github.com/yourusername/STRMGen.git
   cd STRMGen
   ```
2. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```
3. Configure settings:

   * Copy `config.example.json` to `config.json` and fill in values, **OR**
   * Set environment variables (`DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASSWORD`, `DB_NAME`, `TMDB_API_KEY`, etc.)


> **Note:** Emby settings are optional. If not configured, Emby scans will be skipped.

## Usage

### Command Line Runner

Run the pipeline manually:
```bash
python -m strmgen.pipeline.runner
````

### FastAPI Server

Start the API and web UI:

```bash
uvicorn strmgen.main:app --reload
```

* **Web UI:** [http://localhost:8808/](http://localhost:8808/)

### Scheduled Startup

By default, the scheduler runs on startup and according to any configured cron schedules defined in code or environment.

## Docker Deployment

Install STRMGen from Docker Hub:

```bash
docker pull mercenaryjustice/strmgen:latest
```

**Ensure you have your `config.json` in place on the host (e.g., `/mnt/user/appdata/strmgen/config.json`) before running the container.**

Run the container, mounting your media output directory and custom config file:

```bash
docker run -d \
  -v /mnt/user/data/media/vod/:/output \
  -v /mnt/user/appdata/strmgen/config.json:/app/strmgen/core/config.json \
  -e DB_HOST=host.docker.internal \
  -e DB_USER=strmgen \
  -e DB_PASSWORD=secure_password \
  -e DB_NAME=strmgen \
  -e TMDB_API_KEY=YOUR_TMDB_API_KEY \
  -p 8808:8808 \
  mercenaryjustice/strmgen:latest
```

## Optional Emby Scan Trigger

To trigger Emby library scans only for new content, configure:

```json
{
  "emby_api_url": "http://YOUR_EMBY:8096/emby",
  "emby_api_key": "YOUR_KEY",
  "emby_movie_library_id": 3760014
}
```

Then the service will call:

```
GET /Library/Media/Updated?api_key=...&Path=<encoded_folder>
```

## Contributing

1. Fork the repo
2. Create a feature branch
3. Submit a pull request

## License

MIT License. See [LICENSE](LICENSE).
