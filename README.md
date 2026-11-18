# 共用对照与重复随访服务

项目证据目录保存研究、人群、共享试验臂、量表方向、随访和发表材料关联，并提供跨研究证据合成：区分独立人群、共享对照与同一人群的反复测量，只在含义相容的层内合并，未报告相关系数时给出结论对假定相关性的敏感程度，支持是否推广某类服务的判断。

## 运行环境

使用 Python 3.11，仅依赖标准库，无外部服务、账号或网络数据。
示例数据使用虚构标识和本地合成记录，不涉及真实学员。

```bash
python3 -m app check
python3 -m app summary
python3 -m app serve --host 127.0.0.1 --port 8080
```

服务提供只读 JSON 查询：`/api/catalog`, `/api/evidence`, `/api/synthesis`。
`/health` 显示存活及表计数，`/api/records?table=表名` 可查看已知数据表。
详细字段语义、计数单位和当前能力见 `docs/数据契约.md`。

## 验证

```bash
python3 -m unittest discover -s tests -v
python3 -m compileall -q app tests smoke.py
python3 smoke.py
```

测试从实际数据装载进入领域计算、报告与真实 HTTP 服务，并用临时副本验证错误输入。
冒烟程序动态分配本地端口，启动服务后读取全部业务查询并原样输出 JSON，随后正常关闭。
查询不写回数据，因此可以直接重复运行；验证不会访问项目外文件。

## 容器

```bash
docker build -t evidence-network:local .
docker run --rm --network none evidence-network:local
docker run --rm --network none evidence-network:local python3 smoke.py
```

镜像只封装本应用，测试使用回环网络，不依赖宿主端口。
无第三方包依赖，`requirements.lock` 记录此状态。

## 业务办理

人工选择研究与地区形成推广提案，propose 按证据确定办理类型（promote 或补证试点 evidence_pilot，证据不足时不能按全面推广提出），pilot_funds.approve 在地区预算内审批并核对证据基线未过期，pilot_agreements.sign 按获批地区和范围签署参与确认；数据变化后未签署的试点不能沿用旧依据，已签署的确认保留并可在审计中看到基线状态。

业务操作以 JSON 对象 POST 到 `/api/workflow/操作名`，下列操作保留现有函数入参和行为。

- `recommendations.propose`
- `pilot_funds.approve`
- `pilot_agreements.sign`
- `pilot_agreements.audit`（只读，列出三环节记录及基线是否仍然有效）

业务贯通用例见 `tests/test_workflows.py`，其中为可直接运行的本地调用。默认状态存于内存；需要重启后保留时，可运行 `python3 -m app serve --state /tmp/learning-service.sqlite3`。状态库只保留本机操作，不向外部发送数据。
