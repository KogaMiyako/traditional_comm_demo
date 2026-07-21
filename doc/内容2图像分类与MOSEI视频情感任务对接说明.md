# 内容 2：下游任务接口对接说明

本文只说明传统通信程序与图像分类、MOSEI 视频情感分析之间的接口边界、字段契约和扩展方式。训练方法、具体实验命令、通信模式和指标解释分别见项目的其他文档，不在这里重复。

## 1. 对接原则

传统通信主程序不直接导入 CIFAR 或 MMSA 模型，而是在解码完成后，通过配置调用独立推理程序：

```text
traditional_comm/runner.py
        │
        ▼
traditional_comm/task_adapter.py
        │ 读取 tasks.<task_type> 配置
        │ 组装 stdin JSON
        │ 调用 command
        ▼
image_infer.py              video_sentiment_infer.py
        │ stdout 仅返回一个 JSON 对象
        ▼
task_result 写入 metrics.json 和 result.json
```

这样做有三个好处：

- 通信链路和下游模型解耦，模型可以独立训练、替换和升级；
- 推理程序可以由其他团队用不同语言实现，只要遵守 stdin/stdout JSON 协议；
- 任务失败也能返回合法 JSON，不会破坏通信程序的结果文件。

## 2. 接口位置和配置入口

| 内容 | 文件 | 责任 |
| --- | --- | --- |
| 任务适配器 | `traditional_comm_py/traditional_comm/task_adapter.py` | 把通信任务转换为外部推理请求，并接收推理结果 |
| 图像推理接口 | `traditional_comm_py/image_infer.py` | 加载 ResNet18 checkpoint，返回 CIFAR-10 分类结果 |
| 视频推理接口 | `traditional_comm_py/video_sentiment_infer.py` | 加载 MMSA LF-DNN checkpoint，返回 MOSEI 情感结果 |
| 任务配置 | `traditional_comm_py/config/default.json` | 配置 task type、command、工作目录、模型版本、checkpoint 和指标 |
| 训练资产 | `imagec_and_MMSA/` | 保存训练脚本、数据、MMSA/CIFAR 依赖和 checkpoint |

当前配置中的两个任务入口为：

```json
{
  "image_classification": {
    "semantic_task": "imgc",
    "command": ["python", "image_infer.py"],
    "command_cwd": ".."
  },
  "video_sentiment": {
    "semantic_task": "msa",
    "command": ["python", "video_sentiment_infer.py"],
    "command_cwd": ".."
  }
}
```

`command_cwd` 相对于配置文件所在目录解析。当前配置文件位于 `traditional_comm_py/config/`，因此 `".."` 指向 `traditional_comm_py/`，两个脚本不需要写死绝对路径。

## 3. 外部推理程序通用契约

### 3.1 输入

程序从 stdin 读取一个 JSON 对象。通信适配器发送的公共结构如下：

```json
{
  "task_type": "image_classification",
  "semantic_task": "imgc",
  "dataset": "cifar10",
  "input_path": "/absolute/path/to/decoded.ppm",
  "reference_path": "/absolute/path/to/original-input",
  "task_config": {},
  "task_context": {}
}
```

字段含义：

| 字段 | 必需 | 含义 |
| --- | --- | --- |
| `task_type` | 是 | 任务名称，如 `image_classification` 或 `video_sentiment` |
| `semantic_task` | 是 | 语义任务标识，图像分类为 `imgc`，MOSEI 为 `msa` |
| `dataset` | 否 | 数据集名称，当前分别为 `cifar10`、`mosei` |
| `input_path` | 是 | 本次推理实际读取的文件。通信任务中通常是解码后的文件 |
| `reference_path` | 否 | 原始输入路径，用于追溯或计算参考指标，模型通常不直接读取 |
| `task_config` | 是 | 合并后的任务配置，包含模型、checkpoint 和指标等信息 |
| `task_context` | 否 | 样本标签、split、sample index、task id 等上下文 |

`input_path` 和 `reference_path` 由适配器转换为绝对路径；外部程序不应依赖调用进程的当前目录。直接单独调用推理程序时，也应使用项目内可解析的路径或绝对路径。

### 3.2 输出

程序只向 stdout 输出一个 JSON 对象，日志、警告和诊断信息必须输出到 stderr：

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

成功时：

- `success` 为 `true`；
- `prediction` 保存任务预测；
- `metrics` 保存可计算的任务指标；
- `model_version` 和 `checkpoint` 用于结果追溯；
- `error` 必须为 `null`。

失败时仍必须返回 JSON：

```json
{
  "success": false,
  "prediction": null,
  "metrics": {},
  "model_version": "model-version",
  "checkpoint": "checkpoint-path",
  "inference_time_ms": 3.1,
  "error": "具体错误信息"
}
```

不要把日志、进度条、Python traceback 或其他文本写入 stdout，否则适配器无法解析结果。

## 4. 图像分类接口

### 4.1 任务约定

```text
task_type:    image_classification
semantic_task: imgc
dataset:      cifar10
input_type:   decoded_image
output_type:  structured
```

完整传统通信任务中，`input_path` 是 JPEG 解码后的 `decoded.ppm`；独立推理时也可以传入 Pillow 能读取的单张图片。推理程序把输入转换为 RGB、缩放到 32×32，并使用 checkpoint 中的归一化参数。

### 4.2 任务配置

```json
{
  "task_config": {
    "model": {
      "name": "resnet18",
      "version": "resnet18-cifar10-v1",
      "checkpoint": "imagec_and_MMSA/artifacts/checkpoints/resnet18-cifar10-v1.pt",
      "source_root": "imagec_and_MMSA"
    },
    "metrics": ["accuracy", "f1", "top1", "top5"]
  }
}
```

