# OCR 选型调研（截至 2026-10-18）

> 注：本报告写于改造前。`feat/rapidocr-ppocrv6` 分支已按第 4 节把 OCR 切到
> **RapidOCR 3.10 + PP-OCRv6 small（ONNX Runtime）**；下面“现用/当前”均指改造前的 main。

> 目标场景：炉石盒子推荐面板截图、中文 + 数字、固定字体、CPU 推理、离线、需要打进单文件 exe。
> 结论只针对这个场景；文档扫描、表格/公式解析不在同一评价体系里。

## 一、结论

1. **改造前用的不是最好的。** 改造前是 `paddleocr 2.10.0 + paddlepaddle 2.6.2` 的 **PP-OCRv4 mobile**（det 4.5 MB、rec 10.3 MB），2022 年的模型；之后官方已经发布 PP-OCRv5（2025）和 PP-OCRv6（2026-06），当时落后两代。
2. **离线 CPU 可落地的最优解在 PP-OCRv6 家族里：**
   - 准确率最高：**PP-OCRv6 medium**（综合 83.2%，屏幕类 82.5%），但 CPU 端到端约 3.31 s/图，逐帧不现实；
   - 综合最佳：**PP-OCRv6 small**（81.3% / 79.7%，约 0.61 s/图）；
   - 最快：**PP-OCRv6 tiny**（73.5% / 71.2%，约 0.22 s/图，约为 v4 mobile 的 2.2 倍速）。
3. **绝对准确率最高（不限硬件）**：文档解析是 **PaddleOCR-VL-1.6**（0.9B，OmniDocBench v1.6 96.33%）；通用难场景是云 OCR（如 Cloud Vision）。两者分别需要 GPU / 联网，都不适合本项目逐帧、离线、CPU 的约束。
4. **对本项目最值得先试**：`PP-OCRv6 small + RapidOCR(ONNX Runtime)`。但你的 UI 文本很干净，v4 在干净印刷体上并不弱（见下表），换引擎的收益主要来自小字/低对比/花屏等难例，以及更轻的依赖和更快的 CPU 推理；**是否真的更好，必须用现有 ROI 帧做 A/B**。

## 二、主对比表（离线 CPU 候选）

| 方案 | 代际/发布 | 中文综合准确率 | 屏幕文本准确率 | CPU 端到端耗时* | 模型 + 运行时体积 | 离线/打包 | 评价 |
|---|---|---|---|---|---|---|---|
| **改造前：PaddleOCR 2.10 + PP-OCRv4 mobile** | 2022 | 53.0%†（v5 难集）/ 干净印刷 Exact 83.2%‡ | 未测（代际低于 v5 mobile） | 0.49 s（ORT）/ 0.62 s（Paddle） | ~17 MB 模型 + ~300 MB Paddle | ✅ | 基线；干净 UI 够用，难例落后 |
| PP-OCRv5 mobile | 2025 | 73.7% | 57.6% | 0.61 s（ORT）/ 0.80 s（Paddle） | ~23 MB + Paddle | ✅ | 过渡代，不建议新上 |
| **PP-OCRv6 tiny** | 2026-06 | 73.5% | 71.2% | **0.22 s**（ORT）/ 0.32 s（Paddle） | ~5 MB + ORT | ✅ | 最快；准确率约等于 v5 mobile |
| **PP-OCRv6 small** | 2026-06 | 81.3% | 79.7% | 0.61 s（ORT）/ 0.79 s（Paddle） | ~25 MB + ORT | ✅ | **综合首选** |
| PP-OCRv6 medium | 2026-06 | **83.2%** | **82.5%** | 3.31 s（ORT）/ 2.05 s（Paddle）；OpenVINO 1.40 s | ~100–150 MB + ORT | ✅ | 离线 CPU 准确率最高，但太慢 |
| **RapidOCR 3.10（默认 v6 small，ONNX）** | 2026-10-08 | 同 v6 small | 同 v6 small | ≈ v6 small（0.61 s 级） | 27.2 MB wheel + ORT | ✅ | **最省事的落地方式，无需 Paddle** |
| PaddleOCR 3.7 + ONNX Runtime backend | 2026-06-11 | 同 v6 家族 | 同 v6 家族 | 同上，取决于所选模型 | 官方完整依赖，较重 | ✅ | 想留在官方生态时选它 |
| EasyOCR 1.7.2 | 2024-09-24 | 0.09 ANLS§（中文 EPHOIE；Paddle 0.20） | 差 | 慢（PyTorch，未测得同条件数字） | ~50 MB 模型 + Torch（数百 MB～GB） | ✅ | 不推荐：模型两代未更新、依赖重 |
| Tesseract 5.5.3 | 2026-07-24 | 0.02 ANLS§（EPHOIE） | 差 | 快（CPU 传统引擎） | ~40 MB（含 chi_sim） | ✅ | 只适合干净印刷文档 |
| Windows OCR / OneOCR | 系统自带 | 无公开中文基准；用户反馈差¶ | 中/差 | 极快 | 0（系统组件） | ❌ 不可分发 | 不推荐：中文不可控、模型不能打包 |

