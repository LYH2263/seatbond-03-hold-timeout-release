import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";

type Hold = {
  id: number;
  showtime_id: number;
  order_code: string;
  row: number;
  start_col: number;
  end_col: number;
  party_size: number;
  status: string;
  created_at: string;
  expires_at: string;
  released_at: string | null;
};

type StatusFilter = "" | "held" | "released";

const STATUS_LABEL: Record<string, string> = {
  held: "持有中",
  released: "已释放",
};

function fmt(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString();
}

export default function OrdersPage() {
  const [rows, setRows] = useState<Hold[]>([]);
  const [status, setStatus] = useState<StatusFilter>("");
  const [scanMsg, setScanMsg] = useState("");

  const load = useCallback(() => {
    const qs = status ? `?status=${status}` : "";
    api<Hold[]>(`/holds${qs}`).then(setRows);
  }, [status]);

  useEffect(() => {
    load();
  }, [load]);

  async function scan() {
    setScanMsg("");
    try {
      const res = await api<{ released_count: number }>("/holds/release-scan", {
        method: "POST",
        body: JSON.stringify({}),
      });
      setScanMsg(`扫描完成，本次释放 ${res.released_count} 条超时持座`);
      load();
    } catch (e) {
      setScanMsg(e instanceof Error ? e.message : String(e));
    }
  }

  return (
    <>
      <h2>订单</h2>
      <div className="toolbar">
        <label>
          状态{" "}
          <select value={status} onChange={(e) => setStatus(e.target.value as StatusFilter)}>
            <option value="">全部</option>
            <option value="held">持有中</option>
            <option value="released">已释放</option>
          </select>
        </label>
        <button onClick={scan}>扫描释放超时持座（全局）</button>
        {scanMsg && <span className="ok">{scanMsg}</span>}
      </div>
      <table className="table">
        <thead>
          <tr>
            <th>订单号</th>
            <th>场次</th>
            <th>座位</th>
            <th>人数</th>
            <th>状态</th>
            <th>到期时刻</th>
            <th>释放时刻</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((h) => (
            <tr key={h.id}>
              <td className="mono">{h.order_code}</td>
              <td>{h.showtime_id}</td>
              <td className="mono">
                R{h.row} C{h.start_col}-{h.end_col}
              </td>
              <td>{h.party_size}</td>
              <td>{STATUS_LABEL[h.status] ?? h.status}</td>
              <td className="mono">{fmt(h.expires_at)}</td>
              <td className="mono">{fmt(h.released_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}
