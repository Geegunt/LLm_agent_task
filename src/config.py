import os
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent


def _load_local_env(path: Path = ROOT_DIR / ".env") -> None:
    """Читает пары `KEY=VALUE` из `path` и добавляет их в окружение без внешних зависимостей."""
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


if os.getenv("LOAD_DOTENV", "1") != "0":
    _load_local_env()

JOBS_DATA_PATH = ROOT_DIR / "data" / "jobs.json"
TOP_N = int(os.getenv("TOP_N", "5"))

# Веса скоринга — должны суммироваться в 1.0
WEIGHTS = {
    "keyword_overlap": 0.35,
    "type_match":      0.15,
    "location_match":  0.15,
    "junior_fit":      0.10,
    "role_alignment":  0.25,
}

TRUDVSEM_API_BASE = os.getenv("TRUDVSEM_API_BASE", "http://opendata.trudvsem.ru/api/v1")
TRUDVSEM_LIMIT    = int(os.getenv("TRUDVSEM_LIMIT",     "12"))
TRUDVSEM_PAGE_SIZE = int(os.getenv("TRUDVSEM_PAGE_SIZE", "3"))
API_TIMEOUT       = int(os.getenv("API_TIMEOUT",        "15"))
LIVE_API_ENABLED  = os.getenv("LIVE_API_ENABLED", "1") != "0"

GROQ_API_KEY  = os.getenv("GROQ_API_KEY",  "")
GROQ_API_BASE = os.getenv("GROQ_API_BASE", "https://api.groq.com/openai/v1")
GROQ_MODEL    = os.getenv("GROQ_MODEL",    "llama-3.3-70b-versatile")
GROQ_TIMEOUT  = int(os.getenv("GROQ_TIMEOUT", "30"))
