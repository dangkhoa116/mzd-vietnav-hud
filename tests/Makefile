# Host tests (PC, không cần xe). Yêu cầu: python -m ziglang (pip install ziglang).
#
# OEM_AA_MOD: đường dẫn tới bản oem-aa-mod đã áp dụng patch trong patches/
# Ví dụ:  make test OEM_AA_MOD=../../oem-aa-mod
OEM_AA_MOD ?= ../oem-aa-mod
HUD   := $(OEM_AA_MOD)/mazda/patches/blmjciaapa/hud
INCS  := -I shim -I $(HUD) -I $(OEM_AA_MOD)/mazda/patches -I $(OEM_AA_MOD)/mazda/patches/common
CXX   := python -m ziglang c++

test: road_fold_test maneuver_text_test
	./road_fold_test
	./maneuver_text_test

# Chỉ phần CarPlay: không cần checkout oem-aa-mod nào cả.
test-carplay: maneuver_text_test
	./maneuver_text_test

road_fold_test: road_fold_test.cpp $(HUD)/hud_nav16.cpp $(HUD)/hud_nav16.h $(HUD)/translit.h
	$(CXX) -std=c++17 $(INCS) $< $(HUD)/hud_nav16.cpp -o $@

maneuver_text_test: maneuver_text_test.cpp ../patches/carplay-hud/maneuver_text.h
	$(CXX) -std=c++17 -w -I ../patches/carplay-hud $< -o $@

clean:
	rm -f road_fold_test road_fold_test.exe maneuver_text_test maneuver_text_test.exe

.PHONY: test test-carplay clean
