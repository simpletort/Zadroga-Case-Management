# seed_partner.py — run from lead-intake/api with .venv active
import asyncio, hashlib, os
os.environ["FIRESTORE_EMULATOR_HOST"] = "localhost:8080"
from google.cloud import firestore

RAW_KEY  = "zad_testkey_localdevelopment"       # use this in X-API-Key header
KEY_HASH = hashlib.sha256(RAW_KEY.encode()).hexdigest()

async def main():
    db = firestore.AsyncClient(project="simpletort-zadroga-dev")
    await db.collection("partners").document("partner_local01").set({
        "partnerId":     "partner_local01",
        "name":          "Local Dev Partner",
        "active":        True,
        "allowedIps":    [],          # unrestricted
        "requireHmac":   False,
        "requestCount":  0,
        "apiKeys": [{
            "keyId":     "key_local01",
            "label":     "dev",
            "keyHash":   KEY_HASH,
            "active":    True,
            "createdAt": None,
            "expiresAt": None,
        }],
        "createdAt": None,
        "updatedAt": None,
    })
    print("Seeded partner_local01 with key:", RAW_KEY)

asyncio.run(main())