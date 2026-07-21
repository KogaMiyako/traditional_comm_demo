# 传统通信内容 2 Demo

这是一个面向语义通信下游任务的 Python 传统通信基线。项目把“媒体编码/传输/解码”和“解码后的任务推理”拆开，支持在同一台机器上验证完整链路，也支持用两个本地 TCP 端口模拟发送端和接收端。

## 一句话介绍

同一份内容经过传统媒体编码和通信链路传输，在接收端恢复后执行图像分类、视频情感分析或重建任务，并统一记录数据量、时延、吞吐、质量和任务指标，为后续与语义通信方案做对比提供基线。

## 当前功能

| 任务            | 输入                   | 传统通信链路                           | 解码/接收后的处理                  |
| ------------- | -------------------- | -------------------------------- | -------------------------- |
| 文本重建          | UTF-8 文本             | UTF-8 字节分块传输                     | 内容一致性校验                    |
| 图像重建          | PPM 原始 RGB 样本        | JPEG 编码、分块传输、解码                  | PSNR、SSIM 等重建指标            |
| CIFAR-10 图像分类 | CIFAR-10 样本或图片       | CIFAR-10 → PPM → JPEG → 传输 → PPM | ResNet18 分类，输出类别和置信度       |
| 视频重建          | TVID1 原始帧样本          | H.264/MP4 编码、传输、解码               | 视频可解码性和重建指标                |
| MOSEI 情感分析    | 预计算 `.pkl`/`.npz` 特征 | 特征级推理；双端演示使用独立特征 TCP 协议          | MMSA LF-DNN 回归，输出情感分数和正负标签 |

其中，MOSEI 当前模型输入是文本、音频和视觉的预计算特征，不是 MP4。项目不会把 `.pkl` 特征伪装成视频送入 H.264 编解码器；如果未来接入原始 MP4，需要另行增加音视频解码和特征提取模块。

## 通信过程

### 普通媒体任务

```text
输入样本
   │
   ├─ CIFAR-10 样本选择 / 文件读取
   ▼
传统编码器
   ├─ 文本：UTF-8 字节
   ├─ 图片：JPEG
   └─ 视频：H.264 + MP4
   ▼
分块与传输
   ├─ LoopbackTransport：同一进程内存模拟
   └─ LanTcpTransport：发送端与接收端通过 TCP socket 通信
   ▼
接收端重组 → 解码
   ▼
任务适配器
   ├─ 内置重建：保存解码结果并计算质量指标
   └─ 外部任务：通过 stdin/stdout JSON 调用推理脚本
   ▼
运行目录：config.json、metrics.json、result.json
```

### MOSEI 特征任务

```text
MOSEI 预计算特征文件
   ├─ 本地 task-infer：直接调用 video_sentiment_infer.py
   └─ 双端演示：特征文件字节 → mosei-feature-tcp-v1 → 接收端保存并推理
   ▼
MMSA LF-DNN
   ▼
sentiment_score、positive/negative、MAE、correlation、accuracy、F1
```

### 两种通信模式

| 模式     | 入口                                         | 适合说明                                       |
| ------ | ------------------------------------------ | ------------------------------------------ |
| 本地回环   | `task-run`                                 | 快速验证编码、分块、解码和任务推理的完整链路；不创建 TCP socket      |
| 本地模拟双端 | `tcp-receive` + `tcp-send`，或 `demo_all.py` | 在同一台机器上用不同端口模拟发送端/接收端，观察真实 socket 传输和接收端结果 |

`demo_all.py` 会使用图像端口和 MOSEI 特征端口两个不同端口；单独实验时可以只运行一个任务，不需要启动全部 Demo。

## 项目结构

```text
KogaMiyako_traditional_comm_demo/
├── README.md                         # 项目概览和会议介绍
├── traditional_comm_py/              # Python 通信主程序
│   ├── traditional_comm/             # CLI、编解码、传输、任务适配器
│   ├── image_infer.py                # CIFAR-10 外部推理接口
│   ├── video_sentiment_infer.py      # MOSEI 外部推理接口
│   ├── demo_all.py                   # 全功能演示脚本
│   ├── config/default.json            # 数据、模型、命令和通信参数
│   └── runs/                         # 所有实验运行结果
├── imagec_and_MMSA/                  # 训练代码、外部源码、数据和 checkpoint
│   ├── train_image.py
│   ├── train_video_sentiment.py
│   └── artifacts/                    # 日志、指标、模型和环境信息
├── dataset -> ../data                # 已上传数据的链接
└── doc/                              # 运行、实验、训练和接口文档
```

Python 通信实现位于 `traditional_comm_py/`。`traditional_comm_py/traditional_comm/` 是当前使用的 Python 包；项目不再保留旧的 Node.js 版本目录。

## 运行结果

每个实验使用独立的运行目录，例如：

```text
traditional_comm_py/runs/<experiment>/<run_id>/
├── config.json              # 输入、任务、编码和传输配置
├── metrics.json             # 数据量、时延、吞吐、质量和资源指标
├── transport.json           # 传输层统计
├── result.json              # 输出路径、校验信息和任务结果
├── encoded_payload.*        # 编码后的发送载荷
├── received_payload.*       # 实际接收载荷
├── output.*                 # 解码后的正式媒体文件
└── decoded.*                # 用于质量计算的解码内容
```

任务结果统一包含以下核心字段：

```json
{
  "success": true,
  "prediction": {},
  "metrics": {},
  "model_version": "model-version",
  "checkpoint": "checkpoint-path",
  "inference_time_ms": 12.3,
  "error": null
}
```

图像分类的 `prediction` 是类别、类别名称、置信度和 `top_k`；MOSEI 的 `prediction` 是情感分数和正负标签。通信层的指标和下游任务指标分别保存在 `metrics.json` 的链路字段和 `task.task_result` 中。

## 相关文档

* [传统通信任务运行说明](doc/传统通信任务运行说明.md)：整体运行方式、回环/TCP 双端区别、结果和指标解释。

* [传统通信实验命令清单](doc/传统通信实验命令清单.md)：按实验拆分的可复制命令及全部 `--参数` 说明。

* [CIFAR-10 与 MOSEI 训练推理说明](doc/CIFAR-10与MOSEI训练推理说明.md)：训练环境、checkpoint、独立推理接口和验证产物。

* [内容 2 图像分类与 MOSEI 视频情感任务对接说明](doc/内容2图像分类与MOSEI视频情感任务对接说明.md)：任务接口契约、字段映射和扩展边界。

* [Python 通信程序 README](traditional_comm_py/README.md)：Python CLI、配置和基础开发说明。

## 快速入口

进入 Python 通信目录：

```bash
cd traditional_comm_py
```

运行完整演示：

```bash
python demo_all.py
```

只运行一个本地回环任务、一个 TCP 双端任务或一个 MOSEI 特征推理任务，请参考[实验命令清单](doc/传统通信实验命令清单.md)，不需要一次性启动全部演示。
