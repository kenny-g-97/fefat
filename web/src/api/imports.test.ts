import { describe, expect, it } from "vitest"
import { filesCopied, type UploadedFile } from "./imports"
import { ApiProblem } from "./problems"

function kept(file: File): UploadedFile {
  return {
    id: `0193a000-0000-7000-8000-00000000000${file.size}`,
    name: file.name,
    size: file.size,
    sha256: "0".repeat(64),
    uploaded_at: "2026-11-16T10:00:00Z",
  }
}

describe("filesCopied", () => {
  it("sets aside a file refused or lost on the way, with why, and copies the others", async () => {
    const files = [
      new File(["1"], "ES 03-26.Last.txt"),
      new File(["22"], "ES 06-26.Last.txt"),
      new File(["333"], "ES 09-26.Last.txt"),
      new File(["4444"], "ES 12-26.Last.txt"),
    ]
    let copied = 0

    const result = await filesCopied(
      files,
      async (file) => {
        if (file.size === 2) {
          throw new ApiProblem(413, "Expected a file of 256 MB at most.")
        }
        if (file.size === 3) {
          throw new TypeError("Failed to fetch")
        }
        return kept(file)
      },
      () => {
        copied += 1
      }
    )

    expect(result).toEqual({
      uploads: [kept(files[0]), kept(files[3])],
      refused: [
        {
          name: "ES 06-26.Last.txt",
          message: "Expected a file of 256 MB at most.",
        },
        { name: "ES 09-26.Last.txt", message: "Failed to fetch" },
      ],
    })
    expect(copied).toBe(4)
  })
})
