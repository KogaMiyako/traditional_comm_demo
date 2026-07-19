# 内容 2：传统通信 Python 实现说明

本文档说明当前仓库中 traditional_comm_py 的代码作用、运行方法、结果查看方式，以及后续接入课题一和课题三时需要使用或扩展的接口。

任务目标是：在单系统下调通常规通信链路，使用 JPEG、H.264/MP4 等常规媒体编码方式，记录编码、传输、解码和结果质量等性能指标，并为课题三真实通信链路和课题一 Web 控制预留接口。

## 1. 整体工作流程

~~~text
输入样本
  │
  ├─ 文字：UTF-8 字节
  ├─ 图片：PPM 原始 RGB 样本
  └─ 视频：TVID1 原始 RGB 帧样本
  │
  ▼
编解码层 codecs.py
  ├─ 文字 -> UTF-8 字节
  ├─ 图片 -> JPEG（.jpg）
  └─ 视频 -> H.264 编码 + MP4 封装（.mp4）
  │
  ▼
传输层 transport.py
  ├─ 单机阶段：LoopbackTransport 本地回环
  ├─ 两台服务器阶段：LanTcpTransport -> LanTcpReceiver
  └─ 课题三联调阶段：Task3Transport -> 课题三通信链路
  │
  ▼
接收端解码
  ├─ UTF-8 字节 -> 文本
  ├─ JPEG -> PPM，供校验和 PSNR 计算
  └─ MP4 -> RGB 帧，重新组成 TVID1，供校验和 PSNR 计算
  │
  ▼
结果和指标
  ├─ 数据量
  ├─ 编码、传输、解码和端到端时延
  ├─ 吞吐率
  ├─ PSNR 等质量指标
  └─ JSON 结果文件和 JPEG/MP4 文件
~~~

需要区分两类文件：

1. PPM 和 TVID1 是当前 Demo 为了构造可控“原始输入”而使用的本地样本格式。
2. 真正模拟传统通信时，图片经过编码后传输的是 JPEG 字节，视频经过编码后传输的是 H.264/MP4 字节。

所以 PPM/TVID1 只是编码器输入，JPG/MP4 才是当前程序的正式媒体载荷。

## 2. 目录结构

~~~text
traditional_comm_py/
├─ environment.yml                 # Conda 环境和 FFmpeg 依赖
├─ README.md                       # 简要使用说明
├─ samples/                        # Demo 自动生成的输入样本
│  ├─ .gitkeep
│  ├─ sample.txt
│  ├─ sample.ppm
│  └─ sample.tvid
├─ runs/                           # 每次运行生成的结果目录
│  ├─ .gitkeep
│  ├─ <run_id>/
│  └─ latest_summary.json
├─ traditional_comm/
│  ├─ __init__.py                  # 对外导出的主要类
│  ├─ samples.py                   # 原始样本生成和解析
│  ├─ codecs.py                    # JPEG、H.264/MP4 编解码适配
│  ├─ transport.py                 # 传输适配器、本地回环和 TCP 局域网链路
│  ├─ runner.py                    # 单次运行、指标和结果保存
│  ├─ controller.py                # 启动、状态、性能和结果接口
│  └─ cli.py                       # 命令行入口
└─ tests/
   └─ test_smoke.py                # 基础回环测试和接口测试
~~~

## 3. 运行环境

当前准备好的环境：

~~~text
Conda 根目录：D:\miniconda3
环境名称：semcom-py
Python：3.12
FFmpeg：8.1.2
~~~

FFmpeg 安装在 Conda 环境内部，不要求安装到 Windows 全局 PATH。代码会优先查找当前 Python 环境中的 FFmpeg，也会尝试查找系统 PATH。

确认 FFmpeg：

~~~powershell
& D:\miniconda3\Scripts\conda.exe list -n semcom-py ffmpeg
& D:\miniconda3\Scripts\conda.exe run -n semcom-py ffmpeg -version
& D:\miniconda3\Scripts\conda.exe run -n semcom-py ffprobe -version
~~~

如果在另一台电脑重新配置环境，在项目根目录执行：

~~~powershell
& D:\miniconda3\Scripts\conda.exe env create -f traditional_comm_py\environment.yml --force
~~~

environment.yml 中已经声明：

~~~yaml
name: semcom-py
channels:
  - conda-forge
dependencies:
  - python=3.12
  - ffmpeg
~~~

## 4. 每份代码的作用

### 4.1 environment.yml

文件位置：[environment.yml](../traditional_comm_py/environment.yml)

作用：描述 Python 和 FFmpeg 依赖，使其他电脑可以按同一份配置创建环境。

当前依赖：

