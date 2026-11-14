// 고정 용량 이진 힙 (키 낮추기 지원). 메모리는 아레나에서 받은 것을 쓴다
#pragma once
#include <cstdint>

namespace bt {

struct HeapEntry { double f; float h; uint32_t idx; };

// 동률 키는 (f, h, 칸 번호) 사전순으로 고정
inline bool heap_less(const HeapEntry& a, const HeapEntry& b) {
  if (a.f != b.f) return a.f < b.f;
  if (a.h != b.h) return a.h < b.h;
  return a.idx < b.idx;
}

struct Heap {
  HeapEntry* e;      // 용량 cap
  int32_t* pos;      // 칸 번호 → 힙 안 자리 (-1 = 없음). 칸 수만큼
  uint32_t n, cap;

  void clear() { n = 0; }
  void place(uint32_t i, const HeapEntry& v) { e[i] = v; pos[v.idx] = static_cast<int32_t>(i); }
  void up(uint32_t i) {
    const HeapEntry v = e[i];
    while (i > 0) {                       // 상한: 힙 높이
      const uint32_t p = (i - 1) / 2;
      if (!heap_less(v, e[p])) break;
      place(i, e[p]);
      i = p;
    }
    place(i, v);
  }
  void down(uint32_t i) {
    const HeapEntry v = e[i];
    for (;;) {                            // 상한: 힙 높이
      uint32_t c = 2 * i + 1;
      if (c >= n) break;
      if (c + 1 < n && heap_less(e[c + 1], e[c])) c += 1;
      if (!heap_less(e[c], v)) break;
      place(i, e[c]);
      i = c;
    }
    place(i, v);
  }
  // 넣거나, 이미 있으면 키를 낮춘다. 용량이 차면 false
  bool push(const HeapEntry& v, bool in_heap) {
    if (in_heap) {
      const uint32_t i = static_cast<uint32_t>(pos[v.idx]);
      e[i] = v;
      up(i);
      return true;
    }
    if (n >= cap) return false;
    e[n] = v;
    pos[v.idx] = static_cast<int32_t>(n);
    n += 1;
    up(n - 1);
    return true;
  }
  HeapEntry pop() {
    const HeapEntry top = e[0];
    pos[top.idx] = -1;
    n -= 1;
    if (n > 0) {
      e[0] = e[n];
      pos[e[0].idx] = 0;
      down(0);
    }
    return top;
  }
};

}  // namespace bt
