---
name: frontend-design
description: Collaboratively plan, review, and implement intentional frontend UI after clarifying the next scoped goal and obtaining approval for major UX or visual decisions. Use for new interfaces, page layouts, components, and substantial visual redesigns; do not use for backend-only work.
license: Apache-2.0; see LICENSE.txt
---

# Frontend Design

> Adapted from Anthropic's `frontend-design` skill for the TANGLAW-BUHAY project. This version was modified to require incremental collaboration and explicit approval checkpoints.

Create frontend work that is specific to the product, understandable to its users, accessible, and visually intentional. The user's brief and confirmed decisions always take priority over stylistic defaults.

## Collaboration contract

- First determine whether the user is asking for discussion, inspection, planning, or implementation. Do not modify files when they requested only discussion, inspection, or a proposal.
- Work on one agreed slice at a time. Do not turn a feature discussion into authorization to generate the complete system.
- Ask only the questions needed for the next decision. Before choosing a major feature, information architecture, navigation model, design methodology, framework, dependency, API/data contract, or database implication, explain the options and obtain the user's approval.
- Do not invent missing product requirements, audiences, workflows, or content when the choice could materially affect the result. Surface the gap and ask.
- State small, reversible assumptions. Ask before assumptions that would change product behavior or project direction.
- Preserve the existing stack and design decisions unless the user approves a change.

## Ground the design in the product

Before proposing visuals, establish the next screen or component's:

1. users and context;
2. primary job;
3. essential content and actions;
4. important states, including empty, loading, success, error, and permission states when relevant;
5. accessibility, device, connectivity, and presentation constraints.

Use the product's real domain, vocabulary, and content. Structural devices such as steps, cards, tabs, labels, and dashboards must communicate real relationships rather than decorate the page.

## Incremental workflow

### 1. Inspect

Read the supplied references and the relevant existing implementation. Identify confirmed requirements separately from assumptions and open questions. Do not treat old prototypes as approved requirements unless the user confirms them.

### 2. Clarify the next slice

Ask a small set of focused questions. Confirm what is intentionally out of scope for this slice.

### 3. Propose

Present a compact design direction appropriate to the size of the task. It may include:

- the user flow and content hierarchy;
- a small token proposal for color, type, spacing, shape, and motion;
- a concise layout description or small ASCII wireframe when it improves understanding;
- one distinctive visual idea only when it serves the product.

Explain meaningful tradeoffs. Avoid exhaustive feature lists and avoid selecting an aesthetic solely because it is fashionable.

### 4. Approval checkpoint

Wait for explicit approval before implementing a new screen, substantial layout, navigation model, visual identity, design system, or dependency. Incorporate requested revisions and reconfirm the scoped deliverable.

### 5. Implement only the approved slice

Follow the existing project architecture and conventions. Derive implementation choices from the approved direction. Do not add unrequested pages, features, data models, services, packages, or speculative abstractions.

Keep CSS and component responsibilities understandable. Watch for selector conflicts, duplicated tokens, inaccessible interactive elements, and layout behavior that only works at one viewport.

### 6. Verify and review

Verify the result in proportion to the change. Check relevant viewport sizes, keyboard interaction, visible focus, contrast, readable hierarchy, content states, and reduced-motion behavior. Use screenshots or browser inspection when available and useful.

Report what changed, what was verified, and any remaining decision. Stop before beginning the next major slice.

## Design principles

- Make choices that belong to this product rather than copying a generic SaaS template.
- Let typography, layout, color, and motion have clear roles. More visual effects do not imply higher quality.
- Use hierarchy and whitespace to reduce cognitive load while keeping operational information visible.
- Spend visual boldness in at most one justified place; keep supporting elements disciplined.
- Use motion only when it communicates state, relationship, or feedback. Respect `prefers-reduced-motion`.
- Choose fonts only after considering readability, language coverage, loading, licensing, offline behavior, and the existing stack. Always provide suitable fallbacks.
- Use real interface language. Prefer specific action labels such as "Save changes" over vague labels such as "Submit."
- Keep action names consistent across buttons, confirmations, notifications, and documentation.
- Make errors explain what happened and how the user can recover. Make empty states guide the next useful action.

## Optional clean visual direction

Read [references/clean-design.md](references/clean-design.md) only when the user requests or approves a clean, minimal, editorial visual direction. Treat it as a proposal framework, not permission to choose product features, page sections, fonts, or technologies.