- Python 3.12：运行本项目代码。
- FFmpeg：执行 JPEG、H.264/MP4 的实际编码和解码。

程序没有重新实现 JPEG 或 H.264，而是由 Python 通过子进程调用 FFmpeg。这种方式更接近实际工程，也方便后续调整编码参数和接入真实媒体文件。

### 4.2 traditional_comm/__init__.py

文件位置：[__init__.py](../traditional_comm_py/traditional_comm/__init__.py)

作用：定义 Python 包的对外入口，导出以下对象：

~~~python
from traditional_comm import (
    TraditionalCommunicationController,
    LoopbackTransport,
    Task3Transport,
    TransportAdapter,
)
~~~

业务代码可以从包级别导入这些类，不必关心类具体在哪个源文件中。

### 4.3 traditional_comm/samples.py

文件位置：[samples.py](../traditional_comm_py/traditional_comm/samples.py)

作用：生成 Demo 的文字、图片和视频输入，并解析程序使用的原始样本格式。

主要函数：

- create_rgb_frame(width, height, frame_index, total_frames)：生成一帧 RGB 原始像素，不依赖摄像头或真实视频文件。
- create_ppm(width, height, frame_index, total_frames)：生成 P6 类型 PPM 图片，默认大小为 160x90。
- create_tvid(width, height, fps, frame_count)：生成 TVID1 原始帧序列，当前默认 160x90、10 FPS、12 帧。
- parse_ppm(data)：检查 PPM 的尺寸、颜色深度和 RGB 数据长度，并返回像素数据。
- parse_tvid(data)：检查 TVID1 文件头、帧尺寸和原始 RGB 数据长度。
- generate_samples(output_dir)：生成 sample.txt、sample.ppm 和 sample.tvid。

sample.ppm 和 sample.tvid 是编码前输入，不是最终发送格式。

### 4.4 traditional_comm/codecs.py

文件位置：[codecs.py](../traditional_comm_py/traditional_comm/codecs.py)

作用：负责内容编码和解码，不负责传输，是传统通信链路的媒体编解码层。

#### EncodedPayload

~~~python
@dataclass(frozen=True)
class EncodedPayload:
    codec: str
    container: str
    payload: bytes
    metadata: dict
~~~

字段含义：

| 字段 | 含义 |
|---|---|
| codec | 编码方式，例如 utf8、jpeg、h264 |
| container | 载荷格式，例如 txt、jpg、mp4 |
| payload | 真正交给传输层的字节数据 |
| metadata | 分辨率、帧率、帧数、编码参数和编码器信息 |

#### FFmpeg 查找和调用

_find_binary(name) 依次查找：

1. 系统 PATH 中的 FFmpeg。
2. 当前 Python 所属环境目录中的 FFmpeg。
3. Windows Conda 环境的 Library/bin/ffmpeg.exe。

_run_ffmpeg(arguments, input_data) 会将输入字节交给 FFmpeg，收集标准输出作为结果，收集错误信息，并在 FFmpeg 返回非零状态时抛出异常。单次调用最多运行 120 秒。

#### 图片编码

流程：

~~~text
P6 PPM 字节
  -> FFmpeg image2pipe/ppm 输入
  -> FFmpeg mjpeg 编码
  -> JPEG 字节
~~~

默认参数：

~~~python
{"jpeg_quality": 3}
~~~

FFmpeg 的 JPEG 质量参数范围为 2 到 31，通常数值越小质量越高、文件越大。

返回的核心信息类似：

~~~json
{
  "codec": "jpeg",
  "container": "jpg",
  "metadata": {
    "width": 160,
    "height": 90,
    "encoder": "ffmpeg:mjpeg",
    "parameters": {"jpeg_quality": 3},
    "lossless": false
  }
}
~~~

#### 视频编码

流程：

~~~text
TVID1 头 + RGB 原始帧
  -> FFmpeg rawvideo/rgb24 输入
  -> libx264 H.264 编码
  -> MP4 封装
  -> MP4 字节
~~~

默认参数：

~~~python
{
    "h264_crf": 23,
    "h264_preset": "ultrafast",
}
~~~

其中：

- h264_crf 控制质量和码率，通常数值越小质量越高、文件越大。
- h264_preset 控制编码速度和压缩效率，ultrafast 适合 Demo 快速验证。
- 当前使用 yuv420p，所以视频宽度和高度需要是偶数。
- 使用 MP4 分片参数，使 FFmpeg 可以把 MP4 直接输出到标准输出，再作为字节传给传输层。

#### 解码

decode_payload(kind, payload, metadata) 将接收到的正式载荷恢复成程序能够校验的数据：

