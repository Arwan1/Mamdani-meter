# NYC Civic Priorities Platform — local-first

This is the non-UI half of the project. It deliberately replaces the original
cloud architecture with a **loopback-only companion API**, a SQLite database,
and local files. The UI still uses the agreed `/api/v1` contract, but there is
no Docker, Postgres, Redis, S3 bucket, deployment, or GPU setup to manage.

Gemini is the one remote dependency. It is called only by the local process;
the API key is never sent to the browser.

## What is included

- typed FastAPI contract and a generator for `contracts/openapi.json`;
- local SQLite persistence and filesystem-backed image uploads;
- YAML taxonomy, methodology, dataset registry, and indicator specifications;
- deterministic scoring, relative ranking, coverage-aware aggregation, and
  demo seed data for the UI developer;
- local CLI commands to seed, import policy documents, run Gemini extraction,
  and export the contract;
- Gemini structured-output classification for citizen reports and policy
  commitments, with excerpt verification before a commitment is saved.

The service is intended to be run at `http://127.0.0.1:8000` while the UI is
being developed. That is a local process, not a hosted backend. If the UI is
later deployed publicly, this design will need an intentional hosted-service
and privacy review; it should not be exposed directly from a laptop.

## One-time setup (Windows PowerShell)

The present Python 3.14 installation is missing `pip` and cannot create a
working virtual environment. The shortest reliable fix is to install
[uv](https://docs.astral.sh/uv/) (it manages Python and packages):

```powershell
winget install --id=astral-sh.uv -e
```

Close and reopen PowerShell, then from this project directory run:

```powershell
uv python install 3.13
uv sync --extra dev
```

Alternatively, repair/reinstall Python from [python.org](https://www.python.org/downloads/)
with the **pip** and **venv** features selected, then use
`python -m pip install -e ".[dev]"` in a fresh virtual environment.

Copy `.env.example` to `.env` and put a Gemini API key in
   `GEMINI_API_KEY`. Create the key in [Google AI Studio](https://aistudio.google.com/app/apikey).
   Use a paid Gemini project before processing real citizen photos or text.

```powershell
Copy-Item .env.example .env
notepad .env
```

Initialize the local store and contract:

   ```powershell
   uv run nycp init
   uv run nycp contract export
   ```

## Daily development

Start the local API:

```powershell
uv run nycp serve
```

It listens only on `127.0.0.1:8000`. The UI developer can set:

```text
NEXT_PUBLIC_API_BASE=http://127.0.0.1:8000/api/v1
```

Useful commands:

```powershell
uv run nycp demo seed                     # reset/reseed demo platform data
uv run nycp docs ingest C:\path\plan.pdf # parse a PDF into local chunks
uv run nycp docs extract <document-id>    # Gemini structured extraction
uv run nycp contract export               # regenerate OpenAPI for the UI
uv run pytest
```

## Local storage layout

`data/nyc_civic.sqlite3` is the only database. `data/uploads/` holds images
on this computer, and `data/policy/` holds imported source documents. Neither
is committed. Database backups are as simple as copying the SQLite file while
the app is stopped.

## Scope choices

This first platform build supports the UI integration and a Parks vertical
slice. It does **not** quietly claim to do the heavy citywide analysis from the
planning document. Importing full NYC geometry, ACS allocation, Socrata
snapshots, and r5py transit routing should be added only when needed; the last
of these needs JDK 21 and substantial downloaded datasets, and does not need
your GPU. Your 32 GB RAM laptop is sufficient for the later routing work.
