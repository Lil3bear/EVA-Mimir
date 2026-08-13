import socket, time, sys

host, port = "10.0.185.129", 9010

def interact(commands, wait=0.05):
    s = socket.create_connection((host, port), timeout=10)
    f = s.makefile('rwb', buffering=0)
    def send(cmd):
        f.write(cmd.encode() + b"\n")
        time.sleep(wait)
        try:
            return f.readline().decode(errors='replace').strip()
        except Exception as e:
            return f"ERR {e}"
    out = []
    for c in commands:
        out.append((c, send(c)))
    s.close()
    return out

if __name__ == "__main__":
    cmds = sys.argv[1:] if len(sys.argv) > 1 else [""]
    for c, r in interact(cmds):
        print(f">>> {c!r}\n<<< {r!r}")
