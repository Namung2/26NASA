# btcore — C++17 제한 부분집합, 공유 라이브러리 하나 (docs/SYSTEM_SERVICES_BingoTime.md §4)
option(BT_SANITIZE "AddressSanitizer·UBSan으로 빌드" OFF)

set(BT_SRC
  src/api.cpp
  src/mobility.cpp
  src/costmap.cpp
  src/planner.cpp
  src/orienteering.cpp
  src/science.cpp
  src/decision.cpp
  src/safety.cpp
  src/gauge.cpp
  src/link.cpp
  src/eventlog.cpp
  src/digest.cpp
)

# 코어 규칙: 예외·RTTI 없음, 곱셈-덧셈 융합 없음, 경고는 오류. -ffast-math는 쓰지 않는다
set(BT_FLAGS -fno-exceptions -fno-rtti -ffp-contract=off -Wall -Wextra -Werror)
if(BT_SANITIZE)
  set(BT_SAN -fsanitize=address,undefined -fno-omit-frame-pointer)
endif()

function(bt_setup target)
  target_include_directories(${target} PUBLIC include)
  target_compile_features(${target} PRIVATE cxx_std_17)
  target_compile_definitions(${target} PRIVATE BT_BUILD)
  target_compile_options(${target} PRIVATE ${BT_FLAGS} ${BT_SAN})
  target_link_options(${target} PRIVATE ${BT_SAN})
  set_target_properties(${target} PROPERTIES
    CXX_EXTENSIONS OFF
    CXX_VISIBILITY_PRESET hidden
    VISIBILITY_INLINES_HIDDEN ON)
endfunction()

# build/<프리셋>/libbtcore.dylib (macOS) 또는 libbtcore.so (리눅스)
add_library(btcore SHARED ${BT_SRC})
bt_setup(btcore)
set_target_properties(btcore PROPERTIES LIBRARY_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR})

# 자체 시험은 같은 소스를 직접 묶는다 (sanitizer가 코어 안까지 본다)
add_executable(bt_selftest selftest/selftest.cpp ${BT_SRC})
bt_setup(bt_selftest)
set_target_properties(bt_selftest PROPERTIES RUNTIME_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR})
