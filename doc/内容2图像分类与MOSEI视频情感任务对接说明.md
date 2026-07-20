# 内容2：图像分类与 MOSEI 视频情感任务对接说明

## 已接入的模型

模型代码和 checkpoint 位于 `imagec_and_MMSA/`：

```text
imagec_and_MMSA/
  image_infer.py
  video_sentiment_infer.py
  pytorch-cifar/
  MMSA/
  artifacts/checkpoints/resnet18-cifar10-v1.pt
  artifacts/checkpoints/mmsa-mosei-v1.pt
```

主项目配置位于：

```text
traditional_comm_py/config/default.json
```

主项目通过配置调用两个外部推理程序，不把模型代码和传统通信代码耦合在一起。

## 两种运行方式

### 图像分类：完整传统通信链路

CIFAR-10 样本会经过：

```text
CIFAR-10 -> PPM -> JPEG 编码 -> 本地传输模拟 -> JPEG 解码 -> ResNet-18 分类 -> result.json
```

在 `traditional_comm_py` 目录下运行：

```powershell
& D:\miniconda3\envs\semcom-py\python.exe -m traditional_comm.cli task-run `
  --config .\config\default.json `
  --kind image `
  --dataset cifar10 `
  --task-type image_classification `
  --sample-mode index `
  --sample-index 0
```

结果目录为：

```text
traditional_comm_py/runs/<run_id>/
  config.json
  metrics.json
  result.json
  encoded_payload.jpg
  decoded.ppm
```

### MOSEI 情感分析：特征级任务推理

当前 MMSA 模型输入是 MOSEI 的文本、音频和视觉特征，不是 MP4 文件。因此不能把 `.pkl` 特征文件强行放入 H.264/MP4 编解码链路。

项目新增 `task-infer` 命令，直接对已经准备好的 MOSEI 特征样本推理：

```powershell
& D:\miniconda3\envs\semcom-py\python.exe -m traditional_comm.cli task-infer `
  --config .\config\default.json `
  --kind video `
  --input ..\imagec_and_MMSA\data\MOSEI\sample_test.pkl `
  --task-type video_sentiment `
  --split test `
  --sample-index 0
```

结果同样保存到：

```text
traditional_comm_py/runs/<run_id>/
  config.json
  metrics.json
  result.json
```

如果使用完整 MMSA 特征文件，也可以将输入替换为：

```text
..\imagec_and_MMSA\data\MOSEI\mmsa_features.pkl
```

如果后续要求传输真实 MP4，需要另外增加：

```text
MP4 解码 -> 文本/音频/视觉特征提取 -> MMSA 推理
```

这不是当前已训练模型的输入接口。

## 外部推理接口

两个推理程序都通过标准输入接收一个 JSON 对象，并通过标准输出返回一个 JSON 对象。

图像分类输入的关键字段：

```json
{
  "task_type": "image_classification",
  "semantic_task": "imgc",
  "dataset": "cifar10",
  "input_path": "decoded.ppm",
  "task_config": {
    "model": {
      "checkpoint": "artifacts/checkpoints/resnet18-cifar10-v1.pt"
    }
  },
  "task_context": {
    "label": 3
  }
}
```

视频情感输入的关键字段：

```json
{
  "task_type": "video_sentiment",
  "semantic_task": "msa",
  "dataset": "mosei",
  "input_path": "sample_test.pkl",
  "task_config": {
    "model": {
      "checkpoint": "artifacts/checkpoints/mmsa-mosei-v1.pt"
    }
  },
  "task_context": {
    "split": "test",
    "sample_index": 0
  }
}
```

输出统一包含：

```json
{
  "success": true,
  "prediction": {},
  "metrics": {},
  "model_version": "model-version",
  "checkpoint": "checkpoint-path",
  "error": null
}
```

图像分类的 `prediction` 包含 `label`、`label_name`、`confidence` 和 `top_k`；视频情感分析的 `prediction` 包含 `sentiment_score` 和 `label`。

## 本次验证结果

主项目接口级测试已通过：

```text
Ran 7 tests
OK
```

已验证内容包括：

- 外部任务 JSON 输入输出协议；
- `command_cwd` 能够定位到 `imagec_and_MMSA`；
- 任务结果能够写入独立 `runs/<run_id>/result.json`；
- CIFAR-10 读取、随机抽样和传统通信回环；
- TCP 传输回环；
- 图像分类和视频情感任务配置映射。

本机 `semcom-py` 环境当前没有安装 PyTorch、Torchvision 和 Pillow，因此本机只能完成接口级测试，不能重新加载 `.pt` checkpoint 做真实推理。服务器上应使用训练模型所在的 Python/Conda 环境运行上述命令。

项目中已有的模型测试记录位于：

```text
imagec_and_MMSA/artifacts/metrics/cifar10_test.json
imagec_and_MMSA/artifacts/metrics/mosei_test.json
imagec_and_MMSA/artifacts/results/image_result.json
imagec_and_MMSA/artifacts/results/result.json
```
