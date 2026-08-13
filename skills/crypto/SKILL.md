# Crypto 密码学 Skill — CTF Crypto 题全流程指引

## 适用场景
CTF Crypto 类题目，包括古典密码、RSA、AES、哈希破解、编码转换、数论攻击等。

---

## 阶段一：识别密码类型

### 1.1 编码识别
```bash
# Base64 检测和解码
echo "ENCODED_STRING" | base64 -d

# Hex 解码
echo "48656c6c6f" | xxd -r -p

# URL 解码
python3 -c "from urllib.parse import unquote; print(unquote('ENCODED'))"

# 多层编码自动检测
python3 -c "
import base64, binascii
s = 'INPUT_STRING'
# 尝试 base64
try:
    d = base64.b64decode(s)
    print('Base64:', d)
except: pass
# 尝试 hex
try:
    d = binascii.unhexlify(s)
    print('Hex:', d)
except: pass
# 尝试 base32
try:
    d = base64.b32decode(s)
    print('Base32:', d)
except: pass
"
```

### 1.2 古典密码
```python
# Caesar 密码暴力破解
def caesar_brute(ct):
    for shift in range(26):
        pt = ''.join(chr((ord(c)-ord('a')-shift)%26+ord('a')) if c.isalpha() else c for c in ct.lower())
        print(f"shift={shift:2d}: {pt}")

# Vigenere 密码（已知密钥）
def vigenere_decrypt(ct, key):
    key = key.lower()
    result = []
    ki = 0
    for c in ct:
        if c.isalpha():
            shift = ord(key[ki % len(key)]) - ord('a')
            base = ord('A') if c.isupper() else ord('a')
            result.append(chr((ord(c) - base - shift) % 26 + base))
            ki += 1
        else:
            result.append(c)
    return ''.join(result)

# 栅栏密码
def rail_fence_decrypt(ct, rails):
    fence = [[] for _ in range(rails)]
    pattern = list(range(rails)) + list(range(rails-2, 0, -1))
    lengths = [0] * rails
    for i in range(len(ct)):
        lengths[pattern[i % len(pattern)]] += 1
    idx = 0
    for r in range(rails):
        fence[r] = list(ct[idx:idx+lengths[r]])
        idx += lengths[r]
    result = []
    pos = [0] * rails
    for i in range(len(ct)):
        r = pattern[i % len(pattern)]
        result.append(fence[r][pos[r]])
        pos[r] += 1
    return ''.join(result)

# 培根密码、摩尔斯电码等 → 直接用 Python 字典映射
```

---

## 阶段二：RSA 攻击

### 2.1 RSA 基础参数关系
```
n = p * q           # 模数
phi = (p-1)*(q-1)   # 欧拉函数
e * d ≡ 1 (mod phi) # 公钥私钥关系
c = m^e mod n       # 加密
m = c^d mod n       # 解密
```

### 2.2 常见 RSA 攻击
```python
from Crypto.Util.number import long_to_bytes, inverse, GCD

# ===== 小 e 攻击（e=3 且 m^e < n）=====
import gmpy2
m = gmpy2.iroot(c, e)[0]
print(long_to_bytes(m))

# ===== 共模攻击（同 n 不同 e，对同一明文加密）=====
def common_modulus(n, e1, c1, e2, c2):
    g, s1, s2 = extended_gcd(e1, e2)
    if s1 < 0:
        s1 = -s1
        c1 = inverse(c1, n)
    if s2 < 0:
        s2 = -s2
        c2 = inverse(c2, n)
    return (pow(c1, s1, n) * pow(c2, s2, n)) % n

# ===== Wiener 攻击（d 很小）=====
# pip install owiener
import owiener
d = owiener.attack(e, n)
if d:
    m = pow(c, d, n)
    print(long_to_bytes(m))

# ===== Fermat 分解（p 和 q 接近）=====
def fermat_factor(n):
    import gmpy2
    a = gmpy2.isqrt(n) + 1
    while True:
        b2 = a*a - n
        if gmpy2.is_square(b2):
            b = gmpy2.isqrt(b2)
            return int(a-b), int(a+b)
        a += 1

# ===== n 可分解时直接用 factordb =====
# 访问 http://factordb.com/index.php?query=N
# 或用 Python：
# pip install factordb-pycli
from factordb.factordb import FactorDB
f = FactorDB(n)
f.connect()
factors = f.get_factor_list()
```

