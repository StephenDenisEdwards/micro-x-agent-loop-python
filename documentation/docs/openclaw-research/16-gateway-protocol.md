# Gateway Protocol and Network Model

## WebSocket protocol

The Gateway WS protocol is the single control plane and node transport. All clients connect over WebSocket and declare role + scope at handshake.

### Transport

- WebSocket, text frames with JSON payloads
- First frame **must** be a `connect` request

### Framing

- **Request**: `{ type: "req", id, method, params }`
- **Response**: `{ type: "res", id, ok, payload | error }`
- **Event**: `{ type: "event", event, payload, seq?, stateVersion? }`

Side-effecting methods require idempotency keys.

### Handshake

1. Gateway sends `connect.challenge` with nonce
2. Client sends `connect` request with protocol version, client info, role, scopes, caps, commands, permissions, auth token, device identity
3. Gateway responds with `hello-ok` including protocol version, policy, and optional device token

### Roles

- **`operator`** — control plane client (CLI, UI, automation)
  - Scopes: `operator.read`, `operator.write`, `operator.admin`, `operator.approvals`, `operator.pairing`
- **`node`** — capability host (camera, screen, canvas, system.run)
  - Declares `caps`, `commands`, `permissions` at connect time
  - Gateway enforces server-side allowlists

### Auth

- If `OPENCLAW_GATEWAY_TOKEN` is set, `connect.params.auth.token` must match
- After pairing, Gateway issues a **device token** scoped to role + scopes
- Device tokens can be rotated/revoked

### Device identity and pairing

- All clients include stable device identity (`device.id`) from keypair fingerprint
- New device IDs require pairing approval unless local auto-approval enabled
- **Local** connects: loopback + gateway host's own tailnet address (auto-approve eligible)
- **Non-local** connects must sign the server-provided challenge nonce

### Versioning

- `PROTOCOL_VERSION` in TypeBox schemas
- Clients send `minProtocol` + `maxProtocol`; server rejects mismatches
- Schemas generated from TypeBox: JSON Schema + Swift models (`pnpm protocol:gen`, `pnpm protocol:gen:swift`)

## Network model

### Core rules

- **One Gateway per host** recommended; only process allowed to own WhatsApp Web session
- **Loopback first**: Gateway WS defaults to `ws://127.0.0.1:18789`
- Nodes connect over LAN, tailnet, or SSH
- Canvas host served on same port as Gateway (`/__openclaw__/canvas/`, `/__openclaw__/a2ui/`)
- Remote access: SSH tunnel or Tailscale VPN

### TLS

- TLS supported for WS connections
- Optional cert fingerprint pinning (`gateway.tls`, `gateway.remote.tlsFingerprint`)

## Key references

- Protocol: [`docs/gateway/protocol.md`](/root/openclaw/docs/gateway/protocol.md)
- Network model: [`docs/gateway/network-model.md`](/root/openclaw/docs/gateway/network-model.md)
- Architecture: [`docs/concepts/architecture.md`](/root/openclaw/docs/concepts/architecture.md)
- Remote access: [`docs/gateway/remote.md`](/root/openclaw/docs/gateway/remote.md)
- Discovery: [`docs/gateway/discovery.md`](/root/openclaw/docs/gateway/discovery.md)
- Pairing: [`docs/gateway/pairing.md`](/root/openclaw/docs/gateway/pairing.md)
