import { describe, expect, it } from "vitest"
import {
  defaultEntries,
  type ParameterField,
  parameterFields,
  parameterValues,
  typedValue,
} from "./schema-fields"

// The templates' parameter schemas as Pydantic writes them (step 5.2), in the order their code
// declares the parameters.
const BREAKOUT = {
  additionalProperties: false,
  properties: {
    lookback: { default: 12, title: "Lookback", type: "integer" },
    stop_atr: { default: 1.5, title: "Stop Atr", type: "number" },
  },
  title: "strategy_parameters",
  type: "object",
}
const MEAN_REVERSION = {
  additionalProperties: false,
  properties: {
    oversold: { default: 30.0, title: "Oversold", type: "number" },
    long_only: { default: true, title: "Long Only", type: "boolean" },
  },
  title: "strategy_parameters",
  type: "object",
}
const ENTRY_WINDOW = {
  additionalProperties: false,
  properties: {
    side: {
      default: "both",
      enum: ["long", "short", "both"],
      title: "Side",
      type: "string",
    },
    flat_by: { default: "15:05", title: "Flat By", type: "string" },
  },
  title: "strategy_parameters",
  type: "object",
}

describe("parameterFields", () => {
  it("draws every parameter type the templates declare, at its default", () => {
    const fields = [BREAKOUT, MEAN_REVERSION, ENTRY_WINDOW].map(parameterFields)

    expect(fields).toEqual([
      {
        kind: "fields",
        fields: [
          {
            kind: "integer",
            name: "lookback",
            initial: "12",
            description: null,
          },
          {
            kind: "number",
            name: "stop_atr",
            initial: "1.5",
            description: null,
          },
        ],
      },
      {
        kind: "fields",
        fields: [
          {
            kind: "number",
            name: "oversold",
            initial: "30.0",
            description: null,
          },
          {
            kind: "boolean",
            name: "long_only",
            initial: true,
            description: null,
          },
        ],
      },
      {
        kind: "fields",
        fields: [
          {
            kind: "choice",
            name: "side",
            options: ["long", "short", "both"],
            initial: "both",
            description: null,
          },
          {
            kind: "string",
            name: "flat_by",
            initial: "15:05",
            description: null,
          },
        ],
      },
    ])
  })

  it("draws a Literal of one value, and keeps a parameter's description", () => {
    const schema = {
      type: "object",
      properties: {
        session: {
          const: "rth",
          default: "rth",
          description: "Regular hours alone",
        },
      },
    }

    expect(parameterFields(schema)).toEqual({
      kind: "fields",
      fields: [
        {
          kind: "choice",
          name: "session",
          options: ["rth"],
          initial: "rth",
          description: "Regular hours alone",
        },
      ],
    })
  })

  it("draws a strategy without parameters as no fields", () => {
    expect(parameterFields({ type: "object", properties: {} })).toEqual({
      kind: "fields",
      fields: [],
    })
  })

  it("says why it cannot draw a parameter of another shape", () => {
    const nested = {
      type: "object",
      properties: { window: { type: "object", default: { start: "08:30" } } },
    }
    const typeless = {
      type: "object",
      properties: { side: { default: "both" } },
    }
    const outside = {
      type: "object",
      properties: { side: { enum: ["long", "short"], default: "both" } },
    }

    expect([nested, typeless, outside, "nothing"].map(parameterFields)).toEqual(
      [
        {
          kind: "unreadable",
          reason:
            "Expected window with a default of a number, a flag, or a word, got another shape.",
        },
        {
          kind: "unreadable",
          reason:
            "Expected side of a type the form draws, a number, a flag, a word, or one of a few values, got none.",
        },
        {
          kind: "unreadable",
          reason: "Expected the default of side among its values, got both.",
        },
        {
          kind: "unreadable",
          reason:
            "Expected the parameters as an object of named properties, got another shape.",
        },
      ]
    )
  })
})

describe("parameterValues", () => {
  const read = parameterFields(MEAN_REVERSION)
  const fields: readonly ParameterField[] =
    read.kind === "fields" ? read.fields : []

  it("gives each parameter at its default as a run takes it", () => {
    expect(parameterValues(fields, defaultEntries(fields))).toEqual({
      oversold: 30,
      long_only: true,
    })
  })

  it("gives the values entered, and none while a field is refused", () => {
    const entered = new Map(defaultEntries(fields)).set("long_only", false)

    expect([
      parameterValues(fields, new Map(entered).set("oversold", "25.5")),
      parameterValues(fields, new Map(entered).set("oversold", "deep")),
    ]).toEqual([{ oversold: 25.5, long_only: false }, null])
  })
})

describe("typedValue", () => {
  it("reads a whole number, a number, and a word", () => {
    expect([
      typedValue("integer", " 24 ", "12"),
      typedValue("number", "2.0", "1.5"),
      typedValue("number", ".5", "1.5"),
      typedValue("string", "", "15:05"),
    ]).toEqual([
      { kind: "valid", value: 24 },
      { kind: "valid", value: 2 },
      { kind: "valid", value: 0.5 },
      { kind: "valid", value: "" },
    ])
  })

  it("refuses a fraction for a whole number and a word for a number, with what to type", () => {
    expect([
      typedValue("integer", "12.5", "12"),
      typedValue("integer", "", "12"),
      typedValue("number", "wide", "1.5"),
      typedValue("number", "1e999", "1.5"),
    ]).toEqual([
      { kind: "refused", message: "Type a whole number, such as 12." },
      { kind: "refused", message: "Type a whole number, such as 12." },
      { kind: "refused", message: "Type a number, such as 1.5." },
      { kind: "refused", message: "Type a number, such as 1.5." },
    ])
  })
})
