# Clean visual direction

> This project-specific reference was adapted on 2026-09-03 from the user's supplied clean-design notes. It is optional and applies only after the user approves a clean, minimal, editorial direction.

## Intent

Use whitespace, typography, restrained surfaces, and a tight palette to create a professional interface without making it look like a generic SaaS landing page. Product meaning and usability take priority over any rule here.

## Starting tokens

Treat these as a proposal to review with the user, not fixed project requirements:

```css
--background: #ffffff;
--surface-subtle: #f7f6f2;
--surface: #ffffff;
--border: #e8e6e1;
--text-primary: #0f0e0c;
--text-secondary: #6b6760;
--text-muted: #817d77;
--accent: #1a1a1a;
--accent-hover: #333333;
--on-accent: #ffffff;
```

- Confirm that colors fit TANGLAW-BUHAY's identity and meet contrast requirements before adoption.
- Use an 8px spacing rhythm where practical, without forcing it when content or existing conventions require otherwise.
- Prefer restrained radii around 8–12px, subtle 1px borders, and shadows used only to clarify elevation.
- Use a centered content width appropriate to the screen instead of applying a landing-page maximum to every operational view.

## Typography

- Establish a clear display, heading, body, label, and data hierarchy.
- Prioritize readability, Filipino and English character coverage when required, predictable loading, and suitable fallbacks.
- Do not add a hosted font or new font package without approval.
- Avoid oversized display text when it competes with essential operational information.

## Components

- Choose navigation, tabs, cards, tables, forms, steps, maps, and status treatments because the information requires them.
- Use inline or project-standard SVG icons when icons improve recognition. Never use an icon without an accessible name when the meaning is not also conveyed by text.
- Give every interactive element clear default, hover, active, focus, disabled, loading, and error behavior as applicable.
- Do not add marketing sections such as social proof, testimonials, pricing, or logo marquees unless they are explicit requirements.

## Motion

- Motion is optional. Prefer small state transitions and feedback over decorative animation.
- Avoid hiding essential content behind scroll-reveal behavior.
- Provide a `prefers-reduced-motion` path that removes nonessential movement.
- Verify that motion does not delay tasks or presentation walkthroughs.

## Responsive and accessible quality floor

- Review at representative phone, tablet, and desktop widths chosen for the actual users.
- Preserve keyboard navigation, visible focus, sufficient contrast, readable sizing, meaningful labels, and logical source order.
- Do not rely on color alone to communicate severity or status.
- Plan empty, loading, success, validation, error, offline, and permission states when relevant to the approved slice.

## Avoid generic decoration

- No fashionable gradient, blob, marquee, numbered step, oversized icon, or excessive rounded card unless it communicates something specific.
- Keep the palette deliberate and limited, but allow semantic colors for status, warning, danger, and success.
- Use one memorable visual idea only when the user approves it and it improves recognition or comprehension.

