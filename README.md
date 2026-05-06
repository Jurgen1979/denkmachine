# denkmachine

interne ai-tool voor jrgndwvr.be – beheert projecten en voert llm-calls uit via openrouter.

## lokaal starten

1. kopieer `.env.example` naar `.env` en vul de waarden in
2. installeer dependencies: `pip install -r requirements.txt`
3. genereer een wachtwoordhash: `python scripts/hash_password.py "jouwwachtwoord"`
4. vul `DM_PASSWORD_HASH` en `DM_SECRET_KEY` in je `.env` in
5. start de app: `flask --app src.app run`

## deployen op replit

vul de volgende replit secrets in via het secrets-paneel:
- `DM_USER`, `DM_PASSWORD_HASH`, `DM_SECRET_KEY`
- `OPENROUTER_API_KEY`
- overige keys naar behoefte

run daarna de app via de workflow of replit shell: `flask --app src.app run --host 0.0.0.0 --port 5000`
