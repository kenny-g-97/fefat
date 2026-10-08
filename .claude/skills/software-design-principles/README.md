## Software Design Principles Skill

Professional object-oriented design patterns and principles for maintainable, well-structured code.

## What This Skill Provides

Comprehensive design guidance including:
- **Object Calisthenics** - 9 rules for clean OO code
- **Feature Envy Detection** - Identifying and fixing misplaced methods
- **Dependency Inversion** - Injection over instantiation
- **Fail-Fast Error Handling** - Explicit validation over silent fallbacks
- **Intention-Revealing Naming** - Domain language over generic terms (no data/utils/helpers)
- **Type-Driven Design** - Making illegal states unrepresentable

## When to Use

### Auto-Activation
Activates during code refactoring, design reviews, or architecture discussions.

### Explicit Activation
- "Review this code's design"
- "Check for feature envy"
- "Apply object calisthenics"
- "Improve naming in this file"

## Key Principles

### Object Calisthenics (9 Rules)
1. One level of indentation per method
2. Don't use ELSE keyword
3. Wrap all primitives and strings
4. First class collections
5. One dot per line
6. Don't abbreviate
7. Keep all entities small
8. No more than two instance variables
9. No getters/setters/properties

### Dependency Inversion
❌ `const service = new Service()` (tight coupling)
✓ `this.service.doWork()` (injected dependency)

### Fail-Fast
❌ `value ?? backup ?? 'unknown'` (silent fallback)
✓ `if (!value) throw new Error(...)` (explicit validation)

### Naming
❌ `data`, `utils`, `helpers`, `manager`, `processor`
✓ Use domain-specific, intention-revealing names

## Integration

### With TDD Process
Automatically applied during **REFACTOR** state:
- Checks object calisthenics compliance
- Detects feature envy
- Verifies dependency injection
- Validates naming conventions

TDD Process rules that implement these principles:
- **Rule #8**: Fail-fast error handling
- **Rule #9**: Dependency inversion

### Standalone
Use for design reviews, refactoring sessions, or architecture planning without TDD workflow.

## Example: Before and After

### Before (Violates Principles)
```typescript
// Feature envy, generic names, hard dependencies, silent fallbacks
class DataProcessor {
  process(data: any): any {
    const validator = new Validator()  // Hard dependency
    const result = data.value ?? 'unknown'  // Silent fallback
    return validator.process(result)  // Feature envy
  }
}
```

### After (Follows Principles)
```typescript
// Clear responsibilities, domain names, injected dependencies, fail-fast
class OrderTotalCalculator {
  constructor(private taxCalculator: TaxCalculator) {}  // Injected

  calculateTotal(order: Order): Money {
    if (!order.subtotal) {
      throw new Error(
        `Expected order.subtotal to exist, got ${order.subtotal}. ` +
        `Order ID: ${order.id}`
      )
    }

    return this.taxCalculator.applyTax(
      order.subtotal,
      order.taxRate
    )
  }
}
```

## Checklist

When reviewing code, verify:
- [ ] Object calisthenics: Code follows 9 rules
- [ ] Feature envy: Methods in correct classes
- [ ] Dependencies: Injected, not instantiated
- [ ] Errors: Fail-fast with clear messages
- [ ] Naming: Intention-revealing, domain-specific
- [ ] Types: Illegal states impossible, no `any`

## When NOT to Apply

Some exceptions are acceptable:
- Value objects/DTOs may have multiple fields
- Simple scripts don't need full dependency injection
- Configuration objects can have getters
- Test code can be less strict
- Library integration may need type assertions

Use judgment - principles serve quality, not dogma.

## Directory Structure

```
software-design-principles/
├── SKILL.md          # Complete design principles guide
└── README.md         # This file
```

## Installation

Symlink to Claude skills directory:

```bash
ln -s /path/to/claude-skillz/software-design-principles ~/.claude/skills/software-design-principles
```

## Version

1.0.0
