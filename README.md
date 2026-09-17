# SeatBond

影院连座锁座：按场次厅图查找连续空座，过道列断开，冲突检测既有持座。

## 启动

```bash
docker compose up --build
```

| 服务 | 地址 |
| --- | --- |
| 前端 | http://localhost:4100 |
| API | http://localhost:9100 |
| API 文档 | http://localhost:9100/docs |
| Postgres | localhost:5442 |

健康检查：`GET http://localhost:9100/api/health`

## 页面

- `/halls` — 影厅
- `/showtimes` — 场次
- `/seatmap` — 座位图（大网格热力）
- `/hold` — 锁座
- `/orders` — 订单
- `/conflicts` — 冲突

## 使用说明

1. 在影厅与场次页确认厅图与排期。
2. 打开座位图查看占用热力，在锁座页输入连座人数并提交。
3. 订单页查看持座结果；冲突页查看重叠请求。

## 持座超时释放

- 新持座写入 `expires_at`，默认时长由环境变量 `HOLD_TTL_SECONDS` 配置（默认 600 秒）。
- 到期后持座转为 `released`（记录保留主键与原排列，不做物理删除），座位图占用与自动连座搜索立即视该格为空闲。
- 扫描接口：`POST /api/holds/release-expired`（可带 `?showtime_id=` 按场次，不带即全局），幂等。
- 持座列表：`GET /api/holds?status=held|released`，可叠加 `showtime_id`。
- `GET /api/seatmap/{id}` 与 `POST /api/holds` 会先即时释放本场到期持座，刷新座图即与释放结果一致。

## 开发与测试

```bash
docker compose exec api pytest -q
```
