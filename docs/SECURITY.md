# Security Guide — vllm-mlx Dashboard UI

This document describes the security model of the vllm-mlx dashboard, known
risks to be aware of, and how to configure the system securely.

---

## API Keys

The system has two separate API keys:

### 1. Inference Server API Key
Protects the AI inference endpoints (`/v1/chat/completions`, `/v1/models`, etc.).
Any OpenAI-compatible client (Open WebUI, Chatbox, LM Studio) must supply this key
as a Bearer token.

**How to set it:**
1. Open the dashboard → **⚙️ Server** page
2. Scroll to the **Configuration** form
3. Fill in the **API key** field
4. Click **💾 Save configuration**
5. Click **🔄 Restart Server**

Any client connecting to the inference server must then set:
```
Authorization: Bearer <your-key>
```
or enter it as the "API key" in their client settings.

### 2. Management API Key
Protects the dashboard management API (port 8502) — the endpoints that allow
start/stop, config changes, model downloads, and log access.  This is the key
a remote dashboard instance sends when it connects to the server machine.

**How to set it (on the server machine):**
1. Open the dashboard → **⚙️ Settings** page
2. Scroll to **🔗 Remote Server**
3. Fill in **Management API key** and click **💾 Save**
4. The management API will now require this key on every request

**How to set it (on the remote dashboard machine):**
1. Open the remote dashboard → **⚙️ Settings → 🔗 Remote Server**
2. Enter the same key in **Management API key**
3. Save — the remote dashboard will now authenticate automatically

---

## Risk Assessment

### High: Management API exposed with no key

| Condition | Risk |
|-----------|------|
| `mgmt_api_key` is empty AND server listens on `0.0.0.0` | **Anyone on your local network** can start/stop the server, change config, download models, and read logs |

**Mitigation:** Always set a management API key when enabling LAN access.
The dashboard shows a warning banner in the Security section of Settings
when this condition is detected.

### Medium: Inference server exposed with no key

If the inference server listens on `0.0.0.0` with no `api_key`, anyone on
your Wi-Fi can send unlimited chat/completion requests to your GPU.

**Mitigation:** Set an inference server API key (see above) any time you
change *Listen on* to `0.0.0.0`.

### Medium: CORS wildcard

The management API uses `allow_origins=["*"]` and sets `X-Frame-Options: ALLOWALL`.
This is intentional — it allows the dashboard to be embedded in iFrames and makes
browser-based remote control possible.

**Risk:** Any web page you visit could attempt to call the management API in your
browser's context (CORS side-channel).  The API key is your primary protection.

**Mitigation:**
- Always set a management API key.
- Do not expose port 8502 to the public internet (use a VPN or SSH tunnel instead).
- The inference server (port 8000) does not have the CORS wildcard by default.

### Low: HuggingFace token exposure

When downloading models with a HuggingFace access token, the token is briefly set
as an environment variable (`HUGGING_FACE_HUB_TOKEN`) and **cleared immediately**
after the download/prefetch completes.  It is never written to disk by the dashboard.

### Low: Auto model-switch proxy

When enabled, the auto-switch proxy (port 8502) accepts a `model` field in OpenAI
chat requests and automatically swaps the loaded model.

**Risk mitigations already in place:**
- The requested model must be **already cached on the server** — the proxy will
  not trigger a download of an unknown model.
- The model ID must match the `org/repo` format before any action is taken.
- The API key (if set) is required to reach the proxy.

---

## Deployment Recommendations

### Safe local-only setup (default)
Both servers bind to `127.0.0.1` — only accessible from the Mac itself.
No API keys needed.

### Safe LAN setup
1. Server listens on `0.0.0.0`
2. **Both** API keys are set (inference key + management key)
3. Dashboard only accessible within your home/office network
4. Do **not** port-forward 8000, 8501, or 8502 on your router

### Internet-accessible setup (not recommended)
If you must expose the server over the internet:
- Use a reverse proxy (nginx, Caddy) with HTTPS/TLS
- Enforce strong API keys (20+ random characters)
- Consider rate limiting at the proxy level
- **Never** expose 8501 (Streamlit) or 8502 (management API) directly — only
  expose 8000 (inference) via the authenticated reverse proxy

---

## Reporting Security Issues

If you discover a security vulnerability in this dashboard UI, please open a
**private** security advisory at:
https://github.com/clickbrain/vllm-mlx-ui/security/advisories/new

For vulnerabilities in the core vllm-mlx inference engine, report to:
https://github.com/waybarrios/vllm-mlx

---

## Audit Log

| Date | Issue | Status |
|------|-------|--------|
| 2026-04-22 | Auto model-switch accepted uncached model IDs | Fixed — now validates against local cache |
| 2026-04-22 | HF token persisted in env after use | Fixed — cleared in `finally` block |
| 2026-04-22 | No warning when management API has no key | Fixed — warning shown in Settings UI |
| 2026-04-22 | install-remote.sh referenced wrong GitHub repo | Fixed — corrected to `clickbrain/vllm-mlx-ui` |
