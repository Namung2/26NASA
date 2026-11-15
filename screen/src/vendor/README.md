# vendor — 밖에서 가져와 화면에서 그대로 쓰는 코드

이 폴더의 파일은 우리가 쓴 것이 아니다. 고치지 않고 그대로 둔다.

| 파일 | 무엇 | 쓰는 곳 |
|---|---|---|
| `OrbitImages.jsx`, `OrbitImages.css` | 그림이 궤도를 도는 컴포넌트 | 첫 화면의 지도 고르기 (`src/home/main.tsx`) |
| `Galaxy.jsx`, `Galaxy.css` | 별이 깔린 바탕 (WebGL) | 첫 화면에서 지도·시나리오를 고르는 걸음의 배경 (`src/home/main.tsx`) |
| `Topography.jsx`, `Topography.css` | 움직이는 등고선 바탕 (WebGL) | 첫 화면에서 화면(현장/로버)을 고르는 걸음의 배경 |

## 출처와 라이선스

- 받은 곳: React Bits — https://reactbits.dev/ (저장소: https://github.com/DavidHDev/react-bits)
- 저작권: Copyright (c) 2026 David Haz
- 라이선스: MIT + Commons Clause License Condition v1.0 (2026-11-15에 저장소의 LICENSE.md에서 확인)
- 받은 날짜: 2026-11-15 (이철진)

라이선스의 요점(원문이 기준이다):
- 앱·웹사이트·제품의 **일부로** 쓰고, 고치고, 배포할 수 있다.
- 컴포넌트 **그 자체를** 따로 팔거나 다시 나눠 주는 것(단독, 묶음, 옮겨 쓴 판)은 안 된다.
- 저작권 표시와 허락 문구를 사본에 함께 둔다 → 아래에 옮겨 적었다.

그래서 이 폴더에는 **화면이 실제로 쓰는 것만** 둔다. 참고만 한 컴포넌트(Dock, LatticeLoader, ReflectiveCard, AnimatedList, SquishSwitch)는
저장소에 올리지 않는다(`screen/vendor_reference/`, .gitignore). 그것들을 보고 새로 쓴 것이 `src/shared/Dock.tsx`, `src/shared/Loader.tsx`,
첫 화면의 목록·스위치다.

## 허락 문구 (원문)

```
MIT + Commons Clause License Condition v1.0

Copyright (c) 2026 David Haz

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, and distribute the Software as part of an
application, website, or product, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

Commons Clause Restriction

You may use this Software, including for any commercial purpose, so long as you
do not sell, sublicense, or redistribute the components themselves-whether
alone, in a bundle, or as a ported version.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

전체 원문(도구·소리에 관한 조항 포함): https://github.com/DavidHDev/react-bits/blob/main/LICENSE.md
