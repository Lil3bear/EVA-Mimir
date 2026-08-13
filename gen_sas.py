#!/usr/bin/env python3
import hmac, hashlib, base64, datetime, urllib.parse, sys

KEY = base64.b64decode("Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw==")
ACCOUNT = "devstoreaccount1"

def iso8601(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")

def make_sas(version="2021-06-08", sp="rwdlac", ss="b", srt="sco", minutes=60):
    now = datetime.datetime.utcnow()
    start = iso8601(now - datetime.timedelta(minutes=5))
    expiry = iso8601(now + datetime.timedelta(minutes=minutes))

    # Account SAS StringToSign (>= 2020-12-06 includes encryptionScope)
    fields = [
        ACCOUNT,        # accountName
        sp,             # signedPermissions
        ss,             # signedService
        srt,            # signedResourceType
        start,          # signedStart
        expiry,         # signedExpiry
        "",             # signedIP
        "",             # signedProtocol
        version,        # signedVersion
        "",             # signedSnapshotTime (2018-11-09+)
        "",             # signedEncryptionScope (2020-12-06+)
        "",             # cacheControl
        "",             # contentDisposition
        "",             # contentEncoding
        "",             # contentLanguage
        "",             # contentType
    ]
    if version < "2018-11-09":
        fields = fields[:9] + fields[11:]
    if version < "2020-12-06":
        fields = fields[:10] + fields[11:]
    string_to_sign = "\n".join(fields)
    sig = base64.b64encode(hmac.new(KEY, string_to_sign.encode(), hashlib.sha256).digest()).decode()

    params = {
        "sv": version, "sp": sp, "ss": ss, "srt": srt,
        "st": start, "se": expiry, "sig": sig,
    }
    sas = urllib.parse.urlencode(params)
    print("string_to_sign:")
    print(repr(string_to_sign))
    print("SAS:")
    print(sas)
    print("SAS raw (for &):")
    print(sas.replace("%3A", ":").replace("%2B", "+").replace("%3D", "=").replace("%2F", "/"))
    return sas

if __name__ == "__main__":
    v = sys.argv[1] if len(sys.argv) > 1 else "2021-06-08"
    make_sas(version=v)
