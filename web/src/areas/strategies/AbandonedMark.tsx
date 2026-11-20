import { zodResolver } from "@hookform/resolvers/zod"
import { useEffect, useRef } from "react"
import { useForm } from "react-hook-form"
import { z } from "zod"
import type { AbandonedMark, MarkAsked } from "@/api/strategies"
import { Button } from "@/ui/button"
import { Field, FieldError, FieldLabel } from "@/ui/field"
import { InlineConfirmation } from "@/ui/inline-confirmation"
import { formatInstant } from "@/ui/instant"
import { Panel } from "@/ui/panel"
import { Textarea } from "@/ui/textarea"

type AbandonedPanelProps = Readonly<{
  mark: AbandonedMark
  arrived: boolean
  reopening: boolean
  refusal: Error | null
  onReopen: () => void
}>

/** A strategy marked abandoned (D-29; web/DESIGN.md, Patterns, Abandoned mark), first on its
 * page: when, where it broke, and the lesson. Reopen asks once in place, since the mark's words
 * go with it; a mark just made takes the focus, `arrived`, which brings it into view. */
export function AbandonedPanel({
  mark,
  arrived,
  reopening,
  refusal,
  onReopen,
}: AbandonedPanelProps) {
  const shown = useRef<HTMLElement>(null)
  useEffect(() => {
    if (arrived) {
      shown.current?.focus()
    }
  }, [arrived])
  return (
    <Panel
      ref={shown}
      tabIndex={-1}
      title="Abandoned"
      description={`Marked on ${formatInstant(mark.abandoned_at)}; Reopen drops these words, the versions stay`}
      action={
        <div className="-my-2">
          <InlineConfirmation
            trigger="Reopen"
            confirm="Reopen now"
            size="default"
            pending={reopening}
            onConfirm={onReopen}
          />
        </div>
      }
    >
      <dl
        data-testid="abandoned-mark"
        className="grid max-w-3xl grid-cols-[9rem_minmax(0,1fr)] gap-x-4 gap-y-3"
      >
        <dt className="text-foreground-secondary">Where it broke</dt>
        <dd className="whitespace-pre-wrap text-foreground">
          {mark.breaking_point}
        </dd>
        <dt className="text-foreground-secondary">Lesson</dt>
        <dd className="whitespace-pre-wrap text-foreground">{mark.lesson}</dd>
      </dl>
      {refusal !== null && (
        <p role="alert" className="text-negative">
          {refusal.message}
        </p>
      )}
    </Panel>
  )
}

const markForm = z.object({
  breaking_point: z
    .string()
    .trim()
    .min(
      1,
      "Say where the strategy broke, such as the year or the cost that undid it."
    ),
  lesson: z.string().trim().min(1, "Say what it taught, for the next idea."),
})

type AbandonCardProps = Readonly<{
  marking: boolean
  refusal: Error | null
  onMark: (mark: MarkAsked) => void
}>

/** Abandon this strategy, last on its page (web/DESIGN.md, Patterns, Abandoned mark): where it
 * broke and the lesson, so that the library keeps the failure (D-29); the mark labels the
 * strategy and blocks nothing, and Reopen takes it back. */
export function AbandonCard({ marking, refusal, onMark }: AbandonCardProps) {
  const form = useForm({
    resolver: zodResolver(markForm),
    defaultValues: { breaking_point: "", lesson: "" },
    mode: "onTouched",
  })
  const errors = form.formState.errors
  return (
    <Panel
      title="Abandon this strategy"
      description="Keep where the idea broke and what it taught, so the library holds its failures too"
    >
      <form
        onSubmit={form.handleSubmit(onMark)}
        noValidate
        className="flex flex-col gap-5"
      >
        <Field
          data-invalid={errors.breaking_point !== undefined}
          className="gap-2"
        >
          <FieldLabel htmlFor="abandon-breaking-point">
            Where it broke
          </FieldLabel>
          <Textarea
            id="abandon-breaking-point"
            aria-invalid={errors.breaking_point !== undefined}
            {...form.register("breaking_point")}
          />
          <FieldError>{errors.breaking_point?.message}</FieldError>
        </Field>
        <Field data-invalid={errors.lesson !== undefined} className="gap-2">
          <FieldLabel htmlFor="abandon-lesson">Lesson</FieldLabel>
          <Textarea
            id="abandon-lesson"
            aria-invalid={errors.lesson !== undefined}
            {...form.register("lesson")}
          />
          <FieldError>{errors.lesson?.message}</FieldError>
        </Field>
        <div className="flex flex-wrap items-center justify-end gap-3">
          {refusal !== null && (
            <p role="alert" className="mr-auto text-negative">
              {refusal.message}
            </p>
          )}
          <Button type="submit" variant="ghost" disabled={marking}>
            Mark abandoned
          </Button>
        </div>
      </form>
    </Panel>
  )
}
