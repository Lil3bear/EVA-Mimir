# fastcoll 源码

将 fastcoll 源码文件（*.cpp, *.h）放到此目录。

下载地址：https://www.win.tue.nl/hashclash/

编译命令（Ubuntu 22.04）：
```bash
g++ -O2 -o fastcoll *.cpp
```

如果你已有编译好的 linux/amd64 二进制，也可以直接放到 `docker/fastcoll`。
Dockerfile 的多阶段构建会优先从此目录编译。