\* 速度来自 PP-OCRv6 论文 Table 9：Intel Xeon 8350C、200 张混合图、端到端（含读盘）的平均秒/图，ONNX Runtime 与 PaddlePaddle 两个后端。绝对值不能直接搬到本项目的小 ROI 上，只看相对关系。
† v4 的 53.0% 是 PP-OCRv5 官方 12 类评测集的加权识别准确率，和 v6 的 15 类评测集**不是同一套数据**，不能与下表 v5/v6 数字直接横比。
‡ RapidOCR 自己的印刷体识别测试集上，`ch_PP-OCRv4_rec_infer.onnx` 的 Exact Match = 83.2%、Char Match = 93.6%；说明 v4 在“干净印刷体”上仍然很强。
§ DocOCR-Eval（arXiv 2607.16203）Table 3 的 ANLS，EPHOIE 为中文手写试卷类难集；PaddleOCR 0.20、EasyOCR 0.09、Tesseract 0.02。数字只代表难集方向，干净 UI 上差距会缩小。
¶ 见 Windrecorder issue #18 的用户实测反馈（Windows.Media.Ocr 中文效果差），不是正式基准。

### 屏幕文本这一列怎么读

PP-OCRv6 论文的 15 类内部评测里有一类 **Screen（屏幕显示/数码显示类文字）**，最接近“游戏 UI 截图”：

| 模型 | Screen 准确率 | Card 准确率 | 综合 W-Avg | CPU 耗时（ORT，Xeon） |
|---|---:|---:|---:|---:|
| PP-OCRv5 mobile | 57.6% | 81.7% | 73.7% | 0.61 s |
| PP-OCRv6 tiny | 71.2% | 80.5% | 73.5% | 0.22 s |
| PP-OCRv6 small | 79.7% | 86.9% | 81.3% | 0.61 s |
| PP-OCRv6 medium | 82.5% | 88.1% | 83.2% | 3.31 s |

这组数字说明：**v6 相对 v5 的提升，在“屏幕类文本”上比综合平均更明显**；v6 small 在耗时与 v5 mobile 相同的情况下，屏幕类从 57.6% 提到 79.7%。如果主要识别对象是卡牌名（Card 类，实体卡面，和游戏内卡名接近但不完全等同），v6 small 86.9% 也比 v5 mobile 81.7% 更稳，而 v6 tiny 的 Card 只有 80.5%，**卡名场景不要用 tiny**。

## 三、非 CPU 实时方案（为什么不用）

| 方案 | 准确率 | 速度/硬件 | 为什么不适合本项目 |
|---|---|---|---|
| PaddleOCR-VL-1.6（0.9B） | OmniDocBench v1.6 **96.33%**，文档解析 SOTA | GPU 秒级；0.9B 权重约 2 GB | 面向整页文档/表格/公式，输入是 ROI 小图时大材小用；CPU 上不可实时 |
| DeepSeek-OCR2 / HunyuanOCR / Qwen3-VL 等 VLM | 文档/复杂版面强 | 需要 GPU 或云端 | 有幻觉风险、输出无精细框、延迟高；不适合逐帧点击决策 |
| 云 OCR（百度/腾讯/Google Cloud Vision） | 通用/手写中文很强（Cloud Vision EPHOIE ANLS 0.44 vs Paddle 0.20） | 网络 100–500 ms + 费用 | 需要联网、有隐私与稳定性问题；断网/限流会直接卡死自动化 |
| Surya / docTR / Marker | 文档版面/阅读顺序强 | PyTorch，重 | 面向 PDF/文档，不是屏幕 UI 文本 |

## 四、对本项目的迁移建议

### 4.1 首选路线：RapidOCR + PP-OCRv6 small（ONNX Runtime）

