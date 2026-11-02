# Terrain artwork

`terrain-classic.png` is the active terrain atlas. It contains original
AI-generated watercolor-style art created for Unsettled using OpenAI image
generation on 2026-11-01, guided by a user-supplied photo of physical game tiles.
The photo served as a visual reference; it is not bundled with the game.

Six equal square panels appear in this order: wood, brick, wheat / sheep, ore,
desert. The runtime renderer scales each panel into an inset hexagon and adds
sandy shoulders, leaving roads and pieces legible along the edges. Number tokens
are drawn separately by Pygame. Roads, settlements, cities, and dice are original
vector-style shapes drawn directly by the UI, including their facets, shadows,
and die pips; they do not require additional bitmap assets.

`terrain.png` preserves the original full-bleed gouache atlas from the first
version. Both illustrations were generated for this project. No official CATAN
artwork, logos, or card illustrations are bundled.

The perspective view also projects `terrain-classic.png` onto the ground plane.
Rounded forest canopies and sheep use deterministic procedural sphere shading
and material grain; mountain, clay, and dune relief use continuous height fields.
These details are rendered in code and introduce no additional external artwork.
