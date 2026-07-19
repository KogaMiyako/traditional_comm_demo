# 传统通信本地基线

这是“内容2：传统通信模型搭建”的第一版单系统可运行基线，用于本地模拟测试。

## 当前实现

本项目不依赖第三方 npm 包，使用 Node.js 内置模块完成：

- 文字：UTF-8 字节传输
- 图像：标准 PPM 图像 + Deflate 无损压缩
- 视频：自描述 `TVID1` 帧序列 + Deflate 无损压缩
- 传输：本地 Loopback 传输适配器，支持分块、延时和丢包参数
- 记录：运行编号、输入/载荷字节数、吞吐、阶段时延、数据量降幅、资源采样和结果校验

当前环境没有 FFmpeg，因此没有把 H.264/MP4 作为本地默认依赖。编码器和传输层已经通过模块边界隔离，后续可替换为 FFmpeg H.264/AV1 适配器和课题三的链路适配器。

## 运行方式

进入本目录：

```powershell
cd traditional_comm
npm test
npm run demo
```

`npm run demo` 会生成：

```text
samples/sample.txt
samples/sample.ppm
samples/sample.tvid
```

并分别运行文字、图像、视频三种本地传统通信测试。每次运行的结果保存在：

```text
runs/<run_id>/
```

每个运行目录包含：

- `config.json`
- `metrics.json`
- `transport.json`
- `result.json`
- `encoded_payload.bin`
- `output.txt`、`output.ppm` 或 `output.tvid`

## 常用参数

```powershell
npm run demo -- --chunk-size=128 --delay-ms=1
node src/cli.js run --samples=./samples --runs=./runs
```

## 后续接入点

### 替换为 FFmpeg 编码

保留 `src/codecs.js` 的统一调用形式，新增 JPEG/H.264/AV1 编解码器即可；业务运行器不应直接调用具体编码命令。

### 替换为课题三链路

实现一个符合 `TransportAdapter` 约定的适配器，并替换 `LoopbackTransport`。业务代码继续只调用：

```text
healthCheck()
sendPayload(payload, metadata)
```

传输适配器需要返回发送字节数、接收字节数、吞吐、耗时、SNR、丢包/误码等课题三可提供的统计。

## 当前边界

- 这是单机 smoke test，不代表双设备链路已经联调完成。
- `gpu_usage` 在本地 Node 测试中记录为 `null`，接入设备采集后再填充。
- PPM/TVID 是无第三方依赖的本地测试格式；正式 Demo 可替换为 Word 方案中的 JPEG、H.264 或其他双方确认的编码格式。
