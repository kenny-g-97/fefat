import type { Trade } from "@/api/trades"

/** The event the trade table's selection emits (step 5.8), which the trade review chart of step
 * 5.9 follows: `selectedTrade` on the window, the trade as the API gave it in its `detail`. */
export const SELECTED_TRADE = "selectedTrade"

/** A trade selected in the table, told apart from any other event of its name by its class, so
 * that a follower reads its `detail` typed. */
export class SelectedTradeEvent extends CustomEvent<Trade> {
  constructor(trade: Trade) {
    super(SELECTED_TRADE, { detail: trade })
  }
}

/** Tell whoever follows the table's selection that `trade` is now selected. */
export function announceSelectedTrade(trade: Trade): void {
  window.dispatchEvent(new SelectedTradeEvent(trade))
}
