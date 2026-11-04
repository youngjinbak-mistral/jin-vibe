# Parenting - 가족의 하루를 지켜라

A tiny pixel-art web game about keeping your family happy. You play a father or a mother alone at home with the baby from 6 AM to midnight. When your spouse comes home at 6 PM, their needs pile on top of the baby's, so you have to prioritize.

- Move with WASD or the arrow keys. Press `E` near a station (kitchen, changing table, toy box, front door) to pick up its item, then press `E` near the baby or your spouse to fulfill their request. Press `E` on empty floor to drop the item you are holding; dropped items can be picked up again. `Q` remains an optional shortcut, but is no longer advertised in the on-screen controls. Press `E` on a dirty spot to clean the room.
- Each uncleaned floor stain drains 0.4 happiness per second, starting with the first stain. High-contrast stains have cleanup markers; the HUD shows the stain count, drain rate, and happiness percentage. Cleaning removes that stain's drain and restores 3 happiness.
- Characters use alternating footfalls paced by actual distance moved, with a neutral idle pose when stopped or blocked. Dad has softer glasses and a smiling face; the toy is a teddy bear.
- Baby bubbles speak directly: “배고파!”, “졸려”, “기저귀 축축해”, “놀아 줘!”, and “씻겨 줘!”. Partner dialogue stays separate.
- Every request (밥 hungry, 기저귀 wet diaper, 장난감 bored, 잠 sleepy, 장보기 groceries, 대화 talk, 휴식 rest) has a random timer shown in the bubble above the character. Let it expire and the family happiness bar on top drops. At zero, it's game over.
- The spouse comes home at 18:00. Complete the visible evening checklist: bring a towel from the bath station to wash the baby (18:30), bring dinner to your partner (19:00), clear all floor stains after 20:00, put the baby to bed after 21:00, and soothe her back to sleep when she wakes after 22:00. Timed routine requests retry after a miss; missing them still costs happiness.
- Regular requests have 18–28 seconds to act; evening routine requests have 24–34 seconds. Concurrent baby and partner requests make prioritization important.
- Direction, action, and drop buttons support touch or mouse input, including holding a direction while tapping an action. Press `P`/`Esc` or the pause button to take a break. Switching tabs or losing focus pauses automatically; resume explicitly when ready.
- Reach midnight (24:00) with happiness above zero, every checklist task complete, a clean floor, and the baby asleep for the ending screen with both supplied family photos: "오늘 하루도 무사히 이겨낸 거 축하해! 매일의 도전을 더 즐겁게 맞이하자."
- One day lasts 8 real minutes (06:00 → 24:00). Press `R`, `E`, or the action button on the ending/game-over screen to choose a parent and play again.

## Play locally

Open `Parenting-game/index.html` in any modern browser. There is no build step, server requirement, runtime dependency, or external asset request.

## Hosting

If GitHub Pages serves the repository root, the game is at `/Parenting-game/`.

## Files

- `index.html` - canvas shell (960x540 backing store for a 480x270 logical scene, scaled to fill the window, pixelated)
- `assets.js` - hand-coded pixel sprites (father with glasses and light shorts, mother with long hair and jeans, baby girl in a dark outfit with a light collar, items, icons) inspired by the reference photo
- `game.js` - game loop, needs/timers, happiness, clock, day/night sky, screens, WebAudio sound effects
- `assets/family-photo.jpg`, `assets/family-portrait.jpg` - both supplied family photos, resized with orientation applied and metadata removed; shown without stretching on the ending screen
- `game.test.cjs` - deterministic Node tests with a stubbed DOM/canvas; covers input, item delivery, request timing, evening routines, win/loss, and restart

## Verification

Run from the repository root using Node 18 or newer:

```sh
node --check Parenting-game/assets.js
node --check Parenting-game/game.js
node --test Parenting-game/game.test.cjs
```

These tests exercise the game loop without a browser and do not replace browser/device visual and audio checks.

## Credits

- Game engine, photo-inspired pixel sprites, and tests: Vibe
- Image-reference inspection: image analysis tool. No callable GLM, ML4, Claude-opus, or GPT-sol delegation tool was available for this update.
- Reference family photo: provided by the repo owner
