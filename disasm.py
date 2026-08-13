import subprocess, re
from capstone import *

data = open('validator','rb').read()
# vaddr -> file offset: .text vaddr 0x401000, file off 0x1000
def v2o(v): return v - 0x400000

def disasm(vaddr, length, label=''):
    off = v2o(vaddr)
    code = data[off:off+length]
    md = Cs(CS_ARCH_X86, CS_MODE_64)
    md.detail = False
    print(f"===== {label} @ 0x{vaddr:x} =====")
    for i in md.disasm(code, vaddr):
        print(f"  0x{i.address:x}: {i.mnemonic}\t{i.op_str}")
    print()

# From parse_go.py:
funcs = {
 'main.main': (0x47d200, 0x1c0),
 'main.reveal': (0x47d080, 0x180),
 'main.keySchedule': (0x47ce20, 0x180),
 'main.keySchedule.func1': (0x47cfa0, 0xe0),
 'main.rotAdd.apply': (0x47cda0, 0x40),
 'main.sbox.apply': (0x47cde0, 0x20),
 'main.xorMix.apply': (0x47ce00, 0x20),
}
for name,(va,ln) in funcs.items():
    disasm(va, ln, name)
