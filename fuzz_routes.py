import urllib.request, urllib.error, threading, queue, sys

BASE = "http://10.0.185.128:80"
words = """assets asset reimbursement reimbursements report reports download downloads upload uploads export exports generate search api api/search api/v1/search api/v1 api/v1/assets api/v1/reimbursement api/v1/report api/v1/download admin dashboard login logout user users profile me settings setting help about contact notice news announce static templates source src app main run config wsgi requirements.txt Dockerfile docker-compose.yml .git .svn .DS_Store flag flag.txt secret key keys backup bak old test debug console panel manage manager system sys info status check health ping hello index home main root welcome intro view views list lists add create new edit update delete remove submit form forms data dataset datasets file files doc docs pdf excel csv json xml yaml html css js img images image media public private internal network proxy gateway node nodes service services task tasks job jobs log logs error errorlog audit auditlog api_manage api_manage api/user api/users api/asset api/assets api/status api/info api/config api/flag flag1 flag2 root admin/login admin/dashboard admin/user admin/users admin/assets admin/reimbursement admin/report admin/download admin/api admin/log admin/flag user/info user/assets user/reimburse item items detail detail/1 info/1 asset/1 assets/1 reimbursement/1 report/1 download/1 search/1""".split()

q = queue.Queue()
for w in words:
    q.put(w)

results = []
lock = threading.Lock()

def worker():
    while True:
        try:
            w = q.get_nowait()
        except queue.Empty:
            return
        url = BASE + "/" + w
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            r = urllib.request.urlopen(req, timeout=5)
            code = r.status
            body = r.read(200).decode("utf-8", "ignore")
            final = r.geturl()
        except urllib.error.HTTPError as e:
            code = e.code
            final = e.geturl()
            body = ""
        except Exception as e:
            code = "ERR"
            final = str(e)[:60]
            body = ""
        with lock:
            if code != 404 and code != "ERR":
                results.append((code, w, final, body[:80].replace("\n", " ")))
        q.task_done()

threads = [threading.Thread(target=worker) for _ in range(40)]
for t in threads: t.start()
for t in threads: t.join()

results.sort()
seen = set()
for code, w, final, body in results:
    key = (code, final)
    if key in seen: continue
    seen.add(key)
    print(f"[{code}] /{w} -> {final} | {body}")
print("DONE", len(results))
