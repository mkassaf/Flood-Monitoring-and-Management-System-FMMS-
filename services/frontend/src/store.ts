import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type { User, Alert } from './types'

interface AppState {
  token: string | null
  user: User | null
  selectedAreaId: string | null
  liveAlerts: Alert[]
  setToken: (token: string | null) => void
  setUser: (user: User | null) => void
  setSelectedArea: (id: string | null) => void
  addLiveAlert: (alert: Alert) => void
  logout: () => void
}

export const useStore = create<AppState>()(
  persist(
    (set) => ({
      token: null,
      user: null,
      selectedAreaId: null,
      liveAlerts: [],
      setToken: (token) => set({ token }),
      setUser: (user) => set({ user }),
      setSelectedArea: (id) => set({ selectedAreaId: id }),
      addLiveAlert: (alert) =>
        set((s) => ({ liveAlerts: [alert, ...s.liveAlerts].slice(0, 50) })),
      logout: () => set({ token: null, user: null, selectedAreaId: null, liveAlerts: [] }),
    }),
    {
      name: 'fmms-auth',
      partialize: (state) => ({ token: state.token, user: state.user }),
    }
  )
)