| 类型 | 接收到的正式载荷 | 解码后的内部数据 |
|---|---|---|
| 文字 | UTF-8 字节 | UTF-8 字节 |
| 图片 | JPEG | PPM RGB 数据 |
| 视频 | H.264/MP4 | TVID1 RGB 帧数据 |

视频解码需要编码阶段保存的宽度、高度、帧率和预期帧数等元数据。因此，接入课题三时，元数据必须和载荷一起传递，不能只传裸字节。

#### codec_info(kind)

返回当前媒体类型的基础格式：

~~~python
codec_info("text")  # utf8/txt
codec_info("image") # jpeg/jpg
codec_info("video") # h264/mp4
~~~

### 4.5 traditional_comm/transport.py

文件位置：[transport.py](../traditional_comm_py/traditional_comm/transport.py)

作用：提供传输层抽象。编码模块只产生字节，传输模块只负责发送和接收字节。

#### TransportAdapter

当前最小接口：

~~~python
class TransportAdapter(ABC):
    def health_check(self) -> dict:
        ...

    @abstractmethod
    def send_payload(
        self,
        payload: bytes,
        metadata: dict | None = None,
    ) -> tuple[bytes, dict]:
        ...
~~~

输入是编码后的 bytes 和传输元数据；返回值是接收端重组后的 bytes 和传输统计字典。

当前发送元数据包括：

~~~json
{
  "run_id": "本次运行编号",
  "mode": "traditional",
  "sample_id": "sample.ppm 或 sample.tvid",
  "task_id": "任务编号",
  "codec": "jpeg 或 h264",
  "container": "jpg 或 mp4",
  "codec_metadata": {},
  "payload_size": 0,
  "expected_total_bytes": 0
}
~~~

#### LoopbackTransport

这是当前单机实验使用的本地回环链路，不经过网卡，也不代表课题三真实无线链路。

构造参数：

~~~python
LoopbackTransport(
    chunk_size=16 * 1024,
    delay_ms=0,
    loss_rate=0,
)
~~~

字段作用：

- chunk_size：数据分块大小。
- delay_ms：每个数据块额外等待的毫秒数。
- loss_rate：每个数据块被丢弃的概率，范围为 [0, 1)。

它记录发送字节数、接收字节数、分块数量、丢失分块数量、回环耗时、平均吞吐和峰值吞吐。

当前实现没有模拟真实 SNR、BER、Wi-Fi、5G、TCP 或 UDP，只用于先完成单系统闭环和接口测试。

#### LanTcpTransport 和 LanTcpReceiver

LanTcpTransport 是两台服务器局域网测试使用的发送端适配器；LanTcpReceiver 是独立运行在接收服务器上的 TCP 服务。二者使用 semcom-traditional-tcp-v1 协议。

LanTcpTransport.send_payload() 会发送带长度前缀的 JSON 元数据和 payload，等待接收端 ACK，并把接收端是否完整接收、是否成功解码、接收端结果路径等信息写入 transport 统计。为了兼容现有 runner.py，发送端返回本地编码 payload 供发送端流程继续校验；真正的接收文件和接收端解码结果保存在 LanTcpReceiver 的运行目录中。

LanTcpReceiver 会校验 payload 长度和 SHA-256，保存 received_payload.*、output.*、decoded.* 和 receiver_result.json。健康检查消息不会计入业务连接数。

#### Task3Transport

这是接入课题三的适配器：

~~~python
transport = Task3Transport(task3_implementation)
~~~

当前要求 task3_implementation 至少具有：

~~~python
send_payload(payload: bytes, metadata: dict) -> tuple[bytes, dict]
~~~

如果课题三实现 health_check()，Task3Transport.health_check() 会转发调用；如果没有，则返回默认在线状态。

实际联调时建议逐步扩展以下方法：

~~~python
health_check(link_config)
configure_link(link_config)
send_payload(run_context, payload, metadata)
receive_payload(run_context)
close_link(run_id)
get_link_status(run_id)
get_transport_stats(run_id)
~~~

业务代码没有把 TCP 或 UDP 写死，最终协议由课题三适配器内部决定。

### 4.6 traditional_comm/runner.py

文件位置：[runner.py](../traditional_comm_py/traditional_comm/runner.py)

作用：组织一次完整运行，串联编码、传输、解码、校验、性能计算和结果写盘。

主要函数：

- create_run_id(kind)：生成独立运行编号。
- sha256(data)：计算字节 SHA-256。
- _validate(kind, output)：检查解码后的文字、PPM 或 TVID1 是否完整。
- _psnr(source_pixels, output_pixels)：按照像素均方误差计算 PSNR。
- _quality_metrics(kind, source, output)：计算图片或视频 PSNR，预留 SSIM 和 LPIPS 字段。
- run_one(...)：执行一次完整通信流程。
- run_all(...)：连续运行文字、图片和视频三种样本。

