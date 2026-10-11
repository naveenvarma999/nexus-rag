"""Create local configuration once; never overwrites existing settings."""

from pathlib import Path
import secrets

root = Path(__file__).resolve().parent.parent
target = root / ".env"
if target.exists():
    raise SystemExit(".env already exists; edit it directly.")
text = (
    (root / ".env.example")
    .read_text()
    .replace("replace-with-at-least-32-random-characters", secrets.token_urlsafe(48))
)
target.write_text(text)
target.chmod(0o600)
print(
    "Created .env with a random authentication secret. Run docker compose up --build."
)
