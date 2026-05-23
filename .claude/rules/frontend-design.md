## Frontend Design Rules — Anti-AI-Slop

### The Test
Before finishing any frontend work: "Would someone immediately know AI made this?"
If yes — REDESIGN. Every interface must feel intentionally designed, not statistically generated.

### Typography
- NEVER use Inter, Roboto, Arial, Open Sans, Space Grotesk, or system defaults
- Choose distinctive, characterful fonts from Google Fonts or Fontshare
- Use fluid type scales with clamp() for responsive sizing
- Strong visual hierarchy — clear distinction between headings, body, captions

### Color & Theme
- ALL colors as CSS variables using oklch() or color-mix()
- Tint neutrals toward brand hue — never pure #000 or #fff
- NEVER: purple-to-blue gradients, cyan-on-dark, neon-on-dark, gradient text
- NEVER use any gradients — commit to solid, intentional colors
- Sharp accent colors with purpose, not decoration

### Layout
- Create visual rhythm through VARIED spacing — never same padding everywhere
- No glassmorphism, no rounded rectangles with generic shadows
- No large icons with rounded corners above every heading
- Prioritize whitespace and breathing room
- CSS Grid and Flexbox — no float hacks

### Components
- Use professional icon libraries: Lucide, Phosphor Icons, or Heroicons
- Animations with Framer Motion — clean, subtle, purposeful
- No skeleton screens everywhere — use them only where loading is >500ms
- Toast notifications: auto-dismiss, non-blocking, minimal

### Before Building ANY Frontend
1. Choose an aesthetic tone (editorial, brutalist, luxury, minimal, etc.)
2. Define one UNFORGETTABLE element someone would remember
3. Each new page/component must be DIFFERENT from previous ones — avoid template repetition
