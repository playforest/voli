# api

Boundary: HTTP surface area (optional in v1).

Put here:
- FastAPI (or other) app + route handlers (later)
- request/response models (pydantic) for external clients
- auth, rate limiting, deployment-facing concerns

Keep out:
- Polygon-specific logic (belongs in agent/tools)
- finance computations (belongs in analytics later)
