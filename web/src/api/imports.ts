import { queryOptions, useMutation } from "@tanstack/react-query"
import { useState } from "react"
import { z } from "zod"
import { api, queryClient } from "./client"
import { jobsQuery } from "./jobs"
import { ApiProblem, answer } from "./problems"
import type { components, paths } from "./schema"

/** A profile the wizard offers, a preset or one the trader saved. */
export type ListedProfile = components["schemas"]["ListedProfile"]
/** A profile as the server gives it. */
export type ImportProfile = components["schemas"]["ImportProfile-Output"]
/** A profile as the server takes it, which a profile it gave is too. */
export type GivenProfile = components["schemas"]["ImportProfile-Input"]
export type NewInstrument = components["schemas"]["NewInstrument-Input"]
export type ColumnMapping = components["schemas"]["ColumnMapping"]
export type UploadedFile = components["schemas"]["UploadedFile"]
/** What the wizard asks a preview: a file's table, or what its import would do. */
export type PreviewAsked =
  paths["/v1/imports/preview"]["post"]["requestBody"]["content"]["application/json"]
/** What the wizard asks to import. */
export type ImportAsked =
  paths["/v1/imports"]["post"]["requestBody"]["content"]["application/json"]
export type ImportPreviewAnswer = components["schemas"]["ImportPreviewAnswer"]
export type TablePreview = components["schemas"]["TablePreview"]
export type FileSeen = components["schemas"]["FileSeen"]
export type BatchSeen = components["schemas"]["BatchSeen"]
export type MergeSeen = components["schemas"]["MergeSeen"]

/** The presets, then the profiles saved under `profiles/`, read again once an import ends,
 * since it may keep one. */
export const importProfilesQuery = queryOptions({
  queryKey: ["import-profiles"],
  queryFn: async () => answer(await api.GET("/v1/import-profiles")),
})

/** A file the server would not keep, such as one past the upload limit, in its words. */
export type FileRefused = Readonly<{ name: string; message: string }>

/** The files copied into FEAT's folder, and those the server refused. */
export type FilesCopied = Readonly<{
  uploads: readonly UploadedFile[]
  refused: readonly FileRefused[]
}>

/** Copy the files the trader chose into FEAT's folder on this PC, for the wizard to read, one
 * after another, counting those `copied`: each sent as its request's body, which the typed
 * body's placeholder hands over unchanged; a file the server refuses is set aside with why,
 * and the others are copied still (D-102). */
export function useUploads() {
  const [copied, setCopied] = useState(0)
  const mutation = useMutation({
    mutationFn: async (files: readonly File[]): Promise<FilesCopied> => {
      setCopied(0)
      const uploads: UploadedFile[] = []
      const refused: FileRefused[] = []
      for (const file of files) {
        try {
          uploads.push(await uploaded(file))
        } catch (error) {
          if (!(error instanceof ApiProblem)) {
            throw error
          }
          refused.push({ name: file.name, message: error.message })
        }
        setCopied((count) => count + 1)
      }
      return { uploads, refused }
    },
  })
  return { ...mutation, copied }
}

async function uploaded(file: File): Promise<UploadedFile> {
  return answer(
    await api.POST("/v1/uploads", {
      params: { query: { name: file.name } },
      body: "",
      bodySerializer: () => file,
      headers: { "Content-Type": "application/octet-stream" },
    })
  )
}

/** What `asked` finds, read by the server's executor while the request waits; a request the
 * page no longer needs still runs to its end there, so it is never cancelled here. */
export async function previewOf(
  asked: PreviewAsked
): Promise<ImportPreviewAnswer> {
  return answer(await api.POST("/v1/imports/preview", { body: asked }))
}

/** Queue the import of `asked` as a job, which the jobs drawer follows. */
export function useImportStart() {
  return useMutation({
    mutationFn: async (asked: ImportAsked) =>
      answer(await api.POST("/v1/imports", { body: asked })),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: jobsQuery.queryKey }),
  })
}

const writtenDataset = z.object({
  dataset: z.object({
    provider: z.string(),
    schema_name: z.string(),
    root: z.string(),
  }),
  records_added: z.number(),
  records_held: z.number(),
  records_taken: z.number(),
})

const notImported = z.object({
  upload_id: z.string().nullable(),
  file_name: z.string(),
  message: z.string(),
})

/** What a round of several files did with them (D-102): how many it imported, how many were
 * imported before, and the files it left out, with why, the first 50 beside their total. */
const roundFiles = z.object({
  files_imported: z.number(),
  files_imported_before: z.number(),
  not_imported: z.array(notImported),
  not_imported_total: z.number(),
})

/** An import job's result, which the OpenAPI document does not type
 * (`fefat_app.jobs.imports`): what it wrote into each dataset, none where a batch held nothing
 * FEAT stores, and what it kept for the next file; or that the file was imported before; and
 * for a round of several files, what it did with each (`round`). */
export const importResult = z.discriminatedUnion("kind", [
  z.object({
    kind: z.literal("wrote"),
    datasets: z.array(writtenDataset),
    instrument_saved: z.boolean(),
    profile_kept: z.boolean(),
    profile_refusal: z.string().nullable(),
    round: roundFiles.optional(),
  }),
  z.object({
    kind: z.literal("imported_before"),
    round: roundFiles.optional(),
  }),
])

export type ImportResult = z.infer<typeof importResult>
export type DatasetWritten = z.infer<typeof writtenDataset>
export type RoundFiles = z.infer<typeof roundFiles>