PSNR 公式：

~~~text
MSE = 所有像素差值平方的平均值
PSNR = 10 × log10(255² / MSE)
~~~

文字不计算 PSNR；图片和视频使用有损编码，不能要求输出字节与输入逐字节相同，因此使用 PSNR 评价重建质量。

run_one 的调用形式：

~~~python
run_one(
    kind,
    input_path,
    runs_dir,
    transport,
    task=None,
    run_id=None,
    codec_options=None,
)
~~~

执行顺序：

1. 读取输入文件。
2. 创建运行编号和运行目录。
3. 调用 encode_payload() 编码。
4. 调用传输适配器发送字节。
5. 保存实际接收的载荷。
6. 调用 decode_payload() 解码。
7. 校验解码结果。
8. 计算数据量、时延、吞吐、PSNR 和资源指标。
9. 写入 JSON 结果文件。
10. 返回运行编号、运行目录、指标和正式输出路径。

codec_options 示例：

~~~python
codec_options = {
    "jpeg_quality": 5,
    "h264_crf": 28,
    "h264_preset": "fast",
}
~~~

run_all 默认查找：

~~~text
samples/sample.txt
samples/sample.ppm
samples/sample.tvid
~~~

### 4.7 traditional_comm/controller.py

文件位置：[controller.py](../traditional_comm_py/traditional_comm/controller.py)

作用：给课题一 Web 页面或其他上层程序提供基础控制接口。

创建控制器：

~~~python
from pathlib import Path

from traditional_comm.controller import TraditionalCommunicationController
from traditional_comm.transport import LoopbackTransport

controller = TraditionalCommunicationController(
    Path("runs"),
    LoopbackTransport(),
)
~~~

当前已实现接口：

health_check()

检查传输适配器是否在线：

~~~python
controller.health_check()
~~~

switch_mode(mode)

切换 traditional 或 semantic 标志：

~~~python
controller.switch_mode("traditional")
~~~

注意：当前控制器只执行传统通信。虽然可以保存 semantic 模式标志，但调用 start_run() 时会拒绝执行。这是为了让传统通信和语义通信未来共用控制层，并不表示语义通信已经接入。

start_run(config)

启动一次传统通信运行：

~~~python
started = controller.start_run({
    "kind": "image",
    "input_path": "samples/sample.ppm",
    "task": {
        "task_id": "reconstruction-demo",
        "task_type": "reconstruction",
        "output_type": "reconstruction",
    },
})
~~~

必填字段：

- kind：text、image 或 video。
- input_path：输入文件路径。

可选字段：

- task：任务编号、任务类型和输出类型等。

get_status(run_id)

获取运行状态、媒体类型和输入路径：

~~~python
controller.get_status(started["run_id"])
~~~

get_performance(run_id)

读取本次运行的 metrics.json 对应内容：

~~~python
controller.get_performance(started["run_id"])
~~~

get_result(run_id)

读取 result.json，返回正式输出文件、解码文件和校验信息：

~~~python
controller.get_result(started["run_id"])
~~~

stop_run(run_id)

将控制器内存中的状态标记为 cancelled。

当前 run_one() 是同步函数，因此如果运行已经进入 FFmpeg 编码或传输阶段，stop_run() 不能真正中断正在执行的 FFmpeg 子进程。后续接入 Web 现场演示时，需要把运行任务改为后台任务，并增加可取消的进程管理。

### 4.8 traditional_comm/cli.py

文件位置：[cli.py](../traditional_comm_py/traditional_comm/cli.py)

作用：提供命令行入口，方便不用写 Python 代码就运行 Demo。

命令行支持：

- demo：生成样本并运行全部媒体类型。
- generate-samples：只生成输入样本。
- run：使用已有样本运行。

通用参数：

| 参数 | 默认值 | 作用 |
|---|---:|---|
| --samples | samples | 输入样本目录 |
| --runs | runs | 运行结果目录 |
| --chunk-size | 16384 | 回环传输分块大小 |
| --delay-ms | 0 | 每个分块的模拟延迟 |
| --loss-rate | 0 | 每个分块的模拟丢失概率 |

### 4.9 tests/test_smoke.py

文件位置：[test_smoke.py](../traditional_comm_py/tests/test_smoke.py)

作用：验证最基本的可运行性。

当前测试包括：

1. 生成文字、图片和视频样本。
2. 使用本地回环传输运行三种媒体类型。
3. 验证文字字节一致。
4. 验证 JPEG 和 MP4 可以解码。
5. 验证图片和视频能生成 PSNR。
6. 验证控制器的启动、状态、性能和结果接口。

## 5. 如何运行

### 5.1 进入项目目录

