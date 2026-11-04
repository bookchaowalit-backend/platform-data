# 05 — C4 Context

Status: **done**

```mermaid
C4Context
  title System context: platform-data (data-api)
  Person(owner, "Owner / operator", "Runs migrate and railway up")
  System_Ext(hub, "Remote MCP hub", "Identity service client mcp-hub, cell platform-data")
  System_Ext(callers, "Platform services and tools", "Hold workspace JWTs")
  System_Ext(gw, "Edge gateway", "gateway.bookchaowalit.com /v1/platform-data/*, token pass-through")
  System_Ext(aigw, "AI gateway (planned)", "Would call service admissions")
  System(data, "platform-data", "Cache, counters, document search, quota admission")
  System_Ext(identity, "platform-identity", "Issuer + JWKS /.well-known/jwks.json")
  SystemDb_Ext(neon, "Neon PostgreSQL", "Project platform-data")
  System_Ext(sentry, "Sentry", "Project platform-data, errors only")
  System_Ext(uptime, "platform-uptime-worker", "Hourly /readyz")
  System_Ext(lake, "solo-empire data lake", "Lake interfaces still live there")

  Rel(owner, data, "migrate, deploy")
  Rel(hub, data, "HTTPS + Bearer JWT")
  Rel(callers, gw, "HTTPS + Bearer JWT")
  Rel(gw, data, "Proxies with the same token")
  Rel(callers, data, "HTTPS + Bearer JWT, direct URL")
  Rel(aigw, data, "Service + caller JWT")
  Rel(data, identity, "Fetch JWKS")
  Rel(data, neon, "SQL over TLS, runtime role")
  Rel(data, sentry, "Error events without free text")
  Rel(uptime, data, "GET /readyz")
  Rel(data, lake, "Documents contract only")
```

Sources: `README.md`, `docs/runtime.md`, `docs/CONTRACT-SURFACE.md`, `src/platform_data/__main__.py` (`JWT_JWKS_URL`),
`src/platform_data/_sentry.py`; Railway describe-service variable names (`DATABASE_URL`, `JWT_AUDIENCE`, `JWT_ISSUER`,
`JWT_JWKS_URL`, `PLATFORM_SYSTEM_WORKSPACE_ID`, `SENTRY_DSN`); ops record: book-platforms-status (2026-11-03) for identity issuer,
Neon project, Sentry project, uptime worker and MCP hub cell; platform-api-gateway `routes.json` + `README.md` @ `4a31ff5`
(route `platform-data` → `https://data-api-production-bf8a.up.railway.app`; added 2026-11-04).

## Open questions

- gateway มี route `platform-data` แล้ว (`routes.json` @ `4a31ff5`) แต่ direct URL ยังใช้ได้จนกว่าจะบันทึก cutover และ data ไม่เช็ค `X-Gateway-Assertion`: caller ตัวไหนย้ายมา gateway แล้ว และจะปิด direct URL เมื่อไร
- AI gateway (`platform-ai-gateway-api`) จะเป็น caller จริงหรือไม่ เป็น owner decision ที่ยังเปิด
