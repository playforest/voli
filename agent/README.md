# agent

Boundary: orchestration and intent → tool plan → facts → answer.

Put here:
- prompt parsing / constraint extraction
- planning (which tools to call)
- execution wrapper (calls tools, caching, retries)
- writer (builds the final response + Facts section)

Keep out:
- HTTP/server code (api/)
- infrastructure/deploy (infra/)