~~~powershell
Set-Location D:\workspace\SemCom\traditional_comm_py
~~~

### 5.2 生成样本并运行完整 Demo

~~~powershell
& D:\miniconda3\envs\semcom-py\python.exe -m traditional_comm.cli demo
~~~

预期输出类似：

~~~text
text: status=completed input=...B payload=...B latency=...ms content_match=True
image: status=completed input=...B payload=...B latency=...ms content_match=None
video: status=completed input=...B payload=...B latency=...ms content_match=None
Run artifacts saved in ...\traditional_comm_py\runs
~~~

图片和视频显示 content_match=None 是正常的，因为 JPEG 和 H.264 是有损编码，不能进行原始字节级完全一致比较；应查看 output_valid 和 quality.psnr。

### 5.3 分步骤运行

只生成样本：

~~~powershell
& D:\miniconda3\envs\semcom-py\python.exe -m traditional_comm.cli generate-samples
~~~

使用已有样本运行：

~~~powershell
& D:\miniconda3\envs\semcom-py\python.exe -m traditional_comm.cli run
~~~

### 5.4 模拟延迟和丢包

例如，每个分块增加 2 ms 延迟，每个分块以 1% 概率丢失：

~~~powershell
& D:\miniconda3\envs\semcom-py\python.exe -m traditional_comm.cli run --chunk-size 1024 --delay-ms 2 --loss-rate 0.01
~~~

这是本地软件模拟，不等价于真实无线信道。丢包后 JPEG/MP4 可能无法解码，程序会抛出 FFmpeg 或格式校验错误；这可以作为异常路径测试。

### 5.5 运行单元测试

~~~powershell
& D:\miniconda3\envs\semcom-py\python.exe -m unittest discover -s tests -v
~~~

预期结果：

~~~text
Ran 2 tests
OK
~~~

## 6. 如何查看结果

### 6.1 查看运行编号

~~~powershell
Get-ChildItem .\runs -Directory |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 10 Name, LastWriteTime
~~~

每个目录名就是一个 run_id，例如：

~~~text
traditional-image-1784449439773-1c2318
~~~

### 6.2 查看最新汇总

~~~powershell
Get-Content .\runs\latest_summary.json
~~~

格式化显示：

~~~powershell
Get-Content .\runs\latest_summary.json | ConvertFrom-Json | ConvertTo-Json -Depth 10
~~~

### 6.3 查看单次运行文件

~~~powershell
$run = Get-ChildItem .\runs -Directory |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1

Get-ChildItem $run.FullName
Get-Content (Join-Path $run.FullName "metrics.json")
Get-Content (Join-Path $run.FullName "transport.json")
Get-Content (Join-Path $run.FullName "result.json")
~~~

### 6.4 用 FFprobe 查看 JPG/MP4 是否是正式格式

查看图片：

~~~powershell
& D:\miniconda3\Scripts\conda.exe run -n semcom-py ffprobe -v error -show_entries format=format_name:stream=codec_name,codec_type,width,height -of json .\runs\<run_id>\output.jpg
~~~

预期可以看到 mjpeg、video、width 和 height 等字段。

查看视频：

~~~powershell
& D:\miniconda3\Scripts\conda.exe run -n semcom-py ffprobe -v error -show_entries format=format_name:stream=codec_name,codec_type,width,height,avg_frame_rate -of json .\runs\<run_id>\output.mp4
~~~

预期可以看到：

~~~json
{
  "codec_name": "h264",
  "codec_type": "video",
  "width": 160,
  "height": 90,
  "avg_frame_rate": "10/1"
}
~~~

### 6.5 运行结果文件

每个 runs/<run_id>/ 目录当前包含：

~~~text
config.json
metrics.json
transport.json
result.json
encoded_payload.*
received_payload.*
output.*
decoded.*
~~~

| 文件 | 含义 |
|---|---|
| config.json | 本次运行的输入路径、模式、任务和编码配置 |
| metrics.json | 指标汇总，适合 Web 页面或表格读取 |
| transport.json | 传输层统计 |
| result.json | 编码载荷、接收载荷、正式输出和解码结果路径 |
| encoded_payload.* | 发送端编码后的载荷 |
| received_payload.* | 接收端实际收到的载荷 |
| output.* | 正式媒体输出，图片为 .jpg，视频为 .mp4 |
| decoded.* | 用于校验和质量计算的内部解码结果 |

## 7. 性能指标说明

### 7.1 数据量指标

input_bytes：

- 编码前输入文件的字节数。
- 当前图片输入是 PPM，视频输入是 TVID1 原始帧序列，因此通常比较大。

encoded_payload_bytes：

- JPEG 或 MP4 编码结果的字节数。
- 这是当前程序建议用于比较“编码后业务载荷大小”的数据量。

