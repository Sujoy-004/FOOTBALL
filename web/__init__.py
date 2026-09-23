from dotenv import load_dotenv

# Load .env BEFORE any web submodule reads its credential constants. Without
# this, laliga_app.py / ucl_app.py capture "BSD_API_KEY" / "FOOTBALL_DATA_ORG_KEY"
# as empty at import time and every competition resolves to "no data provider"
# (wc_app.py has its own load_dotenv, but it runs last in the registry import
# order, which is too late for the other two).
load_dotenv()