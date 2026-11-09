/** One event of a Server-Sent Events stream: its id, which the server counts up, its type,
 * and its data as sent. */
export type StreamedEvent = {
  readonly id: string | undefined
  readonly event: string
  readonly data: string
}

type Following = {
  readonly url: string
  readonly signal: AbortSignal
  readonly onEvent: (event: StreamedEvent) => void
  readonly lastEventId?: string
  readonly fetchStream?: typeof fetch
}

type LinesRead = {
  readonly lines: readonly string[]
  readonly rest: string
}

const FIRST_PAUSE_MS = 1_000
const LONGEST_PAUSE_MS = 10_000
const LINE_BREAK = /\r\n|\r|\n/

/** Follow the event stream at `url` (`GET /v1/streams/{stream_id}`), handing each event to
 * `onEvent`, which must not throw. When the connection drops, it connects again after a pause
 * that doubles up to ten seconds, sending the id of the last whole event it handed on as
 * `Last-Event-ID`, so that the server sends the events after it, none twice and none missed. It
 * stops when `signal` aborts, and when the server refuses the stream, such as a session that
 * ended. */
export async function followEventStream({
  url,
  signal,
  onEvent,
  lastEventId,
  fetchStream = fetch,
}: Following): Promise<void> {
  let lastId = lastEventId
  let pause = FIRST_PAUSE_MS
  while (!signal.aborted) {
    try {
      const headers: Record<string, string> =
        lastId === undefined ? {} : { "Last-Event-ID": lastId }
      const response = await fetchStream(url, { signal, headers })
      if (!response.ok || response.body === null) {
        return
      }
      for await (const event of eventsOf(response.body)) {
        lastId = event.id === undefined ? lastId : event.id
        pause = FIRST_PAUSE_MS
        onEvent(event)
      }
    } catch {
      if (signal.aborted) {
        return
      }
    }
    await paused(pause, signal)
    pause = Math.min(pause * 2, LONGEST_PAUSE_MS)
  }
}

/** The whole events of a stream's `body`: an event ends at a blank line, and one the stream
 * ends halfway through is dropped, as the protocol has it. */
async function* eventsOf(
  body: ReadableStream<Uint8Array<ArrayBuffer>>
): AsyncGenerator<StreamedEvent> {
  let id: string | undefined
  let event = ""
  let data: string[] = []
  for await (const line of linesOf(body)) {
    if (line === "") {
      if (data.length > 0) {
        yield {
          id,
          event: event === "" ? "message" : event,
          data: data.join("\n"),
        }
      }
      id = undefined
      event = ""
      data = []
      continue
    }
    if (line.startsWith(":")) {
      continue
    }
    const colon = line.indexOf(":")
    const field = colon === -1 ? line : line.slice(0, colon)
    const value = colon === -1 ? "" : line.slice(colon + 1).replace(/^ /, "")
    if (field === "id") {
      id = value
    } else if (field === "event") {
      event = value
    } else if (field === "data") {
      data = [...data, value]
    }
  }
}

/** The lines of a stream's `body`, each without its line break; a carriage return that ends a
 * read waits for the next, which may hold its line feed. */
async function* linesOf(
  body: ReadableStream<Uint8Array<ArrayBuffer>>
): AsyncGenerator<string> {
  let pending = ""
  for await (const text of body.pipeThrough(new TextDecoderStream())) {
    const buffered = pending + text
    const held = buffered.endsWith("\r")
    const read = splitLines(held ? buffered.slice(0, -1) : buffered)
    yield* read.lines
    pending = held ? `${read.rest}\r` : read.rest
  }
}

function splitLines(text: string): LinesRead {
  const parts = text.split(LINE_BREAK)
  return { lines: parts.slice(0, -1), rest: parts[parts.length - 1] }
}

/** A pause of `ms` milliseconds, which `signal` ends early. */
function paused(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    const timer = setTimeout(done, ms)
    signal.addEventListener("abort", done, { once: true })
    function done() {
      clearTimeout(timer)
      signal.removeEventListener("abort", done)
      resolve()
    }
  })
}
