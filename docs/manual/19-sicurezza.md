# Cap 19 — Sicurezza

> *Sintesi 30 secondi.* CARA usa JWT per auth utente e device,
> AES-256-GCM per cifrare i token OAuth a riposo, mkcert per la CA
> locale TLS, e audit log append-only per ogni operazione admin. Tutti
> i secret sono in `.env` (mai DB), mascherati come hash sha256[:8] nei
> log.

## 19.1 Modello di minaccia

CARA è una single-family installation in casa. Il modello di
minaccia non è un servizio cloud globale.

**Avversari plausibili**:
- **Curioso esterno** che scansiona la rete WiFi del vicino → contromisura
  TLS + WireGuard isola da fuori
- **Membro famiglia non admin** che vuole spiare altri → contromisura
  permessi per ruolo + audit log
- **Device perso** (telefono rubato) → contromisura JWT scadenza +
  device deauth
- **Backup/disco rubato** → contromisura `.env` encryption keys
  separate, password hashate bcrypt

**Avversari non considerati**:
- State actor con accesso fisico al server
- Insider threat (Antonio è onesto)
- Breach di Anthropic / Google / FCM (CARA usa solo i loro token,
  non si protegge da loro lato server)

## 19.2 JWT — autenticazione

**File**: `cara/services/auth.py`.

Tre tipi di token, tutti firmati con `JWT_SECRET` HS256.

### Access token
- **Scadenza**: 60 minuti
- **Claim**: `sub` (user_id), `iat`, `exp`, `type=access`, `is_admin`
- **Uso**: ogni request HTTP

### Refresh token
- **Scadenza**: 30 giorni
- **Claim**: `sub`, `iat`, `exp`, `type=refresh`
- **Uso**: chiamare `POST /auth/refresh` per ottenere un nuovo access

### Device token
- **Scadenza**: 365 giorni
- **Claim**: `sub` (device_id), `iat`, `exp`, `type=device`, extra
  (surface, name)
- **Uso**: heartbeat + WebSocket family bus

`type` è discriminato dalla dependency `get_current_user`/`require_admin`
per rifiutare access tokens dove servono device tokens e viceversa.

### Storage frontend

`access_token` + `refresh_token` in localStorage. Su `401` il client
prova `auth.refresh()` una volta; se fallisce, pulisce storage e
redirect a Login.

> **🔒 Sicurezza** — localStorage è accessibile da qualsiasi script
> in pagina. CARA non carica script di terzi né iframe esterni →
> XSS è il principale vettore di leak. La protezione è il `Content-Security-Policy`
> (futuro: header CSP rigoroso).

### `JWT_SECRET`

`JWT_SECRET` in `.env` (32+ byte random).

**Rotazione**: cambiare `JWT_SECRET` invalida ogni token attivo (ogni
utente deve re-login, ogni device deve re-pair). Procedura:

```bash
# Genera nuova secret
NEW=$(openssl rand -hex 32)

# Sostituisci in .env
sed -i "s/^JWT_SECRET=.*/JWT_SECRET=$NEW/" /opt/cara/.env

# Restart
docker restart cara-backend

# Tutti i client si trovano con 401 → re-login
```

## 19.3 Password — bcrypt

**File**: `cara/services/auth.py`.

```python
from passlib.context import CryptContext
_pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")

def hash_password(plain: str) -> str:
    return _pwd.hash(plain)

def verify_password(plain: str, hashed: str) -> bool:
    return _pwd.verify(plain, hashed)
```

bcrypt cost factor 12 (default). Sufficiente per famiglia, troppo
costoso per attacchi mirati a singolo utente (~250ms/verify).

**Politica password** (hardcoded oggi):
- Min 12 caratteri (Step 1 wizard)
- Min 8 caratteri (cambio password admin)
- Niente requisiti di "1 maiuscola, 1 numero" (rilassato per usabilità
  in casa)

> **💡 Suggerimento** — incoraggia l'uso di passphrase ("la mia ricetta
> della pasta al sugo è perfetta") più sicure di password complesse
> brevi.

## 19.4 AES-GCM per OAuth tokens

**File**: `cara/services/secrets.py`.

I refresh_token Google sono cifrati prima di entrare in DB.
AES-256-GCM con chiave globale `OAUTH_ENCRYPTION_KEY`.

```python
import os
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

def _key_bytes() -> bytes:
    key_hex = settings.oauth_encryption_key
    return bytes.fromhex(key_hex)

def encrypt(plaintext: str) -> bytes:
    aesgcm = AESGCM(_key_bytes())
    nonce = os.urandom(12)
    ciphertext = aesgcm.encrypt(nonce, plaintext.encode(), None)
    return nonce + ciphertext   # nonce prepended for storage
```

Il salt (nonce 96 bit) è prepended al ciphertext. Output stored in
`oauth_credentials.encrypted_refresh_token` come bytes.

### Key rotation

