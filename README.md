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
2. 打开座位图查看占用热力，在锁座页输入连座人数并提交。持座写入 `expires_at`（默认 120 秒，可用环境变量 `HOLD_TTL_SECONDS` 配置）。
3. 订单页查看持座结果，可按「持有中/已释放」筛选，并可全局扫描释放超时持座；冲突页查看重叠请求。
4. 到期持座经扫描（`POST /api/holds/release-scan`，可带 `showtime_id`；刷新座位图或重新锁座时也会按场次懒释放）后转为「已释放」：行记录保留主键与原排列用于对账，格子立即腾空，可被新锁座重新占用。

## 开发与测试

```bash
docker compose exec api pytest -q
```
