# Life Is Short

A tiny, silent pixel-art dodger for the browser. You play a little office worker in glasses and a suit. Keep moving through a stream of office supplies, documents, files, and AI models in solid form.

- Move with the arrow keys or WASD. On touch screens, hold and drag.
- The hero runs when moving, then types on a laptop or scribbles notes when standing still.
- The setting changes every 10 seconds: office, toilet, lobby, canteen, rooftop, server room, and more.
- Obstacles come in many sizes and speeds, and move in different patterns: bouncing, zigzagging, raining down, orbiting, swarming, boomeranging, walls, dashes with a warning line, and slow giants.
- Every death shows a short quote about using your time well.
- Survive 1 minute and a terrifying cat boss arrives. It shouts `MEOW!` and the letters fly at you. After 20 meows it gives up.

## Play locally

Open `Claude-1st-game/index.html` in any modern browser. There is no build step and no dependencies.

Append `?t=55` to the URL to start close to the boss fight.

## Hosting

If GitHub Pages serves the repository root, the game is at `/Claude-1st-game/`.

## Credits

- Orchestration, game engine, and hero sprite and animation: Vibe
- Obstacle and boss sprites, plus the quote fact-check: Mistral Large 4
- Quotes, the 5x7 bitmap font, and the 12 background scenes: GLM