Per ruotare `OAUTH_ENCRYPTION_KEY` senza invalidare tutto:

```bash
# scripts/rotate_oauth_key.py (futuro)
# 1. Aggiungi temporaneamente OAUTH_ENCRYPTION_KEY_OLD nel .env
# 2. Per ogni oauth_credentials:
#    - decrypt con OAUTH_ENCRYPTION_KEY_OLD
#    - encrypt con OAUTH_ENCRYPTION_KEY (nuova)
# 3. Rimuovi OAUTH_ENCRYPTION_KEY_OLD
# 4. Restart
```

Lo script automatico non esiste ancora. Per ora, se ruoti la chiave,
gli utenti devono ri-fare OAuth.

## 19.5 TLS — mkcert + Let's Encrypt

CARA gira solo su HTTPS (cap 1.4). Self-signed cert non basta: i
browser bloccano fetch + l'install PWA + i WebSocket.

**Soluzione standard**: mkcert genera una CA locale + cert firmato da
quella CA. Installi la CA come root trusted sui device famiglia. Da
quel momento, Chrome/Safari trattano `192.168.1.23:8455` come trusted.

### Setup mkcert (una volta)

```bash
# Sull'host
sudo apt install libnss3-tools  # dipendenza
curl -Lo /usr/local/bin/mkcert \
  https://github.com/FiloSottile/mkcert/releases/download/v1.4.4/mkcert-v1.4.4-linux-arm64
chmod +x /usr/local/bin/mkcert

# Crea CA
CAROOT=/home/apedo/.local/share/mkcert mkcert -install

# Genera cert per CARA + LAN aliases
cd /tmp
CAROOT=/home/apedo/.local/share/mkcert mkcert \
  -cert-file cara.crt -key-file cara.key \
  192.168.1.23 10.8.0.1 127.0.0.1 localhost \
  nanopc-t6 nanopc-t6.local nanopc-t6.station \
  cara.home.lan cara.local

# Installa in nginx-proxy
sudo cp cara.crt /opt/nginx-proxy/ssl/server.crt
sudo cp cara.key /opt/nginx-proxy/ssl/server.key
sudo docker exec nginx-proxy nginx -s reload
```

### Distribuire la CA ai device famiglia

CARA pubblica la CA in 3 URL:

```
http://192.168.1.23/cara-ca.crt           → HTTP plain (no warning)
http://192.168.1.23:8880/cara-ca.crt      → HTTP plain backup
https://192.168.1.23:8455/cara-ca.crt     → HTTPS (solo se CA già installata)
```

L'HTTP plain è **fondamentale**: il device non può scaricare via HTTPS
finché non ha la CA. Chicken-and-egg risolto.

Per ogni device, segui le istruzioni del cap 2.9.

### Let's Encrypt (futuro)

Per accesso da fuori (vacanza, ufficio) con cert pubblico vero:

1. Registra dominio (es. `cara-pedoto.duckdns.org`)
2. Configura ddclient o equivalente che aggiorna A record
3. certbot in DNS-01 mode (no need open 80/443 al pubblico)
4. nginx-proxy serve cert Let's Encrypt rinnovato auto

Non implementato oggi. Vedi `docs/MANUALE-ADMIN.md` per la
procedura completa quando deciderai di farlo.

## 19.6 Audit log — `audit_log` table

**File**: `cara/services/audit.py`.

Append-only. Ogni operazione admin scrive una entry:

```python
class AuditLog(Base):
    id: BigInt
    actor_user_id: int | None  # chi ha fatto l'azione
    actor_email: str | None    # cached per resilienza (cancellazione user)
    action: str                # "skill.approved", "settings.update", ...
    target_kind: str | None    # "skill" | "user" | "device" | ...
    target_id: str | None      # ID del target
    detail: dict               # JSONB, payload arbitrario
    ip: str | None             # client IP
    note: str | None
    created_at: datetime
```

### Cosa viene loggato

Tutte le mutazioni admin:

- `settings.update` (PATCH /admin/settings)
- `skill.created`, `skill.patched`, `skill.approved`, `skill.rejected`,
  `skill.deleted`
- `device.paired`, `device.patched`, `device.deleted`
- `setup.step.*`, `setup.completed`, `setup.reset`
- `tts.overrides.put/patch/delete`
- `memory.purge` (admin purgina memory di un altro user)
- `oauth.connected`, `oauth.disconnected`

### Mascheramento secrets

`mask_secret(value)` da `cara/services/env_writer.py`:

```python
def mask_secret(value: str | None) -> str:
    if not value:
        return "<empty>"
    h = hashlib.sha256(value.encode()).hexdigest()[:8]
    return f"***hash:{h}***"
```

Esempio audit entry per VAPID setup:

```json
{
  "actor_email": "antonio@example.com",
  "action": "setup.step.integrations.vapid",
  "detail": {
    "public_key_prefix": "BMXyz...",
    "subject": "mailto:antonio@example.com"
  },
  "ip": "192.168.1.50"
}
```

