#!/usr/bin/env python3
# Recover the 33-byte backdoor key by inverting the transform in check() @ 0x1230
import struct

rot = [3, 5, 2, 7, 1, 4]           # rbp @ 0x232d
add = [0x1b, 0x4d, 0x9c, 0x27, 0xe3, 0x5a]   # rbx @ 0x2327
key = [0x6f, 0xa3, 0x11, 0xce, 0x74, 0x2d]   # r11 @ 0x2321

# target output, little-endian of the QWORD constants + final byte
target = bytearray(33)
target[0:8]   = struct.pack('<Q', 0x8c685b3462076e80)
target[8:16]  = struct.pack('<Q', 0x1ec379c2da202eae)
target[16:24] = struct.pack('<Q', 0x1de2892bcc685bde)
target[24:32] = struct.pack('<Q', 0xe5680920711fdc74)
target[32]    = 0x91

def rol(x, n): return ((x << n) | (x >> (8 - n))) & 0xFF
def ror(x, n): return ((x >> n) | (x << (8 - n))) & 0xFF

def forward(inp):
    out = bytearray(33)
    for r9 in range(33):
        x = inp[r9]
        for r in range(6):
            x = rol(x, rot[r])
            x = (x + add[r]) & 0xFF
            x ^= key[(r + r9) % 6]
        out[r9] = x
    return out

# invert
inp = bytearray(33)
for r9 in range(33):
    x = target[r9]
    for r in range(5, -1, -1):
        x ^= key[(r + r9) % 6]
        x = (x - add[r]) & 0xFF
        x = ror(x, rot[r])
    inp[r9] = x

print("recovered key:", inp.hex())
print("as string    :", inp.decode('latin1'))
# verify
assert forward(inp) == target, "verification failed"
print("forward check OK -> target matches")
