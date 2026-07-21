# Scorito Cycling Game Overview

Small Flask app that logs into Scorito, opens a configured Scorito cycling game, and shows the stage lineup for every accepted member in the linked subleague.

## What it does

- Logs in with your Scorito account through Scorito's normal web sign-in flow.
- Lets you switch between configured games such as Tour, Giro, and Vuelta.
- Maps each game to a fixed `market_id` and `subleague_id`.
- Defaults to the live stage, otherwise the next upcoming stage, otherwise the latest finished stage.
- Shows each member's selected riders for that stage and marks the captain.
- Shows a clear message when Scorito no longer exposes historical lineup and score data for an older completed game.

## Files

- `app.py`: Flask app and page route.
- `scorito_client.py`: Scorito login flow and API calls.
- `templates/index.html`: page template.
- `static/styles.css`: page styling.
- `wsgi.py`: PythonAnywhere entrypoint.

## Local setup

1. Create a virtual environment.
2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Copy `.env.example` to `.env`.
4. Fill in:

```env
SCORITO_EMAIL=your-email@example.com
SCORITO_PASSWORD=your-password
SCORITO_DEFAULT_GAME_KEY=tdf-2026

# Optional legacy fallback values:
SCORITO_MARKET_ID=309
SCORITO_DEFAULT_SUBLEAGUE_ID=
```

If Windows makes `.env` awkward to create, `.env.txt` also works.
You can also point to a custom env file with `SCORITO_ENV_FILE=/full/path/to/file`.

5. Run the app:

```bash
python app.py
```

6. Open `http://127.0.0.1:5000`.

## PythonAnywhere setup

1. Upload this project to your PythonAnywhere home directory.
2. Open a Bash console and install the dependency:

```bash
pip3.10 install --user -r requirements.txt
```

3. Create a `.env` file in the project folder with your Scorito credentials.
4. In the PythonAnywhere web app settings, point the WSGI file at this project.
5. Use the contents of `wsgi.py`, or import the Flask app manually:

```python
import sys
from pathlib import Path

project_home = Path("/home/yourusername/your-project-folder")
if str(project_home) not in sys.path:
    sys.path.insert(0, str(project_home))

from app import app as application
```

6. Reload the web app.

## Notes

- Credentials are intentionally not hardcoded.
- The page uses live Scorito endpoints, so if Scorito changes its login flow or API, the client may need an update.
- The app only reads accepted participants and their daily stage selection.
- Your hosting environment must be able to make outbound HTTPS requests to `www.scorito.com`, `idsrv.scorito.com`, `cycling.scorito.com`, and `league.scorito.com`.
