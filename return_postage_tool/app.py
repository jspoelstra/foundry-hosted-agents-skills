from __future__ import annotations

import json
import math
import os
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse


def calculate_return_postage(
    weight_kg: float,
    distance_km: float,
    expedited: bool = False,
) -> dict[str, Any]:
    if weight_kg <= 0:
        raise ValueError("weight_kg must be greater than zero")
    if distance_km < 0:
        raise ValueError("distance_km must be zero or greater")

    distance_bands = math.ceil(distance_km / 500)
    price = 4.50 + (weight_kg * 1.35) + (distance_bands * 0.75)
    if expedited:
        price *= 1.60

    return {
        "currency": "USD",
        "expedited": expedited,
        "price": round(price, 2),
        "service": "expedited return" if expedited else "standard return",
    }


class ReturnPostageHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            self._write_json(HTTPStatus.OK, {"status": "ok"})
            return

        if parsed.path != "/calculate":
            self._write_json(HTTPStatus.NOT_FOUND, {"error": "Not found"})
            return

        try:
            query = parse_qs(parsed.query)
            weight_kg = float(query["weight_kg"][0])
            distance_km = float(query["distance_km"][0])
            expedited = query.get("expedited", ["false"])[0].lower() in {
                "1",
                "true",
                "yes",
            }
            result = calculate_return_postage(weight_kg, distance_km, expedited)
        except (KeyError, ValueError) as exc:
            self._write_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            return

        self._write_json(HTTPStatus.OK, result)

    def _write_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    port = int(os.getenv("PORT", "8080"))
    server = ThreadingHTTPServer(("0.0.0.0", port), ReturnPostageHandler)
    server.serve_forever()


if __name__ == "__main__":
    main()