actual_sent_bytes：

- 传输适配器认为实际发送的字节数。
- 当前回环实现中等于编码载荷大小。

actual_received_bytes：

- 接收端实际重组得到的字节数。
- 发生丢包时可能小于发送字节数。

actual_link_total_bytes：

- 传输适配器统计的实际链路字节总量。
- Loopback 中等于一次本地载荷量；LAN TCP 中包含数据帧和 ACK 帧的协议开销。
- 因此它与 encoded_payload_bytes 不同，比较传统和语义模式时应明确使用哪一种口径。

data_reduction_ratio 计算公式：

~~~text
(input_bytes - encoded_payload_bytes) / input_bytes
~~~

与语义通信比较时，两种模式必须使用一致的数据量统计口径。

### 7.2 时延指标

- encode_time_ms：调用 FFmpeg 或文字编码所用时间。
- transport_time_ms：传输适配器发送和接收所用时间。
- decode_time_ms：接收端解码所用时间。
- end_to_end_latency_ms：当前 Demo 中为编码耗时、传输耗时和解码耗时之和。

正式联调时，建议统一为：

~~~text
结果形成时间 - 任务启动时间
~~~

并记录任务启动、编码开始/结束、发送开始/结束、接收开始/结束、解码开始/结束和结果形成时间。

### 7.3 质量和任务指标

- quality.psnr：当前图片和视频已计算，文字为 null。
- quality.ssim、quality.lpips：字段已经预留，当前因为没有安装对应算法库而为 null。
- task.content_match：文字使用 SHA-256 做字节一致性检查；图片和视频为 null，因为有损编码后不应要求字节完全一致。
- task.output_valid：1 表示接收载荷已成功解码并通过内部格式校验，0 表示结果不可用。

### 7.4 资源指标

当前已经记录：

- Python 进程 CPU 时间。
- Python 内存跟踪当前值。
- Python 内存跟踪峰值。
- GPU 使用率字段，但当前为 null。

正式部署到 DGX Spark 或 RTX 主机时，需要增加 CPU、GPU、内存、显存、设备状态和软件版本采集。

## 8. 预留接口总览

### 8.1 内容 2 内部模块

| 逻辑模块 | 当前实现 | 主要文件 |
|---|---|---|
| 配置 | CLI 参数和函数参数 | cli.py、runner.py |
| 运行控制 | 控制器同步接口 | controller.py |
| 编解码适配 | JPEG、H.264/MP4、UTF-8 | codecs.py |
| 传输适配 | Loopback、LanTcp、Task3 包装器 | transport.py |
| 任务输出 | 当前以重建和格式校验为主 | runner.py |
| 性能指标 | JSON 指标汇总 | runner.py |
| 结果存储 | 独立运行目录和 JSON | runner.py |
| Web 查询适配 | 由控制器方法提供基础能力 | controller.py |

后续建议继续拆分独立模块：

~~~text
config/
run_control/
codec_adapter/
transport_adapter/
task_adapter/
metrics/
state_collector/
result_store/
comparison/
web_adapter/
~~~

### 8.2 运行控制接口

课题一需要的统一生命周期建议保持：

~~~python
health_check()
prepare_run(config)
start_run(context)
get_status(run_id)
cancel_run(run_id)
get_result(run_id)
get_error(run_id)
~~~

当前代码已经实现：

~~~python
health_check()
prepare_run(config)
switch_mode(mode)
start_run(config)
get_status(run_id)
get_performance(run_id)
get_result(run_id)
stop_run(run_id)
cancel_run(run_id)
get_error(run_id)
~~~

prepare_run() 会检查媒体类型、输入文件和输出目录；get_error() 返回结构化错误信息。当前 stop_run()/cancel_run() 可以更新状态，但同步运行中的 FFmpeg 进程仍需要后续后台任务机制才能真正中断。

建议统一状态：

~~~text
offline -> ready -> preparing -> running -> completing -> completed
                                             \-> failed
                                             \-> cancelled
~~~

### 8.3 课题三通信接口

内容 2 不应在业务代码中直接编写 TCP、UDP、Wi-Fi、5G 或硬件控制逻辑。推荐由课题三提供统一实现，内容 2 只调用适配器。

推荐的完整接口：

~~~python
link_health_check(link_config)
configure_link(link_config)
send_payload(run_context, payload, metadata)
receive_payload(run_context)
close_link(run_id)
get_link_status(run_id)
get_transport_stats(run_id)
~~~

至少需要返回：

- 是否发送成功。
- 接收端是否完整重组。
- 发送和接收字节数。
- 平均吞吐和峰值吞吐。
- 传输耗时。
- 丢包率、误码率和重传次数（如果课题三能够提供）。
- 实际 SNR。
- 链路错误信息。

