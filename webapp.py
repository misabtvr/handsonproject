from __future__ import annotations

import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Dict

from app.pipeline import RoutePredictorPipeline


ROOT = Path(__file__).resolve().parent
UI_DIR = ROOT / "ui"
PIPELINE = RoutePredictorPipeline()


def _json_response(handler: BaseHTTPRequestHandler, status: int, payload: Dict[str, Any]) -> None:
    body = json.dumps(payload).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


class RouteUIHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        if self.path in ("/", "/index.html"):
            self._serve_file(UI_DIR / "index.html", "text/html; charset=utf-8")
            return
        if self.path == "/styles.css":
            self._serve_file(UI_DIR / "styles.css", "text/css; charset=utf-8")
            return
        if self.path == "/app.js":
            self._serve_file(UI_DIR / "app.js", "application/javascript; charset=utf-8")
            return
        self.send_error(HTTPStatus.NOT_FOUND, "File not found")

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/api/predict":
            _json_response(self, HTTPStatus.NOT_FOUND, {"error": "Unknown endpoint"})
            return

        content_length = int(self.headers.get("Content-Length", "0"))
        if content_length <= 0:
            _json_response(self, HTTPStatus.BAD_REQUEST, {"error": "Request body is required"})
            return

        try:
            payload = json.loads(self.rfile.read(content_length).decode("utf-8"))
        except json.JSONDecodeError:
            _json_response(self, HTTPStatus.BAD_REQUEST, {"error": "Invalid JSON body"})
            return

        source = str(payload.get("source", "")).strip()
        destination = str(payload.get("destination", "")).strip()
        try:
            passengers = int(payload.get("passengers", 1) or 1)
        except (TypeError, ValueError):
            _json_response(self, HTTPStatus.BAD_REQUEST, {"error": "Passengers must be a valid integer"})
            return
        if not source or not destination:
            _json_response(self, HTTPStatus.BAD_REQUEST, {"error": "Source and destination are required"})
            return
        if passengers < 1:
            _json_response(self, HTTPStatus.BAD_REQUEST, {"error": "Passengers must be at least 1"})
            return

        try:
            result = PIPELINE.run(source, destination, passengers=passengers)
        except Exception as exc:  # Defensive return to keep API robust.
            _json_response(self, HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})
            return

        response = {
            "source_display": result.source_display,
            "destination_display": result.destination_display,
            "selected_mode": result.selected_mode,
            "selected_reason": result.selected_reason,
            "climate_label": result.climate_label,
            "public_transport_assessment": result.public_transport_assessment,
            "best_route_id": result.best_route_id,
            "best_route_path": result.best_route_path,
            "passengers": passengers,
            "all_options": [
                {
                    "mode": option.mode,
                    "duration_min": round(option.duration_min, 2),
                    "distance_km": round(option.distance_km, 2),
                    "score": round(option.score, 2),
                    "notes": option.notes,
                }
                for option in result.all_options
            ],
            "similar_memories": [
                {
                    "source": memory.source,
                    "destination": memory.destination,
                    "recommended_mode": memory.recommended_mode,
                    "reason": memory.reason,
                    "score": round(memory.score, 3),
                    "created_at": memory.created_at,
                }
                for memory in result.similar_memories
            ],
            "tool_log": result.tool_log,
        }
        _json_response(self, HTTPStatus.OK, response)

    def _serve_file(self, file_path: Path, content_type: str) -> None:
        if not file_path.exists():
            self.send_error(HTTPStatus.NOT_FOUND, "File not found")
            return
        content = file_path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        return


def main() -> None:
    server = HTTPServer(("127.0.0.1", 8000), RouteUIHandler)
    print("Route Predictor UI running at http://127.0.0.1:8000")
    server.serve_forever()


if __name__ == "__main__":
    main()
