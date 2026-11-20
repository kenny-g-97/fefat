import { zodResolver } from "@hookform/resolvers/zod"
import { useForm } from "react-hook-form"
import { z } from "zod"
import {
  type AbandonedMark,
  type IndexedStrategy,
  useAbandonment,
  useReopening,
} from "@/api/strategies"
import { Button } from "@/ui/button"
import { Field, FieldError, FieldLabel } from "@/ui/field"
import { formatInstant } from "@/ui/instant"
import { Panel } from "@/ui/panel"
import { Textarea } from "@/ui/textarea"

/** A strategy marked abandoned (D-29; web/DESIGN.md, Patterns, Abandoned mark), first on its
 * page: when, where it broke, and the lesson; Reopen takes the mark back, which asks nothing
 * more, since the strategy can be marked again. */
export function AbandonedPanel({
  strategy,
  mark,
}: Readonly<{ strategy: IndexedStrategy; mark: AbandonedMark }>) {
  const reopening = useReopening(strategy.id)
  return (
    <Panel
      title="Abandoned"
      description={`Marked on ${formatInstant(mark.abandoned_at)}; its versions stay as they are`}
      action={
        <Button
          variant="ghost"
          disabled={reopening.isPending}
          onClick={() => reopening.mutate()}
        >
          Reopen
        </Button>
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
      {reopening.error !== null && (
        <p role="alert" className="text-negative">
          {reopening.error.message}
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

/** Abandon this strategy, last on its page (web/DESIGN.md, Patterns, Abandoned mark): where it
 * broke and the lesson, so that the library keeps the failure (D-29); the mark labels the
 * strategy and blocks nothing, and Reopen takes it back. */
export function AbandonCard({
  strategy,
}: Readonly<{ strategy: IndexedStrategy }>) {
  const abandonment = useAbandonment(strategy.id)
  const form = useForm({
    resolver: zodResolver(markForm),
    defaultValues: { breaking_point: "", lesson: "" },
    mode: "onTouched",
  })
  const errors = form.formState.errors
  const submit = form.handleSubmit((mark) => abandonment.mutate(mark))
  return (
    <Panel
      title="Abandon this strategy"
      description="Keep where the idea broke and what it taught, so the library holds its failures too"
    >
      <form onSubmit={submit} noValidate className="flex flex-col gap-5">
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
          {abandonment.error !== null && (
            <p role="alert" className="mr-auto text-negative">
              {abandonment.error.message}
            </p>
          )}
          <Button
            type="submit"
            variant="ghost"
            disabled={abandonment.isPending}
          >
            Mark abandoned
          </Button>
        </div>
      </form>
    </Panel>
  )
}
