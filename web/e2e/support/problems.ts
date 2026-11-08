/** A refusal worded the way the server words one (application/problem+json), for a request a
 * spec answers itself with `route.fulfill`. */
export function problemAnswer(status: number, detail: string) {
  return {
    status,
    contentType: "application/problem+json",
    body: JSON.stringify({
      type: "about:blank",
      title: "Refused for this test",
      status,
      detail,
      instance: "/",
      request_id: "e2e",
    }),
  }
}
