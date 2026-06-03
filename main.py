"""
TradeAnalyze — Main Entry Point
================================
Runs BOTH pipelines per symbol:

  A) Futures Pipeline  (new — full institutional grade)
     FuturesOrchestrator → HMM regime + market structure +
     RSI divergence + AI score + MC + Kelly + 7-gate decision
     → Sends institutional report via LINE

  B) Options Pipeline  (existing)
     TradeOrchestrator → option chain + Greeks + MC → Options sheet

Symbol config (SYMBOL_CONFIG sheet):
  symbol | group | asset_type
  AAPL   | LINE  | stock
  BTC    | LINE  | crypto
"""

import time
import traceback

from config.config_validator import validate
from config.logging_config import logger
from alerts.line_alert import send_line_message
from core.futures_orchestrator import FuturesOrchestrator
from core.orchestrator import TradeOrchestrator
from data.market_data import get_market_data
from reports.formatter import format_symbol_message
from reports.option_chain_writer import clear_symbol_rows, write_option_chain
from reports.sheet_writer import log_trade_signals, log_options_signals
from utils.symbol_loader import load_symbols_with_type


def run_trading_engine() -> None:

    validate()

    futures_orch = FuturesOrchestrator(win_rate=0.52, avg_rr=2.5)
    options_orch = TradeOrchestrator()
    success = fail = 0

    symbol_list = load_symbols_with_type("LINE")
    if not symbol_list:
        print("❌ No symbols found in SYMBOL_CONFIG (group=LINE)")
        return

    print(f"\n🚀 ===== TRADING ENGINE START =====")
    print(f"📊 Symbols: {len(symbol_list)}")

    for item in symbol_list:
        symbol     = item["symbol"]
        asset_type = item["asset_type"]

        print(f"\n{'━'*42}")
        print(f"📊 {symbol}  ({asset_type})")

        try:
            # ── 1. Fetch market data (shared by both pipelines) ───────────────
            df = get_market_data(symbol)
            if df is None or df.empty:
                print(f"  ❌ No market data")
                fail += 1
                continue

            price = float(df["Close"].iloc[-1])

            # ── 2. FUTURES PIPELINE ───────────────────────────────────────────
            print(f"  ⚙️  Running futures analysis...")
            futures = futures_orch.run(symbol, df)

            decision_emoji = {"LONG": "🟢", "SHORT": "🔴", "NO_TRADE": "⏸️"}.get(
                futures.final_decision, "❓"
            )
            print(
                f"  {decision_emoji} Futures: {futures.final_decision} | "
                f"Regime: {futures.regime} ({futures.regime_conf:.0f}%) | "
                f"AI: {futures.ai_score:.0f} | RR: {futures.rr:.1f} | "
                f"MC: {futures.mc_profit_prob:.0f}%"
            )

            # Send futures report via LINE (truncate to 4500 chars)
            report_msg = futures.report_text
            if len(report_msg) > 4500:
                report_msg = report_msg[:4480] + "\n…(truncated)"
            sent = send_line_message(report_msg)
            print(f"  📱 LINE futures report: {'✅ sent' if sent else '⚠️ skipped'}")

            # ── 3. OPTIONS PIPELINE ───────────────────────────────────────────
            print(f"  ⚙️  Running options analysis...")
            options_data = options_orch.run(symbol, asset_type=asset_type)

            if options_data:
                signals        = options_data["signals"]
                options        = options_data["options"]
                monte          = options_data["monte"]
                enriched_chain = options_data["option_chain"]

                # Option Chain → Sheets
                if enriched_chain:
                    try:
                        clear_symbol_rows(symbol)
                        n = write_option_chain(symbol, enriched_chain)
                        print(f"  📋 Option chain: {n} rows → Option_Chain")
                    except Exception as exc:
                        print(f"  ⚠️  Option chain write: {exc}")

                # Signals + Options → Sheets
                log_trade_signals(symbol, signals, monte)
                log_options_signals(symbol, options, monte)
                print(f"  ✅ Sheets: TradeSignals + Options written")

                # Options summary LINE message
                signal = signals[0]
                option = options[0]
                mc     = monte[0]

                # Inject futures decision into signal for richer display
                signal["futures_decision"]  = futures.final_decision
                signal["futures_ai_score"]  = futures.ai_score
                signal["futures_regime"]    = futures.regime

                options_msg = format_symbol_message(signal, option, mc, enriched_chain)
                if len(options_msg) > 4500:
                    options_msg = options_msg[:4480] + "\n…(truncated)"
                send_line_message(options_msg)

            success += 1
            print(f"  ⏱  {futures.runtime}s")
            time.sleep(2)

        except Exception:
            fail += 1
            logger.error("[%s] UNHANDLED:\n%s", symbol, traceback.format_exc())
            print(f"  ❌ ERROR:\n{traceback.format_exc()}")

    print(f"\n{'━'*42}")
    print(f"🏁 DONE  ✅ {success}  ❌ {fail}")
    logger.info("Engine done — success=%d fail=%d", success, fail)


if __name__ == "__main__":
    try:
        run_trading_engine()
    except Exception:
        logger.critical("GLOBAL ERROR:\n%s", traceback.format_exc())
        print(f"GLOBAL ERROR:\n{traceback.format_exc()}")
