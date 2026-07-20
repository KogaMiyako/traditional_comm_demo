# CIFAR-10 与 MOSEI 训练/推理说明

## 运行环境

项目使用已有的 `BasicTS` Conda 环境：

```bash
conda activate BasicTS
```

MMSA 额外依赖已经安装到该环境：`pytorch-transformers` 和 `nvidia-ml-py3`。

当前配置使用 CUDA。执行前可确认 GPU：

```bash
nvidia-smi
```

## 配置

所有数据路径、模型参数、checkpoint、日志和指标路径集中在：

```text
traditional_comm_py/config/default.json
```

当前关键配置：

- CIFAR-10 数据：`data/cifar/`
- MOSEI 原始上传数据：`data/MOSEI/{train,dev,test}.pkl`
- MMSA 转换特征：`data/MOSEI/mmsa_features.pkl`
- CIFAR checkpoint：`artifacts/checkpoints/resnet18-cifar10-v1.pt`
- MOSEI checkpoint：`artifacts/checkpoints/mmsa-mosei-v1.pt`
- 两个训练设备：`cuda`

上传的 MOSEI 文件是旧版 MISA 列表格式。`train_video_sentiment.py` 会在本地首次运行时转换为 MMSA 字典格式，不重新下载数据；转换后的音频/视觉特征和标签保持原样，token id 使用配置中的确定性紧凑投影生成 LF-DNN 可用的文本特征。

## 训练

```bash
python train_image.py
python train_video_sentiment.py
```

训练会生成：

- `artifacts/checkpoints/`：模型 checkpoint，含 state dict、模型版本、训练配置和环境信息
- `artifacts/logs/`：训练日志
- `artifacts/metrics/`：测试指标
- `artifacts/metadata/`：类别列表和环境信息
- `artifacts/samples/`、`data/MOSEI/sample_test.pkl`：验证用样本

## 独立推理接口

程序从 stdin 读取一个 JSON，只向 stdout 输出一个 JSON；日志和诊断信息输出到 stderr。推理脚本位于项目根目录的 `traditional_comm_py/`，训练目录下只保留训练脚本和模型资产。

图像：

```bash
cd ../traditional_comm_py
printf '%s\n' '{"task_type":"image_classification","semantic_task":"imgc","dataset":"cifar10","input_path":"imagec_and_MMSA/artifacts/samples/cifar10_sample.png","reference_path":"imagec_and_MMSA/data/cifar/test_batch","task_config":{"model":{"name":"resnet18","version":"resnet18-cifar10-v1","checkpoint":"imagec_and_MMSA/artifacts/checkpoints/resnet18-cifar10-v1.pt","source_root":"imagec_and_MMSA"},"metrics":["accuracy","f1","top1","top5"]},"task_context":{}}' | python image_infer.py
```

视频情感：

```bash
cd ../traditional_comm_py
printf '%s\n' '{"task_type":"video_sentiment","semantic_task":"msa","dataset":"mosei","input_path":"imagec_and_MMSA/data/MOSEI/sample_test.pkl","reference_path":"imagec_and_MMSA/data/MOSEI/test.pkl","task_config":{"model":{"name":"lf_dnn","version":"mmsa-mosei-v1","checkpoint":"imagec_and_MMSA/artifacts/checkpoints/mmsa-mosei-v1.pt","mmsa_source":"imagec_and_MMSA/MMSA"},"label_type":"regression","metrics":["mae","correlation","accuracy","f1"]},"task_context":{}}' | python video_sentiment_infer.py
```

图像输入可以是单张图片；视频输入可以是 MMSA 完整 `.pkl` 或单样本 `.pkl/.npz`。完整数据文件默认读取 `test` split 的第 0 条样本，也可以在 `task_context` 中传入 `split` 和 `sample_index`。

## 通信程序和 result.json

主项目的 `traditional_comm` 任务适配器从配置中选择对应的 `command`，调用推理程序，并将结果写入运行目录：

```text
runs/<run_id>/result.json
```

示例：

```bash
python -m traditional_comm.cli task-infer --kind video --input imagec_and_MMSA/data/MOSEI/sample_test.pkl --task-type video_sentiment
```

最终 `result.json` 包含 `prediction`、`metrics`、`model_version`、`checkpoint` 和 `inference_time_ms`。图像推理没有真实标签时，`top1/top5` 为 `null`；在 `task_context.ground_truth_label` 中提供标签即可计算单样本指标。MOSEI 单样本的 correlation 不可定义时写为 JSON `null`，不会输出非法 `NaN`。

## 已验证产物

- `artifacts/checkpoints/resnet18-cifar10-v1.pt`
- `artifacts/checkpoints/mmsa-mosei-v1.pt`
- `artifacts/results/result.json`
- `artifacts/results/image_result.json`
- `artifacts/metrics/cifar10_test.json`
- `artifacts/metrics/mosei_test.json`
