# v15云端运行与恢复

冻结设计在PLAN.md。可读源码为`tools/qc_v15_dynamic_pilot.py`；用下方准备工具生成32KiB以内的`cloud/main.py`放入独立QC项目，不能导入或启动旧v10人工成交代理。

云项目：<https://www.quantconnect.com/project/36834914>。原v14项目36832711保留。参数`mode=audit/A/B/C`、`cost_bps=10/20`；源码无参数时默认audit，本轮云端最后保存为A/10。先完成audit门槛，再按REGISTRATION.json的六组固定组合运行原生历史Backtest。禁止Live/Paper/券商连接；日期在源码锁定2022—2023，21日历史只向过去暖机。

本轮通过网页编辑器粘贴源码；云副本省略注释/docstring，因此字节SHA不同。运行日志同时记录云字节SHA和可执行AST SHA；后者剥离docstring及Python3.12空type_params字段，用于严格核对实际逻辑，不忽略常量、函数体或参数变化。复制回编辑器全源码还需与发送文本核对，不能仅以编译成功替代。

日志`V15_IDENTITY`是运行身份；audit的`V15_MONTH`字段序列由源码`MONTH_FIELDS`定义，时间为自2022-01-01起的纽约本地秒数，成员哈希为完整SHA256的base64。主运行使用`V15_MONTH_CHECK`保留24月共同指纹及目标数量，避免重复输出触及免费日志上限；验证器从audit重建并逐哈希核对。`V15_SUMMARY`为指标，`V15_ISSUE`为异常摘要。使用`Log`；必须核对summary声明的异常数与实际记录数一致，不能以日志出现就当完整保存。

已完成结果只读验证及汇总，不重新查询数据：

```powershell
.\.venv\Scripts\python.exe -B tools/verify_qc_v15_pilot.py
.\.venv\Scripts\python.exe -B tools/summarize_qc_v15_pilot.py
.\.venv\Scripts\python.exe -B tools/prepare_v15_review.py --verify
```

8个实际日线缺口的限定诊断源码为`tools/qc_v15_missing_price_check.py`，已在同云项目Research运行；单日和相邻控制结果及代码身份另存`MISSING_PRICE_*.json`。它不改变基准，也不能从无记录推断现实停牌。默认笔记本示例的无日期History已被替换，不应执行可能读取今天行情的默认示例。

供应商原始候选和行情仅在QC云内使用。本地只保留允许分享的非重建型聚合结果和运行身份。平台原生回测记录用于恢复检查订单、成交及结果；内存内的辅助事件/日线记录不宣称为永久原始数据快照。再次回测会重新读取供应商当时版本，不能冒充本轮原始接收版本。

本地纯逻辑测试不查询行情，也不代表云端成交通过：

```powershell
@'
import runpy
n = runpy.run_path('tests/test_qc_v15_dynamic_pilot.py')
for key in n:
    if key.startswith('test_'):
        n[key]()
print('pure helper tests passed')
'@ | .\.venv\Scripts\python.exe -B -
```

实际完成数量和结果以REPORT.md及运行记录为准，不以本README的运行说明当作已完成事实。


本地精简上传包：先运行 `.\.venv\Scripts\python.exe -B tools/prepare_qc_v15_source.py`，再用同一命令加 `--verify` 做只读核对。生成的 `cloud/main.py` 仅去除注释、格式及开头docstring，保留所有可执行AST；UTF-8大小必须小于32768字节。`cloud/PREPARED_SOURCE_IDENTITY.json`记录规范源码与准备文件各自的字节SHA和共同AST身份。它是本地准备产物，不能称为已下载或已执行的云源码；手动粘贴的实际云副本仍须以运行时AST身份核对，字节哈希不同不得冒充完全相同文件。每次规范源码修改后重新生成。
