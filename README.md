# 规则表达式类型推断 API

规则发布前校验服务：`POST /infer` 接收 JSON 表达式树，按词法作用域做
Hindley–Milner 类型推断（含行多态记录），成功时返回 JSON 主类型方案，
失败时返回 `422` 并附节点路径与原因。

## 一键启动

```bash
docker compose up --build
```

服务地址：**http://localhost:8000**（交互式文档见 http://localhost:8000/docs）。

备选方式：

```bash
# 直接使用 Docker
docker build -t rule-infer . && docker run --rm -p 8000:8000 rule-infer

# 本地开发（Python 3.11+）
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

运行测试：`pip install pytest httpx && pytest tests/`

## 表达式树格式

请求体即表达式树（也接受 `{"expression": ...}` 包装）。每个节点是含
`"kind"` 的对象：

| kind      | 字段                                   | 含义                     |
|-----------|----------------------------------------|--------------------------|
| `int`     | `value`: 整数                          | 整数字面量               |
| `bool`    | `value`: 布尔                          | 布尔字面量               |
| `var`     | `name`: 字符串                         | 变量                     |
| `lambda`  | `param`: 字符串, `body`: 表达式        | 单参数 lambda            |
| `call`    | `func`: 表达式, `arg`: 表达式          | 调用（实参与形参统一）   |
| `let`     | `name`, `value`, `body`                | 非递归 let               |
| `record`  | `fields`: `[{"name": k, "value": e}]`  | 记录字面量（闭合记录）   |
| `field`   | `record`: 表达式, `field`: 字符串      | 字段读取（开放记录）     |

限制：**至多 80 个表达式节点，深度不超过 20**（根节点深度为 1；记录字
面量本身计 1 个节点，各字段值各计 1 个）。记录字段重名属于结构错误。

## 类型规则

- `lambda` 参数保持单态；
- `let` 的值推断后，只泛化不在当前环境自由出现的类型变量与行变量，之
  后每次引用独立实例化；
- 记录字面量是闭合记录；字段读取推断允许额外字段的开放记录
  `{field: α | ρ}`，行变量 `ρ` 不得再含已列出的字段；
- 调用的实参类型须与形参统一；
- 未绑定变量、字段不存在、类型冲突、无限类型（occurs check）均返回
  `422`，不产生类型方案；结构错误（含超限、重名字段、非法节点）同样
  返回 `422`。

## curl 示例

恒等函数，返回主类型方案 `∀ a. a → a`：

```bash
curl -s -X POST http://localhost:8000/infer \
  -H 'Content-Type: application/json' \
  -d '{"kind":"lambda","param":"x","body":{"kind":"var","name":"x"}}'
```

```json
{
  "type_scheme": {
    "quantified": {"type_vars": ["a"], "row_vars": []},
    "type": {"kind": "fun",
             "param": {"kind": "var", "name": "a"},
             "result": {"kind": "var", "name": "a"}},
    "pretty": "∀ a. a → a"
  }
}
```

字段读取（开放记录，尾部行变量排除已列出字段）：

```bash
curl -s -X POST http://localhost:8000/infer \
  -H 'Content-Type: application/json' \
  -d '{"kind":"lambda","param":"r","body":{"kind":"field","record":{"kind":"var","name":"r"},"field":"age"}}'
# → "pretty": "∀ a r0. {age: a | r0} → a"
#   param.tail = {"kind": "row_var", "name": "r0", "excludes": ["age"]}
```

let 多态（每次引用独立实例化）：

```bash
curl -s -X POST http://localhost:8000/infer \
  -H 'Content-Type: application/json' \
  -d '{
    "kind":"let","name":"id",
    "value":{"kind":"lambda","param":"x","body":{"kind":"var","name":"x"}},
    "body":{"kind":"record","fields":[
      {"name":"n","value":{"kind":"call","func":{"kind":"var","name":"id"},"arg":{"kind":"int","value":1}}},
      {"name":"b","value":{"kind":"call","func":{"kind":"var","name":"id"},"arg":{"kind":"bool","value":true}}}
    ]}}'
# → "pretty": "{b: bool, n: int}"
```

错误示例（均返回 `422`，响应中不含类型方案）：

```bash
# 未绑定变量 → {"error":{"code":"unbound_variable", ... ,"path":"/body/arg"}}
curl -s -X POST http://localhost:8000/infer -H 'Content-Type: application/json' \
  -d '{"kind":"lambda","param":"x","body":{"kind":"call","func":{"kind":"var","name":"x"},"arg":{"kind":"var","name":"y"}}}'

# 字段不存在 → {"error":{"code":"missing_field", ...}}
curl -s -X POST http://localhost:8000/infer -H 'Content-Type: application/json' \
  -d '{"kind":"field","record":{"kind":"record","fields":[{"name":"a","value":{"kind":"int","value":1}}]},"field":"b"}'

# 无限类型 → {"error":{"code":"infinite_type", ...}}
curl -s -X POST http://localhost:8000/infer -H 'Content-Type: application/json' \
  -d '{"kind":"lambda","param":"x","body":{"kind":"call","func":{"kind":"var","name":"x"},"arg":{"kind":"var","name":"x"}}}'

# 记录字段重名（结构错误）→ {"error":{"code":"duplicate_field", ...}}
curl -s -X POST http://localhost:8000/infer -H 'Content-Type: application/json' \
  -d '{"kind":"record","fields":[{"name":"a","value":{"kind":"int","value":1}},{"name":"a","value":{"kind":"int","value":2}}]}'
```

## 响应格式

成功（`200`）：

```json
{
  "type_scheme": {
    "quantified": {"type_vars": ["a"], "row_vars": ["r0"]},
    "type": { "kind": "fun | int | bool | var | record", "...": "..." },
    "pretty": "∀ a r0. {age: a | r0} → a"
  }
}
```

- `quantified`：量化的类型变量与行变量（变量名统一重命名为
  `a, b, …` 与 `r0, r1, …`）；
- 记录类型：`fields` 为必需字段（`[{"name", "type"}]`），`tail` 为
  `{"kind": "empty"}`（闭合）或
  `{"kind": "row_var", "name": "r0", "excludes": [...]}`（开放尾部及其
  排除字段）；
- `pretty`：便于阅读的类型字符串。

失败（`422`）：

```json
{"error": {"code": "unbound_variable", "message": "unbound variable 'y'", "path": "/body/arg"}}
```

`path` 为出错节点的 JSON Pointer；`code` 取值：`unbound_variable`、
`missing_field`、`type_mismatch`、`infinite_type`、`duplicate_field`、
`too_many_nodes`、`too_deep`、`invalid_expression`、`invalid_json`。

## 项目结构

```
app/
  main.py       FastAPI 入口与路由
  parser.py     JSON 结构校验（节点数/深度限制、重名字段等）
  astnodes.py   表达式 AST
  typesys.py    类型/行、统一、泛化与实例化
  infer.py      类型推断
  serialize.py  主类型方案的 JSON 序列化
tests/test_infer.py
Dockerfile / docker-compose.yml / requirements.txt
```
