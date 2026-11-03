// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <atomic>
#include <cstdint>

// UI starts a pulse while EmuThread is paused. Only EmuThread advances it.
// A release frame completes it; physical keyboard/gamepad bits remain intact.
struct PCEInputPulse {
    std::atomic<unsigned> remaining{0}, completed{0};
    std::atomic<bool> finished{true}, expired{false};
    unsigned pressed = 0;
    uint64_t deadline = 0;
    bool appliedThisFrame = false;
    void begin(unsigned mask, unsigned frames, uint64_t now) {
        pressed = mask;
        remaining = frames;
        completed = 0;
        expired = false;
        deadline = now + 2000;
        finished = false;
    }
    unsigned apply(unsigned physical, uint64_t now) {
        if (remaining && now >= deadline) { remaining = 0; expired = true; }
        appliedThisFrame = remaining > 0;
        return physical & ~(appliedThisFrame ? pressed : 0);
    }
    void afterFrame() {
        if (appliedThisFrame) { --remaining; ++completed; }
        else if (!finished) { pressed = 0; finished = true; }
    }
};
