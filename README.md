# 规则表达式类型推断服务

基于 FastAPI 的规则表达式类型推断 HTTP API，用于规则发布前的静态校验。
对 JSON 表达式树执行 Hindley-Milner 类型推断（let 多态 + 行多态记录），
成功时返回主类型方案，失败时返回带节点路径与原因的 422 错误。

## 一键启动

```bash
docker compose up --build
```

服务地址：**http://localhost:8000**(API 文档见 http://localhost:8000/docs)

不使用 Docker 的本地启动方式：

```bash
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## API

### POST /infer

请求体为一棵 JSON 表达式树（至多 **80 个节点**、深度不超过 **20**)。每个节点是带
`tag` 字段的对象：

| tag      | 字段                                   | 含义                     |
|----------|----------------------------------------|--------------------------|
| `int`    | `value`: 整数                          | 整数字面量               |
| `bool`   | `value`: 布尔                          | 布尔字面量               |
| `var`    | `name`: 字符串                         | 变量                     |
| `lambda` | `param`, `body`                        | 单参数 lambda            |
| `call`   | `fn`, `arg`                            | 调用                     |
| `let`    | `name`, `value`, `body`                | 非递归 let               |
| `record` | `fields`: `[{"name", "value"}, ...]`   | 记录字面量（闭合记录）   |
| `field`  | `record`, `name`                       | 字段读取                 |

推断规则：

- 词法作用域；lambda 参数在函数体内保持单态；
- `let` 的值推断后，只泛化不在当前环境自由出现的类型变量与行变量，后续每次
  引用都独立实例化；
- 记录字面量是闭合记录；字段读取推断允许额外字段的开放记录，其行变量不得再
  含已列出的字段（`lacks` 约束）；
- 调用的实参类型须与形参统一。

### 成功响应（200)

返回主类型方案，含量化的类型变量与行变量、函数类型、记录必需字段及开放尾部
的排除字段（变量名为统一重命名后的规范名）：

```json
{
  "scheme": {
    "forall": { "type_vars": ["t0"], "row_vars": ["r0"] },
    "type": {
      "kind": "fun",
      "param": {
        "kind": "record",
        "fields": [{ "name": "age", "type": { "kind": "var", "name": "t0" } }],
        "tail": { "kind": "open", "var": "r0", "lacks": ["age"] }
      },
      "result": { "kind": "var", "name": "t0" }
    }
  }
}
```

类型 JSON 的 `kind` 取值：`int` / `bool` / `var` / `fun` / `record`;
记录尾部 `tail` 为 `{"kind": "closed"}` 或
`{"kind": "open", "var": "rN", "lacks": [...]}`。

### 错误响应（422)

不产生类型方案，返回节点路径（JSONPath 风格，`$` 为根）与原因：

```json
{ "error": { "kind": "missing_field", "message": "record is missing field 'b'", "path": "$" } }
```

`kind` 取值：

- `unbound_variable` — 未绑定变量
- `missing_field` — 记录不存在所需字段
- `type_conflict` — 类型冲突
- `infinite_type` — 出现无限类型
- `structural` — 结构错误（非法 JSON、未知 tag、缺字段、记录字段重名、
  超过 80 节点或深度超过 20 等）

## curl 示例

字段读取（开放记录）:

```bash
curl -s http://localhost:8000/infer \
  -H 'Content-Type: application/json' \
  -d '{"tag":"lambda","param":"r","body":{"tag":"field","record":{"tag":"var","name":"r"},"name":"age"}}'
```

let 多态（`let id = λx. x in {a: id 1, b: id true}`):

```bash
curl -s http://localhost:8000/infer \
  -H 'Content-Type: application/json' \
  -d '{"tag":"let","name":"id","value":{"tag":"lambda","param":"x","body":{"tag":"var","name":"x"}},"body":{"tag":"record","fields":[{"name":"a","value":{"tag":"call","fn":{"tag":"var","name":"id"},"arg":{"tag":"int","value":1}}},{"name":"b","value":{"tag":"call","fn":{"tag":"var","name":"id"},"arg":{"tag":"bool","value":true}}}]}}'
```

类型错误（无限类型 `λx. x x`，返回 422):

```bash
curl -s http://localhost:8000/infer \
  -H 'Content-Type: application/json' \
  -d '{"tag":"lambda","param":"x","body":{"tag":"call","fn":{"tag":"var","name":"x"},"arg":{"tag":"var","name":"x"}}}'
# {"error":{"kind":"infinite_type","message":"cannot construct the infinite type ...","path":"$.body"}}
```

## 测试

```bash
pip install pytest httpx
pytest
```
