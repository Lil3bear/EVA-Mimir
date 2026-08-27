## 阶段三：常见算法识别与还原

### ⚠️ 所有算法还原必须写完整 Python 脚本，不要手算！

### 3.1 XOR 加密
```python
# 特征：汇编中出现 xor reg, KEY 循环
# 还原：
encrypted = bytes.fromhex("ENCRYPTED_HEX")
key = b"KEY"
decrypted = bytes(e ^ key[i % len(key)] for i, e in enumerate(encrypted))
print(decrypted)

# 如果密钥未知，尝试已知明文攻击
# 假设 flag 以 "flag{" 开头
known = b"flag{"
key_fragment = bytes(e ^ k for e, k in zip(encrypted[:5], known))
print("Possible key fragment:", key_fragment)
```

### 3.2 Caesar / ROT 变换
```python
# 特征：add/sub 固定值后 mod 26
def caesar_brute(ct):
    for shift in range(256):
        pt = bytes((b - shift) % 256 for b in ct)
        if b'flag' in pt or b'CTF' in pt:
            print(f"shift={shift}: {pt}")

caesar_brute(bytes.fromhex("ENCRYPTED_HEX"))
```

### 3.3 Base64 变表
```python
# 特征：有一个 64 字节的字符串常量作为编码表
import string, base64
std_table = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
custom_table = "CUSTOM_64_CHARS"  # 从程序中提取

encoded = "ENCODED_STRING"
trans = str.maketrans(custom_table, std_table)
decoded = base64.b64decode(encoded.translate(trans))
print(decoded)
```

### 3.4 RC4
```python
def rc4(key, data):
    S = list(range(256))
    j = 0
    for i in range(256):
        j = (j + S[i] + key[i % len(key)]) % 256
        S[i], S[j] = S[j], S[i]
    i = j = 0
    result = []
    for byte in data:
        i = (i + 1) % 256
        j = (j + S[i]) % 256
        S[i], S[j] = S[j], S[i]
        result.append(byte ^ S[(S[i] + S[j]) % 256])
    return bytes(result)

key = b"secret_key"
ct = bytes.fromhex("CIPHERTEXT_HEX")
print(rc4(key, ct))
```

### 3.5 TEA / XTEA
```python
import struct

def tea_decrypt(v, key):
    v0, v1 = struct.unpack('<2I', v)
    k = struct.unpack('<4I', key)
    delta = 0x9e3779b9
    s = (delta * 32) & 0xffffffff
    for _ in range(32):
        v1 = (v1 - (((v0 << 4) + k[2]) ^ (v0 + s) ^ ((v0 >> 5) + k[3]))) & 0xffffffff
        v0 = (v0 - (((v1 << 4) + k[0]) ^ (v1 + s) ^ ((v1 >> 5) + k[1]))) & 0xffffffff
        s = (s - delta) & 0xffffffff
    return struct.pack('<2I', v0, v1)

key = b'\x00' * 16  # 从程序中提取密钥
ct = bytes.fromhex("CIPHERTEXT_HEX")
pt = b''
for i in range(0, len(ct), 8):
    pt += tea_decrypt(ct[i:i+8], key)
print(pt)
```

### 3.6 AES / DES（对称加密）
```python
from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad

# 从逆向中提取 key 和 iv（通常是硬编码常量）
key = bytes.fromhex("KEY_HEX")  # 16/24/32 字节
iv = bytes.fromhex("IV_HEX")    # 16 字节
ct = bytes.fromhex("CT_HEX")

# ECB 模式
cipher = AES.new(key, AES.MODE_ECB)
pt = unpad(cipher.decrypt(ct), AES.block_size)

# CBC 模式
cipher = AES.new(key, AES.MODE_CBC, iv)
pt = unpad(cipher.decrypt(ct), AES.block_size)

print(pt)
```

---

