# GPU 服务器详细采购单

## 一、总体目标

- 本地离线、内网可用  
- 支持中文多模态大模型（复杂文档/PDF/多图分析）  
- 支持几十个内部用户并发访问  
- 部署 vLLM + 多模型 + Agent 编排层

---

## 二、推荐配置（适合当前需求）

用于：单机支撑 14B~32B 多模态模型 + 若干辅助模型，几十并发。

```markdown
### AI GPU 服务器采购单（推荐配置）

- 数量：
  - 1 台（后续需求增加可再横向扩展）

- 机型：
  - 2U 或 4U 机架式服务器（Dell / HPE / Inspur / 联想 等同类机型）

- CPU：
  - 1–2 颗服务器级 CPU（Intel Xeon / AMD EPYC）
  - 总核数 ≥ 32 核（64 线程以上）

- 内存：
  - 128 GB DDR4/DDR5 以上（建议可扩展至 256 GB）

- GPU：
  - 数量：2–4 块
  - 显存：每块 48 GB 级别
  - 类型（任选其一或等效）：
    - NVIDIA L40 / L40S 48GB
    - 或 RTX 6000 Ada 48GB
    - 或 A40 48GB
  - 要求：
    - 支持 CUDA、适配主板电源与空间
    - 整机电源功率满足满载 GPU 场景

- 存储：
  - 系统盘：
    - 1 × 1TB NVMe SSD
  - 数据盘：
    - 2 × 2TB NVMe SSD（或 1 × 4TB NVMe SSD）
    - 用于模型权重、向量库数据、日志等
  - 可选：
    - RAID1/RAID10 视可靠性需求配置

- 网络：
  - 至少 2 × 10GbE 网口（或 25GbE，根据机房网络）
  - 仅接入公司内网/VPN，无需公网

- 电源：
  - 冗余电源（1+1）
  - 单电源输出满足满载 GPU 功率

- 散热：
  - 机房需保证良好散热和风道
  - 服务器选配高风量风扇

- 操作系统：
  - Ubuntu Server 22.04 LTS（或同等级企业 Linux）

- 其他：
  - 远程管理：iDRAC / iLO / BMC 管理口
  - 机架导轨、线缆配件按机柜环境配齐
```

---

## 三、高配方案（预算充足可选）

用于：更大模型（30B+ 多模态）、更高并发、未来可扩展为集群。

```markdown
### AI GPU 服务器采购单（高配配置）

- 数量：
  - 1 台（后续可扩展为多节点集群）

- CPU：
  - 总核数 ≥ 64 核（双路 Xeon / EPYC）

- 内存：
  - 256 GB DDR4/DDR5 以上

- GPU：
  - 数量：2 块
  - 显存：每块 80 GB 级别
  - 类型（任选其一或等效）：
    - NVIDIA A100 80GB
    - NVIDIA H100 80GB
    - 或 H20 96GB
  - 视需求支持 NVLink（模型并行）

- 存储：
  - 系统盘：1 × 1TB NVMe SSD
  - 数据盘：2 × 4TB NVMe SSD（或更大）

- 网络：
  - 2 × 25GbE 起步（视数据中心网络情况）

- 电源与散热：
  - 冗余电源，功率满足 GPU 满配
  - 加强散热配置

- 操作系统：
  - Ubuntu Server 22.04 LTS 或企业 Linux
```

---

## 四、软件与运行环境建议（可附在技术附件中）

```markdown
### 软件与运行环境建议

- 操作系统：
  - Ubuntu Server 22.04 LTS

- GPU 与驱动：
  - NVIDIA 官方驱动（版本匹配 GPU）
  - CUDA Toolkit（与驱动兼容）

- 容器环境：
  - Docker CE
  - nvidia-container-toolkit（GPU 容器）

- AI 推理框架：
  - vLLM（主推理框架，OpenAI API 兼容）

- 向量数据库：
  - Qdrant / Milvus / Chroma（三择一）

- 编程环境：
  - Python 3.10+
  - 主要依赖：
    - PyTorch
    - transformers
    - sentence-transformers（如需）
    - langchain / llama-index（用于 Agent 与 RAG 编排）

- 监控与运维：
  - Prometheus + Grafana（性能监控）
  - Loki/ELK（日志）视情况选配
```

---

## 五、补充说明

- 若后续业务量增长，可按同配置再采购 1–2 台水平扩展。  
- 如有严格高可用要求，可考虑：  
  - 两台服务器 + 负载均衡 + 主备/分布式向量库。
