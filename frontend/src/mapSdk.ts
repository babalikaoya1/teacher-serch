export type MapPoint = { lat: number; lng: number }

type AMapLngLat = {
  getLng(): number
  getLat(): number
}

type AMapMouseEvent = { lnglat: AMapLngLat }

type AMapGeocoderResult = {
  geocodes?: Array<{
    location: AMapLngLat
    formattedAddress?: string
    addressComponent?: { city?: string | string[]; province?: string }
  }>
  regeocode?: {
    formattedAddress?: string
    addressComponent?: { city?: string | string[]; province?: string }
  }
}

type AMapPlaceSearchResult = {
  poiList?: { pois?: Array<{ location?: AMapLngLat; name?: string; address?: string; cityname?: string; pname?: string }> }
}

export type AMapInstance = {
  on(event: 'click', callback: (event: AMapMouseEvent) => void): void
  setCenter(center: [number, number]): void
  add(marker: AMapMarker): void
  destroy(): void
}

type AMapMarker = { setPosition(position: [number, number]): void }

export type AMapApi = {
  Map: new (container: HTMLElement, options: { zoom: number; center: [number, number] }) => AMapInstance
  Marker: new (options: { position: [number, number] }) => AMapMarker
  Geocoder: new () => {
    getLocation(address: string, callback: (status: string, result: AMapGeocoderResult) => void): void
    getAddress(location: AMapLngLat, callback: (status: string, result: AMapGeocoderResult) => void): void
  }
  PlaceSearch: new (options?: { pageSize?: number; city?: string }) => {
    search(keywords: string, callback: (status: string, result: AMapPlaceSearchResult) => void): void
  }
}

declare global {
  interface Window {
    AMapLoader?: { load(options: { key: string; version: string; plugins: string[] }): Promise<AMapApi> }
  }
}

let sdkPromise: Promise<AMapApi> | null = null

export function loadAmapSdk(sdkUrl: string, publicKey: string): Promise<AMapApi> {
  if (!sdkPromise) {
    sdkPromise = new Promise<void>((resolve, reject) => {
      const script = document.createElement('script')
      script.src = sdkUrl
      script.async = true
      const timer = window.setTimeout(() => {
        script.remove()
        reject(new Error('地图 SDK 加载超时。'))
      }, 5000)
      script.onload = () => {
        window.clearTimeout(timer)
        resolve()
      }
      script.onerror = () => {
        window.clearTimeout(timer)
        reject(new Error('地图 SDK 加载失败，请检查 SDK 地址和网络。'))
      }
      document.head.appendChild(script)
    }).then(async () => {
      if (!window.AMapLoader) throw new Error('地图 SDK 未提供加载器，请确认配置的是高德地图 loader.js 地址。')
      return window.AMapLoader.load({ key: publicKey, version: '2.0', plugins: ['AMap.Geocoder', 'AMap.PlaceSearch'] })
    }).catch((error: unknown) => {
      sdkPromise = null
      throw error
    })
  }
  return sdkPromise
}