当前 Task3Transport 是最小适配器，已能隔离业务代码与课题三实现，但完整链路状态接口仍需联调时补充。

### 8.4 任务输出接口

Word 方案允许三种输出：

~~~text
重建图片/视频
结构化语义结果
任务处理结果
~~~

当前传统通信 Demo 主要覆盖：

~~~text
常规解码 -> 保存正式媒体输出
常规解码 -> 格式校验 -> PSNR
~~~

后续接入任务模型时，建议增加：

~~~python
run_task(
    task_id,
    task_type,
    input_path,
    output_type,
    model_version,
) -> dict
~~~

返回内容应包括任务编号、任务类型、输出类型、结构化结果或结果文件、准确率/召回率/F1/mAP 或结果一致性、推理耗时和模型版本。

### 8.5 SNR 对比接口

当前 Loopback 只支持 delay_ms 和 loss_rate，没有真实 SNR。正式联调时应从配置传入 SNR 序列：

~~~yaml
snr_sweep:
  enabled: true
  values_db: []
~~~

每个 SNR 值都应分别运行传统模式和语义模式，并保持样本、任务、编码配置、节点角色、软件版本和统计口径不变。

最终生成：

- 质量随 SNR 变化的数据。
- 任务性能随 SNR 变化的数据。
- 数据量随 SNR 变化的数据。
- 端到端时延随 SNR 变化的数据。

## 9. 当前实现和正式联调之间的差距

当前代码适合内容 2 单机 Demo 和接口验证，还不是完整的现场部署系统，主要差距如下：

1. 当前输入图片默认是 PPM，视频默认是 TVID1；如果要直接读取已有 JPG/MP4，需要增加真实文件输入适配。
2. 当前默认 Demo 使用本地回环；两台服务器的 TCP 局域网适配器已经提供，真实 UDP、无线设备或课题三硬件尚未接入。
3. 当前控制器是同步运行；取消接口还不能中断正在运行的 FFmpeg。
4. 当前没有独立的 events.jsonl 生命周期事件日志。
5. 当前资源指标只记录 Python 进程和内存跟踪，尚未接入 GPU、显存和设备状态采集。
6. 当前没有任务识别模型，准确率、召回率、F1 和 mAP 尚未计算。
7. 当前没有完整的 SNR 扫描执行器和传统/语义自动对比模块。
8. 当前 Task3Transport 是最小适配器，课题三需要确定最终收发接口、链路配置和统计字段。

这些差距属于后续联调和工程化工作，不影响当前单机传统通信链路的编码、传输、解码和性能记录。

## 10. 推荐的下一步使用顺序

### 第一阶段：单机确认

1. 运行 demo。
2. 确认 output.jpg 和 output.mp4 可以被 FFprobe 识别。
3. 查看 metrics.json 中的编码载荷大小、PSNR 和时延。
4. 修改 delay_ms 和 loss_rate，观察传输统计和异常情况。

### 第二阶段：接入真实样本

1. 明确图片和视频的真实输入格式。
2. 如果输入已经是 JPG/MP4，确定是直接传输已编码文件，还是先解码为原始数据后重新编码。
3. 如果要测量编码性能，建议保留原始输入到正式编码的路径。
4. 把真实样本、校验值和样本编号写入统一配置。

### 第三阶段：接入课题三

1. 由课题三确定真实传输适配器的 Python 调用方式。
2. 用 Task3Transport 替换 LoopbackTransport。
3. 验证元数据和载荷是否能在发送端、接收端完整对应。
4. 接入真实吞吐、丢包率、误码率、重传次数和 SNR。
5. 保持 runner.py 和 metrics.json 的统一结果格式不变。

### 第四阶段：与课题一联调

1. 将 TraditionalCommunicationController 包装成 Web API 或课题一要求的接口形式。
2. 增加 prepare_run()、结构化错误和后台任务取消。
3. 提供运行状态、节点状态、链路状态和结果查询。
4. 使用相同的 run_id、sample_id、task_id 和链路条件，与语义通信结果并列展示。

## 11. 两台服务器局域网 TCP 测试

当前已经提供 LanTcpTransport 和 LanTcpReceiver。它们位于 transport.py 中，使用统一的 TransportAdapter 接口，不会让 runner.py 直接依赖 TCP。

### 11.1 两端角色

服务器 A 是发送端：

```text
读取样本 -> JPEG/H.264/MP4 编码 -> TCP 发送 -> 等待接收端确认
```

服务器 B 是接收端：

```text
TCP 监听 -> 接收完整 payload -> 校验长度和 SHA-256
         -> 保存 received_payload.* 和 output.*
         -> 解码 -> 保存 decoded.* 和 receiver_result.json
```