La private key VAPID **mai** loggata in chiaro.

### Lettura

Endpoint admin: `GET /admin/audit?limit=100&action=skill.approved`.

Frontend: tab Audit in `/admin` mostra ultimi 100 con filtro per
action.

> **🔒 Sicurezza** — il `audit_log` è append-only. Niente API DELETE.
> Se vuoi conservare gli audit oltre 1 anno, configura un job di
> archiviazione su filesystem read-only (futuro).

## 19.7 Rate limiting

CARA ha rate limiting in pochi punti critici:

- **CDA discover**: token bucket Redis, 10 token / utente, refill 1
  ogni 2 secondi
- **Setup endpoint** (auth-anonimi): 5 tentativi / 5 min per IP per
  `/setup/admin` (anti-bruteforce takeover)

Future:
- Login: 10 tentativi / 5 min per IP (oggi nessun limit, mitigato da
  bcrypt cost)
- Chat: rate limit per utente per evitare resource hogging

## 19.8 CSRF + CORS

**CSRF**: CARA usa Bearer auth (Authorization header), non cookie.
Quindi CSRF non si applica — un sito malevolo che fa fetch verso CARA
non riceve i nostri Bearer headers.

**CORS**: il backend ha `Access-Control-Allow-Origin: *` per le
richieste API. **Pericoloso** in teoria (siti random potrebbero
chiamare `/api/v1/auth/login` dal browser dell'utente), ma:
- Il login richiede credenziali, non è un endpoint che cambia stato
  dell'utente esterno
- Il bearer auth previene cross-origin write senza token

In produzione futura, restringere `Allow-Origin` a `https://192.168.1.23:8455`.

## 19.9 Container hardening

`cara-backend` ha **una sola** capability speciale: accesso al DRI
device per la NPU.

```yaml
devices:
  - /dev/dri/card0
group_add:
  - "44"  # video group
```

Tutti gli altri privilegi sono al default (no privileged, no host
network, no capability extra). AppArmor abilitato.

`cara-postgres` etc. hanno default Docker (no special privilege).

## 19.10 Backup + recovery

**Backup minimo**:

```bash
# Postgres
docker exec cara-postgres pg_dump -U cara cara > backup-$(date +%Y%m%d).sql.gz

# Encryption key (.env)
cp /opt/cara/.env backup/cara.env

# JWT secret (.env, già coperto)
```

Il `.env` contiene segreti. Backuppalo cifrato (es. `gpg`):

```bash
gpg --symmetric --cipher-algo AES256 /opt/cara/.env
# crea .env.gpg, chiede passphrase
```

**Recovery**: se perdi `OAUTH_ENCRYPTION_KEY` non puoi più decifrare i
token Google → utenti devono ri-OAuth. Se perdi `JWT_SECRET`, tutti
re-login (ma senza perdita dati).

> **⚠️ Attenzione** — il database backup `.sql.gz` contiene password
> hashate (bcrypt — sicure) ma contiene anche oauth_credentials
> cifrate. Senza la chiave di cifratura il backup è inutilizzabile.
> **Backuppali insieme.**

## 19.11 Penetration testing — cose da testare

Ogni 6 mesi consigliamo un assessment manuale:

1. **Login bruteforce**: prova 1000 password contro `/auth/login`.
   Senza rate limit, dovrebbe rallentare per via di bcrypt (~250ms each).
2. **JWT manipulation**: cambia il claim `is_admin` → verifica firma
   rigetta.
3. **CSRF**: visita un sito test che fa `fetch('/api/v1/...')` da
   altro origin → verifica CORS rifiuta o richiede credentials.
4. **Path traversal**: prova `GET /api/v1/files/../../../etc/passwd` →
   verifica 404 o 403.
5. **SQL injection**: gli endpoint accettano JSON tipizzato Pydantic
   → SQLAlchemy parametrizza → bassa probabilità. Comunque test:
   `{"title": "'; DROP TABLE tasks;--"}` non deve droppare nulla.
6. **Audit tampering**: prova a chiamare `DELETE /admin/audit/{id}` →
   non esiste → 404.

## 19.12 Estendere — token blocklist (revoke immediate)

Per supportare revoke immediate (device perso o JWT compromesso):

1. Crea tabella `revoked_tokens` (jti UUID + revoked_at)
2. JWT issue: aggiungi claim `jti=uuid()`
3. JWT verify: prima della verifica scadenza, controlla `jti` non in
   `revoked_tokens`
4. API admin `POST /admin/revoke-token {jti}` aggiunge al table
5. Cleanup periodic: cancella row con `revoked_at < now - 1y` (oltre la
   scadenza naturale)

Effort: ~1 EW. Trade-off: ogni request fa un DB lookup extra.

---

[← Cap 18 Setup wizard](18-setup-wizard.md) · [README](README.md) · [Cap 20 Pannello admin →](20-pannello-admin.md)
