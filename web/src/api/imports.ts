import { queryOptions, useMutation } from "@tanstack/react-query"
import { z } from "zod"
import { api, queryClient } from "./client"
import { jobsQuery } from "./jobs"
import { answer } from "./problems"
import type { components, paths } from "./schema"

/** A profile the wizard offers, a preset or one the trader saved. */
export type ListedProfile = components["schemas"]["ListedProfile"]
/** A profile as the server gives it. */
export type ImportProfile = components["schemas"]["ImportProfile-Output"]
/** A profile as the server takes it, which a profile it gave is too. */
export type GivenProfile = components["schemas"]["ImportProfile-Input"]
export type NewInstrument = components["schemas"]["NewInstrument-Input"]
export type FileLayout = components["schemas"]["FileLayout"]
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
export type DatasetMerge = components["schemas"]["DatasetMerge"]

/** The presets, then the profiles saved under `profiles/`, read again once an import ends,
 * since it may keep one. */
export const importProfilesQuery = queryOptions({
  queryKey: ["import-profiles"],
  queryFn: async () => answer(await api.GET("/v1/import-profiles")),
})

/** Copy a file the trader chose into FEAT's folder on this PC, for the wizard to read: sent
 * as the request's body, which the typed body's placeholder hands over unchanged. */
export function useUpload() {
  return useMutation({
    mutationFn: async (file: File) =>
      answer(
        await api.POST("/v1/uploads", {
          params: { query: { name: file.name } },
          body: "",
          bodySerializer: () => file,
          headers: { "Content-Type": "application/octet-stream" },
        })
      ),
  })
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
  new_sessions: z.number(),
})

/** An import job's result, which the OpenAPI document does not type
 * (`fefat_app.jobs.imports`): what it wrote into each dataset, or that the file was imported
 * before. */
export const importResult = z.discriminatedUnion("kind", [
  z.object({
    kind: z.literal("wrote"),
    datasets: z.array(writtenDataset).min(1),
    instrument_saved: z.boolean(),
    profile_kept: z.boolean(),
  }),
  z.object({ kind: z.literal("imported_before") }),
])

export type ImportResult = z.infer<typeof importResult>
export type DatasetWritten = z.infer<typeof writtenDataset>