`source_root` 用于定位 `pytorch-cifar/models/resnet.py`，也使用相对项目根目录的路径。替换模型时，至少需要同步替换模型加载逻辑、checkpoint、类别列表和输入预处理。

### 4.3 结果约定

```json
{
  "success": true,
  "prediction": {
    "label": 3,
    "label_name": "cat",
    "confidence": 0.91,
    "top_k": [
      {"label": 3, "label_name": "cat", "confidence": 0.91}
    ]
  },
  "metrics": {
    "top1": null,
    "top5": null
  },
  "model_version": "resnet18-cifar10-v1",
  "checkpoint": "imagec_and_MMSA/artifacts/checkpoints/resnet18-cifar10-v1.pt",
  "inference_time_ms": 12.3,
  "error": null
}
```

如果 `task_context` 中存在 `ground_truth_label` 或 `label`，程序计算单样本 `top1` 和 `top5`；没有真实标签时，这两个字段为 JSON `null`，不代表推理失败。

## 5. MOSEI 情感分析接口

### 5.1 任务约定

```text
task_type:    video_sentiment
semantic_task: msa
dataset:      mosei
label_type:   regression
input_type:   mosei_features
```

当前输入是预计算的多模态特征：

```text
text   -> [sequence_length, text_dim]
audio  -> [sequence_length, audio_dim]
vision -> [sequence_length, vision_dim]
label  -> 可选回归分数
```

文件可以是包含 `train`、`valid`、`test` 分片的完整 `.pkl`，也可以是单样本 `.pkl`/`.npz`。完整文件通过 `task_context.split` 和 `task_context.sample_index` 选择样本，默认是 `test` 的第 0 个样本。

### 5.2 任务配置

```json
{
  "task_config": {
    "model": {
      "name": "lf_dnn",
      "version": "mmsa-mosei-v1",
      "checkpoint": "imagec_and_MMSA/artifacts/checkpoints/mmsa-mosei-v1.pt",
      "mmsa_source": "imagec_and_MMSA/MMSA"
    },
    "label_type": "regression",
    "metrics": ["mae", "correlation", "accuracy", "f1"]
  },
  "task_context": {
    "split": "test",
    "sample_index": 0
  }
}
```

`mmsa_source` 用于定位 MMSA 源码。若替换为其他情感模型，外部程序只要继续接受同一输入协议并返回同一输出协议，通信主程序无需修改。

### 5.3 结果约定

```json
{
  "success": true,
  "prediction": {
    "sentiment_score": 0.72,
    "label": "positive"
  },
  "metrics": {
    "mae": 0.18,
    "correlation": 0.81,
    "accuracy": 0.84,
    "f1": 0.81
  },
  "model_version": "mmsa-mosei-v1",
  "checkpoint": "imagec_and_MMSA/artifacts/checkpoints/mmsa-mosei-v1.pt",
  "inference_time_ms": 45.2,
  "error": null
}
```

当输入带真实分数，`task_context.ground_truth_score` 或样本自身的 `label` 会用于计算单样本 MAE、符号 accuracy 和 F1；单个样本无法定义 correlation，因此该字段为 `null` 是正常情况。完整测试集的指标由训练/评估程序写入模型指标文件，不应把单样本结果当作总体测试集结果。

## 6. 任务适配器的保留接口

核心接口由 `TaskAdapter` 协议定义：

```python
class TaskAdapter(Protocol):
    def run(
        self,
        kind,
        source_path,
        decoded_path,
        source_bytes,
        decoded_bytes,
        task,
        quality,
    ) -> dict:
        ...
```

新增下游任务时，建议按以下步骤扩展：

1. 在 `config/default.json` 的 `tasks` 下增加任务配置；
2. 指定 `semantic_task`、`input_type`、`output_type`、`backend`、`command` 和模型信息；
3. 新建独立推理程序，遵守 stdin/stdout JSON 契约；
4. 在 `task_adapter.py` 中把该任务加入外部任务集合，或实现新的 `TaskAdapter`；
5. 为成功、失败、无标签和非法 JSON 等情况增加接口测试。

任务代码不应把 Python 解释器绝对路径、数据集绝对路径或 checkpoint 绝对路径写死在业务代码中。命令、工作目录和模型路径统一放入配置；必要的单次覆盖通过输入 JSON 的 `task_config` 传入。

## 7. 与通信层的边界

通信层只负责：

- 读取原始输入并编码；
- 分块、传输和接收重组；
- 解码并生成 `decoded_path`；
- 调用任务适配器；
- 将链路指标和任务结果保存到运行目录。

任务推理程序负责：

- 加载模型和 checkpoint；
- 读取 `input_path`；
- 生成 `prediction` 和任务 `metrics`；
- 返回模型版本、checkpoint、推理耗时和错误信息。

因此，图像分类的完整链路是“媒体解码后分类”，而 MOSEI 特征任务可以使用 `task-infer` 直接推理，或者由 `demo_all.py` 通过 `mosei-feature-tcp-v1` 将特征文件传到接收端后再推理。后者不是 H.264 视频传输。

## 8. 相关文档

- [项目 README](../README.md)：项目定位、通信流程、目录和会议介绍。
- [传统通信任务运行说明](传统通信任务运行说明.md)：完整运行模式和结果解释。
- [传统通信实验命令清单](传统通信实验命令清单.md)：逐个实验的命令和参数。
- [CIFAR-10 与 MOSEI 训练推理说明](CIFAR-10与MOSEI训练推理说明.md)：训练与独立推理流程。
