````md
# 🔐 Workflow 2FA API Test Guide (QR + OTP Flow)

This document demonstrates how to simulate the **Workflow 2FA Approval Process** using API calls.

---

## ✅ Environment Variables

```bash
BASE_URL="http://localhost:8181"
DB="dev-workflow-studio-1"
LOGIN="administrator"
PASSWORD="admin"
CHALLENGE_ID=123   # From current 2FA dialog / challenge record
````

---

## 1️⃣ Login (Session Authentication)

Authenticate and store session cookie for subsequent requests.

```bash
curl -s -c /tmp/odoo.cookie \
  -H "Content-Type: application/json" \
  -d "{
    \"jsonrpc\":\"2.0\",
    \"method\":\"call\",
    \"params\":{
      \"db\":\"$DB\",
      \"login\":\"$LOGIN\",
      \"password\":\"$PASSWORD\"
    },
    \"id\":1
  }" \
  "$BASE_URL/web/session/authenticate"
```

---

## 2️⃣ Get Challenge Status (Retrieve QR Signature)

Fetch challenge state and obtain the QR signature token.

```bash
STATUS_JSON=$(curl -s -b /tmp/odoo.cookie \
  -H "Content-Type: application/json" \
  -d "{
    \"jsonrpc\":\"2.0\",
    \"method\":\"call\",
    \"params\":{\"challenge_id\":$CHALLENGE_ID},
    \"id\":2
  }" \
  "$BASE_URL/workflow_2fa/challenge/status")

echo "$STATUS_JSON" | jq '.result'

SIGNATURE=$(echo "$STATUS_JSON" | jq -r '.result.signature')
```

---

## 3️⃣ Simulate QR Scan (Mobile Device)

Trigger mobile **QR scanned** event.

```bash
curl -s \
  -H "Content-Type: application/json" \
  -d "{
    \"jsonrpc\":\"2.0\",
    \"method\":\"call\",
    \"params\":{\"challenge_id\":$CHALLENGE_ID},
    \"id\":3
  }" \
  "$BASE_URL/workflow_2fa/mobile/scanned"
```

---

## 4️⃣ Simulate Mobile Approval

Approve the request using the signed QR token.

```bash
curl -s \
  -H "Content-Type: application/json" \
  -d "{
    \"jsonrpc\":\"2.0\",
    \"method\":\"call\",
    \"params":{
      \"challenge_id\":$CHALLENGE_ID,
      \"decision\":\"approve",
      \"signed_token\":\"$SIGNATURE\"
    },
    \"id\":4
  }" \
  "$BASE_URL/workflow_2fa/mobile/confirm"
```

---

## 5️⃣ Verify Final Challenge State

Check whether approval is completed successfully.

```bash
curl -s -b /tmp/odoo.cookie \
  -H "Content-Type: application/json" \
  -d "{
    \"jsonrpc\":\"2.0\",
    \"method\":\"call\",
    \"params\":{\"challenge_id\":$CHALLENGE_ID},
    \"id\":5
  }" \
  "$BASE_URL/workflow_2fa/challenge/status" \
  | jq '.result.state'
```

---

## ✅ Expected Flow

```
pending
   ↓
qr_displayed
   ↓
scanned
   ↓
approved ✅
```

---

## 🧪 Notes

* `/tmp/odoo.cookie` maintains authenticated session.
* `SIGNATURE` acts as secure QR approval proof.
* Mobile endpoints simulate real device interaction.
* Can be automated inside CI or integration tests.

---
