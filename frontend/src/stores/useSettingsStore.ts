import { create } from 'zustand'
import { persist } from 'zustand/middleware'

/** 跨会话保留的设置：当前选中的模型档案名。 */
interface SettingsState {
  selectedProfile: string | null
  setSelectedProfile: (name: string | null) => void
}

export const useSettingsStore = create<SettingsState>()(
  persist(
    (set) => ({
      selectedProfile: null,
      setSelectedProfile: (name) => set({ selectedProfile: name }),
    }),
    { name: 'studywise-settings' },
  ),
)
