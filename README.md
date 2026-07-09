# Scorito Tour de France Lineups

Small Flask app that logs into Scorito, opens the Tour de France market, reads your joined subleagues, and shows the daily stage lineup for every accepted member in the selected subleague.

## What it does

- Logs in with your Scorito account through Scorito's normal web sign-in flow.
- Loads Tour de France market `309`.
- Reads the subleagues attached to that market.
- Defaults to your Scorito-selected subleague.
- Defaults to the live stage, otherwise the next upcoming stage, otherwise the latest finished stage.
- Shows each member's selected riders for that stage and marks the captain.

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
