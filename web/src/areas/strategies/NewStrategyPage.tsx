import { zodResolver } from "@hookform/resolvers/zod"
import { useQuery } from "@tanstack/react-query"
import { useNavigate } from "@tanstack/react-router"
import { useState } from "react"
import { useForm } from "react-hook-form"
import { z } from "zod"
import {
  type StrategyTemplate,
  strategiesQuery,
  strategyTemplatesQuery,
  useStrategyCreation,
} from "@/api/strategies"
import { sentenceCase } from "@/ui/figures"
import { Button } from "@/ui/button"
import { CodeEditor } from "@/ui/code-editor"
import { Field, FieldError, FieldLabel } from "@/ui/field"
import { Input } from "@/ui/input"
import { Page } from "@/ui/page"
import { Panel } from "@/ui/panel"
import { QueryBody } from "@/ui/query-body"
import { Segmented } from "@/ui/segmented"
import { BackLink } from "@/ui/text-link"
import { strategyName } from "./strategy-names"

/** New strategy (step 5.5): a template FEAT ships, its hypothesis and its code, copied whole into
 * a new strategy of the name given, as its version 1, built and saved in the server's executor;
 * the strategy's page opens once it is saved. */
export function NewStrategyPage() {
  const templates = useQuery(strategyTemplatesQuery)
  return (
    <Page
      title="New strategy"
      description="A template copied into your library as a strategy's version 1"
      back={<BackLink to="/strategies">Back to Strategies</BackLink>}
    >
      <QueryBody query={templates}>
        {(offered) => <TemplateCard templates={offered} />}
      </QueryBody>
    </Page>
  )
}

/** The template chosen and the create, which outlives a change of template, so the choice waits
 * while a create runs: the strategy's page opens once it is saved, and a refusal stays with the
 * template it refused. */
function TemplateCard({
  templates,
}: Readonly<{ templates: readonly StrategyTemplate[] }>) {
  const [first] = templates
  if (first === undefined) {
    throw new Error("Expected the templates FEAT ships, got none.")
  }
  const [chosen, setChosen] = useState(first.name)
  const creation = useStrategyCreation()
  const template = templates.find((each) => each.name === chosen)
  if (template === undefined) {
    throw new Error(`Expected the template ${chosen} among FEAT's, got none.`)
  }
  return (
    <Panel
      title="Template"
      description="Its code and hypothesis become the strategy's version 1, which you change once it is saved"
    >
      <div className="flex flex-col gap-5">
        <div>
          <Segmented
            label="Template"
            options={templates.map((each) => ({
              value: each.name,
              label: sentenceCase(each.name),
            }))}
            value={template.name}
            disabled={creation.isPending}
            onChange={(name) => {
              creation.reset()
              setChosen(name)
            }}
            testId="template-choice"
          />
        </div>
        <p className="max-w-3xl text-foreground-secondary">
          {template.hypothesis}
        </p>
        <CodeEditor
          label={`Code of the ${sentenceCase(template.name).toLowerCase()} template`}
          code={template.code}
        />
        <CreateForm
          key={template.name}
          template={template}
          creation={creation}
        />
      </div>
    </Panel>
  )
}

const newStrategyForm = z.object({ name: strategyName })

type CreateFormProps = Readonly<{
  template: StrategyTemplate
  creation: ReturnType<typeof useStrategyCreation>
}>

function CreateForm({ template, creation }: CreateFormProps) {
  const strategies = useQuery(strategiesQuery)
  const navigate = useNavigate()
  const form = useForm({
    resolver: zodResolver(newStrategyForm),
    defaultValues: { name: template.name },
    mode: "onTouched",
  })
  const taken =
    strategies.status === "success"
      ? strategies.data.map((strategy) => strategy.name)
      : []
  const submit = form.handleSubmit(({ name }) => {
    if (taken.includes(name)) {
      form.setError("name", {
        message: `A strategy is already called ${name}. Choose another name.`,
      })
      form.setFocus("name", { shouldSelect: true })
      return
    }
    creation.mutate(
      {
        name,
        code: template.code,
        hypothesis: template.hypothesis,
        changelog: `Created from the ${sentenceCase(template.name).toLowerCase()} template`,
      },
      {
        onSuccess: (saved) =>
          void navigate({
            to: "/strategies/strategy",
            search: { name: saved.name, version: saved.version },
          }),
      }
    )
  })
  const refusal = form.formState.errors.name?.message
  return (
    <form onSubmit={submit} noValidate className="flex flex-col gap-2">
      <div className="flex items-end gap-2">
        <Field data-invalid={refusal !== undefined} className="max-w-xs gap-2">
          <FieldLabel htmlFor="strategy-name">Name</FieldLabel>
          <Input
            id="strategy-name"
            autoComplete="off"
            spellCheck={false}
            aria-invalid={refusal !== undefined}
            {...form.register("name")}
          />
        </Field>
        <Button type="submit" disabled={creation.isPending}>
          Create strategy
        </Button>
      </div>
      <FieldError>{refusal}</FieldError>
      {creation.error !== null && (
        <p role="alert" className="text-negative">
          {creation.error.message}
        </p>
      )}
    </form>
  )
}
