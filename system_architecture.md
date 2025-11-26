# 私有化多模态大模型系统架构图

## 一、架构总览（Mermaid 图）

```mermaid
graph LR
    subgraph Users[内部用户（几十人）]
        U1[浏览器]
        U2[内部系统\n（工单/报表等）]
    end

    U1 -->|HTTPS 内网| FE[AI Web 前端\n(聊天界面 + 文档分析)]
    U2 -->|HTTP API| API[应用服务/API 网关]

    FE --> API

    subgraph AppLayer[应用 & Agent 层]
        API --> AG[Agent 编排服务\n(意图识别/路由/工具调用)]
        AG --> TOOL_RAG[文档检索工具\nRAG API]
        AG --> TOOL_DB[业务系统工具\n(工单/报表/DB)]
        AG --> MGW[模型网关\n(OpenAI 格式调用)]
    end

    subgraph DataLayer[数据与存储层]
        TOOL_RAG --> VDB[向量数据库\n(Qdrant/Milvus...)]
        TOOL_RAG --> FS[文件存储\n(PDF/文档/图片)]
        PARSER[文件解析服务\n(PDF 文本/图片/表格)] --> VDB
        U1 -->|上传文档| PARSER
        PARSER --> FS
    end

    subgraph ModelLayer[模型推理层（GPU 服务器, vLLM）]
        MGW --> MM_L[多模态大模型服务\nvLLM + GPU0-1]
        MGW --> MM_S[轻量多模态服务\nvLLM + GPU2]
        MGW --> TXT_LLM[纯文本/路由模型\nvLLM + GPU3]
        MGW --> EMB[Embedding 模型服务]
    end

    classDef user fill:#f5f5f5,stroke:#999;
    classDef app fill:#e0f7fa,stroke:#00838f;
    classDef data fill:#f3e5f5,stroke:#6a1b9a;
    classDef model fill:#fff3e0,stroke:#ef6c00;

    class U1,U2 user;
    class FE,API,AG,TOOL_RAG,TOOL_DB app;
    class VDB,FS,PARSER data;
    class MGW,MM_L,MM_S,TXT_LLM,EMB model;
```

---

## 二、架构分层说明

### 1. 用户层（Users）

- **浏览器用户（U1）**  
  - 通过内网 HTTPS 访问 AI Web 前端。  
  - 功能：聊天、上传 PDF/文档/图片、查看分析结果、高亮引用等。  

- **内部系统（U2）**  
  - 工单系统、报表系统等现有业务系统。  
  - 通过 HTTP API 调用 Agent 能力，让模型参与业务流程（如自动生成回复、解析报表）。  

---

### 2. 应用 & Agent 层（AppLayer）

- **AI Web 前端（FE）**  
  - 提供对话界面与文档分析界面：  
    - 文档上传/选择  
    - 聊天记录展示  
    - 文本与引用高亮  

- **应用服务 / API 网关（API）**  
  - 统一入口：认证、鉴权、限流、审计。  
  - 对接公司 SSO / LDAP / AD。  

- **Agent 编排服务（AG）**  
  - 核心职责：  
    - 解析用户意图  
    - 决定调用哪些工具（RAG、业务 API）  
    - 决定使用哪一个模型服务（大多模 / 小多模 / 文本模型）  
  - 可以基于 LangChain / LlamaIndex 等实现。  

- **文档检索工具（TOOL_RAG）**  
  - 对 Agent 提供「按语义检索文档」能力：  
    - 输入：自然语言问题 + 可选过滤条件（文档类型、部门、标签）  
    - 输出：相关文本片段 + 文档位置信息（页码、段落 ID）  

- **业务系统工具（TOOL_DB）**  
  - 封装对业务系统/数据库的访问：  
    - 例如：`get_ticket_status`、`run_sql`、`get_report_data`  
  - Agent 可以通过这些工具查询实时业务数据。  

- **模型网关（MGW）**  
  - 对上游：暴露统一 OpenAI 风格接口（/v1/chat/completions 等）  
  - 对下游：转发到不同的 vLLM 模型服务  
  - 可以做简单路由与负载均衡。  

---

### 3. 数据与存储层（DataLayer）

- **文件解析服务（PARSER）**  
  - 解析用户上传/已有的 PDF、Word、图片等：  
    - 抽取文本、标题、段落结构  
    - 抽取表格、图像  
  - 产出结构化内容用于向量化索引和多模态模型输入。  

- **文件存储（FS）**  
  - 存放原始 PDF/文档/图片。  
  - 可用对象存储 / NAS / 本地磁盘。  

- **向量数据库（VDB）**  
  - 存储文档分片的向量表示及 metadata：  
    - 文档 ID、页码、段落位置、权限标签等。  
  - 支持按语义检索 + 条件过滤。  

- **RAG 工具（TOOL_RAG）**  
  - 封装 VDB 的检索能力，供 Agent 使用。  
  - 典型流程：  
    - 对用户问题进行 embedding  
    - 在向量数据库中查相似片段  
    - 返回若干 top-k 片段作为模型上下文。  

---

### 4. 模型推理层（ModelLayer, GPU 服务器 + vLLM）

- **多模态大模型服务（MM_L）**  
  - 主力模型，负责复杂 PDF/报表/多图分析、多轮对话。  
  - 部署在 vLLM 上，绑定 1–2 块 48G GPU 或更高配置。  

- **轻量多模态服务（MM_S）**  
  - 用于：  
    - 快速图像问答  
    - 轻量场景 / 预筛选 / 较简单任务  
  - 也通过 vLLM 提供服务。  

- **纯文本/路由模型（TXT_LLM）**  
  - 负责：  
    - 普通聊天、总结、润色  
    - Agent 思考、规划、选择工具/模型  
  - 通常为轻量级中文指令模型。  

- **Embedding 模型服务（EMB）**  
  - 负责将文本转换为向量，用于：  
    - 文档索引与检索  
    - 相似度判断  
  - 可独立部署或通过 vLLM 的 `/v1/embeddings` 暴露。  

- **模型网关（MGW）**  
  - 同一 GPU 服务器上的统一入口，代理到不同的 vLLM 实例。  

---

## 三、关键设计要点

1. **完全内网/离线**  
   - 所有组件部署在公司内网或专用机房中，不访问外网。  

2. **多模型协同**  
   - 大多模负责困难任务，小多模/文本模型负责轻任务和决策。  

3. **RAG + 多模态**  
   - 文档先结构化 & 向量化，  
   - 再由 Agent 决定检索哪些内容，并组合文本 + 图像交给多模态模型。  

4. **Agent 工具化**  
   - 所有外部能力（文档检索、数据库、业务 API）都封装成可调用的 Tool，  
   - Agent 通过调用 Tool 完成复杂任务。  

5. **可扩展性**  
   - 如果后期再加一台 GPU 服务器，只需：  
     - 新机器部署 vLLM 模型服务  
     - 模型网关/Agent 层做简单扩展路由即可。
