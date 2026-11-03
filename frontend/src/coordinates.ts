const PI = Math.PI
const AXIS = 6378245.0
const ECCENTRICITY_SQUARED = 0.00669342162296594323

function latitudeOffset(x: number, y: number): number {
  let value = -100 + 2 * x + 3 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * Math.sqrt(Math.abs(x))
  value += (20 * Math.sin(6 * x * PI) + 20 * Math.sin(2 * x * PI)) * 2 / 3
  value += (20 * Math.sin(y * PI) + 40 * Math.sin(y / 3 * PI)) * 2 / 3
  value += (160 * Math.sin(y / 12 * PI) + 320 * Math.sin(y * PI / 30)) * 2 / 3
  return value
}

function longitudeOffset(x: number, y: number): number {
  let value = 300 + x + 2 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * Math.sqrt(Math.abs(x))
  value += (20 * Math.sin(6 * x * PI) + 20 * Math.sin(2 * x * PI)) * 2 / 3
  value += (20 * Math.sin(x * PI) + 40 * Math.sin(x / 3 * PI)) * 2 / 3
  value += (150 * Math.sin(x / 12 * PI) + 300 * Math.sin(x / 30 * PI)) * 2 / 3
  return value
}

export function wgs84ToGcj02(latitude: number, longitude: number): { lat: number; lng: number } {
  if (longitude < 72.004 || longitude > 137.8347 || latitude < 0.8293 || latitude > 55.8271) {
    return { lat: latitude, lng: longitude }
  }

  let deltaLatitude = latitudeOffset(longitude - 105, latitude - 35)
  let deltaLongitude = longitudeOffset(longitude - 105, latitude - 35)
  const latitudeRadians = latitude / 180 * PI
  let magic = Math.sin(latitudeRadians)
  magic = 1 - ECCENTRICITY_SQUARED * magic * magic
  const rootMagic = Math.sqrt(magic)
  deltaLatitude = deltaLatitude * 180 / ((AXIS * (1 - ECCENTRICITY_SQUARED)) / (magic * rootMagic) * PI)
  deltaLongitude = deltaLongitude * 180 / (AXIS / rootMagic * Math.cos(latitudeRadians) * PI)
  return { lat: latitude + deltaLatitude, lng: longitude + deltaLongitude }
}