- **改动小**：项目已经有清晰的 OCR 边界（改造前是 `PaddleOcrAdapter.recognize(image, frame_id, preprocessing) -> OcrEvidence`，本分支换成同签名的 `RapidOcrAdapter`）；`StableRecommendationReader`、预处理、缓存、解析层都不用动。
- **依赖变轻**：去掉 `paddlepaddle`（~300 MB）和 `paddleocr`，换成 `rapidocr`（27.2 MB，默认自带 PP-OCRv6 small det/rec/cls）+ `onnxruntime`；单文件 exe 有望从 300 MB 级降到 100 MB 级。
- **速度**：v6 small 与 v4 mobile 同量级（0.61 s vs 0.49 s，Xeon ORT），但准确率明显更高；如果延迟优先，换 **v6 tiny**（0.22 s，约 2.2 倍速）。
- **置信度要重标定**：不同引擎的 score 分布不同，现有 `min_ocr_confidence = 0.70` 不能直接照搬；上线前要用保存的 ROI 帧比较接受/拒绝率。
- **预处理可简化**：现在为了小字放大 1.4 倍（`ocr_preprocess_scale`）。v6 对小字更稳，可以试 1.0–1.2，进一步降延迟；先 A/B 再改默认值。

### 4.2 备选路线

- **想留在 PaddleOCR 官方生态**：升级到 PaddleOCR 3.7，使用 `engine="onnxruntime"`，模型选 PP-OCRv6 small；代价是 PaddleX 依赖和 API 迁移，比 RapidOCR 重。
- **准确率优先、能接受慢**：PP-OCRv6 medium；只建议离线批处理或非实时场景。
- **延迟极致优先**：PP-OCRv6 tiny；或在 Intel CPU 上试 OpenVINO（论文里 v6 medium 从 3.31 s 降到 1.40 s，但 v6 small/tiny 收益较小）。
- **不建议**：EasyOCR（模型停在 2024、Torch 依赖重）、Tesseract（屏幕中文明显弱）、Windows OCR/OneOCR（中文不可控、不可分发）、VLM/云 OCR（延迟/联网/幻觉）。

### 4.3 什么时候“不用换”

如果当前失败主要来自：

- ROI 框偏了 / 盒子面板改版 / 分辨率缩放不对；
- 炉石窗口被遮挡、截图退化成桌面；
- 稳定帧/置信度阈值卡住，而不是文字识别错；

那换 OCR 引擎不会解决问题，先把 ROI、截图和状态机修好。只有在“框对了、图也清晰，但字认错/认不出”时，换 v6 才有明显收益。

## 五、参考来源

- PP-OCRv6 官方介绍（准确率/速度/三档模型）：https://www.paddleocr.ai/latest/version3.x/algorithm/PP-OCRv6/PP-OCRv6.html
- PP-OCRv6 论文（Table 6/9，含 CPU 端到端数据）：https://arxiv.org/abs/2606.13108
- PP-OCRv5 官方介绍（v4 vs v5 准确率与 CPU 数据）：http://www.paddleocr.ai/v3.0.3/version3.x/algorithm/PP-OCRv5/PP-OCRv5.html
- PaddleOCR 3.7 发布 + ONNX Runtime 后端：https://www.53ai.com/news/MultimodalLargeModel/2026061283594.html
- RapidOCR 模型列表（PP-OCRv6 tiny/small/medium 支持）：https://rapidai.github.io/RapidOCRDocs/latest/en/model_list/
- RapidOCR 安装说明（27.2 MB wheel、默认 v6 small）：https://rapidai.github.io/RapidOCRDocs/latest/install_usage/rapidocr/install/
- RapidOCR 开源 OCR 模型对比（v4/v5 干净印刷体 Exact/Char Match）：https://raw.githubusercontent.com/RapidAI/RapidOCRDocs/main/docs/blog/posts/about_model/model_summary.md
- DocOCR-Eval（PaddleOCR/EasyOCR/Tesseract/Cloud Vision 同条件 ANLS）：https://arxiv.org/abs/2607.16203
- PaddleOCR-VL-1.6（0.9B，OmniDocBench v1.6 96.33%）：https://arxiv.org/abs/2606.03264
- OneOCR（Windows 11 截图工具 OCR，模型不可再分发）：https://oneocr.github.io/
- Windows OCR 中文效果差的用户反馈：https://github.com/yuka-friends/Windrecorder/issues/18
- EasyOCR 最新版（1.7.2，2024-09）：https://github.com/JaidedAI/EasyOCR/releases/tag/v1.7.2
- Tesseract 最新版（5.5.3，2026-07）：https://github.com/tesseract-ocr/tesseract/releases/tag/5.5.3
