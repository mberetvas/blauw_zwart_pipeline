# Design System Strategy: The Digital Pitch

## 1. Overview & Creative North Star
The Creative North Star for this design system is **"Stadium Nocturne."** 

We are moving away from the "chat widget" trope and toward a premium, editorial sports experience. The interface should feel like a night match at Jan Breydel: high-contrast, atmospheric, and electric. We achieve this by breaking the traditional chat grid through **intentional asymmetry**, where data-heavy cards overlap conversational bubbles, and **tonal depth** replaces rigid borders. The goal is to blend the authority of a sports broadcast with the sleekness of a high-end lifestyle brand.

## 2. Colors: Tonal Depth & The "No-Line" Rule
The palette is rooted in the deep blues and blacks of Club Brugge, but interpreted through a lens of sophistication.

### The "No-Line" Rule
**Explicit Instruction:** Prohibit 1px solid borders for sectioning. Boundaries must be defined solely through background color shifts. For example, a chat input area (using `surface_container_high`) should sit against the main chat thread (`surface`) without a stroke.

### Surface Hierarchy & Nesting
Treat the UI as physical layers. Depth is achieved by stacking `surface-container` tiers:
- **Base Layer:** `surface` (#0b1326) – The foundation of the chat interface.
- **Sectioning:** `surface_container_low` (#131b2e) – Used for the sidebar or historical chat list.
- **Content Blocks:** `surface_container_highest` (#2d3449) – Reserved for high-priority data cards or product carousels.

### The "Glass & Gradient" Rule
To elevate the "Sporty" vibe, use **Glassmorphism** for floating elements (like the "New Message" toast). Use `surface_variant` at 60% opacity with a 20px backdrop-blur.
- **Signature Textures:** For primary CTAs (e.g., "Buy Kit"), apply a subtle linear gradient from `primary` (#b0c6ff) to `primary_container` (#548dff) at a 135-degree angle. This adds "visual soul" and mimics the sheen of technical sportswear.

## 3. Typography: Editorial Authority
We utilize a hierarchy that balances the aggressive width of a sports headline with the clinical readability of data.

- **Display & Headlines (`spaceGrotesk`):** Used for scorelines, kit prices, and major category headers. The wide tracking and geometric forms convey the "Sporty" energy.
- **Titles & Body (`inter`):** Used for the core chat experience. The transition from a `headline-lg` (Space Grotesk) to a `body-md` (Inter) creates a professional, editorial contrast.
- **Labels (`inter`):** Small, all-caps labels in `label-sm` should be used for data metadata (e.g., "STOCK LEVEL" or "MATCH MINUTE") to maintain a technical, data-focused aesthetic.

## 4. Elevation & Depth
We eschew traditional shadows in favor of **Tonal Layering**.

- **The Layering Principle:** To lift a merchandising card, place a `surface_container_lowest` card on a `surface_container_low` background. This creates a "recessed" or "protruding" look through value shifts rather than drop shadows.
- **Ambient Shadows:** Only use shadows for high-order floating elements (e.g., a zoomed image of a jersey). Use a 32px blur, 8% opacity, tinted with `on_surface` (#dae2fd).
- **The "Ghost Border" Fallback:** If accessibility requires a container edge, use `outline_variant` at 15% opacity. Never use 100% opaque lines.

## 5. Components

### Chat Bubbles
- **User:** `primary_container` background with `on_primary_container` text. 
- **Assistant:** `surface_container_high` background. No borders.
- **Shape:** Use `xl` (0.75rem) roundedness, but keep the "tail" corner at `sm` (0.125rem) for a custom, sharp look.

### Merchandising Cards
- **Structure:** Forbid divider lines. Use `surface_container_highest` for the card background. 
- **Data focus:** Use `title-md` for product names and `primary` color for price points. 
- **Spacing:** Use 24px (1.5rem) of internal padding to let the product photography "breathe."

### Action Chips (Filtering Data)
- **Style:** Pill-shaped (`full` roundedness).
- **Default:** `secondary_container` with `on_secondary_container` text.
- **Active:** `primary` background with `on_primary` text.

### Input Fields
- **Container:** `surface_container_highest`. 
- **Interaction:** On focus, do not use a border. Use a subtle glow effect (ambient shadow) and shift the background color to `surface_bright`.

### Data Visualization (Player Stats/Tables)
- Use `surface_container_lowest` for row backgrounds on alternating items. 
- Use `label-md` for headers to provide a "technical sheet" feel.

## 6. Do’s and Don’ts

### Do
- **Use Asymmetry:** Place the "Club Brugge Assistant" avatar slightly offset or overlapping the header container to break the "boxed-in" feel.
- **Embrace Negative Space:** Allow significant vertical breathing room between chat clusters (use 32px+).
- **Focus on Legibility:** Ensure `on_surface` text always meets WCAG AAA standards against the dark `surface` backgrounds.

### Don’t
- **Don't use Divider Lines:** Never use a horizontal rule to separate chat days or list items. Use a `surface_container_low` background strip or simple whitespace.
- **Don't use Standard Blues:** Stick strictly to the defined `primary` and `primary_container` tokens; avoid "default" HTML/CSS blues.
- **Don't Over-round:** Avoid using `full` roundedness on anything other than buttons and chips. High-end editorial design relies on the tension between soft corners (`xl`) and sharp architectural lines.