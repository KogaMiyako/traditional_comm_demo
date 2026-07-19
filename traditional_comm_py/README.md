# Python 传统通信本地基线

这是传统通信 Demo 的 Python 版本，使用 `D:\miniconda3\envs\semcom-py` 环境运行。

可复现创建环境：

```powershell
& D:\miniconda3\Scripts\conda.exe env create -f environment.yml --force
```

当前版本只使用 Python 标准库，便于先在单机上跑通：

- 文字：UTF-8 字节传输
- 图像：PPM + Deflate 无损压缩
- 视频：自描述 `TVID1` 帧序列 + Deflate 无损压缩
- 传输：本地 Loopback 适配器，支持分块、延时和丢包参数
- 接口：健康检查、启动运行、模式切换、状态查询、性能获取、结果获取
- 日志：配置、传输统计、性能指标、结果校验

当前环境没有 FFmpeg，所以默认没有直接调用 JPEG/H.264/MP4。后续接入 FFmpeg 时，只需替换 `traditional_comm/codecs.py`，不需要改运行控制和传输接口。

## 创建样本并运行 Demo

在 PowerShell 中执行：

```powershell
Set-Location D:\workspace\SemCom\traditional_comm_py
& D:\miniconda3\envs\semcom-py\python.exe -m traditional_comm.cli demo
```

也可以分步执行：

```powershell
& D:\miniconda3\envs\semcom-py\python.exe -m traditional_comm.cli generate-samples
& D:\miniconda3\envs\semcom-py\python.exe -m traditional_comm.cli run
```

测试：

```powershell
& D:\miniconda3\envs\semcom-py\python.exe -m unittest discover -s tests -v
```

运行后生成：

```text
samples/sample.txt
samples/sample.ppm
samples/sample.tvid
runs/<run_id>/config.json
runs/<run_id>/metrics.json
runs/<run_id>/transport.json
runs/<run_id>/result.json
runs/<run_id>/encoded_payload.bin
runs/<run_id>/output.*
runs/latest_summary.json
```

## 代码结构

```text
traditional_comm/
  codecs.py       # 编码和解码适配
  samples.py      # 文字、图像、视频样本生成
  transport.py    # Loopback 和课题三传输适配接口
  runner.py       # 单次运行、指标、日志
  controller.py   # 启动、切换模式、状态、性能、结果接口
  cli.py          # 命令行入口
tests/
  test_smoke.py
```

## 接口示例

```python
controller.health_check()
controller.switch_mode("traditional")
started = controller.start_run({"kind": "image", "input_path": "samples/sample.ppm"})
controller.get_status(started["run_id"])
controller.get_performance(started["run_id"])
controller.get_result(started["run_id"])
```

`Task3Transport` 是预留适配器。接入第三组通信链路时，替换 `LoopbackTransport` 即可，业务运行器不应直接依赖 TCP、UDP 或硬件。
