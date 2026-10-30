# Tastoria: photo-led food motion

User direction: bolder design, larger beautiful real food photography, 3D animation, original logo; no image generation or AI food imagery.

References inspected (ideas only; layouts/code/images not copied):
- https://github.com/codrops/3DCarousel — README and js/index.js, CSS perspective, rotateY + translateZ composition, motion responding to interaction. MIT.
- https://github.com/codrops/RotatingOnScrollAnimations — image rotation and depth on scroll. MIT.
- https://github.com/Dieg0arc/3D-scrolling-practice — README and script.js, transparent Three.js scene, DPR cap, camera/light/resize structure. MIT as described in README.

Implementation: original ceramic plate geometry with real-photo texture; pointer tilt, gentle idle movement, paused when offscreen or tab hidden. Local pinned Three.js r160, MIT license retained in landing/vendor. No external CDN runtime dependency. Accessible motion toggle, system reduced-motion support, static image fallback. Real photo cards use CSS perspective and keyboard focus states; mobile uses native horizontal scrolling.

Identity: bowl + two steam strokes. Palette: chilli orange, lime, cream, dark olive. Removes the asterisk and serif wordmark.

All food photos are sourced photographs; see landing/img/CREDITS.md. Generated images from an earlier cancelled request were not imported or referenced.

## Latest revision
User removed the 3D direction. Removed Three.js, canvas scene, circular plate, floating tags and perspective photo cards. Real photography remains flat. Authentication now uses a responsive split layout on desktop and a focused single-column form on mobile, with password visibility controls.
