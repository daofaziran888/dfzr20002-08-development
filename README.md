# 会展布展协作平台

策展人、设计师和施工团队共同编排展位布局、展品运输与搭建进度，按同一版执行方案完成布展交付。

这是一个前后端分离的管理平台：前端 Vue 3 + Vite + TypeScript，后端 FastAPI（Python）。
两边各自独立启动，前端 dev server 已关掉自动打开页面，启动后按终端打印的地址手工打开。

## 目录结构

```text
.
├── frontend/                 Vue 3 + Vite + TypeScript 前端
│   ├── src/views/WorkbenchView.vue|tsx  全部模块共享工作台
│   ├── src/data/modules.ts              18个业务模块配置
│   ├── src/api/              统一请求封装
│   └── vite.config.ts        dev server 配置（open: false）
├── backend/                  FastAPI（Python） 后端
│   ├── app/routers/resource.py  通用查询/导出/登记/动作接口
│   ├── app/services/<key>.py    每个模块独立领域逻辑
│   ├── app/services/base.py     共享服务骨架
│   └── app/store.py          内存数据仓库与示例数据
├── .gitignore
└── docker-compose.yml
```

## 启动

### 后端

```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
./run.sh
```

健康检查：`curl http://127.0.0.1:8000/api/health`

### 前端

```bash
cd frontend
npm ci
npm run dev
```

前端默认监听 `http://127.0.0.1:5173/`，dev server 不会自动打开浏览器，
需要自己访问。`/api` 由 vite 代理到后端 `http://127.0.0.1:8000`。

## 业务模块

| 模块 | 目录 | 业务对象 | 主要字段 |
| --- | --- | --- | --- |
| 场馆规划 | `venue` | 场馆 | 场馆名称、可用面积、层高限制 |
| 展位编排 | `booth` | 展位 | 展位编号、面积尺寸、开口方向 |
| 参展商管理 | `exhibitor` | 参展商 | 企业名称、展品类别、联系人 |
| 方案设计 | `design` | 设计方案 | 设计风格、结构材料、搭建高度 |
| 搭建物料 | `material` | 物料 | 物料名称、规格型号、配额数量 |
| 展品运输 | `transport` | 运输单 | 展品名称、运输方式、预计到达 |
| 搭建进度 | `construction` | 进度节点 | 节点名称、计划日期、完成日期 |
| 用电配置 | `electrical` | 用电回路 | 回路编号、额定功率、所属展位 |
| 安全巡检 | `safety` | 巡检记录 | 检查点位、隐患等级、整改措施 |
| 灯光编排 | `lighting` | 灯光方案 | 灯位坐标、色温设定、光束角度 |
| 影音布置 | `audio_visual` | 影音设备 | 设备型号、安装位置、信号线路 |
| 家具配置 | `furniture` | 家具方案 | 家具类型、摆放位置、数量需求 |
| 导视系统 | `signage` | 导视牌 | 指示内容、安装点位、尺寸规格 |
| 验收清单 | `checklist` | 验收项 | 验收条目、验收标准、负责班组 |
| 变更指令 | `change_order` | 变更单 | 变更内容、影响展位、施工班组 |
| 布展排期 | `schedule` | 排期计划 | 活动名称、布展起始、撤展截止 |
| 交场确认 | `handover` | 交场单 | 交出班组、接收人员、遗留事项 |
| 突发事件 | `incident` | 事件记录 | 事件类型、发生位置、处置班组 |

## 约定

- 全部模块共享`frontend/src/views/WorkbenchView.vue|tsx`和一套资源路由。
- 每个模块仍保留独立`backend/app/services/<模块>.py`；纯前端保留
  `frontend/src/domain/<模块>.ts`，用于承载真实业务差异并维持36题位容量。
- 列表接口统一返回 `{ items, total, page, size }`，动作接口统一返回 `{ ok, message }`。
- 状态流转只允许在 `app/services` 里改，路由层不做业务判断。

## 用电核验与调试放行

用电配置本身只做即时容量核对（设计负荷 vs 回路额定功率之和），不沉淀结论。
核验通过后由「出具核验回执」动作生成**用电核验回执**，把当时的设计负荷、各回路
额定功率与核验结论固化为快照；影音布置的「调试设备」必须消费一张有效核验回执，
并生成**调试放行回执**占用回路额度。规则集中在 `app/services/power_receipt.py`：

- 一个回路在同一时段只能有一个有效放行额度（占用中的放行回执），重复办理直接拒绝。
- 设计负荷下调导致核验结论由通过变超限时，原核验回执标记**失效**，编号与负荷明细
  仍可按原编号反查；已开始的试音不中断，允许登记完成记录并结清，但失效额度不能再
  办新的试音。
- 失效期间登记的完成记录自动挂「需复核」标记，结清释放后标记保留，复核人取影音
  设备负责人。
- 回路占用核对接口返回回执与用电侧占用是否一致、额度何时释放、谁需要复核旧记录。

| 接口 | 说明 |
| --- | --- |
| `GET /api/exhibition/power/receipts` | 核验回执清单（可按展位/回路/状态/编号过滤） |
| `GET /api/exhibition/power/receipts/by-no/{回执编号}` | 审核员按原编号查当时负荷明细 |
| `POST /api/exhibition/power/receipts/{id}/reissue` | 从新单对同一回路重新核验 |
| `POST /api/exhibition/power/releases` | 基于有效核验回执办理调试放行（占用额度） |
| `POST /api/exhibition/power/releases/{id}/completion` | 登记试音完成记录（只做收尾） |
| `POST /api/exhibition/power/releases/{id}/settle` | 结清占用并释放回路 |
| `POST /api/exhibition/power/design/{id}/load-change` | 设计负荷变更，联动失效超限回执 |
| `GET /api/exhibition/power/circuit/{回路编号}/occupancy` | 回执与用电侧占用一致性核对 |

前端在「用电核验与放行」页（`/power-receipts`，`PowerReceiptView.vue`）集中办理；
「用电配置」工作台新增「出具核验回执」动作，「影音布置」工作台新增「登记试音完成」。

领域：应用开发
子方向：web前端/全栈开发
