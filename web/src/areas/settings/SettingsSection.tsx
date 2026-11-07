import { useId, type ReactNode } from "react"

type SettingsSectionProps = Readonly<{
  title: string
  description: ReactNode
  children: ReactNode
}>

/** A section of the settings page: its title, what it changes, and its controls, divided
 * from the one above by a hairline. */
export function SettingsSection({
  title,
  description,
  children,
}: SettingsSectionProps) {
  const heading = useId()
  return (
    <section
      aria-labelledby={heading}
      className="flex flex-col gap-4 border-t pt-6 first:border-t-0 first:pt-0"
    >
      <div className="flex flex-col gap-1">
        <h2 id={heading} className="text-base font-medium">
          {title}
        </h2>
        <p className="text-caption text-foreground-secondary">{description}</p>
      </div>
      {children}
    </section>
  )
}
