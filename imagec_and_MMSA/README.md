# 下游模型工作区

这个目录保存内容2下游任务的训练脚本、外部模型源码和本地模型资产：

```text
train_image.py             # 图像分类训练
train_video_sentiment.py   # MOSEI 训练
traditional_comm_py/       # 模型工作区的本地配置和运行工具
```

以下内容是本地训练依赖，不提交到 Git：

```text
MMSA/                      # 外部 MMSA 源码
pytorch-cifar/             # 外部 CIFAR-10 源码
data/                      # CIFAR-10 和 MOSEI 数据
artifacts/checkpoints/     # 模型 checkpoint
artifacts/logs/            # 训练日志
```

服务器上需要将上述依赖放回对应路径。训练和推理命令见：

- `../doc/CIFAR-10与MOSEI训练推理说明.md`
- `../doc/内容2图像分类与MOSEI视频情感任务对接说明.md`

推理脚本现在位于主项目的 `traditional_comm_py/image_infer.py` 和
`traditional_comm_py/video_sentiment_infer.py`。本目录只提供训练依赖、数据和 checkpoint；主项目通过 `traditional_comm_py/config/default.json` 调用推理脚本。
