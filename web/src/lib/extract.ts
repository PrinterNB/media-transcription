// Browser-side audio extraction: decode the file to PCM with the Web Audio
// API, resample to 16 kHz mono, and emit a small 16-bit PCM WAV. This lets a
// 5 GB video upload as ~100 MB of audio. Anything we can't decode (mkv/avi/
// wmv, or >500 MB) is returned with `extracted: false` and the server strips
// the audio with ffmpeg instead.

const MAX_CLIENT_EXTRACT_BYTES = 500 * 1024 * 1024 // 500 MB

export interface ExtractResult {
  blob: Blob
  extracted: boolean
}

function encodeWav16(samples: Float32Array, sampleRate: number): Blob {
  const n = samples.length
  const buffer = new ArrayBuffer(44 + n * 2)
  const view = new DataView(buffer)

  const writeStr = (o: number, s: string) => {
    for (let i = 0; i < s.length; i++) view.setUint8(o + i, s.charCodeAt(i))
  }

  writeStr(0, 'RIFF')
  view.setUint32(4, 36 + n * 2, true)
  writeStr(8, 'WAVE')
  writeStr(12, 'fmt ')
  view.setUint32(16, 16, true) // fmt chunk size
  view.setUint16(20, 1, true) // PCM
  view.setUint16(22, 1, true) // mono
  view.setUint32(24, sampleRate, true)
  view.setUint32(28, sampleRate * 2, true) // byte rate
  view.setUint16(32, 2, true) // block align
  view.setUint16(34, 16, true) // bits
  writeStr(36, 'data')
  view.setUint32(40, n * 2, true)

  let o = 44
  for (let i = 0; i < n; i++) {
    let s = Math.max(-1, Math.min(1, samples[i]))
    view.setInt16(o, s < 0 ? s * 0x8000 : s * 0x7fff, true)
    o += 2
  }
  return new Blob([view], { type: 'audio/wav' })
}

export async function extractWav16k(file: File): Promise<ExtractResult> {
  if (file.size > MAX_CLIENT_EXTRACT_BYTES) return { blob: file, extracted: false }
  try {
    const AC: typeof AudioContext =
      window.AudioContext || (window as any).webkitAudioContext
    const ctx = new AC()
    const arrayBuf = await file.arrayBuffer()
    const decoded = await ctx.decodeAudioData(arrayBuf)
    await ctx.close()

    const outLen = Math.ceil(decoded.duration * 16000)
    const offline = new OfflineAudioContext(1, outLen, 16000)
    const src = offline.createBufferSource()
    src.buffer = decoded
    src.connect(offline.destination)
    src.start()
    const rendered = await offline.startRendering()
    const wav = encodeWav16(rendered.getChannelData(0), 16000)
    return { blob: wav, extracted: true }
  } catch {
    return { blob: file, extracted: false }
  }
}
