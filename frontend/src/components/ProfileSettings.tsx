import { useRef, useState, type FormEvent, type MouseEvent as ReactMouseEvent } from 'react'
import { api, ApiError, API_BASE_URL } from '../lib/api'
import { useAuth } from '../lib/useAuth'
import { GlassPanel } from './GlassPanel'

const FRAME_SIZE = 240
const OUTPUT_SIZE = 480

export function ProfileSettings({ onClose }: { onClose: () => void }) {
  const { user, refreshUser } = useAuth()

  const [imageEl, setImageEl] = useState<HTMLImageElement | null>(null)
  const [scale, setScale] = useState(1)
  const [baseScale, setBaseScale] = useState(1)
  const [pan, setPan] = useState({ x: 0, y: 0 })
  const dragRef = useRef<{ startX: number; startY: number; panX: number; panY: number } | null>(null)
  const [savingAvatar, setSavingAvatar] = useState(false)
  const [avatarError, setAvatarError] = useState<string | null>(null)
  const [avatarStatus, setAvatarStatus] = useState<string | null>(null)

  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [passwordError, setPasswordError] = useState<string | null>(null)
  const [passwordStatus, setPasswordStatus] = useState<string | null>(null)
  const [savingPassword, setSavingPassword] = useState(false)

  function clampPan(p: { x: number; y: number }, s: number, img: HTMLImageElement) {
    const w = img.naturalWidth * s
    const h = img.naturalHeight * s
    return {
      x: Math.min(0, Math.max(p.x, FRAME_SIZE - w)),
      y: Math.min(0, Math.max(p.y, FRAME_SIZE - h)),
    }
  }

  function handleFileChange(file: File | null) {
    setAvatarError(null)
    if (!file) return
    const img = new Image()
    img.onload = () => {
      const cover = Math.max(FRAME_SIZE / img.naturalWidth, FRAME_SIZE / img.naturalHeight)
      const centered = {
        x: (FRAME_SIZE - img.naturalWidth * cover) / 2,
        y: (FRAME_SIZE - img.naturalHeight * cover) / 2,
      }
      setImageEl(img)
      setBaseScale(cover)
      setScale(1)
      setPan(centered)
    }
    img.src = URL.createObjectURL(file)
  }

  function handleZoomChange(zoomFactor: number) {
    if (!imageEl) return
    setScale(zoomFactor)
    setPan((p) => clampPan(p, baseScale * zoomFactor, imageEl))
  }

  function handleMouseDown(e: ReactMouseEvent) {
    dragRef.current = { startX: e.clientX, startY: e.clientY, panX: pan.x, panY: pan.y }
  }

  function handleMouseMove(e: ReactMouseEvent) {
    if (!dragRef.current || !imageEl) return
    const dx = e.clientX - dragRef.current.startX
    const dy = e.clientY - dragRef.current.startY
    setPan(clampPan({ x: dragRef.current.panX + dx, y: dragRef.current.panY + dy }, baseScale * scale, imageEl))
  }

  function handleMouseUp() {
    dragRef.current = null
  }

  async function handleSaveAvatar() {
    if (!imageEl) return
    setSavingAvatar(true)
    setAvatarError(null)
    try {
      const effectiveScale = baseScale * scale
      const canvas = document.createElement('canvas')
      canvas.width = OUTPUT_SIZE
      canvas.height = OUTPUT_SIZE
      const ctx = canvas.getContext('2d')
      if (!ctx) throw new Error('Canvas not supported')
      const sx = -pan.x / effectiveScale
      const sy = -pan.y / effectiveScale
      const sSize = FRAME_SIZE / effectiveScale
      ctx.drawImage(imageEl, sx, sy, sSize, sSize, 0, 0, OUTPUT_SIZE, OUTPUT_SIZE)

      const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, 'image/png'))
      if (!blob) throw new Error('Could not export image')
      const file = new File([blob], 'avatar.png', { type: 'image/png' })
      await api.uploadAvatar(file)
      await refreshUser()
      setAvatarStatus('Profile picture updated')
      setImageEl(null)
    } catch (err) {
      setAvatarError(err instanceof ApiError ? err.message : 'Could not save profile picture')
    } finally {
      setSavingAvatar(false)
    }
  }

  async function handleChangePassword(e: FormEvent) {
    e.preventDefault()
    setPasswordError(null)
    setPasswordStatus(null)
    if (newPassword !== confirmPassword) {
      setPasswordError('New passwords do not match')
      return
    }
    setSavingPassword(true)
    try {
      await api.changeOwnPassword(currentPassword, newPassword)
      setCurrentPassword('')
      setNewPassword('')
      setConfirmPassword('')
      setPasswordStatus('Password changed')
    } catch (err) {
      setPasswordError(err instanceof ApiError ? err.message : 'Could not change password')
    } finally {
      setSavingPassword(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink-950/70 backdrop-blur-sm">
      <GlassPanel className="w-full max-w-md">
        <div className="mb-4 flex items-center justify-between">
          <p className="font-display text-lg font-semibold">Profile settings</p>
          <button onClick={onClose} className="text-white/40 hover:text-white">
            <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M6 6l12 12M18 6 6 18" />
            </svg>
          </button>
        </div>

        <p className="mb-2 text-xs font-semibold uppercase tracking-wider text-white/45">Profile picture</p>
        <div className="mb-3 flex items-center gap-4">
          <div
            className="relative h-[240px] w-[240px] shrink-0 overflow-hidden rounded-xl border border-white/15 bg-white/5"
            onMouseDown={imageEl ? handleMouseDown : undefined}
            onMouseMove={imageEl ? handleMouseMove : undefined}
            onMouseUp={handleMouseUp}
            onMouseLeave={handleMouseUp}
          >
            {imageEl ? (
              <img
                src={imageEl.src}
                alt="Crop preview"
                draggable={false}
                className="absolute cursor-move select-none"
                style={{
                  width: imageEl.naturalWidth * baseScale * scale,
                  height: imageEl.naturalHeight * baseScale * scale,
                  left: pan.x,
                  top: pan.y,
                }}
              />
            ) : user?.avatar_url ? (
              <img src={`${API_BASE_URL}${user.avatar_url}`} alt="Current avatar" className="h-full w-full object-cover" />
            ) : (
              <div className="flex h-full w-full items-center justify-center text-3xl font-semibold text-white/30">
                {user?.username.slice(0, 2).toUpperCase()}
              </div>
            )}
          </div>
          <div className="flex-1 space-y-2">
            <label className="block cursor-pointer rounded-xl border border-white/20 px-3 py-2 text-center text-xs font-semibold text-white/80 hover:bg-white/5">
              Choose photo…
              <input
                type="file"
                accept="image/png,image/jpeg,image/webp"
                className="hidden"
                onChange={(e) => handleFileChange(e.target.files?.[0] ?? null)}
              />
            </label>
            {imageEl && (
              <>
                <div>
                  <label className="mb-1 block text-[10px] text-white/45">Zoom</label>
                  <input
                    type="range"
                    min="1"
                    max="3"
                    step="0.01"
                    value={scale}
                    onChange={(e) => handleZoomChange(Number(e.target.value))}
                    className="w-full"
                  />
                </div>
                <button
                  onClick={handleSaveAvatar}
                  disabled={savingAvatar}
                  className="w-full rounded-xl bg-gradient-to-r from-accent-400 to-accent-500 px-3 py-2 text-xs font-semibold text-ink-900 disabled:opacity-50"
                >
                  {savingAvatar ? 'Saving…' : 'Save picture'}
                </button>
              </>
            )}
            {avatarError && <p className="text-xs text-red-300">{avatarError}</p>}
            {avatarStatus && <p className="text-xs text-emerald-300">{avatarStatus}</p>}
          </div>
        </div>

        <p className="mb-2 mt-5 text-xs font-semibold uppercase tracking-wider text-white/45">Change password</p>
        <form onSubmit={handleChangePassword} className="space-y-2">
          <input
            type="password"
            value={currentPassword}
            onChange={(e) => setCurrentPassword(e.target.value)}
            required
            placeholder="Current password"
            className="w-full rounded-xl border border-white/15 bg-white/5 px-3 py-2 text-sm placeholder:text-white/35 focus:border-sky-400/60 focus:outline-none"
          />
          <input
            type="password"
            value={newPassword}
            onChange={(e) => setNewPassword(e.target.value)}
            required
            minLength={8}
            placeholder="New password (min. 8 characters)"
            className="w-full rounded-xl border border-white/15 bg-white/5 px-3 py-2 text-sm placeholder:text-white/35 focus:border-sky-400/60 focus:outline-none"
          />
          <input
            type="password"
            value={confirmPassword}
            onChange={(e) => setConfirmPassword(e.target.value)}
            required
            placeholder="Confirm new password"
            className="w-full rounded-xl border border-white/15 bg-white/5 px-3 py-2 text-sm placeholder:text-white/35 focus:border-sky-400/60 focus:outline-none"
          />
          {passwordError && <p className="text-xs text-red-300">{passwordError}</p>}
          {passwordStatus && <p className="text-xs text-emerald-300">{passwordStatus}</p>}
          <button
            type="submit"
            disabled={savingPassword}
            className="w-full rounded-xl border border-white/20 px-3 py-2 text-sm font-semibold text-white/80 hover:bg-white/5 disabled:opacity-50"
          >
            {savingPassword ? 'Changing…' : 'Change password'}
          </button>
        </form>
      </GlassPanel>
    </div>
  )
}
