"use client";

import React, { useState, useEffect } from "react";
import {
  ShieldAlert,
  Download,
  AlertTriangle,
  RefreshCw,
  TrendingUp,
  Receipt,
  Layers,
  Activity,
  Sliders,
  FileText,
  Lock,
  CheckCircle2,
  XCircle
} from "lucide-react";

export default function Dashboard() {
  const [activeTab, setActiveTab] = useState("live");
  const [status, setStatus] = useState(null);
  const [trades, setTrades] = useState([]);
  const [chargesSummary, setChargesSummary] = useState(null);
  const [positions, setPositions] = useState({ remote_positions: [], active_trades: [] });
  const [selectedTrade, setSelectedTrade] = useState(null);
  const [showKillModal, setShowKillModal] = useState(false);
  const [killConfirmInput, setKillConfirmInput] = useState("");
  const [killLoading, setKillLoading] = useState(false);
  const [lastRefreshed, setLastRefreshed] = useState("");

  const fetchData = async () => {
    try {
      const [resStatus, resTrades, resCharges] = await Promise.all([
        fetch("/api/status").then((r) => r.json()),
        fetch("/api/trades").then((r) => r.json()),
        fetch("/api/charges/summary").then((r) => r.json()),
      ]);
      setStatus(resStatus);
      if (Array.isArray(resTrades)) setTrades(resTrades);
      setChargesSummary(resCharges);
      setLastRefreshed(new Date().toLocaleTimeString("en-IN", { timeZone: "Asia/Kolkata" }));
    } catch (err) {
      console.error("Dashboard fetch error:", err);
    }
  };

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 2500);
    return () => clearInterval(interval);
  }, []);

  const handleKillSwitch = async () => {
    if (killConfirmInput.trim().toUpperCase() !== "HALT") return;
    setKillLoading(true);
    try {
      const res = await fetch("/api/kill-switch", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ confirm: "HALT" }),
      });
      const data = await res.json();
      setShowKillModal(false);
      setKillConfirmInput("");
      fetchData();
    } catch (e) {
      alert("Error triggering kill switch: " + e.message);
    } finally {
      setKillLoading(false);
    }
  };

  const handleDownloadCsv = () => {
    window.location.href = "/api/trades/csv";
  };

  const formatInr = (val) => {
    if (val === null || val === undefined) return "₹0.00";
    return new Intl.NumberFormat("en-IN", {
      style: "currency",
      currency: "INR",
      maximumFractionDigits: 2,
    }).format(val);
  };

  return (
    <div style={{ minHeight: "100vh", display: "flex", flexDirection: "column" }}>
      {/* Header */}
      <header className="header-container">
        <div className="logo-badge">
          <div style={{ width: 12, height: 12, borderRadius: "50%", background: "#00e5ff", boxShadow: "0 0 10px #00e5ff" }}></div>
          <div>
            <span className="logo-title">APEX-IN</span>
            <span style={{ marginLeft: 8, fontSize: "0.8rem", color: "var(--text-muted)", fontWeight: 600 }}>NIFTY / SENSEX F&O</span>
          </div>
          <span className="paper-pill">PAPER SIMULATOR</span>
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: "1rem" }}>
          {status?.sentinel_halted ? (
            <div className="badge-red" style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <ShieldAlert size={14} /> SENTINEL HALTED
            </div>
          ) : (
            <div className="badge-green" style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <CheckCircle2 size={14} /> ACTIVE & ARMED
            </div>
          )}

          <button id="kill-switch-btn" className="btn-danger" onClick={() => setShowKillModal(true)}>
            <AlertTriangle size={16} /> KILL SWITCH
          </button>
        </div>
      </header>

      {/* Navigation Tabs */}
      <nav className="tabs-nav">
        {[
          { id: "live", label: "Live Overview", icon: Activity },
          { id: "trades", label: "Trades Snapshot", icon: TrendingUp },
          { id: "charges", label: "F&O Charges Breakdown", icon: Receipt },
          { id: "performance", label: "Performance vs Target", icon: Layers },
          { id: "risk", label: "Risk Sentinel", icon: ShieldAlert },
          { id: "settings", label: "Settings & Rates", icon: Sliders },
        ].map((tab) => {
          const Icon = tab.icon;
          return (
            <button
              key={tab.id}
              id={`tab-${tab.id}`}
              className={`tab-btn ${activeTab === tab.id ? "active" : ""}`}
              onClick={() => setActiveTab(tab.id)}
            >
              <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
                <Icon size={14} /> {tab.label}
              </span>
            </button>
          );
        })}
      </nav>

      {/* Main Workspace */}
      <main style={{ padding: "1.5rem 2rem", flex: 1 }}>
        {/* Metric Cards Top Row */}
        <div className="metrics-grid">
          <div className="glass-panel metric-card">
            <div className="metric-label">Virtual Capital</div>
            <div className="metric-value">{formatInr(status?.current_equity || 500000)}</div>
            <div className="metric-sub">Peak: {formatInr(status?.peak_equity || 500000)}</div>
          </div>

          <div className="glass-panel metric-card">
            <div className="metric-label">Net Day P&L</div>
            <div className={`metric-value ${(status?.net_pnl_today || 0) >= 0 ? "badge-green" : "badge-red"}`} style={{ display: "inline-block" }}>
              {formatInr(status?.net_pnl_today || 0)}
            </div>
            <div className="metric-sub">Gross: {formatInr(status?.gross_pnl_today || 0)}</div>
          </div>

          <div className="glass-panel metric-card">
            <div className="metric-label">Charges Today</div>
            <div className="metric-value" style={{ color: "var(--accent-amber)" }}>
              {formatInr(status?.charges_today || 0)}
            </div>
            <div className="metric-sub">Full Statutory (STT, Exch, GST)</div>
          </div>

          <div className="glass-panel metric-card">
            <div className="metric-label">Peak Drawdown</div>
            <div className="metric-value" style={{ color: (status?.drawdown_pct || 0) > 5 ? "var(--accent-red)" : "var(--text-primary)" }}>
              {status?.drawdown_pct || 0}%
            </div>
            <div className="metric-sub">Max Limit: -15.0%</div>
          </div>

          <div className="glass-panel metric-card">
            <div className="metric-label">Market Session</div>
            <div className="metric-value" style={{ fontSize: "1.1rem", color: "var(--accent-cyan)" }}>
              {status?.market_session?.phase || "CLOSED"}
            </div>
            <div className="metric-sub">IST Refreshed: {lastRefreshed}</div>
          </div>
        </div>

        {/* TAB 1: LIVE */}
        {activeTab === "live" && (
          <div style={{ display: "flex", flexDirection: "column", gap: "1.5rem" }}>
            <div className="glass-panel" style={{ padding: "1.5rem" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1rem" }}>
                <h2 style={{ fontSize: "1.1rem", fontWeight: 700 }}>Active Sleeve Health & Data Quality</h2>
                <span className="badge-missing">DATA QUALITY: MISSING DEPTH/VOL IS HONESTLY FLAGGED</span>
              </div>
              <p style={{ color: "var(--text-secondary)", fontSize: "0.875rem", lineHeight: 1.6, marginBottom: "1rem" }}>
                MegaBull paper simulator provides Last Traded Price (LTP) only. Per Rule 2, APEX-IN never invents bid/ask quantities or volumes.
                Fills are additionally evaluated against conservative modeled friction (0.75% option spread / 1-3 pt futures spread) to prevent LTP fill optimism.
              </p>

              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: "1rem" }}>
                <div style={{ background: "rgba(255, 255, 255, 0.02)", padding: "1rem", borderRadius: 8, border: "1px solid var(--border-color)" }}>
                  <div style={{ fontWeight: 600, color: "var(--accent-cyan)" }}>Sleeve F (Futures Trend / ORB)</div>
                  <div style={{ fontSize: "0.8rem", color: "var(--text-muted)", marginTop: 4 }}>Near-month Nifty & Sensex futures. 15-min ORB + 20/50 EMA trend + ADX filter.</div>
                </div>
                <div style={{ background: "rgba(255, 255, 255, 0.02)", padding: "1rem", borderRadius: 8, border: "1px solid var(--border-color)" }}>
                  <div style={{ fontWeight: 600, color: "var(--accent-green)" }}>Sleeve O-Buy (Convex Momentum)</div>
                  <div style={{ fontSize: "0.8rem", color: "var(--text-muted)", marginTop: 4 }}>ATM / 1-OTM Call/Put buying. Risk strictly capped to entry premium. VIX &lt; 22 filter.</div>
                </div>
                <div style={{ background: "rgba(255, 255, 255, 0.02)", padding: "1rem", borderRadius: 8, border: "1px solid var(--border-color)" }}>
                  <div style={{ fontWeight: 600, color: "var(--accent-purple)" }}>Sleeve O-Spread (Defined Risk)</div>
                  <div style={{ fontSize: "0.8rem", color: "var(--text-muted)", marginTop: 4 }}>Vertical Credit Spreads. Long hedge leg is placed FIRST. Zero naked options.</div>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* TAB 2: TRADES */}
        {activeTab === "trades" && (
          <div className="glass-panel" style={{ padding: "1.5rem" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1rem", flexWrap: "wrap", gap: "0.75rem" }}>
              <div>
                <h2 style={{ fontSize: "1.1rem", fontWeight: 700 }}>Executed Trade Snapshots</h2>
                <span style={{ fontSize: "0.8rem", color: "var(--text-muted)" }}>Total Trades: {trades.length} | Immutable decision & exit audit records</span>
              </div>
              <button id="download-csv-btn" className="btn-primary" onClick={handleDownloadCsv}>
                <Download size={16} /> Download Full CSV ({trades.length} rows)
              </button>
            </div>

            <div className="table-container">
              <table className="custom-table">
                <thead>
                  <tr>
                    <th>Trade ID</th>
                    <th>Strategy</th>
                    <th>Contract</th>
                    <th>Side</th>
                    <th>Qty</th>
                    <th>Entry IST</th>
                    <th>Entry Px</th>
                    <th>Exit Px</th>
                    <th>Gross P&L</th>
                    <th>Charges</th>
                    <th>Net P&L</th>
                    <th>Data Quality</th>
                  </tr>
                </thead>
                <tbody>
                  {trades.length === 0 ? (
                    <tr>
                      <td colSpan={12} style={{ textAlign: "center", padding: "2rem", color: "var(--text-muted)" }}>
                        No trades executed in current forward-test session.
                      </td>
                    </tr>
                  ) : (
                    trades.map((t) => (
                      <tr key={t.trade_id} style={{ cursor: "pointer" }} onClick={() => setSelectedTrade(t)}>
                        <td>{t.trade_id}</td>
                        <td><span style={{ color: "var(--accent-cyan)" }}>{t.sleeve}</span></td>
                        <td>{t.tradingsymbol}</td>
                        <td>
                          <span className={t.side === "BUY" ? "badge-green" : "badge-red"}>{t.side}</span>
                        </td>
                        <td>{t.quantity}</td>
                        <td>{t.decision_time_ist?.substring(11, 19)}</td>
                        <td>₹{t.entry_price}</td>
                        <td>{t.exit_price ? `₹${t.exit_price}` : "OPEN"}</td>
                        <td>{t.gross_pnl !== null ? formatInr(t.gross_pnl) : "-"}</td>
                        <td style={{ color: "var(--accent-amber)" }}>₹{t.total_charges}</td>
                        <td>
                          <span className={(t.net_pnl || 0) >= 0 ? "badge-green" : "badge-red"}>
                            {t.net_pnl !== null ? formatInr(t.net_pnl) : "OPEN"}
                          </span>
                        </td>
                        <td><span className="badge-missing">{t.data_quality_flags || "OK"}</span></td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* TAB 3: CHARGES BREAKDOWN */}
        {activeTab === "charges" && (
          <div className="glass-panel" style={{ padding: "1.5rem" }}>
            <h2 style={{ fontSize: "1.1rem", fontWeight: 700, marginBottom: "0.5rem" }}>Statutory Levies & Brokerage Summary</h2>
            <p style={{ color: "var(--text-muted)", fontSize: "0.85rem", marginBottom: "1.5rem" }}>
              Computed per leg and per round trip from verified rates.yaml schedules (STT post-April-2026 rates, SEBI fee, NSE IPFT, Stamp Duty, GST).
            </p>

            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: "1rem", marginBottom: "2rem" }}>
              <div style={{ background: "rgba(255, 255, 255, 0.02)", padding: "1rem", borderRadius: 8 }}>
                <div className="metric-label">Securities Tax (STT)</div>
                <div className="metric-value">{formatInr(chargesSummary?.totals?.stt || 0)}</div>
                <div className="metric-sub">0.05% Fut / 0.15% Opt (Sell)</div>
              </div>
              <div style={{ background: "rgba(255, 255, 255, 0.02)", padding: "1rem", borderRadius: 8 }}>
                <div className="metric-label">Brokerage</div>
                <div className="metric-value">{formatInr(chargesSummary?.totals?.brokerage || 0)}</div>
                <div className="metric-sub">₹20 flat per executed leg</div>
              </div>
              <div style={{ background: "rgba(255, 255, 255, 0.02)", padding: "1rem", borderRadius: 8 }}>
                <div className="metric-label">Exchange Txn Charges</div>
                <div className="metric-value">{formatInr(chargesSummary?.totals?.exchange_txn || 0)}</div>
                <div className="metric-sub">0.00173% Fut / 0.035% Opt</div>
              </div>
              <div style={{ background: "rgba(255, 255, 255, 0.02)", padding: "1rem", borderRadius: 8 }}>
                <div className="metric-label">GST (18%)</div>
                <div className="metric-value">{formatInr(chargesSummary?.totals?.gst || 0)}</div>
                <div className="metric-sub">On Brokerage + Txn + SEBI</div>
              </div>
              <div style={{ background: "rgba(255, 255, 255, 0.02)", padding: "1rem", borderRadius: 8 }}>
                <div className="metric-label">Stamp Duty</div>
                <div className="metric-value">{formatInr(chargesSummary?.totals?.stamp_duty || 0)}</div>
                <div className="metric-sub">Buy leg only</div>
              </div>
              <div style={{ background: "rgba(255, 255, 255, 0.02)", padding: "1rem", borderRadius: 8 }}>
                <div className="metric-label">Total Charges</div>
                <div className="metric-value" style={{ color: "var(--accent-amber)" }}>{formatInr(chargesSummary?.totals?.total_charges || 0)}</div>
                <div className="metric-sub">Charges % of Gross P&L: {chargesSummary?.charges_as_pct_of_gross || 0}%</div>
              </div>
            </div>
          </div>
        )}

        {/* TAB 4: PERFORMANCE */}
        {activeTab === "performance" && (
          <div className="glass-panel" style={{ padding: "1.5rem" }}>
            <h2 style={{ fontSize: "1.1rem", fontWeight: 700, marginBottom: "0.5rem" }}>Measured Results vs Owner Return Target</h2>
            <div style={{ background: "rgba(239, 68, 68, 0.1)", border: "1px solid rgba(239, 68, 68, 0.3)", borderRadius: 8, padding: "1rem", marginBottom: "1.5rem" }}>
              <div style={{ fontWeight: 700, color: "var(--accent-red)", marginBottom: 4 }}>Mandatory Red-Flag Protocol</div>
              <div style={{ fontSize: "0.85rem", color: "#fca5a5" }}>
                Target: 20% - 30% per day (Aspirational tail outcome only).  
                Rule: Never loosen risk limits, never sell naked options, and never force trades to chase it. Net Sharpe &gt; 3 or win rate &gt; 70% is assumed to be a bug and investigated.
              </div>
            </div>

            <p style={{ color: "var(--text-secondary)", fontSize: "0.9rem" }}>
              Acceptance Gate: &gt;= 60 live forward sessions on MegaBull simulator. Measured headline P&L reports conservative fill prices (accounting for bid/ask spread) rather than optimistic LTP fills.
            </p>
          </div>
        )}

        {/* TAB 5: RISK SENTINEL */}
        {activeTab === "risk" && (
          <div className="glass-panel" style={{ padding: "1.5rem" }}>
            <h2 style={{ fontSize: "1.1rem", fontWeight: 700, marginBottom: "1rem" }}>Risk Sentinel Guardrails</h2>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))", gap: "1rem" }}>
              <div style={{ background: "rgba(255, 255, 255, 0.02)", padding: "1rem", borderRadius: 8 }}>
                <div className="metric-label">Per-Trade Risk Limit</div>
                <div className="metric-value">1.0%</div>
                <div className="metric-sub">Max ₹5,000 per trade on ₹5L</div>
              </div>
              <div style={{ background: "rgba(255, 255, 255, 0.02)", padding: "1rem", borderRadius: 8 }}>
                <div className="metric-label">Daily Loss Halt</div>
                <div className="metric-value">2.5%</div>
                <div className="metric-sub">Auto-flattens and halts at -₹12,500</div>
              </div>
              <div style={{ background: "rgba(255, 255, 255, 0.02)", padding: "1rem", borderRadius: 8 }}>
                <div className="metric-label">Drawdown Ladder</div>
                <div className="metric-value">-6% / -10% / -15%</div>
                <div className="metric-sub">Halve size / Disable O-Buy / Full halt</div>
              </div>
              <div style={{ background: "rgba(255, 255, 255, 0.02)", padding: "1rem", borderRadius: 8 }}>
                <div className="metric-label">Intraday Square-off</div>
                <div className="metric-value">15:15 IST</div>
                <div className="metric-sub">Mandatory close of all open legs</div>
              </div>
            </div>
          </div>
        )}

        {/* TAB 6: SETTINGS */}
        {activeTab === "settings" && (
          <div className="glass-panel" style={{ padding: "1.5rem" }}>
            <h2 style={{ fontSize: "1.1rem", fontWeight: 700, marginBottom: "1rem" }}>System Configuration (Read-Only)</h2>
            <div className="table-container">
              <table className="custom-table">
                <tbody>
                  <tr><td>PAPER_MODE_ONLY</td><td><span className="badge-green">TRUE (HARD GUARDED)</span></td></tr>
                  <tr><td>Timezone</td><td>Asia/Kolkata (IST)</td></tr>
                  <tr><td>Statutory STT Schedule</td><td>Post-April 2026 (0.05% Fut / 0.15% Opt)</td></tr>
                  <tr><td>Order Rate Cap</td><td>&lt;= 2 orders / sec (Max 40/day)</td></tr>
                  <tr><td>Database Engine</td><td>PostgreSQL (Railway Plugin) / SQLite Local</td></tr>
                </tbody>
              </table>
            </div>
          </div>
        )}
      </main>

      {/* KILL SWITCH CONFIRMATION MODAL */}
      {showKillModal && (
        <div className="modal-backdrop">
          <div className="modal-card">
            <div style={{ display: "flex", alignItems: "center", gap: 10, color: "var(--accent-red)", marginBottom: "1rem" }}>
              <AlertTriangle size={28} />
              <h3 style={{ fontSize: "1.25rem", fontWeight: 800 }}>CONFIRM EMERGENCY KILL SWITCH</h3>
            </div>
            <p style={{ color: "var(--text-secondary)", fontSize: "0.875rem", lineHeight: 1.5, marginBottom: "1.25rem" }}>
              This action will cancel all pending orders and immediately flatten all active positions on MegaBull simulator.
              To confirm, type <strong style={{ color: "#ffffff" }}>HALT</strong> below:
            </p>
            <input
              id="kill-confirm-input"
              type="text"
              placeholder="Type HALT to confirm"
              value={killConfirmInput}
              onChange={(e) => setKillConfirmInput(e.target.value)}
              style={{
                width: "100%",
                padding: "0.75rem 1rem",
                borderRadius: 8,
                background: "rgba(0,0,0,0.4)",
                border: "1px solid var(--border-color)",
                color: "#ffffff",
                fontFamily: "var(--font-mono)",
                marginBottom: "1.5rem",
              }}
            />
            <div style={{ display: "flex", justifyContent: "flex-end", gap: "0.75rem" }}>
              <button className="tab-btn" onClick={() => setShowKillModal(false)}>Cancel</button>
              <button
                id="kill-confirm-submit"
                className="btn-danger"
                disabled={killConfirmInput.trim().toUpperCase() !== "HALT" || killLoading}
                onClick={handleKillSwitch}
              >
                {killLoading ? "Executing..." : "HALT & FLATTEN NOW"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
