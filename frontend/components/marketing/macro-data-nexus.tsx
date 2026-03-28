"use client"

import React, { useState, useEffect } from "react"
import dynamic from "next/dynamic"

const World = dynamic(
  () => import("@/components/ui/globe").then((m) => m.World),
  {
    ssr: false,
  },
)

const globeConfig = {
  pointSize: 1.5,
  globeColor: "#050505",
  showAtmosphere: true,
  atmosphereColor: "#38bdf8",
  atmosphereAltitude: 0.15,
  emissive: "#000000",
  emissiveIntensity: 0.1,
  shininess: 0.9,
  polygonColor: "rgba(255,255,255,0.2)",
  ambientLight: "#38bdf8",
  directionalLeftLight: "#ffffff",
  directionalTopLight: "#ffffff",
  pointLight: "#ffffff",
  arcTime: 2000,
  arcLength: 0.9,
  rings: 1,
  maxRings: 3,
  initialPosition: { lat: 22.3193, lng: 114.1694 },
  autoRotate: true,
  autoRotateSpeed: 0.8,
}

const colors = ["#06b6d4", "#3b82f6", "#6366f1"]
const sampleArcs = [
  {
    order: 1,
    startLat: -15.785493,
    startLng: -47.909029,
    endLat: 38.89511,
    endLng: -77.03637,
    arcAlt: 0.2,
    color: colors[Math.floor(Math.random() * colors.length)],
  },
  {
    order: 2,
    startLat: -22.9068,
    startLng: -43.1729,
    endLat: 28.6139,
    endLng: 77.209,
    arcAlt: 0.3,
    color: colors[Math.floor(Math.random() * colors.length)],
  },
  {
    order: 3,
    startLat: -33.9249,
    startLng: 18.4241,
    endLat: 40.7128,
    endLng: -74.006,
    arcAlt: 0.3,
    color: colors[Math.floor(Math.random() * colors.length)],
  },
  {
    order: 4,
    startLat: 35.6762,
    startLng: 139.6503,
    endLat: 51.5074,
    endLng: -0.1278,
    arcAlt: 0.3,
    color: colors[Math.floor(Math.random() * colors.length)],
  },
  {
    order: 5,
    startLat: 1.3521,
    startLng: 103.8198,
    endLat: 40.7128,
    endLng: -74.006,
    arcAlt: 0.4,
    color: colors[Math.floor(Math.random() * colors.length)],
  },
  {
    order: 6,
    startLat: 51.5074,
    startLng: -0.1278,
    endLat: 28.6139,
    endLng: 77.209,
    arcAlt: 0.2,
    color: colors[Math.floor(Math.random() * colors.length)],
  },
]

export function MacroDataNexus() {
  const [mounted, setMounted] = useState(false)
  const [ready, setReady] = useState(false)

  useEffect(() => {
    // Defer mounting the globe slightly to prioritize hero text paint
    const timer = setTimeout(() => {
      setMounted(true)
    }, 100)
    return () => clearTimeout(timer)
  }, [])

  return (
    <div className="pointer-events-none absolute inset-0 z-0 h-full w-full bg-black">
      <div 
        className={`absolute right-[-20%] top-[5%] h-[110%] w-[110%] md:right-[-10%] md:top-[0%] md:h-[100%] md:w-[90%] lg:right-[-5%] lg:w-[75%] transition-opacity duration-1000 ease-in-out ${ready ? 'opacity-100' : 'opacity-0'}`}
      >
        {mounted && (
          <World 
            globeConfig={globeConfig} 
            data={sampleArcs} 
            onInit={() => setReady(true)} 
          />
        )}
      </div>
      <div className="absolute inset-0 bg-gradient-to-r from-black via-black/60 to-transparent lg:via-black/20" />
    </div>
  )
}
