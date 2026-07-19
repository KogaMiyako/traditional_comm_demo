# Python 传统通信本地基线

这是“内容 2：传统通信模型搭建”的 Python 单机基线。运行环境为：

```text
D:\miniconda3\envs\semcom-py
```

该环境已经安装 FFmpeg 8.1.2，图片和视频不再使用临时的 `deflate` 格式，而是使用正式媒体格式：

- 文字：UTF-8 字节，文件扩展名为 `.txt`。
- 图片：输入使用 PPM 作为人为生成的原始 RGB 样本，发送载荷使用 JPEG，扩展名为 `.jpg`。
- 视频：输入使用 TVID1 作为人为生成的原始 RGB 帧样本，发送载荷使用 H.264 编码并封装为 MP4，扩展名为 `.mp4`。

PPM 和 TVID1 只用于本地构造“原始内容”，便于明确测量编码耗时和压缩前后的数据量。真正经过传统通信链路传输的是 JPEG/MP4 字节数据。

## 创建环境

```powershell
& D:\miniconda3\Scripts\conda.exe env create -f environment.yml --force
```

如果环境已经存在，只需确认 FFmpeg：

```powershell
& D:\miniconda3\Scripts\conda.exe run -n semcom-py ffmpeg -version
```

## 运行 Demo

```powershell
Set-Location D:\workspace\SemCom\traditional_comm_py
& D:\miniconda3\envs\semcom-py\python.exe -m traditional_comm.cli demo
```

也可以分步运行：

```powershell
& D:\miniconda3\envs\semcom-py\python.exe -m traditional_comm.cli generate-samples
& D:\miniconda3\envs\semcom-py\python.exe -m traditional_comm.cli run
```

## 测试

```powershell
& D:\miniconda3\envs\semcom-py\python.exe -m unittest discover -s tests -v
```

## 运行结果

每次运行会生成独立目录：

```text
runs/<run_id>/
  config.json             # 输入、模式、编码器、参数和任务配置
  metrics.json            # 数据量、时延、吞吐、质量和资源指标
  transport.json          # 传输统计
  result.json             # 结果文件和校验信息
  encoded_payload.txt     # 发送端编码后的载荷
  encoded_payload.jpg     # 图片运行的 JPEG 载荷
  encoded_payload.mp4     # 视频运行的 H.264/MP4 载荷
  received_payload.*      # 接收端实际收到的载荷
  output.*                # 可播放或可打开的正式输出文件
  decoded.ppm/tvid        # 用于质量指标计算的解码后原始数据
```

图片和视频使用有损编码，因此不能用原始字节哈希判断完全相同；代码会记录输出是否可解码，并记录 PSNR。文字使用无损 UTF-8，可以进行字节级一致性校验。

## 接入课题三

`traditional_comm/transport.py` 中的 `TransportAdapter` 是统一传输接口。开发阶段使用 `LoopbackTransport`，接入课题三时使用 `Task3Transport` 包装课题三实现，业务代码不直接依赖 TCP、UDP 或具体硬件。

```python
from traditional_comm.transport import Task3Transport

transport = Task3Transport(task3_implementation)
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
