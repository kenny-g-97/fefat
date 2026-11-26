import type { SideResults } from "@/api/run-results"

/** A side's figures as the API answers them, for the tests of their words: a run of 24 trades on
 * ES, 13 of them won, a perpetual's funding left out. */
export const SIDE: SideResults = {
  trades: 24,
  wins: 13,
  losses: 10,
  win_rate: 0.5416666666666666,
  net_pnl: "-1234.500000",
  gross_profit: "2650.000000",
  gross_loss: "-3884.500000",
  profit_factor: 0.6821986098596216,
  expectancy: -51.4375,
  expectancy_r: -0.1234,
  average_win: 203.84615384615384,
  average_loss: -388.45,
  win_loss_ratio: 0.5247680109232563,
  fees: "137.760000",
  funding: null,
  slippage: "600.000000",
  trades_per_day: 8,
  average_minutes_held: 95.5,
  average_mae_ticks: 6.25,
  average_mfe_ticks: 9.5,
  max_drawdown: "2100.250000",
  longest_drawdown_days: 3,
  sharpe: null,
}
