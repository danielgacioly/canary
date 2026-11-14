// Client-side image shrinking. Photos are reduced before they leave the device, so the server never gets a 12 MP picture.

function load(f: File): Promise<{ img: HTMLImageElement; done: () => void }> {
  return new Promise((resolve, reject) => {
    const img = new Image()
    const url = URL.createObjectURL(f)
    img.onload = () => resolve({ img, done: () => URL.revokeObjectURL(url) })
    img.onerror = () => { URL.revokeObjectURL(url); reject(new Error('not an image')) }
    img.src = url
  })
}

/** Center-crop and shrink an image to a small square JPEG data URL (profile photo). */
export async function squareJpeg(f: File, size: number): Promise<string> {
  const { img, done } = await load(f)
  const s = Math.min(img.width, img.height)
  const c = document.createElement('canvas')
  c.width = c.height = size
  c.getContext('2d')!.drawImage(img, (img.width - s) / 2, (img.height - s) / 2, s, s, 0, 0, size, size)
  done()
  return c.toDataURL('image/jpeg', 0.85)
}

/** Keep the aspect ratio, shrink so the long edge is at most `maxEdge`, return a JPEG data URL (photo of a display). */
export async function fitJpeg(f: File, maxEdge = 1024, quality = 0.8): Promise<string> {
  const { img, done } = await load(f)
  const k = Math.min(1, maxEdge / Math.max(img.width, img.height))
  const c = document.createElement('canvas')
  c.width = Math.max(1, Math.round(img.width * k)); c.height = Math.max(1, Math.round(img.height * k))
  c.getContext('2d')!.drawImage(img, 0, 0, c.width, c.height)
  done()
  return c.toDataURL('image/jpeg', quality)
}