发送端仍然会保存自己的运行目录；接收端也会按照相同 run_id 保存一份接收结果，因此两端可以通过 run_id 关联。

### 11.2 启动接收端

在服务器 B 上执行：

```powershell
Set-Location D:\workspace\SemCom\traditional_comm_py
& D:\miniconda3\envs\semcom-py\python.exe -m traditional_comm.cli tcp-receive --bind 0.0.0.0 --port 5000 --output D:\workspace\SemCom\traditional_comm_py\runs_receiver
```

参数含义：

- bind：接收端监听地址。服务器上通常使用 0.0.0.0。
- port：监听端口，默认 5000。
- output：接收端结果目录。
- max-connections：业务载荷数量，默认 1；健康检查连接不计入该数量。

如果需要持续接收多个任务：

```powershell
& D:\miniconda3\envs\semcom-py\python.exe -m traditional_comm.cli tcp-receive --bind 0.0.0.0 --port 5000 --output runs_receiver --max-connections 0
```

持续监听时使用 Ctrl+C 停止服务。

### 11.3 启动发送端

在服务器 A 上执行，下面以图片为例：

```powershell
Set-Location D:\workspace\SemCom\traditional_comm_py
& D:\miniconda3\envs\semcom-py\python.exe -m traditional_comm.cli tcp-send --host 192.168.1.20 --port 5000 --kind image --input samples\sample.ppm --runs runs_sender
```

将 192.168.1.20 替换为服务器 B 的局域网 IP。

视频发送：

```powershell
& D:\miniconda3\envs\semcom-py\python.exe -m traditional_comm.cli tcp-send --host 192.168.1.20 --port 5000 --kind video --input samples\sample.tvid --runs runs_sender
```

发送端支持编码参数：

```powershell
--jpeg-quality 3 --h264-crf 23 --h264-preset ultrafast
```

### 11.4 TCP 帧格式

TCP 是字节流，没有天然的消息边界。因此程序没有直接假设一次 recv 就能收到完整文件，而是使用如下帧格式：

```text
4 字节无符号整数：JSON 头部长度，网络字节序
JSON 头部：run_id、媒体类型、编码格式、载荷长度、序号和 SHA-256
payload：JPEG、MP4 或文字字节
```

发送元数据示例：

```json
{
  "protocol": "semcom-traditional-tcp-v1",
  "message_type": "payload",
  "run_id": "traditional-image-...",
  "media_type": "image",
  "codec": "jpeg",
  "container": "jpg",
  "payload_size": 3449,
  "expected_total_bytes": 3449,
  "sequence_id": 0,
  "sha256": "..."
}
```

接收端会检查协议名、消息类型、载荷长度和 SHA-256；检查失败时返回结构化错误确认。

### 11.5 两端结果

发送端目录：

```text
runs_sender/<run_id>/
  config.json
  metrics.json
  transport.json
  result.json
  encoded_payload.jpg 或 encoded_payload.mp4
  received_payload.jpg 或 received_payload.mp4
  output.jpg 或 output.mp4
  decoded.ppm 或 decoded.tvid
```

接收端目录：

```text
runs_receiver/<run_id>/
  received_payload.jpg 或 received_payload.mp4
  output.jpg 或 output.mp4
  decoded.ppm 或 decoded.tvid
  receiver_result.json
```

接收端的 receiver_result.json 重点查看：

- received_bytes
- sha256
- receiver_decode_valid
- receiver_decode_time_ms
- received_path
- decoded_path

### 11.6 局域网排查顺序

1. 在接收端确认 FFmpeg 和 Python 环境可用。
2. 确认接收端服务显示正在监听目标端口。
3. 在发送端确认目标 IP 正确。
4. 检查 Windows/Linux 防火墙是否允许 TCP 5000 入站。
5. 先发送文字，再发送图片，最后发送视频。
6. 对比两端相同 run_id 的 received_bytes 和 SHA-256。
7. 使用 FFprobe 检查接收端 output.jpg 或 output.mp4。
8. 如果传输成功但解码失败，优先检查两端 FFmpeg 版本、codec_metadata 和文件是否被截断。

### 11.7 当前 TCP 方案的边界

- TCP 版本用于验证两台服务器之间的可靠字节传输，不等价于课题三真实无线链路。
- 当前不模拟 SNR、BER、丢包和重传；TCP 的重传由操作系统负责。
- 当前接收端会解码并保存结果，但任务模型、资源采集和 Web API 尚未接入。
- 后续如果需要显式研究丢包和乱序，应新增 UDP 适配器，不应把 UDP 逻辑写入 runner.py 或 codecs.py。
