# Parenting - 가족의 하루를 지켜라

A tiny pixel-art web game about keeping your family happy. You play a father or a mother alone at home with the baby from 6 AM to midnight. When your spouse comes home at 6 PM, their needs pile on top of the baby's, so you have to prioritize.

- Move with WASD or the arrow keys. Press `E` near a station (kitchen, changing table, toy box, front door) to pick up its item, then press `E` near the baby or your spouse to fulfill their request. Press `Q` (or `E` on empty floor) to drop the item you are holding; dropped items can be picked up again. Press `E` on a dirty spot to clean the room.
- Every request (밥 hungry, 기저귀 wet diaper, 장난감 bored, 잠 sleepy, 장보기 groceries, 대화 talk, 휴식 rest) has a random timer shown in the bubble above the character. Let it expire and the family happiness bar on top drops. At zero, it's game over.
- The spouse comes home at 18:00. At night the baby may wake up crying and need to be put back to sleep.
- Survive until midnight (24:00) for the ending screen with the family photo: "오늘 하루도 무사히 이겨낸 거 축하해! 매일의 도전을 더 즐겁게 맞이하자."
- One day lasts 5 real minutes (06:00 → 24:00). Press `R` on the ending/game-over screen to play again.

## Play locally

Open `Parenting-game/index.html` in any modern browser. There is no build step and no dependencies. (Serving with `python3 -m http.server` also works and avoids any `file://` image restrictions.)

## Hosting

If GitHub Pages serves the repository root, the game is at `/Parenting-game/`.

## Files

- `index.html` - canvas shell (960x540 backing store for a 480x270 logical scene, scaled to fill the window, pixelated)
- `assets.js` - hand-coded pixel sprites (father with glasses and light shorts, mother with long hair and jeans, baby girl in a pink onesie, items, icons) inspired by the reference photo
- `game.js` - game loop, needs/timers, happiness, clock, day/night sky, screens, WebAudio sound effects
- `assets/family-photo.jpg` - the shared family photo shown on the ending screen

## Credits

- Orchestration, game engine, pixel sprites: Vibe
- Reference family photo: provided by the repo owner
