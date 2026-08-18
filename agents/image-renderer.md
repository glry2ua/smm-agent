---
description: Renders the GPT Image 2 prompt for a polished vertical social-media visual
model: gpt-image-2
---
Create one polished vertical social-media image for a San Jose real-estate brand.

ART DIRECTION
- Premium editorial design inspired by an established local luxury-property advisor.
- Warm ivory, charcoal, muted bronze, and restrained navy palette.
- Generous negative space and a precise grid.
- Refined high-contrast serif headline paired with a clean sans-serif.
- Photorealistic architecture or neighborhood imagery with natural California light.
- Sophisticated and approachable, never flashy, generic, or stock-template-like.

CONTENT
- Visual type: {{visual_type}}
- Reference policy: {{reference_policy}}
- Subject: {{subject}}
- Setting: {{setting}}
- Composition: {{composition}}
- Render this exact headline once: {{headline}}
- Render this exact supporting text at most once: {{supporting_text}}
- Must include: {{must_include}}

VERIFIED BUSINESS DETAILS TO RENDER
{{business_details}}
- Render only the fields listed above, verbatim. Do not normalize, shorten, or invent values.

REFERENCE MATERIAL
- Supplied images, in exact attachment order:
{{references}}
- Treat each reference only according to its role. A headshot controls the Realtor's identity; a
  headshot-group controls the identities and relationship of the Realtor and clients; an indoor or
  outdoor reference controls the setting and architecture; the logo controls only the brand mark.
- When identity and setting references are both supplied, place the referenced person or group
  naturally into the referenced setting without changing their identity or the setting's
  recognizable details.
- Use only the references that support the requested subject. Preserve recognizable property,
  neighborhood, and identity details instead of replacing them with generic approximations.
- Integrate the source photography into one cohesive editorial design; do not make a contact sheet,
  before-and-after layout, or arbitrary collage.

CONSTRAINTS
- Portrait 2:3 composition with safe margins for cross-channel cropping.
- Do not add any text beyond the headline, supporting text, and verified business details above.
- Do not invent prices, statistics, awards, testimonials, contact details, names, or logos.
- If the reference policy is outdoor-exact, headshot-exact, or group-exact, use each matching
  role-labeled supplied reference as the exact source for its assigned role. Do not substitute a
  generic scene, person, camera angle, or architectural arrangement.
- {{people_constraint}}
- Keep all text crisp, correctly spelled, and comfortably legible on a phone.
- Avoid: {{avoid}}