### 2.3 RSA 解密完整流程
```python
from Crypto.Util.number import long_to_bytes, inverse

# 已知 p, q, e, c
n = p * q
phi = (p-1) * (q-1)
d = inverse(e, phi)
m = pow(c, d, n)
flag = long_to_bytes(m)
print(flag)
```

---

## 阶段三：对称加密

### 3.1 AES
```python
from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad
import base64

# AES-ECB 解密
key = b'sixteen byte key'  # 16/24/32 字节
cipher = AES.new(key, AES.MODE_ECB)
pt = unpad(cipher.decrypt(ct_bytes), AES.block_size)

# AES-CBC 解密
iv = b'sixteen byte iv!'
cipher = AES.new(key, AES.MODE_CBC, iv)
pt = unpad(cipher.decrypt(ct_bytes), AES.block_size)

# AES-CBC Padding Oracle 攻击
# 原理：通过修改 IV 逐字节爆破明文
# 工具：paddingOracle.py 或手动实现
```

### 3.2 XOR 加密
```python
# 已知密钥 XOR 解密
def xor_decrypt(ct: bytes, key: bytes) -> bytes:
    return bytes(c ^ key[i % len(key)] for i, c in enumerate(ct))

# 单字节 XOR 暴力破解
for k in range(256):
    pt = bytes(c ^ k for c in ct)
    if b'flag' in pt or b'CTF' in pt:
        print(f"key={k}: {pt}")

# 重复密钥 XOR 破解（Kasiski / 重合指数）
# 先确定密钥长度，再逐字节频率分析
```

---

## 阶段四：哈希

### 4.1 哈希识别
```bash
# 常见长度
# 32 hex → MD5
# 40 hex → SHA1
# 64 hex → SHA256
# 128 hex → SHA512

# hashid 工具
hashid 'HASH_VALUE'
```

### 4.2 哈希破解
```bash
# 在线查询
curl -s "https://www.cmd5.com/api.ashx?email=&key=&hash=HASH" 2>/dev/null

# Python hashlib 暴力
python3 -c "
import hashlib, itertools, string
target = 'TARGET_HASH'
for length in range(1, 8):
    for combo in itertools.product(string.ascii_lowercase + string.digits, repeat=length):
        candidate = ''.join(combo)
        if hashlib.md5(candidate.encode()).hexdigest() == target:
            print('Found:', candidate)
            exit()
"
```

### 4.3 哈希长度扩展攻击
```bash
# 原理：知道 H(secret||msg) 和 len(secret)，可计算 H(secret||msg||padding||append)
# 工具：hash_extender
hash_extender --data "original" --secret-length 16 --append "admin" --signature "KNOWN_HASH" --format md5
```

---

## 阶段五：数论工具

```python
# 模逆元
from Crypto.Util.number import inverse
d = inverse(e, phi)

# 中国剩余定理
def crt(remainders, moduli):
    from functools import reduce
    M = reduce(lambda a,b: a*b, moduli)
    result = 0
    for r, m in zip(remainders, moduli):
        Mi = M // m
        yi = inverse(Mi, m)
        result += r * Mi * yi
    return result % M

# 离散对数（小范围）
# Baby-step Giant-step
def bsgs(g, h, p):
    import math
    m = math.ceil(math.sqrt(p))
    table = {}
    power = 1
    for j in range(m):
        table[power] = j
        power = (power * g) % p
    factor = pow(g, -m, p)
    gamma = h
    for i in range(m):
        if gamma in table:
            return i * m + table[gamma]
        gamma = (gamma * factor) % p
    return None
```

---

## 常见坑

| 现象 | 可能原因 | 对策 |
|------|---------|------|
| RSA 解密得到乱码 | padding 没去掉 | 检查 PKCS1_OAEP / PKCS1_v1_5 |
| n 很大无法分解 | 不是直接分解的题 | 看是否有其他条件（共模/小e/leak） |
| AES 解密报 padding error | 密钥/IV/模式错误 | 确认加密模式和参数 |
| 哈希碰撞找不到 | 不是暴力题 | 看是否有 length extension / birthday |
| Python 大数运算慢 | 没用 gmpy2 | `pip install gmpy2`，用 `gmpy2.mpz()` |
