---
name: domain-driven-development-codegen
description: Applies Domain-Driven Development (DDD) to generated code with clear bounded contexts, rich domain models, aggregate boundaries, domain services, repository interfaces, and domain-focused tests. Use when implementing new business logic, refactoring transaction scripts/anemic models, or when the user mentions DDD, domain models, aggregates, invariants, repositories, or ubiquitous language.
---

# Domain-Driven Development Code Generation

## Use when

Use this skill when:
- The task introduces or changes business rules.
- The user requests DDD, clean architecture, rich domain models, or better domain boundaries.
- Existing code mixes business logic into controllers, handlers, routes, or persistence layers.
- You need to refactor while preserving behavior.
- CRUD endpoints must represent meaningful domain behavior, not just data shuffling.

Do not use this skill for:
- Pure infrastructure work (logging setup, CI, formatting, build scripts).
- Thin adapters with no domain decisions.
- Tiny one-off scripts where DDD structure would add friction without value.

## Scope

This skill helps generate implementation-ready code that:
- Starts with domain discovery.
- Keeps domain logic in entities, value objects, aggregates, and domain services.
- Uses application services for orchestration and transaction boundaries.
- Defines repositories as domain interfaces (ports), with persistence deferred to infrastructure adapters.
- Uses explicit ubiquitous language in names.
- Adds tests focused on domain behavior and invariants.
- Preserves behavior when refactoring legacy code toward DDD.

### Non-goals

This skill does **not**:
- Force heavyweight DDD patterns everywhere.
- Assume a specific framework, ORM, event bus, or folder layout beyond portable conventions.
- Require introducing domain events or separate services when simple in-aggregate logic is sufficient.
- Rewrite unrelated modules during focused changes.

## Execution workflow

Follow this sequence before and during code generation.

### 1) Domain discovery first

Identify and write down:
- **Bounded context**: What business area is changing?
- **Entities**: Objects with identity and lifecycle.
- **Value objects**: Immutable concepts defined by attributes.
- **Aggregates** and **aggregate root**: Consistency boundary and command entry point.
- **Invariants**: Rules that must always hold true.
- **Domain actions**: Business operations expressed in ubiquitous language.
- **Domain events** (optional): Facts worth publishing after state changes.

If discovery is ambiguous, make the safest minimal assumption and keep boundaries explicit.

### 2) Define boundaries and responsibilities

Separate by intent:
- **Domain layer**: Business rules, invariants, state transitions.
- **Application layer**: Use-case orchestration, transactions, authorization checks, mapping I/O to domain calls.
- **Infrastructure layer**: Persistence, messaging, APIs, framework adapters.

Rule: no core business rule should live in controllers/handlers/repos/ORM models.

### 3) Model behavior, not just data

Implement:
- Entities/value objects with behavior methods that enforce invariants.
- Aggregate root methods for state-changing commands.
- Domain services only when logic spans multiple aggregates or does not belong to a single entity/value object.

Avoid setter-heavy objects that rely on external scripts for decisions.

### 4) Define repository interfaces in domain

Create repository interfaces as domain contracts, for example:
- `OrderRepository` in domain/application boundary.
- Methods named by domain intent (`save`, `by_id`, `active_for_customer`), not table mechanics.

Implement persistence adapters later/infrastructure, without leaking ORM/query details into domain.

### 5) Add application service orchestration

Use application services to:
- Load aggregates.
- Invoke domain behavior.
- Persist updated aggregates through repository interfaces.
- Emit domain events (if used).
- Return DTOs/view models for adapters.

Keep them thin; they coordinate, not decide business rules.

### 6) Refactor safely toward DDD

When refactoring existing code:
- Preserve external behavior and contracts first.
- Move business rules from handlers/controllers into domain objects/services incrementally.
- Keep old entry points delegating to new domain methods until migration is complete.
- Add characterization tests before major moves if behavior is unclear.

### 7) Add domain-focused tests

Prioritize tests that prove:
- Invariants are enforced.
- Invalid transitions fail clearly.
- Valid transitions produce correct domain state/events.
- Application service orchestration calls domain and repositories correctly.

Prefer fast unit tests for domain logic; add a few integration tests for repository adapters.

## File/module organization conventions (framework-agnostic)

Use a structure equivalent to:

- `domain/`
  - `entities/`
  - `value_objects/`
  - `aggregates/`
  - `services/` (domain services only when needed)
  - `events/`
  - `repositories/` (interfaces/ports)
