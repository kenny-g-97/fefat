/** The attribution notice of Lightweight Charts, the library `PriceChart` draws with, word for
 * word from the NOTICE file of its tag v5.2.1. Its licence asks an app to show the notice and a
 * link to TradingView on a page its users see: the logo on each chart is the link, and the
 * settings' About shows the notice. The letter between the brackets is the file's own, a
 * Cyrillic one, and the year is the file's, where the library's bundle prints its build's. */
export const CHART_NOTICE: Readonly<{
  product: string
  copyright: string
  page: string
}> = {
  product: "TradingView Lightweight Charts™",
  copyright: "Copyright (с) 2025 TradingView, Inc.",
  page: "https://www.tradingview.com/",
}

/** The NOTICE file of Apache ECharts, the library `EquityChart` draws with, word for word from
 * its package at 6.1.0, which its licence, Apache 2.0, asks a distribution to carry. */
export const EQUITY_CHART_NOTICE: Readonly<{
  product: string
  copyright: string
  credit: string
  page: string
}> = {
  product: "Apache ECharts",
  copyright: "Copyright 2017-2026 The Apache Software Foundation",
  credit:
    "This product includes software developed at The Apache Software Foundation",
  page: "https://www.apache.org/",
}
