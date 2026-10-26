"""Write the API's OpenAPI schema to frontend/openapi.json (input for `npm run gen:api`)."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.main import create_app  # noqa: E402

out = Path(__file__).resolve().parents[2] / "frontend" / "openapi.json"
out.write_text(json.dumps(create_app().openapi(), indent=2) + "\n", encoding="utf-8")
print(f"wrote {out}")
