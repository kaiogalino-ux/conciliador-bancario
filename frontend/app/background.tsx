"use client";

import { ShootingStarsGrid } from "@/components/ui/shooting-stars-grid";

export function Background() {
  return (
    <ShootingStarsGrid
      className="fixed inset-0 -z-10 h-screen w-screen rounded-none border-0 shadow-none"
      showGrid
      showStaticStars
      glow
      interactive={false}
    >
      <></>
    </ShootingStarsGrid>
  );
}
