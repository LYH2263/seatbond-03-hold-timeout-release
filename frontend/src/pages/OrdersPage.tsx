import { useEffect, useState } from "react";
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

function fmt(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleString("zh-CN", { hour12: false });
}

export default function OrdersPage() {
  const [rows, setRows] = useState<Hold[]>([]);
  const [status, setStatus] = useState<StatusFilter>("");
  const [sid, setSid] = useState("");
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");

  async function load(next: StatusFilter = status) {
    const qs = next ? `?status=${next}` : "";
    setRows(await api<Hold[]>(`/holds${qs}`));
  }

  useEffect(() => {
    load("").catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function scan() {
    setMsg("");
    setErr("");
    try {
      const param = sid.trim() ? `?showtime_id=${encodeURIComponent(sid.trim())}` : "";
      const res = await api<{ released: number }>(`/holds/release-expired${param}`, {
        method: "POST",
      });
      setMsg(
        `${sid.trim() ? `场次 ${sid.trim()} ` : "全局"}扫描完成，本次释放 ${res.released} 条到期持座`
      );
      await load();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  }

  return (
    <>
      <h2>订单</h2>
      <div className="toolbar">
        <label>
          状态{" "}
          <select
            value={status}
            onChange={(e) => {
              const v = e.target.value as StatusFilter;
              setStatus(v);
              load(v).catch(() => {});
            }}
          >
            <option value="">全部</option>
            <option value="held">持有中</option>
            <option value="released">已释放</option>
          </select>
        </label>
        <label>
          场次ID（可选）{" "}
          <input
            value={sid}
            onChange={(e) => setSid(e.target.value)}
            placeholder="留空=全局"
            style={{ width: 110 }}
          />
        </label>
        <button onClick={scan}>扫描释放到期持座</button>
      </div>
      {msg && <div className="ok">{msg}</div>}
      {err && <div className="err">{err}</div>}
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
              <td>{h.status === "held" ? "持有中" : "已释放"}</td>
              <td className="mono">{fmt(h.expires_at)}</td>
              <td className="mono">{fmt(h.released_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}