- `application/`
  - `services/` (use-case orchestration)
  - `commands_queries/` (optional)
  - `dto/` (optional)
- `infrastructure/`
  - `persistence/` (repo implementations)
  - `messaging/`
  - `web/` or `api/` adapters
- `tests/`
  - `domain/`
  - `application/`
  - `infrastructure/` (selected integrations)

If the repository already uses different top-level names, map these roles to existing structure instead of forcing renames.

## Decision rules for common trade-offs

### CRUD-heavy request vs rich model

- If request is simple data capture with no business rules: keep it simple, but still isolate domain vocabulary.
- If there are business rules (status transitions, limits, approvals, pricing, lifecycle): encode them as domain behavior, not service/handler `if` chains.
- If CRUD endpoint starts gaining rule branches, promote logic into aggregate/entity methods immediately.

### Application service vs domain service

Use **application service** when:
- Coordinating repositories, transactions, external services, or multiple steps of a use case.
- Translating input/output between adapters and domain.

Use **domain service** when:
- Business decision logic does not naturally belong to one entity/value object.
- Logic spans multiple aggregates but remains pure domain logic.

Default: prefer entity/value-object behavior first; introduce domain service only when justified.

### Domain events vs direct calls

Use domain events when:
- A completed domain action should trigger independent follow-up behaviors.
- You need decoupled reactions across modules/contexts.

Avoid events when:
- A direct in-process call is simpler and coupling is acceptable.
- Event plumbing adds more complexity than value for the current scope.

### DDD complexity threshold

Do **not** introduce extra complexity when:
- No meaningful invariant or lifecycle exists.
- The operation is a straightforward pass-through with negligible domain logic.
- Team/project constraints require minimal implementation.

Apply the lightest DDD pattern that protects business rules.

## Anti-patterns to avoid

- Business rules in controllers/handlers/routes.
- Anemic entities used only as DTO containers.
- Repositories exposing DB/ORM internals in domain contracts.
- Aggregate methods that allow invariant violations.
- Generic names (`processData`, `itemService`, `manager`) instead of domain terms.
- God services containing all business behavior.
- Over-splitting tiny modules with no domain payoff.
- Refactors that silently change behavior without tests.

## Output checklist (must satisfy before finishing)

- [ ] Bounded context is explicit.
- [ ] Entities, value objects, and aggregate root are identified where relevant.
- [ ] Core invariants are enforced in domain code.
- [ ] Business rules are not implemented in controllers/handlers.
- [ ] Repository contracts are domain interfaces; infra details are isolated.
- [ ] Naming follows ubiquitous language from the problem domain.
- [ ] Refactor preserves behavior (or explicitly documents intentional changes).
- [ ] Tests cover domain behavior and invariants.
- [ ] Solution is no more complex than needed.

## Examples

### Good (DDD-aligned)

```python
# domain/aggregates/order.py
class Order:
    def __init__(self, order_id, lines, status="draft"):
        self.order_id = order_id
        self.lines = list(lines)
        self.status = status

    def confirm(self):
        if not self.lines:
            raise ValueError("Order cannot be confirmed without lines")
        if self.status != "draft":
            raise ValueError("Only draft orders can be confirmed")
        self.status = "confirmed"
```

Why good:
- Invariants live in the aggregate.
- State transition is explicit and guarded.
- Domain language (`confirm`, `draft`, `confirmed`) is clear.

### Bad (transaction script / anemic model)

```python
# api/orders_handler.py
def confirm_order(order_id, repo):
    row = repo.get(order_id)
    if len(row["lines"]) == 0:
        return {"error": "invalid"}
    if row["status"] == "draft":
        row["status"] = "confirmed"
        repo.update(row)
    return row
```

Why bad:
- Business rules live in handler/adaptor layer.
- Domain model is missing; data row is manipulated directly.
- Persistence and business logic are tightly coupled.

## Final validation rubric (mental pre-flight)

Score each 0-2 (0 = weak, 1 = acceptable, 2 = strong). Target total: 8+.

1. **Domain correctness**
   - Are invariants, transitions, and domain rules encoded in domain objects/services?
2. **Boundary clarity**
   - Are domain, application orchestration, and infrastructure concerns clearly separated?
3. **Naming quality**
   - Do modules, methods, and types reflect ubiquitous language rather than technical jargon?
4. **Test coverage of domain rules**
   - Do tests verify business behavior/invariants, not only happy-path transport logic?
5. **Simplicity vs overengineering**
   - Is DDD depth proportional to business complexity, avoiding unnecessary patterns?
