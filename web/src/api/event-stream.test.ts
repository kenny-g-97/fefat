import { describe, expect, it } from "vitest"
import { followEventStream, type StreamedEvent } from "./event-stream"

const STREAM = "/v1/streams/job:1"

type Ending = "drops" | "closes"

/** An answer whose stream sends `chunks`, one per read, then drops or closes; an error drops
 * the chunks still queued, so the stream sends each only when it is read. */
function streamOf(chunks: readonly string[], ending: Ending): Response {
  const encoder = new TextEncoder()
  let sent = 0
  const body = new ReadableStream<Uint8Array>({
    pull(controller) {
      if (sent < chunks.length) {
        controller.enqueue(encoder.encode(chunks[sent]))
        sent += 1
        return
      }
      if (ending === "drops") {
        controller.error(new TypeError("The connection dropped."))
        return
      }
      controller.close()
    },
  })
  return new Response(body, {
    headers: { "Content-Type": "text/event-stream" },
  })
}

function progress(id: number): string {
  return `event: progress\ndata: {"percent": ${id * 10}}\nid: ${id}\n\n`
}

/** A server that answers each request with the next of `answers`, keeping the requests'
 * headers. */
function serverOf(answers: Response[]) {
  const headers: Headers[] = []
  const fetchStream: typeof fetch = async (_input, init) => {
    headers.push(new Headers(init?.headers))
    const next = answers.shift()
    if (next === undefined) {
      throw new Error("Expected no more requests, got one.")
    }
    return next
  }
  return { fetchStream, headers }
}

describe("followEventStream", () => {
  it("resumes after a dropped connection with the last event id, each event once", async () => {
    // Done means 2: no duplicate or missing event across a disconnect, after the
    // reader's first pause of a second.
    const server = serverOf([
      streamOf([progress(1), progress(2), progress(3)], "drops"),
      streamOf([progress(4), progress(5), progress(6)], "closes"),
    ])
    const stopped = new AbortController()
    const received: StreamedEvent[] = []

    const following = followEventStream({
      url: STREAM,
      signal: stopped.signal,
      fetchStream: server.fetchStream,
      onEvent: (event) => {
        received.push(event)
        if (event.id === "6") {
          stopped.abort()
        }
      },
    })
    await following

    expect(received.map((event) => event.id)).toEqual([
      "1",
      "2",
      "3",
      "4",
      "5",
      "6",
    ])
    expect(received[0]).toEqual({
      id: "1",
      event: "progress",
      data: '{"percent": 10}',
    })
    expect(server.headers.map((sent) => sent.get("Last-Event-ID"))).toEqual([
      null,
      "3",
    ])
  })

  it("resumes from the event id it was given", async () => {
    const server = serverOf([streamOf([progress(8)], "closes")])
    const stopped = new AbortController()

    await followEventStream({
      url: STREAM,
      lastEventId: "7",
      signal: stopped.signal,
      fetchStream: server.fetchStream,
      onEvent: () => stopped.abort(),
    })

    expect(server.headers[0].get("Last-Event-ID")).toBe("7")
  })

  it("skips comments, joins data lines, and reads line breaks split across reads", async () => {
    const server = serverOf([
      streamOf(
        [
          ": ping\n\n",
          "data: first\ndata: second\n\n",
          "data: x\r",
          "\nevent: y\r\n\r\n",
          "event: empty\n\n",
          "data:tight\n\n",
        ],
        "closes"
      ),
    ])
    const stopped = new AbortController()
    const received: StreamedEvent[] = []

    await followEventStream({
      url: STREAM,
      signal: stopped.signal,
      fetchStream: server.fetchStream,
      onEvent: (event) => {
        received.push(event)
        if (received.length === 3) {
          stopped.abort()
        }
      },
    })

    expect(received).toEqual([
      { id: undefined, event: "message", data: "first\nsecond" },
      { id: undefined, event: "y", data: "x" },
      { id: undefined, event: "message", data: "tight" },
    ])
  })

  it("never counts an event the connection dropped halfway through", async () => {
    const server = serverOf([
      streamOf([progress(1), "event: progress\nid: 2\ndata: {}"], "drops"),
      streamOf([progress(2)], "closes"),
    ])
    const stopped = new AbortController()
    const received: (string | undefined)[] = []

    const following = followEventStream({
      url: STREAM,
      signal: stopped.signal,
      fetchStream: server.fetchStream,
      onEvent: (event) => {
        received.push(event.id)
        if (event.id === "2") {
          stopped.abort()
        }
      },
    })
    await following

    expect(received).toEqual(["1", "2"])
    expect(server.headers[1].get("Last-Event-ID")).toBe("1")
  })

  it("tries again after the server failed, as while it restarts", async () => {
    const server = serverOf([
      new Response(null, { status: 502 }),
      streamOf([progress(1)], "closes"),
    ])
    const stopped = new AbortController()
    const received: (string | undefined)[] = []

    await followEventStream({
      url: STREAM,
      signal: stopped.signal,
      fetchStream: server.fetchStream,
      onEvent: (event) => {
        received.push(event.id)
        stopped.abort()
      },
    })

    expect(received).toEqual(["1"])
    expect(server.headers).toHaveLength(2)
  })

  it("stops when the server refuses the stream", async () => {
    const server = serverOf([new Response(null, { status: 401 })])

    await followEventStream({
      url: STREAM,
      signal: new AbortController().signal,
      fetchStream: server.fetchStream,
      onEvent: () => {
        throw new Error("Expected no event from a refused stream.")
      },
    })

    expect(server.headers).toHaveLength(1)
  })
})
